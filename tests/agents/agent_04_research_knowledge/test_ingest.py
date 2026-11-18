"""Ingestion of invented synthetic documents only (U-08, I-03, F-09, AC-14)."""
# ruff: noqa: E501, PT018

import hashlib
from dataclasses import replace

import pytest

from agent_04_research_knowledge.errors import InputInvalid
from agent_04_research_knowledge.ingest.chunker import split_text
from agent_04_research_knowledge.ingest.extract import (
    Page,
    PageQualityChecker,
    detect_format,
    extract_pages,
)
from agent_04_research_knowledge.ingest.pipeline import IngestionPipeline, SourceFile
from agent_04_research_knowledge.ingest.structure import map_structure, qa_sample
from agent_04_research_knowledge.library.models import SearchRequest, TenantScope
from agent_04_research_knowledge.models.ingest import IngestInput
from agent_04_research_knowledge.observability import EventLogger, LogContext
from amw_core.enums import KnowledgeSourceStatus, SourceOwnership
from tests.agents.agent_04_research_knowledge.conftest import build_world, make_run

pytestmark = pytest.mark.unit

DOC = (
    "Chapter 1 Basics\n\nAn order placed in advance limits a loss. Traders review it often.\n\n"
    "\fChapter 2 Sizing\n\nPosition sizing converts risk into a quantity. The stop distance sets the size.\n\n"
    "SOME UNCLEAR HEADING\n\nAnother paragraph about quantity and risk.\n"
    "\f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
)


class Files:
    def __init__(self, content: bytes, media: str = "text/plain") -> None:
        self.file = SourceFile(content, media)

    def read(self, scope: TenantScope, source_id: str) -> SourceFile:
        return self.file


def pipeline(w, content: bytes = DOC.encode(), media: str = "text/plain", **over):  # type: ignore[no-untyped-def]
    src_id = w.add_source(
        "general_trading",
        content_sha256=hashlib.sha256(content).hexdigest(),
        status=KnowledgeSourceStatus.REGISTERED,
        ingest_version=0,
        **over,
    )
    run = make_run(w)
    pipe = IngestionPipeline(
        w.library,
        Files(content, media),
        w.settings.ingest,
        run.audit,
        EventLogger(LogContext(w.org)),
    )
    return pipe, src_id, run


def test_chunker_respects_size_overlap_and_boundaries() -> None:
    text = "One sentence here. Another sentence follows. A third one ends the para.\n\nNew paragraph starts."
    pieces = split_text(text, 45, 10)
    assert pieces and all(len(p) <= 45 + 10 + 1 for p in pieces)
    assert pieces[1].startswith(pieces[0][-10:].strip()[:5]) or len(pieces) == 1
    assert split_text("x" * 100, 30, 0) == ["x" * 30, "x" * 30, "x" * 30, "x" * 10]
    assert split_text("   \n\n  ", 30, 5) == []
    with pytest.raises(ValueError, match="overlap"):
        split_text("a", 10, 10)


def test_extract_detect_and_quality() -> None:
    assert detect_format("text/plain; charset=utf-8") == "text"
    for bad in ("application/pdf", "application/epub+zip"):
        with pytest.raises(InputInvalid):
            detect_format(bad)
    pages = extract_pages(b"a\fb", "text/plain")
    assert [p.number for p in pages] == [1, 2] and repr(pages[0]) == "Page(1)"
    assert extract_pages(b"<p>x</p><script>y</script>", "text/html")[0].text == "x"
    with pytest.raises(InputInvalid):
        extract_pages(b"\xff\xfe", "text/plain")
    qc = PageQualityChecker(20, 0.2)
    assert (
        qc.needs_ocr(Page(1, "short"))
        and qc.needs_ocr(Page(1, "\x00" * 30))
        and qc.needs_ocr(Page(1, "ab�" * 30))
    )
    assert not qc.needs_ocr(Page(1, "This page has plenty of readable text in it."))


def test_map_structure_and_qa_sample() -> None:
    sections, unresolved = map_structure(
        [(1, "Chapter 1 Basics\ntext one"), (2, "# Part Two\nSOME HEADING\ntext two")]
    )
    assert [(s.chapter, s.page) for s in sections] == [
        ("Chapter 1 Basics", 1),
        ("Part Two", 2),
    ] and unresolved == 1
    assert qa_sample(list(range(10)), 3, 1) == qa_sample(list(range(10)), 3, 1)
    assert len(qa_sample([1, 2], 5, 1)) == 2


def test_ingest_then_retrieve_with_chapter_and_page() -> None:
    w = build_world()
    pipe, sid, run = pipeline(w)
    out = pipe.run(run.scope, IngestInput(source_id=sid, ingest_version=1, force_reextract=False))
    assert out.source_status.value == "INDEXED" and out.chunks_written >= 2
    assert out.pages_total == 3 and out.pages_needs_ocr == 1 and out.unresolved_headings == 1
    assert 1 <= out.qa_sample_size <= w.settings.ingest.qa_sample_size
    assert w.library.get_source(run.scope, sid).status is KnowledgeSourceStatus.INDEXED  # type: ignore[union-attr]
    hits = w.library.search(
        run.scope,
        SearchRequest(
            "position sizing", "en", frozenset(w.collections.values()), 5, frozenset({sid})
        ),
    )
    assert hits and hits[0].chapter == "Chapter 2 Sizing" and hits[0].page_from == 2
    assert {a[0] for a in run.audit.rows} == {"knowledge.ingest_completed"}
    # duplicate run: a no-op that writes nothing
    again = pipe.run(run.scope, IngestInput(source_id=sid, ingest_version=1, force_reextract=False))
    assert again.chunks_written == 0 and again.source_status.value == "INDEXED"
    assert w.library.chunk_count(run.scope, sid, 1) == out.chunks_written
    # a re-ingest writes a new ingest_version and never touches the old rows
    third = pipe.run(run.scope, IngestInput(source_id=sid, ingest_version=2, force_reextract=True))
    assert (
        third.chunks_written == out.chunks_written
        and w.library.chunk_count(run.scope, sid, 1) == out.chunks_written
    )
    assert all(
        h.chunk_id
        for h in w.library.search(
            run.scope,
            SearchRequest(
                "position sizing", "en", frozenset(w.collections.values()), 9, frozenset({sid})
            ),
        )
    )
    # a forced replay of the same version inserts nothing new (idempotent chunk key)
    forced = pipe.run(run.scope, IngestInput(source_id=sid, ingest_version=2, force_reextract=True))
    assert forced.chunks_written == 0


def test_ingest_failures_mark_source_failed_not_dropped() -> None:
    w = build_world()
    pipe, sid, run = pipeline(w, b"\xff\xfe\x00bad")
    with pytest.raises(InputInvalid):
        pipe.run(run.scope, IngestInput(source_id=sid, ingest_version=1, force_reextract=False))
    assert w.library.get_source(run.scope, sid).status is KnowledgeSourceStatus.FAILED  # type: ignore[union-attr]
    assert ("knowledge.ingest_failed", "knowledge_source", sid, {}) in run.audit.rows
    # unsupported format, hash mismatch, no text, unknown source, unknown ownership
    w2 = build_world()
    pipe2, sid2, run2 = pipeline(w2, b"%PDF-1.4", "application/pdf")
    with pytest.raises(InputInvalid):
        pipe2.run(run2.scope, IngestInput(source_id=sid2, ingest_version=1, force_reextract=False))
    w3 = build_world()
    pipe3, sid3, run3 = pipeline(w3)
    w3.library._sources[(w3.org, sid3)] = replace(
        w3.library._sources[(w3.org, sid3)], content_sha256="00" * 32
    )
    with pytest.raises(InputInvalid, match="hash"):
        pipe3.run(run3.scope, IngestInput(source_id=sid3, ingest_version=1, force_reextract=False))
    w4 = build_world()
    pipe4, sid4, run4 = pipeline(w4, b"\x00" * 50)
    with pytest.raises(InputInvalid, match="no extractable"):
        pipe4.run(run4.scope, IngestInput(source_id=sid4, ingest_version=1, force_reextract=False))
    with pytest.raises(InputInvalid):
        pipe4.run(
            run4.scope,
            IngestInput(
                source_id="ksr_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e9f",
                ingest_version=1,
                force_reextract=False,
            ),
        )
    w5 = build_world()
    pipe5, sid5, run5 = pipeline(w5, ownership=SourceOwnership.UNKNOWN)
    with pytest.raises(InputInvalid, match="ownership unknown"):
        pipe5.run(run5.scope, IngestInput(source_id=sid5, ingest_version=1, force_reextract=False))
    assert w5.library.get_source(run5.scope, sid5).status is KnowledgeSourceStatus.REGISTERED  # type: ignore[union-attr]


def test_ingest_other_tenant_cannot_ingest_or_see_source() -> None:
    a, b = build_world(), build_world()
    pipe, sid, _ = pipeline(a)
    with pytest.raises(InputInvalid):
        pipe.run(
            TenantScope(b.org, b.channel),
            IngestInput(source_id=sid, ingest_version=1, force_reextract=False),
        )
