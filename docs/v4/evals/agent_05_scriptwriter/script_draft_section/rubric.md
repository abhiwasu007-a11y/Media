# Judge rubric — `agent_05.script_draft` step `section`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 05 |
| Used by | eval gate (27 §5); judge prompt `agent_05/script_draft_judge.v1` |
| Scope | Subjective quality only. Schema, citations, rule checks, cadence arithmetic, chart rules, flags and budgets are deterministic (README §4) and are **not** judged. |

Scores are integers 1–5 with a one-sentence justification each; a score below the case's `judge_min` fails the case.

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Teaching clarity and own words** — the concept is explained step by step with the section's own invented example; nothing is a re-telling of the brief's summary | clear, ordered, original example | one step skipped or one generic sentence | understandable but generic or partly following the summary's order | confusing, or the summary's order and wording are followed | not teachable, or copied |
| **J2 Retention writing** — sentences vary in length and tone; pace and emotion tags fit the meaning (a lesson line `SLOW` or `EMPHASIS`, a question `CURIOUS`); visual intent describes a picture that changes with the sentences; the interrupt sits where attention would drop | tags and visuals follow the meaning throughout | one mismatched tag or one flat stretch | mostly fits, visual intents generic | tags look arbitrary or visuals repeat | one value throughout, or visuals do not match the words |
| **J3 Case-study framing** — past tense about what the chart showed; both a worked and a failed episode when asked; the last scene states the concept lesson and nothing about where the security goes next (not applicable for non-case sections) | exactly this | lesson present but one sentence leans forward | lesson present, framing partly present-tense | the lesson is missing or buried | ends on an expectation about the security |
| **J4 Spoken naturalness** — plain spoken language of the target (Marathi in Devanagari, or English), short sentences, terms explained, no written-style or translated-sounding phrases | sounds like a person speaking | one stiff sentence | readable but written in style | several stiff or machine-translated phrases | hard to speak aloud |

Calibration: two humans label a fixed subset (at least 10 cases); the judge must agree within ±1 point on ≥ 90 % of criterion scores (design default). For J4 in Marathi the human labellers are Marathi speakers; the result is stored with the judge prompt version.
