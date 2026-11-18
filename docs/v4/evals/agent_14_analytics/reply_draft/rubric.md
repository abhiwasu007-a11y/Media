# Judge rubric — `svc_s13.reply_draft`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 14 |
| Used by | eval gate (27 §5); judge prompt `agent_14/reply_draft_judge.v1` (written with the build ticket) |
| Scope | Subjective quality only. Rule outcomes, facts used, links, numbers, length, language and schema are checked deterministically (README §4) and are **not** judged. |

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Faithfulness** — says only what the used facts say, nothing implied beyond them | every statement traceable, no overreach | traceable, one mild paraphrase beyond the fact | one statement slightly beyond the fact | a claim not supported by a fact | invented content |
| **J2 Tone and register** — friendly or formal as configured, calm, respectful, not defensive or salesy | exact register, natural in the language | natural, slightly stiff | acceptable but generic or off-register in places | awkward, pushy or condescending | rude, promotional or unnatural |
| **J3 Usefulness within limits** — answers or declines clearly, points to the video where a fact allows, no filler | clear, complete for what the facts allow | clear, small gap | helpful but vague | confusing or misses the point of the comment | does not address the comment |

Calibration: two humans label at least 10 cases; the judge must agree within ±1 point on at least 90 % of scores (design default). Result stored with the judge prompt version.
