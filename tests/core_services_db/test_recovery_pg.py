"""PostgreSQL breaker function (parity with the pure state machine), dead-letter store and the
catalogue checks of 04 section 3.7.6 for the lane L1b tables."""

import time
from dataclasses import replace
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from amw_core.config import BreakerSettings
from amw_core.enums import CircuitState, DlqRecoveryStatus
from amw_core.errors import CircuitOpenError, PermissionDeniedError
from amw_core.ids import ActorRef
from amw_core.interfaces.system_functions import BreakerKey
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.retries import dlq, record
from amw_core.retries.breaker import new_row
from amw_core.retries.pg import PgBreakerFunctions, PgDeadLetterStore
from amw_core.tenancy import PgTenancy, dsn_connection_factory
from tests.core_services.support import T0, settings
from tests.core_services_db.conftest import Work, make_user, run_sql
from tests.pg_fixtures import Tenant

pytestmark = pytest.mark.integration
ADAPTER = ActorRef("agent_05")
NET = "TEMPORARY.NETWORK"
MY_TABLES = (
    "audit_log",
    "audit_log_default",
    "audit_chain_heads",
    "cost_ledger",
    "budgets",
    "budget_reservations",
    "dead_letter",
    "circuit_breakers",
)


def _functions(pg_dsn: str, open_ms: int = 300) -> PgBreakerFunctions:
    cfg = settings().model_copy(
        update={
            "breaker_default": BreakerSettings(
                open_ms=open_ms, open_ms_max=open_ms * 4, half_open_probe_timeout_ms=5_000
            )
        }
    )
    return PgBreakerFunctions(dsn_connection_factory(pg_dsn, role="amw_app"), cfg)


@pytest.mark.failure_injection
def test_breaker_function_matches_the_pure_state_machine(
    pg_dsn: str, tenancy: PgTenancy, tenant_a: Tenant
) -> None:
    fns = _functions(pg_dsn)
    cfg = BreakerSettings(open_ms=300, open_ms_max=1200)
    key = BreakerKey("llm_provider_parity", "llm.completion", "platform")
    pure = new_row(key, T0)
    outcomes = [
        (True, None),
        (False, NET),
        (False, "PERMANENT.INPUT_INVALID"),
        (False, NET),
        (False, NET),
        (False, NET),
        (False, NET),
    ]
    for ok, code in outcomes:
        state = fns.breaker_record(ADAPTER, key, ok, code)
        pure = record(pure, ok, code, T0, cfg)
        assert state.state is pure.state, (ok, code)
    assert state.state is CircuitState.OPEN
    assert state.open_until is not None
    with tenancy.transaction(TenantContext(tenant_a.org_id, ADAPTER)) as tx:
        row = fns.read_diagnostics(tx, key)  # tenants read the platform row
        assert row is not None
        assert row.open_count == 1
        assert row.last_error_code == NET
        assert row.opened_at is not None
        with pytest.raises(CircuitOpenError):
            fns.require_admission(ADAPTER, key)
    time.sleep(0.35)  # past open_until: the next outcome is the first probe's
    assert fns.breaker_record(ADAPTER, key, True, None).state is CircuitState.HALF_OPEN
    assert fns.breaker_record(ADAPTER, key, True, None).state is CircuitState.CLOSED
    for _ in range(5):
        fns.breaker_record(ADAPTER, key, False, NET)
    time.sleep(0.35)
    reopened = fns.breaker_record(ADAPTER, key, False, "TEMPORARY.UPSTREAM_5XX")
    assert reopened.state is CircuitState.OPEN
    with tenancy.transaction(TenantContext(tenant_a.org_id, ADAPTER)) as tx:
        again = fns.read_diagnostics(tx, key)
        assert again is not None
        assert again.open_count == 2
        assert fns.read_diagnostics(tx, BreakerKey("none", "x", "platform")) is None


@pytest.mark.security
def test_breakers_are_written_only_through_the_function(
    pg_dsn: str, tenancy: PgTenancy, tenant_a: Tenant
) -> None:
    key = BreakerKey("llm_provider_guard", "llm.completion", "platform")
    _functions(pg_dsn).breaker_record(ADAPTER, key, True, None)
    for stmt in (
        "UPDATE circuit_breakers SET state = 'CLOSED'",
        "DELETE FROM circuit_breakers",
        "INSERT INTO circuit_breakers (id, provider, operation_class, credential_scope, state,"
        " window_started_at, window_calls, window_failures, consecutive_failures, open_count,"
        " half_open_in_flight) VALUES (gen_random_uuid(), 'p', 'o', 'platform', 'OPEN', now(),"
        " 0, 0, 0, 0, 0)",
    ):
        with (
            pytest.raises(PermissionDeniedError),
            tenancy.transaction(TenantContext(tenant_a.org_id, ADAPTER)) as tx,
        ):
            run_sql(tx, stmt)


def test_breaker_function_rejects_a_bad_actor_reference(pg_dsn: str) -> None:
    with pytest.raises(ValueError, match="actor"):
        _functions(pg_dsn).breaker_record(
            ActorRef("bob"), BreakerKey("p", "o", "platform"), True, None
        )


def _dead(work: Work) -> dlq.DeadLetter:
    return dlq.build_dead_letter(
        task_id=work.task_id,
        job_id=work.job_id,
        error={"code": "INFRASTRUCTURE.STORAGE_UNAVAILABLE", "message": "injected"},
        reason="retries exhausted",
        payload_ref="amw-blob://org/jobs/j/tasks/t/attempts/a/input.json",
        payload_sha256="cd" * 32,
        retry_history=[
            dlq.AttemptHistoryItem(
                1, T0, T0 + timedelta(seconds=3), None, "INFRASTRUCTURE.STORAGE_UNAVAILABLE"
            )
        ],
        last_attempt_id=work.attempt_id,
    )


@pytest.mark.failure_injection
def test_dead_letter_workflow_on_postgres(
    admin: Any, tenancy: PgTenancy, tenant_a: Tenant, work_a: Work
) -> None:
    store = PgDeadLetterStore()
    owner = make_user(admin)
    perms = frozenset({"dlq.triage", "dlq.replay"})
    cfg = settings()
    ctx = TenantContext(tenant_a.org_id, ActorRef("sys_dlq_handler"))
    with tenancy.transaction(ctx) as tx:
        dlq_id = store.insert(tx, _dead(work_a))
        loaded = store.get(tx, dlq_id)
        assert loaded.retry_history == _dead(work_a).retry_history
        assert loaded.idempotency_scope == "task.agent_05.script_draft"
        item = dlq.triage(loaded, owner, "storage was down", perms, T0)
        item = dlq.approve_replay(dlq.request_replay(item, owner, perms, T0), owner, perms, cfg, T0)
        store.save(tx, dlq_id, item)
        item = dlq.mark_replayed(store.get(tx, dlq_id), cfg, T0)
        store.save(tx, dlq_id, item)
        item = dlq.mark_resolved(store.get(tx, dlq_id), T0)
        store.save(tx, dlq_id, item)
        final = store.get(tx, dlq_id)
        assert final.recovery_status is DlqRecoveryStatus.RESOLVED
        assert final.replay_count == 1
        effect = store.with_effect_scope(final, "delivery.file", final.idempotency_key)  # type: ignore[arg-type]
        assert effect.idempotency_scope == "delivery.file"


@pytest.mark.security
def test_dead_letter_content_is_immutable_and_never_deleted(
    tenancy: PgTenancy, tenant_a: Tenant, work_a: Work
) -> None:
    ctx = TenantContext(tenant_a.org_id, ActorRef("sys_dlq_handler"))
    with tenancy.transaction(ctx) as tx:
        dlq_id = PgDeadLetterStore().insert(tx, _dead(work_a))
    for stmt in (
        "UPDATE dead_letter SET reason = 'rewritten'",
        "UPDATE dead_letter SET recovery_status = 'REPLAY_APPROVED'",  # CHECK: note required
        "DELETE FROM dead_letter",
    ):
        with (
            pytest.raises((PermissionDeniedError, psycopg.errors.CheckViolation)),
            tenancy.transaction(ctx) as tx,
        ):
            run_sql(tx, stmt)
    with tenancy.transaction(ctx) as tx:
        assert PgDeadLetterStore().get(tx, dlq_id).reason == "retries exhausted"
    with pytest.raises(Exception, match="not found"), tenancy.transaction(ctx) as tx:
        PgDeadLetterStore().get(tx, replace(_dead(work_a)).task_id.replace("tsk", "dlq"))  # type: ignore[arg-type]


@pytest.mark.tenancy
def test_lane_tables_have_rls_enabled_and_forced(admin: Any) -> None:
    """04 section 3.7.6 for the tables of migration 0050."""
    rows = admin.execute(
        "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = ANY(%s)",
        (list(MY_TABLES),),
    ).fetchall()
    assert {r[0] for r in rows} == set(MY_TABLES)
    assert all(r[1] and r[2] for r in rows), rows


@pytest.mark.tenancy
def test_unset_context_sees_no_rows(
    pg_dsn: str, tenancy: PgTenancy, tenant_a: Tenant, work_a: Work
) -> None:
    with tenancy.transaction(TenantContext(tenant_a.org_id, ActorRef("sys_dlq_handler"))) as tx:
        PgDeadLetterStore().insert(tx, _dead(work_a))
    with psycopg.connect(pg_dsn) as conn:
        conn.execute("SET ROLE amw_app")
        for table in (
            "dead_letter",
            "budgets",
            "budget_reservations",
            "cost_ledger",
            "audit_chain_heads",
        ):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)  # noqa: S608
        conn.execute("RESET ROLE")
        conn.execute("SET ROLE amw_readonly")
        assert conn.execute("SELECT count(*) FROM audit_log").fetchone() == (0,)
