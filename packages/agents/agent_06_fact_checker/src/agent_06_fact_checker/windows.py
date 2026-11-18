"""Passage windowing (blueprint 6.6 step 4, 10.3 ``PassageWindower``). Pure, code points."""

import re
from dataclasses import dataclass

_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")
_TOKEN = re.compile(r"[\wऀ-ॿ]+")


@dataclass(frozen=True, slots=True)
class Window:
    offset: int
    """Code-point offset of ``text`` inside the source text."""
    text: str


def tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.casefold()))


def _sentences(text: str) -> list[Window]:
    out: list[Window] = []
    pos = 0
    for m in _SENTENCE_END.finditer(text):
        out.append(Window(pos, text[pos : m.start()]))
        pos = m.end()
    out.append(Window(pos, text[pos:]))
    return [w for w in out if w.text]


def window(text: str, claim_tokens: set[str], max_chars: int, k: int) -> list[Window]:
    """One window for a short text; else windows of whole sentences (a sentence longer than the
    cap is cut hard), scored by overlap with the claim, best ``k`` returned in text order."""
    if len(text) <= max_chars:
        return [Window(0, text)]
    pieces: list[Window] = []
    for sent in _sentences(text):
        if len(sent.text) <= max_chars:
            pieces.append(sent)
        else:
            for i in range(0, len(sent.text), max_chars):
                pieces.append(Window(sent.offset + i, sent.text[i : i + max_chars]))
    packed: list[Window] = []
    cur: Window | None = None
    for piece in pieces:
        if cur is None:
            cur = piece
            continue
        end = cur.offset + len(cur.text)
        joined = text[cur.offset : piece.offset + len(piece.text)]
        if piece.offset >= end and len(joined) <= max_chars:
            cur = Window(cur.offset, joined)
        else:
            packed.append(cur)
            cur = piece
    if cur is not None:
        packed.append(cur)
    scored = sorted(packed, key=lambda w: (-len(tokens(w.text) & claim_tokens), w.offset))
    return sorted(scored[: max(k, 1)], key=lambda w: w.offset)
