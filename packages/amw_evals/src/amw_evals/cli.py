"""Command line: ``python -m amw_evals lint|run``."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from amw_evals.adapter import BudgetError, FakeAdapter, LlmResponse
from amw_evals.baseline import (
    changed_files,
    classify,
    load_baseline,
    render_report,
    write_baseline,
)
from amw_evals.eval_lint import dataset_dirs, lint_datasets
from amw_evals.prompt_lint import lint_prompts, prompt_files
from amw_evals.runner import run_eval

DEFAULT_ROOT = (
    "docs/v4"  # moves to the repo root (".") in ticket 3A-01; override with --root / AMW_EVALS_ROOT
)


def _lint(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    base = Path(args.rel_base).resolve()
    findings = sorted(lint_prompts(root, base) + lint_datasets(root, base))
    baseline_path = Path(args.baseline) if args.baseline else None
    if args.update_baseline:
        if baseline_path is None:
            print("--update-baseline needs --baseline", file=sys.stderr)
            return 2
        write_baseline(baseline_path, findings)
        print(f"baseline written: {len(findings)} finding(s)")
        return 0
    changed = changed_files(args.changed_from) if args.changed_from else set()
    cls = classify(findings, load_baseline(baseline_path), changed)
    report = render_report(findings, cls, len(prompt_files(root)), len(dataset_dirs(root)))
    if args.report:
        Path(args.report).write_text(report + "\n", encoding="utf-8")
    for f in cls.blocking:
        print(f"BLOCKING {f.path}: {f.code}: {f.message}", file=sys.stderr)
    print(
        f"prompt/eval lint: {len(findings)} finding(s), {len(cls.known)} known, "
        f"{len(cls.blocking)} blocking"
    )
    return 1 if cls.blocking else 0


def _run(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    dataset = Path(args.dataset)
    dataset = dataset if dataset.is_absolute() else root / dataset
    if args.adapter != "fake":
        print("only the fake adapter is wired until amw_adapters (Step 0) lands", file=sys.stderr)
        return 2
    raw = json.loads(Path(args.responses).read_text(encoding="utf-8"))
    adapter = FakeAdapter({cid: LlmResponse(**resp) for cid, resp in raw.items()})
    try:
        records, summary = run_eval(
            root, dataset, adapter, os.environ, Path(args.out) if args.out else None
        )
    except BudgetError as exc:
        print(f"budget: {exc}", file=sys.stderr)
        return 2
    print(
        f"{summary.passed}/{summary.total} passed; answer-key {summary.answer_key_passed}/"
        f"{summary.answer_key_total}; cost {summary.cost_micros} micros; "
        f"p50 {summary.latency_p50_ms} ms p95 {summary.latency_p95_ms} ms; {len(records)} record(s)"
    )
    for miss in summary.failures:
        print(f"THRESHOLD MISS: {miss}", file=sys.stderr)
    return 0 if summary.ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="amw_evals")
    sub = parser.add_subparsers(dest="command", required=True)
    default_root = os.environ.get("AMW_EVALS_ROOT", DEFAULT_ROOT)

    lint = sub.add_parser("lint", help="lint all prompts and eval datasets under <root>")
    lint.add_argument("--root", default=default_root)
    lint.add_argument("--rel-base", default=".")
    lint.add_argument("--baseline")
    lint.add_argument("--update-baseline", action="store_true")
    lint.add_argument("--changed-from", help="git ref; findings in files changed since it block")
    lint.add_argument("--report")
    lint.set_defaults(func=_lint)

    run = sub.add_parser("run", help="run one dataset through an adapter")
    run.add_argument("--root", default=default_root)
    run.add_argument("--dataset", required=True, help="evals/<agent>/<task>")
    run.add_argument("--adapter", default="fake")
    run.add_argument("--responses", required=True, help="JSON {case_id: LlmResponse fields}")
    run.add_argument("--out", help="write run records (JSONL) here")
    run.set_defaults(func=_run)

    args = parser.parse_args(argv)
    code: int = args.func(args)
    return code
