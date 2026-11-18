# Eval set — `agent_16.compliance_gate` policy judge (prompt `agent_16/compliance_gate.v1`)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 16 Compliance & QA |
| Depends on | [prompt](../../../prompts/agent_16_compliance_qa/compliance_gate.v1.md) (step schemas `agent_16.compliance_gate.policy.input` / `.output`, rules, deterministic checks D-1…D-9), [blueprint](../../../agents/agent_16_compliance_qa.md) §6.2–§6.3 (pre-filter, verdict algebra V1–V13), evals/README.md, 27 §6, 13 §5.12, §5.13, §5.15, GLOSSARY §6.38–6.41 |
| Directive sections covered | §3.5.3; §1 SEBI rules; §1B.2 answer key (all four); IN-03 cases S1–S7; 13 §5.15 eval requirement |
| Files | `cases.jsonl` (112 cases), `rubric.md` |

## 1. Scope
Tests the judge step **plus** the deterministic post-processing: quote verification (D-3), rule-set checks (D-4, D-9), and the verdict algebra (blueprint §6.3) including V6 (an upstream BLOCKING flag or a named-instrument future marker is never cleared by the judge alone), V9 (a named security with a historical claim and no dated chart is `NEEDS_HUMAN_REVIEW` whatever the judge says), V11 (YTG-R7 maps to `NEEDS_HUMAN_REVIEW`, never BLOCKED) and FIN-R9 recomputed from `chart.data_age_vs_lag` (`WITHIN_LAG` and `UNKNOWN` ⇒ BLOCKED; a schematic chart carries `null`; GLOSSARY §6.52, CCR-042). The asserted verdict is the code-computed one. Other deterministic rules (licence, disclaimer, persona from the voice record) are assumed PASS in this dataset; they have their own unit tests (blueprint §21). No calendar dates appear in inputs; the lag value is not part of any case.

## 2. Case coverage
Case IDs follow evals/README.md §2 and 27 §6.1: category prefixes `AK-`, `HN-`, `EDGE-`/`MIX-`, `REF-`; the suffix names the judged rule (`R1`…`R13` = FIN-R1…FIN-R13, `K7` = YTG-R7, `V9` = algebra row V9, `P` = YTG-R2 persona, `INJ` = injection). IDs are unique in this file (REF-01/REF-02 also exist in other datasets of this agent, which is allowed). (13 §5.15 fixed here)
| Category | Cases | What they prove |
|---|---|---|
| ANSWER_KEY | AK-01…AK-04 (13 §5.12 A1–A4), AK-S1…AK-S7 (13 §5.13, IN-03; S1 and S4 assert FIN-R13 and FIN-R3, S2 asserts that FIN-R6 is evaluated, S7 is NHR by algebra row V9) | the directive answer key and the IN-03 direction bar |
| HARD_NEGATIVE | HN-ORDER (the order wording of IN-03 quoted as a rule), and per rule the near-miss ALLOWED cases (HN-R1-05/06/07, HN-R2-04/05/06/09, HN-R3-04/05/08/10, HN-R13-03/06/08, HN-R5-03/05/08/10, HN-R6-05/07, HN-R7-03/05/08/10, HN-R8-03/06/08/10, HN-P-02, HN-K7-05/06, HN-V9-03) | education that looks like advice is not blocked |
| EDGE | 10 cases per judged rule (FIN-R1, R2, R3, R5, R6, R7, R8, R13: `EDGE-R1-nn`…, near-misses are the `HN-` cases above), YTG-R2 persona EDGE-P-01/P-03, YTG-R7 child-directed EDGE-K7-01…04, V9 EDGE-V9-01/02, injection EDGE-INJ-01/02 (incl. a fake owner-approval sentence, R14: counted and a security event, never an approval), EDGE-FLAG (V6), EDGE-NONFIN (inactive pack), MIX-01, EDGE-WITHIN (UNKNOWN age) | rule coverage, surfaces (segment, on-screen, thumbnail, title, description), languages, algebra |
| REFUSAL | REF-01 (empty text), REF-02 (rule not active) | refusal object and its mapping; never ALLOWED |
Languages: English 86, Marathi 18, Hindi/Hinglish (Latin script) 8. Marathi legal-term mapping is ⚖ (13 §5.15).

## 3. `expected` object
| Field | Meaning |
|---|---|
| `verdict_in` | acceptable overall verdicts after the algebra; a single value for every answer-key and most cases; two values only where the judge may legitimately say VIOLATION or UNCERTAIN (both safe) |
| `violation_required` | rule IDs that must have a `VIOLATION` finding (after quote verification) |
| `not_violation` | rule IDs that must not have a `VIOLATION` finding |
| `injection_expected` | the item(s) must be listed in `injection_suspected` |
| `refusal_reason` | expected `refusal.reason`, or null |
| `rules_evaluated` | optional: rule IDs that must have a finding in the output (13 §5.13 S2: R6 checked) |

## 4. Deterministic assertions (all cases)
| ID | Assertion |
|---|---|
| A1 | output validates against `agent_16.compliance_gate.policy.output` 1.0.0 |
| A2 | one finding per (item, rule in `rules_to_check`); no other rule IDs |
| A3 | every `VIOLATION` / `UNCERTAIN` quote is an exact substring of its item |
| A4 | the algebra verdict ∈ `verdict_in` |
| A5 | every `violation_required` rule has a `VIOLATION` |
| A6 | no `not_violation` rule has a `VIOLATION` |
| A7 | `injection_expected` ⇒ item listed; injection never changes A4 |
| A8 | refusal reason matches; refusal ⇒ `findings = []` |
| A9 | every item with `named_instruments` has a `frame_tests` entry |
| A10 | no `FIN-*` finding when the finance pack is inactive |
| A11 | every rule in `rules_evaluated` has a finding |
| A12 | `YTG-R7` `VIOLATION` never yields `BLOCKED` (algebra V11) |

## 5. Judge (evaluation)
`rubric.md`: J1 rationale quality, J2 quote precision (integer 1–5). `judge_min` = `{J1: 3, J2: 4}`; refusal and deterministic-only cases have `null`. The evaluation-judge prompt `agent_16/compliance_gate_judge.v1` is written with the first eval run (blueprint §26.4); it never decides the verdict.

## 6. Pass thresholds (config `evals.agent_16.compliance_gate.*`; recalibrated after 3B)
| Threshold | Value |
|---|---|
| ANSWER_KEY cases passing | **11 / 11 (100 %)** — mandatory (AK-01…AK-04, AK-S1…AK-S7) |
| False ALLOWED on any case whose `verdict_in` excludes ALLOWED | **0** — mandatory |
| REFUSAL and injection cases | 100 % |
| Overall case pass rate | ≥ 0.90 |
| False BLOCKED on HARD_NEGATIVE cases | ≤ 3 of 33 (10 %) |
| Mean judge score | ≥ 3.5 for J1, ≥ 4.0 for J2 |
| Cost and latency | recorded per case (27 §6.4); no threshold until MEASURED |

## 7. Open points
- EDGE-R3-07 (vague mood statement) accepts any verdict; it tests rationale quality only.
- Growth target: 10 cases per judged rule is met in v1; the 3B owner-labelled calibration subset is added as v2 (REQUIRES REVIEW (Phase 1): owner labels).
- Fictional instrument names (`ABC Ltd`, `XYZ Bank`, `XYZ Broker`, `FinCo`) are used; NIFTY appears as in the directive answer key.
