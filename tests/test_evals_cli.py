"""Baseline classification, report rendering and the CLI."""

import json
import subprocess
from pathlib import Path

import pytest

from amw_evals.baseline import (
    changed_files,
    classify,
    counts_per_agent,
    is_changed,
    load_baseline,
    render_report,
    write_baseline,
)
from amw_evals.cli import main
from amw_evals.findings import Finding
from tests.evals_support import OK_OUT, build_tree, case, prompt_text

PROMPT = "docs/v4/prompts/agent_06_fact_checker/claim_extraction.v1.md"
CASES = "docs/v4/evals/agent_06_fact_checker/claim_extraction/cases.jsonl"
F1 = Finding(PROMPT, "P-DATE", "date")
F2 = Finding(CASES, "E-COUNT", "few")


def test_classify_known_new_and_changed() -> None:
    base = {F1.key, "gone|X|y"}
    c = classify([F1, F2], base)
    assert c.known == [F1]
    assert c.blocking == [F2]
    assert c.fixed_baseline_keys == ["gone|X|y"]
    # a changed file blocks even for a known defect
    c = classify([F1, F2], {F1.key, F2.key}, {PROMPT})
    assert c.blocking == [F1]
    # touching any file of a dataset folder makes that dataset's findings blocking
    c = classify([F2], {F2.key}, {"docs/v4/evals/agent_06_fact_checker/claim_extraction/README.md"})
    assert c.blocking == [F2]
    assert not is_changed(F2, {"docs/v4/evals/other/x/cases.jsonl"})


def test_baseline_file_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "b.json"
    write_baseline(p, [F2, F1, F1])
    assert load_baseline(p) == {F1.key, F2.key}
    assert load_baseline(None) == set()
    assert load_baseline(tmp_path / "missing.json") == set()


def test_report_counts_per_agent() -> None:
    assert counts_per_agent([F1, F2]) == {"agent_06_fact_checker": (2, 2)}
    cls = classify([F1, F2], {F1.key, "old|A|b"})
    text = render_report([F1, F2], cls, 10, 16)
    assert "Scanned 10 prompt file(s) and 16 eval dataset(s)" in text
    assert "| agent_06_fact_checker | 2 | 2 |" in text
    assert "## Blocking" in text
    assert "## Known (baseline)" in text
    assert "no longer found" in text
    assert "None." in render_report([], classify([], set()), 0, 0)


def git(cwd: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def test_changed_files_uses_git_diff(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a.txt").write_text("1", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "base")
    git(tmp_path, "checkout", "-qb", "feature")
    (tmp_path / "b.txt").write_text("2", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "more")
    assert changed_files("main", cwd=tmp_path) == {"b.txt"}


def test_cli_lint_blocks_new_defect_and_writes_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build_tree(tmp_path / "v4", cases=[case("A-1")])  # too few cases
    report = tmp_path / "docs-lint-report.md"
    base = tmp_path / "base.json"
    args = ["lint", "--root", str(tmp_path / "v4"), "--rel-base", str(tmp_path)]
    assert main([*args, "--baseline", str(base), "--report", str(report)]) == 1
    assert "BLOCKING" in capsys.readouterr().err
    assert "blocking" in report.read_text(encoding="utf-8")
    # record the defect in the baseline: now report-only
    assert main([*args, "--baseline", str(base), "--update-baseline"]) == 0
    assert main([*args, "--baseline", str(base), "--report", str(report)]) == 0
    assert "1 known" in capsys.readouterr().out
    assert main([*args, "--update-baseline"]) == 2


def test_cli_lint_changed_files_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    build_tree(tmp_path / "v4", cases=[case("A-1")])
    base = tmp_path / "base.json"
    args = ["lint", "--root", str(tmp_path / "v4"), "--rel-base", str(tmp_path)]
    assert main([*args, "--baseline", str(base), "--update-baseline"]) == 0
    monkeypatch.setattr(
        "amw_evals.cli.changed_files",
        lambda ref: {"v4/evals/agent_06_fact_checker/claim_extraction/README.md"},
    )
    assert main([*args, "--baseline", str(base), "--changed-from", "origin/main"]) == 1


def test_cli_run_fake_and_threshold_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "v4"
    build_tree(root)
    ids = [f"C-{i:02d}" for i in range(20)]
    ok = {i: {"output": OK_OUT, "cost_micros": 3} for i in ids}
    resp = tmp_path / "resp.json"
    resp.write_text(json.dumps(ok), encoding="utf-8")
    out = tmp_path / "rec.jsonl"
    args = ["run", "--root", str(root), "--dataset", "evals/agent_06_fact_checker/claim_extraction"]
    assert main([*args, "--responses", str(resp), "--out", str(out)]) == 0
    assert "20/20 passed" in capsys.readouterr().out
    assert len(out.read_text(encoding="utf-8").splitlines()) == 20
    bad: dict[str, object] = {i: {"output": {"claims": []}} for i in ids}
    resp.write_text(json.dumps(bad), encoding="utf-8")
    assert main([*args, "--responses", str(resp)]) == 1
    assert "THRESHOLD MISS" in capsys.readouterr().err
    assert main([*args, "--responses", str(resp), "--adapter", "real"]) == 2


def test_cli_run_budget_error_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "v4"
    build_tree(root)
    resp = tmp_path / "resp.json"
    resp.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("EVAL_MAX_COST_MICROS", "zero")
    args = ["run", "--root", str(root), "--dataset", "evals/agent_06_fact_checker/claim_extraction"]
    assert main([*args, "--responses", str(resp)]) == 2
    assert "budget" in capsys.readouterr().err


def test_prompt_text_helper_used() -> None:
    assert "## Role" in prompt_text()
