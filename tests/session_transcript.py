"""Synthetic Claude Code transcripts with the record STRUCTURE of the session runtime (field names,
nesting, marker values) and no real conversation: every text is made up for the test.

One builder per record kind the evidence source must handle; ``write`` produces the
``<root>/<session_id>.jsonl`` file the source reads.
"""

import json
import uuid
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
OWNER_ACCOUNT = "acct-owner-test"


def stamp(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{at.microsecond // 1000:03d}Z"


class Transcript:
    def __init__(self, session_id: str | None = None) -> None:
        self.session_id = session_id or str(uuid.uuid4())
        self.records: list[dict[str, Any]] = []
        self._last: str | None = None

    def _base(self, kind: str, at: datetime, uid: str | None) -> dict[str, Any]:
        uid = uid or str(uuid.uuid4())
        record: dict[str, Any] = {
            "type": kind,
            "parentUuid": self._last,
            "isSidechain": False,
            "uuid": uid,
            "timestamp": stamp(at),
            "sessionId": self.session_id,
            "cwd": "/work/repo",
            "gitBranch": "main",
            "entrypoint": "remote",
            "userType": "external",
            "version": "0.0.0-test",
        }
        self._last = uid
        return record

    def add(self, record: Mapping[str, Any]) -> str:
        self.records.append(dict(record))
        return str(record["uuid"])

    def human(
        self, text: str | list[dict[str, Any]], at: datetime, uid: str | None = None, **extra: Any
    ) -> str:
        r = self._base("user", at, uid)
        r |= {
            "message": {"role": "user", "content": text},
            "permissionMode": "auto",
            "origin": {"kind": "human"},
            "promptSource": "sdk",
            "turnOrigin": "human",
            "turnPosition": {"promptIndex": 1, "turnIndex": 1},
            "clientPlatform": "mobile",
            "turnAttributionKey": "k-test",
            "promptId": str(uuid.uuid4()),
        }
        r |= extra
        return self.add(r)

    def assistant(self, text: str, at: datetime) -> str:
        r = self._base("assistant", at, None)
        r["message"] = {
            "role": "assistant",
            "type": "message",
            "model": "test-model",
            "content": [{"type": "text", "text": text}],
        }
        return self.add(r)

    def tool_result(self, text: str, at: datetime) -> str:
        r = self._base("user", at, None)
        r |= {
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "toolu_test", "content": text}],
            },
            "toolUseResult": {"stdout": text},
            "sourceToolAssistantUUID": str(uuid.uuid4()),
            "promptId": str(uuid.uuid4()),
        }
        return self.add(r)

    def peer_handback(self, text: str, at: datetime) -> str:
        """A sub-agent hand-back / peer message: user role, ``origin.kind = peer``."""
        r = self._base("user", at, None)
        r |= {
            "message": {"role": "user", "content": text},
            "isMeta": True,
            "origin": {
                "kind": "peer",
                "from": "a0000000000000001",
                "senderTaskId": "a0000000000000001",
                "name": "helper",
                "body": text,
                "handback": True,
                "handbackReportText": text,
                "handbackToolUseId": "toolu_test",
            },
            "promptSource": "system",
            "turnOrigin": "peer",
            "turnPosition": {"promptIndex": 2, "turnIndex": 2},
            "queueSkipAttachments": True,
            "queueSkipSlashCommands": True,
        }
        return self.add(r)

    def task_notification(self, text: str, at: datetime) -> str:
        r = self._base("user", at, None)
        r |= {
            "message": {
                "role": "user",
                "content": f"<task-notification>{text}</task-notification>",
            },
            "origin": {"kind": "task-notification", "producer": "session-task", "runId": "r1"},
            "promptSource": "system",
            "turnOrigin": "task_notification",
            "queueSkipAttachments": True,
        }
        return self.add(r)

    def system_reminder(self, text: str, at: datetime) -> str:
        r = self._base("user", at, None)
        r |= {
            "message": {"role": "user", "content": f"<system-reminder>{text}</system-reminder>"},
            "isMeta": True,
        }
        return self.add(r)

    def meta_text(self, text: str, at: datetime) -> str:
        """Harness-injected plain text (``isMeta``, no wrapper tag, no origin)."""
        r = self._base("user", at, None)
        r |= {"message": {"role": "user", "content": text}, "isMeta": True}
        return self.add(r)

    def compact_summary(self, text: str, at: datetime) -> str:
        r = self._base("user", at, None)
        r |= {
            "message": {"role": "user", "content": text},
            "isCompactSummary": True,
            "isVisibleInTranscriptOnly": True,
        }
        return self.add(r)

    def sidechain(self, text: str, at: datetime) -> str:
        r = self._base("user", at, None)
        r |= {
            "message": {"role": "user", "content": text},
            "isSidechain": True,
            "agentId": "a0000000000000002",
            "origin": {"kind": "human"},
        }
        return self.add(r)

    def queue_operation(self, text: str, at: datetime) -> str:
        r = {"type": "queue-operation", "operation": "enqueue", "timestamp": stamp(at)}
        r |= {"sessionId": self.session_id, "content": text, "uuid": str(uuid.uuid4())}
        return self.add(r)

    def attachment(self, text: str, at: datetime) -> str:
        """A harness attachment that is not a queued command (e.g. a reminder)."""
        r = self._base("attachment", at, None)
        r |= {"attachment": {"type": "task_reminder", "content": text}, "renderedRole": "system"}
        return self.add(r)

    def queued(
        self,
        text: str | list[dict[str, Any]],
        at: datetime,
        *,
        origin: dict[str, Any] | None = None,
        record_extra: Mapping[str, Any] | None = None,
        **attachment_extra: Any,
    ) -> str:
        """A message queued while the assistant was busy: ``type:"attachment"`` /
        ``queued_command``; by default typed by the owner (``origin.kind = human``)."""
        r = self._base("attachment", at, None)
        att: dict[str, Any] = {
            "type": "queued_command",
            "commandMode": "prompt",
            "delivery_id": str(uuid.uuid4()),
            "humanTurn": True,
            "origin": origin if origin is not None else {"kind": "human"},
            "prompt": text,
            "source_uuid": str(uuid.uuid4()),
            "timestamp": r["timestamp"],
        }
        att |= attachment_extra
        r |= {"attachment": att, "renderedRole": "system", "rendered": []}
        r |= dict(record_extra or {})
        return self.add(r)

    def write(self, root: Path, extra_lines: Iterable[str] = (), *, tail: bytes = b"") -> Path:
        """``extra_lines`` are appended as complete lines; ``tail`` as raw bytes after the last
        newline (a line the CLI is still writing)."""
        path = root / f"{self.session_id}.jsonl"
        lines = [json.dumps(r, ensure_ascii=False) for r in self.records]
        body = ("\n".join([*lines, *extra_lines]) + "\n").encode("utf-8")
        path.write_bytes(body + tail)
        return path


def minutes(n: float) -> datetime:
    return T0 + timedelta(minutes=n)
