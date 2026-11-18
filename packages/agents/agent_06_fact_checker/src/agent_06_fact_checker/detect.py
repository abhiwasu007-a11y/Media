"""Code-only detection over the script's own sentences (blueprint 6.8 D3, D4, D11; 13 5.4).

Everything here runs on the *input* (segment text, chart references) and on the rule-pack
lexicon, never on what the model chose to extract. It is the safety net behind the LLM judge
(13 3: ``LLM_JUDGE`` is always paired with a deterministic pre-filter): a model that returns no
claim, no flag or ``ALLOWED`` cannot make a detected call disappear.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from agent_06_fact_checker.lexicon import (
    Suffixes,
    all_markers,
    find_patterns,
    find_urls,
    norm,
    suffix_families,
    term_spans,
)
from agent_06_fact_checker.models import ChartDataRef, DataAge, Segment
from agent_06_fact_checker.numbers import numerals
from agent_06_fact_checker.rulepack import DetectorRule, FinLexicon
from amw_core.enums import RuleSeverity

_SENTENCE_END = re.compile(r"(?<=[.!?।;])\s+")
_OPEN = {'"': '"', "\u201c": "\u201d", "\u2018": "\u2019"}  # straight and curly quotes
URL_TERM = "<URL>"
CODE_TERM = "<CODE>"
WARN_PREFIX = "Code check "


@dataclass(frozen=True, slots=True)
class Finding:
    """A code detection: ``start``/``end`` are offsets in the segment text (a whole sentence)."""

    segment_id: str | None
    start: int
    end: int
    rule_id: str
    severity: RuleSeverity
    evidence: str


def sentences(text: str) -> list[tuple[int, int]]:
    """Sentence spans (offsets) split at ``. ! ? । ;`` followed by white space."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in _SENTENCE_END.finditer(text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(text)))
    return [(a, b) for a, b in spans if b > a]


def quoted_ranges(text: str) -> list[tuple[int, int]]:
    """Ranges inside quotation marks (a third party's words); apostrophes inside words ignored."""
    ranges: list[tuple[int, int]] = []
    open_at: int | None = None
    closer = ""
    for i, ch in enumerate(text):
        if open_at is None:
            opens = ch in _OPEN or (ch == "'" and (i == 0 or not text[i - 1].isalnum()))
            if opens:
                open_at, closer = i, _OPEN.get(ch, "'")
        elif ch == closer and not (ch == "'" and i + 1 < len(text) and text[i + 1].isalnum()):
            ranges.append((open_at, i))
            open_at = None
    return ranges


def _inside(pos: int, ranges: Iterable[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in ranges)


class Detector:
    def __init__(
        self,
        lexicon: FinLexicon,
        markers: Mapping[str, Sequence[str]],
        referral_patterns: Sequence[str],
        extra_instruments: Iterable[str] = (),
    ) -> None:
        self._lex = lexicon
        self._suffixes: Suffixes = suffix_families(lexicon.suffixes)
        self._markers = all_markers(markers)
        self._patterns = tuple(referral_patterns)
        names = {norm(n).strip() for ns in lexicon.instruments.values() for n in ns}
        names |= {norm(n).strip() for n in extra_instruments}
        self._instruments = tuple(sorted(n for n in names if n))

    def _has(self, hay: str, term: str) -> list[tuple[int, int]]:
        return term_spans(hay, term, self._suffixes)

    def _instrument_in(self, hay: str) -> bool:
        return any(self._has(hay, n) for n in self._instruments)

    def _group_hit(self, group: Iterable[str], hay: str, raw: str) -> tuple[int, int, str] | None:
        for term in group:
            if term == URL_TERM:
                spans = find_urls(raw)
            elif term == CODE_TERM:
                spans = find_patterns(raw, self._patterns)
            else:
                spans = self._has(hay, term)
            if spans:
                return spans[0][0], spans[0][1], term
        return None

    def _match(self, rule: DetectorRule, raw: str, hay: str) -> tuple[RuleSeverity, str] | None:
        if rule.needs_instrument and not self._instrument_in(hay):
            return None
        if rule.needs_number and not numerals(raw):
            return None
        first: tuple[int, int, str] | None = None
        for i, group in enumerate(rule.groups):
            hit = self._group_hit(group, hay, raw)
            if hit is None:
                return None
            if i == 0:
                first = hit
        if first is None:  # a rule without groups never matches
            return None
        severity = rule.severity
        if any(self._has(hay, t) for t in rule.warn_if):
            severity = RuleSeverity.WARNING
        if rule.quote_warn and _inside(first[0], quoted_ranges(raw)):
            severity = RuleSeverity.WARNING
        return severity, first[2]

    def scan(self, seg: Segment) -> list[Finding]:
        """Every rule detection and every future-marker hit, per sentence of the segment."""
        out: dict[tuple[int, str], Finding] = {}
        for a, b in sentences(seg.text):
            hay = norm(seg.text[a:b])
            raw = hay  # numerals, URLs, quotes and terms are all read on the normalised sentence
            for rule in self._lex.detectors:
                got = self._match(rule, raw, hay)
                if got is not None:
                    self._put(out, Finding(seg.segment_id, a, b, rule.rule_id, got[0], got[1]))
            if self._instrument_in(hay):  # D11 (13 5.4): named instrument plus a future marker
                for marker in self._markers:
                    if self._has(hay, marker):
                        finding = Finding(
                            seg.segment_id, a, b, "FIN-R13", RuleSeverity.WARNING, marker
                        )
                        self._put(out, finding)
                        break
            if find_urls(raw) or find_patterns(raw, self._patterns):  # D4
                self._put(
                    out, Finding(seg.segment_id, a, b, "FIN-R8", RuleSeverity.WARNING, "link")
                )
        return list(out.values())

    @staticmethod
    def _put(out: dict[tuple[int, str], Finding], f: Finding) -> None:
        key = (f.start, f.rule_id)
        old = out.get(key)
        if old is None or (
            old.severity is RuleSeverity.WARNING and f.severity is RuleSeverity.BLOCKING
        ):
            out[key] = f


def chart_findings(
    refs: Sequence[ChartDataRef],
    segments: Sequence[Segment],
    linked: Iterable[str],
) -> list[Finding]:
    """M-1: a chart inside the lag (or of unknown age) blocks even when no claim links it."""
    seen = set(linked)
    found: list[Finding] = []
    for ref in refs:
        if ref.data_age_vs_lag not in (DataAge.WITHIN_LAG, DataAge.UNKNOWN) or ref.ref_id in seen:
            continue
        home = next((s.segment_id for s in segments if ref.ref_id in s.visual_refs), None)
        found.append(Finding(home, 0, 0, "FIN-R9", RuleSeverity.BLOCKING, ref.ref_id))
    return found
