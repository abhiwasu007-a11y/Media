"""Enum columns are ``text`` + CHECK with the exact GLOSSARY values (04 section 1 rule 4)."""

import re
from typing import Any

import psycopg
import pytest

from amw_core.enums import GLOSSARY_ENUMS
from tests.docs_tables import glossary_enums

pytestmark = pytest.mark.contract
Conn = psycopg.Connection[tuple[Any, ...]]

COLUMNS = {
    ("jobs", "state"): "job_state",
    ("jobs", "outcome"): "job_outcome",
    ("tasks", "state"): "task_state",
    ("tasks", "wait_reason"): "wait_reason",
    ("tasks", "resource_class"): "resource_class",
    ("tasks", "error_class"): "failure_class",
    ("task_attempts", "result"): "attempt_result",
    ("task_queue", "status"): "queue_item_status",
    ("task_queue", "queue_name"): "queue_name",
    ("state_transitions", "entity_kind"): "entity_kind",
    ("state_transitions", "transition_id"): "transition_id",
    ("state_transitions", "actor_kind"): "actor_kind",
    ("idempotency_keys", "status"): "idempotency_status",
    ("organisations", "status"): "org_status",
    ("memberships", "role"): "role",
    ("channels", "status"): "channel_status",
    ("channels", "audience_kind"): "audience_kind",
    ("dead_letter", "recovery_status"): "dlq_recovery_status",
    ("circuit_breakers", "state"): "circuit_state",
    ("approvals", "kind"): "approval_kind",
    ("approvals", "state"): "approval_state",
    ("approval_steps", "state"): "approval_step_state",
    ("owner_instruction_evidence", "state"): "evidence_state",
    ("owner_instruction_evidence", "record_kind"): "evidence_record_kind",
    ("publications", "state"): "publish_state",
    ("renders", "status"): "render_status",
    ("assets", "kind"): "asset_kind",
    ("licences", "state"): "licence_state",
    ("quality_scores", "dimension"): "quality_dimension",
    ("compliance_verdicts", "verdict"): "compliance_verdict",
    ("claims", "claim_type"): "claim_type",
    ("claims", "time_reference_kind"): "time_reference_kind",
    ("claims", "status"): "claim_status",
    ("claims", "proposed_verdict"): "compliance_verdict",
    ("claims", "final_verdict"): "compliance_verdict",
}


def _check_values(admin: Conn, table: str, column: str) -> set[str]:
    rows = admin.execute(
        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c"
        " JOIN pg_class t ON t.oid = c.conrelid WHERE t.relname = %s AND c.contype = 'c'",
        (table,),
    ).fetchall()
    for (definition,) in rows:
        if re.match(rf"CHECK \(\({column} = ANY \(ARRAY\[", definition):
            return set(re.findall(r"'([^']+)'::text", definition))
    raise AssertionError(f"no enum CHECK on {table}.{column}")


@pytest.mark.parametrize(("table", "column"), sorted(COLUMNS))
def test_check_values_equal_the_glossary(admin: Conn, table: str, column: str) -> None:
    name = COLUMNS[(table, column)]
    assert _check_values(admin, table, column) == set(glossary_enums()[name])
    assert name in GLOSSARY_ENUMS or name == "evidence_record_kind"
