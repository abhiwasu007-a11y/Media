"""Step input and output models of the four LLM steps (= the prompt files' schemas, 1.0.0).

Local IDs only (``i01``, ``p01``, ``s01``, ``f01``, ``b01``); no IDs, paths, tenant strings or keys
reach a prompt (section 5 rule 3). Every output carries the 27 section 4.3 ``refusal`` object.
"""

from typing import Literal

from pydantic import Field

from agent_16_compliance_qa.base import Model
from amw_core.enums import DataAgeVsLag

RULE_ID = r"^[A-Z]{2,8}-R[0-9]{1,3}$"
RefusalReasonV = Literal[
    "INSUFFICIENT_INPUT",
    "RULE_WOULD_BE_BROKEN",
    "OUT_OF_SCOPE",
    "CONFLICTING_INSTRUCTIONS",
    "UNSAFE_CONTENT",
]
Surface = Literal["SCRIPT_SEGMENT", "ON_SCREEN_TEXT", "THUMBNAIL_TEXT", "TITLE", "DESCRIPTION"]


class Refusal(Model):
    reason: RefusalReasonV
    message: str = Field(max_length=1000)
    missing_inputs: tuple[str, ...]
    violated_rule_ids: tuple[str, ...]


# --- policy (compliance_gate.v1) -----------------------------------------------------------
class ItemClaim(Model):
    claim_type: str
    time_reference_kind: str
    rule_flags: tuple[str, ...]


class ItemChart(Model):
    chart_kind: str
    instrument: str | None
    data_age_vs_lag: DataAgeVsLag | None


class PolicyItem(Model):
    item_id: str = Field(pattern=r"^i[0-9]{2,3}$")
    surface: Surface
    text: str
    context_before: str
    context_after: str
    named_instruments: tuple[str, ...]
    claims: tuple[ItemClaim, ...]
    chart: ItemChart | None
    rules_to_check: tuple[str, ...]


class PolicyInput(Model):
    channel_category: str
    owner_sebi_registration: Literal["UNREGISTERED"]
    language: str
    active_rule_ids: tuple[str, ...]
    items: tuple[PolicyItem, ...]


class PolicyFinding(Model):
    item_id: str = Field(pattern=r"^i[0-9]{2,3}$")
    rule_id: str = Field(pattern=RULE_ID)
    finding: Literal["VIOLATION", "NO_VIOLATION", "UNCERTAIN"]
    quote: str | None = Field(max_length=400)
    rationale: str = Field(max_length=400)


class FrameTest(Model):
    item_id: str = Field(pattern=r"^i[0-9]{2,3}$")
    past_tense_frame: bool
    teaches_concept: bool
    leaves_expectation: bool


class PolicyOutput(Model):
    findings: tuple[PolicyFinding, ...]
    frame_tests: tuple[FrameTest, ...]
    injection_suspected: tuple[str, ...]
    refusal: Refusal | None


# --- paraphrase (compliance_gate_paraphrase.v1) --------------------------------------------
class Passage(Model):
    passage_id: str = Field(pattern=r"^s[0-9]{2,3}$")
    language: str
    text: str


class ParaphrasePair(Model):
    pair_id: str = Field(pattern=r"^p[0-9]{2,3}$")
    script_span: str
    passages: tuple[Passage, ...]
    attribution_present: bool


class ParaphraseInput(Model):
    language_script: str
    pairs: tuple[ParaphrasePair, ...]


class ParaphraseResult(Model):
    pair_id: str = Field(pattern=r"^p[0-9]{2,3}$")
    decision: Literal["OWN_WORDS", "CLOSE_PARAPHRASE", "UNCERTAIN"]
    same_structure: bool
    same_examples: bool
    same_sequence: bool
    surface_change_only: bool
    is_quotation: bool
    closest_passage_id: str | None
    rationale: str = Field(max_length=400)


class ParaphraseOutput(Model):
    results: tuple[ParaphraseResult, ...]
    injection_suspected: tuple[str, ...]
    refusal: Refusal | None


# --- frames (compliance_gate_frames.v1) ----------------------------------------------------
FrameCheckId = Literal["qc.watermark.visual", "qc.visual.no_synthetic_presenter"]
FrameFindingV = Literal[
    "WATERMARK_PRESENT", "PRESENTER_PRESENT", "NONE_FOUND", "UNCERTAIN", "NOT_EVALUATED"
]


class FrameFinding(Model):
    check_id: FrameCheckId
    finding: FrameFindingV
    frame_ids: tuple[str, ...]
    rationale: str = Field(max_length=400)


class FramesOutput(Model):
    findings: tuple[FrameFinding, ...]
    injection_suspected: tuple[str, ...]
    refusal: Refusal | None


# --- quality judge (quality_score.v1) ------------------------------------------------------
class JudgeScore(Model):
    criterion_id: str = Field(pattern=r"^[a-z]{2}\.j\.[a-z_]{3,40}$")
    points: int = Field(ge=0)
    max_points: int = Field(ge=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    why_not_higher: str = Field(max_length=400)


class CheckElement(Model):
    element_id: str = Field(pattern=r"^(hook|title|thumbnail_[0-9]{1,2}|b[0-9]{2})$")
    score: int = Field(ge=0, le=2)


class JudgedCheck(Model):
    check_id: Literal["edit.promise_alignment", "edit.hook.beat_content"]
    elements: tuple[CheckElement, ...] = Field(min_length=1)
    absent_content_elements: tuple[str, ...]
    rationale: str = Field(max_length=400)


class QualityOutput(Model):
    group_id: Literal["G1", "G2", "G3"]
    scores: tuple[JudgeScore, ...]
    check_results: tuple[JudgedCheck, ...]
    injection_suspected: tuple[str, ...]
    refusal: Refusal | None
