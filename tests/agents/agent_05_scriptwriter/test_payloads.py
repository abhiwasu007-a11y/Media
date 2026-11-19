# ruff: noqa: PT018
"""Agent 05 payload registration: the registered models accept what the stages really emit."""

from pathlib import Path

import pytest

from agent_05_scriptwriter.contracts import (
    ScriptDraftInput,
    ScriptDraftResult,
    ShortsAdaptationInput,
    ShortsAdaptationResult,
)
from amw_core.enums import OutputStatus
from tests.agents.agent_05_scriptwriter import support as sp
from tests.agents.agent_05_scriptwriter.test_entry_point import build_world, exec_ctx, task_input
from tests.agents.agent_05_scriptwriter.test_shorts import parent_script, shorts_input
from tests.agents.payload_support import round_trip

pytestmark = pytest.mark.contract


def test_script_draft_input_and_output_round_trip(tmp_path: Path) -> None:
    w = build_world(tmp_path)
    ti = task_input()
    assert isinstance(round_trip(ti.payload), ScriptDraftInput)
    out = w.draft.run(ti, exec_ctx(ti))
    assert out.status is OutputStatus.SUCCEEDED and out.payload is not None
    assert isinstance(round_trip(out.payload), ScriptDraftResult)


def test_shorts_adaptation_input_and_output_round_trip(tmp_path: Path) -> None:
    doc, sha, cites, _ = parent_script()
    doc = doc.model_copy(update={"channel_id": sp.make_ctx().channel_id})
    w = build_world(
        tmp_path,
        ["VALID_CUT"],
        citations=cites,
        parent_script=doc,
        parent_script_sha256=sha,
        parent_claims_cleared=True,
    )
    data = shorts_input(doc, sha).model_dump(mode="json")
    ti = task_input(data, schema="agent_05.shorts_adaptation.input")
    assert isinstance(round_trip(ti.payload), ShortsAdaptationInput)
    out = w.shorts.run(ti, exec_ctx(ti, "s05_shorts"))
    assert out.status is OutputStatus.SUCCEEDED and out.payload is not None
    assert isinstance(round_trip(out.payload), ShortsAdaptationResult)
