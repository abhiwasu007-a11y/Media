"""ReliabilityScorer and DomainClassRegistry (blueprint 6.3, 10.5): deterministic, no model."""

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from agent_04_research_knowledge.errors import ConfigInvalid
from agent_04_research_knowledge.models.enums import DomainClass, ReliabilityTier
from amw_core.enums import KnowledgeSourceKind as Kind
from amw_core.enums import SourceOwnership as Own

OWNERSHIP_UNKNOWN = "OWNERSHIP_UNKNOWN"


@dataclass(frozen=True, slots=True)
class TierScores:
    """``research.reliability.tier_scores.<tier>``: strictly decreasing from A to D (6.3)."""

    a: float
    b: float
    c: float
    d: float

    def __post_init__(self) -> None:
        values = (self.a, self.b, self.c, self.d)
        if not all(0.0 <= v <= 1.0 for v in values) or not (self.a > self.b > self.c > self.d):
            raise ConfigInvalid("reliability tier scores must be in 0..1 and strictly decrease")

    @classmethod
    def from_mapping(cls, scores: Mapping[str, float]) -> TierScores:
        try:
            return cls(
                scores[ReliabilityTier.A_PRIMARY],
                scores[ReliabilityTier.B_PUBLISHED],
                scores[ReliabilityTier.C_SECONDARY],
                scores[ReliabilityTier.D_UNVERIFIED],
            )
        except KeyError as exc:
            raise ConfigInvalid(f"tier score missing: {exc.args[0]}") from None

    def score(self, tier: ReliabilityTier) -> float:
        return (self.a, self.b, self.c, self.d)[tier.rank]


class DomainClassRegistry:
    """Host to domain class (config ``research.reliability.domain_classes``)."""

    def __init__(self, hosts: Mapping[str, DomainClass]) -> None:
        self._hosts = {h.lower(): c for h, c in hosts.items()}

    def class_of_host(self, host: str) -> DomainClass | None:
        host = host.lower()
        if host in self._hosts:
            return self._hosts[host]
        # a sub-domain of a registered host inherits its class
        parts = host.split(".")
        for i in range(1, len(parts) - 1):
            parent = ".".join(parts[i:])
            if parent in self._hosts:
                return self._hosts[parent]
        return None

    def class_of_url(self, url: str) -> DomainClass | None:
        return self.class_of_host(urlsplit(url).hostname or "")


@dataclass(frozen=True, slots=True)
class SourceMeta:
    kind: Kind
    ownership: Own | None
    """``None`` only for an external reference that is not a library row (CCR-041)."""
    domain_class: DomainClass | None = None
    library_row: bool = True


@dataclass(frozen=True, slots=True)
class Reliability:
    tier: ReliabilityTier | None
    score: float | None
    owner_authored: bool
    ownership_in_pack: Own | None
    excluded: bool
    reason: str | None = None


class ReliabilityScorer:
    def score(
        self, source: SourceMeta, domain_classes: object, tier_scores: TierScores
    ) -> Reliability:
        """Tier from kind, ownership and domain class. ``UNKNOWN`` ownership is excluded (Q25).

        ``domain_classes`` is accepted for the blueprint signature; the host class is resolved by
        the caller (``DomainClassRegistry``) into ``source.domain_class``.
        """
        del domain_classes
        if source.library_row and source.ownership is Own.UNKNOWN:
            return Reliability(None, None, False, Own.UNKNOWN, True, OWNERSHIP_UNKNOWN)
        tier, owner_authored = self._tier(source)
        ownership = source.ownership if source.library_row else None
        return Reliability(tier, tier_scores.score(tier), owner_authored, ownership, False)

    @staticmethod
    def _tier(source: SourceMeta) -> tuple[ReliabilityTier, bool]:
        kind, own = source.kind, source.ownership
        if kind is Kind.WEB_REFERENCE:
            if source.domain_class is DomainClass.OFFICIAL:
                return ReliabilityTier.A_PRIMARY, False
            if source.domain_class is DomainClass.REPUTABLE_SECONDARY:
                return ReliabilityTier.C_SECONDARY, False
            return ReliabilityTier.D_UNVERIFIED, False
        if kind is Kind.OFFICIAL_DOCUMENT and own is Own.PUBLIC_OFFICIAL:
            return ReliabilityTier.A_PRIMARY, False
        if kind is Kind.BOOK and own in (Own.OWNED_COPY, Own.LICENSED):
            return ReliabilityTier.B_PUBLISHED, False
        if kind in (Kind.COURSE_NOTES, Kind.OWNER_NOTES) and own is Own.OWNER_AUTHORED:
            return ReliabilityTier.B_PUBLISHED, True
        if kind is Kind.CLIENT_DOCUMENT:
            return ReliabilityTier.B_PUBLISHED, False
        # A combination 6.3 does not list is the lowest tier, never an invented upgrade.
        return ReliabilityTier.D_UNVERIFIED, False
