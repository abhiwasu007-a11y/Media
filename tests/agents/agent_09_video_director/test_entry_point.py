# ruff: noqa: PT018, E501
"""PASS6-H (CCR-200, 202-205, 208, 210): the task entry point ``run(task_input, ctx)``.

Agent 05's real script document (hook, ``AFTER_HOOK`` and ``END`` disclaimers, two sections) goes
in through the slice model; the blob, the overlays, the chapters and the error objects are
checked against the contract.
"""

import hashlib
import inspect
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from agent_05_scriptwriter.assemble.parts import DisclaimerTemplate
from agent_09_video_director.contracts import HashedRef, OverlayKind, ShotPlanInput
from agent_09_video_director.output import ShotPlanDocument
from agent_09_video_director.protocol import GateFacts, RulePackText, ShotPlanTask
from agent_09_video_director.step import ShotPlanStep
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.validation import validate_task_output
from amw_core.enums import CheckVerdict, OutputStatus
from amw_core.exec_context import ExecContext
from amw_core.ids import ATTEMPT, CHANNEL, CORRELATION, JOB, ORG, TASK, Prefix, new_id
from amw_core.interfaces import TaskWorker
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.tenancy.storage_paths import task_artifact_uri
from tests.agents.agent_05_scriptwriter.test_deterministic_core import _assemble_min
from tests.agents.agent_09_video_director.support import make_step
from tests.agents.agent_09_video_director.test_step import MemBlob

pytestmark = pytest.mark.contract

DURS = [5200, 6100, 5000, 6000, 9000, 12_000, 8000, 6500, 6000]


class Clock:
    def __init__(self) -> None:
        self._ms = 0

    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)

    def monotonic_ms(self) -> int:
        self._ms += 7
        return self._ms


class Ports:
    def __init__(self, brand: dict[str, Any] | None = None) -> None:
        self.brand = brand or {
            "intro_ref": "sting_a",
            "intro_duration_ms": 1200,
            "outro_ref": None,
            "lower_third_template_ref": None,
            "future_field": 1,
        }

    def brand_kit(self, tenant: TenantContext, ref: HashedRef) -> dict[str, Any]:
        return self.brand

    def gate_facts(self, tenant: TenantContext, **_: Any) -> GateFacts:
        return GateFacts()

    def rule_pack(self, tenant: TenantContext, key: str) -> RulePackText:
        return RulePackText(text=f"{key} RULES", version="1")


class World:
    def __init__(self, org: str | None = None) -> None:
        self.org = org or str(ORG.new())
        self.job, self.task = str(JOB.new()), str(TASK.new())
        self.blobs = MemBlob()
        self.tenant = TenantContext(org_id=self.org, actor="agent_09")  # type: ignore[arg-type]

    def put(self, name: str, body: bytes, org: str | None = None) -> HashedRef:
        uri = f"amw-blob://{org or self.org}/jobs/{self.job}/tasks/{name}"
        self.blobs.data[uri] = body
        return HashedRef(uri=uri, sha256=hashlib.sha256(body).hexdigest())


def agent05_document() -> dict[str, Any]:
    tpl = DisclaimerTemplate("tpl_disclaimer", "1", "TEST DISCLAIMER TEXT.")
    doc = _assemble_min(placements=("AFTER_HOOK", "END"), template=tpl, sections=(2, 2))
    dumped: dict[str, Any] = doc.model_dump(mode="json")
    return dumped


def timeline_doc(doc: dict[str, Any]) -> dict[str, Any]:
    t, segs = 0, []
    for seg, d in zip(doc["segments"], DURS, strict=True):
        segs.append(
            {
                "segment_id": seg["segment_id"], "start_ms": t, "end_ms": t + d, "duration_ms": d,
                "pace_requested": "NORMAL", "reused_clip": False, "idempotency_key": None,
            }
        )  # fmt: skip
        t += d
    return {"source": "PROVIDER_CLIPS", "segments": segs, "pauses": []}


def build(
    w: World, *, iteration: int = 0, previous: HashedRef | None = None, **over: Any
) -> tuple[TaskInput, ExecContext]:
    doc = agent05_document()
    body = json.dumps(doc).encode()
    script = w.put("script.json", body)
    sha = script.sha256
    tl = w.put("timeline.json", json.dumps(timeline_doc(doc)).encode())
    data: dict[str, Any] = {
        "production_type_key": "CHANNEL_LONG_FORM",
        "aspect_ratio": "16:9",
        "script_ref": {"script_id": doc["script_id"], "version": doc["version"], **script.model_dump()},
        "verification_ref": {
            "uri": f"amw-blob://{w.org}/jobs/{w.job}/tasks/verify.json", "sha256": "c" * 64,
            "verified_script_sha256": sha, "stage_verdict": "ALLOWED", "approval_id": None,
        },
        "narration_timeline_ref": tl.model_dump(),
        "brand_kit_ref": {"uri": f"amw-entity://{w.org}/brand_kits/bk1", "sha256": "d" * 64},
        "channel_category": "finance",
        "active_rule_packs": ["rp.youtube_general", "rp.finance_sebi_in"],
        "iteration": iteration,
        "previous_plan_ref": previous.model_dump() if previous else None,
        "limits": {"ai_still_allowed": True},
    }  # fmt: skip
    data.update(over)
    task = TaskInput.model_validate(
        {
            "org_id": w.org, "job_id": w.job, "task_id": w.task,
            "project_id": str(new_id(Prefix.PROJECT)), "channel_id": str(CHANNEL.new()),
            "agent_id": "agent_09", "source_agent": "agent_01", "priority": "NORMAL",
            "deadline": None, "context_refs": [],
            "resource_budget": {
                "max_cost_micros": 10**9, "currency": "USD", "max_wall_ms": 60_000,
                "max_llm_calls": 50,
            },
            "payload": {
                "payload_schema": "agent_09.shot_plan.input",
                "payload_schema_version": "1.0.0", "data": data,
            },
            "correlation_id": str(CORRELATION.new()),
            "idempotency_key": "idk_" + "a" * 64,
            "retry_count": 0, "schema_version": "1.0.0",
        }
    )  # fmt: skip
    ctx = ExecContext.from_task_input(
        task, str(ATTEMPT.new()), "agent_09", envelope_org_id=w.org, stage_id="s09_plan",
        iteration=iteration,
    )  # fmt: skip
    return task, ctx


def data_of(out: Any) -> dict[str, Any]:
    assert out.payload is not None and out.payload.data is not None
    return dict(out.payload.data)


def worker(w: World, ports: Ports | None = None) -> ShotPlanTask:
    step: ShotPlanStep = make_step()[0]
    return ShotPlanTask(step, w.blobs, ports or Ports(), Clock(), worst_case_call_micros=1000)


def test_run_is_a_task_worker_with_the_core_parameter_names() -> None:
    w = World()
    assert isinstance(worker(w), TaskWorker)
    params = list(inspect.signature(ShotPlanTask.run).parameters)
    assert params == ["self", "task_input", "ctx"]


def test_real_agent05_document_gives_chapter_one_at_zero_and_a_valid_blob() -> None:
    w = World()
    task, ctx = build(w)
    out = worker(w).run(task_input=task, ctx=ctx)
    assert out.status is OutputStatus.SUCCEEDED, out.error
    validate_task_output(out.to_doc(), version="1.0.0")
    results = {r.check_id: r for r in out.validation_results}
    assert results["a09.q.chapters"].verdict is CheckVerdict.PASS
    data = data_of(out)
    chapters = data["chapters"]
    assert [c["section_id"] for c in chapters] == ["sec1", "sec2"] and chapters[0]["start_ms"] == 0
    # lead-in = hook + AFTER_HOOK disclaimer; section 2 starts at its first segment (CCR-202)
    assert chapters[1]["start_ms"] == sum(DURS[:6])
    # the blob: the whole document without plan_ref, views included, at artifacts/shot_plan.json
    uri = task_artifact_uri(ctx.org_id, ctx.job_id, ctx.task_id, ctx.attempt_id, "shot_plan.json")
    assert data["plan_ref"]["uri"] == uri and out.output_refs[0].uri == uri
    raw = w.blobs.data[uri]
    assert hashlib.sha256(raw).hexdigest() == data["plan_ref"]["sha256"]
    blob = json.loads(raw)
    assert "plan_ref" not in blob and blob["views"]["agent_08_shots"]
    doc = ShotPlanDocument.model_validate(blob)
    assert {k: v for k, v in blob.items() if k not in ("shots", "overlays")} == {
        k: v for k, v in data.items() if k != "plan_ref"
    }
    # Agent 05's reserved values are read as written (hook / null), not re-attributed
    sections = {s.section_id for s in doc.shots}
    assert sections == {"hook", None, "sec1", "sec2"}


def test_overlay_template_refs_are_template_ids_and_end_screen_spans_the_tail() -> None:
    w = World()
    task, ctx = build(w)
    out = worker(w).run(task_input=task, ctx=ctx)
    data = data_of(out)
    blob = json.loads(w.blobs.data[data["plan_ref"]["uri"]])
    overlays = blob["overlays"]
    assert overlays and all(o["template_ref"] for o in overlays)  # never null
    by_kind = {o["kind"]: o for o in overlays}
    assert by_kind["BRAND_STING"]["template_ref"] == "sting_a"
    assert by_kind["DISCLAIMER_CARD"]["template_ref"] == "disclaimer_card"
    end = by_kind["END_SCREEN"]
    assert end["template_ref"] == "end_screen"
    assert (end["start_ms"], end["end_ms"]) == (data["content_end_ms"], data["total_duration_ms"])
    assert {o["kind"] for o in overlays} <= {k.value for k in OverlayKind}


def test_second_iteration_reads_the_previous_plan_from_its_blob() -> None:
    w = World()
    task, ctx = build(w)
    first = worker(w).run(task_input=task, ctx=ctx)
    ref = data_of(first)["plan_ref"]
    prev = HashedRef(uri=ref["uri"], sha256=ref["sha256"])
    task2, ctx2 = build(w, iteration=1, previous=prev)
    # same job / task / blobs: only the attempt differs; the document of attempt 1 is reused
    w2 = w
    out = worker(w2).run(task_input=task2, ctx=ctx2)
    assert out.status is OutputStatus.SUCCEEDED, out.error


def test_input_invalid_error_object_validates_with_typed_violations() -> None:
    w = World()
    task, ctx = build(w)
    data = dict(task.payload.data or {})
    data["verification_ref"] = {**data["verification_ref"], "verified_script_sha256": "e" * 64}
    bad = task.model_copy(update={"payload": task.payload.model_copy(update={"data": data})})
    out = worker(w).run(task_input=bad, ctx=ctx)
    assert out.status is OutputStatus.REJECTED and out.payload is None
    validate_task_output(out.to_doc(), version="1.0.0")
    assert out.error is not None and out.error.code == "PERMANENT.INPUT_INVALID"
    items = out.error.details.violations or ()
    assert [v.keyword for v in items][:1] == ["SCRIPT_HASH_MISMATCH"]
    assert all(v.message for v in items)


def test_payload_schema_violations_are_typed_items() -> None:
    w = World()
    task, ctx = build(w)
    data = {**(task.payload.data or {}), "iteration": -1}
    bad = task.model_copy(update={"payload": task.payload.model_copy(update={"data": data})})
    out = worker(w).run(task_input=bad, ctx=ctx)
    assert out.status is OutputStatus.REJECTED
    validate_task_output(out.to_doc(), version="1.0.0")
    assert out.error is not None and out.error.details.violations


def test_ctx_must_match_the_task_input() -> None:
    w = World()
    task, ctx = build(w)
    other = World()
    _, other_ctx = build(other)
    out = worker(w).run(task_input=task, ctx=other_ctx)
    assert out.status is OutputStatus.REJECTED
    assert out.error is not None and out.error.code == "PERMANENT.TENANT_MISMATCH"
    assert w.blobs.data and not any("shot_plan.json" in u for u in w.blobs.data)
    assert ctx.org_id == w.org


def test_foreign_tenant_ref_is_refused_before_any_read() -> None:
    w = World()
    task, ctx = build(w)
    data = dict(task.payload.data or {})
    foreign = f"amw-blob://{ORG.new()}/jobs/{w.job}/tasks/script.json"
    data["script_ref"] = {**data["script_ref"], "uri": foreign}
    bad = task.model_copy(update={"payload": task.payload.model_copy(update={"data": data})})
    out = worker(w).run(task_input=bad, ctx=ctx)
    assert out.status is OutputStatus.REJECTED
    assert out.error is not None and out.error.code == "PERMANENT.CROSS_TENANT_REF"


def test_brand_kit_uri_instead_of_a_template_id_is_refused() -> None:
    w = World()
    task, ctx = build(w)
    ports = Ports({"intro_ref": "amw-blob://x/y", "intro_duration_ms": 10})
    out = worker(w, ports).run(task_input=task, ctx=ctx)
    assert out.status is OutputStatus.REJECTED
    assert out.error is not None and out.error.details.violations
    assert out.error.details.violations[0].keyword == "BRAND_TEMPLATE_ID"


def test_missing_llm_call_budget_is_config_invalid() -> None:
    w = World()
    task, ctx = build(w)
    budget = task.resource_budget.model_copy(update={"max_llm_calls": None})
    out = worker(w).run(task_input=task.model_copy(update={"resource_budget": budget}), ctx=ctx)
    assert out.error is not None and out.error.code == "PERMANENT.CONFIG_INVALID"


def test_input_model_is_closed() -> None:
    with pytest.raises(ValueError, match="validation error"):
        ShotPlanInput.model_validate({"unknown": 1})
