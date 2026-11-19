"""Contract tests (C-01..C-03, C-07, C-08): models and outputs against the blueprint's schemas."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from agent_10_video_editor import contracts as K  # noqa: N812
from agent_10_video_editor.ports import QcRow, RenderRow
from agent_10_video_editor.qc.gate import PROFILE_CHECKS
from agent_10_video_editor.qc.result import REMEDY, REMEDY_TARGETS, RemedyMapper
from agent_10_video_editor.qc.stage import QcStage
from amw_core.contracts.task_output import gate_failures, has_gate_results, meets_success_rule_2b
from tests.agents.agent_10_video_editor.support import (
    World,
    licensed_snapshot,
    payload_data,
    run_chain,
)
from tests.docs_tables import DOCS, doc_text, section, table_rows

BLUEPRINT = (DOCS / "agents" / "agent_10_video_editor.md").read_text(encoding="utf-8")


def _schemas() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for block in re.findall(r"```json\n(.*?)\n```", BLUEPRINT, flags=re.S):
        if '"$id": "urn:amw:schema:agent_10.' not in block:
            continue
        schema = json.loads(block)
        out[schema["$id"].removeprefix("urn:amw:schema:").removesuffix(":1.0.0")] = schema
    return out


SCHEMAS = _schemas()
REGISTRY: Registry[Any] = Registry().with_resources(
    [
        (s["$id"], Resource.from_contents(s, default_specification=DRAFT202012))
        for s in SCHEMAS.values()
    ]
)
MODELS: dict[str, Any] = {
    "agent_10.render.input": K.RenderInput,
    "agent_10.subtitles.input": K.SubtitlesInput,
    "agent_10.technical_qc.input": K.TechnicalQcInput,
    "agent_10.render.output": K.RenderOutput,
    "agent_10.subtitles.output": K.SubtitlesOutput,
    "agent_10.technical_qc.output": K.TechnicalQcOutput,
    "agent_10.evidence_manifest": K.EvidenceManifest,
}


def _validate(name: str, instance: Any) -> None:
    Draft202012Validator(SCHEMAS[name], registry=REGISTRY).validate(instance)


def _field_names(model: Any) -> tuple[set[str], set[str]]:
    props, required = set(), set()
    for name, info in model.model_fields.items():
        alias = info.alias or name
        props.add(alias)
        if info.is_required():
            required.add(alias)
    return props, required


@pytest.mark.contract
def test_all_seven_blueprint_schemas_are_found() -> None:
    assert set(SCHEMAS) == set(MODELS)


@pytest.mark.contract
@pytest.mark.parametrize("name", sorted(MODELS))
def test_c01_c02_model_fields_equal_schema_fields(name: str) -> None:
    schema = SCHEMAS[name]
    props, required = _field_names(MODELS[name])
    assert props == set(schema["properties"])
    assert required == set(schema["required"])


@pytest.mark.contract
def test_nested_object_field_names_equal_schema(tmp_path: Path) -> None:
    schema = SCHEMAS["agent_10.render.output"]["properties"]
    render_models: list[tuple[str, Any]] = [
        ("segments", K.SegmentsOut),
        ("encoder", K.EncoderOut),
        ("probe", K.ProbeOut),
        ("guards", K.GuardsOut),
        ("provenance", K.ProvenanceOut),
        ("fps", K.FpsOut),
    ]
    for field, model in render_models:
        assert set(model.model_fields) == set(schema[field]["properties"]), field
    qc = SCHEMAS["agent_10.technical_qc.output"]["properties"]
    qc_models: list[tuple[str, Any]] = [
        ("measurements", K.MeasurementsOut),
        ("tier_mix", K.TierMixOut),
        ("evidence", K.EvidenceOut),
        ("selftest", K.SelftestOut),
    ]
    for field, model in qc_models:
        assert set(model.model_fields) == set(qc[field]["properties"]), field
    item = qc["failures"]["items"]["properties"]
    assert set(K.FailureOut.model_fields) == set(item)
    assert {i.alias or n for n, i in K.CountsOut.model_fields.items()} == set(
        qc["counts"]["properties"]
    )


@pytest.mark.contract
def test_real_outputs_validate_against_the_blueprint_schemas(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.licences.snapshot_value = licensed_snapshot(world)
    chain = run_chain(world)
    _validate("agent_10.render.output", payload_data(chain["render"]))
    _validate("agent_10.subtitles.output", payload_data(chain["subtitles"]))
    _validate(
        "agent_10.render.input",
        payload_data(world.render_input().model_copy())
        if False
        else world.render_input().payload.data,
    )
    _validate("agent_10.technical_qc.input", chain["qc_input"].payload.data)

    class _ST:
        def record_for(self, build_id: str) -> Any:
            from agent_10_video_editor.qc.selftest import SelfTestCase, SelfTestRecord

            return SelfTestRecord(build_id, (SelfTestCase("c", "PASS", "PASS"),))

    qc = QcStage(world.deps(), _ST()).execute(chain["qc_input"], world.attempt)
    data = payload_data(qc)
    _validate("agent_10.technical_qc.output", data)
    manifest_uri = data["evidence"]["manifest_ref"]["uri"]
    _validate("agent_10.evidence_manifest", json.loads(world.storage.blobs[manifest_uri]))
    # C-03: the envelope and the success rule
    assert meets_success_rule_2b(qc)
    assert has_gate_results(qc)
    assert (data["gate_verdict"] == "FAILED") == bool(gate_failures(qc))
    for out in (chain["render"], chain["subtitles"]):
        assert meets_success_rule_2b(out)
        assert not has_gate_results(out)
        assert out.quality_score is None
        assert out.confidence is None
        assert out.resource_usage.llm_calls == 0
        assert out.resource_usage.provider_calls == 0
        assert out.resource_usage.cost_estimate_micros == 0
        assert out.resource_usage.render_ms is not None


@pytest.mark.contract
def test_c08_every_gate_check_has_a_remedy_that_is_a_s10_qc_target() -> None:
    for check_id in PROFILE_CHECKS:
        assert re.fullmatch(r"[a-z0-9_.-]{3,96}", check_id)
        assert RemedyMapper.map(check_id) in REMEDY_TARGETS
    assert set(REMEDY) == set(PROFILE_CHECKS)
    # the targets are exactly the target plus the alternatives of s10_qc in 24 section 7.1a
    text = doc_text("24_PRODUCTION_TYPES.md")
    assert "s10_qc" in text
    for stage in REMEDY_TARGETS:
        assert stage in text


@pytest.mark.contract
def test_check_ids_equal_the_table_of_section_20_1() -> None:
    body = section(BLUEPRINT, r"20\.1", 3)
    ids = [
        row[1].strip("`") for row in table_rows(body) if len(row) >= 3 and row[1].startswith("`")
    ]
    gate_ids = [i for i in ids if i.startswith(("qc.", "edit."))]
    assert gate_ids == list(PROFILE_CHECKS)
    assert [i for i in ids if i.startswith("a10.")] == [
        "a10.q.schema", "a10.q.tenant", "a10.q.upstream", "a10.q.timeline_frames",
        "a10.q.segments_verified", "a10.q.no_provider_call", "a10.q.hash_chain",
        "a10.sub.format", "a10.sub.coverage", "a10.sub.text_from_script",
        "a10.q.colour_tags", "a10.q.gop_settings",
    ]  # fmt: skip


@pytest.mark.contract
def test_c07_row_columns_exist_in_the_database_blueprint() -> None:
    db = doc_text("04_DATABASE_ARCHITECTURE.md")
    renders = section(db, r"5\.18 Renders", 3)
    for column in RenderRow.__dataclass_fields__:
        name = {"render_id": "id", "storage_ref": "storage_ref"}.get(column, column)
        assert name == "id" or re.search(rf"\b{name}\b", renders), column
    qc = db[db.index("**qc_results**") :].split("\n", 1)[0]
    for column in QcRow.__dataclass_fields__:
        if column in ("render_id", "task_id", "job_id"):
            assert re.search(rf"`{column}`", qc), column
        else:
            assert re.search(rf"`{column}\b", qc), column
