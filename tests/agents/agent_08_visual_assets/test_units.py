# mypy: disable-error-code="arg-type,attr-defined,misc,has-type,no-untyped-def,no-any-return"
# mypy: disable-error-code="assignment,union-attr,index,call-arg"
# (test helpers feed dataset dicts and fakes into typed APIs; the package is strict clean)
"""Unit, determinism, security and failure tests for the Agent 08 building blocks."""

import hashlib
import subprocess
import sys
from datetime import date
from decimal import Decimal

import pytest
from jsonschema import Draft202012Validator

from agent_08_visual_assets.cascade.share import TierMixReporter
from agent_08_visual_assets.charts.annotations import Annotation
from agent_08_visual_assets.charts.dataset import DatasetLoader
from agent_08_visual_assets.charts.facts import ChartFactsBuilder, FactBar
from agent_08_visual_assets.charts.render import BrandPalette, ChartRenderer, ChartRenderInput
from agent_08_visual_assets.models.output import ChartFact, ChartFactsDocument
from agent_08_visual_assets.registrar import AssetRegistrar, Intake
from agent_08_visual_assets.reuse.fingerprint import Fingerprinter, hamming
from agent_08_visual_assets.settings import AssetSettings
from agent_08_visual_assets.sources.graphics import GraphicKind, GraphicTemplateRenderer
from amw_core.enums import ActorKind, AssetKind, ChartDataKind, VisualSourceTier
from amw_core.errors import (
    ConfigInvalidError,
    CorruptedOutputError,
    CrossTenantRefError,
    InputInvalidError,
    PermissionDeniedError,
)
from tests.agents.agent_08_visual_assets.fixtures import PALETTE, World, settings, synthetic_csv
from tests.agents.agent_08_visual_assets.schemas import facts_schema


def _series() -> object:
    data = synthetic_csv()
    return DatasetLoader.load(data, expected_sha256=hashlib.sha256(data).hexdigest(), max_bars=5000)


def _spec(series: object, w: int = 800, h: int = 450) -> ChartRenderInput:
    bars = series.bars
    return ChartRenderInput(
        bars,
        5,
        60,
        "EX 1D",
        ("SMA_5", "RSI_14"),
        (Annotation(kind="MARK_BAR", bar=30),),
        w,
        h,
        PALETTE,
    )


@pytest.mark.unit
def test_render_is_byte_deterministic_and_reveal_never_exceeds_window() -> None:
    spec = _spec(_series())
    a, b = ChartRenderer.render(spec), ChartRenderer.render(spec)
    assert a.sha256 == b.sha256
    assert a.png[:8] == b"\x89PNG\r\n\x1a\n"
    assert b"Software" not in a.png
    seq = ChartRenderer.reveal_sequence(spec, 3)
    assert len(seq) == 3
    assert len({r.sha256 for r in seq}) == 3
    assert seq[-1].sha256 == a.sha256


@pytest.mark.unit
def test_render_identical_in_another_process() -> None:
    code = (
        "import hashlib,sys;sys.path.insert(0,'.');"
        "from tests.agents.agent_08_visual_assets.test_units import _series,_spec;"
        "from agent_08_visual_assets.charts.render import ChartRenderer;"
        "print(ChartRenderer.render(_spec(_series())).sha256)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)  # noqa: S603
    assert out.stdout.strip() == ChartRenderer.render(_spec(_series())).sha256


@pytest.mark.unit
def test_unknown_indicator_and_both_aspects() -> None:
    series = _series()
    with pytest.raises(InputInvalidError):
        ChartRenderer.render(
            ChartRenderInput(series.bars, 0, 10, "t", ("MAGIC_9",), (), 400, 300, PALETTE)
        )
    vertical = ChartRenderer.render(_spec(series, 450, 800))
    assert (vertical.width_px, vertical.height_px) == (450, 800)


@pytest.mark.unit
def test_schematic_and_graphics() -> None:
    img = ChartRenderer.render_schematic(
        [Decimal(1), Decimal(3), Decimal(2)], width_px=640, height_px=360, palette=PALETTE
    )
    assert img.png
    kw = {"width_px": 640, "height_px": 360, "palette": PALETTE, "allowlist": ["Hello"]}
    card = GraphicTemplateRenderer.render(kind=GraphicKind.TITLE_CARD, lines=["Hello"], **kw)
    assert (
        card.sha256
        == GraphicTemplateRenderer.render(kind=GraphicKind.TITLE_CARD, lines=["Hello"], **kw).sha256
    )
    with pytest.raises(InputInvalidError):
        GraphicTemplateRenderer.render(kind=GraphicKind.TITLE_CARD, lines=["Invented"], **kw)
    with pytest.raises(InputInvalidError):
        GraphicTemplateRenderer.render(kind=GraphicKind.ABSTRACT_MOTION, lines=["words"], **kw)
    assert GraphicTemplateRenderer.render(kind=GraphicKind.ABSTRACT_MOTION, lines=[], **kw).png


@pytest.mark.unit
def test_dataset_loader_rules() -> None:
    good = synthetic_csv(5)
    sha = hashlib.sha256(good).hexdigest()
    assert len(DatasetLoader.load(good, expected_sha256=sha, max_bars=10)) == 5
    with pytest.raises(CorruptedOutputError):
        DatasetLoader.load(good, expected_sha256="0" * 64, max_bars=10)
    for bad in (
        b"date,open,high,low\n",
        b"date,open,high,low,close\n2025-01-01,1,2,0.5,NaN\n",
        b"date,open,high,low,close\n2025-01-02,1,2,0.5,1\n2025-01-01,1,2,0.5,1\n",
        b"date,open,high,low,close\n2025-01-01,1,0.5,0.4,1\n",
        b"date,open,high,low,close\nx,1,2,0.5,1\n",
        b"date,open,high,low,close\n",
        b"date,open,high,low,close\n2025-01-01,a,2,0.5,1\n",
    ):
        with pytest.raises(InputInvalidError):
            DatasetLoader.parse(bad, max_bars=10, sha256="x")
    with pytest.raises(InputInvalidError):
        DatasetLoader.parse(good, max_bars=2, sha256="x")


@pytest.mark.contract
def test_chart_facts_document_matches_schema_and_has_no_direction_words() -> None:
    bars = [
        FactBar(date(2020, 1, 1 + i), Decimal("10"), Decimal(11 + i), Decimal("9"), Decimal(10 + i))
        for i in range(4)
    ]
    facts = ChartFactsBuilder.build(ChartDataKind.REAL_HISTORICAL, "1W", bars)
    doc = ChartFactsDocument(
        chart_id="chart_1",
        instrument="X",
        dataset_asset_id="ast_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e0c",
        dataset_sha256="a" * 64,
        data_start_date="2020-01-01",
        data_end_date="2020-01-04",
        facts=tuple(ChartFact(fact_id=f.fact_id, statement=f.statement) for f in facts.facts),
    )
    assert list(Draft202012Validator(facts_schema()).iter_errors(doc.to_doc())) == []
    text = " ".join(f.statement for f in facts.facts).lower()
    assert "weekly" in text
    assert not {
        "rise",
        "fall",
        "bullish",
        "bearish",
        "will",
        "forecast",
    } & set(text.split())
    with pytest.raises(InputInvalidError):
        ChartFactsBuilder.build(ChartDataKind.REAL_HISTORICAL, "1D", [])
    with pytest.raises(InputInvalidError):
        ChartFactsBuilder.build(
            ChartDataKind.REAL_HISTORICAL, "1D", [FactBar(date(2020, 1, 1), *[Decimal(0)] * 4)]
        )


@pytest.mark.unit
def test_tier_mix_sums_to_1000() -> None:
    total, shares = TierMixReporter.report(
        {VisualSourceTier.A_OWNER_REAL: 1, VisualSourceTier.C_CODE_MOTION: 2}
    )
    assert total == 3
    assert sum(s.share_permille for s in shares.values()) == 1000
    with pytest.raises(InputInvalidError):
        TierMixReporter.report({})


@pytest.mark.unit
def test_fingerprint_still_is_deterministic_and_hamming_validates() -> None:
    png = ChartRenderer.render(_spec(_series())).png
    fp = Fingerprinter.still(png)
    assert fp == Fingerprinter.still(png)
    assert len(fp.perceptual_frames) == 1
    with pytest.raises(InputInvalidError):
        hamming("abc", "def")
    with pytest.raises(InputInvalidError):
        Fingerprinter.still(b"not an image")


@pytest.mark.unit
def test_settings_validation() -> None:
    with pytest.raises(ConfigInvalidError):
        settings(price_data_lag_days=10)
    with pytest.raises(ConfigInvalidError):
        AssetSettings.from_mapping({})
    assert settings().stock_enabled is False
    assert settings().ai_video_max_clips_per_video == 0


@pytest.mark.security
def test_registrar_refuses_agent_and_research_folder() -> None:
    w = World()
    reg = AssetRegistrar(assets=w.assets, blobs=w.blobs, audit=w.audit, max_dataset_bars=100)
    csv = synthetic_csv(5)
    kw = {"content": csv, "instrument": "X", "timeframe": "1D", "title": "t"}
    with pytest.raises(PermissionDeniedError):
        reg.register_dataset(w.tx, Intake(ActorKind.AGENT, "agent_08", True, "data_pack"), **kw)
    with pytest.raises(InputInvalidError):
        reg.register_dataset(
            w.tx, Intake(ActorKind.HUMAN, w.ctx.actor, True, "research_folder"), **kw
        )
    with pytest.raises(PermissionDeniedError):
        reg.register_dataset(
            w.tx, Intake(ActorKind.HUMAN, w.ctx.actor, True, "data_pack", "WRITE"), **kw
        )
    assert w.audit.actions(w.org).count("asset_intake.record_refused") == 3
    ok = reg.register_dataset(w.tx, Intake(ActorKind.HUMAN, w.ctx.actor, True, "data_pack"), **kw)
    assert w.audit.actions(w.org).count("asset_intake.recorded_from_owner_chat") == 1
    assert not any(a.startswith("asset_registrar.") for a in w.audit.actions(w.org))
    assert ok.asset.attributes["source_path_class"] == "data_pack"
    assert ok.asset.attributes["bars_count"] == 5
    with pytest.raises(InputInvalidError):
        reg.register_chart_case(
            w.tx, Intake(ActorKind.HUMAN, w.ctx.actor, True, "data_pack"), document=b"{}", title="x"
        )
    owner = reg.register_owner_asset(
        w.tx,
        Intake(ActorKind.HUMAN, w.ctx.actor, True, "anything"),
        content=b"clip",
        kind=AssetKind.VIDEO,
        title="v",
        tags=("field",),
    )
    assert owner.asset.visual_source_tier is VisualSourceTier.A_OWNER_REAL
    with pytest.raises(PermissionDeniedError):
        reg.register_owner_asset(
            w.tx,
            Intake(ActorKind.AGENT, "agent_08", True, "x"),
            content=b"c",
            kind=AssetKind.VIDEO,
            title="v",
        )
    with pytest.raises(InputInvalidError):
        reg.register_owner_asset(
            w.tx,
            Intake(ActorKind.HUMAN, w.ctx.actor, True, "x"),
            content=b"c",
            kind=AssetKind.CHART,
            title="v",
        )


@pytest.mark.tenancy
def test_tenant_isolation_of_repos_and_blobs() -> None:
    a, b = World(), World()
    a.assets.insert(
        a.tx,
        __import__("agent_08_visual_assets.persistence.records", fromlist=["NewAsset"]).NewAsset(
            kind=AssetKind.IMAGE,
            source_type=__import__(
                "amw_core.enums", fromlist=["LicenceSourceType"]
            ).LicenceSourceType.OWNER_MADE,
            content_sha256="1" * 64,
            uri="u",
            size_bytes=1,
            title="t",
        ),
    )
    assert a.assets.find_by_sha(a.tx, "1" * 64) is not None
    assert b.assets.find_by_sha(b.tx, "1" * 64) is None
    uri = a.blobs.blob_uri(a.ctx, "assets", "x")
    with pytest.raises(CrossTenantRefError):
        b.blobs.head(b.ctx, uri)


@pytest.mark.security
def test_tampered_dataset_blob_is_never_rendered() -> None:
    from tests.agents.agent_08_visual_assets.test_stage import OVERLAYS, Env, plan

    env = Env()
    env.w.blobs.tamper(env.dataset.asset.uri, b"date,open,high,low,close\n")
    with pytest.raises(CorruptedOutputError):
        env.run(plan(), OVERLAYS)


@pytest.mark.unit
def test_lag_floor_default_palette_hash_changes() -> None:
    other = BrandPalette(
        "#000000", "#ffffff", "#111111", "#00ff00", "#ff0000", "#ffff00", "#0000ff"
    )
    assert PALETTE.sha256() != other.sha256()
