"""``EvidenceResolver`` (V-S2; blueprint 6.6, 10.3): which evidence a claim is checked against.

Cited sources first (hash equality with ``available_citations[].content_sha256``), library search
only for a claim with no usable citation (never into a restricted collection), restricted
sources only when released and cited (FIN-R12, Q26), bounded windows with offsets, chart facts of
the claim's own chart. The model never chooses sources and never sees an ID of the database."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from agent_06_fact_checker.config import FactCheckSettings
from agent_06_fact_checker.hashing import sha256_hex
from agent_06_fact_checker.models import (
    AvailableCitation,
    ChartFacts,
    ClaimMode,
    EvidenceSourceKind,
    ReasonCode,
    VerificationClaim,
)
from agent_06_fact_checker.planner import ClaimPlan
from agent_06_fact_checker.ports import KnowledgeReader, SourceText
from agent_06_fact_checker.windows import tokens, window
from amw_core.ids import ChannelId
from amw_core.interfaces import TenantTransaction


@dataclass(frozen=True, slots=True)
class Candidate:
    """One evidence window or chart fact; the unit the model sees as ``p..`` / ``f..``."""

    source_ref: str
    """``citation_ref`` or ``<chart_id>#<fact_id>`` (<= 64 characters)."""
    kind: EvidenceSourceKind
    offset: int
    """Offset of ``text`` in the source text (0 for a chart fact)."""
    text: str
    source_len: int
    source_sha256: str
    tier: str | None
    restricted: bool
    cited: bool


@dataclass(slots=True)
class ClaimEvidence:
    candidates: list[Candidate] = field(default_factory=list)
    reasons: list[ReasonCode] = field(default_factory=list)
    restricted_blocked: int = 0
    unresolvable: int = 0
    reads: int = 0


class EvidenceResolver:
    def __init__(
        self, reader: KnowledgeReader, settings: FactCheckSettings, *, release_approved: bool
    ) -> None:
        self._reader = reader
        self._settings = settings
        self._release = release_approved
        self._cache: dict[str, SourceText | None] = {}

    def preflight(
        self, tx: TenantTransaction, channel_id: ChannelId, citations: Sequence[AvailableCitation]
    ) -> int:
        """V0 check 2: every ``citation_ref`` belongs to the org and channel (a foreign ref raises
        ``CrossTenantRefError`` from the reader). Returns the number of reads (audit count)."""
        for cit in citations:
            self._source(tx, channel_id, cit.citation_ref)
        return len(citations)

    def _source(self, tx: TenantTransaction, channel: ChannelId, ref: str) -> SourceText | None:
        if ref not in self._cache:
            self._cache[ref] = self._reader.get_source(tx, channel, ref)
        return self._cache[ref]

    def resolve(
        self,
        tx: TenantTransaction,
        channel_id: ChannelId,
        plans: Sequence[ClaimPlan],
        citations: Sequence[AvailableCitation],
        chart_facts: Mapping[str, ChartFacts],
    ) -> dict[str, ClaimEvidence]:
        """``local_id`` -> evidence for every claim whose mode needs it."""
        expected = {c.citation_ref: c.content_sha256 for c in citations}
        out: dict[str, ClaimEvidence] = {}
        for plan in plans:
            claim = plan.claim
            if plan.mode is ClaimMode.CHART_FACTS and claim.chart_data_ref is not None:
                out[claim.local_id] = self._chart(claim, chart_facts[claim.chart_data_ref])
            elif plan.mode is ClaimMode.EVIDENCE:
                out[claim.local_id] = self._library(tx, channel_id, claim, expected)
        return out

    def _chart(self, claim: VerificationClaim, facts: ChartFacts) -> ClaimEvidence:
        ev = ClaimEvidence()
        for fact in facts.facts:
            ev.candidates.append(
                Candidate(
                    source_ref=f"{facts.ref_id}#{fact.fact_id}",
                    kind=EvidenceSourceKind.CHART_FACT,
                    offset=0,
                    text=fact.statement,
                    source_len=len(fact.statement),
                    source_sha256=sha256_hex(fact.statement),
                    tier=None,
                    restricted=False,
                    cited=True,
                )
            )
        return ev

    def _library(
        self,
        tx: TenantTransaction,
        channel_id: ChannelId,
        claim: VerificationClaim,
        expected: Mapping[str, str | None],
    ) -> ClaimEvidence:
        s = self._settings
        ev = ClaimEvidence()
        want = tokens(claim.normalized_claim) | tokens(claim.quote)
        usable: list[tuple[SourceText, bool]] = []
        for ref in claim.citation_refs:
            src = self._source(tx, channel_id, ref)
            ev.reads += 1
            if src is None or ref not in expected or src.content_sha256 != expected[ref]:
                ev.unresolvable += 1
                continue
            if src.restricted and not self._release:
                ev.restricted_blocked += 1
                continue
            usable.append((src, True))
        if not usable and s.search_top_k_per_claim > 0:
            found = self._reader.search(
                tx, channel_id, claim.normalized_claim, s.search_top_k_per_claim
            )
            ev.reads += 1
            usable.extend(
                (src, False) for src in found[: s.search_top_k_per_claim] if not src.restricted
            )
        cands: list[Candidate] = []
        for src, cited in usable:
            for win in window(src.text, want, s.max_window_chars, s.max_passages_per_claim):
                cands.append(
                    Candidate(
                        source_ref=src.citation_ref,
                        kind=EvidenceSourceKind(src.kind.value),
                        offset=win.offset,
                        text=win.text,
                        source_len=len(src.text),
                        source_sha256=src.content_sha256,
                        tier=src.reliability_tier,
                        restricted=src.restricted,
                        cited=cited,
                    )
                )
        cands.sort(key=lambda c: (not c.cited, -len(tokens(c.text) & want), c.source_ref, c.offset))
        ev.candidates = sorted(
            cands[: s.max_passages_per_claim], key=lambda c: (c.source_ref, c.offset)
        )
        if ev.unresolvable:
            ev.reasons.append(ReasonCode.CITATION_UNRESOLVABLE)
        return ev
