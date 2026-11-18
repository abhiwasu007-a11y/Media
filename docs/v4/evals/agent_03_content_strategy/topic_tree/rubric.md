# Judge rubric — `agent_03.topic_selection` step `tree`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 03 |
| Used by | eval gate; judge prompt `agent_03/topic_tree_judge.v1` (build time) |
| Scope | Subjective quality only; structure validity, ID existence and rejection reasons are deterministic. |

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Faithfulness to digests** — every node follows from its cited digests' index terms | all nodes clearly supported | one node weakly supported | several nodes stretch the digests | a node unrelated to its digests | nodes invented |
| **J2 Learner-order hierarchy** — parents, prerequisites and sibling order follow what a learner needs next, not a source's order | clear progression | one odd placement | order partly arbitrary | order mirrors digest order | no structure |
| **J3 Label quality** — neutral, own-words noun phrases, local label only when certain | all good | one label vague | several vague or copied-looking | labels copy index terms | unusable |

Calibration as in the other judges (at least 10 labelled cases; agreement within 1 point on at least 90 %).
