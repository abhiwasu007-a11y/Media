"""``agent_13.file_delivery`` entry point: ExecContext check, returned failures, write-once."""

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from amw_core.contracts.common import PayloadObject, ResourceBudget
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import TaskOutput
from amw_core.enums import ComplianceVerdict, NextActionType, OutputStatus, Priority
from amw_core.exec_context import ExecContext
from amw_core.ids import ATTEMPT, CORRELATION, JOB, TASK
from amw_core.interfaces.storage import BlobUri
from amw_delivery.models import ComplianceInfo
from amw_delivery.stage import INPUT_SCHEMA, OUTPUT_SCHEMA, DeliveryStage
from tests.delivery.support import World

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 19, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self._mono = 0

    def now(self) -> datetime:
        return NOW

    def monotonic_ms(self) -> int:
        self._mono += 7
        return self._mono


def _task(w: World, data: dict[str, Any] | None, *, agent: str = "agent_13") -> TaskInput:
    return TaskInput(
        org_id=w.org, job_id=w.job, task_id=TASK.new(), project_id=None, channel_id=None,
        agent_id=agent, source_agent="agent_01", priority=Priority.NORMAL, deadline=None,
        context_refs=(),
        resource_budget=ResourceBudget(max_cost_micros=0, currency="USD", max_wall_ms=600_000),
        payload=PayloadObject(
            payload_schema=INPUT_SCHEMA,
            payload_schema_version="1.0.0",
            **({} if data is None else {"data": data}),
        ),
        correlation_id=CORRELATION.new(), idempotency_key="idk_" + "0" * 64, retry_count=0,
        schema_version="1.0.0",
    )  # fmt: skip


def _ctx(ti: TaskInput, attempt: str | None = None) -> ExecContext:
    return ExecContext.from_task_input(
        ti, attempt or ATTEMPT.new(), "agent_13", envelope_org_id=ti.org_id, stage_id="s13_deliver"
    )


def _stage(w: World, tmp_path: Path) -> DeliveryStage:
    return DeliveryStage(w.storage, _Clock(), scratch_root=tmp_path)


def _data(w: World, **over: object) -> dict[str, Any]:
    return w.inputs(**over).model_dump(mode="json")


def _failed(out: TaskOutput, status: OutputStatus, code: str) -> None:
    assert out.status is status
    assert out.error is not None
    assert out.error.code == code
    assert out.payload is None
    assert out.resource_usage.cost_estimate_micros == 0
    assert out.resource_usage.provider_calls == 0


def test_run_delivers_the_bundle_through_storage(tmp_path: Path) -> None:
    w = World(tmp_path, shorts=True)
    ti = _task(w, _data(w))
    out = _stage(w, tmp_path).run(ti, _ctx(ti))
    assert out.status is OutputStatus.SUCCEEDED
    assert out.payload is not None
    assert out.payload.payload_schema == OUTPUT_SCHEMA
    assert out.next_action.type is NextActionType.CONTINUE
    zip_ref, manifest_ref = out.output_refs
    assert f"/jobs/{w.job}/tasks/{ti.task_id}/attempts/" in zip_ref.uri
    assert out.payload.data is not None
    assert out.payload.data["zip_sha256"] == zip_ref.sha256
    assert out.payload.data["manifest_sha256"] == manifest_ref.sha256
    stored = w.storage.blobs[zip_ref.uri]
    assert len(stored) == zip_ref.size_bytes
    p = tmp_path / "got.zip"
    p.write_bytes(stored)
    with zipfile.ZipFile(p) as zf:
        assert {"video_16x9.mp4", "video_9x16.mp4", "manifest.json"} <= set(zf.namelist())
        assert json.loads(zf.read("manifest.json"))["job_id"] == w.job
    assert list(tmp_path.glob("amw-delivery-*")) == []  # scratch removed


def test_same_attempt_retry_reuses_identical_bytes(tmp_path: Path) -> None:
    w = World(tmp_path)
    ti = _task(w, _data(w))
    ctx = _ctx(ti)
    first = _stage(w, tmp_path).run(ti, ctx)
    again = _stage(w, tmp_path).run(ti, ctx)
    assert first.status is OutputStatus.SUCCEEDED
    assert again.status is OutputStatus.SUCCEEDED
    assert [r.sha256 for r in again.output_refs] == [r.sha256 for r in first.output_refs]


def test_different_bytes_at_the_same_path_are_a_conflict(tmp_path: Path) -> None:
    w = World(tmp_path)
    ti = _task(w, _data(w))
    ctx = _ctx(ti)
    first = _stage(w, tmp_path).run(ti, ctx)
    uri = first.output_refs[1].uri  # manifest.json
    w.storage.blobs[BlobUri(uri)] = b"{}"
    w.storage._recorded[uri] = "0" * 64
    out = _stage(w, tmp_path).run(ti, ctx)
    _failed(out, OutputStatus.FAILED, "PERMANENT.IDEMPOTENCY_CONFLICT")


def test_tenant_mismatch_is_returned_not_raised(tmp_path: Path) -> None:
    w = World(tmp_path)
    ti = _task(w, _data(w))
    other = _task(w, _data(w))  # another task id
    out = _stage(w, tmp_path).run(ti, _ctx(other))
    _failed(out, OutputStatus.FAILED, "PERMANENT.TENANT_MISMATCH")
    # a context built for agent_13 but a Task Input addressed to another agent
    wrong_agent = _task(w, _data(w), agent="agent_10")
    out = _stage(w, tmp_path).run(wrong_agent, _ctx(other))
    _failed(out, OutputStatus.FAILED, "PERMANENT.TENANT_MISMATCH")


def test_payload_for_another_job_is_a_tenant_mismatch(tmp_path: Path) -> None:
    w = World(tmp_path)
    data = _data(w)
    data["job_id"] = JOB.new()
    ti = _task(w, data)
    out = _stage(w, tmp_path).run(ti, _ctx(ti))
    _failed(out, OutputStatus.FAILED, "PERMANENT.TENANT_MISMATCH")


def test_bad_or_not_inline_payload_is_schema_invalid(tmp_path: Path) -> None:
    w = World(tmp_path)
    ti = _task(w, {"org_id": "x"})
    _rejected(_stage(w, tmp_path).run(ti, _ctx(ti)))
    by_ref = ti.model_copy(
        update={
            "payload": PayloadObject(
                payload_schema=INPUT_SCHEMA,
                payload_schema_version="1.0.0",
                data_ref=f"amw-blob://{w.org}/jobs/{w.job}/renders/p.json",
                data_sha256="0" * 64,
            )
        }
    )
    _rejected(_stage(w, tmp_path).run(by_ref, _ctx(ti)))


def _rejected(out: TaskOutput) -> None:
    _failed(out, OutputStatus.REJECTED, "PERMANENT.SCHEMA_INVALID")
    assert out.error is not None
    assert out.error.attempt_no == 0


def test_unauthorised_compliance_is_returned_and_leaves_nothing(tmp_path: Path) -> None:
    w = World(tmp_path)
    base = w.inputs()
    comp = ComplianceInfo(
        verdict=ComplianceVerdict.BLOCKED,
        authorised_for_delivery=False,
        authorisation_verdict_id="cvd_1",
        render_sha256=base.video_16x9.sha256,
    )
    ti = _task(w, base.model_copy(update={"compliance": comp}).model_dump(mode="json"))
    out = _stage(w, tmp_path).run(ti, _ctx(ti))
    assert out.status is OutputStatus.FAILED
    assert out.error is not None
    assert out.error.code == "PUBLISHING.NOT_AUTHORISED"
    assert out.output_refs == ()
    assert not [u for u in w.storage.blobs if "/artifacts/delivery/" in u]


def test_unexpected_exception_is_agent_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from amw_delivery import stage as stage_mod

    w = World(tmp_path)
    ti = _task(w, _data(w))

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("secret detail must not leak")

    monkeypatch.setattr(stage_mod, "build_bundle", boom)
    out = _stage(w, tmp_path).run(ti, _ctx(ti))
    assert out.status is OutputStatus.FAILED
    assert out.error is not None
    assert "secret detail" not in out.error.model_dump_json()
    assert out.next_action.type is NextActionType.RETRY
