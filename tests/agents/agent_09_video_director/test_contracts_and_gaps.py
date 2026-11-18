# ruff: noqa: PT018, E501, RUF059
"""Review round 1: FR-16, gate wiring, refusal WARN, fail-closed budget/packs, TaskOutput and
contract tests C-02/C-04/C-06/C-07, hash-bound checkpoints, IT-04/IT-05, FI-04/11/12, S-02..S-08."""

import itertools
import json
import re
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from agent_09_video_director.assemble import derive_holds
from agent_09_video_director.contracts import AspectRatio, NarrationTimeline
from agent_09_video_director.direction.runner import ResumeState
from agent_09_video_director.output import ShotPlanPayload
from agent_09_video_director.persistence import (
    OutputRefData,
    load_checkpoint,
    persist_plan,
    save_checkpoint,
)
from agent_09_video_director.protocol import ShotPlanTask
from agent_09_video_director.step import Verification
from agent_09_video_director.views import build_views
from amw_adapters.common import FailurePlan
from amw_core.contracts.validation import validate_task_output
from amw_core.enums import CheckVerdict, OutputRefKind
from amw_core.errors import (
    CallTimeoutError,
    ConfigInvalidError,
    CrossTenantRefError,
    InputInvalidError,
    RateLimitedError,
    StorageUnavailableError,
    Upstream5xxError,
)
from amw_core.ids import ATTEMPT, ORG, TASK, OrgId, actor_ref
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.testing.memory import MemoryCheckpointStore, MemoryTransaction
from tests.agents.agent_09_video_director.support import (
    ORG_ID,
    SHA_A,
    TASK_ID,
    ResponderLlm,
    cfg,
    make_request,
    make_step,
    sample_script,
    timeline_for,
)
from tests.agents.agent_09_video_director.test_step import MemBlob

REPO = Path(__file__).resolve().parents[3]
AGENTS = REPO / "docs/v4/agents"


def blocks(doc: str) -> list[Any]:
    out = []
    for b in re.findall(r"```json\n(.*?)\n```", (AGENTS / doc).read_text(encoding="utf-8"), re.S):
        try:
            out.append(json.loads(b))
        except ValueError:
            continue
    return out


def ctx() -> TenantContext:
    return TenantContext(org_id=OrgId(ORG_ID), actor=actor_ref("agent_09"))


def run_task(**over: Any) -> tuple[Any, Any, MemBlob]:
    script, durs = sample_script()
    req = make_request(script, durs, **over)
    store = MemBlob()
    step, _, _ = make_step()
    out = ShotPlanTask(step, store).run(
        req, ctx(), task_path=f"{TASK_ID}/attempts/a1/output.json",
        now=datetime(2026, 1, 1, tzinfo=UTC), currency="USD",
    )  # fmt: skip
    return out, req, store


# ---------------------------------------------------------------- (7) Task Output, C-02/C-04/C-06/C-07
def test_c04_task_output_envelope_validates_against_core_schema() -> None:
    out, _, store = run_task()
    doc = out.to_doc()
    validate_task_output(doc, version="1.0.0")  # 03 section 5 schema + Pydantic rules
    assert out.status.value == "SUCCEEDED" and out.quality_score is None and out.confidence is None
    assert out.downstream_agent == "agent_08"
    assert [r.kind for r in out.output_refs] == [OutputRefKind.DATA]
    assert all(r.gate is False for r in out.validation_results)
    assert all(not r.blocking or r.verdict is CheckVerdict.PASS for r in out.validation_results)
    assert out.resource_usage.llm_calls == 2 and len(out.resource_usage.cost_entry_ids) == 2
    ref = out.output_refs[0]
    assert store.data[ref.uri]
    assert ref.sha256 == (out.payload.data or {})["plan_ref"]["sha256"]


def test_c02_payload_and_plan_validate_against_the_blueprint_schemas() -> None:
    out, req, store = run_task()
    data = out.payload.data
    ShotPlanPayload.model_validate(data)
    assert data["deliberate_black"] == [] and data["timing_basis"] == "MEASURED"
    shot_schema = next(
        b
        for b in blocks("agent_09_video_director.md")
        if b.get("$comment", "").startswith("$defs/shot")
    )
    plan = json.loads(next(iter(store.data.values())))
    for shot in plan["shots"]:
        jsonschema.validate(shot, shot_schema)
    assert set(shot_schema["properties"]) == set(plan["shots"][0])  # Pydantic == JSON Schema


def test_u118_views_validate_against_8_1_1_and_equal_the_shots() -> None:
    out, req, _ = run_task()
    defs = next(b for b in blocks("agent_09_video_director.md") if "agent_08_shot" in b)
    views = out.payload.data["views"]
    for item in views["agent_08_shots"]:
        jsonschema.validate(item, defs["agent_08_shot"])
    for item in views["agent_11_subjects"]:
        jsonschema.validate(item, defs["agent_11_subject"])
    for item in views["agent_16_realism"]:
        jsonschema.validate(item, defs["agent_16_realism"])
    assert [v["shot_id"] for v in views["agent_08_shots"]] == [
        f"sh{i:02d}" for i in range(1, len(views["agent_08_shots"]) + 1)
    ]


def test_c07_plan_ref_and_subjects_match_neighbour_contracts() -> None:
    out, _, _ = run_task()
    data = out.payload.data
    a08 = next(
        b for b in blocks("agent_08_visual_assets.md") if "shot_plan_ref" in b.get("properties", {})
    )
    ref_schema = a08["properties"]["shot_plan_ref"]
    ref = dict(data["plan_ref"])
    ref["uri"] = ref["uri"]
    jsonschema.validate(ref, ref_schema)
    a11 = next(
        b
        for b in blocks("agent_11_thumbnail_design.md")
        if "subject_hints" in b.get("properties", {})
    )
    for hint in data["views"]["agent_11_subjects"]:
        jsonschema.validate(hint, a11["properties"]["subject_hints"]["items"])
    assert 1 <= len(data["views"]["agent_11_subjects"]) <= 4


def test_c06_chapters_follow_the_script_chapter_shape() -> None:
    out, req, _ = run_task()
    chapters = out.payload.data["chapters"]
    a05 = {"section_id", "title_local", "est_start_ms"}  # agent_05 section 8.3 chapters[] item
    assert {"section_id", "title_local"} <= set(chapters[0]) and set(chapters[0]) - a05 == {
        "start_ms"
    }
    assert [c["section_id"] for c in chapters] == [s.section_id for s in req.script.sections]
    assert chapters[0]["start_ms"] == 0


def test_it04_agent_08_view_has_the_fields_the_query_plan_builder_reads() -> None:
    out, _, _ = run_task()
    views = out.payload.data["views"]["agent_08_shots"]
    needed = {"shot_id", "intent_kind", "intent_text", "on_screen_text", "allowed_tiers", "chart_id",
              "tier_hint", "fallback_template_key", "content_key", "change_events_ms"}  # fmt: skip
    assert all(needed <= set(v) for v in views)
    footage = [v for v in views if v["intent_kind"] == "FOOTAGE"]
    assert footage and all(
        v["intent_text"] and "B_LICENSED_STOCK" in v["allowed_tiers"] for v in footage
    )
    assert all(v["intent_text"] == "" for v in views if v["intent_kind"] == "CHART")


def test_it05_a_stub_timeline_compiler_can_consume_the_plan() -> None:
    script, durs = sample_script()
    res = make_step()[0].run(make_request(script, durs))
    p = res.plan
    track = [(s.start_ms, s.end_ms) for s in p.shots]
    assert track[0][0] == 0 and track[-1][1] == p.content_end_ms
    assert all(a[1] == b[0] for a, b in itertools.pairwise(track))  # tiling
    assert all(0 <= o.start_ms < o.end_ms <= p.total_duration_ms for o in p.overlays)
    assert p.overlays[-1].kind.value == "END_SCREEN" and p.overlays[-1].start_ms == p.content_end_ms
    assert [c.start_ms for c in p.chapters] == sorted({c.start_ms for c in p.chapters})
    for h in p.deliberate_hold:  # Agent 10 maps freezedetect to these intervals
        assert any(s.shot_id == h.shot_id and s.start_ms == h.start_ms for s in p.shots)


def test_te37_holds_are_derived_by_the_assembler_not_edited() -> None:
    script, durs = sample_script()
    plan = make_step()[0].run(make_request(script, durs)).plan
    held = [s for s in plan.shots if s.held is not None]
    assert derive_holds(plan.shots) == plan.deliberate_hold
    assert {h.reason.value for h in plan.deliberate_hold} == {
        s.held.reason.value for s in held if s.held
    }
    assert [(h.start_ms, h.end_ms) for h in plan.deliberate_hold] == [
        (s.start_ms, s.end_ms) for s in held
    ]


# ---------------------------------------------------------------- (1) FR-16 wired
def test_changed_timeline_is_rebased_and_limit_failure_is_reachable() -> None:
    script, durs = sample_script()
    first = make_step()[0].run(make_request(script, durs))
    old_tl = make_request(script, durs).timeline
    grown = {k: (v + 300 if k in ("s4", "s5") else v) for k, v in durs.items()}
    req = make_request(script, grown, iteration=1, previous_plan=first.plan,
                       previous_timeline=old_tl, timeline_sha256="c" * 64)  # fmt: skip
    ok = make_step()[0].run(req)
    assert [s.shot_id for s in ok.plan.shots[:6]] == [s.shot_id for s in first.plan.shots[:6]]
    huge = {k: (v * 2 if k == "s4" else v) for k, v in durs.items()}
    bad = make_request(script, huge, iteration=1, previous_plan=first.plan,
                       previous_timeline=old_tl, timeline_sha256="d" * 64)  # fmt: skip
    step, llm, _ = make_step()
    with pytest.raises(InputInvalidError) as ei:
        step.run(bad)
    assert ei.value.details["violations"] == ["REBASE_LIMIT"] and llm.requests == []
    with pytest.raises(InputInvalidError) as ei2:  # the previous timeline is required
        step.run(
            make_request(
                script, grown, iteration=1, previous_plan=first.plan, timeline_sha256="c" * 64
            )
        )
    assert ei2.value.details["violations"] == ["PREVIOUS_TIMELINE_MISSING"]


# ---------------------------------------------------------------- (2) gate wiring
@pytest.mark.parametrize(("kw", "code"), [
    ({"claim_blocked": True}, "CLAIM_BLOCKED"),
    ({"script_status": "REJECTED"}, "SCRIPT_NOT_CURRENT"),
    ({"script_status": "SUPERSEDED"}, "SCRIPT_NOT_CURRENT"),
])  # fmt: skip
def test_script_gate_receives_claim_and_status(kw: dict[str, Any], code: str) -> None:
    script, durs = sample_script()
    step, llm, _ = make_step()
    with pytest.raises(InputInvalidError) as ei:
        step.run(make_request(script, durs, verification=Verification(SHA_A, "ALLOWED", **kw)))
    assert code in ei.value.details["violations"] and llm.requests == []


# ---------------------------------------------------------------- (3) refusal WARN
def test_refused_batch_emits_a_warn_result_never_a_silent_pass() -> None:
    script, durs = sample_script()
    ref = {
        "reason": "RULE_WOULD_BE_BROKEN",
        "message": "m",
        "missing_inputs": [],
        "violated_rule_ids": ["FIN-R7"],
    }
    llm = ResponderLlm(lambda r: json.dumps({"batch_id": "b01", "directions": [], "refusal": ref}))
    step, _, _ = make_step(llm=llm, config=cfg(fallback_max_share_permille=1000))
    res = step.run(make_request(script, durs))
    r = next(x for x in res.results if x.check_id == "a09.q.visual_guard.refusal")
    assert (r.verdict, r.blocking, r.gate, r.rule_id) == (CheckVerdict.WARN, False, False, "FIN-R7")
    assert res.plan.refusal is not None and int(str(r.measured)) > 0
    reasons = {x.refusal_reason for x in build_views(res.plan, script).agent_16_realism}
    assert "RULE_WOULD_BE_BROKEN" in reasons
    clean = make_step()[0].run(make_request(script, durs))
    assert all(x.check_id != "a09.q.visual_guard.refusal" for x in clean.results)


# ---------------------------------------------------------------- (4) fail closed budget
def test_budget_config_is_required_and_fails_closed() -> None:
    script, durs = sample_script()
    step, llm, _ = make_step()
    for bad in ({"max_cost_micros": 0}, {"worst_case_call_micros": 0}, {"max_calls": 0}):
        with pytest.raises(ConfigInvalidError):
            step.run(make_request(script, durs, **bad))
    assert llm.requests == []
    from agent_09_video_director.step import ShotPlanRequest

    with pytest.raises(TypeError):  # no unlimited defaults exist
        ShotPlanRequest(org_id=ORG_ID)  # type: ignore[call-arg]


# ---------------------------------------------------------------- (5) missing pack
def test_missing_rule_pack_fails_closed_before_any_call() -> None:
    script, durs = sample_script()
    step, llm, _ = make_step()
    with pytest.raises(ConfigInvalidError):
        step.run(make_request(script, durs, rule_packs={"rp.youtube_general": "Y"}))
    assert llm.requests == []


# ---------------------------------------------------------------- (8) hash-bound checkpoints
def test_checkpoint_roundtrip_and_stale_checkpoint_is_discarded() -> None:
    script, durs = sample_script()
    config = cfg(llm_batch_slots=4)
    states: list[ResumeState] = []
    step, _, _ = make_step(config=config)
    first = step.run(make_request(script, durs), checkpoint=states.append)
    tx = MemoryTransaction(ctx())
    store, blobs = MemoryCheckpointStore(), MemBlob()
    tid, aid = TASK.new(), ATTEMPT.new()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for st in states[:2]:
        save_checkpoint(store, tx, blobs, ctx(), task_id=tid, attempt_id=aid, state=st, now=now)
    h = states[0].input_sha256
    loaded = load_checkpoint(store, tx, blobs, ctx(), task_id=tid, input_sha256=h)
    assert loaded == states[1] and len(blobs.data) == 2
    assert load_checkpoint(store, tx, blobs, ctx(), task_id=tid, input_sha256="0" * 64) is None
    assert load_checkpoint(store, tx, blobs, ctx(), task_id=TASK.new(), input_sha256=h) is None
    llm2 = ResponderLlm()  # resuming with the right hash skips the stored batches
    again = make_step(llm=llm2, config=config)[0].run(make_request(script, durs), resume=loaded)
    assert len(llm2.requests) == len(states) - 2 and again.plan_sha256 == first.plan_sha256
    # a checkpoint of other inputs (timeline hash changed) is ignored: every batch is re-asked
    llm3 = ResponderLlm()
    other = make_request(script, durs, timeline_sha256="e" * 64)
    make_step(llm=llm3, config=config)[0].run(other, resume=loaded)
    assert len(llm3.requests) == len(states)


# ---------------------------------------------------------------- FI-04, FI-12
def test_fi04_lost_response_is_re_sent_under_the_same_key() -> None:
    script, durs = sample_script()
    llm = ResponderLlm(failures=FailurePlan(sequence=[CallTimeoutError("lost")]))
    step, _, _ = make_step(llm=llm)
    req = make_request(script, durs)
    with pytest.raises(CallTimeoutError):
        step.run(req)
    res = step.run(req)  # the retry (orchestrator RETRY_WAIT) re-sends the same call
    keys = [c.idempotency_key for c in llm.engine.calls]
    assert keys[0] == keys[1] and llm.engine.billable_calls == 2 and res.plan.shots


@pytest.mark.parametrize(
    "error", [RateLimitedError("429", retry_after_ms=1500), Upstream5xxError("503")]
)
def test_fi12_provider_errors_propagate_typed(error: Any) -> None:
    script, durs = sample_script()
    step, _, _ = make_step(llm=ResponderLlm(failures=FailurePlan(sequence=[error])))
    with pytest.raises(type(error)) as ei:
        step.run(make_request(script, durs))
    assert ei.value.retry_after_ms == error.retry_after_ms  # honoured by the orchestrator


# ---------------------------------------------------------------- FI-11, S-03
def test_fi11_failed_blob_write_leaves_no_partial_file_and_paths_come_from_core() -> None:
    script, durs = sample_script()
    plan = make_step()[0].run(make_request(script, durs)).plan

    class Dying(MemBlob):
        built: list[str]

        def __init__(self) -> None:
            super().__init__()
            self.built = []
            self.die = True

        def blob_uri(self, context: TenantContext, area: str, path: str) -> Any:
            uri = super().blob_uri(context, area, path)
            self.built.append(str(uri))
            return uri

        def put(self, context: TenantContext, uri: Any, stream: Any) -> Any:
            if self.die:
                raise StorageUnavailableError("killed mid-write")  # temp file only, never final
            return super().put(context, uri, stream)

    store = Dying()
    with pytest.raises(StorageUnavailableError):
        persist_plan(store, ctx(), plan, task_path="t/output.json")
    assert store.data == {}
    store.die = False
    ref = persist_plan(store, ctx(), plan, task_path="t/output.json")
    assert store.built and ref.uri == store.built[0]  # S-03: URI built by the storage, not here
    assert ref.uri.startswith(f"amw-blob://{ORG_ID}/")


# ---------------------------------------------------------------- S-04, S-05, S-07, S-08
def test_s04_cacheable_prefix_has_no_tenant_data() -> None:
    script, durs = sample_script()
    llm = ResponderLlm()
    make_step(llm=llm)[0].run(make_request(script, durs, rule_packs={
        "rp.youtube_general": "Y", "rp.finance_sebi_in": "F", "rp.tenant_brand_safety": "TENANT-CANARY"}))  # fmt: skip
    for r in llm.requests:
        assert ORG_ID not in r.system and "TENANT-CANARY" not in r.system and r.cache_system_prompt
        assert "TENANT-CANARY" in r.messages[0].content


def test_s07_no_secret_in_sources() -> None:
    pat = re.compile(
        r"(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY|password\s*=)"
    )
    for p in (REPO / "packages/agents/agent_09_video_director").rglob("*.py"):
        assert not pat.search(p.read_text(encoding="utf-8")), p
    assert not list((REPO / "packages/agents/agent_09_video_director").rglob(".env*"))


def test_s08_the_socket_guard_is_active_and_a_plan_needs_no_network() -> None:
    with pytest.raises(AssertionError):
        socket.create_connection(("127.0.0.1", 9))
    script, durs = sample_script()
    assert make_step()[0].run(make_request(script, durs)).plan.shots


def test_s01_cross_tenant_blob_is_refused() -> None:
    out, _, store = run_task()
    other = TenantContext(org_id=ORG.new(), actor=actor_ref("agent_09"))
    ref = out.output_refs[0]
    with pytest.raises(CrossTenantRefError):
        b"".join(store.get(other, ref.uri, ref.sha256))


_ = (AspectRatio, NarrationTimeline, OutputRefData, TASK_ID, timeline_for)
