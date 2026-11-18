# ADR-008 — Text-to-speech provider and narration options

| Field | Value |
|---|---|
| Status | **Proposed** (documentation). Software: **Planned**. |
| Date | 2026-11-18 |
| Directive | §1A.3 (voice), §1A.4 (audio delivery spec), §1B.2 (presenter: owner's voice or neutral narration, no AI persona), §1C.8 (third-party use), §3.2a (provider-independent TTS adapter), §3.3 AI providers |
| Owner decisions | D1 (3A: Agent 07 in the production line; spend controls; secrets), plan Q11 (provisional default: owner's recorded narration or neutral TTS; owner decides after hearing samples) |
| Contracts used | 04 §5.12 (`voices`, `voice_consents`), §5.14 (`cost_ledger`), §5.15 (`licences`, `licence_ledger`, `assets`); GLOSSARY §6 (`voice_kind`, `consent_state`, `licence_source_type`, `third_party_permission`, `FIN-R11`); 24 §3.2 (`agent_07.voice_synthesis`, `agent_07.audio_master`); 07 §2 / §4 |
| Research | PR-04, PR-05, PR-07 |
| MVP scope | **3A** (TTS adapter with fake, one provider, human-narration intake, consent check, cost capture) · **3B** (owner listening test of the options on the golden samples; pronunciation dictionary tuning) · **3C** (fallback provider, per-tenant voices, client use) |
| Enterprise tier | Tier 0: owner channel only. **Tier 1 (clients) blocked** for ElevenLabs output until PR-05 is confirmed in writing. |

## 1. Context
- §1A.3 asks for the best available multilingual TTS with a per-channel pronunciation dictionary (Marathi/Hindi names, numbers, English terms), sentence-level emotion/pace control, and a human listening check on the pilot set; the owner may choose a consented clone of his own voice or his own recorded narration; never clone anyone else.
- Finance channel: no AI presenter persona (`FIN-R11`, YT-09 via the glossary); every video carries the owner's editorial input.
- ElevenLabs (PR-04, VERIFIED 2026-11-18): **Marathi (mr) is supported on Eleven v4, v4 Turbo, v3 and v3 Conversational**; Multilingual v2 and Flash v2.5 support Hindi but **not Marathi**. API price per 1K characters: v4 / v3 / Multilingual v2 $0.08; v4 Turbo / v3 Conversational / Flash $0.04. Plans: Starter $6 · Creator $22 · Pro $99 · Scale $299 · Business $990 per month (credits-based); Free is non-commercial. Cloning requires "right and consent"; the use policy forbids cloning a living person "without their explicit and informed consent".
- PR-04 ESTIMATE: a 10-minute Marathi script ≈ 8–10K characters ≈ $0.64–0.80 per take at $0.08/1K; the character count is an ESTIMATE until measured in the pilot.
- ElevenLabs output for clients (PR-05, **NOT CONFIRMED**): paid users "may use the Services for commercial purposes" and "retain all rights in and to your Output"; there is no explicit client/agency clause; the help centre was blocked.
- Google Cloud TTS (PR-07, PARTIAL): Gemini 3.8 Flash TTS (Preview) "$0.50 per 1 million text tokens" input and $9 per 1M audio tokens output through 2026-12-31, $1 / $18 from 2027-01-01. **Marathi support, voice quality and preview terms are not recorded.** Azure speech: price not in HTML (PR-07).

## 2. Decision
1. **One `TtsAdapter` Protocol** in `amw_adapters/tts/` (synthesize with SSML-like pacing/emotion controls where the provider supports them, pronunciation dictionary, voice list). Fake + recorded fixtures; no paid calls in tests (27 §8).
2. **Primary candidate for Marathi narration: ElevenLabs, v3/v4-class model only** (the only models in PR-04 that list Marathi). The model ID and voice reference are config (`voices.provider_voice_ref`, never hard-coded). Whether v4 or v4 Turbo is used is decided by the 3B listening test, not by price alone.
3. **Fallback candidate: Google Cloud TTS (Gemini Flash TTS)**, adopted only after (a) Marathi support is verified on the official page and recorded in the research log, and (b) it passes the same listening test. Until then it is a candidate, not a configured fallback. **REQUIRES REVIEW (Phase 1): Google TTS Marathi language support and preview-model terms.**
4. **Three narration options behind one interface** (plan Q11), mapped to existing `voice_kind` values:

   | Option | `voice_kind` | Licence record (`licence_source_type`) | Gate |
   |---|---|---|---|
   | Owner's own recorded narration | `HUMAN_RECORDED` (`provider` NULL) | `HUMAN_NARRATION` | owner supplies audio; `agent_07.voice_synthesis` runs intake (level, noise, timing) instead of synthesis |
   | Neutral provider voice (not a persona) | `PROVIDER_STOCK` | `TTS_PROVIDER` | provider licence `ACTIVE` |
   | Consented clone of the owner's voice | `CONSENTED_CLONE` | `VOICE_CLONE` | `voice_consents.state = VERIFIED` (DB CHECK + Agent 07 check) |

   Pilot default (Q11): owner's recorded narration or a neutral voice; the owner chooses after hearing samples in 3B. No AI persona on the finance channel (`FIN-R11`). Cloning anyone other than the consenting voice owner is never configured.
5. **Consent records.** A clone is created only after a `voice_consents` row with `consent_document_ref`, `verification_method`, `scope_note` (permitted channels/uses), `third_party_use` and `state = VERIFIED`; `WITHDRAWN` or `EXPIRED` blocks further renders of that voice. The consent artefacts live in private storage, never in git.
6. **Client use (Tier 1+).** A TTS licence for client work is recorded with `third_party_permission = UNKNOWN` until PR-05 is resolved; per GLOSSARY §6.21 `UNKNOWN` blocks use for any tenant other than the licence holder's own channels. Unblock requires written vendor confirmation or an enterprise agreement (PR-05 decision column, §1C.8).
7. **Cost capture.** Each synthesis call writes a `cost_ledger` row: `operation = tts.synthesize`, `units` = characters (or `audio_ms` where the provider bills by audio), `unit_kind`, `figure_kind = ESTIMATE` with `price_ref`; a `VERIFIED` row follows from the usage export. Retakes are counted (a retake is a new call with its own idempotency key). Budget reservation before the call, as ADR-007 §2.8; breach → `RESOURCE.BUDGET_EXHAUSTED`.
8. **Quality gate.** `agent_07.audio_master` and `agent_10.technical_qc` measure the §1A.4 spec (−14 LUFS integrated, −1 dBTP, 48 kHz) with `ebur128` (INF-09). Pronunciation errors found in the listening check go into the channel's pronunciation dictionary, not into ad-hoc script edits.
9. **Failure handling** uses 07 §2 codes (rate limit, 5xx, timeout, `PERMANENT.AUTH_INVALID`, `PERMANENT.PROVIDER_REFUSAL`) and one breaker per provider (07 §4). Switching provider mid-video is not allowed: one video uses one voice for consistency; a provider outage suspends via the breaker (`INFRASTRUCTURE.CIRCUIT_OPEN`) rather than mixing voices.
10. **Secrets** only through the environment's secret mechanism (D1).

## 3. Options considered (with evidence)
| Option | Evidence | Verdict |
|---|---|---|
| ElevenLabs Multilingual v2 / Flash v2.5 | PR-04: Hindi yes, **Marathi no** | Rejected for Marathi |
| **ElevenLabs v3 / v4 class** | PR-04: Marathi supported; $0.04–0.08 per 1K chars; consent rules stated | **Chosen as primary candidate** (3A/3B) |
| Google Cloud TTS (Gemini Flash TTS, Preview) | PR-07: price recorded; Marathi support not recorded; "Preview" | Fallback candidate pending verification |
| Azure speech | PR-07: price not in HTML; no language facts recorded | Not evaluated; needs research entry |
| Owner's recorded narration | §1A.3, §1B.2, Q11; no vendor licence risk | **Chosen as an always-available option** |
| Consented clone of the owner | PR-04 consent requirement; §1A.3 | Allowed only with a `VERIFIED` consent record |

## 4. Consequences
- Positive: narration choice is a voice row + config, not code; Marathi is covered by a provider whose language list is verified; owner narration removes vendor dependency for the first channel.
- Negative: v3/v4-class is the higher price row in PR-04 ($0.08/1K except Turbo/Conversational at $0.04); a second provider is not usable until verified.
- Client production with ElevenLabs output stays blocked until PR-05 is confirmed (Tier 1 gate).
- REQUIRES REVIEW (Phase 1): owner's narration choice (A6 "narration choice"), plan tier/credits to buy and the provider-side spending limit (owner, rule 8, D1).
- REQUIRES REVIEW (Phase 1): measured Marathi characters per finished minute and retake rate (pilot), replacing the PR-04 ESTIMATE.
- REQUIRES REVIEW (Phase 1): whether the chosen ElevenLabs model supports the sentence-level emotion/pace control §1A.3 asks for (not recorded in PR-04).

## 5. Revisit trigger
- 3B listening test fails for the chosen model, or the owner picks another option.
- PR-05 answered by the vendor (unblocks or keeps blocking Tier 1).
- Google TTS Marathi support verified (adds a configured fallback).
- Price or model-list change at re-verification (> 30 days, plan Q18).
- Withdrawal of the owner's voice consent.

## 6. Research IDs cited
PR-04, PR-05, PR-07; INF-09 (QC measurement).
