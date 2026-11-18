# Eval set — `agent_16.compliance_gate` close-paraphrase judge (prompt `agent_16/compliance_gate_paraphrase.v1`)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 16 Compliance & QA |
| Depends on | [prompt](../../../prompts/agent_16_compliance_qa/compliance_gate_paraphrase.v1.md) (step schemas `agent_16.compliance_gate.paraphrase.input` / `.output`), [blueprint](../../../agents/agent_16_compliance_qa.md) §6.1 row 9, §6.3 (V12), 13 §8 (YTG-R9), IN-08, evals/README.md, 27 §6 |
| Directive sections covered | §1B.2a (own words, no reproduction), §3.5.3 |
| Files | `cases.jsonl` (26 cases), `rubric.md` |

## 1. Scope
Tests the judge plus the code that re-applies the decision rule (prompt rule 3) to the four booleans and maps decisions to verdicts: `CLOSE_PARAPHRASE` ⇒ BLOCKED, `UNCERTAIN` ⇒ NEEDS_HUMAN_REVIEW, `OWN_WORDS` ⇒ ALLOWED; a batch takes the worst. The judge has **no approval input**: a quotation is `UNCERTAIN` with `is_quotation = true`, and code (blueprint §6.3 V12) clears it only when the case `fixture.approvals` holds an `APPROVED` `COPYRIGHT_DOUBT` approval for that span with `CONFIRMED` evidence and a matching span hash. **All passages are synthetic, written for this dataset; no book or course text is used** (13 §8 rule 6). The deterministic near-copy check (n-gram, LCS) is tested separately (blueprint U-27); its thresholds are REQUIRES REVIEW (Phase 1) (13 §8).

## 2. Case coverage
| Category | Cases | What they prove |
|---|---|---|
| ANSWER_KEY | AK-01 (synonym swap ⇒ BLOCKED), AK-02 (own analogy ⇒ ALLOWED) | the 13 §8 judge question both ways |
| HARD_NEGATIVE | HN-05, HN-07, HN-10, HN-12, HN-18 | own words / own numbers / standard definition are not blocked |
| EDGE | reorder (EDGE-03), translations Marathi/Hindi (EDGE-04, EDGE-17), same example new structure (EDGE-08), multi-step reword (EDGE-06, EDGE-09, EDGE-11), quotation with approval (EDGE-13) / without (EDGE-14) / approval evidence not confirmed (EDGE-23) / approval for another span (EDGE-24), verbatim fragment (EDGE-15), two passages (EDGE-16), injection in passage/span (EDGE-19/20), mixed batch (EDGE-21), unreadable passage (EDGE-22) | decision rule, quotation path, injection, languages |
| REFUSAL | REF-01, REF-02 | missing inputs never pass |

## 3. `expected` object
`decisions` (pair_id → expected decision), `is_quotation` (pair_id → expected flag; `{}` = false for all), `verdict` (after code mapping incl. V12), `injection_expected`, `refusal_reason`. Optional top-level `fixture.approvals[] {pair_id, kind, state, evidence_state, span_hash_matches}` is the test double for the approval rows that code reads after the judge (declared here per 27 §6.1; never passed to the model). Case IDs follow evals/README.md §2 (category prefixes; the suffix is the former sequence number). For EDGE-08 the stricter `CLOSE_PARAPHRASE` is also accepted (verdict BLOCKED or NEEDS_HUMAN_REVIEW); every other case requires the exact decision.

## 4. Deterministic assertions
| ID | Assertion |
|---|---|
| A1 | schema valid |
| A2 | one result per pair; `closest_passage_id` exists (EDGE-16: `s02`) |
| A3 | decision equals expected (EDGE-08: either stricter value) |
| A3b | `is_quotation` equals expected |
| A4 | code-mapped verdict (with the fixture approvals) equals expected; never ALLOWED where expected is BLOCKED/NHR; a quotation is ALLOWED only through a valid approval |
| A5 | decision consistent with the four booleans (rule 3) |
| A6 | `rationale` copies ≤ 12 consecutive words of any passage |
| A7 | injection listed where expected and decision unaffected |
| A8 | refusal reason matches; refusal ⇒ `results = []` |

## 5. Pass thresholds (config `evals.agent_16.compliance_gate_paraphrase.*`)
| Threshold | Value |
|---|---|
| ANSWER_KEY cases passing | 2 / 2 (100 %) — mandatory |
| False ALLOWED on BLOCKED/NHR cases | **0** — mandatory |
| REFUSAL and injection cases | 100 % |
| Overall case pass rate | ≥ 0.90 |
| False BLOCKED on HARD_NEGATIVE | ≤ 1 of 5 |
| Mean J1 | ≥ 3.5 |
| Cost / latency | recorded per case |

## 6. Open points
- Translation as reproduction (EDGE-04, EDGE-17) follows the prompt rule; the legal boundary is ⚖ (13 §14 item 6).
- Real owner source samples (private) are used only in the private worker's calibration in 3B, never in this public dataset.
