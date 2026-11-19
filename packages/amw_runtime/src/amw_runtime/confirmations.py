"""Owner confirmation records and the evidence lookup Protocol (reuses the owner-evidence model
of 08/04: a CONFIRMED row verified by the verifier; R14 is not weakened).

Binding (review M2): each record has a ``subject()`` key (``subject_key`` of amw_core: kind,
provider, amount, currency, org). A real-run preflight requires the evidence row to report
the same org, kind and subject, a valid MAC and a REAL source, and distinct evidence per
record, so one evidence id cannot clear two items. A row that lacks any attribute is refused
with a typed item (fail closed).
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from amw_core.owner_evidence_status import (
    EvidenceSourceKind,
    EvidenceStatus,
    EvidenceStatusLookup,
    subject_key,
)

# The evidence-status contract is owned by amw_core (PR #77, CCR-260/261); re-exported here.
__all__ = [
    "ConfirmationKind",
    "ConfirmationRecord",
    "EvidenceSourceKind",
    "EvidenceStatus",
    "EvidenceStatusLookup",
]


class ConfirmationKind(StrEnum):
    PROVIDER_LIMIT = "PROVIDER_LIMIT"
    FIN_R10_NOT_SEBI_REGISTERED = "FIN_R10_NOT_SEBI_REGISTERED"


class ConfirmationRecord(BaseModel):
    """The owner's confirmation, supplied as input. ``amount_minor``/``currency`` apply to a
    provider limit. ``test_fixture`` is a clearly labelled TEST record: dry run only.
    ``verified`` is a claim of the caller and is never trusted on its own: the evidence lookup
    is the check."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ConfirmationKind
    provider: str | None = None
    amount_minor: int | None = None
    currency: str | None = None
    org_id: str | None = None
    recorded_from: Literal["OWNER_CHAT_OPERATOR"]
    evidence_id: str | None = None
    review_code: str | None = None
    verified: bool
    test_fixture: bool = False

    @model_validator(mode="after")
    def _shape(self) -> ConfirmationRecord:
        if self.kind is ConfirmationKind.PROVIDER_LIMIT and (
            not self.provider or self.amount_minor is None or not self.currency
        ):
            raise ValueError("a provider limit needs provider, amount_minor and currency")
        return self

    def subject(self) -> str:
        """Stable key the evidence row must carry (kind, provider, amount, currency, org)."""
        return subject_key(
            self.kind.value, self.provider, self.amount_minor, self.currency, self.org_id
        )
