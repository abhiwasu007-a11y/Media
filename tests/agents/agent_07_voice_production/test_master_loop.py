"""U-38...U-43: loudness solver, pass loop, gate truth table, admission, config spec lock."""

from pathlib import Path
from typing import Any

import pytest

from agent_07_voice_production import contracts as c
from agent_07_voice_production.admission import AdmissionState, is_admitted
from agent_07_voice_production.config import AgentSevenConfig
from agent_07_voice_production.master import (
    MasterRun,
    PassState,
    limiter_reduction,
    loudness_in_tolerance,
    run_passes,
    solve_gain,
)
from agent_07_voice_production.master_stage import evaluate_master, silence_findings
from agent_07_voice_production.ports import AudioAnalysis, Loudness, SilenceSpan, StreamFacts
from amw_core.contracts.task_output import ValidationResult
from amw_core.errors import ConfigInvalidError, InputInvalidError
from tests.agents.agent_07_voice_production.master_world import StubFfmpeg
from tests.agents.agent_07_voice_production.support import config

pytestmark = pytest.mark.unit


def stem(i: float | None = -20.0, tp: float | None = -0.5, **kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "duration_ms": 1000,
        "sample_rate_hz": 48_000,
        "channels": 1,
        "integrated_lufs": i,
        "true_peak_dbtp": tp,
        "lra_lu": 5.0,
        "clipping_samples": 0,
        "silence_runs": [],
        "noise_floor_dbfs": -60.0,
    }
    base.update(kw)
    return base


def analysis(ff: StubFfmpeg) -> AudioAnalysis:
    return ff.analyse(Path("x"), silence_noise_db=-50, silence_min_s=0.3)


def go(
    cfg: AgentSevenConfig,
    overshoot: list[float],
    tmp: Path,
    s: dict[str, object] | None = None,
    **kw: Any,
) -> tuple[StubFfmpeg, MasterRun]:
    ff = StubFfmpeg(s or stem(), overshoot, 384_000, [])
    return ff, run_passes(ff, stem=Path("x"), pre=analysis(ff), cfg=cfg, workdir=tmp, **kw)


def test_solver_gain_and_silent_stem() -> None:
    assert solve_gain(Loudness(-23.0, -13.0, 5.0), -14.0) == 9.0
    with pytest.raises(InputInvalidError):
        solve_gain(Loudness(None, None, None), -14.0)


def test_limiter_reduction_is_never_negative() -> None:
    assert limiter_reduction(Loudness(-20, -0.5, 5), 6.0, -1.5) == 7.0
    assert limiter_reduction(Loudness(-20, -10, 5), 6.0, -4.0) == 0.0
    assert limiter_reduction(Loudness(-20, None, 5), 6.0, -4.0) == 0.0


def test_tolerance_none_until_calibrated() -> None:
    assert loudness_in_tolerance(-14.2, config()) is None
    assert loudness_in_tolerance(-14.2, config(tolerance_lu=0.5)) is True
    assert loudness_in_tolerance(-15.0, config(tolerance_lu=0.5)) is False
    assert loudness_in_tolerance(None, config(tolerance_lu=0.5)) is False


def test_ceiling_steps_down_until_the_post_codec_peak_fits(tmp_path: Path) -> None:
    _, run = go(config(), [0.6, 0.6, 0.6], tmp_path)
    assert (run.passes, run.ceiling_dbtp, run.targets_met) == (2, -2.0, True)
    assert run.codec.post_codec.true_peak_dbtp is not None
    assert run.codec.post_codec.true_peak_dbtp <= -1.0


def test_pass_cap_ends_with_unmet_targets(tmp_path: Path) -> None:
    _, run = go(config(codec_headroom_step_db=0.1), [0.9] * 3, tmp_path)
    assert run.passes == 3
    assert not run.targets_met


def test_gain_is_corrected_when_a_tolerance_is_set(tmp_path: Path) -> None:
    # a heavy limiter pulls the loudness below target: the second pass adds the difference
    cfg = config(tolerance_lu=0.5)
    ff, run = go(cfg, [0.3, 0.3, 0.3], tmp_path, stem(-24.0, 0.0))
    assert run.passes >= 2
    assert ff.renders[1]["gain"] > ff.renders[0]["gain"]


def test_resume_continues_after_the_checkpointed_pass(tmp_path: Path) -> None:
    state = PassState(1, 6.0, -1.5, 6.0, -2.0, satisfied=False)
    ff, run = go(config(), [0.6, 0.6], tmp_path, resume=state)
    assert ff.renders[0] == {"gain": 6.0, "ceiling": -2.0}
    assert run.passes == 2
    done = PassState(1, 6.0, -1.5, 6.0, -1.5, satisfied=True)
    ff2, run2 = go(config(), [0.3], tmp_path, resume=done)
    assert ff2.renders[0]["ceiling"] == -1.5
    assert run2.passes == 1


def test_after_pass_callback_runs_before_the_pass_is_judged(tmp_path: Path) -> None:
    seen: list[PassState] = []

    def stop(state: PassState) -> None:
        seen.append(state)
        raise RuntimeError("drain")

    with pytest.raises(RuntimeError):
        go(config(), [0.3], tmp_path, after_pass=stop)
    assert seen[0].satisfied
    assert seen[0].pass_no == 1


def master_results(
    cfg: AgentSevenConfig, s: dict[str, object], overshoot: list[float], tmp: Path, **kw: Any
) -> tuple[
    dict[str, ValidationResult], tuple[ValidationResult, ...], tuple[c.MasterSilenceRun, ...]
]:
    ff, run = go(cfg, overshoot, tmp, s)
    pre = analysis(ff)
    results, runs = evaluate_master(
        cfg=cfg,
        pre=pre,
        run=run,
        pauses=kw.get("pauses", ()),
        duration_delta_samples=kw.get("delta", 0),
        music_offset=None,
        music_active=False,
    )
    return {r.check_id: r for r in results}, results, runs


def test_gate_truth_table(tmp_path: Path) -> None:
    by_id, results, _ = master_results(config(), stem(-23.0, -13.0), [0.3], tmp_path)
    gates = {r.check_id for r in results if r.gate}
    assert {
        "qc.audio.true_peak",
        "qc.audio.integrated_lufs",
        "qc.audio.sample_rate",
        "qc.audio.codec",
        "qc.audio.channels",
        "qc.audio.bitrate",
        "qc.voice.clipping",
        "a07.silence.max_run",
        "a07.master.limiter_reduction",
        "qc.audio.music_bed_offset",
    } <= gates
    assert not by_id["a07.master.duration_preserved"].gate
    assert not by_id["a07.tenant.scope"].gate
    assert gate_failures_of(results) == []
    assert integrity_of(results) == []
    assert by_id["qc.audio.integrated_lufs"].verdict.value == "WARN"
    assert not by_id["qc.audio.integrated_lufs"].blocking
    assert by_id["qc.audio.music_bed_offset"].verdict.value == "SKIPPED"


def gate_failures_of(results: tuple[ValidationResult, ...]) -> list[str]:
    return [r.check_id for r in results if r.gate and r.blocking and r.verdict.value == "FAIL"]


def integrity_of(results: tuple[ValidationResult, ...]) -> list[str]:
    return [r.check_id for r in results if r.blocking and not r.gate and r.verdict.value != "PASS"]


def test_each_gate_failure_names_the_remedy_stage(tmp_path: Path) -> None:
    cfg = config(
        max_silence_ms=2000,
        max_limiter_reduction_db=6.0,
        tolerance_lu=0.5,
        noise_floor_max_dbfs=-70.0,
    )
    s = stem(-24.0, 0.0, clipping_samples=5, silence_runs=[{"start_ms": 0, "end_ms": 3000}])
    s["duration_ms"] = 5000
    _, results, _ = master_results(cfg, s, [0.3], tmp_path)
    failing = gate_failures_of(results)
    assert {"qc.voice.clipping", "a07.silence.max_run", "a07.master.limiter_reduction"} <= set(
        failing
    )
    for r in results:
        if r.gate and r.verdict.value == "FAIL":
            assert r.remedy_stage_id == "s07_voice"
            assert r.blocking
        else:
            assert r.remedy_stage_id is None
    noise = next(r for r in results if r.check_id == "a07.noise.floor")
    assert noise.verdict.value == "FAIL"
    assert not noise.gate


def test_duration_and_caps_are_integrity_not_gate(tmp_path: Path) -> None:
    _, results, _ = master_results(config(), stem(-23.0, -13.0), [0.3], tmp_path, delta=3)
    assert integrity_of(results) == ["a07.master.duration_preserved"]
    assert gate_failures_of(results) == []


def test_silence_inside_a_deliberate_pause_is_not_dead_air() -> None:
    runs = [SilenceSpan(20_000, 23_000)]
    marked, longest = silence_findings(runs, [c.PauseSpan(start_ms=19_500, end_ms=23_500)], 100)
    assert marked[0].in_deliberate_pause
    assert longest == 0
    marked, longest = silence_findings(runs, [], 100)
    assert not marked[0].in_deliberate_pause
    assert longest == 3000


def test_admission_rule() -> None:
    quiet, market, drain = (
        AdmissionState(False, False),
        AdmissionState(True, False),
        AdmissionState(False, True),
    )
    master, voice = "agent_07.audio_master", "agent_07.voice_synthesis"
    assert is_admitted(master, quiet)
    assert is_admitted(voice, quiet)
    assert not is_admitted(master, market)
    assert is_admitted(voice, market)
    assert not is_admitted(master, drain)
    assert is_admitted(voice, drain)  # only HEAVY_CPU is held back (IT-05, ADR-012 3.3)
    assert not is_admitted("agent_07.other", quiet)


@pytest.mark.parametrize(
    "bad",
    [
        {"min_bitrate_bps": 256_000},
        {"sample_rate_hz": 44_100},
        {"true_peak_max_dbtp": -0.5},
        {"limiter_ceiling_dbtp": -0.5},
        {"music_band_min_db": -25.0},
        {"music_band_max_db": -10.0},
        {"music_band_min_db": -15.0, "music_band_max_db": -20.0},
    ],
)
def test_the_delivery_spec_cannot_be_loosened(bad: dict[str, object]) -> None:
    with pytest.raises(ConfigInvalidError):
        config(**bad)


def test_required_voice_keys() -> None:
    with pytest.raises(ConfigInvalidError):
        AgentSevenConfig.checked(config_version="x").require_voice()
    config().require_voice()
    with pytest.raises(ConfigInvalidError):
        AgentSevenConfig.checked(config_version="x", max_passes=0)
    assert StreamFacts(48_000, 1, 48_000, "x").duration_ms == 1000
