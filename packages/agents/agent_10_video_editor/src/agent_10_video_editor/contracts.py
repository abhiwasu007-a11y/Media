"""Payload models of the three task types (blueprint 10 sections 7, 8; CCR-018).

Pydantic equivalents of the JSON Schemas of the blueprint (``extra = forbid``); the contract tests
compare field names, required sets and patterns against the schemas embedded in the blueprint.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StringConstraints

_UUID7 = r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
RenderIdStr = Annotated[str, StringConstraints(pattern=rf"^rnd_{_UUID7}$")]
AssetIdStr = Annotated[str, StringConstraints(pattern=rf"^ast_{_UUID7}$")]
LicenceIdStr = Annotated[str, StringConstraints(pattern=rf"^lic_{_UUID7}$")]
LedgerIdStr = Annotated[str, StringConstraints(pattern=rf"^lcu_{_UUID7}$")]
Language = Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")]
Uri = Annotated[str, StringConstraints(max_length=1024)]
PresetKey = Literal["yt_master_1080p", "yt_master_1440p", "shorts_9x16"]
RemedyStage = Literal["s07_voice", "s08_assets", "s09_plan", "s10_render"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BlobRef(_Strict):
    uri: Uri
    sha256: Sha256


class BlobRefSized(_Strict):
    uri: Uri
    sha256: Sha256
    size_bytes: Annotated[int, Field(ge=1, strict=True)]


class MusicBed(_Strict):
    asset_id: AssetIdStr
    licence_id: LicenceIdStr
    ledger_entry_ids: Annotated[tuple[LedgerIdStr, ...], Field(min_length=1)]
    music_stem: BlobRef
    voice_stem: BlobRef


# ----------------------------------------------------------------------------- inputs (7.2, 7.3)


class RenderInput(_Strict):
    render_kind: Literal["MASTER"]
    preset_key: PresetKey
    aspect_ratio: Literal["16:9", "9:16"]
    language: Language
    iteration: Annotated[int, Field(ge=0, strict=True)]
    verified_script_sha256: Sha256
    previous_render_ref: BlobRef | None
    music_bed: MusicBed | None


class SubtitlesInput(_Strict):
    render_id: RenderIdStr
    language: Language
    iteration: Annotated[int, Field(ge=0, strict=True)]
    verified_script_sha256: Sha256
    caption_style: None


class TechnicalQcInput(_Strict):
    render_id: RenderIdStr
    render_sha256: Sha256
    qc_profile: Literal["qc.long_form", "qc.shorts"]
    iteration: Annotated[int, Field(ge=0, strict=True)]
    music_bed: MusicBed | None
    destination: Literal["MONETIZED_YOUTUBE", "NON_MONETIZED"]


# ----------------------------------------------------------------------------- render output (8.1)


class FpsOut(_Strict):
    num: Annotated[int, Field(ge=1, strict=True)]
    den: Annotated[int, Field(ge=1, strict=True)]


class SegmentsOut(_Strict):
    planned: Annotated[int, Field(ge=1, strict=True)]
    encoded: Annotated[int, Field(ge=0, strict=True)]
    reused: Annotated[int, Field(ge=0, strict=True)]
    resumed_from_checkpoint: StrictBool


class GopOut(_Strict):
    gop_frames: Annotated[int, Field(ge=1, strict=True)]
    closed_gop: StrictBool
    idr_at_segment_start: StrictBool


class ColourOut(_Strict):
    primaries: str
    transfer: str
    matrix: str
    range: str


class EncoderOut(_Strict):
    ffmpeg_build_id: Annotated[str, StringConstraints(max_length=128)]
    video_encoder: Annotated[str, StringConstraints(max_length=64)]
    args_sha256: Sha256
    preset_key: PresetKey
    gop: GopOut
    colour: ColourOut
    audio_bitrate_nominal_bps: Annotated[int, Field(ge=1, strict=True)]


class ProbeOut(_Strict):
    width_px: StrictInt
    height_px: StrictInt
    video_codec: str
    audio_codec: str
    video_bitrate_bps: StrictInt
    audio_bitrate_avg_bps: StrictInt
    audio_sample_rate_hz: StrictInt
    channels: StrictInt


class GuardsOut(_Strict):
    market_hours_checks: Annotated[int, Field(ge=0, strict=True)]
    night_window_checks: Annotated[int, Field(ge=0, strict=True)]
    drained: StrictBool


class ProvenanceOut(_Strict):
    config_keys_family: Literal["agent_10.*"]
    ffmpeg_version_string_sha256: Sha256


class RenderOutput(_Strict):
    render_id: RenderIdStr
    render_ref: BlobRefSized
    timeline_ref: BlobRef
    fps: FpsOut
    frame_count: Annotated[int, Field(ge=1, strict=True)]
    duration_ms: Annotated[int, Field(ge=1, strict=True)]
    segments: SegmentsOut
    encoder: EncoderOut
    probe: ProbeOut
    render_ms: Annotated[int, Field(ge=0, strict=True)]
    guards: GuardsOut
    provenance: ProvenanceOut


# ----------------------------------------------------------------------------- subtitles (8.2)


class SrtEntry(_Strict):
    language: Language
    uri: Uri
    sha256: Sha256
    size_bytes: Annotated[int, Field(ge=1, strict=True)]
    cue_count: Annotated[int, Field(ge=1, strict=True)]
    asset_id: AssetIdStr
    last_cue_end_ms: Annotated[int, Field(ge=1, strict=True)]


class SubtitlesOutput(_Strict):
    srt: Annotated[tuple[SrtEntry, ...], Field(min_length=1)]
    warnings: tuple[
        Annotated[
            str,
            StringConstraints(
                pattern=r"^(OVERLONG_TOKEN|CUE_SHORTER_THAN_MIN):[A-Za-z0-9_.-]{1,32}$"
            ),
        ],
        ...,
    ]
    timeline_source: Literal["PROVIDER_CLIPS", "OWNER_MARKS"]
    sync_basis: Literal["NARRATION_TIMELINE"]


# ----------------------------------------------------------------------------- QC output (8.3)


class FailureOut(_Strict):
    check_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_.-]{3,96}$")]
    shot_ids: tuple[Annotated[str, StringConstraints(pattern=r"^sh[0-9]{2,4}$")], ...]
    measured: float | int | str | None
    threshold: float | int | str | None
    unit: Annotated[str, StringConstraints(max_length=16)]
    remedy_stage: RemedyStage
    message: Annotated[str, StringConstraints(max_length=240)]


class CountsOut(_Strict):
    # field names are the schema's (`pass` is a keyword, so it is set through an alias)
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    pass_: Annotated[int, Field(ge=0, strict=True, alias="pass")]
    fail: Annotated[int, Field(ge=0, strict=True)]
    warn: Annotated[int, Field(ge=0, strict=True)]
    skipped: Annotated[int, Field(ge=0, strict=True)]


class MeasurementsOut(_Strict):
    integrated_lufs: float
    true_peak_dbtp: float
    lra_lu: float
    video_bitrate_bps: StrictInt
    audio_bitrate_nominal_bps: StrictInt
    audio_bitrate_avg_bps: StrictInt
    duration_ms: StrictInt
    expected_ms: StrictInt
    black_runs: Annotated[int, Field(ge=0, strict=True)]
    freeze_runs: Annotated[int, Field(ge=0, strict=True)]
    silence_runs: Annotated[int, Field(ge=0, strict=True)]
    scene_events: Annotated[int, Field(ge=0, strict=True)]


class TierMixOut(_Strict):
    A_OWNER_REAL: Annotated[int, Field(ge=0, le=1000, strict=True)]
    B_LICENSED_STOCK: Annotated[int, Field(ge=0, le=1000, strict=True)]
    C_CODE_MOTION: Annotated[int, Field(ge=0, le=1000, strict=True)]
    D_AI_VIDEO: Annotated[int, Field(ge=0, le=1000, strict=True)]
    E_AI_STILL: Annotated[int, Field(ge=0, le=1000, strict=True)]
    ai_video_ms: Annotated[int, Field(ge=0, strict=True)]


class EvidenceOut(_Strict):
    manifest_ref: BlobRef
    contact_sheet_ref: BlobRef
    sample_frames_ref: tuple[BlobRef, ...]
    loudness_series_ref: BlobRef
    report_ref: BlobRef


class SelftestOut(_Strict):
    ffmpeg_build_id: Annotated[str, StringConstraints(max_length=128)]
    selftest_ref: BlobRef
    passed: StrictBool


class TechnicalQcOutput(_Strict):
    gate_verdict: Literal["PASSED", "FAILED"]
    failures: tuple[FailureOut, ...]
    render_id: RenderIdStr
    render_sha256: Sha256
    profile: Literal["qc.long_form", "qc.shorts"]
    iteration: Annotated[int, Field(ge=0, strict=True)]
    counts: CountsOut
    measurements: MeasurementsOut
    tier_mix: TierMixOut
    evidence: EvidenceOut
    selftest: SelftestOut


# ----------------------------------------------------------------------------- evidence manifest


class EvidenceFrame(_Strict):
    frame_id: Annotated[str, StringConstraints(pattern=r"^f[0-9]{2,3}$")]
    frame_index: Annotated[int, Field(ge=0, strict=True)]
    t_ms: Annotated[int, Field(ge=0, strict=True)]
    shot_id: Annotated[str, StringConstraints(pattern=r"^sh[0-9]{2,4}$")] | None
    uri: Uri
    sha256: Sha256


class EvidenceOverlay(_Strict):
    overlay_id: Annotated[str, StringConstraints(pattern=r"^ov[0-9]{2,4}$")]
    kind: Annotated[str, StringConstraints(max_length=32)]
    start_ms: Annotated[int, Field(ge=0, strict=True)]
    end_ms: Annotated[int, Field(ge=1, strict=True)]


class EvidenceManifest(_Strict):
    """``agent_10.evidence_manifest`` 1.0.0: the document Agent 16 reads as ``frames_ref``."""

    render_id: RenderIdStr
    render_sha256: Sha256
    timeline_sha256: Sha256
    fps_num: Annotated[int, Field(ge=1, strict=True)]
    fps_den: Annotated[int, Field(ge=1, strict=True)]
    total_frames: Annotated[int, Field(ge=1, strict=True)]
    frames: Annotated[tuple[EvidenceFrame, ...], Field(min_length=1, max_length=999)]
    contact_sheet: BlobRef
    overlays: tuple[EvidenceOverlay, ...]
