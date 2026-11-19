# ruff: noqa: PT018
"""``svc_s07.request_approval`` payload schemas (CCR-283 PROVISIONAL): the models, the allow-list
entry, the builder's input, and the round trip through the real ``ApprovalWorker`` and the default
executor (real registry). Fail closed: anything that does not match is ``SCHEMA_INVALID``."""

from collections.abc import Callable
from typing import Any

import pytest

from amw_core.contracts.payloads import PayloadSchemaRegistry
from amw_core.enums import OutputStatus
from amw_core.errors import SchemaInvalidError
from amw_core.ids import APPROVAL, ATTEMPT, OWNER_EVIDENCE, RENDER, Prefix, new_id
from amw_orchestrator.executor import ApprovalWorker, BuildContext, TaskExecutor
from amw_orchestrator.input_builders import BuilderTable
from amw_orchestrator.outputs import now_z
from amw_orchestrator.payloads import ApprovalOutput, ApprovalRequestInput
from tests.orchestrator.builder_world import World
from tests.orchestrator.world import TestDesk, approval_output

pytestmark = pytest.mark.unit

SHA = "ab" * 32


def _registry() -> PayloadSchemaRegistry:
    from amw_core.contracts.payloads import load_payload_schema_plugins

    reg = PayloadSchemaRegistry()
    load_payload_schema_plugins(reg)
    return reg


def _input(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "subject": {"kind": "render", "id": str(RENDER.new()), "sha256": SHA},
        "approval_kind": "FINAL_VIDEO",
        "workflow_key": "owner_one_tap",
    }
    return {**base, **over}


def _validate_input(data: dict[str, Any]) -> None:
    _registry().validate("svc_s07.request_approval.input", "1.0.0", data)


def _validate_output(data: dict[str, Any]) -> None:
    _registry().validate("svc_s07.request_approval.output", "1.0.0", data)


# --- input ------------------------------------------------------------------------------------
def test_a_well_formed_input_validates_and_round_trips() -> None:
    data = _input()
    model = _registry().validate("svc_s07.request_approval.input", "1.0.0", data)
    assert isinstance(model, ApprovalRequestInput)
    assert model.model_dump(mode="json", exclude_none=True) == data


def test_a_set_subject_may_carry_its_ref() -> None:
    subject = {**_input()["subject"], "kind": "knowledge_release", "ref": "tenants/x/doc.json"}
    subject["id"] = "kcl_" + str(RENDER.new()).split("_", 1)[1]
    _validate_input(_input(subject=subject))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: {**d, "extra": 1},  # additionalProperties: false
        lambda d: {k: v for k, v in d.items() if k != "workflow_key"},
        lambda d: {k: v for k, v in d.items() if k != "subject"},
        lambda d: {**d, "approval_kind": "NOT_A_KIND"},
        lambda d: {**d, "workflow_key": "Owner One Tap"},
        lambda d: {**d, "subject": {**d["subject"], "kind": "unlisted_kind"}},
        lambda d: {**d, "subject": {**d["subject"], "sha256": "xyz"}},
        lambda d: {**d, "subject": {**d["subject"], "id": "not-an-id"}},
        lambda d: {**d, "subject": {**d["subject"], "id": new_id(Prefix.SCRIPT)}},  # not a render
        lambda d: {**d, "subject": {**d["subject"], "extra": 1}},
        lambda d: {**d, "subject": {k: v for k, v in d["subject"].items() if k != "sha256"}},
    ],
)
def test_a_malformed_input_is_refused(mutate: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
    with pytest.raises(SchemaInvalidError):
        _validate_input(mutate(_input()))


# --- output -----------------------------------------------------------------------------------
@pytest.mark.parametrize("state", ["PENDING", "APPROVED", "REJECTED", "EXPIRED", "WITHDRAWN"])
def test_every_state_validates_in_the_shape_the_test_desk_emits(state: str) -> None:
    data = approval_output(SHA, state=state)
    model = _registry().validate("svc_s07.request_approval.output", "1.0.0", data)
    assert isinstance(model, ApprovalOutput) and model.state == state


def test_changes_requested_carries_its_target_stage() -> None:
    _validate_output(approval_output(SHA, state="CHANGES_REQUESTED", target_stage="s05_script"))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: {**d, "state": "OPEN"},  # not a GLOSSARY 6.13 state (what the old desk said)
        lambda d: {**d, "extra": 1},
        lambda d: {k: v for k, v in d.items() if k != "approval_id"},
        lambda d: {k: v for k, v in d.items() if k != "subject_sha256"},
        lambda d: {k: v for k, v in d.items() if k != "evidence_ids"},
        lambda d: {k: v for k, v in d.items() if k != "parsed_target_stage_id"},
        lambda d: {**d, "approval_id": "x"},  # the old test payload
        lambda d: {**d, "approval_id": str(RENDER.new())},  # wrong prefix
        lambda d: {**d, "evidence_ids": ["oie_nope"]},
        lambda d: {**d, "evidence_ids": [str(APPROVAL.new())]},  # an approval is not evidence
        lambda d: {**d, "evidence_ids": []},  # an owner decision without confirmed evidence
        lambda d: {**d, "parsed_target_stage_id": "s05_script"},  # target on a plain approval
        lambda d: {**d, "subject_sha256": "short"},
        lambda d: {**d, "approval_kind": "NOPE"},
        lambda d: {"state": "APPROVED"},  # the earlier minimal shape (CCR-278)
    ],
)
def test_a_malformed_output_is_refused(mutate: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
    with pytest.raises(SchemaInvalidError):
        _validate_output(mutate(approval_output(SHA)))


def test_a_change_request_without_a_stage_word_is_refused() -> None:
    with pytest.raises(SchemaInvalidError):
        _validate_output(approval_output(SHA, state="CHANGES_REQUESTED"))


def test_a_pending_approval_needs_no_evidence_and_an_expired_one_none() -> None:
    for state in ("PENDING", "EXPIRED", "WITHDRAWN"):
        data = approval_output(SHA, state=state)
        assert data["evidence_ids"] == []
        _validate_output(data)
    assert OWNER_EVIDENCE.validate(str(approval_output(SHA)["evidence_ids"][0]))  # type: ignore[index]


# --- the builder's input is the registered model ------------------------------------------------
@pytest.mark.parametrize(
    ("stage_id", "kind", "subject_kind", "id_prefix"),
    [("a_final", "FINAL_VIDEO", "render", "rnd_")],
)
def test_the_builder_input_validates_against_the_registered_model(
    stage_id: str, kind: str, subject_kind: str, id_prefix: str
) -> None:
    w = World()
    built = BuilderTable().build(w.ctx(stage_id))
    assert built.payload_schema == "svc_s07.request_approval.input"
    model = _registry().validate(built.payload_schema, built.payload_schema_version, built.data)
    assert isinstance(model, ApprovalRequestInput)
    assert model.approval_kind.value == kind
    assert model.subject.kind == subject_kind and model.subject.id.startswith(id_prefix)
    assert len(model.subject.sha256) == 64


def test_the_builder_refuses_a_subject_without_an_id() -> None:
    from amw_core.errors import InputInvalidError
    from tests.orchestrator.builder_world import data_of, with_data

    w = World()
    data = {k: v for k, v in data_of(w.up["s10_render"]).items() if k != "render_id"}
    w.up["s10_render"] = with_data(w.up["s10_render"], data)
    with pytest.raises(InputInvalidError):
        BuilderTable().build(w.ctx("a_final"))


# --- the real ApprovalWorker through the default executor -----------------------------------
class _Reg:
    def __init__(self, worker: ApprovalWorker) -> None:
        self.worker = worker

    def worker_for(self, stage: object) -> ApprovalWorker:
        return self.worker

    def builder_for(self, stage: object) -> BuilderTable:
        return BuilderTable()


def _executor(desk: TestDesk) -> TaskExecutor:
    return TaskExecutor(_Reg(ApprovalWorker(desk, now_z)), schemas=PayloadSchemaRegistry())


def _prepare_and_run(ex: TaskExecutor, bc: BuildContext) -> Any:
    return ex.run(ex.prepare(bc, str(ATTEMPT.new())))


def test_the_real_approval_worker_suspends_then_succeeds_with_a_registered_payload() -> None:
    desk = TestDesk()
    ex = _executor(desk)
    bc = World().ctx("a_final")
    waiting = _prepare_and_run(ex, bc)
    assert waiting.status is OutputStatus.SUSPENDED and waiting.payload is not None
    assert waiting.payload.data is not None and waiting.payload.data["state"] == "PENDING"
    ApprovalOutput.model_validate(waiting.payload.data)  # the suspended payload has the shape too
    desk.decisions.add(bc.task_id)
    done = _prepare_and_run(ex, bc)
    assert done.status is OutputStatus.SUCCEEDED and done.error is None
    assert done.payload is not None and done.payload.data is not None
    out = ApprovalOutput.model_validate(done.payload.data)
    assert out.state == "APPROVED" and out.evidence_ids and out.parsed_target_stage_id is None
    assert out.subject_sha256 == desk.last_subject_sha256


@pytest.mark.parametrize("state", ["REJECTED", "CHANGES_REQUESTED"])
def test_other_owner_decisions_pass_the_executor(state: str) -> None:
    desk = TestDesk(state)
    ex = _executor(desk)
    bc = World().ctx("a_final")
    desk.decisions.add(bc.task_id)
    done = _prepare_and_run(ex, bc)
    assert done.status is OutputStatus.SUCCEEDED, done.error
    assert done.payload is not None and done.payload.data is not None
    assert done.payload.data["state"] == state


def test_a_desk_that_returns_the_old_minimal_payload_is_refused_fail_closed() -> None:
    class OldDesk(TestDesk):
        def decision(self, task_input: Any, ctx: Any) -> dict[str, object] | None:
            return {"state": "APPROVED", "approval_id": str(APPROVAL.new())}

    ex = _executor(OldDesk())
    done = _prepare_and_run(ex, World().ctx("a_final"))
    assert done.status is OutputStatus.FAILED and done.error is not None
    assert done.error.code == "PERMANENT.SCHEMA_INVALID"
