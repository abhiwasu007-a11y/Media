"""QUOTE-VERIFY (D12): exact verification of quotes and attributions against the library text.

Extends Agent 06 inside the existing contract: claim type ``QUOTED_THIRD_PARTY`` (GLOSSARY 6.39)
with the existing statuses and reason code ``QUOTE_NOT_ATTRIBUTABLE`` and revision action
``REMOVE_OR_REWORD`` (blueprint 6.4). The finer ``QuoteCode`` is package-internal until CCR-285
(PROPOSED) is decided. Library text is read through the read-only reader, compared in memory and
never returned: a result carries offsets, counts and hashes only (NFR-6).

Matching, defined exactly (the shared fuzzy ``amw_core.text_normalise`` is deliberately NOT used:
it folds look-alike letters, which would let a changed quote pass):

1. NFC; typographic single quotes (U+2018, U+2019, U+201A, U+201B) become ``'`` and typographic
   double quotes (U+201C, U+201D, U+201E, U+201F) become ``"``;
2. every run of Unicode whitespace (including NBSP and line breaks) becomes one space; ends trimmed;
3. nothing else is normalised: case, punctuation, dashes, diacritics, zero-width characters and
   look-alike letters all count. An ellipsis is literal: quote the parts as separate quotes;
4. the quote must be an exact substring of the (normalised) text of the cited section, and must
   begin and end on a word boundary (``ort life`` never matches inside ``short life``).
"""

import hashlib
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from agent_06_fact_checker.library.copyright import (
    PdReason,
    WorkCopyrightRecord,
    evaluate_public_domain,
    job_year,
)
from agent_06_fact_checker.library.reader import KnowledgeLibraryReader
from agent_06_fact_checker.models import ReasonCode, RevisionAction
from amw_core.contracts.common import AmwModel
from amw_core.enums import ClaimStatus

_QUOTE_MAP = {
    **dict.fromkeys((0x2018, 0x2019, 0x201A, 0x201B), "'"),
    **dict.fromkeys((0x201C, 0x201D, 0x201E, 0x201F), '"'),
}
_SECTION_MARKER = re.compile(r"^§[ \t]*(?P<loc>\S.*?)[ \t]*$")
_SPANS = (
    re.compile("\\u201c([^\\u201c\\u201d]*)\\u201d"),
    re.compile("\\u00ab([^\\u00ab\\u00bb]*)\\u00bb"),
    re.compile(r'"([^"\n]*)"'),
)


def normalise_quote_text(text: str) -> str:
    """Rules 1 and 2 of the module docstring; nothing else is changed."""
    folded = unicodedata.normalize("NFC", text).translate(_QUOTE_MAP)
    return " ".join(folded.split())


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class QuoteCode(StrEnum):
    VERIFIED_EXACT = "VERIFIED_EXACT"
    EMPTY_QUOTE = "EMPTY_QUOTE"
    NO_SOURCE = "NO_SOURCE"
    ATTRIBUTION_MISMATCH = "ATTRIBUTION_MISMATCH"
    NOT_PUBLIC_DOMAIN = "NOT_PUBLIC_DOMAIN"
    LOCATOR_MISSING = "LOCATOR_MISSING"
    LOCATOR_UNVERIFIABLE = "LOCATOR_UNVERIFIABLE"
    LOCATOR_NOT_FOUND = "LOCATOR_NOT_FOUND"
    LOCATOR_MISMATCH = "LOCATOR_MISMATCH"
    NOT_IN_SOURCE = "NOT_IN_SOURCE"


class QuoteAction(StrEnum):
    KEEP = "KEEP"
    REMOVE_QUOTE = "REMOVE_QUOTE"
    """Nothing to check against: the quote is removed or reworded as ideas."""
    BLOCK_CLAIM = "BLOCK_CLAIM"
    """A checked source contradicts or forbids the quote (fake quote, wrong place, not PD)."""


# code -> (action, status); one table so the mapping is reviewable in one place (CCR-285)
_OUTCOME: Mapping[QuoteCode, tuple[QuoteAction, ClaimStatus]] = {
    QuoteCode.VERIFIED_EXACT: (QuoteAction.KEEP, ClaimStatus.VERIFIED),
    QuoteCode.EMPTY_QUOTE: (QuoteAction.REMOVE_QUOTE, ClaimStatus.NEEDS_SUBSTANTIATION),
    QuoteCode.NO_SOURCE: (QuoteAction.REMOVE_QUOTE, ClaimStatus.NEEDS_SUBSTANTIATION),
    QuoteCode.LOCATOR_MISSING: (QuoteAction.REMOVE_QUOTE, ClaimStatus.NEEDS_SUBSTANTIATION),
    QuoteCode.LOCATOR_UNVERIFIABLE: (QuoteAction.REMOVE_QUOTE, ClaimStatus.NEEDS_SUBSTANTIATION),
    QuoteCode.ATTRIBUTION_MISMATCH: (QuoteAction.BLOCK_CLAIM, ClaimStatus.CONTRADICTED),
    QuoteCode.NOT_PUBLIC_DOMAIN: (QuoteAction.BLOCK_CLAIM, ClaimStatus.CONTRADICTED),
    QuoteCode.LOCATOR_NOT_FOUND: (QuoteAction.BLOCK_CLAIM, ClaimStatus.CONTRADICTED),
    QuoteCode.LOCATOR_MISMATCH: (QuoteAction.BLOCK_CLAIM, ClaimStatus.CONTRADICTED),
    QuoteCode.NOT_IN_SOURCE: (QuoteAction.BLOCK_CLAIM, ClaimStatus.CONTRADICTED),
}


@dataclass(frozen=True, slots=True)
class QuoteSubmission:
    """One quote of a ``QUOTED_THIRD_PARTY`` claim as the script presents it."""

    claim_id: str
    quoted_text: str
    """The words inside the quotation marks (marks excluded)."""
    attributed_author: str
    work_id: str | None
    locator: str | None
    """Chapter / verse reference as the script gives it, e.g. ``I.3``."""


@dataclass(frozen=True, slots=True)
class QuoteSettings:
    """Configuration; no defaults."""

    require_locator: bool
    """``True``: a PD quote without a verifiable chapter / verse reference is not accepted."""
    guard_min_words: int
    """Quoted spans of at least this many words must be checked quotes (fake-quote guard)."""


class QuoteCheckResult(AmwModel):
    claim_id: str
    code: QuoteCode
    action: QuoteAction
    status: ClaimStatus
    reason: ReasonCode | None
    revision_action: RevisionAction | None
    work_id: str | None = None
    pd_reason: PdReason | None = None
    locator: str | None = None
    locator_verified: bool = False
    match_start: int | None = None
    match_end: int | None = None
    """Offsets (code points) inside the normalised text of the cited section."""
    occurrences: int = 0
    quote_sha256: str


def _result(
    sub: QuoteSubmission,
    code: QuoteCode,
    *,
    quote: str,
    pd_reason: PdReason | None = None,
    locator_verified: bool = False,
    span: tuple[int, int] | None = None,
    occurrences: int = 0,
) -> QuoteCheckResult:
    action, status = _OUTCOME[code]
    kept = action is QuoteAction.KEEP
    return QuoteCheckResult(
        claim_id=sub.claim_id,
        code=code,
        action=action,
        status=status,
        reason=None if kept else ReasonCode.QUOTE_NOT_ATTRIBUTABLE,
        revision_action=None if kept else RevisionAction.REMOVE_OR_REWORD,
        work_id=sub.work_id,
        pd_reason=pd_reason,
        locator=sub.locator,
        locator_verified=locator_verified,
        match_start=span[0] if span else None,
        match_end=span[1] if span else None,
        occurrences=occurrences,
        quote_sha256=_sha(quote),
    )


@dataclass(frozen=True, slots=True)
class _Sections:
    by_locator: Mapping[str, str]
    ambiguous: frozenset[str]
    whole: str
    """Normalised text of all sections, marker lines excluded."""


def split_sections(raw_text: str) -> _Sections:
    """Sections start at a marker line ``§ <locator>`` (CCR-285 PROPOSED); text before the first
    marker belongs to no section. A repeated locator is ambiguous and never verifies."""
    buckets: dict[str, list[str]] = {}
    seen_twice: set[str] = set()
    current: list[str] | None = None
    for line in raw_text.splitlines():
        marker = _SECTION_MARKER.match(line)
        if marker:
            loc = normalise_quote_text(marker.group("loc"))
            if loc in buckets:
                seen_twice.add(loc)
            current = buckets.setdefault(loc, [])
        elif current is not None:
            current.append(line)
    by_loc = {loc: normalise_quote_text("\n".join(lines)) for loc, lines in buckets.items()}
    return _Sections(by_loc, frozenset(seen_twice), " ".join(by_loc.values()))


def _boundary_ok(text: str, start: int, end: int) -> bool:
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    first, last = text[start], text[end - 1]
    return not ((before.isalnum() and first.isalnum()) or (after.isalnum() and last.isalnum()))


def find_exact(haystack: str, needle: str) -> tuple[int, int, int] | None:
    """First word-bounded exact occurrence as ``(start, end, count)``; ``None`` when absent."""
    if not needle:
        return None
    hits: list[int] = []
    pos = haystack.find(needle)
    while pos != -1:
        if _boundary_ok(haystack, pos, pos + len(needle)):
            hits.append(pos)
        pos = haystack.find(needle, pos + 1)
    if not hits:
        return None
    return hits[0], hits[0] + len(needle), len(hits)


class QuoteVerifier:
    """Verifies submissions against the records and the library text, read-only."""

    def __init__(
        self,
        records: Mapping[str, WorkCopyrightRecord],
        reader: KnowledgeLibraryReader,
        settings: QuoteSettings,
    ) -> None:
        self._records = records
        self._reader = reader
        self._settings = settings
        self._sections: dict[str, _Sections] = {}

    def verify(
        self, submissions: Sequence[QuoteSubmission], *, job_date: date
    ) -> list[QuoteCheckResult]:
        return [self._verify_one(sub, job_date) for sub in submissions]

    def _text_of(self, record: WorkCopyrightRecord) -> _Sections:
        cached = self._sections.get(record.work_id)
        if cached is None:
            cached = split_sections(self._reader.read_text(record.text_path))
            self._sections[record.work_id] = cached
        return cached

    def _verify_one(self, sub: QuoteSubmission, job_date: date) -> QuoteCheckResult:
        quote = normalise_quote_text(sub.quoted_text)
        if not quote:
            return _result(sub, QuoteCode.EMPTY_QUOTE, quote=quote)
        record = self._records.get(sub.work_id) if sub.work_id else None
        if record is None:
            return _result(sub, QuoteCode.NO_SOURCE, quote=quote)
        if normalise_quote_text(sub.attributed_author).casefold() != (
            normalise_quote_text(record.author).casefold()
        ):
            return _result(sub, QuoteCode.ATTRIBUTION_MISMATCH, quote=quote)
        decision = evaluate_public_domain(record, year=job_year(job_date))
        if not decision.public_domain:  # the text of a non-PD work is never read
            return _result(sub, QuoteCode.NOT_PUBLIC_DOMAIN, quote=quote, pd_reason=decision.reason)
        loc = normalise_quote_text(sub.locator) if sub.locator else ""
        if not loc and self._settings.require_locator:
            return _result(sub, QuoteCode.LOCATOR_MISSING, quote=quote, pd_reason=decision.reason)
        return self._match(sub, record, quote, loc, decision.reason)

    def _match(
        self,
        sub: QuoteSubmission,
        record: WorkCopyrightRecord,
        quote: str,
        loc: str,
        pd_reason: PdReason,
    ) -> QuoteCheckResult:
        sections = self._text_of(record)

        def out(
            code: QuoteCode,
            *,
            verified_locator: bool = False,
            span: tuple[int, int] | None = None,
            occurrences: int = 0,
        ) -> QuoteCheckResult:
            return _result(
                sub,
                code,
                quote=quote,
                pd_reason=pd_reason,
                locator_verified=verified_locator,
                span=span,
                occurrences=occurrences,
            )

        if not loc:  # allowed only when require_locator is False
            hit = find_exact(sections.whole, quote)
            if hit is None:
                return out(QuoteCode.NOT_IN_SOURCE)
            return out(QuoteCode.VERIFIED_EXACT, span=(hit[0], hit[1]), occurrences=hit[2])
        if not sections.by_locator or loc in sections.ambiguous:
            return out(QuoteCode.LOCATOR_UNVERIFIABLE)
        body = sections.by_locator.get(loc)
        if body is None:
            return out(QuoteCode.LOCATOR_NOT_FOUND)
        hit = find_exact(body, quote)
        if hit is not None:
            return out(
                QuoteCode.VERIFIED_EXACT,
                verified_locator=True,
                span=(hit[0], hit[1]),
                occurrences=hit[2],
            )
        elsewhere = find_exact(sections.whole, quote)
        return out(QuoteCode.NOT_IN_SOURCE if elsewhere is None else QuoteCode.LOCATOR_MISMATCH)


@dataclass(frozen=True, slots=True)
class QuotedSpan:
    start: int
    end: int
    """Offsets (code points) of the text between the marks, in the script."""
    words: int
    sha256: str


def find_quoted_spans(script_text: str) -> list[QuotedSpan]:
    """Spans in double quotation marks (straight, curly, guillemets). Single quotes are not
    scanned: an apostrophe cannot be told from a mark by a pure rule (documented limit)."""
    spans: list[QuotedSpan] = []
    for pattern in _SPANS:
        for m in pattern.finditer(script_text):
            inner = normalise_quote_text(m.group(1))
            spans.append(QuotedSpan(m.start(1), m.end(1), len(inner.split()), _sha(inner)))
    return sorted(spans, key=lambda s: s.start)


def unchecked_quotes(
    script_text: str, submissions: Sequence[QuoteSubmission], *, min_words: int
) -> list[QuotedSpan]:
    """Fake-quote guard for the whole script: every quoted span of ``min_words`` or more that
    is not one of the submitted (and so checked) quotes. The caller blocks or removes them."""
    checked = {_sha(normalise_quote_text(s.quoted_text)) for s in submissions}
    return [
        s
        for s in find_quoted_spans(script_text)
        if s.words >= min_words and s.sha256 not in checked
    ]
