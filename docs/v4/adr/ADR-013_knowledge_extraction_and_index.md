# ADR-013 — Knowledge library: text extraction, OCR and retrieval index

| Field | Value |
|---|---|
| Status | **Proposed** (documentation). Software: **Planned**. |
| Date | 2026-11-18 |
| Directive | §1B.2a (Trading Knowledge Library), §3.3 Memory (isolation, retrieval rules), §3.2a (simplest option wins), rule 9 (tenant isolation), public-repo rule |
| Plan | `KNOWLEDGE_LIBRARY_PLAN.md` §1 principles, §2 steps 4 (Extract) and 7 (Index), §4 owner items K1–K8; plan Q19, Q25, Q26 |
| Owner decisions | D1 (Agent 04 is in 3A; topic is owner-given), D2 |
| Contracts used | 04 §5.10 (`knowledge_sources`, `knowledge_chunks`, `memory_items`), §5.11 (`citations`); GLOSSARY §6 (`knowledge_source_kind`, `knowledge_source_status`, `source_ownership`, `capability`); 24 §3.2 (`agent_04.research_pack`); 07 §2 |
| Research | IN-08 (copyright posture); no research entry exists yet for OCR engines, PostgreSQL text-search language support or embedding providers |
| MVP scope | **3A** (text-layer extraction, PostgreSQL full-text index, citations into `agent_04.research_pack`) · **3B** (retrieval-quality measurement on the golden-sample topics; OCR only if K4 says scanned/Devanagari sources exist) · **3C** (embeddings if measured to be needed, client libraries) |
| Enterprise tier | Tier 0: one owner library per channel. Tier 1+: `CLIENT_DOCUMENT` sources, same isolation (`org_id` + `channel_id` on every row). |

## 1. Context
- §1B.2a: ingest the owner's collection into "a private, channel-isolated index (chunk → embed or keyword index → store book title, author, chapter/page for every chunk)"; index and extracted text stay out of git, in factory private storage; every script concept cites its chunk(s); concepts without a source are flagged, not invented.
- Copyright posture (IN-08, SECONDARY-only): fair dealing in India is narrow and has no general education head for public online video; hence concepts only, in original words, no reproduction or close paraphrase (plan §1.4, §3).
- Plan §1.3: figures, scanned page images and covers are never stored for display; page images are OCR input only and then discarded.
- Plan step 4: text-layer extraction; OCR only for scanned pages; the OCR engine is chosen in an ADR; Devanagari support is needed if Marathi sources exist. Step 7: keyword index first (PostgreSQL full-text search); embeddings optional, decided by measured retrieval quality vs cost.
- Known facts: the location of the collection is pending (K1); whether any source is scanned or in Marathi/Hindi is pending (K4); ownership/licence status is pending (Q25, `source_ownership = UNKNOWN` blocks ingestion). Plan Q19: no text extraction before the build.
- `knowledge_chunks.search_tsv` exists with a GIN index; its per-language text-search configuration is REQUIRES REVIEW, and `embedding_ref` store choice was deferred to "an ADR on vector store" (04 §5.10) — this ADR.
- No task type exists for ingestion: 24 §3.2 has only `agent_04.research_pack`.

## 2. Decision
1. **Ingestion is a deterministic batch job owned by Agent 04**, run as task type `agent_04.knowledge_ingest` **(pending CCR)**, one task per source, in the night window on the VPS or in the development environment. It never writes to the source location (plan §1.1). It starts only when the source row has `source_ownership ≠ UNKNOWN` (04 §5.10) and the owner has given K1/K2/K8.
2. **Extraction order (per page):**
   1. Text layer first (PDF text layer, EPUB/DOCX/PPTX/Markdown text). Deterministic.
   2. A page is routed to OCR only when its text layer is missing or fails a deterministic quality check (e.g. characters per page below a config threshold, or a high share of replacement/unmapped glyphs). Thresholds are config, calibrated on the 3B QA sample. Legacy (non-Unicode) Devanagari font encodings in a text layer are treated as a failed text layer.
   3. Every chunk records how its text was obtained and the OCR confidence **(pending CCR: `knowledge_chunks` extraction provenance fields)**, so QA (plan step 8) can sample OCR chunks separately and citations can show reduced confidence.
   4. Page images used for OCR are deleted after the page is processed (plan §1.3); only text and citation metadata are kept.
3. **OCR engine: not chosen now; chosen by these criteria once K4 shows OCR is needed.** No OCR engine has a research-log entry, so no candidate is named here as a fact. Criteria, in priority order:

   | # | Criterion | How it is measured |
   |---|---|---|
   | 1 | Devanagari (Marathi, Hindi) and English recognition, including mixed-script pages (English terms in brackets, §1B.2a) | character error rate on an owner-approved sample of the actual sources, scored against hand-corrected text |
   | 2 | Data stays private: runs locally, or a cloud API whose terms allow confidential document processing without retention/training | official terms recorded in RESEARCH_LOG |
   | 3 | Page-level confidence output and layout (reading order, columns, headings) for step 5 Structure | feature present / absent on the test set |
   | 4 | Resource footprint inside the factory's cgroup caps (INF-03/04) on the shared VPS, or runs on the movable worker | MEASURED CPU/RAM per page |
   | 5 | Licence permitting commercial use; cost per page | official licence/pricing page in RESEARCH_LOG |
   **REQUIRES REVIEW (Phase 1): OCR engine research entries (Devanagari support, licence, footprint) — needed only if K4 = scanned or Marathi/Hindi sources.**
4. **Index: PostgreSQL full-text search first.** `knowledge_chunks.search_tsv` (GIN) with a text-search configuration per `language`. Every query filters `org_id` (RLS) **and** `channel_id` (04 §5.10); restricted "our method" sources are retrievable only when `release_approval_id` is set (Q26, `FIN-R12`). No new service is added in 3A.
   - English sources: a stemming configuration. Marathi/Hindi sources: **REQUIRES REVIEW (Phase 1): which PostgreSQL text-search configuration handles Devanagari (a `simple` configuration without stemming is the fallback until verified; no research entry yet).**
5. **Embeddings later, only if measured to be needed.** Decision rule (3B):
   - Build a retrieval test set per channel: owner-given topics (the 3B golden-sample topics and others) with the chunks a human reviewer marks as relevant.
   - Measure FTS recall@k and precision@k (k in config) and the rate of "concept not found although present" flags from Agent 04/06.
   - If FTS meets the thresholds (config, set with the owner after the first measurement), embeddings are **not** added. If it fails, an amendment to this ADR evaluates embeddings (provider or local model, vector store — e.g. a PostgreSQL extension vs a separate store), with cost per 1K chunks and measured gain, all facts recorded in the research log first. `knowledge_chunks.embedding_ref` stays NULL until then.
6. **Chunking** by section with small overlap (plan step 6); chunk size ESTIMATE, tuned in 3B. `token_count` stored per chunk (feeds ADR-007 Devanagari measurement).
7. **Use at retrieval time** (`agent_04.research_pack`): results carry chunk IDs → `citations`; chunk `body` is confidential, never logged, never sent to another tenant's prompts (04 §5.10); the uniqueness gate (S2) compares scripts against cited chunks (plan §3).
8. **Failures**: unreadable/corrupt file → `PERMANENT.INPUT_INVALID`, source `FAILED`; storage outage → `INFRASTRUCTURE.STORAGE_UNAVAILABLE` (07 §2). A failed page is re-queued by the QA step, never silently dropped.
9. **Worker capability**: extraction/OCR runs on a worker declaring capability `doc_extract` **(pending CCR: new `capability` value)**.

## 3. Options considered (with evidence)
| Option | Evidence | Verdict |
|---|---|---|
| OCR every page | Plan step 4 (OCR only for scanned pages); text layers are exact where present | Rejected |
| **Text layer first, OCR fallback per page** | Plan step 4; plan §1.3 | **Chosen** |
| Pick an OCR engine now | No research entry; K4 unknown | Deferred to measured criteria |
| **PostgreSQL FTS first** | Plan step 7; `search_tsv` + GIN already in 04 §5.10; §3.2a simplest option; no extra service on the shared VPS | **Chosen for 3A** |
| Embeddings + vector store from day one | §1B.2a allows "embed or keyword"; no measured need; adds cost and a component | Rejected until measured (3B) |
| Hybrid (FTS + embeddings) | Same as above | Candidate in the amendment if FTS fails |

## 4. Consequences
- Positive: no new infrastructure for 3A; isolation reuses RLS + `channel_id`; extraction provenance makes OCR errors visible in citations.
- Negative: FTS has no semantic matching; synonyms and Marathi/English mixed terms may be missed — exactly what the 3B retrieval test measures. The shared glossary (K7) can feed a synonym dictionary later.
- Ingestion cannot start until K1, K2, K4, K8 and Q25 are answered; until then `agent_04.research_pack` in 3A can draw on owner-given material and verified external references only.
- REQUIRES REVIEW (Phase 1): PostgreSQL text-search configuration for Marathi/Hindi; OCR engine facts; retrieval thresholds (owner, after first measurement).

## 5. Revisit trigger
- K4 answered with scanned or Devanagari sources (choose the OCR engine by §2.3).
- 3B retrieval test fails the thresholds (embedding amendment).
- Library size or query latency exceeds config limits on the shared VPS.
- First client library (Tier 1) with document types not covered here.

## 6. Research IDs cited
IN-08; INF-03, INF-04 (resource caps referenced for criterion 4). Missing research: OCR engines, PostgreSQL Devanagari text search, embedding providers.
