"""Execution context guard and scratch space of both stages (19.1 layers 1, 3).

The context type is ``amw_core.exec_context.ExecContext`` (CCR-203); there is no agent-local one."""

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from amw_core.contracts.task_input import TaskInput
from amw_core.errors import TenantMismatchError
from amw_core.exec_context import ExecContext

AGENT_ID = "agent_07"


def check_ctx(task_input: TaskInput, ctx: ExecContext) -> None:
    """The context and the Task Input must name the same agent, org, job and task (19.1 layer 1,
    V1 TenantScope; the same rule as agent_04). Anything else is ``TENANT_MISMATCH`` before any
    step runs."""
    if task_input.agent_id != AGENT_ID:
        raise TenantMismatchError("task is not addressed to agent_07")
    if (
        str(ctx.org_id) != task_input.org_id
        or str(ctx.job_id) != task_input.job_id
        or str(ctx.task_id) != task_input.task_id
    ):
        raise TenantMismatchError("execution context does not match the Task Input")


@contextmanager
def scratch_dir(root: Path, ctx: ExecContext) -> Iterator[Path]:
    """Per-org, per-task scratch space, mode 0700, wiped at attempt end and on drain (19.1 layer 3).
    FFmpeg is given absolute paths inside this directory only."""
    path = root / str(ctx.org_id) / str(ctx.task_id) / str(ctx.attempt_id)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        yield path.resolve()
    finally:
        shutil.rmtree(path, ignore_errors=True)
