"""Local mock HTTP servers for the real adapters (``httpx.MockTransport``; no socket, no key).

The mocks follow the wire formats recorded in RESEARCH_LOG PR-08 / PR-11 / PR-12. They check what
a real server would need (key header present, model sent, no sampling parameter) and count the
requests that would be billable. ``script`` queues one-shot responses (status, headers, body)
consumed before the default behaviour; ``RecordedTransport`` replays redacted fixture files.
"""

import hashlib
import io
import json
import wave
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

TEST_KEY_VALUE = "test-value-not-a-key"
"""Placeholder in the test environment only; never a real key."""
ANTHROPIC_SECRET = "AMW_SECRET_ANTHROPIC_API_KEY"  # noqa: S105 - a secret NAME
ELEVENLABS_SECRET = "AMW_SECRET_ELEVENLABS_API_KEY"  # noqa: S105 - a secret NAME
TEST_ENV = {ANTHROPIC_SECRET: TEST_KEY_VALUE, ELEVENLABS_SECRET: TEST_KEY_VALUE}


@dataclass
class Scripted:
    status: int
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    raise_exc: Exception | None = None


def wav_bytes(frames: int, rate: int, width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        handle.writeframes(b"\x01\x00" * frames if width == 2 else b"\x01" * frames)
    return buf.getvalue()


class _Base:
    key_header: str = ""

    def __init__(self) -> None:
        self.script: deque[Scripted] = deque()
        self.requests: list[httpx.Request] = []
        self.billable = 0

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get(self.key_header) != TEST_KEY_VALUE:
            return httpx.Response(401, json={"error": {"type": "authentication_error"}})
        if self.script:
            item = self.script.popleft()
            if item.raise_exc is not None:
                raise item.raise_exc
            content = (
                item.body
                if isinstance(item.body, bytes)
                else json.dumps(item.body or {}).encode("utf-8")
            )
            return httpx.Response(item.status, content=content, headers=item.headers)
        return self.default(request)

    def default(self, request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise NotImplementedError


class MockAnthropic(_Base):
    key_header = "x-api-key"

    def default(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.headers["anthropic-version"]
        for banned in ("temperature", "top_p", "top_k", "tools", "tool_choice"):
            assert banned not in body, banned
        system = body.get("system", "")
        system_text = system if isinstance(system, str) else "".join(b["text"] for b in system)
        chars = len(system_text) + sum(len(m["content"]) for m in body["messages"])
        tokens_in = max(1, chars // 4)
        if request.url.path == "/v1/messages/count_tokens":
            return httpx.Response(200, json={"input_tokens": tokens_in})
        assert request.url.path == "/v1/messages"
        digest = hashlib.sha256(request.content).hexdigest()
        text = f"mock reply {digest[:16]}"
        tokens_out = min(max(1, len(text) // 4), body["max_tokens"])
        self.billable += 1
        cached = isinstance(system, list)
        return httpx.Response(
            200,
            headers={"request-id": f"req_mock{digest[:12]}"},
            json={
                "id": f"msg_mock{digest[:12]}",
                "type": "message",
                "role": "assistant",
                "model": body["model"],
                "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": text}],
                "stop_reason": "end_turn",
                "stop_details": None,
                "usage": {
                    "input_tokens": tokens_in,
                    "output_tokens": tokens_out,
                    "cache_creation_input_tokens": 8 if cached else 0,
                    "cache_read_input_tokens": 0,
                },
            },
        )


def anthropic_message(
    *,
    stop_reason: str = "end_turn",
    text: str = "ok",
    usage: dict[str, Any] | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    return {
        "id": "msg_scripted",
        "type": "message",
        "role": "assistant",
        "model": "m",
        "content": [] if stop_reason == "refusal" else [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_details": (
            {"type": "refusal", "category": category, "explanation": None}
            if stop_reason == "refusal"
            else None
        ),
        "usage": usage or {"input_tokens": 10, "output_tokens": 5},
    }


class MockElevenLabs(_Base):
    key_header = "xi-api-key"

    def __init__(self, voices: list[dict[str, Any]] | None = None) -> None:
        super().__init__()
        self.voices = voices or [
            {"voice_id": "mrVoice1", "name": "Neutral Marathi",
             "verified_languages": [{"language": "mr"}]},
            {"voice_id": "enVoice1", "name": "Neutral English", "labels": {"language": "en"}},
        ]  # fmt: skip

    def default(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/v2/voices":
            size = int(request.url.params["page_size"])
            start = int(request.url.params.get("next_page_token") or 0)
            page = self.voices[start : start + size]
            more = start + size < len(self.voices)
            return httpx.Response(
                200,
                json={
                    "voices": page,
                    "has_more": more,
                    "total_count": len(self.voices),
                    "next_page_token": str(start + size) if more else None,
                },
            )
        assert request.url.path.startswith("/v1/text-to-speech/")
        body = json.loads(request.content)
        assert body["model_id"], "model_id must always be sent (provider default: v2)"
        fmt = request.url.params["output_format"]
        assert fmt.startswith("wav_")
        rate = int(fmt.removeprefix("wav_"))
        self.billable += 1
        frames = len(body["text"]) * rate // 20  # synthetic pace of the mock
        digest = hashlib.sha256(request.content).hexdigest()
        return httpx.Response(
            200,
            content=wav_bytes(frames, rate),
            headers={"content-type": "audio/wav", "request-id": f"el{digest[:12]}"},
        )


class RecordedTransport(httpx.BaseTransport):
    """Replays redacted recordings ``{"method", "path", "status", "headers", "body"}`` in file
    order; any request beyond the recordings fails the test."""

    def __init__(self, folder: Path, check: Callable[[httpx.Request], None] | None = None) -> None:
        self._items = deque(
            json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))
        )
        self._check = check
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._check is not None:
            self._check(request)
        assert self._items, "no recorded response left"
        item = self._items.popleft()
        assert request.method == item["method"]
        assert request.url.path == item["path"]
        if item.get("wav"):
            content = wav_bytes(int(item["wav"]["frames"]), int(item["wav"]["rate"]))
        else:
            content = json.dumps(item["body"]).encode("utf-8")
        return httpx.Response(item["status"], content=content, headers=item.get("headers", {}))
