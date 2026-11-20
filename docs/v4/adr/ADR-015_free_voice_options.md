# ADR-015 — Free voice options for the Seneca sample (Marathi, no paid ElevenLabs)

| Field | Value |
|---|---|
| Status | **Proposed** (documentation). Owner must pick (section 5). Software: **Not built** (no candidate qualified, section 4). |
| Date | 2026-11-20 |
| Directive | §1A.3 (voice), §1C.8 (third-party use), §3.2a (provider-independent TTS adapter) |
| Owner decisions | Priority unchanged: Seneca sample MP4 with a free voice (owner chat, 2026-11-20); D1 (no paid calls without owner budget); ADR-008 (narration options) |
| Contracts used | `TtsAdapter` Protocol (`amw_adapters.tts`: `TtsCapabilities`, `TtsRequest`), sealed preflight gate of the real adapters (PR 96); no contract change |
| Research | FV-01 to FV-10 (RESEARCH_LOG.md, read 2026-11-20); PR-04, PR-11 for the paid baseline |
| MVP scope | **3A** sample only; the choice may change after the 3B listening test |

## 1. Context
- The owner wants the Seneca sample MP4 with a free voice. ADR-008 names ElevenLabs as the primary Marathi candidate (PR-04, PR-11: v3/v4 list Marathi), which is paid.
- The video will be monetised on YouTube, so a voice whose licence is non-commercial, unknown or unofficial is not acceptable (fail closed).
- This lane could not reach huggingface.co, learn.microsoft.com, azure.microsoft.com or docs.cloud.google.com (blocked in the session; not bypassed). Several rows are therefore UNVERIFIED and say what is missing. No audio was generated or heard by this lane: **no quality claim is made for any option.**
- Dev container: 4 CPU cores, 16 GB, no GPU. No model weights are in the repo and none were downloaded.

## 2. Comparison
"Licence" is the licence of what would actually be used (code and weights). "Local" = runs offline once the weights are present.

| Option | Marathi | Licence for monetised use | Local (CPU) / network | Quality note | Risk | Verdict | Research |
|---|---|---|---|---|---|---|---|
| AI4Bharat Indic Parler-TTS | Yes (named Marathi speakers, per card snippets) | Weights Apache-2.0 per search snippet of the card only; a government catalogue says MIT; training-data licences unread. **UNVERIFIED** | Local in principle; a model of this class on 4 CPU cores is expected to be slow (not measured); weights from an unreachable host | Not heard | Licence unconfirmed first-hand; speed on CPU unmeasured | **Best candidate, blocked** until the card is read and a sample is heard | FV-02 |
| AI4Bharat Indic-TTS | Yes (13 languages incl. Marathi) | Code MIT (verified); checkpoint and dataset licence **not stated** | Local | Not heard | Weights licence unknown | Blocked (fail closed) | FV-03 |
| Meta MMS-TTS `mar` | Yes | Brief says CC-BY-NC 4.0 (not read first-hand) | Local | Not heard | Non-commercial | **Excluded** | FV-04 |
| Coqui XTTS | Not confirmed | CPML, non-commercial (snippet of the licence); code MPL-2.0 | Local | n/a | Non-commercial | **Excluded** | FV-05 |
| Piper | **No Marathi voice listed** | GPL-3.0 code; no licence over voices | Local | n/a | n/a | **Excluded** | FV-01 |
| eSpeak NG | Yes (`mr` row) | GPL-3.0-or-later | Local, tiny | Not heard (brief: robotic) | GPL; quality | Excluded for the channel voice | FV-10 |
| Edge read-aloud (edge-tts) | Yes (Aarohi, Manohar) | **No usage right on record**; unofficial endpoint; package LGPL-3.0 | Network | Not heard | Can break or be blocked; terms unknown | **Excluded** from the pipeline | FV-06 |
| gTTS | Not confirmed | Unofficial, undocumented Google Translate function; package MIT | Network | n/a | No usage right on record | **Excluded** | FV-09 |
| Azure AI Speech (official) mr-IN-Aarohi / Manohar | Yes (snippets) | Free tier and commercial terms **UNVERIFIED** | Network + key | Not heard | Needs Azure account; F0 limits unknown | Candidate once terms are read | FV-07 |
| Google Cloud TTS | Not read | **UNVERIFIED** | Network + key | n/a | Unknown | Candidate once read | FV-08 |

## 3. Recommendation (fails closed)
1. **No option is clearly licence-clean and runnable offline today.** Nothing is adopted into the pipeline by this ADR.
2. **First choice: Indic Parler-TTS, run locally, after a first-hand licence read.** If the card and the training-data licences confirm commercial output, adopt it behind `TtsAdapter` as a local adapter (cost 0 micros, no key, local model path and expected sha256 from config). If the licence is anything other than a permissive one, or unclear, do not use it.
3. **Second choice: Azure AI Speech official API, mr-IN voices**, only if the owner accepts a key and the F0 free tier terms (FV-07) allow commercial output. The same adapter slot applies; spend stays within the owner's budget.
4. **Never in the pipeline:** the Edge read-aloud endpoint, gTTS (no usage right on record), MMS-TTS, XTTS (non-commercial), Piper (no Marathi), eSpeak NG (voice quality; GPL).
5. **Fallback while the owner decides:** the owner's own recorded narration (ADR-008) or the existing paid ElevenLabs route within an owner budget. The sample may be cut with a placeholder track only if the owner says so.

## 4. Implementation status
No adapter was written. The rule was: build only if a candidate is licence-clean and runnable offline in this container. Neither condition is met (weights host unreachable, licence unverified, CPU speed unmeasured). Building an adapter against an unverified weights licence would risk shipping a non-compliant voice. The adapter is a ticket (section 6) that starts after item R1 below.

## 5. REQUIRES REVIEW (owner)
- **R1 (owner): pick the route.** (a) Indic Parler-TTS local, pending licence read; (b) Azure official free tier, pending terms; (c) own recording; (d) paid ElevenLabs within a budget. Provisional default if no answer: (a), with (c) as the sample fallback; nothing paid.
- **R2 (owner or a run on an allowed network): allow huggingface.co and learn.microsoft.com** (and azure.microsoft.com, docs.cloud.google.com) in the session's network settings so FV-02, FV-04, FV-07 and FV-08 can be read first-hand.
- **R3 (owner): listening test.** The owner listens to a short Marathi sample from the chosen route before it is used (no quality claim is made here).
- **R4 (counsel): training-data licences** of the chosen open model, and AI-voice disclosure for the finance and philosophy channels (YT policy rows already in the log).

## 6. Ticket
**FREE-VOICE-1**: local TTS adapter behind `TtsAdapter` for the owner-chosen open model. Scope: `amw_adapters/tts/local_<name>.py` plus a real-adapter entry that passes the sealed preflight gate with cost = 0 micros; config supplies a local model path and an expected sha256 (refuse to load on mismatch; no download from unpinned sources); capabilities declare what the model honestly supports (pace, emotion, pronunciation dictionary, markup delimiters); the same conformance suite as the other adapters; tests use a fake model, no weights in the repo, no network. Starts after R1 and R2 are answered. A CPU timing measurement for a 10-minute script is part of the ticket.
