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
def test_bad_payload_is_rejected_and_unreadable_document_is_schema_invalid(tmp_path: Path) -> None:
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
    assert out.status in (OutputStatus.REJECTED, OutputStatus.FAILED)
    assert out.error is not None
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
