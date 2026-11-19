"""Tenant scope, blob access and scratch directories (blueprint 10 s10, s19.1; F-01, F-02).

Layer 1 of tenant isolation: ``TenantScope.assert_consistent`` compares the org of the envelope,
the Task Input and every context ref BEFORE any file is staged; every blob read verifies the
SHA-256 (``BlobStorage.get`` raises ``CorruptedOutputError``); paths are built by ``amw_core`` and
never from payload, script or asset text.
"""

import shutil
from collections.abc import Sequence
from pathlib import Path

from agent_10_video_editor.errors import input_invalid
from amw_core.contracts.task_input import TaskInput
from amw_core.errors import CrossTenantRefError, TenantMismatchError
from amw_core.ids import AttemptId, JobId, Prefix, TaskId, parse_id
from amw_core.interfaces.storage import BlobInfo, BlobStorage, BlobUri
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.tenancy import storage_paths


class TenantScope:
    def __init__(self, context: TenantContext, storage: BlobStorage) -> None:
        self.context = context
        self.storage = storage

    @staticmethod
    def assert_consistent(envelope_org: str, task_input: TaskInput) -> None:
        """F-01: org of envelope, Task Input and every ref are equal (``platform`` read-only)."""
        if envelope_org != task_input.org_id:
            raise TenantMismatchError("envelope and input organisations differ")
        TenantScope.assert_refs_owned(task_input)

    @staticmethod
    def assert_refs_owned(task_input: TaskInput) -> None:
        """Every context ref belongs to the input's organisation or to ``platform``."""
        for ref in task_input.context_refs:
            owner = _owner(ref.uri)
            if owner not in (task_input.org_id, "platform"):
                raise CrossTenantRefError("reference belongs to another tenant")

    # -- blob access -------------------------------------------------------------------------

    def uri(self, area: str, path: str) -> BlobUri:
        for segment in path.split("/"):
            if segment in ("", ".", "..") or segment.startswith("/"):
                raise input_invalid("PATH_SEGMENT_REJECTED")
        return self.storage.blob_uri(self.context, area, path)

    # Every path below is built by the ``amw_core`` storage path builders (03 section 8 rule 5,
    # CCR-208); this agent never assembles a ``jobs`` sub-path by hand.

    def checkpoint_uri(self, job_id: str, task_id: str, name: str) -> BlobUri:
        """``jobs/<job>/checkpoints/<task>/<name>``."""
        org = self.context.org_id
        return BlobUri(storage_paths.checkpoint_uri(org, JobId(job_id), TaskId(task_id), name))

    def artifact_uri(self, job_id: str, task_id: str, attempt_id: str, name: str) -> BlobUri:
        """``jobs/<job>/tasks/<task>/attempts/<att>/artifacts/<name>`` (write-once task file)."""
        return BlobUri(
            storage_paths.task_artifact_uri(
                self.context.org_id, JobId(job_id), TaskId(task_id), AttemptId(attempt_id), name
            )
        )

    def render_uri(self, job_id: str, name: str) -> BlobUri:
        """``jobs/<job>/renders/<name>``."""
        return BlobUri(storage_paths.render_uri(self.context.org_id, JobId(job_id), name))

    def read_bytes(self, uri: str, sha256: str) -> bytes:
        return b"".join(self.storage.get(self.context, BlobUri(uri), sha256))

    def read_to(self, uri: str, sha256: str, target: Path) -> None:
        with target.open("wb") as handle:
            for chunk in self.storage.get(self.context, BlobUri(uri), sha256):
                handle.write(chunk)

    def head(self, uri: str) -> BlobInfo | None:
        head = self.storage.head(self.context, BlobUri(uri))
        if not head.exists or head.sha256 is None or head.size_bytes is None:
            return None
        return BlobInfo(BlobUri(uri), head.sha256, head.size_bytes)

    def put_file(self, uri: str, source: Path) -> BlobInfo:
        """Write-once put; an existing blob with the same content is returned (replay)."""
        with source.open("rb") as stream:
            return self.storage.put(self.context, BlobUri(uri), stream)

    def put_bytes(self, uri: str, data: bytes) -> BlobInfo:
        import io

        from agent_10_video_editor.canonical import sha256_hex

        existing = self.head(uri)
        if existing is not None and existing.sha256 == sha256_hex(data):
            return existing
        return self.storage.put(self.context, BlobUri(uri), io.BytesIO(data))


def _owner(uri: str) -> str:
    if "://" not in uri:
        raise CrossTenantRefError("reference has no storage owner")
    rest = uri.split("://", 1)[1]
    return rest.split("/", 1)[0]


class ScratchDir:
    """``<scratch_root>/<org uuid>/<task>/``: per task, cleaned at completion and worker start."""

    def __init__(self, root: Path, org_id: str, task_id: str) -> None:
        org_dir = str(parse_id(org_id, Prefix.ORGANISATION))
        self.path = root / org_dir / task_id.replace("/", "_")

    def open(self) -> Path:
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    def clean(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)

    @staticmethod
    def clean_all(root: Path) -> None:
        """At worker start: nothing from a previous process survives."""
        if root.exists():
            for child in root.iterdir():
                shutil.rmtree(child, ignore_errors=True)


def one_ref_per_schema(
    task_input: TaskInput, required: Sequence[str]
) -> dict[str, tuple[str, str]]:
    """Exactly one context ref per required schema (zero or two is ``INPUT_INVALID``)."""
    found: dict[str, list[tuple[str, str]]] = {}
    for ref in task_input.context_refs:
        if ref.schema_ is not None and ref.sha256 is not None:
            found.setdefault(ref.schema_, []).append((ref.uri, ref.sha256))
    violations = [f"REF_COUNT:{name}" for name in required if len(found.get(name, [])) != 1]
    if violations:
        raise input_invalid(*violations)
    return {name: found[name][0] for name in required}
