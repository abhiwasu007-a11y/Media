"""Typed ports (Protocols) of Agent 06 that Step 0 does not provide (blueprint 9.1, 9.2).

They are package-internal seams, not contracts: ``ClaimStore`` is the only writer of the
``claims`` / ``citations`` tables (04 5.11), ``KnowledgeReader`` the read-only view of the knowledge
tables, ``ScriptRegistry`` the read of ``scripts.content_sha256``. Every method takes the tenant
transaction (27 7.3 rule 3); implementations enforce ``org_id`` (and ``channel_id``) predicates, RLS
is the second line. core_needs: promote them to ``amw_core.interfaces`` if other agents need them.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from agent_06_fact_checker.models import (
    CitationKind,
    ExtractedClaim,
    Relation,
    Verdict,
    VerifiedClaim,
)
from amw_core.ids import ChannelId, TaskId
from amw_core.interfaces.tenancy_context import TenantTransaction


@dataclass(frozen=True, slots=True)
class SourceText:
    """One library source of the task's own org and channel, text loaded by code."""

    citation_ref: str
    kind: CitationKind
    text: str
    content_sha256: str
    """Chunk ``body_sha256`` or reference snapshot hash (CCR-053)."""
    reliability_tier: str | None
    """Agent 04 tier from the research pack; ``None`` when the pack has none."""
    restricted: bool
    """The source sits in a restricted ("our method") collection (FIN-R12, Q26)."""


@dataclass(frozen=True, slots=True)
class CitationRow:
    """One ``citations`` row (04 5.11): a cited or supporting source of a claim."""

    claim_id: str
    source_ref: str
    kind: CitationKind
    support: Relation


@runtime_checkable
class KnowledgeReader(Protocol):
    def get_source(
        self, tx: TenantTransaction, channel_id: ChannelId, citation_ref: str
    ) -> SourceText | None:
        """A chunk or reference snapshot of the tx org and ``channel_id``, else ``None``.
        A ref of another tenant is ``CrossTenantRefError``, never ``None`` (no existence oracle)."""
        ...

    def search(
        self, tx: TenantTransaction, channel_id: ChannelId, query: str, top_k: int
    ) -> Sequence[SourceText]:
        """Full-text search over the channel library (ADR-013 2.4); never restricted collections."""
        ...


@runtime_checkable
class ClaimStore(Protocol):
    def insert_claims(
        self,
        tx: TenantTransaction,
        *,
        script_id: str,
        task_id: TaskId,
        claims: Sequence[ExtractedClaim],
    ) -> Mapping[str, str]:
        """Write-once, status ``EXTRACTED``; a replay of the same (script, task) returns the same
        ids. Result maps ``local_id`` to ``claim_id``."""
        ...

    def owned_claim_ids(
        self, tx: TenantTransaction, *, script_id: str, claim_ids: Sequence[str]
    ) -> frozenset[str]:
        """The subset of ``claim_ids`` that belong to the tx org and ``script_id``."""
        ...

    def extraction_verdicts(
        self, tx: TenantTransaction, *, script_id: str, claim_ids: Sequence[str]
    ) -> Mapping[str, Verdict]:
        """The stored, code-recomputed extraction verdict of each claim (``claims`` rows)."""
        ...

    def update_status(
        self, tx: TenantTransaction, *, task_id: TaskId, results: Sequence[VerifiedClaim]
    ) -> None:
        """``status``, ``status_reasons``, ``verified_by_task_id``; a claim already changed by a
        different verification task is ``IdempotencyConflictError`` (chart task excepted)."""
        ...

    def insert_citations(self, tx: TenantTransaction, rows: Sequence[CitationRow]) -> None:
        """Idempotent by (org, claim, source)."""
        ...


@runtime_checkable
class ScriptRegistry(Protocol):
    def content_sha256(
        self, tx: TenantTransaction, *, script_id: str, script_version: int
    ) -> str | None:
        """``scripts.content_sha256`` of a script of the tx org, else ``None``."""
        ...


class ChartRanges(Protocol):
    def range_end(self, ref_id: str) -> date | None:
        """Last bar date of a chart whose dataset is already known (owner-made dataset)."""
        ...
