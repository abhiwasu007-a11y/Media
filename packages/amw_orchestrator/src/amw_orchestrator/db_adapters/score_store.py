"""``ScoreStore`` of agent_16 on PostgreSQL: machine ``quality_scores`` and ``qc_results`` rows
(04 section 5.17; agent_16 blueprint section 6.6).

Runs in the stage's tenant transaction as ``amw_app``. Writes only those two tables plus the
``idempotency_keys`` row of the key (scope ``db.output``, 03 section 9.2), in the same
transaction: a replay with the same key and the same row returns the stored ID and writes
nothing; the same key with another row is ``IdempotencyConflictError`` (from the key store).

Fail closed: the job, task and render must exist in the tenant (``MissingDependencyError``), the
score subject hash must equal ``renders.content_sha256`` (a score never attaches to another
render's content), and a ``HUMAN`` score is refused (04 section 5.16: human rows exist only
through ``amw_human_record_apply``).

Provisional where 04 has no column (CCR-301): ``qc_results`` has no ``gate`` or
``remedy_stage_id`` column, so those two fields stay in the Task Output only; the per-criterion
detail of a score is stored as the canonical JSON text of ``quality_scores.evidence_ref``
(18 section 9.1.5). The lock window of the idempotency row is configuration (``lock_ms``).
"""

import hashlib
import json
import uuid
from typing import Any, Final

import psycopg

from agent_16_compliance_qa.scoring.stage import NewScoreQcRow, NewScoreRow
from amw_core.errors import (
    InputInvalidError,
    LockConflictError,
    MissingDependencyError,
)
from amw_core.idempotency_store import PgIdempotencyStore
from amw_core.ids import JOB, RENDER, TASK, IdempotencyKey, IdempotencyScope, new_uuid7
from amw_core.interfaces import Clock
from amw_core.interfaces.idempotency_store import BeginAction
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_orchestrator.db_adapters._sql import (
    QC_RESULT,
    QUALITY_SCORE,
    org_of,
    require,
    rows,
    uuid_of,
)

SCORER_REF: Final = "agent_16"
_MACHINE_KINDS: Final = frozenset({"DETERMINISTIC", "LLM_JUDGE"})


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _digest32(hex_digest: str, what: str) -> bytes:
    try:
        digest = bytes.fromhex(hex_digest)
    except ValueError:
        raise InputInvalidError(f"{what} is not hexadecimal") from None
    if len(digest) != 32:
        raise InputInvalidError(f"{what} must be 32 bytes")
    return digest


class PgScoreStore:
    def __init__(
        self, clock: Clock, idempotency: PgIdempotencyStore | None = None, *, lock_ms: int
    ) -> None:
        if lock_ms < 1:
            raise InputInvalidError("lock_ms must be positive")
        self._clock = clock
        self._idem = idempotency or PgIdempotencyStore()
        self._lock_ms = lock_ms

    def insert_score(self, tx: TenantTransaction, row: NewScoreRow, key: IdempotencyKey) -> str:
        org, job, task = org_of(tx), uuid_of(JOB, row.job_id), uuid_of(TASK, row.task_id)
        render = uuid_of(RENDER, row.render_id)
        if row.scorer_kind not in _MACHINE_KINDS:
            raise InputInvalidError("only DETERMINISTIC and LLM_JUDGE scores are written here")
        rubric = row.evidence.get("rubric_version")
        if not isinstance(rubric, str) or not rubric:
            raise InputInvalidError("the score evidence must name its rubric_version")
        subject_sha = _digest32(row.render_sha256, "render sha256")
        request = _canonical(
            {
                "kind": "score",
                "job": row.job_id,
                "task": row.task_id,
                "render": row.render_id,
                "sha": row.render_sha256,
                "dimension": row.dimension,
                "max": row.max_points,
                "points": row.points,
                "scorer": row.scorer_kind,
                "evidence": row.evidence,
            }
        )
        self._check_subject(tx, org, job, task, render, subject_sha)
        stored = self._begin(tx, key, request, task)
        if stored is not None:
            return stored
        score = new_uuid7()
        try:
            rows(
                tx,
                "INSERT INTO quality_scores (id, org_id, job_id, subject_kind, subject_id,"
                " subject_sha256, rubric_version, dimension, max_points, points, scorer_kind,"
                " scorer_ref, evidence_ref)"
                " VALUES (%s, %s, %s, 'render', %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    score, org, job, render, subject_sha, rubric, row.dimension, row.max_points,
                    round(row.points, 2), row.scorer_kind, SCORER_REF, _canonical(row.evidence),
                ),
            )  # fmt: skip
        except psycopg.errors.CheckViolation:
            raise InputInvalidError(
                "the score is outside its dimension (max_points or points range)"
            ) from None
        wire = QUALITY_SCORE.from_uuid(score)
        self._complete(tx, key, wire)
        return wire

    def insert_qc_result(
        self, tx: TenantTransaction, row: NewScoreQcRow, key: IdempotencyKey
    ) -> str:
        org, job, task = org_of(tx), uuid_of(JOB, row.job_id), uuid_of(TASK, row.task_id)
        render = uuid_of(RENDER, row.render_id)
        result = row.result
        request = _canonical(
            {
                "kind": "qc",
                "job": row.job_id,
                "task": row.task_id,
                "render": row.render_id,
                "result": result.model_dump(mode="json"),
            }
        )
        require(tx, "jobs", org, job, "job")
        require(tx, "tasks", org, task, "task")
        require(tx, "renders", org, render, "render")
        stored = self._begin(tx, key, request, task)
        if stored is not None:
            return stored
        num, text = _measured(result.measured)
        thr_num, thr_text = _measured(result.threshold)
        qc = new_uuid7()
        rows(
            tx,
            "INSERT INTO qc_results (id, org_id, job_id, task_id, render_id, check_id, kind,"
            " verdict, blocking, rule_id, measured_num, measured_text, threshold_num,"
            " threshold_text, unit, message, evidence_ref)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                qc, org, job, task, render, result.check_id, result.kind.value,
                result.verdict.value, result.blocking, result.rule_id, num, text, thr_num,
                thr_text, result.unit, result.message,
                None if result.evidence_ref is None else str(result.evidence_ref),
            ),
        )  # fmt: skip
        wire = QC_RESULT.from_uuid(qc)
        self._complete(tx, key, wire)
        return wire

    # -- helpers ---------------------------------------------------------------------------
    def _begin(
        self, tx: TenantTransaction, key: IdempotencyKey, request: str, task: uuid.UUID
    ) -> str | None:
        """The stored result of a completed key, else ``None`` (proceed); never two writers."""
        decision = self._idem.begin(
            tx,
            key,
            IdempotencyScope.DB_OUTPUT.value,
            hashlib.sha256(request.encode()).hexdigest(),
            TASK.from_uuid(task),
            self._clock.now(),
            self._lock_ms,
        )
        if decision.action is BeginAction.PROCEED:
            return None
        if decision.action is BeginAction.RETURN_STORED and decision.record.result_ref:
            return decision.record.result_ref
        raise LockConflictError("the idempotency key is held by another attempt")

    def _complete(self, tx: TenantTransaction, key: IdempotencyKey, wire: str) -> None:
        self._idem.complete(tx, key, wire, self._clock.now())

    @staticmethod
    def _check_subject(
        tx: TenantTransaction,
        org: uuid.UUID,
        job: uuid.UUID,
        task: uuid.UUID,
        render: uuid.UUID,
        sha: bytes,
    ) -> None:
        require(tx, "jobs", org, job, "job")
        require(tx, "tasks", org, task, "task")
        found = rows(
            tx,
            "SELECT content_sha256 FROM renders WHERE org_id = %s AND id = %s AND job_id = %s",
            (org, render, job),
        )
        if not found:
            raise MissingDependencyError("render not found", details={"class": "render"})
        if bytes(found[0][0]) != sha:
            raise InputInvalidError("the score subject hash is not the render's content hash")


def _measured(value: bool | int | float | str | None) -> tuple[Any, str | None]:
    """``(num, text)``: numbers go to the numeric column, anything else to the text column."""
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, "true" if value else "false"
    if isinstance(value, int | float):
        return value, None
    return None, str(value)
