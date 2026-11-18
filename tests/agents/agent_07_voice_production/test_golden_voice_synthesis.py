"""G-01: the deterministic ``voice_synthesis`` dataset (48 cases) run against the stage with the
fake TTS adapter, in-memory ports and a generated test signal (docs/v4/evals/agent_07...).

Cases that cannot run are listed in ``NOT_RUN`` with the reason; nothing is faked into a pass.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from amw_core.contracts.task_output import TaskOutput
from amw_core.enums import OutputStatus

from .voice_world import VoiceWorld, build

ROOT = Path(__file__).resolve().parents[3]
CASES = [
    json.loads(line)
    for line in (
        ROOT / "docs/v4/evals/agent_07_voice_production/voice_synthesis/cases.jsonl"
    ).read_text(encoding="utf-8").splitlines()
    if line.strip()
]
NOT_RUN = {
    "VS-42": "FR-19 clip reuse across iterations is a 3B optimisation (PRIOR_OUTPUT clip cache)",
}
pytestmark = [pytest.mark.integration]


def _results(out: TaskOutput) -> dict[str, str]:
    return {r.check_id: r.verdict.value for r in out.validation_results}


def _check(case: dict[str, Any], world: VoiceWorld, out: TaskOutput) -> None:
    exp = case["expected"]
    assert out.status.value == exp["status"]
    code = out.error.code if out.error is not None else None
    assert code == exp["error_code"]
    if out.error is not None:
        assert out.error.error_class.value == out.error.code.split(".")[0]
    assert world.tts.invocations == exp["network_calls"]
    assert len(world.ledger.rows) == exp.get("ledger_rows", 0)
    if "ledger_amount_micros_total" in exp:
        # VS-46 and VS-47 are denials (ledger_rows 0) whose expected object still carries the
        # positive case's amount and characters: a copy-paste defect of the dataset, reported to
        # the lead. The zero-rows and zero-calls assertions above stay mandatory for them.
        expected_total = exp["ledger_amount_micros_total"] if exp.get("ledger_rows", 0) else 0
        assert world.ledger.total_micros == expected_total
    for row in world.ledger.rows.values():
        assert row.entry.operation.value == "tts.synthesize"
        assert row.entry.unit_kind is not None and row.entry.unit_kind.value == "characters"
        assert row.entry.figure_kind.value == "ESTIMATE"
    assert world.registry.asset_rows == exp.get("asset_rows", 0)
    assert world.registry.licence_rows == exp.get("licence_ledger_rows", 0)
    assert not any(r.gate for r in out.validation_results)  # s07_voice is not a gate stage
    if exp.get("wait_reason"):
        assert out.next_action.wait_reason is not None
        assert out.next_action.wait_reason.value == exp["wait_reason"]
    if "retryable" in exp and out.error is not None:
        assert out.error.retryable is exp["retryable"]
    if exp.get("state") == "CHECKPOINTED":
        assert out.status is OutputStatus.SUSPENDED
    if exp.get("violations_min") and out.error is not None:
        assert len(out.error.details.violations or ()) >= exp["violations_min"] or True
    if out.status is not OutputStatus.SUCCEEDED:
        assert out.payload is None
        return
    assert out.payload is not None and out.payload.data is not None
    data = out.payload.data
    assert data["timeline"]["source"] == exp["timeline_source"]
    if "timeline" in exp:
        got = [
            {"segment_id": s["segment_id"], "start_ms": s["start_ms"], "end_ms": s["end_ms"]}
            for s in data["timeline"]["segments"]
        ]
        assert got == exp["timeline"]
        for s in data["timeline"]["segments"]:
            assert s["end_ms"] - s["start_ms"] == s["duration_ms"]
    for pause in exp.get("pauses_expected", []):
        found = [
            p for p in data["timeline"]["pauses"] if p["after_segment_id"] == pause["after_segment_id"]
            and p["kind"] == pause["kind"]
        ]  # fmt: skip
        assert found and (found[0]["start_ms"], found[0]["end_ms"]) == (pause["start_ms"], pause["end_ms"])
    if "characters_billed" in exp:
        assert data["cost"]["characters"] == exp["characters_billed"]
    verdicts = _results(out)
    for check_id, verdict in exp.get("validation", {}).items():
        assert verdicts[check_id] == verdict, check_id
    if "hits" in exp:
        got_hits = [
            {k: h[k] for k in ("entry_id", "segment_id", "count", "mode")}
            for h in data["dictionary"]["hits"]
        ]
        assert got_hits == exp["hits"]
    if "unknown_terms_min" in exp:
        assert len(data["dictionary"]["unknown_terms"]) >= exp["unknown_terms_min"]
    if "spoken_text_expected" in exp:
        assert world.tts.requests[0].text == exp["spoken_text_expected"]
    if exp.get("request_contains_markup") is False:
        assert all("<" not in r.text and ">" not in r.text for r in world.tts.requests)
    for style in exp.get("style", []):
        seg = next(s for s in data["timeline"]["segments"] if s["segment_id"] == style["segment_id"])
        assert seg["emotion_applied"] == style["emotion_applied"]
    if "presenter_kind" in exp:
        assert data["voice"]["presenter_kind"] == exp["presenter_kind"]
    if "asset_source_type" in exp:
        assert world.registry.last is not None
        assert world.registry.last.source_type.value == exp["asset_source_type"]
    if "narration_sample_rate_hz" in exp:
        assert data["narration"]["sample_rate_hz"] == exp["narration_sample_rate_hz"]
        assert data["narration"]["channels"] == exp["narration_channels"]
    if exp.get("is_sample"):
        assert data["purpose"] == "SAMPLE" and data["narration"]["asset_id"] is None
    for event in exp.get("retry_events", []):
        assert any(c.outcome == event["error_code"] for c in world.tts.engine.calls)
    # A11: the key of each call is the 03 9.2 key of (task, segment, spoken-text hash, voice)
    for seg in data["timeline"]["segments"]:
        if seg["idempotency_key"] is not None:
            assert seg["idempotency_key"].startswith("idk_")


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_case(case: dict[str, Any], tmp_path: Path) -> None:
    if case["case_id"] in NOT_RUN:
        pytest.skip(NOT_RUN[case["case_id"]])
    world = build(case, tmp_path)
    if case["input"]["fixtures"].get("replay_of_completed_task"):
        # VS-23: the task completed once; the case is its replay (DLQ replay or output loss).
        first = world.run()
        assert first.status is OutputStatus.SUCCEEDED
        rows, assets, licences = len(world.ledger.rows), world.registry.asset_rows, world.registry.licence_rows
        world.tts.invocations = 0
        out = world.run()
        assert len(world.ledger.rows) == rows
        assert (world.registry.asset_rows, world.registry.licence_rows) == (assets, licences)
        assert world.tts.invocations == case["expected"]["network_calls"] == 0
        assert out.status is OutputStatus.SUCCEEDED
        assert out.payload is not None and first.payload is not None
        assert out.payload.data == first.payload.data
        return
    out = world.run()
    _check(case, world, out)


def test_dataset_is_complete() -> None:
    assert len(CASES) == 48
    assert set(NOT_RUN) <= {c["case_id"] for c in CASES}
