"""Owner confirmation records and the evidence lookup Protocol (reuses the owner-evidence model
of 08/04: a CONFIRMED row verified by the verifier; R14 is not weakened)."""

from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, model_validator


class ConfirmationKind(StrEnum):
    PROVIDER_LIMIT = "PROVIDER_LIMIT"
    FIN_R10_NOT_SEBI_REGISTERED = "FIN_R10_NOT_SEBI_REGISTERED"


class ConfirmationRecord(BaseModel):
    """The owner's confirmation, supplied as input. ``amount_minor``/``currency`` apply to a
    provider limit. ``test_fixture`` is a clearly labelled TEST record: dry run only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ConfirmationKind
    provider: str | None = None
    amount_minor: int | None = None
    currency: str | None = None
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


class EvidenceView(Protocol):
    """What the runtime needs of an owner-evidence row (04/08 model)."""

    @property
    def evidence_state(self) -> str: ...  # "CONFIRMED" once the verifier confirmed it

    @property
    def recorded_from(self) -> str: ...  # "OWNER_CHAT_OPERATOR"


class EvidenceLookup(Protocol):
    def get(self, evidence_id: str) -> EvidenceView | None: ...
