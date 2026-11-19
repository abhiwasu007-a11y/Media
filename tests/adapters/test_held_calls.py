# ruff: noqa: PT018
"""Owner runbook for unreconciled holds (PROVIDERS.md section 5): list, reconcile (library and
the two command-line entries), shared in-flight holds across the LLM and TTS guards, and the
job binding of a real preflight."""

from datetime import UTC, datetime

import httpx
import pytest

from amw_adapters.real.authorisation import verify_authorisation
from amw_adapters.real.guard import CapBook, CapOnlyCallGuard, PlannedCall, call_scope
from amw_adapters.real.holds import (
    held_calls,
    is_hold_row,
    list_held,
    list_main,
    reconcile_held,
    reconcile_main,
)
from amw_core.cost.ledger import effective_rows
from amw_core.enums import CostFigureKind
from amw_core.errors import BudgetExhaustedError, CallTimeoutError, InputInvalidError
from amw_core.ids import make_idempotency_key
from amw_orchestrator.executor import ChannelCategory
from amw_orchestrator.services import run_job_preflight
from amw_runtime.config import load_runtime_config
from tests.adapters.guards import GuardedWorld, MemoryTenancy, auth, cap_guard
from tests.adapters.mock_providers import Scripted
from tests.adapters.preflight_support import EVENING, ORG_ID, REAL_ENV, Lookup, limits
from tests.adapters.test_real_guard_and_controls import key, llm, llm_request
from tests.orchestrator.test_executor import _job

pytestmark = pytest.mark.failure_injection
TIMEOUT = Scripted(0, raise_exc=httpx.ReadTimeout("slow"))


def _held_world() -> tuple[GuardedWorld, object]:
    world = GuardedWorld()
    guard = world.guard("anthropic")
    adapter, mock = llm(guard)
    mock.script.append(TIMEOUT)
    with call_scope(world.ctx), pytest.raises(CallTimeoutError):
        adapter.complete(llm_request(), idempotency_key=key())
    return world, guard


def test_a_timeout_leaves_a_listed_hold_and_a_settled_call_is_not_listed() -> None:
    world, _ = _held_world()
    tenant = world.ctx.tenant
    held = list_held(world.w.ledger, MemoryTenancy(), tenant, world.job)
    assert len(held) == 1
    h = held[0]
    assert (h.provider, h.job_id, h.currency) == ("anthropic", world.job, "USD")
    assert h.amount_micros > 0 and h.operation == "llm.completion"
    # a settled call (tokens recorded) is never listed as a hold
    adapter, _mock = llm(world.guard("anthropic"))
    with call_scope(world.ctx):
        adapter.complete(llm_request(), idempotency_key=key(2))
    rows = list(world.w.ledger.for_job(world.w.tx, world.job))
    assert len(rows) == 2
    assert [x.entry_id for x in held_calls(rows)] == [h.entry_id]
    assert not is_hold_row(next(r for r in rows if r.id != h.entry_id).entry)


def test_reconcile_replaces_the_hold_with_a_verified_row_and_unblocks_the_cap() -> None:
    world, _ = _held_world()
    tenant, tenancy = world.ctx.tenant, MemoryTenancy()
    (h,) = list_held(world.w.ledger, tenancy, tenant, world.job)
    row = reconcile_held(
        world.w.ledger, tenancy, tenant, h.entry_id,
        actual_micros=0, verification_ref="provider-usage-console 2026-11-19",
    )  # fmt: skip
    assert row.entry.figure_kind is CostFigureKind.VERIFIED
    assert row.entry.estimate_entry_id == h.entry_id and row.entry.amount_micros == 0
    assert list_held(world.w.ledger, tenancy, tenant, world.job) == []
    eff = effective_rows(world.w.ledger.for_job(world.w.tx, world.job))
    assert sum(r.entry.amount_micros for r in eff) == 0
    with pytest.raises(InputInvalidError):  # a second reconcile of the same hold is refused
        reconcile_held(
            world.w.ledger, tenancy, tenant, h.entry_id,
            actual_micros=0, verification_ref="again",
        )  # fmt: skip
    with pytest.raises(InputInvalidError):  # a VERIFIED row is not a hold
        reconcile_held(
            world.w.ledger, tenancy, tenant, row.id,
            actual_micros=0, verification_ref="x",
        )  # fmt: skip


def test_reconcile_refuses_bad_figures_and_a_row_of_another_tenant() -> None:
    world, _ = _held_world()
    tenant, tenancy = world.ctx.tenant, MemoryTenancy()
    (h,) = list_held(world.w.ledger, tenancy, tenant, world.job)
    for bad in (-1, True):
        with pytest.raises(InputInvalidError):
            reconcile_held(
                world.w.ledger, tenancy, tenant, h.entry_id,
                actual_micros=bad, verification_ref="r",
            )  # fmt: skip
    with pytest.raises(InputInvalidError):
        reconcile_held(
            world.w.ledger, tenancy, tenant, h.entry_id,
            actual_micros=1, verification_ref="  ",
        )  # fmt: skip
    other = GuardedWorld()  # another org: the row does not exist for it
    with pytest.raises(InputInvalidError):
        reconcile_held(
            world.w.ledger, tenancy, other.ctx.tenant, h.entry_id,
            actual_micros=0, verification_ref="r",
        )  # fmt: skip
    assert list_held(world.w.ledger, tenancy, other.ctx.tenant, world.job) == []


def test_the_two_commands_list_dry_run_and_apply() -> None:
    world, _ = _held_world()
    out: list[str] = []
    org, ops = str(world.ctx.tenant.org_id), "sys_operator"
    services = (world.w.ledger, MemoryTenancy())
    base = ["--org-id", org, "--operator", ops]
    assert list_main([*base, "--job-id", str(world.job)], services=services, out=out.append) == 0
    (line,) = [x for x in out if x.startswith("cst_")]
    entry_id = line.split(" | ")[0]
    assert "1 held call(s)" in out[-1]
    out.clear()
    args = [*base, "--entry-id", entry_id, "--actual-micros", "0", "--verification-ref", "console"]
    assert reconcile_main(args, services=services, out=out.append) == 0
    assert "dry run" in out[0] and "nothing written" in out[-1]
    assert len(list_held(*services, world.ctx.tenant, world.job)) == 1
    out.clear()
    assert reconcile_main([*args, "--apply"], services=services, out=out.append) == 0
    assert out[-1].startswith("recorded")
    out.clear()
    assert list_main([*base, "--job-id", str(world.job)], services=services, out=out.append) == 0
    assert out == ["no held calls"]
    out.clear()  # a second apply is refused (exit 2), as is a bad id
    assert reconcile_main([*args, "--apply"], services=services, out=out.append) == 2
    bad = [*base, "--entry-id", "nope", "--actual-micros", "0", "--verification-ref", "c"]
    assert reconcile_main(bad, services=services, out=out.append) == 2


def test_the_command_refuses_without_a_database_variable() -> None:
    out: list[str] = []
    code = list_main(["--org-id", "org_x", "--job-id", "job_x"], out=out.append, environ={})
    assert code == 2 and "AMW_DATABASE_URL" in out[0]


def test_an_amount_above_the_held_worst_case_is_flagged_by_the_command() -> None:
    world, _ = _held_world()
    out: list[str] = []
    services = (world.w.ledger, MemoryTenancy())
    (h,) = list_held(*services, world.ctx.tenant, world.job)
    code = reconcile_main(
        ["--org-id", str(world.ctx.tenant.org_id), "--entry-id", str(h.entry_id),
         "--actual-micros", str(h.amount_micros + 1), "--verification-ref", "c"],
        services=services, out=out.append,
    )  # fmt: skip
    assert code == 0 and out[0].startswith("warning: actual")


# ---- one hold book per job: LLM and TTS guards see each other's in-flight calls -----------------


def _plan(provider: str, op: str, micros: int, n: int, ctx_org: str) -> PlannedCall:
    return PlannedCall(
        provider=provider, operation=op, worst_case_micros=micros, currency="USD",
        idempotency_key=make_idempotency_key(ctx_org, "llm.call", [provider, n]),
        price_ref="PR-10",
    )  # fmt: skip


def test_in_flight_holds_are_shared_by_the_llm_and_tts_guards_of_one_job() -> None:
    world = GuardedWorld()
    llm_guard, tts_guard = world.guard("anthropic"), world.guard("elevenlabs")
    org = str(world.ctx.tenant.org_id)
    with call_scope(world.ctx):
        llm_guard.before(_plan("anthropic", "llm.completion", 3_000_000, 1, org))
        with pytest.raises(BudgetExhaustedError):  # 3 + 3 > 5: the TTS guard sees the LLM hold
            tts_guard.before(_plan("elevenlabs", "tts.synthesize", 3_000_000, 1, org))
        assert llm_guard.in_flight_micros(org, str(world.job)) == 3_000_000
        llm_guard.failed(_plan("anthropic", "llm.completion", 0, 1, org).idempotency_key,
                         delivered=False)  # fmt: skip
        assert tts_guard.in_flight_micros(org, str(world.job)) == 0
        tts_guard.before(_plan("elevenlabs", "tts.synthesize", 3_000_000, 1, org))
        tts_guard.failed(_plan("elevenlabs", "tts.synthesize", 0, 1, org).idempotency_key,
                         delivered=False)  # fmt: skip


def test_cap_only_guards_with_one_book_share_the_cap_and_without_one_do_not() -> None:
    book = CapBook()
    a = CapOnlyCallGuard(auth("anthropic"), book=book)
    b = CapOnlyCallGuard(auth("elevenlabs"), book=book)
    a.before(_plan("anthropic", "llm.completion", 3_000_000, 1, ORG_ID))
    with pytest.raises(BudgetExhaustedError):
        b.before(_plan("elevenlabs", "tts.synthesize", 3_000_000, 1, ORG_ID))
    assert b.held_micros == 3_000_000
    lone_a, lone_b = cap_guard("anthropic"), cap_guard("elevenlabs")  # the old behaviour
    lone_a.before(_plan("anthropic", "llm.completion", 3_000_000, 2, ORG_ID))
    lone_b.before(_plan("elevenlabs", "tts.synthesize", 3_000_000, 2, ORG_ID))  # not refused


# ---- a real run preflight binds its tokens to the job -------------------------------------------


def test_run_job_preflight_binds_the_authorisations_to_the_job_and_org() -> None:
    job = _job(ChannelCategory.FINANCE)
    config = load_runtime_config(REAL_ENV)
    records = limits(job.org_id)
    report = run_job_preflight(
        job, config, records, env=REAL_ENV, evidence=Lookup(records, job.org_id),
        render_start=EVENING, job_id="job_someone_else",
    )  # fmt: skip
    assert {a.provider for a in report.provider_authorisations} == {"anthropic", "elevenlabs"}
    for token in report.provider_authorisations:
        grant = verify_authorisation(
            token, datetime.now(UTC), provider=token.provider, currency=config.currency
        )
        assert (grant.org_id, grant.job_id) == (job.org_id, job.job_id)
