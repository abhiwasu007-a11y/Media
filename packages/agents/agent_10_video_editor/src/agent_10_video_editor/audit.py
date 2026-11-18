"""Audit actions of Agent 10 (blueprint 10 section 22): IDs, hashes, numbers only."""

from collections.abc import Mapping

from amw_core.enums import ActorKind
from amw_core.ids import ActorRef, CorrelationId, JobId
from amw_core.interfaces.audit_log import AuditLog, NewAuditEntry
from amw_core.interfaces.clock import Clock
from amw_core.interfaces.tenancy_context import TenantTransaction

AUDIT_ACTIONS = frozenset(
    {
        "render.started", "render.completed", "render.superseded", "render.guard_refused",
        "subtitles.completed", "qc.completed", "qc.gate_failed",
    }
)  # fmt: skip
AUTHORITY = "policy.agent_10.heavy_work"


def record(
    audit: AuditLog | None,
    tx: TenantTransaction,
    clock: Clock,
    *,
    action: str,
    target_kind: str,
    target_id: str,
    job_id: str,
    correlation_id: str,
    details: Mapping[str, int | str | bool | None],
) -> None:
    """Append one audit entry in the caller's transaction (no-op when no log is wired)."""
    if action not in AUDIT_ACTIONS:
        raise ValueError(f"unknown audit action {action!r}")
    if audit is None:
        return
    audit.append(
        tx,
        NewAuditEntry(
            actor_kind=ActorKind.AGENT,
            actor_ref=ActorRef("agent_10"),
            authority=AUTHORITY,
            action=action,
            target_kind=target_kind,
            target_id=target_id,
            occurred_at=clock.now(),
            job_id=JobId(job_id),
            correlation_id=CorrelationId(correlation_id),
            details=dict(details),
        ),
    )
