"""Failure injection (FI-02, FI-03, FI-10..FI-12), error mapping (U-103..U-109), runner."""

import signal
import sys
from pathlib import Path

import pytest

from agent_10_video_editor.errors import violations_of
from agent_10_video_editor.ffmpeg import (
    ProcessFfmpegRunner,
    ProcessResult,
    RunLimits,
    error_for_result,
)
from agent_10_video_editor.render import RenderStage
from amw_core.enums import OutputStatus
from amw_core.errors import (
    AgentHangError,
    DiskFullError,
    InputInvalidError,
    OomError,
    RenderCrashError,
)
from tests.agents.agent_10_video_editor.support import World, payload_data


class _Died(Exception):  # noqa: N818 - simulated process death, not an error class
    """The worker process dies at this point (nothing after it runs)."""


def _final_bytes(world: World, out: object) -> bytes:
    return world.storage.blobs[payload_data(out)["render_ref"]["uri"]]


@pytest.mark.failure_injection
def test_fi02_kill_between_segment_rename_and_checkpoint_adopts_the_orphan(tmp_path: Path) -> None:
    reference = World(tmp_path / "ref", shots=4)
    ref_out = RenderStage(reference.deps()).execute(reference.render_input(), reference.attempt)
    world = World(tmp_path / "run", shots=4)

    def die_after_first_segment(uri: str) -> None:
        if "/segments/" in uri:
            world.storage.after_put = None
            raise _Died  # the blob is renamed into place, the checkpoint is never written

    world.storage.after_put = die_after_first_segment
    with pytest.raises(_Died):
        RenderStage(world.deps()).execute(world.render_input(), world.attempt)
    assert any("/segments/" in uri for uri in world.storage.blobs)
    done = RenderStage(world.deps()).execute(world.render_input(), world.attempt)
    segs = payload_data(done)["segments"]
    assert segs["reused"] == 1
    assert segs["encoded"] == 1
    assert segs["resumed_from_checkpoint"]
    assert _final_bytes(world, done) == _final_bytes(reference, ref_out)


@pytest.mark.failure_injection
def test_fi03_a_kill_during_the_final_store_leaves_no_file_at_the_final_path(
    tmp_path: Path,
) -> None:
    reference = World(tmp_path / "ref")
    ref_out = RenderStage(reference.deps()).execute(reference.render_input(), reference.attempt)
    world = World(tmp_path / "run")

    def die(uri: str) -> None:
        if "/renders/rnd_" in uri:
            world.storage.before_put = None
            raise _Died

    world.storage.before_put = die
    with pytest.raises(_Died):
        RenderStage(world.deps()).execute(world.render_input(), world.attempt)
    assert not [u for u in world.storage.blobs if "/renders/rnd_" in u]
    assert world.renders.rows == {}
    done = RenderStage(world.deps()).execute(world.render_input(), world.attempt)
    assert done.status is OutputStatus.SUCCEEDED
    assert payload_data(done)["segments"]["reused"] == payload_data(done)["segments"]["planned"]
    assert _final_bytes(world, done) == _final_bytes(reference, ref_out)
    assert len(world.renders.rows) == 1


@pytest.mark.failure_injection
def test_fi11_a_corrupt_segment_blob_is_detected_and_reencoded(tmp_path: Path) -> None:
    world = World(tmp_path, shots=4)

    fired: list[bool] = []

    def drain(step: str) -> None:
        if step == "render.seg_0" and not fired:
            fired.append(True)
            world.probe.drain = True

    world.hook_checkpoints(drain)
    stage = RenderStage(world.deps())
    assert stage.execute(world.render_input(), world.attempt).status is OutputStatus.SUSPENDED
    first = next(u for u in world.storage.blobs if "/segments/" in u)
    world.storage.corrupt(first)
    world.probe.drain = False
    done = stage.execute(world.render_input(), world.attempt)
    assert done.status is OutputStatus.SUCCEEDED
    segs = payload_data(done)["segments"]
    assert segs["reused"] == 0
    assert segs["encoded"] == 2
    assert any(u.endswith(".r1.mp4") for u in world.storage.blobs)  # write-once: a new generation


@pytest.mark.failure_injection
def test_fi12_unreadable_input_asset_is_input_invalid_not_a_skipped_shot(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.runner.unreadable_inputs = {"in_0.png"}
    with pytest.raises(InputInvalidError) as info:
        RenderStage(world.deps()).execute(world.render_input(), world.attempt)
    assert violations_of(info.value)[0].startswith("ASSET_UNREADABLE:")
    assert world.renders.rows == {}


@pytest.mark.failure_injection
def test_fi10_crash_and_failed_verification_are_render_crashes_and_store_nothing(
    tmp_path: Path,
) -> None:
    crash = World(tmp_path / "a")
    crash.runner.crash_on_encode = {1}
    with pytest.raises(RenderCrashError):
        RenderStage(crash.deps()).execute(crash.render_input(), crash.attempt)
    assert not [u for u in crash.storage.blobs if "/segments/" in u]
    idr = World(tmp_path / "b")
    idr.runner.bad_idr = True
    with pytest.raises(RenderCrashError):
        RenderStage(idr.deps()).execute(idr.render_input(), idr.attempt)
    assert not [u for u in idr.storage.blobs if "/segments/" in u]
    # a retry after the crash resumes and completes (the bad .part was discarded)
    crash.runner.crash_on_encode = set()
    assert (
        RenderStage(crash.deps()).execute(crash.render_input(), crash.attempt).status
        is OutputStatus.SUCCEEDED
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("result", "error"),
    [
        (ProcessResult(-9, killed_by="SIGKILL"), OomError),
        (ProcessResult(-signal.SIGKILL), OomError),
        (ProcessResult(0, killed_by="TIMEOUT"), AgentHangError),
        (ProcessResult(1, stderr="write error: No space left on device"), DiskFullError),
        (ProcessResult(1, stderr="boom"), RenderCrashError),
        (ProcessResult(0), None),
        (ProcessResult(-15, killed_by="SIGTERM"), None),
    ],
)
def test_u103_u109_process_end_maps_to_the_07_codes(
    result: ProcessResult, error: type | None
) -> None:
    mapped = error_for_result(result)
    if error is None:
        assert mapped is None
    else:
        assert type(mapped) is error
    # an error never carries stderr text (section 18)
    if mapped is not None:
        assert "boom" not in mapped.message
        assert "boom" not in str(mapped.details)


@pytest.mark.unit
def test_process_runner_runs_stops_and_times_out(tmp_path: Path) -> None:
    runner = ProcessFfmpegRunner(poll_ms=5)
    ok = runner.run(
        [sys.executable, "-c", "import sys; print('out'); sys.stderr.write('err'); sys.exit(3)"],
        cwd=tmp_path,
        limits=RunLimits(),
    )
    assert (ok.exit_code, ok.stdout.strip(), ok.stderr, ok.killed_by) == (3, "out", "err", None)
    sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
    stopped = runner.run(sleeper, cwd=tmp_path, limits=RunLimits(), stop=lambda: True)
    assert stopped.killed_by == "SIGTERM"
    assert stopped.wall_ms < 10_000
    timed = runner.run(sleeper, cwd=tmp_path, limits=RunLimits(timeout_ms=100))
    assert timed.killed_by == "TIMEOUT"
    assert not list(tmp_path.glob(".std*"))  # no leftover capture files


@pytest.mark.unit
def test_scratch_is_cleaned_after_success_and_after_failure(tmp_path: Path) -> None:
    world = World(tmp_path)
    RenderStage(world.deps()).execute(world.render_input(), world.attempt)
    assert not (world.scratch / world.org.removeprefix("org_") / world.task).exists()
    crash = World(tmp_path / "x")
    crash.runner.crash_on_encode = {1}
    with pytest.raises(RenderCrashError):
        RenderStage(crash.deps()).execute(crash.render_input(), crash.attempt)
    assert not (crash.scratch / crash.org.removeprefix("org_") / crash.task).exists()


@pytest.mark.unit
def test_cost_row_is_a_render_ms_estimate_with_no_money(tmp_path: Path) -> None:
    from amw_core.enums import CostFigureKind, CostOperation, CostUnitKind

    world = World(tmp_path)
    RenderStage(world.deps()).execute(world.render_input(), world.attempt)
    (row,) = world.cost.rows
    e = row.entry
    assert (e.provider, e.operation, e.unit_kind, e.amount_micros, e.figure_kind) == (
        "ffmpeg", CostOperation.RENDER_FFMPEG, CostUnitKind.RENDER_MS, 0, CostFigureKind.ESTIMATE,
    )  # fmt: skip
    assert e.units is not None
    assert e.units >= 0
