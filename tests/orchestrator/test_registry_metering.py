# ruff: noqa: PT018
"""amw_orchestrator: registry records (24 section 7.1a / 7.2a), materialisation, deterministic
order, metering wrappers (no unattributed call, paid-call refusal before the adapter)."""

from typing import Any

import pytest

from amw_adapters.llm import LlmMessage, LlmRequest
from amw_adapters.llm.fake import FakeLlmAdapter
from amw_core.contracts.production_type import ReviseOnFail
from amw_core.enums import ProductionTypeKey
from amw_core.errors import ConfigInvalidError
from amw_orchestrator.metering import Meter, MeteredLlm, MeteredTask, metered_task
from amw_orchestrator.registry import job_graph, record, topological_order
from amw_runtime.calendar import MarketCalendar

pytestmark = pytest.mark.unit
LONG = ProductionTypeKey.CHANNEL_LONG_FORM


def test_long_form_v2_graph_matches_24_section_7_1a() -> None:
    pt = record(LONG)
    assert pt.version == 2 and pt.limits.max_revision_loops == 3
    assert pt.destinations[0].value == "FILE_DELIVERY"
    graph = job_graph(LONG)
    ids = [s.stage_id for s in graph]
    assert "a_script" not in ids and "s12_meta" not in ids  # optional, disabled by default
    assert topological_order(graph)[0] == "s04_research"
    assert topological_order(graph)[-1] == "s13_deliver"
    qc = pt.stage("s10_qc")
    assert qc.gate is not None and isinstance(qc.gate.on_fail, ReviseOnFail)
    assert qc.gate.on_fail.target_stage_id == "s10_render"
    assert pt.stage("s16_auth").gate is not None


def test_enabling_the_script_approval_keeps_it_in_the_graph() -> None:
    graph = job_graph(LONG, frozenset({"a_script"}))
    voice = next(s for s in graph if s.stage_id == "s07_voice")
    assert "a_script" in voice.depends_on


def test_shorts_v2_is_a_child_with_its_own_script_stage() -> None:
    pt = record(ProductionTypeKey.SHORTS)
    assert pt.parent_input.value == "PARENT_JOB" and pt.qc_profile == "qc.shorts"
    assert topological_order(job_graph(ProductionTypeKey.SHORTS))[0] == "s05_shorts"


def test_order_is_deterministic() -> None:
    assert topological_order(job_graph(LONG)) == topological_order(job_graph(LONG))


class _Meter:
    def __init__(self, allow: bool) -> None:
        self.allow, self.after = allow, 0

    def before_call(self, task: MeteredTask, provider: str, estimate_micros: int) -> None:
        if not self.allow:
            raise ConfigInvalidError("refused")

    def after_call(self, task: MeteredTask, usage: Any) -> None:
        self.after += 1


def _req() -> LlmRequest:
    return LlmRequest(
        model="m", system="s", messages=(LlmMessage(role="user", content="x"),), max_output_tokens=5
    )


TASK = MeteredTask("org_x", "job_x", "tsk_x", "att_x", "s05_script", "agent_05", None)
KEY = "idk_" + "a" * 64


def test_metering_refuses_calls_outside_a_task_and_before_the_adapter() -> None:
    meter: Meter = _Meter(allow=True)
    llm = MeteredLlm(FakeLlmAdapter(), meter, 10)
    with pytest.raises(ConfigInvalidError):
        llm.complete(_req(), idempotency_key=KEY)
    with metered_task(TASK):
        llm.complete(_req(), idempotency_key=KEY)
    assert meter.after == 1  # type: ignore[attr-defined]
    refusing = _Meter(allow=False)
    with metered_task(TASK), pytest.raises(ConfigInvalidError):
        MeteredLlm(FakeLlmAdapter(), refusing, 10).complete(_req(), idempotency_key=KEY)
    assert refusing.after == 0


def test_runtime_calendar_refuses_the_regular_session() -> None:
    from datetime import UTC, datetime

    cal = MarketCalendar()
    assert not cal.render_allowed(datetime(2026, 11, 19, 6, 0, tzinfo=UTC))  # Thu 11:30 IST
    assert cal.render_allowed(datetime(2026, 11, 19, 20, 0, tzinfo=UTC))
    assert cal.render_allowed(datetime(2026, 11, 21, 6, 0, tzinfo=UTC))  # Saturday
