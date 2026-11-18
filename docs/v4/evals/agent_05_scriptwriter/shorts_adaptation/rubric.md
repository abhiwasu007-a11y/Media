# Judge rubric — `agent_05.shorts_adaptation`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 05 |
| Used by | eval gate (27 §5); judge prompt `agent_05/script_draft_judge.v1` (shared judge shell, one rubric per dataset) |
| Scope | Subjective quality only. Provenance, new-content check, flags, counts, durations, rule scans and language are deterministic (README §4). |

Scores are integers 1–5 with a one-sentence justification each; below the case's `judge_min` fails the case.

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Stands alone** — a viewer who has not seen the long video understands the short from its first hook to its end | fully self-contained | one reference needs context | understandable but a term or step is assumed | confusing without the long video | only meaningful with the long video |
| **J2 Hook quality** — options differ in style; each proves the short's promise with something concrete from the parent inside the hook budget | all options concrete and different | one weaker option | generic but correct | an option states a claim without proof | rewordings, or a hook promises more than the cut delivers |
| **J3 Fidelity and economy** — the cut keeps the parent's framing (past tense, lesson last, invented-numbers statement) and uses only parent content; nothing padded | faithful and tight | one sentence slightly stretched | faithful but loose | framing weakened (for example the lesson dropped) | meaning changed |
| **J4 Short pacing** — scenes are re-written for vertical pacing; the first beat lands fast; tags and visual intent fit | pacing clearly re-edited | one slow scene | little re-editing (close to a crop) | pacing copied from the long form | a long-form transcript in short form |

Calibration: two humans label a fixed subset (at least 10 cases); the judge must agree within ±1 point on ≥ 90 % of criterion scores (design default); result stored with the judge prompt version.
