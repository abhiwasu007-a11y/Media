"""TextOptionBuilder (F-06; blueprint 6.2). Pure: the same inputs give the same options."""

from collections.abc import Sequence
from dataclasses import dataclass

from agent_11_thumbnail_design.models import ExcludedText, TextOption, TextSource
from agent_11_thumbnail_design.scanner import InjectionScanner
from agent_11_thumbnail_design.textutil import (
    contains_sequence,
    fold,
    folded_words,
    has_digit_or_symbol,
    normalise,
    words,
)


@dataclass(frozen=True, slots=True)
class TextBuildConfig:
    max_words: int
    max_chars: int
    max_options: int


@dataclass(frozen=True, slots=True)
class TextOptions:
    options: tuple[TextOption, ...]
    excluded: tuple[ExcludedText, ...]


def finance_text_hit(text: str, lexicon: Sequence[str]) -> bool:
    """FIN_TEXT: a digit or currency/percent symbol, or a marker-list hit (whole word/phrase)."""
    if has_digit_or_symbol(text):
        return True
    toks = folded_words(text)
    return any(contains_sequence(toks, folded_words(entry)) for entry in lexicon if entry.strip())


def _key_term_ids(text: str, key_terms: Sequence[str]) -> tuple[str, ...]:
    toks = folded_words(text)
    return tuple(
        f"k{i + 1}" for i, term in enumerate(key_terms) if contains_sequence(toks, folded_words(term))
    )


def _title_spans(title: str, key_terms: Sequence[str], max_words: int) -> list[str]:
    ws = words(title)
    ranked: list[tuple[int, int, int, str]] = []
    for n in range(1, max_words + 1):
        for start in range(0, len(ws) - n + 1):
            span = " ".join(ws[start : start + n])
            distinct = len(_key_term_ids(span, key_terms))
            if distinct:
                ranked.append((-distinct, n, start, span))
    ranked.sort(key=lambda r: r[:3])
    return [r[3] for r in ranked]


def build_text_options(
    *,
    working_title_local: str,
    promise_key_terms: Sequence[str],
    brief_text: str,
    banned_words: Sequence[str],
    must_not_promise: Sequence[str],
    finance: bool,
    cfg: TextBuildConfig,
    lexicon: Sequence[str],
    scanner: InjectionScanner,
) -> TextOptions:
    candidates: list[tuple[str, TextSource]] = [(normalise(brief_text), "BRIEF_TEXT")]
    candidates += [(normalise(t), "KEY_TERM") for t in promise_key_terms]
    candidates += [(s, "TITLE_SPAN") for s in _title_spans(working_title_local, promise_key_terms, cfg.max_words)]
    seen: set[str] = set()
    kept: list[tuple[str, TextSource]] = []
    excluded: list[ExcludedText] = []
    banned = [fold(b) for b in banned_words if b.strip()]
    must_not = [fold(m) for m in must_not_promise if m.strip()]
    for text, source in candidates:
        key = fold(text)
        if key and key in seen:
            continue
        seen.add(key)
        reason = _exclusion(text, banned, must_not, finance, cfg, lexicon, scanner)
        if reason is None:
            kept.append((text, source))
        else:
            excluded.append(ExcludedText(text=text, source=source, reason=reason))
    options = tuple(
        TextOption(
            text_id=f"t{i + 1:02d}",
            text=text,
            source=source,
            key_term_ids=_key_term_ids(text, promise_key_terms),
            word_count=len(words(text)),
        )
        for i, (text, source) in enumerate(kept[: cfg.max_options])
    )
    return TextOptions(options, tuple(excluded))


def _exclusion(
    text: str,
    banned: Sequence[str],
    must_not: Sequence[str],
    finance: bool,
    cfg: TextBuildConfig,
    lexicon: Sequence[str],
    scanner: InjectionScanner,
) -> str | None:
    folded = fold(text)
    if not folded:
        return "EMPTY"
    if len(words(text)) > cfg.max_words or len(text) > cfg.max_chars:
        return "TOO_LONG"
    if any(b in folded for b in banned):
        return "BANNED_WORD"
    if any(m in folded for m in must_not):
        return "MUST_NOT_PROMISE"
    if scanner.scan(text).flagged:
        return "INJECTION"
    if finance and finance_text_hit(text, lexicon):
        return "FIN_TEXT"
    return None
