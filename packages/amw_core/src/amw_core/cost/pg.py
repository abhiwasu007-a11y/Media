"""PostgreSQL ``CostLedger`` (04 section 5.14; 09 sections 5-6). Append-only: INSERT and SELECT
only (the table's trigger rejects UPDATE / DELETE / TRUNCATE for every role).

A replayed write is detected under a transaction advisory lock on ``(org, idempotency_key)`` so
two concurrent writers of the same call can never both insert (the table's UNIQUE key includes
``occurred_at`` because of the partition key, so it alone would not catch a re-stamped retry).
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import psycopg

from amw_core.cost.ledger import same_content, totals, validate_new_entry
from amw_core.enums import BillingMode, CostFigureKind, CostOperation, CostUnitKind
from amw_core.errors import IdempotencyConflictError, InputInvalidError
from amw_core.ids import (
    ATTEMPT,
    CHANNEL,
    COST_ENTRY,
    JOB,
    TASK,
    CostEntryId,
    ExecutorId,
    IdempotencyKey,
    JobId,
    OrgId,
    TaskId,
)
from amw_core.interfaces.cost_ledger import CostEntry, CostTotals, NewCostEntry
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.tenancy import connection_of, org_uuid_of, translate_db_error

COLUMNS = (
    "id, org_id, job_id, task_id, attempt_id, channel_id, agent_id, provider, model, operation,"
    " billing_mode, tokens_in, tokens_out, tokens_cached_in, tokens_cache_write_in, chars_in,"
    " language, units, unit_kind, amount_micros, currency, fx_rate, fx_source, figure_kind,"
    " price_ref, estimate_entry_id, verification_ref, idempotency_key, occurred_at"
)


def _u(kind: Any, wire: str | None) -> uuid.UUID | None:
    return None if wire is None else kind.to_uuid(wire)


def _w(kind: Any, value: uuid.UUID | None) -> Any:
    return None if value is None else kind.from_uuid(value)


def row_to_entry(row: Sequence[Any]) -> CostEntry:
    (rid, org, job, task, att, chn, agent, provider, model, op, billing, t_in, t_out, t_cached,
     t_write, chars, lang, units, unit_kind, amount, currency, fx_rate, fx_source, kind,
     price_ref, estimate, verification, idk, occurred_at) = row  # fmt: skip
    entry = NewCostEntry(
        provider=provider,
        operation=CostOperation(op),
        amount_micros=int(amount),
        currency=str(currency),
        figure_kind=CostFigureKind(kind),
        occurred_at=occurred_at,
        job_id=_w(JOB, job),
        task_id=_w(TASK, task),
        attempt_id=_w(ATTEMPT, att),
        channel_id=_w(CHANNEL, chn),
        agent_id=ExecutorId(agent) if agent else None,
        model=model,
        billing_mode=BillingMode(billing) if billing else None,
        tokens_in=t_in,
        tokens_out=t_out,
        tokens_cached_in=t_cached,
        tokens_cache_write_in=t_write,
        chars_in=chars,
        language=lang,
        units=units,
        unit_kind=CostUnitKind(unit_kind) if unit_kind else None,
        fx_rate=fx_rate,
        fx_source=fx_source,
        price_ref=price_ref,
        estimate_entry_id=_w(COST_ENTRY, estimate),
        verification_ref=verification,
        idempotency_key=IdempotencyKey(idk) if idk else None,
    )
    return CostEntry(id=COST_ENTRY.from_uuid(rid), org_id=OrgId(f"org_{org}"), entry=entry)


class PgCostLedger:
    def _select(self, tx: TenantTransaction, where: str, params: Sequence[Any]) -> list[CostEntry]:
        conn = connection_of(tx)
        try:
            rows = conn.execute(
                f"SELECT {COLUMNS} FROM cost_ledger WHERE org_id = %s AND {where}"  # noqa: S608
                " ORDER BY occurred_at, id",
                (org_uuid_of(tx), *params),
            ).fetchall()
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc
        return [row_to_entry(r) for r in rows]

    def record(self, tx: TenantTransaction, entry: NewCostEntry) -> CostEntry:
        validate_new_entry(entry)
        conn = connection_of(tx)
        org = org_uuid_of(tx)
        try:
            if entry.idempotency_key is not None:
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"cost_ledger:{org}:{entry.idempotency_key}",),
                )
                found = self._select(
                    tx,
                    "idempotency_key = %s AND figure_kind = %s",
                    (entry.idempotency_key, str(entry.figure_kind)),
                )
                if found:
                    if not same_content(found[0].entry, entry):
                        raise IdempotencyConflictError("ledger replay with different content")
                    return found[0]
            if entry.estimate_entry_id is not None:
                target = self.get(tx, entry.estimate_entry_id)
                if target is None or target.entry.figure_kind is not CostFigureKind.ESTIMATE:
                    raise InputInvalidError("estimate_entry_id must point to an ESTIMATE row")
                if self._select(tx, "estimate_entry_id = %s", (_u(COST_ENTRY, target.id),)):
                    raise InputInvalidError("that ESTIMATE already has a VERIFIED row")
            entry_id = COST_ENTRY.new()
            e = entry
            conn.execute(
                f"INSERT INTO cost_ledger ({COLUMNS}) VALUES ("  # noqa: S608
                + ", ".join(["%s"] * 29)
                + ")",
                (
                    COST_ENTRY.to_uuid(entry_id),
                    org,
                    _u(JOB, e.job_id),
                    _u(TASK, e.task_id),
                    _u(ATTEMPT, e.attempt_id),
                    _u(CHANNEL, e.channel_id),
                    e.agent_id,
                    e.provider,
                    e.model,
                    str(e.operation),
                    str(e.billing_mode) if e.billing_mode else None,
                    e.tokens_in,
                    e.tokens_out,
                    e.tokens_cached_in,
                    e.tokens_cache_write_in,
                    e.chars_in,
                    e.language,
                    e.units,
                    str(e.unit_kind) if e.unit_kind else None,
                    e.amount_micros,
                    e.currency,
                    e.fx_rate,
                    e.fx_source,
                    str(e.figure_kind),
                    e.price_ref,
                    _u(COST_ENTRY, e.estimate_entry_id),
                    e.verification_ref,
                    e.idempotency_key,
                    e.occurred_at,
                ),
            )
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc
        return CostEntry(id=entry_id, org_id=tx.context.org_id, entry=entry)

    def get(self, tx: TenantTransaction, entry_id: CostEntryId) -> CostEntry | None:
        rows = self._select(tx, "id = %s", (COST_ENTRY.to_uuid(entry_id),))
        return rows[0] if rows else None

    def for_job(self, tx: TenantTransaction, job_id: JobId) -> Sequence[CostEntry]:
        return self._select(tx, "job_id = %s", (JOB.to_uuid(job_id),))

    def for_task(self, tx: TenantTransaction, task_id: TaskId) -> Sequence[CostEntry]:
        return self._select(tx, "task_id = %s", (TASK.to_uuid(task_id),))

    def job_totals(self, tx: TenantTransaction, job_id: JobId) -> CostTotals:
        return totals(self.for_job(tx, job_id))

    def query(
        self,
        tx: TenantTransaction,
        *,
        job_id: JobId | None = None,
        task_id: TaskId | None = None,
        provider: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[CostEntry]:
        """Rows matching every given filter (budget scopes; the JSON export)."""
        clauses = ["TRUE"]
        params: list[Any] = []
        for clause, value in (
            ("job_id = %s", _u(JOB, job_id)),
            ("task_id = %s", _u(TASK, task_id)),
            ("provider = %s", provider),
            ("occurred_at >= %s", since),
            ("occurred_at < %s", until),
        ):
            if value is not None:
                clauses.append(clause)
                params.append(value)
        return self._select(tx, " AND ".join(clauses), params)
