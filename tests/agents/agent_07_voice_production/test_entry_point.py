"""PASS6-F (CCR-200, CCR-203, CCR-208): the shared worker entry point, the ctx-vs-Task-Input
guard, the 03 section 8 rule 5 storage paths and the job clip cache."""

import copy
import inspect
from pathlib import Path
from typing import Any

import pytest

from agent_07_voice_production import AudioMasterStage, VoiceSynthesisStage
from amw_core.enums import OutputStatus
from amw_core.exec_context import ExecContext
from amw_core.ids import TASK, Prefix, new_id
from amw_core.interfaces import TaskWorker
from amw_core.interfaces.storage import BlobUri
from amw_core.storage.local import LocalDiskStorage
from tests.agents.agent_07_voice_production.master_world import build as build_master
from tests.agents.agent_07_voice_production.support import FakeControl, MemoryBlobs, exec_ctx
from tests.agents.agent_07_voice_production.test_contracts import cases
from tests.agents.agent_07_voice_production.voice_world import VoiceWorld
from tests.agents.agent_07_voice_production.voice_world import build as build_voice

OTHER_ATTEMPT = "att_01939e5a-7c3b-7d1e-8a4f-0123456789a2"


def _voice(case_id: str, tmp: Path) -> VoiceWorld:
    case = next(x for x in cases("voice_synthesis") if x["case_id"] == case_id)
    return build_voice(copy.deepcopy(case), tmp)


def _code(out: Any) -> str:
    assert out.error is not None
    return str(out.error.code)


@pytest.mark.parametrize("stage", [VoiceSynthesisStage, AudioMasterStage])
def test_both_stages_satisfy_the_task_worker_protocol(
    stage: type[VoiceSynthesisStage] | type[AudioMasterStage],
) -> None:
    assert [*inspect.signature(stage.run).parameters] == ["self", "task_input", "ctx"]
    assert issubclass(stage, TaskWorker)


def test_the_core_exec_context_is_the_only_context_type() -> None:
    import agent_07_voice_production.context as module

    assert module.check_ctx.__annotations__["ctx"] in ("ExecContext", ExecContext)
    assert ExecContext.__module__ == "amw_core.exec_context"


@pytest.mark.tenancy
def test_a_context_of_another_task_job_or_org_is_a_tenant_mismatch(tmp_path: Path) -> None:
    w = _voice("VS-01", tmp_path)
    good = w.ctx()
    other_task = ExecContext(
        tenant=good.tenant,
        job_id=good.job_id,
        task_id=TASK.validate(new_id(Prefix.TASK)),
        attempt_id=good.attempt_id,
        channel_id=good.channel_id,
        attempt_no=good.attempt_no,
    )
    other_job = ExecContext(
        tenant=good.tenant,
        job_id=type(good.job_id)(new_id(Prefix.JOB)),
        task_id=good.task_id,
        attempt_id=good.attempt_id,
        channel_id=good.channel_id,
        attempt_no=good.attempt_no,
    )
    other_org_input = w.task_input.model_copy(
        update={"org_id": "org_01939e5a-7c3b-7d1e-8a4f-0123456789cd"}
    )
    for stage_input, ctx in (
        (w.task_input, other_task),
        (w.task_input, other_job),
        (other_org_input, good),
    ):
        out = w.stage.run(stage_input, ctx)
        assert _code(out) == "PERMANENT.TENANT_MISMATCH"
    assert w.tts.invocations == 0
    m = build_master(copy.deepcopy(cases("audio_master")[0]), tmp_path / "m")
    mismatched = m.task_input.model_copy(update={"job_id": new_id(Prefix.JOB)})
    assert _code(m.stage.run(mismatched, m.ctx())) == "PERMANENT.TENANT_MISMATCH"
    assert not m.master_written()


def test_every_write_is_a_03_section_8_path_and_lands_where_the_rule_says(tmp_path: Path) -> None:
    w = _voice("VS-01", tmp_path)
    ctx = w.ctx()
    seeded = set(w.blobs.data)
    out = w.stage.run(w.task_input, ctx)
    assert out.status is OutputStatus.SUCCEEDED
    prefix = f"amw-blob://{ctx.org_id}/jobs/{ctx.job_id}/"
    written = [u for u in w.blobs.data if u not in seeded]
    attempt = f"{prefix}tasks/{ctx.task_id}/attempts/{ctx.attempt_id}/artifacts/"
    assert f"{attempt}narration.wav" in written
    assert f"{attempt}timeline.json" in written
    cache = [u for u in written if u.startswith(f"{prefix}cache/agent_07/")]
    clips = [u for u in cache if u.endswith(".wav")]
    sidecars = [u for u in cache if u.endswith(".audio.json")]  # CCR-269: recorded audio hash
    assert clips
    assert all(u.rsplit("/", 1)[1].startswith("s") for u in clips)
    assert sorted(u[: -len(".audio.json")] for u in sidecars) == sorted(
        u[: -len(".wav")] for u in clips
    )
    assert len(cache) + 2 == len(written)  # nothing else, in particular no s07_* path
    assert not [u for u in written if "/s07_" in u]


def test_a_drained_voice_task_checkpoints_under_checkpoints_task(tmp_path: Path) -> None:
    case = next(x for x in cases("voice_synthesis") if x["case_id"] == "VS-01")
    w = build_voice(copy.deepcopy(case), tmp_path, control=FakeControl(drain=True))
    ctx = w.ctx()
    seeded = set(w.blobs.data)
    out = w.stage.run(w.task_input, ctx)
    assert out.status is OutputStatus.SUSPENDED
    prefix = (
        f"amw-blob://{ctx.org_id}/jobs/{ctx.job_id}/checkpoints/{ctx.task_id}/{ctx.attempt_id}/"
    )
    assert [u for u in w.blobs.data if u not in seeded and u.startswith(prefix)]


def test_master_writes_artifacts_and_checkpoints_by_the_rule(tmp_path: Path) -> None:
    m = build_master(copy.deepcopy(cases("audio_master")[0]), tmp_path)
    ctx = m.ctx()
    seeded = set(m.blobs.data)
    out = m.stage.run(m.task_input, ctx)
    assert out.status is OutputStatus.SUCCEEDED
    job = f"amw-blob://{ctx.org_id}/jobs/{ctx.job_id}/"
    written = [u for u in m.blobs.data if u not in seeded]
    artifacts = f"{job}tasks/{ctx.task_id}/attempts/{ctx.attempt_id}/artifacts/"
    assert {f"{artifacts}master.wav", f"{artifacts}report.json"} <= set(written)
    assert [u for u in written if u.startswith(f"{job}checkpoints/{ctx.task_id}/")]
    assert not [u for u in written if "/s07_" in u]


class _SeededThenDisk:
    """Reads fall back to the in-memory seeds (the case inputs); every write goes to the real
    ``LocalDiskStorage``, which refuses a path that is not a 03 section 8 path."""

    def __init__(self, seeds: MemoryBlobs, disk: LocalDiskStorage) -> None:
        self.seeds, self.disk = seeds, disk
        self.wrote: list[str] = []

    def blob_uri(self, context: Any, area: str, path: str) -> BlobUri:
        return self.disk.blob_uri(context, area, path)

    def put(self, context: Any, uri: BlobUri, stream: Any) -> Any:
        info = self.disk.put(context, uri, stream)
        self.wrote.append(str(uri))
        return info

    def _side(self, uri: BlobUri) -> Any:
        return self.seeds if str(uri) in self.seeds.data else self.disk

    def get(self, context: Any, uri: BlobUri, expected_sha256: str) -> Any:
        return self._side(uri).get(context, uri, expected_sha256)

    def head(self, context: Any, uri: BlobUri) -> Any:
        return self._side(uri).head(context, uri)

    def list_prefix(self, context: Any, org_id: Any, area: str) -> Any:
        return []


def test_the_real_local_backend_accepts_every_write_of_both_stages(tmp_path: Path) -> None:
    w = _voice("VS-01", tmp_path / "v")
    ctx = w.ctx()
    store = _SeededThenDisk(w.blobs, LocalDiskStorage(tmp_path / "blobs"))
    object.__setattr__(w.stage._d, "storage", store)
    out = w.stage.run(w.task_input, ctx)
    assert out.status is OutputStatus.SUCCEEDED
    assert len(store.wrote) >= 3
    m = build_master(copy.deepcopy(cases("audio_master")[0]), tmp_path / "m")
    mstore = _SeededThenDisk(m.blobs, LocalDiskStorage(tmp_path / "mblobs"))
    object.__setattr__(m.stage._d, "storage", mstore)
    mout = m.stage.run(m.task_input, m.ctx())
    assert mout.status is OutputStatus.SUCCEEDED
    assert any(u.endswith("/artifacts/master.wav") for u in mstore.wrote)


def test_a_second_iteration_reuses_a_cached_clip_without_a_provider_call(tmp_path: Path) -> None:
    w = _voice("VS-01", tmp_path)
    first = w.stage.run(w.task_input, w.ctx())
    assert first.status is OutputStatus.SUCCEEDED
    assert w.tts.invocations > 0
    rows, calls = len(w.ledger.rows), w.tts.invocations
    # the next iteration is a new task of the same job with the same sentences
    second_input = w.task_input.model_copy(update={"task_id": new_id(Prefix.TASK)})
    second = w.stage.run(second_input, exec_ctx(second_input, OTHER_ATTEMPT))
    assert second.status is OutputStatus.SUCCEEDED
    assert w.tts.invocations == calls  # no provider call
    assert len(w.ledger.rows) == rows  # no new ledger row
    assert second.resource_usage.provider_calls == 0
    assert second.payload is not None
    assert second.payload.data is not None
    assert first.payload is not None
    assert first.payload.data is not None
    assert second.payload.data["cost"]["reused_clips"] > 0
    assert second.payload.data["cost"]["calls"] == 0
    assert first.payload.data["cost"]["reused_clips"] == 0
