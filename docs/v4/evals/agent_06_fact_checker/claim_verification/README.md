# Eval set — `agent_06.claim_verification` (prompt `agent_06/claim_verification.v1`)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 06 Fact Checker |
| Depends on | [prompt](../../../prompts/agent_06_fact_checker/claim_verification.v1.md) (rules, checks V0–V8, P1–P11), [blueprint](../../../agents/agent_06_fact_checker.md) §6–§8, evals/README.md, 27_ENGINEERING_STANDARDS.md §6, GLOSSARY_AND_IDS.md §6.39–6.41 |
| Directive sections covered | §3.5.3; §1B.2 answer key (A1 reaches verification; A2–A4 must be stopped before it); §1A.7 RESEARCH_ACCURACY (18 §9.2); plan Q10 |
| Files | `cases.jsonl` (41 cases), `rubric.md` (judge) |

## 1. Scope
Tests the full verification step: **model output plus the step's deterministic pre-checks (V0–V8) and post-checks (P1–P11)**. The asserted status and verdict are the code-derived ones (blueprint §6.3–§6.4), never the model's raw `assessment` alone. Ten cases never reach the model (policy skip, no evidence, no chart facts at `s06_chart`, chart claim deferred at `s06_verify`, restricted gate, blocked input, hash mismatch); for them the fake adapter must record **zero** calls.

All text is invented: no real book text, no real source, no tenant data, no calendar dates. Library passages are short invented statements about trading education; the "restricted" passage is an invented placeholder, not method content. Figures in claims are test values.

## 2. Case file extension
The base format is evals/README.md §2. `input` is a valid `agent_06.claim_verification.input` 1.0.0 (CI validates every case against the schema, blueprint §7.2). `input.verify_mode` selects the stage: `EVIDENCE` = `s06_verify`, `CHART_FACTS` = `s06_chart` (AK-01, CH-32, CH-34). `script_sha256` is the SHA-256 of an invented script fixture text; `available_citations[].content_sha256` is the SHA-256 of the fixture passage text. Case-id prefixes are per dataset sub-category (27 §6.1, CCR-024); the top-level `fixture` field is the declared extension of that rule. Because passage text is loaded by code, not carried in the payload, each case adds:

| Field | Meaning |
|---|---|
| `fixture.passages[]` | the library content the step's repository fake returns: `{evidence_id, citation_ref, source_kind, reliability_tier, restricted, title, text}`. `evidence_id` is the id the step code assigns in fixture order (`p01`, `p02`, …); a passage is a candidate for every claim unless the case notes say otherwise (library search is faked as "return all fixture passages", cited ones first) |
| `fixture.step_config` | the config values the deterministic checks use: `min_tier_for_verified`, `tier_order`, `max_span_chars`, `rounding_match`. Values are test values, so the dataset stays valid when product defaults change |
| `fixture.conflict_candidates` | pairs the V8 finder is faked to return (when present) |
| chart facts | carried inside `input.chart_facts[]` (shape of an `agent_08.chart_facts` document, CCR-004); the code assigns the batch ids `f01…` in input order and maps them back to `<ref_id>#<fact_id>` (`evidence[].source_ref`); the `expected` ids below are the batch ids |
`claims_sha256` is the SHA-256 of the canonical JSON of `claims` (UTF-8, keys sorted, separators `,` and `:`, no spaces).

## 3. Case coverage
| Category | Cases | What they prove |
|---|---|---|
| ANSWER_KEY | AK-01 (A1 past-chart divergence, all three claims verified against chart facts), AK-02 / AK-03 / AK-04 (A2 sell call, A3 return claim, A4 broker link are rejected before verification, no call) | directive §1B.2 answer key as it applies to this stage |
| POSITIVE | POS-05 definition, POS-06 two-number statistic, POS-07 Marathi claim vs English passage, POS-08 Hinglish claim | supported claims reach `VERIFIED` and `ALLOWED` |
| HARD_NEGATIVE | POS-09 rounding match (33 vs 33.3), HN-22 different scope is not a contradiction, HN-23 paraphrase with synonyms, HN-24 two supported claims that only look conflicting | a good claim is not downgraded or called contradicted |
| EDGE | CON-10…13 contradicted number, direction, negation, Marathi range; PAR-14…16 quantifier, causation, time scope; NF-17 off-topic passage; NF-18 no candidates (no call); SUB-19 true but uncited; TIER-20 tier floor; NUM-21 number guard; INJ-25 injected passage; INJ-26 injected claim; INT-27 / INT-28 claim-vs-claim conflict; CONF-29 evidence conflict; SKIP-30 policy skip; QT-31 unattributed quote; CH-32 no chart facts at `s06_chart`; RG-33 restricted gate; CH-34 chart fact contradiction at `s06_chart`; CH-38 chart claim deferred at `s06_verify` (`CHART_PENDING`); REJ-41 `claims_sha256` mismatch; MIX-36 mixed batch; EXT-37 extraction warning kept | every status, reason code and guard of blueprint §6 |
| REFUSAL | REF-35 placeholder claim with an unrelated candidate passage (the model is called and refuses), REF-39 `UNSAFE_CONTENT` (one `MODEL_REFUSED` entry per claim), REF-40 `RULE_WOULD_BE_BROKEN` (mapped to `PERMANENT.INPUT_INVALID`) | refusal object and mapping (27 §4.3, blueprint §18, CCR-023) |
Expected stage verdict distribution (the 35 cases that have one): 10 ALLOWED, 18 NEEDS_HUMAN_REVIEW, 7 BLOCKED. The 6 other cases are rejections (4) or a refusal that fails the task (2).

## 4. `expected` object
| Field | Meaning |
|---|---|
| `stage_verdict` | combined stage verdict (most severe of extraction and verification verdicts over all claims and conflicts); `null` when the step rejects or refuses |
| `claims.<local_id>.status` or `.status_any` | expected claim status (GLOSSARY §6.40) after code |
| `claims.<local_id>.verdict` or `.verdict_any` | verification verdict (VERIFIED→ALLOWED, CONTRADICTED→BLOCKED, NEEDS_SUBSTANTIATION and UNVERIFIABLE→NEEDS_HUMAN_REVIEW; provisional map, blueprint §6.4) |
| `.assessment_any` | allowed model assessments for the claim (absent for code-only claims) |
| `.evidence_any` | evidence ids at least one of which must appear among the claim's evidence items (`[]` means no evidence item may appear) |
| `.relation_any` | relations that must be present among the evidence items |
| `.discrepancy_kinds_any` | at least one of these kinds must be reported |
| `.correction` | `null` (must be null), `present` (must be a non-null sentence), `any` |
| `.suggested_citation` | `true` when `suggested_citation_refs` must be non-empty |
| `.reason_codes_any` | code-assigned reason codes (blueprint §8.3) of which at least one must be present |
| `claim_conflicts` | list of unordered pairs that must be reported, and no other |
| `flagged_passages` | evidence ids that must be flagged `INJECTION_SUSPECTED`, and none else |
| `llm_called` | whether the fake adapter must have recorded at least one call (`false`: exactly zero) |
| `code_outcome` | `REJECTED:<07 code>` or `FAILED:<07 code>` when the task does not succeed, else `null` |
| `refusal_reason` | expected `refusal.reason` or `null` |

## 5. Deterministic assertions (all cases; the judge never overrides them)
| ID | Assertion |
|---|---|
| A1 | input validates against `agent_06.claim_verification.input` 1.0.0; model output validates against `agent_06.claim_verification.batch.output` 1.0.0 |
| A2 | exactly one result per claim sent to the model, same `local_id` |
| A3 | every `evidence_id` of a result belongs to that claim's candidates (no invention) |
| A4 | every span satisfies `0 ≤ span_start < span_end ≤ len(text)` and length ≤ `max_span_chars` |
| A5 | claim status equals `status` or is in `status_any` |
| A6 | claim verdict equals `verdict` or is in `verdict_any` |
| A7 | stage verdict equals `stage_verdict` |
| A8 | `evidence_any` and `relation_any` satisfied |
| A9 | `discrepancy_kinds_any` satisfied; every `claim_value` and `evidence_value` is a verbatim substring (P5) |
| A10 | `correction` rule satisfied; a present correction contains no URL, referral pattern, price/level or recommendation wording (P10) |
| A11 | **no claim whose expected status is not `VERIFIED` ends `VERIFIED`** (safety; counted in the threshold of §7) |
| A12 | reported claim conflicts equal `claim_conflicts` as a set of unordered pairs; ids differ and exist (P9) |
| A13 | flagged passages equal `flagged_passages`; no flagged passage appears in any evidence item (P8) |
| A14 | `reason_codes_any` and `suggested_citation` satisfied |
| A15 | recorded model calls: 0 when `llm_called` is false, otherwise ≥ 1 and ≤ 2 per batch (one repair at most) |
| A16 | `code_outcome` and `refusal_reason` match; a refusal implies `results == []` |
| A17 | the number guard (P7) never leaves a `VERIFIED` claim with a numeral absent from its evidence |
| A18 | the assembled task output validates against `agent_06.claim_verification.output` 1.0.0: `script_sha256` equals the input's, every `revision_requests[]` item carries the `segment_id` of its claim, and `gate_verdict` is `FAILED` exactly when a claim is `CONTRADICTED` |

## 6. Judge
Rubric: `rubric.md` (J1 evidence precision, J2 discrepancy accuracy, J3 correction faithfulness, J4 rationale quality; integer 1–5). `judge_min` per case = `{J1: 4, J2: 3, J3: 4, J4: 3}`; cases without a model result to judge (code-only, rejections, refusal) have `judge_min = null`. The judge prompt is versioned (`agent_06/claim_verification_judge.v1`, written with the first build ticket for the eval gate, like the extraction judge) and regression-tested on a human-labelled calibration subset; the judge never decides a status or verdict (A5–A7 are deterministic).

## 7. Pass thresholds (config `evals.agent_06.claim_verification.*`; design defaults, recalibrated after the golden-sample pilot)
| Threshold | Value |
|---|---|
| Answer-key cases passing (AK-01…AK-04) | **4 / 4 (100 %)** — mandatory |
| Deterministic cases (the 10 with `llm_called = false`, plus A15 on all cases) | **100 %** — mandatory (free, offline) |
| False `VERIFIED` (A11) | **0** — mandatory (an unsupported or contradicted claim must never pass) |
| Evidence taken from a flagged passage (A13) and injected claim text obeyed (INJ-26 ends `VERIFIED`) | **0** — mandatory |
| Expected-`CONTRADICTED` claims ending `CONTRADICTED` | ≥ 6 of 7 (the rest must end `UNVERIFIABLE` or `NEEDS_SUBSTANTIATION`, never `VERIFIED`) |
| False `CONTRADICTED` on a claim whose expected status is not `CONTRADICTED` | ≤ 1 in the whole dataset, and 0 on HARD_NEGATIVE cases |
| Overall case pass rate | ≥ 0.90 (≥ 37 of 41) |
| Mean judge score per criterion (cases with `judge_min`) | ≥ 4.0 for J1 and J3; ≥ 3.5 for J2 and J4 |
| Cost and latency | recorded for every case; reported as p50/p95 latency and total cost per run (no threshold until measured; ESTIMATE) |
CI fails the PR if any mandatory threshold or any other threshold is missed.

## 8. Recording fields (per case per run; 27 §6.4)
`run_id`, `prompt_id`, `prompt_sha256`, `rule_pack_versions` (empty object: none injected), `config_key`, `provider`, `model`, `case_id`, `passed`, `assertions` (A1–A17 → pass/fail + detail), `judge_scores` (J1–J4), `judge_prompt_id`, `tokens_in`, `tokens_out`, `tokens_cached_in`, `cost_micros`, `currency`, `latency_ms`, `started_at`, `figure_kind`. Passage text is never written to a run record (IDs, offsets and hashes only).

## 9. Open points
- NUM-21: numerals must occur in the evidence; word-to-digit conversion (and Marathi/Hindi number words) is not done in v1. **REQUIRES REVIEW (3B)** after the first measurement of false downgrades on owner material.
- AK-01, CH-32 and CH-34 run at `s06_chart` and need the `agent_08.chart_facts` documents (CCR-004); until Agent 08's blueprint fixes their `fact_id` format the cases use `^f[0-9]{2,3}$` as in the blueprint input schema.
- Provisional verdict map and skip policy (blueprint §6.3–§6.4, questions Q-F1, Q-F2) are logged for the owner; if either changes, cases SKIP-30, QT-31, SUB-19, PAR-14…16, CONF-29 change by CCR to this dataset.
- EXT-37 follows the open point in the extraction README §8 (backtest figures: 13 decides).
- The dataset contains no Devanagari evidence passage; a Marathi-passage set is added when the owner's Marathi library material is ingested (3B).
