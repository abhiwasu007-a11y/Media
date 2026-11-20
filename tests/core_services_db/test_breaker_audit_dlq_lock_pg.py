"""Ticket P4-06 (PR #44 review m6, m8): breaker transitions are audited in the platform owner
org's chain in the same transaction as the transition (07 section 4.3), and a dead-letter save
refuses a stale base under the row lock (two replays cannot both pass ``max_replays_per_item``).
The RECONCILE lock renewal (m9) is in ``test_stores_pg.py`` / ``test_memory_fakes.py``."""

import threading
import time
import uuid
from typing import Any

import pytest

from amw_core.audit.pg import PgAuditLog
from amw_core.config import BreakerSettings
from amw_core.enums import CircuitState, DlqRecoveryStatus
from amw_core.errors import ConfigInvalidError, LockConflictError
from amw_core.ids import ActorRef
from amw_core.interfaces.system_functions import BreakerKey
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.retries import dlq
from amw_core.retries.pg import PgBreakerFunctions, PgDeadLetterStore
from amw_core.tenancy import PgTenancy, dsn_connection_factory
from tests.core_services.support import T0, settings
from tests.core_services_db.conftest import (
    Work,
    breaker_functions,
    ensure_platform_owner,
    make_user,
)
from tests.core_services_db.test_recovery_pg import _dead
from tests.pg_fixtures import Tenant

pytestmark = pytest.mark.integration
ADAPTER = ActorRef("agent_05")
NET = "TEMPORARY.NETWORK"


def _settings(open_ms: int = 100) -> Any:
    breaker = BreakerSettings(
        open_ms=open_ms,
        open_ms_max=open_ms * 4,
        consecutive_failures=3,
        half_open_max_probes=1,
        half_open_successes_to_close=1,
        half_open_probe_timeout_ms=5_000,
    )
    return settings().model_copy(update={"breaker_default": breaker})


def _key() -> BreakerKey:
    return BreakerKey(f"llm_audit_{uuid.uuid4().hex[:8]}", "llm.completion", "platform")


def _transitions(admin: Any, key: BreakerKey) -> list[tuple[str, str, str, str]]:
    rows = admin.execute(
        "SELECT action, details->>'from', details->>'to', org_id::text FROM audit_log"
        " WHERE target_kind = 'CIRCUIT_BREAKER' AND details->>'provider' = %s ORDER BY seq",
        (key.provider,),
    ).fetchall()
    return [tuple(r) for r in rows]


def test_every_transition_is_audited_in_the_platform_owner_chain(
    pg_dsn: str, admin: Any, readonly: PgTenancy
) -> None:
    owner = ensure_platform_owner(pg_dsn)
    fns = breaker_functions(pg_dsn, _settings())
    key = _key()
    assert fns.breaker_record(ADAPTER, key, True, None).state is CircuitState.CLOSED
    for _ in range(3):
        fns.breaker_record(ADAPTER, key, False, NET)
    assert fns.breaker_record(ADAPTER, key, False, NET).state is CircuitState.OPEN  # no change
    assert not fns.admit(ADAPTER, key).admitted  # refused while OPEN: no transition
    time.sleep(0.15)
    probe = fns.admit(ADAPTER, key)
    assert probe.probe
    closed = fns.breaker_record(ADAPTER, key, True, None, probe=True, probe_epoch=probe.epoch)
    assert closed.state is CircuitState.CLOSED
    org = str(uuid.UUID(owner.split("_", 1)[1]))
    assert _transitions(admin, key) == [
        ("breaker.open", "CLOSED", "OPEN", org),
        ("breaker.half_open", "OPEN", "HALF_OPEN", org),
        ("breaker.closed", "HALF_OPEN", "CLOSED", org),
    ]
    with readonly.transaction(TenantContext(owner, ActorRef("sys_auditor"))) as tx:
        assert PgAuditLog().verify_chain(tx).ok


def test_a_failed_audit_rolls_the_transition_back(
    pg_dsn: str, admin: Any, tenant_a: Tenant
) -> None:
    """``platform_owner_org`` set to an ordinary tenant: the audit is refused and the breaker
    stays CLOSED (the transition and its audit row commit together or not at all)."""
    wrong = PgBreakerFunctions(
        dsn_connection_factory(pg_dsn, role="amw_app"),
        _settings(),
        audit=PgAuditLog(),
        platform_owner_org=tenant_a.org_id,
    )
    key = _key()
    for _ in range(2):
        wrong.breaker_record(ADAPTER, key, False, NET)
    with pytest.raises(ConfigInvalidError, match="platform owner"):
        wrong.breaker_record(ADAPTER, key, False, NET)
    state = admin.execute(
        "SELECT state, consecutive_failures FROM circuit_breakers WHERE provider = %s",
        (key.provider,),
    ).fetchone()
    assert state == ("CLOSED", 2)
    assert _transitions(admin, key) == []


def test_tenant_credential_scopes_are_refused_until_3c(pg_dsn: str) -> None:
    fns = breaker_functions(pg_dsn, _settings())
    key = BreakerKey("llm_tenant_scope", "llm.completion", f"gcp_{uuid.uuid4()}")
    with pytest.raises(ConfigInvalidError, match="3C"):
        fns.breaker_record(ADAPTER, key, True, None)
    with pytest.raises(ConfigInvalidError, match="3C"):
        fns.admit(ADAPTER, key)


def test_parallel_failures_audit_the_opening_once(pg_dsn: str, admin: Any) -> None:
    fns = breaker_functions(pg_dsn, _settings(open_ms=60_000))
    key = _key()
    errors: list[BaseException] = []

    def fail() -> None:
        try:
            fns.breaker_record(ADAPTER, key, False, NET)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=fail) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert _transitions(admin, key) == [
        ("breaker.open", "CLOSED", "OPEN", _transitions(admin, key)[0][3])
    ]


# --- dead-letter save under the row lock --------------------------------------------------------
def _approved(tenancy: PgTenancy, tenant: Tenant, work: Work, admin: Any) -> tuple[Any, Any]:
    store = PgDeadLetterStore()
    owner = make_user(admin)
    perms = frozenset({"dlq.triage", "dlq.replay"})
    ctx = TenantContext(tenant.org_id, ActorRef("sys_dlq_handler"))
    with tenancy.transaction(ctx) as tx:
        dlq_id = store.insert(tx, _dead(work))
        base = store.get(tx, dlq_id, for_update=True)
        item = dlq.triage(base, owner, "storage was down", perms, T0)
        item = dlq.approve_replay(
            dlq.request_replay(item, owner, perms, T0), owner, perms, settings(), T0
        )
        store.save(tx, dlq_id, item, base=base)
    return dlq_id, ctx


@pytest.mark.failure_injection
def test_save_refuses_a_stale_base(
    admin: Any, tenancy: PgTenancy, tenant_a: Tenant, work_a: Work
) -> None:
    dlq_id, ctx = _approved(tenancy, tenant_a, work_a, admin)
    store = PgDeadLetterStore()
    with tenancy.transaction(ctx) as tx:
        stale = store.get(tx, dlq_id)
    with tenancy.transaction(ctx) as tx:
        fresh = store.get(tx, dlq_id, for_update=True)
        store.save(tx, dlq_id, dlq.mark_replayed(fresh, settings(), T0), base=fresh)
    with pytest.raises(LockConflictError), tenancy.transaction(ctx) as tx:
        store.save(tx, dlq_id, dlq.mark_replayed(stale, settings(), T0), base=stale)
    with tenancy.transaction(ctx) as tx:
        final = store.get(tx, dlq_id)
    assert final.replay_count == 1
    assert final.recovery_status is DlqRecoveryStatus.REPLAYED


@pytest.mark.failure_injection
@pytest.mark.parametrize("lock_on_read", [True, False])
def test_concurrent_replays_count_once(
    admin: Any, tenancy: PgTenancy, tenant_a: Tenant, work_a: Work, lock_on_read: bool
) -> None:
    """Ten workers race to record the replay of one approved item: the row lock serialises them
    and only the first step is valid from the state it reads (the others see REPLAYED). Without
    the read lock all ten compute from the same base; the save's own row lock and base check
    still let exactly one through."""
    dlq_id, ctx = _approved(tenancy, tenant_a, work_a, admin)
    store = PgDeadLetterStore()
    done: list[int] = []
    refused: list[BaseException] = []
    barrier = threading.Barrier(10, timeout=60)

    def replay() -> None:
        barrier.wait()
        try:
            with tenancy.transaction(ctx) as tx:
                base = store.get(tx, dlq_id, for_update=lock_on_read)
                step = dlq.mark_replayed(base, settings(), T0)
                if not lock_on_read:
                    barrier.wait()  # every worker has read the same base before any save
                store.save(tx, dlq_id, step, base=base)
                done.append(1)
        except Exception as exc:
            refused.append(exc)

    threads = [threading.Thread(target=replay) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with tenancy.transaction(ctx) as tx:
        final = store.get(tx, dlq_id)
    assert len(done) == 1
    assert len(refused) == 9
    if not lock_on_read:
        assert all(isinstance(e, LockConflictError) for e in refused), refused
    assert final.replay_count == 1
