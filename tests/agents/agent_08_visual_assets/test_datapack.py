# mypy: disable-error-code="arg-type,attr-defined,misc,has-type,no-untyped-def,no-any-return"
# mypy: disable-error-code="assignment,union-attr,index,call-arg,no-untyped-call,type-arg"
# (test helpers feed dataset dicts and fakes into typed APIs; the package is strict clean)
"""data_pack chart scenes (tier C): reader port, per-bar lag, RSI, rendering, facts, registration.

Every bar here is SYNTHETIC, generated at test time; no market data is read or committed.
"""

import io
import random
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from PIL import Image
from pydantic import ValidationError

from agent_06_fact_checker.models import DataAge
from agent_06_fact_checker.price_age import classify
from agent_08_visual_assets.charts.annotations import Annotation
from agent_08_visual_assets.charts.datapack import (
    DataPackSettings,
    FileDataPackReader,
    MemoryDataPackReader,
)
from agent_08_visual_assets.charts.datapack_builder import (
    SOURCE_LABEL,
    ChartFontCheck,
    Connector,
    DataPackChartBuilder,
    DataPackChartRegistrar,
    DataPackChartRequest,
    DataPackLagGuard,
    is_data_within_lag,
    provenance_json,
)
from agent_08_visual_assets.charts.dataset import Bar
from agent_08_visual_assets.charts.fonts import PinnedFontResolver
from agent_08_visual_assets.charts.render import rsi
from amw_core.enums import AssetKind, DataAgeVsLag, LicenceSourceType, VisualSourceTier
from amw_core.errors import ConfigInvalidError, InputInvalidError, MissingDependencyError
from tests.agents.agent_08_visual_assets.fixtures import PALETTE, World
from tests.agents.agent_08_visual_assets.schemas import facts_schema

ROOT = Path(__file__).resolve().parents[3]
FONT_MANIFEST = (
    ROOT
    / "packages/agents/agent_11_thumbnail_design/src/agent_11_thumbnail_design/data/fonts"
    / "manifest.json"
)
DS_ID = "ast_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e0c"
AS_OF = date(2026, 6, 1)


def pack_csv(
    n: int = 260, start: date = date(2025, 1, 1), step: int = 1, seed: int = 11, header: str = ""
) -> bytes:
    """Synthetic daily rows in the data_pack layout (``timestamp`` first, extra columns)."""
    rnd = random.Random(seed)  # noqa: S311
    price = 100.0
    rows = [header or "timestamp,open,high,low,close,volume"]
    for i in range(n):
        o, c = price, price + rnd.uniform(-2, 2)
        h, low = max(o, c) + rnd.uniform(0, 1), min(o, c) - rnd.uniform(0, 1)
        price = c
        rows.append(f"{start + timedelta(days=i * step)},{o:.2f},{h:.2f},{low:.2f},{c:.2f},0")
    return ("\n".join(rows) + "\n").encode()


def palette():
    font = PinnedFontResolver.resolve(FONT_MANIFEST)
    return replace(PALETTE, font_path=str(font.path), font_sha256=font.sha256)


def builder(reader=None, **over):
    kw = {
        "reader": reader or MemoryDataPackReader({"SYN@1D": pack_csv()}),
        "palette": palette(),
        "lag_days": 30,
        "platform_min_lag_days": 30,
        "width_px": 1920,
        "height_px": 1080,
    }
    kw.update(over)
    return DataPackChartBuilder(**kw)


def request(**over):
    base = {
        "chart_id": "chart_syn",
        "instrument": "SYN",
        "timeframe": "1D",
        "window_start": date(2025, 3, 1),
        "window_end": date(2025, 6, 30),
        "indicators": ("RSI_14",),
        "connectors": (
            Connector(from_offset=10, to_offset=60, panel="PRICE", anchor="HIGH"),
            Connector(from_offset=10, to_offset=60, panel="RSI"),
        ),
        "annotations": (Annotation(kind="LABEL", bar=60, text="Historical example"),),
        "rsi_guides": (30.0, 70.0),
    }
    base.update(over)
    return DataPackChartRequest(**base)


def bars_ending(last: date, n: int = 5, step: int = 1) -> list[Bar]:
    from decimal import Decimal

    d = Decimal(10)
    return [Bar(last - timedelta(days=(n - 1 - i) * step), d, d, d, d) for i in range(n)]


# -- lag per bar -------------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(("age", "ok"), [(30, True), (29, False), (31, True)])
def test_lag_boundary_daily(age: int, ok: bool) -> None:
    bars = bars_ending(AS_OF - timedelta(days=age))
    kw = {
        "timeframe": "1D",
        "as_of": AS_OF,
        "lag_days": 30,
        "platform_min_lag_days": 30,
        "clip_to_lag": False,
    }
    if ok:
        keep, proof = DataPackLagGuard.check(bars, **kw)
        assert keep == len(bars)
        assert proof.age_days == age
        assert proof.data_age_vs_lag is DataAgeVsLag.OLDER_THAN_LAG
        assert proof.cutoff_date == AS_OF - timedelta(days=30)
        assert proof.data_end_date <= proof.cutoff_date
        assert proof.earliest_compliant_publish_date == proof.data_end_date + timedelta(days=30)
    else:
        with pytest.raises(InputInvalidError) as exc:
            DataPackLagGuard.check(bars, **kw)
        assert is_data_within_lag(exc.value)
        assert exc.value.details["bars_within_lag"] == 1


@pytest.mark.unit
@pytest.mark.parametrize("age", range(25, 36))
def test_lag_arithmetic_matches_agent_06_classify(age: int) -> None:
    last = AS_OF - timedelta(days=age)
    ours = True
    try:
        DataPackLagGuard.check(
            bars_ending(last),
            timeframe="1D",
            as_of=AS_OF,
            lag_days=30,
            platform_min_lag_days=30,
            clip_to_lag=False,
        )
    except InputInvalidError:
        ours = False
    assert ours == (classify(last, AS_OF, 30) is DataAge.OLDER_THAN_LAG)


@pytest.mark.unit
@pytest.mark.parametrize(("bar_age", "ok"), [(36, True), (35, False)])
def test_weekly_bar_covers_its_whole_week(bar_age: int, ok: bool) -> None:
    bars = bars_ending(AS_OF - timedelta(days=bar_age), n=3, step=7)
    kw = {"as_of": AS_OF, "lag_days": 30, "platform_min_lag_days": 30, "clip_to_lag": False}
    if ok:
        assert DataPackLagGuard.check(bars, timeframe="1W", **kw)[1].age_days == 30
    else:
        with pytest.raises(InputInvalidError):
            DataPackLagGuard.check(bars, timeframe="1W", **kw)


@pytest.mark.unit
def test_window_with_newer_bars_is_refused_never_truncated() -> None:
    b = builder()
    # the series runs 2025-01-01 + 259 days; as_of puts its last 9 bars (ages 21..29 days)
    # inside the lag
    last_bar = date(2025, 1, 1) + timedelta(days=259)
    as_of = last_bar + timedelta(days=21)
    req = request(window_end=last_bar)
    with pytest.raises(InputInvalidError) as exc:
        b.build(req, as_of=as_of, dataset_asset_id=DS_ID)
    assert is_data_within_lag(exc.value)
    assert exc.value.details["bars_within_lag"] == 9
    assert exc.value.details["cutoff_date"] == (as_of - timedelta(days=30)).isoformat()
    clipped = b.build(
        req.model_copy(update={"clip_to_lag": True}), as_of=as_of, dataset_asset_id=DS_ID
    )
    assert clipped.lag.bars_clipped == 9
    assert clipped.lag.last_bar_date == last_bar - timedelta(days=9)
    assert clipped.provenance["lag_check"]["bars_clipped"] == 9


@pytest.mark.unit
def test_clip_with_no_old_bar_left_is_refused() -> None:
    bars = bars_ending(AS_OF - timedelta(days=3))
    with pytest.raises(InputInvalidError) as exc:
        DataPackLagGuard.check(
            bars,
            timeframe="1D",
            as_of=AS_OF,
            lag_days=30,
            platform_min_lag_days=30,
            clip_to_lag=True,
        )
    assert is_data_within_lag(exc.value)


@pytest.mark.unit
def test_future_bar_and_low_lag_are_refused() -> None:
    with pytest.raises(InputInvalidError):
        DataPackLagGuard.check(
            bars_ending(AS_OF + timedelta(days=1)),
            timeframe="1D",
            as_of=AS_OF,
            lag_days=30,
            platform_min_lag_days=30,
            clip_to_lag=True,
        )
    with pytest.raises(ConfigInvalidError):
        builder(lag_days=29)


# -- configuration and reader ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"charts.data_pack_root": ""},
        {"charts.data_pack_root": "/x"},
        {"charts.data_pack_root": "/x", "charts.data_pack_files": {}},
        {"charts.data_pack_root": "/x", "charts.data_pack_files": {"SYN@1D": "../a.csv"}},
        {"charts.data_pack_root": "/x", "charts.data_pack_files": {"SYN@5M": "a.csv"}},
    ],
)
def test_missing_or_bad_data_pack_config_fails_closed(raw: dict) -> None:
    with pytest.raises(ConfigInvalidError):
        DataPackSettings.from_mapping(raw, max_bars=1000)


@pytest.mark.unit
def test_root_that_is_not_a_directory_is_config_invalid(tmp_path: Path) -> None:
    s = DataPackSettings.from_mapping(
        {
            "charts.data_pack_root": str(tmp_path / "absent"),
            "charts.data_pack_files": {"SYN@1D": "syn.csv"},
        },
        max_bars=1000,
    )
    with pytest.raises(ConfigInvalidError):
        FileDataPackReader(s)


@pytest.mark.unit
def test_file_reader_reads_configured_files_only(tmp_path: Path) -> None:
    (tmp_path / "syn.csv").write_bytes(pack_csv(50))
    s = DataPackSettings.from_mapping(
        {
            "charts.data_pack_root": str(tmp_path),
            "charts.data_pack_files": {"SYN@1D": "syn.csv", "OTH@1D": "missing.csv"},
        },
        max_bars=1000,
    )
    reader = FileDataPackReader(s)
    with pytest.raises(ConfigInvalidError):  # every configured file must exist (manifest)
        reader.load("SYN", "1D")
    (tmp_path / "missing.csv").write_bytes(pack_csv(10, seed=3))
    reader = FileDataPackReader(s)
    series = reader.load("SYN", "1D")
    assert len(series.bars) == 50
    first = reader.manifest_sha256()
    assert series.manifest_sha256 == first
    with pytest.raises(MissingDependencyError):
        reader.load("NONE", "1D")
    with pytest.raises(InputInvalidError):
        reader.load("SYN", "5M")
    (tmp_path / "missing.csv").write_bytes(pack_csv(11, seed=3))
    assert FileDataPackReader(s).manifest_sha256() != first


@pytest.mark.unit
@pytest.mark.parametrize(
    "body",
    [
        "2025-01-01,1,2,0.5,abc,0",
        "2025-01-01 09:15:00,1,2,0.5,1.5,0",
        "2025-01-01,1,2,0.5,1.5,0,9",
        "2025-01-01,1,0.4,0.5,1.5,0",
        "2025-01-01,1,2,0.5,,0",
        "01/01/2025,1,2,0.5,1.5,0",
        "2025-01-02,1,2,0.5,1.5,0\n2025-01-01,1,2,0.5,1.5,0",
        "2025-01-01,1,2,0.5,nan,0",
    ],
)
def test_malformed_rows_are_refused(body: str) -> None:
    reader = MemoryDataPackReader(
        {"SYN@1D": ("timestamp,open,high,low,close,volume\n" + body + "\n").encode()}
    )
    with pytest.raises(InputInvalidError):
        reader.load("SYN", "1D")


@pytest.mark.unit
def test_bad_header_and_bar_cap_are_refused() -> None:
    with pytest.raises(InputInvalidError):
        MemoryDataPackReader({"SYN@1D": b"when,open,high,low,close\n"}).load("SYN", "1D")
    with pytest.raises(InputInvalidError):
        MemoryDataPackReader({"SYN@1D": pack_csv(20)}, max_bars=10).load("SYN", "1D")


@pytest.mark.unit
def test_window_without_bars_is_refused() -> None:
    with pytest.raises(InputInvalidError):
        builder().build(
            request(window_start=date(2030, 1, 1), window_end=date(2030, 2, 1)),
            as_of=AS_OF,
            dataset_asset_id=DS_ID,
        )


# -- RSI ---------------------------------------------------------------------------------------


@pytest.mark.unit
def test_rsi_matches_hand_computed_wilder_values() -> None:
    # changes +1 +1 -1 +1 +1; period 3
    # bar 3: avg gain 2/3, avg loss 1/3 -> RS 2 -> 66.666..
    # bar 4: gain (2/3*2+1)/3 = 7/9, loss (1/3*2)/3 = 2/9 -> RS 3.5 -> 77.777..
    # bar 5: gain (7/9*2+1)/3 = 23/27, loss (2/9*2)/3 = 4/27 -> RS 5.75 -> 85.185..
    out = rsi([1.0, 2.0, 3.0, 2.0, 3.0, 4.0], 3)
    assert out[:3] == [None, None, None]
    assert out[3] == pytest.approx(100 - 100 / 3)
    assert out[4] == pytest.approx(100 - 100 / 4.5)
    assert out[5] == pytest.approx(100 - 100 / 6.75)
    assert rsi([1.0, 2.0, 3.0, 4.0], 2)[2:] == [100.0, 100.0]
    assert rsi([1.0, 2.0], 3) == [None, None]


# -- rendering, fonts, facts -------------------------------------------------------------------


@pytest.mark.unit
def test_render_is_byte_identical_and_layout_holds() -> None:
    b = builder()
    one = b.build(request(reveal_steps=3), as_of=AS_OF, dataset_asset_id=DS_ID)
    two = b.build(request(reveal_steps=3), as_of=AS_OF, dataset_asset_id=DS_ID)
    assert [s.png for s in one.stills] == [s.png for s in two.stills]
    assert one.spec_sha256 == two.spec_sha256
    assert len(one.stills) == 3
    img = Image.open(io.BytesIO(one.png))
    assert img.size == (1920, 1080)
    assert "Software" not in img.info
    boxes = dict(one.stills[-1].text_boxes)
    assert set(boxes) == {"title", "footer_0", "footer_1"}
    for x0, y0, x1, y1 in boxes.values():  # every template text is inside the canvas
        assert 0 <= x0 < x1 <= 1920
        assert 0 <= y0 < y1 <= 1080
    assert boxes["footer_0"][1] >= boxes["footer_1"][3]  # the two footer lines do not overlap
    assert boxes["footer_0"][3] < 0.17 * 1080  # below the plot area
    assert boxes["title"][1] > 0.90 * 1080  # above the plot area
    other = b.build(
        request(connectors=()), as_of=AS_OF, dataset_asset_id=DS_ID
    )  # a different spec changes the image and the spec hash
    assert other.png != one.png
    assert other.spec_sha256 != one.spec_sha256


@pytest.mark.unit
def test_as_of_does_not_change_the_image() -> None:
    b = builder()
    a = b.build(request(), as_of=AS_OF, dataset_asset_id=DS_ID)
    c = b.build(request(), as_of=AS_OF + timedelta(days=40), dataset_asset_id=DS_ID)
    assert a.png == c.png
    assert a.lag.age_days + 40 == c.lag.age_days


@pytest.mark.unit
def test_devanagari_label_has_no_notdef_glyph() -> None:
    import matplotlib._text_helpers as helpers
    import matplotlib.ft2font as ft2font

    pal = palette()
    ChartFontCheck.verify(pal, [SOURCE_LABEL])
    font = ft2font.FT2Font(pal.font_path)
    font.set_size(20, 100)
    glyphs = list(helpers.layout(SOURCE_LABEL, font))
    assert glyphs
    assert all(g.glyph_index != 0 for g in glyphs)
    # shaping happened: the pre-base vowel sign of "ति" is placed before its consonant
    deva = list(helpers.layout("ति", font))
    first = min(deva, key=lambda g: g.x)
    assert first.glyph_index != font.get_char_index(ord("त"))  # unshaped text would start with त
    assert ft2font.__libraqm_version__


@pytest.mark.unit
def test_font_without_devanagari_or_no_font_is_refused() -> None:
    import matplotlib

    dejavu = str(Path(matplotlib.get_data_path()) / "fonts/ttf/DejaVuSans.ttf")
    with pytest.raises(ConfigInvalidError) as exc:
        ChartFontCheck.verify(replace(PALETTE, font_path=dejavu), [SOURCE_LABEL])
    assert "U+0910" in exc.value.details["codepoints"]
    with pytest.raises(ConfigInvalidError):
        ChartFontCheck.verify(PALETTE, [SOURCE_LABEL])
    with pytest.raises(ConfigInvalidError):
        builder(palette=replace(PALETTE, font_path=dejavu)).build(
            request(), as_of=AS_OF, dataset_asset_id=DS_ID
        )


@pytest.mark.unit
def test_pinned_font_resolver_checks_the_hash(tmp_path: Path) -> None:
    font = PinnedFontResolver.resolve(FONT_MANIFEST)
    assert font.key in ("mukta_regular", "noto_sans_devanagari_vf")
    (tmp_path / "f.ttf").write_bytes(b"x")
    (tmp_path / "m.json").write_text(
        '{"fonts": [{"key": "noto_sans_devanagari_vf", "file": "f.ttf", "sha256": "00"}]}'
    )
    with pytest.raises(ConfigInvalidError):
        PinnedFontResolver.resolve(tmp_path / "m.json")
    with pytest.raises(ConfigInvalidError):
        PinnedFontResolver.resolve(tmp_path / "m.json", ("unknown",))
    with pytest.raises(ConfigInvalidError):
        PinnedFontResolver.resolve(tmp_path / "absent.json")


@pytest.mark.unit
def test_chart_facts_document_is_contract_valid_and_provenance_complete() -> None:
    chart = builder().build(request(), as_of=AS_OF, dataset_asset_id=DS_ID)
    doc = chart.facts.model_dump(mode="json")
    Draft202012Validator(facts_schema()).validate(doc)
    assert [f["fact_id"] for f in doc["facts"]] == ["f01", "f02", "f03", "f04"]
    assert doc["data_end_date"] == chart.lag.data_end_date.isoformat()
    assert f"{chart.bars_count} daily bars" in doc["facts"][0]["statement"]
    prov = chart.provenance
    assert prov["data_pack_manifest_sha256"] == chart.manifest_sha256
    assert prov["lag_check"]["data_age_vs_lag"] == "OLDER_THAN_LAG"
    assert prov["source_label"] == SOURCE_LABEL
    assert prov["chart_sha256"] == chart.stills[-1].sha256
    attrs = chart.attributes()
    assert attrs["source_path_class"] == "data_pack"
    assert attrs["bars_count"] == chart.bars_count
    assert set(provenance_json(chart)) == {"chart_facts", "provenance"}


@pytest.mark.unit
@pytest.mark.parametrize(
    "over",
    [
        {"annotations": (Annotation(kind="LABEL", bar=10, text="Buy here"),)},
        {"annotations": (Annotation(kind="MARK_BAR", bar=999),)},
        {"connectors": (Connector(from_offset=1, to_offset=999, panel="PRICE"),)},
        {"connectors": (Connector(from_offset=0, to_offset=5, panel="RSI"),)},
    ],
)
def test_forward_looking_or_unlisted_annotations_are_refused(over: dict) -> None:
    # window starts at the first bar so offset 0 is inside the RSI warm-up
    with pytest.raises(InputInvalidError):
        builder().build(
            request(window_start=date(2025, 1, 1), **over), as_of=AS_OF, dataset_asset_id=DS_ID
        )


@pytest.mark.unit
def test_request_model_rules() -> None:
    with pytest.raises(ValidationError):
        request(connectors=(Connector(from_offset=0, to_offset=5, panel="RSI"),), indicators=())
    with pytest.raises(ValidationError):
        Connector(from_offset=5, to_offset=5, panel="PRICE")
    with pytest.raises(ValidationError):
        request(window_end=date(2025, 1, 1))
    with pytest.raises(ValidationError):
        request(timeframe="5M")


# -- registration ------------------------------------------------------------------------------


@pytest.mark.unit
def test_registration_writes_a_code_generated_tier_c_chart() -> None:
    w = World()
    chart = builder().build(request(reveal_steps=2), as_of=AS_OF, dataset_asset_id=DS_ID)
    reg = DataPackChartRegistrar(assets=w.assets, blobs=w.blobs, licences=w.licences).register(
        w.tx, chart, "shot_1"
    )
    rec = reg.asset
    assert rec.asset.kind is AssetKind.CHART
    assert rec.asset.source_type is LicenceSourceType.CODE_GENERATED
    assert rec.asset.visual_source_tier is VisualSourceTier.C_CODE_MOTION
    assert rec.asset.content_sha256 == chart.stills[-1].sha256
    assert rec.asset.licence_id is not None
    assert rec.asset.attributes["data_pack_manifest_sha256"] == chart.manifest_sha256
    assert len(reg.reveal) == 1
    assert reg.reveal[0].asset.kind is AssetKind.IMAGE
    assert reg.facts_uri.endswith(".json")
    assert reg.provenance_uri.endswith(".json")


@pytest.mark.unit
def test_registration_without_self_grant_row_is_missing_dependency() -> None:
    from agent_08_visual_assets.testing.memory import MemoryLicenceRepository

    w = World()
    chart = builder().build(request(), as_of=AS_OF, dataset_asset_id=DS_ID)
    with pytest.raises(MissingDependencyError):
        DataPackChartRegistrar(
            assets=w.assets, blobs=w.blobs, licences=MemoryLicenceRepository()
        ).register(w.tx, chart, "shot_1")
