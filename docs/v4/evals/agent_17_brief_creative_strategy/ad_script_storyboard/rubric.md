# Judge rubric — `agent_17.ad_script_storyboard`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 17 |
| Used by | eval gate (27 §5); judge prompt `agent_17/ad_script_storyboard_judge.v1` (written at build time) |
| Scope | Subjective quality only. Schema, counts, references, flags, names and wording limits are checked deterministically (README §4) and are **not** judged. |

The judge receives the case input, the step output and this rubric, and returns integer scores 1-5 per criterion with a one-sentence justification each. Scores below the case's `judge_min` fail the case.

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Hook and idea fidelity** — script carries the approved variant's idea and hook | hook and idea of the variant fully carried | hook carried, idea slightly diluted | idea partly lost | hook missing or idea changed | unrelated to the variant |
| **J2 Storyboard craft** — shots are visualisable, varied, sequenced to the script, and fit the ratio | shots clear, varied, ordered to script, fit the ratio | one weak shot | several vague or repetitive shots | shots do not follow the script | storyboard unusable |
| **J3 Wording discipline** — no stronger, broader or condition-free claim wording; no fluff that implies a result | every statement exactly as strong as its register text, conditions visible | one minor softening | one slightly stronger phrase | a stronger claim or a hidden condition | claims invented or inflated |
| **J4 Rationale and notes quality** — camera notes and disclaimer reasons are brief and correct | notes and reasons brief and correct | minor looseness | generic but correct | vague or partly wrong | missing or wrong |

Calibration: before the judge is used in CI, two humans label a fixed calibration subset (at least 10 cases from `cases.jsonl`); the judge must agree within ±1 point on >= 90 % of criterion scores (design default, recalibrated after the first client ad pilot). The calibration result is stored with the judge prompt version.
