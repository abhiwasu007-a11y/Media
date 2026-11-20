"""Why each port of a REAL run is still unwired (the PR explains every entry; this keeps the
explanation and the list from drifting apart): a new entry needs a reason."""

import pytest

from tests.orchestrator.run_job_world import EXPECTED_UNMET_PORTS

OWNER_VALUES = "owner decision: values or paths are not set (REQUIRES REVIEW), no sourced default"
OTHER_LANE = (
    "other lane: input resolver / brand kit / library chunk index (v4-inputs-brandkit-index)"
)
FREE_TTS = "owner decision: the free voice route is not chosen, no capabilities declared"
RULE_PACKS = "contract gap: no production source of rule-pack texts (CCR-278, CCR-290)"
NO_ADAPTER = "no PostgreSQL adapter yet: the table exists, the port was not in the PR 116 set"
NO_CONTRACT = "contract gap: no table, schema or port semantics to implement against (see CCRs)"

REASON_BY_PARAMETER = {
    "settings": OWNER_VALUES, "config": OWNER_VALUES, "cfg": OWNER_VALUES,
    "worst_case_call_micros": OWNER_VALUES, "scratch_root": OWNER_VALUES,
    "scanners_for": OWNER_VALUES, "lexicons": OWNER_VALUES, "admission": OWNER_VALUES,
    "tools": OWNER_VALUES, "backend": OWNER_VALUES,
    "library": OTHER_LANE, "knowledge": OTHER_LANE, "chunks": OTHER_LANE,
    "resolver": OTHER_LANE, "brand_kits": OTHER_LANE, "quotes": OTHER_LANE,
    "plan_input_ports": OTHER_LANE,
    "tts": FREE_TTS,
    "rule_packs": RULE_PACKS, "packs": RULE_PACKS, "pack_texts": RULE_PACKS,
    "prompts": RULE_PACKS,  # agent_04 only: its loader renders rule-pack text into the prompt
    "directory": NO_ADAPTER, "memory": NO_ADAPTER, "claims": NO_ADAPTER, "assets": NO_ADAPTER,
    "licences": NO_ADAPTER, "ledger": NO_ADAPTER, "approvals": NO_ADAPTER,
    "renders": NO_ADAPTER, "qc_results": NO_ADAPTER, "facts": NO_ADAPTER,
    "registry": NO_ADAPTER, "store": NO_ADAPTER, "source": NO_ADAPTER, "writer": NO_ADAPTER,
    "web": NO_CONTRACT, "control": NO_CONTRACT, "hook_history": NO_CONTRACT,
    "breaker": NO_CONTRACT, "recorder": NO_CONTRACT, "selftests": NO_CONTRACT,
    "evidence": NO_CONTRACT, "assembler": NO_CONTRACT, "extractor": NO_CONTRACT,
    "groups": NO_CONTRACT, "repo": NO_CONTRACT, "chart_ranges": NO_CONTRACT,
    "fingerprints": NO_CONTRACT,
    "budget": NO_CONTRACT, "checkpoints": NO_CONTRACT, "idempotency": NO_CONTRACT,
    "audit": NO_CONTRACT,  # agent_05 narrow ports (CCR-307)
}  # fmt: skip


def _split(entry: str) -> tuple[str, str]:
    task, _, name = entry.partition(":")
    return task, name


@pytest.mark.parametrize("entry", sorted(EXPECTED_UNMET_PORTS))
def test_every_remaining_port_has_exactly_one_reason(entry: str) -> None:
    _, name = _split(entry)
    assert name in REASON_BY_PARAMETER, entry


def test_the_reason_table_has_no_unused_parameter() -> None:
    used = {_split(e)[1] for e in EXPECTED_UNMET_PORTS}
    assert set(REASON_BY_PARAMETER) == used


def test_agent_08_ledger_is_the_licence_ledger_and_has_no_cost_ledger_meaning() -> None:
    assert "agent_08.asset_sourcing:ledger" in EXPECTED_UNMET_PORTS  # not the S4 cost ledger
