"""Prompt lint (27 section 4.4)."""

from pathlib import Path

import pytest

from amw_evals.findings import Finding
from amw_evals.prompt_lint import lint_prompt, lint_prompts, prompt_files
from tests.evals_support import OUT_SCHEMA, prompt_text

REPO = Path(__file__).resolve().parent.parent


def lint(tmp_path: Path, text: str, name: str = "claim_extraction.v1.md") -> list[Finding]:
    d = tmp_path / "prompts" / "agent_06_fact_checker"
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text(text, encoding="utf-8")
    return lint_prompt(f, f.relative_to(tmp_path).as_posix())


def codes(found: list[Finding]) -> set[str]:
    return {f.code for f in found}


def test_valid_prompt_is_clean(tmp_path: Path) -> None:
    assert lint(tmp_path, prompt_text()) == []


def test_missing_section(tmp_path: Path) -> None:
    text = prompt_text(sections=("Role", "Objective", "Inputs", "Rules", "Output JSON Schema"))
    found = lint(tmp_path, text)
    assert any("Worked examples" in f.message for f in found if f.code == "P-SECTIONS")


def test_sections_out_of_order(tmp_path: Path) -> None:
    text = prompt_text(
        sections=(
            "Objective",
            "Role",
            "Inputs",
            "Rules",
            "Output JSON Schema",
            "Worked examples",
            "Refusal and escalation",
            "Self-check",
        )
    )
    assert "P-SECTIONS" in codes(lint(tmp_path, text))


def test_bad_file_name(tmp_path: Path) -> None:
    assert "P-NAME" in codes(lint(tmp_path, prompt_text(), name="claim_extraction.md"))


def test_prompt_id_mismatch(tmp_path: Path) -> None:
    assert "P-ID" in codes(lint(tmp_path, prompt_text(prompt_id="agent_06/other.v1")))


def test_header_row_missing(tmp_path: Path) -> None:
    text = prompt_text().replace("| Eval set | z |\n", "")
    assert any("Eval set" in f.message for f in lint(tmp_path, text) if f.code == "P-HEADER")


@pytest.mark.parametrize(
    "snippet",
    ["Valid until 2031-04-05.", "Posted March 3, 2030.", "Call at 9:30 pm.", "At 10:15:00 sharp."],
)
def test_dates_and_times_flagged(tmp_path: Path, snippet: str) -> None:
    assert "P-DATE" in codes(lint(tmp_path, prompt_text(extra_rules=snippet)))


def test_aspect_ratio_is_not_a_time(tmp_path: Path) -> None:
    assert lint(tmp_path, prompt_text(extra_rules="Use 9:16 framing.")) == []


def test_banned_terms_and_price(tmp_path: Path) -> None:
    found = lint(tmp_path, prompt_text(extra_rules="Use GPT-4 for $5 per call."))
    assert {"P-BANNED-TERM", "P-PRICE"} <= codes(found)


def test_undeclared_variable(tmp_path: Path) -> None:
    found = lint(tmp_path, prompt_text(extra_rules="See {{mystery}}."))
    assert any("mystery" in f.message for f in found if f.code == "P-VAR-UNDECLARED")


def test_rule_pack_reference_is_not_a_variable(tmp_path: Path) -> None:
    assert lint(tmp_path, prompt_text(extra_rules="{{config:x}}")) == []


def test_schema_not_json(tmp_path: Path) -> None:
    text = prompt_text().replace('"type": "object",', '"type": "object" ,,', 1)
    assert "P-SCHEMA-PARSE" in codes(lint(tmp_path, text))


def test_schema_not_object(tmp_path: Path) -> None:
    assert "P-SCHEMA-PARSE" in codes(lint(tmp_path, prompt_text(out_schema=[1])))


def test_schema_wrong_dialect_and_invalid(tmp_path: Path) -> None:
    bad = {**OUT_SCHEMA, "$schema": "http://json-schema.org/draft-07/schema#", "type": 5}
    found = codes(lint(tmp_path, prompt_text(out_schema=bad)))
    assert {"P-SCHEMA-DIALECT", "P-SCHEMA-INVALID"} <= found


def test_schema_missing(tmp_path: Path) -> None:
    text = prompt_text().replace("```json", "```text", 1)
    assert "P-SCHEMA-MISSING" in codes(lint(tmp_path, text))


def test_refusal_property_required(tmp_path: Path) -> None:
    schema = {**OUT_SCHEMA, "required": ["claims", "overall"]}
    props = dict(OUT_SCHEMA["properties"])  # type: ignore[call-overload]
    props.pop("refusal")
    schema["properties"] = props
    assert "P-REFUSAL" in codes(lint(tmp_path, prompt_text(out_schema=schema)))


def test_example_count(tmp_path: Path) -> None:
    assert "P-EXAMPLES-COUNT" in codes(lint(tmp_path, prompt_text(n_examples=1)))
    assert "P-EXAMPLES-COUNT" in codes(lint(tmp_path, prompt_text(n_examples=4)))


def test_example_output_invalid(tmp_path: Path) -> None:
    found = lint(tmp_path, prompt_text(example_out={"claims": []}))
    assert "P-EXAMPLE-INVALID" in codes(found)


def test_example_input_invalid_against_input_schema(tmp_path: Path) -> None:
    assert "P-EXAMPLE-INPUT-INVALID" in codes(lint(tmp_path, prompt_text(example_in={"x": 1})))


def test_example_without_output_block(tmp_path: Path) -> None:
    text = prompt_text().replace("Output:", "Result:")
    assert "P-EXAMPLE-OUTPUT" in codes(lint(tmp_path, text))


def test_example_not_json(tmp_path: Path) -> None:
    text = prompt_text(with_input_schema=False).replace('"claims": []', '"claims": [')
    assert "P-EXAMPLE-JSON" in codes(lint(tmp_path, text))


def test_inline_input_reference_is_skipped(tmp_path: Path) -> None:
    text = prompt_text(example_in={"x": 1}).replace("Input:\n", "Input: as Example 1 with\n")
    assert "P-EXAMPLE-INPUT-INVALID" not in codes(lint(tmp_path, text))


def test_lint_prompts_walks_tree_and_skips_template(tmp_path: Path) -> None:
    root = tmp_path / "v4"
    d = root / "prompts" / "agent_06_fact_checker"
    d.mkdir(parents=True)
    (d / "claim_extraction.v1.md").write_text(prompt_text(), encoding="utf-8")
    (d / "_TEMPLATE.v1.md").write_text("junk", encoding="utf-8")
    (root / "prompts" / "README.md").write_text("x", encoding="utf-8")
    assert [p.name for p in prompt_files(root)] == ["claim_extraction.v1.md"]
    assert lint_prompts(root) == []
    assert prompt_files(tmp_path / "nope") == []


def test_real_repo_prompts_have_no_unlisted_defects() -> None:
    from amw_evals.baseline import load_baseline

    base = load_baseline(REPO / "scripts" / "docs_lint_baseline.json")
    found = lint_prompts(REPO / "docs" / "v4", REPO)
    assert [f for f in found if f.key not in base] == []
