"""IngestionPipeline (blueprint 10.9): hash check, format, text layer, structure, chunk, index, QA.

Idempotent: the chunk key ``(org, source, ingest_version, chunk_no)`` makes a replayed insert a
no-op, and a re-ingest uses a new ``ingest_version`` (old rows are never updated, CCR-013).
"""

import hashlib
import uuid
from dataclasses import dataclass
from typing import Protocol

from agent_04_research_knowledge.errors import InputInvalid
from agent_04_research_knowledge.ingest.chunker import split_text
from agent_04_research_knowledge.ingest.extract import PageQualityChecker, extract_pages
from agent_04_research_knowledge.ingest.structure import map_structure, qa_sample
from agent_04_research_knowledge.library.models import ChunkRow, TenantScope
from agent_04_research_knowledge.library.protocol import KnowledgeLibrary
from agent_04_research_knowledge.models.enums import IngestSourceStatus
from agent_04_research_knowledge.models.ingest import IngestInput, IngestOutput
from agent_04_research_knowledge.observability import AuditSink, EventLogger
from agent_04_research_knowledge.settings import IngestSettings
from amw_core.enums import ExtractionMethod, KnowledgeSourceStatus, SourceOwnership
from amw_core.ids import Prefix, new_id


@dataclass(frozen=True, slots=True)
class SourceFile:
    content: bytes
    media_type: str


class SourceFiles(Protocol):
    def read(self, scope: TenantScope, source_id: str) -> SourceFile:
        """The registered file from private storage (read-only)."""
        ...


class IngestionPipeline:
    def __init__(
        self,
        library: KnowledgeLibrary,
        files: SourceFiles,
        settings: IngestSettings,
        audit: AuditSink,
        log: EventLogger,
    ) -> None:
        self._lib, self._files, self._cfg = library, files, settings
        self._audit, self._log = audit, log

    def run(self, scope: TenantScope, request: IngestInput) -> IngestOutput:
        source = self._lib.get_source(scope, request.source_id)
        if source is None:
            raise InputInvalid("unknown source")
        if source.ownership is SourceOwnership.UNKNOWN:
            raise InputInvalid("ownership unknown")
        version = request.ingest_version
        existing = self._lib.chunk_count(scope, source.source_id, version)
        if existing and not request.force_reextract:
            self._lib.set_source_status(
                scope, source.source_id, KnowledgeSourceStatus.INDEXED, version
            )
            return IngestOutput(
                source_id=source.source_id,
                ingest_version=version,
                source_status=IngestSourceStatus.INDEXED,
                chunks_written=0,
                pages_total=0,
                pages_needs_ocr=0,
                qa_sample_size=0,
                unresolved_headings=0,
            )
        self._lib.set_source_status(
            scope, source.source_id, KnowledgeSourceStatus.INGESTING, version
        )
        try:
            return self._ingest(
                scope,
                request,
                source.content_sha256,
                source.collection_id,
                source.language,
                source.source_id,
            )
        except InputInvalid:
            self._lib.set_source_status(scope, source.source_id, KnowledgeSourceStatus.FAILED)
            self._audit.record("knowledge.ingest_failed", "knowledge_source", source.source_id, {})
            self._log.error("ingest.failed", source_id=source.source_id)
            raise

    def _ingest(
        self,
        scope: TenantScope,
        request: IngestInput,
        sha: str,
        collection_id: str,
        language: str,
        source_id: str,
    ) -> IngestOutput:
        file = self._files.read(scope, source_id)
        if hashlib.sha256(file.content).hexdigest() != sha:
            raise InputInvalid("source file does not match its registered hash")
        pages = extract_pages(file.content, file.media_type)
        checker = PageQualityChecker(self._cfg.min_page_chars, self._cfg.max_nonprintable_ratio)
        usable = [(p.number, p.text) for p in pages if not checker.needs_ocr(p)]
        needs_ocr = len(pages) - len(usable)
        if needs_ocr:
            self._log.warning("ingest.page_needs_ocr", source_id=source_id, pages=needs_ocr)
        sections, unresolved = map_structure(usable)
        rows: list[ChunkRow] = []
        for section in sections:
            for piece in split_text(
                section.text, self._cfg.chunk_target_chars, self._cfg.chunk_overlap_chars
            ):
                rows.append(
                    ChunkRow(
                        chunk_id=new_id(Prefix.KNOWLEDGE_CHUNK),
                        org_id=scope.org_id,
                        channel_id=scope.channel_id,
                        source_id=source_id,
                        collection_id=collection_id,
                        ingest_version=request.ingest_version,
                        chunk_no=len(rows) + 1,
                        chapter=section.chapter,
                        section=None,
                        page_from=section.page,
                        page_to=section.page,
                        language=language,
                        body=piece,
                        body_sha256=hashlib.sha256(piece.encode()).hexdigest(),
                        extraction_method=ExtractionMethod.TEXT_LAYER,
                        token_count=len(piece.split()),
                    )
                )
        if not rows:
            raise InputInvalid("no extractable text in the source")
        write = self._lib.insert_chunks(scope, rows)
        sample = qa_sample(
            [r.chunk_no for r in rows],
            self._cfg.qa_sample_size,
            self._cfg.qa_seed + uuid.UUID(source_id.split("_", 1)[1]).int % 10_000,
        )
        self._lib.set_source_status(
            scope, source_id, KnowledgeSourceStatus.INDEXED, request.ingest_version
        )
        self._audit.record(
            "knowledge.ingest_completed",
            "knowledge_source",
            source_id,
            {"chunks": write.written, "pages": len(pages), "needs_ocr": needs_ocr},
        )
        self._log.info("ingest.step_done", source_id=source_id, chunks=write.written)
        return IngestOutput(
            source_id=source_id,
            ingest_version=request.ingest_version,
            source_status=IngestSourceStatus.INDEXED,
            chunks_written=write.written,
            pages_total=len(pages),
            pages_needs_ocr=needs_ocr,
            qa_sample_size=len(sample),
            unresolved_headings=unresolved,
        )
