"""03 section 11 transition tables: code == document, checks per row, job derivation."""

import re
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from amw_core.enums import (
    ActorKind,
    EntityKind,
    JobOutcome,
    JobState,
    TaskState,
    TransitionId,
    WaitReason,
)
from amw_core.errors import InputInvalidError, InvalidTransitionError
from amw_core.ids import JOB, TASK, ActorRef
from amw_core.interfaces.job_store import JobTransition, TaskTransition
from amw_core.state_machine import (
    JOB_RULES,
    TASK_RULES,
    Rule,
    TaskView,
    actor_kind_of,
    authority_of,
    check_job,
    check_task,
    derive_job,
    is_allowed_pair,
    rule_for_pair,
)
from tests.docs_tables import doc_text, section, table_rows

pytestmark = pytest.mark.state_machine

ACTOR_TOKENS = {
    "ORCH": {ActorKind.AGENT},
    "WKR": {ActorKind.AGENT, ActorKind.SERVICE},
    "SCHED": {ActorKind.SYSTEM},
    "REAP": {ActorKind.SYSTEM},
    "DLQH": {ActorKind.SYSTEM},
    "HUMAN": {ActorKind.HUMAN},
}
ACTOR_FOR = {
    ActorKind.AGENT: ActorRef("agent_01"),
    ActorKind.SERVICE: ActorRef("svc_s07"),
    ActorKind.SYSTEM: ActorRef("sys_scheduler"),
    ActorKind.HUMAN: ActorRef("usr_0190a5e2-7b1c-7d2e-8f3a-123456789abc"),
}


def _states(cell: str) -> list[str | None]:
    if cell.strip() == "∅":
        return [None]
    return [s.strip() for s in cell.split("/")]


def doc_task_rows() -> set[tuple[str, str | None, str, frozenset[ActorKind], str]]:
    body = section(doc_text("03_COMMUNICATION_STANDARD.md"), r"11\.3 ", 3)
    rows = set()
    for cells in table_rows(body):
        tid, frm, to, _trigger, guard, actor, _effects, audit = cells
        kinds: set[ActorKind] = set()
        for token in re.findall(r"[A-Z]+", actor.split("(")[0]):
            kinds |= ACTOR_TOKENS.get(token, set())
        event = re.findall(r"`([^`]+)`", audit)[0]
        for state in _states(frm):
            actors = kinds
            if tid == "T19" and state == "FAILED":
                assert "human decision" in guard
                actors = {ActorKind.HUMAN}
            rows.add((tid, state, to.strip(), frozenset(actors), event))
    return rows


def doc_job_rows() -> set[tuple[str, str | None, str, str]]:
    body = section(doc_text("03_COMMUNICATION_STANDARD.md"), r"11\.5 ", 3)
    rows = set()
    for tid, frm, to, _rule, audit in table_rows(body):
        event = re.findall(r"`([^`]+)`", audit)[0]
        for state in _states(frm):
            rows.add((tid, state, to.strip(), event))
    return rows


def test_task_table_equals_document() -> None:
    code = {
        (r.transition_id.value, r.from_state, r.to_state, r.actor_kinds, r.audit_event)
        for r in TASK_RULES
    }
    assert code == doc_task_rows()
    assert len(TASK_RULES) == len(code)


def test_job_table_equals_document() -> None:
    code = {(r.transition_id.value, r.from_state, r.to_state, r.audit_event) for r in JOB_RULES}
    assert code == doc_job_rows()
    assert len(JOB_RULES) == len(code)


def test_every_transition_id_has_rows() -> None:
    used = {r.transition_id for r in (*TASK_RULES, *JOB_RULES)}
    assert used == set(TransitionId)


def test_each_pair_has_one_transition() -> None:
    pairs = [(r.entity_kind, r.from_state, r.to_state) for r in (*TASK_RULES, *JOB_RULES)]
    assert len(pairs) == len(set(pairs))


def _task_change(rule: Rule, actor_kind: ActorKind | None = None) -> TaskTransition:
    to = TaskState(rule.to_state)
    kind = actor_kind or sorted(rule.actor_kinds)[0]
    return TaskTransition(
        task_id=TASK.new(),
        transition_id=rule.transition_id,
        from_state=TaskState(rule.from_state) if rule.from_state else TaskState.PENDING,
        to_state=to,
        expected_state_version=1,
        actor=ACTOR_FOR[kind],
        wait_reason=(
            WaitReason.AWAITING_BUDGET
            if rule.transition_id is TransitionId.T05
            else WaitReason.DRAIN
            if to is TaskState.CHECKPOINTED
            else None
        ),
        next_attempt_at=datetime.now(UTC) if to is TaskState.RETRY_WAIT else None,
        reason="superseded" if to is TaskState.CANCELLED else None,
    )


TASK_IDS = [f"{r.transition_id.value}:{r.from_state}" for r in TASK_RULES]
JOB_IDS = [f"{r.transition_id.value}:{r.from_state}" for r in JOB_RULES]


@pytest.mark.parametrize("rule", [r for r in TASK_RULES if r.from_state], ids=TASK_IDS[1:])
def test_task_row_is_accepted(rule: Rule) -> None:
    for kind in rule.actor_kinds:
        assert check_task(_task_change(rule, kind)) is rule


@pytest.mark.parametrize("rule", [r for r in TASK_RULES if r.from_state], ids=TASK_IDS[1:])
def test_task_row_refuses_other_actor_kinds(rule: Rule) -> None:
    for kind in set(ActorKind) - rule.actor_kinds:
        with pytest.raises(InvalidTransitionError):
            check_task(_task_change(rule, kind))


def _job_change(rule: Rule, actor_kind: ActorKind | None = None) -> JobTransition:
    to = JobState(rule.to_state)
    tid = rule.transition_id
    return JobTransition(
        job_id=JOB.new(),
        transition_id=tid,
        from_state=JobState(rule.from_state) if rule.from_state else JobState.PENDING,
        to_state=to,
        expected_state_version=1,
        actor=ACTOR_FOR[actor_kind or sorted(rule.actor_kinds)[0]],
        outcome=JobOutcome.DELIVERED if to is JobState.COMPLETED else None,
        failed_task_id=TASK.new() if tid is TransitionId.J08 else None,
        monetized_destination=True if tid is TransitionId.J02 else None,
    )


@pytest.mark.parametrize("rule", [r for r in JOB_RULES if r.from_state], ids=JOB_IDS[1:])
def test_job_row_is_accepted(rule: Rule) -> None:
    for kind in rule.actor_kinds:
        assert check_job(_job_change(rule, kind)) is rule
    for kind in set(ActorKind) - rule.actor_kinds:
        with pytest.raises(InvalidTransitionError):
            check_job(_job_change(rule, kind))


TASK_STATES = [None, *TaskState]
JOB_STATES = [None, *JobState]
INVALID_TASK_PAIRS = [
    (f, t)
    for f in TASK_STATES
    for t in TaskState
    if f != t and not is_allowed_pair(EntityKind.TASK, f, t)
]
INVALID_JOB_PAIRS = [
    (f, t)
    for f in JOB_STATES
    for t in JobState
    if f != t and not is_allowed_pair(EntityKind.JOB, f, t)
]


@pytest.mark.parametrize(("frm", "to"), INVALID_TASK_PAIRS)
def test_invalid_task_pair_is_rejected(frm: TaskState | None, to: TaskState) -> None:
    for tid in (t for t in TransitionId if t.entity_kind is EntityKind.TASK):
        change = TaskTransition(
            task_id=TASK.new(),
            transition_id=tid,
            from_state=frm or TaskState.PENDING,
            to_state=to,
            expected_state_version=1,
            actor=ACTOR_FOR[ActorKind.AGENT],
        )
        if frm is None:
            continue  # creation is T01 only; covered by the DB insert test
        with pytest.raises(InvalidTransitionError):
            check_task(change)


@pytest.mark.parametrize(("frm", "to"), INVALID_JOB_PAIRS)
def test_invalid_job_pair_is_rejected(frm: JobState | None, to: JobState) -> None:
    if frm is None:
        return
    for tid in (t for t in TransitionId if t.entity_kind is EntityKind.JOB):
        change = JobTransition(
            job_id=JOB.new(),
            transition_id=tid,
            from_state=frm,
            to_state=to,
            expected_state_version=1,
            actor=ACTOR_FOR[ActorKind.AGENT],
        )
        with pytest.raises(InvalidTransitionError):
            check_job(change)


def test_wrong_entity_transition_id() -> None:
    rule = rule_for_pair(EntityKind.JOB, "PENDING", "VALIDATING")
    assert rule is not None
    change = _task_change(TASK_RULES[1])
    with pytest.raises(InvalidTransitionError, match="not a task"):
        check_task(replace(change, transition_id=TransitionId.J02))


@pytest.mark.parametrize(
    ("field", "value", "rule_index"),
    [
        ("wait_reason", None, 4),  # T05 without wait reason
        ("wait_reason", WaitReason.DRAIN, 4),  # T05 needs AWAITING_BUDGET
        ("wait_reason", WaitReason.DRAIN, 1),  # T02 with a wait reason
        ("next_attempt_at", None, 9),  # T10 without time
        ("reason", None, 17),  # T18 without reason
    ],
)
def test_row_conditions(field: str, value: Any, rule_index: int) -> None:
    rule = TASK_RULES[rule_index]
    change = _task_change(rule)
    with pytest.raises(InvalidTransitionError):
        check_task(replace(change, **{field: value}))


def test_job_row_conditions() -> None:
    j07 = next(r for r in JOB_RULES if r.transition_id is TransitionId.J07)
    base = _job_change(j07)
    with pytest.raises(InvalidTransitionError, match="outcome"):
        check_job(replace(base, outcome=None))
    with pytest.raises(InvalidTransitionError, match="J02"):
        check_job(replace(base, monetized_destination=True))
    j08 = next(r for r in JOB_RULES if r.transition_id is TransitionId.J08)
    with pytest.raises(InvalidTransitionError, match="J08"):
        check_job(replace(_job_change(j08), failed_task_id=None))


def test_actor_kinds_and_authority() -> None:
    assert actor_kind_of(ActorRef("agent_05")) is ActorKind.AGENT
    assert actor_kind_of(ActorRef("svc_s07")) is ActorKind.SERVICE
    assert actor_kind_of(ActorRef("sys_reaper")) is ActorKind.SYSTEM
    assert actor_kind_of(ACTOR_FOR[ActorKind.HUMAN]) is ActorKind.HUMAN
    with pytest.raises(InputInvalidError):
        actor_kind_of(ActorRef("root"))
    assert authority_of(TASK_RULES[0]) == "state_machine.T01"


R, Q, C, F = TaskState.RUNNING, TaskState.QUEUED, TaskState.CHECKPOINTED, TaskState.FAILED


@pytest.mark.parametrize(
    ("job", "tasks", "cause", "expected"),
    [
        (JobState.QUEUED, [(R, True)], TransitionId.T07, TransitionId.J05),
        (JobState.CHECKPOINTED, [(Q, True)], TransitionId.T15, TransitionId.J05),
        (JobState.CHECKPOINTED, [(Q, True)], TransitionId.T19, None),
        (
            JobState.RUNNING,
            [(C, True), (TaskState.COMPLETED, True)],
            TransitionId.T09,
            TransitionId.J06,
        ),
        (JobState.RUNNING, [(C, True), (R, True)], TransitionId.T09, None),
        (
            JobState.RUNNING,
            [(TaskState.COMPLETED, True), (TaskState.PENDING, False)],
            TransitionId.T08,
            TransitionId.J07,
        ),
        (
            JobState.RUNNING,
            [(TaskState.COMPLETED, True), (TaskState.CANCELLED, True)],
            TransitionId.T19,
            TransitionId.J07,
        ),
        (JobState.RUNNING, [(TaskState.CANCELLED, True)], TransitionId.T19, None),
        (
            JobState.RUNNING,
            [(F, True), (TaskState.COMPLETED, True)],
            TransitionId.T11,
            TransitionId.J08,
        ),
        (JobState.CHECKPOINTED, [(F, True)], TransitionId.T16, TransitionId.J08),
        (JobState.RUNNING, [(F, False), (R, True)], TransitionId.T11, None),
        (JobState.FAILED, [(TaskState.DEAD_LETTER, True)], TransitionId.T14, TransitionId.J09),
        (JobState.FAILED, [(TaskState.DEAD_LETTER, True)], None, None),
        (JobState.DEAD_LETTER, [(Q, True)], TransitionId.T17, TransitionId.J10),
        (JobState.DEAD_LETTER, [(Q, True)], None, None),
        (JobState.COMPLETED, [(TaskState.COMPLETED, True)], TransitionId.T08, None),
        (JobState.QUEUED, [(Q, True)], TransitionId.T03, None),
    ],
)
def test_derive_job(
    job: JobState,
    tasks: list[tuple[TaskState, bool]],
    cause: TransitionId | None,
    expected: TransitionId | None,
) -> None:
    result = derive_job(job, [TaskView(s, r) for s, r in tasks], cause)
    assert (result.transition_id if result else None) is expected
    if result is not None:
        assert rule_for_pair(EntityKind.JOB, job, result.to_state) is not None
