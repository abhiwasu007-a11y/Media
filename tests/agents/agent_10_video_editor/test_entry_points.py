"""PASS6-I: ``run(task_input, ctx)`` entry points, chapters with a lead-in, the default font reader,
readiness without a reader, violation items, checkpoint paths (CCR-202..210)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_10_video_editor.errors import input_invalid
from agent_10_video_editor.fonts import cmap_font_reader
from agent_10_video_editor.qc import checks as C  # noqa: N812
from agent_10_video_editor.render import RenderStage
from agent_10_video_editor.subtitle_stage import SubtitleStage
from amw_core.contracts.error import error_object_from_exception
from amw_core.enums import CheckVerdict, OutputStatus
from amw_core.exec_context import ExecContext
from tests.agents.agent_10_video_editor.support import COR, World
from tests.agents.agent_10_video_editor.test_font_reader import FONTS


def _ctx(world: World, **kw: str) -> ExecContext:
    ti = world.render_input()
    return ExecContext.from_task_input(
        ti, kw.get("attempt", world.attempt), "agent_10", envelope_org_id=world.org
    )


@pytest.mark.unit
def test_render_entry_point_succeeds_and_checkpoints_use_the_core_path(tmp_path: Path) -> None:
    world = World(tmp_path)
    out = RenderStage(world.deps()).run(world.render_input(), _ctx(world))
    assert out.status is OutputStatus.SUCCEEDED
    uris = [u for u in world.storage.blobs if f"/checkpoints/{world.task}/{world.attempt}/" in u]
    assert uris
    assert all(f"/jobs/{world.job}/checkpoints/" in u for u in uris)


@pytest.mark.unit
def test_entry_point_returns_tenant_mismatch_instead_of_raising(tmp_path: Path) -> None:
    world, other = World(tmp_path / "a"), World(tmp_path / "b")
    out = RenderStage(world.deps()).run(world.render_input(), _ctx(other))
    assert out.status is OutputStatus.FAILED
    assert out.error is not None
    assert out.error.code.endswith("TENANT_MISMATCH")
    assert out.payload is None


@pytest.mark.unit
def test_bad_payload_is_rejected_with_schema_invalid(tmp_path: Path) -> None:
    world = World(tmp_path)
    bad = world.task_input("render", {"render_kind": 7})
    out = RenderStage(world.deps()).run(bad, _ctx(world))
    assert out.status is OutputStatus.REJECTED
    assert out.error is not None
    assert out.error.code.endswith("SCHEMA_INVALID")
    assert out.error.attempt_no == 0


@pytest.mark.unit
def test_subtitles_entry_point_returns_failures(tmp_path: Path) -> None:
    world = World(tmp_path)
    ti = world.task_input("subtitles", {"language": "mr"})
    out = SubtitleStage(world.deps()).run(ti, _ctx(world))
    assert out.status is OutputStatus.REJECTED  # the payload misses required fields
    assert out.error is not None
    assert out.error.code.endswith("SCHEMA_INVALID")
    assert out.error.attempt_no == 0
    assert out.resource_usage.cost_estimate_micros == 0


@pytest.mark.unit
def test_chapters_with_a_lead_in_pass() -> None:
    shots = [("hook", 0), ("s1", 5_000), ("s1", 9_000), ("s2", 20_000), (None, 30_000)]
    starts = C.section_starts_ms(shots)
    assert starts == [0, 20_000]  # first section = 0 (it covers the hook lead-in)
    res = C.edit_chapters(chapters_ms=[0, 20_000], section_starts_ms=starts, tolerance_ms=1000)
    assert res.verdict is CheckVerdict.PASS
    late = C.edit_chapters(chapters_ms=[0, 25_000], section_starts_ms=starts, tolerance_ms=1000)
    assert late.verdict is CheckVerdict.FAIL


@pytest.mark.unit
def test_default_font_reader_covers_devanagari_and_flags_a_missing_code_point() -> None:
    from agent_10_video_editor.deps import StageDeps
    from agent_10_video_editor.timeline import FontCoverage
    from amw_core.errors import InputInvalidError

    assert StageDeps.__dataclass_fields__["font_reader"].default is cmap_font_reader
    mukta = cmap_font_reader((FONTS / "Mukta-Bold.ttf").read_bytes())
    FontCoverage.check(mukta, ["मराठी ट्रेंड"])
    with pytest.raises(InputInvalidError) as info:
        FontCoverage.check(mukta, ["ॸ"])
    assert info.value.details["violations"][0].keyword == "GLYPH_MISSING"


@pytest.mark.unit
def test_readiness_fails_without_a_font_reader(tmp_path: Path) -> None:
    from tests.agents.agent_10_video_editor.test_readiness_observability import _probe

    world = World(tmp_path)
    probe = _probe(world, tmp_path)
    probe._font_reader = None
    assert probe.run().failed == ("font_reader",)


@pytest.mark.unit
def test_violation_items_build_a_valid_error_object() -> None:
    exc = input_invalid("TEMPLATE_MISMATCH:ov01", "NO_ASSET:sh02")
    err = error_object_from_exception(
        exc,
        actor="agent_10",
        attempt_no=1,
        occurred_at=datetime.now(UTC),
        correlation_id=COR,
    )
    assert [v.keyword for v in err.details.violations or ()] == ["TEMPLATE_MISMATCH", "NO_ASSET"]


# -- PASS6-I review fixes ----------------------------------------------------------------------

BAD_BLOBS = {
    "not_json": b"this is not json",
    "empty": b"",
    "too_deep": b"[" * 100_000 + b"]" * 100_000,
    "not_utf8": b'{"a": "\xff\xfe"}'.replace(b"\\xff\\xfe", b"\xff\xfe"),
}


def _subtitle_input(world: World) -> object:
    from amw_core.ids import RENDER

    uri, sha = world.put("render-out.json", b"{}")
    ref = {"uri": uri, "purpose": "PRIOR_OUTPUT", "sha256": sha, "schema": "agent_10.render.output"}
    payload = {
        "render_id": str(RENDER.new()),
        "language": "mr",
        "iteration": 0,
        "verified_script_sha256": world.script_blob_sha,
        "caption_style": None,
    }
    return world.task_input(
        "subtitles",
        payload,
        extra_refs=[ref],
        schemas=["agent_07.voice_synthesis.output", "agent_05.script_document"],
    )


@pytest.mark.unit
@pytest.mark.parametrize("name", sorted(BAD_BLOBS))
def test_unparsable_referenced_blob_is_rejected_schema_invalid_in_render(
    tmp_path: Path, name: str
) -> None:
    world = World(tmp_path)
    world.refs["agent_09.shot_plan.output"] = world.put("bad.json", BAD_BLOBS[name])
    out = RenderStage(world.deps()).run(world.render_input(), _ctx(world))
    assert out.status is OutputStatus.REJECTED
    assert out.error is not None
    assert out.error.code.endswith("SCHEMA_INVALID")
    assert out.error.attempt_no == 0
    assert [v.keyword for v in out.error.details.violations or ()] == ["PAYLOAD_NOT_JSON"]


@pytest.mark.unit
@pytest.mark.parametrize("name", sorted(BAD_BLOBS))
def test_unparsable_referenced_blob_is_rejected_schema_invalid_in_subtitles(
    tmp_path: Path, name: str
) -> None:
    world = World(tmp_path)
    world.refs["agent_07.voice_synthesis.output"] = world.put("bad.json", BAD_BLOBS[name])
    out = SubtitleStage(world.deps()).run(_subtitle_input(world), _ctx(world))  # type: ignore[arg-type]
    assert out.status is OutputStatus.REJECTED
    assert out.error is not None
    assert out.error.code.endswith("SCHEMA_INVALID")
    assert [v.keyword for v in out.error.details.violations or ()] == ["PAYLOAD_NOT_JSON"]


@pytest.mark.unit
def test_blob_of_the_wrong_shape_is_schema_invalid_with_a_pointer() -> None:
    from agent_10_video_editor.inputs import ShotPlan
    from agent_10_video_editor.taskio import parse_blob, parse_json_object
    from amw_core.errors import SchemaInvalidError

    with pytest.raises(SchemaInvalidError) as info:
        parse_blob(ShotPlan, b"{}", "agent_09.shot_plan.output")
    assert info.value.details["violations"][0].path.startswith("/context_refs/")
    with pytest.raises(SchemaInvalidError):
        parse_json_object(b"[1, 2]")


@pytest.mark.unit
def test_internal_validation_error_is_a_crash_not_schema_invalid() -> None:
    from pydantic import BaseModel, ValidationError

    from agent_10_video_editor.entry import classify
    from amw_core.errors import AgentCrashError, SchemaInvalidError

    class Internal(BaseModel):
        n: int

    with pytest.raises(ValidationError) as info:
        Internal.model_validate({"n": "x"})
    got = classify(info.value)
    assert isinstance(got, AgentCrashError)
    assert got.code == "AGENT.CRASH"
    assert classify(SchemaInvalidError("x")).code.endswith("SCHEMA_INVALID")


@pytest.mark.unit
def test_internal_validation_error_comes_back_failed_attempt_no_kept(tmp_path: Path) -> None:
    from pydantic import BaseModel

    from agent_10_video_editor.entry import run_task

    class Internal(BaseModel):
        n: int

    world = World(tmp_path)
    out = run_task(
        world.render_input(),
        _ctx(world),
        world.clock,
        lambda: Internal.model_validate({"n": "x"}) and None,  # type: ignore[arg-type,return-value]
    )
    assert out.status is OutputStatus.FAILED
    assert out.error is not None
    assert out.error.code == "AGENT.CRASH"


class _Scope:
    def __init__(self, exc: Exception | None, data: bytes = b"font") -> None:
        self.exc, self.data = exc, data

    def read_bytes(self, uri: str, sha256: str) -> bytes:
        if self.exc is not None:
            raise self.exc
        return self.data


def _bind(monkeypatch: pytest.MonkeyPatch, scope: _Scope, reader: object) -> None:
    from types import SimpleNamespace

    from agent_10_video_editor import render as R  # noqa: N812
    from agent_10_video_editor.inputs import AssetRecord
    from agent_10_video_editor.timeline import TextBinder

    monkeypatch.setattr(TextBinder, "bind", staticmethod(lambda o, s: {"h": "अ"}))
    rec = AssetRecord(asset_id="f1", uri="amw-blob://o/jobs/j/inputs/f", sha256="a" * 64)
    loaded = SimpleNamespace(
        manifest=SimpleNamespace(fonts=[SimpleNamespace(asset_id="f1")]), script=None
    )
    run = SimpleNamespace(d=SimpleNamespace(font_reader=reader), scope=scope)
    R._RenderRun._bind_text(run, SimpleNamespace(overlays=()), loaded, {"f1": rec})  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("exc", "code"),
    [
        ("CrossTenantRefError", "CROSS_TENANT_REF"),
        ("MissingDependencyError", "MISSING_DEPENDENCY"),
        ("InputInvalidError", "INPUT_INVALID"),
        ("CorruptedOutputError", "CORRUPTED"),
    ],
)
def test_font_read_errors_keep_their_class(
    monkeypatch: pytest.MonkeyPatch, exc: str, code: str
) -> None:
    import amw_core.errors as E  # noqa: N812

    err = getattr(E, exc)("boom")
    with pytest.raises(type(err)) as info:
        _bind(monkeypatch, _Scope(err), cmap_font_reader)
    assert info.value is err
    assert code in info.value.code


@pytest.mark.unit
def test_unparsable_font_is_font_coverage_unavailable_and_reader_amw_error_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from amw_core.errors import ConfigInvalidError, MissingDependencyError

    with pytest.raises(ConfigInvalidError) as info:
        _bind(monkeypatch, _Scope(None, b"not a font"), cmap_font_reader)
    assert info.value.details["violations"][0].keyword == "FONT_COVERAGE_UNAVAILABLE"

    def reader(_: bytes) -> frozenset[int]:
        raise MissingDependencyError("x")

    with pytest.raises(MissingDependencyError):
        _bind(monkeypatch, _Scope(None), reader)
