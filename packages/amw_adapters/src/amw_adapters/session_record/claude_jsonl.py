"""Session-record source over a Claude Code session transcript (WS-08 / 3A-13; R14, D5).

A Claude Code session writes its conversation to ``<transcript_root>/<session_id>.jsonl``, one
JSON record per line. Only some of those records are messages the owner typed. This module turns
the transcript into the ``SessionEventSource`` of ``amw_core.owner_evidence_verifier``, which the
evidence **verifier** (not the operator) reads.

**Strict allow-list by structure, never by text.** A record is an owner chat message only if every
one of these holds (the field names are the transcript schema observed on the session runtime;
``EVIDENCE_PATH.md`` lists them):

* ``type == "user"`` and ``message.role == "user"``;
* ``origin`` is exactly ``{"kind": "human"}`` (peer / sub-agent hand-backs carry
  ``{"kind": "peer", ...}``, task notifications ``{"kind": "task-notification", ...}``, tool
  results and harness-injected text carry no ``origin``);
* ``turnOrigin`` is absent or ``"human"``;
* ``isSidechain`` is ``False`` and there is no ``agentId`` (sub-agent transcripts);
* none of ``isMeta``, ``isCompactSummary``, ``isVisibleInTranscriptOnly``, ``queueTranscriptOnly``,
  ``toolUseResult``, ``sourceToolAssistantUUID``, ``sourceToolUseID`` is present and truthy;
* every top-level key is in ``allowed_keys`` (unknown shape -> refused, fail closed);
* ``message.content`` is a string, or a list of ``text`` blocks only;
* ``uuid``, ``timestamp`` and ``sessionId`` are present, and ``sessionId`` is the requested one;
* the event UUID occurs exactly once in the file.

A text test is used only to **refuse** more, never to accept: a message that contains a harness
wrapper tag (``<system-reminder>``, ``<task-notification>``, ...) is refused.

Pasted or attached content (a ``pastedContents`` / ``imagePasteIds`` key, or a non-text content
block) is marked ``embeds_earlier_message`` with no owner-authored part, so the verifier refuses
it as ``embedded_part_unmarked`` (CCR-125, ``NEEDS_CLARIFICATION``): the owner restates.

Every refused record is returned as a ``SessionEvent`` that fails the verifier's authenticity
tests (role, ``is_synthetic``, ``inbound_origin = "refused:<reason>"``) and carries no text, so
the evidence row becomes ``REFUSED`` with a reason instead of staying pending.

**What the transcript does not show** (see ``docs/v4/runtime/EVIDENCE_PATH.md``): it carries no
account identity (``sender_account`` is the configured owner account of the session) and no
parent-session link for a cloud child session (top level only for configured session IDs). The
file is writable by the process that runs the assistant; this source cannot detect an edit made
before it reads the file. REQUIRES REVIEW (owner): the residual risks listed there.
"""

import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from amw_core.owner_evidence_verifier import USER_ROLE, SessionEvent

HUMAN_ORIGIN: Final = "claude_code.human"
"""``inbound_origin`` of an accepted owner chat message (put it in ``human_inbound_origins``)."""
REFUSED_PREFIX: Final = "refused:"
UNVERIFIED_PARENT: Final = "unverified:not-a-configured-top-level-session"
"""``parent_session_id`` when the session is not configured as top level (A5 then refuses)."""
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_SESSION_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_EVENT_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

DEFAULT_ALLOWED_KEYS: Final = frozenset(
    {
        "type", "parentUuid", "isSidechain", "message", "uuid", "timestamp", "sessionId",
        "permissionMode", "origin", "promptSource", "turnOrigin", "turnPosition",
        "clientPlatform", "turnAttributionKey", "cwd", "gitBranch", "entrypoint", "promptId",
        "userType", "version", "slug", "mergedSendUuids", "savedFiles",
        # paste markers: allowed as keys, but they mark the event as embedding content
        "pastedContents", "imagePasteIds",
    }
)  # fmt: skip
"""Top-level keys a human-typed record may carry (observed schema; owner to confirm)."""
_REFUSING_FLAGS: Final = (
    "isMeta",
    "isCompactSummary",
    "isVisibleInTranscriptOnly",
    "queueTranscriptOnly",
    "toolUseResult",
    "sourceToolAssistantUUID",
    "sourceToolUseID",
    "agentId",
)
_PASTE_KEYS: Final = ("pastedContents", "imagePasteIds")
DEFAULT_WRAPPER_TAGS: Final = (
    "<system-reminder",
    "<task-notification",
    "<agent-message",
    "<local-command-",
    "<command-name",
    "<command-message",
    "<command-args",
    "<user-prompt-submit-hook",
    "<webhook-payload",
    "<child-session-event",
    "<wake ",
    "<event source=",
    "<persisted-output",
    "<tool_use_error",
    "<function_results",
    "<standing_owner_message",
)
"""Harness wrapper markers; a message containing one is refused (deny only, never allow)."""


class Verdict(StrEnum):
    """Why a transcript record is (not) an owner chat message."""

    OWNER_CHAT = "owner_chat"
    ASSISTANT = "assistant_message"
    TOOL_RESULT = "tool_result"
    PEER_OR_HANDBACK = "peer_or_subagent_handback"
    TASK_NOTIFICATION = "task_notification"
    META_OR_INJECTED = "meta_or_injected"
    SIDECHAIN = "sidechain_or_subagent"
    NOT_HUMAN_ORIGIN = "not_human_origin"
    NOT_A_MESSAGE = "not_a_user_message"
    UNKNOWN_SHAPE = "unknown_record_shape"
    WRAPPER_TEXT = "harness_wrapper_text"
    MALFORMED = "malformed_record"
    SESSION_MISMATCH = "session_mismatch"
    DUPLICATE_EVENT = "duplicate_event_uuid"


@dataclass(frozen=True, slots=True)
class Classified:
    verdict: Verdict
    content: str = ""
    embeds: bool = False


@dataclass(frozen=True, slots=True)
class OwnerChatEvent:
    """One accepted owner chat message (no other record kind is ever yielded)."""

    session_id: str
    event_uuid: str
    timestamp: datetime
    content: str
    content_sha256: str
    embeds_earlier_message: bool


@dataclass(frozen=True, slots=True)
class JsonlSourceConfig:
    """Verifier-side configuration (never from the operator or the model)."""

    transcript_root: Path
    owner_account_id: str
    """The owner's platform account this session belongs to (the transcript names none)."""
    top_level_session_ids: frozenset[str] = frozenset()
    """Sessions the owner declared top level; any other session gets ``UNVERIFIED_PARENT``."""
    allowed_keys: frozenset[str] = DEFAULT_ALLOWED_KEYS
    wrapper_tags: tuple[str, ...] = DEFAULT_WRAPPER_TAGS
    max_file_bytes: int = 256 * 1024 * 1024


def _content_of(message: Mapping[str, Any]) -> tuple[str, bool] | None:
    """``(text, has_non_text_block)`` or ``None`` when the content has no usable shape."""
    content = message.get("content")
    if isinstance(content, str):
        return content, False
    if not isinstance(content, list) or not content:
        return None
    texts: list[str] = []
    other = False
    for block in content:
        if not isinstance(block, dict):
            return None
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            texts.append(block["text"])
        elif block.get("type") in ("tool_result", "tool_use"):
            return None
        else:
            other = True  # image / document: an attachment, not owner-typed text
    return "\n".join(texts), other


def classify(record: Mapping[str, Any], config: JsonlSourceConfig) -> Classified:
    """The structural verdict for one transcript record (see the module docstring)."""
    kind = record.get("type")
    if kind == "assistant":
        return Classified(Verdict.ASSISTANT)
    if kind != "user":
        return Classified(Verdict.NOT_A_MESSAGE)
    message = record.get("message")
    if not isinstance(message, dict) or message.get("role") != USER_ROLE:
        return Classified(Verdict.MALFORMED)
    if "toolUseResult" in record or "sourceToolAssistantUUID" in record:
        return Classified(Verdict.TOOL_RESULT)
    if record.get("isSidechain") is not False or "agentId" in record:
        return Classified(Verdict.SIDECHAIN)
    origin = record.get("origin")
    origin_kind = origin.get("kind") if isinstance(origin, dict) else None
    if origin_kind == "peer":
        return Classified(Verdict.PEER_OR_HANDBACK)
    if origin_kind == "task-notification":
        return Classified(Verdict.TASK_NOTIFICATION)
    if any(record.get(flag) for flag in _REFUSING_FLAGS):
        return Classified(Verdict.META_OR_INJECTED)
    if origin != {"kind": "human"} or record.get("turnOrigin", "human") != "human":
        return Classified(Verdict.NOT_HUMAN_ORIGIN)
    if not set(record) <= config.allowed_keys:
        return Classified(Verdict.UNKNOWN_SHAPE)
    shaped = _content_of(message)
    if shaped is None:
        return Classified(Verdict.TOOL_RESULT if _has_tool_block(message) else Verdict.MALFORMED)
    text, non_text = shaped
    if not all(isinstance(record.get(k), str) for k in ("uuid", "timestamp", "sessionId")):
        return Classified(Verdict.MALFORMED)
    if any(tag in text for tag in config.wrapper_tags):
        return Classified(Verdict.WRAPPER_TEXT)
    pasted = non_text or any(record.get(k) for k in _PASTE_KEYS)
    return Classified(Verdict.OWNER_CHAT, text, pasted)


def _has_tool_block(message: Mapping[str, Any]) -> bool:
    content = message.get("content")
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") in ("tool_result", "tool_use") for b in content
    )


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def content_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ClaudeSessionJsonlSource:
    """``SessionEventSource`` over Claude Code transcripts; read-only, opened per call.

    ``production_grade`` marks it as a real session record (``amw_core.owner_evidence_real``
    refuses an in-memory source in real mode); it is not a claim of tamper-proofness."""

    production_grade: Final = True

    def __init__(self, config: JsonlSourceConfig) -> None:
        self._config = config

    def _path(self, session_id: str) -> Path | None:
        if not _SESSION_ID.match(session_id):
            return None
        path = self._config.transcript_root / f"{session_id}.jsonl"
        if path.is_symlink() or not path.is_file():
            return None
        if path.stat().st_size > self._config.max_file_bytes:
            return None
        return path

    def _records(self, session_id: str) -> Iterator[Mapping[str, Any]]:
        path = self._path(session_id)
        if path is None:
            return
        with path.open("r", encoding="utf-8", errors="strict") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue  # a partly written last line, or garbage: never an owner message
                if isinstance(record, dict):
                    yield record

    def _refused(
        self, session_id: str, event_uuid: str, verdict: Verdict, record: Any
    ) -> SessionEvent:
        stamp = _timestamp(record.get("timestamp")) if isinstance(record, dict) else None
        role = "assistant" if verdict is Verdict.ASSISTANT else "user"
        return SessionEvent(
            session_id=session_id,
            event_uuid=event_uuid,
            role=role if verdict is not Verdict.DUPLICATE_EVENT else "unknown",
            is_synthetic=True,
            inbound_origin=f"{REFUSED_PREFIX}{verdict.value}",
            content="",
            timestamp=stamp or _EPOCH,
            sender_account="",
            parent_session_id=UNVERIFIED_PARENT,
        )

    def _parent(self, session_id: str) -> str | None:
        return None if session_id in self._config.top_level_session_ids else UNVERIFIED_PARENT

    def fetch(self, session_id: str, event_uuid: str) -> SessionEvent | None:
        """The event as the verifier sees it; ``None`` if the session or event is not there."""
        if not _EVENT_UUID.match(event_uuid):
            return None
        matches = [r for r in self._records(session_id) if r.get("uuid") == event_uuid]
        if not matches:
            return None
        if len(matches) > 1:
            return self._refused(session_id, event_uuid, Verdict.DUPLICATE_EVENT, None)
        record = matches[0]
        if record.get("sessionId") != session_id:
            return self._refused(session_id, event_uuid, Verdict.SESSION_MISMATCH, record)
        verdict = classify(record, self._config)
        stamp = _timestamp(record.get("timestamp"))
        if verdict.verdict is not Verdict.OWNER_CHAT or stamp is None:
            reason = verdict.verdict if stamp is not None else Verdict.MALFORMED
            return self._refused(session_id, event_uuid, reason, record)
        return SessionEvent(
            session_id=session_id,
            event_uuid=event_uuid,
            role=USER_ROLE,
            is_synthetic=False,
            inbound_origin=HUMAN_ORIGIN,
            content=verdict.content,
            timestamp=stamp,
            sender_account=self._config.owner_account_id,
            parent_session_id=self._parent(session_id),
            embeds_earlier_message=verdict.embeds,
            owner_authored_content=None,
        )

    def owner_messages(self, session_id: str) -> Iterator[OwnerChatEvent]:
        """Every accepted owner chat message of the session, in file order (event UUIDs that
        occur more than once are skipped)."""
        records = list(self._records(session_id))
        counts: dict[str, int] = {}
        for record in records:
            uid = record.get("uuid")
            if isinstance(uid, str):
                counts[uid] = counts.get(uid, 0) + 1
        for record in records:
            uid = record.get("uuid")
            if not isinstance(uid, str) or counts[uid] != 1 or not _EVENT_UUID.match(uid):
                continue
            if record.get("sessionId") != session_id:
                continue
            verdict = classify(record, self._config)
            stamp = _timestamp(record.get("timestamp"))
            if verdict.verdict is Verdict.OWNER_CHAT and stamp is not None:
                yield OwnerChatEvent(
                    session_id=session_id,
                    event_uuid=uid,
                    timestamp=stamp,
                    content=verdict.content,
                    content_sha256=content_sha256(verdict.content),
                    embeds_earlier_message=verdict.embeds,
                )
