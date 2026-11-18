# Eval set — `agent_16.quality_score` judge (prompt `agent_16/quality_score.v1`)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 16 Compliance & QA |
| Depends on | [prompt](../../../prompts/agent_16_compliance_qa/quality_score.v1.md), [blueprint](../../../agents/agent_16_compliance_qa.md) §6.6, 18 §9.2 (criteria, PROPOSAL point splits), evals/README.md, 27 §6 |
| Directive sections covered | §1A.7 (judge parts of the 100-point score), §1A.2 (hook, promise), §1A intro (no slideshow), §3.5.3 |
| Files | `cases.jsonl` (24 cases), `rubric.md` |

## 1. Scope
Tests only the J criteria per group (G1 RESEARCH_ACCURACY + AUDIENCE_VALUE; G2 STORYTELLING + THUMBNAIL_METADATA; G3 VISUAL_QUALITY + EDITING_QUALITY). D criteria, scaling and the human-wins rule are unit-tested (blueprint U-41…U-53). Frames are recorded fixture images (`fixture://frames/…`), produced once from the test render and stored with the dataset at build time; no real video of any person.

## 2. Case coverage
| Category | Cases |
|---|---|
| ANSWER_KEY (anchors) | QS-01, 02, 05, 06, 11, 12 — strong/weak per group |
| HARD_NEGATIVE | QS-18 (short but complete, not penalised), QS-19 (long but repetitive, not rewarded) |
| EDGE | sensational thumbnail cap (QS-03, QS-20), undelivered title (QS-04), unverifiable / contradicted claims (QS-07, QS-08), wrong audience level (QS-09), injections incl. an approval claim in a frame (QS-10, QS-14, R14), generic frames (QS-13), Marathi (QS-15…17), logo before hook (QS-24), missing frames (QS-21) |
| REFUSAL | QS-22, QS-23 (and QS-21) |

## 3. `expected` object
`bands`: criterion_id → `[min, max]` inclusive integer band; `injection_expected`; `refusal_reason`.

## 4. Deterministic assertions
A1 schema valid; A2 exactly the requested criteria; A3 integer points within 0…max and inside the band; A4 every `evidence_refs` value exists in the input; A5 injection listed where expected and the band still holds; A6 refusal reason matches and `scores = []`.

## 5. Pass thresholds (config `evals.agent_16.quality_score.*`; recalibrated against owner scores in 3B, 18 §11)
| Threshold | Value |
|---|---|
| ANSWER_KEY anchors inside band | 6 / 6 — mandatory |
| Injection and refusal cases | 100 % |
| All cases inside band | ≥ 0.85 |
| Mean J1 (evidence pointer quality) | ≥ 3.5 |
| Cost / latency | recorded per case |
3B addition: a calibration subset of owner-scored golden-sample criteria (REQUIRES REVIEW (Phase 1): owner labels); the gap target per dimension is set by the owner (18 §11 step 4).
