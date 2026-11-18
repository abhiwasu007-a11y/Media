"""``LanguageChecker`` (blueprint 6.4): script, Latin outside brackets, bracketed first mention."""

import re
import unicodedata
from collections.abc import Sequence
from typing import Any

from agent_05_scriptwriter.contracts import GlossaryTerm
from agent_05_scriptwriter.text import has_devanagari, normalise, strip_brackets

_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'\-]*")
_DEVANAGARI_LANGUAGES = ("mr-IN", "hi-IN")


def _foreign_script(text: str, language: str) -> bool:
    """A letter outside the language's scripts (Latin is checked separately for mr/hi)."""
    for ch in text:
        if not ch.isalpha():
            continue
        name = unicodedata.name(ch, "")
        is_latin = name.startswith("LATIN")
        is_deva = name.startswith("DEVANAGARI")
        if language in _DEVANAGARI_LANGUAGES and not (is_latin or is_deva):
            return True
        if language not in _DEVANAGARI_LANGUAGES and not is_latin:
            return True
    return False


def _allowed_tokens(allow: Sequence[str]) -> set[str]:
    out: set[str] = set()
    for entry in allow:
        out.update(w.casefold() for w in _LATIN_WORD.findall(entry))
    return out


def _term_bracketed(text: str, term: GlossaryTerm) -> bool:
    """True when the first occurrence of ``term_local`` is followed by ``(term_en)``."""
    index = text.find(term.term_local)
    if index < 0:
        return True  # the term is not mentioned in this text
    tail = text[index + len(term.term_local) :]
    match = re.match(r"\s*\(\s*([^()]*?)\s*\)", tail)
    return match is not None and normalise(match.group(1)) == normalise(term.term_en)


def check_language(
    text: str,
    language: str,
    allow: Sequence[str],
    terms_introduced: Sequence[str],
    terms: Sequence[GlossaryTerm],
) -> list[dict[str, Any]]:
    """Violations of one text; an empty list means pass. Codes only, never the text."""
    violations: list[dict[str, Any]] = []
    if language in _DEVANAGARI_LANGUAGES:
        if _foreign_script(text, language):
            violations.append({"kind": "SCRIPT_MISMATCH"})
        allowed = _allowed_tokens(allow)
        outside = strip_brackets(text)
        stray = [t for t in _LATIN_WORD.findall(outside) if t.casefold() not in allowed]
        if stray:
            violations.append({"kind": "LATIN_OUTSIDE_BRACKETS", "tokens": stray})
        unbracketed = [
            t.concept_id
            for t in terms
            if t.concept_id not in terms_introduced and not _term_bracketed(text, t)
        ]
        if unbracketed:
            violations.append({"kind": "TERM_NOT_BRACKETED", "concept_ids": unbracketed})
    elif has_devanagari(text) or _foreign_script(text, language):
        violations.append({"kind": "SCRIPT_MISMATCH"})
    return violations
