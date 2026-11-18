"""S1: ConceptPlanner (LLM step 1) and PlanValidator PL3 to PL11 (blueprint 10.2, prompt plan)."""

from dataclasses import dataclass

from agent_04_research_knowledge.errors import (
    InputInvalid,
    InsufficientInput,
    OutputSchemaInvalid,
    TopicBlocked,
    TopicNeedsReview,
)
from agent_04_research_knowledge.llm import StructuredLlmCaller
from agent_04_research_knowledge.models.common import Refusal
from agent_04_research_knowledge.models.enums import ConceptKind, ConceptTimeReference
from agent_04_research_knowledge.models.plan import ResearchPlan, ResearchPlanInput
from agent_04_research_knowledge.patterns import has_url_or_referral
from agent_04_research_knowledge.prompts import (
    PLAN_PROMPT_ID,
    PromptLoader,
    build_user_message,
)
from agent_04_research_knowledge.runtime import RunInfo
from agent_04_research_knowledge.settings import StepLlm
from amw_core.enums import RefusalReason, VideoKind

STEP_KEY = "S1_plan"


@dataclass(frozen=True, slots=True)
class Violation:
    check: str
    detail: str


def _primary(tag: str) -> str:
    return tag.split("-", 1)[0].lower()


class PlanValidator:
    """Deterministic post-checks PL3 to PL11 (+ P9 collection keys) on the parsed plan."""

    def validate(self, plan: ResearchPlan, data: ResearchPlanInput) -> list[Violation]:
        out: list[Violation] = []
        refusal = plan.refusal
        if refusal is not None:
            if plan.concepts:  # PL10
                out.append(Violation("PL10", "a refusal needs an empty concept list"))
            return out
        if not plan.concepts:
            return [Violation("PL5", "no concept and no refusal")]
        out.extend(self._concepts(plan, data))
        return out

    @staticmethod
    def _concepts(plan: ResearchPlan, data: ResearchPlanInput) -> list[Violation]:
        out: list[Violation] = []
        ids = [c.concept_id for c in plan.concepts]
        if ids != [f"c{i:02d}" for i in range(1, len(ids) + 1)]:
            out.append(Violation("PL4", "concept ids must be c01, c02, ... in order"))
        if len(ids) > data.max_concepts:
            out.append(Violation("PL5", "too many concepts"))
        languages = {_primary(x) for x in (*data.library_languages, data.video_language)}
        allowed_keys = {c.collection_key for c in data.collections}
        input_gaps = {g.gap_id for g in data.revision_gaps}
        closed: set[str] = set()
        for c in plan.concepts:
            if len(c.queries) > data.max_queries_per_concept:
                out.append(Violation("PL5", f"{c.concept_id}: too many queries"))
            if c.time_reference is ConceptTimeReference.CURRENT and c.kind not in (
                ConceptKind.REGULATORY_CONTEXT,
                ConceptKind.DEFINITION_TERM,
            ):
                out.append(Violation("PL6", f"{c.concept_id}: CURRENT only for rules and terms"))
            if c.wants_method_material and data.video_kind is not VideoKind.METHOD_TOPIC:
                out.append(Violation("PL7", f"{c.concept_id}: method material on a general topic"))
            texts = [c.label, c.label_en, *(q.text for q in c.queries)]
            if any(has_url_or_referral(t) for t in texts):
                out.append(Violation("PL8", f"{c.concept_id}: URL, e-mail or referral pattern"))
            for gap_id in c.closes_gap_ids:
                if gap_id not in input_gaps:
                    out.append(Violation("PL9", f"{c.concept_id}: unknown gap {gap_id}"))
            closed.update(c.closes_gap_ids)
            for q in c.queries:
                if _primary(q.language) not in languages:
                    out.append(Violation("PL11", f"{c.concept_id}: query language {q.language}"))
            if any(k not in allowed_keys for k in c.target_collection_keys):
                out.append(Violation("P9", f"{c.concept_id}: collection key not in the input"))
        if input_gaps - closed and not plan.out_of_scope_notes:
            out.append(Violation("PL9", "input gaps neither closed nor explained"))
        return out


def refusal_to_outcome(refusal: Refusal) -> None:
    """27 section 4.3 mapping of a plan refusal (blueprint 18). Always raises."""
    rules = tuple(refusal.violated_rule_ids)
    match refusal.reason:
        case RefusalReason.RULE_WOULD_BE_BROKEN:
            raise TopicBlocked(rules)
        case RefusalReason.UNSAFE_CONTENT:
            raise TopicNeedsReview(rules)
        case RefusalReason.INSUFFICIENT_INPUT:
            raise InsufficientInput(
                "the topic has no researchable subject", details={"missing": refusal.missing_inputs}
            )
        case _:  # OUT_OF_SCOPE, CONFLICTING_INSTRUCTIONS
            raise InputInvalid(
                "the topic cannot be planned", details={"reason": refusal.reason.value}
            )


class ConceptPlanner:
    def __init__(self, caller: StructuredLlmCaller, prompts: PromptLoader, step: StepLlm) -> None:
        self._caller, self._prompts, self._step = caller, prompts, step
        self._validator = PlanValidator()

    def plan(self, run: RunInfo, plan_input: ResearchPlanInput) -> ResearchPlan:
        """One call, one repair on a failed PL check, then ``OUTPUT_SCHEMA_INVALID``.

        Raises ``TopicBlocked`` / ``TopicNeedsReview`` (successes with a verdict) and the typed
        errors of 27 section 4.3; a returned plan has passed PL3 to PL11.
        """
        rendered = self._prompts.render(
            self._prompts.load(PLAN_PROMPT_ID), tuple(plan_input.active_rule_packs)
        )
        user = build_user_message(rendered, plan_input)
        result = self._caller.call(
            run,
            self._step,
            STEP_KEY,
            rendered.system,
            user,
            ResearchPlan,
            language=plan_input.video_language,
        )
        plan = result.value
        violations = self._validator.validate(plan, plan_input)
        if violations:
            run.log.warning("research.plan_invalid", checks=[v.check for v in violations])
            hint = "; ".join(f"{v.check}: {v.detail}" for v in violations[:20])
            repair = self._caller.call(
                run,
                self._step,
                STEP_KEY,
                rendered.system,
                f"{user}\n\n<validation_error>\nYour plan failed checks: {hint}. "
                "Return one corrected JSON object only.\n</validation_error>",
                ResearchPlan,
                repairs=0,
                language=plan_input.video_language,
                seq_start=result.last_seq + 1,
            )
            plan = repair.value
            violations = self._validator.validate(plan, plan_input)
            if violations:
                raise OutputSchemaInvalid(
                    "plan failed the deterministic checks after the repair",
                    details={"checks": [v.check for v in violations]},
                )
        if plan.refusal is not None:
            refusal_to_outcome(plan.refusal)
        return plan
