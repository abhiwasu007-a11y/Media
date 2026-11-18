"""``LicenceGuard`` (D11): mirrors the insert guard of 04 section 5.15 and goes further (6.6).

Pure. ``usable`` only if the state is ``ACTIVE`` (or ``EXPIRING``, with a warning), the licence
has not expired, a platform-held licence used by another tenant has ``PERMITTED`` third-party
permission, and for a monetized destination ``covers_monetized_youtube`` is true (NULL blocks,
ADR-009). A free or paid stock licence without indemnification yields a warning.
"""

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from amw_core.enums import (
    LicenceDestination,
    LicenceSourceType,
    LicenceState,
    SourcingWarning,
    ThirdPartyPermission,
)


class GuardReason(StrEnum):
    STATE_NOT_ACTIVE = "STATE_NOT_ACTIVE"
    EXPIRED = "EXPIRED"
    THIRD_PARTY_NOT_PERMITTED = "THIRD_PARTY_NOT_PERMITTED"
    MONETIZED_UNKNOWN = "MONETIZED_UNKNOWN"
    MONETIZED_NOT_COVERED = "MONETIZED_NOT_COVERED"


@dataclass(frozen=True, slots=True)
class LicenceView:
    """The licence fields the guard reads (a ``licences`` row, read only for Agent 08)."""

    state: LicenceState
    expires_in: timedelta | None
    platform_held: bool
    third_party_permission: ThirdPartyPermission | None
    covers_monetized_youtube: bool | None
    indemnification: bool | None
    source_type: LicenceSourceType


@dataclass(frozen=True, slots=True)
class GuardResult:
    usable: bool
    reason: GuardReason | None
    warnings: tuple[SourcingWarning, ...] = ()


_STOCK = frozenset({LicenceSourceType.PAID_STOCK, LicenceSourceType.FREE_STOCK})
_USABLE_STATES = frozenset({LicenceState.ACTIVE, LicenceState.EXPIRING})


def _block(reason: GuardReason) -> GuardResult:
    return GuardResult(False, reason)


class LicenceGuard:
    @staticmethod
    def check(
        *,
        licence: LicenceView,
        destination: LicenceDestination,
        tenant_is_platform_owner: bool,
        warning_window: timedelta,
    ) -> GuardResult:
        if licence.state not in _USABLE_STATES:
            return _block(GuardReason.STATE_NOT_ACTIVE)
        if licence.expires_in is not None and licence.expires_in <= timedelta(0):
            return _block(GuardReason.EXPIRED)
        if (
            licence.platform_held
            and not tenant_is_platform_owner
            and licence.third_party_permission is not ThirdPartyPermission.PERMITTED
        ):
            return _block(GuardReason.THIRD_PARTY_NOT_PERMITTED)
        if destination is LicenceDestination.MONETIZED_YOUTUBE:
            if licence.covers_monetized_youtube is None:
                return _block(GuardReason.MONETIZED_UNKNOWN)
            if not licence.covers_monetized_youtube:
                return _block(GuardReason.MONETIZED_NOT_COVERED)
        warnings: list[SourcingWarning] = []
        expiring = licence.state is LicenceState.EXPIRING or (
            licence.expires_in is not None and licence.expires_in <= warning_window
        )
        if expiring:
            warnings.append(SourcingWarning.LICENCE_EXPIRING)
        if licence.source_type in _STOCK and licence.indemnification is not True:
            warnings.append(SourcingWarning.NO_INDEMNIFICATION)
        return GuardResult(True, None, tuple(warnings))
