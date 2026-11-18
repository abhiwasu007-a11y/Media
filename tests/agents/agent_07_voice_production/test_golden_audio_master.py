"""G-01: the deterministic ``audio_master`` dataset (34 cases) against the stage with a
descriptor-driven FFmpeg stub (``stub`` measurement mode of the dataset README).

Harness notes (not a weakening of any assertion):
* AM-30 expects an FFmpeg crash "during pass 2", but a case with the given codec model would
  finish in pass 1; the harness gives that case a first-pass codec overshoot of 0.6 dB so that a
  second pass exists, then asserts the resume from ``master.pass_1`` on retry.
* AM-17, AM-18, AM-19 are 3B music cases (D6): music mixing is not implemented in 3A.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from agent_07_voice_production.admission import TASK_MASTER, AdmissionState, is_admitted
from amw_core.contracts.task_output import TaskOutput, gate_failures
from amw_core.enums import OutputStatus
from amw_core.errors import ConfigInvalidError
from tests.agents.agent_07_voice_production.master_world import MasterWorld, build
from tests.agents.agent_07_voice_production.support import config

ROOT = Path(__file__).resolve().parents[3]
CASES = [
    json.loads(line)
    for line in (ROOT / "docs/v4/evals/agent_07_voice_production/audio_master/cases.jsonl")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip()
]
NOT_RUN = {
    "AM-17": "3B music mix (D6, CCR-007): only the optional-input hook exists in 3A",
    "AM-18": "3B music mix (D6, CCR-007): only the optional-input hook exists in 3A",
    "AM-19": "3B music mix (D6, CCR-007): only the optional-input hook exists in 3A",
}
pytestmark = [pytest.mark.integration]


def _assert_success(case: dict[str, Any], world: MasterWorld, out: TaskOutput) -> None:
    exp = case["expected"]
    assert out.payload is not None
    assert out.payload.data is not None
    data = out.payload.data
    assert data["gate_verdict"] == exp["gate_verdict"]
    assert [g["check_id"] for g in data["gate_reasons"]] == exp["gate_reasons"]
    failing = [r.check_id for r in gate_failures(out)]
    assert failing == exp["gate_reasons"]  # rule 4: the verdict echoes the results
    by_id = {r.check_id: r for r in out.validation_results}
    for check_id, verdict in exp.get("validation", {}).items():
        assert by_id[check_id].verdict.value == verdict, check_id
    for check_id, is_gate in exp.get("gate_results", {}).items():
        assert by_id[check_id].gate is is_gate, check_id
    for check_id, remedy in exp.get("remedy_stage_id", {}).items():
        assert by_id[check_id].remedy_stage_id == remedy
    for r in out.validation_results:  # 03 5.2: remedy only on failing gate results
        assert (r.remedy_stage_id is not None) == (r.gate and r.verdict.value == "FAIL")
    if "next_action_reason" in exp:
        assert out.next_action.reason == exp["next_action_reason"]
    assert out.status is OutputStatus.SUCCEEDED  # never INCOMPLETE_OUTPUT for a failed gate
    post_tp = data["codec_verification"]["post_codec"]["true_peak_dbtp"]
    if data["gate_verdict"] == "PASSED":
        assert post_tp <= exp["post_true_peak_le_dbtp"]
    assert data["master"]["sample_rate_hz"] == exp["master_sample_rate_hz"]
    assert data["master"]["channels"] == exp["master_channels"]
    assert data["measurements"]["duration_delta_samples"] == exp["duration_delta_samples"] == 0
    profile = exp["codec_profile"]
    cv = data["codec_verification"]
    assert (cv["codec"], cv["profile"], cv["sample_rate_hz"], cv["channels"]) == (
        profile["codec"],
        profile["profile"],
        profile["sample_rate_hz"],
        profile["channels"],
    )
    assert cv["bitrate_bps"] >= profile["bitrate_ge_bps"]
    m = data["mastering"]
    if "gain_db_first_pass" in exp:
        assert world.ffmpeg.renders[0]["gain"] == pytest.approx(
            exp["gain_db_first_pass"], abs=0.001
        )
    if "passes" in exp:
        assert m["passes"] == exp["passes"]
    if "passes_ge" in exp:
        assert m["passes"] >= exp["passes_ge"]
    assert m["passes"] <= world.deps.config.max_passes
    if "limiter_engaged" in exp:
        assert (m["limiter_gain_reduction_db"] > 0) is exp["limiter_engaged"]
    if "limiter_gain_reduction_db_gt" in exp:
        assert m["limiter_gain_reduction_db"] > exp["limiter_gain_reduction_db_gt"]
    if "limiter_ceiling_dbtp_final" in exp:
        assert m["limiter_ceiling_dbtp"] == pytest.approx(exp["limiter_ceiling_dbtp_final"])
    if "integrated_abs_error_le_lu" in exp:
        loud = data["codec_verification"]["post_codec"]["integrated_lufs"]
        assert abs(loud - exp["post_integrated_target_lufs"]) <= exp["integrated_abs_error_le_lu"]
    if exp.get("music_offset_db_between"):  # pragma: no cover - 3B
        raise AssertionError("3B case reached the 3A harness")
    assert world.master_written()


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_case(case: dict[str, Any], tmp_path: Path) -> None:
    cid = case["case_id"]
    if cid in NOT_RUN:
        pytest.skip(NOT_RUN[cid])
    exp = case["expected"]
    if cid == "AM-12":  # the spec cannot be loosened: the configuration is refused, no master
        with pytest.raises(ConfigInvalidError) as err:
            config(min_bitrate_bps=case["input"]["fixtures"]["config"]["min_bitrate_bps"])
        assert err.value.code == exp["error_code"]
        return
    if cid == "AM-24":  # admission: not claimed in market hours, no attempt, nothing touched
        state = AdmissionState(**case["input"]["fixtures"]["admission"])
        assert is_admitted(TASK_MASTER, state) is exp["admitted"]
        assert is_admitted("agent_07.voice_synthesis", state) is True  # the light step still runs
        return
    world = build(case, tmp_path)
    out = world.run()
    if "status" in exp and out.status.value != exp["status"]:
        raise AssertionError(f"{cid}: status {out.status.value} != {exp['status']} ({out.error})")
    if cid == "AM-29":
        latest = world.checkpoints.latest(_tx(world), _task(world))
        assert latest is not None
        assert latest.checkpoint.step_key == exp["checkpoint_step_key"]
        assert out.next_action.wait_reason is not None
        assert out.next_action.wait_reason.value == exp["wait_reason"]
        assert not world.master_written()
        return
    if out.status is OutputStatus.FAILED:
        assert out.error is not None
        assert out.error.code == exp["error_code"]
        assert out.error.retryable is exp.get("retryable", out.error.retryable)
        assert not world.master_written()
        assert exp["gate_verdict"] is None
        if cid == "AM-30":  # retry resumes from the pass-1 checkpoint with no partial file
            latest = world.checkpoints.latest(_tx(world), _task(world))
            assert latest is not None
            assert latest.checkpoint.step_key == exp["resume_from"]
            world.ffmpeg.faults.clear()
            renders_before = len(world.ffmpeg.renders)
            again = world.run()
            assert again.status is OutputStatus.SUCCEEDED
            assert len(world.ffmpeg.renders) == renders_before + 1  # only pass 2 was rendered
            assert world.ffmpeg.renders[-1]["ceiling"] == pytest.approx(-2.0)
        return
    _assert_success(case, world, out)


def _ctx(world: MasterWorld) -> Any:
    from amw_core.ids import ActorRef, OrgId
    from amw_core.interfaces.tenancy_context import TenantContext

    return TenantContext(OrgId(world.task_input.org_id), ActorRef("agent_07"))


def _tx(world: MasterWorld) -> Any:
    from amw_core.testing.memory import MemoryTransaction

    return MemoryTransaction(_ctx(world))


def _task(world: MasterWorld) -> Any:
    return world.task_input.task_id


def test_dataset_is_complete() -> None:
    assert len(CASES) == 34
    assert set(NOT_RUN) <= {c["case_id"] for c in CASES}
