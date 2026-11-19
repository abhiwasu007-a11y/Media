"""PASS6-A1 (CCR-203, CCR-208, CCR-210): shared worker interface, ExecContext stage/iteration,
violation helper and the 03 section 8 rule 5 storage paths enforced by the real backend."""

import io
from datetime import UTC, datetime
from pathlib import Path

import pytest

from amw_core import contracts
from amw_core.contracts import TaskInput, TaskOutput
from amw_core.errors import InputInvalidError, SchemaInvalidError, TenantMismatchError
from amw_core.exec_context import ExecContext
from amw_core.ids import ATTEMPT, JOB, ORG, PUBLICATION, TASK, ActorRef
from amw_core.interfaces import TaskWorker
from amw_core.interfaces.storage import BlobUri
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.storage import LocalDiskStorage
from amw_core.tenancy import storage_paths as sp
from tests.contract.examples import COR
from tests.contract.examples import task_input as task_input_doc

pytestmark = pytest.mark.unit
NOW = datetime(2026, 1, 1, tzinfo=UTC)


# --- TaskWorker (CCR-203) -----------------------------------------------------------------------
class _Worker:
    def run(self, task_input: TaskInput, ctx: ExecContext) -> TaskOutput:
        raise NotImplementedError


class _NotAWorker:
    def execute(self, task_input: TaskInput, ctx: ExecContext) -> TaskOutput:
        raise NotImplementedError


def test_task_worker_protocol() -> None:
    assert isinstance(_Worker(), TaskWorker)
    assert not isinstance(_NotAWorker(), TaskWorker)


def _ti() -> TaskInput:
    return TaskInput.model_validate(task_input_doc() | {"agent_id": "agent_07"})


def test_exec_context_carries_stage_and_iteration() -> None:
    ti = _ti()
    att = ATTEMPT.new()
    ctx = ExecContext.from_task_input(
        ti, att, "agent_07", envelope_org_id=ti.org_id, stage_id="voice_production", iteration=2
    )
    assert (ctx.stage_id, ctx.iteration) == ("voice_production", 2)
    default = ExecContext.from_task_input(ti, att, "agent_07", envelope_org_id=ti.org_id)
    assert (default.stage_id, default.iteration) == (None, 0)


@pytest.mark.parametrize(
    ("stage_id", "iteration"),
    [("Bad Stage", 0), ("x", 0), ("a" * 33, 0), ("voice", -1), ("voice", True)],
)
def test_exec_context_refuses_malformed_stage_or_iteration(stage_id: str, iteration: int) -> None:
    ti = _ti()
    with pytest.raises(InputInvalidError):
        ExecContext.from_task_input(
            ti,
            ATTEMPT.new(),
            "agent_07",
            envelope_org_id=ti.org_id,
            stage_id=stage_id,
            iteration=iteration,
        )


def test_exec_context_tenant_checks_still_run_first() -> None:
    ti = _ti()
    with pytest.raises(TenantMismatchError):
        ExecContext.from_task_input(
            ti, ATTEMPT.new(), "agent_08", envelope_org_id=ti.org_id, stage_id="voice"
        )


# --- violations (CCR-210) -----------------------------------------------------------------------
def _error_doc(details: dict[str, object]) -> dict[str, object]:
    exc = SchemaInvalidError("rejected", details=details)
    obj = contracts.error_object_from_exception(
        exc, actor="agent_09", attempt_no=1, occurred_at=NOW, correlation_id=COR
    )
    doc = obj.to_doc()
    assert contracts.validate_error(doc) == obj  # valid against amw.error 1.0.0
    return doc


def test_bare_string_violations_do_not_raise_and_are_converted() -> None:
    doc = _error_doc({"violations": ["SCRIPT_HASH_MISMATCH", "TEMPLATE_MISMATCH:ov03"]})
    assert doc["details"]["violations"] == [  # type: ignore[index]
        {"path": "", "keyword": "SCRIPT_HASH_MISMATCH", "message": "SCRIPT_HASH_MISMATCH"},
        {"path": "", "keyword": "TEMPLATE_MISMATCH:ov03", "message": "TEMPLATE_MISMATCH:ov03"},
    ]


def test_helper_built_violations_are_valid() -> None:
    item = contracts.violation("SCRIPT_HASH_MISMATCH", "/script_sha256", "hash differs")
    assert (item.path, item.keyword, item.message) == (
        "/script_sha256",
        "SCRIPT_HASH_MISMATCH",
        "hash differs",
    )
    assert contracts.violation("X_CODE").message == "X_CODE"
    assert len(contracts.violation("X_CODE", message="m" * 900).message) == 500
    doc = _error_doc({"violations": [item, contracts.violation("OTHER")]})
    assert [v["keyword"] for v in doc["details"]["violations"]] == [  # type: ignore[index]
        "SCRIPT_HASH_MISMATCH",
        "OTHER",
    ]


def test_odd_violation_shapes_never_break_error_building() -> None:
    doc = _error_doc(
        {"violations": [{"keyword": "K"}, {"path": "/a", "keyword": "B", "message": "m"}, 7]}
    )
    kinds = [v["keyword"] for v in doc["details"]["violations"]]  # type: ignore[index]
    assert kinds == ["K", "B", "7"]
    assert _error_doc({"violations": "ONLY_ONE"})["details"]["violations"][0]["keyword"] == (  # type: ignore[index]
        "ONLY_ONE"
    )
    many = _error_doc({"violations": [f"C{i}" for i in range(300)]})
    assert len(many["details"]["violations"]) == 200  # type: ignore[index]


# --- storage paths (CCR-208) --------------------------------------------------------------------
A = TenantContext(ORG.new(), ActorRef("agent_11"))
J, T, AT, P = JOB.new(), TASK.new(), ATTEMPT.new(), PUBLICATION.new()


@pytest.fixture
def store(tmp_path: Path) -> LocalDiskStorage:
    return LocalDiskStorage(tmp_path / "root")


def _builders() -> list[str]:
    org = A.org_id
    return [
        sp.task_artifact_uri(org, J, T, AT, "shot_plan.json"),
        sp.task_artifact_uri(org, J, T, AT, "frames/f001.png"),
        sp.task_io_uri(org, J, T, AT, "input.json"),
        sp.task_io_uri(org, J, T, AT, "output.json"),
        sp.checkpoint_uri(org, J, T, f"{AT}/step1.json"),
        sp.job_cache_uri(org, J, "agent_07", "clip-" + "a" * 64 + ".wav"),
        sp.render_uri(org, J, "master.mp4"),
        sp.delivery_uri(org, J, P, "bundle/manifest.json"),
    ]


def test_every_builder_uri_is_accepted_by_the_real_backend(store: LocalDiskStorage) -> None:
    uris = _builders()
    assert len(set(uris)) == len(uris)
    for uri in uris:
        info = store.put(A, BlobUri(uri), io.BytesIO(b"x"))
        assert info.uri == uri
        assert store.head(A, BlobUri(uri)).exists


@pytest.mark.security
@pytest.mark.parametrize(
    "tail",
    [
        "agent_11/x.json",  # jobs/<job>/agent_11/x
        "s07_voice/x.wav",
        "s07_master/t/step.json",
        "checkpoints/x.json",  # checkpoint without a task segment
        "tasks/{T}/attempts/{AT}/x.json",  # not input/output/artifacts
        "tasks/{T}/attempts/{AT}/artifacts",  # no name
        "tasks/{T}/attempts/{AT}/input.json/more",
        "tasks/{T}/attempts/{AT}/output.json.bak",
        "tasks/{T}/x.json",
        "tasks/{AT}/attempts/{AT}/output.json",  # attempt ID where a task ID belongs
        "checkpoints/{AT}/x.json",
        "cache/Agent07/x",  # bad agent segment
        "cache/agent_07",  # no name
        "deliveries/{T}/x",  # not a publication ID
        "deliveries/{P}",  # no file
        "renders",
        "x.json",
    ],
)
def test_backend_refuses_non_conforming_jobs_subpaths(store: LocalDiskStorage, tail: str) -> None:
    path = f"{J}/" + tail.format(T=T, AT=AT, P=P)
    with pytest.raises(InputInvalidError):
        store.put(A, BlobUri(f"amw-blob://{A.org_id}/jobs/{path}"), io.BytesIO(b"x"))


@pytest.mark.security
@pytest.mark.parametrize("head", ["{T}/checkpoints/x", "job_1/renders/x", "x/renders/y"])
def test_backend_refuses_a_non_job_second_segment(store: LocalDiskStorage, head: str) -> None:
    uri = f"amw-blob://{A.org_id}/jobs/{head.format(T=T)}"
    with pytest.raises(InputInvalidError):
        store.put(A, BlobUri(uri), io.BytesIO(b"x"))
    with pytest.raises(InputInvalidError):
        store.head(A, BlobUri(uri))


def test_other_areas_and_platform_uris_are_not_restricted_by_the_jobs_rule(
    store: LocalDiskStorage,
) -> None:
    ev = BlobUri(f"amw-blob://{A.org_id}/evidence/{J}/snap.json")
    store.put(A, ev, io.BytesIO(b"x"))
    assert store.head(A, ev).exists


def test_builders_reject_unsafe_input() -> None:
    org = A.org_id
    with pytest.raises(InputInvalidError):
        sp.task_artifact_uri(org, J, T, AT, "../x")
    with pytest.raises(InputInvalidError):
        sp.task_artifact_uri(org, J, T, AT, "a//b")
    with pytest.raises(InputInvalidError):
        sp.task_artifact_uri(org, T, T, AT, "x")  # type: ignore[arg-type]
    with pytest.raises(InputInvalidError):
        sp.task_io_uri(org, J, T, AT, "other.json")
    with pytest.raises(InputInvalidError):
        sp.job_cache_uri(org, J, "../agent", "x")
    with pytest.raises(InputInvalidError):
        sp.delivery_uri(org, J, T, "x")  # type: ignore[arg-type]
    with pytest.raises(InputInvalidError):
        sp.checkpoint_uri(J, J, T, "x")  # type: ignore[arg-type]
    with pytest.raises(InputInvalidError):
        sp.render_uri(org, J, "")


@pytest.mark.parametrize("bad", [5, True, False, None, 3.5, "S", b"x", {"a": 1}, [[1, 2]], [None]])
def test_non_list_violations_never_break_error_building(bad: object) -> None:
    doc = _error_doc({"violations": bad})
    items = doc["details"].get("violations", [])  # type: ignore[attr-defined]
    assert all({"path", "keyword", "message"} == set(v) for v in items)


def test_non_string_stage_id_is_input_invalid() -> None:
    ti = _ti()
    for bad in (5, b"voice", ["voice"]):
        with pytest.raises(InputInvalidError):
            ExecContext.from_task_input(
                ti,
                ATTEMPT.new(),
                "agent_07",
                envelope_org_id=ti.org_id,
                stage_id=bad,  # type: ignore[arg-type]
            )


@pytest.mark.parametrize(
    "name", [".hidden", "_x", "-x", "a" * 201, "a b", "x/.y", "x/" + "b" * 201]
)
def test_builders_are_at_least_as_strict_as_the_backend(name: str) -> None:
    with pytest.raises(InputInvalidError):
        sp.task_artifact_uri(A.org_id, J, T, AT, name)
    with pytest.raises(InputInvalidError):
        sp.render_uri(A.org_id, J, name)


def test_every_builder_output_passes_the_backend_parser() -> None:
    from amw_core.storage import parse_uri

    for uri in [
        *_builders(),
        sp.render_uri(A.org_id, J, "a" * 200),
        sp.render_uri(A.org_id, J, "a.b=c"),
    ]:
        parse_uri(uri)
