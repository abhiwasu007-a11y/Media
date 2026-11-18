"""S4: EvidenceNoter (LLM step 2), NoteValidator NT4 to NT10 and the batch repair (blueprint 10.6).

The model proposes notes in original words; code decides. A note is dropped, never kept, when it
copies its passage, carries a number the passage does not, holds a URL, a referral or a quotation,
or is ambiguous. A note with a future reference or a forward-looking flag is stored but is not
usable for the script (FIN-R3, FIN-R13). The model never sets reliability, release or usability.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from agent_04_research_knowledge.guards.copy_guard import (
    CROSS_LANGUAGE,
    CopyGuard,
    CopyResult,
    CopyThresholds,
)
from agent_04_research_knowledge.guards.text_match import dominant_script
from agent_04_research_knowledge.llm import StructuredLlmCaller
from agent_04_research_knowledge.models.common import Refusal
from agent_04_research_knowledge.models.enums import (
    Clarity,
    CopyGuardStatus,
    ExclusionReason,
    NoteProblem,
    Relevance,
    ReliabilityTier,
)
from agent_04_research_knowledge.models.notes import (
    EvidenceNotes,
    EvidenceNotesInput,
    NoteCandidate,
    NotesConcept,
    NotesPassage,
    RepairItem,
)
from agent_04_research_knowledge.models.plan import PlannedConcept
from agent_04_research_knowledge.patterns import has_quote_span, has_url_or_referral, numbers_in
from agent_04_research_knowledge.prompts import NOTES_PROMPT_ID, PromptLoader, build_user_message
from agent_04_research_knowledge.runtime import RunInfo
from agent_04_research_knowledge.settings import CopyGuardSettings, NotesSettings, StepLlm
from amw_core.enums import TimeReferenceKind

NOTE_SCRIPT = "LATIN"
"""Notes are written in English (prompt rule 2); their script must be Latin."""


@dataclass(frozen=True, slots=True)
class NoteLimits:
    max_note_chars: int
    copy: CopyThresholds
    max_pack_source_coverage: float

    @classmethod
    def from_settings(cls, notes: NotesSettings, guard: CopyGuardSettings) -> NoteLimits:
        return cls(notes.max_note_chars, guard.thresholds(), guard.max_pack_source_coverage)

    @property
    def max_verbatim_words(self) -> int:
        return self.copy.max_verbatim_words


@dataclass(frozen=True, slots=True)
class NoteVerdict:
    passed: bool
    problem: NoteProblem | None
    usable: bool
    exclusion_reason: ExclusionReason | None
    copy: CopyResult | None

    @property
    def copy_guard_status(self) -> CopyGuardStatus:
        skipped = self.copy is not None and self.copy.skipped_reason == CROSS_LANGUAGE
        return CopyGuardStatus.SKIPPED_CROSS_LANGUAGE if skipped else CopyGuardStatus.PASSED


class NoteValidator:
    """Pure: NT6 copy guard (cited passage AND the whole retrieval set), NT7 length and script,
    NT8 number match and URL/quote, NT9 forward-looking."""

    def __init__(self, guard: CopyGuard | None = None) -> None:
        self._guard = guard or CopyGuard()

    def validate(
        self,
        note: NoteCandidate,
        passage_text: str,
        limits: NoteLimits,
        pool: Sequence[str] = (),
    ) -> NoteVerdict:
        """``pool``: every passage text of the job's retrieval set; a note that copies any of
        them fails, whichever passage it cites."""
        text = note.note
        problem: NoteProblem | None = None
        copy: CopyResult | None = None
        if has_url_or_referral(text) or has_quote_span(text):
            problem = NoteProblem.URL_OR_QUOTE
        else:
            cited = self._guard.check(text, passage_text, limits.copy)
            others = self._guard.check_pool(text, pool, limits.copy)
            copy = (
                cited if cited.passed and others.passed else (cited if not cited.passed else others)
            )
            if not (cited.passed and others.passed):
                problem = NoteProblem.COPY_OVERLAP
            elif not numbers_in(text) <= numbers_in(passage_text) or not (
                {n.replace(",", "").rstrip("%") for n in note.numbers_in_note}
                <= numbers_in(passage_text)
            ):
                problem = NoteProblem.NUMBER_NOT_IN_PASSAGE
            elif (
                note.clarity is Clarity.AMBIGUOUS
                or len(text) > limits.max_note_chars
                or dominant_script(text) not in (None, NOTE_SCRIPT)
            ):
                # NT7: a note over the cap, or not in the note language's script (notes are
                # English, prompt rule 2), is not acceptable; the repair-feedback enum is closed,
                # so it is reported as AMBIGUOUS.
                problem = NoteProblem.AMBIGUOUS
        if problem is not None:
            return NoteVerdict(False, problem, False, None, copy)
        forward = note.forward_looking or note.time_reference_kind is TimeReferenceKind.FUTURE
        return NoteVerdict(
            True, None, not forward, ExclusionReason.FORWARD_LOOKING if forward else None, copy
        )


@dataclass(frozen=True, slots=True)
class PassageSource:
    """A passage with the identity the pack needs (code-side; the model sees only id and text)."""

    passage_id: str
    text: str
    language: str
    tier: ReliabilityTier
    citation_ref: str
    source_ref: str
    method_labelled: bool
    owner_authored: bool
    chapter: str | None
    page_from: int | None
    page_to: int | None

    def __repr__(self) -> str:
        return f"PassageSource({self.passage_id}, {self.citation_ref})"


@dataclass(frozen=True, slots=True)
class ValidatedNote:
    note_ref: str
    passage: PassageSource
    note: NoteCandidate
    usable: bool
    exclusion_reason: ExclusionReason | None
    copy_guard: CopyGuardStatus
    copy: CopyResult | None = None


@dataclass(frozen=True, slots=True)
class DroppedNote:
    note_ref: str
    passage_id: str
    problem: NoteProblem


@dataclass
class NotesResult:
    concept_id: str
    notes: list[ValidatedNote] = field(default_factory=list)
    dropped: list[DroppedNote] = field(default_factory=list)
    excluded_forward_looking: int = 0
    injection_passages: list[str] = field(default_factory=list)
    unassessed: bool = False
    refusal: Refusal | None = None
    repaired: bool = False


class EvidenceNoter:
    def __init__(
        self,
        caller: StructuredLlmCaller,
        prompts: PromptLoader,
        step: StepLlm,
        settings: NotesSettings,
        limits: NoteLimits,
        validator: NoteValidator | None = None,
    ) -> None:
        self._caller, self._prompts, self._step = caller, prompts, step
        self._settings, self._limits = settings, limits
        self._validator = validator or NoteValidator()

    def _input(
        self,
        concept: PlannedConcept,
        channel_category: str,
        rule_packs: tuple[str, ...],
        passages: list[PassageSource],
        repair: list[RepairItem],
    ) -> EvidenceNotesInput:
        return EvidenceNotesInput(
            concept=NotesConcept(
                concept_id=concept.concept_id,
                label_en=concept.label_en,
                kind=concept.kind,
                evidence_needs=tuple(n.value for n in concept.evidence_needs),
            ),
            channel_category=channel_category,
            active_rule_packs=rule_packs,
            passages=tuple(
                NotesPassage(
                    passage_id=p.passage_id,
                    language=p.language,
                    reliability_tier=p.tier,
                    text=p.text,
                )
                for p in passages
            ),
            max_note_chars=self._limits.max_note_chars,
            max_notes_per_passage=self._settings.max_notes_per_passage,
            max_verbatim_words=self._limits.max_verbatim_words,
            repair_feedback=tuple(repair),
        )

    def note(
        self,
        run: RunInfo,
        concept: PlannedConcept,
        passages: list[PassageSource],
        step_key: str,
        channel_category: str,
        rule_packs: tuple[str, ...],
        pool: Sequence[str] = (),
    ) -> NotesResult:
        result = NotesResult(concept.concept_id)
        rendered = self._prompts.render(self._prompts.load(NOTES_PROMPT_ID), rule_packs)
        base = self._input(concept, channel_category, rule_packs, passages, [])
        first = self._caller.call(
            run,
            self._step,
            step_key,
            rendered.system,
            build_user_message(rendered, base),
            EvidenceNotes,
            repairs=1,
        )
        output = first.value
        if output.refusal is not None:
            result.refusal = output.refusal
            return result
        by_id = {p.passage_id: p for p in passages}
        assessed = [a.passage_id for a in output.assessments]
        if sorted(assessed) != sorted(by_id) or len({*assessed}) != len(assessed):
            result.unassessed = True  # NT5: not exactly one assessment per input passage
            run.log.warning("research.notes_unassessed", concept_id=concept.concept_id)
        relevance = {a.passage_id: a.relevance for a in output.assessments if a.passage_id in by_id}
        for pid, rel in sorted(relevance.items()):
            if rel is Relevance.INJECTION_SUSPECTED:
                result.injection_passages.append(pid)
                run.log.warning("research.injection_suspected", passage_id=pid)
                run.audit.record(
                    "research.injection_suspected", "passage", by_id[pid].citation_ref, {}
                )
        result.excluded_forward_looking = sum(
            1 for e in output.excluded_statements if e.passage_id in by_id
        )
        accepted, failing = self._check(output.notes, by_id, relevance, result, pool)
        if failing and self._settings.max_repair_rounds > 0:
            repair_items = [
                RepairItem(note_ref=n, passage_id=p, problem=pr) for n, p, pr in failing
            ]
            repaired = self._caller.call(
                run,
                self._step,
                step_key,
                rendered.system,
                build_user_message(
                    rendered,
                    self._input(concept, channel_category, rule_packs, passages, repair_items),
                ),
                EvidenceNotes,
                repairs=0,
                seq_start=first.last_seq + 1,
            )
            result.repaired = True
            wanted = {n for n, _, _ in failing}
            retry = tuple(n for n in repaired.value.notes if n.note_ref in wanted)
            more, failing = self._check(retry, by_id, relevance, result, pool)
            accepted.extend(more)
        for note_ref, passage_id, problem in failing:
            result.dropped.append(DroppedNote(note_ref, passage_id, problem))
            run.log.info(
                "research.note_dropped",
                note_ref=note_ref,
                passage_id=passage_id,
                problem=problem.value,
            )
        result.notes = sorted(accepted, key=lambda v: v.note_ref)
        return result

    def _check(
        self,
        notes: tuple[NoteCandidate, ...],
        by_id: dict[str, PassageSource],
        relevance: dict[str, Relevance],
        result: NotesResult,
        pool: Sequence[str] = (),
    ) -> tuple[list[ValidatedNote], list[tuple[str, str, NoteProblem]]]:
        accepted: list[ValidatedNote] = []
        failing: list[tuple[str, str, NoteProblem]] = []
        per_passage: dict[str, int] = {}
        for cand in notes:
            passage = by_id.get(cand.passage_id)
            if passage is None:
                continue  # NT5: a note citing an unknown passage is dropped without repair
            if relevance.get(cand.passage_id) is not Relevance.RELEVANT:
                continue  # NT10 and rule 2: notes only from RELEVANT passages
            if per_passage.get(cand.passage_id, 0) >= self._settings.max_notes_per_passage:
                continue
            verdict = self._validator.validate(cand, passage.text, self._limits, pool)
            if not verdict.passed:
                problem = verdict.problem or NoteProblem.AMBIGUOUS
                failing.append((cand.note_ref, cand.passage_id, problem))
                continue
            per_passage[cand.passage_id] = per_passage.get(cand.passage_id, 0) + 1
            accepted.append(
                ValidatedNote(
                    cand.note_ref,
                    passage,
                    cand,
                    verdict.usable,
                    verdict.exclusion_reason,
                    verdict.copy_guard_status,
                    verdict.copy,
                )
            )
        return accepted, failing
