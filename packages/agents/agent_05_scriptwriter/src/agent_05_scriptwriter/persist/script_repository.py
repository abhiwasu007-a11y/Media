"""``ScriptRepository``: the ``ScriptStore`` adapter (blueprint 9.1, 10.7, 13).

The script document is a write-once task artifact at
``jobs/<job>/tasks/<task>/attempts/<att>/artifacts/script.json`` (03 section 8 rule 5, CCR-208),
built only by ``amw_core.tenancy.storage_paths``. The ``scripts`` row sits behind the narrow
``ScriptRowPort`` (one tenancy transaction, written by the worker's database adapter); this class
owns the blob, the SHA-256 check and the replay rule (same ``(job, language, version)`` with an
equal hash returns the stored row, a different hash is an error).
"""

from io import BytesIO
from typing import Protocol, runtime_checkable

from agent_05_scriptwriter.protocols import SavedScript, StepContext
from amw_core.errors import CorruptedOutputError
from amw_core.ids import ATTEMPT, CORRELATION, JOB, ORG, TASK, actor_ref
from amw_core.interfaces import BlobStorage, TenantContext
from amw_core.interfaces.storage import BlobUri
from amw_core.tenancy.storage_paths import task_artifact_uri

ARTIFACT = "script.json"
"""File name under ``attempts/<att>/artifacts/``."""
AGENT = "agent_05"


def tenant_context(ctx: StepContext) -> TenantContext:
    """The tenancy context of one attempt (org, actor ``agent_05``, correlation)."""
    return TenantContext(
        org_id=ORG.validate(ctx.org_id),
        actor=actor_ref(AGENT),
        correlation_id=CORRELATION.validate(ctx.correlation_id),
    )


@runtime_checkable
class ScriptRowPort(Protocol):
    """The ``scripts`` table access (04 section 5; org filter plus RLS), one transaction each."""

    def latest_version(self, ctx: StepContext, language: str) -> int:
        """Highest stored ``version`` of ``(job, language)``, 0 when none."""
        ...

    def find(self, ctx: StepContext, language: str, version: int) -> SavedScript | None: ...

    def insert(
        self,
        ctx: StepContext,
        saved: SavedScript,
        *,
        iteration: int,
        language: str,
        parent_script_id: str | None,
        segment_count: int,
        word_count: int,
        est_duration_ms: int | None,
        prompt_id: str,
    ) -> None:
        """Insert the ``DRAFT`` row, mark the previous iteration ``SUPERSEDED``, write the audit
        event: one transaction, idempotent per ``(job, language, version)``."""
        ...


class ScriptRepository:
    def __init__(self, storage: BlobStorage, rows: ScriptRowPort) -> None:
        self._storage = storage
        self._rows = rows

    def next_version(self, ctx: StepContext, language: str) -> int:
        return self._rows.latest_version(ctx, language) + 1

    def read_blob(self, ctx: StepContext, uri: str, sha256: str) -> bytes:
        """The storage backend checks the org of the URI and the SHA-256 while streaming."""
        return b"".join(self._storage.get(tenant_context(ctx), BlobUri(uri), sha256))

    def save(
        self,
        ctx: StepContext,
        *,
        script_id: str,
        version: int,
        iteration: int,
        language: str,
        content: bytes,
        sha256: str,
        parent_script_id: str | None,
        segment_count: int,
        word_count: int,
        est_duration_ms: int | None,
        prompt_id: str,
    ) -> SavedScript:
        existing = self._rows.find(ctx, language, version)
        if existing is not None:
            if existing.sha256 != sha256:
                raise CorruptedOutputError(
                    "a script row with this version exists with another hash",
                    details={"version": version},
                )
            return SavedScript(
                existing.script_id, existing.version, existing.uri, existing.sha256, False
            )
        tenant = tenant_context(ctx)
        uri = BlobUri(
            task_artifact_uri(
                ORG.validate(ctx.org_id),
                JOB.validate(ctx.job_id),
                TASK.validate(ctx.task_id),
                ATTEMPT.validate(ctx.attempt_id),
                ARTIFACT,
            )
        )
        head = self._storage.head(tenant, uri)
        if head.exists:  # a crash between the blob and the row: the blob is write-once
            if head.sha256 != sha256:
                raise CorruptedOutputError("stored script blob has another hash")
        else:
            info = self._storage.put(tenant, uri, BytesIO(content))
            if info.sha256 != sha256:
                raise CorruptedOutputError("script blob hash differs from the document hash")
        saved = SavedScript(script_id, version, str(uri), sha256, True)
        self._rows.insert(
            ctx,
            saved,
            iteration=iteration,
            language=language,
            parent_script_id=parent_script_id,
            segment_count=segment_count,
            word_count=word_count,
            est_duration_ms=est_duration_ms,
            prompt_id=prompt_id,
        )
        return saved
