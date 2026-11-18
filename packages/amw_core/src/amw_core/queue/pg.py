"""``TaskQueue`` on PostgreSQL (ADR-001 option A; 04 section 5.4; 03 section 11.4 step 5).

Enqueue / done / cancel run in the tenant transaction of the transition that causes them. Claim and
lease renewal are cross-tenant and go through the ``SECURITY DEFINER`` functions
``amw_queue_claim`` / ``amw_queue_heartbeat`` on a connection of their own (no tenant setting).
LISTEN/NOTIFY is a wake-up only: the payload is the queue name, never tenant content.
"""

import logging
from collections.abc import Sequence
from datetime import datetime

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from amw_core.contracts.envelope import Envelope
from amw_core.enums import Capability, Priority, QueueItemStatus, QueueName, ResourceClass
from amw_core.errors import InputInvalidError, InvalidTransitionError, WorkerLostError
from amw_core.ids import (
    CHECKPOINT,
    JOB,
    ORG,
    QUEUE_ITEM,
    TASK,
    WORKER,
    QueueItemId,
    TaskId,
    WorkerId,
    new_uuid7,
)
from amw_core.interfaces.queue import ClaimedItem, ClaimRequest, NewQueueItem, QueueItem
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.tenancy import ConnectionFactory, connection_of, org_uuid_of, translate_db_error

NOTIFY_CHANNEL = "amw_queue"
_log = logging.getLogger("amw_core.queue")


def _priority(value: int) -> Priority:
    return next(p for p in Priority if p.queue_int == value)


class PgTaskQueue:
    """``connections`` yields an ``amw_app`` connection with no tenant context (claims, NOTIFY)."""

    def __init__(self, connections: ConnectionFactory) -> None:
        self._connections = connections

    def enqueue(self, tx: TenantTransaction, item: NewQueueItem) -> QueueItem:
        if item.envelope.org_id != tx.context.org_id:
            raise InputInvalidError("envelope org differs from the transaction tenant")
        conn = connection_of(tx)
        try:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "INSERT INTO task_queue (id, org_id, task_id, job_id, queue_name, priority,"
                    " resource_class, required_capabilities, scheduled_at, fair_share_key,"
                    " resume_checkpoint_id, envelope)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
                    (
                        new_uuid7(),
                        org_uuid_of(tx),
                        TASK.to_uuid(item.task_id),
                        JOB.to_uuid(item.job_id),
                        item.queue_name.value,
                        item.priority.queue_int,
                        item.resource_class.value,
                        [c.value for c in item.required_capabilities],
                        item.scheduled_at,
                        tx.context.org_id,
                        CHECKPOINT.to_uuid(item.resume_checkpoint_id)
                        if item.resume_checkpoint_id
                        else None,
                        Jsonb(item.envelope.to_doc()),
                    ),
                )
                row = cur.fetchone()
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc
        assert row is not None  # noqa: S101 - INSERT ... RETURNING
        return QueueItem(
            id=QUEUE_ITEM.from_uuid(row["id"]),
            org_id=ORG.from_uuid(row["org_id"]),
            task_id=item.task_id,
            job_id=item.job_id,
            queue_name=QueueName(row["queue_name"]),
            status=QueueItemStatus(row["status"]),
            priority=_priority(row["priority"]),
            resource_class=ResourceClass(row["resource_class"]),
            required_capabilities=tuple(Capability(c) for c in row["required_capabilities"]),
            scheduled_at=row["scheduled_at"],
            claimed_by=None,
            lease_expires_at=None,
            envelope=item.envelope,
            resume_checkpoint_id=item.resume_checkpoint_id,
        )

    def claim(self, request: ClaimRequest) -> Sequence[ClaimedItem]:
        if request.limit < 1 or request.lease_ms < 1:
            raise InputInvalidError("claim limit and lease_ms must be positive")
        try:
            with self._connections() as conn, conn.transaction():
                rows = conn.execute(
                    "SELECT queue_item_id, org_id, task_id, envelope"
                    " FROM amw_queue_claim(%s, %s, %s, %s, %s, %s)",
                    (
                        WORKER.to_uuid(request.worker_id),
                        [c.value for c in request.capabilities],
                        [r.value for r in request.resource_classes],
                        request.limit,
                        [q.value for q in request.queue_names],
                        request.lease_ms,
                    ),
                ).fetchall()
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc
        claimed = [
            ClaimedItem(
                queue_item_id=QUEUE_ITEM.from_uuid(item),
                org_id=ORG.from_uuid(org),
                task_id=TASK.from_uuid(task),
                envelope=Envelope.model_validate(envelope),
            )
            for item, org, task, envelope in rows
        ]
        _log.info(
            "queue.claim",
            extra={"actor": request.worker_id, "claimed": len(claimed), "system_function": True},
        )
        return claimed

    def heartbeat(self, item_id: QueueItemId, worker_id: WorkerId, lease_ms: int) -> datetime:
        if lease_ms < 1:
            raise InputInvalidError("lease_ms must be positive")
        try:
            with self._connections() as conn, conn.transaction():
                row = conn.execute(
                    "SELECT amw_queue_heartbeat(%s, %s, %s)",
                    (QUEUE_ITEM.to_uuid(item_id), WORKER.to_uuid(worker_id), lease_ms),
                ).fetchone()
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc
        if row is None or row[0] is None:
            raise WorkerLostError("lease is no longer held by this worker")
        until: datetime = row[0]
        return until

    def mark_done(self, tx: TenantTransaction, item_id: QueueItemId) -> None:
        conn = connection_of(tx)
        try:
            cur = conn.execute(
                "UPDATE task_queue SET status = 'DONE'"
                " WHERE org_id = %s AND id = %s AND status = 'CLAIMED'",
                (org_uuid_of(tx), QUEUE_ITEM.to_uuid(item_id)),
            )
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc
        if cur.rowcount != 1:
            raise InvalidTransitionError("queue item is not CLAIMED in this tenant")

    def cancel_for_task(self, tx: TenantTransaction, task_id: TaskId) -> None:
        conn = connection_of(tx)
        try:
            conn.execute(
                "UPDATE task_queue SET status = 'CANCELLED'"
                " WHERE org_id = %s AND task_id = %s AND status IN ('READY', 'CLAIMED')",
                (org_uuid_of(tx), TASK.to_uuid(task_id)),
            )
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc

    def notify(self, queue_name: QueueName) -> None:
        try:
            with self._connections() as conn, conn.transaction():
                conn.execute("SELECT pg_notify(%s, %s)", (NOTIFY_CHANNEL, queue_name.value))
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc

    def wait_for_work(self, queue_names: Sequence[QueueName], timeout_ms: int) -> bool:
        wanted = {q.value for q in queue_names}
        try:
            with self._connections() as conn:
                conn.autocommit = True
                conn.execute(
                    psycopg.sql.SQL("LISTEN {}").format(psycopg.sql.Identifier(NOTIFY_CHANNEL))
                )
                for note in conn.notifies(timeout=timeout_ms / 1000.0):
                    if note.payload in wanted:
                        return True
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc
        return False
