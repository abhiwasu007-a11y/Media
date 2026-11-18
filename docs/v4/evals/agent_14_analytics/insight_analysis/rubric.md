# Judge rubric — `agent_14.insight_analysis`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 14 |
| Used by | eval gate (27 §5); judge prompt `agent_14/insight_analysis_judge.v1` (written with the build ticket) |
| Scope | Subjective quality only. Numbers, labels, citations, forbidden wording, counts and schema are checked deterministically (README §4) and are **not** judged. |

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Clarity** — a non-technical owner understands the statement at once | plain, one idea, units and group named | clear, slightly dense | understandable after rereading | confusing wording or jargon | unreadable |
| **J2 Honesty about limits** — `limitations` and `does_not_show` are concrete and true to the facts | specific to this figure (small group, estimate, other factors) | specific, one generic part | generic but true | partly untrue or irrelevant | missing in substance or misleading |
| **J3 Faithfulness of direction and comparison** — higher/lower, which group is compared with which, window and group size are right | exactly right | right, one imprecise word | right direction, imprecise group or window | direction or group swapped in part | direction or group wrong |

Calibration: two humans label at least 10 cases; the judge must agree within ±1 point on at least 90 % of scores (design default). Result stored with the judge prompt version.
