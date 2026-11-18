"""Parse a prompt file (27 section 4.2) into its parts."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from amw_evals.findings import JsonObject
from amw_evals.mdparse import Block, Section, split_h2, split_h3

REQUIRED_SECTIONS = (
    "Role",
    "Objective",
    "Inputs",
    "Rules",
    "Output JSON Schema",
    "Worked examples",
    "Refusal and escalation",
    "Self-check",
)
NAME_RE = re.compile(r"^(?P<task>[a-z][a-z0-9_]*)\.v(?P<ver>[0-9]+)\.md$")
AGENT_DIR_RE = re.compile(r"^(?P<id>agent_[0-9]{2}|s[0-9]{2})_[a-z0-9_]+$")
VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
HEADER_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|\s*$")


@dataclass
class Example:
    title: str
    input_blocks: list[Block] = field(default_factory=list)
    output_blocks: list[Block] = field(default_factory=list)
    input_inline: bool = False  # "Input: as Example 1 with ..." (text after the colon)


@dataclass
class PromptDoc:
    path: Path
    text: str
    sections: list[Section]
    header: dict[str, str]
    examples: list[Example]

    def section(self, name: str) -> Section | None:
        for s in self.sections:
            if s.title.lower().startswith(name.lower()):
                return s
        return None

    @property
    def agent_dir(self) -> str:
        return self.path.parent.name

    @property
    def task(self) -> str:
        m = NAME_RE.match(self.path.name)
        return m.group("task") if m else self.path.stem

    @property
    def expected_prompt_id(self) -> str | None:
        a = AGENT_DIR_RE.match(self.agent_dir)
        m = NAME_RE.match(self.path.name)
        if not (a and m):
            return None
        return f"{a.group('id')}/{m.group('task')}.v{m.group('ver')}"

    def _first_json(self, section: Section | None) -> str | None:
        if section is None:
            return None
        for b in section.blocks:
            if b.lang == "json":
                return b.text
        return None

    def output_schema_text(self) -> str | None:
        return self._first_json(self.section("Output JSON Schema"))

    def input_schema_text(self) -> str | None:
        for s in self.sections:
            if "input payload schema" in s.title.lower():
                return self._first_json(s)
        return None

    def output_schema(self) -> JsonObject | None:
        return _load_object(self.output_schema_text())

    def input_schema(self) -> JsonObject | None:
        return _load_object(self.input_schema_text())


def _load_object(text: str | None) -> JsonObject | None:
    if text is None:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _header(text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("## "):
            break
        m = HEADER_ROW_RE.match(line)
        if m and not set(m.group(1)) <= set("-: "):
            rows[m.group(1).strip()] = m.group(2).strip()
    return rows


def _examples(sections: list[Section]) -> list[Example]:
    we = next((s for s in sections if s.title.lower().startswith("worked examples")), None)
    if we is None:
        return []
    out: list[Example] = []
    for sub in split_h3(we):
        ex = Example(sub.title)
        for b in sub.blocks:
            tag = b.preceding.lower()
            if tag.startswith("input"):
                ex.input_blocks.append(b)
                if tag.rstrip(": ") != "input":
                    ex.input_inline = True
            elif tag.startswith("output"):
                ex.output_blocks.append(b)
        out.append(ex)
    return out


def parse_prompt(path: Path) -> PromptDoc:
    text = path.read_text(encoding="utf-8")
    sections = split_h2(text)
    return PromptDoc(path, text, sections, _header(text), _examples(sections))
