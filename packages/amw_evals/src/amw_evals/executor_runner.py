"""Executor-dataset eval runner (CCR-130, ticket P4-17; 27 section 6.1).

A deterministic dataset has no prompt and no model: each case input is run through an injected
*executor* (a plain function of the agent's code) and the output is checked with the same
assertions and thresholds as an LLM dataset. Cost is always 0; the run records carry no provider.
An executor that raises fails that case with the exception type recorded (never swallowed
silently, never counted as a pass).
"""

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from amw_evals.assertions import AssertionResult, run_assertions
from amw_evals.eval_lint import load_cases
from amw_evals.findings import JsonObject
from amw_evals.runner import RunSummary, aggregate
from amw_evals.thresholds import parse_thresholds

type Executor = Callable[[JsonObject], object]
"""``case input -> output``; must be pure code (fakes only, no network, no paid call)."""

PROVIDER = "executor"


def run_executor_eval(
    dataset: Path,
    executor: Executor,
    *,
    dataset_id: str,
    output_schema: JsonObject | None = None,
    records_out: Path | None = None,
) -> tuple[list[JsonObject], RunSummary]:
    """Run every case of ``dataset/cases.jsonl`` through ``executor``."""
    cases, errors = load_cases(dataset / "cases.jsonl")
    if errors:
        raise ValueError(f"cases.jsonl has {len(errors)} unreadable line(s); run the lint first")
    thresholds = parse_thresholds(dataset / "README.md")
    run_id = "run_" + uuid.uuid4().hex
    records: list[JsonObject] = []
    for case in cases:
        raw_in, raw_exp = case.get("input"), case.get("expected")
        payload: JsonObject = raw_in if isinstance(raw_in, dict) else {}
        expected: JsonObject = raw_exp if isinstance(raw_exp, dict) else {}
        started = datetime.now(UTC)
        t0 = perf_counter()
        results: dict[str, AssertionResult]
        try:
            output = executor(payload)
        except Exception as exc:
            results = {"executor": AssertionResult(False, f"raised {type(exc).__name__}")}
        else:
            results = run_assertions(output, expected, payload, output_schema)
        latency_ms = int((perf_counter() - t0) * 1000)
        records.append(
            {
                "run_id": run_id,
                "prompt_id": None,
                "dataset_id": dataset_id,
                "provider": PROVIDER,
                "model": None,
                "case_id": str(case["case_id"]),
                "category": case.get("category"),
                "passed": all(r.passed for r in results.values()) and bool(results),
                "assertions": {k: v.as_json() for k, v in results.items()},
                "tokens_in": 0,
                "tokens_out": 0,
                "tokens_cached_in": 0,
                "cost_micros": 0,
                "currency": "USD",
                "latency_ms": latency_ms,
                "started_at": started.isoformat(),
                "figure_kind": "ESTIMATE",
            }
        )
    if records_out is not None:
        records_out.parent.mkdir(parents=True, exist_ok=True)
        with records_out.open("w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    summary = aggregate(records, thresholds, run_id)
    summary.unevaluated = [u for u in summary.unevaluated if "judge" not in u] + [
        "step-specific threshold rows are not machine-evaluated"
    ]
    return records, summary


__all__ = ["Executor", "run_executor_eval"]
