"""``agent_08.asset_sourcing.output`` 1.0.0 (blueprint 8.2) and ``agent_08.chart_facts`` 1.0.0 (8.5).

Pydantic models equal to the JSON Schemas of the blueprint (contract tests assert it both ways,
27 section 4.4). Every field is required; nullable ones carry ``None`` explicitly.
"""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from amw_core.contracts.common import AmwModel
from amw_core.enums import (
    ChartDataKind,
    CropMode,
    DataAgeVsLag,
    ReuseKind,
    ShotIntentKind,
    ShotSourcingStatus,
    ShotUnresolvedReason,
    SourcingWarning,
    SubjectAnchor,
    VisualSkipReason,
    VisualSourceTier,
)

from agent_08_visual_assets.models.common import (
    AssetIdStr,
    ChartIdStr,
    Currency,
    IsoDateStr,
    LedgerIdStr,
    LicenceIdStr,
    NonNegInt,
    OverlayIdStr,
    PerceptualHex,
    Permille,
    PosInt,
    Sha256Hex,
    ShotIdStr,
    StorageUri,
)
from agent_08_visual_assets.models.task_input import Aspect

ShotUsage = Literal["SHOT", "IMAGE", "AI_OUTPUT", "TEMPLATE"]
ShotSourceType = Literal[
    "OWNER_MADE", "CLIENT_SUPPLIED", "PAID_STOCK", "FREE_STOCK", "CODE_GENERATED", "AI_GENERATED", "FONT"
]
LedgerIds = tuple[LedgerIdStr, ...]


class Crop(AmwModel):
    mode: CropMode
    anchor: SubjectAnchor | None
    keep_permille: Annotated[int, Field(ge=1, le=1000, strict=True)]


class Media(AmwModel):
    width_px: PosInt
    height_px: PosInt
    duration_ms: PosInt | None
    source_in_ms: NonNegInt
    crop: Crop


class PerceptualFrame(AmwModel):
    frame_ms: NonNegInt
    hash_hex: PerceptualHex


class Fingerprints(AmwModel):
    sha256: Sha256Hex
    algo_version: PosInt
    perceptual_frames: tuple[PerceptualFrame, ...]


class SkipEntry(AmwModel):
    tier: VisualSourceTier
    reason: VisualSkipReason


class ReuseInfo(AmwModel):
    kind: ReuseKind
    source_asset_id: AssetIdStr


class ChartInfo(AmwModel):
    chart_id: ChartIdStr
    data_kind: ChartDataKind
    instrument: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,64}$")] | None
    timeframe: Literal["1D", "1W", "1M"]
    data_start_date: IsoDateStr | None
    data_end_date: IsoDateStr | None
    data_age_vs_lag: DataAgeVsLag | None
    earliest_compliant_publish_date: IsoDateStr | None
    dataset_asset_id: AssetIdStr | None
    dataset_sha256: Sha256Hex | None
    case_asset_id: AssetIdStr
    spec_sha256: Sha256Hex
    template_id: Annotated[str, StringConstraints(max_length=64)]
    template_version: PosInt
    bars_count: NonNegInt
    annotation_count: NonNegInt
    method_content: bool


class Disclosure(AmwModel):
    is_realistic_synthetic: bool
    depicts_real_person: bool


class Selection(AmwModel):
    fit: Literal["STRONG", "ACCEPTABLE"]
    candidate_count: PosInt


class ShotResult(AmwModel):
    shot_id: ShotIdStr
    scene_id: Annotated[str, StringConstraints(max_length=32)]
    content_key: Sha256Hex
    start_ms: NonNegInt
    end_ms: PosInt
    aspect_ratio: Aspect
    intent_kind: ShotIntentKind
    status: ShotSourcingStatus
    tier: VisualSourceTier | None
    asset_id: AssetIdStr | None
    asset_uri: StorageUri | None
    source_type: ShotSourceType | None
    licence_id: LicenceIdStr | None
    ledger_entry_ids: LedgerIds
    usage_kind: ShotUsage | None
    media: Media | None
    fingerprints: Fingerprints | None
    skips: tuple[SkipEntry, ...]
    warnings: tuple[SourcingWarning, ...]
    unresolved_reason: ShotUnresolvedReason | None
    reuse: ReuseInfo | None
    chart: ChartInfo | None
    disclosure: Disclosure
    cost_micros: NonNegInt
    selection: Selection | None


class OverlayResult(AmwModel):
    overlay_id: OverlayIdStr
    kind: Literal[
        "BRAND_STING", "LOWER_THIRD", "CAPTION_CARD", "CHAPTER_CARD", "DISCLAIMER_CARD", "END_SCREEN"
    ]
    start_ms: NonNegInt
    end_ms: PosInt
    template_asset_id: AssetIdStr
    source_type: Literal["OWNER_MADE", "CODE_GENERATED"]
    licence_id: LicenceIdStr
    ledger_entry_ids: Annotated[LedgerIds, Field(min_length=1)]
    usage_kind: Literal["TEMPLATE"]


class FontResult(AmwModel):
    asset_id: AssetIdStr
    licence_id: LicenceIdStr
    ledger_entry_ids: Annotated[LedgerIds, Field(min_length=1)]
    usage_kind: Literal["FONT"]
    used_from_ms: Literal[0]
    used_to_ms: PosInt


class MusicBedResult(AmwModel):
    asset_id: AssetIdStr
    licence_id: LicenceIdStr
    ledger_entry_ids: Annotated[LedgerIds, Field(min_length=1)]
    usage_kind: Literal["MUSIC_BED"]
    used_from_ms: NonNegInt
    used_to_ms: PosInt


class ChartFactsRef(AmwModel):
    chart_id: ChartIdStr
    document_uri: StorageUri
    document_sha256: Sha256Hex
    fact_count: Annotated[int, Field(ge=1, le=20, strict=True)]


class TierShareEntry(AmwModel):
    ms: NonNegInt
    share_permille: Permille


class ByTier(AmwModel):
    A_OWNER_REAL: TierShareEntry
    B_LICENSED_STOCK: TierShareEntry
    C_CODE_MOTION: TierShareEntry
    D_AI_VIDEO: TierShareEntry
    E_AI_STILL: TierShareEntry


class TierMix(AmwModel):
    total_visual_ms: NonNegInt
    by_tier: ByTier


class AiBroll(AmwModel):
    clips: NonNegInt
    total_ms: NonNegInt
    cost_micros: NonNegInt
    currency: Currency


class CostSummary(AmwModel):
    llm_micros: NonNegInt
    stock_micros: NonNegInt
    ai_video_micros: NonNegInt
    ai_still_micros: NonNegInt
    currency: Currency
    figure_kind: Literal["ESTIMATE", "VERIFIED"]


class LicenceWarning(AmwModel):
    code: Literal["LICENCE_EXPIRING", "NO_INDEMNIFICATION", "RELEASE_RECORD_ABSENT"]
    shot_id: ShotIdStr | None
    licence_id: LicenceIdStr | None


class LicenceSummary(AmwModel):
    ledger_rows_written: NonNegInt
    overlay_rows: NonNegInt
    font_rows: NonNegInt
    music_rows: NonNegInt
    warnings: tuple[LicenceWarning, ...]


class ReuseSummary(AmwModel):
    reused_exact: NonNegInt
    reused_near_duplicate: NonNegInt
    new_assets: NonNegInt
    near_duplicate_flags: NonNegInt


class PromptProvenance(AmwModel):
    prompt_id: str
    sha256: Sha256Hex


class RulePackVersion(AmwModel):
    key: str
    version: int


class AdapterProvenance(AmwModel):
    capability: Literal["llm", "stock_search", "video_gen", "image_gen", "media_probe"]
    config_ref: Annotated[str, StringConstraints(max_length=64)]


class Provenance(AmwModel):
    prompts: tuple[PromptProvenance, ...]
    rule_pack_versions: tuple[RulePackVersion, ...]
    adapters: tuple[AdapterProvenance, ...]
    config_sha256: Sha256Hex
    lag_days: NonNegInt | None
    shot_plan_sha256: Sha256Hex
    script_sha256: Sha256Hex


class RefusalEntry(AmwModel):
    step: Literal["query_plan", "candidate_rank"]
    batch_id: str
    reason: Literal["INSUFFICIENT_INPUT", "OUT_OF_SCOPE", "CONFLICTING_INSTRUCTIONS", "UNSAFE_CONTENT"]


class SourcingOutput(AmwModel):
    """Payload ``agent_08.asset_sourcing.output`` 1.0.0."""

    iteration: NonNegInt
    gate_verdict: Literal["PASSED", "FAILED"]
    shots: tuple[ShotResult, ...]
    overlays: tuple[OverlayResult, ...]
    fonts: tuple[FontResult, ...]
    music_beds: tuple[MusicBedResult, ...]
    chart_facts: tuple[ChartFactsRef, ...]
    tier_mix: TierMix
    ai_broll: AiBroll
    cost_summary: CostSummary
    licence_summary: LicenceSummary
    reuse_summary: ReuseSummary
    earliest_compliant_publish_date: IsoDateStr | None
    unresolved_shot_ids: tuple[ShotIdStr, ...]
    provenance: Provenance
    refusals: tuple[RefusalEntry, ...]


class ChartFact(AmwModel):
    fact_id: Annotated[str, StringConstraints(pattern=r"^f[0-9]{2}$")]
    statement: Annotated[str, StringConstraints(min_length=1, max_length=300)]


class ChartFactsDocument(AmwModel):
    """Agent document ``agent_08.chart_facts`` 1.0.0; evidence ref is ``<chart_id>#<fact_id>``."""

    chart_id: ChartIdStr
    instrument: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,64}$")]
    dataset_asset_id: AssetIdStr
    dataset_sha256: Sha256Hex
    data_start_date: IsoDateStr
    data_end_date: IsoDateStr
    facts: Annotated[tuple[ChartFact, ...], Field(min_length=1, max_length=20)]
