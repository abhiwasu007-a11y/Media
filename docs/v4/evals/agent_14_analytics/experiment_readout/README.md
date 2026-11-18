# Eval set — experiment gates of the learning loop (no LLM; deterministic golden dataset)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 14 Analytics |
| MVP | **3C** · Tier 0 |
| Task types | `agent_14.experiment_proposal` and `agent_14.experiment_readout` (both pending CCR; 15 §14 item 2) |
| Prompt | **none**: proposal gating, sufficiency, critical-key refusal and result validation are deterministic (blueprint §6). The hypothesis sentence is built from a template, not a model. |
| Depends on | 15_LEARNING_LOOP.md §4 (sufficiency), §5 (critical policies), §6 (record, kinds), §7 (state machine), §8 (Studio test); GLOSSARY_AND_IDS.md §6.35–6.36 |
| Directive sections covered | §3.3 Learning loop (no automatic change to critical policies; no significance claims without sufficient data) |
| Files | `cases.jsonl` (32 cases), `rubric.md` (states that no judge applies) |

## 1. Scope
Tests three pure functions of `ExperimentGate`: `readout_gate` (sufficiency and labels), `proposal_gate` (critical-key refusal, one factor, one primary metric, conflicts, data gate), `studio_result_validate` (human entry of a YouTube Studio test result). The numeric thresholds in `config` (`learning.min_sample_size`, `learning.min_duration_ms`, `learning.critical_key_patterns`) are **test fixtures**, not proposals: the real values are REQUIRES REVIEW (15 §4) and the dataset stays valid for any values because every case carries them. No statistical significance method is tested; confidence is computed only by a method that 15 §4 leaves to Phase 1.

## 2. Case coverage
| Category | Cases | What they prove |
|---|---|---|
| ANSWER_KEY | C-01…C-07 | the loop cannot propose changes to publish threshold, price-data lag, budgets, model routing tier, night window, rule pack text, tenant isolation (15 §5) |
| POSITIVE | S-01, S-02, C-08…C-10, T-01 | sufficient data reads out with a `MEASURED` label; adjustable keys are accepted and need an `EXPERIMENT` approval; a valid Studio entry is accepted |
| HARD_NEGATIVE | S-03, S-04, C-11, T-06 | partial data never yields confidence or a decision; a prefix pattern is not a substring search; a declared winner must be a known variant |
| EDGE | S-05…S-08, P-01…P-07, T-02…T-05 | abort handling; unset config fails closed; state machine; inconclusive end; conflicting experiments; multiple factors; small channel; two primary metrics; invalid hypothesis; sample below minimum; Studio entry validation |

## 3. `expected` object
Function-specific. `readout_gate`: `ready`, `label`, `confidence_allowed`, `decision_allowed`, `final_state`, `decision`, or `status` + `error_code`. `proposal_gate`: `accepted`, `reason`, `approval_required`. `studio_result_validate`: `accepted`, `reason`, `decision`, `confidence`, `label`.

## 4. Deterministic assertions (all cases)
| ID | Assertion |
|---|---|
| X1 | output equals `expected` on every listed field |
| X2 | `confidence_allowed = false` ⇒ no `confidence` value is produced anywhere in the result |
| X3 | a rejected proposal creates no `experiments` row and no approval request |
| X4 | an accepted proposal sets `state = PROPOSED` only; it never sets `APPROVED_TO_RUN` or `APPLIED` (those need a human approval, 15 §7) |
| X5 | no function reads a default for an unset config value; unset ⇒ `PERMANENT.CONFIG_INVALID` |
| X6 | `studio_result_validate` never computes a confidence for `TITLE_THUMBNAIL_STUDIO_TEST` (15 §8) |

## 5. Judge
None; `judge_min` is `null` for every case (blueprint §26).

## 6. Pass thresholds (config `evals.agent_14.experiment_readout.*`)
| Threshold | Value |
|---|---|
| All cases | **32 / 32** — mandatory (deterministic) |
| ANSWER_KEY (critical keys) | **7 / 7** — mandatory |
| Mutation check: removing any critical pattern from the fixture makes the matching case fail | required in CI (27 §8) |

## 7. Recording fields
`run_id`, `case_id`, `passed`, `assertions` (X1–X6), `started_at`, code version.

## 8. Open points
- The authoritative critical-key list is owned by 15 §5 and the key names by the config registry; the patterns in the fixtures are illustrative of the classes listed there.
- Whether a Studio-reported share tolerance is needed (rounding in the Studio display) is REQUIRES REVIEW; cases use exact sums only.
