"""Voices and voice consents, read side (04 section 5.12; CCR-026, CCR-027; ADR-008).

What Agent 07 needs before synthesis: the voice's licence link (``licence_id``, required when
``ACTIVE``), its ``presenter_kind`` (provisional until the owner answers 3A R4; FIN-R11 /
YTG-R2), and for a consented clone the consent's state and ``permitted_channel_ids`` (NULL = no
channel permitted). Tenant-scoped. Implementation: lane of Agent 07 / L1.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from amw_core.enums import AssetStatus, ConsentState, PresenterKind, VoiceKind
from amw_core.ids import ChannelId, OrgId, WireId
from amw_core.interfaces.tenancy_context import TenantTransaction


@dataclass(frozen=True, slots=True)
class VoiceRecord:
    id: WireId
    org_id: OrgId
    display_name: str
    kind: VoiceKind
    provider: str | None
    provider_voice_ref: str | None
    languages: tuple[str, ...]
    consent_id: WireId | None
    pronunciation_dict_ref: str | None
    licence_id: WireId | None
    presenter_kind: PresenterKind
    status: AssetStatus


@dataclass(frozen=True, slots=True)
class VoiceConsentRecord:
    id: WireId
    org_id: OrgId
    state: ConsentState
    permitted_channel_ids: tuple[ChannelId, ...] | None
    third_party_use: bool
    expires_at: datetime | None
    withdrawn_at: datetime | None


@runtime_checkable
class VoiceRegistry(Protocol):
    def get_voice(self, tx: TenantTransaction, voice_id: WireId) -> VoiceRecord | None: ...

    def get_consent(
        self, tx: TenantTransaction, consent_id: WireId
    ) -> VoiceConsentRecord | None: ...
