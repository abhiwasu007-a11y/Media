"""``agent_04.research_pack.notes.input`` / ``.output`` 1.0.0 (prompt research_pack_notes.v1)."""

from typing import Annotated

from pydantic import Field, StringConstraints

from agent_04_research_knowledge.models.common import (
    ChannelCategory,
    ConceptId,
    Refusal,
    RulePackKeyStr,
)
from agent_04_research_knowledge.models.enums import (
    Clarity,
    ConceptKind,
    ExcludedReason,
    NoteProblem,
    Relevance,
    ReliabilityTier,
    StatementKind,
)
from amw_core.contracts.common import AmwModel
from amw_core.enums import TimeReferenceKind

NOTES_INPUT_SCHEMA = "agent_04.research_pack.notes.input"
NOTES_OUTPUT_SCHEMA = "agent_04.research_pack.notes.output"

PassageId = Annotated[str, StringConstraints(pattern=r"^p[0-9]{1,3}$")]
NoteRef = Annotated[str, StringConstraints(pattern=r"^n[0-9]{1,3}$")]


class NotesConcept(AmwModel):
    concept_id: ConceptId
    label_en: Annotated[str, StringConstraints(max_length=120)]
    kind: ConceptKind
    evidence_needs: tuple[str, ...]


class NotesPassage(AmwModel):
    passage_id: PassageId
    language: str
    reliability_tier: ReliabilityTier
    text: Annotated[str, StringConstraints(min_length=1, max_length=12000)]


class RepairItem(AmwModel):
    note_ref: str
    passage_id: str
    problem: NoteProblem


class EvidenceNotesInput(AmwModel):
    concept: NotesConcept
    channel_category: ChannelCategory
    active_rule_packs: Annotated[tuple[RulePackKeyStr, ...], Field(min_length=1)]
    passages: Annotated[tuple[NotesPassage, ...], Field(max_length=64)]
    max_note_chars: Annotated[int, Field(ge=50, le=600)]
    max_notes_per_passage: Annotated[int, Field(ge=1, le=10)]
    max_verbatim_words: Annotated[int, Field(ge=3, le=20)]
    repair_feedback: Annotated[tuple[RepairItem, ...], Field(max_length=64)]


class Assessment(AmwModel):
    passage_id: PassageId
    relevance: Relevance
    reason: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class NoteCandidate(AmwModel):
    note_ref: NoteRef
    passage_id: PassageId
    statement_kind: StatementKind
    note: Annotated[str, StringConstraints(min_length=3, max_length=600)]
    time_reference_kind: TimeReferenceKind
    instruments: tuple[Annotated[str, StringConstraints(max_length=100)], ...]
    numbers_in_note: tuple[Annotated[str, StringConstraints(max_length=32)], ...]
    clarity: Clarity
    forward_looking: bool


class ExcludedStatement(AmwModel):
    passage_id: PassageId
    reason: ExcludedReason


class EvidenceNotes(AmwModel):
    assessments: Annotated[tuple[Assessment, ...], Field(max_length=64)]
    notes: Annotated[tuple[NoteCandidate, ...], Field(max_length=128)]
    excluded_statements: Annotated[tuple[ExcludedStatement, ...], Field(max_length=64)]
    refusal: Refusal | None
