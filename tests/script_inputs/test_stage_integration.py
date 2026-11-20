"""The real resolver inside ``ScriptDraftStage``: a first draft of a non-finance (philosophy)
channel runs end to end on the scripted fake model; no network, no paid call."""

from pathlib import Path

import pytest

from agent_05_scriptwriter import ScriptDraftStage, ScriptDraftStep, ScriptRepository
from amw_core.enums import OutputStatus
from tests.agents.agent_05_scriptwriter import support as sp
from tests.agents.agent_05_scriptwriter.test_entry_point import Clock, Rows, exec_ctx
from tests.script_inputs.world import World

pytestmark = pytest.mark.integration


def test_stage_runs_with_the_real_resolver(tmp_path: Path) -> None:
    w = World(tmp_path)
    st = sp.MemoryState()
    ports = sp.make_ports(st)
    rows = Rows()
    ports.scripts = ScriptRepository(w.storage, rows)
    llm = sp.ScriptedLlm(["VALID_PLAN", "VALID_SECTIONS"], 2, None)
    step = ScriptDraftStep(llm, ports, sp.make_settings(), sp.prompts(), sp.scanners_for)
    stage = ScriptDraftStage(step, w.resolver(), w.storage, Clock())
    ti = w.task()
    out = stage.run(ti, exec_ctx(ti))
    assert out.status is OutputStatus.SUCCEEDED, out.error
    assert len(llm.requests) == 3
    assert set(w.library.reads) == {"works/pd.txt"}
