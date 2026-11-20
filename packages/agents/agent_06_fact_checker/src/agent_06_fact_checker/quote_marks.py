"""Quotation-mark spans from a CONFIGURATION table (D16: no mark list in the code).

A span is an opening mark of ANY kind followed later (same line) by a closing mark of ANY kind:
mixed or mismatched marks (``"x”``, ``«x"``) are spans too, which is the conservative reading for
a guard. The marks come from ``QuoteMarkConfig``: an explicit pair table (marks that Unicode does
not class as quotation marks, such as the low-9 ``„``, corner brackets, the straight mark, the
reversed ``»x«``) plus whole Unicode categories (``Pi`` opens, ``Pf`` closes), so a quotation mark
that the table forgot is still seen. The apostrophe ``'`` is in no table: it cannot be told from a
mark by a pure rule (documented limit); a closing curly single mark alone never starts a span.

Invisible characters: a ZERO WIDTH SPACE separates words (configured); every other format
character (ZWJ, ZWNJ, soft hyphen, word joiner, bidi marks) is dropped before counting words."""

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


@dataclass(frozen=True, slots=True)
class QuoteMarks:
    openers: frozenset[str]
    closers: frozenset[str]
    opening_categories: frozenset[str]
    closing_categories: frozenset[str]
    separators: frozenset[str]

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

    def spans(self, text: str) -> list[MarkedSpan]:
        found: list[MarkedSpan] = []
        i, n = 0, len(text)
        while i < n:
            if not self.is_opener(text[i]):
                i += 1
                continue
            j = i + 1
            while j < n and text[j] != "\n" and not self.is_closer(text[j]):
                j += 1
            if j < n and text[j] != "\n":
                found.append(MarkedSpan(i + 1, j, len(self.clean(text[i + 1 : j]).split())))
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
