# Judge rubric — `agent_09.shot_direction`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 09 |
| Used by | eval gate (27 §5); judge prompt `agent_09/shot_direction_judge.v1` (to be written with the first eval run) |
| Scope | Subjective quality only. Status, flags, vocabulary, text IDs, devices, anchors and schema are checked deterministically (README §4) and are **not** judged. |

The judge receives the case input, the step output and this rubric, and returns integer scores 1–5 per criterion with a one-sentence justification each. Scores below the case's `judge_min` fail the case.

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Relevance** — the picture fits the narration and the scene's visual intent without adding claims | every direction clearly supports its sentence | one direction is generic but fits | one direction only loosely fits | a direction adds a meaning the narration does not carry | pictures unrelated to the narration |
| **J2 Filmability** — `intent_text` names subject, setting, action, light or shot type; a stock library or a code template could realise it | every description is concrete and realisable | one description is slightly vague | several vague, still realisable | a description cannot be filmed or built (abstract, contradictory) | descriptions are slogans or instructions |
| **J3 Variety** — adjacent slots differ in subject, framing or motion; the first slot differs from `previous_tail` | all neighbours clearly differ | one pair is similar | two similar pairs | most neighbours repeat the same picture | the same picture throughout |
| **J4 Rationale and device quality** — `rationale` is short, factual and specific; an interrupt device and picture really break the rhythm | all rationales specific; interrupts clearly distinct from the previous slot | one rationale generic | rationales generic but correct | a rationale is wrong or an interrupt looks like the slot before it | rationale missing or misleading |

Calibration: before the judge is used in CI, two humans label a fixed calibration subset (at least 10 cases from `cases.jsonl`); the judge must agree within ±1 point on ≥ 90 % of criterion scores (design default, recalibrated after the pilot). The calibration result is stored with the judge prompt version.
