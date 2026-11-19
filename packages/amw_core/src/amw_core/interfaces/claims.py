"""``claims`` / ``citations`` store (04 5.11, migration 0054; CCR-130, ticket P4-17).

The only writer of those tables for the fact-checking agent. The records mirror the table
columns and use the GLOSSARY enums (``ClaimType``, ``TimeReferenceKind``, ``ClaimStatus``,
``ComplianceVerdict``, ``RuleSeverity``, ``VerificationReasonCode``, ``CitationSupport``); an
agent maps its own Pydantic models onto them, and the free-form parts of an agent's model (a
rationale, an instrument) have no column and are not carried. Every method takes the tenant
transaction and enforces ``org_id`` (27 section 7.3 rule 3).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from amw_core.enums import (
    CitationSupport,
    ClaimStatus,
    ClaimType,
    ComplianceVerdict,
    RuleSeverity,
    TimeReferenceKind,
    VerificationReasonCode,
)
from amw_core.errors import InputInvalidError
from amw_core.ids import TaskId
from amw_core.interfaces.tenancy_context import TenantTransaction


def _enum(value: object, kind: type[StrEnum]) -> None:
    """Runtime check: a plain string that merely looks like an enum value is refused."""
    if not isinstance(value, kind):
        raise InputInvalidError(f"{kind.__name__} value expected")


@dataclass(frozen=True, slots=True)
class RuleFlag:
    """One element of ``claims.rule_flags`` (``{rule_id, severity, evidence}``)."""

    rule_id: str
    severity: RuleSeverity
    evidence: str

    def __post_init__(self) -> None:
        _enum(self.severity, RuleSeverity)


@dataclass(frozen=True, slots=True)
class NewClaim:
    """A ``claims`` row at extraction (status ``EXTRACTED``). The replay key of CCR-029 is
    ``(script_id, extracted_by_task_id, segment_id, char_start, char_end)``."""

    local_id: str
    """The id the extractor gave the claim inside its output (not a column)."""
    job_id: str
    """``claims.job_id`` (NOT NULL, FK jobs)."""
    segment_id: str
    char_start: int
    char_end: int
    quote: str
    normalized_claim: str
    claim_type: ClaimType
    time_reference_kind: TimeReferenceKind
    requires_citation: bool
    proposed_verdict: ComplianceVerdict
    rule_flags: tuple[RuleFlag, ...] = ()

    def __post_init__(self) -> None:
        _enum(self.claim_type, ClaimType)
        _enum(self.time_reference_kind, TimeReferenceKind)
        _enum(self.proposed_verdict, ComplianceVerdict)
        for flag in self.rule_flags:
            _enum(flag.severity, RuleSeverity)
        if self.char_start < 0 or self.char_end <= self.char_start:
            raise InputInvalidError("claim span must satisfy 0 <= char_start < char_end")
        if not self.quote or not self.normalized_claim:
            raise InputInvalidError("claim quote and normalized_claim are required")


@dataclass(frozen=True, slots=True)
class ClaimStatusUpdate:
    """The verification result written to a claim: ``status``, ``status_reasons`` and
    ``verified_by_task_id`` (the task id comes from ``update_status``)."""

    claim_id: str
    status: ClaimStatus
    reasons: tuple[VerificationReasonCode, ...] = ()
    substantiation_ref: str | None = None
    """``claims.substantiation_ref`` (set with ``SUBSTANTIATED``)."""

    def __post_init__(self) -> None:
        _enum(self.status, ClaimStatus)
        for reason in self.reasons:
            _enum(reason, VerificationReasonCode)


@dataclass(frozen=True, slots=True)
class CitationRow:
    """One ``citations`` row. Exactly one of ``knowledge_chunk_id`` and ``external_url`` is set
    (table CHECK); ``accessed_at`` is required with ``external_url``."""

    claim_id: str
    support: CitationSupport
    knowledge_chunk_id: str | None = None
    external_url: str | None = None
    research_log_id: str | None = None
    accessed_at: datetime | None = None

    def __post_init__(self) -> None:
        _enum(self.support, CitationSupport)
        if (self.knowledge_chunk_id is None) == (self.external_url is None):
            raise InputInvalidError("exactly one of knowledge_chunk_id and external_url")
        if self.external_url is not None and self.accessed_at is None:
            raise InputInvalidError("accessed_at is required with external_url")


@runtime_checkable
class ClaimStore(Protocol):
    def insert_claims(
        self, tx: TenantTransaction, *, script_id: str, task_id: TaskId, claims: Sequence[NewClaim]
    ) -> Mapping[str, str]:
        """Write-once, status ``EXTRACTED``; a replay of the same (script, task, span) returns
        the same ids. The result maps ``local_id`` to ``claim_id``."""
        ...

    def owned_claim_ids(
        self, tx: TenantTransaction, *, script_id: str, claim_ids: Sequence[str]
    ) -> frozenset[str]:
        """The subset of ``claim_ids`` that belong to the tx org and ``script_id``."""
        ...

    def extraction_verdicts(
        self, tx: TenantTransaction, *, script_id: str, claim_ids: Sequence[str]
    ) -> Mapping[str, ComplianceVerdict]:
        """The stored ``proposed_verdict`` of each claim."""
        ...

    def update_status(
        self, tx: TenantTransaction, *, task_id: TaskId, results: Sequence[ClaimStatusUpdate]
    ) -> None:
        """Set status and reasons; a claim already changed by a different verification task is
        ``IdempotencyConflictError``."""
        ...

    def insert_citations(self, tx: TenantTransaction, rows: Sequence[CitationRow]) -> None:
        """Idempotent by (org, claim, chunk, url)."""
        ...
