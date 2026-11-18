# Judge rubric — `agent_05.script_draft` step `plan`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 05 |
| Used by | eval gate (27 §5); judge prompt `agent_05/script_draft_judge.v1` (written with the first build ticket for the eval gate) |
| Scope | Subjective quality only. Schema, refusals, rule IDs, counts, shares, terms, promise key terms, history and budget checks are deterministic (README §4) and are **not** judged. |

The judge receives the case input, the step output (after code checks) and this rubric, and returns integer scores 1–5 per criterion with a one-sentence justification each. Scores below the case's `judge_min` fail the case.

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Hook quality** — each option's proof beat shows the title's promise with one concrete example, the why beat names a viewer problem or payoff, the covers beat says what the video contains; options differ in style and angle | all options do what their beats say and are clearly different | one option is weaker or close to another | beats mostly right but generic, or two options nearly the same | a proof beat only states a claim without an example, or a why beat is vague | beats do not match their names, or options are rewordings |
| **J2 Promise coherence** — one promise that the title, the proof beats, the description draft and the thumbnail brief repeat, and the sections can deliver | all repeat the same promise; nothing promised is missing from the plan | one text drifts slightly | the promise is stated but a section or the thumbnail brief adds a second idea | a text promises something no section delivers | no single promise; or a guaranteed outcome or urgency appears |
| **J3 Structure fit** — the sections follow this topic's logic, not a fixed template; order teaches in dependency order; the case study (if any) sits where a past chart teaches the concept; the recap is last | order and sizes clearly follow the topic | one section is out of order or oversized | structure is acceptable but generic | a needed step is missing or a section is padding | structure ignores the concepts or the duration |
| **J4 Originality of angle and examples** — `own_words_angle` and `original_example_idea` are the model's own, concrete and different per concept; no mirroring of a brief's wording or order | all ideas concrete and original | one idea generic | several ideas generic but not copied | an idea repeats the brief's summary order or wording | ideas copy the briefs |

Calibration: before use in CI, two humans label a fixed subset (at least 10 cases of this dataset); the judge must agree within ±1 point on ≥ 90 % of criterion scores (design default, recalibrated after the pilot). The calibration result is stored with the judge prompt version.
