"""Eval runner: assertions, run records, thresholds, budget cap. No network, no paid calls."""

import json
from pathlib import Path

import pytest

from amw_evals.adapter import (
    BUDGET_ENV,
    BudgetError,
    FakeAdapter,
    LlmAdapter,
    LlmRequest,
    LlmResponse,
    resolve_budget,
)
from amw_evals.assertions import (
    check_offsets,
    collect_rule_ids,
    refusal_reason_of,
    run_assertions,
    verdict_of,
)
from amw_evals.runner import aggregate, run_eval
from amw_evals.thresholds import Thresholds, parse_thresholds
from tests.evals_support import OK_OUT, OUT_SCHEMA, build_tree, case


class PaidStub:
    provider = "paid"
    model = "m"
    is_fake = False

    def __init__(self, cost: int) -> None:
        self.cost = cost
        self.n = 0

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.n += 1
        return LlmResponse(OK_OUT, cost_micros=self.cost, latency_ms=10)


def canned(ids: list[str], out: object = OK_OUT) -> FakeAdapter:
    return FakeAdapter({i: LlmResponse(out, 5, 7, 1, 100, "USD", 20) for i in ids})


def test_fake_adapter_satisfies_protocol_and_records_calls() -> None:
    a = canned(["x"])
    assert isinstance(a, LlmAdapter)
    a.complete(LlmRequest("x", "p", "t", {}, None))
    assert a.calls == ["x"]
    with pytest.raises(KeyError):
        a.complete(LlmRequest("y", "p", "t", {}, None))


def test_budget_required_for_non_fake_adapter() -> None:
    with pytest.raises(BudgetError, match=BUDGET_ENV):
        resolve_budget(PaidStub(1), {})
    assert resolve_budget(PaidStub(1), {BUDGET_ENV: "500"}) == 500
    assert resolve_budget(canned([]), {}) is None
    for bad in ("0", "-3", "abc"):
        with pytest.raises(BudgetError):
            resolve_budget(canned([]), {BUDGET_ENV: bad})


def test_paid_adapter_not_called_without_budget(tmp_path: Path) -> None:
    d = build_tree(tmp_path)
    stub = PaidStub(1)
    with pytest.raises(BudgetError):
        run_eval(tmp_path, d, stub, {})
    assert stub.n == 0


def test_cost_cap_stops_the_run(tmp_path: Path) -> None:
    d = build_tree(tmp_path)
    stub = PaidStub(100)
    records, summary = run_eval(tmp_path, d, stub, {BUDGET_ENV: "250"})
    assert stub.n == 3  # 100, 200, 300 >= 250 stops after the third
    assert len(records) == 3
    assert not summary.ok
    assert any("cost cap" in f for f in summary.failures)


def test_run_records_have_27_6_4_fields_and_pass(tmp_path: Path) -> None:
    ids = [f"C-{i:02d}" for i in range(20)]
    d = build_tree(tmp_path)
    out = tmp_path / "out" / "records.jsonl"
    records, summary = run_eval(tmp_path, d, canned(ids), {}, out)
    assert summary.ok
    assert summary.passed == summary.total == 20
    assert summary.cost_micros == 2000
    assert summary.latency_p50_ms == summary.latency_p95_ms == 20
    lines = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 20
    required = {
        "run_id", "prompt_id", "prompt_sha256", "rule_pack_versions", "config_key", "provider",
        "model", "case_id", "passed", "assertions", "judge_scores", "judge_prompt_id", "tokens_in",
        "tokens_out", "tokens_cached_in", "cost_micros", "currency", "latency_ms", "started_at",
        "figure_kind",
    }  # fmt: skip
    assert required <= set(lines[0])
    assert records[0]["run_id"] == lines[0]["run_id"]
    assert str(lines[0]["run_id"]).startswith("run_")
    assert lines[0]["figure_kind"] == "ESTIMATE"
    assert lines[0]["prompt_id"] == "agent_06/claim_extraction.v1"
    assert lines[0]["tokens_in"] == 5


def test_below_threshold_exits_nonzero_state(tmp_path: Path) -> None:
    ids = [f"C-{i:02d}" for i in range(20)]
    bad: dict[str, object] = {"claims": []}  # fails schema
    adapter = FakeAdapter({i: LlmResponse(OK_OUT if n % 4 else bad) for n, i in enumerate(ids)})
    d = build_tree(tmp_path, readme="| Overall case pass rate | ≥ 0.90 (x) |\n")
    _, summary = run_eval(tmp_path, d, adapter, {})
    assert not summary.ok
    assert "overall pass rate" in summary.failures[0]


def test_answer_key_requires_100_percent(tmp_path: Path) -> None:
    rows = [case("AK-01", "ANSWER_KEY", verdict="BLOCKED")] + [
        case(f"C-{i:02d}") for i in range(19)
    ]
    d = build_tree(
        tmp_path, cases=rows, readme="| Answer-key cases passing | **1 / 1 (100 %)** |\n"
    )
    adapter = canned([str(r["case_id"]) for r in rows])  # AK-01 returns ALLOWED
    _, summary = run_eval(tmp_path, d, adapter, {})
    assert summary.answer_key_total == 1
    assert summary.answer_key_passed == 0
    assert any("answer-key" in f for f in summary.failures)


def test_unreadable_cases_and_missing_prompt(tmp_path: Path) -> None:
    d = build_tree(tmp_path)
    with (d / "cases.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("{bad\n")
    with pytest.raises(ValueError, match="unreadable"):
        run_eval(tmp_path, d, canned([]), {})
    orphan = tmp_path / "evals" / "agent_06_fact_checker" / "orphan"
    orphan.mkdir()
    with pytest.raises(FileNotFoundError):
        run_eval(tmp_path, orphan, canned([]), {})


def test_aggregate_percentiles_and_categories() -> None:
    recs: list[dict[str, object]] = [
        {"passed": True, "category": "EDGE", "latency_ms": ms, "cost_micros": 1}
        for ms in (10, 20, 30, 40, 100)
    ]
    s = aggregate(recs, Thresholds(overall_pass_rate=1.0), "run_x")
    assert (s.latency_p50_ms, s.latency_p95_ms) == (30, 100)
    assert s.by_category == {"EDGE": (5, 5)}
    assert aggregate([], Thresholds(), "r").total == 0


def test_parse_thresholds(tmp_path: Path) -> None:
    f = tmp_path / "README.md"
    f.write_text(
        "| Threshold | Value |\n|---|---|\n"
        "| Answer-key cases passing | **4 / 4 (100 %)** — mandatory |\n"
        "| Overall case pass rate | ≥ 0.85 (≥ 26 of 30) |\n",
        encoding="utf-8",
    )
    t = parse_thresholds(f)
    assert (t.answer_key_pass_rate, t.overall_pass_rate) == (1.0, 0.85)
    f.write_text("| Pass rate | **100 %** (x) |\n", encoding="utf-8")
    assert parse_thresholds(f).overall_pass_rate == 1.0
    assert parse_thresholds(tmp_path / "none.md") == Thresholds()


def test_real_dataset_thresholds_parse() -> None:
    root = Path(__file__).resolve().parent.parent / "docs" / "v4" / "evals"
    t = parse_thresholds(root / "agent_06_fact_checker" / "claim_extraction" / "README.md")
    assert t.overall_pass_rate == 0.9
    assert t.answer_key_pass_rate == 1.0


# --- deterministic assertions ---------------------------------------------------------------


def claim_out(start: int, end: int, quote: str, flags: list[str]) -> dict[str, object]:
    claim = {"local_id": "c1", "segment_id": "s1", "char_start": start, "char_end": end,
             "quote": quote, "rule_flags": [{"rule_id": r} for r in flags]}  # fmt: skip
    return {"claims": [claim], "overall": {"proposed_verdict": "BLOCKED"}, "refusal": None}


PAYLOAD: dict[str, object] = {"segments": [{"segment_id": "s1", "text": "hello world"}]}


def test_offsets() -> None:
    assert check_offsets(claim_out(0, 5, "hello", []), PAYLOAD) is not None
    ok = check_offsets(claim_out(0, 5, "hello", []), PAYLOAD)
    assert ok is not None
    assert ok.passed
    bad = check_offsets(claim_out(0, 5, "world", []), PAYLOAD)
    assert bad is not None
    assert not bad.passed
    assert check_offsets(OK_OUT, PAYLOAD) is not None
    assert check_offsets("x", PAYLOAD) is None
    assert check_offsets(claim_out(0, 5, "hello", []), {}) is None
    unknown = claim_out(0, 5, "hello", [])
    unknown["claims"][0]["segment_id"] = "s9"  # type: ignore[index]
    res = check_offsets(unknown, PAYLOAD)
    assert res is not None
    assert not res.passed


def test_flag_verdict_banned_refusal_assertions() -> None:
    out = claim_out(0, 5, "hello", ["FIN-R1"])
    expected: dict[str, object] = {
        "must_flag": ["FIN-R1", "FIN-R2"],
        "must_not_flag": ["FIN-R9", "FIN-R1"],
        "verdict": "ALLOWED",
        "banned": ["HELLO"],
        "refusal_reason": "OUT_OF_SCOPE",
    }
    res = run_assertions(out, expected, PAYLOAD, OUT_SCHEMA)
    assert not res["expected_flags"].passed
    assert "FIN-R2" in res["expected_flags"].detail
    assert not res["forbidden_flags"].passed
    assert not res["verdict"].passed
    assert not res["banned_phrases"].passed
    assert not res["refusal_reason"].passed
    assert res["schema"].passed
    assert res["offsets"].passed


def test_schema_and_required_assertions() -> None:
    res = run_assertions({"claims": 5}, {}, {}, OUT_SCHEMA)
    assert not res["schema"].passed
    assert not res["required_fields"].passed
    res = run_assertions("text", {}, {}, OUT_SCHEMA)
    assert not res["required_fields"].passed
    assert run_assertions(OK_OUT, {}, {}, None) == {}


def test_helpers() -> None:
    refusal = {"refusal": {"reason": "OUT_OF_SCOPE", "violated_rule_ids": ["FIN-R3"]}}
    assert collect_rule_ids(refusal) == {"FIN-R3"}
    assert refusal_reason_of(refusal) == "OUT_OF_SCOPE"
    assert refusal_reason_of("x") is None
    assert verdict_of({"proposed_verdict": "ALLOWED"}) == "ALLOWED"
    assert verdict_of([]) is None
    res = run_assertions(
        refusal, {"rule_ids_all": ["FIN-R3"], "refusal_reason": "OUT_OF_SCOPE"}, {}, None
    )
    assert res["expected_flags"].passed
    assert res["refusal_reason"].passed
