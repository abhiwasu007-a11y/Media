# ruff: noqa: PT018
"""ComplianceGateStage / UniquenessCheckStage / GateInputAssembler / VerdictWriter /
ReportSectionBuilder over in-memory ports (review M4). The judge replies are synthesised by the
scripted LLM (no paid call); FIN-R12 release states come from real evidence rows of the fake
evidence database through ``ApprovalStepVerifier``."""

import hashlib
import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Any

import pytest

from agent_16_compliance_qa.assembler import ExtractedGate, GateInputAssembler, ReleaseRef
from agent_16_compliance_qa.authorisation.stage import (
    ApprovalRow,
    ApprovalStepVerifier,
    StepRow,
)
from agent_16_compliance_qa.checks import rules as R  # noqa: N812
from agent_16_compliance_qa.report import UNKNOWN, ReportSectionBuilder
from agent_16_compliance_qa.stages import (
    ComplianceGateStage,
    GateStageDeps,
    UniquenessCheckStage,
    UniquenessFacts,
    UniquenessStageDeps,
)
from agent_16_compliance_qa.uniqueness import Segment
from agent_16_compliance_qa.verdicts import NewQcRow, NewVerdictRow, VerdictWriter
from amw_core import ids
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.validation import validate_task_output
from amw_core.enums import (
    ApprovalKind,
    ApprovalState,
    ApprovalStepState,
    ComplianceVerdict,
    OutputStatus,
)
from amw_core.errors import (
    AmwError,
    CorruptedOutputError,
    CrossTenantRefError,
    InputInvalidError,
    LoopCapExceededError,
    MissingDependencyError,
    SchemaInvalidError,
)
from amw_core.exec_context import ExecContext
from amw_core.ids import IdempotencyKey
from amw_core.interfaces.storage import BlobHead, BlobInfo, BlobUri
from amw_core.interfaces.tenancy_context import TenantContext, TenantTransaction
from amw_core.testing.memory import MemoryTransaction
from tests.agents.agent_16_compliance_qa.r14_support import CODE, R14, REQUESTED
from tests.agents.agent_16_compliance_qa.support import (
    PROMPTS,
    Breaker,
    Budget,
    FixedClock,
    Ledger,
    ScriptedLlm,
    config,
    validate_against_blueprint,
)
from tests.agents.agent_16_compliance_qa.test_gate import (
    clean_inputs,
    frames_clean,
    packs,
    policy_reply,
)
from tests.fake_audit import RecordingAuditLog

pytestmark = pytest.mark.integration
NOW = datetime(2026, 1, 31, tzinfo=UTC)
R_SHA = "a" * 64
OP = "sys_operator"


class Tenancy:
    @contextmanager
    def transaction(self, context: TenantContext) -> Iterator[TenantTransaction]:
        yield MemoryTransaction(context)

    def require_same_tenant(self, tx: TenantTransaction, org_id: str) -> None:
        if tx.context.org_id != org_id:
            raise CrossTenantRefError("other tenant")

    def cache_key(self, org_id: str, area: str, key: str) -> str:
        return f"amw:{org_id}:{area}:{key}"


def data_of(out: Any) -> dict[str, Any]:
    assert out.payload is not None and out.payload.data is not None
    return dict(out.payload.data)


class Storage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def blob_uri(self, context: TenantContext, area: str, path: str) -> BlobUri:
        return BlobUri(f"amw-blob://{context.org_id}/{area}/{path}")

    def _check(self, context: TenantContext, uri: str) -> None:
        if uri.split("://", 1)[1].split("/", 1)[0] not in (context.org_id, "platform"):
            raise CrossTenantRefError("blob of another tenant")

    def put(self, context: TenantContext, uri: BlobUri, stream: Any) -> BlobInfo:
        self._check(context, uri)
        assert uri not in self.blobs, "write-once"
        data = stream.read()
        self.blobs[uri] = data
        return BlobInfo(uri, hashlib.sha256(data).hexdigest(), len(data))

    def get(self, context: TenantContext, uri: BlobUri, expected_sha256: str) -> Iterator[bytes]:
        self._check(context, uri)
        if uri not in self.blobs:
            raise MissingDependencyError("absent")
        if hashlib.sha256(self.blobs[uri]).hexdigest() != expected_sha256:
            raise CorruptedOutputError("sha mismatch")
        yield self.blobs[uri]

    def head(self, context: TenantContext, uri: BlobUri) -> BlobHead:
        data = self.blobs.get(uri)
        sha = hashlib.sha256(data).hexdigest() if data is not None else None
        return BlobHead(data is not None, sha, len(data) if data is not None else None)

    def list_prefix(self, context: TenantContext, org_id: Any, area: str) -> Iterable[BlobInfo]:
        return []

    def add(self, org: str, name: str, data: bytes) -> dict[str, str]:
        uri = f"amw-blob://{org}/artifacts/{name}.json"
        self.blobs[uri] = data
        return {"uri": uri, "sha256": hashlib.sha256(data).hexdigest()}


@dataclass
class Store:
    verdicts: dict[str, tuple[str, NewVerdictRow]] = field(default_factory=dict)
    qc: dict[str, tuple[str, NewQcRow]] = field(default_factory=dict)
    claims: dict[str, ComplianceVerdict] = field(default_factory=dict)

    def insert_verdict(self, tx: TenantTransaction, row: NewVerdictRow, key: IdempotencyKey) -> str:
        if key not in self.verdicts:
            self.verdicts[key] = (ids.new_id(ids.Prefix.COMPLIANCE_VERDICT), row)
        return self.verdicts[key][0]

    def insert_qc_result(self, tx: TenantTransaction, row: NewQcRow, key: IdempotencyKey) -> str:
        if key not in self.qc:
            self.qc[key] = (f"qcr_{len(self.qc)}", row)
        return self.qc[key][0]

    def set_claim_final_verdict(
        self, tx: TenantTransaction, claim_id: str, verdict: ComplianceVerdict, key: IdempotencyKey
    ) -> None:
        self.claims[claim_id] = verdict


@dataclass
class Approvals:
    approvals: dict[str, ApprovalRow] = field(default_factory=dict)
    steps_: dict[str, list[StepRow]] = field(default_factory=dict)
    render_sha: dict[str, str] = field(default_factory=dict)

    def approval(self, tx: TenantTransaction, approval_id: str) -> ApprovalRow | None:
        return self.approvals.get(approval_id)

    def steps(self, tx: TenantTransaction, approval_id: str) -> Sequence[StepRow]:
        return self.steps_.get(approval_id, [])

    def render_content_sha256(self, tx: TenantTransaction, render_id: str) -> str | None:
        return self.render_sha.get(render_id)


class Extractor:
    """Fixture extractor: the facts of ``clean_inputs`` plus a method segment whose upstream
    blob CLAIMS ``APPROVED`` (the assembler must overwrite it)."""

    def __init__(self, release_id: str | None, items: Any = None) -> None:
        self.release_id, self.items = release_id, items
        self.released = R_SHA
        self.quotations: dict[str, str | None] = {}
        self.seen: Mapping[str, bytes] = {}

    def extract(
        self, request: Any, blobs: Mapping[str, bytes], evaluation_date: date, tx: Any
    ) -> ExtractedGate:
        self.seen = blobs
        seg = R.MethodSegment(
            segment_ref="seg_m", cites_method_chunk=True, labelled=True, release_state="APPROVED"
        )
        over: dict[str, Any] = {"method_segments": [seg], "method_label_overlay": True}
        if self.items is not None:
            over["items"] = self.items
        return ExtractedGate(
            inputs=clean_inputs(**over),
            method_release_approvals={
                "seg_m": ReleaseRef(approval_id=self.release_id, released_sha256=self.released)
                if self.release_id
                else None
            },
            quotation_approvals=dict(self.quotations),
        )


class Packs:
    def __init__(self) -> None:
        self._loaded = packs()  # stable pack ids across attempts (as stored rows are)

    def load(self, tx: TenantTransaction, channel_category: str) -> Any:
        return self._loaded


class PolicyLlm(ScriptedLlm):
    """Synthesised replies (no model): every rule NO_VIOLATION, frame tests pass."""

    def __init__(self) -> None:
        super().__init__([])

    def complete(self, request: Any, *, idempotency_key: str) -> Any:
        from agent_16_compliance_qa.judge.models import PolicyInput

        payload = request.messages[0].content.split("<<<INPUT\n", 1)[1].split("\nINPUT>>>")[0]
        doc = json.loads(payload)
        if "checks_requested" in doc:  # the frames judge
            reply = frames_clean(doc).model_dump_json()
        else:
            reply = policy_reply(PolicyInput.model_validate(doc)).model_dump_json()
        self._texts = iter([reply])
        return super().complete(request, idempotency_key=idempotency_key)


REFS = (
    "script_ref",
    "claims_ref",
    "verification_ref",
    "asset_manifest_ref",
    "shot_plan_ref",
    "render_qc_ref",
    "voice_ref",
    "thumbnails_ref",
    "uniqueness_ref",
    "research_pack_ref",
    "frames_ref",
)


@dataclass
class World:
    h: R14
    storage: Storage
    store: Store
    approvals: Approvals
    audit: RecordingAuditLog
    ledger: Ledger
    extractor: Extractor
    stage: ComplianceGateStage
    ti: TaskInput


def _blob_of(name: str) -> bytes:
    """frames_ref is read as the Agent 10 evidence manifest (every frame hash is verified)."""
    return json.dumps({"frames": []} if name == "frames_ref" else {"n": name}).encode()


def gate_world(*, release: str = "approved", items: Any = None, budget_calls: int = 8) -> World:
    h = R14()
    org = str(h.org)
    storage, store, approvals = Storage(), Store(), Approvals()
    approvals.render_sha[h.render] = R_SHA
    rel_id: str | None = None
    if release != "none":
        rel = ids.APPROVAL.new()
        rel_id = rel
        state = ApprovalStepState.APPROVED
        ev = h.record(f"approve {CODE}", approval_id=rel)
        approvals.approvals[rel] = ApprovalRow(
            rel,
            h.org,
            ApprovalKind.KNOWLEDGE_RELEASE,
            ApprovalState.APPROVED,
            "render",
            h.render,
            R_SHA,
            CODE,
            REQUESTED,
        )
        evidence_id = ev.id if release == "approved" else None
        approvals.steps_[rel] = [
            StepRow(
                rel,
                h.org,
                1,
                state,
                h.owner,
                True,
                True,
                OP,
                h_channel(),
                evidence_id,
                f"step:{rel}:1",
            )
        ]
    extractor = Extractor(rel_id, items)
    audit, ledger = RecordingAuditLog(), Ledger()
    cfg = config()
    assembler = GateInputAssembler(
        storage, approvals, ApprovalStepVerifier(approvals, h.a16, cfg.accepted_channels), extractor
    )
    prompts = {
        k: (PROMPTS / f"{n}.v1.md").read_text(encoding="utf-8")
        for k, n in (
            ("policy", "compliance_gate"),
            ("paraphrase", "compliance_gate_paraphrase"),
            ("frames", "compliance_gate_frames"),
        )
    }
    deps = GateStageDeps(
        config=cfg,
        tenancy=Tenancy(),
        storage=storage,
        audit=audit,
        budget=Budget(),
        costs=ledger,
        breaker=Breaker(),
        clock=FixedClock(NOW),
        llm=PolicyLlm(),
        assembler=assembler,
        evidence=h.a16,
        packs=Packs(),
        writer=VerdictWriter(store, storage, audit),
        prompts=prompts,
        pack_texts={},
        prompt_ids=("agent_16/compliance_gate.v1",),
    )
    refs = {name: storage.add(org, name, _blob_of(name)) for name in REFS}
    payload = {
        "subject": {
            "render_id": h.render,
            "render_sha256": R_SHA,
            "script_id": ids.new_id(ids.Prefix.SCRIPT),
            "script_sha256": "b" * 64,
        },
        "iteration": 0,
        "channel_category": "finance",
        "production_type_key": "CHANNEL_LONG_FORM",
        "destination_kinds": ["FILE_DELIVERY"],
        "evaluate_as_destination": "YOUTUBE",
        "owner_sebi_registration": "UNREGISTERED",
        "language": "en-IN",
        "routing": {
            "script_stage_id": "s05_script",
            "assets_stage_id": "s08_assets",
            "thumbnails_stage_id": None,
        },
        "inputs": refs | {"metadata_ref": None},
    }
    ti = task_input(org, "agent_16", "agent_16.compliance_gate.input", payload, budget_calls)
    return World(
        h, storage, store, approvals, audit, ledger, extractor, ComplianceGateStage(deps), ti
    )


def ctx_of(ti: TaskInput) -> ExecContext:
    """A fresh attempt context for the Task Input (03 section 1 rule 5, CCR-203)."""
    return ExecContext.from_task_input(
        ti, str(ids.ATTEMPT.new()), ti.agent_id, envelope_org_id=ti.org_id
    )


def assert_returned(out: Any, exc: type[AmwError]) -> None:
    """Failures are returned as a Task Output, never raised out of ``run`` (CCR-203)."""
    assert out.status in (OutputStatus.FAILED, OutputStatus.REJECTED), out.status
    assert out.error is not None and out.error.code == exc.code, out.error
    validate_task_output(out.model_dump(mode="json"))


def h_channel() -> Any:
    from amw_core.enums import ApprovalChannel

    return ApprovalChannel.OWNER_CHAT_OPERATOR


def task_input(
    org: str, agent: str, schema: str, payload: dict[str, Any], calls: int = 8
) -> TaskInput:
    return TaskInput.model_validate(
        {
            "org_id": org,
            "job_id": str(ids.new_id(ids.Prefix.JOB)),
            "task_id": str(ids.new_id(ids.Prefix.TASK)),
            "project_id": None,
            "channel_id": None,
            "agent_id": agent,
            "source_agent": "agent_01",
            "priority": "NORMAL",
            "deadline": None,
            "context_refs": [],
            "resource_budget": {
                "max_cost_micros": 100000,
                "currency": "USD",
                "max_wall_ms": 600000,
                "max_llm_calls": calls,
            },
            "payload": {
                "payload_schema": schema,
                "payload_schema_version": "1.0.0",
                "data": payload,
            },
            "correlation_id": str(ids.new_id(ids.Prefix.CORRELATION)),
            "idempotency_key": "idk_" + "c" * 64,
            "retry_count": 0,
            "schema_version": "1.0.0",
        }
    )


def test_gate_stage_end_to_end_writes_rows_blob_audit_and_valid_output() -> None:
    w = gate_world()
    out = w.stage.run(w.ti, ctx_of(w.ti))
    validate_task_output(out.model_dump(mode="json"))
    data = data_of(out)
    validate_against_blueprint(data, "### 8.2 `agent_16.compliance_gate.output`")
    assert data["verdict"] == "ALLOWED", data["rules"]
    assert len(data["verdict_ids"]) == len(w.store.verdicts) > 0
    assert w.store.qc and out.output_refs and out.output_refs[0].uri in w.storage.blobs
    assert w.audit.actions() == [
        "compliance_gate.started",
        "compliance.gate.verdicts_written",
        "compliance_gate.completed",
    ]
    assert out.resource_usage.llm_calls == len(w.ledger.entries) >= 1
    assert set(w.extractor.seen) == set(REFS)  # every ref read through hash-verified storage
    assert all(r.gate is False for r in out.validation_results if r.check_id.startswith("a16.out"))


def test_gate_stage_derives_release_state_and_ignores_the_blob_claim() -> None:
    """FIN-R12: the extractor says APPROVED; the release step has no evidence, so F-26 derives
    APPROVED_UNVERIFIED and the gate blocks (derive_approval_state on the gate path)."""
    w = gate_world(release="unverified")
    data = data_of(w.stage.run(w.ti, ctx_of(w.ti)))
    assert data is not None
    r12 = next(r for r in data["rules"] if r["rule_id"] == "FIN-R12")
    assert r12["compliance_verdict"] == "BLOCKED" and data["verdict"] == "BLOCKED"
    assert data["gate_verdict"] == "FAILED"
    assert w.audit.actions()[-1] == "compliance_gate.blocked"
    w = gate_world(release="none")
    data = data_of(w.stage.run(w.ti, ctx_of(w.ti)))
    assert data is not None and data["verdict"] == "BLOCKED"


def test_gate_stage_mac_invalid_release_evidence_is_a_security_audit_event() -> None:
    w = gate_world()
    rel = next(iter(w.approvals.steps_.values()))[0]
    assert rel.evidence_id is not None
    w.h.db.superuser_tamper(w.h.tx(), rel.evidence_id, evidence_mac=b"\x00" * 32)
    data = data_of(w.stage.run(w.ti, ctx_of(w.ti)))
    assert data is not None and data["verdict"] == "BLOCKED"
    assert "security.evidence_mac_invalid" in w.audit.actions()


def test_gate_stage_claims_final_verdict_from_the_worst_rule_of_the_item() -> None:
    from agent_16_compliance_qa.gate import SourceItem

    items = [
        SourceItem(
            ref="seg_x", surface="SCRIPT_SEGMENT", text="Buy this stock now", claim_ids=("clm_1",)
        )
    ]
    w = gate_world(items=items)
    w.stage.run(w.ti, ctx_of(w.ti))
    assert w.store.claims == {"clm_1": ComplianceVerdict.ALLOWED}


def test_gate_stage_refuses_foreign_refs_bad_hashes_and_wrong_render() -> None:
    w = gate_world()
    data = dict(w.ti.payload.data or {})
    other = str(ids.ORG.new())
    data["inputs"] = dict(data["inputs"]) | {
        "script_ref": {"uri": f"amw-blob://{other}/artifacts/x.json", "sha256": "0" * 64}
    }
    with pytest.raises(CrossTenantRefError):
        GateInputAssembler.parse(
            w.ti.model_copy(update={"payload": w.ti.payload.model_copy(update={"data": data})})
        )
    w = gate_world()
    uri = next(u for u in w.storage.blobs if "script_ref" in u)
    w.storage.blobs[uri] = b"tampered"
    assert_returned(w.stage.run(w.ti, ctx_of(w.ti)), CorruptedOutputError)
    assert w.audit.actions()[-1] == "compliance_gate.failed"
    w = gate_world()
    w.approvals.render_sha[w.h.render] = "f" * 64
    assert_returned(w.stage.run(w.ti, ctx_of(w.ti)), InputInvalidError)
    w = gate_world()
    w.approvals.render_sha.clear()
    assert_returned(w.stage.run(w.ti, ctx_of(w.ti)), MissingDependencyError)
    bad = w.ti.model_copy(
        update={"payload": w.ti.payload.model_copy(update={"payload_schema": "x.input"})}
    )
    assert_returned(w.stage.run(bad, ctx_of(bad)), SchemaInvalidError)


def test_gate_stage_cross_tenant_ref_is_audited() -> None:
    w = gate_world()
    data = dict(w.ti.payload.data or {})
    data["inputs"] = dict(data["inputs"]) | {
        "voice_ref": {"uri": f"amw-blob://{ids.ORG.new()}/a/x.json", "sha256": "0" * 64}
    }
    ti = w.ti.model_copy(update={"payload": w.ti.payload.model_copy(update={"data": data})})
    assert_returned(w.stage.run(ti, ctx_of(ti)), CrossTenantRefError)
    assert w.audit.actions() == ["security.cross_tenant_ref"]


def test_gate_stage_envelope_call_budget_is_enforced() -> None:
    w = gate_world(budget_calls=0)
    assert_returned(w.stage.run(w.ti, ctx_of(w.ti)), LoopCapExceededError)
    assert w.ledger.entries == {}


def test_verdict_writer_is_idempotent_per_task() -> None:
    w = gate_world()
    w.stage.run(w.ti, ctx_of(w.ti))
    first = dict(w.store.verdicts)
    w.stage.run(w.ti, ctx_of(w.ti))  # a retried attempt: same rows, same blob
    assert w.store.verdicts == first


# --- S2 uniqueness stage -------------------------------------------------------------------
class UniqExtractor:
    def __init__(self, identical: bool) -> None:
        self.identical = identical

    def extract(self, blobs: Mapping[str, bytes]) -> UniquenessFacts:
        template = (Segment(section_role="HOOK", text="Today we learn {topic} in five steps."),)
        text = "Today we learn gaps in five steps." if self.identical else "A fresh hook."
        return UniquenessFacts(
            script=(Segment(section_role="HOOK", text=text),),
            template=template,
            shots=("A", "B"),
            template_shots=("C", "D"),
            complete=True,
        )


class Priors:
    def prior_scripts(
        self, tx: TenantTransaction, channel_id: str, limit: int
    ) -> Sequence[tuple[Segment, ...]]:
        return []


def uniq_world(identical: bool) -> tuple[UniquenessCheckStage, TaskInput, Store, RecordingAuditLog]:
    org = str(ids.ORG.new())
    storage, store, audit = Storage(), Store(), RecordingAuditLog()
    refs = {
        n: storage.add(org, n, json.dumps({"n": n}).encode())
        for n in ("script_ref", "shot_plan_ref", "thumbnails_ref", "template_ref")
    }
    payload = {
        "subject": {"script_id": ids.new_id(ids.Prefix.SCRIPT), "script_sha256": "b" * 64},
        "iteration": 0,
        "channel_id": ids.new_id(ids.Prefix.CHANNEL),
        "production_type_key": "CHANNEL_LONG_FORM",
        "routing": {"script_stage_id": "s05_script"},
        "inputs": refs,
        "prior_window": {"max_prior_jobs": 5},
    }
    deps = UniquenessStageDeps(
        config=config(),
        tenancy=Tenancy(),
        storage=storage,
        audit=audit,
        clock=FixedClock(NOW),
        store=store,
        source=Priors(),
        extractor=UniqExtractor(identical),
    )
    ti = task_input(org, "svc_s02", "svc_s02.uniqueness_check.input", payload)
    return UniquenessCheckStage(deps), ti, store, audit


@pytest.mark.parametrize("identical", [False, True])
def test_uniqueness_stage_end_to_end(identical: bool) -> None:
    stage, ti, store, audit = uniq_world(identical)
    out = stage.run(ti, ctx_of(ti))
    validate_task_output(out.model_dump(mode="json"))
    data = data_of(out)
    validate_against_blueprint(data, "### 8.3 `svc_s02.uniqueness_check.output`")
    assert (data["verdict"] == "BLOCKED") is identical
    assert store.qc and audit.actions()[0] == "uniqueness_check.started"
    assert audit.actions()[-1].endswith("blocked" if identical else "completed")


# --- report section ------------------------------------------------------------------------
def test_report_section_lists_every_row_and_never_prints_zero_for_unknown() -> None:
    w = gate_world()
    gate = data_of(w.stage.run(w.ti, ctx_of(w.ti)))
    rep = ReportSectionBuilder().build(gate, None, None)
    assert (
        len([r for r in rep.rows if r.section == "compliance"])
        == len(gate["rules"]) + len(gate["frame_checks"]) + 1
    )
    assert rep.quality_total == UNKNOWN and rep.authorisation_verdict == UNKNOWN
    assert any(r.check_id == "s16_score" and r.verdict == UNKNOWN for r in rep.rows)
    score = {
        "machine_total": None,
        "dimensions": [
            {
                "dimension": "AUDIO_QUALITY",
                "criteria": [
                    {"criterion_id": "a.music", "status": "SKIPPED", "earned": 0, "max": 1},
                    {"criterion_id": "a.loud", "status": "PASS", "earned": 2, "max": 2},
                ],
            }
        ],
        "judged_checks": [],
    }
    auth = {
        "verdict": "ALLOWED",
        "guards": [{"guard_id": "G0", "result": "PASS", "detail": "ok"}],
        "earliest_compliant_publish_date": "2025-12-01",
        "evaluation_date": "2026-01-31",
    }
    rep = ReportSectionBuilder().build(gate, score, auth)
    music = next(r for r in rep.rows if r.check_id == "a.music")
    assert music.value == f"{UNKNOWN} / 1"  # SKIPPED never prints as 0 points
    assert rep.quality_total == UNKNOWN
    assert rep.publish_date_note.startswith("already compliant")


NOT_APPROVED = [s for s in ApprovalState if s is not ApprovalState.APPROVED]


@pytest.mark.parametrize("state", NOT_APPROVED, ids=lambda s: s.value)
def test_release_approval_state_must_be_approved(state: ApprovalState) -> None:
    """Re-review N1 (FIN-R12): a WITHDRAWN / EXPIRED / ... release never releases method
    content, even with APPROVED steps and CONFIRMED evidence."""
    w = gate_world()
    rel = next(iter(w.approvals.approvals))
    w.approvals.approvals[rel] = replace(w.approvals.approvals[rel], state=state)
    data = data_of(w.stage.run(w.ti, ctx_of(w.ti)))
    r12 = next(r for r in data["rules"] if r["rule_id"] == "FIN-R12")
    assert r12["compliance_verdict"] == "BLOCKED" and data["verdict"] == "BLOCKED"


def test_release_approval_for_another_subject_never_counts() -> None:
    """Re-review m3: the release must be for the hash of what is released."""
    w = gate_world()
    w.extractor.released = "e" * 64
    data = data_of(w.stage.run(w.ti, ctx_of(w.ti)))
    assert data["verdict"] == "BLOCKED"


@pytest.mark.parametrize("state", [ApprovalState.APPROVED, *NOT_APPROVED], ids=lambda s: s.value)
def test_quotation_approval_state_and_span_binding(state: ApprovalState) -> None:
    """Re-review N1 + m3 (V12): a COPYRIGHT_DOUBT approval counts only when APPROVED (state and
    steps) and only for its own span hash."""
    w = gate_world()
    rel = next(iter(w.approvals.approvals))
    span = R_SHA
    w.approvals.approvals[rel] = replace(
        w.approvals.approvals[rel], kind=ApprovalKind.COPYRIGHT_DOUBT, state=state
    )
    verifier = ApprovalStepVerifier(w.approvals, w.h.a16, config().accepted_channels)
    tx = MemoryTransaction(TenantContext(w.h.org, ids.ActorRef("agent_16")))
    got = verifier.derive(tx, rel, ApprovalKind.COPYRIGHT_DOUBT, span)
    assert (got == "APPROVED") is (state is ApprovalState.APPROVED)
    assert verifier.derive(tx, rel, ApprovalKind.COPYRIGHT_DOUBT, "f" * 64) == "NONE"
    assert verifier.derive(tx, rel, ApprovalKind.COPYRIGHT_DOUBT, None) == "NONE"
    w.extractor.quotations = {span: rel}
    data_of(w.stage.run(w.ti, ctx_of(w.ti)))  # the assembler path runs the same check
