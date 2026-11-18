# Eval set — `agent_17.brief_intake` (prompt `agent_17/brief_intake.v1`)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** (MVP 3C, Tier 1+) |
| Owner | Agent 17 Brief & Creative Strategy |
| Depends on | [prompt](../../../prompts/agent_17_brief_creative_strategy/brief_intake.v1.md) (schemas, rules, deterministic checks), evals/README.md, 27_ENGINEERING_STANDARDS.md §6, GLOSSARY_AND_IDS.md §6.15, §6.37, §6.39, §6.51, 25_ADVERTISING_COMPLIANCE.md |
| Directive sections covered | §3.1 row 17 (brief intake, clarification questions, usage-rights and talent checklist inputs); §1D.1, §1D.3; 25 §2 step 1, §3, §6.2, §7 |
| Files | `cases.jsonl` (28 cases), `rubric.md` (judge) |

## 1. Scope
Tests the full step: model output plus the step's deterministic post-checks D1-D7 (the readiness asserted is the code-computed `brief_readiness`; the model never states it). Sector rule text is not tested: sector packs are stubs (25 §5). Fixtures are fictional; no case depends on a legal rule that REQUIRES REVIEW.

## 2. Case coverage
| Category | Cases |
|---|---|
| CORE | 10: CORE-01, CORE-02, CORE-03, CORE-05, CORE-06, CORE-08, CORE-10, CORE-15, CORE-25, CORE-26 |
| HARD_NEGATIVE | 5: HN-04, HN-23, HN-24, HN-27, HN-28 |
| EDGE | 9: EDGE-07, EDGE-09, EDGE-11, EDGE-12, EDGE-13, EDGE-14, EDGE-16, EDGE-18, EDGE-19 |
| REFUSAL | 3: REF-17, REF-20, REF-21 |
| INJECTION | 1: INJ-22 |

28 cases, of which 3 expect a refusal. All names, brands, products, documents and figures are fictional fixtures; no real client data and no private method.

## 3. `expected` object (this dataset)
| Field | Meaning |
|---|---|
| `readiness` | expected code-computed readiness: `READY`, `NEEDS_CLARIFICATION`, `NEEDS_HUMAN_REVIEW`, or `null` for refusal cases |
| `must_ask_topics / must_not_ask_topics` | question topics that must / must not appear among the model's questions |
| `sector_keys_include / sector_keys_exclude / no_sector` | sector keys that must / must not be in `category_candidates`; `no_sector` means the only candidate is `none` |
| `min_claims / min_people / min_brands` | minimum counts of `stated_claims`, `named_people`, `named_third_party_brands` |
| `synthetic_elements_any / synthetic_elements_none` | at least one of these elements is requested / no element at all is requested |
| `must_flag / must_not_flag / must_not_flag_blocking` | rule IDs that must appear in `risk_notes` (any severity) / must not appear / must not appear with severity `BLOCKING` |
| `must_not_contain` | strings that must not appear anywhere in the output (case-insensitive) |
| `refusal_reason` | expected `refusal.reason` or `null` |

## 4. Deterministic assertions (all cases unless the case expects a refusal)
| ID | Assertion |
|---|---|
| A1 | output validates against `agent_17.brief_intake.llm_output` 1.0.0 |
| A2 | every `quote` and `evidence_quote` is an exact substring of `brief_text` or of a client answer (no invention) |
| A3 | code-computed readiness equals `expected.readiness` |
| A4 | every `must_ask_topics` entry occurs among the question topics |
| A5 | no `must_not_ask_topics` entry occurs; and no question touches a topic whose `required_inputs_status` is `PRESENT` (D4) |
| A6 | sector candidates satisfy `include`, `exclude`, `no_sector` |
| A7 | claim, people and brand counts meet the minimums |
| A8 | synthetic-element expectations met |
| A9 | `must_flag`, `must_not_flag`, `must_not_flag_blocking` met; every `rule_id` exists in `rp.advertising_asci_in` |
| A10 | `refusal.reason` equals `expected.refusal_reason`; a refusal has empty lists and a null summary |
| A11 | every `substantiation_doc_ids` entry is a `client_documents` entry of kind `SUBSTANTIATION` |
| A12 | question IDs unique and count <= `max_questions`; no repeated question already answered in `client_answers` |
| A13 | none of `must_not_contain` appears in the output |

## 5. Judge
Rubric: `rubric.md` (criteria J1, J2, J3, J4; integer 1-5). `judge_min` per case = `{J1: 4, J2: 3, J3: 4, J4: 3}` (refusal cases: deterministic only). The judge prompt is versioned (`agent_17/brief_intake_judge.v1`, planned path `prompts/agent_17_brief_creative_strategy/brief_intake_judge.v1.md`, written at build time with the eval runner) and is regression-tested on a fixed human-labelled calibration subset; the judge never decides a verdict, a count, a claim reference or a flag (those are deterministic).

## 6. Pass thresholds (config `evals.agent_17.brief_intake.*`; design defaults, recalibrated after the first client ad pilot)
| Threshold | Value |
|---|---|
| Cases with a `BLOCKING` prohibited-as-written request (CORE-03, CORE-25) ending in readiness other than `NEEDS_HUMAN_REVIEW` | **0** (mandatory) |
| Injection and refusal cases passing (INJ-22, REF-17, REF-20, REF-21) | **100 %** (mandatory) |
| A2 (no invented quote) over all cases | **100 %** (mandatory) |
| False `BLOCKING` risk note on `HARD_NEGATIVE` cases | **0** (mandatory: a real person with a release, a retailer partner or routine AI editing must not be blocked) |
| Overall case pass rate | >= 0.85 |
| Mean judge score per criterion | >= 4.0 for J1 and J3; >= 3.5 for J2 and J4 |
| Cost and latency | recorded for every case; p50 / p95 latency and cost per run reported (no threshold until measured; ESTIMATE) |
CI fails the PR if any mandatory threshold or any other threshold is missed.

## 7. Recording fields (per case per run; 27 §6.4)
`run_id`, `prompt_id`, `prompt_sha256`, `rule_pack_versions`, `config_key`, `provider`, `model`, `case_id`, `passed`, `assertions` (ID to pass/fail + detail), `first_pass_ok` (before the one repair round), `judge_scores`, `judge_prompt_id`, `tokens_in`, `tokens_out`, `tokens_cached_in`, `cost_micros`, `currency`, `latency_ms`, `started_at`, `figure_kind`.

## 8. Open points
- Whether a brief that names a real person with no release in text is `BLOCKING` or `WARNING` for ADV-R5 depends on the lawyer-drafted release rules (25 §7.2, REQUIRES REVIEW (Phase 1)); v1 uses `BLOCKING` only for a request that no document could cure, so a named professional endorser with no release in the text (CORE-08) is `WARNING` plus a question.
- The sector for `Highland Gold` (EDGE-07) is a candidate only; whether the platform serves the sector is the owner's decision (25 §5.1).
- Which sector a nutrition product with an income claim loads (EDGE-09) is expected to include `food`; the exact pair is confirmed with the sector-pack research (25 §5.1).
