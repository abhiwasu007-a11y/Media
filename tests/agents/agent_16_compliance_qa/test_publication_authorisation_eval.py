# ruff: noqa: PT018
"""Dataset ``publication_authorisation`` (58 cases, 100 % threshold): every PA case through
``AuthorisationGuards.evaluate``; exact verdict, failed guards, action and human-wins total."""

import json
from typing import Any

import jsonschema
import pytest

from agent_16_compliance_qa.authorisation.facts import AuthRows, StepFacts
from agent_16_compliance_qa.authorisation.guards import AuthorisationGuards, GuardPolicy
from amw_core.enums import ApprovalChannel, ComplianceVerdict
from tests.agents.agent_16_compliance_qa.support import EVALS, case_ids, cases

PA = cases("publication_authorisation")
GUARDS = AuthorisationGuards(GuardPolicy(frozenset({ApprovalChannel.OWNER_CHAT_OPERATOR}), 20))


def _with_recorder(ev: dict[str, Any] | None, operator: bool) -> dict[str, Any] | None:
    return None if ev is None else ev | {"recorded_by_operator": operator}


def fixture_rows(fx: dict[str, Any]) -> AuthRows:
    """The dataset fixture (schema 1.0.0) as ``AuthRows``.

    The fixture predates the review-B1 fields, so the harness states them from the fixture's own
    facts (contract_need: add them to the fixture schema):

    * ``recorded_by_operator``: a step's ``recorded_by_kind == OPERATOR``; every other record of
      the fixture is operator-recorded (the fixture has no field for it);
    * ``nhr_items``: one item per ``unresolved_nhr`` plus one per resolution row, each resolution
      bound to its own item;
    * the resolving approval: the fixture's ``NHR_RESOLUTION`` approval when it has one, else a
      ``SENSITIVE_CLAIM`` approval whose single step is the resolution row's own record (state
      APPROVED, same channel and evidence: the row and its step are one record, CCR-102).
    """
    fx = json.loads(json.dumps(fx))
    for st in fx["steps"]:
        st["evidence"] = _with_recorder(st["evidence"], st["recorded_by_kind"] == "OPERATOR")
    for a in fx["other_approvals"]:
        for st in a["steps"]:
            st["evidence"] = _with_recorder(st["evidence"], st["recorded_by_kind"] == "OPERATOR")
    for c in fx["contributions"]:
        c["evidence"] = _with_recorder(c["evidence"], True)
    for h in fx["scores"]["human"]:
        h["evidence"] = _with_recorder(h["evidence"], True)
    gate = fx["gate"]
    items = [f"item-{i + 1}" for i in range(gate["unresolved_nhr"] + len(gate["nhr_resolutions"]))]
    gate["nhr_items"] = items
    relied = next((a for a in fx["other_approvals"] if a["relied_on_by"] == "NHR_RESOLUTION"), None)
    for i, r in enumerate(gate["nhr_resolutions"]):
        r["evidence"] = _with_recorder(r["evidence"], True)
        step = {
            "step_no": 1,
            "state": "APPROVED",
            "decided_by_kind": r["decided_by_kind"],
            "membership_active": True,
            "holds_required_role": True,
            "recorded_by_kind": "OPERATOR",
            "approval_channel": r["approval_channel"],
            "evidence": r["evidence"] and r["evidence"] | {"parsed_decision_matches": True},
        }
        r |= {
            "item_ref": items[gate["unresolved_nhr"] + i],
            "step_state": "APPROVED",
            "reuses_step_evidence": True,
            "resolving_approval": {
                "kind": relied["kind"] if relied else "SENSITIVE_CLAIM",
                "state": relied["state"] if relied else "APPROVED",
                "subject_matches_item": r["same_subject_hash"],
                "steps": relied["steps"] if relied else [step],
            },
        }
    return AuthRows.model_validate(fx)


def _fixture_schema() -> dict[str, Any]:
    text = (EVALS / "publication_authorisation/README.md").read_text(encoding="utf-8")
    start = text.index("```json") + len("```json")
    return dict(json.loads(text[start : text.index("```", start)]))


def test_dataset_has_58_cases_and_valid_fixtures() -> None:
    schema = _fixture_schema()
    assert len(PA) == 58
    for c in PA:
        jsonschema.validate(c["input"]["fixture"], schema)


@pytest.mark.unit
@pytest.mark.parametrize("case", PA, ids=case_ids(PA))
def test_pa_case(case: dict[str, Any]) -> None:
    decision = GUARDS.evaluate(fixture_rows(case["input"]["fixture"]))
    exp = case["expected"]
    assert decision.verdict.value == exp["verdict"]
    assert decision.failed_guards == exp["failed_guards"]
    assert decision.authorised_action == exp["authorised_action"]
    assert decision.human_wins_total == exp["human_wins_total"]
    assert decision.is_final is True
    assert [g.guard_id for g in decision.guards][-1] == "G14"
    assert decision.guards[-1].result == "SKIPPED"  # G14 is 3C


def test_compliance_blocked_stops_delivery_whatever_the_score() -> None:
    fx = next(c for c in PA if c["case_id"] == "PA-04")["input"]["fixture"]
    rows = fixture_rows(fx)
    assert rows.gate.overall is ComplianceVerdict.BLOCKED
    hi = rows.model_copy(update={"threshold": 0.0})
    d = GUARDS.evaluate(hi)
    assert d.verdict is ComplianceVerdict.BLOCKED and d.authorised_action is None
    assert {"G5", "G6"} <= set(d.failed_guards)


def test_approval_state_alone_never_counts() -> None:
    """PA-56 style: approvals.state APPROVED, steps undecided => G2 FAIL (CCR-102)."""
    fx = next(c for c in PA if c["case_id"] == "PA-01")["input"]["fixture"]
    rows = fixture_rows(fx)
    step = StepFacts.model_validate(
        rows.steps[0].model_dump()
        | {"state": "PENDING", "approval_channel": None, "evidence": None}
    )
    d = GUARDS.evaluate(rows.model_copy(update={"steps": (step,)}))
    assert d.failed_guards == ["G2"]
    assert GUARDS.evaluate(rows.model_copy(update={"steps": ()})).failed_guards == ["G2"]


def test_three_a_delivers_only() -> None:
    fx = next(c for c in PA if c["case_id"] == "PA-01")["input"]["fixture"]
    rows = fixture_rows(fx)
    for action in ("UPLOAD_PRIVATE", "PUBLISH"):
        d = GUARDS.evaluate(rows.model_copy(update={"requested_action": action}))
        assert "G0" in d.failed_guards and d.authorised_action is None
    yt = rows.model_copy(update={"destination": "YOUTUBE"})
    assert "G0" in GUARDS.evaluate(yt).failed_guards
