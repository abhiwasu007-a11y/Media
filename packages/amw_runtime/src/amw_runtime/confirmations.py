"""Owner confirmation records and the evidence lookup Protocol (reuses the owner-evidence model
of 08/04: a CONFIRMED row verified by the verifier; R14 is not weakened).

Binding (review M2): each record has a ``subject()`` key built from (kind, provider, amount,
currency, org). A real-run preflight requires the evidence row to report the same org, kind and
subject, a valid MAC and a REAL source, and distinct evidence per record, so one evidence id
cannot clear two items. A row that lacks any attribute is refused with a typed item (fail closed).
"""

from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, model_validator


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
        return (
            f"{self.kind.value}|{self.provider or '-'}|"
            f"{'-' if self.amount_minor is None else self.amount_minor}|"
            f"{self.currency or '-'}|{self.org_id or '-'}"
        )


# Binding constants (provisional until PR #77 / CCR-260 fixes the shared evidence contract in
# amw_core; the attribute NAMES below are the agreed ones). The row's subject is the preflight
# confirmation identified by ``ConfirmationRecord.subject()``.
SUBJECT_KIND = "PREFLIGHT_CONFIRMATION"
SOURCE_REAL = "REAL"
SOURCE_TEST_FIXTURE = "TEST_FIXTURE"


class EvidenceView(Protocol):
    """What the runtime needs of an owner-evidence row. The attribute names are those of the
    shared evidence contract owned by PR #77 (``amw_core``, CCR-260/261). The runtime reads every
    attribute defensively: a missing or wrongly typed one is a typed refusal, never an error."""

    @property
    def evidence_id(self) -> str: ...

    @property
    def evidence_state(self) -> str: ...  # "CONFIRMED" once the verifier confirmed it

    @property
    def recorded_from(self) -> str: ...  # "OWNER_CHAT_OPERATOR"

    @property
    def org_id(self) -> str: ...

    @property
    def kind(self) -> str: ...  # the ConfirmationKind value

    @property
    def subject_kind(self) -> str: ...

    @property
    def subject_id(self) -> str: ...

    @property
    def source_kind(self) -> str: ...  # REAL | TEST_FIXTURE

    @property
    def mac_valid(self) -> bool: ...


class EvidenceLookup(Protocol):
    def get(self, evidence_id: str) -> EvidenceView | None: ...
