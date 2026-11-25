# Feature Film Studio Plan (V5.0 direction) — discussion and plan

Status: **PLAN ONLY, not approved.** Owner vision 2026-11-25: `directives/V5_FEATURE_FILM_VISION.md` (Marathi,
verbatim). It extends the V4.0 cinematic directive and its plan (`CINEMATIC_UPGRADE_PLAN.md`): the engineering
phases there (P0–P10) stay the build order; this file adds the feature-film engines and makes the owner's seven
deliverable phases the quality milestones. 16 agents, 0 new agents. Any provider fact not yet in `RESEARCH_LOG.md`
is `REQUIRES REVIEW (Phase 1)`; the owner's ₹ per-second table is the owner's own illustration, not a verified price.

## 1. Discussion: where the plan agrees, and where it advises caution

1. **Milestones first, 180 minutes last.** The owner's roadmap (60 s trailer → 5 min scenes → song → 15 min →
   45 → 90 → 180) is the right shape. Each milestone is a go/no-go gate on measured cost and quality, not a date.
2. **Start the actor library small.** Build 4 actors for Milestone 1 (hero, heroine, villain, elder) and add actors
   when a story needs them. 25 actors made up front cost reference images and voice work that may never be used.
   The registry is designed for any number from day one.
3. **Human review is part of the design, not an exception.** A 180-minute film is about 1,800 final shots
   (owner's table). The dashboard needs a fast approve/reject screen per shot; the owner's review time is a real
   production cost and is measured from Milestone 1.
4. **Budget arithmetic from the owner's own example.** ₹2,00,000 for 16,200 generated seconds (1,800 shots + 50 %
   retries) allows about ₹12.3 per generated second for video alone, before voice, music, lip sync and rendering.
   Whether that is possible depends on verified prices (VEO-02). Milestone 1 measures the real cost per accepted
   second; the 180-minute budget is set from that figure.
5. **The hardest parts.** Current generators are weakest at multi-character dialogue with correct lip sync, long
   fight choreography, dance synced to music, and a face staying the same across hundreds of shots. The plan
   tests exactly these in Milestones 1–3 before any long film.
6. **Marathi speech.** Whether generated video can speak Marathi natively is unknown (VEO-03). Safe route: our
   own per-actor voices (A07) + a lip-sync step, so the actor's voice is the same in every film.
7. **Music.** Suno/Udio public API and commercial terms must be verified (MUS-02). If no official API exists, songs
   are a clearly marked manual step (owner creates in the provider's app, uploads to the dashboard), never shown as
   automated. Singer voices are original; no imitation of real singers.
8. **Rights and policy.** AI actors, songs and footage may not be protectable as owned IP (directive A15); faces
   must not resemble real people; every upload carries the synthetic-media disclosure (YT-07, IN-06); romance stays
   adult, consensual and non-explicit; YouTube's inauthentic-content rules (YT-09) favour original, varied work.
9. **Format (opinion, no data yet).** A web series in 20–45 minute episodes may reach an audience and recover cost
   sooner than one 180-minute film, and uses the same engine. Analytics from early episodes then guide the long film.
10. **Server.** The VPS runs orchestration, dashboard, database and editing; generation runs at providers. Long
    4K masters are heavy for 2 vCPU in the night window; an external render worker is planned and its need is
    measured at Milestone 4.
11. **First things first.** The four open defects (P0 of the V4 plan) are fixed before any new engine.

## 2. The 16 core engines inside the 16 agents

| Engine (owner list) | Agent(s) | Builds on |
|---|---|---|
| Autonomous Film Production Management | A01 | V4 planning engine, modes, night window, budgets, approvals |
| Professional Feature Film Screenplay | A05 | V4 screenplay engine + configurable act structure (owner's 180-min table as one template) |
| Dialogue Intelligence | A05 | Dialogue segments with character background, age, education, emotion; silence and subtext allowed |
| Romance and Relationship | A05, A09 | Relationship graph with stage per scene (meeting → bond → conflict → resolution) in story state |
| Emotional Acting | A09, A08 | Shot-level performance notes (eyes, micro-expression, body language) compiled into prompts |
| Action Choreography | A09, A08 | Beat-by-beat fight/chase plans, continuity of injuries/props, slow-motion and SFX cues |
| Dance Choreography | A09, A08, A10 | Beat map from the song; short cut-based dance shots edited on the beat |
| Original Song and Music | A05 (lyrics), A07 (singing), A10 (score, mix, master) | Provider adapter after MUS-02; character/romance/villain/action themes; licence records |
| Digital Actor DNA | A08 (+A07 voice, A05 acting profile) | Actor Passport: physical, voice and acting DNA; versions; reference package |
| Permanent Voice DNA | A07 | VoiceProfiles incl. laugh, cry, anger, whisper styles only where the provider supports them; singer profiles |
| Digital Location | A08 (+A04 research) | Location Library: Location ID, reference stills per time of day, props, layout notes |
| Google Cinematic Video Generation | A08 | CinematicVideoProvider + Veo adapter after VEO-01..04; Flow as manual-assist |
| Visual Effects | A08, A10 | Generated VFX shots + FFmpeg compositing; deterministic where possible |
| Film Continuity | A09, A16 | SceneContinuityState across the whole film: costume, props, injuries, time of day, location state |
| Professional Post-Production | A10 | Scene-cached render, dialogue/music/ambience stems, grade, titles, credits, trailer/teaser/shorts cuts |
| Film Quality Assurance | A16 | 12 V4 gates + acting, dance-sync and long-range continuity checks; selective correction |

Supporting agents: A02 genre demand evidence; A03 franchise/universe; A04 period, culture and location research;
A06 plot and timeline logic; A11 posters; A12 movie metadata; A13 film, trailer, teaser and shorts publishing;
A14 scene-wise retention; A15 film budget and profitability.

## 3. New data (adds to the 20 V4 entities, reusing them where equivalent)

actor_passports (extends characters: physical DNA, acting DNA, roles played), singer_profiles (extends
voice_profiles), locations + location_versions + location_reference_assets, songs (lyrics, composition, singer,
licence), music_cues (scene, theme, mood), choreography_plans (fight/dance beats, linked to shots), films
(extends productions: mode, structure template, budget), shot_reviews (human approve/reject with reason and time).

## 4. Production modes (one engine, configuration only)

Cinematic Shorts 15–60 s · Music Video 3–7 min · Short Film 5–15 min · Web Series Episode 20–45 min · Mini Movie
45–60 min · Feature Film 90–120 min · Mega Feature Film 150–180 min. Each mode sets structure template, shot
count, song count, quality tier, budget cap, retry cap, review policy and render target (1080p; 4K only if the
provider supports it and the budget allows).

## 5. Build order

| Step | What | Owner milestone it serves |
|---|---|---|
| 0 | V4 P0 fixes (Cloudflare 429, Kaggle voice, preview race, picture prompts) | current videos |
| 1 | V4 P1 research + new: MUS-02 (Suno/Udio API and licence), DANCE-01 (motion/dance capability of video models), LOC-01 (location consistency via references) | budgets for everything below |
| 2 | Registries: Actor Passport (4 actors), Voice DNA, Location Library (3 locations), Film/Universe | Milestone 1 |
| 3 | Screenplay + dialogue engines, storyboard Stage A, continuity state | Milestone 1 |
| 4 | Video provider + lip sync + shot review screen → **Milestone 1: 60 s trailer** (measure cost/sec, consistency, review time) | M1 |
| 5 | Action and romance engines → **Milestone 2: 5 min scenes** | M2 |
| 6 | Music engine + dance → **Milestone 3: 5 min original song** | M3 |
| 7 | Full post-production, QA gates, publishing → **Milestone 4: 15 min short film** end to end | M4 |
| 8 | Long-run scheduling, external render worker, cost controls → **Milestones 5–7: 45 → 90 → 180 min** | M5–M7 |

Each milestone ends with: real output, measured cost/time/consistency/regeneration rate, owner score, and the
owner's written go-ahead and budget for the next one.

## 6. Owner decisions needed now

1. Approve this direction and the milestone gates (Milestone 1 = 60 s trailer).
2. Budget for Milestone 1 (paid video generation is required; amount set after Step 1 research gives prices).
3. First 4 actors: names, ages, look (photoreal fictional). Language of the first film: **Hindi (owner, D33)**.
4. Genre and one-line story idea for the trailer.
5. Earlier V4 decisions still open (`CINEMATIC_UPGRADE_PLAN.md` §6): voice provider, database, server limits,
   external worker.

## 7. Comparison with the owner's V5.0 master prompt (`directives/V5_FEATURE_FILM_MASTER_PROMPT.md`)

**Same direction.** 16 agents, no new agents; reuse V4; actor library, voice DNA, screenplay, dialogue, romance,
action, music, locations, Google video with Flow optional, storyboard before paid generation, per-shot continuity,
selective regeneration, budget reservation, night window, "never claim realism without measured validation".
The prompt's 19 sections map onto the 16 engines in §2 without a new agent.

**The prompt adds (adopted into this plan):**
1. Actor identity separate from the film role (an actor plays different characters in different films): data
   model = `actor_passports` (permanent) + `characters` (per film, linked to an actor version).
2. Story bible + incremental screenplay generation from structured memory (never resend the full script): cuts
   LLM cost for long films; matches CLAUDE.md token rules (§18 of the prompt).
3. Richer dialogue segments: listener, subtext, facial expression, body language, reaction of others.
4. Locations: interior/exterior, spatial layout, weather and day/night variants.
5. Workflow order puts **Music before Shot Generation** (songs and dance shots are cut to the music's beats).
6. Film configuration: content rating, target audience, story complexity, automatic vs human-assisted mode,
   configurable quality thresholds; duration any value 1–180 min (the 7 modes become presets).
7. Exports: individual songs, audio masters, posters, teaser, promotional clips.
8. QC dimensions: story, dialogue, romance chemistry, dance sync, originality.
9. Infrastructure: external object storage, disk-space monitoring, temp-file cleanup.

**Points that need the owner's decision or keep this plan's position:**
1. **Coding vs plan.** Prompt §19 says "Do not produce another architecture proposal instead of implementation";
   the owner's D34 says "no coding". This plan follows D34 until the owner gives the go-ahead to build.
2. **Human review.** The prompt keeps human review for unresolved critical defects only. This plan adds an owner
   shot-review screen in Milestones 1–4 to calibrate the automatic thresholds (prompt §14 asks for calibration
   on real samples); after calibration it narrows to critical defects as the prompt says.
3. **Validation order.** Prompt: trailer → dialogue+romance → action → song → 15-min film → extended-duration and
   recovery tests → 180 min. Vision: 60 s → 5-min action+romance → 5-min song → 15 → 45 → 90 → 180.
   Merged (proposed): **M1** 60 s Hindi trailer; **M2** dialogue + romance scene; **M3** action scene; **M4**
   original song with dance; **M5** 15-min short film; **M6** 45 and 90 min with pause/resume and failure-recovery
   tests; **M7** 180 min when budget and measured quality allow.
4. Not in the prompt, kept here: Phase 0 bug fixes first; start with 4 actors; Hindi first (D33); research gate
   with official prices before any spend; synthetic-media disclosure on every upload (YT-07, IN-06); faces must not
   resemble real people (the prompt covers voices; faces are added).
