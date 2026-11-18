"""``DisclosureFlags`` (D15): asset flags for the disclosure decision (YT-06, YT-07).

The decision itself (``containsSyntheticMedia``) is Agent 16's. Output depicting a real person is
rejected (``REAL_PERSON_IN_AI_OUTPUT``); a code-made or real asset is never synthetic media.
"""

from dataclasses import dataclass
from enum import StrEnum

from amw_core.enums import LicenceUsageKind, VisualSourceTier

_AI_TIERS = frozenset({VisualSourceTier.D_AI_VIDEO, VisualSourceTier.E_AI_STILL})
PHOTOREAL = "PHOTOREAL"


class DisclosureRejection(StrEnum):
    REAL_PERSON_IN_AI_OUTPUT = "REAL_PERSON_IN_AI_OUTPUT"


@dataclass(frozen=True, slots=True)
class Flags:
    is_realistic_synthetic: bool
    depicts_real_person: bool
    usage_kind: LicenceUsageKind | None


@dataclass(frozen=True, slots=True)
class FlagsResult:
    flags: Flags | None
    rejection: DisclosureRejection | None = None


class DisclosureFlags:
    @staticmethod
    def compute(
        *, tier: VisualSourceTier, style: str, depicts_real_person: bool
    ) -> FlagsResult:
        if tier not in _AI_TIERS:
            return FlagsResult(Flags(False, False, None))
        if depicts_real_person:
            return FlagsResult(None, DisclosureRejection.REAL_PERSON_IN_AI_OUTPUT)
        return FlagsResult(Flags(style == PHOTOREAL, False, LicenceUsageKind.AI_OUTPUT))
