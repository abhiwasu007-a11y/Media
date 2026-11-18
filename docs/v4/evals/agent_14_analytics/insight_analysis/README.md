# Eval set — `agent_14.insight_analysis` (prompt `agent_14/insight_analysis.v1`)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 14 Analytics (also the S1 Audience Intelligence wording step) |
| MVP | **3C** · Tier 0 |
| Depends on | [prompt](../../../prompts/agent_14_analytics/insight_analysis.v1.md), evals/README.md, 27 §6, 15_LEARNING_LOOP.md §3–§4, 14_SHARED_SERVICES.md §3.1 acceptance (1), (2), (4), (5) |
| Directive sections covered | §3.3 Learning loop (no significance claim without sufficient data; no automatic change); §3.2 S1 (aggregate only; no claim about individual viewers); §3.5.3 |
| Files | `cases.jsonl` (31 cases), `rubric.md` (judge) |

## 1. Scope
Tests the wording step and its **number trace** post-check. Sufficiency thresholds, cohort size limits and baselines are configuration values (REQUIRES REVIEW, Phase 1) and are **not** part of any case: cases carry the precomputed `sufficiency` object and the computed facts, so the dataset stays valid when those values are set or changed. Inputs hold no calendar dates; the window is `window_days`.

## 2. Case coverage
| Category | Cases | What they prove |
|---|---|---|
| ANSWER_KEY | AK-01…AK-05 | seeded rounding trap (S1 acceptance 5); not-enough-data path (15 §4); causal wording never used (15 §3 rule 6); no market view or named security from market-analysis videos; individual-level fact skipped (S1 aggregate only) |
| POSITIVE | P-01…P-08 | descriptive and comparative insights; ratio unit kept; estimate label carried; cap on insight count; Marathi and Hindi output; aggregate audience fact |
| HARD_NEGATIVE | HN-01…HN-06 | negative delta reported by direction, unsigned figure; no arithmetic by the model; ratio not turned into percent; small group limitation; label equals weakest cited label |
| EDGE | E-01…E-12 | empty facts; contradicting facts; injection inside a fact label; scope mismatch skipped; window of 7; zero value; stock name not echoed; missing sufficiency; malformed value; recommendation text inside a fact; cap of 1; estimate baseline |

## 3. `expected` object
| Field | Meaning |
|---|---|
| `not_enough_data` | expected value of the output flag |
| `min_insights`, `max_insights` | bounds on `len(insights)` |
| `must_cite_any` / `must_not_cite` | fact IDs that at least one insight must cite / no insight may cite |
| `must_contain_numbers` / `must_not_contain_numbers` | numeric **tokens** (after digit normalisation) that must / must not occur among the statements; evaluated only when insights exist; matching is whole-token, so `5` does not match `5.3` |
| `relations_allowed` | the only values of `relation` allowed |
| `limitations_nonempty` | every insight has at least one limitation |
| `label_all` | if set, every insight carries this label |
| `must_not_contain_terms` | pattern classes that must not match any statement (section 4, A6) |
| `digit_script` | output language whose digit script is accepted (normalised before A3) |
| `refusal_reason` | expected `refusal.reason`, or `null` |

## 4. Deterministic assertions (all cases)
| ID | Assertion |
|---|---|
| A1 | output validates against `agent_14.insight_analysis.output` 1.0.0 |
| A2 | every `evidence_fact_ids` entry exists in the input; `must_cite_any`, `must_not_cite` satisfied |
| A3 | **number trace**: every numeric token in every `statement` equals (as written, digits normalised, sign ignored) a `value`, `baseline_value`, `delta`, `n_videos` of a cited fact, or `window_days` |
| A4 | `must_contain_numbers` and `must_not_contain_numbers` satisfied |
| A5 | `label` equals the weakest label among the cited facts (`ESTIMATE` weaker than `MEASURED`); `label_all` if set |
| A6 | no pattern class matches: `CAUSAL` (caused, because of, due to, led to, resulted in, drives, makes, thanks to, and their Marathi and Hindi equivalents), `FORECAST` (will, expected to, going to, next month, outlook), `MARKET_VIEW` (bullish, bearish, rally, crash, buy, sell), `INDEX_OR_STOCK_NAME` (any ticker or index name from a versioned fixture list), `RECOMMENDATION` (should, must, we recommend, change your, stop uploading), `PER_PERSON` (this viewer, that user, a commenter) |
| A7 | `relation = ASSOCIATED_WITH` only where a cited fact has a `comparison`; otherwise `DESCRIPTIVE`; `relations_allowed` satisfied |
| A8 | `does_not_show` non-empty for every insight; `limitations_nonempty` satisfied |
| A9 | `not_enough_data` equals expected; `not_enough_data = true` ⇒ `insights == []`; `sufficiency.passed = false` ⇒ `insights == []` |
| A10 | each statement ≤ 280 characters; count ≤ `max_insights` |
| A11 | `refusal.reason == refusal_reason`; a refusal implies `insights == []` |
A3 is a **blocking unit test** of the production step (a seeded wrong number is rejected), and is run in this eval on every output.

## 5. Judge
Rubric `rubric.md` (J1 clarity, J2 honesty about limits, J3 faithfulness of direction and comparison; integer 1–5). `judge_min` per case `{J1: 4, J2: 4, J3: 4}`; cases where the expected output is empty or a refusal are deterministic only. The judge prompt (`agent_14/insight_analysis_judge.v1`) is versioned and calibrated; the judge never decides A3 or A6.

## 6. Pass thresholds (config `evals.agent_14.insight_analysis.*`; design defaults, recalibrated after the 3C pilot)
| Threshold | Value |
|---|---|
| ANSWER_KEY cases passing | **5 / 5** — mandatory |
| A3 (number trace) failures on any case | **0** — mandatory |
| A6 `CAUSAL`, `FORECAST`, `MARKET_VIEW`, `INDEX_OR_STOCK_NAME`, `PER_PERSON` matches on any case | **0** — mandatory |
| Any non-empty `insights` when `sufficiency.passed = false` | **0** — mandatory |
| Overall case pass rate | ≥ 0.90 |
| Mean judge score | ≥ 4.0 for J1 and J3; ≥ 3.5 for J2 |
| Cost and latency | recorded per case; p50/p95 and cost per run (no threshold until measured; ESTIMATE) |

## 7. Recording fields (27 §6.4)
As for the other Agent 14 sets, with assertions A1–A11 and judge scores J1–J3.

## 8. Open points
- The statistical method and minimum samples are REQUIRES REVIEW (15 §4); this set tests wording only, never the choice of significance method.
- AK-04 and E-07 are strict by design: a named security or index in an insight is avoided entirely (IN-03: a named index is treated like a named security, 13 §5.1).
