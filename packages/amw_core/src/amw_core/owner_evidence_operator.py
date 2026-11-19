"""Operator side of the real owner-evidence path (R14, D5; 08 ``sys_operator``; WS-08 / WS-10).

The assistant acting as ``sys_operator`` uses this module, connected as ``amw_operator`` only. It
can: find the owner's message that holds a quote (``locate``), record **pending** evidence or an
attempt it refuses itself (``record`` / ``refuse``), and produce the text it posts back to the
owner (``echo_*``). It cannot verify, confirm or stamp a MAC: those are the verifier's
(``amw_core.owner_evidence_real.VerifierWorker``, ``amw_verifier`` login).

The echo is an owner-visible **disclosure, not an independent control**
(``docs/v4/runtime/EVIDENCE_PATH.md`` section 5): this module only returns its text, and the
same assistant decides whether and what to post. It shows the owner the verbatim quote, the
review code and the exact reply; the verifier counts a reply only after an echo of that row is
in the session record. Texts are configuration (``owner_evidence_echo.json``; owner to
confirm), English and Marathi.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from typing import Final

from amw_core.enums import EvidenceState
from amw_core.errors import ConfigInvalidError, InputInvalidError
from amw_core.interfaces.audit_log import AuditLog
from amw_core.interfaces.owner_evidence import (
    DbRole,
    DbSession,
    EvidenceDatabase,
    EvidenceRecord,
    NewEvidence,
)
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.owner_evidence_audit import audit_entry, operator_reason
from amw_core.owner_evidence_real import OwnerMessage, OwnerMessageIndex

TEMPLATE_KEYS: Final = frozenset({"ask_decision", "recorded", "needs_clarification", "refused"})
MAX_ECHO_QUOTE: Final = 600


def load_echo_templates(raw: str | None = None) -> Mapping[str, Mapping[str, str]]:
    """``{lang: {key: template}}`` from the packaged JSON (or ``raw``); every language must
    define every key."""
    text = (
        raw
        if raw is not None
        else (resources.files("amw_core").joinpath("owner_evidence_echo.json").read_text("utf-8"))
    )
    data = json.loads(text)
    out: dict[str, dict[str, str]] = {}
    for lang, templates in data.items():
        if lang.startswith("_"):
            continue
        if not isinstance(templates, dict) or set(templates) != TEMPLATE_KEYS:
            raise ConfigInvalidError(f"echo templates for {lang!r} are incomplete")
        out[lang] = {k: str(v) for k, v in templates.items()}
    if not out:
        raise ConfigInvalidError("no echo templates")
    return out


def _shown(quote: str) -> str:
    """The quote as the owner sees it in the echo (verbatim; long quotes are cut visibly)."""
    one_line = quote.replace("\r", " ").replace("\n", " ")
    if len(one_line) <= MAX_ECHO_QUOTE:
        return one_line
    return one_line[: MAX_ECHO_QUOTE - 1] + "…"


@dataclass(frozen=True, slots=True)
class Echo:
    """What the operator posts to the owner (``text``) and the row it is about."""

    text: str
    row: EvidenceRecord | None = None


def locate(index: OwnerMessageIndex, session_id: str, quote: str) -> OwnerMessage:
    """The one owner chat message whose text contains ``quote`` verbatim. None or several ->
    ``InputInvalidError``: the operator asks the owner to restate (nothing is recorded)."""
    if not quote.strip():
        raise InputInvalidError("empty quote")
    hits = [m for m in index.owner_messages(session_id) if quote in m.content]
    if len(hits) != 1:
        raise InputInvalidError("the quote must occur in exactly one owner chat message")
    return hits[0]


class OperatorDesk:
    def __init__(
        self,
        database: EvidenceDatabase,
        operator: DbSession,
        audit: AuditLog,
        *,
        language: str = "mr",
        templates: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        if operator.role is not DbRole.OPERATOR:
            raise ConfigInvalidError("the operator desk runs as amw_operator")
        self._db = database
        self._operator = operator
        self._audit = audit
        self._templates = templates if templates is not None else load_echo_templates()
        if language not in self._templates:
            raise ConfigInvalidError(f"no echo templates for language {language!r}")
        self._lang = language

    def _text(self, key: str, **values: str) -> str:
        return self._templates[self._lang][key].format(**values)

    def ask_decision(self, review_code: str) -> Echo:
        return Echo(self._text("ask_decision", code=review_code))

    def record(self, tx: TenantTransaction, evidence: NewEvidence) -> Echo:
        """Insert ``PENDING_VERIFICATION`` evidence and return the echo with its review code
        (the approval's code, or the evidence's own code issued at insert, CCR-116)."""
        row = self._db.insert_evidence(self._operator, tx, evidence)
        return Echo(
            self._text(
                "recorded",
                quote=_shown(row.evidence.quote),
                code=row.evidence.review_code or "",
                kind=row.evidence.record_kind.value,
            ),
            row,
        )

    def refuse(
        self, tx: TenantTransaction, evidence: NewEvidence, reason: str, now: datetime
    ) -> Echo:
        """Record an attempt the operator refuses itself (e.g. the text came from a tool result
        or a sub-agent: never evidence), audited, and tell the owner."""
        safe = operator_reason(reason)
        row = self._db.insert_evidence(
            self._operator, tx, evidence, state=EvidenceState.REFUSED, refused_reason=safe
        )
        self._audit.append(tx, audit_entry(row, now))
        return Echo(self._text("refused", quote=_shown(row.evidence.quote), reason=safe), row)

    def needs_clarification(self, reason: str, review_code: str) -> Echo:
        """Nothing is recorded; the owner is asked to restate."""
        return Echo(
            self._text("needs_clarification", reason=operator_reason(reason), code=review_code)
        )

    def status(self, tx: TenantTransaction, row: EvidenceRecord) -> EvidenceState:
        """The current state of a row the operator recorded (it may read, never change it)."""
        current = self._db.get(self._operator, tx, row.id)
        if current is None:
            raise InputInvalidError("evidence not found")
        return current.state
