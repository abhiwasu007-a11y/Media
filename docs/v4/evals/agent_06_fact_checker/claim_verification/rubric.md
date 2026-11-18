# Judge rubric — `agent_06.claim_verification`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 06 |
| Used by | eval gate (27 §5); judge prompt `agent_06/claim_verification_judge.v1` (written with the first build ticket for the eval gate) |
| Scope | Subjective quality only. Status, verdict, span bounds, evidence ids, conflicts, flags and call counts are checked deterministically (README §5) and are **not** judged. The judge sees evidence text only inside the private worker and stores IDs and one-sentence justifications, never passage text. |

The judge receives the case input, the fixture passages, the model's batch output and this rubric, and returns integer scores 1–5 per criterion with a one-sentence justification each. A score below the case's `judge_min` fails the case.

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Evidence precision** — spans point at the statement that decides the claim | every span is the shortest stretch carrying the statement; all deciding statements cited | spans correct but one is wider than needed | one deciding statement missing, or one span partly off | a span points at text that does not decide the claim | spans unrelated to the claim |
| **J2 Discrepancy accuracy** — right kind, right values, nothing missed or invented | every difference reported with the right kind; values verbatim and relevant | one minor difference missing or one kind loosely chosen | one wrong kind or a missed difference that matters | a discrepancy invented, or the main difference missed | discrepancies unrelated to the claim |
| **J3 Correction faithfulness** — `suggested_correction` restates only the evidence | restates exactly the evidence, minimal, `null` where it should be | minor extra wording, no new fact | one detail softened or broadened | adds a fact, level, forecast or recommendation not in the evidence | contradicts the evidence or is a rule-breaking statement |
| **J4 Rationale quality** — names what matched or differed, specific to this claim | specific for every claim, mentions scope and numbers | specific for most | generic but correct | vague or partly wrong | missing or wrong |

Anchors for J2 kinds: `NUMBER` a different figure; `UNIT` percent vs absolute; `DIRECTION` rise/fall, above/below, higher/lower; `TIME_SCOPE` past, current or future, or a different period; `QUANTIFIER` all, most, some, never, always, often; `CAUSATION` a cause stated where the evidence shows an association or order; `SCOPE` different instrument, timeframe, market or population; `ENTITY` a different person, instrument or organisation; `NEGATION` the opposite polarity; `DEFINITION` a different meaning of the same term.

Calibration: before the judge is used in CI, two humans label a fixed calibration subset (at least 10 cases from `cases.jsonl`, including CON-10, PAR-14, MIX-36 and INT-27); the judge must agree within ±1 point on ≥ 90 % of criterion scores (design default, recalibrated after the pilot). The calibration result is stored with the judge prompt version.
