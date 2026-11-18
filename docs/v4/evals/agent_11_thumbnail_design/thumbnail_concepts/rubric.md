# Judge rubric — `agent_11.thumbnail_concepts`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 11 |
| Used by | eval gate (27 §5); judge prompt `agent_11/thumbnail_concepts_judge.v1` (to be written with the first eval run) |
| Scope | Subjective quality of the choice only. Schema, statuses, reason codes, IDs, forbidden options, the one-change rule and rationale hygiene are checked deterministically (README §4) and are **not** judged. |

The judge receives the case input, the step output and this rubric, and returns integer scores 1–5 per criterion with a one-sentence justification each. Scores below the case's `judge_min` fail the case. The criteria apply to concepts with `status = OK`; for refusal cases and all-`NO_SAFE_CONCEPT` outputs only J3 and J4 are scored, on the stated reason.

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Promise fit** — the chosen text and picture best repeat the promise among the offered options | every concept uses the offered option that states the promise most directly; picture matches the subject idea | one concept uses a weaker but valid option | a valid but generic choice where a clearly better offered option existed | an option that only loosely relates to the promise | the choice does not repeat the promise |
| **J2 Test design** — the set is a clean one-change-at-a-time A/B test and the changed variable is worth testing | control is the brief's own idea; each later concept varies the most informative available factor | valid set; a more informative factor was available | valid set; the varied factor is trivial (for example near-identical wording) | the set is valid but gives little to learn | variants are effectively duplicates |
| **J3 Fidelity of `angle` and `hypothesis_kind`** — labels describe the chosen options honestly | every label matches the options | one label slightly off | one label clearly generic | a label contradicts the options | labels invented |
| **J4 Rationale quality** — one short factual English sentence saying why the combination repeats the promise; no instruction echoed, no new fact | clear, specific, within limits | specific for most concepts | generic but correct | vague or partly wrong | missing, wrong or adds a claim |

Calibration: before the judge is used in CI, two humans label a fixed calibration subset (at least 10 cases from `cases.jsonl`); the judge must agree within ±1 point on ≥ 90 % of criterion scores (design default, recalibrated after the pilot). The calibration result is stored with the judge prompt version.
