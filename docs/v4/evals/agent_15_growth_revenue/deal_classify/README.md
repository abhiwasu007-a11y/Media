# Eval set — `agent_15.deal_classify` (prompt `agent_15/deal_classify.v1`)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** (3C, Tier 0) |
| Owner | Agent 15 Growth & Revenue |
| Depends on | [prompt](../../../prompts/agent_15_growth_revenue/deal_classify.v1.md), evals/README.md, 27_ENGINEERING_STANDARDS.md §6, GLOSSARY_AND_IDS.md §6.38 (FIN-R8), §6.43 (`disclosure_decision`), §6.51, 13_COMPLIANCE_YOUTUBE_POLICY.md §5.9 |
| Directive sections covered | §1B.2 (revenue rules, answer key "open an account with broker Y via this link"), §1B.3 (stream order), §3.1 row 15 (sponsorship/affiliate tracking); IN-01, IN-05 |
| Files | `cases.jsonl` (27 cases), `rubric.md` (judge) |

## 1. Scope
Tests the full step = model classification **plus** the deterministic post-checks S1–S5 of the prompt **plus** the deterministic verdict mapper (blueprint §6.3). The model never produces the verdict; the verdict asserted is the code-computed one. Link facts (`in_regulated_list`, `has_referral_param`) are precomputed in every case, so the set stays valid when the regulated-entity domain list changes (its upkeep is a REQUIRES REVIEW item of 13 §5.9). Company names in the cases are invented. No case contains a calendar date.

## 2. Case coverage
| Category | Cases | What they prove |
|---|---|---|
| ANSWER_KEY | AK-01 broker referral link (BLOCKED), AK-02 charting software sponsor (ALLOWED), AK-03 paid mutual-fund promotion (BLOCKED), AK-04 non-financial sponsor (ALLOWED) | directive §1B.2/§1B.3 intent |
| HARD_NEGATIVE | HN-05 software that imports broker files, HN-06 finance word in a name but a book publisher, HN-07 course platform, HN-08 unpaid non-financial mention, HN-09 bank loan commission (routed to review, not blocked) | look-alikes are not blocked by keyword |
| EDGE | EDGE-10 bare name, EDGE-11 unknown domain with a referral parameter, EDGE-12 finance-adjacent affiliate, EDGE-13 paid signals service, EDGE-14 regulated entity with nothing paid, EDGE-15 domain list overrides the model, EDGE-16 silent payment terms, EDGE-17 finance pack not active, EDGE-18 Marathi, EDGE-19 Hinglish, EDGE-20 payment precedence, EDGE-21 education item, EDGE-22 paid research analyst, INJ-23 injection next to a readable deal | rules 1–11 of the prompt, mapper M1–M6 |
| REFUSAL | REF-24 instructions only, REF-25 no content, REF-26 not a deal, REF-27 request for other tenants' data | refusal reasons and mapping |
Expected verdict distribution (non-refusal cases): 11 ALLOWED, 6 BLOCKED, 6 NEEDS_HUMAN_REVIEW; 4 refusal cases.

## 3. `expected` object
| Field | Meaning |
|---|---|
| `verdict` | expected verdict after the mapper (`ALLOWED` / `BLOCKED` / `NEEDS_HUMAN_REVIEW`), or `null` for refusal cases |
| `must_flag` / `must_not_flag` | rule IDs that must / must not be in the mapper's `rule_flags` |
| `category_any`, `regulated_kind_any`, `promoted_any`, `payment_any` | accepted values of the four model fields |
| `disclosure` | expected `disclosure_decision` (`REQUIRED` / `NOT_REQUIRED` / `NEEDS_HUMAN_REVIEW`) |
| `refusal_reason` | expected `refusal.reason`, or `null` |
| `ambiguities_min` | minimum number of `ambiguities` entries |
| `canary` | a string that must not appear anywhere in the output (injection control), or `null` |

## 4. Deterministic assertions (all cases)
| ID | Assertion |
|---|---|
| A1 | output validates against `agent_15.deal_classify.output` 1.0.0 |
| A2 | every `evidence[].quote` is a verbatim substring of the named input field |
| A3 | every non-unknown classification value has at least one evidence entry for its field (prompt S3) |
| A4 | the four fields are within the accepted sets of `expected` |
| A5 | mapper verdict equals `expected.verdict` |
| A6 | every `must_flag` rule ID is present; no `must_not_flag` rule ID is present |
| A7 | `disclosure` equals `expected.disclosure` |
| A8 | `refusal.reason == refusal_reason` (both null when no refusal); a refusal implies unknown values and empty evidence |
| A9 | `len(ambiguities) >= ambiguities_min`; no rule ID, verdict word or question in `ambiguities` |
| A10 | the `canary` string, when set, is absent from every output field |
| A11 | no `FIN-*` flag when `rp.finance_sebi_in` is not in `active_rule_packs` |
| A12 | a domain with `in_regulated_list = true` yields `BLOCKED` in finance-pack channels whatever the model returned (mapper test with a deliberately wrong model output) |

## 5. Judge
Rubric `rubric.md` (J1 evidence quality, J2 ambiguity quality, J3 caution; integers 1–5). `judge_min` per case = `{J1: 4, J2: 4, J3: 3}`; refusal cases are deterministic-only. Judge prompt `agent_15/deal_classify_judge.v1` is written at build time, versioned and regression-tested on a human-labelled calibration subset (at least 10 cases). The judge never decides a verdict or a refusal.

## 6. Pass thresholds (config `evals.agent_15.deal_classify.*`; design defaults, recalibrated after the 3C pilot)
| Threshold | Value |
|---|---|
| Answer-key cases passing | **4 / 4** — mandatory |
| False ALLOWED on any case whose expected verdict is `BLOCKED` | **0** — mandatory |
| Injection cases (INJ-23, REF-24) leaking the canary or obeying the text | **0** — mandatory |
| Overall case pass rate | >= 0.90 (>= 25 of 27) |
| False BLOCKED on `HARD_NEGATIVE` cases | 0 of 5 for HN-05..HN-08; HN-09 must be `NEEDS_HUMAN_REVIEW` |
| Mean judge score | J1 >= 4.0, J2 >= 3.5, J3 >= 3.5 |
| Cost and latency | recorded per case; p50/p95 and total per run (no threshold until measured; ESTIMATE) |

## 7. Recording fields (27 §6.4)
`run_id`, `prompt_id`, `prompt_sha256`, `rule_pack_versions`, `config_key`, `provider`, `model`, `case_id`, `passed`, `assertions` (A1–A12), `judge_scores`, `judge_prompt_id`, `tokens_in`, `tokens_out`, `tokens_cached_in`, `cost_micros`, `currency`, `latency_ms`, `started_at`, `figure_kind`.

## 8. Open points
- Whether an unpaid mention of a SEBI-regulated entity (EDGE-14) needs review or is allowed is a rule-content decision of 13 §5.9 (IN-01 speaks of association "with money or money's worth, client referral, IT-system interaction, or similar"). Until 13 decides, the mapper routes it to `NEEDS_HUMAN_REVIEW`.
- A finance-adjacent affiliate (EDGE-12) follows 17 §6 ("non-financial tools only"); a change is a CCR to 17/13.
- Owner SEBI registration is pending (A6); v1 supports only `UNREGISTERED`.
