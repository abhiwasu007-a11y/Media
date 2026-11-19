"""Code-review fixes of PR 42: disclosure, finance fail-closed, cost attribution, short sources,
silent audio, tenant envelope, grace-zone timer (fakes; real-FFmpeg ones: test_integration)."""

from pathlib import Path
from typing import Any

import pytest

from agent_10_video_editor.config import Placement
from agent_10_video_editor.errors import MeasurementUnavailable, violations_of
from agent_10_video_editor.guard import SelfDrainTimer
from agent_10_video_editor.inputs import AssetManifest, ScriptStrings, ShotPlan
from agent_10_video_editor.probe import SILENCE_FLOOR_DBTP, Ebur128Parser
from agent_10_video_editor.qc import checks as C  # noqa: N812
from agent_10_video_editor.qc.stage import QcStage, _word_overlap_permille
from agent_10_video_editor.subtitles import Cue
from agent_10_video_editor.taskio import ffmpeg_cost_entry
from agent_10_video_editor.testing import MemoryCostLedger, make_config
from agent_10_video_editor.timeline import TimelineCompiler
from amw_core.errors import InputInvalidError, TenantMismatchError
from amw_core.ids import CHANNEL, ORG
from tests.agents.agent_10_video_editor.support import (
    World,
    audio_master,
    licensed_snapshot,
    payload_data,
    run_chain,
)
from tests.agents.agent_10_video_editor.test_guard import CFG, _at
from tests.agents.agent_10_video_editor.test_qc_stage import _qc


def _results(world: World, chain: dict[str, Any]) -> dict[str, Any]:
    out = _qc(world, chain)
    return {r.check_id: r for r in out.validation_results}


def _chain(world: World) -> dict[str, Any]:
    world.licences.snapshot_value = licensed_snapshot(world)
    return run_chain(world)


# -- M1 disclosure -----------------------------------------------------------------------------


@pytest.mark.unit
def test_missing_disclosure_record_on_an_ai_asset_fails_the_gate(tmp_path: Path) -> None:
    world = World(tmp_path, entry_overrides={0: {"tier": "D_AI_VIDEO"}})
    by_id = _results(world, _chain(world))
    result = by_id["qc.visual.ai_disclosure_recorded"]
    assert result.verdict == "FAIL"
    assert result.blocking


@pytest.mark.unit
def test_recorded_disclosure_passes_and_a_partial_record_is_invalid(tmp_path: Path) -> None:
    record = {"is_realistic_synthetic": True, "depicts_real_person": False}
    world = World(tmp_path, entry_overrides={0: {"tier": "E_AI_STILL", "disclosure": record}})
    assert _results(world, _chain(world))["qc.visual.ai_disclosure_recorded"].verdict == "PASS"
    with pytest.raises(ValueError):  # noqa: PT011 - pydantic ValidationError
        AssetManifest.model_validate(
            {"shots": [{"shot_id": "sh01", "aspect_ratio": "16:9", "status": "SOURCED",
                        "disclosure": {"is_realistic_synthetic": True}}]}
        )  # fmt: skip


# -- M3 finance fail-closed --------------------------------------------------------------------

_CHART = {"chart": {"chart_id": "c1", "data_end_date": "2020-01-01"}}


@pytest.mark.unit
def test_finance_chart_with_unset_lag_is_a_blocking_fail(tmp_path: Path) -> None:
    world = World(tmp_path, chart=True, entry_overrides={1: _CHART})
    result = _results(world, _chain(world))["qc.visual.chart_data_age"]
    assert result.verdict == "FAIL"
    assert result.blocking
    assert result.message == "PRICE_DATA_LAG_UNSET"


@pytest.mark.unit
def test_non_finance_channel_without_charts_is_not_blocked_by_finance_rules(
    tmp_path: Path,
) -> None:
    channel = str(CHANNEL.new())
    cfg = make_config(qc={"non_finance_channel_ids": [channel]})
    world = World(tmp_path, config=cfg, channel_id=channel)
    by_id = _results(world, _chain(world))
    assert by_id["qc.visual.chart_data_age"].verdict == "WARN"
    assert not by_id["qc.visual.chart_data_age"].blocking


@pytest.mark.unit
def test_unlisted_channel_is_a_finance_channel_so_a_presenter_is_blocked(tmp_path: Path) -> None:
    person = {"is_realistic_synthetic": True, "depicts_real_person": True}
    world = World(
        tmp_path, channel_id=str(CHANNEL.new()),
        entry_overrides={0: {"tier": "D_AI_VIDEO", "disclosure": person}},
    )  # fmt: skip
    result = _results(world, _chain(world))["qc.visual.no_synthetic_presenter"]
    assert result.verdict == "FAIL"
    assert result.blocking


@pytest.mark.unit
def test_chart_check_unit_branches() -> None:
    from datetime import date

    chart = [{"element_id": "sh02", "data_end_date": "2020-01-01"}]
    today = date(2020, 6, 1)
    unset = C.qc_visual_chart_data_age(
        charts=chart, lag_days=None, today=today, finance_channel=True
    )
    assert unset.verdict == "FAIL"
    assert unset.blocking
    none = C.qc_visual_chart_data_age(charts=[], lag_days=None, today=today, finance_channel=True)
    assert none.verdict == "PASS"


# -- M2 cost ledger ----------------------------------------------------------------------------


@pytest.mark.unit
def test_cost_rows_are_attributed_and_idempotent(tmp_path: Path) -> None:
    world = World(tmp_path)
    chain = _chain(world)
    _qc(world, chain)
    rows = [r.entry for r in world.cost.rows]
    assert len(rows) == 2  # render + qc
    for entry in rows:
        assert entry.job_id == world.job
        assert entry.task_id is not None
        assert entry.attempt_id is not None
        assert entry.agent_id == "agent_10"
        assert entry.idempotency_key is not None
    assert len({e.idempotency_key for e in rows}) == 2
    ledger = MemoryCostLedger()
    entry = ffmpeg_cost_entry(
        chain["qc_input"], world.attempt, task_type="agent_10.technical_qc",
        occurred_at=world.clock.now(), units_ms=5,
    )  # fmt: skip
    tx: Any = type("Tx", (), {"context": world.ctx})()
    first = ledger.record(tx, entry)
    again = ledger.record(tx, entry)
    assert first is again
    assert len(ledger.rows) == 1


# -- M4 short source ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_source_shorter_than_its_shot_is_refused_at_compile_time() -> None:
    def build(duration_ms: int, source_in_ms: int = 0) -> Any:
        digest = "ab" * 32
        entry = {
            "shot_id": "sh01", "aspect_ratio": "16:9", "status": "SOURCED", "tier": "C_CODE_MOTION",
            "asset_id": "a1", "asset_uri": "amw-blob://org_x/assets/a1.mp4",
            "fingerprints": {"sha256": digest},
            "media": {"width_px": 1920, "height_px": 1080, "duration_ms": duration_ms,
                      "source_in_ms": source_in_ms},
        }  # fmt: skip
        plan = ShotPlan.model_validate(
            {"timing_basis": "MEASURED", "language": "mr", "aspect_ratio": "16:9",
             "total_duration_ms": 3000, "content_end_ms": 3000,
             "shots": [{"shot_id": "sh01", "start_ms": 0, "end_ms": 3000}]}
        )  # fmt: skip
        from agent_10_video_editor.inputs import AssetRecord

        assets = {"a1": AssetRecord(asset_id="a1", uri=entry["asset_uri"], sha256=digest)}
        return TimelineCompiler.compile(
            plan, AssetManifest.model_validate({"shots": [entry]}), assets,
            audio_master(3000), make_config(), "16:9",
        )  # fmt: skip

    assert build(3000).shots[0].shot_id == "sh01"
    with pytest.raises(InputInvalidError) as err:
        build(2000)
    assert "SOURCE_TOO_SHORT:sh01" in violations_of(err.value)
    with pytest.raises(InputInvalidError):
        build(3000, source_in_ms=500)  # in-point eats into the length


# -- m1..m7 ------------------------------------------------------------------------------------


@pytest.mark.unit
def test_watermark_visual_is_honestly_skipped_and_accuracy_is_computed(tmp_path: Path) -> None:
    world = World(tmp_path)
    by_id = _results(world, _chain(world))
    assert by_id["qc.watermark.visual"].verdict == "SKIPPED"
    assert by_id["qc.subtitles.accuracy"].measured == 1000
    assert by_id["qc.subtitles.accuracy"].verdict == "PASS"
    script = ScriptStrings(segments={"s1": "one two three"})
    cues = [Cue(1, 0, 1, "one two three")]
    assert _word_overlap_permille(cues, ["s1"], script) == 1000
    tampered = [Cue(1, 0, 1, "one two BUY NOW")]
    assert _word_overlap_permille(tampered, ["s1"], script) == 571
    assert C.qc_subtitles_accuracy(overlap_permille=571).verdict == "WARN"


@pytest.mark.unit
def test_process_checks_are_computed_and_tenant_needs_the_envelope(tmp_path: Path) -> None:
    world = World(tmp_path)
    chain = _chain(world)
    skipped = QcStage(world.deps(), _selftests()).execute(chain["qc_input"], world.attempt)
    by_id = {r.check_id: r for r in skipped.validation_results}
    assert by_id["a10.q.tenant"].verdict == "SKIPPED"
    assert by_id["a10.q.no_provider_call"].measured == 0
    with pytest.raises(TenantMismatchError):
        QcStage(world.deps(), _selftests()).execute(
            chain["qc_input"], world.attempt, envelope_org=str(ORG.new())
        )
    world2 = World(tmp_path / "b")
    chain2 = _chain(world2)
    checked = QcStage(world2.deps(), _selftests()).execute(
        chain2["qc_input"], world2.attempt, envelope_org=world2.org
    )
    assert {r.check_id: r for r in checked.validation_results}["a10.q.tenant"].verdict == "PASS"


def _selftests() -> Any:
    from tests.agents.agent_10_video_editor.test_qc_stage import _SelfTests

    return _SelfTests()


@pytest.mark.unit
def test_silent_audio_is_a_gate_fail_not_a_crash(tmp_path: Path) -> None:
    summary = (
        "[Parsed_ebur128_0 @ 0x1] Summary:\n\n  Integrated loudness:\n    I:         -70.0 LUFS\n"
        "    Threshold: -70.0 LUFS\n\n  Loudness range:\n    LRA:         0.0 LU\n"
        "    Threshold: -70.0 LUFS\n    LRA low:   -70.0 LUFS\n    LRA high:  -70.0 LUFS\n\n"
        "  True peak:\n    Peak:       -inf dBFS\n"
    )
    parsed = Ebur128Parser.parse(summary)
    assert parsed["true_peak_dbtp"] == SILENCE_FLOOR_DBTP
    assert parsed["silent"] == 1.0
    with pytest.raises(MeasurementUnavailable):
        Ebur128Parser.parse("no summary here")
    world = World(tmp_path)
    chain = _chain(world)
    world.runner.detector_text["ebur128"] = summary
    by_id = _results(world, chain)
    assert by_id["qc.audio.integrated_lufs"].verdict == "FAIL"
    assert by_id["qc.audio.integrated_lufs"].message == "AUDIO_SILENT"
    assert by_id["qc.audio.integrated_lufs"].remedy_stage_id == "s07_voice"


@pytest.mark.unit
def test_self_drain_inside_the_vps_grace_zone_is_now_not_a_week_away() -> None:
    now = _at("TUE", "06:55")  # grace 10 min before 07:00: drain point 06:50 is already past
    act = SelfDrainTimer.act_by(now, Placement.VPS, CFG)
    assert SelfDrainTimer.delay_ms(now, act) == 0


@pytest.mark.unit
def test_a_malformed_stored_srt_is_a_gate_fail_with_remedy_not_input_invalid(
    tmp_path: Path,
) -> None:
    import json

    world = World(tmp_path)
    chain = _chain(world)
    subs = json.loads(world.storage.blobs[world.refs["agent_10.subtitles.output"][0]])
    old = world.storage.blobs[subs["srt"][0]["uri"]]
    uri, sha = world.put("bad.srt", old.replace(b"\n", b"\r\n"))
    subs["srt"][0].update({"uri": uri, "sha256": sha})
    world.refs["agent_10.subtitles.output"] = world.put(
        "subs2.json", json.dumps(subs, sort_keys=True).encode()
    )
    qc_in = world.task_input("technical_qc", chain["qc_input"].payload.data)
    out = _qc(world, {"qc_input": qc_in})
    by_id = {r.check_id: r for r in out.validation_results}
    assert by_id["qc.subtitles.format"].verdict == "FAIL"
    assert by_id["qc.subtitles.format"].blocking
    assert payload_data(out)["gate_verdict"] == "FAILED"
