"""QualityScoreStage (``agent_16.quality_score``, gate ``s16_score``; F-18 to F-20; CCR-203,
CCR-209; blueprint sections 7.4, 8.4, 15.1b).

The entry point ``run(task_input, ctx)`` reads the section 7.4 documents through hash-verified
storage, extracts the deterministic facts of 15.1b (``DocumentScoreFactExtractor``: no
constants; an absent source scores the criterion 0 with a finding, never full points), asks the
three judge groups through ``GroupRequestBuilder`` (the judge payloads of
``quality_score.v1``), aggregates with ``QualityScorer``, writes one machine ``quality_scores``
row per dimension, the ``qc_results`` of the ``gate: true`` results and the write-once report
artifact, and returns the Task Output. Failures are returned, never raised.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol

from pydantic import Field, ValidationError

from agent_16_compliance_qa.assembler import BlobRefIn, RenderHashReader, verify_frames
from agent_16_compliance_qa.base import Model
from agent_16_compliance_qa.config import Agent16Config
from agent_16_compliance_qa.entry import Spend, put_artifact_once, run_guarded
from agent_16_compliance_qa.inputs.extractors import (
    DocumentScoreFactExtractor,
    FactRowReader,
    ReadScope,
    is_sensitive,
)
from agent_16_compliance_qa.judge.client import (
    Breaker,
    CallMeter,
    CallScope,
    JudgeClient,
    system_prompt,
)
from agent_16_compliance_qa.judge.models import QualityOutput
from agent_16_compliance_qa.output import BlobRef, Usage, build_task_output, integrity
from agent_16_compliance_qa.quality import GroupRequest, QualityScorer, ScoreResult, score_payload
from agent_16_compliance_qa.scoring.rubric import RUBRIC_VERSION, Group
from amw_adapters.llm.protocol import LlmAdapter
from amw_core.contracts.common import storage_uri_owner
from amw_core.contracts.error import violation
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import TaskOutput, ValidationResult
from amw_core.enums import ActorKind, ComplianceVerdict
from amw_core.errors import (
    ConfigInvalidError,
    CrossTenantRefError,
    InputInvalidError,
    MissingDependencyError,
    SchemaInvalidError,
)
from amw_core.exec_context import ExecContext
from amw_core.ids import (
    ActorRef,
    AttemptId,
    CorrelationId,
    IdempotencyKey,
    IdempotencyScope,
    JobId,
    TaskId,
    make_idempotency_key,
)
from amw_core.interfaces.audit_log import AuditLog, NewAuditEntry
from amw_core.interfaces.budget_guard import BudgetGuard
from amw_core.interfaces.clock import Clock
from amw_core.interfaces.cost_ledger import CostLedger
from amw_core.interfaces.storage import BlobStorage, BlobUri
from amw_core.interfaces.tenancy_context import TenancyContext, TenantTransaction
from amw_core.tenancy.storage_paths import task_artifact_uri

_LOG = logging.getLogger(__name__)
AGENT_ID: Final = "agent_16"
QUALITY_INPUT: Final = "agent_16.quality_score.input"
QUALITY_OUTPUT: Final = "agent_16.quality_score.output"
_SHA = r"^[0-9a-f]{64}$"
_STAGE = r"^[a-z0-9_]{2,32}$"


class ScoreSubject(Model):
    render_id: str = Field(pattern=r"^rnd_")
    render_sha256: str = Field(pattern=_SHA)
    script_id: str = Field(pattern=r"^scr_")
    script_sha256: str = Field(pattern=_SHA)


class ScoreRouting(Model):
    script_stage_id: str = Field(pattern=_STAGE)
    plan_stage_id: str = Field(pattern=_STAGE)
    voice_stage_id: str = Field(pattern=_STAGE)
    render_stage_id: str = Field(pattern=_STAGE)
    thumbnails_stage_id: str | None = Field(pattern=_STAGE)


class ScoreRefs(Model):
    script_ref: BlobRefIn
    claims_ref: BlobRefIn
    verification_ref: BlobRefIn
    research_pack_ref: BlobRefIn
    render_qc_ref: BlobRefIn
    shot_plan_ref: BlobRefIn
    thumbnails_ref: BlobRefIn
    gate_output_ref: BlobRefIn
    frames_ref: BlobRefIn
    metadata_ref: BlobRefIn | None = None


class QualityScoreInput(Model):
    """``agent_16.quality_score.input`` 1.0.0 (section 7.4)."""

    subject: ScoreSubject
    iteration: int = Field(ge=0)
    rubric_version: str = Field(pattern=r"^rubric\.v[0-9]+$")
    language: str = Field(min_length=2)
    audience_level: str | None = None
    routing: ScoreRouting
    inputs: ScoreRefs


@dataclass(frozen=True, slots=True)
class NewScoreRow:
    """One machine ``quality_scores`` row (04 section 5.17): a dimension of the render."""

    job_id: str
    task_id: str
    render_id: str
    render_sha256: str
    dimension: str
    max_points: int
    points: float
    scorer_kind: str
    evidence: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class NewScoreQcRow:
    job_id: str
    task_id: str
    render_id: str
    result: ValidationResult


class ScoreStore(Protocol):
    """``amw_app`` writes (RLS + explicit ``org_id``); idempotent per key (``db.output``)."""

    def insert_score(self, tx: TenantTransaction, row: NewScoreRow, key: IdempotencyKey) -> str: ...
    def insert_qc_result(
        self, tx: TenantTransaction, row: NewScoreQcRow, key: IdempotencyKey
    ) -> str: ...


class GroupRequestBuilder(Protocol):
    """Builds the ``agent_16.quality_score.judge.input`` payload of each group (G1 to G3) from the
    verified documents; a group whose inputs are absent maps to ``None`` (the judge is not
    called and its criteria earn 0 with a finding)."""

    def build(
        self,
        req: QualityScoreInput,
        blobs: Mapping[str, bytes],
        audience_level: str,
    ) -> Mapping[Group, GroupRequest]: ...


@dataclass(frozen=True, slots=True)
class ScoreStageDeps:
    config: Agent16Config
    tenancy: TenancyContext
    storage: BlobStorage
    audit: AuditLog
    budget: BudgetGuard
    costs: CostLedger
    breaker: Breaker
    clock: Clock
    llm: LlmAdapter
    renders: RenderHashReader
    rows: FactRowReader
    extractor: DocumentScoreFactExtractor
    groups: GroupRequestBuilder
    store: ScoreStore
    prompt: str
    """The ``quality_score.v1`` prompt file text (versioned, docs/v4/prompts)."""
    prompt_ids: tuple[str, ...] = ()


class QualityScoreStage:
    def __init__(self, deps: ScoreStageDeps) -> None:
        self.d = deps
        self._spend = Spend()

    @staticmethod
    def parse(ti: TaskInput) -> QualityScoreInput:
        if ti.payload.payload_schema != QUALITY_INPUT or ti.payload.data is None:
            raise SchemaInvalidError("payload is not agent_16.quality_score.input")
        try:
            req = QualityScoreInput.model_validate(ti.payload.data)
        except ValidationError as exc:
            raise SchemaInvalidError(
                "agent_16.quality_score.input invalid",
                details={
                    "violations": [
                        violation("FIELD_INVALID", "/" + "/".join(map(str, e["loc"])))
                        for e in exc.errors()[:20]
                    ]
                },
            ) from exc
        for name, ref in req.inputs:
            if ref is not None and storage_uri_owner(ref.uri) != ti.org_id:
                raise CrossTenantRefError(
                    "reference belongs to another tenant", details={"ref": name}
                )
        if req.rubric_version != RUBRIC_VERSION:
            raise InputInvalidError("rubric_version is not the stage's rubric")
        return req

    def run(self, task_input: TaskInput, ctx: ExecContext) -> TaskOutput:
        """``TaskWorker`` entry point; every failure is returned, never raised."""
        return run_guarded(
            agent_id=AGENT_ID,
            actor=AGENT_ID,
            task_input=task_input,
            ctx=ctx,
            spend=self._spend,
            now=self.d.clock.now,
            body=lambda: self._run(task_input, ctx),
            event="a16.score.failed",
        )

    def _audit(
        self, tx: TenantTransaction, ti: TaskInput, action: str, details: Mapping[str, Any]
    ) -> None:
        self.d.audit.append(
            tx,
            NewAuditEntry(
                actor_kind=ActorKind.AGENT,
                actor_ref=ActorRef(AGENT_ID),
                authority=AGENT_ID,
                action=action,
                target_kind="job",
                target_id=ti.job_id,
                occurred_at=self.d.clock.now(),
                job_id=JobId(ti.job_id),
                correlation_id=CorrelationId(ti.correlation_id),
                details=dict(details),
            ),
        )

    def _run(self, ti: TaskInput, ctx: ExecContext) -> TaskOutput:
        d, cfg = self.d, self.d.config
        req = self.parse(ti)
        step = cfg.step("llm_quality")  # a missing step config is CONFIG_INVALID before any call
        if cfg.default_audience_level is None and req.audience_level is None:
            raise ConfigInvalidError("quality.judge.default_audience_level is not configured")
        audience = req.audience_level or str(cfg.default_audience_level)
        meter = CallMeter.for_task([step], step.max_calls, ti.resource_budget)
        self._spend.meter = meter
        with d.tenancy.transaction(ctx.tenant) as tx:
            self._audit(tx, ti, "quality_score.started", {})
            stored = d.renders.render_content_sha256(tx, req.subject.render_id)
            if stored is None:
                raise MissingDependencyError("render not found in this tenant")
            if stored != req.subject.render_sha256:
                raise InputInvalidError("subject.render_sha256 is not renders.content_sha256")
            blobs: dict[str, bytes] = {}
            for name, ref in req.inputs:
                if ref is not None:
                    chunks = d.storage.get(tx.context, BlobUri(ref.uri), ref.sha256)
                    blobs[name] = b"".join(chunks)
            verify_frames(d.storage, tx, blobs.get("frames_ref"))
            channel = d.rows.channel(tx, ti.job_id)
            job = d.rows.job(tx, ti.job_id)
            if channel is None or job is None:
                raise MissingDependencyError("channel or job row not found in this tenant")
            if job.language != req.language:
                raise InputInvalidError("language differs from the job row")
            facts = d.extractor.extract(
                req.subject.render_id,
                blobs,
                tx,
                ReadScope(ti.job_id, req.subject.render_id),
                is_sensitive(channel, job.active_pack_keys),
            )
            groups = d.groups.build(req, blobs, audience)
            client = JudgeClient(
                llm=d.llm,
                step=step,
                meter=meter,
                budget=d.budget,
                costs=d.costs,
                breaker=d.breaker,
                clock=d.clock,
                scope=CallScope(
                    tx, JobId(ti.job_id), TaskId(ti.task_id), AttemptId(str(ctx.attempt_id))
                ),
                language=req.language,
            )
            system = system_prompt(d.prompt, {})
            seq = {"n": 0}

            def judge(payload: Mapping[str, Any]) -> QualityOutput:
                seq["n"] += 1
                return client.judge(system, payload, QualityOutput, f"quality.g{seq['n']}")

            result = QualityScorer(cfg, judge).score(
                facts, groups, req.routing.model_dump(mode="json")
            )
            return self._write(tx, ti, ctx, req, result, meter)

    def _write(
        self,
        tx: TenantTransaction,
        ti: TaskInput,
        ctx: ExecContext,
        req: QualityScoreInput,
        result: ScoreResult,
        meter: CallMeter,
    ) -> TaskOutput:
        d = self.d

        def key(*parts: str) -> IdempotencyKey:
            return make_idempotency_key(
                ti.org_id, IdempotencyScope.DB_OUTPUT, [ti.task_id, req.iteration, *parts]
            )

        ids: list[str] = []
        for row in result.dimensions:
            ids.append(
                d.store.insert_score(
                    tx,
                    NewScoreRow(
                        job_id=ti.job_id,
                        task_id=ti.task_id,
                        render_id=req.subject.render_id,
                        render_sha256=req.subject.render_sha256,
                        dimension=row.dimension.value,
                        max_points=row.max_points,
                        points=row.points,
                        scorer_kind=row.scorer_kind,
                        evidence={
                            "rubric_version": RUBRIC_VERSION,
                            "criteria": [
                                {
                                    "criterion_id": c.criterion_id,
                                    "kind": c.kind,
                                    "max": c.max,
                                    "earned": c.earned,
                                    "status": c.status,
                                    "precondition": c.precondition,
                                }
                                for c in row.criteria
                            ],
                        },
                    ),
                    key("score", row.dimension.value),
                )
            )
        for r in result.results:
            if r.gate:
                d.store.insert_qc_result(
                    tx,
                    NewScoreQcRow(ti.job_id, ti.task_id, req.subject.render_id, r),
                    key("qc", r.check_id),
                )
        provenance = {"prompt_ids": list(d.prompt_ids)}
        payload = score_payload(result, ids, provenance)
        uri = BlobUri(
            task_artifact_uri(
                ctx.org_id,
                ctx.job_id,
                ctx.task_id,
                ctx.attempt_id,
                f"quality_score-{req.iteration}.json",
            )
        )
        blob: BlobRef = put_artifact_once(d.storage, ctx.tenant, uri, payload)
        self._audit(
            tx,
            ti,
            "quality_score.completed",
            {
                "gate": result.gate,
                "machine_total": result.machine_total,
                "judge_calls": meter.calls,
            },
        )
        checks = [
            *result.results,
            integrity("tenant", True, "every reference in the envelope org"),
            integrity("rows", len(ids) == len(result.dimensions), f"{len(ids)} score rows written"),
            integrity("evidence", True, "score report written"),
        ]
        return build_task_output(
            payload_schema=QUALITY_OUTPUT,
            data=payload,
            results=checks,
            blob=blob,
            usage=Usage(
                tokens_in=meter.tokens_in,
                tokens_out=meter.tokens_out,
                tokens_cached_in=meter.tokens_cached_in,
                llm_calls=meter.calls,
                cost_micros=meter.spent_micros,
                cost_entry_ids=tuple(meter.cost_entry_ids),
            ),
            now=d.clock.now(),
            currency=ti.resource_budget.currency,
            quality_score=result.machine_total,
            verdict=ComplianceVerdict.ALLOWED,
            downstream=None,
        )
