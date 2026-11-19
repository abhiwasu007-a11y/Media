"""Stage classes of Agent 16 / S2 that take a Task Input and return a Task Output (constructor
DI; blueprint section 9 ``stages.py``).

* ``ComplianceGateStage`` (F-01, ``agent_16.compliance_gate``, gate ``s16_comp``)
* ``UniquenessCheckStage`` (F-17, ``svc_s02.uniqueness_check``, gate ``s02u_unique``)

Each stage has the one entry point ``run(task_input, ctx: ExecContext) -> TaskOutput`` (03 section
1 rule 5, CCR-203): a context that does not match the Task Input is ``TENANT_MISMATCH`` before any
step runs, and every failure is returned as a Task Output carrying the cost incurred so far.
Everything a stage does happens inside ONE tenant transaction opened from the envelope org.
Every task emits ``audit_log`` entries (``<task>.started``, ``.completed`` / ``.blocked`` /
``.failed``, ``security.*``; NF-09); logs carry the 27 section 7.3.6 fields and no content text.

What is a port here (implemented by lane L1): the SQL repositories (``VerdictStore``,
``RenderHashReader``, ``ApprovalReader``, ``PackSource``, ``UniquenessSource``, ``FactRowReader``)
and the breaker read. The extractors are this package's own (``inputs/extractors.py``).
"""

import logging
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Final, Protocol

from pydantic import Field, ValidationError

from agent_16_compliance_qa.assembler import ComplianceGateInput, GateInputAssembler
from agent_16_compliance_qa.authorisation.evidence import OwnerEvidenceVerifier
from agent_16_compliance_qa.base import Model
from agent_16_compliance_qa.config import Agent16Config, LlmStepConfig
from agent_16_compliance_qa.entry import Spend, put_artifact_once, run_guarded
from agent_16_compliance_qa.gate import (
    ComplianceGate,
    GateDecision,
    gate_payload,
    validation_results,
)
from agent_16_compliance_qa.judge.client import (
    Breaker,
    CallMeter,
    CallScope,
    JudgeClient,
    system_prompt,
)
from agent_16_compliance_qa.judge.models import (
    FramesOutput,
    ParaphraseInput,
    ParaphraseOutput,
    PolicyInput,
    PolicyOutput,
)
from agent_16_compliance_qa.output import (
    BlobRef,
    Usage,
    build_task_output,
    integrity,
    uniqueness_payload,
)
from agent_16_compliance_qa.packs import LoadedPacks
from agent_16_compliance_qa.uniqueness import (
    Measures,
    Segment,
    Thresholds,
    decide,
    masked_identical,
    role_sequence_equal,
    shot_sequence_identity,
    template_text_share,
)
from agent_16_compliance_qa.verdicts import (
    GateSubjectRef,
    NewQcRow,
    VerdictStore,
    VerdictWriter,
    WriteScope,
)
from amw_adapters.llm.protocol import LlmAdapter
from amw_core.contracts.common import storage_uri_owner
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import TaskOutput
from amw_core.enums import ActorKind, ComplianceVerdict
from amw_core.errors import CrossTenantRefError, SchemaInvalidError
from amw_core.exec_context import ExecContext
from amw_core.ids import (
    ActorRef,
    AttemptId,
    CorrelationId,
    IdempotencyScope,
    JobId,
    OrgId,
    TaskId,
    make_idempotency_key,
)
from amw_core.interfaces.audit_log import AuditLog, NewAuditEntry
from amw_core.interfaces.budget_guard import BudgetGuard
from amw_core.interfaces.clock import Clock
from amw_core.interfaces.cost_ledger import CostLedger
from amw_core.interfaces.storage import BlobStorage, BlobUri
from amw_core.interfaces.tenancy_context import TenancyContext, TenantContext, TenantTransaction
from amw_core.tenancy.storage_paths import task_artifact_uri

_LOG = logging.getLogger(__name__)
AGENT_ID: Final = "agent_16"
S02_ID: Final = "svc_s02"
GATE_OUTPUT: Final = "agent_16.compliance_gate.output"
UNIQ_INPUT: Final = "svc_s02.uniqueness_check.input"
UNIQ_OUTPUT: Final = "svc_s02.uniqueness_check.output"


def log_fields(ti: TaskInput, attempt_id: str, actor: str) -> dict[str, str]:
    """27 section 7.3.6: every log line of a task carries these (never content text)."""
    return {
        "org_id": ti.org_id,
        "correlation_id": ti.correlation_id,
        "job_id": ti.job_id,
        "task_id": ti.task_id,
        "attempt_id": attempt_id,
        "actor": actor,
    }


@dataclass(frozen=True, slots=True)
class _Audit:
    audit: AuditLog
    clock: Clock
    ti: TaskInput
    actor: str

    def __call__(
        self, tx: TenantTransaction, action: str, details: Mapping[str, Any], target: str
    ) -> None:
        self.audit.append(
            tx,
            NewAuditEntry(
                actor_kind=ActorKind.AGENT,
                actor_ref=ActorRef(self.actor),
                authority=self.actor,
                action=action,
                target_kind="job",
                target_id=target,
                occurred_at=self.clock.now(),
                job_id=JobId(self.ti.job_id),
                correlation_id=CorrelationId(self.ti.correlation_id),
                details=dict(details),
            ),
        )


class PackSource(Protocol):
    def load(self, tx: TenantTransaction, channel_category: str) -> LoadedPacks:
        """F-02 ``RulePackLoader.load``: profile + category packs, hash-verified."""
        ...


@dataclass(frozen=True, slots=True)
class GateStageDeps:
    config: Agent16Config
    tenancy: TenancyContext
    storage: BlobStorage
    audit: AuditLog
    budget: BudgetGuard
    costs: CostLedger
    breaker: Breaker
    clock: Clock
    llm: LlmAdapter
    assembler: GateInputAssembler
    evidence: OwnerEvidenceVerifier
    """The same verifier instance the assembler's ``ApprovalStepVerifier`` uses (MAC log)."""
    packs: PackSource
    writer: VerdictWriter
    prompts: Mapping[str, str]
    """``policy`` / ``paraphrase`` / ``frames`` prompt file texts (versioned, docs/v4/prompts)."""
    pack_texts: Mapping[str, str]
    prompt_ids: Sequence[str] = ()


@contextmanager
def _security_events(audit: _Audit, tenancy: TenancyContext, tc: TenantContext) -> Iterator[None]:
    """A foreign reference is a security event, never a silent drop (blueprint 19.1)."""
    try:
        yield
    except CrossTenantRefError as exc:
        with tenancy.transaction(tc) as tx:
            audit(tx, "security.cross_tenant_ref", dict(exc.details or {}), audit.ti.job_id)
        raise


def _mac_events(audit: _Audit, tx: TenantTransaction, evidence: OwnerEvidenceVerifier) -> None:
    for kind, evidence_id in evidence.log.mac_invalid:
        audit(
            tx,
            "security.evidence_mac_invalid",
            {"evidence_id": evidence_id, "record_kind": kind.value},
            audit.ti.job_id,
        )
    evidence.log.mac_invalid.clear()


class ComplianceGateStage:
    def __init__(self, deps: GateStageDeps) -> None:
        self.d = deps
        self._spend = Spend()

    def _judges(
        self,
        tx: TenantTransaction,
        ti: TaskInput,
        attempt_id: str,
        packs: LoadedPacks,
        language: str,
    ) -> tuple[
        CallMeter,
        Callable[[PolicyInput], PolicyOutput],
        Callable[[ParaphraseInput], ParaphraseOutput],
        Callable[[Mapping[str, Any]], FramesOutput],
    ]:
        d, cfg = self.d, self.d.config
        steps: dict[str, LlmStepConfig] = {
            "policy": cfg.step("llm_policy"),
            "paraphrase": cfg.step("llm_paraphrase"),
            "frames": cfg.step("llm_frames"),
        }  # a missing step config is PERMANENT.CONFIG_INVALID before any call
        meter = CallMeter.for_task(list(steps.values()), cfg.gate_max_llm_calls, ti.resource_budget)
        self._spend.meter = meter  # an error output reports what was really spent
        scope = CallScope(tx, JobId(ti.job_id), TaskId(ti.task_id), AttemptId(attempt_id))
        texts = {k: d.pack_texts[k] for k in sorted(packs.keys) if k in d.pack_texts}

        def client(name: str) -> tuple[JudgeClient, str]:
            jc = JudgeClient(
                llm=d.llm,
                step=steps[name],
                meter=meter,
                budget=d.budget,
                costs=d.costs,
                breaker=d.breaker,
                clock=d.clock,
                scope=scope,
                language=language,
            )
            return jc, system_prompt(d.prompts[name], texts)

        pol, pol_sys = client("policy")
        par, par_sys = client("paraphrase")
        fra, fra_sys = client("frames")
        seq = {"policy": 0}

        def policy(batch: PolicyInput) -> PolicyOutput:
            seq["policy"] += 1
            payload = batch.model_dump(mode="json")
            return pol.judge(pol_sys, payload, PolicyOutput, f"policy.b{seq['policy']:02d}")

        def paraphrase(inp: ParaphraseInput) -> ParaphraseOutput:
            return par.judge(par_sys, inp.model_dump(mode="json"), ParaphraseOutput, "paraphrase")

        def frames(payload: Mapping[str, Any]) -> FramesOutput:
            return fra.judge(fra_sys, payload, FramesOutput, "frames")

        return meter, policy, paraphrase, frames

    def run(self, task_input: TaskInput, ctx: ExecContext) -> TaskOutput:
        """``TaskWorker`` entry point (F-01); every failure is returned, never raised."""
        return run_guarded(
            agent_id=AGENT_ID,
            actor=AGENT_ID,
            task_input=task_input,
            ctx=ctx,
            spend=self._spend,
            now=self.d.clock.now,
            body=lambda: self._run(task_input, str(ctx.attempt_id)),
            event="a16.gate.failed",
        )

    def _run(self, ti: TaskInput, attempt_id: str) -> TaskOutput:
        d = self.d
        fields = log_fields(ti, attempt_id, AGENT_ID)
        d.evidence.log_fields = fields
        tc = TenantContext(OrgId(ti.org_id), ActorRef(AGENT_ID), CorrelationId(ti.correlation_id))
        audit = _Audit(d.audit, d.clock, ti, AGENT_ID)
        with _security_events(audit, d.tenancy, tc):
            GateInputAssembler.parse(ti)
        try:
            with d.tenancy.transaction(tc) as tx:
                audit(tx, "compliance_gate.started", {}, ti.job_id)
                req, inputs = d.assembler.assemble(ti, tx, d.clock.now().date())
                _mac_events(audit, tx, d.evidence)
                packs = d.packs.load(tx, req.channel_category)
                meter, policy, paraphrase, frames = self._judges(
                    tx, ti, attempt_id, packs, req.language
                )
                gate = ComplianceGate(d.config, packs, policy, paraphrase, frames, fields)
                decision = gate.evaluate(inputs)
                out = self._write(
                    tx, ti, attempt_id, req, decision, packs, meter, inputs.items, audit
                )
        except Exception as exc:
            _LOG.warning(
                "a16.gate.failed", extra=fields | {"code": getattr(exc, "code", type(exc).__name__)}
            )
            with d.tenancy.transaction(tc) as tx:
                audit(
                    tx,
                    "compliance_gate.failed",
                    {"code": str(getattr(exc, "code", type(exc).__name__))},
                    ti.job_id,
                )
            raise
        return out

    def _write(
        self,
        tx: TenantTransaction,
        ti: TaskInput,
        attempt_id: str,
        req: ComplianceGateInput,
        decision: GateDecision,
        packs: LoadedPacks,
        meter: CallMeter,
        items: Sequence[Any],
        audit: _Audit,
    ) -> TaskOutput:
        d = self.d
        subject = req.subject.model_dump(mode="json")
        results = validation_results(decision, req.routing, packs)
        provenance = {
            "prompt_ids": list(d.prompt_ids),
            "lexicon_version": d.config.prefilter_lexicon(req.language).version,
        }
        evidence = gate_payload(decision, subject, req.routing, packs, [], provenance)
        written = d.writer.write(
            tx,
            decision,
            GateSubjectRef(**subject),
            packs,
            results,
            {i.ref: tuple(i.claim_ids) for i in items if i.claim_ids},
            WriteScope(
                ti.job_id, ti.task_id, attempt_id, req.iteration, ti.correlation_id, d.clock.now()
            ),
            evidence,
        )
        payload = gate_payload(
            decision, subject, req.routing, packs, written.verdict_ids, provenance
        )
        expected_rows = sum(1 for r in payload["rules"] if r["compliance_verdict"] is not None)
        checks = [
            *results,
            integrity("tenant", True, "every reference in the envelope org"),
            integrity(
                "rows",
                len(written.verdict_ids) == expected_rows,
                f"{len(written.verdict_ids)} verdict rows for {expected_rows} rule rows",
            ),
            integrity("evidence", bool(written.blob_sha256), "evidence blob written"),
        ]
        blocked = decision.verdict is ComplianceVerdict.BLOCKED
        audit(
            tx,
            "compliance_gate.blocked" if blocked else "compliance_gate.completed",
            {"verdict": decision.verdict.value, "judge_calls": decision.judge_calls},
            ti.job_id,
        )
        return build_task_output(
            payload_schema=GATE_OUTPUT,
            data=payload,
            results=checks,
            blob=BlobRef(
                uri=written.blob_uri, sha256=written.blob_sha256, size_bytes=written.blob_size
            ),
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
            quality_score=None,
            verdict=decision.verdict,
            downstream=None,
        )


# --- S2 uniqueness ------------------------------------------------------------------------
class UniqRef(Model):
    uri: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class UniqInputs(Model):
    script_ref: UniqRef
    shot_plan_ref: UniqRef
    thumbnails_ref: UniqRef
    template_ref: UniqRef


class UniqSubject(Model):
    script_id: str = Field(pattern=r"^scr_")
    script_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    render_id: str | None = None
    render_sha256: str | None = None


class UniqRouting(Model):
    script_stage_id: str = Field(pattern=r"^[a-z0-9_]{2,32}$")


class UniqPriorWindow(Model):
    max_prior_jobs: int = Field(ge=0)


class UniquenessInput(Model):
    """``svc_s02.uniqueness_check.input`` 1.0.0 (section 7.3)."""

    subject: UniqSubject
    iteration: int = Field(ge=0)
    channel_id: str = Field(pattern=r"^chn_")
    production_type_key: str
    routing: UniqRouting
    inputs: UniqInputs
    prior_window: UniqPriorWindow


class UniquenessFacts(Model):
    """What ``UniquenessExtractor`` returns from the verified blobs."""

    script: tuple[Segment, ...]
    template: tuple[Segment, ...]
    shots: tuple[str, ...]
    template_shots: tuple[str, ...]
    complete: bool


class UniquenessExtractor(Protocol):
    def extract(self, blobs: Mapping[str, bytes]) -> UniquenessFacts: ...


class UniquenessSource(Protocol):
    def prior_scripts(
        self, tx: TenantTransaction, channel_id: str, limit: int
    ) -> Sequence[tuple[Segment, ...]]:
        """Masked prior scripts of the same channel and org (RLS + explicit ``org_id``)."""
        ...


@dataclass(frozen=True, slots=True)
class UniquenessStageDeps:
    config: Agent16Config
    tenancy: TenancyContext
    storage: BlobStorage
    audit: AuditLog
    clock: Clock
    store: VerdictStore
    source: UniquenessSource
    extractor: UniquenessExtractor
    cross_video_comparator_built: bool = False
    """3C; while False the cross-video measure is SKIPPED / NEEDS_HUMAN_REVIEW (section 8.3)."""


class UniquenessCheckStage:
    def __init__(self, deps: UniquenessStageDeps) -> None:
        self.d = deps
        self._spend = Spend()

    @staticmethod
    def parse(ti: TaskInput) -> UniquenessInput:
        if ti.payload.payload_schema != UNIQ_INPUT or ti.payload.data is None:
            raise SchemaInvalidError("payload is not svc_s02.uniqueness_check.input")
        try:
            req = UniquenessInput.model_validate(ti.payload.data)
        except ValidationError as exc:
            raise SchemaInvalidError(
                "svc_s02.uniqueness_check.input invalid",
                details={"violations": [".".join(map(str, e["loc"])) for e in exc.errors()]},
            ) from exc
        for name, ref in req.inputs:
            if storage_uri_owner(ref.uri) != ti.org_id:
                raise CrossTenantRefError(
                    "reference belongs to another tenant", details={"ref": name}
                )
        return req

    def run(self, task_input: TaskInput, ctx: ExecContext) -> TaskOutput:
        """``TaskWorker`` entry point (F-17); every failure is returned, never raised."""
        return run_guarded(
            agent_id=S02_ID,
            actor=S02_ID,
            task_input=task_input,
            ctx=ctx,
            spend=self._spend,
            now=self.d.clock.now,
            body=lambda: self._run(task_input, str(ctx.attempt_id)),
            event="a16.uniqueness.failed",
        )

    def _run(self, ti: TaskInput, attempt_id: str) -> TaskOutput:
        d, cfg = self.d, self.d.config
        fields = log_fields(ti, attempt_id, S02_ID)
        tc = TenantContext(OrgId(ti.org_id), ActorRef(S02_ID), CorrelationId(ti.correlation_id))
        audit = _Audit(d.audit, d.clock, ti, S02_ID)
        with _security_events(audit, d.tenancy, tc):
            req = self.parse(ti)
        with d.tenancy.transaction(tc) as tx:
            audit(tx, "uniqueness_check.started", {}, ti.job_id)
            blobs = {
                name: b"".join(d.storage.get(tc, BlobUri(ref.uri), ref.sha256))
                for name, ref in req.inputs
            }
            facts = d.extractor.extract(blobs)
            priors = d.source.prior_scripts(tx, req.channel_id, req.prior_window.max_prior_jobs)
            measures = Measures(
                masked_structure_identical_to_template=masked_identical(
                    facts.script, facts.template
                ),
                masked_structure_identical_to_prior_video=any(
                    masked_identical(facts.script, p) for p in priors
                ),
                template_text_share=template_text_share(facts.script, facts.template),
                section_role_sequence_equal_to_template=role_sequence_equal(
                    facts.script, facts.template
                ),
                shot_type_sequence_identity=shot_sequence_identity(
                    facts.shots, facts.template_shots
                ),
                prior_videos_on_channel=len(priors),
                cross_video_comparator_built=d.cross_video_comparator_built,
                inputs_complete=facts.complete,
                refs_same_org=True,
            )
            thresholds = Thresholds(
                template_text_share=cfg.uniq_template_text_share_max,
                shot_type_sequence_identity=cfg.uniq_shot_sequence_identity_max,
                cross_video_similarity=cfg.uniq_cross_video_max_similarity,
            )
            decision = decide(
                measures,
                thresholds,
                cfg.cross_video_skip_below_prior_count,
                req.routing.script_stage_id,
            )
            uri = BlobUri(
                task_artifact_uri(
                    OrgId(ti.org_id),
                    JobId(ti.job_id),
                    TaskId(ti.task_id),
                    AttemptId(attempt_id),
                    f"uniqueness-{req.iteration}.json",
                )
            )
            payload = uniqueness_payload(decision, measures, thresholds, str(uri))
            for r in decision.results:
                key = make_idempotency_key(
                    ti.org_id, IdempotencyScope.DB_OUTPUT, [ti.task_id, req.iteration, r.check_id]
                )
                d.store.insert_qc_result(tx, NewQcRow(ti.job_id, ti.task_id, None, r), key)
            info = put_artifact_once(d.storage, tc, uri, payload)
            audit(
                tx,
                "uniqueness_check.blocked"
                if decision.verdict is ComplianceVerdict.BLOCKED
                else "uniqueness_check.completed",
                {"verdict": decision.verdict.value},
                ti.job_id,
            )
        _LOG.info("a16.uniqueness.done", extra=fields | {"verdict": decision.verdict.value})
        return build_task_output(
            payload_schema=UNIQ_OUTPUT,
            data=payload,
            results=[*decision.results, integrity("evidence", True, "report blob written")],
            blob=info,
            usage=Usage(),
            now=d.clock.now(),
            currency=ti.resource_budget.currency,
            quality_score=None,
            verdict=decision.verdict,
            downstream=None,
        )
