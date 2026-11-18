"""State machine (03 section 11): transition tables, checks, job derivation.

Persistence with optimistic locking and the audit row of every transition is the job store's
(``amw_core.job_store``); this package decides what is allowed.
"""

from amw_core.state_machine.machine import (
    Derivation,
    TaskView,
    actor_kind_of,
    authority_of,
    check_job,
    check_task,
    derive_job,
)
from amw_core.state_machine.rules import (
    ALL_RULES,
    JOB_RULES,
    TASK_REJECTED_EVENT,
    TASK_RULES,
    Rule,
    find_rule,
    is_allowed_pair,
    rule_for_pair,
)

__all__ = [
    "ALL_RULES",
    "JOB_RULES",
    "TASK_REJECTED_EVENT",
    "TASK_RULES",
    "Derivation",
    "Rule",
    "TaskView",
    "actor_kind_of",
    "authority_of",
    "check_job",
    "check_task",
    "derive_job",
    "find_rule",
    "is_allowed_pair",
    "rule_for_pair",
]
