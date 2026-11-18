# ruff: noqa: E501
# mypy: disable-error-code="arg-type,attr-defined,misc,has-type,no-untyped-def,no-any-return"
# mypy: disable-error-code="assignment,union-attr,index,call-arg"
# (test helpers feed dataset dicts and fakes into typed APIs; the package is strict clean)
"""End-to-end stage runs on synthetic data: charts, graphics, ledger rows, gate, facts."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from agent_08_visual_assets.cascade.selection import Assessment, Fit
from agent_08_visual_assets.licence.ledger import CoverageVerifier, CoverElement, CoverRow
from agent_08_visual_assets.models.output import SourcingOutput
from agent_08_visual_assets.models.task_input import SourcingInput
from agent_08_visual_assets.persistence.records import LedgerEntry, NewAsset
from agent_08_visual_assets.registrar import AssetRegistrar, Intake
from agent_08_visual_assets.stage import AssetSourcingStage, BrandKit, FootageChoice, JobScope
from amw_core.enums import (
    ActorKind,
    AssetKind,
    AssetStatus,
    LicenceDestination,
    LicenceSourceType,
)
from amw_core.errors import (
    ConfigInvalidError,
    CrossTenantRefError,
    InputInvalidError,
    MissingDependencyError,
)
from amw_core.ids import ORG, Prefix, new_id
from amw_core.interfaces.storage import BlobUri
from tests.agents.agent_08_visual_assets.fixtures import (
    PALETTE,
    FakeTenancy,
    FixedClock,
    World,
    case_json,
    lic,
    settings,
    synthetic_csv,
)
from tests.agents.agent_08_visual_assets.schemas import output_schema


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
    def __init__(self, timeframe: str = "1D", dataset_step: int = 1, **case_over: object) -> None:
        self.w = World()
        start0 = date(2025, 1, 1) if dataset_step == 1 else date(2015, 1, 1)
        w = self.w
        reg = AssetRegistrar(assets=w.assets, blobs=w.blobs, audit=w.audit, max_dataset_bars=5000)
        self.intake = Intake(ActorKind.HUMAN, w.ctx.actor, True, "data_pack")
        ds = reg.register_dataset(
            w.tx,
            self.intake,
            content=synthetic_csv(start=start0, step=dataset_step),
            instrument="EXAMPLE_X",
            timeframe=timeframe,
            title="ds",
        )
        self.dataset = ds
        self.last_bar_start = start0 + timedelta(days=100 * dataset_step)
        self.case = reg.register_chart_case(
            w.tx,
            self.intake,
            document=case_json(ds.asset_id, timeframe=timeframe, **case_over),
            title="c",
        )
        self.font = w.add_font()
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
        *,
        timeframe: str = "1D",
        previous: Any = None,
        task_id: str = "tsk_x",
        world: World | None = None,
        plan_hash: str | None = None,
        **inp: Any,
    ) -> Any:
        w = world or self.w
        plan = json.dumps({"views": {"agent_08_shots": shots}, "overlays": overlays or []}).encode()
        script = {
            "chart_requests": [
                {
                    "chart_id": "chart_1",
                    "chart_kind": "REAL_HISTORICAL",
                    "instrument": "EXAMPLE_X",
                    "timeframe": timeframe,
                    "indicators": ["SMA_10"],
                    "pattern_concept_id": "k1",
                    "outcome_shown": "WORKED",
                }
            ],
            "scenes": [{"scene_id": "sec1.sc1", "on_screen_text": ["Pattern forms"]}],
        }
        script_bytes = json.dumps(script).encode()
        uri = f"amw-blob://{w.org}/jobs/x/plan.json"
        data = {
            "shot_plan_ref": {
                "uri": uri,
                "sha256": plan_hash or hashlib.sha256(plan).hexdigest(),
                "schema": "agent_09.shot_plan.output",
                "schema_version": "1.0.0",
            },
            "script_ref": {
                "uri": uri,
                "sha256": hashlib.sha256(script_bytes).hexdigest(),
                "script_id": str(new_id(Prefix.SCRIPT)),
            },
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
        job = JobScope("job_x", task_id, "chn_x", w.org)
        return self.stage.run(
            ctx=w.ctx,
            envelope_org=w.org,
            scope=job,
            inp=SourcingInput.model_validate({**data, **inp}),
            script_bytes=script_bytes,
            plan_bytes=plan,
            brand=BrandKit(PALETTE, (self.font,), {"tpl1": self.tpl}),
            timeline_end_ms=end_ms,
            previous=previous,
            job_destination=LicenceDestination.MONETIZED_YOUTUBE,
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
    other = str(ORG.new())
    with pytest.raises(CrossTenantRefError):
        env.run(
            plan(),
            OVERLAYS,
            shot_plan_ref={
                "uri": f"amw-blob://{other}/x/p.json",
                "sha256": "a" * 64,
                "schema": "agent_09.shot_plan.output",
                "schema_version": "1.0.0",
            },
        )


@pytest.mark.integration
def test_input_hash_mismatch_is_input_invalid() -> None:
    env = Env()
    with pytest.raises(InputInvalidError):
        env.run(plan(), OVERLAYS, plan_hash="b" * 64)
    env2 = Env()
    original = env2.stage.run

    def bad_script(**kw: Any) -> Any:
        return original(**{**kw, "script_bytes": kw["script_bytes"] + b" "})

    env2.stage.run = bad_script
    with pytest.raises(InputInvalidError):
        env2.run(plan(), OVERLAYS)


@pytest.mark.integration
def test_destination_must_match_job() -> None:
    env = Env()
    with pytest.raises(InputInvalidError):
        env.run(plan(), OVERLAYS, destination="NON_MONETIZED")


@pytest.mark.integration
def test_revision_re_sources_only_the_changed_shot() -> None:
    env = Env()
    first = env.run(plan(), OVERLAYS)
    rows_before = {e.ledger_entry_id for e in env.w.ledger.for_job(env.w.tx, "job_x")}
    changed = plan()
    changed[1] = shot(
        2, "TEXT_CARD", 6000, 8000, on_screen_text=["Pattern forms"], content_key="9" * 64
    )
    changed[1]["start_ms"] = 6000
    second = env.run(
        changed,
        OVERLAYS,
        iteration=1,
        previous=first.payload,
        task_id="tsk_y",
        previous_sourcing_ref={
            "uri": f"amw-blob://{env.w.org}/jobs/x/prev.json",
            "sha256": "c" * 64,
        },
    )
    a, b = first.payload, second.payload
    assert second.task_status == "SUCCEEDED"
    assert a.shots[0] == b.shots[0]
    assert a.shots[2] == b.shots[2]
    assert [f.chart_id for f in b.chart_facts] == ["chart_1"]
    # same asset and interval: the covering row is reused, nothing is written twice
    assert {e.ledger_entry_id for e in env.w.ledger.for_job(env.w.tx, "job_x")} == rows_before
    assert b.shots[1].ledger_entry_ids == a.shots[1].ledger_entry_ids
    # a changed asset writes exactly one new row
    third = plan()
    third[1] = shot(2, "TEXT_CARD", 6000, 8000, on_screen_text=["Other text"], content_key="8" * 64)
    out3 = env.run(
        third,
        OVERLAYS,
        iteration=2,
        previous=b,
        task_id="tsk_z",
        previous_sourcing_ref={
            "uri": f"amw-blob://{env.w.org}/jobs/x/prev.json",
            "sha256": "c" * 64,
        },
    ).payload
    now = {e.ledger_entry_id for e in env.w.ledger.for_job(env.w.tx, "job_x")}
    assert len(now - rows_before) == 1
    assert out3.shots[1].ledger_entry_ids[0] in now - rows_before
    assert out3.shots[0] == a.shots[0]


class FakeSelector:
    """Scripted tier-A selector: returns fixed assessments (the model is advisory)."""

    def __init__(self, fits: dict[str, tuple[str, tuple[str, ...]]], **kw: Any) -> None:
        self.fits, self.kw, self.calls = fits, kw, 0

    def select(self, shot: Any, candidates: Any) -> FootageChoice:
        self.calls += 1
        ass = tuple(
            Assessment(c.asset_id, Fit(self.fits[c.asset_id][0]), self.fits[c.asset_id][1])
            for c in candidates
            if c.asset_id in self.fits
        )
        order = tuple(a.candidate_id for a in ass)
        return FootageChoice(assessments=ass, order=order, **self.kw)


def _owner_env(sel: FakeSelector | None = None, n: int = 1, **asset: Any) -> tuple[Env, list[str]]:
    env = Env()
    ids = []
    for i in range(n):
        reg = AssetRegistrar(
            assets=env.w.assets, blobs=env.w.blobs, audit=env.w.audit, max_dataset_bars=10
        )
        rec = reg.register_owner_asset(
            env.w.tx, Intake(ActorKind.HUMAN, env.w.ctx.actor, True, "x"), content=f"clip{i}".encode(),
            kind=AssetKind.VIDEO, title=f"v{i}", width_px=1920, height_px=1080, duration_ms=20000,
        )  # fmt: skip
        ids.append(rec.asset_id)
    if sel is not None:
        env.stage._selector = sel
    return env, ids


def _footage_plan() -> list[dict[str, Any]]:
    return [shot(1, "FOOTAGE", 0, 4000)]


@pytest.mark.integration
def test_tier_a_owner_footage_sourced_with_floor_and_tiebreak() -> None:
    env, ids = _owner_env(n=3)
    sel = FakeSelector({
        ids[0]: ("ACCEPTABLE", ("ON_TOPIC",)),
        ids[1]: ("STRONG", ("ON_TOPIC", "SHOWS_BRAND_OR_LOGO")),  # floor forces REJECT
        ids[2]: ("STRONG", ("ON_TOPIC",)),
    })  # fmt: skip
    env.stage._selector = sel
    res = env.run(_footage_plan(), None, 4000)
    s1 = res.payload.shots[0]
    assert s1.tier == "A_OWNER_REAL"
    assert s1.asset_id == ids[2]
    assert s1.skips == ()
    assert s1.selection is not None
    assert s1.selection.fit == "STRONG"
    assert s1.source_type == "OWNER_MADE"
    assert s1.usage_kind == "SHOT"
    assert s1.media is not None
    assert s1.media.duration_ms == 20000
    assert sel.calls == 1
    assert res.task_status == "SUCCEEDED"
    assert any(
        v.check_id == "a08.asset.duration_cover" and v.verdict.value == "PASS"
        for v in res.validation_results
    )


@pytest.mark.integration
def test_tier_a_weak_fit_is_not_accepted() -> None:
    env, ids = _owner_env(FakeSelector({}), n=1)
    env.stage._selector = FakeSelector({ids[0]: ("WEAK", ("TOO_GENERIC",))})
    s1 = env.run(_footage_plan(), None, 4000).payload.shots[0]
    assert s1.tier == "C_CODE_MOTION"
    assert s1.skips[0].tier.value == "A_OWNER_REAL"
    assert s1.skips[0].reason.value == "NO_ACCEPTABLE_FIT"


@pytest.mark.integration
def test_tier_a_refusal_prohibited_and_missing_selector() -> None:
    env, ids = _owner_env(n=1)
    env.stage._selector = FakeSelector({ids[0]: ("STRONG", ("ON_TOPIC",))}, prohibited=True)
    s1 = env.run(_footage_plan(), None, 4000).payload.shots[0]
    assert s1.skips[0].reason.value == "PROHIBITED_DEPICTION"
    assert s1.tier == "C_CODE_MOTION"
    env.stage._selector = None
    with pytest.raises(ConfigInvalidError):
        env.run(_footage_plan(), None, 4000)


@pytest.mark.integration
def test_tier_a_candidate_filters() -> None:
    env, ids = _owner_env(n=1)
    sel = FakeSelector({ids[0]: ("STRONG", ("ON_TOPIC",))})
    env.stage._selector = sel
    for status in (AssetStatus.QUARANTINED, AssetStatus.EXPIRED):
        env.w.assets.set_status(env.w.org, ids[0], status)
        out = env.run(_footage_plan(), None, 4000).payload.shots[0]
        assert out.tier == "C_CODE_MOTION"
        assert out.skips[0].reason.value == "NO_CANDIDATE"
    assert sel.calls == 0
    env.w.assets.set_status(env.w.org, ids[0], AssetStatus.ACTIVE)
    short = plan_short = _footage_plan()
    short[0] = shot(1, "FOOTAGE", 0, 25000)  # longer than the 20 s clip: dropped
    assert env.run(short, None, 25000).payload.shots[0].tier == "C_CODE_MOTION"
    assert plan_short


@pytest.mark.integration
def test_client_supplied_needs_its_own_licence_row() -> None:
    env = Env()
    rec = env.w.assets.insert(
        env.w.tx,
        NewAsset(kind=AssetKind.VIDEO, source_type=LicenceSourceType.CLIENT_SUPPLIED, content_sha256="9" * 64,
                 uri=f"amw-blob://{env.w.org}/assets/client", size_bytes=1, title="c", width_px=1920, height_px=1080, duration_ms=20000),
    )  # fmt: skip
    env.stage._selector = FakeSelector({rec.asset_id: ("STRONG", ("ON_TOPIC",))})
    with pytest.raises(MissingDependencyError):  # never ledgered under the OWNER_MADE self-grant
        env.run(_footage_plan(), None, 4000)
    env.w.licences.add(lic(env.w.org, LicenceSourceType.CLIENT_SUPPLIED))
    out = env.run(_footage_plan(), None, 4000).payload.shots[0]
    assert out.source_type == "CLIENT_SUPPLIED"


@pytest.mark.integration
def test_validation_rows_are_measured_or_skipped() -> None:
    res = Env().run(plan(), OVERLAYS)
    by = {v.check_id: v for v in res.validation_results}
    expected = {
        "a08.pre.tenant", "a08.pre.refs", "a08.pre.shot_plan", "a08.pre.config", "a08.pre.licence_rows",
        "a08.pre.budget", "a08.pre.batch_size", "a08.cov.all_shots_resolved", "a08.cov.licence_row_per_shot",
        "a08.cov.overlay_rows", "a08.cov.font_rows", "a08.cov.interval_match", "a08.hier.skip_reasons_recorded",
        "a08.hier.tier_order", "a08.chart.data_age", "a08.chart.annotations", "a08.chart.provenance",
        "a08.chart.facts", "a08.lic.guard", "a08.lic.no_preview", "a08.lic.third_party", "a08.lic.expiry_window",
        "a08.ai.budget", "a08.ai.no_real_person", "a08.ai.disclosure_flags", "a08.tier.share_e",
        "a08.tier.mix_report", "a08.asset.resolution", "a08.asset.duration_cover", "a08.asset.crop",
        "a08.asset.fingerprint", "a08.reuse.channel_permission", "a08.reuse.report", "a08.cost.within_budget",
        "a08.output.refs", "a08.tenant.output_scope",
    }  # fmt: skip
    assert set(by) == expected
    assert len(res.validation_results) == len(expected)
    skipped = {k for k, v in by.items() if v.verdict.value == "SKIPPED"}
    assert {
        "a08.pre.budget",
        "a08.lic.no_preview",
        "a08.cost.within_budget",
        "a08.ai.budget",
    } <= skipped
    assert all(not by[k].blocking for k in skipped)
    assert by["a08.chart.annotations"].verdict.value == "PASS"
    assert by["a08.output.refs"].verdict.value == "PASS"
    # without charts nothing is claimed about charts
    nochart = {v.check_id: v for v in Env().run([plan()[1]], None, 8000).validation_results}
    assert nochart["a08.chart.data_age"].verdict.value == "SKIPPED"
    assert nochart["a08.chart.facts"].verdict.value == "SKIPPED"


@pytest.mark.integration
def test_coverage_check_fails_on_duplicates_and_on_zero() -> None:
    env = Env()
    res = env.run(plan(), OVERLAYS)
    rows = env.w.ledger.for_job(env.w.tx, "job_x")
    s2 = res.payload.shots[1]
    # a second covering row for the same asset: duplicate
    e = next(r for r in rows if r.entry.shot_id == s2.shot_id).entry
    env.w.ledger.write(env.w.tx, replace(e, shot_id="dupe"))
    again = env.run(plan(), OVERLAYS, task_id="tsk_x")
    v = {x.check_id: x for x in again.validation_results}["a08.cov.licence_row_per_shot"]
    assert v.verdict.value == "FAIL"
    assert again.task_status == "FAILED"
    # zero covering rows
    env2 = Env()
    env2.w.ledger.write = lambda tx, entry: LedgerEntry(
        str(new_id(Prefix.LICENCE_LEDGER_ENTRY)), env2.w.org, entry
    )
    z = env2.run(plan(), OVERLAYS)
    assert {x.check_id: x for x in z.validation_results}[
        "a08.cov.licence_row_per_shot"
    ].verdict.value == "FAIL"


@pytest.mark.integration
def test_reveal_last_still_has_exactly_one_row() -> None:
    env = Env()
    res = env.run(plan(), OVERLAYS)
    s1 = res.payload.shots[0]
    rows = [
        r.entry for r in env.w.ledger.for_job(env.w.tx, "job_x") if r.entry.asset_id == s1.asset_id
    ]
    assert len(rows) == 1
    assert s1.reveal_stills[-1].asset_id == s1.asset_id
    assert s1.reveal_stills[-1].ledger_entry_ids == s1.ledger_entry_ids


@pytest.mark.security
@pytest.mark.parametrize("which", ["case", "dataset"])
def test_research_folder_data_fails_closed(which: str) -> None:
    env = Env()
    rec = env.case if which == "case" else env.dataset
    env.w.assets._rows[env.w.org][rec.asset_id] = replace(
        rec,
        asset=replace(
            rec.asset, attributes={**rec.asset.attributes, "source_path_class": "research_folder"}
        ),
    )
    with pytest.raises(InputInvalidError):
        env.run(plan(), OVERLAYS)
    env.w.assets._rows[env.w.org][rec.asset_id] = replace(
        rec, asset=replace(rec.asset, source_type=LicenceSourceType.CLIENT_SUPPLIED)
    )
    with pytest.raises(InputInvalidError):
        env.run(plan(), OVERLAYS)


@pytest.mark.security
def test_quarantined_asset_is_never_reused_and_replay_is_stable() -> None:
    env = Env()
    first = env.run(plan(), OVERLAYS).payload
    assert env.run(plan(), OVERLAYS).payload.shots == first.shots  # SOURCED stays SOURCED
    for rec in env.w.assets.list_assets(env.w.tx, kinds=[AssetKind.CHART, AssetKind.IMAGE]):
        env.w.assets.set_status(env.w.org, rec.asset_id, AssetStatus.QUARANTINED)
    with pytest.raises(InputInvalidError):
        env.run(plan(), OVERLAYS, task_id="tsk_other")


@pytest.mark.integration
def test_reuse_across_jobs_is_reported() -> None:
    env = Env()
    env.run(plan(), OVERLAYS)
    out = env.run(plan(), OVERLAYS, task_id="tsk_other").payload
    assert out.shots[1].status.value == "REUSED"
    assert out.shots[1].reuse is not None
    assert out.reuse_summary.reused_exact >= 1


@pytest.mark.parametrize(
    ("timeframe", "step", "span"), [("1D", 1, 0), ("1W", 7, 6), ("1M", 31, 30)]
)
@pytest.mark.integration
def test_data_end_date_is_period_end_and_publish_date_is_end_plus_lag(
    timeframe: str, step: int, span: int
) -> None:
    env = Env(timeframe=timeframe, dataset_step=step)
    out = env.run(plan(), OVERLAYS, timeframe=timeframe).payload
    chart = out.shots[0].chart
    assert chart is not None
    assert chart.data_end_date is not None
    start = env.last_bar_start
    assert date.fromisoformat(chart.data_end_date) == start + timedelta(days=span)
    assert date.fromisoformat(chart.earliest_compliant_publish_date or "") == start + timedelta(
        days=span + 30
    )
    assert out.earliest_compliant_publish_date == chart.earliest_compliant_publish_date


@pytest.mark.parametrize(
    ("timeframe", "step", "span"), [("1D", 1, 0), ("1W", 7, 6), ("1M", 31, 30)]
)
@pytest.mark.integration
def test_lag_boundary_per_timeframe(timeframe: str, step: int, span: int) -> None:
    env = Env(timeframe=timeframe, dataset_step=step)
    end = env.last_bar_start + timedelta(days=span)
    for offset, expected in ((29, "FAILED"), (30, "PASSED")):  # age 29 within lag, 30 allowed
        env.stage._clock = FixedClock(
            datetime.combine(end + timedelta(days=offset), time(), tzinfo=UTC)
        )
        assert env.run(plan(), OVERLAYS, timeframe=timeframe).payload.gate_verdict == expected


@pytest.mark.tenancy
def test_two_tenants_share_repositories_without_seeing_each_other() -> None:
    a = Env()
    out_a = a.run(plan(), OVERLAYS).payload
    b_world = a.w.second_tenant()
    # tenant B on the SAME repositories: sees none of A's assets, ledger rows, cases, datasets
    assert b_world.assets.get(b_world.tx, a.dataset.asset_id) is None
    assert b_world.assets.list_assets(b_world.tx, kinds=[AssetKind.DOCUMENT]) == []
    assert b_world.ledger.for_job(b_world.tx, "job_x") == []
    assert b_world.assets.find_by_sha(b_world.tx, a.dataset.asset.content_sha256) is None
    assert b_world.fps.perceptual_library(b_world.tx) == []
    assert out_a.shots[0].asset_id is not None
    assert b_world.assets.get(b_world.tx, out_a.shots[0].asset_id) is None
    # a stage run for B finds no case (it cannot reach A's), and writes only under B
    b_env = a
    b_env.font, b_env.tpl = (
        b_world.add_font(),
        b_world.add_asset(AssetKind.TEMPLATE, "d" * 64, "tpl", LicenceSourceType.CODE_GENERATED),
    )
    res_b = b_env.run(plan(), OVERLAYS, world=b_world)
    assert res_b.task_status == "FAILED"
    assert res_b.unresolved[0].reason.value == "NO_CHART_CASE"
    # B's blob store view cannot read A's blob
    with pytest.raises(CrossTenantRefError):
        list(
            b_world.blobs.get(
                b_world.ctx, BlobUri(a.dataset.asset.uri), a.dataset.asset.content_sha256
            )
        )


@pytest.mark.integration
def test_font_used_for_rendering_is_the_ledgered_brand_font() -> None:
    env = Env()
    res = env.run(plan(), OVERLAYS)
    font_sha = env.w.assets.get(env.w.tx, env.font).asset.content_sha256
    assert res.payload.fonts[0].asset_id == env.font
    # the palette hash covers the font content, so a different font changes the chart bytes
    other = replace(PALETTE, font_sha256=font_sha)
    assert other.sha256() != PALETTE.sha256()
    env.font = env.w.add_asset(AssetKind.TEMPLATE, "1" * 64, "notfont", LicenceSourceType.FONT)
    with pytest.raises(MissingDependencyError):
        env.run(plan(), OVERLAYS)
