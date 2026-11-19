"""Typed inputs and outputs of the delivery bundle (3A slice spec section 4; 24 section 4).

Everything is passed in by the caller (the runtime lane): the bundle builder reads the stored
artefacts by reference with SHA-256 verification and never decides policy values (banner text,
disclaimer wording, size limits, caps) itself.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from amw_core.contracts.common import JobIdStr, OrgIdStr, Sha256Hex, StorageUri
from amw_core.cost.report import CostStageReport
from amw_core.enums import ComplianceVerdict

SAFE_ID = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
LANGUAGE = r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$"
MAX_MACHINE_POINTS = 79
"""Machine rows score at most 79 of 100; the rest needs HUMAN rows (18 section 9, R1)."""
TOTAL_POINTS = 100


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ArtefactRef(_Model):
    """A stored blob read by reference: URI plus the SHA-256 and size recorded at write time."""

    uri: StorageUri
    sha256: Sha256Hex
    size_bytes: Annotated[int, Field(ge=0, strict=True)]


class ThumbnailOption(_Model):
    option_id: Annotated[str, StringConstraints(pattern=SAFE_ID)]
    ref: ArtefactRef
    media_type: Literal["image/png", "image/jpeg", "image/webp"]


class SubtitleFile(_Model):
    language: Annotated[str, StringConstraints(pattern=LANGUAGE)]
    ref: ArtefactRef


class CheckVerdict(StrEnum):
    PASS = "PASS"  # noqa: S105
    WARN = "WARN"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"


class QcCheckRow(_Model):
    check_id: Annotated[str, StringConstraints(min_length=1, max_length=96)]
    verdict: CheckVerdict
    measured: str | None = None
    threshold: str | None = None
    unit: str | None = None


class ScoreSource(StrEnum):
    MACHINE = "MACHINE"
    HUMAN = "HUMAN"


class ScoreRow(_Model):
    """One scored dimension from one source (machine row or human row)."""

    dimension: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    source: ScoreSource
    max_points: Annotated[Decimal, Field(ge=0)]
    points: Annotated[Decimal, Field(ge=0)]
    evidence: Annotated[str, StringConstraints(max_length=500)] = ""

    @model_validator(mode="after")
    def _points_within_max(self) -> ScoreRow:
        if self.points > self.max_points:
            raise ValueError("points exceed max_points")
        return self


class GateRow(_Model):
    gate_id: Annotated[str, StringConstraints(min_length=1, max_length=96)]
    passed: bool
    remedy: str | None = None
    blocking: bool = True


class ComplianceInfo(_Model):
    """The compliance verdict and the delivery authorisation for the render being delivered."""

    verdict: ComplianceVerdict
    authorised_for_delivery: bool
    authorisation_verdict_id: Annotated[str, StringConstraints(min_length=1)]
    render_sha256: Sha256Hex
    """The render hash the verdict and the owner's approval refer to (must equal the 16:9 file)."""


class DisclaimerInfo(_Model):
    """FIN-R10 text as supplied by the runtime lane; the status label is never dropped."""

    text: Annotated[str, StringConstraints(min_length=1)]
    version: Annotated[str, StringConstraints(min_length=1)]
    status_label: Annotated[str, StringConstraints(min_length=1)]
    """For example ``DRAFT - not lawyer-approved``."""


class BundleLimits(_Model):
    """Size limits from configuration (the caller passes them; no literal in this package)."""

    max_file_bytes: Annotated[int, Field(ge=1, strict=True)]
    max_total_bytes: Annotated[int, Field(ge=1, strict=True)]
    max_thumbnail_bytes: Annotated[int, Field(ge=1, strict=True)]


class BundleInputs(_Model):
    org_id: OrgIdStr
    job_id: JobIdStr
    deliverable_preset: Annotated[str, StringConstraints(min_length=1)] = "yt_master_1080p"
    production_type_key: Annotated[str, StringConstraints(min_length=1)]
    production_type_version: Annotated[str, StringConstraints(min_length=1)]
    config_version: Annotated[str, StringConstraints(min_length=1)]
    metadata_present: bool
    banner: Annotated[str, StringConstraints(min_length=1)]
    """Header banner for every report, e.g. ``PLUMBING TEST - NOT QUALITY`` (caller decides)."""
    disclaimer: DisclaimerInfo
    disclosure_note: Annotated[str, StringConstraints(min_length=1)]
    """Plain words about the disclosure decision and that the owner applies the label by hand."""
    video_16x9: ArtefactRef
    video_9x16: ArtefactRef | None = None
    shorts_wanted: bool = False
    thumbnails: Annotated[tuple[ThumbnailOption, ...], Field(min_length=1)]
    chosen_thumbnail_id: Annotated[str, StringConstraints(pattern=SAFE_ID)]
    subtitles: Annotated[tuple[SubtitleFile, ...], Field(min_length=1)]
    primary_language: Annotated[str, StringConstraints(pattern=LANGUAGE)]
    qc_checks: tuple[QcCheckRow, ...]
    score_rows: tuple[ScoreRow, ...]
    gates: tuple[GateRow, ...]
    compliance: ComplianceInfo
    cost_report: CostStageReport
    limits: BundleLimits


class ManifestFile(_Model):
    name: str
    sha256: Sha256Hex
    size_bytes: int
    media_type: str


class BundleManifest(_Model):
    """Returned by ``build_bundle``; ``manifest.json`` holds the same data (without the zip)."""

    schema_id: Literal["amw.delivery_manifest"] = "amw.delivery_manifest"
    schema_version: Literal[1] = 1
    org_id: str
    job_id: str
    deliverable_preset: str
    production_type_key: str
    production_type_version: str
    config_version: str
    metadata_present: bool
    banner: str
    render_sha256: Sha256Hex
    chosen_thumbnail_id: str
    shorts_included: bool
    files: tuple[ManifestFile, ...]
    manifest_sha256: Sha256Hex
    """SHA-256 of ``manifest.json`` (delivery.file key material, 24 section 4)."""
    zip_name: str
    zip_sha256: Sha256Hex
    zip_size_bytes: int
