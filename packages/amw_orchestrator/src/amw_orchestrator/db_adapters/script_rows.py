"""``ScriptRowPort`` of agent_05 on PostgreSQL: the ``scripts`` table (04 section 5.11; agent_05
blueprint section 13).

Each call is one short tenant transaction as ``amw_app`` with actor ``agent_05`` (explicit
``org_id`` on every statement, RLS behind it). ``insert`` is the blueprint's one transaction: the
``DRAFT`` row, the previous version of the same job and language set to ``SUPERSEDED`` (the only
UPDATE agent_05 makes; the row trigger of CCR-033 allows nothing else) and the audit event.

Idempotent per ``(job, language, version)``: the same row with an equal hash is a no-op replay
(no second audit event, no second supersede); the same key with another hash, or the same script
ID under another key, is ``IdempotencyConflictError``. A job, channel, task or parent script that
is not in the tenant is ``MissingDependencyError`` (fail closed; another tenant's row is invisible).
Writes only ``scripts`` and ``audit_log``.
"""

import psycopg

from agent_05_scriptwriter.protocols import SavedScript, StepContext
from amw_core.enums import ActorKind
from amw_core.errors import IdempotencyConflictError, InputInvalidError, MissingDependencyError
from amw_core.ids import (
    CHANNEL,
    CORRELATION,
    JOB,
    ORG,
    TASK,
    actor_ref,
    format_id,
)
from amw_core.interfaces import Clock, TenancyContext, TenantContext
from amw_core.interfaces.audit_log import AuditLog, NewAuditEntry
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_orchestrator.db_adapters._sql import SCRIPT, org_of, require, rows, uuid_of

AGENT = "agent_05"
AUTHORITY = "agent_05.persist"
EVENT = "script.created"
_SUPERSEDABLE = ("DRAFT", "IN_REVIEW")


class PgScriptRowPort:
    def __init__(self, tenancy: TenancyContext, audit: AuditLog, clock: Clock) -> None:
        self._tenancy = tenancy
        self._audit = audit
        self._clock = clock

    @staticmethod
    def _context(ctx: StepContext) -> TenantContext:
        return TenantContext(
            org_id=ORG.validate(ctx.org_id),
            actor=actor_ref(AGENT),
            correlation_id=CORRELATION.validate(ctx.correlation_id),
        )

    def latest_version(self, ctx: StepContext, language: str) -> int:
        with self._tenancy.transaction(self._context(ctx)) as tx:
            found = rows(
                tx,
                "SELECT coalesce(max(version), 0) FROM scripts"
                " WHERE org_id = %s AND job_id = %s AND language = %s",
                (org_of(tx), uuid_of(JOB, ctx.job_id), language),
            )
        return int(found[0][0])

    def find(self, ctx: StepContext, language: str, version: int) -> SavedScript | None:
        with self._tenancy.transaction(self._context(ctx)) as tx:
            return self._find(tx, ctx, language, version)

    def insert(
        self,
        ctx: StepContext,
        saved: SavedScript,
        *,
        iteration: int,
        language: str,
        parent_script_id: str | None,
        segment_count: int,
        word_count: int,
        est_duration_ms: int | None,
        prompt_id: str,
    ) -> None:
        script = uuid_of(SCRIPT, saved.script_id)
        job = uuid_of(JOB, ctx.job_id)
        try:
            digest = bytes.fromhex(saved.sha256)
        except ValueError:
            raise InputInvalidError("script sha256 is not hexadecimal") from None
        if len(digest) != 32:
            raise InputInvalidError("script sha256 must be 32 bytes")
        with self._tenancy.transaction(self._context(ctx)) as tx:
            org = org_of(tx)
            task = uuid_of(TASK, ctx.task_id)
            channel = uuid_of(CHANNEL, ctx.channel_id)
            parent = None if parent_script_id is None else uuid_of(SCRIPT, parent_script_id)
            require(tx, "jobs", org, job, "job")
            require(tx, "tasks", org, task, "task")
            require(tx, "channels", org, channel, "channel")
            if parent is not None:
                require(tx, "scripts", org, parent, "parent script")
            existing = self._find(tx, ctx, language, saved.version)
            if existing is not None:
                if existing.sha256 != saved.sha256 or existing.script_id != saved.script_id:
                    raise IdempotencyConflictError(
                        "a script row for this job, language and version exists with another"
                        " hash or ID",
                        details={"version": saved.version},
                    )
                return  # an equal replay: nothing to write, nothing to audit twice
            try:
                tx_rows = rows(
                    tx,
                    "INSERT INTO scripts (id, org_id, job_id, channel_id, language, version,"
                    " iteration, parent_script_id, status, body_ref, content_sha256,"
                    " segment_count, word_count, est_duration_ms, created_by_task_id, prompt_id)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'DRAFT', %s, %s, %s, %s, %s, %s, %s)"
                    " RETURNING id",
                    (
                        script, org, job, channel, language, saved.version, iteration, parent,
                        saved.uri, digest, segment_count, word_count, est_duration_ms, task,
                        prompt_id,
                    ),
                )  # fmt: skip
            except psycopg.errors.UniqueViolation:
                raise IdempotencyConflictError(
                    "the script ID is already used by another row",
                    details={"version": saved.version},
                ) from None
            if not tx_rows:  # pragma: no cover - INSERT ... RETURNING always returns the row
                raise MissingDependencyError("script row was not written")
            rows(
                tx,
                "UPDATE scripts SET status = 'SUPERSEDED' WHERE org_id = %s AND job_id = %s"
                " AND language = %s AND status = ANY(%s) AND version = ("
                "   SELECT max(version) FROM scripts WHERE org_id = %s AND job_id = %s"
                "   AND language = %s AND version < %s)",
                (org, job, language, list(_SUPERSEDABLE), org, job, language, saved.version),
            )
            self._audit.append(
                tx,
                NewAuditEntry(
                    actor_kind=ActorKind.AGENT,
                    actor_ref=actor_ref(AGENT),
                    authority=AUTHORITY,
                    action=EVENT,
                    target_kind="SCRIPT",
                    target_id=saved.script_id,
                    occurred_at=self._clock.now(),
                    job_id=JOB.validate(ctx.job_id),
                    correlation_id=CORRELATION.validate(ctx.correlation_id),
                    details={
                        "version": saved.version,
                        "iteration": iteration,
                        "language": language,
                        "sha256": saved.sha256,
                    },
                ),
            )

    @staticmethod
    def _find(
        tx: TenantTransaction, ctx: StepContext, language: str, version: int
    ) -> SavedScript | None:
        found = rows(
            tx,
            "SELECT id, version, body_ref, content_sha256 FROM scripts"
            " WHERE org_id = %s AND job_id = %s AND language = %s AND version = %s",
            (org_of(tx), uuid_of(JOB, ctx.job_id), language, version),
        )
        if not found:
            return None
        sid, ver, uri, digest = found[0]
        return SavedScript(
            format_id(SCRIPT.prefix, sid), int(ver), str(uri), bytes(digest).hex(), False
        )
