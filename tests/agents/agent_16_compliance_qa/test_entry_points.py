# ruff: noqa: PT018
"""PASS6-K: the ``TaskWorker`` entry point of every Agent 16 task type, ``QualityScoreStage``,
the imported disclaimer label and the real storage backend.

* ``run(task_input, ctx: ExecContext)``; a context that does not match the Task Input is
  ``TENANT_MISMATCH`` returned as a Task Output (never raised);
* an error output reports the cost really incurred so far;
* every write of every stage is accepted by ``LocalDiskStorage`` (03 section 8 rule 5)."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import pytest

from agent_16_compliance_qa.authorisation.stage import (
    PublicationAuthorisationStage,
    PublicationAuthorisationWorker,
)
from agent_16_compliance_qa.checks import rules as R  # noqa: N812
from agent_16_compliance_qa.config import Agent16Config
from agent_16_compliance_qa.inputs.extractors import DocumentScoreFactExtractor
from agent_16_compliance_qa.quality import GroupRequest
from agent_16_compliance_qa.scoring.rubric import group_criteria
from agent_16_compliance_qa.scoring.stage import (
    NewScoreQcRow,
    NewScoreRow,
    QualityScoreStage,
    ScoreStageDeps,
)
from amw_core import ids
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.validation import validate_task_output
from amw_core.enums import OutputStatus
from amw_core.errors import TenantMismatchError
from amw_core.exec_context import ExecContext
from amw_core.ids import IdempotencyKey
from amw_core.interfaces.storage import BlobUri
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.storage.local import LocalDiskStorage
from amw_runtime.disclaimer import DRAFT_STATUS
from tests.agents.agent_16_compliance_qa.extractor_support import (
    CLAIM_ROWS,
    PASS_QC,
    R_SHA,
    blobs_of,
    docs,
    full_rows,
)
from tests.agents.agent_16_compliance_qa.support import (
    Breaker,
    Budget,
    FixedClock,
    Ledger,
    ScriptedLlm,
    config,
    validate_against_blueprint,
)
from tests.agents.agent_16_compliance_qa.test_stages import (
    NOW,
    Storage,
    Tenancy,
    assert_returned,
    ctx_of,
    data_of,
    gate_world,
    task_input,
    uniq_world,
)
from tests.fake_audit import RecordingAuditLog

pytestmark = pytest.mark.integration
QUALITY_PROMPT = (
    Path(__file__).resolve().parents[3]
    / "docs/v4/prompts/agent_16_compliance_qa/quality_score.v1.md"
)


# --- imported label (item 1) -----------------------------------------------------------------
def test_the_report_label_is_the_runtime_constant_not_a_copy() -> None:
    assert R.DRAFT_DISCLAIMER_LABEL is DRAFT_STATUS
    assert DRAFT_STATUS == "DRAFT \u2013 not lawyer-approved"
    res = R.disclaimer(True, True, "v1", False, None)
    assert res.extras["report_label"] == DRAFT_STATUS


# --- ExecContext guard on every entry point (item 4) ----------------------------------------
def mismatched(ti: TaskInput, **over: str) -> ExecContext:
    other = ti.model_copy(update=over)
    return ExecContext.from_task_input(
        other, str(ids.ATTEMPT.new()), other.agent_id, envelope_org_id=other.org_id
    )


@pytest.mark.parametrize(
    "over",
    [
        {"org_id": str(ids.ORG.new())},
        {"job_id": str(ids.new_id(ids.Prefix.JOB))},
        {"task_id": str(ids.new_id(ids.Prefix.TASK))},
    ],
)
def test_gate_and_uniqueness_return_tenant_mismatch(over: dict[str, str]) -> None:
    w = gate_world()
    assert_returned(w.stage.run(w.ti, mismatched(w.ti, **over)), TenantMismatchError)
    assert w.audit.actions() == []  # nothing ran before the guard
    stage, ti, store, audit = uniq_world(False)
    assert_returned(stage.run(ti, mismatched(ti, **over)), TenantMismatchError)
    assert audit.actions() == [] and not store.qc


def test_a_task_addressed_to_another_agent_is_a_tenant_mismatch() -> None:
    w = gate_world()
    ti = w.ti.model_copy(update={"agent_id": "agent_05"})
    assert_returned(w.stage.run(ti, ctx_of(ti)), TenantMismatchError)


# --- QualityScoreStage (item 3) --------------------------------------------------------------
@dataclass
class Renders:
    sha: str | None = R_SHA

    def render_content_sha256(self, tx: TenantTransaction, render_id: str) -> str | None:
        return self.sha


@dataclass
class ScoreStore:
    scores: dict[str, NewScoreRow] = field(default_factory=dict)
    qc: dict[str, NewScoreQcRow] = field(default_factory=dict)

    def insert_score(self, tx: TenantTransaction, row: NewScoreRow, key: IdempotencyKey) -> str:
        self.scores.setdefault(key, row)
        return str(ids.new_id(ids.Prefix.QUALITY_SCORE)) if len(self.scores) else ""

    def insert_qc_result(
        self, tx: TenantTransaction, row: NewScoreQcRow, key: IdempotencyKey
    ) -> str:
        self.qc.setdefault(key, row)
        return f"qcr_{len(self.qc)}"


class Groups:
    """Judge payloads of the three groups (a port of lane L1; here fixed fixtures)."""

    def __init__(self, groups: tuple[str, ...] = ("G1", "G2", "G3")) -> None:
        self.groups = groups

    def build(self, req: Any, blobs: Mapping[str, bytes], audience_level: str) -> Any:
        assert audience_level == "beginner"
        return {
            g: GroupRequest(payload={"group_id": g}, known_refs=frozenset({"s01"}))
            for g in self.groups
        }


def judge_text(group: Literal["G1", "G2", "G3"]) -> str:
    return json.dumps(
        {
            "group_id": group,
            "scores": [
                {
                    "criterion_id": c.criterion_id,
                    "points": c.max_points,
                    "max_points": c.max_points,
                    "evidence_refs": ["s01"],
                    "why_not_higher": "-",
                }
                for c in group_criteria(group)
            ],
            "check_results": [],
            "injection_suspected": [],
            "refusal": None,
        }
    )


class _Verifier:
    def derive(self, tx: Any, approval_id: str, kind: Any, subject: str) -> str:
        return "APPROVED"


@dataclass
class ScoreWorld:
    stage: QualityScoreStage
    ti: TaskInput
    store: ScoreStore
    storage: Any
    audit: RecordingAuditLog
    llm: ScriptedLlm
    ledger: Ledger


class SeededThenDisk:
    """Reads fall back to the seeded documents; every write goes to the real
    ``LocalDiskStorage``, which refuses a path that is not a 03 section 8 path."""

    def __init__(self, seeds: Storage, disk: LocalDiskStorage) -> None:
        self.seeds, self.disk = seeds, disk
        self.wrote: list[str] = []

    def blob_uri(self, context: Any, area: str, path: str) -> BlobUri:
        return self.disk.blob_uri(context, area, path)

    def put(self, context: Any, uri: BlobUri, stream: Any) -> Any:
        info = self.disk.put(context, uri, stream)
        self.wrote.append(str(uri))
        return info

    def _side(self, uri: BlobUri) -> Any:
        return self.seeds if str(uri) in self.seeds.blobs else self.disk

    def get(self, context: Any, uri: BlobUri, expected_sha256: str) -> Any:
        return self._side(uri).get(context, uri, expected_sha256)

    def head(self, context: Any, uri: BlobUri) -> Any:
        return self._side(uri).head(context, uri)

    def list_prefix(self, context: Any, org_id: Any, area: str) -> Any:
        return []


SCORE_REFS = (
    "script_ref",
    "claims_ref",
    "verification_ref",
    "research_pack_ref",
    "render_qc_ref",
    "shot_plan_ref",
    "thumbnails_ref",
    "gate_output_ref",
    "frames_ref",
)


def score_world(
    texts: list[str] | None = None,
    *,
    cfg: Agent16Config | None = None,
    disk: Path | None = None,
    renders: Renders | None = None,
    audience: bool = True,
) -> ScoreWorld:
    org = str(ids.ORG.new())
    seeds = Storage()
    d = docs()
    frames = [seeds.add(org, f"frame{i}", b"png%d" % i) for i in range(3)]
    d["frames_ref"]["frames"] = [
        {
            "frame_id": f"f{i + 1:02d}",
            "frame_index": i,
            "t_ms": i,
            "uri": f["uri"],
            "sha256": f["sha256"],
        }
        for i, f in enumerate(frames)
    ]
    refs = {n: seeds.add(org, n, blobs_of(d)[n]) for n in SCORE_REFS}
    payload = {
        "subject": {
            "render_id": ids.new_id(ids.Prefix.RENDER),
            "render_sha256": R_SHA,
            "script_id": ids.new_id(ids.Prefix.SCRIPT),
            "script_sha256": "b" * 64,
        },
        "iteration": 0,
        "rubric_version": "rubric.v1",
        "language": "mr-IN",
        "routing": {
            "script_stage_id": "s05_script",
            "plan_stage_id": "s09_plan",
            "voice_stage_id": "s07_voice",
            "render_stage_id": "s10_render",
            "thumbnails_stage_id": "s11_thumbs",
        },
        "inputs": refs | {"metadata_ref": None},
    }
    ti = task_input(org, "agent_16", "agent_16.quality_score.input", payload, 3)
    rows = full_rows(qc=(PASS_QC,), claim_rows=CLAIM_ROWS)
    storage: Any = SeededThenDisk(seeds, LocalDiskStorage(disk)) if disk else seeds
    llm = ScriptedLlm(texts if texts is not None else [judge_text(g) for g in ("G1", "G2", "G3")])
    audit, ledger, store = RecordingAuditLog(), Ledger(), ScoreStore()
    cfg = cfg or config(
        **({"quality.judge.default_audience_level": "beginner"} if audience else {})
    )
    deps = ScoreStageDeps(
        config=cfg,
        tenancy=Tenancy(),
        storage=storage,
        audit=audit,
        budget=Budget(),
        costs=ledger,
        breaker=Breaker(),
        clock=FixedClock(NOW),
        llm=llm,
        renders=renders or Renders(),
        rows=rows,
        extractor=DocumentScoreFactExtractor(rows, _Verifier()),  # type: ignore[arg-type]
        groups=Groups(),
        store=store,
        prompt=QUALITY_PROMPT.read_text(encoding="utf-8"),
        prompt_ids=("agent_16/quality_score.v1",),
    )
    return ScoreWorld(QualityScoreStage(deps), ti, store, storage, audit, llm, ledger)


def test_quality_stage_end_to_end_scores_persists_and_validates() -> None:
    w = score_world()
    out = w.stage.run(w.ti, ctx_of(w.ti))
    assert out.status is OutputStatus.SUCCEEDED, out.error
    validate_task_output(out.model_dump(mode="json"))
    data = data_of(out)
    validate_against_blueprint(data, "### 8.4 `agent_16.quality_score.output`")
    assert data["gate"] == "NOT_GATING" and data["judge_calls"] == 3
    assert len(data["dimensions"]) == 8 and len(w.store.scores) == 8
    assert len(data["quality_score_ids"]) == 8
    assert out.quality_score == data["machine_total"] <= 79
    assert out.resource_usage.llm_calls == 3 == len(w.ledger.entries)
    assert out.resource_usage.cost_estimate_micros == 30
    assert w.store.qc and all(r.result.gate for r in w.store.qc.values())
    assert w.audit.actions() == ["quality_score.started", "quality_score.completed"]
    assert out.output_refs and out.output_refs[0].uri in w.storage.blobs
    # the sensitive-claim approval of the unverifiable claim came from the derived state
    assert data["gate_verdict"] == "PASSED"


def test_a_source_that_is_absent_scores_zero_never_full_points() -> None:
    w = score_world()
    rows = w.stage.d.rows
    assert isinstance(rows, type(full_rows()))
    rows.claim_rows = ()
    rows.thumb_qc = ()
    data = data_of(w.stage.run(w.ti, ctx_of(w.ti)))
    thumbs = next(r for r in data["dimensions"] if r["dimension"] == "THUMBNAIL_METADATA")
    unknown = [c for c in thumbs["criteria"] if c["kind"] == "DETERMINISTIC" and c["earned"] == 0]
    assert unknown, "an unevaluated deterministic criterion earns 0"


@pytest.mark.parametrize(
    "over",
    [
        {"org_id": str(ids.ORG.new())},
        {"job_id": str(ids.new_id(ids.Prefix.JOB))},
        {"task_id": str(ids.new_id(ids.Prefix.TASK))},
    ],
)
def test_quality_stage_returns_tenant_mismatch(over: dict[str, str]) -> None:
    w = score_world()
    assert_returned(w.stage.run(w.ti, mismatched(w.ti, **over)), TenantMismatchError)
    assert not w.llm.requests and w.audit.actions() == []


def test_quality_stage_failure_reports_the_cost_really_incurred() -> None:
    """G1 answers with invalid output twice (one paid call and one paid retry): the error output
    names those two calls and their cost, never a silent 0."""
    w = score_world(["not json", "still not json"])
    out = w.stage.run(w.ti, ctx_of(w.ti))
    assert out.status is OutputStatus.FAILED and out.error is not None
    assert out.error.code == "AGENT.INVALID_JSON"
    assert out.resource_usage.llm_calls == 2 and out.resource_usage.cost_estimate_micros == 20
    assert len(out.resource_usage.cost_entry_ids) == 2 == len(w.ledger.entries)
    assert not w.store.scores  # nothing persisted for a failed attempt


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"renders": Renders(None)}, "PERMANENT.MISSING_DEPENDENCY"),
        ({"renders": Renders("f" * 64)}, "PERMANENT.INPUT_INVALID"),
        ({"audience": False}, "PERMANENT.CONFIG_INVALID"),
    ],
)
def test_quality_stage_refusals_are_returned_before_any_call(
    kwargs: dict[str, Any], code: str
) -> None:
    w = score_world(**kwargs)
    out = w.stage.run(w.ti, ctx_of(w.ti))
    assert out.status is OutputStatus.FAILED and out.error is not None and out.error.code == code
    assert not w.llm.requests and out.resource_usage.cost_estimate_micros == 0


def test_quality_stage_refuses_a_foreign_ref_and_a_foreign_rubric() -> None:
    w = score_world()
    data = dict(w.ti.payload.data or {})
    data["inputs"] = dict(data["inputs"]) | {
        "script_ref": {"uri": f"amw-blob://{ids.ORG.new()}/jobs/x", "sha256": "0" * 64}
    }
    ti = w.ti.model_copy(update={"payload": w.ti.payload.model_copy(update={"data": data})})
    out = w.stage.run(ti, ctx_of(ti))
    assert out.error is not None and out.error.code == "PERMANENT.CROSS_TENANT_REF"
    data = dict(w.ti.payload.data or {}) | {"rubric_version": "rubric.v9"}
    ti = w.ti.model_copy(update={"payload": w.ti.payload.model_copy(update={"data": data})})
    out = w.stage.run(ti, ctx_of(ti))
    assert out.error is not None and out.error.code == "PERMANENT.INPUT_INVALID"
    bad = w.ti.model_copy(
        update={"payload": w.ti.payload.model_copy(update={"payload_schema": "x.input"})}
    )
    out = w.stage.run(bad, ctx_of(bad))
    assert out.status is OutputStatus.REJECTED


def test_a_tampered_frame_is_corrupted_output() -> None:
    w = score_world()
    frame_uri = next(u for u in w.storage.blobs if "frame0" in u)
    w.storage.blobs[frame_uri] = b"tampered"
    out = w.stage.run(w.ti, ctx_of(w.ti))
    assert out.error is not None and out.error.code == "AGENT.CORRUPTED_OUTPUT"


# --- the real backend accepts every write (item 5) -----------------------------------------
def test_the_real_local_backend_accepts_every_write_of_the_score_stage(tmp_path: Path) -> None:
    w = score_world(disk=tmp_path / "blobs")
    out = w.stage.run(w.ti, ctx_of(w.ti))
    assert out.status is OutputStatus.SUCCEEDED, out.error
    assert w.storage.wrote and all("/jobs/" in u and "/artifacts/" in u for u in w.storage.wrote)


def test_the_real_local_backend_accepts_every_write_of_gate_and_uniqueness(tmp_path: Path) -> None:
    g = gate_world()
    store = SeededThenDisk(g.storage, LocalDiskStorage(tmp_path / "g"))
    object.__setattr__(g.stage.d, "storage", store)
    object.__setattr__(g.stage.d.writer, "_storage", store)
    out = g.stage.run(g.ti, ctx_of(g.ti))
    assert out.status is OutputStatus.SUCCEEDED, out.error
    assert any("compliance_gate-0.json" in u for u in store.wrote)
    stage, ti, _, _ = uniq_world(False)
    ustore = SeededThenDisk(stage.d.storage, LocalDiskStorage(tmp_path / "u"))  # type: ignore[arg-type]
    object.__setattr__(stage.d, "storage", ustore)
    uout = stage.run(ti, ctx_of(ti))
    assert uout.status is OutputStatus.SUCCEEDED, uout.error
    assert any("uniqueness-0.json" in u for u in ustore.wrote)


# --- publication authorisation worker -------------------------------------------------------
def test_authorisation_worker_returns_a_valid_output_and_failures() -> None:
    from tests.agents.agent_16_compliance_qa.test_auth_stage import AUDIT, Writer, world

    h, repo, req = world()
    stage = PublicationAuthorisationStage(config(), repo, h.a16, Writer(), AUDIT)
    storage = Storage()
    worker = PublicationAuthorisationWorker(stage, Tenancy(), storage, FixedClock(NOW))
    ti = task_input(
        str(h.org),
        "agent_16",
        "agent_16.publication_authorisation.input",
        json.loads(req.model_dump_json()),
    )
    out = worker.run(ti, ctx_of(ti))
    assert out.status is OutputStatus.SUCCEEDED, out.error
    validate_task_output(out.model_dump(mode="json"))
    data = data_of(out)
    validate_against_blueprint(data, "### 8.5 `agent_16.publication_authorisation.output`")
    assert out.quality_score == data["human_wins_total"] and out.output_refs[0].uri in storage.blobs
    assert all(r.gate for r in out.validation_results if not r.check_id.startswith("a16.out"))
    assert_returned(worker.run(ti, mismatched(ti, job_id=str(ids.JOB.new()))), TenantMismatchError)
    bad = ti.model_copy(
        update={"payload": ti.payload.model_copy(update={"payload_schema": "x.input"})}
    )
    assert worker.run(bad, ctx_of(bad)).status is OutputStatus.REJECTED
    blocked_ti = ti.model_copy(
        update={
            "payload": ti.payload.model_copy(
                update={"data": {**(ti.payload.data or {}), "approval_id": str(ids.APPROVAL.new())}}
            )
        }
    )
    out = worker.run(blocked_ti, ctx_of(blocked_ti))  # an unknown approval is refused, returned
    assert out.status is OutputStatus.FAILED and out.error is not None
    assert out.error.code == "PERMANENT.INPUT_INVALID" and out.downstream_agent is None
