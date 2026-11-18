"""``ReuseEngine`` (D12, blueprint 6.9): exact and near-duplicate reuse, never across tenants.

``decide`` is the pure rule (RE-01 to RE-10). ``find`` walks one tenant's library through a
repository Protocol and returns the first reusable hit; the tenant predicate is applied in code
and the repository additionally scopes by ``org_id`` (RLS is the second line).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from agent_08_visual_assets.reuse.fingerprint import hamming


class ReuseDecisionKind(StrEnum):
    REUSE_EXACT = "REUSE_EXACT"
    REUSE_NEAR_DUPLICATE = "REUSE_NEAR_DUPLICATE"
    NOT_REUSABLE = "NOT_REUSABLE"
    MISS = "MISS"


@dataclass(frozen=True, slots=True)
class ReuseCandidate:
    org: str
    status: str
    expires_in: timedelta | None
    allowed_channels: tuple[str, ...] | None
    uses_in_window: int
    sha: str


@dataclass(frozen=True, slots=True)
class ReuseRequest:
    org: str
    channel: str
    sha: str


@dataclass(frozen=True, slots=True)
class ReuseDecision:
    decision: ReuseDecisionKind
    reason: str | None = None


class ReuseEngine:
    @staticmethod
    def decide(
        *,
        asset: ReuseCandidate,
        request: ReuseRequest,
        distance: int | None,
        max_uses: int | None,
        hamming_threshold: int | None,
    ) -> ReuseDecision:
        if asset.org != request.org:
            return ReuseDecision(ReuseDecisionKind.MISS, "OTHER_TENANT_NOT_VISIBLE")
        exact = asset.sha == request.sha
        near = (
            not exact
            and distance is not None
            and hamming_threshold is not None
            and distance <= hamming_threshold
        )
        if not exact and not near:
            return ReuseDecision(ReuseDecisionKind.MISS, "DISTINCT")
        if asset.status != "ACTIVE":
            return ReuseDecision(ReuseDecisionKind.NOT_REUSABLE, f"STATUS_{asset.status}")
        if asset.expires_in is not None and asset.expires_in <= timedelta(0):
            return ReuseDecision(ReuseDecisionKind.NOT_REUSABLE, "EXPIRED")
        if asset.allowed_channels is not None and request.channel not in asset.allowed_channels:
            return ReuseDecision(ReuseDecisionKind.NOT_REUSABLE, "CHANNEL_NOT_ALLOWED")
        if max_uses is not None and asset.uses_in_window >= max_uses:
            return ReuseDecision(ReuseDecisionKind.NOT_REUSABLE, "REUSE_LIMIT")
        return ReuseDecision(
            ReuseDecisionKind.REUSE_EXACT if exact else ReuseDecisionKind.REUSE_NEAR_DUPLICATE
        )

    @classmethod
    def find(
        cls,
        *,
        library: Sequence[tuple[str, ReuseCandidate, str | None]],
        request: ReuseRequest,
        request_phash: str | None,
        max_uses: int | None,
        hamming_threshold: int | None,
    ) -> tuple[str, ReuseDecision] | None:
        """First reusable ``(asset_id, decision)``; exact hits are preferred over near ones.

        ``library`` rows are ``(asset_id, candidate, perceptual_hash_hex)`` of the request's
        tenant only: foreign rows are skipped here as well (``RE-02``).
        """
        best_near: tuple[str, ReuseDecision] | None = None
        for asset_id, candidate, phash in library:
            if candidate.org != request.org:
                continue
            distance = (
                hamming(phash, request_phash) if phash is not None and request_phash else None
            )
            decision = cls.decide(
                asset=candidate,
                request=request,
                distance=distance,
                max_uses=max_uses,
                hamming_threshold=hamming_threshold,
            )
            if decision.decision is ReuseDecisionKind.REUSE_EXACT:
                return asset_id, decision
            if decision.decision is ReuseDecisionKind.REUSE_NEAR_DUPLICATE and best_near is None:
                best_near = (asset_id, decision)
        return best_near
