"""Regression tests of the code fixes made by the second dry run (PLUMBING TEST - NOT QUALITY)."""

from pathlib import Path

import pytest

from amw_core.contracts import TaskOutput
from amw_core.ids import ATTEMPT, JOB, ORG, TASK
from amw_core.interfaces import TenantContext
from amw_core.storage.local import LocalDiskStorage
from amw_core.tenancy.storage_paths import task_artifact_uri
from amw_orchestrator.task_io import TaskIo
from tests.orchestrator.world import ok_output

pytestmark = pytest.mark.unit


def _output(uri: str) -> TaskOutput:
    base = ok_output("agent_10.render.output", {"render_id": "rnd_x"}).model_dump(
        mode="json", by_alias=True
    )
    base["output_refs"] = [
        {
            "uri": uri,
            "kind": "VIDEO",
            "sha256": "a" * 64,
            "size_bytes": 1,
            "media_type": "video/mp4",
        }
    ]
    return TaskOutput.model_validate(base)


def test_payload_copy_of_an_output_whose_files_are_not_task_artifacts(tmp_path: Path) -> None:
    """CCR-286: Agent 10 render outputs name only ``renders/`` files; the verbatim payload copy
    falls back to the content-addressed ``cache/agent_01/payload-<sha>.json`` (it raised
    ``IndexError``)."""
    org, job = str(ORG.new()), str(JOB.new())
    io = TaskIo(LocalDiskStorage(tmp_path))
    ctx = TenantContext(org, "agent_01", None)  # type: ignore[arg-type]
    out = _output(f"amw-blob://{org}/jobs/{job}/renders/rnd_x.mp4")
    first = io.put_payload(ctx, job, out)
    assert f"/jobs/{job}/cache/agent_01/payload-" in first.uri
    again = io.put_payload(ctx, job, out)  # replay: the same blob, nothing rewritten
    assert again == first
    assert io.get_json(ctx, first.uri, first.sha256) == {"render_id": "rnd_x"}


def test_payload_copy_of_an_output_with_a_task_artifact_stays_next_to_it(tmp_path: Path) -> None:
    org, job = str(ORG.new()), str(JOB.new())
    task, att = str(TASK.new()), str(ATTEMPT.new())
    ref = task_artifact_uri(org, job, task, att, "doc.json")  # type: ignore[arg-type]
    io = TaskIo(LocalDiskStorage(tmp_path))
    ctx = TenantContext(org, "agent_01", None)  # type: ignore[arg-type]
    stored = io.put_payload(ctx, job, _output(ref))
    assert stored.uri == task_artifact_uri(org, job, task, att, "payload.json")  # type: ignore[arg-type]
