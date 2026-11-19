# ruff: noqa: PT018
"""Held calls on the real PostgreSQL ledger: list and reconcile through the two command-line
entries (RLS as ``amw_app``, append-only ledger, tenant isolation)."""

from datetime import UTC, datetime

import pytest

from amw_adapters.real.holds import list_held, list_main, reconcile_main
from amw_core.cost.pg import PgCostLedger
from amw_core.enums import CostFigureKind, CostOperation
from amw_core.ids import ActorRef, make_idempotency_key
from amw_core.interfaces.cost_ledger import NewCostEntry
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.tenancy import PgTenancy
from tests.core_services_db.conftest import Work
from tests.pg_fixtures import Tenant

pytestmark = pytest.mark.integration
OP = ActorRef("sys_operator")
T0 = datetime(2026, 11, 19, 10, 0, tzinfo=UTC)


def _hold(work: Work, tenant: Tenant, micros: int, n: int) -> NewCostEntry:
    return NewCostEntry(
        provider="anthropic", operation=CostOperation.LLM_COMPLETION, amount_micros=micros,
        currency="USD", figure_kind=CostFigureKind.ESTIMATE, occurred_at=T0,
        job_id=work.job_id, task_id=work.task_id, attempt_id=work.attempt_id,
        model="claude-haiku-5-5", price_ref="PR-10",
        idempotency_key=make_idempotency_key(tenant.org_id, "llm.call", ["held", n]),
    )  # fmt: skip


def test_list_and_reconcile_a_held_call_on_postgres(
    tenancy: PgTenancy, tenant_a: Tenant, tenant_b: Tenant, work_a: Work
) -> None:
    led = PgCostLedger()
    ctx = TenantContext(tenant_a.org_id, OP)
    with tenancy.transaction(ctx) as tx:
        hold = led.record(tx, _hold(work_a, tenant_a, 1_500_000, 1))
        led.record(tx, _settled(work_a, tenant_a))
    held = list_held(led, tenancy, ctx, work_a.job_id)
    assert [h.entry_id for h in held] == [hold.id]  # the settled call (tokens) is not a hold
    out: list[str] = []
    services = (led, tenancy)
    base = ["--org-id", tenant_a.org_id]
    assert list_main([*base, "--job-id", work_a.job_id], services=services, out=out.append) == 0
    assert any(x.startswith(str(hold.id)) for x in out) and "1500000 micros held" in out[-1]
    args = [
        *base,
        "--entry-id",
        hold.id,
        "--actual-micros",
        "0",
        "--verification-ref",
        "console",
    ]
    out.clear()
    assert reconcile_main(args, services=services, out=out.append) == 0  # dry run writes nothing
    assert len(list_held(led, tenancy, ctx, work_a.job_id)) == 1
    assert reconcile_main([*args, "--apply"], services=services, out=out.append) == 0
    assert list_held(led, tenancy, ctx, work_a.job_id) == []
    with tenancy.transaction(ctx) as tx:
        totals = led.job_totals(tx, work_a.job_id)
    assert (totals.estimate_micros, totals.verified_micros, totals.effective_micros) == (
        1_502_000,
        0,
        2_000,
    )  # hold (1.5M) + settled call; the VERIFIED 0 supersedes the hold
    assert reconcile_main([*args, "--apply"], services=services, out=out.append) == 2  # again


def test_another_tenant_cannot_list_or_reconcile_a_hold(
    tenancy: PgTenancy, tenant_a: Tenant, tenant_b: Tenant, work_a: Work
) -> None:
    led = PgCostLedger()
    with tenancy.transaction(TenantContext(tenant_a.org_id, OP)) as tx:
        hold = led.record(tx, _hold(work_a, tenant_a, 900, 3))
    other = TenantContext(tenant_b.org_id, OP)
    assert list_held(led, tenancy, other, work_a.job_id) == []
    out: list[str] = []
    code = reconcile_main(
        ["--org-id", tenant_b.org_id, "--entry-id", hold.id, "--actual-micros", "0",
         "--verification-ref", "c", "--apply"],
        services=(led, tenancy), out=out.append,
    )  # fmt: skip
    assert code == 2 and "no such ledger row" in out[0]


def _settled(work: Work, tenant: Tenant) -> NewCostEntry:
    return NewCostEntry(
        provider="anthropic", operation=CostOperation.LLM_COMPLETION, amount_micros=2_000,
        currency="USD", figure_kind=CostFigureKind.ESTIMATE, occurred_at=T0,
        job_id=work.job_id, task_id=work.task_id, attempt_id=work.attempt_id,
        model="claude-haiku-5-5", price_ref="PR-10", tokens_in=10, tokens_out=5,
        idempotency_key=make_idempotency_key(tenant.org_id, "llm.call", ["settled", 1]),
    )  # fmt: skip
