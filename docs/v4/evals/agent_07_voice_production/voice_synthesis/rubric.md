# Human listening rubric — Agent 07 (not an LLM judge)

| Field | Value |
|---|---|
| Used by | the owner (or a delegate) at the 3B golden-sample review and, afterwards, on sampled videos (sampling rate **REQUIRES REVIEW (Phase 1)**) |
| Records | HUMAN rows in `quality_scores` for the 3 human points of AUDIO_QUALITY (18 §9.2) and the check row `qc.voice.listening` (18 §4), both written under the human-row rule against confirmed owner evidence (04 §5.16, CCR-010) |
| Scope | subjective narration quality only. Loudness, true peak, clipping, silence, sync and dictionary application are measured deterministically (README §4) and are **not** scored here. |
| Not an eval gate | this rubric does not decide a case of this dataset; it is stored here so the calibration of the human points is reproducible. |

Scores are integers 1–5 per criterion with one free-text line. Fixes found go to the channel's pronunciation dictionary (a new version), not to the script (§1A.3, ADR-008 §2.8).

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **H1 Pronunciation** (names, numbers, English terms in the target language) | none wrong | one minor slip, meaning clear | two or three slips | a key term repeatedly wrong | many terms wrong |
| **H2 Pace** (fits the meaning; lesson sentences slower, transitions lighter) | natural throughout | one stretch too fast or slow | several stretches off | monotone or rushed through most of the video | unusable pace |
| **H3 Tone** (neutral narration, no persona; emotion follows the sentence) | fitting everywhere | one mismatched sentence | several flat or over-acted sentences | tone distracts | wrong tone throughout |
| **H4 Artefacts** (clicks, breaths cut, word clipping, robotic runs) | none | one faint artefact | a few audible artefacts | frequent artefacts | constant artefacts |

Mapping to points: the three human AUDIO_QUALITY points are scored by the owner from H1–H4 with the provisional rule "total points = round(3 × mean(H1..H4) / 5)" (PROPOSAL; **REQUIRES REVIEW (Phase 1): owner sets the mapping in 3B**). A pronunciation or artefact finding is listed with the sentence ID (never the sentence text in a log) so the dictionary owner can fix it.
