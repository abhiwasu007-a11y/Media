# Judge rubric — `agent_12.metadata_draft`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 12 |
| Used by | eval gate (27 §5); judge prompt `agent_12/metadata_draft_judge.v1` (written with the Agent 12 build ticket) |
| Scope | Subjective quality only. Schema, lengths, forbidden strings, numbers, ids, lexicon verdict and distinctness are checked deterministically (README §4) and are **not** judged. |

The judge receives the case input, the step output and this rubric, and returns integer scores 1 to 5 per criterion with a one-sentence justification each. A score below the case's `judge_min` fails the case. The judge never overrides a deterministic assertion.

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Promise fidelity** — titles, description and chapter titles say what the script and the thumbnail texts deliver, no more, no less | all variants carry the one promise; mismatches with thumbnail texts reported precisely | one variant slightly broader or narrower than the promise | a variant adds an unsupported hint of result or benefit | a variant promises content the script lacks | titles unrelated to the script |
| **J2 Language quality** — natural Marathi, Hindi or English as the channel speaks; technical terms in the form of the input | reads like a native channel title, terms exact | one slightly stiff phrase | several stiff or literal phrases, still understandable | grammar or script mixing errors that distract | unreadable or wrong language |
| **J3 Description truthfulness and usefulness** — the opening and bullet points restate the sections, in a useful order | every sentence is traceable to a section and useful | one point generic | one point repeats another or is vague | a point not supported by a section | invented content |
| **J4 Chapter title quality** — short, natural, faithful to the section, no stuffing | all faithful and readable | one wordy | several wordy or repeating the keyword | a title that does not match its section | unrelated or missing |
| **J5 Education framing** — wording describes concepts and past charts; no advice tone, no hype | clearly educational throughout | one phrase slightly directive | a hype word or directive tone in one place | repeated directive or hype wording | advice or prediction wording (this also fails the deterministic lexicon) |

Calibration: before the judge is used in CI, two humans label a fixed calibration subset (at least 10 cases); the judge must agree within ±1 point on at least 90 % of criterion scores (design default, recalibrated after the pilot). The calibration result is stored with the judge prompt version.
