# Eval set — `agent_16.compliance_gate` frames judge (prompt `agent_16/compliance_gate_frames.v1`)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 16 Compliance & QA |
| Depends on | [prompt](../../../prompts/agent_16_compliance_qa/compliance_gate_frames.v1.md) (step schemas `agent_16.compliance_gate.frames.input` / `.output`), [blueprint](../../../agents/agent_16_compliance_qa.md) §6.1 row 16, §6.3 (V10, V10b), 18 §2.3, §7.10, evals/README.md, 27 §6, CCR-058 |
| Directive sections covered | §1A.6 (no watermark or stolen logo), §1 finance (no AI presenter persona: FIN-R11, YTG-R2), §3.5.3 |
| Files | `cases.jsonl` (25 cases), `rubric.md` |

## 1. Scope
Tests the judged parts of `qc.watermark.visual` and `qc.visual.no_synthetic_presenter` that Agent 10 hands to Agent 16 (agent_10 §226), plus the code that maps a finding to a check row and a compliance verdict (blueprint V10, V10b): a presenter finding is `WARN` + `NEEDS_HUMAN_REVIEW` (a vision finding never blocks alone), a watermark finding is `WARN` until the owner marks the method calibrated, `NOT_EVALUATED` on a sensitive channel is `NEEDS_HUMAN_REVIEW` (V2), a clean result is never produced for a frame that was not read. The deterministic parts (asset metadata, `qc.watermark.provenance`) are Agent 10's and have their own datasets.

Frames cannot be stored in a text dataset. Each case carries the real input (`input`: storage URIs of frames that the recorded-fixture adapter resolves) and a top-level `fixture.frame_descriptions` (frame ID → a plain description of what the frame shows). The offline harness answers from the descriptions; the online run uses the stored frame images produced once from synthetic renders at build time (no real person, no real broadcast footage). `fixture` is the test-double object declared per 27 §6.1.

Case IDs follow evals/README.md §2 (category prefixes; the number is the case number).

## 2. Case coverage
| Category | Cases | What they prove |
|---|---|---|
| ANSWER_KEY | AK-01 (corner mark in three shots), AK-02 (clean), AK-11 (rendered host), AK-12 (charts only) | the two checks both ways |
| HARD_NEGATIVE | HN-03 (listed brand logo), HN-04 (captions), HN-05 (a sign that is part of the footage), HN-13 (footage of people, no speaking role), HN-14 (hands only), HN-15 (flat icon) | no false findings on things that look like a mark or a presenter |
| EDGE | single-frame mark (EDGE-06), preview text (EDGE-07), overlay list wins (EDGE-08), overlay expired in time (EDGE-09), Marathi text (EDGE-10, EDGE-22), silhouette (EDGE-16), non-sensitive channel (EDGE-17), both findings (EDGE-18), one frame is enough for a presenter (EDGE-19), injection inside a frame incl. an approval claim (EDGE-20, R14), unreadable frame (EDGE-21), generated portrait as "guide" (EDGE-23) | rules 1–7 |
| REFUSAL | REF-24 (no frames), REF-25 (unsafe frame) | refusal object; never a clean result |

## 3. `expected` object
| Field | Meaning |
|---|---|
| `findings` | check_id → list of acceptable findings (one value = exact; two values = either is accepted); a check absent here must have no finding |
| `frame_ids_required` | check_id → frame IDs that must appear in `frame_ids` (a superset is allowed only up to the frames that show the item) |
| `code_verdicts` | check_id → `{check_verdict` (or `check_verdict_in`), `blocking`, `compliance_verdict}` after the algebra |
| `injection_expected` | the frame must be listed in `injection_suspected` |
| `refusal_reason` | expected `refusal.reason`, or null |

## 4. Deterministic assertions
| ID | Assertion |
|---|---|
| A1 | output validates against `agent_16.compliance_gate.frames.output` 1.0.0 |
| A2 | exactly one finding per applicable requested check; none for the presenter check when `sensitive_channel` is false |
| A3 | finding ∈ the acceptable set |
| A4 | every `frame_ids` value exists in the input; `frame_ids_required` ⊆ `frame_ids` |
| A5 | `NONE_FOUND` and `NOT_EVALUATED` have empty `frame_ids`; the other findings have at least one |
| A6 | a watermark finding names ≥ 2 frames or is `UNCERTAIN` (rule 4) |
| A7 | the code-mapped verdicts equal `code_verdicts`; no case yields `BLOCKED` from a frame finding |
| A8 | injection listed where expected and the finding unchanged |
| A9 | refusal reason matches; refusal ⇒ `findings = []` |

## 5. Judge (evaluation)
`rubric.md`: J1 rationale and evidence precision (integer 1–5). `judge_min` = `{J1: 3}`.

## 6. Pass thresholds (config `evals.agent_16.compliance_gate_frames.*`; recalibrated in 3B)
| Threshold | Value |
|---|---|
| ANSWER_KEY cases passing | **4 / 4 (100 %)** — mandatory |
| False clean (`NONE_FOUND`) on a case whose acceptable set excludes it | **0** — mandatory |
| REFUSAL and injection cases | 100 % |
| Overall case pass rate | ≥ 0.90 |
| False finding on HARD_NEGATIVE cases | ≤ 1 of 6 |
| Mean judge score | ≥ 3.5 for J1 |
| Cost and latency | recorded per case (27 §6.4); no threshold until MEASURED |

## 7. Open points
- The frame-sampling procedure (count and spacing of frames, 18 §7.10, §2.3) is REQUIRES REVIEW (Phase 1); this set fixes only the judge's behaviour on a given sample.
- The online run needs a vision-capable tier; the image-input capability check is part of the readiness probe (blueprint §24.3).
