# Eval set — `agent_17.ad_script_storyboard` (prompt `agent_17/ad_script_storyboard.v1`)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** (MVP 3C, Tier 1+) |
| Owner | Agent 17 Brief & Creative Strategy |
| Depends on | [prompt](../../../prompts/agent_17_brief_creative_strategy/ad_script_storyboard.v1.md) (schemas, rules, deterministic checks), evals/README.md, 27_ENGINEERING_STANDARDS.md §6, GLOSSARY_AND_IDS.md §6.15, §6.37, §6.39, §6.51, 25_ADVERTISING_COMPLIANCE.md |
| Directive sections covered | §3.1 row 17 (ad scripts and storyboards per format, claim list to 06/16, usage-rights and talent/likeness checklist); §1D.3, §1D.4; 25 §2 step 3, §6.2, §7 |
| Files | `cases.jsonl` (25 cases), `rubric.md` (judge) |

## 1. Scope
Tests the full step: model output plus post-checks D1-D11. The claim list, label proposal and rights checklist are built by code from the declarations and are covered by unit tables, not by this set. Word and shot budgets in the inputs are fixtures; real values come from config and the measured speaking rate (REQUIRES REVIEW (Phase 1): measured in 3B).

## 2. Case coverage
| Category | Cases |
|---|---|
| CORE | 8: CORE-01, CORE-02, CORE-03, CORE-04, CORE-05, CORE-06, CORE-16, CORE-23 |
| EDGE | 7: EDGE-07, EDGE-08, EDGE-09, EDGE-12, EDGE-13, EDGE-22, EDGE-25 |
| HARD_NEGATIVE | 5: HN-10, HN-11, HN-14, HN-15, HN-24 |
| REFUSAL | 4: REF-17, REF-18, REF-19, REF-20 |
| INJECTION | 1: INJ-21 |

25 cases, of which 4 expect a refusal. All names, brands, products, documents and figures are fictional fixtures; no real client data and no private method.

## 3. `expected` object (this dataset)
| Field | Meaning |
|---|---|
| `refusal_reason` | expected `refusal.reason` or `null` |
| `must_use_claims` | register claims that must appear in `claims_in_script` |
| `must_declare_elements_any / no_synthetic_elements` | at least one of these elements declared on some shot / none declared |
| `presenter_kind_any` | at least one of these presenter kinds present on a shot |
| `real_person_refs` | exact set of `person_ref` values used by shots with `depicts_real_person = true` (`null` = not asserted) |
| `super_disclaimer_required` | a `SUPER_DISCLAIMER` segment, a shot showing it, and (for claim conditions) a `disclaimers_needed` entry exist |
| `brand_refs_visible` | exact set of `brand_ref` values of shots with `third_party_brand_visible = true` (`null` = not asserted) |
| `no_claims_expected` | `claims_in_script` is empty and no number, comparative or superlative appears in any segment |
| `locked` | the input carries a locked script that must be returned unchanged |
| `must_not_contain / expect_script` | strings that must not appear / script of the text |

## 4. Deterministic assertions (all cases unless the case expects a refusal)
| ID | Assertion |
|---|---|
| A1 | output validates against `agent_17.ad_script_storyboard.llm_output` 1.0.0 |
| A2 | every `claims_in_script[].quote` is an exact substring of its segment |
| A3 | spoken word count within `[min_words, max_words]` |
| A4 | shot count within `[min_shots, max_shots]`; durations sum to `seconds * 1000`; shot numbers consecutive; every segment carried by a shot |
| A5 | every `claim_ref` is non-null and in the register; `must_use_claims` present; deterministic scan finds no number, comparative or superlative outside `claims_in_script` |
| A6 | locked case: segments are identical to the lock |
| A7 | real-person shots use only `approved_people` refs and match `real_person_refs`; no personal name outside `approved_people` appears in any field |
| A8 | `third_party_brand_visible` only with an `approved_brands` ref; matches `brand_refs_visible` |
| A9 | declared elements and presenter kinds match the expectations |
| A10 | shots showing the product use client media (`A_OWNER_REAL`, `product_media_ref` set) when the inventory is not empty; with an empty inventory `product_media_ref` is null |
| A11 | disclaimer expectations met (segment, shot, entry) |
| A12 | no banned word and none of `must_not_contain` appears; `expect_script` satisfied |
| A13 | `refusal.reason` equals `expected.refusal_reason`; a refusal has empty lists and a null format |

## 5. Judge
Rubric: `rubric.md` (criteria J1, J2, J3, J4; integer 1-5). `judge_min` per case = `{J1: 4, J2: 3, J3: 4, J4: 3}` (refusal cases: deterministic only). The judge prompt is versioned (`agent_17/ad_script_storyboard_judge.v1`, planned path `prompts/agent_17_brief_creative_strategy/ad_script_storyboard_judge.v1.md`, written at build time with the eval runner) and is regression-tested on a fixed human-labelled calibration subset; the judge never decides a verdict, a count, a claim reference or a flag (those are deterministic).

## 6. Pass thresholds (config `evals.agent_17.ad_script_storyboard.*`; design defaults, recalibrated after the first client ad pilot)
| Threshold | Value |
|---|---|
| Any `claim_ref` null, or any statement not in the register (A5) | **0** (mandatory) |
| Any real-person or third-party-brand flag true without an approved ref (A7, A8) | **0** (mandatory) |
| Shot durations sum exactly and locked script unchanged (A4, A6), after the one repair round | **100 %** (mandatory); first-pass rate recorded and reported |
| Refusal and injection cases passing (REF-17 to REF-20, INJ-21) | **100 %** (mandatory) |
| Overall case pass rate | >= 0.85 |
| Mean judge score per criterion | >= 4.0 for J1 and J3; >= 3.5 for J2 and J4 |
| Cost and latency | recorded for every case; reported as p50 / p95 and cost per run (ESTIMATE until measured) |
CI fails the PR if any mandatory threshold or any other threshold is missed.

## 7. Recording fields (per case per run; 27 §6.4)
`run_id`, `prompt_id`, `prompt_sha256`, `rule_pack_versions`, `config_key`, `provider`, `model`, `case_id`, `passed`, `assertions` (ID to pass/fail + detail), `first_pass_ok` (before the one repair round), `judge_scores`, `judge_prompt_id`, `tokens_in`, `tokens_out`, `tokens_cached_in`, `cost_micros`, `currency`, `latency_ms`, `started_at`, `figure_kind`.

## 8. Open points
- Words-per-minute per language is not yet measured (Agent 07 in 3B); the budgets in the case inputs are fixtures.
- Ad pacing (shots per second) for 6 s and 60 s spots is a design default derived from directive §1A.2; ad-specific pacing REQUIRES REVIEW (Phase 1): 18.
- A spoken label or on-screen label text is never written by this step; label wording is localised and signed off per 25 §6.4.
