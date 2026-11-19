"""Deterministic rule functions F-04...F-09 (FIN-R4, R9, R10, R11/YTG-R2, R12, YTG-R3, R5, R6,
YTG-R7 V11a). Arguments are the minimal facts each function reads (the ``compliance_rules_core``
argument objects); ``inputs.extractors`` derives them from the upstream documents and rows."""

from typing import Final, Literal

from pydantic import Field

from agent_16_compliance_qa.base import Model, worst
from agent_16_compliance_qa.checks import RuleResult, failed, needs_human, passed, skipped
from amw_core.enums import (
    AudienceKind,
    CheckVerdict,
    ComplianceVerdict,
    DisclosureDecision,
    LicenceState,
    PresenterKind,
    VisualSourceTier,
)
from amw_runtime.disclaimer import DRAFT_STATUS

# Owner-set status string (CCR-212; en dash), single source ``amw_runtime.disclaimer``: the report
# label is that module's constant, never a second copy of the text (ticket PASS6-K item 1).
DRAFT_DISCLAIMER_LABEL: Final = DRAFT_STATUS
"""3A R5 report label (a fixed report string of 3A_SLICE_SPEC, not a threshold)."""


# --- FIN-R9 price lag (F-05) ---------------------------------------------------------------
class ChartAge(Model):
    chart_id: str
    age_days: int | None = Field(ge=0)


class TextPrice(Model):
    price_ref: str
    has_date: bool
    age_days: int | None = Field(ge=0)


def price_lag(charts: list[ChartAge], text_prices: list[TextPrice], lag_days: int) -> RuleResult:
    """Age >= lag passes (calendar days, 3A R6); any younger price blocks; an undated price or
    an unknown chart age needs a human; no price data at all is ``SKIPPED`` (V1)."""
    if not charts and not text_prices:
        return skipped(
            "FIN-R9", "no chart and no price in the video", extras={"days_until_compliant": None}
        )
    ages = [c.age_days for c in charts] + [t.age_days if t.has_date else None for t in text_prices]
    known = [a for a in ages if a is not None]
    ev = {"lag_days": lag_days, "youngest_age_days": min(known) if known else None}
    young = [a for a in known if a < lag_days]
    if young:
        wait = lag_days - min(young)
        return failed(
            "FIN-R9",
            f"price data {min(young)} days old, lag {lag_days} days",
            evidence=ev,
            remedy="assets",
            extras={"days_until_compliant": wait},
        )
    if len(known) < len(ages):
        return needs_human(
            "FIN-R9",
            "a price or chart has no known date (13 section 5.5)",
            evidence=ev,
            extras={"days_until_compliant": None},
        )
    return passed(
        "FIN-R9",
        f"every price at least {lag_days} days old",
        evidence=ev,
        extras={"days_until_compliant": 0},
    )


# --- FIN-R10 disclaimer (F-06) -------------------------------------------------------------
def disclaimer(
    spoken_present: bool,
    onscreen_present: bool,
    template_version: str | None,
    metadata_present: bool,
    description_hash_matches: bool | None,
) -> RuleResult:
    """Spoken and on-screen disclaimer of the versioned template; the description part is
    ``SKIPPED`` while there is no metadata (3A, Agent 12 disabled)."""
    if not metadata_present:
        desc: CheckVerdict = CheckVerdict.SKIPPED
    else:
        desc = CheckVerdict.PASS if description_hash_matches is True else CheckVerdict.FAIL
    missing = [
        name
        for name, ok in (
            ("spoken", spoken_present),
            ("on-screen", onscreen_present),
            ("template version", template_version is not None),
            ("description", desc is not CheckVerdict.FAIL),
        )
        if not ok
    ]
    extras = {"description_check": desc.value}
    ev = {"template_version": template_version}
    if missing:
        return failed(
            "FIN-R10",
            "disclaimer missing: " + ", ".join(missing),
            evidence=ev,
            remedy="script",
            extras={**extras, "report_label": None},
        )
    return passed(
        "FIN-R10",
        "spoken and on-screen disclaimer present",
        evidence=ev,
        extras={**extras, "report_label": DRAFT_DISCLAIMER_LABEL},
    )


# --- FIN-R12 method release (F-07) ---------------------------------------------------------
ReleaseState = Literal["APPROVED", "APPROVED_UNVERIFIED", "PENDING", "REJECTED", "NONE"]


class MethodSegment(Model):
    segment_ref: str
    cites_method_chunk: bool
    labelled: bool
    release_state: ReleaseState
    """Derived by ``authorisation.evidence.derive_approval_state`` from the release approval's
    steps (G2 + G4), never from ``approvals.state`` (CCR-102)."""


def method_release(segments: list[MethodSegment], label_overlay_present: bool) -> RuleResult:
    cited = [s for s in segments if s.cites_method_chunk]
    if not cited:
        return skipped("FIN-R12", "no segment cites a method-labelled chunk")
    bad = [
        s.segment_ref
        for s in cited
        if s.release_state != "APPROVED" or not s.labelled or not label_overlay_present
    ]
    if bad:
        return failed(
            "FIN-R12",
            "method content without a verified release or label",
            item_refs=tuple(bad),
            remedy="script",
            evidence={"segments": bad, "overlay": label_overlay_present},
        )
    return passed("FIN-R12", "every method segment released (steps verified) and labelled")


# --- FIN-R4 live format --------------------------------------------------------------------
def live_format(
    production_type_key: str,
    fmt: Literal["STANDARD", "LIVE"],
    metadata_terms: list[str] | None,
    live_terms: tuple[str, ...],
) -> RuleResult:
    """No live trading format; metadata scanned for live-format terms (lexicon config)."""
    if metadata_terms is None:
        meta = CheckVerdict.SKIPPED
    else:
        hits = [t for t in metadata_terms if any(w.casefold() in t.casefold() for w in live_terms)]
        meta = CheckVerdict.FAIL if hits else CheckVerdict.PASS
    extras = {"metadata_check": meta.value}
    if fmt == "LIVE" or meta is CheckVerdict.FAIL:
        return failed(
            "FIN-R4", f"live format ({production_type_key})", extras=extras, remedy="script"
        )
    return passed("FIN-R4", "standard recorded format", extras=extras)


# --- FIN-R11 / YTG-R2 persona (F-08) -------------------------------------------------------
class PersonAsset(Model):
    shows_person: bool
    is_realistic_synthetic: bool


def persona(
    channel_sensitive: bool,
    presenter_kind: PresenterKind | None,
    voice_known: bool,
    render_assets: list[PersonAsset],
    thumbnail_assets: list[PersonAsset],
) -> RuleResult:
    """``voices.presenter_kind`` is NOT NULL in the DB (CCR-027): an absent voice record is a
    missing input (NHR). Render **and thumbnail** assets are checked."""
    if not channel_sensitive:
        return passed("YTG-R2", "persona rule applies to finance, health and political channels")
    results: list[RuleResult] = []
    if not voice_known:
        results.append(needs_human("YTG-R2", "voice record missing (presenter_kind unknown)"))
    elif presenter_kind is PresenterKind.SYNTHETIC_PERSONA:
        results.append(
            failed("YTG-R2", "synthetic presenter persona on a sensitive channel", remedy="assets")
        )
    for where, assets in (("render", render_assets), ("thumbnail", thumbnail_assets)):
        if any(a.shows_person and a.is_realistic_synthetic for a in assets):
            results.append(
                failed(
                    "YTG-R2",
                    f"realistic synthetic person in a {where} asset",
                    remedy="thumbnails" if where == "thumbnail" else "assets",
                )
            )
    if not results:
        return passed("YTG-R2", "no synthetic presenter")
    v = worst(r.compliance_verdict for r in results)
    return next(r for r in results if r.compliance_verdict is v)


# --- YTG-R5 / YTG-R6 licences (F-04) -------------------------------------------------------
SourceKind = Literal[
    "STOCK_LICENSED", "OWNER_MADE", "CODE_GENERATED", "AI_OUTPUT", "THIRD_PARTY_OTHER"
]
_DEAD: Final = frozenset({LicenceState.EXPIRED, LicenceState.REVOKED, LicenceState.REJECTED})


class LicensedAsset(Model):
    asset_ref: str
    source_kind: SourceKind
    has_ledger_row: bool
    licence_state: LicenceState | None
    covers_monetized_youtube: bool | None
    third_party_permission: Literal["KNOWN", "UNKNOWN", "NOT_APPLICABLE"]


def licence(assets: list[LicensedAsset]) -> tuple[RuleResult, RuleResult, list[str]]:
    """Returns (YTG-R5, YTG-R6, expiring asset refs); evaluated as monetized YouTube (3A R3)."""
    r5_fail = [
        a.asset_ref for a in assets if a.source_kind == "THIRD_PARTY_OTHER" and not a.has_ledger_row
    ]
    r5_nhr = [a.asset_ref for a in assets if a.third_party_permission == "UNKNOWN"]
    if r5_fail:
        r5 = failed(
            "YTG-R5",
            "third-party material without a licence record",
            item_refs=tuple(r5_fail),
            remedy="assets",
        )
    elif r5_nhr:
        r5 = needs_human("YTG-R5", "third-party permission unknown", item_refs=tuple(r5_nhr))
    else:
        r5 = passed("YTG-R5", "no unlicensed third-party material")
    r6_fail, r6_nhr, expiring = [], [], []
    for a in assets:
        if not a.has_ledger_row or a.licence_state in _DEAD or a.covers_monetized_youtube is False:
            r6_fail.append(a.asset_ref)
        elif (
            a.licence_state is None
            or a.licence_state is LicenceState.PENDING_VERIFICATION
            or a.covers_monetized_youtube is None
        ):
            r6_nhr.append(a.asset_ref)
        elif a.licence_state is LicenceState.EXPIRING:
            expiring.append(a.asset_ref)
    if r6_fail:
        r6 = failed(
            "YTG-R6",
            "asset without a valid licence for monetized YouTube",
            item_refs=tuple(r6_fail),
            remedy="assets",
        )
    elif r6_nhr:
        r6 = needs_human("YTG-R6", "licence term unknown or unverified", item_refs=tuple(r6_nhr))
    else:
        r6 = passed("YTG-R6", "every asset has an ACTIVE licence record")
    return r5, r6, expiring


# --- YTG-R7 audience (V11a, CCR-081) -------------------------------------------------------
def audience(audience_kind: AudienceKind | None, kids_pack_active: bool) -> RuleResult:
    if audience_kind is None:
        return needs_human("YTG-R7", "channels.audience_kind not decided (NULL)")
    if audience_kind is AudienceKind.KIDS and not kids_pack_active:
        return needs_human("YTG-R7", "KIDS channel without rp.kids in the active packs")
    return passed("YTG-R7", f"audience {audience_kind.value}")


# --- YTG-R3 disclosure decision (F-09, section 6.4) ----------------------------------------
_AI_TIERS: Final = frozenset({VisualSourceTier.D_AI_VIDEO, VisualSourceTier.E_AI_STILL})


class DisclosureAsset(Model):
    asset_ref: str
    tier: VisualSourceTier
    is_realistic_synthetic: bool | None
    realistic_person: bool


class RealismShot(Model):
    shot_ref: str
    tier: VisualSourceTier
    realistic_event_depiction: bool
    schematic: bool | None
    has_origin: bool


VoiceKind = Literal["OWNER_VOICE", "OWNER_CLONE", "NEUTRAL_TTS", "OTHER_REAL_PERSON"]


class DisclosureResult(Model):
    rule_id: Literal["YTG-R3"] = "YTG-R3"
    disclosure_decision: DisclosureDecision
    decided_by_order: Literal[1, 2, 3]
    rationale: str
    check_verdict: CheckVerdict
    compliance_verdict: ComplianceVerdict


def disclosure(
    assets: list[DisclosureAsset], shots: list[RealismShot], voice_kind: VoiceKind | None
) -> DisclosureResult:
    """First matching row of section 6.4 over every render and thumbnail asset."""
    doubt = [a.asset_ref for a in assets if a.is_realistic_synthetic is None]
    doubt += [s.shot_ref for s in shots if s.realistic_event_depiction and not s.has_origin]
    doubt += [s.shot_ref for s in shots if s.tier in _AI_TIERS and s.schematic is None]
    if doubt or voice_kind is None:
        return DisclosureResult(
            disclosure_decision=DisclosureDecision.NEEDS_HUMAN_REVIEW,
            decided_by_order=1,
            rationale="realism flag missing or ambiguous: " + ", ".join(doubt or ["voice"]),
            check_verdict=CheckVerdict.WARN,
            compliance_verdict=ComplianceVerdict.NEEDS_HUMAN_REVIEW,
        )
    required = [
        a.asset_ref
        for a in assets
        if a.is_realistic_synthetic and (a.tier in _AI_TIERS or a.realistic_person)
    ]
    if required or voice_kind == "OTHER_REAL_PERSON":
        return DisclosureResult(
            disclosure_decision=DisclosureDecision.REQUIRED,
            decided_by_order=2,
            rationale="realistic synthetic content: " + ", ".join(required or ["voice"]),
            check_verdict=CheckVerdict.PASS,
            compliance_verdict=ComplianceVerdict.ALLOWED,
        )
    return DisclosureResult(
        disclosure_decision=DisclosureDecision.NOT_REQUIRED,
        decided_by_order=3,
        rationale="every AI-touched element is in the YT-07 not-required list",
        check_verdict=CheckVerdict.PASS,
        compliance_verdict=ComplianceVerdict.ALLOWED,
    )
