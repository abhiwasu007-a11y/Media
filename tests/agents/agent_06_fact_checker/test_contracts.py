"""Contract tests (C-01 ...): payloads against the JSON Schemas published in the docs."""

# ruff: noqa: E501, PT018

import json
import re
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from agent_06_fact_checker.models import (
    ExtractionInput,
    ExtractionOutput,
    VerificationBatchOutput,
    VerificationInput,
    VerificationOutput,
)
from amw_core.contracts.validation import validate_task_output
from amw_core.enums import OutputStatus
from tests.agents.agent_06_fact_checker.eval_support import ExtractionStepAdapter, load_cases
from tests.agents.agent_06_fact_checker.support import DOCS, PROMPTS
from tests.agents.agent_06_fact_checker.verification_harness import RespondingLlm, run_case

pytestmark = pytest.mark.contract
BLUEPRINT = (DOCS / "agents" / "agent_06_fact_checker.md").read_text(encoding="utf-8")
_FENCE = re.compile(r"```json\n(.*?)\n```", re.DOTALL)


def schema_after(text: str, heading: str) -> dict[str, Any]:
    start = text.index(heading)
    match = _FENCE.search(text, start)
    assert match is not None
    loaded: dict[str, Any] = json.loads(match.group(1))
    return loaded


def validator(schema: dict[str, Any]) -> Draft202012Validator:
    return Draft202012Validator(schema)


EXTRACTION = (PROMPTS / "claim_extraction.v1.md").read_text(encoding="utf-8")
VERIFICATION = (PROMPTS / "claim_verification.v1.md").read_text(encoding="utf-8")
EXT_IN = validator(schema_after(EXTRACTION, "## A. Input payload schema"))
EXT_OUT = validator(schema_after(EXTRACTION, "## Output JSON Schema"))
VER_IN = validator(schema_after(BLUEPRINT, "### 7.2 `agent_06.claim_verification.input`"))
VER_OUT = validator(schema_after(BLUEPRINT, "### 8.2 `agent_06.claim_verification.output`"))
BATCH_OUT = validator(schema_after(VERIFICATION, "## Output JSON Schema"))


def test_every_dataset_input_validates_against_schema_and_model() -> None:
    for case in load_cases("claim_extraction").values():
        assert not list(EXT_IN.iter_errors(case["input"])), case["case_id"]
        ExtractionInput.model_validate(case["input"])
    for case in load_cases("claim_verification").values():
        assert not list(VER_IN.iter_errors(case["input"])), case["case_id"]
        VerificationInput.model_validate(case["input"])


def test_extraction_outputs_validate_against_the_published_schema() -> None:
    cases = load_cases("claim_extraction")
    adapter = ExtractionStepAdapter(cases)
    from amw_evals.adapter import LlmRequest

    for cid in cases:
        out = adapter.complete(LlmRequest(cid, "p", "t", {}, None)).output
        assert not list(EXT_OUT.iter_errors(out)), cid
        ExtractionOutput.model_validate(out)


def test_verification_outputs_and_model_batches_validate() -> None:
    seen = 0
    for cid, case in load_cases("claim_verification").items():
        run = run_case(case)
        if run.output.status is OutputStatus.SUCCEEDED and run.output.payload is not None:
            doc = run.output.payload.data
            assert not list(VER_OUT.iter_errors(doc)), cid
            VerificationOutput.model_validate(doc)
            validate_task_output(run.output.to_doc(), version="1.0.0")
            seen += 1
        assert isinstance(run.llm, RespondingLlm)
        for request in run.llm.requests:
            assert request.messages[0].content.startswith("<<<INPUT")
    assert seen >= 35


def test_batch_output_models_match_the_prompt_schema() -> None:
    good: dict[str, Any] = {
        "results": [],
        "claim_conflicts": [],
        "passage_flags": [],
        "refusal": None,
    }
    assert not list(BATCH_OUT.iter_errors(good))
    VerificationBatchOutput.model_validate(good)
    bad = dict(
        good,
        refusal={
            "reason": "UNSAFE_CONTENT",
            "message": "m",
            "missing_inputs": [],
            "violated_rule_ids": [],
        },
    )
    bad["results"] = [
        {"local_id": "c1", "assessment": "SUPPORTED", "evidence": [], "discrepancies": [], "certainty": "HIGH", "suggested_correction": None, "rationale": "r"}
    ]  # fmt: skip
    assert list(BATCH_OUT.iter_errors(bad))
    with pytest.raises(ValueError, match="refusal"):
        VerificationBatchOutput.model_validate(bad)


def test_prompt_files_load_with_their_variables_and_no_undeclared_placeholder() -> None:
    from agent_06_fact_checker.prompts import parse_prompt_doc, render_system
    from tests.agents.agent_06_fact_checker.support import StaticPacks

    ext = parse_prompt_doc(
        "agent_06/claim_extraction.v1", (PROMPTS / "claim_extraction.v1.md").read_bytes()
    )
    assert {"segments", "chart_data_refs", "available_citations"} <= ext.declared_variables
    rendered = render_system(ext, StaticPacks(), ("rp.youtube_general", "rp.finance_sebi_in"))
    assert rendered.rule_pack_versions == {"rp.youtube_general": 1, "rp.finance_sebi_in": 1}
    inactive = render_system(ext, StaticPacks(), ("rp.youtube_general",))
    assert "[rules of rp.finance_sebi_in]" not in inactive.system
    ver = parse_prompt_doc(
        "agent_06/claim_verification.v1", (PROMPTS / "claim_verification.v1.md").read_bytes()
    )
    assert "claims" in ver.declared_variables and render_system(ver, None, ()).system.startswith(
        "## Role"
    )
    no_resolver = parse_prompt_doc("x/y", b"## Role\nuse {{rule_pack:rp.a}} {{undeclared}}\n")
    with pytest.raises(Exception, match="rule packs"):
        render_system(no_resolver, None, ("rp.a",))
    with pytest.raises(Exception, match="undeclared"):
        render_system(no_resolver, StaticPacks(), ("rp.a",))
    with pytest.raises(Exception, match="no Role"):
        parse_prompt_doc("x/y", b"nothing")
