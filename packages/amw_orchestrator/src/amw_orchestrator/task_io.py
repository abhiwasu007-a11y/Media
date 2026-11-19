"""Task Input / Task Output documents in blob storage (03 section 8 rule 5, CCR-208).

``jobs/<job>/tasks/<task>/attempts/<attempt>/input.json`` and ``output.json`` are written once per
attempt through the core path builder; the task row keeps ``input_ref`` / ``output_ref`` and the
SHA-256 so a resumed runner reads the upstream outputs back (crash-resume) and the 03 section 5.3
success rule can ``head`` the stored output.
"""

import hashlib
import io
import json
from dataclasses import dataclass

from amw_core.contracts import TaskInput, TaskOutput
from amw_core.errors import MissingDependencyError
from amw_core.ids import AttemptId, JobId, OrgId, TaskId
from amw_core.interfaces import BlobStorage, TenantContext
from amw_core.interfaces.storage import BlobUri
from amw_core.tenancy.storage_paths import task_io_uri


@dataclass(frozen=True, slots=True)
class StoredDoc:
    uri: str
    sha256: str


def _bytes(doc: dict[str, object]) -> bytes:
    return json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


class TaskIo:
    def __init__(self, storage: BlobStorage) -> None:
        self._s = storage

    def _put(self, ctx: TenantContext, uri: str, doc: dict[str, object]) -> StoredDoc:
        data = _bytes(doc)
        info = self._s.put(ctx, BlobUri(uri), io.BytesIO(data))
        return StoredDoc(str(info.uri), info.sha256)

    def put_input(
        self, ctx: TenantContext, job: str, task: str, attempt: str, doc: TaskInput
    ) -> StoredDoc:
        uri = task_io_uri(
            OrgId(ctx.org_id), JobId(job), TaskId(task), AttemptId(attempt), "input.json"
        )
        return self._put(ctx, uri, doc.to_doc())

    def put_output(
        self, ctx: TenantContext, job: str, task: str, attempt: str, doc: TaskOutput
    ) -> StoredDoc:
        uri = task_io_uri(
            OrgId(ctx.org_id), JobId(job), TaskId(task), AttemptId(attempt), "output.json"
        )
        return self._put(ctx, uri, doc.to_doc())

    def get_output(self, ctx: TenantContext, uri: str, sha256: str) -> TaskOutput:
        """Verified read (SHA-256 checked while streaming); a missing ref is a typed error."""
        if not uri or not sha256:
            raise MissingDependencyError("completed task has no stored output")
        raw = b"".join(self._s.get(ctx, BlobUri(uri), sha256))
        if hashlib.sha256(raw).hexdigest() != sha256:  # defence in depth (the store verifies too)
            raise MissingDependencyError("stored output does not match its hash")
        return TaskOutput.model_validate(json.loads(raw))
