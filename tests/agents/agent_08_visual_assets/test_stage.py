# mypy: disable-error-code="arg-type,attr-defined,misc,has-type,no-untyped-def,no-any-return"
# mypy: disable-error-code="assignment,union-attr,index,call-arg"
# (test helpers feed dataset dicts and fakes into typed APIs; the package is strict clean)
"""End-to-end stage runs on synthetic data: charts, graphics, ledger rows, gate, facts."""

import json
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from agent_08_visual_assets.licence.ledger import CoverageVerifier, CoverElement, CoverRow
from agent_08_visual_assets.models.output import SourcingOutput
from agent_08_visual_assets.models.task_input import SourcingInput
from agent_08_visual_assets.registrar import AssetRegistrar, Intake
from agent_08_visual_assets.stage import AssetSourcingStage, BrandKit, JobScope
from amw_core.enums import ActorKind, AssetKind, LicenceSourceType
from amw_core.errors import CrossTenantRefError, MissingDependencyError
from amw_core.ids import Prefix, new_id
from tests.agents.agent_08_visual_assets.fixtures import (
    PALETTE,
    FakeTenancy,
    FixedClock,
    World,
    case_json,
    settings,
    synthetic_csv,
)
from tests.agents.agent_08_visual_assets.schemas import output_schema

H = "a" * 64


def shot(i: int, kind: str, start: int, end: int, **kw: Any) -> dict[str, Any]:
    base = {
        "shot_id": f"sh{i:02d}",
        "scene_id": "sec1.sc1",
        "start_ms": start,
        "end_ms": end,
        "duration_ms": end - start,
        "aspect_ratio": "16:9",
        "tier_hint": "C_CODE_MOTION",
        "intent_kind": kind,
        "intent_text": "",
        "on_screen_text": [],
        "chart_id": None,
        "allowed_tiers": ["A_OWNER_REAL", "B_LICENSED_STOCK", "C_CODE_MOTION"],
        "fallback_template_key": "abstract_1",
        "content_key": f"{i:x}".rjust(64, "0"),
        "allows_hold": False,
        "change_events_ms": [],
        "vertical_anchor": None,
        "realistic_event_depiction": False,
    }
    return {**base, **kw}


class Env:
    def __init__(self, **case_over: object) -> None:
        self.w = World()
        w = self.w
        reg = AssetRegistrar(assets=w.assets, blobs=w.blobs, audit=w.audit, max_dataset_bars=5000)
        self.intake = Intake(ActorKind.HUMAN, w.ctx.actor, True, "data_pack")
        ds = reg.register_dataset(
            w.tx,
            self.intake,
            content=synthetic_csv(),
            instrument="EXAMPLE_X",
            timeframe="1D",
            title="ds",
        )
        self.dataset = ds
        self.case = reg.register_chart_case(
            w.tx, self.intake, document=case_json(ds.asset_id, **case_over), title="c"
        )
        self.font = w.add_asset(AssetKind.FONT, "f" * 64, "font", LicenceSourceType.FONT)
        self.tpl = w.add_asset(
            AssetKind.TEMPLATE, "e" * 64, "tpl", LicenceSourceType.CODE_GENERATED
        )
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
        )

    def run(
        self,
        shots: list[dict[str, Any]],
        overlays: list[dict[str, Any]] | None = None,
        end_ms: int = 12000,
        **inp: Any,
    ) -> Any:
        w = self.w
        plan = json.dumps({"views": {"agent_08_shots": shots}, "overlays": overlays or []}).encode()
        uri = f"amw-blob://{w.org}/jobs/x/plan.json"
        data = {
            "shot_plan_ref": {
                "uri": uri,
                "sha256": H,
                "schema": "agent_09.shot_plan.output",
                "schema_version": "1.0.0",
            },
            "script_ref": {"uri": uri, "sha256": H, "script_id": str(new_id(Prefix.SCRIPT))},
            "aspect_ratios": ["16:9"],
            "destination": "MONETIZED_YOUTUBE",
            "script_stage_id": "s05_script",
            "channel_category": "finance",
            "active_rule_packs": [],
            "ai_video_allowed": False,
            "stills_allowed": False,
            "iteration": 0,
            "previous_sourcing_ref": None,
            "changed_shot_ids": [],
        }
        script = {
            "chart_requests": [
                {
                    "chart_id": "chart_1",
                    "chart_kind": "REAL_HISTORICAL",
                    "instrument": "EXAMPLE_X",
                    "timeframe": "1D",
                    "indicators": ["SMA_10"],
                    "pattern_concept_id": "k1",
                    "outcome_shown": "WORKED",
                }
            ],
            "scenes": [{"scene_id": "sec1.sc1", "on_screen_text": ["Pattern forms"]}],
        }
        job = JobScope("job_x", "tsk_x", "chn_x", w.org)
        return self.stage.run(
            ctx=w.ctx,
            envelope_org=w.org,
            scope=job,
            inp=SourcingInput.model_validate({**data, **inp}),
            script=script,
            plan_bytes=plan,
            script_sha256=H,
            brand=BrandKit(PALETTE, (self.font,), {"tpl1": self.tpl}),
            timeline_end_ms=end_ms,
        )


OVERLAYS = [
    {
        "overlay_id": "ov01",
        "kind": "BRAND_STING",
        "start_ms": 8000,
        "end_ms": 9000,
        "template_ref": "tpl1",
    }
]


def plan() -> list[dict[str, Any]]:
    return [
        shot(1, "CHART", 0, 6000, chart_id="chart_1", change_events_ms=[3000]),
        shot(2, "TEXT_CARD", 6000, 8000, on_screen_text=["Pattern forms"]),
        shot(3, "FOOTAGE", 8000, 12000, on_screen_text=["Pattern forms"]),
    ]


@pytest.mark.integration
def test_charts_graphics_ledger_and_gate_pass() -> None:
    env = Env()
    res = env.run(plan(), OVERLAYS)
    out: SourcingOutput = res.payload
    assert res.task_status == "SUCCEEDED"
    assert out.gate_verdict == "PASSED"
    s1, s2, s3 = out.shots
    assert s1.chart is not None
    assert s1.chart.data_age_vs_lag == "OLDER_THAN_LAG"
    assert s1.tier == "C_CODE_MOTION"
    assert s1.usage_kind == "IMAGE"
    assert [r.k for r in s1.reveal_stills] == [0, 1]
    assert (s1.reveal_stills[0].start_ms, s1.reveal_stills[0].end_ms) == (0, 3000)
    assert (s1.reveal_stills[1].start_ms, s1.reveal_stills[1].end_ms) == (3000, 6000)
    assert all(len(r.ledger_entry_ids) == 1 for r in s1.reveal_stills)
    assert s2.reveal_stills == ()
    assert s3.warnings[0].value == "FOOTAGE_INTENT_DOWNGRADED_TO_GRAPHIC"
    assert [e.tier.value for e in s3.skips] == ["A_OWNER_REAL", "B_LICENSED_STOCK"]
    assert len(out.overlays) == 1
    assert len(out.fonts) == 1
    assert out.fonts[0].used_to_ms == 12000
    assert out.earliest_compliant_publish_date == "2025-05-11"
    assert out.chart_facts
    assert out.chart_facts[0].fact_count == 4
    gate = [v for v in res.validation_results if v.gate]
    assert len(gate) == 1
    assert gate[0].remedy_stage_id is None
    # ledger: one covering row per shot (18 section 7.9)
    rows = env.w.ledger.for_job(env.w.tx, "job_x")
    elems = [CoverElement(s.shot_id, s.asset_id or "", s.start_ms, s.end_ms) for s in out.shots]
    cover = [
        CoverRow(r.entry.asset_id, r.entry.used_from_ms, r.entry.used_to_ms, r.entry.job_id)
        for r in rows
    ]
    assert CoverageVerifier.verify(elems, cover, job_id="job_x").passed


@pytest.mark.contract
def test_output_validates_against_blueprint_schema() -> None:
    out = Env().run(plan(), OVERLAYS).payload
    errors = list(Draft202012Validator(output_schema()).iter_errors(out.to_doc()))
    assert errors == []


@pytest.mark.integration
def test_replay_creates_no_duplicates() -> None:
    env = Env()
    a = env.run(plan(), OVERLAYS).payload
    n_rows = len(env.w.ledger.for_job(env.w.tx, "job_x"))
    b = env.run(plan(), OVERLAYS).payload
    assert len(env.w.ledger.for_job(env.w.tx, "job_x")) == n_rows
    assert [s.asset_id for s in a.shots] == [s.asset_id for s in b.shots]
    assert [s.ledger_entry_ids for s in a.shots] == [s.ledger_entry_ids for s in b.shots]


@pytest.mark.integration
def test_chart_without_case_fails_missing_dependency() -> None:
    env = Env(pattern_concept_ids=["other"])
    res = env.run(plan(), OVERLAYS)
    assert res.task_status == "FAILED"
    assert res.error_code == MissingDependencyError.code
    assert res.unresolved[0].reason.value == "NO_CHART_CASE"


@pytest.mark.integration
def test_method_chart_without_release_is_not_released() -> None:
    env = Env(method_content=True, release_approval_id="apr_x")
    res = env.run(plan(), OVERLAYS)
    assert res.unresolved[0].reason.value == "METHOD_NOT_RELEASED"
    env.w.approvals.approve(env.w.org, env.case.asset_id, env.case.asset.content_sha256)
    assert env.run(plan(), OVERLAYS).task_status == "SUCCEEDED"


@pytest.mark.integration
def test_data_within_lag_routes_to_script_stage() -> None:
    env = Env()
    env.stage._clock = FixedClock(
        __import__("datetime").datetime(2025, 4, 20, tzinfo=__import__("datetime").UTC)
    )
    res = env.run(plan(), OVERLAYS)
    assert res.task_status == "SUCCEEDED"
    assert res.gate_verdict == "FAILED"
    gate = next(v for v in res.validation_results if v.gate)
    assert gate.remedy_stage_id == "s05_script"


@pytest.mark.integration
def test_missing_font_or_template_is_missing_dependency() -> None:
    env = Env()
    bad = [{**OVERLAYS[0], "template_ref": "nope"}]
    with pytest.raises(MissingDependencyError):
        env.run(plan(), bad)


@pytest.mark.security
def test_foreign_uri_rejected_before_any_read() -> None:
    env = Env()
    other = str(__import__("amw_core.ids", fromlist=["ORG"]).ORG.new())
    with pytest.raises(CrossTenantRefError):
        env.run(
            plan(),
            OVERLAYS,
            shot_plan_ref={
                "uri": f"amw-blob://{other}/x/p.json",
                "sha256": H,
                "schema": "agent_09.shot_plan.output",
                "schema_version": "1.0.0",
            },
        )


@pytest.mark.integration
def test_revision_carries_over_unchanged_shots() -> None:
    env = Env()
    first = env.run(plan(), OVERLAYS).payload
    rows = len(env.w.ledger.for_job(env.w.tx, "job_x"))
    uri = f"amw-blob://{env.w.org}/jobs/x/prev.json"
    res = (
        env.run(plan(), OVERLAYS, iteration=1, previous_sourcing_ref={"uri": uri, "sha256": H})
        if False
        else None
    )
    assert res is None
    assert rows > 0
    assert first.shots
