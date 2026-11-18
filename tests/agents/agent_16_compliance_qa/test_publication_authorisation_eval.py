"""Dataset ``publication_authorisation`` (58 cases, 100 % threshold): every PA case through
``AuthorisationGuards.evaluate``; exact verdict, failed guards, action and human-wins total."""

from typing import Any

import jsonschema
import pytest

from agent_16_compliance_qa.authorisation.facts import AuthRows, StepFacts
from agent_16_compliance_qa.authorisation.guards import AuthorisationGuards, GuardPolicy
from amw_core.enums import ApprovalChannel, ComplianceVerdict
from tests.agents.agent_16_compliance_qa.support import EVALS, case_ids, cases

PA = cases("publication_authorisation")
GUARDS = AuthorisationGuards(GuardPolicy(frozenset({ApprovalChannel.OWNER_CHAT_OPERATOR}), 20))


def _fixture_schema() -> dict[str, Any]:
    import json

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
    decision = GUARDS.evaluate(AuthRows.model_validate(case["input"]["fixture"]))
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
    rows = AuthRows.model_validate(fx)
    assert rows.gate.overall is ComplianceVerdict.BLOCKED
    hi = rows.model_copy(update={"threshold": 0.0})
    d = GUARDS.evaluate(hi)
    assert d.verdict is ComplianceVerdict.BLOCKED and d.authorised_action is None
    assert {"G5", "G6"} <= set(d.failed_guards)


def test_approval_state_alone_never_counts() -> None:
    """PA-56 style: approvals.state APPROVED, steps undecided => G2 FAIL (CCR-102)."""
    fx = next(c for c in PA if c["case_id"] == "PA-01")["input"]["fixture"]
    rows = AuthRows.model_validate(fx)
    step = StepFacts.model_validate(
        rows.steps[0].model_dump() | {"state": "PENDING", "approval_channel": None, "evidence": None}
    )
    d = GUARDS.evaluate(rows.model_copy(update={"steps": (step,)}))
    assert d.failed_guards == ["G2"]
    assert GUARDS.evaluate(rows.model_copy(update={"steps": ()})).failed_guards == ["G2"]


def test_three_a_delivers_only() -> None:
    fx = next(c for c in PA if c["case_id"] == "PA-01")["input"]["fixture"]
    rows = AuthRows.model_validate(fx)
    for action in ("UPLOAD_PRIVATE", "PUBLISH"):
        d = GUARDS.evaluate(rows.model_copy(update={"requested_action": action}))
        assert "G0" in d.failed_guards and d.authorised_action is None
    yt = rows.model_copy(update={"destination": "YOUTUBE"})
    assert "G0" in GUARDS.evaluate(yt).failed_guards
