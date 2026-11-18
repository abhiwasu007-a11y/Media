"""S5: PackAssembler, CitationBuilder (blueprint 6.5, 8, 10.7). Pure: no I/O, no model.

Coverage: ``SOURCED`` needs a usable note for every DEFINITION, MECHANISM, PRINCIPLE or STATISTIC
need and the reliability floor; ``PARTIAL`` is some usable notes or only low-reliability support;
``UNSOURCED`` is none. A concept without a source is flagged, never filled (SC-6).
"""

from dataclasses import dataclass, field
from datetime import datetime

from agent_04_research_knowledge.errors import InsufficientInput
from agent_04_research_knowledge.models.enums import (
    FACTUAL_KINDS,
    REQUIRED_NEED_KINDS,
    CopyGuardStatus,
    Coverage,
    ExclusionReason,
    FetchStatus,
    GapReason,
    NoteProblem,
    ReliabilityTier,
    StatementKind,
)
from agent_04_research_knowledge.models.pack_output import (
    Citation,
    CoverageSummary,
    EvidenceItem,
    FurtherReading,
    Locator,
    MethodInfo,
    PackConcept,
    PackGap,
    PackSource,
    PackTopic,
    Provenance,
    ResearchPack,
    RestrictedPending,
    TopicVerdict,
)
from agent_04_research_knowledge.models.plan import PlannedConcept
from agent_04_research_knowledge.steps.notes import DroppedNote, ValidatedNote
from amw_core.enums import (
    ComplianceVerdict,
    EvidenceSourceKind,
    KnowledgeSourceKind,
    SourceOwnership,
)


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_ref: str
    kind: KnowledgeSourceKind
    title: str
    author: str | None
    edition: str | None
    ownership: SourceOwnership | None
    tier: ReliabilityTier
    score: float | None
    collection_key: str | None
    external_url: str | None
    accessed_at: datetime | None
    fetch_status: FetchStatus
    content_sha256: str | None
    snapshot_ref: str | None
    credit_in_description: bool = False


@dataclass(frozen=True, slots=True)
class CitationMeta:
    kind: EvidenceSourceKind
    title: str
    content_sha256: str


@dataclass
class ConceptEvidence:
    concept: PlannedConcept
    notes: list[ValidatedNote] = field(default_factory=list)
    dropped: list[DroppedNote] = field(default_factory=list)
    excluded_forward_looking: int = 0
    restricted_blocked: bool = False
    notes_refused: bool = False


@dataclass
class AssemblyInput:
    topic: PackTopic
    iteration: int
    concepts: list[ConceptEvidence]
    sources: dict[str, SourceRecord]
    citations: dict[str, CitationMeta]
    restricted_pending: dict[str, list[str]]
    input_gap_ids: frozenset[str]
    approvals_by_citation: dict[str, str | None]
    """citation_ref to the ``KNOWLEDGE_RELEASE`` approval that released a restricted chunk."""
    min_tier_for_factual: ReliabilityTier
    rule_pack_versions: dict[str, str]
    plan_prompt_id: str
    notes_prompt_id: str
    llm_calls: int


@dataclass(frozen=True, slots=True)
class Assembly:
    pack: ResearchPack
    usable_total: int
    unclosed_gap_ids: tuple[str, ...]
    cross_language_items: int


def blocked_pack(
    topic: PackTopic,
    iteration: int,
    verdict: ComplianceVerdict,
    rule_ids: tuple[str, ...],
    rule_pack_versions: dict[str, str],
    plan_prompt_id: str,
    notes_prompt_id: str,
    llm_calls: int,
) -> ResearchPack:
    """A BLOCKED or NEEDS_HUMAN_REVIEW topic: empty concepts, evidence, citations and sources."""
    return ResearchPack(
        pack_version=1,
        iteration=iteration,
        topic_verdict=TopicVerdict(verdict=verdict, violated_rule_ids=rule_ids),
        topic=topic,
        concepts=(),
        evidence=(),
        citations_available=(),
        sources=(),
        gaps=(),
        method=MethodInfo(used=False, release_approval_ids=(), restricted_pending=()),
        further_reading=(),
        terminology=(),
        coverage_summary=CoverageSummary(
            concepts_total=0,
            sourced=0,
            partial=0,
            unsourced=0,
            evidence_total=0,
            evidence_usable=0,
            excluded_forward_looking=0,
            excluded_copy_guard=0,
        ),
        provenance=Provenance(
            plan_prompt_id=plan_prompt_id,
            notes_prompt_id=notes_prompt_id,
            rule_pack_versions=rule_pack_versions,
            llm_calls=llm_calls,
        ),
    )


class PackAssembler:
    def assemble(self, data: AssemblyInput) -> Assembly:
        floor = data.min_tier_for_factual.rank
        concepts: list[PackConcept] = []
        evidence: list[EvidenceItem] = []
        gaps: list[PackGap] = []
        used_sources: dict[str, SourceRecord] = {}
        unclosed: set[str] = set()
        cross = 0
        excl_fwd = excl_copy = 0
        counter = 0
        for ce in data.concepts:
            c = ce.concept
            floor_met = any(n.passage.tier.rank <= floor for n in ce.notes if self._clean(n))
            items: list[EvidenceItem] = []
            for note in ce.notes:
                counter += 1
                reason = note.exclusion_reason
                usable = note.usable
                factual = note.note.statement_kind in FACTUAL_KINDS
                if usable and factual and not floor_met:
                    usable, reason = False, ExclusionReason.LOW_RELIABILITY
                if note.copy_guard is CopyGuardStatus.SKIPPED_CROSS_LANGUAGE and usable:
                    cross += 1
                src = data.sources[note.passage.source_ref]
                used_sources[src.source_ref] = src
                items.append(self._item(counter, c.concept_id, note, usable, reason))
            evidence.extend(items)
            usable_items = [i for i in items if i.usable_for_script]
            coverage = self._coverage(c, items, usable_items, floor_met)
            concepts.append(
                PackConcept(
                    concept_id=c.concept_id,
                    label=c.label,
                    label_en=c.label_en,
                    kind=c.kind,
                    evidence_needs=tuple(n.value for n in c.evidence_needs),
                    time_reference=c.time_reference,
                    coverage=coverage,
                    evidence_ids=tuple(i.evidence_id for i in items),
                    has_example=any(
                        i.statement_kind
                        in (StatementKind.EXAMPLE_HISTORICAL, StatementKind.EXAMPLE_HYPOTHETICAL)
                        for i in usable_items
                    ),
                    closes_gap_ids=c.closes_gap_ids,
                )
            )
            excl_fwd += ce.excluded_forward_looking + sum(
                1 for i in items if i.exclusion_reason is ExclusionReason.FORWARD_LOOKING
            )
            excl_copy += sum(1 for d in ce.dropped if d.problem is NoteProblem.COPY_OVERLAP)
            reasons = self._gap_reasons(ce, coverage, items, usable_items)
            gaps.extend(PackGap(concept_id=c.concept_id, reason=r) for r in reasons)
            if coverage is not Coverage.SOURCED:
                for gap_id in c.closes_gap_ids:
                    if gap_id in data.input_gap_ids:
                        unclosed.add(gap_id)
                        gaps.append(
                            PackGap(concept_id=c.concept_id, reason=GapReason.PRIOR_GAP_NOT_CLOSED)
                        )
        for src in data.sources.values():  # unreachable references stay on record, without a hash
            if src.fetch_status is FetchStatus.UNREACHABLE:
                used_sources[src.source_ref] = src
        usable_refs = sorted({e.citation_ref for e in evidence if e.usable_for_script})
        citations = tuple(self._citation(r, data.citations[r]) for r in usable_refs)
        method_items = [e for e in evidence if e.usable_for_script and e.method_labelled]
        approvals = sorted(
            {
                a
                for e in method_items
                if (a := data.approvals_by_citation.get(e.citation_ref)) is not None
            }
        )
        pack = ResearchPack(
            pack_version=1,
            iteration=data.iteration,
            topic_verdict=TopicVerdict(verdict=ComplianceVerdict.ALLOWED, violated_rule_ids=()),
            topic=data.topic,
            concepts=tuple(concepts),
            evidence=tuple(evidence),
            citations_available=citations,
            sources=tuple(self._source(s) for _, s in sorted(used_sources.items())),
            gaps=tuple(dict.fromkeys(gaps)),
            method=MethodInfo(
                used=bool(method_items),
                release_approval_ids=tuple(approvals),
                restricted_pending=tuple(
                    RestrictedPending(collection_key=k, concept_ids=tuple(sorted(set(v))))
                    for k, v in sorted(data.restricted_pending.items())
                ),
            ),
            further_reading=self._further_reading(data, evidence),
            terminology=(),
            coverage_summary=CoverageSummary(
                concepts_total=len(concepts),
                sourced=sum(c.coverage is Coverage.SOURCED for c in concepts),
                partial=sum(c.coverage is Coverage.PARTIAL for c in concepts),
                unsourced=sum(c.coverage is Coverage.UNSOURCED for c in concepts),
                evidence_total=len(evidence),
                evidence_usable=sum(e.usable_for_script for e in evidence),
                excluded_forward_looking=excl_fwd,
                excluded_copy_guard=excl_copy,
            ),
            provenance=Provenance(
                plan_prompt_id=data.plan_prompt_id,
                notes_prompt_id=data.notes_prompt_id,
                rule_pack_versions=data.rule_pack_versions,
                llm_calls=data.llm_calls,
            ),
        )
        return Assembly(
            pack, sum(e.usable_for_script for e in evidence), tuple(sorted(unclosed)), cross
        )

    @staticmethod
    def require_usable(assembly: Assembly) -> None:
        """A pack with no usable note at all is a failure, never a best-effort success (6.5)."""
        if assembly.usable_total == 0:
            raise InsufficientInput("no usable note in the whole pack")

    @staticmethod
    def _clean(note: ValidatedNote) -> bool:
        """Evidence that is sound in itself (not forward-looking): counts for the floor."""
        return note.exclusion_reason is None

    @staticmethod
    def _item(
        n: int, concept_id: str, note: ValidatedNote, usable: bool, reason: ExclusionReason | None
    ) -> EvidenceItem:
        p = note.passage
        return EvidenceItem(
            evidence_id=f"ev_{n:03d}",
            concept_id=concept_id,
            statement_kind=note.note.statement_kind,
            note=note.note.note,
            time_reference_kind=note.note.time_reference_kind,
            instruments=note.note.instruments,
            citation_ref=p.citation_ref,
            source_ref=p.source_ref,
            reliability_tier=p.tier,
            owner_authored=p.owner_authored,
            method_labelled=p.method_labelled,
            usable_for_script=usable,
            exclusion_reason=None if usable else reason,
            copy_guard=note.copy_guard,
            locator=Locator(chapter=p.chapter, page_from=p.page_from, page_to=p.page_to),
        )

    @staticmethod
    def _coverage(
        c: PlannedConcept,
        items: list[EvidenceItem],
        usable: list[EvidenceItem],
        floor_met: bool,
    ) -> Coverage:
        if not usable:
            low = any(i.exclusion_reason is ExclusionReason.LOW_RELIABILITY for i in items)
            return Coverage.PARTIAL if low else Coverage.UNSOURCED
        needs = [n for n in c.evidence_needs if n in REQUIRED_NEED_KINDS]
        met = all(any(u.statement_kind is n for u in usable) for n in needs)
        factual = any(n in FACTUAL_KINDS for n in c.evidence_needs)
        if met and (floor_met or not factual):
            return Coverage.SOURCED
        return Coverage.PARTIAL

    @staticmethod
    def _gap_reasons(
        ce: ConceptEvidence,
        coverage: Coverage,
        items: list[EvidenceItem],
        usable: list[EvidenceItem],
    ) -> list[GapReason]:
        if coverage is Coverage.SOURCED:
            return []
        reasons: list[GapReason] = []
        if any(i.exclusion_reason is ExclusionReason.LOW_RELIABILITY for i in items):
            reasons.append(GapReason.ONLY_LOW_RELIABILITY)
        if not usable:
            if ce.restricted_blocked:
                reasons.append(GapReason.ONLY_RESTRICTED_NOT_RELEASED)
            if ce.excluded_forward_looking or any(
                i.exclusion_reason is ExclusionReason.FORWARD_LOOKING for i in items
            ):
                reasons.append(GapReason.ONLY_EXCLUDED_FORWARD_LOOKING)
        if any(d.problem is NoteProblem.COPY_OVERLAP for d in ce.dropped):
            reasons.append(GapReason.COPY_GUARD_REMOVED)
        if not reasons or (coverage is Coverage.PARTIAL and usable and not reasons):
            reasons.append(GapReason.NO_SOURCE_FOUND)
        if not usable and not items and GapReason.NO_SOURCE_FOUND not in reasons:
            reasons.append(GapReason.NO_SOURCE_FOUND)
        return reasons

    @staticmethod
    def _citation(ref: str, meta: CitationMeta) -> Citation:
        kind = (
            EvidenceSourceKind.KNOWLEDGE_CHUNK
            if ref.startswith("kch_")
            else EvidenceSourceKind.EXTERNAL_REFERENCE
        )
        return Citation(
            citation_ref=ref, kind=kind, title=meta.title[:300], content_sha256=meta.content_sha256
        )

    @staticmethod
    def _source(s: SourceRecord) -> PackSource:
        return PackSource(
            source_ref=s.source_ref,
            kind=s.kind,
            title=s.title,
            author=s.author,
            edition=s.edition,
            ownership=s.ownership,
            reliability_tier=s.tier,
            reliability_score=s.score,
            collection_key=s.collection_key,
            external_url=s.external_url,
            accessed_at=s.accessed_at,
            fetch_status=s.fetch_status,
            content_sha256=s.content_sha256,
            snapshot_ref=s.snapshot_ref,
        )

    @staticmethod
    def _further_reading(
        data: AssemblyInput, evidence: list[EvidenceItem]
    ) -> tuple[FurtherReading, ...]:
        cited = {e.source_ref for e in evidence if e.usable_for_script}
        rows = [
            FurtherReading(
                source_ref=s.source_ref, title=s.title, author=s.author, edition=s.edition
            )
            for ref, s in sorted(data.sources.items())
            if ref in cited and s.credit_in_description and not ref.startswith("ext_")
        ]
        return tuple(rows)
