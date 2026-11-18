"""Rules added by contract integrator pass 1 (docs/v4/CONTRACT_CHANGE_REQUESTS.md).

* CCR-001: gate results (``gate: true``, ``remedy_stage_id``) inside a ``SUCCEEDED`` task;
  WARN/SKIPPED never block; process-integrity failures still break 03 section 5.3 rule 2(b).
* CCR-006: ``amw.owner_topic``.
* CCR-057 / CCR-002 / CCR-003: ``amw.production_type`` and the 24 section 7.1a / 7.2a graphs.
"""

import copy
from typing import Any

import pytest
from pydantic import ValidationError as PydanticError

from amw_core import contracts
from amw_core.errors import SchemaInvalidError
from tests.contract import examples as ex
from tests.docs_tables import stage_table

pytestmark = pytest.mark.contract

LONG_FORM_V2 = stage_table(r"7\.1a ")
SHORTS_V2 = stage_table(r"7\.2a ")


def _both_reject(name: str, model: Any, doc: dict[str, Any]) -> None:
    assert contracts.schema_violations(name, "1.0.0", doc)
    with pytest.raises(PydanticError):
        model.model_validate(doc)


def _output_with(results: list[dict[str, Any]]) -> dict[str, Any]:
    doc = ex.task_output()
    doc["validation_results"] = results
    return doc


# --- CCR-001 gate results ---------------------------------------------------------------


def test_failed_gate_inside_succeeded_task_is_valid() -> None:
    doc = _output_with([ex.task_output()["validation_results"][0], ex.gate_result("FAIL")])
    doc["next_action"]["reason"] = "gate FAILED: qc.audio.integrated_lufs"
    out = contracts.validate_task_output(doc, version="1.0.0")
    assert contracts.meets_success_rule_2b(out)
    assert [r.check_id for r in contracts.gate_failures(out)] == ["qc.audio.integrated_lufs"]
    assert contracts.gate_failures(out)[0].remedy_stage_id == "s07_voice"
    assert contracts.has_gate_results(out)


def test_passed_gate_has_no_failures() -> None:
    out = contracts.validate_task_output(_output_with([ex.gate_result("PASS")]), version="1.0.0")
    assert not contracts.gate_failures(out)
    assert contracts.meets_success_rule_2b(out)


def test_integrity_failure_breaks_the_success_rule() -> None:
    integrity = ex.task_output()["validation_results"][0] | {"verdict": "FAIL"}
    out = contracts.validate_task_output(
        _output_with([integrity, ex.gate_result("PASS")]), version="1.0.0"
    )
    assert not contracts.meets_success_rule_2b(out)  # -> AGENT.INCOMPLETE_OUTPUT (07 section 2)
    assert [r.check_id for r in contracts.integrity_failures(out)] == ["script.length"]
    assert not contracts.gate_failures(out)


def test_non_blocking_integrity_warning_does_not_break_success() -> None:
    warn = ex.task_output()["validation_results"][0] | {"verdict": "WARN", "blocking": False}
    out = contracts.validate_task_output(_output_with([warn]), version="1.0.0")
    assert contracts.meets_success_rule_2b(out)


def test_gate_defaults_to_false_and_round_trips() -> None:
    out = contracts.validate_task_output(ex.task_output(), version="1.0.0")
    assert out.validation_results[0].gate is False
    assert not contracts.has_gate_results(out)
    again = contracts.validate_task_output(out.to_doc(), version="1.0.0")
    assert again == out


@pytest.mark.parametrize("verdict", ["WARN", "SKIPPED"])
def test_warn_or_skipped_must_not_block(verdict: str) -> None:
    result = ex.gate_result(verdict, remedy=None) | {"blocking": True}
    _both_reject("amw.task_output", contracts.TaskOutput, _output_with([result]))


def test_remedy_stage_requires_gate_true() -> None:
    result = ex.gate_result("FAIL") | {"gate": False}
    _both_reject("amw.task_output", contracts.TaskOutput, _output_with([result]))
    missing = ex.gate_result("FAIL")
    del missing["gate"]
    _both_reject("amw.task_output", contracts.TaskOutput, _output_with([missing]))


@pytest.mark.parametrize("bad", ["S07", "x", "a" * 33, 1, True])
def test_remedy_stage_id_format(bad: object) -> None:
    _both_reject(
        "amw.task_output",
        contracts.TaskOutput,
        _output_with([ex.gate_result() | {"remedy_stage_id": bad}]),
    )


def test_gate_must_be_a_boolean() -> None:
    _both_reject(
        "amw.task_output", contracts.TaskOutput, _output_with([ex.gate_result() | {"gate": 1}])
    )


# --- CCR-006 owner topic ----------------------------------------------------------------


def test_owner_topic_valid_and_round_trip() -> None:
    topic = contracts.validate_owner_topic(ex.owner_topic(), version="1.0.0")
    assert topic.video_kind.value == "METHOD_TOPIC"
    assert contracts.validate_owner_topic(topic.to_doc(), version="1.0.0") == topic


@pytest.mark.parametrize(
    ("index", "change"),
    [
        (0, {"url": None}),
        (0, {"knowledge_source_id": "ksr_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e97"}),
        (1, {"url": "https://example.org"}),
        (1, {"knowledge_source_id": None}),
        (0, {"url": "http://insecure.example"}),
        (1, {"knowledge_source_id": "kch_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e97"}),
    ],
)
def test_owner_reference_kind_rules(index: int, change: dict[str, Any]) -> None:
    doc = ex.owner_topic()
    doc["owner_references"][index].update(change)
    _both_reject("amw.owner_topic", contracts.OwnerTopic, doc)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "ab"),
        ("language", "Marathi"),
        ("video_kind", "OTHER"),
        ("target_duration_ms", 999),
        ("target_duration_ms", "600000"),
        ("shorts_wanted", 1),
        ("course_chapter_pointer", {"label": ""}),
        ("owner_references", [ex.owner_topic()["owner_references"][0]] * 21),
    ],
)
def test_owner_topic_field_rules(field: str, value: object) -> None:
    _both_reject("amw.owner_topic", contracts.OwnerTopic, ex.owner_topic() | {field: value})


# --- CCR-057 production type and the 3A graphs -------------------------------------------


@pytest.mark.parametrize(
    ("name", "stages"), [("long_form_v2", LONG_FORM_V2), ("shorts_v2", SHORTS_V2)]
)
def test_3a_graphs_from_24_load(name: str, stages: list[dict[str, Any]]) -> None:
    assert len(stages) >= 5, name
    record = contracts.validate_production_type(ex.production_type(stages), version="1.0.0")
    ancestors = contracts.stage_ancestors(record.stages)
    for stage in record.stages:
        assert stage.stage_id not in ancestors[stage.stage_id]
    assert contracts.validate_production_type(record.to_doc(), version="1.0.0") == record


def test_long_form_v2_routes_match_24() -> None:
    record = contracts.validate_production_type(ex.production_type(LONG_FORM_V2), version="1.0.0")
    qc = record.stage("s10_qc").gate
    assert qc is not None
    assert qc.on_fail.action == "REVISE"
    assert isinstance(qc.on_fail, contracts.production_type.ReviseOnFail)
    assert qc.on_fail.target_stage_id == "s10_render"
    assert qc.on_fail.alt_target_stage_ids == ("s07_voice", "s08_assets", "s09_plan")
    auth = record.stage("s16_auth").gate
    assert auth is not None
    assert auth.on_fail.action == "STOP"
    final = record.stage("a_final").approval
    assert final is not None
    assert final.approval_kind.value == "FINAL_VIDEO"


def _record_with(mutate: Any) -> dict[str, Any]:
    doc = ex.production_type(copy.deepcopy(LONG_FORM_V2))
    mutate(doc)
    return doc


def _stage(doc: dict[str, Any], stage_id: str) -> dict[str, Any]:
    found: dict[str, Any] = next(s for s in doc["stages"] if s["stage_id"] == stage_id)
    return found


def _apply(doc: dict[str, Any], stage_id: str | None, keys: str, value: Any) -> None:
    target: dict[str, Any] = _stage(doc, stage_id) if stage_id else doc
    *head, last = keys.split(".")
    for key in head:
        target = target[key]
    target[last] = value


NO_LIMIT: dict[str, Any] = {"mandatory": [], "by_category": {}}
STOP_WITH_TARGET = {"action": "STOP", "target_stage_id": "a_final"}
FINAL_PRICE = {"amount_minor": 1, "currency": "INR", "label": "FINAL"}
LOAD_RULES = [
    ("target-not-ancestor", "s10_qc", "gate.on_fail.target_stage_id", "s16_auth"),
    ("alt-not-ancestor", "s06_verify", "gate.on_fail.alt_target_stage_ids", ["s13_deliver"]),
    ("cycle", "s04_research", "depends_on", ["s13_deliver"]),
    ("unknown-dependency", "s05_script", "depends_on", ["s99_missing"]),
    ("duplicate-stage", "s05_script", "stage_id", "s04_research"),
    ("youtube-without-general-pack", None, "destinations", ["YOUTUBE"]),
]
SCHEMA_RULES = [
    ("gate-not-blocking", "s10_qc", "gate.blocking", False),
    ("revise-without-target", "s10_qc", "gate.on_fail", {"action": "REVISE"}),
    ("stop-with-target", "s16_auth", "gate.on_fail", STOP_WITH_TARGET),
    ("bad-task-type", "s05_script", "task_type", "agent_99.x"),
    ("unknown-capability", "s05_script", "capabilities", ["telepathy"]),
    ("revision-loops-over-ceiling", None, "limits", {"max_revision_loops": 11}),
    ("price-not-proposal", None, "default_price", FINAL_PRICE),
    ("params-too-many", "s06_chart", "params", {f"k{i}": i for i in range(17)}),
]


@pytest.mark.parametrize(("case", "stage_id", "keys", "value"), LOAD_RULES)
def test_load_rules_reject(case: str, stage_id: str | None, keys: str, value: Any) -> None:
    doc = ex.production_type(copy.deepcopy(LONG_FORM_V2))
    _apply(doc, stage_id, keys, value)
    if case == "youtube-without-general-pack":
        doc["rule_packs"] = NO_LIMIT
    assert not contracts.schema_violations("amw.production_type", "1.0.0", doc), case
    with pytest.raises(SchemaInvalidError):
        contracts.validate_production_type(doc, version="1.0.0")


@pytest.mark.parametrize(("case", "stage_id", "keys", "value"), SCHEMA_RULES)
def test_schema_rules_reject_in_both_layers(
    case: str, stage_id: str | None, keys: str, value: Any
) -> None:
    doc = ex.production_type(copy.deepcopy(LONG_FORM_V2))
    _apply(doc, stage_id, keys, value)
    _both_reject("amw.production_type", contracts.ProductionType, doc)


def test_stage_params_and_enabled_by_default() -> None:
    def add(d: dict[str, Any]) -> None:
        _stage(d, "s06_chart")["params"] = {"verify_mode": "CHART_FACTS"}
        _stage(d, "a_script")["enabled_by_default"] = False

    record = contracts.validate_production_type(_record_with(add), version="1.0.0")
    assert record.stage("s06_chart").params == {"verify_mode": "CHART_FACTS"}
    assert record.stage("a_script").enabled_by_default is False
