"""Fact extractors of Agent 16 (CCR-209; blueprint sections 9, 15.1a, 15.1b).

``DocumentGateFactExtractor`` (gate facts), ``DocumentUniquenessExtractor`` (S2 facts) and
``DocumentScoreFactExtractor`` (``quality_score`` deterministic facts) read the upstream
documents through **tolerant slice models** (03 section 2.3 rule 2: unread fields are ignored,
the producer's schema is the full contract) and the database rows of section 15.1a through the
``FactRowReader`` port. Rules that hold everywhere in this module:

* no fact is a constant; a source that is absent yields the stated missing-input result, and a
  missing result is always the **stricter** one (compliance fails closed, never passes on
  missing input);
* a document that does not parse is ``PERMANENT.SCHEMA_INVALID``; a document that is absent is
  ``PERMANENT.MISSING_DEPENDENCY``; a document that contradicts the request or the rows is
  ``PERMANENT.INPUT_INVALID``;
* what upstream blobs claim about an approval is never read here (``GateInputAssembler`` derives
  approval states from the steps).
"""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from agent_16_compliance_qa.assembler import (
    ComplianceGateInput,
    ExtractedGate,
    ReleaseRef,
)
from agent_16_compliance_qa.authorisation.stage import ApprovalStepVerifier
from agent_16_compliance_qa.checks import rules as R  # noqa: N812
from agent_16_compliance_qa.config import Agent16Config
from agent_16_compliance_qa.gate import GateInputs, SourceItem
from agent_16_compliance_qa.judge.models import ItemChart, ItemClaim, ParaphrasePair, Passage
from agent_16_compliance_qa.nearcopy import NearCopyResult, PrivateChunkReader, check_near_copy
from agent_16_compliance_qa.scoring.aggregate import (
    ClaimFact,
    DeterministicInputs,
    GateFacts,
    QcRow,
    ScriptFacts,
    ThumbnailFacts,
)
from agent_16_compliance_qa.stages import UniquenessFacts
from agent_16_compliance_qa.uniqueness import Segment
from amw_core.contracts.error import violation
from amw_core.enums import (
    ApprovalKind,
    AudienceKind,
    CheckVerdict,
    ClaimStatus,
    ComplianceVerdict,
    DataAgeVsLag,
    DisclosureDecision,
    LicenceState,
    PresenterKind,
    VisualSourceTier,
)
from amw_core.errors import (
    InputInvalidError,
    MissingDependencyError,
    SchemaInvalidError,
)
from amw_core.interfaces.tenancy_context import TenantTransaction

FINANCE_PACK: Final = "rp.finance_sebi_in"
SENSITIVE_CATEGORIES: Final = frozenset({"finance", "health", "political"})
THREE_A_TYPES: Final = frozenset({"CHANNEL_LONG_FORM", "SHORTS"})
REQUIRED_THUMBNAIL_VARIANTS: Final = 3
FRAMES_SCHEMA_CAP: Final = 60
"""``agent_16.compliance_gate.frames.input`` allows at most 60 frames (prompt schema A)."""
_JUDGED_CHECKS: Final = ("qc.watermark.visual", "qc.visual.no_synthetic_presenter")
_PRICE_CLAIM_TYPES: Final = frozenset({"HISTORICAL_MARKET", "PRICE_LEVEL"})
_THIRD_PARTY_SOURCES: Final = frozenset({"CLIENT_SUPPLIED"})
_STOCK_SOURCES: Final = frozenset({"PAID_STOCK", "FREE_STOCK", "FONT"})


class _Slice(BaseModel):
    """Tolerant reader of another component's document (03 section 2.3 rule 2, CCR-200)."""

    model_config = ConfigDict(frozen=True, extra="ignore")


# --- slice models ---------------------------------------------------------------------------
class _ConceptRef(_Slice):
    citation_refs: tuple[str, ...] = ()


class _ScriptSegment(_Slice):
    segment_id: str
    kind: str = "BODY"
    section_id: str | None = None
    scene_id: str | None = None
    text: str
    method_label: bool = False
    chart_ref: str | None = None
    concept_refs: tuple[_ConceptRef, ...] = ()


class _ScriptScene(_Slice):
    scene_id: str
    on_screen_text: tuple[str, ...] = ()
    method_label: bool = False


class _ScriptSection(_Slice):
    section_id: str
    section_kind: str = "CONCEPT"


class _Promise(_Slice):
    working_title_local: str | None = None
    promise_statement: str | None = None
    promise_key_terms: tuple[str, ...] = ()


class _DisclaimerSlot(_Slice):
    slot_id: str | None = None
    segment_id: str
    template_version: str | None = None


class _ChartRequest(_Slice):
    chart_id: str
    chart_kind: str


class _ScriptDoc(_Slice):
    segments: tuple[_ScriptSegment, ...]
    scenes: tuple[_ScriptScene, ...] = ()
    sections: tuple[_ScriptSection, ...] = ()
    promise: _Promise | None = None
    disclaimer_slots: tuple[_DisclaimerSlot, ...] = ()
    chart_requests: tuple[_ChartRequest, ...] = ()
    hook_options: tuple[Any, ...] | None = None
    description_draft: str | None = None


class _RuleFlag(_Slice):
    rule_id: str


class _ExtractedClaim(_Slice):
    local_id: str
    segment_id: str
    claim_type: str
    time_reference_kind: str = "UNSPECIFIED"
    instrument: str | None = None
    chart_data_ref: str | None = None
    citation_refs: tuple[str, ...] = ()
    rule_flags: tuple[_RuleFlag, ...] = ()


class _ClaimsDoc(_Slice):
    claims: tuple[_ExtractedClaim, ...]


class _VerifiedClaim(_Slice):
    claim_id: str
    local_id: str


class _VerificationDoc(_Slice):
    """``agent_06.claim_verification.output``: ``script_id`` and ``script_sha256`` are required
    fields of that output (agent_06 section 8.2, CCR-049) and bind it to the subject."""

    script_id: str
    script_sha256: str
    claims: tuple[_VerifiedClaim, ...]


class _Disclosure(_Slice):
    is_realistic_synthetic: bool | None = None
    depicts_real_person: bool | None = None


class _ShotChart(_Slice):
    chart_id: str
    data_end_date: date | None = None
    data_age_vs_lag: DataAgeVsLag | None = None
    method_content: bool = False


class _ManifestShot(_Slice):
    shot_id: str
    status: str
    tier: VisualSourceTier | None = None
    asset_id: str | None = None
    source_type: str | None = None
    licence_id: str | None = None
    ledger_entry_ids: tuple[str, ...] = ()
    disclosure: _Disclosure | None = None
    chart: _ShotChart | None = None


class _ManifestAsset(_Slice):
    asset_id: str | None = None
    template_asset_id: str | None = None
    licence_id: str | None = None
    source_type: str | None = None
    ledger_entry_ids: tuple[str, ...] = ()


class _ManifestDoc(_Slice):
    shots: tuple[_ManifestShot, ...]
    overlays: tuple[_ManifestAsset, ...] = ()
    fonts: tuple[_ManifestAsset, ...] = ()
    music_beds: tuple[_ManifestAsset, ...] = ()


class _Overlay(_Slice):
    overlay_id: str
    kind: str


class _Realism(_Slice):
    shot_id: str
    realistic_event_depiction: bool
    schematic: bool | None = None
    origin: str | None = None
    refusal_reason: str | None = None


class _Views(_Slice):
    agent_16_realism: tuple[_Realism, ...] = ()


class _PlanDoc(_Slice):
    overlays: tuple[_Overlay, ...] = ()
    views: _Views | None = None


class _PlanShot(_Slice):
    intent_kind: str


class _PlanShotsDoc(_Slice):
    shots: tuple[_PlanShot, ...]


class _VoiceBlock(_Slice):
    voice_kind: str
    presenter_kind: str


class _VoiceDoc(_Slice):
    voice: _VoiceBlock


class _ThumbPicture(_Slice):
    kind: str | None = None
    asset_id: str | None = None


class _ThumbVariantDoc(_Slice):
    variant_id: str
    text_local: str = ""
    picture: _ThumbPicture | None = None


class _ThumbDoc(_Slice):
    variants: tuple[_ThumbVariantDoc, ...]


class _EvidenceFrame(_Slice):
    frame_id: str
    t_ms: int
    uri: str
    sha256: str


class _EvidenceDoc(_Slice):
    render_sha256: str
    frames: tuple[_EvidenceFrame, ...]


class _Evidence(_Slice):
    citation_ref: str
    method_labelled: bool = False
    usable_for_script: bool = True


class _Citation(_Slice):
    citation_ref: str
    kind: str


class _PackMethod(_Slice):
    used: bool = False
    release_approval_ids: tuple[str, ...] = ()


class _PackDoc(_Slice):
    evidence: tuple[_Evidence, ...] = ()
    citations_available: tuple[_Citation, ...] = ()
    method: _PackMethod = _PackMethod()


class _UniquenessDoc(_Slice):
    verdict: ComplianceVerdict


class _GateRule(_Slice):
    rule_id: str
    check_verdict: CheckVerdict


class _GateDisclosure(_Slice):
    decision: DisclosureDecision


class _GateSubjectDoc(_Slice):
    render_id: str
    render_sha256: str
    script_id: str
    script_sha256: str


class _GateDoc(_Slice):
    """``agent_16.compliance_gate.output`` (8.2): ``subject`` binds it to one render and script."""

    subject: _GateSubjectDoc
    verdict: ComplianceVerdict
    rules: tuple[_GateRule, ...] = ()
    disclosure: _GateDisclosure


class _TemplateSegment(_Slice):
    section_role: str
    text: str


class _TemplateDoc(_Slice):
    segments: tuple[_TemplateSegment, ...]
    shot_types: tuple[str, ...] = ()


class _QcDoc(_Slice):
    """``agent_10.technical_qc.output``: only its presence and shape are required here (the
    rows of the render's ``qc_results`` are the source of the judged checks) and the render it
    names (agent_10 section 8.2: ``render_id``, ``render_sha256`` are required fields)."""

    render_id: str
    render_sha256: str


def parse_doc[M: BaseModel](model: type[M], blobs: Mapping[str, bytes], key: str) -> M:
    """A required document: absent is ``MISSING_DEPENDENCY``, unparsable is ``SCHEMA_INVALID``."""
    raw = blobs.get(key)
    if raw is None:
        raise MissingDependencyError(f"{key} document is absent", details={"ref": key})
    try:
        return model.model_validate_json(raw)
    except ValidationError as exc:
        raise SchemaInvalidError(
            f"{key} document does not match its slice",
            details={
                "violations": [
                    violation("DOCUMENT_INVALID", "/" + "/".join(map(str, e["loc"])), key)
                    for e in exc.errors()[:20]
                ]
            },
        ) from exc


@dataclass(frozen=True, slots=True)
class SubjectBinding:
    """The subject hashes a request names; every document that carries them must agree."""

    render_id: str
    render_sha256: str
    script_id: str
    script_sha256: str


def bind_subject(
    subject: SubjectBinding,
    blobs: Mapping[str, bytes],
    *,
    verification: _VerificationDoc,
    qc: _QcDoc,
    gate: _GateDoc | None = None,
) -> None:
    """Fail closed (``INPUT_INVALID``) when a document is not about the subject: the script blob
    hashes to ``script_sha256`` (agent_06 section 8.2: the hash of the script blob), the
    verification output names the same script, the render QC output the same render and the
    gate output (score only) the same four subject fields. Org binding is the blob URI owner
    (checked at ``parse``)."""
    script = blobs.get("script_ref")
    if script is None or hashlib.sha256(script).hexdigest() != subject.script_sha256:
        raise InputInvalidError("script blob does not hash to subject.script_sha256")
    if (
        verification.script_sha256 != subject.script_sha256
        or verification.script_id != subject.script_id
    ):
        raise InputInvalidError("verification output is not about the subject's script")
    if qc.render_sha256 != subject.render_sha256 or qc.render_id != subject.render_id:
        raise InputInvalidError("render QC output is not about the subject's render")
    if gate is not None and (
        gate.subject.render_id != subject.render_id
        or gate.subject.render_sha256 != subject.render_sha256
        or gate.subject.script_id != subject.script_id
        or gate.subject.script_sha256 != subject.script_sha256
    ):
        raise InputInvalidError("gate output is not about the subject's render and script")


# --- database rows (the FactRowReader port) -------------------------------------------------
@dataclass(frozen=True, slots=True)
class ChannelRow:
    category: str | None
    audience_kind: AudienceKind | None
    knowledge_collection_id: str | None = None


@dataclass(frozen=True, slots=True)
class JobRow:
    language: str
    production_type_key: str
    live_format: Literal["STANDARD", "LIVE"] | None
    active_pack_keys: tuple[str, ...]
    routing_script_stage_id: str
    routing_assets_stage_id: str
    routing_thumbnails_stage_id: str | None


@dataclass(frozen=True, slots=True)
class AssetFactRow:
    """``assets`` joined with its ``licences`` row and the ``licence_ledger`` (15.1a)."""

    asset_id: str
    tier: VisualSourceTier | None
    shows_person: bool | None
    is_realistic_synthetic: bool | None
    has_ledger_row: bool
    licence_state: LicenceState | None
    covers_monetized_youtube: bool | None
    third_party_permission: Literal["PERMITTED", "NOT_PERMITTED", "UNKNOWN"] | None


@dataclass(frozen=True, slots=True)
class ClaimRow:
    claim_id: str
    claim_type: str
    status: ClaimStatus | None
    citation_count: int
    chart_data_ref: str | None
    sensitive_approval: tuple[str, str] | None
    """(approval id, subject sha256) of a ``SENSITIVE_CLAIM`` approval bound to the claim."""


class FactRowReader(Protocol):
    """``amw_app`` reads under RLS plus an explicit ``org_id`` filter (lane L1 implements it)."""

    def channel(self, tx: TenantTransaction, job_id: str) -> ChannelRow | None: ...
    def job(self, tx: TenantTransaction, job_id: str) -> JobRow | None: ...
    def assets(
        self, tx: TenantTransaction, asset_ids: Sequence[str], job_id: str
    ) -> Mapping[str, AssetFactRow]:
        """Fact rows of the assets; ``has_ledger_row`` counts only a ledger row of THIS job."""
        ...
    def voice_presenter_kind(self, tx: TenantTransaction, job_id: str) -> PresenterKind | None: ...
    def judged_qc_check_ids(self, tx: TenantTransaction, render_id: str) -> tuple[str, ...]:
        """``qc_results`` of the render that are ``SKIPPED`` with ``JUDGED_BY_AGENT_16``."""
        ...

    def release_approval_subjects(
        self, tx: TenantTransaction, approval_ids: Sequence[str]
    ) -> Mapping[str, str]:
        """approval id -> ``subject_sha256`` of ``KNOWLEDGE_RELEASE`` approvals of this org."""
        ...

    def copyright_doubt_approvals(
        self, tx: TenantTransaction, span_hashes: Sequence[str]
    ) -> Mapping[str, str]:
        """span sha256 -> approval id of ``COPYRIGHT_DOUBT`` approvals (state derived later)."""
        ...

    def qc_rows(self, tx: TenantTransaction, render_id: str) -> tuple[QcRow, ...] | None:
        """``qc_results`` of the render; ``None`` when the render does not exist."""
        ...

    def thumbnail_qc_rows(self, tx: TenantTransaction, job_id: str) -> tuple[QcRow, ...]: ...
    def claims(self, tx: TenantTransaction, claim_ids: Sequence[str]) -> tuple[ClaimRow, ...]: ...


@dataclass(frozen=True, slots=True)
class ReadScope:
    job_id: str
    render_id: str


def is_sensitive(channel: ChannelRow | None, packs: Sequence[str]) -> bool:
    """15.1a: an active ``rp.finance_sebi_in`` pack makes a channel sensitive; an unknown
    category (no channel row, NULL or empty) is treated as finance (as CCR-128 for Agent 10)."""
    if channel is None or not channel.category:
        return True
    return FINANCE_PACK in packs or channel.category.casefold() in SENSITIVE_CATEGORIES


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _voice_kind(kind: str, presenter: PresenterKind) -> R.VoiceKind | None:
    """Agent 07 ``voice_kind`` x ``voices.presenter_kind`` to the disclosure voice kind (CCR-272,
    provisional). A combination with no row is ``None`` (the disclosure decision then needs a
    human, 6.4 order 1)."""
    table: Mapping[tuple[str, PresenterKind], R.VoiceKind] = {
        ("HUMAN_RECORDED", PresenterKind.OWNER_VOICE): "OWNER_VOICE",
        ("CONSENTED_CLONE", PresenterKind.OWNER_VOICE): "OWNER_CLONE",
        ("PROVIDER_STOCK", PresenterKind.NEUTRAL_NARRATION): "NEUTRAL_TTS",
        ("CONSENTED_CLONE", PresenterKind.SYNTHETIC_PERSONA): "OTHER_REAL_PERSON",
        ("CONSENTED_CLONE", PresenterKind.NEUTRAL_NARRATION): "OTHER_REAL_PERSON",
        ("HUMAN_RECORDED", PresenterKind.NEUTRAL_NARRATION): "OTHER_REAL_PERSON",
    }
    return table.get((kind, presenter))


def _source_kind(source_type: str | None) -> R.SourceKind:
    if source_type in _STOCK_SOURCES:
        return "STOCK_LICENSED"
    if source_type in _THIRD_PARTY_SOURCES or source_type is None:
        return "THIRD_PARTY_OTHER"  # unknown origin is third-party until a record says otherwise
    if source_type == "OWNER_MADE":
        return "OWNER_MADE"
    if source_type == "CODE_GENERATED":
        return "CODE_GENERATED"
    if source_type == "AI_GENERATED":
        return "AI_OUTPUT"
    return "THIRD_PARTY_OTHER"


def _licensed(ref: str, source_type: str | None, row: AssetFactRow | None) -> R.LicensedAsset:
    """A missing row is a missing ledger row and licence (YTG-R6 ``FAIL``, 15.1a)."""
    perm: Literal["KNOWN", "UNKNOWN", "NOT_APPLICABLE"]
    covers = row.covers_monetized_youtube if row else None
    kind = _source_kind(source_type)
    given = row.third_party_permission if row else None
    if given == "NOT_PERMITTED":
        covers = False  # a licence that forbids third-party use does not cover monetized use
    if kind == "THIRD_PARTY_OTHER":
        perm = "KNOWN" if given == "PERMITTED" else "UNKNOWN"
    else:  # own or licensed material: the permission only matters when a row says UNKNOWN
        perm = "UNKNOWN" if given in ("UNKNOWN", "NOT_PERMITTED") else "NOT_APPLICABLE"
    return R.LicensedAsset(
        asset_ref=ref,
        source_kind=kind,
        has_ledger_row=bool(row and row.has_ledger_row),
        licence_state=row.licence_state if row else None,
        covers_monetized_youtube=covers,
        third_party_permission=perm,
    )


def _person(row: AssetFactRow, realistic: bool | None) -> R.PersonAsset:
    synth = True if realistic is None else realistic  # unknown realism counts as synthetic
    shows = row.shows_person if row.shows_person is not None else synth
    return R.PersonAsset(shows_person=shows, is_realistic_synthetic=synth)


class DocumentGateFactExtractor:
    """Implements ``GateFactExtractor`` (15.1a)."""

    def __init__(
        self,
        rows: FactRowReader,
        cfg: Agent16Config,
        scope: ReadScope | None = None,
        chunks: PrivateChunkReader | None = None,
    ) -> None:
        self._rows, self._cfg, self._scope, self._chunks = rows, cfg, scope, chunks

    def bind(self, scope: ReadScope) -> DocumentGateFactExtractor:
        """Same ports for another task (the stage binds the job and render per run)."""
        return DocumentGateFactExtractor(self._rows, self._cfg, scope, self._chunks)

    def extract(
        self,
        request: ComplianceGateInput,
        blobs: Mapping[str, bytes],
        evaluation_date: date,
        tx: TenantTransaction | None = None,
    ) -> ExtractedGate:
        if tx is None or self._scope is None:
            raise MissingDependencyError("gate fact extractor has no tenant transaction or scope")
        scope, rows = self._scope, self._rows
        script = parse_doc(_ScriptDoc, blobs, "script_ref")
        claims = parse_doc(_ClaimsDoc, blobs, "claims_ref")
        verification = parse_doc(_VerificationDoc, blobs, "verification_ref")
        manifest = parse_doc(_ManifestDoc, blobs, "asset_manifest_ref")
        plan = parse_doc(_PlanDoc, blobs, "shot_plan_ref")
        voice = parse_doc(_VoiceDoc, blobs, "voice_ref")
        thumbs = parse_doc(_ThumbDoc, blobs, "thumbnails_ref")
        uniq = parse_doc(_UniquenessDoc, blobs, "uniqueness_ref")
        pack = parse_doc(_PackDoc, blobs, "research_pack_ref")
        evidence = parse_doc(_EvidenceDoc, blobs, "frames_ref")
        if "metadata_ref" in blobs:
            raise InputInvalidError("a metadata bundle is read from 3C (Agent 12) only")
        qc_doc = parse_doc(_QcDoc, blobs, "render_qc_ref")
        sub = request.subject
        bind_subject(
            SubjectBinding(sub.render_id, sub.render_sha256, sub.script_id, sub.script_sha256),
            blobs,
            verification=verification,
            qc=qc_doc,
        )

        channel = rows.channel(tx, scope.job_id)
        job = rows.job(tx, scope.job_id)
        if channel is None or job is None:
            raise MissingDependencyError("channel or job row not found in this tenant")
        self._same(request, channel, job)
        sensitive = is_sensitive(channel, job.active_pack_keys)
        if evidence.render_sha256 != request.subject.render_sha256:
            raise InputInvalidError("evidence manifest render_sha256 is not the subject's")

        unresolved = [s.shot_id for s in manifest.shots if s.status == "UNRESOLVED"]
        if unresolved:
            raise InputInvalidError("asset manifest has an unresolved shot")
        used: dict[str, str | None] = {}
        for s in manifest.shots:
            if s.asset_id:
                used.setdefault(s.asset_id, s.source_type)
        for o in (*manifest.overlays, *manifest.fonts, *manifest.music_beds):
            aid = o.template_asset_id or o.asset_id
            if aid:
                used.setdefault(aid, o.source_type)
        pictures = [
            v.picture.asset_id
            for v in thumbs.variants
            if v.picture and v.picture.kind == "OWNER_IMAGE"
        ]
        if any(a is None for a in pictures):
            raise InputInvalidError("an owner-image thumbnail names no asset")
        thumb_assets = [a for a in pictures if a]
        arows = rows.assets(tx, sorted({*used, *thumb_assets}), scope.job_id)

        licensed = tuple(_licensed(a, st, arows.get(a)) for a, st in sorted(used.items()))
        render_persons: list[R.PersonAsset] = []
        disclosure: list[R.DisclosureAsset] = []
        shot_tier: dict[str, VisualSourceTier] = {}
        for s in manifest.shots:
            if s.tier is None:
                raise InputInvalidError("a manifest shot has no tier")
            shot_tier[s.shot_id] = s.tier
            d = s.disclosure
            synth = d.is_realistic_synthetic if d else None
            real = bool(d.depicts_real_person) if d else False
            disclosure.append(
                R.DisclosureAsset(
                    asset_ref=s.shot_id,
                    tier=s.tier,
                    is_realistic_synthetic=synth,
                    realistic_person=real,
                )
            )
            row = arows.get(s.asset_id) if s.asset_id else None
            if row is not None and row.shows_person is not None:
                shows = real or row.shows_person  # the asset row knows whether a person is shown
            else:
                shows = real or synth is not False  # unknown counts as a person (CCR-272)
            if s.asset_id and shows:
                render_persons.append(
                    R.PersonAsset(shows_person=True, is_realistic_synthetic=synth is not False)
                )
        thumb_persons: list[R.PersonAsset] = []
        for a in thumb_assets:
            row = arows.get(a)
            if row is None or row.tier is None:
                raise MissingDependencyError("thumbnail asset row or tier is missing")
            thumb_persons.append(_person(row, row.is_realistic_synthetic))
            disclosure.append(
                R.DisclosureAsset(
                    asset_ref=a,
                    tier=row.tier,
                    is_realistic_synthetic=row.is_realistic_synthetic,
                    realistic_person=bool(row.shows_person),
                )
            )
        realism: list[R.RealismShot] = []
        for r in plan.views.agent_16_realism if plan.views else ():
            if r.shot_id not in shot_tier:
                raise InputInvalidError("realism view names a shot the manifest does not have")
            realism.append(
                R.RealismShot(
                    shot_ref=r.shot_id,
                    tier=shot_tier[r.shot_id],
                    realistic_event_depiction=r.realistic_event_depiction,
                    schematic=r.schematic,
                    has_origin=r.origin is not None and r.refusal_reason is None,
                )
            )

        presenter = rows.voice_presenter_kind(tx, scope.job_id)
        if presenter is not None and presenter.value != voice.voice.presenter_kind:
            raise InputInvalidError("voice document presenter_kind differs from voices row")
        voice_kind = _voice_kind(voice.voice.voice_kind, presenter) if presenter else None

        items, text_prices, _ids = self._items(script, claims, verification, thumbs, manifest)
        method_segments, release_refs = self._method(tx, script, pack)
        pairs, span_hashes, near_copy, quotations = self._paraphrase(
            tx, request, script, claims, pack, channel
        )

        slots = script.disclaimer_slots
        versions = {s.template_version for s in slots}
        disclaimer_segments = {s.segment_id for s in script.segments if s.kind == "DISCLAIMER"}
        spoken = any(
            s.segment_id in disclaimer_segments
            and next((x.text for x in script.segments if x.segment_id == s.segment_id), "").strip()
            for s in slots
        )
        version = versions.pop() if len(versions) == 1 else None
        onscreen = any(o.kind == "DISCLAIMER_CARD" for o in plan.overlays)

        judged = rows.judged_qc_check_ids(tx, request.subject.render_id)
        wanted = [
            c
            for c in _JUDGED_CHECKS
            if c in judged and (c != "qc.visual.no_synthetic_presenter" or sensitive)
        ]
        frames = self._frames(wanted, sensitive, evidence)
        live = job.live_format
        if live is None:
            if request.production_type_key not in THREE_A_TYPES:
                raise MissingDependencyError("production type record has no live_format")
            live = "STANDARD"
        age_charts: list[R.ChartAge] = []
        for s in manifest.shots:
            if s.chart is None:
                continue
            end = s.chart.data_end_date
            if end is not None and end > evaluation_date:
                raise InputInvalidError("chart data ends after the evaluation date")
            age_charts.append(
                R.ChartAge(
                    chart_id=s.chart.chart_id,
                    age_days=None if end is None else (evaluation_date - end).days,
                )
            )
        inputs = GateInputs(
            channel_category=request.channel_category,
            language=request.language,
            sensitive_channel=sensitive,
            routing=request.routing,
            items=items,
            charts=tuple(age_charts),
            text_prices=text_prices,
            disclaimer_spoken=spoken,
            disclaimer_onscreen=onscreen,
            disclaimer_template_version=version,
            metadata_present=False,
            description_hash_matches=None,
            method_segments=method_segments,
            method_label_overlay=False,
            production_type_key=request.production_type_key,
            live_format=live,
            metadata_terms=None,
            presenter_kind=presenter,
            voice_known=presenter is not None,
            render_person_assets=tuple(render_persons),
            thumbnail_person_assets=tuple(thumb_persons),
            licensed_assets=licensed,
            audience_kind=channel.audience_kind,
            disclosure_assets=tuple(disclosure),
            realism_shots=tuple(realism),
            voice_kind=voice_kind,
            paraphrase_pairs=pairs,
            span_hashes=span_hashes,
            near_copy=near_copy,
            frame_ids=tuple(f.frame_id for f in evidence.frames),
            frames_payload=frames,
            uniqueness_verdict=uniq.verdict,
            evaluation_date=evaluation_date,
        )
        return ExtractedGate(
            inputs=inputs, method_release_approvals=release_refs, quotation_approvals=quotations
        )

    # -- helpers --------------------------------------------------------------------------
    @staticmethod
    def _same(request: ComplianceGateInput, channel: ChannelRow, job: JobRow) -> None:
        """The request echoes rows the database owns; any difference is refused."""
        if channel.category != request.channel_category:
            raise InputInvalidError("channel_category differs from channels.category")
        if (
            job.language != request.language
            or job.production_type_key != request.production_type_key
        ):
            raise InputInvalidError("language or production type differs from the job row")
        if (
            job.routing_script_stage_id != request.routing.script_stage_id
            or job.routing_assets_stage_id != request.routing.assets_stage_id
            or job.routing_thumbnails_stage_id != request.routing.thumbnails_stage_id
        ):
            raise InputInvalidError("routing differs from the production type record")

    @staticmethod
    def _items(
        script: _ScriptDoc,
        claims: _ClaimsDoc,
        verification: _VerificationDoc,
        thumbs: _ThumbDoc,
        manifest: _ManifestDoc,
    ) -> tuple[tuple[SourceItem, ...], tuple[R.TextPrice, ...], dict[str, str]]:
        ids = {c.local_id: c.claim_id for c in verification.claims}
        by_segment: dict[str, list[_ExtractedClaim]] = {}
        for c in claims.claims:
            by_segment.setdefault(c.segment_id, []).append(c)
        kinds = {c.chart_id: c.chart_kind for c in script.chart_requests}
        chart_info = {s.chart.chart_id: s.chart for s in manifest.shots if s.chart}
        items: list[SourceItem] = []
        segs = script.segments
        known = {x.segment_id for x in segs}
        if any(c.segment_id not in known for c in claims.claims):
            raise InputInvalidError("a claim names a segment the script does not have")
        for i, seg in enumerate(segs):
            mine = by_segment.get(seg.segment_id, [])
            chart = None
            if seg.chart_ref:
                if seg.chart_ref not in kinds:
                    raise InputInvalidError("a segment names a chart the script never requested")
                info = chart_info.get(seg.chart_ref)
                chart = ItemChart(
                    chart_kind=kinds[seg.chart_ref],
                    instrument=next((c.instrument for c in mine if c.instrument), None),
                    data_age_vs_lag=info.data_age_vs_lag if info else None,
                )
            for c in mine:
                if c.local_id not in ids:
                    raise InputInvalidError("a claim has no claim_id in the verification output")
            items.append(
                SourceItem(
                    ref=f"seg.{seg.segment_id}",
                    surface="SCRIPT_SEGMENT",
                    text=seg.text,
                    context_before=segs[i - 1].text if i else "",
                    context_after=segs[i + 1].text if i + 1 < len(segs) else "",
                    named_instruments=tuple(sorted({c.instrument for c in mine if c.instrument})),
                    claims=tuple(
                        ItemClaim(
                            claim_type=c.claim_type,
                            time_reference_kind=c.time_reference_kind,
                            rule_flags=tuple(f.rule_id for f in c.rule_flags),
                        )
                        for c in mine
                    ),
                    chart=chart,
                    claim_ids=tuple(ids[c.local_id] for c in mine),
                )
            )
        for sc in script.scenes:
            for k, text in enumerate(sc.on_screen_text):
                items.append(
                    SourceItem(ref=f"scene.{sc.scene_id}.t{k}", surface="ON_SCREEN_TEXT", text=text)
                )
        if script.promise and script.promise.working_title_local:
            items.append(
                SourceItem(ref="title", surface="TITLE", text=script.promise.working_title_local)
            )
        if script.description_draft:
            items.append(
                SourceItem(ref="description", surface="DESCRIPTION", text=script.description_draft)
            )
        for v in thumbs.variants:
            if v.text_local:
                items.append(
                    SourceItem(
                        ref=f"thumb.{v.variant_id}", surface="THUMBNAIL_TEXT", text=v.text_local
                    )
                )
        prices = tuple(
            R.TextPrice(
                price_ref=f"claim.{ids.get(c.local_id, c.local_id)}", has_date=False, age_days=None
            )
            for c in claims.claims
            # a price whose chart is not in the manifest has no date either (needs a human)
            if c.claim_type in _PRICE_CLAIM_TYPES
            and (c.chart_data_ref is None or c.chart_data_ref not in chart_info)
        )
        return tuple(items), prices, ids

    def _method(
        self, tx: TenantTransaction, script: _ScriptDoc, pack: _PackDoc
    ) -> tuple[tuple[R.MethodSegment, ...], dict[str, ReleaseRef | None]]:
        method_cites = {e.citation_ref for e in pack.evidence if e.method_labelled}
        segments: list[R.MethodSegment] = []
        refs: dict[str, ReleaseRef | None] = {}
        ids = pack.method.release_approval_ids
        subjects = self._rows.release_approval_subjects(tx, ids) if ids else {}
        single = ids[0] if len(ids) == 1 and ids[0] in subjects else None
        for seg in script.segments:
            cited = {c for cr in seg.concept_refs for c in cr.citation_refs}
            if not cited & method_cites:
                continue
            ref = f"seg.{seg.segment_id}"
            segments.append(
                R.MethodSegment(
                    segment_ref=ref,
                    cites_method_chunk=True,
                    labelled=seg.method_label,
                    release_state="NONE",
                )
            )
            refs[ref] = (
                ReleaseRef(approval_id=single, released_sha256=subjects[single]) if single else None
            )
        return tuple(segments), refs

    def _paraphrase(
        self,
        tx: TenantTransaction,
        request: ComplianceGateInput,
        script: _ScriptDoc,
        claims: _ClaimsDoc,
        pack: _PackDoc,
        channel: ChannelRow,
    ) -> tuple[
        tuple[ParaphrasePair, ...],
        Mapping[str, str],
        tuple[NearCopyResult, ...],
        dict[str, str | None],
    ]:
        chunk_cites = {
            c.citation_ref for c in pack.citations_available if c.kind == "KNOWLEDGE_CHUNK"
        }
        quoted = {
            c.segment_id
            for c in claims.claims
            if c.claim_type == "QUOTED_THIRD_PARTY" and c.citation_refs
        }
        sentences: list[tuple[str, str, tuple[str, ...]]] = []
        for seg in script.segments:
            cited = tuple(
                sorted({c for cr in seg.concept_refs for c in cr.citation_refs} & chunk_cites)
            )
            if cited:
                sentences.append((f"seg.{seg.segment_id}", seg.text, cited))
        if not sentences:
            return (), {}, (), {}
        if self._chunks is None or channel.knowledge_collection_id is None:
            raise MissingDependencyError(
                "cited knowledge chunks exist but no private chunk reader or collection is wired;"
                " YTG-R9 cannot be evaluated"
            )
        cfg = self._cfg
        results = check_near_copy(
            tx,
            sentences,
            self._chunks,
            channel.knowledge_collection_id,
            cfg.paraphrase_ngram_n,
            cfg.paraphrase_max_overlap_ratio,
            cfg.paraphrase_lcs_max_chars,
        )
        texts = {ref: text for ref, text, _ in sentences}
        pairs: list[ParaphrasePair] = []
        hashes: dict[str, str] = {}
        by_ref: dict[str, list[NearCopyResult]] = {}
        for r in results:
            if r.candidate:
                by_ref.setdefault(r.sentence_ref, []).append(r)
        for ref in sorted(by_ref):
            pid = f"p{len(pairs) + 1:02d}"
            passages = tuple(
                Passage(
                    passage_id=f"s{k + 1:02d}",
                    language=request.language,
                    text=self._chunks.read(tx, r.chunk_id).text,
                )
                for k, r in enumerate(by_ref[ref])
            )
            seg_id = ref.removeprefix("seg.")
            pairs.append(
                ParaphrasePair(
                    pair_id=pid,
                    script_span=texts[ref],
                    passages=passages,
                    attribution_present=seg_id in quoted,
                )
            )
            hashes[pid] = _sha(texts[ref])
        found = self._rows.copyright_doubt_approvals(tx, sorted(set(hashes.values())))
        quotations = {h: found.get(h) for h in sorted(set(hashes.values()))}
        return tuple(pairs), hashes, tuple(results), quotations

    def _frames(
        self, wanted: Sequence[str], sensitive: bool, ev: _EvidenceDoc
    ) -> dict[str, Any] | None:
        if not wanted:
            return None  # no JUDGED_BY_AGENT_16 row: no frames call (15.1a)
        cap = min(self._cfg.compliance_max_frames or FRAMES_SCHEMA_CAP, FRAMES_SCHEMA_CAP)
        frames = list(ev.frames)
        if len(frames) > cap:
            step = len(frames) / cap
            frames = [frames[int(i * step)] for i in range(cap)]
        return {
            "checks_requested": list(wanted),
            "sensitive_channel": sensitive,
            "frames": [{"frame_id": f.frame_id, "t_ms": f.t_ms, "image": f.uri} for f in frames],
            # the evidence manifest has no overlay region (CCR-272): an empty list is the
            # stricter default, a branded overlay may then be reported as a possible watermark
            "overlay_list": [],
        }


class DocumentUniquenessExtractor:
    """Implements ``UniquenessExtractor`` (S2 facts from the script, the plan and the template).

    The template document shape (``segments[{section_role, text}]``, ``shot_types[]``) is
    provisional (CCR-272); an empty template is ``complete = False`` (the measures then need a
    human, never a pass)."""

    def extract(self, blobs: Mapping[str, bytes]) -> UniquenessFacts:
        script = parse_doc(_ScriptDoc, blobs, "script_ref")
        plan = parse_doc(_PlanShotsDoc, blobs, "shot_plan_ref")
        parse_doc(_ThumbDoc, blobs, "thumbnails_ref")
        template = parse_doc(_TemplateDoc, blobs, "template_ref")
        roles = {s.section_id: s.section_kind for s in script.sections}
        segments = tuple(
            Segment(section_role=_role(seg, roles), text=seg.text) for seg in script.segments
        )
        shots = tuple(s.intent_kind for s in plan.shots)
        tpl = tuple(Segment(section_role=t.section_role, text=t.text) for t in template.segments)
        return UniquenessFacts(
            script=segments,
            template=tpl,
            shots=shots,
            template_shots=template.shot_types,
            complete=bool(segments and shots and tpl and template.shot_types),
        )


def _role(seg: _ScriptSegment, roles: Mapping[str, str]) -> str:
    """Section role of a segment: the section's kind; ``HOOK`` for the reserved ``hook`` section
    (CCR-202); ``DISCLAIMER`` for a segment outside every section."""
    if seg.section_id == "hook":
        return "HOOK"
    if seg.section_id is None:
        return "DISCLAIMER"
    return roles.get(seg.section_id, "UNKNOWN")


class DocumentScoreFactExtractor:
    """``agent_16.quality_score`` deterministic facts (15.1b)."""

    def __init__(self, rows: FactRowReader, verifier: ApprovalStepVerifier) -> None:
        self._rows, self._verifier = rows, verifier

    def extract(
        self,
        subject: SubjectBinding,
        blobs: Mapping[str, bytes],
        tx: TenantTransaction,
        scope: ReadScope,
        sensitive: bool,
    ) -> DeterministicInputs:
        script = parse_doc(_ScriptDoc, blobs, "script_ref")
        verification = parse_doc(_VerificationDoc, blobs, "verification_ref")
        thumbs = parse_doc(_ThumbDoc, blobs, "thumbnails_ref")
        gate = parse_doc(_GateDoc, blobs, "gate_output_ref")
        claims_doc = parse_doc(_ClaimsDoc, blobs, "claims_ref")
        bind_subject(
            subject,
            blobs,
            verification=verification,
            qc=parse_doc(_QcDoc, blobs, "render_qc_ref"),
            gate=gate,
        )
        listed = {c.local_id for c in verification.claims}
        if any(c.local_id not in listed for c in claims_doc.claims):
            raise InputInvalidError("a claim has no claim_id in the verification output")
        qc = self._rows.qc_rows(tx, subject.render_id)
        if qc is None:
            raise MissingDependencyError("render not found in this tenant")
        wanted = [c.claim_id for c in verification.claims]
        if len(set(wanted)) != len(wanted):
            raise InputInvalidError("verification output lists a claim_id twice")
        crow = self._rows.claims(tx, wanted)
        if len(crow) != len(wanted) or {c.claim_id for c in crow} != set(wanted):
            # (counts too: a duplicated row or id would otherwise pass as a set)
            # a listed claim without its row would score as if it were verified (15.1b: no claim
            # at all is ``[]``, a claim the verification names but the database lacks is not)
            raise MissingDependencyError(
                "claims named by the verification output differ from the claims rows"
            )
        claims = tuple(
            ClaimFact(
                claim_id=c.claim_id,
                claim_type=c.claim_type,
                status=c.status,
                has_citation_or_chart=c.citation_count > 0 or c.chart_data_ref is not None,
                sensitive_claim_approved=self._approved(tx, c),
            )
            for c in crow
        )
        promise = script.promise
        fields_ok = bool(
            promise
            and promise.working_title_local
            and promise.promise_statement
            and promise.promise_key_terms
        )
        tqc = self._rows.thumbnail_qc_rows(tx, scope.job_id)
        legible = _all_pass(tqc, ("a11.q.legibility", "a11.q.text_fit"))
        spec = [
            r
            for r in tqc
            if r.check_id.startswith("a11.q.")
            and r.check_id not in ("a11.q.legibility", "a11.q.text_fit")
        ]
        spec_ok: bool | None = (
            None if not spec else all(r.verdict is CheckVerdict.PASS for r in spec)
        )
        results = {r.rule_id: r.check_verdict for r in gate.rules}
        finance_rule = results.get("FIN-R10")
        return DeterministicInputs(
            qc=qc,
            claims=claims,
            script=ScriptFacts(
                hook_options=None if script.hook_options is None else len(script.hook_options),
                promise_fields_present=fields_ok,
                sections_with_takeaway=None,
                sections_with_example=None,
                section_count=len(script.sections),
                viewer_problem_addressed=None,
            ),
            thumbnails=ThumbnailFacts(
                variants=len(thumbs.variants),
                required_variants=REQUIRED_THUMBNAIL_VARIANTS,
                spec_ok=spec_ok,
                legible=legible,
                title_length_ok=None,
            ),
            gate=GateFacts(
                overall=gate.verdict,
                licence_pass=None
                if "YTG-R6" not in results
                else results["YTG-R6"] is CheckVerdict.PASS,
                disclosure_decision=gate.disclosure.decision,
                disclaimer_pass=None if finance_rule is None else finance_rule is CheckVerdict.PASS,
                finance=sensitive,
            ),
        )

    def _approved(self, tx: TenantTransaction, c: ClaimRow) -> bool:
        if c.sensitive_approval is None:
            return False
        aid, subject = c.sensitive_approval
        return self._verifier.derive(tx, aid, ApprovalKind.SENSITIVE_CLAIM, subject) == "APPROVED"


def _all_pass(rows: Sequence[QcRow], ids: Sequence[str]) -> bool | None:
    found = [next((r for r in rows if r.check_id == i), None) for i in ids]
    if any(f is None for f in found):
        return None
    return all(f is not None and f.verdict is CheckVerdict.PASS for f in found)
