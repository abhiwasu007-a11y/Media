# ruff: noqa: PT018
"""PASS6-D (CCR-202, CCR-203, CCR-208): the one worker entry point ``run(task_input, ctx)``.

Task Input in, Task Output out for both task types, over the real ``LocalDiskStorage`` (the
write-once and ``jobs`` sub-path rules of 03 section 8 are enforced by the backend, not faked).
"""

import dataclasses
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from agent_05_scriptwriter import (
    ScriptDraftStage,
    ScriptDraftStep,
    ScriptRepository,
    ShortsAdaptationStage,
    ShortsAdaptationStep,
)
from agent_05_scriptwriter.contracts import ScriptDocument
from agent_05_scriptwriter.errors import CrossTenantRef
from agent_05_scriptwriter.persist.script_repository import tenant_context
from agent_05_scriptwriter.protocols import SavedScript, StepContext
from agent_05_scriptwriter.steps.common import ResolvedInputs
from amw_core import ids
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import TaskOutput
from amw_core.contracts.validation import validate_task_output
from amw_core.enums import OutputRefKind, OutputStatus
from amw_core.errors import CorruptedOutputError
from amw_core.exec_context import ExecContext
from amw_core.interfaces import TaskWorker
from amw_core.interfaces.storage import BlobUri
from amw_core.storage.local import LocalDiskStorage
from amw_core.tenancy.storage_paths import check_jobs_subpath
from tests.agents.agent_05_scriptwriter import support as sp
from tests.agents.agent_05_scriptwriter.test_shorts import parent_script, shorts_input

pytestmark = pytest.mark.contract


class Clock:
    def __init__(self) -> None:
        self._mono = 0

    def now(self) -> datetime:
        return datetime(2030, 1, 1, tzinfo=UTC)

    def monotonic_ms(self) -> int:
        self._mono += 5
        return self._mono


@dataclass
class Rows:
    """In-memory ``ScriptRowPort`` (the real one is a tenancy transaction in the worker)."""

    rows: dict[tuple[str, str, int], SavedScript] = field(default_factory=dict)
    fail_inserts: int = 0

    def latest_version(self, ctx: StepContext, language: str) -> int:
        return max((k[2] for k in self.rows if k[:2] == (ctx.job_id, language)), default=0)

    def find(self, ctx: StepContext, language: str, version: int) -> SavedScript | None:
        return self.rows.get((ctx.job_id, language, version))

    def insert(self, ctx: StepContext, saved: SavedScript, **kw: Any) -> None:
        if self.fail_inserts:
            self.fail_inserts -= 1
            raise RuntimeError("row insert failed")
        self.rows[(ctx.job_id, kw["language"], saved.version)] = saved


class Resolver:
    def __init__(self, **over: Any) -> None:
        self.over = over
        self.calls = 0
        self.error: Exception | None = None

    def resolve(self, ctx: StepContext, task_input: TaskInput, data: Any) -> ResolvedInputs:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return sp.make_resolved(ctx, **self.over)


@dataclass
class World:
    storage: LocalDiskStorage
    rows: Rows
    st: sp.MemoryState
    llm: sp.ScriptedLlm
    resolver: Resolver
    draft: ScriptDraftStage
    shorts: ShortsAdaptationStage


def build_world(
    tmp_path: Path, script: list[Any] | None = None, *, citations: Any = None, **res: Any
) -> World:
    storage = LocalDiskStorage(tmp_path)
    rows = Rows()
    st = sp.MemoryState()
    ports = sp.make_ports(st)
    ports.scripts = ScriptRepository(storage, rows)
    llm = sp.ScriptedLlm(
        script if script is not None else ["VALID_PLAN", "VALID_SECTIONS"], 2, citations
    )
    resolver = Resolver(**res)
    clock = Clock()
    draft_step = ScriptDraftStep(llm, ports, sp.make_settings(), sp.prompts(), sp.scanners_for)
    shorts_step = ShortsAdaptationStep(
        llm, ports, sp.make_settings(), sp.prompts(), sp.scanners_for
    )
    return World(
        storage,
        rows,
        st,
        llm,
        resolver,
        ScriptDraftStage(draft_step, resolver, storage, clock),
        ShortsAdaptationStage(shorts_step, resolver, storage, clock),
    )


def task_input(
    data: dict[str, Any] | None = None,
    *,
    schema: str = "agent_05.script_draft.input",
    version: str = "1.0.0",
    **over: Any,
) -> TaskInput:
    data = data if data is not None else sp.make_input().model_dump(mode="json")
    doc: dict[str, Any] = {
        "org_id": sp._Ids.org,
        "job_id": sp._Ids.job,
        "task_id": ids.TASK.new(),
        "project_id": sp._Ids.project,
        "channel_id": sp._Ids.channel,
        "agent_id": "agent_05",
        "source_agent": "agent_01",
        "priority": "NORMAL",
        "deadline": None,
        "context_refs": [],
        "resource_budget": {
            "max_cost_micros": 10_000_000,
            "currency": "USD",
            "max_wall_ms": 600000,
            "max_llm_calls": 30,
        },
        "payload": {
            "payload_schema": schema,
            "payload_schema_version": version,
            "data": data,
        },
        "correlation_id": ids.CORRELATION.new(),
        "idempotency_key": "idk_" + "a" * 64,
        "retry_count": 0,
        "schema_version": "1.0.0",
    }
    doc.update(over)
    return TaskInput.model_validate(doc)


def exec_ctx(ti: TaskInput, stage: str = "s05_script") -> ExecContext:
    return ExecContext.from_task_input(
        ti,
        ids.ATTEMPT.new(),
        "agent_05",
        envelope_org_id=ti.org_id,
        stage_id=stage,
        iteration=0,
    )


def valid(out: TaskOutput) -> TaskOutput:
    validate_task_output(out.model_dump(mode="json"), version="1.0.0")
    return out


def read_doc(w: World, out: TaskOutput) -> dict[str, Any]:
    ref = out.output_refs[0]
    raw = b"".join(w.storage.get(tenant_for(), BlobUri(ref.uri), ref.sha256))
    return json.loads(raw)  # type: ignore[no-any-return]


def tenant_for() -> Any:
    return tenant_context(sp.make_ctx())


# ---------------------------------------------------------------------------- conformance
def test_stages_conform_to_task_worker(tmp_path: Path) -> None:
    w = build_world(tmp_path)
    assert isinstance(w.draft, TaskWorker) and isinstance(w.shorts, TaskWorker)


# ---------------------------------------------------------------------------- script_draft
def test_script_draft_task_input_in_task_output_out(tmp_path: Path) -> None:
    w = build_world(tmp_path)
    ti = task_input()
    ctx = exec_ctx(ti)
    out = valid(w.draft.run(ti, ctx))
    assert out.status is OutputStatus.SUCCEEDED, out.error
    assert out.payload is not None
    assert out.payload.payload_schema == "agent_05.script_draft.output"
    assert len(w.llm.requests) == 3  # plan + 2 sections
    (ref,) = out.output_refs
    assert ref.kind is OutputRefKind.SCRIPT
    # the document is a task artifact of THIS attempt (CCR-208), accepted by the 03 section 8 check
    assert ref.uri.endswith(f"/tasks/{ti.task_id}/attempts/{ctx.attempt_id}/artifacts/script.json")
    check_jobs_subpath(ref.uri.split("/jobs/", 1)[1])
    assert w.rows.find(sp.make_ctx(), "en-IN", 1) is not None
    on_disk = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert len(on_disk) == 1 and on_disk[0].as_posix().endswith("/artifacts/script.json")


def test_hook_and_disclaimer_scenes_carry_hook_and_null_and_are_not_sections(
    tmp_path: Path,
) -> None:
    """agent_05 section 8.3 values unchanged (CCR-202): ``"hook"`` / ``null``, never in sections."""
    w = build_world(tmp_path)
    ti = task_input()
    out = w.draft.run(ti, exec_ctx(ti))
    assert out.status is OutputStatus.SUCCEEDED, out.error
    doc = ScriptDocument.model_validate(read_doc(w, out))
    section_ids = [s.section_id for s in doc.sections]
    assert section_ids and "hook" not in section_ids and None not in section_ids
    hook = [s for s in doc.scenes if s.scene_id.startswith("hook.")]
    disc = [s for s in doc.scenes if s.scene_id.startswith("disc.")]
    assert hook and disc
    assert all(s.section_id == "hook" for s in hook)
    assert all(s.section_id is None for s in disc)
    assert {s.section_id for s in doc.segments if s.kind.startswith("HOOK_")} == {"hook"}
    assert {s.section_id for s in doc.segments if s.kind == "DISCLAIMER"} == {None}
    # every scene outside the sections lies before the first section's first scene or after the last
    assert [c.section_id for c in doc.chapters] == section_ids


def test_replay_of_the_same_task_returns_the_stored_output(tmp_path: Path) -> None:
    w = build_world(tmp_path)
    ti = task_input()
    first = w.draft.run(ti, exec_ctx(ti))
    calls = len(w.llm.requests)
    again = w.draft.run(ti, exec_ctx(ti))
    assert again.status is OutputStatus.SUCCEEDED and len(w.llm.requests) == calls
    assert again.output_refs == first.output_refs


def test_step_failure_is_returned_as_a_failed_task_output(tmp_path: Path) -> None:
    w = build_world(tmp_path, ["INVALID_JSON", "INVALID_JSON"])
    ti = task_input()
    out = valid(w.draft.run(ti, exec_ctx(ti)))
    assert out.status is OutputStatus.FAILED
    assert out.error is not None and out.error.code == "AGENT.INVALID_JSON"
    assert out.output_refs == ()
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]


def test_unset_llm_call_cap_makes_no_paid_call(tmp_path: Path) -> None:
    w = build_world(tmp_path)
    ti = task_input(
        resource_budget={"max_cost_micros": 10_000_000, "currency": "USD", "max_wall_ms": 600000}
    )
    out = valid(w.draft.run(ti, exec_ctx(ti)))
    assert out.error is not None and out.error.code == "AGENT.LOOP_CAP_EXCEEDED"
    assert not w.llm.requests


# ---------------------------------------------------------------------------- shorts
def test_shorts_adaptation_task_input_in_task_output_out(tmp_path: Path) -> None:
    doc, sha, cites, _ = parent_script()
    ctx0 = sp.make_ctx()
    doc = doc.model_copy(update={"channel_id": ctx0.channel_id})
    w = build_world(
        tmp_path,
        ["VALID_CUT"],
        citations=cites,
        parent_script=doc,
        parent_script_sha256=sha,
        parent_claims_cleared=True,
    )
    data = shorts_input(doc, sha).model_dump(mode="json")
    ti = task_input(data, schema="agent_05.shorts_adaptation.input")
    ctx = exec_ctx(ti, "s05_shorts")
    out = valid(w.shorts.run(ti, ctx))
    assert out.status is OutputStatus.SUCCEEDED, out.error
    assert out.payload is not None
    assert out.payload.payload_schema == "agent_05.shorts_adaptation.output"
    (ref,) = out.output_refs
    assert ref.uri.endswith(f"/attempts/{ctx.attempt_id}/artifacts/script.json")
    check_jobs_subpath(ref.uri.split("/jobs/", 1)[1])
    cut = read_doc(w, out)
    assert cut["aspect_ratio"] == "9:16" and cut["sections"] == []
    # a 9:16 cut has no sections: every segment's section_id is null (agent_05 section 8.3)
    assert {s["section_id"] for s in cut["segments"]} == {None}
    assert len(w.llm.requests) == 1


# ---------------------------------------------------------------------------- guards
def _rejected(out: TaskOutput, code: str) -> None:
    valid(out)
    assert out.status is OutputStatus.REJECTED
    assert out.error is not None and out.error.code == code


@pytest.mark.parametrize("what", ["task", "job", "org", "channel", "channel_none"])
def test_context_disagreeing_with_the_task_input_is_refused(tmp_path: Path, what: str) -> None:
    w = build_world(tmp_path)
    ti = task_input()
    ctx = exec_ctx(ti)
    if what == "task":
        ctx = dataclasses.replace(ctx, task_id=ids.TASK.new())
    elif what == "job":
        ctx = dataclasses.replace(ctx, job_id=ids.JOB.new())
    elif what == "org":
        ctx = dataclasses.replace(ctx, tenant=dataclasses.replace(ctx.tenant, org_id=ids.ORG.new()))
    elif what == "channel":
        ctx = dataclasses.replace(ctx, channel_id=ids.CHANNEL.new())
    else:
        ctx = dataclasses.replace(ctx, channel_id=None)
    _rejected(w.draft.run(ti, ctx), "PERMANENT.TENANT_MISMATCH")
    assert not w.llm.requests and w.resolver.calls == 0


def test_task_without_channel_is_input_invalid_with_a_violation(tmp_path: Path) -> None:
    w = build_world(tmp_path)
    ti = task_input(channel_id=None)
    out = w.draft.run(ti, exec_ctx(ti))
    _rejected(out, "PERMANENT.INPUT_INVALID")
    assert out.error is not None and out.error.details.violations
    assert out.error.details.violations[0].keyword == "CHANNEL_MISSING"
    assert not w.llm.requests


def test_other_agent_or_other_payload_schema_is_unsupported(tmp_path: Path) -> None:
    w = build_world(tmp_path)
    task = ids.TASK.new()
    ti = task_input(agent_id="agent_04", task_id=task)
    _rejected(w.draft.run(ti, exec_ctx(task_input(task_id=task))), "PERMANENT.UNSUPPORTED_TASK")
    ti = task_input()
    # a draft payload sent to the shorts entry point
    _rejected(w.shorts.run(ti, exec_ctx(ti)), "PERMANENT.UNSUPPORTED_TASK")
    assert w.resolver.calls == 0


def test_unknown_major_payload_version_is_refused(tmp_path: Path) -> None:
    w = build_world(tmp_path)
    ti = task_input(version="2.0.0")
    _rejected(w.draft.run(ti, exec_ctx(ti)), "PERMANENT.SCHEMA_VERSION_UNSUPPORTED")


def test_payload_failing_the_schema_lists_violations(tmp_path: Path) -> None:
    w = build_world(tmp_path)
    data = sp.make_input().model_dump(mode="json")
    data["language"] = "xx-XX"
    del data["topic"]
    ti = task_input(data)
    out = w.draft.run(ti, exec_ctx(ti))
    _rejected(out, "PERMANENT.SCHEMA_INVALID")
    assert out.error is not None
    paths = {v.path for v in out.error.details.violations or ()}
    assert "/payload/data/topic" in paths and "/payload/data/language" in paths
    assert not w.llm.requests and w.resolver.calls == 0


def test_payload_by_reference_is_read_and_hash_verified(tmp_path: Path) -> None:
    w = build_world(tmp_path)
    body = json.dumps(sp.make_input().model_dump(mode="json")).encode()
    ti0 = task_input()
    uri = BlobUri(
        f"amw-blob://{sp._Ids.org}/jobs/{sp._Ids.job}/tasks/{ti0.task_id}/attempts/"
        f"{ids.ATTEMPT.new()}/artifacts/input_data.json"
    )
    ctx0 = exec_ctx(ti0)
    info = w.storage.put(ctx0.tenant, uri, BytesIO(body))
    payload = {
        "payload_schema": "agent_05.script_draft.input",
        "payload_schema_version": "1.0.0",
        "data_ref": str(uri),
        "data_sha256": info.sha256,
    }
    ti = task_input(payload=payload)
    assert w.draft.run(ti, exec_ctx(ti)).status is OutputStatus.SUCCEEDED
    bad = task_input(payload={**payload, "data_sha256": "0" * 64})
    out = valid(w.draft.run(bad, exec_ctx(bad)))
    assert out.status is OutputStatus.FAILED and out.error is not None
    assert out.error.code == "AGENT.CORRUPTED_OUTPUT"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (b"this is not json", "PAYLOAD_NOT_JSON"),
        (b"", "PAYLOAD_NOT_JSON"),
        (b"\xff\xfe\x00{", "PAYLOAD_NOT_JSON"),
        (b"[" * 100000, "PAYLOAD_NOT_JSON"),
        (b'{"unexpected": 1}', "missing"),
        (b"[1, 2, 3]", "model_type"),
    ],
    ids=["non_json", "empty", "not_utf8", "too_deep", "wrong_shape_object", "wrong_shape_list"],
)
def test_hash_valid_but_unusable_blob_is_returned_as_schema_invalid(
    tmp_path: Path, body: bytes, code: str
) -> None:
    w = build_world(tmp_path)
    ti0 = task_input()
    uri = BlobUri(
        f"amw-blob://{sp._Ids.org}/jobs/{sp._Ids.job}/tasks/{ti0.task_id}/attempts/"
        f"{ids.ATTEMPT.new()}/artifacts/input_data.json"
    )
    info = w.storage.put(exec_ctx(ti0).tenant, uri, BytesIO(body))
    ti = task_input(
        payload={
            "payload_schema": "agent_05.script_draft.input",
            "payload_schema_version": "1.0.0",
            "data_ref": str(uri),
            "data_sha256": info.sha256,
        }
    )
    out = w.draft.run(ti, exec_ctx(ti))
    _rejected(out, "PERMANENT.SCHEMA_INVALID")
    assert out.error is not None
    assert code in {v.keyword for v in out.error.details.violations or ()}
    assert not w.llm.requests and w.resolver.calls == 0


def test_cross_tenant_reference_from_the_resolver_is_rejected(tmp_path: Path) -> None:
    w = build_world(tmp_path)
    w.resolver.error = CrossTenantRef("reference belongs to another tenant")
    ti = task_input()
    _rejected(w.draft.run(ti, exec_ctx(ti)), "PERMANENT.CROSS_TENANT_REF")
    assert not w.llm.requests


# ---------------------------------------------------------------------------- ScriptStore adapter
def _save(repo: ScriptRepository, ctx: StepContext, content: bytes, sha: str) -> SavedScript:
    return repo.save(
        ctx,
        script_id=ids.new_id(ids.Prefix.SCRIPT),
        version=1,
        iteration=0,
        language="en-IN",
        content=content,
        sha256=sha,
        parent_script_id=None,
        segment_count=1,
        word_count=1,
        est_duration_ms=None,
        prompt_id="p",
    )


def _sha(b: bytes) -> str:
    import hashlib

    return hashlib.sha256(b).hexdigest()


def test_repository_writes_a_task_artifact_and_replays_idempotently(tmp_path: Path) -> None:
    storage, rows = LocalDiskStorage(tmp_path), Rows()
    repo = ScriptRepository(storage, rows)
    ctx = sp.make_ctx()
    assert repo.next_version(ctx, "en-IN") == 1
    saved = _save(repo, ctx, b"{}", _sha(b"{}"))
    assert saved.inserted and saved.uri.endswith(
        f"/attempts/{ctx.attempt_id}/artifacts/script.json"
    )
    assert repo.read_blob(ctx, saved.uri, saved.sha256) == b"{}"
    assert repo.next_version(ctx, "en-IN") == 2
    again = _save(repo, sp.make_ctx(ctx.task_id), b"{}", _sha(b"{}"))  # a later attempt
    assert not again.inserted and again.uri == saved.uri
    with pytest.raises(CorruptedOutputError):
        _save(repo, ctx, b"[]", _sha(b"[]"))


def test_repository_resumes_after_a_crash_between_blob_and_row(tmp_path: Path) -> None:
    repo = ScriptRepository(LocalDiskStorage(tmp_path), rows := Rows(fail_inserts=1))
    ctx = sp.make_ctx()
    with pytest.raises(RuntimeError):
        _save(repo, ctx, b"{}", _sha(b"{}"))
    saved = _save(repo, ctx, b"{}", _sha(b"{}"))  # same attempt: the write-once blob is reused
    assert saved.inserted and len(rows.rows) == 1
    # the blob under that path has other content: refused, not overwritten
    other = ScriptRepository(LocalDiskStorage(tmp_path), Rows())
    with pytest.raises(CorruptedOutputError):
        _save(other, ctx, b"[]", _sha(b"[]"))


def test_repository_refuses_another_tenants_blob(tmp_path: Path) -> None:
    repo = ScriptRepository(LocalDiskStorage(tmp_path), Rows())
    ctx = sp.make_ctx()
    saved = _save(repo, ctx, b"{}", _sha(b"{}"))
    foreign = dataclasses.replace(ctx, org_id=ids.ORG.new())
    from amw_core.errors import CrossTenantRefError

    with pytest.raises(CrossTenantRefError):
        repo.read_blob(foreign, saved.uri, saved.sha256)
