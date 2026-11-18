"""C-01...C-06: every payload validates against the agent-owned JSON Schemas of the blueprint
(7.2, 7.3, 7.4, 8.1, 8.2), and the Pydantic models agree with them."""

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from agent_07_voice_production import contracts as c
from amw_core.contracts import registry
from amw_core.contracts.validation import validate_task_output
from tests.agents.agent_07_voice_production.master_world import build as build_master
from tests.agents.agent_07_voice_production.voice_world import build as build_voice

ROOT = Path(__file__).resolve().parents[3]
BLUEPRINT = (ROOT / "docs/v4/agents/agent_07_voice_production.md").read_text(encoding="utf-8")
EVALS = ROOT / "docs/v4/evals/agent_07_voice_production"
pytestmark = pytest.mark.contract


def schemas() -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for block in re.findall(r"```json\n(.*?)\n```", BLUEPRINT, flags=re.S):
        doc = json.loads(block)
        if isinstance(doc, dict) and str(doc.get("$id", "")).startswith("urn:amw:schema:agent_07."):
            found[doc["$id"].split(":")[3]] = doc
    return found


SCHEMAS = schemas()


def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(SCHEMAS[name], registry=registry._registry())


def cases(name: str) -> list[dict[str, Any]]:
    return [
        json.loads(x) for x in (EVALS / name / "cases.jsonl").read_text("utf-8").splitlines() if x
    ]


def test_all_five_blueprint_schemas_are_found() -> None:
    assert set(SCHEMAS) == {
        "agent_07.voice_synthesis.input",
        "agent_07.voice_synthesis.output",
        "agent_07.audio_master.input",
        "agent_07.audio_master.output",
        "agent_07.pronunciation_dictionary",
    }


def test_dataset_payloads_validate_against_the_input_schemas_and_models() -> None:
    for case in cases("voice_synthesis"):
        validator("agent_07.voice_synthesis.input").validate(case["input"]["payload"])
        c.VoiceSynthesisInput.model_validate(case["input"]["payload"])
        validator("agent_07.pronunciation_dictionary").validate(
            {
                "dictionary_key": "test-dict",
                "language": "mr-IN",
                "version": 1,
                "entries": case["input"]["fixtures"]["dictionary"]["entries"],
            }
        )
    for case in cases("audio_master"):
        validator("agent_07.audio_master.input").validate(case["input"]["payload"])
        c.AudioMasterInput.model_validate(case["input"]["payload"])


def test_unknown_payload_fields_are_refused() -> None:
    payload = copy.deepcopy(cases("voice_synthesis")[0]["input"]["payload"])
    payload["monetized_destination"] = (
        True  # licence checks read the job, never the payload (CCR-028)
    )
    assert list(validator("agent_07.voice_synthesis.input").iter_errors(payload))
    with pytest.raises(ValueError, match=r"validation error"):
        c.VoiceSynthesisInput.model_validate(payload)


def test_voice_output_validates_against_the_schema(tmp_path: Path) -> None:
    by_id = {x["case_id"]: x for x in cases("voice_synthesis")}
    for case_id in ("VS-01", "VS-12", "VS-18", "VS-41", "VS-07"):
        out = build_voice(copy.deepcopy(by_id[case_id]), tmp_path / case_id).run()
        assert out.payload is not None, case_id
        assert out.payload.data is not None, case_id
        validator("agent_07.voice_synthesis.output").validate(out.payload.data)
        validate_task_output(out.model_dump(mode="json"), version="1.0.0")  # envelope contract


def test_master_output_validates_against_the_schema(tmp_path: Path) -> None:
    by_id = {x["case_id"]: x for x in cases("audio_master")}
    for case_id in ("AM-01", "AM-05", "AM-08", "AM-14", "AM-20", "AM-27"):
        out = build_master(copy.deepcopy(by_id[case_id]), tmp_path / case_id).run()
        assert out.payload is not None, case_id
        assert out.payload.data is not None, case_id
        validator("agent_07.audio_master.output").validate(out.payload.data)
        validate_task_output(out.model_dump(mode="json"), version="1.0.0")
        assert out.quality_score is None
        assert out.confidence is None
        assert out.resource_usage.llm_calls == 0  # no LLM step


def test_output_models_forbid_extra_fields() -> None:
    with pytest.raises(ValueError, match=r"validation error"):
        c.GateReason.model_validate(
            {
                "check_id": "qc.audio.true_peak",
                "measured": 1.0,
                "threshold": -1.0,
                "remedy_stage_id": "s07_voice",
                "extra": 1,
            }
        )
    with pytest.raises(ValueError, match=r"validation error"):
        c.GateReason.model_validate(
            {
                "check_id": "qc.audio.true_peak",
                "measured": 1.0,
                "threshold": -1.0,
                "remedy_stage_id": "s05_script",
            }
        )
