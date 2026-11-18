"""The 03 section 11 transition tables in code (task 11.3, job 11.5).

Every allowed ``(from, to)`` pair is one ``Rule``; ``T19``, ``J05``-``J08`` and ``J12`` have one row
per source state, exactly as the ``state_transition_rules`` seed of migration 0002 (a test checks
code, seed and document agree). Anything not listed is invalid (03 section 11.3).

Actor kinds per the 03 actor column: ``ORCH`` = ``agent_01`` (AGENT), ``WKR`` = the executing agent
or service (AGENT, SERVICE), ``SCHED`` / ``REAP`` / ``DLQH`` = ``sys_*`` (SYSTEM), ``HUMAN``. A job
row is derived in the transaction of the task transition that causes it, so it takes the actor
kinds of the causing task rows.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from amw_core.enums import ActorKind, EntityKind, JobState, TaskState, TransitionId

A, S, Y, H = ActorKind.AGENT, ActorKind.SERVICE, ActorKind.SYSTEM, ActorKind.HUMAN


@dataclass(frozen=True, slots=True)
class Rule:
    transition_id: TransitionId
    from_state: str | None
    to_state: str
    actor_kinds: frozenset[ActorKind]
    audit_event: str

    @property
    def entity_kind(self) -> EntityKind:
        return self.transition_id.entity_kind


def _t(
    tid: str, frm: TaskState | None, to: TaskState, actors: tuple[ActorKind, ...], event: str
) -> Rule:
    return Rule(TransitionId(tid), frm, to, frozenset(actors), event)


def _j(
    tid: str, frm: JobState | None, to: JobState, actors: tuple[ActorKind, ...], event: str
) -> Rule:
    return Rule(TransitionId(tid), frm, to, frozenset(actors), event)


T = TaskState
J = JobState
_T19_FROM = (T.PENDING, T.VALIDATING, T.QUEUED, T.RETRY_WAIT, T.CHECKPOINTED, T.FAILED)

TASK_RULES: tuple[Rule, ...] = (
    _t("T01", None, T.PENDING, (A,), "task.created"),
    _t("T02", T.PENDING, T.VALIDATING, (A,), "task.validating"),
    _t("T03", T.VALIDATING, T.QUEUED, (A,), "task.queued"),
    _t("T04", T.VALIDATING, T.COMPLETED, (A,), "task.completed_idempotent"),
    _t("T05", T.VALIDATING, T.CHECKPOINTED, (A,), "task.suspended"),
    _t("T06", T.VALIDATING, T.FAILED, (A,), "task.failed"),
    _t("T07", T.QUEUED, T.RUNNING, (A, S), "task.started"),
    _t("T08", T.RUNNING, T.COMPLETED, (A, S), "task.completed"),
    _t("T09", T.RUNNING, T.CHECKPOINTED, (A, S), "task.suspended"),
    _t("T10", T.RUNNING, T.RETRY_WAIT, (A, S, Y), "task.retry_scheduled"),
    _t("T11", T.RUNNING, T.FAILED, (A, S, Y), "task.failed"),
    _t("T12", T.RETRY_WAIT, T.QUEUED, (Y,), "task.requeued"),
    _t("T13", T.RETRY_WAIT, T.FAILED, (Y,), "task.failed"),
    _t("T14", T.FAILED, T.DEAD_LETTER, (Y,), "task.dead_lettered"),
    _t("T15", T.CHECKPOINTED, T.QUEUED, (Y, A, H), "task.resumed"),
    _t("T16", T.CHECKPOINTED, T.FAILED, (Y,), "task.failed"),
    _t("T17", T.DEAD_LETTER, T.QUEUED, (H,), "task.replayed"),
    _t("T18", T.DEAD_LETTER, T.CANCELLED, (H,), "task.cancelled"),
    *(
        _t("T19", s, T.CANCELLED, (H,) if s is T.FAILED else (A, H), "task.cancelled")
        for s in _T19_FROM
    ),
    _t("T20", T.RUNNING, T.CANCELLED, (A, S, Y), "task.cancelled"),
)

_J12_FROM = (J.PENDING, J.VALIDATING, J.QUEUED, J.RUNNING, J.CHECKPOINTED, J.FAILED)
JOB_RULES: tuple[Rule, ...] = (
    _j("J01", None, J.PENDING, (A, Y, H), "job.created"),
    _j("J02", J.PENDING, J.VALIDATING, (A,), "job.validating"),
    _j("J03", J.VALIDATING, J.QUEUED, (A,), "job.queued"),
    _j("J04", J.VALIDATING, J.FAILED, (A,), "job.failed"),
    *(_j("J05", s, J.RUNNING, (A, S, Y, H), "job.running") for s in (J.QUEUED, J.CHECKPOINTED)),
    *(_j("J06", s, J.CHECKPOINTED, (A, S), "job.suspended") for s in (J.QUEUED, J.RUNNING)),
    *(_j("J07", s, J.COMPLETED, (A, S, H), "job.completed") for s in (J.QUEUED, J.RUNNING)),
    *(
        _j("J08", s, J.FAILED, (A, S, Y), "job.failed")
        for s in (J.QUEUED, J.RUNNING, J.CHECKPOINTED)
    ),
    _j("J09", J.FAILED, J.DEAD_LETTER, (Y,), "job.dead_lettered"),
    _j("J10", J.DEAD_LETTER, J.RUNNING, (H,), "job.replayed"),
    _j("J11", J.DEAD_LETTER, J.CANCELLED, (H,), "job.cancelled"),
    *(_j("J12", s, J.CANCELLED, (A, H), "job.cancelled") for s in _J12_FROM),
)

ALL_RULES: tuple[Rule, ...] = TASK_RULES + JOB_RULES

_BY_KEY: Mapping[tuple[TransitionId, str | None, str], Rule] = MappingProxyType(
    {(r.transition_id, r.from_state, r.to_state): r for r in ALL_RULES}
)
_PAIRS: Mapping[tuple[EntityKind, str | None, str], Rule] = MappingProxyType(
    {(r.entity_kind, r.from_state, r.to_state): r for r in ALL_RULES}
)

TASK_REJECTED_EVENT = "task.transition_rejected"
"""03 section 11.3: an invalid task transition attempt is audited under this event (03 names no
job counterpart, so a rejected job transition is logged and raised only)."""


def find_rule(transition_id: TransitionId, from_state: str | None, to_state: str) -> Rule | None:
    return _BY_KEY.get((transition_id, from_state, to_state))


def rule_for_pair(entity: EntityKind, from_state: str | None, to_state: str) -> Rule | None:
    """The rule of an allowed pair (each pair has exactly one transition ID)."""
    return _PAIRS.get((entity, from_state, to_state))


def is_allowed_pair(entity: EntityKind, from_state: str | None, to_state: str) -> bool:
    return (entity, from_state, to_state) in _PAIRS
