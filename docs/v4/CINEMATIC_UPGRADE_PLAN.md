# Cinematic Upgrade Plan (answers the V4.0 Cinematic directive)

Status: **PLAN ONLY, not approved.** Owner instruction 2026-11-25: "Store karun thewa, no coding, only plan tayar kr".
Directive text: `docs/v4/directives/V4_CINEMATIC_DIRECTIVE.md`. No code, migration, config or server change follows
from this file until the owner approves it in writing (CLAUDE.md hard rule). Every provider fact below that is not
already in `RESEARCH_LOG.md` is marked `REQUIRES REVIEW (Phase 1)`; no price, limit or capability is assumed.

## 1. Starting point (what exists today)

| Area | Today (apps/studio, deployed) | Gap to the directive |
|---|---|---|
| Orchestration (A01) | One worker, persistent JSON queue, stage re-run with "stale" downstream, market-hours guard, reserved LLM cost, $5/video and $50 pilot caps (D9) | Production modes, planning engine (scenes/clips/cost/time/storage), 00:00–07:00 IST window with hard cutoff, per-scene retry limits, external worker |
| Research (A04) | Stage 04 web research pack with sources (D29) | WorldReferencePackage (period, costume, location, canon vs fact) |
| Script (A05) | Narration script per scene, craft rules, 05c editor pass (D30), 22 languages | Screenplay with characters, dialogue segments, story state, structure choice, validation |
| Fact-check (A06) | Deterministic + LLM check, finance rules | Fiction mode: canon, timeline, knowledge contradictions; 4-way error classes |
| Voice (A07) | One narrator: pack/Kaggle Parler/Google Chirp3 HD (GTTS-01), per-sentence timing | VoiceProfiles per character, multi-voice dialogue, speaker-similarity check, lip sync |
| Visuals (A08) | FLUX.1 schnell stills on Cloudflare free tier (CF-01, IMG-04), Pixabay clips (STK-02), parallax, character sheet | Digital Actor Registry, reference packages, identity-preserving generation, video provider interface (Veo), consistency checks, asset records |
| Director (A09) | 05b shot list (2–3 stills per scene), 09 timeline from real audio | Storyboard Stage A/B, shot grammar, SceneContinuityState |
| Editor (A10) | FFmpeg render, film look, SFX, ducking, loudness −14 LUFS, QC length/streams | Multi-track dialogue, licensed music library, titles/credits, scene-level cached render, freeze/black/sync/integrity QC |
| Thumbnail (A11) | One AI thumbnail + text | Character-faithful concepts, several variants |
| Metadata/Publish (A12/A13) | Title/description/disclaimer drafts; no upload | Series/episode metadata, YouTube upload with disclosure (YT-06, YT-07) |
| Analytics/Growth (A14/A15) | Cost ledger per job | Real performance data, cost per second/shot, mode economics |
| Compliance/QA (A16) | 16 gate (auto part), finance pack | 12 cinematic gates, selective correction engine |
| Data | JSON files per job | The 20 entities of the directive (reuse `04_DATABASE_ARCHITECTURE.md`) |

Known open defects (diagnosed, fix waiting for owner "हो"): Cloudflare 429 when the free daily image allocation is
used up (stage must stop and resume next day instead of falling back to all code-made scenes); Kaggle voice breaks
because `parler-tts` downgrades protobuf to 4.25 (fix tested locally: re-upgrade protobuf after install and set
`USE_TF=0`); preview/export double-click race (corrupt file); full character sheet added to every picture prompt
(crowded, repetitive pictures). **Phase 0 fixes these first.**

## 2. Principles applied

1. **No new agents.** Every capability is a module inside the agent named by the directive (table in §4).
2. **Build on the working line.** apps/studio is deployed and producing; it is extended stage by stage, its stage
   numbers already follow agent numbers. The `packages/` 3A platform contracts change only through
   `CONTRACT_CHANGE_REQUESTS.md` (Wave A rule).
3. **Cheapest mode first, evidence before spend** (directive A15 + owner D16–D19): ECONOMY (today's free path) stays
   default; STANDARD/PREMIUM/CINEMA are unlocked one at a time only after a measured pilot and an owner budget.
4. **Plan before spend.** Paid video generation only after screenplay, actors, storyboard and the cost estimate are
   approved on the dashboard (directive A01).
5. **Selective work.** One failed shot or line regenerates alone; approved assets are never re-made because a render fails.
6. **Honest outputs.** Mocks only in tests; a missing key, budget or capability is shown as a blocker, never faked.

## 3. Facts to verify before any build (REQUIRES REVIEW, Phase 1 research, new RESEARCH_LOG IDs)

| ID (to add) | Question | Why it decides the design |
|---|---|---|
| VEO-01 | Veo models on Gemini API and Vertex AI: availability in India, clip length, resolution, aspect ratios, reference images, first/last frame, extension, native audio, rate limits | Core of A08 video provider; shot length drives storyboard |
| VEO-02 | Veo price per second (with and without audio), free/trial credit if any, billing account need | Mode economics, pilot budget |
| VEO-03 | Veo native speech: languages (Marathi/Hindi?), voice control, can it lip-sync to our own audio | Decides lip-sync route (§5 P6) |
| VEO-04 | Output terms: commercial use, SynthID watermark, disclosure duties | A16 licensing gate, YT-07 |
| FLOW-01 | Google Flow: any official API or export path; plan/credit limits | Flow is manual-assist only unless an official API exists |
| GIMG-01 | Google image models (Gemini image / Imagen): reference-image identity, price, terms | Actor reference packages, consistent stills |
| IMG-05 | Free/cheap identity-preserving options (FLUX Kontext or similar on Cloudflare or other hosts), licence | Keeps ECONOMY mode consistent at no cost |
| VOI-01 | Voice providers for multi-character Marathi/Hindi/English: Google Chirp3 HD voices list and controls (GTTS-01 update), ElevenLabs paid plans (PR-04, PR-11, PR-12 re-read), others | VoiceProfile fields, emotion controls actually supported |
| VOI-02 | Speaker-similarity model (e.g. ECAPA embeddings) licence and CPU cost | Voice consistency gate |
| LIP-01 | Lip-sync options: provider APIs and open models, licences (several open models are non-commercial) | P6 route |
| MUS-01 | Commercially safe music: YouTube Audio Library terms, Pixabay music licence, generated-music terms | A10 music module |
| FACE-01 | Face-embedding model for character consistency (licence, CPU cost, use only on fictional characters) | Character identity gate |
| YT-18 | Current YouTube API support for synthetic-content flag, playlists, premieres, captions upload (YT-06 re-read) | A13: what is automatic vs manual task |

## 4. Where each capability lives (no new agents)

| Agent | New internal modules |
|---|---|
| A01 Orchestrator | Production modes registry (8 modes × required stages, assets, thresholds, cost cap, retry cap, duration, providers, ETA); Production Planning Engine; night-window scheduler (00:00–07:00 IST hard cutoff, checkpoint, pause/resume, backup-job awareness); approval gates; budget reservations per provider; external worker hook |
| A02 Market | CinematicOpportunityReport (evidence vs AI opinion separated; no invented numbers) |
| A03 Strategist | Story Universe Registry; Series/Season/Episode engine; canon guard; CinematicContentBrief |
| A04 Research | WorldReferencePackage (extends stage 04) |
| A05 Script | Screenplay engine: structure chooser, character psychology profiles, dialogue segments, story state after each scene, validator; machine + human readable outputs |
| A06 Fact-check | Fiction mode (canon/timeline/knowledge/location/relationship checks); error classes; structured correction requests |
| A07 Voice | Voice DNA registry (VoiceProfile + versions); provider adapters (Google, Parler, ElevenLabs if approved); per-line dialogue synthesis with timestamps; pronunciation dictionary; similarity check with calibrated threshold; Lip Sync service |
| A08 Visuals | Digital Actor Registry + reference packages + versions; identity-preserving stills; CinematicVideoProvider interface (Veo adapter, Kaggle/free adapter, manual Flow import adapter); prompt compiler with capability detection; consistency checker; asset records |
| A09 Director | Storyboard Stage A (before generation) and timeline Stage B (after real audio/clips); shot grammar; SceneContinuityState; last-frame reuse |
| A10 Editor | Scene-level cached render; dialogue multi-track mix; music module with licence records; SFX sync; grade presets (deterministic LUTs); titles/credits; extended QC (freeze, black, clipping, A/V sync, integrity, subtitle timing) |
| A11 Thumbnail | Poster/episode/character concepts from registry references; 3 different concepts |
| A12 Metadata | Series/episode metadata; fiction and synthetic-media disclosures |
| A13 Publish | YouTube upload (resumable, dedupe, sequence guard); unsupported steps as manual tasks |
| A14 Analytics | Retention mapped to scene boundaries; correlation-only language |
| A15 Growth | Cost per second/shot/regeneration; ECONOMY/STANDARD/PREMIUM/CINEMA comparison from real data |
| A16 Compliance/QA | 12 gates; Selective Correction Engine (structured requests with cost and retry budget) |

## 5. Phases (each ends with a demo to the owner and the owner's written OK before the next)

| Phase | Content | Paid spend | Exit check |
|---|---|---|---|
| **P0 Fix** | The 4 open defects in §1 | none | Sample video plays on phone; Kaggle voice and pictures complete |
| **P1 Research** | §3 questions answered with official URLs + dates in RESEARCH_LOG; cost model per mode with sources | none | Owner reads a 1-page cost table per mode and picks budgets |
| **P2 Data + registries** | Schema for the 20 entities (reusing `04_DATABASE_ARCHITECTURE.md`; contract change requests filed); Actor, Voice, Universe, Series registries; dashboard Actor/Voice/Universe/Series pages | none | Two fictional actors and two voice profiles created and versioned |
| **P3 Screenplay** | A05 screenplay engine + story state + validator; A06 fiction mode; dashboard Screenplay editor | small LLM (within D9 caps) | Two-character short screenplay passes validation |
| **P4 Storyboard + stills** | A09 Stage A storyboard and continuity state; A08 identity-preserving stills from reference packages (free path first); character consistency check | free tier | Storyboard viewer shows consistent faces and costumes across shots |
| **P5 Dialogue voices** | A07 per-character dialogue, timing, similarity gate, regeneration of failed lines | free tier (Google) or owner-approved | Two distinct, stable voices; failed lines regenerate alone |
| **P6 Video + lip sync** | CinematicVideoProvider; Veo adapter behind the approval gate; lip-sync route chosen from VEO-03/LIP-01; Flow manual-import path | **owner budget required** | 3–5 approved shots of the pilot with correct speaker lip sync |
| **P7 Post** | A10 music (licensed), SFX, grade presets, titles/credits, scene-cached render, extended QC; A11 concepts | none | Pilot cut passes technical QC |
| **P8 QA gates** | A16 twelve gates + selective correction; thresholds calibrated on real samples | small | Gate report with evidence per shot |
| **P9 Publish** | A12/A13 metadata, disclosures, private upload, playlists, manual tasks list | none (API quota) | Pilot uploaded as private with correct disclosure |
| **P10 Pilot + economics** | Directive acceptance pilot (2 actors, 2 voices, dialogue, lip sync, music, subtitles, thumbnail, metadata); measure cost, time, consistency, regeneration rate; A14/A15 reports | **owner budget required** | All mandatory gates pass; owner score (D5) |

Shorts, episodic series and HYBRID mode reuse the same modules; they are switched on after P10.

## 6. Decisions the owner must make (before P2 / P6)

1. **Budget for cinematic video** (Veo or other paid video): per pilot and per month. Current caps $5/video and $50
   pilot (D9) cannot fund generated cinematic footage; P6/P10 stay blocked until a number is set.
2. **Voice for commercial videos:** Google Chirp3 HD (free tier, GTTS-01) vs paid ElevenLabs (PR-04). Kaggle is
   non-commercial (KG-01).
3. **Look:** photorealistic actors (directive) vs stylised illustration (today). Photoreal needs synthetic-media
   disclosure on every upload (YT-07, IN-06) and only fictional faces.
4. **Database:** Postgres per `04_DATABASE_ARCHITECTURE.md` (more RAM on the shared server) or SQLite inside
   studio first. Recommendation: SQLite now behind the same schema, Postgres when a second server exists.
5. **Server:** the directive states 8 GB RAM; the owner earlier said about 4 GB is free and the studio is capped
   at 2 CPUs / 3 GB (D23). Confirm what the studio may use, and that heavy jobs run only 00:00–07:00 IST (this
   replaces the market-hours guard for heavy stages). Trading app and BagMitra are never touched.
6. **External worker:** a second VPS or a free GPU notebook for heavy work (Kaggle is non-commercial).

## 7. Risks

- **Cost:** generated video is billed per second; a 10-minute film is many clips plus retries. Mitigation: the
  ECONOMY/STANDARD mix (generated clips only for key moments), hard reservations, per-scene retry caps.
- **Character drift:** no model guarantees identity; similarity scores are indicators only (directive A08/A16).
- **Marathi dialogue in generated video:** native-audio language support unknown (VEO-03).
- **Rights:** AI output ownership is not guaranteed (directive A15); music and lip-sync model licences can bar
  commercial use. Licence records per asset are mandatory.
- **Shared server:** heavy stages stay in the night window with CPU/RAM caps; generation runs at providers.

## 8. Effort guide (sessions, not dates)

P0 one session; P1 one; P2 two; P3 two; P4 two; P5 two; P6 two plus provider waits; P7 two; P8 one; P9 one;
P10 one plus owner review. Model use per CLAUDE.md: Opus for P2 schema/contracts and final review, Sonnet for
modules and tests, Haiku for inventories.
