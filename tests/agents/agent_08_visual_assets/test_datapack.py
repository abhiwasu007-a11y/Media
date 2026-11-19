# mypy: disable-error-code="arg-type,attr-defined,misc,has-type,no-untyped-def,no-any-return"
# mypy: disable-error-code="assignment,union-attr,index,call-arg,no-untyped-call,type-arg"
# (test helpers feed dataset dicts and fakes into typed APIs; the package is strict clean)
"""data_pack chart scenes (tier C): guarded intake, per-bar lag from the system clock, RSI,
rendering, chart facts, stage wiring.

Every bar here is SYNTHETIC, generated at test time; no market data is read or committed.
"""

import hashlib
import inspect
import io
import json
import os
import random
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from PIL import Image
from pydantic import ValidationError

from agent_06_fact_checker.models import DataAge
from agent_06_fact_checker.price_age import classify
from agent_08_visual_assets.charts.annotations import Annotation, Connector
from agent_08_visual_assets.charts.cases import ChartCase
from agent_08_visual_assets.charts.datapack import (
    DataPackSettings,
    FileDataPackReader,
    MemoryDataPackReader,
)
from agent_08_visual_assets.charts.datapack_builder import (
    SOURCE_LABEL,
    ChartFontCheck,
    DataPackChartBuilder,
    DataPackChartRequest,
    DataPackLagGuard,
    RegisteredDataset,
    is_data_within_lag,
    ist_today,
    provenance_json,
)
from agent_08_visual_assets.charts.dataset import Bar, DatasetLoader
from agent_08_visual_assets.charts.fonts import PinnedFontResolver
from agent_08_visual_assets.charts.render import rsi
from agent_08_visual_assets.persistence.records import NewAsset
from agent_08_visual_assets.registrar import AssetRegistrar, Intake
from amw_core.enums import ActorKind, AssetKind, DataAgeVsLag, LicenceSourceType
from amw_core.errors import (
    ConfigInvalidError,
    CorruptedOutputError,
    InputInvalidError,
    MissingDependencyError,
    PermissionDeniedError,
)
from tests.agents.agent_08_visual_assets.fixtures import PALETTE, FixedClock, World
from tests.agents.agent_08_visual_assets.schemas import facts_schema
from tests.agents.agent_08_visual_assets.test_stage import OVERLAYS, Env, plan

ROOT = Path(__file__).resolve().parents[3]
FONT_MANIFEST = (
    ROOT
    / "packages/agents/agent_11_thumbnail_design/src/agent_11_thumbnail_design/data/fonts"
    / "manifest.json"
)
DS_ID = "ast_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e0c"
AS_OF = date(2026, 6, 1)
CLOCK = FixedClock(datetime(2026, 6, 1, 6, 0, tzinfo=UTC))  # IST date 2026-06-01


def pack_csv(n: int = 260, start: date = date(2025, 1, 1), step: int = 1, seed: int = 11) -> bytes:
    """Synthetic daily rows in the data_pack layout (``timestamp`` first, extra columns)."""
    rnd = random.Random(seed)  # noqa: S311
    price = 100.0
    rows = ["timestamp,open,high,low,close,volume"]
    for i in range(n):
        o, c = price, price + rnd.uniform(-2, 2)
        h, low = max(o, c) + rnd.uniform(0, 1), min(o, c) - rnd.uniform(0, 1)
        price = c
        rows.append(f"{start + timedelta(days=i * step)},{o:.2f},{h:.2f},{low:.2f},{c:.2f},0")
    return ("\n".join(rows) + "\n").encode()


def registered(content: bytes | None = None, **attrs: object) -> RegisteredDataset:
    content = content or pack_csv()
    sha = hashlib.sha256(content).hexdigest()
    series = DatasetLoader.parse(content, max_bars=10000, sha256=sha)
    base = {
        "doc_kind": "DATASET",
        "source_path_class": "data_pack",
        "instrument": "SYN",
        "timeframe": "1D",
        "data_pack_manifest_sha256": "a" * 64,
    }
    return RegisteredDataset(DS_ID, sha, {**base, **attrs}, series)


def palette():
    font = PinnedFontResolver.resolve(FONT_MANIFEST)
    return replace(PALETTE, font_path=str(font.path), font_sha256=font.sha256)


def builder(**over):
    kw = {
        "palette": palette(),
        "clock": CLOCK,
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


def _check(bars, timeframe="1D", clip=False):
    return DataPackLagGuard.check(
        bars,
        timeframe=timeframe,
        as_of=AS_OF,
        lag_days=30,
        platform_min_lag_days=30,
        clip_to_lag=clip,
    )


# -- lag per bar -------------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(("age", "ok"), [(30, True), (29, False), (31, True)])
def test_lag_boundary_daily(age: int, ok: bool) -> None:
    bars = bars_ending(AS_OF - timedelta(days=age))
    if ok:
        keep, proof = _check(bars)
        assert keep == len(bars)
        assert proof.age_days == age
        assert proof.data_age_vs_lag is DataAgeVsLag.OLDER_THAN_LAG
        assert proof.cutoff_date == AS_OF - timedelta(days=30)
        assert proof.data_end_date <= proof.cutoff_date
        assert proof.earliest_compliant_publish_date == proof.data_end_date + timedelta(days=30)
    else:
        with pytest.raises(InputInvalidError) as exc:
            _check(bars)
        assert is_data_within_lag(exc.value)
        assert exc.value.details["bars_within_lag"] == 1


@pytest.mark.unit
@pytest.mark.parametrize("age", range(25, 36))
def test_lag_arithmetic_matches_agent_06_classify(age: int) -> None:
    last = AS_OF - timedelta(days=age)
    ours = True
    try:
        _check(bars_ending(last))
    except InputInvalidError:
        ours = False
    assert ours == (classify(last, AS_OF, 30) is DataAge.OLDER_THAN_LAG)


@pytest.mark.unit
@pytest.mark.parametrize(("bar_age", "ok"), [(36, True), (35, False)])
def test_weekly_bar_covers_its_whole_week(bar_age: int, ok: bool) -> None:
    bars = bars_ending(AS_OF - timedelta(days=bar_age), n=3, step=7)
    if ok:
        assert _check(bars, "1W")[1].age_days == 30
    else:
        with pytest.raises(InputInvalidError):
            _check(bars, "1W")


@pytest.mark.unit
def test_window_with_newer_bars_is_refused_never_truncated() -> None:
    last_bar = date(2025, 1, 1) + timedelta(days=259)
    clock = FixedClock(datetime.combine(last_bar + timedelta(days=21), datetime.min.time(), UTC))
    b = builder(clock=clock)
    req = request(window_end=last_bar)
    # the last 9 bars (ages 21..29 days) are inside the lag
    with pytest.raises(InputInvalidError) as exc:
        b.build(req, registered())
    assert is_data_within_lag(exc.value)
    assert exc.value.details["bars_within_lag"] == 9
    clipped = b.build(req.model_copy(update={"clip_to_lag": True}), registered())
    assert clipped.lag.bars_clipped == 9
    assert clipped.lag.last_bar_date == last_bar - timedelta(days=9)
    assert clipped.provenance["lag_check"]["bars_clipped"] == 9
    assert clipped.provenance["requested_window"] == ["2025-03-01", last_bar.isoformat()]


@pytest.mark.unit
def test_clip_never_hides_a_future_bar_or_an_all_new_window() -> None:
    bars = bars_ending(AS_OF - timedelta(days=40), n=3) + bars_ending(
        AS_OF + timedelta(days=1), n=1
    )
    with pytest.raises(InputInvalidError, match="after the as-of date"):
        _check(bars, clip=True)
    with pytest.raises(InputInvalidError) as exc:
        _check(bars_ending(AS_OF - timedelta(days=3)), clip=True)
    assert is_data_within_lag(exc.value)
    with pytest.raises(ConfigInvalidError):
        builder(lag_days=29)


# -- as-of date comes from the system clock only (MAJOR-2) ---------------------------------------


@pytest.mark.security
def test_caller_cannot_pass_an_as_of_date() -> None:
    assert "as_of" not in inspect.signature(DataPackChartBuilder.build).parameters
    with pytest.raises(TypeError):
        builder().build(request(), registered(), as_of=date(2099, 1, 1))


@pytest.mark.security
def test_payload_cannot_carry_an_as_of_date() -> None:
    with pytest.raises(ValidationError):
        request(as_of=date(2099, 1, 1))
    case = json.loads(
        json.dumps(
            {
                "case_id": "c",
                "data_kind": "REAL_HISTORICAL",
                "instrument": "SYN",
                "timeframe": "1D",
                "dataset_asset_id": DS_ID,
                "window": None,
                "window_dates": {"start_date": "2025-03-01", "end_date": "2025-06-30"},
                "indicators": [],
                "pattern_concept_ids": ["k"],
                "outcome": "WORKED",
                "annotations": [],
                "method_content": False,
                "template_id": "chart_datapack",
            }
        )
    )
    ChartCase.model_validate(case)
    with pytest.raises(ValidationError):
        ChartCase.model_validate({**case, "as_of": "2099-01-01"})


@pytest.mark.security
def test_an_old_clock_date_cannot_be_injected_through_the_request() -> None:
    """A late clock passes a window, the real clock refuses it: only the clock decides."""
    last_bar = date(2025, 1, 1) + timedelta(days=259)
    req = request(window_end=last_bar)
    late = FixedClock(datetime(2030, 1, 1, tzinfo=UTC))
    real = FixedClock(datetime.combine(last_bar + timedelta(days=5), datetime.min.time(), UTC))
    assert builder(clock=late).build(req, registered()).lag.as_of == date(2030, 1, 1)
    with pytest.raises(InputInvalidError):
        builder(clock=real).build(req, registered())


@pytest.mark.unit
def test_as_of_is_the_ist_calendar_date_of_the_utc_clock() -> None:
    assert ist_today(FixedClock(datetime(2026, 5, 31, 18, 29, tzinfo=UTC))) == date(2026, 5, 31)
    assert ist_today(FixedClock(datetime(2026, 5, 31, 18, 30, tzinfo=UTC))) == date(2026, 6, 1)
    with pytest.raises(ConfigInvalidError):
        ist_today(FixedClock(datetime(2026, 5, 31, 18, 30)))


# -- the dataset actually read (MAJOR-1) ---------------------------------------------------------


@pytest.mark.security
@pytest.mark.parametrize(
    ("ds_over", "exc"),
    [
        ({"content_sha256": "b" * 64}, CorruptedOutputError),
        ({"attrs": {"source_path_class": "research"}}, InputInvalidError),
        ({"attrs": {"doc_kind": "CHART_CASE"}}, InputInvalidError),
        ({"attrs": {"instrument": "OTHER"}}, InputInvalidError),
        ({"attrs": {"timeframe": "1W"}}, InputInvalidError),
        ({"attrs": {"data_pack_manifest_sha256": None}}, InputInvalidError),
    ],
)
def test_dataset_must_be_the_registered_data_pack_bytes(ds_over: dict, exc: type) -> None:
    ds = registered(**ds_over.get("attrs", {}))
    if "content_sha256" in ds_over:
        ds = replace(ds, content_sha256=ds_over["content_sha256"])
    with pytest.raises(exc):
        builder().build(request(), ds)


def _pack_dir(tmp_path: Path) -> Path:
    root = tmp_path / "course" / "data_pack"
    root.mkdir(parents=True)
    (root / "syn.csv").write_bytes(pack_csv(50))
    return root


def _settings(root: Path, files: dict | None = None, max_bars: int = 1000) -> DataPackSettings:
    return DataPackSettings.from_mapping(
        {
            "charts.data_pack_root": str(root),
            "charts.data_pack_files": files or {"SYN@1D": "syn.csv"},
        },
        max_bars=max_bars,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"charts.data_pack_root": ""},
        {"charts.data_pack_root": "/x"},
        {"charts.data_pack_root": "/x", "charts.data_pack_files": {}},
        {"charts.data_pack_root": "/x", "charts.data_pack_files": {"SYN@1D": "../a.csv"}},
        {"charts.data_pack_root": "/x", "charts.data_pack_files": {"SYN@1D": "d/a.csv"}},
        {"charts.data_pack_root": "/x", "charts.data_pack_files": {"SYN@5M": "a.csv"}},
    ],
)
def test_missing_or_bad_data_pack_config_fails_closed(raw: dict) -> None:
    with pytest.raises(ConfigInvalidError):
        DataPackSettings.from_mapping(raw, max_bars=1000)


@pytest.mark.security
def test_root_must_be_the_course_data_pack_folder(tmp_path: Path) -> None:
    root = _pack_dir(tmp_path)
    FileDataPackReader(_settings(root))
    other = tmp_path / "elsewhere"
    other.mkdir()
    for bad in (tmp_path / "absent", other, tmp_path / "course"):
        with pytest.raises(ConfigInvalidError):
            FileDataPackReader(_settings(bad))
    for area in ("HOLDOUT", "IS", "val", "oos", "holdout_2024"):
        sealed = tmp_path / area / "course" / "data_pack"
        sealed.mkdir(parents=True)
        with pytest.raises(ConfigInvalidError, match="research area"):
            FileDataPackReader(_settings(sealed))


@pytest.mark.security
def test_symlinked_root_or_file_and_oversize_file_are_refused(tmp_path: Path) -> None:
    root = _pack_dir(tmp_path)
    link_parent = tmp_path / "alias" / "course"
    link_parent.mkdir(parents=True)
    os.symlink(root, link_parent / "data_pack")
    with pytest.raises(ConfigInvalidError, match="symbolic link"):
        FileDataPackReader(_settings(link_parent / "data_pack"))
    outside = tmp_path / "outside.csv"
    outside.write_bytes(pack_csv(10))
    os.symlink(outside, root / "linked.csv")
    with pytest.raises(ConfigInvalidError, match="not a regular file"):
        FileDataPackReader(_settings(root, {"SYN@1D": "linked.csv"})).read("SYN", "1D")
    with pytest.raises(ConfigInvalidError, match="size cap"):
        FileDataPackReader(_settings(root, max_bars=2)).read("SYN", "1D")


@pytest.mark.unit
def test_file_reader_reads_configured_files_only(tmp_path: Path) -> None:
    root = _pack_dir(tmp_path)
    s = _settings(root, {"SYN@1D": "syn.csv", "OTH@1D": "missing.csv"})
    with pytest.raises(ConfigInvalidError):  # every configured file must exist (manifest)
        FileDataPackReader(s).read("SYN", "1D")
    (root / "missing.csv").write_bytes(pack_csv(10, seed=3))
    reader = FileDataPackReader(s)
    pack = reader.read("SYN", "1D")
    assert pack.sha256 == hashlib.sha256(pack.content).hexdigest()
    first = reader.manifest_sha256()
    assert pack.manifest_sha256 == first
    with pytest.raises(MissingDependencyError):
        reader.read("NONE", "1D")
    with pytest.raises(InputInvalidError):
        reader.read("SYN", "5M")
    (root / "missing.csv").write_bytes(pack_csv(11, seed=3))
    assert FileDataPackReader(s).manifest_sha256() != first


@pytest.mark.security
def test_intake_guard_runs_before_the_pack_is_read() -> None:
    w = World()
    reg = AssetRegistrar(assets=w.assets, blobs=w.blobs, audit=w.audit, max_dataset_bars=5000)
    reader = MemoryDataPackReader({"SYN@1D": pack_csv(80)})
    for intake, exc in (
        (Intake(ActorKind.AGENT, w.ctx.actor, True, "data_pack"), PermissionDeniedError),
        (Intake(ActorKind.HUMAN, w.ctx.actor, False, "data_pack"), PermissionDeniedError),
        (Intake(ActorKind.HUMAN, w.ctx.actor, True, "research"), InputInvalidError),
    ):
        with pytest.raises(exc):
            reg.register_data_pack_series(
                w.tx, intake, reader, instrument="SYN", timeframe="1D", title="d"
            )
    assert reader.reads == []  # refused before any read
    rec = reg.register_data_pack_series(
        w.tx,
        Intake(ActorKind.HUMAN, w.ctx.actor, True, "data_pack"),
        reader,
        instrument="SYN",
        timeframe="1D",
        title="d",
    )
    assert rec.asset.content_sha256 == hashlib.sha256(pack_csv(80)).hexdigest()
    assert rec.asset.attributes["data_pack_manifest_sha256"] == reader.manifest_sha256()
    assert rec.asset.attributes["source_path_class"] == "data_pack"
    assert rec.asset.source_type is LicenceSourceType.OWNER_MADE


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
        "2025-01-01,0,2,0,1,0",
        "2025-01-01,-1,2,0.5,1,0",
        "2025-01-01,1E+3,2E+3,0.5,1,0",
    ],
)
def test_malformed_rows_and_non_positive_prices_are_refused(body: str) -> None:
    content = ("timestamp,open,high,low,close,volume\n" + body + "\n").encode()
    with pytest.raises(InputInvalidError):
        DatasetLoader.parse(content, max_bars=100, sha256="0" * 64)


@pytest.mark.unit
def test_window_without_bars_is_refused() -> None:
    with pytest.raises(InputInvalidError):
        builder().build(
            request(window_start=date(2030, 1, 1), window_end=date(2030, 2, 1)), registered()
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


@pytest.mark.unit
def test_rsi_of_a_flat_span_is_undefined_and_cannot_be_marked() -> None:
    assert rsi([5.0] * 6, 3) == [None] * 6
    # after movement the value returns: 0/0 only while both averages are zero
    assert rsi([5.0, 5.0, 5.0, 5.0, 6.0], 3)[4] == 100.0
    flat = "timestamp,open,high,low,close\n" + "".join(
        f"{date(2025, 1, 1) + timedelta(days=i)},5,5,5,5\n" for i in range(40)
    )
    with pytest.raises(InputInvalidError, match="no RSI value"):
        builder().build(
            request(
                window_start=date(2025, 1, 1),
                window_end=date(2025, 2, 9),
                connectors=(Connector(from_offset=20, to_offset=30, panel="RSI"),),
                annotations=(),
            ),
            registered(flat.encode()),
        )


# -- rendering, fonts, facts -------------------------------------------------------------------


def _overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


@pytest.mark.unit
def test_render_is_byte_identical_and_layout_holds() -> None:
    b = builder()
    one = b.build(request(reveal_steps=3), registered())
    two = b.build(request(reveal_steps=3), registered())
    assert [s.png for s in one.stills] == [s.png for s in two.stills]
    assert one.spec_sha256 == two.spec_sha256
    assert len(one.stills) == 3
    img = Image.open(io.BytesIO(one.png))
    assert img.size == (1920, 1080)
    assert "Software" not in img.info
    boxes = dict(one.stills[-1].text_boxes)
    assert set(boxes) == {"title", "price_axes", "label_0", "footer_0", "footer_1"}
    for role, (x0, y0, x1, y1) in boxes.items():  # every text is inside the canvas
        assert 0 <= x0 < x1 <= 1920, role
        assert 0 <= y0 < y1 <= 1080, role
    axes = boxes["price_axes"]
    # the label sits above the plot area: it never covers a candle, a line or a connector point
    assert boxes["label_0"][1] >= axes[3] - 1
    assert not _overlap(boxes["label_0"], boxes["title"])
    assert not _overlap(boxes["footer_0"], boxes["footer_1"])
    assert boxes["footer_0"][3] < 0.17 * 1080  # below the plot area
    other = b.build(request(connectors=()), registered())
    assert other.png != one.png
    assert other.spec_sha256 != one.spec_sha256


@pytest.mark.unit
def test_label_near_the_edges_stays_inside_the_canvas() -> None:
    for bar in (0, 80):
        chart = builder().build(
            request(
                connectors=(),
                annotations=(Annotation(kind="LABEL", bar=bar, text="Historical example"),),
            ),
            registered(),
        )
        x0, _, x1, _ = dict(chart.stills[-1].text_boxes)["label_0"]
        assert 0 <= x0 < x1 <= 1920


@pytest.mark.unit
def test_clock_date_does_not_change_the_image() -> None:
    a = builder().build(request(), registered())
    later = FixedClock(datetime(2026, 7, 11, 6, 0, tzinfo=UTC))
    c = builder(clock=later).build(request(), registered())
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
        builder(palette=replace(PALETTE, font_path=dejavu)).build(request(), registered())


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
    chart = builder().build(request(), registered())
    doc = chart.facts.model_dump(mode="json")
    Draft202012Validator(facts_schema()).validate(doc)
    assert [f["fact_id"] for f in doc["facts"]] == ["f01", "f02", "f03", "f04"]
    assert doc["data_end_date"] == chart.lag.data_end_date.isoformat()
    assert doc["dataset_sha256"] == chart.dataset.content_sha256
    assert f"{chart.bars_count} daily bars" in doc["facts"][0]["statement"]
    prov = chart.provenance
    assert prov["data_pack_manifest_sha256"] == "a" * 64
    assert prov["lag_check"]["data_age_vs_lag"] == "OLDER_THAN_LAG"
    assert prov["lag_check"]["as_of_source"] == "system_clock_ist"
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
        builder().build(request(window_start=date(2025, 1, 1), **over), registered())


@pytest.mark.unit
def test_request_and_case_model_rules() -> None:
    with pytest.raises(ValidationError):
        request(connectors=(Connector(from_offset=0, to_offset=5, panel="RSI"),), indicators=())
    with pytest.raises(ValidationError):
        Connector(from_offset=5, to_offset=5, panel="PRICE")
    with pytest.raises(ValidationError):
        request(window_end=date(2025, 1, 1))
    with pytest.raises(ValidationError):
        request(timeframe="5M")


# -- stage wiring ------------------------------------------------------------------------------


def _datapack_env(start: date = date(2025, 1, 1), n: int = 200) -> Env:
    env = Env()
    w = env.w
    reg = AssetRegistrar(assets=w.assets, blobs=w.blobs, audit=w.audit, max_dataset_bars=5000)
    reader = MemoryDataPackReader({"EXAMPLE_X@1D": pack_csv(n, start=start)})
    ds = reg.register_data_pack_series(
        w.tx, env.intake, reader, instrument="EXAMPLE_X", timeframe="1D", title="pack"
    )
    case = {
        "case_id": "case_0",  # sorts before the bar-index case of Env: this one matches first
        "data_kind": "REAL_HISTORICAL",
        "instrument": "EXAMPLE_X",
        "timeframe": "1D",
        "dataset_asset_id": ds.asset_id,
        "window": None,
        "window_dates": {
            "start_date": (start + timedelta(days=40)).isoformat(),
            "end_date": (start + timedelta(days=n - 1)).isoformat(),
        },
        "indicators": ["SMA_10", "RSI_14"],
        "pattern_concept_ids": ["k1"],
        "outcome": "WORKED",
        "annotations": [{"kind": "LABEL", "bar": 50, "text": "Historical example"}],
        "connectors": [
            {"from_offset": 10, "to_offset": 50, "panel": "PRICE", "anchor": "HIGH"},
            {"from_offset": 10, "to_offset": 50, "panel": "RSI"},
        ],
        "rsi_guides": [30, 70],
        "method_content": False,
        "template_id": "chart_datapack",
    }
    reg.register_chart_case(w.tx, env.intake, document=json.dumps(case).encode(), title="dp")
    font = PinnedFontResolver.resolve(FONT_MANIFEST)
    data = font.path.read_bytes()
    uri = w.blobs.blob_uri(w.ctx, "assets", f"fonts/{font.sha256}.ttf")
    w.blobs.put(w.ctx, uri, io.BytesIO(data))
    env.latin_font = env.font  # Env's DejaVu font asset
    env.font = w.assets.insert(
        w.tx,
        NewAsset(
            kind=AssetKind.FONT,
            source_type=LicenceSourceType.FONT,
            content_sha256=font.sha256,
            uri=str(uri),
            size_bytes=len(data),
            title="brand font",
        ),
    ).asset_id
    env.dataset = ds
    return env


@pytest.mark.integration
def test_stage_draws_a_data_pack_chart_scene_with_facts() -> None:
    env = _datapack_env()
    res = env.run(plan(), OVERLAYS)
    out = res.payload
    assert res.task_status == "SUCCEEDED"
    assert out.gate_verdict == "PASSED"
    s1 = out.shots[0]
    assert s1.chart is not None
    assert s1.chart.template_id == "chart_datapack"
    assert s1.chart.dataset_asset_id == env.dataset.asset_id
    assert s1.chart.dataset_sha256 == env.dataset.asset.content_sha256
    assert s1.chart.data_age_vs_lag == "OLDER_THAN_LAG"
    rec = env.w.assets.get(env.w.tx, s1.asset_id)
    assert rec.asset.kind is AssetKind.CHART
    assert rec.asset.source_type is LicenceSourceType.CODE_GENERATED
    assert rec.asset.attributes["source_path_class"] == "data_pack"
    assert rec.asset.attributes["lag_check"]["as_of"] == "2026-06-01"
    assert (
        rec.asset.attributes["data_pack_manifest_sha256"]
        == (env.dataset.asset.attributes["data_pack_manifest_sha256"])
    )
    assert out.chart_facts[0].fact_count == 4
    assert len(s1.reveal_stills) == 2


@pytest.mark.integration
def test_stage_data_pack_scene_within_lag_routes_to_script_stage() -> None:
    env = _datapack_env(start=date(2025, 11, 20), n=180)  # last bar 2026-05-18, 14 days old
    res = env.run(plan(), OVERLAYS)
    assert res.task_status == "SUCCEEDED"
    assert res.gate_verdict == "FAILED"
    assert res.unresolved[0].reason.value == "DATA_WITHIN_LAG"
    gate = next(v for v in res.validation_results if v.gate)
    assert gate.remedy_stage_id == "s05_script"


@pytest.mark.integration
def test_stage_data_pack_scene_with_a_latin_only_brand_font_fails_closed() -> None:
    env = _datapack_env()
    env.font = env.latin_font  # DejaVu: no Devanagari glyphs
    with pytest.raises(ConfigInvalidError):
        env.run(plan(), OVERLAYS)
