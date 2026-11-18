# Judge rubric — `agent_03.topic_selection` step `strategy`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 03 |
| Used by | eval gate; judge prompt `agent_03/strategy_proposal_judge.v1` (build time) |
| Scope | Subjective quality only; schema, kinds, shares, forbidden phrases and chapter IDs are deterministic. |

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Coherence** — positioning, pillars and personas agree with each other and with the library and chapters | fully coherent | one weak link | several loose links | contradicts an input | incoherent |
| **J2 Reasoned weighting** — shares follow library support and chapters, not trend popularity alone; rationale cites inputs without invented numbers | clear and grounded | one share unexplained | generic rationale | share contradicts the inputs | invented support |
| **J3 Persona usefulness** — personas are distinct, specific audience profiles a script writer can write for | distinct and specific | one generic | all generic | overlapping | not audience profiles |

Calibration: at least 10 labelled cases; agreement within 1 point on at least 90 %.
