"""VerdictWriter (F-16; blueprint section 4 C8): the gate's rows, evidence blob and audit entry.

Per gate decision, in the caller's tenant transaction:

* one non-final ``compliance_verdicts`` row per rule row (``rule_id``, ``rule_pack_id`` /
  ``rule_pack_version`` of the pack holding the rule, ``subject_sha256`` = render hash, or the
  script hash for a script-level rule) plus the YTG-R3 disclosure row (``disclosure_decision``);
  an ``NEEDS_HUMAN_REVIEW`` row is an item G5 later binds a resolution to (rule + subject hash);
* one ``qc_results`` row per ``gate: true`` validation result;
* ``claims.final_verdict`` of every claim inside a judged item: the worst verdict over the rule
  rows that name the item (Agent 16 is the final authority, 04 table ``claims``);
* the evidence blob ``jobs/<job>/tasks/<task>/attempts/<att>/artifacts/compliance_gate-<iter>.json``
  (03 section 8 rule 5, CCR-208; write-once per attempt; an identical existing blob is reused,
  a different one is refused);
* one ``audit_log`` entry ``compliance.gate.verdicts_written`` (NF-09).

Every row write carries an ``idempotency_key`` of scope ``db.output`` over (task, kind, key), so
a retried attempt returns the stored rows (07 section 11). ``VerdictStore`` is the SQL port; its
``amw_app`` implementation is lane L1's (core_need), as is the ``claims.final_verdict`` column
(04 section 5 lists it; no migration has it yet).
"""

import hashlib
import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from agent_16_compliance_qa.base import worst
from agent_16_compliance_qa.checks import RuleResult
from agent_16_compliance_qa.gate import GateDecision, rule_rows
from agent_16_compliance_qa.packs import LoadedPacks
from amw_core.contracts.task_output import ValidationResult
from amw_core.enums import ActorKind, ComplianceVerdict, DisclosureDecision
from amw_core.errors import IdempotencyConflictError
from amw_core.ids import (
    ActorRef,
    AttemptId,
    CorrelationId,
    IdempotencyKey,
    IdempotencyScope,
    JobId,
    OrgId,
    TaskId,
    make_idempotency_key,
)
from amw_core.interfaces.audit_log import AuditLog, NewAuditEntry
from amw_core.interfaces.storage import BlobStorage, BlobUri
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.tenancy.storage_paths import task_artifact_uri

AGENT_ID = "agent_16"


@dataclass(frozen=True, slots=True)
class NewVerdictRow:
    job_id: str
    subject_kind: str
    subject_id: str
    subject_sha256: str
    rule_pack_id: str | None
    rule_pack_version: int | None
    rule_id: str | None
    verdict: ComplianceVerdict
    disclosure_decision: DisclosureDecision | None
    rationale: str
    evidence_ref: str | None
    decided_by: str = AGENT_ID
    is_final: bool = False


@dataclass(frozen=True, slots=True)
class NewQcRow:
    job_id: str
    task_id: str
    render_id: str | None
    result: ValidationResult


class VerdictStore(Protocol):
    """``amw_app`` writes (RLS + explicit ``org_id``); every method is idempotent per key."""

    def insert_verdict(
        self, tx: TenantTransaction, row: NewVerdictRow, key: IdempotencyKey
    ) -> str: ...
    def insert_qc_result(
        self, tx: TenantTransaction, row: NewQcRow, key: IdempotencyKey
    ) -> str: ...
    def set_claim_final_verdict(
        self, tx: TenantTransaction, claim_id: str, verdict: ComplianceVerdict, key: IdempotencyKey
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class GateSubjectRef:
    render_id: str
    render_sha256: str
    script_id: str
    script_sha256: str


@dataclass(frozen=True, slots=True)
class WriteScope:
    job_id: str
    task_id: str
    attempt_id: str
    iteration: int
    correlation_id: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class WrittenVerdicts:
    verdict_ids: tuple[str, ...]
    qc_ids: tuple[str, ...]
    claims_updated: int
    blob_uri: str
    blob_sha256: str
    blob_size: int


def _subject(rule: RuleResult, s: GateSubjectRef) -> tuple[str, str, str]:
    if rule.remedy == "script":
        return "script", s.script_id, s.script_sha256
    return "render", s.render_id, s.render_sha256


class VerdictWriter:
    def __init__(self, store: VerdictStore, storage: BlobStorage, audit: AuditLog) -> None:
        self._store, self._storage, self._audit = store, storage, audit

    def _key(self, tx: TenantTransaction, scope: WriteScope, *parts: str) -> IdempotencyKey:
        return make_idempotency_key(
            tx.context.org_id, IdempotencyScope.DB_OUTPUT, [scope.task_id, scope.iteration, *parts]
        )

    def _blob(
        self, tx: TenantTransaction, scope: WriteScope, payload: Mapping[str, Any]
    ) -> tuple[str, str, int]:
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        sha = hashlib.sha256(data).hexdigest()
        uri = BlobUri(
            task_artifact_uri(
                OrgId(tx.context.org_id),
                JobId(scope.job_id),
                TaskId(scope.task_id),
                AttemptId(scope.attempt_id),
                f"compliance_gate-{scope.iteration}.json",
            )
        )
        head = self._storage.head(tx.context, uri)
        if head.exists:
            if head.sha256 != sha:
                raise IdempotencyConflictError(
                    "a different evidence blob already exists for this task"
                )
            return str(uri), sha, len(data)
        info = self._storage.put(tx.context, uri, io.BytesIO(data))
        return str(info.uri), info.sha256, info.size_bytes

    def write(
        self,
        tx: TenantTransaction,
        decision: GateDecision,
        subject: GateSubjectRef,
        packs: LoadedPacks,
        results: Sequence[ValidationResult],
        claims_by_item: Mapping[str, Sequence[str]],
        scope: WriteScope,
        evidence_payload: Mapping[str, Any],
    ) -> WrittenVerdicts:
        uri, sha, size = self._blob(tx, scope, evidence_payload)
        ids: list[str] = []
        for r in rule_rows(decision):
            if r.compliance_verdict is None:
                continue  # SKIPPED / warning-only rows are qc_results, not verdicts
            pack = packs.pack_of(r.rule_id)
            kind, sid, ssha = _subject(r, subject)
            row = NewVerdictRow(
                job_id=scope.job_id,
                subject_kind=kind,
                subject_id=sid,
                subject_sha256=ssha,
                rule_pack_id=pack.rule_pack_id if pack else None,
                rule_pack_version=pack.version if pack else None,
                rule_id=r.rule_id if pack else None,
                verdict=r.compliance_verdict,
                disclosure_decision=decision.disclosure.disclosure_decision
                if r.rule_id == "YTG-R3"
                else None,
                rationale=r.rationale[:1000] or r.rule_id,
                evidence_ref=uri,
            )
            ids.append(
                self._store.insert_verdict(tx, row, self._key(tx, scope, "verdict", r.rule_id))
            )
        qc = [
            self._store.insert_qc_result(
                tx,
                NewQcRow(scope.job_id, scope.task_id, subject.render_id, v),
                self._key(tx, scope, "qc", v.check_id),
            )
            for v in results
            if v.gate
        ]
        per_item: dict[str, list[ComplianceVerdict | None]] = {}
        for r in decision.rules:
            for ref in r.item_refs:
                per_item.setdefault(ref, []).append(r.compliance_verdict)
        updated = 0
        for item_ref, claim_ids in sorted(claims_by_item.items()):
            v = worst(per_item.get(item_ref, ()))
            for cid in claim_ids:
                self._store.set_claim_final_verdict(tx, cid, v, self._key(tx, scope, "claim", cid))
                updated += 1
        self._audit.append(
            tx,
            NewAuditEntry(
                actor_kind=ActorKind.AGENT,
                actor_ref=ActorRef(AGENT_ID),
                authority=AGENT_ID,
                action="compliance.gate.verdicts_written",
                target_kind="render",
                target_id=subject.render_id,
                occurred_at=scope.occurred_at,
                job_id=JobId(scope.job_id),
                correlation_id=CorrelationId(scope.correlation_id),
                details={
                    "verdict": decision.verdict.value,
                    "verdict_rows": len(ids),
                    "qc_rows": len(qc),
                    "claims_updated": updated,
                    "evidence_sha256": sha,
                },
            ),
        )
        return WrittenVerdicts(tuple(ids), tuple(qc), updated, uri, sha, size)
