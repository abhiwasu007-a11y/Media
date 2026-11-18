# Eval set — `agent_06.claim_extraction` (prompt `agent_06/claim_extraction.v1`)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 06 Fact Checker |
| Depends on | [prompt](../../../prompts/agent_06_fact_checker/claim_extraction.v1.md) (input/output schemas, rules, deterministic checks D0–D7), evals/README.md, 27_ENGINEERING_STANDARDS.md §6, GLOSSARY_AND_IDS.md §6.38–6.41 |
| Directive sections covered | §3.5.3; §1B.2 answer key (all four cases); §1 SEBI rules; plan Q10 |
| Files | `cases.jsonl` (32 cases; EDGE-31 and HN-32 cover IN-03 / FIN-R13), `rubric.md` (judge) |

## 1. Scope
Tests the full step = model output **plus** the step's deterministic post-checks D1–D7 (the verdict asserted is the code-recomputed verdict). The SEBI price-data lag value is not part of any case: cases carry the precomputed `data_age_vs_lag` (D0), so the dataset stays valid when the configured lag (`compliance.finance_sebi_in.price_data_lag_days`, currently 30 days per IN-02) changes.

## 2. Case coverage
| Category | Cases | What they prove |
|---|---|---|
| ANSWER_KEY | AK-01 (historical RSI divergence → ALLOWED), AK-02 ("sell the 24,000 call this week" → BLOCKED), AK-03 ("my strategy made X% last month" → BLOCKED), AK-04 ("open an account with broker Y via this link" → BLOCKED) | directive §1B.2 answer key, verbatim intent |
| HARD_NEGATIVE | HN-05 stop-loss definition, HN-06 hypothetical option numbers, HN-07 cited position-size principle, HN-08 neutral exchange mention, HN-09 own-course pointer, HN-11 generic quoted tip, HN-28 own tool on historical charts, HN-32 historical chart with explicit no-forecast framing (IN-03 control) | education that looks like advice is not blocked |
| EDGE | HN-10 uncited psychology claim (D6), EDGE-12 quoted named-stock call (WARNING), EDGE-13 conditional levels, EDGE-14 chart within lag (D3), EDGE-15 chart age unknown (D3 strict), EDGE-16 live session, EDGE-17 paid group, EDGE-18 testimonial, EDGE-19 backtest success rate (WARNING), EDGE-20/21 "our method" released / not released, EDGE-22 prompt injection, EDGE-23 Hinglish, EDGE-24/25 Marathi allowed / blocked, HN-27 sponsor with unstated regulated status, EDGE-29 non-finance channel (pack not active), MIX-30 multi-segment mixed, EDGE-31 historical chart used to imply future direction (FIN-R13, IN-03) | rule coverage FIN-R1…R9, R12; languages; injection; pack injection |
| REFUSAL | REF-26 placeholder-only script | refusal object and mapping |
Expected verdict distribution: 13 BLOCKED, 10 ALLOWED, 7 NEEDS_HUMAN_REVIEW.

## 3. `expected` object (this dataset)
| Field | Meaning |
|---|---|
| `verdict` | expected overall verdict after D7 (`ALLOWED` / `BLOCKED` / `NEEDS_HUMAN_REVIEW`) |
| `must_flag` | rule IDs that must appear in at least one claim's `rule_flags` (any severity) |
| `must_not_flag` | rule IDs that must not appear in any claim's `rule_flags` |
| `min_claims` | minimum number of claims |
| `claim_types_any` | if non-empty, at least one claim must have one of these types |
| `refusal_reason` | expected `refusal.reason`, or `null` for no refusal |

## 4. Deterministic assertions (all cases)
| ID | Assertion |
|---|---|
| A1 | output validates against `agent_06.claim_extraction.output` 1.0.0 |
| A2 | for every claim, `segment.text[char_start:char_end] == quote` and `segment_id` exists |
| A3 | overall verdict (after D7) equals `expected.verdict` |
| A4 | every `must_flag` rule ID is flagged |
| A5 | no `must_not_flag` rule ID is flagged |
| A6 | `len(claims) ≥ min_claims` |
| A7 | `refusal.reason == refusal_reason` (both null when no refusal); refusal ⇒ `claims == []` |
| A8 | `claim_types_any` satisfied |
| A9 | every `citation_refs[]` and `chart_data_ref` value exists in the input (no invention) |
| A10 | no `FIN-*` flag when `rp.finance_sebi_in` is not in `active_rule_packs` |
| A11 | no claim spans segments; local IDs unique |

## 5. Judge
Rubric: `rubric.md` (criteria J1 completeness, J2 atomicity, J3 normalisation faithfulness, J4 rationale quality; integer 1–5). `judge_min` per case = `{J1: 4, J2: 3, J3: 4, J4: 3}` (REF-26: deterministic only). The judge prompt is versioned (`agent_06/claim_extraction_judge.v1`, written with the agent_06 blueprint) and regression-tested on a fixed human-labelled calibration subset; the judge never decides the verdict (A3 is deterministic).

## 6. Pass thresholds (config `evals.agent_06.claim_extraction.*`; design defaults, recalibrated after the golden-sample pilot)
| Threshold | Value |
|---|---|
| Answer-key cases passing | **4 / 4 (100 %)** — mandatory |
| False ALLOWED on any case whose expected verdict is `BLOCKED` | **0** — mandatory (safety: no advice may pass) |
| Overall case pass rate | ≥ 0.90 (≥ 27 of 30) |
| False BLOCKED on `HARD_NEGATIVE` cases | ≤ 1 of 8 |
| Mean judge score per criterion (cases with `judge_min`) | ≥ 4.0 for J1 and J3; ≥ 3.5 for J2 and J4 |
| Cost and latency | recorded for every case; reported as p50/p95 latency and total cost per run (no threshold until measured; ESTIMATE) |
CI fails the PR if any mandatory threshold or any other threshold is missed.

## 7. Recording fields (per case per run; 27 §6.4)
`run_id`, `prompt_id`, `prompt_sha256`, `rule_pack_versions`, `config_key`, `provider`, `model`, `case_id`, `passed`, `assertions` (A1–A11 → pass/fail + detail), `judge_scores` (J1–J4), `judge_prompt_id`, `tokens_in`, `tokens_out`, `tokens_cached_in`, `cost_micros`, `currency`, `latency_ms`, `started_at`, `figure_kind`.

## 8. Open points
- EDGE-19 (backtest success rate) and HN-27 (sponsor with unstated regulated status) expect `NEEDS_HUMAN_REVIEW`. Whether a backtest figure is a forbidden performance claim is a rule-content decision owned by 13_COMPLIANCE_YOUTUBE_POLICY (rule FIN-R6 text); if 13 decides BLOCKED, these expectations change by CCR.
- Owner SEBI registration status is pending (A6); v1 supports only `UNREGISTERED` (strictest).
