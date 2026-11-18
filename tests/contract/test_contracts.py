"""Contract tests: 03 schemas shipped verbatim; valid examples pass; conditional rules reject."""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import BaseModel
from pydantic import ValidationError as PydanticError

from amw_core import contracts
from amw_core.contracts import registry
from amw_core.errors import (
    CrossTenantRefError,
    RateLimitedError,
    SchemaInvalidError,
    SchemaVersionUnsupportedError,
)
from tests.contract import examples as ex
from tests.docs_tables import doc_json_schemas

pytestmark = pytest.mark.contract

Validator = Callable[..., BaseModel]
CASES: list[tuple[str, Callable[[], dict[str, Any]], Validator, str | None]] = [
    ("amw.task_input", ex.task_input, contracts.validate_task_input, None),
    ("amw.envelope", ex.envelope, contracts.validate_envelope, None),
    ("amw.control", ex.control, contracts.validate_control, None),
    ("amw.error", ex.error, contracts.validate_error, "1.0.0"),
    ("amw.task_output", ex.task_output, contracts.validate_task_output, "1.0.0"),
]


def test_every_doc_schema_block_equals_the_shipped_file() -> None:
    blocks = [json.loads(b) for b in doc_json_schemas()]
    assert {b["$id"] for b in blocks} == {
        registry.schema_id(n, v) for (n, v) in registry.all_schemas()
    }
    for block in blocks:
        _, _, rest = block["$id"].partition("urn:amw:schema:")
        name, version = rest.split(":")
        assert registry.get_schema(name, version) == block
    assert set(registry.CONTRACT_SCHEMAS) == {n for (n, _) in registry.all_schemas()}


@pytest.mark.parametrize(("name", "make", "validate", "version"), CASES)
def test_valid_example_passes_and_round_trips(
    name: str, make: Callable[[], dict[str, Any]], validate: Validator, version: str | None
) -> None:
    doc = make()
    model = validate(doc, version=version)
    again = validate(json.loads(model.model_dump_json()), version=version)
    assert again == model
    assert isinstance(model, contracts.AmwModel)
    assert registry.validator(name, "1.0.0").is_valid(model.to_doc())


@pytest.mark.parametrize("status", ["FAILED", "REJECTED", "SUSPENDED"])
def test_other_statuses_valid(status: str) -> None:
    out = contracts.validate_task_output(ex.task_output(status), version="1.0.0")
    assert out.status.value == status


def test_control_envelope_may_omit_job_and_task() -> None:
    doc = ex.envelope("amw.control")
    doc["job_id"] = doc["task_id"] = None
    env = contracts.validate_envelope(doc)
    assert env.is_control


def _schema_rejects(name: str, doc: dict[str, Any]) -> bool:
    return bool(contracts.schema_violations(name, "1.0.0", doc))


def _model_rejects(model: type[BaseModel], doc: dict[str, Any]) -> bool:
    try:
        model.model_validate(doc)
    except PydanticError:
        return True
    return False


def _mut(
    make: Callable[[], dict[str, Any]], change: Callable[[dict[str, Any]], None]
) -> dict[str, Any]:
    doc = make()
    change(doc)
    return doc


def _set(path: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def apply(doc: dict[str, Any]) -> None:
        *head, last = path.split(".")
        target: Any = doc
        for key in head:
            target = target[int(key)] if isinstance(target, list) else target[key]
        if isinstance(target, list):
            target[int(last)] = value
        else:
            target[last] = value

    return apply


def _drop(path: str) -> Callable[[dict[str, Any]], None]:
    def apply(doc: dict[str, Any]) -> None:
        *head, last = path.split(".")
        target: Any = doc
        for key in head:
            target = target[key]
        del target[last]

    return apply


# (schema name, model, broken doc) - each is a documented rule; both layers must refuse it.
BOTH_LAYERS: list[tuple[str, str, type[BaseModel], dict[str, Any]]] = [
    ("succeeded-with-error", "amw.task_output", contracts.TaskOutput,
     _mut(ex.task_output, _set("error", ex.error()))),
    ("succeeded-without-payload", "amw.task_output", contracts.TaskOutput,
     _mut(ex.task_output, _set("payload", None))),
    ("failed-without-error", "amw.task_output", contracts.TaskOutput,
     _mut(lambda: ex.task_output("FAILED"), _set("error", None))),
    ("rejected-without-error", "amw.task_output", contracts.TaskOutput,
     _mut(lambda: ex.task_output("REJECTED"), _set("error", None))),
    ("suspended-without-wait-reason", "amw.task_output", contracts.TaskOutput,
     _mut(lambda: ex.task_output("SUSPENDED"), _set("next_action.wait_reason", None))),
    ("suspended-not-wait", "amw.task_output", contracts.TaskOutput,
     _mut(lambda: ex.task_output("SUSPENDED"), _set("next_action.type", "CONTINUE"))),
    ("quality-over-100", "amw.task_output", contracts.TaskOutput,
     _mut(ex.task_output, _set("quality_score", 101))),
    ("negative-duration", "amw.task_output", contracts.TaskOutput,
     _mut(ex.task_output, _set("duration", -1))),
    ("payload-data-and-ref", "amw.task_input", contracts.TaskInput,
     _mut(ex.task_input, _set("payload.data_ref", ex.blob()))),
    ("payload-ref-without-sha", "amw.task_output", contracts.TaskOutput,
     _mut(ex.task_output, _drop("payload.data_sha256"))),
    ("payload-neither", "amw.task_input", contracts.TaskInput,
     _mut(ex.task_input, _drop("payload.data"))),
    ("extra-top-level-field", "amw.task_input", contracts.TaskInput,
     _mut(ex.task_input, _set("surprise", 1))),
    ("missing-nullable-field", "amw.task_input", contracts.TaskInput,
     _mut(ex.task_input, _drop("channel_id"))),
    ("wrong-id-prefix", "amw.task_input", contracts.TaskInput,
     _mut(ex.task_input, _set("job_id", ex.TASK.replace("tsk_", "job_")[:-1] + "Z"))),
    ("task-id-as-job-id", "amw.task_input", contracts.TaskInput,
     _mut(ex.task_input, _set("task_id", ex.JOB))),
    ("money-as-float", "amw.task_input", contracts.TaskInput,
     _mut(ex.task_input, _set("resource_budget.max_cost_micros", 1.5))),
    ("bad-currency", "amw.task_input", contracts.TaskInput,
     _mut(ex.task_input, _set("resource_budget.currency", "inr"))),
    ("retry-count-over-cap", "amw.task_input", contracts.TaskInput,
     _mut(ex.task_input, _set("retry_count", 101))),
    ("executor-is-human", "amw.task_input", contracts.TaskInput,
     _mut(ex.task_input, _set("agent_id", "sys_scheduler"))),
    ("dispatch-without-job", "amw.envelope", contracts.Envelope,
     _mut(ex.envelope, _set("job_id", None))),
    ("result-without-task", "amw.envelope", contracts.Envelope,
     _mut(lambda: ex.envelope("amw.task_output"), _set("task_id", None))),
    ("payload-ref-not-json", "amw.envelope", contracts.Envelope,
     _mut(ex.envelope, _set("payload_ref.media_type", "text/plain"))),
    ("control-unknown-command", "amw.control", contracts.ControlCommand,
     _mut(ex.control, _set("command", "STOP"))),
    ("control-empty-reason", "amw.control", contracts.ControlCommand,
     _mut(ex.control, _set("reason", ""))),
    ("error-bad-code", "amw.error", contracts.ErrorObject,
     _mut(ex.error, _set("code", "TEMPORARY.x"))),
    ("error-upstream-status", "amw.error", contracts.ErrorObject,
     _mut(ex.error, _set("upstream_status", 99))),
]  # fmt: skip


@pytest.mark.parametrize(
    ("case", "name", "model", "doc"), BOTH_LAYERS, ids=[c[0] for c in BOTH_LAYERS]
)
def test_rule_rejected_by_schema_and_model(
    case: str, name: str, model: type[BaseModel], doc: dict[str, Any]
) -> None:
    assert _schema_rejects(name, doc), case
    assert _model_rejects(model, doc), case


# Rules 03 states outside the schema: only the model (and so validate_*) refuses them.
MODEL_ONLY: list[tuple[str, str, Validator, dict[str, Any]]] = [
    ("error-class-not-code-prefix", "amw.error", contracts.validate_error,
     _mut(ex.error, _set("error_class", "PERMANENT"))),
    ("error-code-not-in-catalogue", "amw.error", contracts.validate_error,
     _mut(ex.error, lambda d: d.update(code="TEMPORARY.SOLAR_FLARE"))),
    ("rejected-with-output-refs", "amw.task_output", contracts.validate_task_output,
     _mut(lambda: ex.task_output("REJECTED"),
          _set("output_refs", ex.task_output()["output_refs"]))),
    ("rejected-attempt-not-zero", "amw.task_output", contracts.validate_task_output,
     _mut(lambda: ex.task_output("REJECTED"), _set("error.attempt_no", 2))),
]  # fmt: skip


@pytest.mark.parametrize(
    ("case", "name", "validate", "doc"), MODEL_ONLY, ids=[c[0] for c in MODEL_ONLY]
)
def test_model_only_rules(case: str, name: str, validate: Validator, doc: dict[str, Any]) -> None:
    assert not _schema_rejects(name, doc), case
    with pytest.raises(SchemaInvalidError) as info:
        validate(doc, version="1.0.0")
    assert info.value.details["violations"][0]["keyword"] == "model"


def test_schema_violation_details_are_json_pointers() -> None:
    doc = _mut(ex.task_input, _set("resource_budget.currency", "inr"))
    with pytest.raises(SchemaInvalidError) as info:
        contracts.validate_task_input(doc)
    violation = info.value.details["violations"][0]
    assert violation["path"] == "/resource_budget/currency"
    assert violation["keyword"] == "pattern"
    contracts.Violation.model_validate(violation)


@pytest.mark.parametrize(
    "uri", [ex.blob(ex.OTHER_ORG), f"amw-entity://{ex.OTHER_ORG}/assets/{ex.JOB}"]
)
def test_cross_tenant_context_ref(uri: str) -> None:
    doc = ex.task_input()
    doc["context_refs"][0]["uri"] = uri
    with pytest.raises(CrossTenantRefError):
        contracts.validate_task_input(doc)


def test_cross_tenant_payload_data_ref() -> None:
    doc = ex.task_input()
    doc["payload"] = {
        "payload_schema": "a.b",
        "payload_schema_version": "1.0.0",
        "data_ref": ex.blob(ex.OTHER_ORG),
        "data_sha256": ex.SHA,
    }
    with pytest.raises(CrossTenantRefError):
        contracts.validate_task_input(doc)


def test_envelope_payload_of_another_org() -> None:
    doc = ex.envelope()
    doc["payload_ref"]["uri"] = ex.blob(ex.OTHER_ORG)
    with pytest.raises(CrossTenantRefError):
        contracts.validate_envelope(doc)


def test_unsupported_version() -> None:
    doc = ex.task_input()
    doc["schema_version"] = "2.0.0"
    with pytest.raises(SchemaVersionUnsupportedError):
        contracts.validate_task_input(doc)
    with pytest.raises(SchemaVersionUnsupportedError):
        contracts.validate_task_output(ex.task_output(), version="1.1.0")


def test_malformed_version_is_schema_invalid() -> None:
    doc = ex.task_input()
    doc["schema_version"] = "one"
    with pytest.raises(SchemaInvalidError):
        contracts.validate_task_input(doc)


def test_wire_timestamps_must_be_utc_z() -> None:
    doc = _mut(ex.task_input, _set("deadline", "2026-01-01T05:30:00+05:30"))
    with pytest.raises(SchemaInvalidError):
        contracts.validate_task_input(doc)


def test_non_object_document() -> None:
    with pytest.raises(SchemaInvalidError):
        contracts.validate_control(["DRAIN"])


def test_timestamps_accept_only_utc() -> None:
    utc = contracts.ControlCommand(
        command="PAUSE", reason="r", act_by=datetime(2026, 1, 1, tzinfo=UTC), schema_version="1.0.0"
    )
    assert utc.to_doc()["act_by"] == "2026-01-01T00:00:00Z"
    ist = timezone(timedelta(hours=5, minutes=30))
    for bad in (datetime(2026, 1, 1, 5, 30, tzinfo=ist), datetime(2026, 1, 1)):
        with pytest.raises(PydanticError):
            contracts.ControlCommand(
                command="PAUSE", reason="r", act_by=bad, schema_version="1.0.0"
            )


@pytest.mark.parametrize(
    "act_by",
    [
        1767225600,
        1767225600.5,
        "1767225600",
        "2026-01-01",
        "2026-01-01T00:00:00",
        "2026-01-01T05:30:00+05:30",
        "2026-01-01T00:00:00+00:00",
        "2026-13-01T00:00:00Z",
        "2026-01-01 00:00:00Z",
        True,
    ],
)
def test_strict_timestamps(act_by: object) -> None:
    doc = {**ex.control(), "act_by": act_by}
    assert _schema_rejects("amw.control", doc)
    assert _model_rejects(contracts.ControlCommand, doc)
    with pytest.raises(PydanticError):
        contracts.ControlCommand.model_validate_json(json.dumps(doc))


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("validation_results.0.blocking", 1),
        ("validation_results.0.blocking", 0),
        ("validation_results.0.blocking", "true"),
        ("quality_score", "80"),
        ("quality_score", True),
        ("duration", "1500"),
        ("duration", 1500.0),
        ("resource_usage.tokens_in", False),
    ],
)
def test_strict_scalars(path: str, value: object) -> None:
    doc = _mut(ex.task_output, _set(path, value))
    assert _model_rejects(contracts.TaskOutput, doc)
    with pytest.raises(PydanticError):
        contracts.TaskOutput.model_validate_json(json.dumps(doc))
    if value != 1500.0:  # JSON Schema treats 1500.0 as an integer; the model is stricter.
        assert _schema_rejects("amw.task_output", doc)


def test_model_validate_json_accepts_documented_strings() -> None:
    doc = ex.task_output()
    model = contracts.TaskOutput.model_validate_json(json.dumps(doc))
    assert model == contracts.validate_task_output(doc, version="1.0.0")


def test_models_are_frozen() -> None:
    model = contracts.validate_control(ex.control())
    with pytest.raises(PydanticError):
        model.reason = "changed"  # type: ignore[misc]


def test_optional_fields_omitted_not_null() -> None:
    doc = contracts.validate_task_input(ex.task_input()).to_doc()
    assert "schema" not in doc["context_refs"][1]
    assert doc["context_refs"][0]["schema"] == "agent_04.x.output"
    assert "max_tokens_in" not in doc["resource_budget"]
    assert "data_ref" not in doc["payload"]
    assert doc["channel_id"] is None


def test_error_object_from_exception() -> None:
    exc = RateLimitedError("slow", retry_after_ms=5000, provider="anthropic", upstream_status=429)
    obj = contracts.error_object_from_exception(
        exc,
        actor="agent_05",
        attempt_no=1,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        correlation_id=ex.COR,
        extra_details={"note": "x"},
    )
    assert obj.code == "TEMPORARY.RATE_LIMITED"
    assert obj.error_class.value == "TEMPORARY"
    assert obj.retryable is True
    doc = obj.to_doc()
    assert doc["details"] == {"note": "x"}
    assert contracts.validate_error(doc) == obj


def test_error_with_violations_round_trips() -> None:
    try:
        contracts.validate_control({})
    except SchemaInvalidError as exc:
        obj = contracts.error_object_from_exception(
            exc,
            actor="agent_01",
            attempt_no=0,
            occurred_at=datetime.now(UTC),
            correlation_id=ex.COR,
        )
    assert obj.details.violations
    assert contracts.validate_error(obj.to_doc()) == obj
