"""Seed rows for the lane L1b tables (04 section 5.13, 5.14)."""

from datetime import UTC, datetime
from typing import Any

import psycopg

from amw_core.ids import new_uuid7
from tests.pg_fixtures import Tenant
from tests.tenancy.seed import SHA, World, ins

Conn = psycopg.Connection[tuple[Any, ...]]


def seed(conn: Conn, tenant: Tenant, w: World) -> None:
    now = datetime.now(UTC)
    ins(
        conn,
        w,
        "audit_log",
        with_id=True,
        seq=1,
        occurred_at=now,
        actor_kind="SYSTEM",
        actor_ref="sys_seed",
        authority="seed",
        action="seed.row",
        target_kind="job",
        job_id=w["job"],
        details={},
        prev_hash=SHA,
        row_hash=SHA,
    )
    w.tables.add("audit_log_default")
    ins(conn, w, "audit_chain_heads", with_id=False, last_seq=1, last_hash=SHA)
    estimate = new_uuid7()
    ins(
        conn,
        w,
        "cost_ledger",
        id=estimate,
        job_id=w["job"],
        task_id=w["task0"],
        provider="llm_provider",
        operation="llm.completion",
        amount_micros=1,
        currency="USD",
        figure_kind="ESTIMATE",
        price_ref="seed",
        occurred_at=now,
    )
    ins(
        conn,
        w,
        "cost_ledger",
        job_id=w["job"],
        task_id=w["task0"],
        provider="llm_provider",
        operation="llm.completion",
        amount_micros=1,
        currency="USD",
        figure_kind="VERIFIED",
        estimate_entry_id=estimate,
        verification_ref="seed",
        occurred_at=now,
    )
    budget = new_uuid7()
    ins(
        conn,
        w,
        "budgets",
        "budget",
        id=budget,
        scope_kind="ORG",
        period="MONTH",
        limit_minor=1000,
        currency="USD",
        soft_limit_ratio=0.8,
        state="ACTIVE",
    )
    ins(
        conn,
        w,
        "budget_reservations",
        budget_id=budget,
        task_id=w["task0"],
        amount_micros=1,
        currency="USD",
        status="HELD",
    )
