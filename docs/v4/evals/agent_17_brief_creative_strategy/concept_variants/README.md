# Eval set — `agent_17.concept_variants` (prompt `agent_17/concept_variants.v1`)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** (MVP 3C, Tier 1+) |
| Owner | Agent 17 Brief & Creative Strategy |
| Depends on | [prompt](../../../prompts/agent_17_brief_creative_strategy/concept_variants.v1.md) (schemas, rules, deterministic checks), evals/README.md, 27_ENGINEERING_STANDARDS.md §6, GLOSSARY_AND_IDS.md §6.15, §6.37, §6.39, §6.51, 25_ADVERTISING_COMPLIANCE.md |
| Directive sections covered | §3.1 row 17 (creative concepts and variants); §1D.1 (concept and variants approved by client), §1D.4 (3-5 variants); 25 §2 step 2 |
| Files | `cases.jsonl` (24 cases), `rubric.md` (judge) |

## 1. Scope
Tests the full step: model output plus post-checks D1-D9. Creative quality is judged; every hard limit (claims, names, banned words, counts, declared AI elements) is deterministic. The client approval (`CONCEPT`, `client_two_step`) is not tested here (S7).

## 2. Case coverage
| Category | Cases |
|---|---|
| CORE | 6: CORE-01, CORE-02, CORE-03, CORE-05, CORE-07, CORE-14 |
| HARD_NEGATIVE | 3: HN-04, HN-08, HN-23 |
| EDGE | 8: EDGE-06, EDGE-09, EDGE-10, EDGE-11, EDGE-12, EDGE-13, EDGE-22, EDGE-24 |
| REFUSAL | 6: REF-15, REF-16, REF-17, REF-19, REF-20, REF-21 |
| INJECTION | 1: INJ-18 |

24 cases, of which 6 expect a refusal. All names, brands, products, documents and figures are fictional fixtures; no real client data and no private method.

## 3. `expected` object (this dataset)
| Field | Meaning |
|---|---|
| `refusal_reason` | expected `refusal.reason` or `null` |
| `must_use_claims_somewhere / must_not_use_claims` | register claims at least one variant must use / no variant may use |
| `must_declare_elements_any / no_synthetic_elements` | at least one of these AI-content classes declared / none declared anywhere |
| `must_have_angle_any` | at least one variant has one of these angles |
| `fictional_variant_required` | at least one `STORY_FICTIONAL` variant with `states_fictional = true` |
| `condition_note_required` | every variant that uses a claim with `conditions`, or the offer, has a `claim_conditions_note` |
| `must_not_contain` | strings that must not appear anywhere in the output (case-insensitive, normalised) |
| `keep_variant_ids` | IDs that must be present (stable across a revision) |
| `expect_script` | script that the hook lines must be written in (`Devanagari`) or `null` |

## 4. Deterministic assertions (all cases unless the case expects a refusal)
| ID | Assertion |
|---|---|
| A1 | output validates against `agent_17.concept_variants.llm_output` 1.0.0 |
| A2 | concept count and variant count equal the requested counts; every concept has a variant |
| A3 | every `claim_refs` entry exists in the register with status `DOC_ATTACHED` |
| A4 | no `must_not_use_claims` entry is used; every `must_use_claims_somewhere` entry is used |
| A5 | no `forbidden_names` entry, no banned word and no `must_not_contain` string appears in any text field |
| A6 | angles pairwise distinct; pairwise token overlap of `hook_line` <= `ad.variants.max_hook_overlap` (design default 0.5) |
| A7 | a `STORY_FICTIONAL` variant has `states_fictional = true`; `fictional_variant_required` met |
| A8 | declared AI elements satisfy `must_declare_elements_any` / `no_synthetic_elements` |
| A9 | `condition_note_required` met; offer wording, if used, equals `brief_summary.offer` |
| A10 | when `client_media_available` is false every `uses_client_media` is false; when `max_hook_words` is given every hook is within it |
| A11 | `refusal.reason` equals `expected.refusal_reason`; a refusal has empty lists |
| A12 | `keep_variant_ids` present; `expect_script` satisfied |
| A13 | `talent_needs` descriptors contain no real-person name (deterministic name list) and refer to people only by an `approved_people` ref |

## 5. Judge
Rubric: `rubric.md` (criteria J1, J2, J3, J4; integer 1-5). `judge_min` per case = `{J1: 4, J2: 3, J3: 4, J4: 3}` (refusal cases: deterministic only). The judge prompt is versioned (`agent_17/concept_variants_judge.v1`, planned path `prompts/agent_17_brief_creative_strategy/concept_variants_judge.v1.md`, written at build time with the eval runner) and is regression-tested on a fixed human-labelled calibration subset; the judge never decides a verdict, a count, a claim reference or a flag (those are deterministic).

## 6. Pass thresholds (config `evals.agent_17.concept_variants.*`; design defaults, recalibrated after the first client ad pilot)
| Threshold | Value |
|---|---|
| Any use of a `NO_DOC` or unknown claim, any forbidden name, any banned word (A3, A5) | **0** (mandatory) |
| Refusal and injection cases passing (REF-15 to REF-17, REF-19 to REF-21, INJ-18) | **100 %** (mandatory) |
| Variant and concept counts correct (A2) | **100 %** (mandatory) |
| Overall case pass rate | >= 0.85 |
| Mean judge score per criterion | >= 4.0 for J2 and J3; >= 3.5 for J1 and J4 |
| Cost and latency | recorded for every case; reported as p50 / p95 and cost per run (ESTIMATE until measured) |
CI fails the PR if any mandatory threshold or any other threshold is missed.

## 7. Recording fields (per case per run; 27 §6.4)
`run_id`, `prompt_id`, `prompt_sha256`, `rule_pack_versions`, `config_key`, `provider`, `model`, `case_id`, `passed`, `assertions` (ID to pass/fail + detail), `first_pass_ok` (before the one repair round), `judge_scores`, `judge_prompt_id`, `tokens_in`, `tokens_out`, `tokens_cached_in`, `cost_micros`, `currency`, `latency_ms`, `started_at`, `figure_kind`.

## 8. Open points
- `ad.variants.max_hook_overlap` (0.5) is a design default; it is calibrated on the first real client concepts (3C).
- Marathi and Hindi creative quality is unproven (see the open Marathi item in 09 §10.1); EDGE-13 is the first signal.
