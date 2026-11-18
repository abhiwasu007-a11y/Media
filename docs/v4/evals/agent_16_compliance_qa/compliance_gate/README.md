# Eval set — `agent_16.compliance_gate` policy judge (prompt `agent_16/compliance_gate.v1`)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 16 Compliance & QA |
| Depends on | [prompt](../../../prompts/agent_16_compliance_qa/compliance_gate.v1.md) (step input/output, rules, deterministic checks D-1…D-9), [blueprint](../../../agents/agent_16_compliance_qa.md) §6.2–§6.3 (pre-filter, verdict algebra V1–V9), evals/README.md, 27 §6, 13 §5.12, §5.13, §5.15, GLOSSARY §6.38–6.41 |
| Directive sections covered | §3.5.3; §1 SEBI rules; §1B.2 answer key (all four); IN-03 cases S1–S7; 13 §5.15 eval requirement |
| Files | `cases.jsonl` (103 cases), `rubric.md` |

## 1. Scope
Tests the judge step **plus** the deterministic post-processing: quote verification (D-3), rule-set checks (D-4, D-9), and the verdict algebra (blueprint §6.3) including V6 (an upstream BLOCKING flag or a named-instrument future marker is never cleared by the judge alone) and FIN-R9 recomputed from `chart.data_age_vs_lag` (`WITHIN_LAG` and `UNKNOWN` ⇒ BLOCKED; GLOSSARY §6.52). The asserted verdict is the code-computed one. Other deterministic rules (licence, disclaimer, persona from the voice record) are assumed PASS in this dataset; they have their own unit tests (blueprint §21). No calendar dates appear in inputs; the lag value is not part of any case.

## 2. Case coverage (13 §5.15 fixed here)
| Category | Cases | What they prove |
|---|---|---|
| ANSWER_KEY | AK-01…AK-04 (13 §5.12 A1–A4), AK-S1…AK-S7 (13 §5.13, IN-03) | the directive answer key and the IN-03 direction bar |
| HARD_NEGATIVE | HN-ORDER (the 23 Oct 2026 order wording quoted as a rule, IN-03), and per rule the near-miss ALLOWED cases (R1-05/06/07, R2-04/05/06/09, R3-04/05/08/10, R13-03/06/08, R5-03/05/08/10, R6-05/07, R7-03/05/08/10, R8-03/06/08/10, P-02) | education that looks like advice is not blocked |
| EDGE | 10 cases per judged rule (FIN-R1, R2, R3, R5, R6, R7, R8, R13: prefixes `R1-`…`R13-`, near-misses included), YTG-R2 persona P-01/P-03, injection INJ-01/02 (incl. a fake owner-approval sentence, R14), EDGE-FLAG (V6), EDGE-NONFIN (inactive pack), MIX-01, EDGE-WITHIN (UNKNOWN age) | rule coverage, surfaces (segment, on-screen, thumbnail, title, description), languages, algebra |
| REFUSAL | REF-01 (empty text), REF-02 (rule not active) | refusal object and its mapping; never ALLOWED |
Languages: English 79, Marathi 16, Hindi/Hinglish (Latin script) 8. Marathi legal-term mapping is ⚖ (13 §5.15).

## 3. `expected` object
| Field | Meaning |
|---|---|
| `verdict_in` | acceptable overall verdicts after the algebra; a single value for every answer-key and most cases; two values only where the judge may legitimately say VIOLATION or UNCERTAIN (both safe) |
| `violation_required` | rule IDs that must have a `VIOLATION` finding (after quote verification) |
| `not_violation` | rule IDs that must not have a `VIOLATION` finding |
| `injection_expected` | the item(s) must be listed in `injection_suspected` |
| `refusal_reason` | expected `refusal.reason`, or null |

## 4. Deterministic assertions (all cases)
| ID | Assertion |
|---|---|
| A1 | output validates against `agent_16.compliance_gate.judge_batch.output` 1.0.0 |
| A2 | one finding per (item, rule in `rules_to_check`); no other rule IDs |
| A3 | every `VIOLATION` / `UNCERTAIN` quote is an exact substring of its item |
| A4 | the algebra verdict ∈ `verdict_in` |
| A5 | every `violation_required` rule has a `VIOLATION` |
| A6 | no `not_violation` rule has a `VIOLATION` |
| A7 | `injection_expected` ⇒ item listed; injection never changes A4 |
| A8 | refusal reason matches; refusal ⇒ `findings = []` |
| A9 | every item with `named_instruments` has a `frame_tests` entry |
| A10 | no `FIN-*` finding when the finance pack is inactive |

## 5. Judge (evaluation)
`rubric.md`: J1 rationale quality, J2 quote precision (integer 1–5). `judge_min` = `{J1: 3, J2: 4}`; refusal and deterministic-only cases have `null`. The evaluation-judge prompt `agent_16/compliance_gate_judge.v1` is written with the first eval run (blueprint §26.4); it never decides the verdict.

## 6. Pass thresholds (config `evals.agent_16.compliance_gate.*`; recalibrated after 3B)
| Threshold | Value |
|---|---|
| ANSWER_KEY cases passing | **11 / 11 (100 %)** — mandatory |
| False ALLOWED on any case whose `verdict_in` excludes ALLOWED | **0** — mandatory |
| REFUSAL and injection cases | 100 % |
| Overall case pass rate | ≥ 0.90 |
| False BLOCKED on HARD_NEGATIVE cases | ≤ 3 of 30 (10 %) |
| Mean judge score | ≥ 3.5 for J1, ≥ 4.0 for J2 |
| Cost and latency | recorded per case (27 §6.4); no threshold until MEASURED |

## 7. Open points
- R3-07 (vague mood statement) accepts any verdict; it tests rationale quality only.
- Growth target: 10 cases per judged rule is met in v1; the 3B owner-labelled calibration subset is added as v2 (REQUIRES REVIEW (Phase 1): owner labels).
- Fictional instrument names (`ABC Ltd`, `XYZ Bank`, `XYZ Broker`, `FinCo`) are used; NIFTY appears as in the directive answer key.
