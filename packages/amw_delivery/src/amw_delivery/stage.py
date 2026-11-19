"""Worker entry point of ``agent_13.file_delivery`` (stage ``s13_deliver``, ticket 3A-14).

``DeliveryStage.run(task_input, ctx)`` is the ``TaskWorker`` shape of the merged PASS6 pattern
(03 section 1 rule 5, CCR-203): the execution context must match the Task Input (19.1 layer 1,
``TENANT_MISMATCH``), a payload that fails its schema is ``SCHEMA_INVALID`` (``REJECTED``), every
failure is RETURNED as a Task Output and never raised past ``run``. The stage has no provider
spend: the error output reports the time really spent and ``cost_estimate_micros`` 0 is the real
figure.

The payload is the inline :class:`~amw_delivery.models.BundleInputs` document (schema name
``agent_13.file_delivery.input``; registering agent payload schemas in the core allow-list is a
separate ticket, so nothing is registered here). The bundle is built in a private temporary
directory by :func:`~amw_delivery.bundle.build_bundle` and the zip and ``manifest.json`` are
written once through ``BlobStorage`` under the task's artifact path (core builder); a retried
attempt that finds identical bytes reuses them, different bytes are ``IDEMPOTENCY_CONFLICT``.
Nothing is uploaded to any platform: this is file delivery only.

The 9:16 re-frame (3A-15) stays in :mod:`amw_delivery.vertical`; the script side of 3A-15 is
``agent_05.shorts_adaptation`` (merged).
"""

import tempfile
from pathlib import Path

from pydantic import ValidationError

from amw_core.contracts.common import PayloadObject
from amw_core.contracts.error import error_object_from_exception, violation
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import NextAction, OutputRef, ResourceUsage, TaskOutput
from amw_core.enums import EscalationLevel, NextActionType, OutputRefKind, OutputStatus
from amw_core.errors import (
    AgentCrashError,
    AmwError,
    IdempotencyConflictError,
    InputInvalidError,
    SchemaInvalidError,
    SchemaVersionUnsupportedError,
    TenantMismatchError,
)
from amw_core.exec_context import ExecContext
from amw_core.interfaces.clock import Clock
from amw_core.interfaces.storage import BlobStorage, BlobUri
from amw_core.tenancy.storage_paths import task_artifact_uri
from amw_delivery.bundle import build_bundle
from amw_delivery.models import BundleInputs, BundleManifest

AGENT_ID = "agent_13"
INPUT_SCHEMA = "agent_13.file_delivery.input"
OUTPUT_SCHEMA = "agent_13.file_delivery.output"
SCHEMA_VERSION = "1.0.0"


def check_ctx(task_input: TaskInput, ctx: ExecContext) -> None:
    """Agent, org, job and task of the context equal those of the Task Input, else
    ``TENANT_MISMATCH`` before any step runs (19.1 layer 1)."""
    if task_input.agent_id != AGENT_ID:
        raise TenantMismatchError("task is not addressed to agent_13")
    if (
        str(ctx.org_id) != task_input.org_id
        or str(ctx.job_id) != task_input.job_id
        or str(ctx.task_id) != task_input.task_id
    ):
        raise TenantMismatchError("execution context does not match the Task Input")


def classify(exc: BaseException) -> AmwError:
    """One typed exception to one 07 code; anything else is ``AGENT.CRASH`` (no message copied)."""
    if isinstance(exc, AmwError):
        return exc
    return AgentCrashError("unhandled exception in agent_13", details={"type": type(exc).__name__})


def parse_inputs(task_input: TaskInput) -> BundleInputs:
    """The inline payload as typed inputs; a bad or absent payload is ``SCHEMA_INVALID``, and the
    org and job inside it must be those of the Task Input (``TENANT_MISMATCH``)."""
    data = task_input.payload.data
    if data is None or task_input.payload.payload_schema != INPUT_SCHEMA:
        raise SchemaInvalidError(
            "the delivery payload must be inline and named " + INPUT_SCHEMA,
            details={"violations": [violation("PAYLOAD_NOT_INLINE", "/payload")]},
        )
    try:
        inputs = BundleInputs.model_validate(data)
    except ValidationError as exc:
        raise SchemaInvalidError(
            "the delivery payload does not match its schema",
            details={
                "violations": [
                    violation(str(e["type"]), "/payload/data/" + "/".join(map(str, e["loc"])))
                    for e in exc.errors()[:50]
                ]
            },
        ) from None
    if inputs.org_id != task_input.org_id or inputs.job_id != task_input.job_id:
        raise TenantMismatchError("the delivery payload names another org or job")
    return inputs


class DeliveryStage:
    """Typed implementation of task type ``agent_13.file_delivery`` (``s13_deliver``)."""

    def __init__(
        self, storage: BlobStorage, clock: Clock, *, scratch_root: Path | None = None
    ) -> None:
        self._storage = storage
        self._clock = clock
        self._scratch_root = scratch_root

    def run(self, task_input: TaskInput, ctx: ExecContext) -> TaskOutput:
        """``TaskWorker`` entry point; every failure is returned as a Task Output."""
        started = self._clock.monotonic_ms()
        try:
            check_ctx(task_input, ctx)
            return self._execute(task_input, ctx, started)
        except Exception as raw:
            return self._failed(classify(raw), task_input, ctx, started)

    def _execute(self, task_input: TaskInput, ctx: ExecContext, started: int) -> TaskOutput:
        inputs = parse_inputs(task_input)
        scratch = str(self._scratch_root) if self._scratch_root is not None else None
        with tempfile.TemporaryDirectory(prefix="amw-delivery-", dir=scratch) as tmp:
            out_dir = Path(tmp) / "bundle"
            manifest = build_bundle(inputs, out_dir, storage=self._storage, context=ctx.tenant)
            zip_ref = self._put_once(
                ctx, out_dir / manifest.zip_name, manifest.zip_name, OutputRefKind.DATA,
                "application/zip", manifest.zip_sha256,
            )  # fmt: skip
            manifest_ref = self._put_once(
                ctx, out_dir / "manifest.json", "manifest.json", OutputRefKind.METADATA,
                "application/json", manifest.manifest_sha256,
            )  # fmt: skip
            refs = (zip_ref, manifest_ref)
        now = self._clock.now()
        elapsed = max(0, self._clock.monotonic_ms() - started)
        return TaskOutput(
            status=OutputStatus.SUCCEEDED,
            payload=PayloadObject(
                payload_schema=OUTPUT_SCHEMA,
                payload_schema_version=SCHEMA_VERSION,
                data=_manifest_data(manifest),
            ),
            output_refs=refs,
            quality_score=None,
            confidence=None,
            validation_results=(),
            duration=elapsed,
            resource_usage=_usage(elapsed, task_input.resource_budget.currency),
            error=None,
            next_action=NextAction(
                type=NextActionType.CONTINUE,
                wait_reason=None,
                escalation_level=None,
                reason="delivery bundle written",
            ),
            downstream_agent=None,
            timestamp=now,
        )

    def _put_once(
        self,
        ctx: ExecContext,
        path: Path,
        name: str,
        kind: OutputRefKind,
        media_type: str,
        sha256: str,
    ) -> OutputRef:
        """Write-once task artifact: equal bytes already stored (a retry) are reused, different
        bytes at the same URI are ``IDEMPOTENCY_CONFLICT``, never an overwrite (03 section 8.2)."""
        uri = BlobUri(
            task_artifact_uri(
                ctx.org_id, ctx.job_id, ctx.task_id, ctx.attempt_id, f"delivery/{name}"
            )
        )
        head = self._storage.head(ctx.tenant, uri)
        if head.exists:
            if head.sha256 != sha256 or head.size_bytes is None:
                raise IdempotencyConflictError("a different delivery file already exists here")
            return OutputRef(
                uri=str(uri), kind=kind, sha256=sha256, size_bytes=head.size_bytes,
                media_type=media_type,
            )  # fmt: skip
        with path.open("rb") as fh:
            info = self._storage.put(ctx.tenant, uri, fh)
        if info.sha256 != sha256 or info.size_bytes != path.stat().st_size:
            raise InputInvalidError("stored delivery file does not match the built file")
        return OutputRef(
            uri=str(info.uri), kind=kind, sha256=info.sha256, size_bytes=info.size_bytes,
            media_type=media_type,
        )  # fmt: skip

    def _failed(
        self, exc: AmwError, task_input: TaskInput, ctx: ExecContext, started: int
    ) -> TaskOutput:
        rejected = isinstance(exc, SchemaInvalidError | SchemaVersionUnsupportedError)
        now = self._clock.now()
        elapsed = max(0, self._clock.monotonic_ms() - started)
        error = error_object_from_exception(
            exc,
            actor=AGENT_ID,
            attempt_no=0 if rejected else ctx.attempt_no,
            occurred_at=now,
            correlation_id=task_input.correlation_id,
        )
        return TaskOutput(
            status=OutputStatus.REJECTED if rejected else OutputStatus.FAILED,
            payload=None,
            output_refs=(),
            quality_score=None,
            confidence=None,
            validation_results=(),
            duration=elapsed,
            resource_usage=_usage(elapsed, task_input.resource_budget.currency),
            error=error,
            next_action=NextAction(
                type=NextActionType.RETRY if exc.retryable else NextActionType.STOP,
                wait_reason=None,
                escalation_level=(
                    EscalationLevel.L2 if exc.error_class.value == "PERMANENT" else None
                )
                if not exc.retryable
                else None,
                reason=exc.code,
            ),
            downstream_agent=None,
            timestamp=now,
        )


def _usage(elapsed_ms: int, currency: str) -> ResourceUsage:
    """No provider spend in this stage: 0 micros is the real cost, not a placeholder."""
    return ResourceUsage(
        cpu_ms=elapsed_ms,
        peak_rss_bytes=0,
        tokens_in=0,
        tokens_out=0,
        tokens_cached_in=0,
        llm_calls=0,
        provider_calls=0,
        render_ms=0,
        cost_estimate_micros=0,
        currency=currency,
        cost_entry_ids=(),
    )


def _manifest_data(manifest: BundleManifest) -> dict[str, object]:
    return manifest.model_dump(mode="json")


__all__ = ["AGENT_ID", "DeliveryStage", "check_ctx", "classify", "parse_inputs"]
