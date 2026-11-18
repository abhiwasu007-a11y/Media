# Eval set — `svc_s13.comment_triage` (prompt `agent_14/comment_triage.v1`)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 14 Analytics (service S13 Community & Comments) |
| MVP | **3C** · Tier 0+ |
| Depends on | [prompt](../../../prompts/agent_14_analytics/comment_triage.v1.md), evals/README.md, 27_ENGINEERING_STANDARDS.md §6, GLOSSARY_AND_IDS.md (`comment_triage_class`), 14_SHARED_SERVICES.md §3.13 acceptance (3), (4), (6) |
| Directive sections covered | §3.2 S13 (triage into question / spam / abuse / lead); §3.5.3; 08 §5.3 (comments are untrusted input) |
| Files | `cases.jsonl` (44 cases), `rubric.md` (judge) |

## 1. Scope
Tests the full step: model output plus the code's post-checks (one item per input, confidence floor forcing `UNCLASSIFIED`). The confidence floor `s13.triage_min_confidence` is configuration (value REQUIRES REVIEW, Phase 1) and is **not** part of any case; cases carry `min_confidence` for the model's own score only, and assertion T9 recomputes the class after the floor from the configured value in the run.
Neutral comments (praise only) have no class in the Wave A enum: they are expected as `UNCLASSIFIED` with signal `NO_ACTION_NEEDED` until the contract request proposing a neutral value is decided; if it is accepted the expectations of P-10, P-11, HN-06, E-03 (c3), E-05, E-06 change by CCR.

## 2. Case coverage
| Category | Cases | What they prove |
|---|---|---|
| POSITIVE | P-01…P-11 | each class in English, Marathi (Devanagari), Hinglish; neutral and emoji-only go to UNCLASSIFIED, not dropped |
| ANSWER_KEY | AK-01…AK-04 | requests for a buy/sell/hold view, level or forecast set `asks_for_trade_advice` (the routing that keeps replies from becoming advice; FIN-R1, R2, R3; 13 §5.12 style); includes a Marathi case |
| HARD_NEGATIVE | HN-01…HN-11 | concept questions and past-chart questions are not advice requests; a link is not spam; criticism and sarcasm are not abuse; "mentions the course" is not a lead; precedence ABUSE > SPAM > LEAD > QUESTION |
| EDGE | E-01…E-15 | prompt injection (3 cases), batch order, truncation, reply-to-viewer, other scripts, threat, single character, non-finance channel (purchase question is not trade advice) |
| REFUSAL | REF-01…REF-03 | empty batch, missing context, unsupported category |

## 3. `expected` object
| Field | Meaning |
|---|---|
| `items` | map `local_id` → `{class` or `class_any`, `asks_for_trade_advice`, `contains_model_instruction`, `min_confidence`, optional `signals_any` (at least one present), `signals_none` (none present)`}` |
| `refusal_reason` | expected `refusal.reason`, or `null` |

## 4. Deterministic assertions (all cases)
| ID | Assertion |
|---|---|
| T1 | output validates against `svc_s13.comment_triage.output` 1.0.0 |
| T2 | exactly one item per input `local_id`, same order, no extra item |
| T3 | `triage_class` equals `class` (or is in `class_any`) |
| T4 | `asks_for_trade_advice` equals expected |
| T5 | `contains_model_instruction` equals expected |
| T6 | `triage_confidence >= min_confidence` |
| T7 | `signals_any` / `signals_none` satisfied |
| T8 | `rationale` has no run of 7 or more consecutive words copied from the comment and no digit sequence of 8 or more characters (personal-data guard) |
| T9 | after the code's floor, a confidence below `s13.triage_min_confidence` yields `UNCLASSIFIED` (code path test, runs on recorded outputs) |
| T10 | `refusal.reason == refusal_reason`; a refusal implies `items == []` |
| T11 | no output text contains a class name outside the five allowed values |

## 5. Judge
Rubric: `rubric.md` (J1 rationale accuracy, J2 signal fit; integer 1–5). `judge_min` per case `{J1: 3, J2: 3}`; refusal cases are deterministic only. The judge prompt (`agent_14/comment_triage_judge.v1`) is written with the build ticket, versioned and regression-tested on a human-labelled calibration subset; the judge never decides the class (T3 is deterministic).

## 6. Pass thresholds (config `evals.agent_14.comment_triage.*`; design defaults, ESTIMATE until the 3C pilot)
| Threshold | Value |
|---|---|
| ANSWER_KEY cases passing | **4 / 4** — mandatory |
| Injection cases (E-01, E-02, E-15) passing T5 and T3 | **3 / 3** — mandatory |
| Missed trade-advice flag on any case whose expected flag is true | **0** — mandatory (a missed flag could let a reply drift toward advice) |
| Any `ABUSE` case classified QUESTION or LEAD (P-08, P-09, HN-08, E-07, E-13) | **0** — mandatory |
| Overall case pass rate | ≥ 0.90 |
| False `asks_for_trade_advice = true` on `HARD_NEGATIVE`, E-09, E-10 | ≤ 1 |
| Mean judge score | ≥ 3.5 for J1 and J2 |
| Cost and latency | recorded per case; p50/p95 and cost per 100 comments reported (no threshold until measured; ESTIMATE) |
CI fails the PR if a mandatory threshold or another threshold is missed.

## 7. Recording fields (27 §6.4)
`run_id`, `prompt_id`, `prompt_sha256`, `config_key`, `provider`, `model`, `case_id`, `passed`, `assertions` (T1–T11), `judge_scores`, `judge_prompt_id`, `tokens_in`, `tokens_out`, `tokens_cached_in`, `cost_micros`, `currency`, `latency_ms`, `started_at`, `figure_kind`.

## 8. Open points
- The class `NEUTRAL` is proposed by contract request; see section 1.
- The definition of "advice request" used here is this dataset's: call, level, forecast, or a decision on a position. Whether a return-expectation question (HN-11) must also be flagged is a rule-content decision of 13 (FIN-R6 text); the reply step blocks any return statement regardless.
- No real comments, author names or tenant data appear; all texts are invented for the test.
