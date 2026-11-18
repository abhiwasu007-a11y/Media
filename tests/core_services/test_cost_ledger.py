"""Cost ledger rules (09 sections 3.3, 5, 6; 04 section 5.14) on the in-memory ledger."""

from dataclasses import replace
from decimal import Decimal

import pytest

from amw_core.cost import MemoryCostLedger, amount_in, effective_rows, figure_kind_label, totals
from amw_core.enums import CostFigureKind, CostOperation, CostUnitKind
from amw_core.errors import ConfigInvalidError, IdempotencyConflictError, InputInvalidError
from amw_core.ids import JOB, ORG, TASK, make_idempotency_key
from amw_core.interfaces.cost_ledger import CostLedger, NewCostEntry
from tests.core_services.support import T0, tx_for

pytestmark = pytest.mark.unit
ORG_A = ORG.new()
JOB_A = JOB.new()
TASK_A = TASK.new()


def _e(amount: int = 1_000, **kw: object) -> NewCostEntry:
    base = NewCostEntry(
        provider="llm_provider",
        operation=CostOperation.LLM_COMPLETION,
        amount_micros=amount,
        currency="INR",
        figure_kind=CostFigureKind.ESTIMATE,
        occurred_at=T0,
        job_id=JOB_A,
        task_id=TASK_A,
        model="model-from-config",
        tokens_in=10,
        tokens_out=20,
        price_ref="pricing.v1",
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def test_is_a_cost_ledger() -> None:
    assert isinstance(MemoryCostLedger(), CostLedger)


def test_record_and_read_back() -> None:
    led = MemoryCostLedger()
    tx = tx_for(ORG_A)
    row = led.record(tx, _e())
    assert led.get(tx, row.id) == row and led.for_job(tx, JOB_A) == [row]
    assert led.for_task(tx, TASK_A) == [row]
    t = led.job_totals(tx, JOB_A)
    assert (t.estimate_micros, t.verified_micros, t.effective_micros, t.rows) == (1000, 0, 1000, 1)


def test_replay_by_idempotency_key_is_a_no_op_and_conflict_is_refused() -> None:
    led = MemoryCostLedger()
    tx = tx_for(ORG_A)
    key = make_idempotency_key(ORG_A, "llm.call", [TASK_A, "draft", 1])
    first = led.record(tx, _e(idempotency_key=key))
    again = led.record(tx, _e(idempotency_key=key, occurred_at=T0.replace(minute=5)))
    assert again == first and len(led.all_rows(tx)) == 1
    with pytest.raises(IdempotencyConflictError):
        led.record(tx, _e(2_000, idempotency_key=key))


def test_verified_replaces_its_estimate_in_effective_sums() -> None:
    led = MemoryCostLedger()
    tx = tx_for(ORG_A)
    est = led.record(tx, _e(1_000))
    est2 = led.record(tx, _e(500))
    ver = led.record(
        tx,
        _e(1_200, figure_kind=CostFigureKind.VERIFIED, price_ref=None, estimate_entry_id=est.id,
           verification_ref="usage-export-1"),
    )  # fmt: skip
    t = led.job_totals(tx, JOB_A)
    assert (t.estimate_micros, t.verified_micros, t.effective_micros) == (1500, 1200, 1700)
    assert (t.rows, t.verified_rows) == (2, 1)
    assert figure_kind_label(t) == "partly verified (1 of 2 rows)"
    assert {r.id for r in effective_rows(led.all_rows(tx))} == {ver.id, est2.id}
    assert led.get(tx, est.id) is not None  # the estimate is never overwritten
    with pytest.raises(InputInvalidError):  # one VERIFIED per estimate
        led.record(tx, _e(1, figure_kind=CostFigureKind.VERIFIED, price_ref=None,
                          estimate_entry_id=est.id, verification_ref="x"))  # fmt: skip
    with pytest.raises(InputInvalidError):  # must point to an ESTIMATE
        led.record(tx, _e(1, figure_kind=CostFigureKind.VERIFIED, price_ref=None,
                          estimate_entry_id=ver.id, verification_ref="x"))  # fmt: skip


def test_leak_and_labels() -> None:
    led = MemoryCostLedger()
    tx = tx_for(ORG_A)
    assert figure_kind_label(totals([], "INR")) == "ESTIMATE"
    leak = led.record(
        tx, _e(300, figure_kind=CostFigureKind.VERIFIED, price_ref=None, verification_ref="inv-7")
    )
    assert [f.entry_id for f in led.leaks(tx)] == [leak.id]
    assert figure_kind_label(led.job_totals(tx, JOB_A)) == "VERIFIED"


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"amount_micros": -1}, ConfigInvalidError),
        ({"amount_micros": 1.5}, InputInvalidError),
        ({"amount_micros": True}, InputInvalidError),
        ({"currency": "inr"}, InputInvalidError),
        ({"price_ref": None}, ConfigInvalidError),
        ({"fx_rate": Decimal("83.1")}, ConfigInvalidError),
        ({"fx_rate": Decimal(0), "fx_source": "x"}, ConfigInvalidError),
        ({"units": Decimal(5)}, InputInvalidError),
        ({"units": Decimal(-1), "unit_kind": CostUnitKind.CHARACTERS}, InputInvalidError),
        ({"tokens_in": -1}, InputInvalidError),
        ({"provider": ""}, InputInvalidError),
        ({"occurred_at": T0.replace(tzinfo=None)}, InputInvalidError),
        ({"units": Decimal(10), "unit_kind": CostUnitKind.QUOTA_UNITS}, InputInvalidError),
        ({"verification_ref": "x"}, InputInvalidError),
        ({"figure_kind": CostFigureKind.VERIFIED}, InputInvalidError),
        ({"idempotency_key": "not-a-key"}, InputInvalidError),
    ],
)
def test_invalid_rows_are_refused(change: dict[str, object], error: type[Exception]) -> None:
    with pytest.raises(error):
        MemoryCostLedger().record(tx_for(ORG_A), _e(**change))


def test_quota_rows_carry_no_money_and_need_no_price() -> None:
    row = MemoryCostLedger().record(
        tx_for(ORG_A),
        _e(0, operation=CostOperation.YOUTUBE_QUOTA, price_ref=None, units=Decimal(1600),
           unit_kind=CostUnitKind.QUOTA_UNITS),
    )  # fmt: skip
    assert row.entry.amount_micros == 0


@pytest.mark.tenancy
def test_rows_are_partitioned_by_tenant() -> None:
    led = MemoryCostLedger()
    a, b = tx_for(ORG_A), tx_for(ORG.new())
    row = led.record(a, _e())
    assert led.get(b, row.id) is None and led.for_job(b, JOB_A) == []


def test_currency_rules() -> None:
    led = MemoryCostLedger()
    tx = tx_for(ORG_A)
    usd = led.record(tx, _e(1_000_000, currency="USD", fx_rate=Decimal("83.25"), fx_source="rbi"))
    assert amount_in(usd, "INR") == 83_250_000
    assert amount_in(usd, "USD") == 1_000_000
    odd = led.record(tx, _e(3, currency="USD", fx_rate=Decimal("0.5"), fx_source="x"))
    assert amount_in(odd, "INR") == 2  # rounded up: a budget is never under-counted
    plain = led.record(tx, _e(5, currency="USD"))
    with pytest.raises(ConfigInvalidError):
        amount_in(plain, "INR")
    led.record(tx, _e(5))
    with pytest.raises(ConfigInvalidError):
        led.job_totals(tx, JOB_A)
