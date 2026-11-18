"""Transition checks and job derivation (03 sections 11.3-11.5).

``check_task`` / ``check_job`` validate one requested change against the code table and the
row-level conditions the tables state (``wait_reason`` iff ``CHECKPOINTED``, ``next_attempt_at`` for
``RETRY_WAIT``, ``outcome`` iff ``COMPLETED``, the actor kind of the actor column). Guards that need
other data (budget, admission, permissions, deadlines) are the caller's (orchestrator, worker,
scheduler); the DB trigger re-checks the pair. ``derive_job`` is the 03 section 11.5 rule set,
evaluated after every task transition in the same transaction.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from amw_core.enums import ActorKind, EntityKind, JobState, TaskState, TransitionId, WaitReason
from amw_core.errors import InputInvalidError, InvalidTransitionError
from amw_core.ids import ActorRef, is_actor_ref
from amw_core.interfaces.job_store import JobTransition, TaskTransition
from amw_core.state_machine.rules import Rule, find_rule


def actor_kind_of(actor: ActorRef) -> ActorKind:
    """GLOSSARY section 2.3: ``usr_`` human, ``agent_NN`` agent, ``svc_sNN`` service, ``sys_*``."""
    if not is_actor_ref(actor):
        raise InputInvalidError("not an actor reference", details={"value": actor[:80]})
    if actor.startswith("usr_"):
        return ActorKind.HUMAN
    if actor.startswith("agent_"):
        return ActorKind.AGENT
    if actor.startswith("svc_"):
        return ActorKind.SERVICE
    return ActorKind.SYSTEM


def authority_of(rule: Rule) -> str:
    """``state_transitions.authority`` / ``audit_log.authority`` of a state-machine transition:
    the policy ID of the table row that allowed it."""
    return f"state_machine.{rule.transition_id.value}"


def _rule(tid: TransitionId, entity: EntityKind, frm: str | None, to: str) -> Rule:
    if tid.entity_kind is not entity:
        raise InvalidTransitionError(f"{tid.value} is not a {entity.value.lower()} transition")
    rule = find_rule(tid, frm, to)
    if rule is None:
        raise InvalidTransitionError(
            f"{tid.value} does not allow {frm or '∅'} -> {to}",
            details={"transition_id": tid.value, "from": frm, "to": to},
        )
    return rule


def _check_actor(rule: Rule, actor: ActorRef) -> None:
    kind = actor_kind_of(actor)
    if kind not in rule.actor_kinds:
        raise InvalidTransitionError(
            f"{rule.transition_id.value} is not allowed for a {kind.value} actor",
            details={"transition_id": rule.transition_id.value, "actor_kind": kind.value},
        )


def check_task(change: TaskTransition) -> Rule:
    rule = _rule(change.transition_id, EntityKind.TASK, change.from_state, change.to_state)
    _check_actor(rule, change.actor)
    to = change.to_state
    if (to is TaskState.CHECKPOINTED) != (change.wait_reason is not None):
        raise InvalidTransitionError("wait_reason is set exactly when the task is CHECKPOINTED")
    if (
        change.transition_id is TransitionId.T05
        and change.wait_reason is not WaitReason.AWAITING_BUDGET
    ):
        raise InvalidTransitionError("T05 suspends with wait_reason AWAITING_BUDGET")
    if (to is TaskState.RETRY_WAIT) != (change.next_attempt_at is not None):
        raise InvalidTransitionError("next_attempt_at is set exactly for RETRY_WAIT")
    if (
        change.transition_id is TransitionId.T19
        and change.from_state is TaskState.FAILED
        and not change.reason
    ):
        raise InvalidTransitionError("cancelling a FAILED task records a reason")
    if change.transition_id in (TransitionId.T18, TransitionId.T19) and not change.reason:
        raise InvalidTransitionError("a cancellation records its reason")
    return rule


def check_job(change: JobTransition) -> Rule:
    rule = _rule(change.transition_id, EntityKind.JOB, change.from_state, change.to_state)
    _check_actor(rule, change.actor)
    if (change.to_state is JobState.COMPLETED) != (change.outcome is not None):
        raise InvalidTransitionError("outcome is set exactly when the job is COMPLETED")
    if (change.monetized_destination is not None) != (change.transition_id is TransitionId.J02):
        raise InvalidTransitionError("monetized_destination is set only at J02 (CCR-028)")
    if change.transition_id is TransitionId.J08 and change.failed_task_id is None:
        raise InvalidTransitionError("J08 names the failed required task")
    return rule


@dataclass(frozen=True, slots=True)
class TaskView:
    """What job derivation reads of one task."""

    state: TaskState
    is_required: bool


@dataclass(frozen=True, slots=True)
class Derivation:
    transition_id: TransitionId
    to_state: JobState


_ACTIVE = frozenset(
    {TaskState.VALIDATING, TaskState.QUEUED, TaskState.RUNNING, TaskState.RETRY_WAIT}
)


def derive_job(
    job_state: JobState, tasks: Sequence[TaskView], cause: TransitionId | None
) -> Derivation | None:
    """03 section 11.5 after a task transition ``cause`` (``None`` = re-evaluation only).

    Precedence: a failed required task (J08) wins over completion (J07), which wins over the
    wait (J06) and the start (J05). J07 is returned as a candidate; the orchestrator supplies the
    outcome (``PUBLISHED`` / ``DELIVERED`` need the publication or delivery check). A required
    task ``CANCELLED`` counts as superseded only when the job has at least one completed required
    task (a job cancel is J12, never J07).
    """
    required = [t for t in tasks if t.is_required]
    states = {t.state for t in tasks}
    if job_state is JobState.FAILED:
        if cause is TransitionId.T14 and any(t.state is TaskState.DEAD_LETTER for t in required):
            return Derivation(TransitionId.J09, JobState.DEAD_LETTER)
        return None
    if job_state is JobState.DEAD_LETTER:
        if cause is TransitionId.T17:
            return Derivation(TransitionId.J10, JobState.RUNNING)
        return None
    if job_state not in (JobState.QUEUED, JobState.RUNNING, JobState.CHECKPOINTED):
        return None
    if any(t.state is TaskState.FAILED for t in required):
        return Derivation(TransitionId.J08, JobState.FAILED)
    if job_state is JobState.CHECKPOINTED:
        if cause is TransitionId.T15:
            return Derivation(TransitionId.J05, JobState.RUNNING)
        return None
    done = {TaskState.COMPLETED, TaskState.CANCELLED}
    if (
        required
        and all(t.state in done for t in required)
        and any(t.state is TaskState.COMPLETED for t in required)
    ):
        return Derivation(TransitionId.J07, JobState.COMPLETED)
    if not (states & _ACTIVE) and TaskState.CHECKPOINTED in states:
        return Derivation(TransitionId.J06, JobState.CHECKPOINTED)
    if job_state is JobState.QUEUED and TaskState.RUNNING in states:
        return Derivation(TransitionId.J05, JobState.RUNNING)
    return None
