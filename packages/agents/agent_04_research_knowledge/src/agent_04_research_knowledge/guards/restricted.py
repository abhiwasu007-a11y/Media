"""RestrictedCollectionGate (blueprint 6.4; Q26, FIN-R12; release rule of 04 section 5.16).

``evaluate`` is pure given the approval lookup. A restricted chunk is allowed only for a method
topic AND when a same-org ``KNOWLEDGE_RELEASE`` approval in state ``APPROVED`` covers it.
"""

import hashlib
import json
from collections.abc import Collection
from dataclasses import dataclass
from typing import Protocol

from agent_04_research_knowledge.errors import CrossTenantRef
from agent_04_research_knowledge.models.enums import GateReason
from amw_core.enums import ApprovalKind, ApprovalState, VideoKind

SUBJECT_KNOWLEDGE_SOURCE = "knowledge_source"
SUBJECT_KNOWLEDGE_RELEASE = "knowledge_release"


@dataclass(frozen=True, slots=True)
class ApprovalView:
    """The approvals columns the gate reads: ``kind, state, subject_*, org_id`` (13)."""

    approval_id: str
    org_id: str
    kind: ApprovalKind
    state: ApprovalState
    subject_kind: str | None = None
    subject_id: str | None = None
    subject_sha256: str | None = None


class ApprovalLookup(Protocol):
    def approval(self, approval_id: str) -> ApprovalView | None: ...

    def released_chunk_ids(self, approval_id: str, collection_id: str) -> frozenset[str]:
        """Wire IDs of every chunk of the collection whose ``release_approval_id`` is the approval."""
        ...


@dataclass(frozen=True, slots=True)
class ChunkMeta:
    chunk_id: str
    org_id: str
    collection_id: str
    collection_key: str
    collection_restricted: bool
    source_id: str
    source_release_approval_id: str | None = None
    chunk_release_approval_id: str | None = None


@dataclass(frozen=True, slots=True)
class TopicFlags:
    video_kind: VideoKind
    title: str


@dataclass(frozen=True, slots=True)
class GateDecision:
    allowed: bool
    reason: GateReason | None
    release_approval_id: str | None = None
    method_labelled: bool = False
    restricted_pending: bool = False


def release_subject_sha256(
    topic_title: str, collection_key: str, chunk_ids: Collection[str]
) -> str:
    """SHA-256 of the canonical JSON ``{topic_title, collection_key, chunk_ids (sorted)}``."""
    doc = {
        "chunk_ids": sorted(chunk_ids),
        "collection_key": collection_key,
        "topic_title": topic_title,
    }
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _covers(
    approval: ApprovalView, chunk: ChunkMeta, topic: TopicFlags, lookup: ApprovalLookup
) -> bool:
    """04 section 5.16 release rule, both forms."""
    # (a) source level: the source carries the approval, or the approval's subject is the source
    if chunk.source_release_approval_id == approval.approval_id or (
        approval.subject_kind == SUBJECT_KNOWLEDGE_SOURCE and approval.subject_id == chunk.source_id
    ):
        return True
    # (b) per topic and chunk
    if (
        chunk.chunk_release_approval_id == approval.approval_id
        and approval.subject_kind == SUBJECT_KNOWLEDGE_RELEASE
        and approval.subject_id == chunk.collection_id
    ):
        released = lookup.released_chunk_ids(approval.approval_id, chunk.collection_id)
        expected = release_subject_sha256(topic.title, chunk.collection_key, released)
        return chunk.chunk_id in released and approval.subject_sha256 == expected
    return False


class RestrictedCollectionGate:
    def evaluate(self, chunk: ChunkMeta, topic: TopicFlags, lookup: ApprovalLookup) -> GateDecision:
        if not chunk.collection_restricted:
            return GateDecision(True, None, None, method_labelled=False)
        if topic.video_kind is not VideoKind.METHOD_TOPIC:
            return GateDecision(False, GateReason.NOT_METHOD_TOPIC)
        approval_id = chunk.chunk_release_approval_id or chunk.source_release_approval_id
        approval = lookup.approval(approval_id) if approval_id else None
        if approval is None:
            return GateDecision(False, GateReason.RELEASE_MISSING, restricted_pending=True)
        if approval.org_id != chunk.org_id:
            raise CrossTenantRef("approval belongs to another tenant")
        if approval.kind is not ApprovalKind.KNOWLEDGE_RELEASE:
            return GateDecision(False, GateReason.RELEASE_WRONG_KIND, restricted_pending=True)
        if approval.state is not ApprovalState.APPROVED:
            return GateDecision(False, GateReason.RELEASE_NOT_APPROVED, restricted_pending=True)
        if not _covers(approval, chunk, topic, lookup):
            return GateDecision(False, GateReason.RELEASE_NOT_COVERING, restricted_pending=True)
        return GateDecision(True, None, approval.approval_id, method_labelled=True)
