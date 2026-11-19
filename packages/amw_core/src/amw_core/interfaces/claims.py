"""``claims`` / ``citations`` store (04 5.11; CCR-130, ticket P4-17).

The only writer of those tables for the fact-checking agent. The records here are neutral
(strings and mappings); an agent maps its own Pydantic models onto them. Every method takes the
tenant transaction and enforces ``org_id`` (27 section 7.3 rule 3).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from amw_core.ids import TaskId
from amw_core.interfaces.tenancy_context import TenantTransaction


@dataclass(frozen=True, slots=True)
class NewClaim:
    local_id: str
    """The id the extractor gave the claim inside its output."""
    text: str
    claim_kind: str
    attributes: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ClaimStatusUpdate:
    claim_id: str
    status: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CitationRow:
    """One ``citations`` row: a cited or supporting source of a claim."""

    claim_id: str
    source_ref: str
    kind: str
    support: str


@runtime_checkable
class ClaimStore(Protocol):
    def insert_claims(
        self, tx: TenantTransaction, *, script_id: str, task_id: TaskId, claims: Sequence[NewClaim]
    ) -> Mapping[str, str]:
        """Write-once, status ``EXTRACTED``; a replay of the same (script, task) returns the same
        ids. The result maps ``local_id`` to ``claim_id``."""
        ...

    def owned_claim_ids(
        self, tx: TenantTransaction, *, script_id: str, claim_ids: Sequence[str]
    ) -> frozenset[str]:
        """The subset of ``claim_ids`` that belong to the tx org and ``script_id``."""
        ...

    def extraction_verdicts(
        self, tx: TenantTransaction, *, script_id: str, claim_ids: Sequence[str]
    ) -> Mapping[str, str]:
        """The stored extraction verdict of each claim."""
        ...

    def update_status(
        self, tx: TenantTransaction, *, task_id: TaskId, results: Sequence[ClaimStatusUpdate]
    ) -> None:
        """Set status and reasons; a claim already changed by a different verification task is
        ``IdempotencyConflictError``."""
        ...

    def insert_citations(self, tx: TenantTransaction, rows: Sequence[CitationRow]) -> None:
        """Idempotent by (org, claim, source)."""
        ...
