# Trading Knowledge Library — Ingestion Plan (generic)

| Field | Value |
|---|---|
| Status | Draft (documentation). Software: **Planned**. |
| Owner | Agent 04 Research & Knowledge (directive §1B.2a). Consumers: Agent 03 (topic tree), 05 (script), 06 (verification), S2 (uniqueness). |
| Basis | Directive §1B.2a, rule 9 (tenant isolation), §3.3 Memory. Owner note 2026-11-18: the book collection is **not** in `atp-private` or `trade-data`; the location will be provided. |
| Scope | Generic for any tenant. First instance: platform owner → trading-education channel. |

> **Fact for the owner (audit Part B.2):** `trade-data/research/books/` does contain 13 PDF, 1 EPUB and 4 PPTX files (+ extracted page images). Per your note, these are **not** treated as the library until you say otherwise (question K6 below).

## 1. Principles
1. **Source is read-only.** The ingestion pipeline copies sources into the factory's private storage and never modifies, moves or re-commits the original location.
2. **Nothing in git.** Book files, extracted text, chunks and indexes live only under the factory's private storage, e.g. `/opt/amw-media-factory/storage/<org_id>/knowledge/`. This repo is public, and `.gitignore` blocks index files.
3. **Text only.** Figures, diagrams, scanned page images and covers are never stored for display and never shown in a video. Page images are used only as OCR input and then discarded.
4. **Concepts, not expression** (§1B.2a). Retrieval supplies concepts plus citations. Scripts teach in original words, with original examples and our own code-rendered charts.
5. **Every chunk is citable**: book title, author, edition, chapter, page range, language, source file hash.
6. **Isolated per tenant and per collection.** Every record carries `org_id` and a `collection_id`. The owner's private method ("our method") is a separate restricted collection: a topic is used only after the owner releases it (S7 approval).

## 2. Pipeline (a batch job; runs in the night window)

| Step | What happens | Deterministic / LLM | Output |
|---|---|---|---|
| 1 Intake | Owner provides a manifest (§4); each source is registered with its licence/ownership record | Deterministic | `knowledge_sources` row + licence entry |
| 2 Copy & hash | Copy into private storage; SHA-256; duplicate detection | Deterministic | stored file, hash |
| 3 Format detect | PDF with text layer / scanned PDF / EPUB / PPTX / DOCX / Markdown | Deterministic | format flag |
| 4 Extract | Text layer extraction. OCR only for scanned pages; the OCR engine is chosen in an ADR, and Devanagari support is needed if Marathi sources exist | Deterministic | page-tagged text |
| 5 Structure | Detect title, chapters and headings, and map pages to chapters | Deterministic first; LLM only to resolve unclear headings | chapter map |
| 6 Chunk | Split by section with small overlap. Target size: ESTIMATE, tuned in the pilot | Deterministic | chunks with citation metadata |
| 7 Index | Keyword index first (PostgreSQL full-text search). Embeddings are optional, decided in an ADR by measured retrieval quality vs cost | Deterministic (+ embedding API if chosen) | searchable index |
| 8 QA sample | Random sample of chunks checked for extraction errors and correct citations; failures re-queued | Deterministic + human spot check | QA record |
| 9 Topic tree | Agent 03 maps concepts → sub-concepts → common mistakes → psychology, with a pointer to the matching course chapter | LLM proposal, human approval | topic tree |

## 3. Guards at use time
- **Citation required:** every concept in a script cites its chunk(s) in the job record. A concept with no source in the library or in a verified external reference is flagged, never invented.
- **Uniqueness gate (S2, blocking):** each script is compared with the cited chunks for close paraphrase (n-gram/similarity threshold in config, calibrated in the pilot).
- **Quotes:** short attributed quotes only when essential and approved by the human reviewer. Books are credited as "further reading" in the description.
- **No chapter-structure copying:** the series plan comes from the topic tree, not from a book's table of contents.

## 4. What I need from the owner (exact list)

| # | Need | Why | Needed by |
|---|---|---|---|
| K1 | **Location** of the book collection and the read-only access method (private repo name, Drive folder, or a path on a machine) | Inventory and ingestion design | Before the Agent 04 blueprint is finalised |
| K2 | **Manifest per book**: title, author, edition/year, language, format, and how acquired (purchased / licensed / free / other) | Citation metadata, copyright posture | Before ingestion (build phase) |
| K3 | Which books are **in scope for channel 1** (and any to exclude) | Library scope | Before the topic tree |
| K4 | Whether any source is **scanned** (no text layer) or in **Marathi/Hindi** | OCR need and engine choice | Before the ADR |
| K5 | Which **"our method"** topics may appear in public videos (default: none until released per topic; Q26) | Protect the private method | Before the content plan |
| K6 | Should the 14 documents found in `trade-data/research/books/` be part of the library, or excluded? | Avoid ingesting the wrong set | Before inventory |
| K7 | Confirm the **course glossary** (the glossary blocks in the course's chapter content) is the shared Marathi terminology source (§1B.2a) | One glossary for course and channel | Before the Agent 05 blueprint |
| K8 | Approval to store copies of the books in the factory's private storage on the server (encrypted at rest, not in git) | Storage and DR design | Build phase |
