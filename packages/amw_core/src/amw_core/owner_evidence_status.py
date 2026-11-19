"""The ONE evidence-status contract between the owner-evidence store and its consumers (the run
preflight of ``amw_runtime``, PR #70; integrator decision for PR #77 + #70). ``amw_runtime``
imports these types and defines no copy of its own.

``EvidenceStatus`` is what a consumer may know about one evidence row. It is produced only by
``amw_core.owner_evidence_real.ConfirmedEvidenceLookup``, inside one tenant transaction and
from the database's own answers. A consumer accepts a row only if all of these hold:
``evidence_state == "CONFIRMED"``, ``recorded_from == "OWNER_CHAT_OPERATOR"``, ``mac_valid``,
``source_kind is EvidenceSourceKind.REAL``, ``org_id`` is the run's org, and ``subject`` equals
the key of the confirmation it backs.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol, runtime_checkable

OWNER_CHAT_OPERATOR: Final = "OWNER_CHAT_OPERATOR"


class EvidenceSourceKind(StrEnum):
    """Which kind of session source verified the row. It comes from the mark in
    ``verifier_result`` (inside the MAC; it cannot change after verification, migration 0059)."""

    REAL = "REAL"
    TEST_FIXTURE = "TEST_FIXTURE"
    """Verified through the in-memory dry-run source, or carrying no production mark."""


def subject_key(
    kind: str, provider: str | None, amount_minor: int | None, currency: str | None, org: str | None
) -> str:
    """The binding key of one confirmation: ``kind|provider|amount_minor|currency|org_id``, with
    ``-`` for an absent part (equal to ``amw_runtime`` ``ConfirmationRecord.subject()``)."""
    amount = "-" if amount_minor is None else str(amount_minor)
    return f"{kind}|{provider or '-'}|{amount}|{currency or '-'}|{org or '-'}"


@dataclass(frozen=True, slots=True)
class EvidenceStatus:
    """One evidence row as a run preflight sees it.

    * ``evidence_id``, ``org_id``: the row and its tenant (wire IDs).
    * ``evidence_state``: ``PENDING_VERIFICATION`` / ``VERIFIED`` / ``CONFIRMED`` / ``REFUSED``.
    * ``recorded_from``: ``OWNER_CHAT_OPERATOR`` for an owner-chat row, else its source kind.
    * ``kind``: the confirmation kind the row is bound to (e.g. ``PROVIDER_LIMIT``,
      ``FIN_R10_NOT_SEBI_REGISTERED``); ``None`` when the row does not state what that
      confirmation claims (wrong record kind, provider, amount, currency or org).
    * ``subject_kind``, ``subject_id``: the evidence row's own subject (04 section 5.16).
    * ``subject``: the bound confirmation key (``subject_key``), carrying the provider, amount
      and currency of a limit; ``None`` when unbound.
    * ``source_kind``: REAL or TEST_FIXTURE (immutable, see ``EvidenceSourceKind``).
    * ``mac_valid``: the database's ``amw_evidence_mac_valid`` at read time.
    """

    evidence_id: str
    evidence_state: str
    recorded_from: str
    org_id: str
    kind: str | None
    subject_kind: str
    subject_id: str
    subject: str | None
    source_kind: EvidenceSourceKind
    mac_valid: bool

    @property
    def usable(self) -> bool:
        """CONFIRMED, owner chat, MAC-valid, REAL and bound (the org and subject are the
        consumer's checks)."""
        return (
            self.evidence_state == "CONFIRMED"
            and self.recorded_from == OWNER_CHAT_OPERATOR
            and self.mac_valid
            and self.source_kind is EvidenceSourceKind.REAL
            and self.kind is not None
            and self.subject is not None
        )


@runtime_checkable
class EvidenceStatusLookup(Protocol):
    """What the run preflight calls: one row by its evidence ID, or ``None`` if the lookup was
    not built for that ID or the row is not in this tenant."""

    def get(self, evidence_id: str) -> EvidenceStatus | None: ...
