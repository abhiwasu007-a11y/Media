# Judge rubric — `agent_03.topic_selection` step `brief`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 03 |
| Used by | eval gate (27 §5); judge prompt `agent_03/topic_brief_judge.v1` (written at build time) |
| Scope | Subjective quality only. Schema, refusals, rule flags, banned phrases, script and lengths are deterministic (README §4) and not judged. |

Integer scores 1–5 per criterion with a one-sentence justification. A score below the case's `judge_min` fails the case.

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Faithfulness** — brief stays on the given node and persona | exactly the node, persona's level and goal respected | one small drift | noticeable drift in one part | brief mostly about another topic | unrelated |
| **J2 Teaching order and clarity** — prerequisites first, one idea at a time, outcomes checkable | clear order, every outcome observable | one outcome vague | order partly wrong or two vague outcomes | confusing order | not usable by a script writer |
| **J3 Compliance framing** — no implied advice or view, past-data framing where needed | no implication at all | one soft phrase that could be misread | an implied direction or action in one place | clear implied advice | explicit advice |
| **J4 Language quality and novelty** — natural language in the channel language, angle differs from recent angles | natural, idiomatic, clearly new angle | minor awkwardness, new angle | understandable but stiff, or angle only slightly new | machine-like or angle repeats a recent one | wrong language or unreadable |

Calibration: two humans label a fixed subset (at least 10 cases); the judge must agree within 1 point on at least 90 % of scores (design default). The result is stored with the judge prompt version.
