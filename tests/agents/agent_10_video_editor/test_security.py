"""Security (S-01..S-09): tenant isolation, command injection, no network, no LLM, no secrets."""

import ast
import re
from pathlib import Path

import pytest

import agent_10_video_editor
from agent_10_video_editor.ffmpeg import ArgvBuilder
from agent_10_video_editor.render import RenderStage
from agent_10_video_editor.scope import TenantScope
from agent_10_video_editor.segments import Segment, SegmentSlice
from agent_10_video_editor.testing import MemoryBlobStorage, make_config
from agent_10_video_editor.timeline import TimelineOverlay, TimelineShot
from amw_core.errors import CrossTenantRefError, InputInvalidError
from tests.agents.agent_10_video_editor.support import World, payload_data

PACKAGE = Path(agent_10_video_editor.__file__).parent
EVIL = "x'; rm -rf / #\"$(touch /tmp/pwn)`id`%{eif:1:d}\nsecond line :;|&"


def _shot(uri: str) -> TimelineShot:
    return TimelineShot(
        shot_id="sh01", start_frame=0, end_frame=30, plan_start_ms=0, plan_end_ms=1000,
        asset_id="ast_x", asset_sha256="1" * 64, asset_uri=uri, source_in_ms=0,
        crop={"mode": "NONE", "anchor": None, "keep_permille": 1000}, motion="STATIC",
        transition_in={"kind": "CUT", "duration_ms": 0}, tier="C_CODE_MOTION",
        change_events_ms=(), reveal_steps=(), intent_kind="FOOTAGE",
    )  # fmt: skip


@pytest.mark.security
def test_s06_no_payload_text_reaches_an_argument() -> None:
    uri = 'amw-blob://org_x/jobs/j/it\'s "quoted" $(cmd) `tick`;|&.png'
    overlay = TimelineOverlay(
        overlay_id="ov01", kind="LOWER_THIRD", start_frame=0, end_frame=30, plan_start_ms=0,
        plan_end_ms=1000, template_asset_id="ast_t", template_sha256="2" * 64,
        template_uri="amw-blob://org_x/jobs/j/t.png", text_sha256s=("3" * 64,),
    )  # fmt: skip
    with pytest.raises(InputInvalidError):  # the extension is not on the whitelist
        ArgvBuilder(make_config().render).segment_command(
            SegmentSlice(Segment(0, 0, 30, ("sh01",)), (_shot(uri.replace(".png", ".sh")),), ())
        )
    command = ArgvBuilder(make_config().render).segment_command(
        SegmentSlice(Segment(0, 0, 30, ("sh01",)), (_shot(uri),), (overlay,))
    )
    for arg in command.argv:
        for fragment in ("quoted", "$(", "`", "rm -rf", "it's", "org_x", "jobs/"):
            assert fragment not in arg
    assert {s.name for s in command.inputs} == {"in_0.png", "in_1.png"}
    inputs = [a for a in command.argv if a.startswith("in_")]
    assert inputs == ["in_0.png", "in_1.png"]
    assert command.argv.count("-protocol_whitelist") == 2  # one per input
    assert "OVERLAY_TEXT_NOT_DRAWN:ov01" in command.warnings


@pytest.mark.security
def test_s06_script_text_never_reaches_any_recorded_command(tmp_path: Path) -> None:
    world = World(tmp_path, script_overrides={"s1": EVIL})
    RenderStage(world.deps()).execute(world.render_input(), world.attempt)
    for call in world.runner.calls:
        assert all("rm -rf" not in a and "touch" not in a for a in call.argv)


@pytest.mark.security
def test_s01_s03_s04_tenant_isolation_of_blobs_scratch_and_segment_cache(tmp_path: Path) -> None:
    shared = MemoryBlobStorage()
    a = World(tmp_path / "a", storage=shared)
    b = World(tmp_path / "b", storage=shared)
    assert a.org != b.org
    out_a = RenderStage(a.deps()).execute(a.render_input(), a.attempt)
    assert payload_data(out_a)["segments"]["encoded"] == 2
    # tenant B cannot read tenant A's blobs, with or without the right hash
    a_uri = payload_data(out_a)["render_ref"]["uri"]
    sha = payload_data(out_a)["render_ref"]["sha256"]
    with pytest.raises(CrossTenantRefError):
        b"".join(shared.get(b.ctx, a_uri, sha))
    with pytest.raises(CrossTenantRefError):
        shared.head(b.ctx, a_uri)
    # the content-addressed segment cache is looked up only under the tenant's own prefix
    out_b = RenderStage(b.deps()).execute(b.render_input(), b.attempt)
    assert payload_data(out_b)["segments"]["reused"] == 0
    assert payload_data(out_b)["segments"]["encoded"] == 2
    assert a_uri != payload_data(out_b)["render_ref"]["uri"]
    # every row read or written carries the tenant of the transaction
    assert all(k[0] in (a.org, b.org) for k in a.renders.rows)
    assert {org for org, _ in a.renders.rows} == {a.org}
    assert {org for org, _ in b.renders.rows} == {b.org}


@pytest.mark.security
@pytest.mark.parametrize("path", ["a/../b", "/abs", "a//b", "./x"])
def test_s03_paths_with_traversal_segments_are_rejected(tmp_path: Path, path: str) -> None:
    world = World(tmp_path)
    with pytest.raises(InputInvalidError):
        TenantScope(world.ctx, world.storage).uri("jobs", path)


@pytest.mark.security
def test_s09_no_network_no_llm_no_prompt_file_no_secret_in_the_package() -> None:
    forbidden_imports = {
        "socket",
        "http",
        "urllib",
        "requests",
        "httpx",
        "aiohttp",
        "ssl",
        "ftplib",
        "smtplib",
        "anthropic",
        "openai",
    }
    for source in PACKAGE.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                root = name.split(".")[0]
                assert root not in forbidden_imports, f"{source.name} imports {name}"
                assert not name.startswith("amw_adapters"), f"{source.name} imports an adapter"
        text = source.read_text(encoding="utf-8")
        assert not re.search(
            r"(?i)(api[_-]?key|secret|password|token)\s*=\s*[\"'][^\"']+[\"']", text
        ), source.name
        assert "shell=True" not in text
    prompts = Path(__file__).resolve().parents[3] / "prompts" / "agent_10_video_editor"
    assert not prompts.exists()


@pytest.mark.security
def test_s05_error_objects_carry_no_text_from_inputs(tmp_path: Path) -> None:
    world = World(tmp_path, script_overrides={"s1": EVIL})
    world.runner.crash_on_encode = {1}
    from amw_core.errors import RenderCrashError

    with pytest.raises(RenderCrashError) as info:
        RenderStage(world.deps()).execute(world.render_input(), world.attempt)
    assert EVIL not in str(info.value)
    assert EVIL not in str(info.value.details)
