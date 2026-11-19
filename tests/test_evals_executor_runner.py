"""Executor-dataset runner (CCR-130): no prompt, no model; assertions and thresholds as usual."""

import json
from pathlib import Path

import pytest

from amw_evals.executor_runner import ExecutorCaseError, run_executor_eval
from amw_evals.findings import JsonObject


def dataset(tmp_path: Path, cases: list[dict[str, object]], readme: str) -> Path:
    d = tmp_path / "det"
    d.mkdir()
    (d / "cases.jsonl").write_text("\n".join(json.dumps(c) for c in cases) + "\n", "utf-8")
    (d / "README.md").write_text(readme, encoding="utf-8")
    return d


def case(cid: str, text: str, banned: str) -> dict[str, object]:
    return {
        "case_id": cid,
        "category": "EDGE",
        "input": {"text": text},
        "expected": {"must_not_contain": [banned]},
    }


def upper(payload: JsonObject) -> object:
    return {"out": str(payload["text"]).upper()}


def test_executor_cases_pass_and_fail_by_assertion(tmp_path: Path) -> None:
    d = dataset(
        tmp_path,
        [case("A-1", "abc", "xyz"), case("A-2", "abc", "ABC")],
        "| Overall case pass rate | 100 % |\n",
    )
    out = tmp_path / "records.jsonl"
    records, summary = run_executor_eval(d, upper, dataset_id="det", records_out=out)
    assert [r["passed"] for r in records] == [True, False]
    assert summary.total == 2
    assert summary.cost_micros == 0
    assert not summary.ok  # 100 % threshold missed
    assert len(out.read_text("utf-8").splitlines()) == 2


def test_raising_executor_is_a_failed_case_not_a_pass(tmp_path: Path) -> None:
    def boom(payload: JsonObject) -> object:
        raise RuntimeError("secret detail")

    d = dataset(tmp_path, [case("A-1", "a", "b")], "| Overall case pass rate | ≥ 0.50 |\n")
    records, summary = run_executor_eval(d, boom, dataset_id="det")
    assert records[0]["passed"] is False
    assert "RuntimeError" in json.dumps(records[0]["assertions"])
    assert "secret detail" not in json.dumps(records[0])
    assert not summary.ok


def test_schema_is_checked_when_given(tmp_path: Path) -> None:
    d = dataset(tmp_path, [case("A-1", "a", "zzz")], "| Overall case pass rate | ≥ 0.50 |\n")
    schema: JsonObject = {"type": "object", "required": ["other"]}
    records, _ = run_executor_eval(d, upper, dataset_id="det", output_schema=schema)
    assert records[0]["passed"] is False


def test_unreadable_cases_refuse_the_run(tmp_path: Path) -> None:
    import pytest

    d = dataset(tmp_path, [], "")
    (d / "cases.jsonl").write_text("{bad\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unreadable"):
        run_executor_eval(d, upper, dataset_id="det")


@pytest.mark.parametrize("bad_input", [None, "text", [1], 5])
def test_case_input_that_is_not_an_object_refuses_the_run(
    tmp_path: Path, bad_input: object
) -> None:
    good = case("A-1", "a", "b")
    bad: dict[str, object] = {
        "case_id": "A-2",
        "category": "EDGE",
        "input": bad_input,
        "expected": {},
    }
    d = dataset(tmp_path, [good, bad], "")
    with pytest.raises(ExecutorCaseError, match="A-2"):
        run_executor_eval(d, upper, dataset_id="det")
    no_input: dict[str, object] = {"case_id": "A-3", "category": "EDGE", "expected": {}}
    (tmp_path / "x").mkdir()
    d2 = dataset(tmp_path / "x", [no_input], "")
    with pytest.raises(ExecutorCaseError, match="A-3"):
        run_executor_eval(d2, upper, dataset_id="det")


def test_currency_is_recorded_as_given_not_invented(tmp_path: Path) -> None:
    d = dataset(tmp_path, [case("A-1", "a", "b")], "")
    records, _ = run_executor_eval(d, upper, dataset_id="det")
    assert records[0]["currency"] is None
    records, _ = run_executor_eval(d, upper, dataset_id="det", currency="XXX")
    assert records[0]["currency"] == "XXX"
