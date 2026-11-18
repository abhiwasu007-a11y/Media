"""Minimal Markdown helpers for prompt files: H2 sections and fenced code blocks."""

import re
from dataclasses import dataclass, field

FENCE = re.compile(r"^```(\w*)\s*$")
H2 = re.compile(r"^## (.+?)\s*$")
H3 = re.compile(r"^### (.+?)\s*$")


@dataclass
class Block:
    lang: str
    text: str
    line: int  # 1-based line of the opening fence
    preceding: str  # last non-empty line before the fence


@dataclass
class Section:
    title: str
    line: int
    blocks: list[Block] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)


def split_h2(text: str) -> list[Section]:
    """Split on level-2 headings that are outside fenced code."""
    sections: list[Section] = []
    current: Section | None = None
    in_fence = False
    fence_lang = ""
    buf: list[str] = []
    fence_line = 0
    last_text = ""
    for no, line in enumerate(text.splitlines(), start=1):
        m = FENCE.match(line)
        if m and not in_fence:
            in_fence, fence_lang, buf, fence_line = True, m.group(1), [], no
            if current:
                current.lines.append(line)
            continue
        if in_fence:
            if line.startswith("```"):
                in_fence = False
                if current:
                    current.blocks.append(Block(fence_lang, "\n".join(buf), fence_line, last_text))
                    current.lines.append(line)
                last_text = ""
            else:
                buf.append(line)
                if current:
                    current.lines.append(line)
            continue
        h = H2.match(line)
        if h:
            current = Section(h.group(1), no)
            sections.append(current)
            last_text = ""
            continue
        if current:
            current.lines.append(line)
        if line.strip():
            last_text = line.strip()
    return sections


def split_h3(section: Section) -> list[Section]:
    """Split one H2 section into its H3 subsections (blocks keep their order)."""
    subs: list[Section] = []
    current: Section | None = None
    in_fence = False
    block_iter = iter(section.blocks)
    for line in section.lines:
        if line.startswith("```"):
            if not in_fence:
                blk = next(block_iter, None)
                if blk and current:
                    current.blocks.append(blk)
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        h = H3.match(line)
        if h:
            current = Section(h.group(1), 0)
            subs.append(current)
        elif current:
            current.lines.append(line)
    return subs
