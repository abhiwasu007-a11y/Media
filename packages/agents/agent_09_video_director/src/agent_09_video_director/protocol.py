"""VideoDirector Protocol (blueprint 9): the task entry the AI worker calls."""

from datetime import datetime
from typing import Protocol

from agent_09_video_director.output import build_task_output
from agent_09_video_director.persistence import persist_plan
from agent_09_video_director.step import ShotPlanRequest, ShotPlanStep
from amw_core.contracts.task_output import TaskOutput
from amw_core.interfaces.storage import BlobStorage
from amw_core.interfaces.tenancy_context import TenantContext


class VideoDirector(Protocol):
    def run(
        self,
        req: ShotPlanRequest,
        ctx: TenantContext,
        *,
        task_path: str,
        now: datetime,
        currency: str,
    ) -> TaskOutput: ...


class ShotPlanTask:
    """``agent_09.shot_plan``: run the step, write the plan blob once, build the Task Output."""

    def __init__(self, step: ShotPlanStep, storage: BlobStorage) -> None:
        self._step, self._storage = step, storage

    def run(
        self,
        req: ShotPlanRequest,
        ctx: TenantContext,
        *,
        task_path: str,
        now: datetime,
        currency: str,
    ) -> TaskOutput:
        result = self._step.run(req)
        ref = persist_plan(self._storage, ctx, result.plan, task_path=task_path)
        return build_task_output(result, req.script, ref, now=now, duration_ms=0, currency=currency)
