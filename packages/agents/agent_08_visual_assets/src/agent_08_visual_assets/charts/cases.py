"""``ChartCase`` and ``ChartCaseLibrary`` (D5, blueprint 6.4(2)).

A chart case is an owner-curated JSON document registered as a ``DOCUMENT`` asset. Agent 08 only
matches and renders it: it never generates, edits or "improves" a case, and the matching key holds
no date, time or session (owner rule C.4; U-07 asserts the signature).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from amw_core.enums import ChartDataKind

from agent_08_visual_assets.charts.annotations import Annotation

OUTCOMES = ("WORKED", "FAILED", "BOTH", "NOT_APPLICABLE")
CaseId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")]


class Window(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    first_bar_index: Annotated[int, Field(ge=0)]
    last_bar_index: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.last_bar_index < self.first_bar_index:
            raise ValueError("window last bar precedes the first bar")
        return self


class ChartCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: CaseId
    data_kind: ChartDataKind
    instrument: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")] | None
    timeframe: Annotated[str, Field(pattern=r"^(1D|1W|1M)$")]
    dataset_asset_id: str | None
    window: Window | None
    indicators: tuple[str, ...]
    pattern_concept_ids: tuple[str, ...]
    outcome: Annotated[str, Field(pattern=r"^(WORKED|FAILED|BOTH|NOT_APPLICABLE)$")]
    annotations: tuple[Annotation, ...]
    method_content: bool
    release_approval_id: str | None = None
    template_id: str
    schematic_points: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def _shape(self) -> Self:
        real = self.data_kind is ChartDataKind.REAL_HISTORICAL
        if real and (self.instrument is None or self.dataset_asset_id is None or self.window is None):
            raise ValueError("a real historical case needs instrument, dataset and window")
        if not real and (self.instrument is not None or self.dataset_asset_id is not None):
            raise ValueError("a schematic case has no instrument and no dataset")
        if not real and not self.schematic_points:
            raise ValueError("a schematic case carries its points")
        if self.method_content and self.release_approval_id is None:
            raise ValueError("method content needs a release approval id")
        return self


@dataclass(frozen=True, slots=True)
class ChartRequest:
    """``chart_requests[]`` item of the script (agent_05 section 8.2)."""

    chart_id: str
    chart_kind: ChartDataKind
    instrument: str | None
    timeframe: str
    indicators: tuple[str, ...]
    pattern_concept_id: str
    outcome_shown: str


@dataclass(frozen=True, slots=True)
class StoredCase:
    asset_id: str
    case: ChartCase
    sha256: str
    last_used: datetime | None = None
    """Last use for the requesting channel; ``None`` = never (least recently used)."""


class ChartCaseLibrary:
    @staticmethod
    def match(request: ChartRequest, cases: Sequence[StoredCase]) -> StoredCase | None:
        """Key: (instrument, timeframe, pattern concept, outcome in {shown, BOTH}, indicators
        subset). Several matches: least recently used for the channel, then lowest case id."""
        hits = [
            c
            for c in cases
            if c.case.data_kind is request.chart_kind
            and c.case.instrument == request.instrument
            and c.case.timeframe == request.timeframe
            and request.pattern_concept_id in c.case.pattern_concept_ids
            and c.case.outcome in (request.outcome_shown, "BOTH")
            and set(request.indicators) <= set(c.case.indicators)
        ]
        if not hits:
            return None
        epoch = datetime.min
        return min(
            hits,
            key=lambda c: (
                c.last_used.replace(tzinfo=None) if c.last_used is not None else epoch,
                c.case.case_id,
            ),
        )


def label_set(templates: Mapping[str, Sequence[str]], template_id: str) -> tuple[str, ...]:
    """Versioned template label set of a chart template (e.g. "Historical example")."""
    return tuple(templates.get(template_id, ()))
