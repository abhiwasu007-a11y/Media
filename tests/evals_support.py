"""Builders for a minimal valid prompt + eval dataset tree used by the amw_evals tests."""

import json
from pathlib import Path

OUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["claims", "overall", "refusal"],
    "properties": {
        "claims": {"type": "array"},
        "overall": {
            "type": "object",
            "required": ["proposed_verdict"],
            "properties": {"proposed_verdict": {"enum": ["ALLOWED", "BLOCKED"]}},
        },
        "refusal": {"oneOf": [{"type": "null"}, {"type": "object"}]},
    },
}
IN_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["segments"],
    "properties": {"segments": {"type": "array"}},
}
OK_OUT: dict[str, object] = {
    "claims": [],
    "overall": {"proposed_verdict": "ALLOWED"},
    "refusal": None,
}
OK_IN = {"segments": [{"segment_id": "s1", "text": "hello world", "visual_refs": []}]}


def _j(obj: object) -> str:
    return "```json\n" + json.dumps(obj, indent=1) + "\n```"


def prompt_text(
    *,
    sections: tuple[str, ...] = (
        "Role",
        "Objective",
        "Inputs",
        "Rules",
        "Output JSON Schema",
        "Worked examples",
        "Refusal and escalation",
        "Self-check",
    ),
    extra_rules: str = "",
    out_schema: object = OUT_SCHEMA,
    n_examples: int = 2,
    example_out: object = OK_OUT,
    example_in: object = OK_IN,
    prompt_id: str = "agent_06/claim_extraction.v1",
    with_input_schema: bool = True,
    inputs_vars: str = "`{{segments}}`",
) -> str:
    header = (
        "# t\n\n| Field | Value |\n|---|---|\n"
        f"| Prompt ID | `{prompt_id}` |\n| Task type | `agent_06.claim_extraction` |\n"
        "| Status | Draft |\n| Input payload schema | x |\n| Output payload schema | y |\n"
        "| Eval set | z |\n| Config keys | k |\n"
    )
    bodies = {
        "Inputs": f"| Variable | Type |\n|---|---|\n| {inputs_vars} | list |",
        "Rules": "1. Be good. " + extra_rules + "\n\n{{rule_pack:rp.x}}",
        "Output JSON Schema": _j(out_schema),
        "Worked examples": "\n".join(
            f"### Example {i} — name\nInput:\n{_j(example_in)}\nOutput:\n{_j(example_out)}\n"
            for i in range(1, n_examples + 1)
        ),
    }
    parts = [header]
    for s in sections:
        parts.append(f"## {s}\n{bodies.get(s, 'text')}\n")
    if with_input_schema:
        parts.append(f"## A. Input payload schema\n{_j(IN_SCHEMA)}\n")
    return "\n".join(parts)


def case(cid: str, category: str = "EDGE", **expected: object) -> dict[str, object]:
    return {
        "case_id": cid,
        "category": category,
        "description": "d",
        "input": OK_IN,
        "expected": expected,
        "judge_min": None,
        "notes": "",
    }


def build_tree(
    root: Path,
    cases: list[dict[str, object]] | None = None,
    prompt: str | None = None,
    readme: str | None = "| Overall case pass rate | ≥ 0.50 |\n",
) -> Path:
    """Create <root>/prompts/agent_06_fact_checker/claim_extraction.v1.md and its dataset."""
    p = root / "prompts" / "agent_06_fact_checker"
    p.mkdir(parents=True)
    (p / "claim_extraction.v1.md").write_text(prompt or prompt_text(), encoding="utf-8")
    d = root / "evals" / "agent_06_fact_checker" / "claim_extraction"
    d.mkdir(parents=True)
    rows = cases if cases is not None else [case(f"C-{i:02d}") for i in range(20)]
    (d / "cases.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    if readme is not None:
        (d / "README.md").write_text(readme, encoding="utf-8")
    (d / "rubric.md").write_text("r", encoding="utf-8")
    return d
