"""``DataPackChartBuilder``: tier C chart scenes drawn from the course ``data_pack``
(owner decision:
the real skeleton run includes data_pack chart scenes; Q22, IN-02, FIN-R9, FIN-R13).

Flow for one ``DataPackChartRequest`` (instrument, timeframe, date window, indicators, annotations,
bar connectors):

1. bars come from the ``DataPackReader`` port (file-backed at the configured root, or the in-memory
   test double); nothing is invented, a missing series is ``PERMANENT.MISSING_DEPENDENCY``;
2. **lag per bar** (``DataPackLagGuard``): every bar of the window must cover only dates at least
   ``lag_days`` before ``as_of`` (``as_of - bar_end >= lag_days``, the same arithmetic as
   ``ChartLagGuard`` and Agent 06 ``price_age.classify``; a weekly bar ends at its date + 6 days,
   the largest span). A window holding a newer bar is REFUSED (``DATA_WITHIN_LAG``); bars are
   dropped from the end only when the request says ``clip_to_lag`` explicitly, and the proof records
   how many were dropped. ``as_of`` is the earliest date the chart can be shown (the run date): the
   age only grows until publish, where Agent 16 re-checks with ``recheck_lag_at``;
3. indicators are computed in code (RSI: Wilder, ``render.rsi``), warm-up bars before the window
   come from the same series (they are older than the window, so the lag holds for them too);
4. annotations go through ``AnnotationValidator`` (FIN-R13); connectors are checked to start and end
   inside the window (kind ``CONNECT_BARS`` is proposed in CCR-255);
5. rendering: ``ChartRenderer`` with the brand font (Devanagari-capable, from the pinned font
   manifest or the tenant's font asset), the bilingual source label and the as-of range on every
   still; ``ChartFontCheck`` refuses a font that lacks any character drawn (no notdef box) and a
   matplotlib without libraqm shaping;
6. outputs: the reveal stills, the contract ``agent_08.chart_facts`` document (f01-f04), the chart
   provenance (lag proof and data_pack manifest hash, CCR-256) and the asset attributes.

No real price is written in this package; tests use synthetic bars only.
"""

import hashlib
import io
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Annotated, Any, Literal, Self

import matplotlib.ft2font as ft2font
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_08_visual_assets.charts.annotations import Annotation, AnnotationValidator
from agent_08_visual_assets.charts.datapack import DATA_PACK_TIMEFRAMES, DataPackReader
from agent_08_visual_assets.charts.dataset import Bar
from agent_08_visual_assets.charts.facts import ChartFactsBuilder, FactBar
from agent_08_visual_assets.charts.lag import ChartLagGuard, LagResult
from agent_08_visual_assets.charts.render import (
    BarConnector,
    BrandPalette,
    ChartRenderer,
    ChartRenderInput,
    RenderedImage,
    parse_indicator,
    rsi,
)
from agent_08_visual_assets.charts.spec import ChartSpec, ChartSpecHasher, canonical_json
from agent_08_visual_assets.models.output import ChartFact, ChartFactsDocument
from agent_08_visual_assets.persistence.protocols import AssetRepository, LicenceRepository
from agent_08_visual_assets.persistence.records import AssetRecord, NewAsset
from amw_core.enums import (
    AssetKind,
    ChartDataKind,
    DataAgeVsLag,
    LicenceSourceType,
    LicenceState,
    VisualSourceTier,
)
from amw_core.errors import ConfigInvalidError, InputInvalidError, MissingDependencyError
from amw_core.interfaces.storage import BlobStorage
from amw_core.interfaces.tenancy_context import TenantTransaction

TEMPLATE_ID = "chart_datapack"
TEMPLATE_VERSION = 1
HISTORICAL_LABEL = "Historical example"
SOURCE_LABEL = "ऐतिहासिक data / Historical data"
"""Visible source label of every data_pack chart (owner decision relayed in the lane brief;
final wording is owned by 13, REQUIRES REVIEW (Phase 1))."""
LAG_UNIT = "CALENDAR_DAYS"
_PROVENANCE_SCHEMA = "agent_08.chart_provenance:0.1.0 (proposed, CCR-256)"


DATA_WITHIN_LAG = "DATA_WITHIN_LAG"


def bars_within_lag(message: str, **details: object) -> InputInvalidError:
    """The refusal of a window holding a bar newer than the price-data lag (FIN-R9): the typed
    ``InputInvalidError`` (``PERMANENT.INPUT_INVALID``; ``amw_core`` allows one class per 07 code,
    so no subclass) with ``details.reason = DATA_WITHIN_LAG``, which the stage maps to the shot's
    ``UNRESOLVED(DATA_WITHIN_LAG)``."""
    return InputInvalidError(message, details={"reason": DATA_WITHIN_LAG, **details})


def is_data_within_lag(exc: BaseException) -> bool:
    return isinstance(exc, InputInvalidError) and exc.details.get("reason") == DATA_WITHIN_LAG


class Connector(BaseModel):
    """Window-relative bar offsets (0 = first bar of the window)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    from_offset: Annotated[int, Field(ge=0)]
    to_offset: Annotated[int, Field(ge=0)]
    panel: Literal["PRICE", "RSI"]
    anchor: Literal["HIGH", "LOW"] = "HIGH"

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.to_offset <= self.from_offset:
            raise ValueError("a connector joins an earlier bar to a later bar")
        return self


class DataPackChartRequest(BaseModel):
    """One chart scene. Annotation bar numbers are window-relative offsets."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chart_id: Annotated[str, Field(pattern=r"^chart_[0-9a-z_]{1,32}$")]
    instrument: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")]
    timeframe: Annotated[str, Field(pattern=r"^(1D|1W)$")]
    window_start: date
    window_end: date
    indicators: tuple[str, ...] = ()
    annotations: tuple[Annotation, ...] = ()
    connectors: tuple[Connector, ...] = ()
    on_screen_text_allowlist: tuple[str, ...] = ()
    rsi_guides: tuple[Annotated[float, Field(gt=0, lt=100)], ...] = ()
    clip_to_lag: bool = False
    reveal_steps: Annotated[int, Field(ge=1, le=12)] = 1
    aspect_ratio: Literal["16:9", "9:16"] = "16:9"

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.window_end < self.window_start:
            raise ValueError("window_end precedes window_start")
        for name in self.indicators:
            parse_indicator(name)
        if any(c.panel == "RSI" for c in self.connectors) and not any(
            i.startswith("RSI_") for i in self.indicators
        ):
            raise ValueError("an RSI connector needs an RSI indicator")
        return self


@dataclass(frozen=True, slots=True)
class LagProof:
    as_of: date
    lag_days: int
    cutoff_date: date
    """Latest calendar date a bar may cover: ``as_of - lag_days``."""
    last_bar_date: date
    data_end_date: date
    age_days: int
    data_age_vs_lag: DataAgeVsLag
    earliest_compliant_publish_date: date
    bars_checked: int
    bars_clipped: int

    def as_dict(self) -> dict[str, object]:
        return {
            "as_of": self.as_of.isoformat(),
            "lag_days": self.lag_days,
            "lag_unit": LAG_UNIT,
            "cutoff_date": self.cutoff_date.isoformat(),
            "last_bar_date": self.last_bar_date.isoformat(),
            "data_end_date": self.data_end_date.isoformat(),
            "age_days": self.age_days,
            "data_age_vs_lag": self.data_age_vs_lag.value,
            "earliest_compliant_publish_date": self.earliest_compliant_publish_date.isoformat(),
            "bars_checked": self.bars_checked,
            "bars_clipped": self.bars_clipped,
        }


class DataPackLagGuard:
    @staticmethod
    def check(
        bars: Sequence[Bar],
        *,
        timeframe: str,
        as_of: date,
        lag_days: int,
        platform_min_lag_days: int,
        clip_to_lag: bool,
    ) -> tuple[int, LagProof]:
        """Return how many leading bars of ``bars`` are usable and the proof; raise
        ``DATA_WITHIN_LAG`` when a bar is newer than the lag and clipping was not asked."""
        if lag_days < platform_min_lag_days:
            raise ConfigInvalidError("price data lag is below the platform minimum")
        if not bars:
            raise InputInvalidError("chart window holds no bar")
        cutoff = as_of - timedelta(days=lag_days)
        keep = 0
        for bar in bars:
            if bar.date > as_of:
                raise InputInvalidError("a bar is dated after the as-of date")
            end = ChartLagGuard.bar_end_date(timeframe, bar.date, None)
            if (as_of - end).days >= lag_days:
                keep += 1
                continue
            break
        newer = len(bars) - keep
        if newer and not clip_to_lag:
            raise bars_within_lag(
                "chart window holds bars newer than the price-data lag",
                bars_within_lag=newer,
                first_bar_within_lag=bars[keep].date.isoformat(),
                cutoff_date=cutoff.isoformat(),
            )
        if keep == 0:
            raise bars_within_lag(
                "every bar of the window is newer than the price-data lag",
                cutoff_date=cutoff.isoformat(),
            )
        last = bars[keep - 1]
        result: LagResult = ChartLagGuard.classify(
            timeframe=timeframe,
            lag_days=lag_days,
            platform_min_lag_days=platform_min_lag_days,
            last_bar_start=last.date,
            period_end=None,
            today=as_of,
        )
        if (
            result.data_age_vs_lag is not DataAgeVsLag.OLDER_THAN_LAG
            or result.data_end_date is None
            or result.age_days is None
            or result.earliest_publish_date is None
        ):  # pragma: no cover - the loop above already proved every kept bar
            raise bars_within_lag("lag re-check failed")
        return keep, LagProof(
            as_of,
            lag_days,
            cutoff,
            last.date,
            result.data_end_date,
            result.age_days,
            result.data_age_vs_lag,
            result.earliest_publish_date,
            len(bars),
            newer,
        )


class ChartFontCheck:
    @staticmethod
    def verify(palette: BrandPalette, texts: Sequence[str]) -> None:
        """The brand font must be a file, libraqm must shape it, and it must have a glyph for every
        character drawn (a missing glyph would render as a notdef box)."""
        if palette.font_path is None:
            raise ConfigInvalidError("data_pack charts need the brand font file (Devanagari label)")
        if not getattr(ft2font, "__libraqm_version__", None):
            raise ConfigInvalidError("matplotlib has no libraqm: Devanagari cannot be shaped")
        try:
            font = ft2font.FT2Font(palette.font_path)
        except OSError:
            raise ConfigInvalidError("brand font file cannot be opened") from None
        missing = sorted(
            {
                ch
                for t in texts
                for ch in t
                if not ch.isspace() and font.get_char_index(ord(ch)) == 0
            }
        )
        if missing:
            raise ConfigInvalidError(
                "brand font lacks glyphs for chart text",
                details={"codepoints": [f"U+{ord(c):04X}" for c in missing]},
            )


@dataclass(frozen=True, slots=True)
class DataPackChart:
    request: DataPackChartRequest
    stills: tuple[RenderedImage, ...]
    """Reveal sequence; the last still shows the whole window (the chart asset)."""
    spec: ChartSpec
    spec_sha256: str
    lag: LagProof
    facts: ChartFactsDocument
    provenance: dict[str, object]
    bars_count: int
    data_start_date: date
    file_sha256: str
    manifest_sha256: str
    dataset_asset_id: str

    @property
    def png(self) -> bytes:
        return self.stills[-1].png

    def attributes(self) -> dict[str, object]:
        """``assets.attributes`` of the chart asset (04 §5.15 keys, CCR-032) plus the proposed
        provenance keys of CCR-256 (``source_path_class``, ``data_pack_manifest_sha256``,
        ``lag_check``)."""
        return {
            "dataset_asset_id": self.dataset_asset_id,
            "spec_sha256": self.spec_sha256,
            "template_id": TEMPLATE_ID,
            "template_version": TEMPLATE_VERSION,
            "instrument": self.request.instrument,
            "timeframe": self.request.timeframe,
            "data_start_date": self.data_start_date.isoformat(),
            "data_end_date": self.lag.data_end_date.isoformat(),
            "bars_count": self.bars_count,
            "source_path_class": "data_pack",
            "data_pack_manifest_sha256": self.manifest_sha256,
            "lag_check": self.lag.as_dict(),
        }


def _offset(a: Annotation, first: int) -> Annotation:
    def shift(v: int | None) -> int | None:
        return None if v is None else v + first

    return a.model_copy(
        update={"bar": shift(a.bar), "from_bar": shift(a.from_bar), "to_bar": shift(a.to_bar)}
    )


class DataPackChartBuilder:
    def __init__(
        self,
        *,
        reader: DataPackReader,
        palette: BrandPalette,
        lag_days: int,
        platform_min_lag_days: int,
        width_px: int,
        height_px: int,
    ) -> None:
        if lag_days < platform_min_lag_days:
            raise ConfigInvalidError("price data lag is below the platform minimum")
        self._reader = reader
        self._palette = palette
        self._lag = lag_days
        self._min_lag = platform_min_lag_days
        self._w, self._h = width_px, height_px

    def build(
        self, request: DataPackChartRequest, *, as_of: date, dataset_asset_id: str
    ) -> DataPackChart:
        if request.timeframe not in DATA_PACK_TIMEFRAMES:  # pragma: no cover - model pattern
            raise InputInvalidError("timeframe is not supported for data_pack charts")
        series = self._reader.load(request.instrument, request.timeframe)
        first, last = series.index_window(request.window_start, request.window_end)
        keep, proof = DataPackLagGuard.check(
            series.bars[first : last + 1],
            timeframe=request.timeframe,
            as_of=as_of,
            lag_days=self._lag,
            platform_min_lag_days=self._min_lag,
            clip_to_lag=request.clip_to_lag,
        )
        last = first + keep - 1
        n = last - first + 1
        annotations = tuple(_offset(a, first) for a in request.annotations)
        verdict = AnnotationValidator.validate(
            annotations=annotations,
            first_bar_index=first,
            last_bar_index=last,
            on_screen_text_allowlist=request.on_screen_text_allowlist,
            template_labels=(HISTORICAL_LABEL,),
        )
        if not verdict.ok:
            raise InputInvalidError(
                "chart annotation rejected (FIN-R13)", details={"reason": str(verdict.reason)}
            )
        connectors = self._connectors(request, series.bars, first, last)
        window = series.bars[first : last + 1]
        start, end_bar = window[0].date.isoformat(), window[-1].date.isoformat()
        title = f"{request.instrument}  {request.timeframe}  {start} to {end_bar}"
        footer = (
            SOURCE_LABEL,
            f"{request.instrument} | {request.timeframe} | {start} to {end_bar} | {n} bars",
        )
        rsi_period = next(
            (p for k, p in map(parse_indicator, request.indicators) if k == "RSI"), None
        )
        caption = None if rsi_period is None else f"RSI {rsi_period} (Wilder)"
        texts = [title, *footer, *(a.text for a in annotations if a.text), caption or ""]
        ChartFontCheck.verify(self._palette, texts)
        spec = ChartSpec(
            dataset_sha256=series.file_sha256,
            window=(first, last),
            instrument=request.instrument,
            timeframe=request.timeframe,
            indicators=request.indicators,
            template_id=TEMPLATE_ID,
            template_version=TEMPLATE_VERSION,
            annotations=annotations,
            aspect_ratio=request.aspect_ratio,
            palette_ref="brand_kit",
            reveal_steps=request.reveal_steps,
            palette_sha256=self._palette.sha256(),
        )
        spec_sha = hashlib.sha256(
            canonical_json(
                {
                    "chart_spec": ChartSpecHasher.hash(spec),
                    "connectors": [c.model_dump(mode="json") for c in request.connectors],
                    "footer": list(footer),
                    "rsi_guides": list(request.rsi_guides),
                    "canvas": [self._w, self._h],
                }
            ).encode("utf-8")
        ).hexdigest()
        stills = ChartRenderer.reveal_sequence(
            ChartRenderInput(
                series=series.bars,
                first_bar_index=first,
                last_bar_index=last,
                title=title,
                indicators=request.indicators,
                annotations=annotations,
                width_px=self._w,
                height_px=self._h,
                palette=self._palette,
                footer_lines=footer,
                connectors=connectors,
                rsi_guides=request.rsi_guides,
                rsi_caption=caption,
                labels_below=frozenset(
                    c.to_bar for c in connectors if c.panel == "PRICE" and c.anchor == "LOW"
                )
                | frozenset(
                    c.from_bar for c in connectors if c.panel == "PRICE" and c.anchor == "LOW"
                ),
            ),
            request.reveal_steps,
        )
        built = ChartFactsBuilder.build(
            ChartDataKind.REAL_HISTORICAL,
            request.timeframe,
            [FactBar(b.date, b.open, b.high, b.low, b.close) for b in window],
        )
        facts = ChartFactsDocument(
            chart_id=request.chart_id,
            instrument=request.instrument,
            dataset_asset_id=dataset_asset_id,
            dataset_sha256=series.file_sha256,
            data_start_date=start,
            data_end_date=proof.data_end_date.isoformat(),
            facts=tuple(ChartFact(fact_id=f.fact_id, statement=f.statement) for f in built.facts),
        )
        provenance: dict[str, object] = {
            "schema": _PROVENANCE_SCHEMA,
            "chart_id": request.chart_id,
            "instrument": request.instrument,
            "timeframe": request.timeframe,
            "data_start_date": start,
            "last_bar_date": end_bar,
            "bars_count": n,
            "dataset_sha256": series.file_sha256,
            "data_pack_manifest_sha256": series.manifest_sha256,
            "spec_sha256": spec_sha,
            "chart_sha256": stills[-1].sha256,
            "lag_check": proof.as_dict(),
            "source_label": SOURCE_LABEL,
            "font_sha256": self._palette.font_sha256,
        }
        return DataPackChart(
            request,
            tuple(stills),
            spec,
            spec_sha,
            proof,
            facts,
            provenance,
            n,
            window[0].date,
            series.file_sha256,
            series.manifest_sha256,
            dataset_asset_id,
        )

    @staticmethod
    def _connectors(
        request: DataPackChartRequest, bars: Sequence[Bar], first: int, last: int
    ) -> tuple[BarConnector, ...]:
        out: list[BarConnector] = []
        rsi_values: list[float | None] | None = None
        for c in request.connectors:
            a, b = first + c.from_offset, first + c.to_offset
            if b > last:
                raise InputInvalidError(
                    "connector ends outside the window (FIN-R13)",
                    details={"reason": "BEYOND_LAST_BAR"},
                )
            if c.panel == "RSI":
                if rsi_values is None:
                    period = next(
                        p for k, p in map(parse_indicator, request.indicators) if k == "RSI"
                    )
                    rsi_values = rsi([float(x.close) for x in bars[: last + 1]], period)
                if rsi_values[a] is None or rsi_values[b] is None:
                    raise InputInvalidError("connector bar has no RSI value (warm-up)")
            out.append(BarConnector(a, b, c.panel, c.anchor))
        return tuple(out)


@dataclass(frozen=True, slots=True)
class RegisteredChart:
    asset: AssetRecord
    reveal: tuple[AssetRecord, ...]
    facts_uri: str
    provenance_uri: str


class DataPackChartRegistrar:
    """Stores the stills and documents and inserts the ``CHART`` asset (tier C, ``CODE_GENERATED``,
    CCR-045) covered by the tenant's standing self-grant row ``self_grant.CODE_GENERATED``
    (blueprint 13.3; a missing row is ``PERMANENT.MISSING_DEPENDENCY``). Ledger rows per shot are
    written by the stage, which knows the job, task and shot interval."""

    def __init__(
        self, *, assets: AssetRepository, blobs: BlobStorage, licences: LicenceRepository
    ) -> None:
        self._assets, self._blobs, self._licences = assets, blobs, licences

    def _put(self, tx: TenantTransaction, name: str, data: bytes) -> str:
        uri = self._blobs.blob_uri(tx.context, "assets", name)
        if not self._blobs.head(tx.context, uri).exists:
            self._blobs.put(tx.context, uri, io.BytesIO(data))
        return str(uri)

    def register(self, tx: TenantTransaction, chart: DataPackChart, title: str) -> RegisteredChart:
        lic = self._licences.self_grant(tx, LicenceSourceType.CODE_GENERATED)
        if lic is None or lic.state is not LicenceState.ACTIVE:
            raise MissingDependencyError("self-grant licence row CODE_GENERATED is missing")
        attrs = chart.attributes()
        records: list[AssetRecord] = []
        for k, img in enumerate(chart.stills):
            is_chart = k == len(chart.stills) - 1
            uri = self._put(tx, f"generated/{img.sha256}.png", img.png)
            records.append(
                self._assets.insert(
                    tx,
                    NewAsset(
                        kind=AssetKind.CHART if is_chart else AssetKind.IMAGE,
                        source_type=LicenceSourceType.CODE_GENERATED,
                        content_sha256=img.sha256,
                        uri=uri,
                        size_bytes=len(img.png),
                        title=title if is_chart else f"{title}_reveal",
                        visual_source_tier=VisualSourceTier.C_CODE_MOTION,
                        licence_id=lic.licence_id,
                        width_px=img.width_px,
                        height_px=img.height_px,
                        attributes=attrs,
                    ),
                )
            )
        facts_raw = chart.facts.model_dump_json().encode("utf-8")
        prov_raw = canonical_json(chart.provenance).encode("utf-8")
        facts_uri = self._put(
            tx, f"chart_facts/{hashlib.sha256(facts_raw).hexdigest()}.json", facts_raw
        )
        prov_uri = self._put(
            tx, f"chart_provenance/{hashlib.sha256(prov_raw).hexdigest()}.json", prov_raw
        )
        return RegisteredChart(records[-1], tuple(records[:-1]), facts_uri, prov_uri)


def provenance_json(chart: DataPackChart) -> dict[str, Any]:
    """The demo / operator view: contract chart facts plus the provenance record."""
    return {
        "chart_facts": chart.facts.model_dump(mode="json"),
        "provenance": chart.provenance,
    }
