"""VideoDirector Protocol and the task's one entry point ``run(task_input, ctx)`` (blueprint 9).

03 section 1 rule 5 / CCR-203: ``ShotPlanTask.run`` is the only way in. It reads only what the Task
Input carries and references (the Agent 05 script document through a slice model, CCR-200; the
narration timeline; the brand kit; the previous and the parent plan), runs ``ShotPlanStep`` and
returns a Task Output. A domain failure, rejection or refusal is returned as a Task Output; only a
retryable infrastructure error propagates (the worker owns retry).
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import ValidationError

from agent_09_video_director.contracts import (
    TEMPLATE_ID_RE,
    BrandKit,
    BrandKitSlice,
    HashedRef,
    ScriptDocSlice,
    ShotPlan,
    ShotPlanInput,
    SliceModel,
    TimelineSlice,
)
from agent_09_video_director.direction.client import CallMeter
from agent_09_video_director.output import (
    AGENT_ID,
    ShotPlanDocument,
    build_document,
    build_task_output,
    check_ctx,
    error_output,
    plan_from_document,
)
from agent_09_video_director.persistence import persist_plan
from agent_09_video_director.problems import input_invalid
from agent_09_video_director.step import ShotPlanRequest, ShotPlanStep, Verification
from amw_core.contracts.error import violation
from amw_core.contracts.payloads import PAYLOAD_SCHEMAS, PayloadSchemaRegistry
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import TaskOutput
from amw_core.errors import (
    AgentError,
    BudgetExhaustedError,
    ConfigInvalidError,
    PermanentError,
    SchemaInvalidError,
    SchemaVersionUnsupportedError,
)
from amw_core.exec_context import ExecContext
from amw_core.interfaces.clock import Clock
from amw_core.interfaces.storage import BlobStorage, BlobUri
from amw_core.interfaces.tenancy_context import TenantContext

INPUT_SCHEMA = "agent_09.shot_plan.input"
SCRIPT_DOCUMENT_SCHEMA = "agent_05.script_document"
SCRIPT_DOCUMENT_SCHEMA_VERSION = "1.0.0"

_TEMPLATE_ID = re.compile(TEMPLATE_ID_RE)
_S = TypeVar("_S", bound=SliceModel)


@dataclass(frozen=True, slots=True)
class GateFacts:
    """Database facts of the script gate (F-03) that no hashed ref carries.

    Fail closed: a bare ``GateFacts()`` (a port that knows nothing) blocks the plan: the claim is
    treated as blocked and the status is ``UNKNOWN`` (refused by ``script_gate``)."""

    approval_approved: bool = False
    claim_blocked: bool = True
    script_status: str = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class RulePackText:
    text: str
    version: str


class PlanInputPorts(Protocol):
    """Reads that are not blob reads (entity rows, rule packs). Wired by ``workers/ai_worker``;
    every read is tenant-scoped by the tenant context it receives (provisional port, CCR-267)."""

    def brand_kit(self, tenant: TenantContext, ref: HashedRef) -> Mapping[str, Any]:
        """The current ``brand_kits`` row behind an ``amw-entity://`` ref, SHA-256 verified."""
        ...

    def gate_facts(
        self, tenant: TenantContext, *, script_id: str, script_version: int, approval_id: str | None
    ) -> GateFacts: ...

    def rule_pack(self, tenant: TenantContext, key: str) -> RulePackText: ...


class VideoDirector(Protocol):
    def run(self, task_input: TaskInput, ctx: ExecContext) -> TaskOutput: ...


class ShotPlanTask:
    """``agent_09.shot_plan``: read inputs, run the step, write the plan blob once, build the
    Task Output."""

    def __init__(
        self,
        step: ShotPlanStep,
        storage: BlobStorage,
        ports: PlanInputPorts,
        clock: Clock,
        *,
        worst_case_call_micros: int,
        schemas: PayloadSchemaRegistry = PAYLOAD_SCHEMAS,
    ) -> None:
        self._step, self._storage, self._ports, self._clock = step, storage, ports, clock
        self._schemas = schemas
        self._worst_case_call_micros = worst_case_call_micros

    # ------------------------------------------------------------------ entry point
    def run(self, task_input: TaskInput, ctx: ExecContext) -> TaskOutput:
        started = self._clock.monotonic_ms()
        meters: list[CallMeter] = []  # filled once the step may make paid calls
        try:
            return self._run(task_input, ctx, started, meters)
        except (PermanentError, AgentError, BudgetExhaustedError) as exc:
            return error_output(
                exc,
                task_input=task_input,
                now=self._clock.now(),
                duration_ms=max(0, self._clock.monotonic_ms() - started),
                meter=meters[0] if meters else None,
            )

    # ------------------------------------------------------------------ reading
    def _blob(self, ctx: ExecContext, ref: HashedRef) -> bytes:
        return b"".join(self._storage.get(ctx.tenant, BlobUri(ref.uri), ref.sha256))

    def _json(self, ctx: ExecContext, ref: HashedRef) -> Any:
        try:
            return json.loads(self._blob(ctx, ref))
        except ValueError:
            raise input_invalid("REF_NOT_JSON", path=ref.uri) from None

    def _slice(self, ctx: ExecContext, ref: HashedRef, model: type[_S], code: str) -> _S:
        try:
            return model.model_validate(self._json(ctx, ref))
        except ValidationError:
            raise input_invalid(code) from None

    def _script_slice(self, ctx: ExecContext, ref: HashedRef) -> ScriptDocSlice:
        """03 section 2.3 rule 2 (CCR-200): validate the producer's document against the producer's
        registered schema where one is shipped, then map it with the own slice model. When Agent 05
        has not registered ``agent_05.script_document`` the slice model's required fields are the
        only check (recorded as open in the README)."""
        doc = self._json(ctx, ref)
        if not isinstance(doc, dict):
            raise input_invalid("SCRIPT_DOCUMENT_INVALID")
        if SCRIPT_DOCUMENT_SCHEMA in self._schemas.names():
            try:
                self._schemas.validate(SCRIPT_DOCUMENT_SCHEMA, SCRIPT_DOCUMENT_SCHEMA_VERSION, doc)
            except SchemaInvalidError, SchemaVersionUnsupportedError:
                raise input_invalid("SCRIPT_SCHEMA_INVALID") from None
        try:
            return ScriptDocSlice.model_validate(doc)
        except ValidationError:
            raise input_invalid("SCRIPT_DOCUMENT_INVALID") from None

    def _payload(self, task_input: TaskInput, ctx: ExecContext) -> ShotPlanInput:
        if task_input.agent_id != AGENT_ID:
            raise input_invalid("AGENT_MISMATCH")
        payload = task_input.payload
        if payload.payload_schema != INPUT_SCHEMA:
            raise SchemaInvalidError("unexpected payload schema")
        if not payload.payload_schema_version.startswith("1."):
            raise SchemaVersionUnsupportedError("payload schema major is not supported")
        if payload.data is not None:
            doc: Any = payload.data
        else:
            assert payload.data_ref is not None  # noqa: S101
            assert payload.data_sha256 is not None  # noqa: S101
            doc = self._json(ctx, HashedRef(uri=payload.data_ref, sha256=payload.data_sha256))
        try:
            return ShotPlanInput.model_validate(doc)
        except ValidationError as exc:
            raise SchemaInvalidError(
                "shot plan input does not match the schema",
                details={
                    "violations": [
                        violation(e["type"], "/" + "/".join(str(p) for p in e["loc"]))
                        for e in exc.errors()[:50]
                    ]
                },
            ) from None

    def _brand(self, ctx: ExecContext, inp: ShotPlanInput) -> BrandKit:
        try:
            brand = BrandKitSlice.model_validate(
                self._ports.brand_kit(ctx.tenant, inp.brand_kit_ref)
            )
        except ValidationError:
            raise input_invalid("BRAND_KIT_INVALID") from None
        ids = (brand.intro_ref, brand.outro_ref, brand.lower_third_template_ref)
        if any(i is not None and not _TEMPLATE_ID.fullmatch(i) for i in ids):
            raise input_invalid("BRAND_TEMPLATE_ID")  # a template ID, never a URI (CCR-204)
        return brand.to_brand_kit()

    def _previous(self, ctx: ExecContext, ref: HashedRef | None) -> ShotPlan | None:
        if ref is None:
            return None
        try:
            return plan_from_document(ShotPlanDocument.model_validate(self._json(ctx, ref)))
        except ValidationError:
            raise input_invalid("PREVIOUS_PLAN_INVALID") from None

    def _parent_shots(
        self, ctx: ExecContext, ref: HashedRef | None
    ) -> Mapping[str, tuple[str, ...]] | None:
        """Parent segment ID -> parent shot IDs overlapping it (Shorts child job only)."""
        if ref is None:
            return None
        try:
            parent = ShotPlanDocument.model_validate(self._json(ctx, ref))
        except ValidationError:
            raise input_invalid("PARENT_PLAN_INVALID") from None
        out: dict[str, list[str]] = {}
        for shot in parent.shots:
            for seg in shot.segment_ids:
                out.setdefault(seg, []).append(shot.shot_id)
        return {k: tuple(v) for k, v in out.items()}

    # ------------------------------------------------------------------ the run
    def _run(
        self, task_input: TaskInput, ctx: ExecContext, started_ms: int, meters: list[CallMeter]
    ) -> TaskOutput:
        check_ctx(task_input, ctx)
        inp = self._payload(task_input, ctx)
        refs = [
            inp.script_ref,
            inp.verification_ref,
            inp.narration_timeline_ref,
            inp.brand_kit_ref,
            *(r for r in (inp.parent_plan_ref, inp.previous_plan_ref) if r is not None),
        ]
        script_slice = self._script_slice(ctx, inp.script_ref)
        if (script_slice.script_id, script_slice.version) != (
            inp.script_ref.script_id,
            inp.script_ref.version,
        ):
            raise input_invalid("SCRIPT_REF_MISMATCH")
        script = script_slice.to_script_doc()
        timeline = self._slice(
            ctx, inp.narration_timeline_ref, TimelineSlice, "TIMELINE_INVALID"
        ).to_timeline()
        brand = self._brand(ctx, inp)
        facts = self._ports.gate_facts(
            ctx.tenant,
            script_id=inp.script_ref.script_id,
            script_version=inp.script_ref.version,
            approval_id=inp.verification_ref.approval_id,
        )
        packs = {k: self._ports.rule_pack(ctx.tenant, k) for k in inp.active_rule_packs}
        budget = task_input.resource_budget
        if budget.max_llm_calls is None:
            raise ConfigInvalidError("resource_budget.max_llm_calls is required for this task")
        req = ShotPlanRequest(
            org_id=task_input.org_id,
            task_id=task_input.task_id,
            declared_orgs=(task_input.org_id, str(ctx.org_id)),
            uris=[*(r.uri for r in refs), *(r.uri for r in task_input.context_refs)],
            production_type_key=inp.production_type_key,
            aspect_ratio=inp.aspect_ratio,
            script=script,
            script_sha256=inp.script_ref.sha256,
            script_ref_sha256=inp.script_ref.sha256,
            verification=Verification(
                verified_script_sha256=inp.verification_ref.verified_script_sha256,
                stage_verdict=inp.verification_ref.stage_verdict,
                approval_approved=facts.approval_approved,
                claim_blocked=facts.claim_blocked,
                script_status=facts.script_status,
            ),
            timeline=timeline,
            timeline_sha256=inp.narration_timeline_ref.sha256,
            brand=brand,
            channel_category=inp.channel_category,
            banned_subjects=brand.banned_words,
            limits=inp.limits,
            rule_packs={k: v.text for k, v in packs.items()},
            rule_pack_versions={k: v.version for k, v in packs.items()},
            iteration=inp.iteration,
            previous_plan=self._previous(ctx, inp.previous_plan_ref),
            feedback=inp.revision_feedback,
            parent_shots=self._parent_shots(ctx, inp.parent_plan_ref),
            max_calls=budget.max_llm_calls,
            max_cost_micros=budget.max_cost_micros,
            worst_case_call_micros=self._worst_case_call_micros,
        )
        meter = CallMeter(req.max_calls, req.max_cost_micros, req.worst_case_call_micros)
        meters.append(meter)  # kept for the error output: paid calls before a failure
        result = self._step.run(req, meter=meter)
        doc = build_document(result.plan, script)
        ref = persist_plan(
            self._storage,
            ctx.tenant,
            doc,
            job_id=ctx.job_id,
            task_id=ctx.task_id,
            attempt_id=ctx.attempt_id,
        )
        return build_task_output(
            result,
            doc,
            ref,
            now=self._clock.now(),
            duration_ms=max(0, self._clock.monotonic_ms() - started_ms),
            currency=budget.currency,
        )
