"""``ConceptBriefMapper`` (blueprint 7.4, 10.1): research pack to concept briefs.

The model never sees chunk text or another tenant's data: a brief holds the pack's own-words notes,
the exact ``citation_ref`` strings and the method release status looked up in the task's org.
``ResearchPackView`` is a tolerant reader of the Agent 04 pack (the fields this stage consumes);
it is not a second definition of the pack contract.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from agent_05_scriptwriter.contracts import AvailableCitation, ConceptBrief

SUMMARY_MAX = 600


class _View(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class PackConcept(_View):
    concept_id: str
    label: str
    label_en: str
    coverage: str


class PackEvidence(_View):
    evidence_id: str
    concept_id: str
    citation_ref: str
    note: str
    usable_for_script: bool
    method_labelled: bool
    exclusion_reason: str | None = None


class PackCitation(_View):
    citation_ref: str
    kind: str
    title: str


class PackMethod(_View):
    used: bool
    release_approval_ids: list[str]


class PackTerm(_View):
    term: str
    term_en: str
    glossary_term_id: str


class TopicVerdict(_View):
    verdict: str
    violated_rule_ids: list[str] = []


class ResearchPackView(_View):
    topic_verdict: TopicVerdict | None = None
    concepts: list[PackConcept]
    evidence: list[PackEvidence]
    citations_available: list[PackCitation] = []
    method: PackMethod
    terminology: list[PackTerm] = []


@dataclass(frozen=True, slots=True)
class ApprovalView:
    """A ``KNOWLEDGE_RELEASE`` lookup row; ``same_org`` is false for a foreign row."""

    id: str
    kind: str
    state: str
    same_org: bool


@dataclass(frozen=True, slots=True)
class BriefSet:
    briefs: list[ConceptBrief]
    available_citations: list[AvailableCitation]
    concept_map: dict[str, str]
    """step-local ``k<n>`` to pack ``c<nn>`` (stored in the checkpoint, reversed on output)."""


def local_id(pack_concept_id: str) -> str:
    return "k" + str(int(pack_concept_id[1:]))


def _summary(notes: Sequence[str]) -> str:
    out = ""
    for note in notes:
        candidate = f"{out} {note}" if out else note
        if len(candidate) > SUMMARY_MAX:
            if not out:
                return note[:SUMMARY_MAX]
            break
        out = candidate
    return out


def released(method: PackMethod, approvals: Sequence[ApprovalView]) -> bool:
    ids = set(method.release_approval_ids)
    return any(
        a.id in ids and a.kind == "KNOWLEDGE_RELEASE" and a.state == "APPROVED" and a.same_org
        for a in approvals
    )


def map_briefs(pack: ResearchPackView, approvals: Sequence[ApprovalView]) -> BriefSet:
    is_released = released(pack.method, approvals)
    glossary = {(t.term, t.term_en): t.glossary_term_id for t in pack.terminology}
    briefs: list[ConceptBrief] = []
    for concept in pack.concepts:
        usable = [
            e for e in pack.evidence if e.concept_id == concept.concept_id and e.usable_for_script
        ]
        refs = list(dict.fromkeys(e.citation_ref for e in usable))
        method_content = any(e.method_labelled for e in usable)
        k = local_id(concept.concept_id)
        briefs.append(
            ConceptBrief(
                concept_id=k,
                term_local=concept.label,
                term_en=concept.label_en,
                glossary_term_id=glossary.get((concept.label, concept.label_en), f"g_{k}"),
                summary=_summary([e.note for e in usable]),
                citation_refs=refs,
                method_content=method_content,
                release_status=(
                    "NOT_APPLICABLE"
                    if not method_content
                    else ("RELEASED" if is_released else "NOT_RELEASED")
                ),
            )
        )
    used = {ref for b in briefs for ref in b.citation_refs}
    citations = [
        AvailableCitation(
            citation_ref=c.citation_ref,
            kind=c.kind,  # type: ignore[arg-type]
            title=c.title[:300],
        )
        for c in pack.citations_available
        if c.citation_ref in used
    ]
    return BriefSet(
        briefs, citations, {local_id(c.concept_id): c.concept_id for c in pack.concepts}
    )
