# Trading Knowledge Library — Ingestion Plan (generic)

| Field | Value |
|---|---|
| Status | Draft (documentation). Software: **Planned**. |
| Owner | Agent 04 Research & Knowledge (directive §1B.2a). Consumers: Agent 03 (topic tree), 05 (script), 06 (verification), S2 (uniqueness). |
| Basis | Directive §1B.2a, rule 9 (tenant isolation), §3.3 Memory. Owner answer to K1 (2026-11-18): the books are in three private locations, listed in §5. |
| Scope | Generic for any tenant. First instance: platform owner → trading-education channel. |

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

## 5. Owner answer to K1 (2026-11-18): where the books are
All three locations are **private repositories**, read-only for the factory. Counts below come from directory listings on 2026-11-18 (file names and sizes only; no file content was read). Titles are deliberately not listed here, because this repo is public.

| # | Proposed collection id | Location | What the listing shows |
|---|---|---|---|
| 1 | `pd_books` | `trade-data`, branch `ccr-7e74426e-fiv6z2` (**not merged to main**), folder `books/public-domain`. The owner states the origin as "trade-data M85 @ 6dd8bf4"; commit `6dd8bf4` was checked and contains this folder. | 21 PDF files + 1 plain-text file (file names date the books 1841–1930), a README and a `_proof` folder (title-page images and an index file). 18 PDFs have book-like sizes (0.9–49 MB). **3 PDFs are only 133 bytes each.** |
| 2 | `owner_strategies_notes` | Same branch: `books/strategies` (17 per-book strategy files, README, template) and `books/notes` (20 per-book notes, a synthesis file, template). The ATP site's runtime copy of the 17 strategy files is in `atp-private`, `atp_private/chart_reader/strategies`; its listing matches the branch copy in names and sizes. | Owner-derived summaries of the books in collection 1. |
| 3 | `owner_books` | `trade-data`, `main`, folder `research/books` (the owner-supplied books; the owner counts 30 files and keeps a README listing them) | My earlier file-tree count for this folder: 13 PDF, 1 EPUB, 4 PPTX, plus extracted page images. To be reconciled with the owner's list. |

### 5.1 Findings (what the listings show, and what they do not)
1. **Three 133-byte PDFs** are too small to be books. They may be pointer or placeholder files; this is **not verified**. The real files are needed.
2. **Count mismatch:** the owner said 23 PDFs; the listing shows 21 PDFs + 1 text file in `books/public-domain`.
3. **The branch is not on `main`.** The factory must read a pinned commit (`6dd8bf4`) or the owner merges the branch. A branch name can move; a commit hash cannot.
4. **Public-domain status is the owner's statement, based on publication dates in the file names.** Copyright terms differ by country, and editions, translations and scans can carry their own rights. ⚖ Verify per book and edition.
5. **Scan quality is unknown.** Old scanned books usually need OCR (ADR-013 criteria). One book has a plain-text edition, which needs no OCR.
6. **Strategy files** hold rule-style summaries. In videos they can be taught only as concepts on **historical** charts (FIN-R2, FIN-R3, FIN-R13). The 17-file copy in `atp-private` sits in the owner's private method area, whose repository rules forbid copying it into any public place. **Default: the factory reads the `trade-data` branch copy (collection 2), never the `atp-private` runtime copy.** Per-topic release by the owner still applies (Q26).

### 5.2 Design consequences
- Three collections per tenant, each with its own `collection_id`: `pd_books`, `owner_strategies_notes` (restricted), `owner_books`. Every chunk keeps its citation back to the source book, chapter and page.
- Collection 2 is a **secondary index**: a concept found there must still cite the source chunk in collection 1 or 3 (§3 guard "citation required").
- **3A needs only a subset.** The owner gives the topic directly (D1), so Agent 04 ingests only the books that the first golden topics need; the full library can follow later.

### 5.3 Updated owner needs
| # | Status | Need |
|---|---|---|
| K1 | **Answered** | Location (this section). |
| K6 | **Answered** | Yes: `research/books` is collection 3. |
| K2 | Open | Manifest per book: edition/year, language, how acquired; for collection 3, whether each copy is owned or licensed. For collection 1, which edition/scan source. |
| K3 | Open (default: all three collections for channel 1) | Which books are in scope or excluded. |
| K4 | Partly answered | Old scans are likely (not verified); English text, so no Devanagari OCR is needed for these sources. |
| K5, K7, K8 | Open | As in §4. |
| K9 | New | The 3 files of 133 bytes and the missing 2 of the 23 PDFs. |
| K10 | New | Merge the branch into `main`, or confirm that commit `6dd8bf4` stays reachable. |
| K11 | New ⚖ | Per-book public-domain verification (by the owner's lawyer). |
| K12 | New | May verified public-domain books be quoted at greater length (always attributed)? |

### 5.4 Provisional defaults until the owner answers (owner rule A.9)
- **Q34:** collections as in §5.2.
- **Q35 / Q36:** the concept-only rule of §1 and §3 applies to **all** collections, public-domain or not. A short attributed quote still needs the human reviewer's approval. Reason: public-domain status is unverified (finding 4), and the rule keeps every video original.
- **Q37:** the 3 stub PDFs are excluded until real files are provided.
