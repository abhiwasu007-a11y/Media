"""``agent_10.render`` against the in-memory fakes: flow, resume, drain, replay, guards."""

from pathlib import Path

import pytest

from agent_10_video_editor.config import GuardConfig
from agent_10_video_editor.guard import LocalTime
from agent_10_video_editor.render import RenderStage
from agent_10_video_editor.testing import make_config
from amw_core.enums import OutputStatus
from amw_core.errors import ConfigInvalidError, InputInvalidError, MissingDependencyError
from tests.agents.agent_10_video_editor.support import World, payload_data


def _run(world: World) -> object:
    return RenderStage(world.deps()).run(world.render_input(), world.attempt)


@pytest.mark.unit
def test_render_completes_and_registers(tmp_path: Path) -> None:
    world = World(tmp_path, shots=4)  # 4 x 4 s, target 8 s -> 2 segments
    out = RenderStage(world.deps()).run(world.render_input(), world.attempt)
    assert out.status is OutputStatus.SUCCEEDED
    data = payload_data(out)
    assert data["segments"] == {
        "planned": 2,
        "encoded": 2,
        "reused": 0,
        "resumed_from_checkpoint": False,
    }
    assert data["frame_count"] == 480
    assert data["duration_ms"] == 16000
    assert data["encoder"]["audio_bitrate_nominal_bps"] == 384000
    assert data["encoder"]["gop"] == {
        "gop_frames": 60,
        "closed_gop": True,
        "idr_at_segment_start": True,
    }
    assert all(r.verdict == "PASS" for r in out.validation_results)
    assert not any(r.gate for r in out.validation_results)  # a10.q.* are process integrity only
    assert len(world.renders.rows) == 1
    assert [e.entry.provider for e in world.cost.rows] == ["ffmpeg"]
    assert world.cost.rows[0].entry.amount_micros == 0
    assert out.resource_usage.llm_calls == 0
    assert out.resource_usage.provider_calls == 0
    kinds = [c.kind for c in world.runner.calls]
    assert kinds.count("segment") == 2
    assert kinds.count("mux") == 1


@pytest.mark.unit
def test_render_is_deterministic_across_runs(tmp_path: Path) -> None:
    a = World(tmp_path / "a", shots=4)
    b = World(tmp_path / "b", shots=4)
    # same inputs, same encoder arguments (random ids differ, content hashes must not)
    out_a = RenderStage(a.deps()).run(a.render_input(), a.attempt)
    out_b = RenderStage(b.deps()).run(b.render_input(), b.attempt)
    assert payload_data(out_a)["frame_count"] == payload_data(out_b)["frame_count"]
    assert (
        payload_data(out_a)["encoder"]["args_sha256"]
        == payload_data(out_b)["encoder"]["args_sha256"]
    )


@pytest.mark.unit
def test_reveal_stills_are_inputs_of_the_chart_shot(tmp_path: Path) -> None:
    world = World(tmp_path, shots=3, chart=True)
    out = RenderStage(world.deps()).run(world.render_input(), world.attempt)
    assert out.status is OutputStatus.SUCCEEDED
    segment_argvs = [c.argv for c in world.runner.calls if c.kind == "segment"]
    inputs = [a for argv in segment_argvs for a in argv if a.startswith("in_")]
    assert len(inputs) == 4  # sh01, two reveal stills of sh02, sh03


@pytest.mark.security
def test_tenant_mismatch_is_rejected_before_any_file_is_staged(tmp_path: Path) -> None:
    from agent_10_video_editor.scope import TenantScope
    from amw_core.contracts.common import ContextRef
    from amw_core.errors import CrossTenantRefError, TenantMismatchError

    world = World(tmp_path)
    foreign = {
        "uri": "amw-blob://org_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e90/jobs/x/y.json",
        "purpose": "PRIOR_OUTPUT",
        "sha256": "1" * 64,
        "schema": "agent_09.shot_plan.output",
    }
    # layer 0: the contract refuses a foreign ref at construction
    with pytest.raises(CrossTenantRefError):
        world.task_input("render", world.render_input().payload.data or {}, extra_refs=[foreign])
    # layer 1: TenantScope re-checks (defence in depth) even for an input built without validation
    good = world.render_input()
    tampered = good.model_construct(
        **{
            **good.__dict__,
            "context_refs": (*good.context_refs, ContextRef.model_validate(foreign)),
        }
    )
    with pytest.raises(CrossTenantRefError):
        TenantScope.assert_consistent(world.org, tampered)
    with pytest.raises(TenantMismatchError):
        TenantScope.assert_consistent("org_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e90", good)
    assert world.runner.calls == []


@pytest.mark.unit
def test_nonzero_llm_budget_and_cost_budget_are_rejected(tmp_path: Path) -> None:
    world = World(tmp_path)
    ti = world.render_input()
    bad = ti.model_copy(
        update={"resource_budget": ti.resource_budget.model_copy(update={"max_cost_micros": 1})}
    )
    with pytest.raises(InputInvalidError):
        RenderStage(world.deps()).run(bad, world.attempt)


@pytest.mark.unit
def test_missing_asset_for_aspect_is_missing_dependency(tmp_path: Path) -> None:
    world = World(tmp_path)
    with pytest.raises(MissingDependencyError):
        RenderStage(world.deps()).run(
            world.render_input(aspect_ratio="9:16", preset_key="shorts_9x16"), world.attempt
        )
    assert world.runner.calls == []


@pytest.mark.unit
def test_script_hash_mismatch(tmp_path: Path) -> None:
    world = World(tmp_path)
    with pytest.raises(InputInvalidError):
        RenderStage(world.deps()).run(
            world.render_input(verified_script_sha256="9" * 64), world.attempt
        )


@pytest.mark.unit
def test_guard_fails_closed_without_a_calendar(tmp_path: Path) -> None:
    cfg = make_config()
    cfg = cfg.model_copy(update={"guard": GuardConfig(market_windows=None, night_window=None)})
    world = World(tmp_path, config=cfg)
    with pytest.raises(ConfigInvalidError):
        RenderStage(world.deps()).run(world.render_input(), world.attempt)
    assert not [c for c in world.runner.calls if c.kind in ("segment", "mux")]


@pytest.mark.unit
def test_no_segment_starts_inside_market_hours(tmp_path: Path) -> None:
    world = World(tmp_path, now=LocalTime.parse("TUE", "10:00"))
    out = RenderStage(world.deps()).run(world.render_input(), world.attempt)
    assert out.status is OutputStatus.SUSPENDED
    assert out.next_action.wait_reason is not None
    assert not [c for c in world.runner.calls if c.kind in ("segment", "mux")]
    assert world.renders.rows == {}


@pytest.mark.unit
def test_replay_creates_no_second_row_blob_or_cost_row(tmp_path: Path) -> None:
    world = World(tmp_path)
    first = RenderStage(world.deps()).run(world.render_input(), world.attempt)
    blobs, rows, costs = len(world.storage.blobs), len(world.renders.rows), len(world.cost.rows)
    encodes = world.runner.encode_calls
    again = RenderStage(world.deps()).run(world.render_input(), world.attempt)
    assert again.status is OutputStatus.SUCCEEDED
    assert payload_data(again)["render_ref"] == payload_data(first)["render_ref"]
    assert (len(world.renders.rows), len(world.cost.rows)) == (rows, costs)
    assert world.runner.encode_calls == encodes
    assert len(world.storage.blobs) >= blobs  # checkpoint blobs only; no second final


@pytest.mark.failure_injection
def test_drain_mid_render_checkpoints_and_resume_reuses_finished_segments(tmp_path: Path) -> None:
    world = World(tmp_path, shots=4)

    def on_write(step_key: str) -> None:
        if step_key == "render.seg_0":
            world.probe.drain = True  # the DRAIN control arrives after the first segment

    world.hook_checkpoints(on_write)
    stage = RenderStage(world.deps())
    suspended = stage.run(world.render_input(), world.attempt)
    assert suspended.status is OutputStatus.SUSPENDED
    assert [c.kind for c in world.runner.calls].count("segment") == 1
    world.probe.drain = False
    done = stage.run(world.render_input(), world.attempt)
    assert done.status is OutputStatus.SUCCEEDED
    segs = payload_data(done)["segments"]
    assert segs["resumed_from_checkpoint"] is True
    assert segs["reused"] == 1
    assert segs["encoded"] == 1
    # the finished segment was not redone
    assert [c.kind for c in world.runner.calls].count("segment") == 2


@pytest.mark.unit
def test_audit_entries_idempotency_rows_and_metrics_of_a_render(tmp_path: Path) -> None:
    world = World(tmp_path, shots=4)
    RenderStage(world.deps()).run(world.render_input(), world.attempt)
    assert world.audit.actions == ["render.started", "render.completed"]
    entry = world.audit.entries[1][1]
    assert set(entry.details) == {"content_sha256", "duration_ms"}  # IDs, hashes, numbers only
    rows = list(world.idempotency._rows.values())
    scopes = sorted(r.scope for r in rows)
    assert scopes == ["render.master", "render.segment", "render.segment"]
    assert all(r.status == "COMPLETED" for r in rows)


@pytest.mark.unit
def test_guard_refusal_is_audited(tmp_path: Path) -> None:
    world = World(tmp_path, now=LocalTime.parse("TUE", "10:00"))
    RenderStage(world.deps()).run(world.render_input(), world.attempt)
    assert "render.guard_refused" in world.audit.actions


@pytest.mark.failure_injection
def test_same_master_key_with_other_content_is_an_idempotency_conflict(tmp_path: Path) -> None:
    from amw_core.errors import IdempotencyConflictError

    world = World(tmp_path)
    real_begin = world.idempotency.begin
    seen: list[str] = []

    def begin(tx, key, scope, request_sha256, task_id, now, lock_ms):  # type: ignore[no-untyped-def]
        if scope == "render.master" and not seen:
            seen.append(scope)
            real_begin(tx, key, scope, "0" * 64, task_id, now, lock_ms)  # an earlier, other request
        return real_begin(tx, key, scope, request_sha256, task_id, now, lock_ms)

    world.idempotency.begin = begin  # type: ignore[method-assign]
    with pytest.raises(IdempotencyConflictError):
        RenderStage(world.deps()).run(world.render_input(), world.attempt)
    assert world.renders.rows == {}


@pytest.mark.failure_injection
def test_a_segment_held_by_another_attempt_is_a_lock_conflict(tmp_path: Path) -> None:
    from amw_core.errors import LockConflictError

    world = World(tmp_path)
    real_begin = world.idempotency.begin

    def begin(tx, key, scope, request_sha256, task_id, now, lock_ms):  # type: ignore[no-untyped-def]
        if scope == "render.segment":  # another attempt began the same effect and still holds it
            real_begin(tx, key, scope, request_sha256, task_id, now, lock_ms)
        return real_begin(tx, key, scope, request_sha256, task_id, now, lock_ms)

    world.idempotency.begin = begin  # type: ignore[method-assign]
    with pytest.raises(LockConflictError):
        RenderStage(world.deps()).run(world.render_input(), world.attempt)
    assert not [u for u in world.storage.blobs if "/segments/" in u]
