# Judge rubric — `agent_08.asset_sourcing` step `candidate_rank`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 08 |
| Used by | eval gate (27 §5); judge prompt `agent_08/candidate_rank_judge.v1` (pending Agent 08 build ticket) |
| Scope | Subjective quality only. Schema, coverage, order consistency, reject-class reasons, release-record handling and refusal mapping are checked deterministically (README §4) and are **not** judged. |

The judge receives the case input, the step output and this rubric, and returns integer scores 1–5 per criterion with a one-sentence justification each. Scores below the case's `judge_min` fail the case.

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Fit accuracy** — fit labels are sensible given only the metadata | every label is what an experienced editor would give; ordering matches | one adjacent-level difference (e.g. STRONG vs ACCEPTABLE) | two adjacent-level differences | a clearly relevant clip rated WEAK or an off-topic clip rated ACCEPTABLE | labels unrelated to the metadata |
| **J2 Reason precision** — reason codes name the real cause, nothing extra | exact codes, no over-flagging | one extra or missing minor code | main cause present, one wrong extra code | main cause missing | codes contradict the rationale |
| **J3 Rationale quality** — short, factual, tied to metadata | each rationale cites a metadata field and states the cause | most do | generic but correct | vague or partly wrong | invented detail or advice |

Calibration: as for the query-plan rubric (two humans, at least 10 cases, agreement within ±1 point on ≥ 90 % of scores, stored with the judge prompt version).
