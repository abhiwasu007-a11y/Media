# Eval set — `agent_15.cost_stage_report` (deterministic, no prompt, no judge)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** (3A, Tier 0) |
| Owner | Agent 15 Growth & Revenue |
| Depends on | 09_COST_AND_BUDGET.md §5, §6, §9, §12; 04 §5.14; 3A_SLICE_SPEC.md §4 item 6; agent_15 blueprint §6.6 |
| Directive sections covered | D1 (cost per stage in the downloadable bundle), §1B.5 |
| Files | `cases.jsonl` (23 cases); no `rubric.md` (no LLM step, 27 §6 applies only to LLM steps; the deterministic standard is 27 §6.2 item 1) |

## 1. Scope
Tests `CostStageReporter.build` (blueprint §6.6, §10 row 12): ledger rows to the per-stage table, total, per-term split, figure-kind summary and leak count of 09 §12. Input is a ledger extract plus the stage order of the production type (24 §7.1); no database. Amounts are integer micros; shares are integer basis points, rounded half up; currency conversion uses the row's own `fx_micros` (the integer form of `fx_rate`, millionths), never a guess (09 §3.3).

## 2. Case coverage
| Category | Cases | What they prove |
|---|---|---|
| POSITIVE | POS-01, POS-02 | single and multi-stage ordering, shares |
| ANSWER_KEY | AK-03 | empty ledger prints no stages and "REQUIRES REVIEW" for unknown human review time, never an invented zero (09 §12.3 rule 3) |
| EDGE | EDGE-04 … EDGE-23 | retries billed, revision loops, wasted (discarded) cost, VERIFIED replacement (tokens stay from the ESTIMATE), mixed and fully verified summaries, leaks (VERIFIED without ESTIMATE) under `UNATTRIBUTED`, unmapped task types, term mapping, image generation as `OTHER` (open item O-4), share rounding, foreign currency with and without fx, human review minutes, zero-amount capacity rows, cached tokens, duplicate VERIFIED rows (open item O-5) |

## 3. Input and `expected`
Input: `job_ref`, `currency`, `stage_order[]` (`stage_id`, `task_type`), `rows[]` (ledger columns used: `entry_id`, `figure_kind`, `estimate_entry_id`, `task_type`, `stage_id`, `operation`, `amount_micros`, `currency`, `fx_micros`, `tokens_in/out/cached_in`, plus the derived `iteration` and `discarded`), `human_review_minutes` (integer or null).
Expected: `error` (null or a 07 code), `stages[]` (`stage`, `calls`, tokens, `cost_micros`, `figure_kind` of ESTIMATE / VERIFIED / MIXED, `share_bp`, `revision_loops`, `wasted_micros`), `total_micros`, `terms` (LLM, TTS, footage, music, ai_broll, infra, OTHER; operation prefix map `llm.`, `tts.`, `stock.`, `music.`, `video_gen.`, `render.`, config `finance.term_map`), `figure_summary` (`ESTIMATE`, `VERIFIED` or `partly verified (n of m rows)`), `leak_rows`, `human_review`.

## 4. Assertions and thresholds
Exact equality of every field; invariants checked on every case: sum of `cost_micros` over stages equals `total_micros`; sum of terms equals `total_micros`; no key, account ID or prompt text in the output (09 §12.3 rule 5). **Threshold: 100 % of cases** (`evals.agent_15.cost_stage_report.min_pass_rate` = 1.0). Free in CI.

## 5. Open points
- O-4: 09 §9 has no term for image generation (thumbnail variants, AI stills). It is shown as `OTHER` until 09 decides.
- O-5: two VERIFIED rows for one ESTIMATE are refused (`PERMANENT.INPUT_INVALID`); 04 has no uniqueness rule for that, to be settled with 09 §6.
