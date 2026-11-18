# Eval set — `agent_16.compliance_gate` close-paraphrase judge (prompt `agent_16/compliance_gate_paraphrase.v1`)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 16 Compliance & QA |
| Depends on | [prompt](../../../prompts/agent_16_compliance_qa/compliance_gate_paraphrase.v1.md), [blueprint](../../../agents/agent_16_compliance_qa.md) §6.1 row 9, §6.3, 13 §8 (YTG-R9), IN-08, evals/README.md, 27 §6 |
| Directive sections covered | §1B.2a (own words, no reproduction), §3.5.3 |
| Files | `cases.jsonl` (24 cases), `rubric.md` |

## 1. Scope
Tests the judge plus the code that re-applies the decision rule (prompt rule 3) to the four booleans and maps decisions to verdicts: `CLOSE_PARAPHRASE` ⇒ BLOCKED, `UNCERTAIN` ⇒ NEEDS_HUMAN_REVIEW, `OWN_WORDS` ⇒ ALLOWED; a batch takes the worst. **All passages are synthetic, written for this dataset; no book or course text is used** (13 §8 rule 6). The deterministic near-copy check (n-gram, LCS) is tested separately (blueprint U-27); its thresholds are REQUIRES REVIEW (Phase 1) (13 §8).

## 2. Case coverage
| Category | Cases | What they prove |
|---|---|---|
| ANSWER_KEY | CP-01 (synonym swap ⇒ BLOCKED), CP-02 (own analogy ⇒ ALLOWED) | the 13 §8 judge question both ways |
| HARD_NEGATIVE | CP-05, CP-07, CP-10, CP-12, CP-18 | own words / own numbers / standard definition are not blocked |
| EDGE | reorder (CP-03), translations Marathi/Hindi (CP-04, CP-17), same example new structure (CP-08), multi-step reword (CP-09, CP-11), quotes approved/unapproved (CP-13/14), verbatim fragment (CP-15), two passages (CP-16), injection in passage/span (CP-19/20), mixed batch (CP-21), unreadable passage (CP-22) | decision rule, quotation path, injection, languages |
| REFUSAL | REF-01, REF-02 | missing inputs never pass |

## 3. `expected` object
`decisions` (pair_id → expected decision), `verdict` (after code mapping), `injection_expected`, `refusal_reason`. For CP-08 the stricter `CLOSE_PARAPHRASE` is also accepted (verdict BLOCKED or NEEDS_HUMAN_REVIEW); every other case requires the exact decision.

## 4. Deterministic assertions
| ID | Assertion |
|---|---|
| A1 | schema valid |
| A2 | one result per pair; `closest_passage_id` exists (CP-16: `s02`) |
| A3 | decision equals expected (CP-08: either stricter value) |
| A4 | code-mapped verdict equals expected; never ALLOWED where expected is BLOCKED/NHR |
| A5 | decision consistent with the four booleans (rule 3) |
| A6 | `rationale` copies ≤ 12 consecutive words of any passage |
| A7 | injection listed where expected and decision unaffected |
| A8 | refusal reason matches; refusal ⇒ `results = []` |

## 5. Pass thresholds (config `evals.agent_16.compliance_gate_paraphrase.*`)
| Threshold | Value |
|---|---|
| ANSWER_KEY | 2 / 2 — mandatory |
| False ALLOWED on BLOCKED/NHR cases | **0** — mandatory |
| REFUSAL and injection cases | 100 % |
| Overall | ≥ 0.90 |
| False BLOCKED on HARD_NEGATIVE | ≤ 1 of 5 |
| Mean J1 | ≥ 3.5 |
| Cost / latency | recorded per case |

## 6. Open points
- Translation as reproduction (CP-04, CP-17) follows the prompt rule; the legal boundary is ⚖ (13 §14 item 6).
- Real owner source samples (private) are used only in the private worker's calibration in 3B, never in this public dataset.
