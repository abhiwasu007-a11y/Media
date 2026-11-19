# ruff: noqa: PT018
"""PASS6-H review fixes: cost on an error output, fail-closed gate facts, no hidden slice defaults,
producer-schema validation (CCR-200, CCR-267)."""

from typing import Any

import pytest
from pydantic import ValidationError

from agent_05_scriptwriter.contracts import ScriptDocument
from agent_09_video_director.contracts import ScriptDocSlice
from agent_09_video_director.gates import script_gate
from agent_09_video_director.protocol import (
    SCRIPT_DOCUMENT_SCHEMA,
    GateFacts,
    ShotPlanTask,
)
from amw_core.contracts.payloads import PayloadSchemaRegistry
from amw_core.contracts.validation import validate_task_output
from amw_core.enums import OutputStatus
from amw_core.errors import AmwError, ConfigInvalidError
from tests.agents.agent_09_video_director.support import ResponderLlm, cfg, make_step
from tests.agents.agent_09_video_director.test_entry_point import (
    Clock,
    Ports,
    World,
    agent05_document,
    build,
    worker,
)

pytestmark = pytest.mark.contract


# ------------------------------------------------------------ (b) cost on the error output
def test_error_output_reports_the_paid_calls_made_before_the_failure() -> None:
    """Every answer is unparseable: the repair calls are paid, then the fallback share cap fails
    the plan. The error output must carry the real cost, not 0 (USD 5 per-video cap)."""
    w = World()
    task, ctx = build(w)
    step, _, rec = make_step(
        llm=ResponderLlm(lambda r: "not json"), config=cfg(fallback_max_share_permille=0)
    )
    out = ShotPlanTask(step, w.blobs, Ports(), Clock(), worst_case_call_micros=1000).run(
        task_input=task, ctx=ctx
    )
    assert out.status is OutputStatus.FAILED and out.error is not None
    assert rec.rows, "the scenario must make paid calls"
    usage = out.resource_usage
    assert usage.llm_calls == len(rec.rows) == len(usage.cost_entry_ids) > 0
    assert usage.provider_calls == usage.llm_calls
    assert usage.cost_estimate_micros == sum(m for _, m in rec.rows)
    assert out.next_action is not None and "cost unknown" not in out.next_action.reason
    validate_task_output(out.to_doc(), version="1.0.0")


def test_failure_before_any_paid_call_reports_zero_cost() -> None:
    w = World()
    task, ctx = build(w)
    data = {**(task.payload.data or {}), "iteration": -1}
    bad = task.model_copy(update={"payload": task.payload.model_copy(update={"data": data})})
    out = worker(w).run(task_input=bad, ctx=ctx)
    assert out.resource_usage.cost_estimate_micros == 0 and out.resource_usage.llm_calls == 0
    assert out.resource_usage.cost_entry_ids == ()


def test_call_with_unrecorded_cost_is_reported_unknown_upper_bound_not_zero() -> None:
    """The provider call raised after it was sent: it may have been charged, so the cost is not
    0; it is the worst case of the call, and the output says it is unknown."""

    def boom(_: Any) -> str:
        raise ConfigInvalidError("provider failed after the request was sent")

    w = World()
    task, ctx = build(w)
    step, _, _ = make_step(llm=ResponderLlm(boom))
    out = ShotPlanTask(step, w.blobs, Ports(), Clock(), worst_case_call_micros=1000).run(
        task_input=task, ctx=ctx
    )
    assert out.status is OutputStatus.FAILED
    assert out.resource_usage.llm_calls == 1
    assert out.resource_usage.cost_estimate_micros == 1000  # worst case of the unrecorded call
    assert out.resource_usage.cost_entry_ids == ()
    assert out.next_action is not None and "cost unknown" in out.next_action.reason
    validate_task_output(out.to_doc(), version="1.0.0")


# ------------------------------------------------------------ fail-closed gate facts
def test_bare_gate_facts_block_the_plan() -> None:
    w = World()
    task, ctx = build(w)

    class Bare(Ports):
        def gate_facts(self, tenant: Any, **_: Any) -> GateFacts:
            return GateFacts()

    step, llm, _ = make_step()
    out = ShotPlanTask(step, w.blobs, Bare(), Clock(), worst_case_call_micros=1000).run(
        task_input=task, ctx=ctx
    )
    assert out.status is OutputStatus.REJECTED and llm.requests == []
    assert out.error is not None and out.error.details.violations
    keywords = [v.keyword for v in out.error.details.violations]
    assert "CLAIM_BLOCKED" in keywords or "SCRIPT_STATUS_UNKNOWN" in keywords
    assert "SCRIPT_STATUS_UNKNOWN" in keywords  # the unknown status alone is enough


def test_gate_facts_defaults_are_fail_closed() -> None:
    g = GateFacts()
    assert g.claim_blocked is True and g.script_status == "UNKNOWN" and g.approval_approved is False


@pytest.mark.parametrize("status", ["ACTIVE", "UNKNOWN", "", "approved"])
def test_script_gate_refuses_a_status_outside_the_glossary(status: str) -> None:
    with pytest.raises(AmwError) as ei:
        script_gate(
            script_sha256="a" * 64, ref_sha256="a" * 64, verified_script_sha256="a" * 64,
            stage_verdict="ALLOWED", approval_approved=False, claim_blocked=False,
            script_status=status,
        )  # fmt: skip
    assert "SCRIPT_STATUS_UNKNOWN" in str(ei.value.details)


@pytest.mark.parametrize("status", ["DRAFT", "IN_REVIEW", "APPROVED"])
def test_script_gate_passes_the_current_glossary_statuses(status: str) -> None:
    script_gate(
        script_sha256="a" * 64, ref_sha256="a" * 64, verified_script_sha256="a" * 64,
        stage_verdict="ALLOWED", approval_approved=False, claim_blocked=False,
        script_status=status,
    )  # fmt: skip


# ------------------------------------------------------------ no hidden slice defaults
@pytest.mark.parametrize(
    "where",
    [
        ("scenes", 0, "beat"),
        ("scenes", 0, "explanatory"),
        ("scenes", 0, "deliberate_pause_ms"),
        ("scenes", 0, "visual_intent"),
        ("scenes", 0, "on_screen_text"),
        ("sections", 0, "section_kind"),
        ("sections", 0, "heading_local"),
        ("segments", 0, "text"),
        ("segments", 0, "section_id"),
        ("sections",),
        ("chart_requests",),
        ("disclaimer_slots",),
    ],
)
def test_a_missing_required_field_of_the_agent05_document_is_an_error(
    where: tuple[Any, ...],
) -> None:
    doc = agent05_document()
    ScriptDocSlice.model_validate(doc)  # the intact document is read
    node: Any = doc
    for key in where[:-1]:
        node = node[key]
    del node[where[-1]]
    with pytest.raises(ValidationError):
        ScriptDocSlice.model_validate(doc)


def test_entry_point_refuses_a_malformed_script_document_with_a_typed_code() -> None:
    w = World()
    doc = agent05_document()
    del doc["scenes"][0]["beat"]
    task, ctx = build(w, script_override=doc)
    out = worker(w).run(task_input=task, ctx=ctx)
    assert out.status is OutputStatus.REJECTED and out.error is not None
    assert [v.keyword for v in (out.error.details.violations or ())][:1] == [
        "SCRIPT_DOCUMENT_INVALID"
    ]


def test_unknown_fields_of_the_agent05_document_are_still_ignored() -> None:
    doc = agent05_document()
    doc["future_field"] = {"x": 1}
    doc["scenes"][0]["future_scene_field"] = 1
    ScriptDocSlice.model_validate(doc)


# ------------------------------------------------------------ producer schema (CCR-200)
def _registry_with_agent05() -> PayloadSchemaRegistry:
    reg = PayloadSchemaRegistry()
    reg.register(SCRIPT_DOCUMENT_SCHEMA, "1.0.0", ScriptDocument)
    return reg


def test_real_agent05_document_passes_the_registered_producer_schema() -> None:
    w = World()
    task, ctx = build(w)
    step, _, _ = make_step()
    out = ShotPlanTask(
        step, w.blobs, Ports(), Clock(), worst_case_call_micros=1000,
        schemas=_registry_with_agent05(),
    ).run(task_input=task, ctx=ctx)  # fmt: skip
    assert out.status is OutputStatus.SUCCEEDED, out.error


def test_document_failing_the_registered_producer_schema_is_refused() -> None:
    w = World()
    doc = agent05_document()
    doc["promise"] = {"not": "a promise"}  # a field Agent 09 never reads
    task, ctx = build(w, script_override=doc)
    step, llm, _ = make_step()
    out = ShotPlanTask(
        step, w.blobs, Ports(), Clock(), worst_case_call_micros=1000,
        schemas=_registry_with_agent05(),
    ).run(task_input=task, ctx=ctx)  # fmt: skip
    assert out.status is OutputStatus.REJECTED and llm.requests == []
    assert out.error is not None
    assert [v.keyword for v in (out.error.details.violations or ())][:1] == [
        "SCRIPT_SCHEMA_INVALID"
    ]


def test_without_a_registered_producer_schema_only_the_slice_model_applies() -> None:
    w = World()
    doc = agent05_document()
    doc["promise"] = {"not": "a promise"}
    task, ctx = build(w, script_override=doc)
    step, _, _ = make_step()
    out = ShotPlanTask(
        step, w.blobs, Ports(), Clock(), worst_case_call_micros=1000,
        schemas=PayloadSchemaRegistry(),
    ).run(task_input=task, ctx=ctx)  # fmt: skip
    assert out.status is OutputStatus.SUCCEEDED, out.error


def test_non_object_script_document_is_invalid() -> None:
    w = World()
    task, ctx = build(w, script_override=[1, 2])
    out = worker(w).run(task_input=task, ctx=ctx)
    assert out.status is OutputStatus.REJECTED and out.error is not None
    assert [v.keyword for v in (out.error.details.violations or ())] == ["SCRIPT_DOCUMENT_INVALID"]
