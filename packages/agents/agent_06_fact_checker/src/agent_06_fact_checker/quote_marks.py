"""Quotation-mark spans from a CONFIGURATION table (D16: no mark list in the code).

A span is an opening mark of ANY kind followed later (same line) by a closing mark of ANY kind:
mixed or mismatched marks (``"x”``, ``«x"``) are spans too, which is the conservative reading for
a guard. The marks come from ``QuoteMarkConfig``: an explicit pair table (marks that Unicode does
not class as quotation marks, such as the low-9 ``„``, corner brackets, the straight mark, the
reversed ``»x«``) plus whole Unicode categories (``Pi`` opens, ``Pf`` closes), so a quotation mark
that the table forgot is still seen. The apostrophe ``'`` is in no table: it cannot be told from a
mark by a pure rule (documented limit); a closing curly single mark alone never starts a span.

Invisible characters: a ZERO WIDTH SPACE separates words (configured) in pattern matching; every
other format character (ZWJ, ZWNJ, soft hyphen, word joiner, BOM, bidi marks) is dropped there.
WORD COUNTING is stricter (fail closed, more words = more guarding): the configured
``word_count_separators`` (format characters such as ZWNJ, ZWJ, word joiner, BOM, soft hyphen and
the hyphens) also split words, so a six-word span glued together by invisible characters or hyphens
is still six words.

A span may cross line breaks (verse) but is at most ``max_quote_span_chars`` long. The scan is
linear: a closer lookup table is built in one backward pass, so an opener with no closer (repeated
``„``) costs nothing more than any other character; ``WorkCounter`` counts the steps for tests."""

import json
import unicodedata
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Annotated, Any

from pydantic import Field, field_validator, model_validator

from amw_core.contracts.common import AmwModel
from amw_core.errors import ConfigInvalidError

_MARK_CATEGORIES = frozenset({"Pi", "Pf", "Ps", "Pe", "Po"})
_CLASS_CATEGORIES = frozenset({"Pi", "Pf", "Ps", "Pe"})
_FORMAT = "Cf"


class QuoteMarkConfig(AmwModel):
    """``factcheck.quote_guard.marks``."""

    pairs: Annotated[tuple[tuple[str, str], ...], Field(min_length=1)]
    """(opening, closing) pairs, one code point each; both directions of a mark may appear."""
    opening_categories: tuple[str, ...]
    """Unicode general categories whose every member is an opening mark (``Pi``)."""
    closing_categories: tuple[str, ...]
    """Unicode general categories whose every member is a closing mark (``Pf``)."""
    invisible_separators: tuple[str, ...]
    """Invisible code points that separate words (``U+200B``); other format characters are
    removed."""
    word_count_separators: tuple[str, ...]
    """Code points that ALSO split words when words are counted (ZWNJ, ZWJ, word joiner, BOM, soft
    hyphen, hyphens). Only for counting: pattern matching still removes the format characters."""
    max_quote_span_chars: Annotated[int, Field(ge=1)]
    """Longest span (code points between the marks, line breaks included); an opener whose nearest
    closer lies further away opens no span (a stray mark must not swallow a document)."""

    @field_validator("opening_categories", "closing_categories")
    @classmethod
    def _categories(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        bad = [c for c in value if c not in _CLASS_CATEGORIES]
        if bad:
            raise ConfigInvalidError("not a quotation mark category", details={"bad": bad})
        return value

    @field_validator("invisible_separators")
    @classmethod
    def _separators(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for ch in value:
            if len(ch) != 1 or unicodedata.category(ch) != _FORMAT:
                raise ConfigInvalidError("not one invisible format character", details={"ch": ch})
        return value

    @field_validator("word_count_separators")
    @classmethod
    def _count_separators(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for ch in value:
            if len(ch) != 1 or unicodedata.category(ch)[0] in "LNM":
                raise ConfigInvalidError("not one separator code point", details={"ch": ch})
        return value

    @model_validator(mode="after")
    def _marks(self) -> QuoteMarkConfig:
        for pair in self.pairs:
            for ch in pair:
                if len(ch) != 1 or unicodedata.category(ch) not in _MARK_CATEGORIES:
                    raise ConfigInvalidError(
                        "pair member is not one punctuation code point", details={"mark": ch}
                    )
        return self

    def compiled(self) -> QuoteMarks:
        return _compile(self)


@dataclass(frozen=True, slots=True)
class MarkedSpan:
    start: int
    end: int
    """Offsets (code points) of the text between the marks, in the scanned text."""
    words: int


@dataclass(slots=True)
class WorkCounter:
    """Optional deterministic step counter of ``QuoteMarks.spans`` (tests bound the work)."""

    steps: int = 0


@dataclass(frozen=True, slots=True)
class QuoteMarks:
    openers: frozenset[str]
    closers: frozenset[str]
    opening_categories: frozenset[str]
    closing_categories: frozenset[str]
    separators: frozenset[str]
    count_separators: frozenset[str]
    max_span_chars: int

    def is_opener(self, ch: str) -> bool:
        return ch in self.openers or unicodedata.category(ch) in self.opening_categories

    def is_closer(self, ch: str) -> bool:
        return ch in self.closers or unicodedata.category(ch) in self.closing_categories

    def clean(self, text: str) -> str:
        """NFC, the configured invisible separators become a space, other format characters go."""
        out = []
        for ch in unicodedata.normalize("NFC", text):
            if ch in self.separators:
                out.append(" ")
            elif unicodedata.category(ch) != _FORMAT:
                out.append(ch)
        return "".join(out)

    def strip(self, text: str) -> str:
        """NFC with EVERY format character removed (a separator inside a word does not split it)."""
        return "".join(
            ch for ch in unicodedata.normalize("NFC", text) if unicodedata.category(ch) != _FORMAT
        )

    def count_words(self, text: str) -> int:
        """Words of ``text`` for the guard: separators (configured) split, other format
        characters are dropped."""
        out = []
        for ch in unicodedata.normalize("NFC", text):
            if ch in self.separators or ch in self.count_separators:
                out.append(" ")
            elif unicodedata.category(ch) != _FORMAT:
                out.append(ch)
        return len("".join(out).split())

    def spans(self, text: str, work: WorkCounter | None = None) -> list[MarkedSpan]:
        """Marked spans, left to right, in O(len(text)): the nearest closer after every position
        comes from one backward pass, so no opener rescans the text."""
        n = len(text)
        nearest = [n] * (n + 1)  # nearest[k] = first closer at or after k (n = none)
        for k in range(n - 1, -1, -1):
            nearest[k] = k if self.is_closer(text[k]) else nearest[k + 1]
        if work is not None:
            work.steps += n
        found: list[MarkedSpan] = []
        i = 0
        while i < n:
            if work is not None:
                work.steps += 1
            if not self.is_opener(text[i]):
                i += 1
                continue
            j = nearest[i + 1]
            if j < n and j - i - 1 <= self.max_span_chars:
                found.append(MarkedSpan(i + 1, j, self.count_words(text[i + 1 : j])))
                if work is not None:
                    work.steps += j - i
                i = j + 1
            else:
                i += 1
        return found


@cache
def _compile(cfg: QuoteMarkConfig) -> QuoteMarks:
    return QuoteMarks(
        openers=frozenset(p[0] for p in cfg.pairs),
        closers=frozenset(p[1] for p in cfg.pairs),
        opening_categories=frozenset(cfg.opening_categories),
        closing_categories=frozenset(cfg.closing_categories),
        separators=frozenset(cfg.invisible_separators),
        count_separators=frozenset(cfg.word_count_separators),
        max_span_chars=cfg.max_quote_span_chars,
    )


SEED_FILE = "quote_guard.seed.json"


@cache
def _seed_json() -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(
        files("agent_06_fact_checker").joinpath("data", SEED_FILE).read_text("utf-8")
    )
    return raw


def seed_data() -> dict[str, Any]:
    """The seeded data file (a copy; PROVISIONAL, needs editor review)."""
    copy: dict[str, Any] = json.loads(json.dumps(_seed_json()))
    return copy


def default_quote_marks() -> QuoteMarks:
    """Marks of the seed file: the default of ``find_quoted_spans`` when the caller passes none."""
    return QuoteMarkConfig.model_validate(_seed_json()["quote_marks"]).compiled()
