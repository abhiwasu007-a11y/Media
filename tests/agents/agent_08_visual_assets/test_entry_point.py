# ruff: noqa: PT018
# mypy: disable-error-code="arg-type,index,no-untyped-def,union-attr"
"""PASS6-G: the ``TaskWorker`` entry point ``run(task_input, ctx)`` (CCR-203), the plan's
``total_duration_ms`` as the timeline end (CCR-205) and ``TemplateResolver`` (CCR-204).

The plan blob is Agent 09's real output: its step runs on its fake model, and the blob is the
whole ``agent_09.shot_plan.output`` document without ``plan_ref`` (plan model plus ``views``).
Agent 09 still emits ``template_ref = null`` for chapter and disclaimer cards (its CCR-204 part is
ticket PASS6-F); those entries are filled with the platform template IDs of agent_09 section 8.2,
and nothing else of the blob is touched.
"""

import hashlib
import io
import json
from typing import Any

import pytest

from agent_08_visual_assets.licence.timeline import OverlayInput, TimelineLedgerPlanner
from agent_08_visual_assets.models.shot_plan import ShotPlanReader
from agent_08_visual_assets.stage import AssetSourcingStage, BrandKit
from agent_08_visual_assets.templates import TemplateResolver
from agent_09_video_director.contracts import BrandKit as PlanBrandKit
from agent_09_video_director.views import build_views
from amw_core.contracts.task_input import TaskInput
from amw_core.enums import AssetKind, LicenceUsageKind, OutputStatus
from amw_core.errors import MissingDependencyError
from amw_core.exec_context import ExecContext
from amw_core.ids import (
    ATTEMPT,
    CHANNEL,
    CORRELATION,
    JOB,
    ORG,
    TASK,
    ActorRef,
    AttemptId,
    ChannelId,
    CorrelationId,
    JobId,
    OrgId,
    TaskId,
)
from amw_core.interfaces.storage import BlobUri
from amw_core.interfaces.tenancy_context import TenantContext
from tests.agents.agent_08_visual_assets.fixtures import PALETTE, FakeTenancy, FixedClock, settings
from tests.agents.agent_08_visual_assets.test_stage import Env
from tests.agents.agent_09_video_director.support import (
    make_request,
    make_step,
    sample_script,
)

PLATFORM_IDS = (
    "caption_card",
    "chapter_card",
    "disclaimer_card",
    "end_screen",
    "lower_third",
    "sting_a",
)
CARD_ID = {
    "CHAPTER_CARD": "chapter_card",
    "DISCLAIMER_CARD": "disclaimer_card",
    "CAPTION_CARD": "caption_card",
}


class Brands:
    def __init__(self, kit: BrandKit | None) -> None:
        self.kit = kit
        self.seen: list[tuple[str, str | None]] = []

    def brand_kit(self, tx, uri, sha256):
        self.seen.append((uri, sha256))
        return self.kit


class Jobs:
    """``jobs.monetized_destination`` of the task's job; ``None`` is an unreadable value."""

    def __init__(self, monetized: bool | None) -> None:
        self.monetized = monetized
        self.seen: list[str] = []

    def monetized_destination(self, tx, job_id):
        self.seen.append(job_id)
        return self.monetized


def real_plan() -> tuple[dict[str, Any], int]:
    script, durs = sample_script()
    step, _, _ = make_step()
    req = make_request(
        script,
        durs,
        brand=PlanBrandKit(
            intro_ref="sting_a",
            intro_duration_ms=1200,
            outro_ref="end_screen",
            lower_third_template_ref="lower_third",
        ),
    )
    res = step.run(req)
    doc = res.plan.model_dump(mode="json")
    doc["views"] = build_views(res.plan, script).model_dump(mode="json")
    for ov in doc["overlays"]:
        if ov["template_ref"] is None:
            ov["template_ref"] = CARD_ID[ov["kind"]]
    return doc, res.plan.total_duration_ms


def script_doc() -> dict[str, Any]:
    return {
        "chart_requests": [
            {
                "chart_id": "chart_hist1",
                "chart_kind": "REAL_HISTORICAL",
                "instrument": "EXAMPLE_X",
                "timeframe": "1D",
                "indicators": ["SMA_10"],
                "pattern_concept_id": "k1",
                "outcome_shown": "WORKED",
            }
        ],
        "scenes": [
            {"scene_id": s, "on_screen_text": ["Core idea", "First term", "Second term", "Key"]}
            for s in (
                "sec1.sc1",
                "sec1.sc2",
                "sec2.sc1",
                "sec2.sc2",
                "sec2.sc3",
                "sec3.sc1",
                "sec3.sc2",
            )
        ],
    }


class Rig:
    """One tenant, Agent 09's real plan and script blobs in storage, the stage with fakes."""

    def __init__(
        self,
        *,
        templates: tuple[str, ...] = PLATFORM_IDS,
        kit: bool = True,
        monetized: bool | None = True,
        with_jobs: bool = True,
    ) -> None:
        self.env = Env()
        w = self.env.w
        for i, tid in enumerate(templates):
            w.add_template(tid, f"{i + 1:x}".rjust(64, "a"))
        self.plan, self.total = real_plan()
        self.brands = Brands(BrandKit(PALETTE, (self.env.font,)) if kit else None)
        self.jobs = Jobs(monetized)
        self.stage = AssetSourcingStage(
            tenancy=FakeTenancy(),
            assets=w.assets,
            licences=w.licences,
            ledger=w.ledger,
            fingerprints=w.fps,
            approvals=w.approvals,
            blobs=w.blobs,
            clock=FixedClock(),
            settings=settings(),
            brand_kits=self.brands,
            job_destinations=self.jobs if with_jobs else None,
        )
        self.job, self.task = str(JOB.new()), str(TASK.new())
        self.attempt = str(ATTEMPT.new())
        self.cor = str(CORRELATION.new())
        self.chn = str(CHANNEL.new())
        self.ctx = ExecContext(
            tenant=TenantContext(OrgId(w.org), ActorRef("agent_08"), CorrelationId(self.cor)),
            job_id=JobId(self.job),
            task_id=TaskId(self.task),
            attempt_id=AttemptId(self.attempt),
            channel_id=ChannelId(self.chn),
            attempt_no=1,
            stage_id="s08_assets",
            iteration=0,
        )

    def put(self, name: str, body: bytes) -> tuple[str, str]:
        w = self.env.w
        uri = w.blobs.blob_uri(w.ctx, "jobs", f"{self.job}/{name}")
        if not w.blobs.head(w.ctx, uri).exists:
            w.blobs.put(w.ctx, uri, io.BytesIO(body))
        return str(uri), hashlib.sha256(body).hexdigest()

    def task_input(self, *, plan: dict[str, Any] | None = None, **over: Any) -> TaskInput:
        w = self.env.w
        plan_bytes = json.dumps(plan or self.plan).encode()
        script_bytes = json.dumps(script_doc()).encode()
        p_uri, p_sha = self.put("plan.json", plan_bytes)
        s_uri, s_sha = self.put("script.json", script_bytes)
        data = {
            "shot_plan_ref": {
                "uri": p_uri,
                "sha256": over.pop("plan_sha", p_sha),
                "schema": "agent_09.shot_plan.output",
                "schema_version": "1.0.0",
            },
            "script_ref": {
                "uri": s_uri,
                "sha256": s_sha,
                "script_id": "scr_" + "0" * 8 + "-0000-7000-8000-" + "0" * 12,
            },
            "aspect_ratios": ["16:9"],
            "destination": over.pop("destination", "MONETIZED_YOUTUBE"),
            "script_stage_id": "s05_script",
            "channel_category": "finance",
            "active_rule_packs": [],
            "ai_video_allowed": False,
            "stills_allowed": False,
            "iteration": 0,
            "previous_sourcing_ref": None,
            "changed_shot_ids": [],
        }
        refs = [
            {
                "uri": f"amw-blob://{w.org}/assets/brand_kit.json",
                "purpose": "BRAND_KIT",
                "sha256": "c" * 64,
            }
        ]
        return TaskInput.model_validate(
            {
                "org_id": w.org,
                "job_id": self.job,
                "task_id": self.task,
                "project_id": None,
                "channel_id": self.chn,
                "agent_id": over.pop("agent_id", "agent_08"),
                "source_agent": "agent_01",
                "priority": "NORMAL",
                "deadline": None,
                "context_refs": over.pop("context_refs", refs),
                "resource_budget": {
                    "max_cost_micros": 0,
                    "currency": "USD",
                    "max_wall_ms": 600000,
                    "max_llm_calls": 0,
                },
                "payload": {
                    "payload_schema": "agent_08.asset_sourcing.input",
                    "payload_schema_version": "1.0.0",
                    "data": data,
                },
                "correlation_id": self.cor,
                "idempotency_key": "idk_" + "ab" * 32,
                "retry_count": 0,
                "schema_version": "1.0.0",
            }
        )


@pytest.fixture(scope="module")
def good():
    rig = Rig()
    return rig, rig.stage.run(rig.task_input(), rig.ctx)


def test_real_plan_in_task_output_out(good) -> None:
    rig, out = good
    assert out.status is OutputStatus.SUCCEEDED, out.error
    assert out.payload is not None
    assert out.payload.payload_schema == "agent_08.asset_sourcing.output"
    assert out.payload.data["iteration"] == 0
    assert out.error is None and out.quality_score is None
    # the manifest blob is the first output ref, under the attempt's artifacts path (CCR-208)
    ref = out.output_refs[0]
    assert f"/jobs/{rig.job}/tasks/{rig.task}/attempts/{rig.attempt}/artifacts/" in ref.uri
    body = b"".join(rig.env.w.blobs.get(rig.env.w.ctx, BlobUri(ref.uri), ref.sha256))
    assert json.loads(body) == out.payload.data
    assert rig.brands.seen == [(f"amw-blob://{rig.env.w.org}/assets/brand_kit.json", "c" * 64)]


def test_end_screen_overlay_runs_to_total_duration_and_gets_a_template_row(good) -> None:
    rig, out = good
    data = out.payload.data
    end = next(o for o in data["overlays"] if o["kind"] == "END_SCREEN")
    assert end["end_ms"] == rig.total
    assert rig.total > max(s["end_ms"] for s in data["shots"])  # past the content end (CCR-205)
    assert end["usage_kind"] == "TEMPLATE" and end["template_asset_id"]
    assert end["ledger_entry_ids"]
    assert all(f["used_to_ms"] == rig.total for f in data["fonts"])
    rows = rig.env.w.ledger.for_job(rig.env.w.tx, rig.job)
    assert any(
        r.entry.usage_kind is LicenceUsageKind.TEMPLATE and r.entry.used_to_ms == rig.total
        for r in rows
    )


def test_every_overlay_resolves_to_the_asset_of_its_template_id(good) -> None:
    rig, out = good
    kinds = {o["kind"] for o in out.payload.data["overlays"]}
    assert {"BRAND_STING", "END_SCREEN", "DISCLAIMER_CARD"} <= kinds
    by_id = {
        o.asset.attributes["template_id"]: o.asset_id
        for o in rig.env.w.assets.list_assets(rig.env.w.tx, kinds=[AssetKind.TEMPLATE])
    }
    refs = {o["overlay_id"]: o["template_ref"] for o in rig.plan["overlays"]}
    for ov in out.payload.data["overlays"]:
        assert ov["template_asset_id"] == by_id[refs[ov["overlay_id"]]]


def test_all_3a_overlay_kinds_resolve_with_the_platform_ids() -> None:
    rig = Rig()
    tx = rig.env.w.tx
    got = TemplateResolver(rig.env.w.assets).resolve(tx, PLATFORM_IDS)
    assert set(got) == set(PLATFORM_IDS) and len(set(got.values())) == len(PLATFORM_IDS)


def test_unknown_template_id_fails_with_the_typed_violation() -> None:
    rig = Rig(templates=tuple(t for t in PLATFORM_IDS if t != "end_screen"))
    out = rig.stage.run(rig.task_input(), rig.ctx)
    assert out.status is OutputStatus.FAILED
    assert out.error.code == "PERMANENT.MISSING_DEPENDENCY"
    keywords = [v.keyword for v in out.error.details.violations]
    assert keywords == ["NO_TEMPLATE:end_screen"]
    assert out.payload is None


def test_resolver_reports_every_unknown_id_and_ignores_other_tenants_and_inactive_assets() -> None:
    rig = Rig(templates=("sting_a",))
    other = rig.env.w.second_tenant()
    other.add_template("end_screen", "9" * 64)  # another tenant's template is invisible
    with pytest.raises(MissingDependencyError) as ei:
        TemplateResolver(rig.env.w.assets).resolve(
            rig.env.w.tx, ["sting_a", "end_screen", "x_card"]
        )
    assert [v.keyword for v in ei.value.details["violations"]] == [
        "NO_TEMPLATE:end_screen",
        "NO_TEMPLATE:x_card",
    ]


def test_newest_asset_of_a_template_id_is_current() -> None:
    rig = Rig(templates=())
    w = rig.env.w
    first = w.add_template("end_screen", "1" * 64)
    second = w.add_template("end_screen", "2" * 64)
    got = TemplateResolver(w.assets).resolve(w.tx, ["end_screen"])["end_screen"]
    assert got in (first, second)
    newest = max((first, second), key=lambda a: (w.assets.get(w.tx, a).created_at, a))
    assert got == newest


def test_planner_names_the_missing_template_id_and_rejects_overlay_past_total() -> None:
    with pytest.raises(MissingDependencyError) as ei:
        TimelineLedgerPlanner.plan(
            [OverlayInput("ov01", "END_SCREEN", 0, 100, None, "end_screen")], ["f"], 200
        )
    assert ei.value.details["violations"][0].keyword == "NO_TEMPLATE:end_screen"
    from amw_core.errors import InputInvalidError

    with pytest.raises(InputInvalidError):
        TimelineLedgerPlanner.plan([OverlayInput("ov01", "END_SCREEN", 0, 300, "a")], ["f"], 200)


def test_total_duration_reader() -> None:
    assert ShotPlanReader.total_duration_ms({"total_duration_ms": 5}) == 5
    assert (
        ShotPlanReader.total_duration_ms(json.dumps({"data": {"total_duration_ms": 7}}).encode())
        == 7
    )
    from amw_core.errors import InputInvalidError

    for bad in (
        {},
        {"total_duration_ms": 0},
        {"total_duration_ms": "9"},
        {"total_duration_ms": True},
    ):
        with pytest.raises(InputInvalidError):
            ShotPlanReader.total_duration_ms(bad)


def test_entry_point_parameter_names_match_the_task_worker_protocol() -> None:
    from amw_core.interfaces.worker import TaskWorker

    want = TaskWorker.run.__code__.co_varnames[:3]
    assert AssetSourcingStage.run.__code__.co_varnames[:3] == want == ("self", "task_input", "ctx")


@pytest.mark.parametrize("field", ["org_id", "job_id", "task_id"])
def test_ctx_disagreeing_with_the_task_input_is_tenant_mismatch(field: str) -> None:
    from dataclasses import replace

    rig = Rig()
    ti = rig.task_input()
    other = {
        "org_id": ORG.new(),
        "job_id": JobId(str(JOB.new())),
        "task_id": TaskId(str(TASK.new())),
    }[field]
    ctx = (
        replace(rig.ctx, tenant=TenantContext(other, ActorRef("agent_08"), CorrelationId(rig.cor)))
        if field == "org_id"
        else replace(rig.ctx, **{field: other})
    )
    out = rig.stage.run(ti, ctx)
    assert out.status is OutputStatus.REJECTED
    assert out.error.code == "PERMANENT.TENANT_MISMATCH"


def test_matching_ctx_is_not_a_mismatch(good) -> None:
    assert good[1].error is None


def test_wrong_agent_hash_mismatch_and_missing_brand_kit_are_typed() -> None:
    rig = Rig()
    assert (
        rig.stage.run(rig.task_input(agent_id="agent_09"), rig.ctx).error.code
        == "PERMANENT.INPUT_INVALID"
    )
    bad = rig.stage.run(rig.task_input(plan_sha="0" * 64), rig.ctx)
    assert bad.status is OutputStatus.REJECTED and bad.error.code == "PERMANENT.INPUT_INVALID"
    nobrand = rig.stage.run(rig.task_input(context_refs=[]), rig.ctx)
    assert nobrand.error.code == "PERMANENT.MISSING_DEPENDENCY"
    empty = Rig(kit=False)
    assert (
        empty.stage.run(empty.task_input(), empty.ctx).error.code == "PERMANENT.MISSING_DEPENDENCY"
    )


def test_a_plan_blob_without_total_duration_is_input_invalid() -> None:
    rig = Rig()
    plan = {k: v for k, v in rig.plan.items() if k != "total_duration_ms"}
    out = rig.stage.run(rig.task_input(plan=plan), rig.ctx)
    assert out.error.code == "PERMANENT.INPUT_INVALID"


def test_a_later_attempt_writes_its_own_manifest_and_keeps_the_assets() -> None:
    from dataclasses import replace

    rig = Rig()
    ti = rig.task_input()
    a = rig.stage.run(ti, rig.ctx)
    b = rig.stage.run(ti, replace(rig.ctx, attempt_id=AttemptId(str(ATTEMPT.new())), attempt_no=2))
    assert a.status is b.status is OutputStatus.SUCCEEDED
    assert a.output_refs[0].uri != b.output_refs[0].uri
    assert [s["asset_id"] for s in a.payload.data["shots"]] == [
        s["asset_id"] for s in b.payload.data["shots"]
    ]
    assert [o["template_asset_id"] for o in a.payload.data["overlays"]] == [
        o["template_asset_id"] for o in b.payload.data["overlays"]
    ]


def test_the_entry_point_reads_the_job_destination_and_a_matching_payload_passes() -> None:
    rig = Rig(monetized=True)
    out = rig.stage.run(rig.task_input(destination="MONETIZED_YOUTUBE"), rig.ctx)
    assert out.status is OutputStatus.SUCCEEDED and out.error is None
    assert rig.jobs.seen == [rig.job]
    rig = Rig(monetized=False)
    out = rig.stage.run(rig.task_input(destination="NON_MONETIZED"), rig.ctx)
    assert out.status is OutputStatus.SUCCEEDED and out.error is None


def test_a_non_monetized_payload_on_a_monetized_job_does_not_relax_the_licence_gate() -> None:
    rig = Rig(monetized=True)
    out = rig.stage.run(rig.task_input(destination="NON_MONETIZED"), rig.ctx)
    assert out.status is not OutputStatus.SUCCEEDED
    assert out.error.code == "PERMANENT.INPUT_INVALID"
    assert out.payload is None and not out.output_refs
    assert not list(rig.env.w.ledger.for_job(rig.env.w.tx, rig.job))


def test_a_monetized_payload_on_a_non_monetized_job_is_refused_too() -> None:
    rig = Rig(monetized=False)
    out = rig.stage.run(rig.task_input(destination="MONETIZED_YOUTUBE"), rig.ctx)
    assert out.error.code == "PERMANENT.INPUT_INVALID"


def test_an_unreadable_job_destination_fails_closed() -> None:
    rig = Rig(monetized=None)
    for dest in ("MONETIZED_YOUTUBE", "NON_MONETIZED"):
        out = rig.stage.run(rig.task_input(destination=dest), rig.ctx)
        assert out.status is not OutputStatus.SUCCEEDED
        assert out.error.code == "PERMANENT.MISSING_DEPENDENCY"
        assert out.payload is None


def test_no_job_destination_reader_fails_closed() -> None:
    rig = Rig(with_jobs=False)
    out = rig.stage.run(rig.task_input(destination="NON_MONETIZED"), rig.ctx)
    assert out.status is not OutputStatus.SUCCEEDED
    assert out.error.code == "PERMANENT.CONFIG_INVALID"


def test_a_failed_gate_is_succeeded_with_continue_and_the_reason() -> None:
    import datetime as dt

    from amw_core.enums import NextActionType

    rig = Rig()
    rig.stage._clock = FixedClock(dt.datetime(2025, 4, 20, tzinfo=dt.UTC))
    out = rig.stage.run(rig.task_input(), rig.ctx)
    assert out.status is OutputStatus.SUCCEEDED
    assert out.payload.data["gate_verdict"] == "FAILED"
    assert out.next_action.type is NextActionType.CONTINUE
    assert out.next_action.reason.startswith("gate FAILED: ")
    assert out.error is None
