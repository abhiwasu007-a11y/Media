"""SubjectOptionBuilder (F-07; blueprint 6.3). Pure eligibility by code, never by the model."""

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from agent_11_thumbnail_design.models import PictureOption


class AssetFacts(BaseModel):
    """The eligibility facts of one tenant asset (already read inside the tenant transaction)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sha: str
    label: str
    kind: str
    status: str
    source_type: str
    licence_state: str
    covers_monetized: bool
    expired: bool
    channel_allowed: bool
    width_px: int
    height_px: int
    depicts_real_person: bool
    release_ref: bool
    data_age_vs_lag: str
    label_free: bool
    direction_balanced: bool
    third_party_permission: str | None = None


class GlyphFacts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    label: str
    direction_neutral: bool


@dataclass(frozen=True, slots=True)
class PictureBuildConfig:
    min_w: int
    min_h: int
    faces_allowed: bool
    chart_still_allowed: bool


@dataclass(frozen=True, slots=True)
class ExcludedPicture:
    reason: str
    asset: str | None = None
    glyph: str | None = None

    def as_dict(self) -> dict[str, str]:
        return (
            {"asset": self.asset, "reason": self.reason}
            if self.asset
            else {
                "glyph": str(self.glyph),
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class PictureOptions:
    options: tuple[PictureOption, ...]
    excluded: tuple[ExcludedPicture, ...]


_SOURCE_OK = frozenset({"OWNER_MADE", "CLIENT_SUPPLIED"})
_KINDS = frozenset({"IMAGE", "CHART"})


def asset_exclusion(a: AssetFacts, cfg: PictureBuildConfig, finance: bool) -> str | None:
    if a.status != "ACTIVE":
        return "STATUS"
    if a.kind not in _KINDS:
        return "KIND"
    if a.source_type not in _SOURCE_OK:
        return "SOURCE_TYPE"
    if (
        a.licence_state != "ACTIVE"
        or not a.covers_monetized
        or a.third_party_permission in ("UNKNOWN", "NOT_PERMITTED")
    ):
        return "LICENCE"
    if a.expired:
        return "EXPIRED"
    if not a.channel_allowed:
        return "CHANNEL"
    if a.width_px < cfg.min_w or a.height_px < cfg.min_h:
        return "RESOLUTION"
    if a.depicts_real_person and not (cfg.faces_allowed and a.release_ref and not finance):
        return "PERSON"
    if a.kind == "CHART":
        if not cfg.chart_still_allowed:
            return "CHART_DISABLED"
        if a.data_age_vs_lag != "OLDER_THAN_LAG":
            return "CHART_LAG"
        if not a.label_free:
            return "CHART_LABEL"
        if not a.direction_balanced:
            return "CHART_DIRECTION"
    return None


def build_picture_options(
    *,
    assets: Sequence[AssetFacts],
    glyphs: Sequence[GlyphFacts],
    finance: bool,
    cfg: PictureBuildConfig,
    requested_glyphs: frozenset[str] = frozenset(),
) -> PictureOptions:
    """``requested_glyphs``: glyph keys a template explicitly requests. On a finance channel the
    default is NO icon (owner decision D13 item 3, Q-O31): a glyph is offered only if it is on the
    strict neutral allow-list AND requested. Non-finance channels are not restricted here."""
    owner: list[PictureOption] = []
    excluded: list[ExcludedPicture] = []
    for a in sorted(assets, key=lambda x: x.sha):
        reason = asset_exclusion(a, cfg, finance)
        if reason:
            excluded.append(ExcludedPicture(reason, asset=a.sha))
        else:
            owner.append(
                PictureOption(
                    option_id="o00",
                    kind="OWNER_IMAGE",
                    key=a.sha,
                    label=a.label,
                    has_face=a.depicts_real_person,
                    direction_neutral=True,
                )
            )
    code: list[PictureOption] = []
    for g in sorted(glyphs, key=lambda x: x.key):
        if finance and not g.direction_neutral:
            excluded.append(ExcludedPicture("FINANCE_DIRECTION", glyph=g.key))
            continue
        if finance and g.key not in requested_glyphs:
            excluded.append(ExcludedPicture("FINANCE_NO_ICON", glyph=g.key))
            continue
        code.append(
            PictureOption(
                option_id="o00",
                kind="CODE_GLYPH",
                key=g.key,
                label=g.label,
                has_face=False,
                direction_neutral=g.direction_neutral,
            )
        )
    none = PictureOption(
        option_id="o00",
        kind="NONE",
        key="none",
        label="text only",
        has_face=False,
        direction_neutral=True,
    )
    ordered = [*owner, *code, none]
    numbered = tuple(
        o.model_copy(update={"option_id": f"o{i + 1:02d}"}) for i, o in enumerate(ordered)
    )
    return PictureOptions(numbered, tuple(excluded))
