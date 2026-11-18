"""S3: ExternalReferenceFetcher and the reference snapshot writer (blueprint 10.4, 19.1 control 6).

Owner-supplied HTTPS references are fetched through the ``web_fetch`` adapter (idempotency scope
``fetch.reference``: task, ``r<position>``, URL SHA-256), hashed, reduced to text and cut into
passages. A 404, 410 or 403 does not fail the task: the source is recorded ``UNREACHABLE`` with no
hash and no snapshot. A snapshot is written write-once for every reference that backs a usable note.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import urlsplit

from agent_04_research_knowledge.errors import IdempotencyConflict, InputInvalid, RateLimited
from agent_04_research_knowledge.ingest.chunker import split_text
from agent_04_research_knowledge.models.enums import FetchStatus
from agent_04_research_knowledge.runtime import RunInfo
from agent_04_research_knowledge.settings import ExternalSettings
from amw_adapters.web_fetch.protocol import WebFetchAdapter, WebFetchRequest
from amw_core.errors import Upstream5xxError
from amw_core.ids import (
    IdempotencyScope,
    make_external_ref_id,
    make_idempotency_key,
    normalise_reference_url,
)
from amw_core.interfaces import BlobStorage, BlobUri, Clock

UNREACHABLE_STATUSES = frozenset({401, 403, 404, 410, 451})
TEXT_TYPES = ("text/plain", "text/markdown")
HTML_TYPES = ("text/html", "application/xhtml+xml")


class _TextExtractor(HTMLParser):
    _SKIP = frozenset({"script", "style", "noscript", "template"})
    _BREAK = frozenset(
        {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._depth += 1
        elif tag in self._BREAK:
            self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._depth:
            self._depth -= 1
        elif tag in self._BREAK:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if not self._depth:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return "".join(parser.parts).strip()


@dataclass(frozen=True, slots=True)
class ExternalPassage:
    text: str
    language: str


@dataclass
class FetchedSource:
    ref_id: str
    url: str
    ext_ref: str
    status: FetchStatus
    accessed_at: datetime
    content_sha256: str | None
    text: str = field(default="", repr=False)
    passages: list[ExternalPassage] = field(default_factory=list, repr=False)


def fetch_key(org_id: str, task_id: str, ref_id: str, url: str) -> str:
    """Idempotency key of one reference fetch (03 section 9.2, CCR-015)."""
    url_sha = hashlib.sha256(normalise_reference_url(url).encode("utf-8")).hexdigest()
    return make_idempotency_key(
        org_id, IdempotencyScope.FETCH_REFERENCE, [task_id, ref_id, url_sha]
    )


class ExternalReferenceFetcher:
    def __init__(self, web: WebFetchAdapter, clock: Clock, settings: ExternalSettings) -> None:
        self._web, self._clock, self._cfg = web, clock, settings

    def fetch(self, run: RunInfo, ref_id: str, url: str, language: str) -> FetchedSource:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname:
            raise InputInvalid("references must be HTTPS URLs")
        normalised = normalise_reference_url(url)
        ext_ref = make_external_ref_id(run.context.org_id, normalised)
        key = fetch_key(run.context.org_id, run.task_id, ref_id, url)
        run.effects.append(key)
        result = self._web.fetch(
            WebFetchRequest(
                url=url,
                max_bytes=self._cfg.max_bytes,
                timeout_ms=self._cfg.timeout_ms,
                max_redirects=self._cfg.max_redirects,
            ),
            idempotency_key=key,
        )
        run.usage.provider_calls += 1
        accessed_at = self._clock.now()
        final_host = (urlsplit(result.final_url).hostname or "").lower()
        if final_host != parts.hostname.lower() and final_host not in self._cfg.allowlist:
            raise InputInvalid("redirect to a host that is not allow-listed")
        status = result.status_code
        if status in UNREACHABLE_STATUSES or (status >= 300 and status < 500 and status != 429):
            run.log.info(
                "research.external_fetch", ref_id=ref_id, status=status, outcome="UNREACHABLE"
            )
            return FetchedSource(
                ref_id, normalised, ext_ref, FetchStatus.UNREACHABLE, accessed_at, None
            )
        if status == 429:
            raise RateLimited("reference host rate limited")
        if status >= 500:
            raise Upstream5xxError("reference host error", upstream_status=status)
        if len(result.content) > self._cfg.max_bytes:
            raise InputInvalid("reference larger than the size cap")
        media = result.media_type.split(";", 1)[0].strip().lower()
        raw = result.content.decode("utf-8", errors="replace")
        if media in HTML_TYPES:
            text = html_to_text(raw)
        elif media in TEXT_TYPES:
            text = raw.strip()
        else:
            raise InputInvalid("unsupported content type for a reference")
        passages = [
            ExternalPassage(piece, language)
            for piece in split_text(text, self._cfg.passage_target_chars, 0)
        ]
        run.log.info(
            "research.external_fetch",
            ref_id=ref_id,
            status=status,
            bytes=len(result.content),
            outcome="OK",
        )
        return FetchedSource(
            ref_id,
            normalised,
            ext_ref,
            FetchStatus.OK,
            accessed_at,
            result.content_sha256,
            text,
            passages,
        )


def snapshot_document(source: FetchedSource) -> bytes:
    """Canonical snapshot ``{extracted_text, content_sha256, external_url, accessed_at}``."""
    doc = {
        "accessed_at": source.accessed_at.isoformat().replace("+00:00", "Z"),
        "content_sha256": source.content_sha256,
        "external_url": source.url,
        "extracted_text": source.text,
    }
    return json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


class SnapshotWriter:
    """Write-once ``evidence/<job>/<ext_ref>.json`` (03 section 8, CCR-016)."""

    def __init__(self, storage: BlobStorage) -> None:
        self._storage = storage

    def write(self, run: RunInfo, source: FetchedSource) -> tuple[BlobUri, str]:
        body = snapshot_document(source)
        sha = hashlib.sha256(body).hexdigest()
        uri = self._storage.blob_uri(run.context, "evidence", f"{run.job_id}/{source.ext_ref}.json")
        head = self._storage.head(run.context, uri)
        if head.exists:
            if head.sha256 != sha:
                raise IdempotencyConflict("snapshot exists with different content")
            return uri, sha  # a replay: write-once, nothing to do
        self._storage.put(run.context, uri, BytesIO(body))
        run.audit.record(
            "research.reference_snapshot_written", "reference", source.ext_ref, {"sha256": sha}
        )
        return uri, sha
