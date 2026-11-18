# Judge rubric — `agent_04.research_pack` step `notes`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 04 |
| Used by | eval gate (27 §5); judge prompt `agent_04/research_pack_notes_judge.v1` (written with the first build ticket for the gate) |
| Scope | Subjective quality only. Schema, citations, copy guard, numbers, quotes, exclusions and injection handling are deterministic (README §4) and are **not** judged. |

The judge receives the case input, the output and this rubric and returns integer scores 1–5 per criterion with a one-sentence justification each. It runs inside the private worker; its output contains passage IDs and rationale, never passage text.

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Relevance and completeness** — relevant passages are noted, irrelevant ones are not | every needed point noted, nothing off-topic | one minor point missed | one needed point missed or one off-topic note | a needed point missed and an off-topic note | most notes off-topic or most needed points missing |
| **J2 Originality of wording** — own words, own structure, not a paraphrase of the passage's sentence order | clearly own wording and structure | same idea, one note follows the sentence order closely | several notes follow the passage's order | notes are light edits of the passage (passes the code guard only by luck) | notes are the passage with synonyms |
| **J3 Faithfulness** — each note states only what its passage states | exact | minor softening | one detail lost or one slight overstatement | a fact added or a number context changed | note contradicts the passage |
| **J4 Reason quality** — `reason` per assessment and `statement_kind` fit | specific and right | minor vagueness | generic but right | partly wrong | missing or wrong |

Calibration: two humans label a fixed subset (at least 10 cases); the judge must agree within ±1 point on ≥ 90 % of criterion scores (design default, recalibrated after the pilot). The result is stored with the judge prompt version.
