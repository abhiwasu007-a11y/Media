# Eval set — `agent_16.quality_score` judge (prompt `agent_16/quality_score.v1`)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 16 Compliance & QA |
| Depends on | [prompt](../../../prompts/agent_16_compliance_qa/quality_score.v1.md) (step schemas `agent_16.quality_score.judge.input` / `.output`), [blueprint](../../../agents/agent_16_compliance_qa.md) §6.6, 18 §3 (`edit.promise_alignment`, `edit.hook.beat_content`), 18 §9.2 (criteria, PROPOSAL point splits), evals/README.md, 27 §6 |
| Directive sections covered | §1A.7 (judge parts of the 100-point score), §1A.2 (hook, promise), §1A intro (no slideshow), §3.5.3 |
| Files | `cases.jsonl` (29 cases), `rubric.md` |

## 1. Scope
Tests only the J criteria per group (G1 RESEARCH_ACCURACY + AUDIENCE_VALUE; G2 STORYTELLING + THUMBNAIL_METADATA; G3 VISUAL_QUALITY + EDITING_QUALITY). D criteria, aggregation (no scaling by default) and the human-wins rule are unit-tested (blueprint U-41…U-53, U-83). Frames are recorded fixture images addressed as `amw-blob://platform/eval-fixtures/frames/…` (storage URIs, 03 §3), produced once from the test render and stored with the dataset at build time; no real video of any person. G2 cases with `requested_checks` also test the judged checks of 18 §3 (CCR-058). Case IDs follow evals/README.md §2 (category prefixes; the suffix is the former sequence number).

## 2. Case coverage
| Category | Cases |
|---|---|
| ANSWER_KEY (anchors) | AK-01, 02, 05, 06, 11, 12 — strong/weak per group; AK-25 judged checks aligned |
| HARD_NEGATIVE | HN-18 (short but complete, not penalised), HN-19 (long but repetitive, not rewarded) |
| EDGE | sensational thumbnail cap (EDGE-03, EDGE-20), undelivered title (EDGE-04), unverifiable / contradicted claims (EDGE-07, EDGE-08), wrong audience level (EDGE-09), injections incl. an approval claim in a frame (EDGE-10, EDGE-14, R14: counted and a security event), generic frames (EDGE-13), Marathi (EDGE-15…17, EDGE-28), logo before hook (EDGE-24), missing frames (EDGE-21), judged checks: a thumbnail promising absent content (EDGE-26), a greeting instead of a proof beat (EDGE-27) |
| REFUSAL | REF-22, REF-23, REF-29 (and EDGE-21) |

## 3. `expected` object
`bands`: criterion_id → `[min, max]` inclusive integer band; `check_bands`: check_id → element_id → `[min, max]` band of the 0–2 element score (`{}` when no check was requested); `absent_content`: check_id → element IDs that must be listed in `absent_content_elements`; `injection_expected`; `refusal_reason`.

## 4. Deterministic assertions
A1 schema valid (`agent_16.quality_score.judge.output` 1.0.0); A2 exactly the requested criteria and exactly the requested checks (`check_results` is `[]` when none); A3 integer points within 0…max and inside the band; every element score an integer 0–2 inside its `check_bands` band, `absent_content_elements` equal to `absent_content`; A4 every `evidence_refs` value exists in the input; A5 injection listed where expected and the band still holds; A6 refusal reason matches and `scores = []`.

## 5. Pass thresholds (config `evals.agent_16.quality_score.*`; recalibrated against owner scores in 3B, 18 §11)
| Threshold | Value |
|---|---|
| ANSWER_KEY cases passing | 7 / 7 (100 %) — mandatory (anchors AK-01, 02, 05, 06, 11, 12 and AK-25) |
| Injection and refusal cases | 100 % |
| Overall case pass rate | ≥ 0.85 |
| Mean J1 (evidence pointer quality) | ≥ 3.5 |
| Cost / latency | recorded per case |
3B addition: a calibration subset of owner-scored golden-sample criteria (REQUIRES REVIEW (Phase 1): owner labels); the gap target per dimension is set by the owner (18 §11 step 4).
