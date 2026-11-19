# mypy: disable-error-code="arg-type,attr-defined,unused-ignore,var-annotated"
# mypy: disable-error-code="index,no-untyped-call,misc,union-attr"
# (throw-away dry-run fixtures feed fakes and dataset dicts into typed APIs)
"""Common pieces of the dry-run stage executors."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from amw_core.contracts import ContextRef, TaskInput, TaskOutput
from amw_core.enums import Priority
from amw_orchestrator.executor import StageCall
from amw_orchestrator.metering import Meter
from tests.dryrun.kit import Blobs, WallClock


@dataclass
class World:
    """Everything shared by the stage executors of one dry run."""

    blobs: Blobs
    meter: Meter
    clock: WallClock
    scratch: Path
    render_scale: str = "tiny"
    """``tiny`` (CI) or ``modest`` (the downloadable sample)."""
    extras: dict[str, Any] = field(default_factory=dict)


def task_input(
    call: StageCall,
    agent_id: str,
    schema: str,
    data: Mapping[str, Any],
    refs: Sequence[Mapping[str, Any]] = (),
    version: str = "1.0.0",
) -> TaskInput:
    job = call.job
    return TaskInput(
        org_id=job.org_id,
        job_id=job.job_id,
        task_id=call.task_id,
        project_id=job.project_id,
        channel_id=job.channel_id,
        agent_id=agent_id,
        source_agent="agent_01",
        priority=Priority.NORMAL,
        deadline=None,
        context_refs=tuple(ContextRef.model_validate(r) for r in refs),
        resource_budget=call.resource_budget,
        payload={  # type: ignore[arg-type]
            "payload_schema": schema,
            "payload_schema_version": version,
            "data": dict(data),
        },
        correlation_id=job.correlation_id,
        idempotency_key=call.idempotency_key,
        retry_count=call.attempt_no - 1,
        schema_version="1.0.0",
    )


def upstream(call: StageCall, stage_id: str) -> TaskOutput:
    try:
        return call.upstream[stage_id]
    except KeyError:
        raise KeyError(f"{call.stage.stage_id}: upstream {stage_id} has no output") from None


def upstream_data(call: StageCall, stage_id: str) -> dict[str, Any]:
    out = upstream(call, stage_id)
    assert out.payload is not None
    return dict(out.payload.data)
