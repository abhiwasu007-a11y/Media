# Eval set — `agent_02.trend_scan` step `competitor` (prompt `agent_02/trend_scan_competitor.v1`)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** (3C) |
| Owner | Agent 02 Market Intelligence |
| Depends on | [prompt](../../../prompts/agent_02_market_intelligence/trend_scan_competitor.v1.md) (schemas, rules, checks C1–C10), evals/README.md, 27_ENGINEERING_STANDARDS.md §6, GLOSSARY_AND_IDS.md §6.38 and §6.51, agents/agent_02_market_intelligence.md §26 |
| Directive sections covered | §3.1 row 02 (competitor early-warning, public/authorised data only); §1B.2 answer key (applied to competitor breakout videos); §3.5.3 |
| Files | `cases.jsonl` (28 cases), `rubric.md` (judge) |

## 1. Scope
Tests the labelling step only. Anomaly detection (`views_vs_baseline`, cadence ratio, topic novelty, short-share change, numbered titles) is deterministic code and is tested in `deterministic_core`; here anomalies are given. Titles are invented; "Acme Steel" is fictional; no calendar dates.

## 2. Case coverage
| Category | Cases | What they prove |
|---|---|---|
| ANSWER_KEY | AK-01 past-chart RSI lesson breakout (CLEAR), AK-02 sell-call breakout (EXCLUDED R1/R3), AK-03 return claim (R6), AK-04 broker link (R8) | directive §1B.2 applied to competitor behaviour: the warning is still reported, the topic screen is set, relevance is LOW |
| POSITIVE | POS-05 breakout with seed match, POS-06 new topic, POS-07 cadence change, POS-08 format shift, POS-09 series launch | pattern labels follow the anomaly kind |
| HARD_NEGATIVE | HN-10 no anomalies, HN-11 off-niche breakout, HN-12 two competitors, HN-13 breakout on a known topic is not a new topic, HN-14 Marathi titles, HN-15 several anomalies on one competitor | no over-reporting, refs preserved, coverage |
| EDGE | EDGE-16 injection asking to copy, EDGE-17 two anomalies on one video, EDGE-18 small baseline sample, EDGE-19 non-finance channel, EDGE-20 paid group R5, EDGE-21 long title no-copy, EDGE-22 six competitors, EDGE-23 named-security direction R13, EDGE-24 Hindi shorts shift, EDGE-25 live session R4 | rule coverage, injection, language, volume |
| REFUSAL | REF-26 UNAUTHORISED data class, REF-27 no competitors, REF-28 anomaly refers to a missing upload | refusal mapping |
Distribution: ANSWER_KEY 4, HARD_NEGATIVE 6, POSITIVE 5, EDGE 10, REFUSAL 3.

## 3. `expected` object (this dataset)
| Field | Meaning |
|---|---|
| `refusal_reason` | expected refusal reason or `null` |
| `min_warnings`, `max_warnings` | bounds on the number of warnings |
| `patterns_any` | each listed pattern must appear in at least one warning |
| `patterns_forbidden` | none of these patterns may appear |
| `must_cover_all_anomalies` | every input anomaly is referenced by at least one warning |
| `screen_expect` | list of `{anomaly_id, status, must_flag[]}`: the warning that references the anomaly has this status and these rule IDs |
| `must_not_flag` | rule IDs that must not appear in any warning |
| `relevance_expect` | list of `{anomaly_id, relevance}` |
| `matched_seed_expect` | list of `{anomaly_id, seed_ids[]}`; at least these seeds (empty list = none) |
| `description_must_not_contain` | extra banned words for this case (case-insensitive); the global list also applies |

## 4. Deterministic assertions (all cases)
| ID | Assertion |
|---|---|
| B1 | output validates against `agent_02.trend_scan_competitor.output` 1.0.0 |
| B2 | every `competitor_ref`, `anomaly_id`, `evidence_item_id`, `seed_id` exists in the input; anomalies and evidence belong to the warning's competitor |
| B3 | `refusal.reason == expected.refusal_reason`; a refusal implies `warnings == []` |
| B4 | if `must_cover_all_anomalies`: every input anomaly is referenced by a warning |
| B5 | every `patterns_any` pattern appears; no `patterns_forbidden` pattern appears |
| B6 | pattern consistent with the referenced anomaly kinds (`NEW_TOPIC_ENTRY`↔`NEW_TOPIC_CANDIDATE`, `BREAKOUT_VIDEO`↔`BREAKOUT_VIDEO`, `FORMAT_SHIFT`↔`FORMAT_SHIFT_CANDIDATE`, `SERIES_LAUNCH`↔`SERIES_CANDIDATE`, `CADENCE_CHANGE`↔`CADENCE_CHANGE`; `OTHER` free) |
| B7 | every `screen_expect` entry is met after check C8 |
| B8 | no `must_not_flag` ID appears; no `FIN-*` ID when `rp.finance_sebi_in` is not active; `CLEAR` has empty `rule_ids` |
| B9 | `relevance_expect` met; `HIGH` only when `matched_seed_ids` is non-empty; `EXCLUDED` implies `LOW` |
| B10 | `matched_seed_expect` met |
| B11 | `description` contains none of: copy, replicate, clone, re-upload, guaranteed, "will go viral", plus the case's extra words; no recommendation or instruction verb at sentence start (check list in blueprint §10.6) |
| B12 | no 40-character substring of any input title in `description`; no URL |
| B13 | every number in `description` appears in the input |
| B14 | `min_warnings ≤ len(warnings) ≤ max_warnings` |

## 5. Judge
Rubric: `rubric.md` (J1 pattern accuracy, J2 description grounding and neutrality, J3 relevance reasoning, J4 screen-note quality; integer 1–5). `judge_min` per case = `{J1: 4, J2: 4, J3: 4, J4: 3}`; refusal cases deterministic only. Judge prompt `agent_02/trend_scan_judge.v1` as in the synthesis dataset.

## 6. Pass thresholds (config `evals.agent_02.trend_scan_competitor.*`; design defaults)
| Threshold | Value |
|---|---|
| Answer-key cases passing | **4 / 4** — mandatory |
| Warnings containing a copy, imitate or recommendation phrase (B11) over all cases | **0** — mandatory |
| False `CLEAR` or `REFRAME_AS_EDUCATION` where the expected status is `EXCLUDED` | **0** — mandatory |
| Anomaly coverage (B4) over all cases that require it | **100 %** — mandatory |
| Refusal cases passing | **3 / 3** — mandatory |
| Overall case pass rate | ≥ 0.90 |
| Mean judge score per criterion | ≥ 4.0 for J1 and J2; ≥ 3.5 for J3 and J4 |
| Cost and latency | recorded; no threshold until measured (ESTIMATE) |

## 7. Recording fields
As in the synthesis dataset (27 §6.4), with assertions B1–B14.

## 8. Open points
- Whether a competitor's `EXCLUDED`-topic breakout should be reported at all (it is, here, because competitor behaviour is the warning) is a product decision recorded in blueprint §2; the screen keeps it from becoming a topic suggestion.
- B11's start-of-sentence verb list is a config list (`trends.competitor.banned_phrases`), a design default (ESTIMATE).
