"""PASS6-J: the ``TaskWorker`` entry point, core storage paths, returned failures (CCR-203,
CCR-208, CCR-210)."""

import dataclasses
import inspect
from pathlib import Path
from typing import Any

import pytest

from agent_11_thumbnail_design.stage import ThumbnailStage
from amw_core.contracts.error import ErrorObject
from amw_core.contracts.task_output import TaskOutput
from amw_core.enums import OutputStatus
from amw_core.errors import (
    InputInvalidError,
    QualityRepeatedFailureError,
    SchemaInvalidError,
    TenantMismatchError,
)
from amw_core.exec_context import ExecContext
from amw_core.ids import JOB, TASK, Prefix, new_id
from amw_core.interfaces.worker import TaskWorker
from amw_core.storage.local import LocalDiskStorage
from amw_core.tenancy.storage_paths import check_jobs_subpath
from tests.agents.agent_11_thumbnail_design.env import (
    Env,
    err_of,
    exec_ctx,
    make_env,
    run_att,
    violation_keys,
)


class _SeededThenDisk:
    """Seeded input blobs are read from the fake; everything the stage writes (and every read of
    it) goes to the real ``LocalDiskStorage``, which refuses a non-03-section-8 path."""

    def __init__(self, seeds: Any, disk: LocalDiskStorage) -> None:
        self._seeds, self._disk = seeds, disk

    def _target(self, uri: Any) -> Any:
        return self._seeds if uri in self._seeds.blobs else self._disk

    def blob_uri(self, context: Any, area: str, path: str) -> Any:
        return self._disk.blob_uri(context, area, path)

    def put(self, context: Any, uri: Any, stream: Any) -> Any:
        return self._disk.put(context, uri, stream)

    def get(self, context: Any, uri: Any, expected_sha256: str) -> Any:
        return self._target(uri).get(context, uri, expected_sha256)

    def head(self, context: Any, uri: Any) -> Any:
        return self._target(uri).head(context, uri)

    def list_prefix(self, context: Any, org_id: Any, area: str) -> Any:
        return self._disk.list_prefix(context, org_id, area)


def _on_disk(env: Env, tmp_path: Path) -> Env:
    storage = _SeededThenDisk(env.storage, LocalDiskStorage(tmp_path / "blobs"))
    deps = dataclasses.replace(env.stage.d, storage=storage)
    return dataclasses.replace(env, stage=ThumbnailStage(deps))


def _written(env: Env) -> list[str]:
    return sorted(str(u) for u in env.storage.blobs)


def test_the_stage_satisfies_the_task_worker_protocol() -> None:
    assert [*inspect.signature(ThumbnailStage.run).parameters] == ["self", "task_input", "ctx"]
    assert issubclass(ThumbnailStage, TaskWorker)
    assert ExecContext.__module__ == "amw_core.exec_context"


@pytest.mark.tenancy
def test_a_context_of_another_org_job_or_task_is_a_tenant_mismatch() -> None:
    env = make_env()
    good = exec_ctx(env.ti)
    other_task = dataclasses.replace(good, task_id=TASK.validate(new_id(Prefix.TASK)))
    other_job = dataclasses.replace(good, job_id=JOB.validate(new_id(Prefix.JOB)))
    other_org = env.ti.model_copy(update={"org_id": "org_01939e5a-7c3b-7d1e-8a4f-0123456789cd"})
    for ti, ctx in ((env.ti, other_task), (env.ti, other_job), (other_org, good)):
        out = env.stage.run(ti, ctx)
        e = err_of(out, TenantMismatchError)
        assert out.status is OutputStatus.REJECTED
        assert e.attempt_no == 0
    assert env.llm.calls == 0
    assert env.audit.entries == []
    assert not [u for u in env.storage.blobs if "/jobs/" in u]  # nothing written


def test_every_write_is_a_core_path_and_accepted_by_the_real_backend(tmp_path: Path) -> None:
    env = _on_disk(make_env(owner_assets=1), tmp_path)
    out = run_att(env, env.ti, "att_1")
    assert out.status is OutputStatus.SUCCEEDED
    ctx = exec_ctx(env.ti, "att_1")
    root = tmp_path / "blobs"
    files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert files
    for rel in files:
        path = rel.split("/", 2)[2]  # <org dir>/jobs/<rest>
        assert rel.split("/", 2)[1] == "jobs"
        check_jobs_subpath(path)
    art = f"{ctx.job_id}/tasks/{ctx.task_id}/attempts/{ctx.attempt_id}/artifacts/"
    ck = f"{ctx.job_id}/checkpoints/{ctx.task_id}/"
    assert sum(1 for f in files if art in f and f.endswith(".png")) == 3
    assert any(
        f.startswith(tuple(f"{d}/jobs/{art}" for d in [files[0].split("/")[0]])) for f in files
    )
    assert any(f"/jobs/{ck}CK1_OPTIONS-" in f for f in files)
    assert any(f"/jobs/{art}thumbnails/manifest-" in f for f in files)
    assert any(f"/jobs/{art}llm/concepts-1-" in f for f in files)
    for ref in out.output_refs:
        assert f"/{art}" in ref.uri


def test_a_dlq_replay_in_a_new_attempt_gives_identical_files_and_no_second_row() -> None:
    env = make_env(owner_assets=1)
    first = run_att(env, env.ti, "att_1")
    assets, ledger, cost_rows, calls = (
        len(env.repo.image_inserts),
        len(env.repo.ledger_inserts),
        len(env.costs.rows),
        env.llm.calls,
    )
    second = run_att(env, env.ti, "att_2")
    assert first.status is second.status is OutputStatus.SUCCEEDED
    assert (len(env.repo.image_inserts), len(env.repo.ledger_inserts)) == (assets, ledger)
    assert (len(env.costs.rows), env.llm.calls) == (cost_rows, calls)
    pngs = [(r.sha256, r.size_bytes) for r in first.output_refs if r.media_type == "image/png"]
    assert pngs == [
        (r.sha256, r.size_bytes) for r in second.output_refs if r.media_type == "image/png"
    ]
    assert len(pngs) == 3
    assert {r.uri for r in first.output_refs}.isdisjoint({r.uri for r in second.output_refs})
    d1, d2 = first.payload, second.payload
    assert d1 is not None
    assert d2 is not None
    assert d1.data is not None
    assert d2.data is not None
    assert d1.data["set_sha256"] == d2.data["set_sha256"]
    # the second attempt's files sit under its own attempt path
    a2 = str(exec_ctx(env.ti, "att_2").attempt_id)
    assert all(f"/attempts/{a2}/artifacts/" in r.uri for r in second.output_refs)
    # the recorded concept response is read back from the first attempt's path, not rewritten
    a1 = str(exec_ctx(env.ti, "att_1").attempt_id)
    assert not any(f"/attempts/{a2}/artifacts/llm/" in u for u in _written(env))
    assert any(f"/attempts/{a1}/artifacts/llm/" in u for u in _written(env))


def test_an_input_invalid_error_object_validates_and_is_returned() -> None:
    env = make_env()
    data: Any = dict(env.ti.payload.data or {})
    data["variant_count"] = "many"
    ti = env.ti.model_copy(update={"payload": env.ti.payload.model_copy(update={"data": data})})
    out = run_att(env, ti, "att_1")
    e = err_of(out, SchemaInvalidError)
    assert out.status is OutputStatus.REJECTED
    assert violation_keys(e) == ["FIELD_INVALID"]
    assert e.details.violations is not None
    assert e.details.violations[0].path == "/variant_count"
    ErrorObject.model_validate(e.model_dump(mode="json"))
    TaskOutput.model_validate(out.model_dump(mode="json"))
    over = make_env(agent_11__max_variants=2)
    e2 = err_of(run_att(over, over.ti, "att_1"), InputInvalidError)
    assert violation_keys(e2) == ["VARIANT_COUNT"]
    ErrorObject.model_validate(e2.model_dump(mode="json"))


def test_a_failure_after_a_paid_call_reports_the_real_cost() -> None:
    env = make_env(agent_11__legibility__min_contrast_ratio=21.0)
    out = run_att(env, env.ti, "att_1")
    err_of(out, QualityRepeatedFailureError)
    assert out.status is OutputStatus.FAILED
    assert env.llm.calls == 1
    assert out.resource_usage.llm_calls == 1
    assert out.resource_usage.cost_estimate_micros == sum(
        r.entry.amount_micros for r in env.costs.rows
    )
    assert out.resource_usage.cost_entry_ids == tuple(str(r.id) for r in env.costs.rows)
    assert out.output_refs == ()


def test_a_bug_inside_the_stage_is_returned_as_agent_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = make_env()

    def boom(*_a: Any, **_k: Any) -> Any:
        raise ZeroDivisionError("secret detail")

    monkeypatch.setattr(env.repo, "script_view", boom)
    out = run_att(env, env.ti, "att_1")
    assert out.status is OutputStatus.FAILED
    assert out.error is not None
    assert out.error.code == "AGENT.CRASH"
    assert "secret detail" not in out.error.message
