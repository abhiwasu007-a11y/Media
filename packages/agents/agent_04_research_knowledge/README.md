# agent_04_research_knowledge: status

Agent 04 Research & Knowledge (blueprint `docs/v4/agents/agent_04_research_knowledge.md`, ticket 3A-04).
Status: built against fakes and one real PostgreSQL scratch database. Nothing runs on a server.

## What exists
- `agent_04.research_pack` (S0 to S7, checkpoints, replay), topic gate `a04.topic_allowed`, citations.
- Retrieval behind the `KnowledgeLibrary` Protocol: in-memory implementation and `library/sql.py`.
- Text-layer ingestion (plain text, Markdown, HTML only).

## What is NOT done
- Real model runs, judge prompts and judge scores (the eval fixtures are synthesised from the cases).
- PDF, EPUB and DOCX extraction (needs a library decision); OCR; glossary terminology.
- `library/sql.py` is tested against a scratch PostgreSQL schema written from 04 section 5.10 and
  5.16 (`tests/.../test_sql_integration.py`, marker `integration`, needs `AMW_TEST_DATABASE_URL`);
  it still has to be run against the real L1a migrations when they merge.
- Without a document reader the released-chunk list falls back to the set-once pointer
  `knowledge_chunks.release_approval_id`; the authoritative list is the `subject_ref` document
  (CCR-070) and is used when a `SubjectDocuments` reader is injected.

## Copy guard: thresholds are PROPOSALS (REQUIRES REVIEW: owner and counsel, H-6)
There is no default in code; `CopyGuardSettings` must be supplied. The values below are the ones
the tests use. They are proposals only and must be set on measured samples of the owner's real
sources before the first real library run.

| Key (`research.copy_guard.*`) | Proposal | Meaning |
|---|---|---|
| `max_verbatim_words` | 8 | a run of this many consecutive copied words fails the note |
| `ngram_n` | 5 | shingle size of the containment measure |
| `max_containment_ratio` | 0.3 | share of the note's n-grams found in a passage |
| `max_lcs_ratio` | 0.65 | windowed longest-common-subsequence share (tolerates filler and changed words) |
| `fuzzy_edits` | 1 | edits tolerated inside one aligned segment |
| `max_fuzzy_words` | 12 | matched words in one such segment that fail the note |
| `max_pack_source_coverage` | 0.5 | share of one passage that all notes of the pack together may rebuild |

Rules: texts are compared after the shared `amw_core.text_normalise` (CCR-105; invisible and
combining characters, look-alikes and Devanagari variants folded); the
cross-language skip depends only on the actual scripts of both texts, never on language tags; each
note is checked against every passage of the job's retrieval set; notes must be in Latin script.
Known limit: a note written in transliteration (Latin letters) of a Devanagari passage is not
detected (scripts differ, the pair is skipped and the WARN `a04.copy_guard_cross_language` is raised).
