"""OwnerEvidenceVerifier (F-22) and ApprovalStepVerifier (F-26): guard G4 over the stored rows.

Agent 16 **re-checks**; it never verifies events and never writes evidence. It holds only an
``amw_app`` session (``StoreMacValidator`` refuses any other role at construction), so the only
evidence methods it can reach are the read methods and ``mac_valid``
(``amw_evidence_mac_valid``, 04 section 3.6a). Marking evidence ``VERIFIED`` / ``CONFIRMED`` and
stamping the keyed MAC is done only by the verifier component
(``amw_core.owner_evidence_service.EvidenceVerifierService``) through ``amw_verifier`` and the
``amw_verifier_fn`` definer functions; the operator assistant (``sys_operator``, the AI that
records the owner's chat decisions) holds an ``amw_operator`` session that can only insert
``PENDING_VERIFICATION`` / ``REFUSED`` rows and call ``amw_human_record_apply`` on CONFIRMED rows
(tests: ``test_operator_has_no_path_to_verified``).

Provenance (CCR-100): every evidence row a record relies on must pass ``mac_valid``; a row
inserted or edited by any connection other than the verifier functions (also one that set
``app.actor = 'sys_operator'``) fails. A MAC check that raises is a FAIL, never a PASS.
Honest limit (08 section 5.3): a shared superuser can bypass roles; the MAC makes that
detectable, not impossible.
"""

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal, Protocol

from agent_16_compliance_qa.authorisation.facts import EvidenceFacts, StepFacts, VerifierTest
from agent_16_compliance_qa.authorisation.guards import steps_approved
from amw_core.enums import (
    ApprovalChannel,
    ApprovalState,
    ApprovalStepState,
    EvidenceRecordKind,
    EvidenceState,
    EvidenceVerificationKind,
    InstructionSourceKind,
    QualityDimension,
)
from amw_core.errors import PermissionDeniedError
from amw_core.ids import ApprovalId, OrgId, UserId, WireId
from amw_core.interfaces.owner_evidence import DbRole, DbSession, EvidenceDatabase, EvidenceRecord
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.owner_evidence_verifier import (
    AUTHENTICITY_TESTS,
    DEFAULT_RECORD_KIND_RULES,
    NEEDS_CLARIFICATION,
    NEGATION_OR_WITHHOLDING,
    QUESTION_OR_DEFERRED,
    QUOTED_OR_FORWARDED,
    evidence_sha256,
)

_LOG = logging.getLogger(__name__)
OPERATOR_ACTOR: Final = "sys_operator"
_DECISION_KINDS: Final = frozenset(
    k for k, v in DEFAULT_RECORD_KIND_RULES.items() if v is EvidenceVerificationKind.DECISION
)
_COMMON_RULES: Final = ("rule_defined",)
_CONTENT_COMMON: Final = (
    NEGATION_OR_WITHHOLDING,
    QUOTED_OR_FORWARDED,
    QUESTION_OR_DEFERRED,
    "decision_not_applicable",
)
RULE_SET_TESTS: Final[Mapping[EvidenceVerificationKind, tuple[str, ...]]] = {
    EvidenceVerificationKind.DECISION: (
        *_COMMON_RULES,
        "review_code_given",
        "decision_given",
        NEEDS_CLARIFICATION,
        "decision_matches",
        "target_stage_matches",
    ),
    EvidenceVerificationKind.CONTENT: (*_COMMON_RULES, *_CONTENT_COMMON, "content_present"),
    EvidenceVerificationKind.SCORE: (
        *_COMMON_RULES,
        *_CONTENT_COMMON,
        "scores_given",
        "scores_in_range",
        "scores_stated",
    ),
}
"""The stored ``verifier_result`` names of each rule set (blueprint section 19.3 rules 4, 4b),
as ``amw_core.owner_evidence_verifier.verify_owner_event`` records them."""
_RULE_LABEL: Final[Mapping[EvidenceVerificationKind, VerifierTest]] = {
    EvidenceVerificationKind.DECISION: "DECISION_GRAMMAR",
    EvidenceVerificationKind.CONTENT: "CONTENT_RULES",
    EvidenceVerificationKind.SCORE: "SCORE_RULES",
}
CONFIRMATION_TESTS: Final = ("confirmation_grammar",)


def failed_verifier_tests(
    record_kind: EvidenceRecordKind, verifier_result: Mapping[str, bool]
) -> tuple[VerifierTest, ...]:
    """G4 (e): A1-A9, the kind's rule set and the confirmation whitelist, each passed; a test
    that is missing from the stored result counts as failed."""
    failed: list[VerifierTest] = []
    for label, names in AUTHENTICITY_TESTS.items():
        if not all(verifier_result.get(n) is True for n in names):
            failed.append(label)  # type: ignore[arg-type]
    kind = DEFAULT_RECORD_KIND_RULES.get(record_kind)
    if kind is None:
        failed.append("DECISION_GRAMMAR")
    elif not all(verifier_result.get(n) is True for n in RULE_SET_TESTS[kind]):
        failed.append(_RULE_LABEL[kind])
    if not all(verifier_result.get(n) is True for n in CONFIRMATION_TESTS):
        failed.append("CONFIRMATION_GRAMMAR")
    return tuple(failed)


class EvidenceReader(Protocol):
    """Read access to ``owner_instruction_evidence`` as ``amw_app`` (no write method exists)."""

    def get(self, tx: TenantTransaction, evidence_id: WireId) -> EvidenceRecord | None: ...

    def mac_valid(self, tx: TenantTransaction, evidence_id: WireId) -> bool: ...


class EvidenceUseIndex(Protocol):
    """Queries the replay and one-record checks need (core_need: L1 implements them as RLS
    reads of ``owner_instruction_evidence`` and the human-row tables)."""

    def live_rows_using_events(
        self, tx: TenantTransaction, event_uuids: frozenset[str]
    ) -> Sequence[EvidenceRecord]:
        """Every non-REFUSED evidence row of the org whose ``event_uuid`` or
        ``confirmation_event_uuid`` is in ``event_uuids``."""
        ...

    def record_keys_citing(self, tx: TenantTransaction, evidence_id: WireId) -> frozenset[str]:
        """Keys of every human record of the org whose ``evidence_id`` is this row (one
        ``amw_human_record_apply`` call = one key)."""
        ...


class StoreMacValidator:
    """``EvidenceReader`` over the evidence database with an ``amw_app`` session only."""

    def __init__(self, database: EvidenceDatabase, session: DbSession) -> None:
        if session.role is not DbRole.APP:
            raise PermissionDeniedError("Agent 16 reads evidence as amw_app only (CCR-100)")
        self._db = database
        self._session = session

    def get(self, tx: TenantTransaction, evidence_id: WireId) -> EvidenceRecord | None:
        return self._db.get(self._session, tx, evidence_id)

    def mac_valid(self, tx: TenantTransaction, evidence_id: WireId) -> bool:
        try:
            return self._db.mac_valid(self._session, tx, evidence_id) is True
        except Exception:  # a check that cannot run is a FAIL, never a PASS (section 18)
            _LOG.warning(
                "a16.evidence.mac_check_unavailable",
                extra={"org_id": tx.context.org_id, "evidence_id": evidence_id},
            )
            return False


@dataclass(frozen=True, slots=True)
class HumanRecordRef:
    """One human-originated row as the authorisation reads it (step, contribution, HUMAN
    score set, human verdict row)."""

    record_kind: EvidenceRecordKind
    record_key: str
    org_id: OrgId
    subject_kind: str
    subject_id: WireId
    approval_id: ApprovalId | None
    step_no: int | None
    human: UserId | None
    approval_channel: ApprovalChannel | None
    recorded_by: str | None
    evidence_id: WireId | None
    step_state: ApprovalStepState | None = None
    target_stage_id: str | None = None
    scores: tuple[tuple[QualityDimension, float], ...] = ()
    description: str | None = None


@dataclass(frozen=True, slots=True)
class ApprovalAnchor:
    approval_id: ApprovalId
    org_id: OrgId
    review_code: str | None
    created_at: datetime


@dataclass(slots=True)
class EvidenceCheckLog:
    mac_invalid: list[tuple[EvidenceRecordKind, WireId]] = field(default_factory=list)


def _invisible(evidence_id: WireId) -> EvidenceFacts:
    """The row is not visible under this tenant (RLS) or does not exist: nothing holds."""
    return EvidenceFacts(
        state=EvidenceState.PENDING_VERIFICATION,
        source_kind=InstructionSourceKind.OWNER_CHAT_MESSAGE,
        same_org=False,
        on_behalf_of_matches=False,
        subject_matches=False,
        review_code_matches=False,
        parsed_decision_matches=False,
        message_after_request=False,
        confirmation_after_message=False,
        verifier_all_passed=False,
        failed_tests=("A1",),
        refused_reason="EVENT_NOT_FOUND",
        hash_recomputes=False,
        mac_valid=False,
        replay_free=False,
        backs_only_this_record=False,
        recorded_by_operator=False,
        evidence_id=evidence_id,
    )


def _refused_label(
    reason: str | None,
) -> Literal["NEEDS_CLARIFICATION", "NOT_OWNER_AUTHORED", "EVENT_NOT_FOUND", "CHECK_FAILED"] | None:
    if reason is None:
        return None
    if reason in (
        NEEDS_CLARIFICATION,
        NEGATION_OR_WITHHOLDING,
        QUESTION_OR_DEFERRED,
        QUOTED_OR_FORWARDED,
    ):
        return "NEEDS_CLARIFICATION"
    if reason in ("source_owner_chat", "human_origin", "owner_account", "top_level_session"):
        return "NOT_OWNER_AUTHORED"
    return "CHECK_FAILED"


class OwnerEvidenceVerifier:
    """Computes the G4 facts of one human record from the stored rows."""

    def __init__(
        self,
        reader: EvidenceReader,
        index: EvidenceUseIndex,
        log: EvidenceCheckLog | None = None,
    ) -> None:
        self._reader = reader
        self._index = index
        self.log = log or EvidenceCheckLog()

    def facts(
        self,
        tx: TenantTransaction,
        record: HumanRecordRef,
        approval: ApprovalAnchor,
        loaded: Iterable[HumanRecordRef] = (),
    ) -> EvidenceFacts | None:
        if record.evidence_id is None:
            return None
        row = self._reader.get(tx, record.evidence_id)
        org = tx.context.org_id
        if row is None or row.org_id != org:
            return _invisible(record.evidence_id)
        e = row.evidence
        mac_ok = self._reader.mac_valid(tx, row.id)
        if not mac_ok:
            self.log.mac_invalid.append((record.record_kind, row.id))
            _LOG.warning(  # security event (section 22): a16_evidence_mac_invalid_total
                "a16.evidence.mac_invalid",
                extra={"org_id": org, "evidence_id": row.id, "record_kind": record.record_kind},
            )
        decision_kind = record.record_kind in _DECISION_KINDS
        if decision_kind:
            parsed: bool | None = e.parsed_decision is not None and (
                e.parsed_decision == record.step_state
                and (e.parsed_target_stage_id is not None)
                == (record.step_state is ApprovalStepState.CHANGES_REQUESTED)
                and e.parsed_target_stage_id == record.target_stage_id
            )
        elif record.record_kind is EvidenceRecordKind.HUMAN_SCORE:
            claimed = dict(e.claimed_scores)
            parsed = bool(record.scores) and all(
                d in claimed and float(claimed[d]) == float(p) for d, p in record.scores
            )
        elif record.record_kind is EvidenceRecordKind.CONTRIBUTION:
            parsed = bool(record.description) and (record.description or "") in e.quote
        else:
            parsed = None
        code_ok = (
            approval.review_code is not None
            and e.review_code is not None
            and e.review_code.upper() == approval.review_code.upper()
        )
        events = frozenset(u for u in (e.event_uuid, row.confirmation_event_uuid) if u is not None)
        others = [r for r in self._index.live_rows_using_events(tx, events) if r.id != row.id]
        keys = set(self._index.record_keys_citing(tx, row.id))
        keys |= {r.record_key for r in loaded if r.evidence_id == row.id}
        keys.add(record.record_key)
        confirmed_after = (
            row.confirmation_message_at is not None
            and row.confirmation_event_uuid is not None
            and row.confirmation_event_uuid != e.event_uuid
            and row.confirmation_message_at > e.message_at
        )
        failed = failed_verifier_tests(e.record_kind, row.verifier_result)
        return EvidenceFacts(
            state=row.state,
            source_kind=e.source_kind,
            same_org=row.org_id == org == record.org_id == approval.org_id,
            on_behalf_of_matches=record.human is not None and e.on_behalf_of == record.human,
            subject_matches=(
                e.record_kind is record.record_kind
                and e.subject_kind == record.subject_kind
                and e.subject_id == record.subject_id
                and e.approval_id == record.approval_id
                and e.step_no == record.step_no
            ),
            review_code_matches=code_ok,
            parsed_decision_matches=parsed,
            message_after_request=e.message_at > approval.created_at,
            confirmation_after_message=confirmed_after,
            verifier_all_passed=not failed,
            failed_tests=failed,
            refused_reason=_refused_label(row.refused_reason),
            hash_recomputes=evidence_sha256(e) == row.evidence_sha256,
            mac_valid=mac_ok,
            replay_free=not others,
            backs_only_this_record=len(keys) == 1,
            recorded_by_operator=(
                record.recorded_by == OPERATOR_ACTOR and e.recorded_by == OPERATOR_ACTOR
            ),
            evidence_id=row.id,
        )


VerifiedApprovalState = Literal["APPROVED", "APPROVED_UNVERIFIED", "PENDING", "REJECTED", "NONE"]


def derive_approval_state(
    state: ApprovalState | None,
    steps: Sequence[StepFacts],
    accepted_channels: frozenset[ApprovalChannel],
) -> VerifiedApprovalState:
    """F-26 (section 19.3 rule 13, CCR-102): ``APPROVED`` only when the approval has steps and
    every step is ``APPROVED`` and passes G2 and G4; ``approvals.state = APPROVED`` with a
    failing or undecided step is ``APPROVED_UNVERIFIED`` (never counted as approved)."""
    if state is None:
        return "NONE"
    if steps_approved(steps, accepted_channels):
        return "APPROVED"
    if state is ApprovalState.APPROVED:
        return "APPROVED_UNVERIFIED"
    if state is ApprovalState.PENDING:
        return "PENDING"
    return "REJECTED"
