"""Eval dataset lint (evals/README.md section 2, 27 section 6.1)."""

import json
from pathlib import Path

from amw_evals.eval_lint import dataset_dirs, find_prompt, lint_datasets, load_cases
from amw_evals.findings import Finding
from tests.evals_support import build_tree, case

REPO = Path(__file__).resolve().parent.parent


def run(tmp_path: Path, **kw: object) -> list[Finding]:
    build_tree(tmp_path, **kw)  # type: ignore[arg-type]
    return lint_datasets(tmp_path, tmp_path)


def codes(found: list[Finding]) -> set[str]:
    return {f.code for f in found}


def test_valid_dataset_is_clean(tmp_path: Path) -> None:
    assert run(tmp_path) == []


def test_too_few_cases(tmp_path: Path) -> None:
    assert "E-COUNT" in codes(run(tmp_path, cases=[case("A-1")]))


def test_duplicate_case_id(tmp_path: Path) -> None:
    rows = [case(f"C-{i:02d}") for i in range(20)] + [case("C-00")]
    assert "E-DUP-ID" in codes(run(tmp_path, cases=rows))


def test_missing_keys_and_bad_category(tmp_path: Path) -> None:
    rows = [case(f"C-{i:02d}") for i in range(19)]
    bad = case("C-99", category="WEIRD")
    del bad["description"]
    del bad["judge_min"]
    found = run(tmp_path, cases=[*rows, bad])
    assert {"E-KEYS", "E-CATEGORY"} <= codes(found)


def test_flag_overlap(tmp_path: Path) -> None:
    rows = [case(f"C-{i:02d}") for i in range(19)]
    rows.append(case("C-X", must_flag=["FIN-R1"], must_not_flag=["FIN-R1", "FIN-R2"]))
    found = run(tmp_path, cases=rows)
    assert any("FIN-R1" in f.message for f in found if f.code == "E-FLAG-OVERLAP")


def test_input_must_match_prompt_input_schema(tmp_path: Path) -> None:
    rows = [case(f"C-{i:02d}") for i in range(19)]
    bad = case("C-BAD")
    bad["input"] = {"nope": 1}
    assert "E-INPUT-INVALID" in codes(run(tmp_path, cases=[*rows, bad]))


def test_answer_key_named_in_readme_must_exist(tmp_path: Path) -> None:
    found = run(tmp_path, readme="AK-01 and AK-02 are the answer keys\n")
    assert [f.message for f in found if f.code == "E-ANSWER-KEY"] == [
        "README names AK-01 but cases.jsonl has no such case_id",
        "README names AK-02 but cases.jsonl has no such case_id",
    ]
    rows = [case("AK-01", "ANSWER_KEY")] + [case(f"C-{i:02d}") for i in range(19)]
    found = run(tmp_path / "ok", cases=rows, readme="AK-01 only\n")
    assert "E-ANSWER-KEY" not in codes(found)


def test_missing_readme_and_rubric(tmp_path: Path) -> None:
    d = build_tree(tmp_path, readme=None)
    (d / "rubric.md").unlink()
    assert {"E-README", "E-RUBRIC"} <= codes(lint_datasets(tmp_path, tmp_path))


def test_bad_lines(tmp_path: Path) -> None:
    d = build_tree(tmp_path)
    with (d / "cases.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("{not json\n[1]\n\n")
    found = lint_datasets(tmp_path, tmp_path)
    msgs = [f.message for f in found if f.code == "E-JSON"]
    assert len(msgs) == 3
    assert any("invalid JSON" in m for m in msgs)
    assert any("not a JSON object" in m for m in msgs)
    assert any("blank line" in m for m in msgs)


def test_non_string_case_id_and_expected(tmp_path: Path) -> None:
    rows = [case(f"C-{i:02d}") for i in range(19)]
    weird = case("x")
    weird["case_id"] = 5
    weird["expected"] = []
    found = run(tmp_path, cases=[*rows, weird])
    assert sum(1 for f in found if f.code == "E-KEYS") == 2


def test_dataset_without_prompt_has_no_llm_requirements(tmp_path: Path) -> None:
    d = tmp_path / "evals" / "agent_09_video_director" / "timeline_engine"
    d.mkdir(parents=True)
    row = {"case_id": "T-1", "category": "POSITIVE", "description": "d", "input": {},
           "expected": {}, "notes": ""}  # fmt: skip
    (d / "cases.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    (d / "README.md").write_text("x", encoding="utf-8")
    assert find_prompt(tmp_path, d) is None
    assert lint_datasets(tmp_path, tmp_path) == []


def test_find_prompt_prefers_highest_version(tmp_path: Path) -> None:
    d = build_tree(tmp_path)
    v2 = tmp_path / "prompts" / "agent_06_fact_checker" / "claim_extraction.v2.md"
    v2.write_text("x", encoding="utf-8")
    assert find_prompt(tmp_path, d) == v2
    assert dataset_dirs(tmp_path / "missing") == []


def test_load_cases_roundtrip(tmp_path: Path) -> None:
    d = build_tree(tmp_path)
    cases, errors = load_cases(d / "cases.jsonl")
    assert len(cases) == 20
    assert errors == []


def test_real_repo_datasets_have_no_unlisted_defects() -> None:
    from amw_evals.baseline import load_baseline

    base = load_baseline(REPO / "scripts" / "docs_lint_baseline.json")
    found = lint_datasets(REPO / "docs" / "v4", REPO)
    assert [f for f in found if f.key not in base] == []
