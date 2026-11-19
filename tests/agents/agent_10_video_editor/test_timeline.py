# ruff: noqa: E501
"""Timeline compiler extras, hashing, text binding, font coverage, config and canonical JSON."""

import json
from typing import Any

import pytest

from agent_10_video_editor.canonical import canonical_json, canonical_sha256
from agent_10_video_editor.config import AgentTenConfig
from agent_10_video_editor.errors import violations_of
from agent_10_video_editor.frames import FrameQuantiser
from agent_10_video_editor.inputs import AssetManifest, AssetRecord, ScriptStrings, ShotPlan
from agent_10_video_editor.segments import (
    BlobFacts,
    RenderState,
    ResumeVerifier,
    Segment,
    SegmentPlanner,
    SegmentRecord,
    ShotFrames,
    target_frames_of,
)
from agent_10_video_editor.testing import make_config
from agent_10_video_editor.timeline import (
    FontCoverage,
    TextBinder,
    TimelineCompiler,
    TimelineHasher,
    UpstreamGate,
)
from amw_core.errors import ConfigInvalidError, InputInvalidError, MissingDependencyError
from tests.agents.agent_10_video_editor.support import audio_master

SHA = "e" * 64


def _doc(
    *, end_screen: bool = False, overlay_ref: str | None = "amw-blob://org_x/t.png", reveal: int = 2
) -> tuple[ShotPlan, AssetManifest, dict[str, AssetRecord]]:
    plan: dict[str, Any] = {
        "timing_basis": "MEASURED", "language": "mr", "aspect_ratio": "16:9",
        "total_duration_ms": 12_000 if end_screen else 10_000, "content_end_ms": 10_000,
        "shots": [
            {"shot_id": "sh01", "start_ms": 0, "end_ms": 4000},
            {"shot_id": "sh02", "start_ms": 4000, "end_ms": 10_000, "intent_kind": "CHART", "change_events_ms": [7000]},
        ],
        "overlays": [{"overlay_id": "ov01", "kind": "LOWER_THIRD", "start_ms": 1000, "end_ms": 3000, "template_ref": overlay_ref, "text_refs": [{"sha256": SHA, "scene_id": "s", "index": 0}]}],
    }  # fmt: skip
    if end_screen:
        plan["overlays"].append(
            {
                "overlay_id": "ov02",
                "kind": "END_SCREEN",
                "start_ms": 10_000,
                "end_ms": 12_000,
                "template_ref": "amw-blob://org_x/e.png",
            }
        )
    stills = [{"k": k, "asset_id": f"st{k}", "asset_uri": f"amw-blob://org_x/st{k}.png", "sha256": str(k) * 64, "start_ms": [4000, 7000][k], "end_ms": [7000, 10_000][k], "licence_id": "L", "ledger_entry_ids": ["l"]} for k in range(reveal)]  # fmt: skip
    shots = [
        {"shot_id": "sh01", "aspect_ratio": "16:9", "status": "SOURCED", "tier": "B_LICENSED_STOCK", "asset_id": "a1", "asset_uri": "amw-blob://org_x/a1.mp4", "fingerprints": {"sha256": "1" * 64}, "media": {"width_px": 3840, "height_px": 2160, "source_in_ms": 1500, "crop": {"mode": "ANCHOR_CROP", "anchor": "UPPER_THIRD", "keep_permille": 800}}},
        {"shot_id": "sh02", "aspect_ratio": "16:9", "status": "SOURCED", "tier": "C_CODE_MOTION", "asset_id": "a2", "asset_uri": "amw-blob://org_x/a2.png", "fingerprints": {"sha256": "2" * 64}, "reveal_stills": stills},
        {"shot_id": "sh01", "aspect_ratio": "9:16", "status": "SOURCED", "asset_id": "z", "asset_uri": "amw-blob://org_x/z.mp4", "fingerprints": {"sha256": "9" * 64}},
    ]  # fmt: skip
    overlays = [{"overlay_id": "ov01", "kind": "LOWER_THIRD", "template_asset_id": "t1"}]
    assets = {"t1": AssetRecord(asset_id="t1", uri="amw-blob://org_x/t.png", sha256="5" * 64)}
    if end_screen:
        overlays.append({"overlay_id": "ov02", "kind": "END_SCREEN", "template_asset_id": "t2"})
        assets["t2"] = AssetRecord(asset_id="t2", uri="amw-blob://org_x/e.png", sha256="6" * 64)
    return (
        ShotPlan.model_validate(plan),
        AssetManifest.model_validate({"shots": shots, "overlays": overlays}),
        assets,
    )


def _compile(**kw: Any) -> Any:
    plan, manifest, assets = _doc(**kw)
    return TimelineCompiler.compile(
        plan, manifest, assets, audio_master(plan.total_duration_ms), make_config(), "16:9"
    )


@pytest.mark.unit
def test_compile_selects_the_requested_aspect_binds_assets_and_keeps_plan_ms() -> None:
    t = _compile()
    assert [s.asset_id for s in t.shots] == ["a1", "a2"]  # the 9:16 entry is ignored
    first = t.shots[0]
    assert first.source_in_ms == 1500
    assert first.crop["anchor"] == "UPPER_THIRD"
    assert (first.plan_start_ms, first.plan_end_ms) == (0, 4000)
    chart = t.shots[1]
    assert [(r.k, r.start_frame) for r in chart.reveal_steps] == [(0, 120), (1, 210)]
    assert t.overlays[0].template_asset_id == "t1"
    assert t.overlays[0].text_sha256s == (SHA,)
    assert t.total_frames == 300
    assert t.end_screen is None
    assert TimelineHasher.timeline_sha256(t) == TimelineHasher.timeline_sha256(_compile())
    json.loads(canonical_json(t.canonical()))  # canonical form is plain JSON (integers and strings)


@pytest.mark.unit
def test_end_screen_tail_is_a_pseudo_shot_of_the_template() -> None:
    t = _compile(end_screen=True)
    assert t.end_screen is not None
    assert (t.end_screen.start_frame, t.end_screen.end_frame) == (300, 360)
    assert [p.shot_id for p in t.visual_parts()] == ["sh01", "sh02", "end_screen"]
    assert t.expected_render_duration_ms == 12_000


@pytest.mark.unit
def test_template_mismatch_and_reveal_rules_and_missing_overlay_entry() -> None:
    with pytest.raises(InputInvalidError) as info:
        _compile(overlay_ref="amw-blob://org_x/other.png")
    assert violations_of(info.value) == ["TEMPLATE_MISMATCH:ov01"]
    with pytest.raises(InputInvalidError) as count:
        _compile(reveal=1)
    assert violations_of(count.value) == ["REVEAL_COUNT:sh02"]
    plan, manifest, assets = _doc()
    no_overlay = AssetManifest.model_validate({**manifest.model_dump(), "overlays": []})
    with pytest.raises(MissingDependencyError):
        TimelineCompiler.compile(
            plan, no_overlay, assets, audio_master(10_000), make_config(), "16:9"
        )
    shifted = json.loads(manifest.model_dump_json())
    shifted["shots"][1]["reveal_stills"][1]["start_ms"] = 7001
    with pytest.raises(InputInvalidError):
        TimelineCompiler.compile(
            plan,
            AssetManifest.model_validate(shifted),
            assets,
            audio_master(10_000),
            make_config(),
            "16:9",
        )
    unledgered = json.loads(manifest.model_dump_json())
    unledgered["shots"][1]["reveal_stills"][1]["ledger_entry_ids"] = []
    with pytest.raises(MissingDependencyError) as missing:
        TimelineCompiler.compile(
            plan,
            AssetManifest.model_validate(unledgered),
            assets,
            audio_master(10_000),
            make_config(),
            "16:9",
        )
    assert violations_of(missing.value) == ["NO_ASSET:sh02#1"]


@pytest.mark.unit
def test_tiling_errors_at_the_ends_of_the_plan() -> None:
    plan, manifest, assets = _doc()
    for patch, expected in (
        ({"shots": [{"shot_id": "sh01", "start_ms": 100, "end_ms": 4000}, {"shot_id": "sh02", "start_ms": 4000, "end_ms": 10_000}]}, "TILING_GAP:START>sh01"),
        ({"shots": [{"shot_id": "sh01", "start_ms": 0, "end_ms": 4100}, {"shot_id": "sh02", "start_ms": 4000, "end_ms": 10_000}]}, "TILING_OVERLAP:sh01>sh02"),
        ({"shots": [{"shot_id": "sh01", "start_ms": 0, "end_ms": 4000}, {"shot_id": "sh02", "start_ms": 4000, "end_ms": 9000}]}, "TILING_GAP:sh02>END"),
    ):  # fmt: skip
        bad = ShotPlan.model_validate({**json.loads(plan.model_dump_json()), **patch})
        with pytest.raises(InputInvalidError) as info:
            TimelineCompiler.compile(
                bad, manifest, assets, audio_master(10_000), make_config(), "16:9"
            )
        assert expected in violations_of(info.value)


@pytest.mark.unit
def test_text_binding_and_font_coverage() -> None:
    text = "आज"
    import hashlib

    sha = hashlib.sha256(text.encode()).hexdigest()
    plan, _, _ = _doc()
    overlay = plan.overlays[0].model_copy(
        update={"text_refs": (plan.overlays[0].text_refs[0].model_copy(update={"sha256": sha}),)}
    )
    assert TextBinder.bind([overlay], ScriptStrings(segments={}, on_screen={sha: text})) == {
        sha: text
    }
    with pytest.raises(InputInvalidError) as missing:
        TextBinder.bind([overlay], ScriptStrings(segments={}, on_screen={}))
    assert violations_of(missing.value) == ["TEXT_REF_MISSING:ov01"]
    with pytest.raises(InputInvalidError) as wrong:
        TextBinder.bind([overlay], ScriptStrings(segments={}, on_screen={sha: "other"}))
    assert violations_of(wrong.value) == ["TEXT_HASH_MISMATCH:ov01"]
    FontCoverage.check({ord(c) for c in text}, [text])
    with pytest.raises(InputInvalidError) as glyph:
        FontCoverage.check({ord("आ")}, [text])
    assert violations_of(glyph.value) == [f"GLYPH_MISSING:U+{ord('ज'):04X}"]


@pytest.mark.unit
def test_upstream_gate_collects_every_violation_and_audio_coverage() -> None:
    kw: dict[str, Any] = {
        "timing_basis": "MEASURED", "shot_ids": ["sh01"], "manifest_entries": [{"shot_id": "sh01", "aspect_ratio": "16:9", "status": "SOURCED"}],
        "audio_gate_verdict": "PASSED", "audio_sample_rate_hz": 48000, "audio_channels": 2, "audio_duration_ms": 8000,
        "narration_end_ms": 8000, "script_sha_equal": True, "aspect_ratio": "16:9",
    }  # fmt: skip
    UpstreamGate.check_render(**kw)
    with pytest.raises(InputInvalidError) as info:
        UpstreamGate.check_render(
            **{
                **kw,
                "timing_basis": "ESTIMATED",
                "script_sha_equal": False,
                "audio_duration_ms": 7000,
            }
        )
    assert violations_of(info.value) == [
        "PLAN_NOT_MEASURED",
        "SCRIPT_HASH_MISMATCH",
        "AUDIO_COVERAGE",
    ]
    with pytest.raises(MissingDependencyError) as unresolved:
        UpstreamGate.check_render(**{**kw, "unresolved_shot_ids": ["sh01"]})
    assert "NO_ASSET:sh01" in violations_of(unresolved.value)


@pytest.mark.unit
def test_frame_quantiser_rejects_bad_arguments() -> None:
    with pytest.raises(InputInvalidError):
        FrameQuantiser.to_frame(-1, 30, 1)
    with pytest.raises(InputInvalidError):
        FrameQuantiser.to_frame(1, 0, 1)
    with pytest.raises(InputInvalidError):
        FrameQuantiser.frames_to_ms(-1, 30, 1)


@pytest.mark.unit
def test_canonical_json_rejects_floats_and_sorts_keys() -> None:
    assert canonical_json({"b": 1, "a": [2, "x"]}) == b'{"a":[2,"x"],"b":1}'
    with pytest.raises(InputInvalidError):
        canonical_json({"a": {"b": [1.5]}})
    assert canonical_sha256({"a": 1}) == canonical_sha256({"a": 1})


@pytest.mark.unit
def test_config_validation_and_defaults() -> None:
    cfg = make_config()
    assert cfg.render.geometry == (1920, 1080)
    shorts = {"preset_key": "shorts_9x16", "video_bitrate_bps": 8_000_000}  # no INF-12 row
    assert make_config(render=shorts).render.geometry == (1080, 1920)
    assert target_frames_of(60_000, 30, 1) == 1800
    assert target_frames_of(1001, 30000, 1001) == 30
    with pytest.raises(ConfigInvalidError) as info:
        AgentTenConfig.from_mapping({"render": {"fps_num": 30}, "sub": {}})
    keys = violations_of(info.value)
    assert "CONFIG_KEY:render.fps_den" in keys
    assert "CONFIG_KEY:sub.max_chars_per_cue" in keys


@pytest.mark.unit
def test_segment_resume_verifier_branches() -> None:
    segs = [
        (Segment(0, 0, 60, ("a",)), "k0", "u0"),
        (Segment(1, 60, 120, ("b",)), "k1", "u1"),
        (Segment(2, 120, 180, ("c",)), "k2", "u2"),
    ]
    rec0 = SegmentRecord(ordinal=0, key="k0", uri="u0", sha256="a" * 64, size_bytes=10, frames=60)
    state = RenderState(render_id="r", final_uri="f", segments={0: rec0})
    heads = {
        "u0": BlobFacts(True, "a" * 64, 10),
        "u1": BlobFacts(True, "b" * 64, 20),
        "u2": BlobFacts(True, "c" * 64, 30),
    }
    plan = ResumeVerifier.verify(segs, state, heads.__getitem__, lambda uri: 60)
    assert [r.ordinal for r in plan.reusable] == [0, 1, 2]
    assert [r.ordinal for r in plan.adopted] == [1, 2]
    assert plan.to_encode == ()
    # a hash mismatch at segment 0 ends the skip run: nothing after it is trusted
    state_bad = RenderState(
        render_id="r", final_uri="f", segments={0: rec0.model_copy(update={"sha256": "d" * 64})}
    )
    bad = ResumeVerifier.verify(segs, state_bad, heads.__getitem__, lambda uri: 60)
    assert bad.reusable == ()
    assert bad.to_encode == (0, 1, 2)
    # an orphan with the wrong frame count is re-encoded
    wrong = ResumeVerifier.verify(segs, None, heads.__getitem__, lambda uri: 59)
    assert wrong.to_encode == (0, 1, 2)
    missing = ResumeVerifier.verify(
        segs, None, lambda uri: BlobFacts(False, None, None), lambda uri: None
    )
    assert missing.to_encode == (0, 1, 2)
    assert SegmentPlanner.plan([ShotFrames("a", 0, 10)], 5)[0].shot_ids == ("a",)
