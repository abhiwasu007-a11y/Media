# Deterministic golden dataset — Agent 05 non-LLM core (`agent_05.script_draft` and `agent_05.shorts_adaptation`)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 05 Scriptwriter |
| Depends on | blueprint `agents/agent_05_scriptwriter.md` §6, §9, §10, §16, §19; 07 §2; 08 §8; 18 §3; 27 §6.1 |
| Why this dataset exists | Agent 05's decisions that matter most for safety, isolation and reproducibility (hook selection, speech budgets, concept mapping, scanners, cadence, assembly, whole-script checks, revision routing, refusal mapping, tenant guard, flow caps, near-copy) are **deterministic**, so they have their own golden dataset in addition to the three LLM-step datasets. No model is called; the LLM adapter is a scripted fake. |
| MVP scope | **3A** (all cases) · Tier 0; `TN-*` are part of the Tier 1 cross-tenant suite already at Tier 0 |
| Files | `cases.jsonl` (114 cases; no judge) |

## 1. Case format
Function-level dataset (27 §6.1, CCR-024): folder `deterministic_core/`, no prompt, no judge, `judge_min` omitted. Case fields: `case_id`, `category` (`eval_case_category`), `description`, `function` (the unit under test: a class name of blueprint §9), `input` (the argument object of that unit), `expected` (the exact deterministic result), `notes`. **Case-ID prefixes** are component prefixes `<COMP>-NN` (declared in §2: HS, SB, BM, FP, CD, AS, SV, RV, RM, TN, SC, NC), as 27 §6.1 allows for deterministic datasets; the answer-key mapping is stated in §3a. Values such as speech rates, thresholds and the scanner lexicon `lex_test_v1` are **test values**, not product defaults: the product lexicons and thresholds are **REQUIRES REVIEW (Phase 1)** (13 §5, §8) and are not part of this dataset. `lex_test_v1` is a small fixed word list that makes the engine logic testable.

## 2. Coverage
| Prefix | Component | Cases |
|---|---|---|
| HS | `HookSelector` (totals, tie rules, disqualification, repair, schema failure) | 7 |
| SB | `SpeechBudgeter` (hook budget, scene budget, null without a rate) | 5 |
| BM | `ConceptBriefMapper` (ID mapping, citations, summary, method release status, cross-org approval) | 7 |
| FP | `FinPrefilter`, `ForbiddenTokenScanner`, `ForwardLookingScanner`, `LanguageChecker` (answer-key texts, tokens, FIN-R13, bracketing, script) | 17 |
| CD | `CadenceChecker` (change beats, pauses, no rate, held chart, interrupt) | 9 |
| AS | `Segmenter`, `ScriptAssembler`, `ChartIdAllocator`, `DurationEstimator`, `ChapterBuilder`, `DisclaimerSlotter` | 17 |
| SV | `ScriptValidator` (hook window, coverage, citations, promise delivery, tags, hook options, chapters; SKIPPED checks carry `blocking: false`) | 13 |
| RV | `FeedbackRouter` (long form sections, plan re-run, Shorts cut) | 7 |
| RM | `RefusalMapper` (27 §4.3) | 6 |
| TN | `TenantGuard`, `HookHistoryMemory`, log redaction, prompt prefix | 10 |
| SC | `ScriptDraftStep` flow: repair, caps, resume, replay, drain, budget, provider errors, persist retry | 12 |
| NC | `NearCopyGuard` (test thresholds `ngram_n = 4`, `max_overlap_ratio = 0.5`, `max_common_run_chars = 60`) | 4 |

## 3. Assertions
Each case passes when the component's result equals `expected` on every listed key (extra keys in the result are allowed). Error codes are exactly the 07 §2 codes. `security_event: true` requires a log event `security.cross_tenant_ref` with the caller's `org_id` and no content; `security_event: false` requires that none is emitted (no existence oracle). `canary_in_logs: false` requires that the canary string appears in no log line, metric label, error message or audit row on any listed path.

## 3a. Answer key
The directive §1B.2 answer-key cases FP-01…FP-04 (category `ANSWER_KEY`) are the deterministic side of the answer key; the LLM-step datasets carry the other side (27 §6.1: each dataset README states which answer-key cases apply).

## 4. Thresholds
All cases must pass (114 of 114); any failure blocks the PR (unit level, free, run on every CI run). `TN-01…TN-10` also belong to the `security` / `tenancy` marker suites (08 §8.2).

## 5. Open points
- Grapheme unit for `speech_chars` (Unicode extended grapheme clusters excluding whitespace) is **REQUIRES REVIEW (Phase 1)** until a measured rate exists; no case depends on a Devanagari conjunct count.
- `Segmenter` boundary rule (terminator followed by whitespace and a letter) does not handle every abbreviation (for example "e.g."); known limitation, to be measured on the golden samples.
- `TN-03` encodes "not found" for another org's channel (no existence oracle); a URI of another org is visible in the string and is `CROSS_TENANT_REF`.
