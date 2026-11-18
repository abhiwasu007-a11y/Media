"""Eval runner skeleton: dataset + prompt + injected adapter -> records -> threshold decision."""

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from amw_evals.adapter import BudgetError, LlmAdapter, LlmRequest, LlmResponse, resolve_budget
from amw_evals.assertions import AssertionResult, run_assertions
from amw_evals.eval_lint import find_prompt, load_cases
from amw_evals.findings import JsonObject
from amw_evals.prompt_doc import parse_prompt
from amw_evals.thresholds import Thresholds, parse_thresholds


@dataclass
class RunSummary:
    run_id: str
    total: int
    passed: int
    answer_key_total: int
    answer_key_passed: int
    cost_micros: int
    latency_p50_ms: int
    latency_p95_ms: int
    by_category: dict[str, tuple[int, int]]
    failures: list[str] = field(default_factory=list)  # threshold misses
    unevaluated: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def _percentile(values: list[int], pct: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, -(-len(ordered) * pct // 100) - 1))
    return ordered[idx]


def aggregate(
    records: list[JsonObject], thresholds: Thresholds, run_id: str, skipped_budget: int = 0
) -> RunSummary:
    total = len(records)
    passed = sum(1 for r in records if r["passed"] is True)
    ak = [r for r in records if r.get("category") == "ANSWER_KEY"]
    ak_passed = sum(1 for r in ak if r["passed"] is True)
    cats: dict[str, tuple[int, int]] = {}
    for r in records:
        cat = str(r.get("category"))
        n, p = cats.get(cat, (0, 0))
        cats[cat] = (n + 1, p + (1 if r["passed"] is True else 0))
    latencies = [int(str(r["latency_ms"])) for r in records]
    cost = sum(int(str(r["cost_micros"])) for r in records)
    summary = RunSummary(
        run_id, total, passed, len(ak), ak_passed, cost,
        _percentile(latencies, 50), _percentile(latencies, 95), cats,
        unevaluated=["judge scores and step-specific threshold rows are not machine-evaluated"],
    )  # fmt: skip
    if skipped_budget:
        summary.failures.append(f"{skipped_budget} case(s) not run: cost cap reached")
    if thresholds.overall_pass_rate is not None and total:
        rate = passed / total
        if rate < thresholds.overall_pass_rate:
            summary.failures.append(
                f"overall pass rate {rate:.3f} below {thresholds.overall_pass_rate:.3f}"
            )
    if thresholds.answer_key_pass_rate is not None and ak:
        rate = ak_passed / len(ak)
        if rate < thresholds.answer_key_pass_rate:
            summary.failures.append(
                f"answer-key pass rate {ak_passed}/{len(ak)} below "
                f"{thresholds.answer_key_pass_rate:.0%}"
            )
    return summary


def run_eval(
    root: Path,
    dataset: Path,
    adapter: LlmAdapter,
    env: Mapping[str, str],
    records_out: Path | None = None,
    prompt_path: Path | None = None,
) -> tuple[list[JsonObject], RunSummary]:
    """Run every case once through ``adapter``. ``dataset`` is evals/<agent>/<task>/."""
    cap = resolve_budget(adapter, env)  # raises BudgetError for a paid adapter without a cap
    prompt_path = prompt_path or find_prompt(root, dataset)
    if prompt_path is None:
        raise FileNotFoundError(f"no prompt file for dataset {dataset}")
    doc = parse_prompt(prompt_path)
    prompt_id = doc.expected_prompt_id or prompt_path.stem
    sha = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
    out_schema = doc.output_schema()
    cases, errors = load_cases(dataset / "cases.jsonl")
    if errors:
        raise ValueError(f"cases.jsonl has {len(errors)} unreadable line(s); run the lint first")
    thresholds = parse_thresholds(dataset / "README.md")
    run_id = "run_" + uuid.uuid4().hex
    records: list[JsonObject] = []
    spent = 0
    skipped = 0
    for case in cases:
        if cap is not None and spent >= cap:
            skipped += 1
            continue
        case_id = str(case["case_id"])
        raw_in, raw_exp = case.get("input"), case.get("expected")
        payload: JsonObject = raw_in if isinstance(raw_in, dict) else {}
        expected: JsonObject = raw_exp if isinstance(raw_exp, dict) else {}
        started = datetime.now(UTC)
        request = LlmRequest(case_id, prompt_id, doc.text, payload, out_schema)
        response: LlmResponse = adapter.complete(request)
        results: dict[str, AssertionResult] = run_assertions(
            response.output, expected, payload, out_schema
        )
        spent += response.cost_micros
        records.append(
            {
                "run_id": run_id,
                "prompt_id": prompt_id,
                "prompt_sha256": sha,
                "rule_pack_versions": {},
                "config_key": f"llm.{prompt_id.split('/')[0]}.{doc.task}",
                "provider": adapter.provider,
                "model": adapter.model,
                "case_id": case_id,
                "category": case.get("category"),
                "passed": all(r.passed for r in results.values()) and bool(results),
                "assertions": {k: v.as_json() for k, v in results.items()},
                "judge_scores": {},
                "judge_prompt_id": None,
                "tokens_in": response.tokens_in,
                "tokens_out": response.tokens_out,
                "tokens_cached_in": response.tokens_cached_in,
                "cost_micros": response.cost_micros,
                "currency": response.currency,
                "latency_ms": response.latency_ms,
                "started_at": started.isoformat(),
                "figure_kind": "ESTIMATE",
            }
        )
    if records_out is not None:
        records_out.parent.mkdir(parents=True, exist_ok=True)
        with records_out.open("w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return records, aggregate(records, thresholds, run_id, skipped)


__all__ = ["BudgetError", "RunSummary", "aggregate", "run_eval"]
