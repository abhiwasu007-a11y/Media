"""PlanWriter (F-30) and blob loading: write-once, SHA-256 verified, tenant checked by core."""

import hashlib
import json
from dataclasses import dataclass
from io import BytesIO

from agent_09_video_director.assemble import canonical_json
from agent_09_video_director.contracts import Model, ShotPlan
from amw_core.errors import CorruptedOutputError
from amw_core.interfaces.storage import BlobStorage, BlobUri
from amw_core.interfaces.tenancy_context import TenantContext


@dataclass(frozen=True, slots=True)
class OutputRefData:
    uri: str
    sha256: str
    size_bytes: int


def persist_plan(
    storage: BlobStorage, ctx: TenantContext, plan: ShotPlan, *, task_path: str
) -> OutputRefData:
    """Write the plan blob once. A repeat with the same content returns the stored ref; a
    different content under the same path is refused by the storage (write-once, 03 section 8.2).
    The path is built by core (``blob_uri``), never by string formatting here."""
    body = canonical_json(plan.model_dump(mode="json")).encode("utf-8")
    sha = hashlib.sha256(body).hexdigest()
    uri: BlobUri = storage.blob_uri(ctx, "jobs", task_path)
    head = storage.head(ctx, uri)
    if head.exists:
        if head.sha256 != sha:
            raise CorruptedOutputError("plan blob exists with different content")
        return OutputRefData(str(uri), sha, head.size_bytes or len(body))
    info = storage.put(ctx, uri, BytesIO(body))
    return OutputRefData(str(info.uri), info.sha256, info.size_bytes)


def load_model[M: Model](
    storage: BlobStorage, ctx: TenantContext, uri: str, sha256: str, model: type[M]
) -> M:
    """Read a referenced JSON blob (hash verified by the storage while streaming)."""
    raw = b"".join(storage.get(ctx, BlobUri(uri), sha256))
    try:
        return model.model_validate(json.loads(raw))
    except ValueError as exc:
        raise CorruptedOutputError("referenced blob is not valid for its schema") from exc
