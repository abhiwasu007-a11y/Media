# Eval set — `agent_07.voice_synthesis` (deterministic; no LLM step, no prompt)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 07 Voice Production |
| MVP | 3A (all cases except VS-41, VS-42) · 3B (VS-41 voice sample, VS-42 clip reuse) · Tier 0 |
| Depends on | [blueprint](../../../agents/agent_07_voice_production.md) §5–§8, §10, §18, §20; evals/README.md; 27_ENGINEERING_STANDARDS.md §6, §8; GLOSSARY_AND_IDS.md §6; 03 §9.2 |
| Directive sections covered | §3.1 row 07; §1A.3 (voice, pronunciation dictionary, pace/emotion, consent, own narration); §1C.8 (third-party use); §3.5.3 (golden dataset: this step has no LLM, so the dataset is deterministic: fixture description + expected result) |
| Files | `cases.jsonl` (44 cases), `rubric.md` (the owner's HUMAN listening rubric, not an LLM judge) |

## 1. Scope
The step under test is the whole `agent_07.voice_synthesis` executor run against a `FakeTtsAdapter` and in-memory (or test-Postgres) fixtures. No network, no paid call, no LLM. The fake adapter returns a synthetic clip whose duration is `code points of the spoken text × fake.ms_per_char` (a fixture parameter), so every timeline in `expected` is exact arithmetic. Sentence text in the fixtures is neutral teaching text; it contains no market statement and no book content.

## 2. Case coverage
| Category | Cases | What they prove |
|---|---|---|
| POSITIVE (11) | VS-01, 02, 07, 09, 11, 12, 18, 23, 39, 41, 42 | timeline arithmetic, scene pause, dictionary hit logging, longest match, style passthrough, consented clone, owner recording with marks, replay, retry after 429, voice sample, clip reuse |
| HARD_NEGATIVE (17) | VS-03, 06, 08, 10, 13, 14, 15, 16, 20, 22, 27, 28, 30, 31, 32, 33, 38 | look-alikes: a refusal that looks harmless (edited script, withdrawn consent) and a pass that looks refusable (approved review verdict, longer Latin word, Devanagari boundary, 44.1 kHz recording, PERMITTED platform licence, identical sentences) |
| EDGE (16) | VS-04, 05, 17, 19, 21, 24, 25, 26, 29, 34, 35, 36, 37, 40, 43, 44 | blocked verdict, adapter without emotion control, unaligned recording, clipping at intake, budget and breaker fail-closed, unsupported language, markup text, empty text, over-long sentence, garbage audio, resume after consent withdrawal, brand-kit binding |

## 3. Case format and `expected` object
Case file format: evals/README.md §2 (`case_id`, `category`, `description`, `input`, `expected`, `judge_min` = null, `notes`). `input` is a **fixture description** (not the Task Input itself): the harness builds the Task Input, rows, blobs and fake adapter from it.
| `input` key | Meaning |
|---|---|
| `script` | `segments[]` (`segment_id`, `text`, `pace`, `emotion`, `scene_id`), `scenes[]` (`deliberate_pause_ms`, `pronunciation_candidates`) |
| `script_gate` | `sha_matches`, Agent 06 stage `verdict`, linked `approval`, `script_ref_org` (`same` / `other`) |
| `voice` | `kind`, `status`, `languages`, `org`, `brand_kit_binds`, `licence` (`state`, `source_type`, flags, `holder` = `org` / `platform`), `consent` (`state`, `withdrawn`, `expired`, `voice_owner_is_org_owner`) |
| `dictionary` | `entries[]` (agent_07 dictionary schema §7.4), `channel_permitted`, `sha_matches`, `org` |
| `adapter` | declared `languages`, `pace_control`, `emotion_control`, `phoneme_support`, `max_chars_per_request`, `fake` (`ms_per_char`, `behaviour`) |
| `config` | `gap_ms`, `trim_keep_ms`, `price_micros_per_1k_chars` (fixture price: the PR-04 $0.08 row = 80 000 micros), `sample_max_segments` |
| `budget` | `provider_budget_row`, `reservation_micros`, `breaker` |
| `org_kind`, `human_narration`, `prior_iteration_clips`, `replay_of_completed_task`, `resume_from_checkpoint` | as named |
| `expected` key | Meaning |
|---|---|
| `status`, `error_code` | Task Output status and 07 §2 code (null on success); `state`, `wait_reason`, `retryable` where the disposition matters |
| `network_calls` | number of provider calls made (0 for every denial: the mandatory property) |
| `ledger_rows`, `ledger_amount_micros_total`, `characters_billed` | cost ledger rows and the integer micros (`characters × 80`) |
| `asset_rows`, `licence_ledger_rows`, `asset_source_type` | rows written |
| `timeline_source`, `timeline[]` | exact `start_ms` / `end_ms` per segment (null when `UNALIGNED`) |
| `hits`, `unknown_terms_min`, `spoken_text_expected` | dictionary result |
| `style[]`, `validation{}` | applied style and verdict per `check_id` |

## 4. Deterministic assertions (all cases)
| ID | Assertion |
|---|---|
| A1 | the Task Output payload validates against `agent_07.voice_synthesis.output` 1.0.0 when `status = SUCCEEDED`; `payload` is null otherwise |
| A2 | `status` and `error_code` equal `expected`; the `error_class` equals the code prefix |
| A3 | the number of adapter calls equals `network_calls` (fake adapter counter); denial cases show 0 |
| A4 | cost ledger rows and total micros equal `expected`; each row has `operation = tts.synthesize`, `unit_kind = characters`, `figure_kind = ESTIMATE` |
| A5 | `assets` and `licence_ledger` rows written equal `expected`; a replay writes none |
| A6 | `timeline[]` equals `expected` exactly; `end − start` equals the trimmed clip duration; starts are monotonic |
| A7 | every `validation{}` entry equals the verdict in the Task Output `validation_results` |
| A8 | dictionary `hits` equal `expected`; the text received by the fake adapter equals `spoken_text_expected` when given; it contains no unescaped markup characters |
| A9 | no log record, error, output or metric label contains script text, spoken text, consent person data, a provider voice reference or a secret (canary strings in the fixtures) |
| A10 | no row or blob of another tenant was read (storage and DB access log of the harness) |
| A11 | the idempotency key of each call equals the 03 §9.2 key for (`task_id`, `segment_id`, `spoken_text_sha256`, `voice_id`) |

## 5. Judge
None. Subjective voice quality is the owner's HUMAN check (rubric.md), recorded in `quality_scores` at `FINAL_VIDEO` approval; it is not part of this dataset's pass rule.

## 6. Pass thresholds (config `evals.agent_07.voice_synthesis.*`; design defaults)
| Threshold | Value |
|---|---|
| Overall case pass rate | **100 %** (44 of 44) |
| Denial cases (error code expected) returning the expected code with `network_calls = 0` | **100 %** — mandatory (VS-03, 04, 05, 13–16, 20, 21, 24–29, 30–32, 34, 36, 37, 43, 44) |
| Cases creating a paid call, ledger row, asset row or licence row that `expected` forbids | **0** — mandatory |
| Cases where a canary string reaches a log or output | **0** — mandatory |
Cost and latency per case are recorded (zero cost with the fake). CI fails the PR on any miss.

## 7. Recording fields (per case per run)
`run_id`, `case_id`, `passed`, `assertions` (A1–A11 → pass/fail + detail), `config_version`, `adapter` (`fake`), `started_at`, `figure_kind`.

## 8. Open points
- VS-39 and VS-40 encode the provider-fault behaviour of the fake; real provider error bodies are added as recorded fixtures when the adapter exists (27 §8.2). **REQUIRES REVIEW (Phase 1): provider error codes.**
- VS-37 uses a 40-character limit as a fixture value only; the real `agent_07.tts.max_chars_per_request` is **REQUIRES REVIEW (Phase 1)**.
- VS-12 / VS-16 assume the Tier 0 rule "the clone's voice owner is an owner of the org"; the Tier 1 rule is an owner decision.
