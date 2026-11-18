"""U-02, U-03, U-13...U-20: script gate, voice resolver, licence and consent matrices."""

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from agent_07_voice_production import contracts as c
from agent_07_voice_production.policy import (
    ResolvedVoice,
    check_consent,
    check_licence,
    check_script_gate,
    language_supported,
    resolve_voice,
)
from agent_07_voice_production.ports import ApprovalFacts, LicenceFacts, ScriptRowFacts, VoiceBundle
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
from amw_core.ids import CHANNEL, ORG, Prefix, WireId, new_id
from amw_core.interfaces.voices import VoiceConsentRecord, VoiceRecord
from tests.agents.agent_07_voice_production.support import NOW, capabilities

pytestmark = pytest.mark.unit
SHA = "a" * 64
ORGID = ORG.new()
CH = CHANNEL.new()


def payload(**kw: Any) -> c.VoiceSynthesisInput:
    base: dict[str, Any] = {
        "purpose": "PRODUCTION",
        "script_id": new_id(Prefix.SCRIPT),
        "script_version": 1,
        "iteration": 0,
        "language": "mr-IN",
        "script_ref": f"amw-blob://{ORGID}/s/1",
        "script_sha256": SHA,
        "verification_ref": f"amw-blob://{ORGID}/v/1",
        "voice_id": new_id(Prefix.VOICE),
        "dictionary_ref": f"amw-blob://{ORGID}/d/1",
    }
    base.update(kw)
    return c.VoiceSynthesisInput.model_validate(base)


def verification(
    p: c.VoiceSynthesisInput, verdict: str = "ALLOWED", version: int | None = None
) -> c.VerificationOutput:
    return c.VerificationOutput(
        script_id=p.script_id,
        script_version=version or p.script_version,
        verification_verdict=verdict,
    )


def gate(p: c.VoiceSynthesisInput, **kw: Any) -> None:
    args: dict[str, Any] = {
        "blob_sha256": SHA,
        "row": ScriptRowFacts(SHA),
        "verification": verification(p),
        "approval": None,
    }
    args.update(kw)
    check_script_gate(p, **args)


def test_script_gate_passes_and_each_mismatch_is_input_invalid() -> None:
    p = payload()
    gate(p)
    for kw in (
        {"blob_sha256": "b" * 64},
        {"row": ScriptRowFacts("c" * 64)},
        {"verification": verification(p, version=2)},
        {"verification": verification(p, "BLOCKED")},
        {"verification": verification(p, "NEEDS_HUMAN_REVIEW")},
    ):
        with pytest.raises(InputInvalidError):
            gate(p, **kw)
    with pytest.raises(MissingDependencyError):
        gate(p, row=None)


def test_needs_human_review_requires_an_approved_approval_bound_to_the_hash() -> None:
    p = payload()
    review = verification(p, "NEEDS_HUMAN_REVIEW")
    gate(p, verification=review, approval=ApprovalFacts(ApprovalState.APPROVED, SHA))
    for approval in (
        ApprovalFacts(ApprovalState.PENDING, SHA),
        ApprovalFacts(ApprovalState.APPROVED, "d" * 64),
        None,
    ):
        with pytest.raises(InputInvalidError):
            gate(p, verification=review, approval=approval)


def bundle(kind: VoiceKind = VoiceKind.PROVIDER_STOCK, **kw: Any) -> VoiceBundle:
    vid = new_id(Prefix.VOICE)
    human = kind is VoiceKind.HUMAN_RECORDED
    clone = kind is VoiceKind.CONSENTED_CLONE
    source = {
        VoiceKind.PROVIDER_STOCK: LicenceSourceType.TTS_PROVIDER,
        VoiceKind.CONSENTED_CLONE: LicenceSourceType.VOICE_CLONE,
        VoiceKind.HUMAN_RECORDED: LicenceSourceType.HUMAN_NARRATION,
    }[kind]
    consent_id = new_id(Prefix.VOICE_CONSENT) if clone else None
    voice = VoiceRecord(
        vid,
        ORGID,
        "v",
        kind,
        None if human else "fake_tts",
        None if human else "ref",
        ("mr-IN",),
        consent_id,
        None,
        new_id(Prefix.LICENCE),
        PresenterKind.NEUTRAL_NARRATION,
        AssetStatus.ACTIVE,
    )
    licence = LicenceFacts(
        WireId(str(voice.licence_id)),
        ORGID,
        LicenceState.ACTIVE,
        source,
        True,
        ThirdPartyPermission.PERMITTED,
    )
    consent = (
        VoiceConsentRecord(
            WireId(str(consent_id)), ORGID, ConsentState.VERIFIED, (CH,), False, None, None
        )
        if clone
        else None
    )
    b = VoiceBundle(voice, licence, consent, True)
    return replace(b, **kw)


def resolved(b: VoiceBundle, **kw: Any) -> ResolvedVoice:
    args: dict[str, Any] = {
        "language": "mr-IN",
        "caps": capabilities(),
        "brand_kit_voice_id": b.voice.id,
        "production": True,
    }
    args.update(kw)
    return resolve_voice(b, **args)


def test_language_matching() -> None:
    assert language_supported("mr-IN", ["mr-IN"])
    assert language_supported("mr-IN", ["mr"])
    assert not language_supported("mr-IN", ["hi-IN"])
    assert not language_supported("ta", ["mr"])


def test_voice_resolution_matrix() -> None:
    b = bundle()
    assert resolved(b).presenter_kind is PresenterKind.NEUTRAL_NARRATION
    with pytest.raises(MissingDependencyError):
        resolve_voice(
            None, language="mr-IN", caps=capabilities(), brand_kit_voice_id=None, production=True
        )
    inactive = replace(b, voice=replace(b.voice, status=AssetStatus.QUARANTINED))
    with pytest.raises(PermissionDeniedError):
        resolved(inactive)
    with pytest.raises(UnsupportedTaskError):
        resolved(b, language="ta-IN")  # adapter does not declare it
    with pytest.raises(UnsupportedTaskError):
        resolved(
            b, caps=capabilities(languages=("mr-IN", "ta-IN")), language="ta-IN"
        )  # voice does not
    with pytest.raises(PermissionDeniedError):
        resolved(b, brand_kit_voice_id=new_id(Prefix.VOICE))
    assert resolved(
        b, brand_kit_voice_id=None, production=False
    )  # a sample needs no brand-kit binding
    with pytest.raises(MissingDependencyError):
        resolved(replace(b, voice=replace(b.voice, provider_voice_ref=None)))
    human = bundle(VoiceKind.HUMAN_RECORDED)
    assert resolved(
        human, caps=capabilities(languages=("en",))
    )  # a recording never needs the adapter
    with pytest.raises(InputInvalidError):
        resolved(replace(human, voice=replace(human.voice, provider="x")))


def licence_of(b: VoiceBundle, **kw: Any) -> VoiceBundle:
    assert b.licence is not None
    return replace(b, licence=replace(b.licence, **kw))


def check(b: VoiceBundle, **kw: Any) -> LicenceFacts:
    args: dict[str, Any] = {
        "monetized_destination": True,
        "org_is_platform_owner": True,
        "now": NOW,
    }
    args.update(kw)
    return check_licence(resolved(b), **args)


@pytest.mark.parametrize(
    "change",
    [
        {"state": LicenceState.EXPIRED},
        {"state": LicenceState.REVOKED},
        {"state": LicenceState.PENDING_VERIFICATION},
        {"expires_at": NOW - timedelta(seconds=1)},
        {"source_type": LicenceSourceType.VOICE_CLONE},
        {"covers_monetized_youtube": None},
        {"covers_monetized_youtube": False},
    ],
)
def test_licence_denials(change: dict[str, Any]) -> None:
    with pytest.raises(PermissionDeniedError):
        check(licence_of(bundle(), **change))


def test_licence_allowances_and_platform_held_rule() -> None:
    assert check(licence_of(bundle(), state=LicenceState.EXPIRING))
    assert check(licence_of(bundle(), covers_monetized_youtube=None), monetized_destination=False)
    platform = licence_of(
        bundle(), org_id=None, third_party_permission=ThirdPartyPermission.UNKNOWN
    )
    assert check(platform, org_is_platform_owner=True)
    with pytest.raises(PermissionDeniedError):
        check(platform, org_is_platform_owner=False)
    permitted = licence_of(
        bundle(), org_id=None, third_party_permission=ThirdPartyPermission.PERMITTED
    )
    assert check(permitted, org_is_platform_owner=False)
    with pytest.raises(MissingDependencyError):
        check(replace(bundle(), licence=None))


def consent_of(b: VoiceBundle, **kw: Any) -> VoiceBundle:
    assert b.consent is not None
    return replace(b, consent=replace(b.consent, **kw))


def run_consent(b: VoiceBundle, channel: Any = CH) -> None:
    check_consent(resolved(b), channel_id=channel, now=NOW)


@pytest.mark.parametrize(
    "change",
    [
        {"state": ConsentState.PENDING_VERIFICATION},
        {"state": ConsentState.WITHDRAWN},
        {"state": ConsentState.EXPIRED},
        {"state": ConsentState.REJECTED},
        {"withdrawn_at": NOW - timedelta(days=1)},
        {"expires_at": NOW - timedelta(days=1)},
        {"permitted_channel_ids": None},
        {"permitted_channel_ids": ()},
    ],
)
def test_consent_denials(change: dict[str, Any]) -> None:
    with pytest.raises(PermissionDeniedError):
        run_consent(consent_of(bundle(VoiceKind.CONSENTED_CLONE), **change))


def test_consent_other_cases() -> None:
    clone = bundle(VoiceKind.CONSENTED_CLONE)
    run_consent(clone)
    run_consent(consent_of(clone, expires_at=NOW + timedelta(days=1)))
    with pytest.raises(PermissionDeniedError):
        run_consent(replace(clone, voice_owner_is_org_owner=False))
    with pytest.raises(PermissionDeniedError):
        run_consent(clone, channel=CHANNEL.new())
    with pytest.raises(PermissionDeniedError):
        run_consent(replace(clone, voice=replace(clone.voice, consent_id=None)))
    with pytest.raises(MissingDependencyError):
        run_consent(replace(clone, consent=None))
    run_consent(bundle())  # not a clone: nothing to check
