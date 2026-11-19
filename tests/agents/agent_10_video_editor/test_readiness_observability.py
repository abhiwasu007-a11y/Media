"""Readiness probe (IT-06 with fakes) and the structural no-leak logging guarantee (S-05)."""

import json
import logging
from pathlib import Path

import pytest

from agent_10_video_editor.fonts import cmap_font_reader
from agent_10_video_editor.observability import LogContext, MemoryMetrics, emit, labels
from agent_10_video_editor.qc.selftest import SelfTestCase, SelfTestRecord
from agent_10_video_editor.readiness import ReadinessProbe
from agent_10_video_editor.render import RenderStage
from agent_10_video_editor.testing import FakeFfmpegRunner
from tests.agents.agent_10_video_editor.support import World, run_chain

EVIL = "SECRET-SCRIPT-LINE अक्षर /home/user/x.mp4 'quote' \n newline"
CTX = LogContext("org_x", "job_x", "tsk_x", "att_x", "cor_x")


class _SelfTests:
    def __init__(self, passed: bool = True) -> None:
        self.passed = passed

    def record_for(self, build_id: str) -> SelfTestRecord:
        return SelfTestRecord(
            build_id, (SelfTestCase("c", "PASS", "PASS" if self.passed else "FAIL"),)
        )


def _probe(
    world: World,
    tmp: Path,
    *,
    pinned: str | None = "ffmpeg version fake-1.0 (in-memory)",
    selftests: _SelfTests | None = None,
    runner: FakeFfmpegRunner | None = None,
) -> ReadinessProbe:
    return ReadinessProbe(
        runner=runner or world.runner, cfg=world.cfg, scratch_root=tmp / "scratch-ready",
        selftests=selftests or _SelfTests(), admission=world.probe, pinned_build_id=pinned,
        font_reader=cmap_font_reader,
    )  # fmt: skip


@pytest.mark.integration
def test_it06_readiness_passes_and_fails_on_each_missing_dependency(tmp_path: Path) -> None:
    world = World(tmp_path)
    assert _probe(world, tmp_path).run().ready
    assert _probe(world, tmp_path, pinned="another build").run().failed == ("build_pinned",)
    assert _probe(world, tmp_path, pinned=None).run().failed == ("build_pinned",)
    assert _probe(world, tmp_path, selftests=_SelfTests(False)).run().failed == ("selftest",)
    runner = FakeFfmpegRunner()
    runner.filters_text = " T.. scale  V->V  x\n"
    report = _probe(world, tmp_path, runner=runner).run()
    assert report.failed == ("filters",)
    assert "blackdetect" in next(c.detail for c in report.checks if c.name == "filters")
    broken = World(tmp_path / "b")
    broken.cfg = broken.cfg.model_copy(
        update={"guard": broken.cfg.guard.model_copy(update={"market_windows": None})}
    )
    assert "calendar" in _probe(broken, tmp_path).run().failed


@pytest.mark.integration
def test_readiness_on_the_vps_placement_needs_eta_and_night_window(tmp_path: Path) -> None:
    from agent_10_video_editor.config import Placement

    world = World(tmp_path, placement=Placement.VPS)
    assert _probe(world, tmp_path).run().failed == ("vps_eta",)


@pytest.mark.security
def test_s05_log_canary_no_script_subtitle_text_or_path_in_any_log_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    world = World(tmp_path, script_overrides={"s1": EVIL})
    world.licences.snapshot_value = world.licences.snapshot_value
    with caplog.at_level(logging.INFO, logger="agent_10"):
        chain = run_chain(world)
        RenderStage(world.deps()).execute(world.render_input(), world.attempt)
    assert chain["render"].status.value == "SUCCEEDED"
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert caplog.records
    for fragment in ("SECRET-SCRIPT-LINE", "अक्षर", "/home/", ".mp4", "amw-blob://", "quote"):
        assert fragment not in text
    events = [json.loads(r.getMessage())["event"] for r in caplog.records]
    assert {
        "render.start",
        "render.timeline",
        "render.segment_done",
        "render.registered",
        "subs.cues",
    } <= set(events)
    for record in caplog.records:
        body = json.loads(record.getMessage())
        assert body["org_id"] == world.org
        assert body["actor"] == "agent_10"


@pytest.mark.unit
def test_emit_refuses_anything_that_is_not_identifier_like() -> None:
    emit(
        "render.start",
        CTX,
        count=3,
        ok=True,
        none=None,
        digest="a" * 64,
        check_id="qc.audio.true_peak",
    )
    for bad in (EVIL, "has space", "a/b", "x" * 200, ""):
        with pytest.raises(ValueError, match="identifier-like"):
            emit("render.start", CTX, field=bad)
    with pytest.raises(ValueError, match="unknown log event"):
        emit("not.an.event", CTX)


@pytest.mark.unit
def test_metrics_carry_org_and_agent_labels(tmp_path: Path) -> None:
    world = World(tmp_path)
    metrics = MemoryMetrics()
    deps = world.deps()
    from dataclasses import replace

    RenderStage(replace(deps, metrics=metrics)).execute(world.render_input(), world.attempt)
    names = {name for name, _ in metrics.counters}
    assert {"a10_segments_total", "a10_guard_checks_total"} <= names
    for _, label_items in metrics.counters:
        label = dict(label_items)
        assert label["org_id"] == world.org
        assert label["agent_id"] == "agent_10"
    assert labels("o")["agent_id"] == "agent_10"
