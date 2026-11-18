"""``agent_10.technical_qc`` against the in-memory fakes: gate, evidence, persistence, guards."""

import json
from pathlib import Path
from typing import Any

import pytest

from agent_10_video_editor.contracts import EvidenceManifest, TechnicalQcOutput
from agent_10_video_editor.guard import LocalTime
from agent_10_video_editor.qc.gate import PROFILE_CHECKS
from agent_10_video_editor.qc.selftest import SelfTestCase, SelfTestRecord
from agent_10_video_editor.qc.stage import QcStage
from amw_core.contracts.task_output import TaskOutput
from amw_core.enums import OutputStatus, RenderStatus
from amw_core.errors import AgentCrashError, IncompleteOutputError
from tests.agents.agent_10_video_editor.support import (
    World,
    licensed_snapshot,
    payload_data,
    run_chain,
)


class _SelfTests:
    def __init__(self, passed: bool = True) -> None:
        self._passed = passed

    def record_for(self, build_id: str) -> SelfTestRecord:
        return SelfTestRecord(
            build_id, (SelfTestCase("clean", "PASS", "PASS" if self._passed else "FAIL"),)
        )


def _qc(world: World, chain: dict[str, Any], selftests: _SelfTests | None = None) -> TaskOutput:
    return QcStage(world.deps(), selftests or _SelfTests()).run(chain["qc_input"], world.attempt)


@pytest.mark.unit
def test_gate_passes_with_licences_and_persists_every_profile_check(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.licences.snapshot_value = licensed_snapshot(world)
    chain = run_chain(world)
    out = _qc(world, chain)
    assert out.status is OutputStatus.SUCCEEDED
    data = TechnicalQcOutput.model_validate(payload_data(out))
    assert data.gate_verdict == "PASSED"
    assert data.failures == ()
    gate_ids = {r.check_id for r in out.validation_results if r.gate}
    assert gate_ids == set(PROFILE_CHECKS)  # every check of the profile has a gate result
    persisted = {r.check_id for r in world.qc_results.rows.values()}
    assert persisted == set(PROFILE_CHECKS)
    row = world.renders.rows[(world.org, payload_data(chain["render"])["render_id"])]
    assert row.status is RenderStatus.QC_PASSED
    assert row.true_peak_dbtp == -1.5
    assert row.integrated_lufs == -14.0
    # measured values are recorded: never a silent default
    by_id = {r.check_id: r for r in out.validation_results}
    assert by_id["qc.audio.true_peak"].measured == -1.5
    assert by_id["qc.audio.integrated_lufs"].verdict == "WARN"
    assert by_id["qc.audio.integrated_lufs"].threshold is None
    assert not by_id["qc.audio.integrated_lufs"].blocking
    assert by_id["qc.audio.music_bed_offset"].verdict == "SKIPPED"
    assert by_id["qc.audio.bitrate"].measured == 384000
    assert all(
        r.blocking
        for r in out.validation_results
        if r.gate and r.verdict in ("PASS", "FAIL") and r.check_id == "qc.audio.true_peak"
    )


@pytest.mark.unit
def test_failed_gate_is_a_succeeded_task_with_remedy_stage(tmp_path: Path) -> None:
    world = World(tmp_path)  # no ledger rows at all: licence completeness fails
    chain = run_chain(world)
    out = _qc(world, chain)
    assert out.status is OutputStatus.SUCCEEDED
    data = TechnicalQcOutput.model_validate(payload_data(out))
    assert data.gate_verdict == "FAILED"
    failure = next(f for f in data.failures if f.check_id == "qc.licence.completeness")
    assert failure.remedy_stage == "s08_assets"
    assert set(failure.shot_ids) == {"sh01", "sh02", "sh03", "sh04"}
    result = next(r for r in out.validation_results if r.check_id == "qc.licence.completeness")
    assert result.gate
    assert result.blocking
    assert result.verdict == "FAIL"
    assert result.remedy_stage_id == "s08_assets"
    assert out.next_action.type.value == "CONTINUE"
    assert "gate FAILED" in out.next_action.reason
    row = world.renders.rows[(world.org, payload_data(chain["render"])["render_id"])]
    assert row.status is RenderStatus.QC_FAILED


@pytest.mark.unit
def test_evidence_manifest_is_the_single_document_for_agent_16(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.cfg = world.cfg.model_copy(
        update={"qc": world.cfg.qc.model_copy(update={"sample_frames_per_min": 15})}
    )
    world.licences.snapshot_value = licensed_snapshot(world)
    chain = run_chain(world)
    out = _qc(world, chain)
    data = TechnicalQcOutput.model_validate(payload_data(out))
    manifest = EvidenceManifest.model_validate_json(
        world.storage.blobs[data.evidence.manifest_ref.uri]
    )
    assert [f.frame_id for f in manifest.frames][:3] == ["f01", "f02", "f03"]
    assert manifest.contact_sheet == data.evidence.contact_sheet_ref
    assert [f.sha256 for f in manifest.frames] == [
        r.sha256 for r in data.evidence.sample_frames_ref
    ]
    assert [f.uri for f in manifest.frames] == [r.uri for r in data.evidence.sample_frames_ref]
    indices = [f.frame_index for f in manifest.frames]
    assert indices == sorted(indices)
    assert indices[0] == 0
    assert all(f.shot_id in {"sh01", "sh02", "sh03", "sh04"} for f in manifest.frames)
    assert manifest.total_frames == 480
    assert manifest.fps_num == 30
    for frame in manifest.frames:  # every sha256 equals the stored blob's hash
        import hashlib

        assert hashlib.sha256(world.storage.blobs[frame.uri]).hexdigest() == frame.sha256
    assert "evidence_manifest" in data.evidence.manifest_ref.uri
    assert json.loads(world.storage.blobs[data.evidence.loudness_series_ref.uri])["hz"] == 1


@pytest.mark.failure_injection
def test_unparseable_measurement_is_never_pass(tmp_path: Path) -> None:
    world = World(tmp_path)
    chain = run_chain(world)
    world.runner.detector_text["ebur128"] = (
        "[Parsed_ebur128_0 @ 0x1] t: 3.0 M: -20 S: -19 I: -14.1 LUFS"
    )
    with pytest.raises(AgentCrashError):
        _qc(world, chain)
    assert not world.qc_results.rows  # nothing persisted as PASS


@pytest.mark.failure_injection
def test_missing_true_peak_block_is_agent_crash(tmp_path: Path) -> None:
    world = World(tmp_path)
    chain = run_chain(world)
    text = world.runner.detector_text["ebur128"]
    world.runner.detector_text["ebur128"] = text[: text.index("  True peak:")]
    with pytest.raises(AgentCrashError):
        _qc(world, chain)


@pytest.mark.unit
def test_hash_chain_mismatch_is_incomplete_output(tmp_path: Path) -> None:
    world = World(tmp_path)
    chain = run_chain(world)
    bad = chain["qc_input"].model_copy(
        update={
            "payload": chain["qc_input"].payload.model_copy(
                update={"data": {**payload_data(chain["qc_input"]), "render_sha256": "5" * 64}}
            )
        }
    )
    with pytest.raises(IncompleteOutputError):
        QcStage(world.deps(), _SelfTests()).run(bad, world.attempt)


@pytest.mark.unit
def test_failed_selftest_blocks_qc(tmp_path: Path) -> None:
    world = World(tmp_path)
    chain = run_chain(world)
    from amw_core.errors import ConfigInvalidError

    with pytest.raises(ConfigInvalidError):
        _qc(world, chain, _SelfTests(passed=False))


@pytest.mark.unit
def test_black_run_is_reported_with_shot_id_and_remedy(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.cfg = world.cfg.model_copy(
        update={"qc": world.cfg.qc.model_copy(update={"black_calibrated": True})}
    )
    world.licences.snapshot_value = licensed_snapshot(world)
    chain = run_chain(world)
    world.runner.detector_text["blackdetect"] = (
        "[blackdetect @ 0x1] black_start:5 black_end:7.5 black_duration:2.5\n"
    )
    out = _qc(world, chain)
    data = TechnicalQcOutput.model_validate(payload_data(out))
    failure = next(f for f in data.failures if f.check_id == "qc.video.black_frames")
    assert failure.remedy_stage == "s08_assets"
    assert failure.shot_ids == ("sh02",)
    assert data.gate_verdict == "FAILED"
    assert data.measurements.black_runs == 1


@pytest.mark.unit
def test_qc_is_blocked_inside_market_hours(tmp_path: Path) -> None:
    world = World(tmp_path)
    chain = run_chain(world)
    world.probe.now = LocalTime.parse("MON", "09:30")
    out = _qc(world, chain)
    assert out.status is OutputStatus.SUSPENDED
    assert not world.qc_results.rows


@pytest.mark.failure_injection
def test_self_drain_timer_stops_a_running_detector_pass(tmp_path: Path) -> None:
    """FI-13 for QC: the timer fires during a decode pass -> stop, checkpoint, SUSPENDED."""
    world = World(tmp_path)
    world.licences.snapshot_value = licensed_snapshot(world)
    chain = run_chain(world)
    calls = {"n": 0}
    real_run = world.runner.run

    def run(argv: Any, *, cwd: Any, limits: Any, stop: Any = None) -> Any:
        if "blackdetect" in " ".join(argv):
            calls["n"] += 1
            world.timers.fire_all()  # act_by reached while the pass is running
            from agent_10_video_editor.ffmpeg import ProcessResult

            return (
                ProcessResult(-15, killed_by="SIGTERM")
                if stop and stop()
                else real_run(argv, cwd=cwd, limits=limits, stop=stop)
            )
        return real_run(argv, cwd=cwd, limits=limits, stop=stop)

    world.runner.run = run  # type: ignore[method-assign]
    out = _qc(world, chain)
    assert calls["n"] == 1
    assert out.status is OutputStatus.SUSPENDED
    assert out.next_action.wait_reason is not None
    assert not world.qc_results.rows  # nothing persisted from a half-finished QC


@pytest.mark.unit
def test_qc_and_subtitle_audit_actions(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.licences.snapshot_value = licensed_snapshot(world)
    chain = run_chain(world)
    _qc(world, chain)
    assert (
        world.audit.actions[-2:] == ["subtitles.completed", "qc.completed"]
        or "qc.completed" in world.audit.actions
    )
    assert "subtitles.completed" in world.audit.actions
    failing = World(tmp_path / "f")
    chain2 = run_chain(failing)
    _qc(failing, chain2)
    assert "qc.gate_failed" in failing.audit.actions
