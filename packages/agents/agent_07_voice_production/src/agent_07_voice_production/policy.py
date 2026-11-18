"""Deterministic gates before any paid call (FR-2...FR-5, F-02...F-05; blueprint 6.2).

Every function is pure over facts the stage has read under RLS. Safe default: when consent or
licence state is unknown, deny (18). Error details carry reason codes only, never personal data.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from agent_07_voice_production.contracts import (
    VerificationOutput,
    VoiceSynthesisInput,
)
from agent_07_voice_production.ports import (
    ApprovalFacts,
    LicenceFacts,
    ScriptRowFacts,
    TtsCapabilities,
    VoiceBundle,
)
from amw_core.enums import (
    ApprovalState,
    AssetStatus,
    ConsentState,
    LicenceSourceType,
    LicenceState,
    PresenterKind,
    ThirdPartyPermission,
    VoiceKind,
)
from amw_core.errors import (
    InputInvalidError,
    MissingDependencyError,
    PermissionDeniedError,
    UnsupportedTaskError,
)
from amw_core.ids import ChannelId

_REQUIRED_SOURCE = {
    VoiceKind.PROVIDER_STOCK: LicenceSourceType.TTS_PROVIDER,
    VoiceKind.CONSENTED_CLONE: LicenceSourceType.VOICE_CLONE,
    VoiceKind.HUMAN_RECORDED: LicenceSourceType.HUMAN_NARRATION,
}
_LIVE_LICENCE_STATES = (LicenceState.ACTIVE, LicenceState.EXPIRING)


def language_supported(language: str, declared: Sequence[str]) -> bool:
    """``mr-IN`` is served by a declared ``mr-IN`` or ``mr``; never by another language."""
    return language in declared or language.split("-")[0] in declared


# --- F-02 script gate -------------------------------------------------------------------


def check_script_gate(
    payload: VoiceSynthesisInput,
    *,
    blob_sha256: str,
    row: ScriptRowFacts | None,
    verification: VerificationOutput,
    approval: ApprovalFacts | None,
) -> None:
    """Paid audio only for the script Agent 06 verified (FR-2). Binding is by version: blob hash
    equals the payload hash equals ``scripts.content_sha256``; Agent 06 names the same script."""
    if row is None:
        raise MissingDependencyError("script version row not found")
    violations: list[str] = []
    if blob_sha256 != payload.script_sha256:
        violations.append("script blob hash differs from payload.script_sha256")
    if row.content_sha256 != payload.script_sha256:
        violations.append("scripts.content_sha256 differs from payload.script_sha256")
    if (verification.script_id, verification.script_version) != (
        payload.script_id,
        payload.script_version,
    ):
        violations.append("verification output names another script version")
    verdict = verification.verification_verdict
    if verdict == "BLOCKED":
        violations.append("stage verdict is BLOCKED")
    elif verdict == "NEEDS_HUMAN_REVIEW" and not (
        approval is not None
        and approval.state is ApprovalState.APPROVED
        and approval.subject_sha256 == payload.script_sha256
    ):
        violations.append("NEEDS_HUMAN_REVIEW without an APPROVED approval bound to this script")
    if violations:
        raise InputInvalidError(
            "the script is not the verified one", details={"violations": _violations(violations)}
        )


def _violations(messages: Sequence[str]) -> list[dict[str, str]]:
    return [{"path": "", "keyword": "gate", "message": m} for m in messages]


# --- F-03 voice resolution ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolvedVoice:
    bundle: VoiceBundle
    kind: VoiceKind
    presenter_kind: PresenterKind

    @property
    def provider_voice_ref(self) -> str | None:
        return self.bundle.voice.provider_voice_ref


def resolve_voice(
    bundle: VoiceBundle | None,
    *,
    language: str,
    caps: TtsCapabilities,
    brand_kit_voice_id: str | None,
    production: bool,
) -> ResolvedVoice:
    if bundle is None:
        raise MissingDependencyError("voice not found")
    voice = bundle.voice
    if voice.status is not AssetStatus.ACTIVE:
        raise PermissionDeniedError("voice is not ACTIVE", details={"reason": "voice_inactive"})
    # Unsupported capability value fails before any paid call (18 section 4, Q-01). A recording
    # is never sent to a provider, so the adapter's languages do not apply to it.
    if voice.kind is not VoiceKind.HUMAN_RECORDED and not language_supported(language, caps.languages):
        raise UnsupportedTaskError(
            "the adapter does not declare the script language",
            details={"language": language, "reason": "adapter_language"},
        )
    if not language_supported(language, voice.languages):
        raise UnsupportedTaskError(
            "the voice does not declare the script language",
            details={"language": language, "reason": "voice_language"},
        )
    if production and brand_kit_voice_id != voice.id:
        raise PermissionDeniedError(
            "the voice is not bound to the channel's current brand kit",
            details={"reason": "brand_kit_binding"},
        )
    if voice.kind is VoiceKind.HUMAN_RECORDED and voice.provider is not None:
        raise InputInvalidError("a HUMAN_RECORDED voice must not name a provider")
    if voice.kind is not VoiceKind.HUMAN_RECORDED and (
        voice.provider is None or voice.provider_voice_ref is None
    ):
        raise MissingDependencyError("voice has no provider reference")
    return ResolvedVoice(bundle, voice.kind, voice.presenter_kind)


# --- F-05 licence ------------------------------------------------------------------------


def check_licence(
    voice: ResolvedVoice,
    *,
    monetized_destination: bool,
    org_is_platform_owner: bool,
    now: datetime,
) -> LicenceFacts:
    licence = voice.bundle.licence
    if licence is None:
        raise MissingDependencyError("the voice's licence row is absent")
    deny = _deny_licence
    if licence.state not in _LIVE_LICENCE_STATES:
        deny("licence_state")
    if licence.expires_at is not None and licence.expires_at <= now:
        deny("licence_expired")
    if licence.source_type is not _REQUIRED_SOURCE[voice.kind]:
        deny("licence_source_type")
    if monetized_destination and licence.covers_monetized_youtube is not True:
        deny("licence_monetised_unknown_or_false")
    if (
        licence.org_id is None
        and not org_is_platform_owner
        and licence.third_party_permission is not ThirdPartyPermission.PERMITTED
    ):
        deny("third_party_permission")
    return licence


def _deny_licence(reason: str) -> None:
    raise PermissionDeniedError("the voice licence does not allow this render", details={"reason": reason})


# --- F-04 consent ------------------------------------------------------------------------


def check_consent(voice: ResolvedVoice, *, channel_id: ChannelId | None, now: datetime) -> None:
    """Only for ``CONSENTED_CLONE``; re-run on resume and before each checkpointed batch."""
    if voice.kind is not VoiceKind.CONSENTED_CLONE:
        return
    bundle = voice.bundle
    if bundle.voice.consent_id is None:
        raise PermissionDeniedError("a clone without a consent", details={"reason": "no_consent"})
    consent = bundle.consent
    if consent is None:
        raise MissingDependencyError("consent row not found")
    reason: str | None = None
    if consent.state is not ConsentState.VERIFIED:
        reason = f"consent_{consent.state.value.lower()}"
    elif consent.withdrawn_at is not None:
        reason = "consent_withdrawn"
    elif consent.expires_at is not None and consent.expires_at <= now:
        reason = "consent_expired"
    elif not bundle.voice_owner_is_org_owner:
        reason = "not_the_owners_voice"
    elif consent.permitted_channel_ids is None or channel_id not in consent.permitted_channel_ids:
        reason = "channel_outside_consent_scope"
    if reason is not None:
        raise PermissionDeniedError(
            "the voice consent does not allow this render", details={"reason": reason}
        )
