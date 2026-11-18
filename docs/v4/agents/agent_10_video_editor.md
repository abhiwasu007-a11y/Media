# Agent 10 — Video Editor (blueprint)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** (rule 6, rule 7) |
| Owner | Agent 10 Video Editor; integration owner: Agent 01 (orchestrator) |
| Package | `agent_10_video_editor` (27 §7.2); worker `workers/render_worker` (SOURCE_LAYOUT; movable, ADR-012). **No LLM step: no prompt file exists** (§5, §26). Deterministic golden dataset: `evals/agent_10_video_editor/deterministic_core/` (§26) |
| Task types (24 §3.2) | `agent_10.render` (stage `s10_render`), `agent_10.subtitles` (`s10_subs`), `agent_10.technical_qc` (`s10_qc`, blocking gate); all `HEAVY_CPU` (24 §7.1) |
| Directive sections covered | §3.1 row 10 (FFmpeg render pipeline, resumable rendering, subtitles and accessibility, automated video inspection: integrity, duration, resolution, fps, aspect, black frames, missing audio, A/V and subtitle sync), §1A.4 (audio delivery), §1A.5 (video delivery), §1A.6 (automated QC), §1A.2 and §1A.8 (rendered-file side of the retention rules and formats), §1A.1 (tier mix and licence per shot, measured on the render), §1 Heavy work (FFmpeg as a separately configurable, movable worker), §3.3 (contracts, failures, checkpoints, quality, observability), §1C.1 (tenant isolation) |
| Owner decisions applied | D1 (3A production line with Agents 04–11 and the Agent 16 gates; outputs are files: MP4 16:9 (+ 9:16 where applicable), SRT, QC data for the report; no YouTube upload, no Google OAuth; paid calls only inside owner-set limits; keys only through the environment's secret mechanism; **render never in market hours**), D2 (full blueprint for 3A agents; REQUIRES REVIEW items do not block 3A unless they change a 3A design decision), D6 (IMPLEMENTATION_PROGRESS: no scoring without a licensed music bed; music is 3B and blocked until the owner chooses a source; 3A technical runs use no bed), D8 rule 4 (development environment only, nothing on the VPS: the VPS placement of this blueprint is specified but **disabled** until the owner lifts that rule) |
| Binding contracts | GLOSSARY_AND_IDS.md (§2 IDs, §3 units, §6.1–6.10, §6.17–6.22, §6.27–6.28, §6.31, §6.45, §6.50–6.52), 03_COMMUNICATION_STANDARD.md (§3–§9, §11), 04_DATABASE_ARCHITECTURE.md (§3, §5.4, §5.7, §5.9, §5.10, §5.12, §5.14, §5.15, §5.17, §5.18), 07_FAILURE_MANAGEMENT.md (§2–§4, §8–§10), 24_PRODUCTION_TYPES.md (§3.1–§3.3, §3.2, §4, §5, §7.1a `CHANNEL_LONG_FORM` v2, §7.2a `SHORTS` v2), 27_ENGINEERING_STANDARDS.md (§3–§9); decided register: CONTRACT_CHANGE_REQUESTS.md §5 "Resolved for blueprint 10" (CCR-001, -002, -003, -007, -015, -018…-020, -024, -030…-032, -038, -051, -055, -056) |
| Shared docs referenced by name/§ only | 18_PRODUCTION_QUALITY_STANDARD.md (§2.3, §3, §5, §6, §7, §8, §10, §13), 13_COMPLIANCE_YOUTUBE_POLICY.md (FIN-R rules, §3.6 licence completeness), 09_COST_AND_BUDGET.md (§5, §12), 08_SECURITY.md (§3 secrets, §5.3 identities, §8 tenant isolation), 3A_SLICE_SPEC.md (§3 flow, §4 bundle, ticket 3A-10), ADR-005 (storage), ADR-009 (visual and music sourcing), ADR-012 (render worker placement), agent blueprints 07, 08, 09 (producers of this agent's inputs), 06_NIGHT_SCHEDULING.md (owner of the market-hours and night-window configuration; not yet written) |
| Facts cited | RESEARCH_LOG INF-01 (VPS size), INF-03 / INF-04 (resource caps), INF-09 (FFmpeg `silencedetect`, `blackdetect`, `freezedetect`, `ebur128` incl. true peak), INF-10 (YouTube upload encoding), INF-11 (RLS), IN-02 / IN-03 (chart data age), YT-06 / YT-07 (synthetic-media disclosure), YT-09 (no AI persona on finance) |
| Marking | Every section states its **MVP** in the first line: 3A / 3B / 3C (owner build stages of D1) and Tier 0–3 (GLOSSARY §6.47) |
| Conventions | Every contract name used here is a real Wave A name (the register of CONTRACT_CHANGE_REQUESTS.md was applied; no pending marker remains). `REQUIRES REVIEW (Phase 1): <need>` = unknown value; none is invented. A value called **PROPOSAL** is a design default of this document (no source, calibrated in 3B), not a fact. **ESTIMATE** = derived by arithmetic from configuration or design, not measured. Config key names follow the registry rules of CCR-019/020 (family `agent_10.*`; `qc.*` IDs and keys are 18's, never new). `gate_verdict` is the GLOSSARY §6.52 echo; `remedy_stage_id` is the contract field of 03 §5.3 (the payload copy `failures[].remedy_stage` only echoes it). Field names of other agents' payloads are quoted from their blueprints, not redefined. |

---

## 1 Identity and mission
**MVP: 3A (render, subtitles, full automated QC; 9:16 when the `SHORTS` v2 child job runs, i.e. `owner_topic.shorts_wanted = true`) · 3B (detector and tolerance calibration on three golden samples; music-stem measurement once the owner has chosen the licensed source, D6) · 3C (preview and burned-in caption variants, 1440p, ad/dubbing profiles) · Tier 0 → Tier 1 (render-only worker before the first client) → Tier 3 (dedicated workers per tenant).**

### 1.1 Mission
Agent 10 is the editor's hands and the quality inspector's eyes. It turns three finished inputs — the **shot plan** (Agent 09), the **asset manifest** (Agent 08) and the **mastered narration** (Agent 07) — into **one frame-exact, resumable FFmpeg render** that meets the delivery specification of 18 §5–§6 (H.264 High, constant frame rate, 15–25 Mbps target with the INF-10 floor, AAC-LC 48 kHz at a configured nominal 384 kbps, MP4 faststart), writes **one accurate SRT per language**, and then **measures the finished file** with the blocking automated QC of 18 §7 (ffprobe, `ebur128`, `blackdetect`, `freezedetect`, `silencedetect`, A/V and subtitle sync, duration against the script and the timeline, no source watermark, a licence record for every shot). It decides nothing about what the video says or shows; it proves what the file contains.

It does three jobs on one worker and no others:
1. **Render** (`agent_10.render`): compile the render timeline, bind every shot to its asset, encode in checkpointed segments, mux the mastered audio, write the final MP4 once.
2. **Subtitles** (`agent_10.subtitles`): build the SRT from the approved script text and the narration timeline; validate it; never rewrite text.
3. **Technical QC** (`agent_10.technical_qc`): run the `qc.long_form` / `qc.shorts` check set on the final MP4, its stems, SRT and timeline; persist every result; return the gate verdict that routes REVISE or continues (24 §7.1).

### 1.2 Where it sits
Stages of `CHANNEL_LONG_FORM` v2 and, for the 9:16 cut, of the `SHORTS` v2 child job (24 §7.1a, §7.2a; 3A_SLICE_SPEC §3): `s10_render` (depends on `s07_master`, `s08_assets`, `s06_chart`), `s10_subs` (depends on `s10_render`), `s10_qc` (depends on `s10_subs`; **blocking gate**, `on_fail REVISE → s10_render`, `alt_target_stage_ids` `s07_voice`, `s08_assets`, `s09_plan`; CCR-002). The earliest stage named by the failing results' `remedy_stage_id` among target and alternatives is re-run with its dependants as a new iteration, at most `limits.max_revision_loops` (3) times; after that the job completes with `outcome = BLOCKED_COMPLIANCE` (24 §3.3, 18 §7.0.4). Downstream: `svc_s02.uniqueness_check`, `agent_16.compliance_gate`, `agent_16.quality_score` (reads `qc_results`), the `FINAL_VIDEO` approval (`a_final`, bound to the render's SHA-256), `agent_16.publication_authorisation` and `agent_13.file_delivery` (bundle). All three tasks run as `HEAVY_CPU` on the movable render worker (ADR-012).

### 1.3 Authority boundaries
| Agent 10 decides (by code, from contracts and measurement) | Agent 10 does **not** decide |
|---|---|
| frame quantisation of the plan, segment boundaries, FFmpeg arguments, encoder parameters inside the configured profile | what is on screen, when it changes, pacing, interrupts, J/L offsets, brand sting position, chapters (Agent 09; Agent 10 renders them as given and checks them) |
| whether a render may start now (market-hours and night-window guards; defence in depth over admission) | admission itself and the schedule (queue admission, 06; ADR-012) |
| the SRT cues (text from the script by reference; timing from the narration timeline) | any subtitle wording; translation (S3, 3C); the script (Agent 05) |
| the measurements of the final MP4 and each blocking/WARN verdict of 18 §7, and the technical `gate_verdict` | the 100-point score, the compliance verdict, disclosure decisions, publication authorisation (Agent 16) |
| which failures are render-fixable and a `remedy_stage_id` for each failing gate result | the revision route (the orchestrator picks the earliest named stage among the target and alternatives of `s10_qc`, 24 §3.3 rule 1) |
| nothing about money: it spends nothing paid | budgets, provider limits (owner, S4) |
Hard limits: no network call to any AI or stock provider; no LLM; no text of its own on screen or in subtitles; no re-sourcing or substitution of assets (a shot without an asset fails `PERMANENT.MISSING_DEPENDENCY`, Agent 08 §15); no loudness or limiter change of the narration (Agent 07 owns mastering; Agent 10 encodes with Agent 07's codec profile and re-measures); no upload; no write to any tenant other than the task's.

### 1.4 Success criteria (measurable; thresholds are config, sourced where 18 sources them)
| ID | Criterion | Measure | MVP |
|---|---|---|---|
| SC-1 | The delivered MP4 meets the video and audio delivery specification | 100 % of the blocking checks of §20.1 are `PASS` on the file handed to approval | 3A |
| SC-2 | The render is exactly the timeline | `|actual_ms − timeline_ms| ≤ 1 frame`; frame count equals the compiled frame count | 3A |
| SC-3 | A killed or drained render resumes without redoing finished segments and without a corrupt file at a final path | FI-01…FI-04 | 3A |
| SC-4 | No `HEAVY_CPU` task of Agent 10 (render, subtitles, QC) starts inside market hours, and a running one checkpoints before the next market window opens (`act_by`, CCR-056); on the VPS (disabled in 3A, D8 rule 4) also none outside the night window | FI-08, FI-09, FI-13, acceptance 27 §9 test 6 | 3A |
| SC-5 | Every shot, voice, font and template on the timeline has a usable licence record, or the QC gate fails | `qc.licence.completeness` zero gaps | 3A |
| SC-6 | Every check records its measured value; no check is silently skipped or defaulted to `PASS` | `qc_results` row per check of the profile; `SKIPPED` only in the listed cases | 3A |
| SC-7 | A failing gate tells the orchestrator and Agent 09/07/08 exactly what to fix | `gate: true` results with `remedy_stage_id`; `failures[]` with check ID, shot IDs, measured, threshold | 3A |
| SC-8 | Detectors and tolerances become calibrated thresholds | every "WARN until calibrated" check promoted or kept advisory by the owner (18 §11 exit criteria) | 3B |

---

## 2 Functional requirements
**MVP: 3A unless marked · Tier 0. "Why" cites the directive, 18, INF-09/INF-10 or ADR-012.**

### 2.1 Requirements
| ID | What | Why | When / trigger | Inputs | Outputs | Dependants | MVP |
|---|---|---|---|---|---|---|---|
| FR-01 | Validate Task Input, tenant scope, every ref and its SHA-256 before any media work | 03 §7; rule 9 | task start (`VALIDATING`/`RUNNING`) | Task Input, context refs | accept or `REJECTED` | all | 3A |
| FR-02 | Upstream gate: plan `timing_basis = MEASURED` (any other value is refused; no estimated mode exists, CCR-051) and covers the narration; manifest has an asset for every shot of the requested aspect and the reveal stills of every chart shot; audio master is `PASSED` and covers the narration; script SHA-256 equals the verified one | §1A.6; Agents 07/08/09 contracts | after FR-01 | plan, manifest, audio master output, script ref | gate result | FR-03 | 3A |
| FR-03 | Worker-side guards for **all three tasks**: market-hours guard (every placement) and night-window guard (VPS placement, disabled in 3A) at task start, before every segment and the mux, between QC check groups and evidence passes; a **self-drain timer** armed with `act_by` (next market-window start, or `07:00 − drain.grace` on the VPS) that checkpoints a running task at its next safe point | D1; ADR-012 §3.3; CCR-056 | task start, between units, timer | clock via admission probe, placement, ETA | allow / drain | FR-06, FR-13…FR-22 | 3A |
| FR-04 | Compile the **render timeline** `$T` (frame-quantised, canonical JSON, SHA-256) from plan + manifest (shots of the requested aspect, overlays, reveal stills) + audio master | 18 §3 (timeline SHA-256 = `renders.timeline_sha256`); Agent 09 §15.2 | after FR-02 | plan, manifest | `$T`, `timeline_sha256` | FR-05…FR-09, QC | 3A |
| FR-05 | Bind every on-screen text to its script string by SHA-256 and verify glyph coverage of the brand font for every code point | §1B.2; 13; Agent 09 AC-12 | FR-04 | `text_refs`, script, font asset | bound text or `INPUT_INVALID` | FR-07 | 3A |
| FR-06 | Plan **render segments** at GOP-safe shot boundaries | resumability (§1 Heavy work; 07 §10) | FR-04 | `$T` | segment list | FR-07 | 3A |
| FR-07 | Encode each segment with FFmpeg (argument list, no shell), verify, store atomically, checkpoint | 07 §8, §10; INF-10 | per segment | `$T` slice, assets | segment blob + checkpoint | FR-08 | 3A |
| FR-08 | Concatenate segments, mux the mastered audio with Agent 07's codec profile, pad audio to the video length, write MP4 faststart once | §1A.4, §1A.5; Agent 07 §15 | all segments done | segments, master WAV, `codec_profile` | final MP4 blob | FR-09 | 3A |
| FR-09 | Probe the final file and register the `renders` row (status `COMPLETE`) | 04 §5.18; 18 §6 "Metadata persisted" | FR-08 | final MP4 | `renders` row, render report | FR-10, QC | 3A |
| FR-10 | Resume: after a kill, drain or host restart continue from the latest checkpoint, re-verifying finished segments | 07 §8, §10; 27 §9 test 2 | T15 resume | checkpoint | same output as an uninterrupted run | — | 3A |
| FR-11 | Build the SRT per language from script text and the aligned narration timeline (always aligned in 3A, CCR-051); split by configured limits; one language in the MVP | §1A.5; 18 §7.6; 3A_SLICE_SPEC §4 | `agent_10.subtitles` | script, narration timeline, brand font | SRT blob, `assets` row (`SUBTITLE`) | QC, bundle | 3A |
| FR-12 | Validate the SRT format before QC (cue numbering, times, order, no overlap, UTF-8, last cue ≤ video duration) | 18 §7.6 | after FR-11 | SRT, render duration | `a10.sub.*` results | QC | 3A |
| FR-13 | Run container and stream metadata checks (ffprobe) against the preset | §1A.5; 18 §6, §7.1 | `agent_10.technical_qc` | final MP4, `$T` | `qc.video.*`, `qc.audio.*`, `qc.container.*` rows | gate | 3A |
| FR-14 | Measure loudness, true peak, LRA and (3B) music bed offset | §1A.4; INF-09; 18 §7.2, §7.4 | QC | final MP4, stems | `qc.audio.*` rows, `renders.integrated_lufs`, `.true_peak_dbtp` | gate, Agent 16 | 3A (music 3B) |
| FR-15 | Run `blackdetect`, `freezedetect`, `silencedetect`; map detections to shots and to the plan's `deliberate_black[]`, `deliberate_hold[]` and `audio_plan.deliberate_pauses[]` intervals (agent_09 §8, CCR register) | §1A.6; INF-09; 18 §7.3, §7.5, §7.8 | QC | final MP4, `$T` | `qc.video.black_frames`, `.freeze`, `qc.audio.silence_mix`, `edit.dead_air` rows | gate | 3A |
| FR-16 | Check A/V container sync, subtitle sync and subtitle accuracy | §1A.6; 18 §7.6 | QC | probe, SRT, narration timeline | `qc.sync.*`, `qc.subtitles.*` rows | gate | 3A |
| FR-17 | Check duration against the script, the timeline and the production-type bounds | §1A.6; 18 §7.7 | QC | probe, narration timeline, `$T` | `qc.duration.*` rows | gate | 3A |
| FR-18 | Check the retention edit rules that need the timeline or the rendered file: hook window, no brand intro, cadence (+ render cross-check), interrupts, J/L, chapters, end screen | §1A.2; 18 §3 | QC | `$T`, final MP4 | `edit.*` rows | gate, Agent 16 | 3A |
| FR-19 | Check licence completeness, licence expiry window, source watermark provenance, and the visual-source checks (tier share E, tier mix, AI budget, disclosure facts, chart data age, synthetic presenter metadata) | §1A.1, §1A.6; 18 §2.3, §7.9, §7.10; FIN-R9, FIN-R11; YT-06/07/09 | QC | `$T`, manifest, DB | `qc.licence.*`, `qc.watermark.*`, `qc.visual.*` rows | gate | 3A |
| FR-20 | Report every domain result with `gate: true` (blocking ones with their verdict, `remedy_stage_id` on failures), echo `gate_verdict` and `failures[]` | 03 §5.3 rule 4 (CCR-001); 24 §3.3; 18 §7.0.4 | end of QC | all results | gate output | orchestrator | 3A |
| FR-21 | Persist every result as a `qc_results` row, update `renders.status` (`QC_PASSED` / `QC_FAILED`) and measured columns, write evidence blobs | 18 §1.4; 04 §5.17, §5.18 | end of QC | results | rows, blobs | Agent 16, bundle | 3A |
| FR-22 | Produce the evidence pack: contact sheet of sampled frames and loudness-over-time data | owner rule A.12; 18 §11 evidence package (PROPOSAL) | QC | final MP4 | `IMAGE` + `REPORT` output refs | owner review | 3A |
| FR-23 | Run the QC self-test on every FFmpeg build change (synthetic `lavfi` fixtures, expected verdicts asserted) | 18 §7.11 | readiness / CI | fixtures | self-test record | readiness | 3A |
| FR-24 | Record render time as `render_ms` cost units | 24 §6; 09 §5 | every attempt | wall time | `cost_ledger` row | S4, cost report | 3A |
| FR-25 | Render the 9:16 cut for the `SHORTS` v2 child job with the `shorts_9x16` preset and `qc.shorts` | D1 "where applicable"; 24 §7.2a; 18 §10 | child job (`owner_topic.shorts_wanted = true`) | child plan | MP4 9:16 | bundle | 3A (only when the owner asks for the cut) |
| FR-26 | Render a low-resolution **PREVIEW** for a rough-cut approval | GLOSSARY §6.15 `ROUGH_CUT`; §6.45 `render_kind` | not in the 3A graph | plan | preview MP4 | S7 | 3C |
| FR-27 | Render the **EXPORT** variant with styled burned-in captions | §1A.5 (optional burned-in captions as a separate variant); 24 §4 | optional | SRT, caption style | MP4 variant | bundle | 3C |
| FR-28 | Measure the music bed offset on stems (narration-active spans) and clip/noise of stems | §1A.4; 18 §7.4 (CCR-007, CCR-055: Agent 07 produces the stems, Agent 10 measures them) | when a music bed exists (3B, after D6) | stems `$V`, `$M` | `qc.audio.music_bed_offset`, `qc.audio.clipping` | gate | 3B (music); clipping on the narration stem 3A |
| FR-29 | `qc.ad_spot`, `qc.dubbing`, `qc.corporate` profiles | 18 §8 | client types | profile config | rows | — | 3C, Tier 1+ |

### 2.2 Triggers and non-triggers
| Trigger | Result |
|---|---|
| Orchestrator creates `s10_render`, `s10_subs`, `s10_qc` tasks of a job (24 §7.1) | the task is queued on queue `render`; a render worker with capabilities `render_ffmpeg` + `media_probe` claims it only when admission allows (market hours, night window, ADR-012) |
| `s10_qc` reports a blocking gate FAIL (`gate_verdict = FAILED`) | the orchestrator re-runs the earliest stage named by the results' `remedy_stage_id` (target `s10_render` or alt `s07_voice`, `s08_assets`, `s09_plan`) and its dependants as a new iteration (new tasks, new idempotency keys) up to `limits.max_revision_loops`; after that the job completes with `outcome = BLOCKED_COMPLIANCE` (24 §3.3) |
| `DRAIN` control, guard closing or the self-drain timer reaching `act_by` | checkpoint at the next safe point, `CHECKPOINTED / DRAIN`, resume next window (T09, T15) |
| Replay from the DLQ | same Task Input and idempotency key; finished segments and the final blob are reused after verification (03 §9) |
| Not triggers | upload or publication (Agent 13, 3C); any change of script, plan or assets; any call to a provider |

### 2.3 Dependants (who reads what Agent 10 writes)
`renders` row and final MP4 → Agent 16 (score, authorisation), S7 (approval subject `content_sha256`), Agent 13 (bundle). `qc_results` → Agent 16 (`qc.*` evidence for scores: AUDIO_QUALITY, EDITING_QUALITY, VISUAL_QUALITY deterministic parts, COMPLIANCE licence line), S4 (cost report). SRT → bundle. Evidence pack → owner review (3B pilot). `failures[]` → Agent 09 (`revision_feedback`), Agent 07, Agent 08 through the orchestrator (24 §3.3 rule 7); the QC report of the delivery bundle (`qc_report` export preset, CCR-043) is built from `qc_results`.

---

## 3 Non-functional requirements
**MVP: 3A (targets set from measurement in 3B) · Tier 0. No figure below is measured; every number is a design default (PROPOSAL) or `REQUIRES REVIEW (Phase 1)`.**

| ID | Requirement | Target | Status / how verified |
|---|---|---|---|
| NFR-1 | **Render speed**: encode wall time per minute of output | not stated; **REQUIRES REVIEW (Phase 1): MEASURED on the walking skeleton in the development environment and on the VPS (24 §6 `render_ms`)** | metric `a10_render_wall_ms_per_output_s`; P-01 |
| NFR-2 | **Lost work after a kill** | at most one segment (+ the drain-finish window) | FI-01, FI-02 |
| NFR-3 | **Segment length** (checkpoint granularity vs overhead) | `agent_10.render.segment_target_ms` = 60 000 (PROPOSAL; calibrate in 3B) | P-02 |
| NFR-4 | **Determinism of the plan-to-timeline step**: same inputs give the same `$T` bytes and SHA-256 | exact | U-17…U-26, R-01 |
| NFR-5 | **Frame exactness**: output frame count = compiled frame count; CFR | exact | `qc.duration.vs_timeline`, `qc.video.cfr` |
| NFR-6 | **Atomic finals**: no partially written file exists at a final path; blobs are write-once | exact | 07 §8; FI-03 |
| NFR-7 | **Idempotency**: replay creates no second render row, no second final blob | exact | FI-05; 03 §9 `render.master` |
| NFR-8 | **No network and no paid call** from any Agent 10 code path | zero outbound connections except DB and storage; `max_llm_calls = 0`; `resource_budget.max_cost_micros = 0` | S-09 (socket guard), U-102 |
| NFR-9 | **Tenant isolation** (rule 9) | five layers, §19.1 | S-01…S-08 |
| NFR-10 | **Reproducibility**: one pinned FFmpeg build; build ID recorded with every render and every QC run | pinned value **REQUIRES REVIEW (Phase 1): 18 §7.0.2** | readiness check §24.3; QC self-test §21 R-02 |
| NFR-11 | **Portability**: placement by configuration only; same image everywhere | no code change to move (§1 Heavy work; ADR-012 §3.1) | IT-07 |
| NFR-12 | **Memory and disk bounded**: scratch directory per task, cleaned on completion and at worker start; segments streamed, never whole-video in memory | limits from systemd slice and Compose limits (INF-03, INF-04); values from measurement (05) | P-03, P-04 |
| NFR-13 | **Observability**: every log line/metric has `org_id`; no script text, subtitle text, asset titles or keys in logs | canary test | S-05 |
| NFR-14 | **Safe failure**: an unparseable or missing measurement is never `PASS` (18 §7.0.3) | exact | U-61…U-70 |
| NFR-15 | **Accessibility**: one accurate SRT per language, UTF-8 | 18 §7.6 | `qc.subtitles.*` |
| NFR-16 | **QC cost**: full-decode passes minimised; cheap checks first; optional single-pass mode proven equal to the reference passes before use | `agent_10.qc.single_pass` default off in 3A | R-02 fixture equality |
| NFR-17 | **No heavy work in market hours, including a task already running** (every placement; CCR-056): a running task of any of the three types reaches a checkpoint before the next market window starts | checkpoint written at or before `act_by`; lost work at most one segment or one QC pass | FI-08, FI-13, U-233, U-234 |

---

## 4 Internal architecture
**MVP: 3A · Tier 0. The package is library code run by `workers/render_worker`; no HTTP server, no public port. FFmpeg and ffprobe are local binaries called through `FfmpegRunner` (argument list, never a shell string).**

### 4.1 `agent_10.render` task flow
```mermaid
flowchart TD
  IN["Task Input (03 §7 validated)"] --> R1["R1 TenantScope: org of envelope, input, every ref"]
  R1 --> R2["R2 UpstreamGate: plan MEASURED, manifest covers every shot of the aspect incl. reveal stills, audio master PASSED, hashes"]
  R2 --> G1{"R3 HeavyWorkGuard: market hours closed? night window (VPS, disabled in 3A)? ETA fits before act_by?"}
  G1 -- "no" --> SUS["CHECKPOINTED / DRAIN (or admission refused before start)"]
  G1 -- "yes" --> R4["R4 TimelineCompiler: frame quantise, bind assets, text bind, font coverage, SHA-256"]
  R4 --> R5["R5 SegmentPlanner: GOP-safe boundaries, ResumeVerifier over checkpoint"]
  R5 --> L{"next unfinished segment"}
  L -- "guard closed" --> SUS
  L -- "segment" --> R6["R6 SegmentEncoder: ffmpeg argv, .part file, verify frames, atomic rename, checkpoint"]
  R6 --> L
  L -- "none left" --> R7["R7 Muxer: concat copy + mastered audio (codec profile) + pad + faststart, .part then rename"]
  R7 --> R8["R8 RenderProbe + RenderRegistrar: renders row COMPLETE, render report, cost row"]
  R8 --> OUT["Task Output SUCCEEDED: render ref, timeline ref, SHA-256s"]
  R6 -. "checkpoint per segment" .-> CK[("checkpoints")]
  R4 -. "checkpoint" .-> CK
  DR["DRAIN control / self-drain timer at act_by / 07:00 stop (VPS)"] -.-> L
```

### 4.2 `agent_10.subtitles` and `agent_10.technical_qc` flows
```mermaid
flowchart TD
  subgraph SUBS["agent_10.subtitles"]
    S1["S1 TenantScope + HeavyWorkGuard + gate: script SHA-256, narration timeline aligned (PROVIDER_CLIPS or OWNER_MARKS)"] --> S2["S2 CueBuilder: script text by segment id, split by limits, timing from narration timeline"]
    S2 --> S3["S3 SrtWriter: UTF-8, LF, numbered cues"] --> S4["S4 SrtValidator (format, order, overlap, last cue <= video duration)"]
    S4 --> S5["S5 write-once blob + assets row SUBTITLE + output ref"]
  end
  subgraph QC["agent_10.technical_qc"]
    Q0["Q0 TenantScope + HeavyWorkGuard + load render, timeline, SRT, stems, manifest, plan"] --> Q1["Q1 QcPlan: profile checks, cheap first; guard before every group"]
    Q1 --> Q2["Q2 ffprobe + CFR packet test + MP4 atom order"]
    Q2 --> Q3["Q3 audio passes: ebur128 (true peak), silencedetect final mix + narration stem"]
    Q3 --> Q4["Q4 video passes: blackdetect, freezedetect, scene cadence"]
    Q4 --> Q5["Q5 timeline and DB checks: edit.*, licence, sourcing, watermark provenance"]
    Q5 --> Q6["Q6 sync, subtitles, duration"]
    Q6 --> Q7["Q7 GateAggregator: gate_verdict, failures with remedy_stage_id"]
    Q7 --> Q8["Q8 persist qc_results, renders status + measures, evidence pack, report blob"]
  end
```

### 4.3 Interaction with neighbours (one stage, one direction of data)
```mermaid
sequenceDiagram
  participant O as Orchestrator (01)
  participant W as Render worker (Agent 10)
  participant C as amw_core (tenancy, storage, cost, audit, retries)
  participant F as FFmpeg / ffprobe (local)
  participant N as Agents 16 / 13, S7
  O->>W: s10_render Task Input (plan, manifest, audio master refs)
  W->>C: open tenant transaction, verify refs and SHA-256
  W->>W: gates, timeline compile, segment plan (pure code)
  loop per segment
    W->>F: encode segment (argv list, protocol whitelist)
    W->>C: store blob atomically, write checkpoint
  end
  W->>F: concat + mux + faststart
  W->>C: renders row, report blob, cost row, audit
  W-->>O: SUCCEEDED
  O->>W: s10_subs then s10_qc
  W->>F: ffprobe and detector passes on the final MP4
  W->>C: qc_results, renders.status, evidence
  W-->>O: gate_verdict (PASSED or FAILED with failures)
  O->>N: s02u, s16_comp, s16_score read qc_results; FINAL_VIDEO approval binds the render SHA-256
```

### 4.4 Components and boundaries
| Component | Responsibility | Talks to |
|---|---|---|
| `TenantScope` | the one place that checks org, channel and URI ownership; opens tenant transactions via `amw_core.tenancy` | DB, storage |
| `UpstreamGate`, `HeavyWorkGuard`, `SelfDrainTimer` | deterministic gates before any media work; the timer raises the internal drain flag at `act_by` for all three tasks | DB (RLS), storage, admission probe |
| `TimelineCompiler`, `FrameQuantiser`, `RevealStepBuilder`, `TimelineHasher`, `TextBinder`, `FontCoverage` | plan → canonical frame-quantised timeline (incl. reveal steps of chart shots); text binding; glyph check | storage |
| `SegmentPlanner`, `ResumeVerifier`, `CheckpointWriter` | segment boundaries, resume decision, durable progress | storage, `checkpoints` |
| `ArgvBuilder`, `FfmpegRunner`, `SegmentEncoder`, `Muxer`, `RenderProbe` | FFmpeg invocation and verification | local binaries, scratch dir |
| `CueBuilder`, `SrtWriter`, `SrtParser`, `SrtValidator` | subtitles | storage |
| `QcPlan`, parsers, `*Checks`, `GateAggregator`, `EvidenceWriter`, `QcPersister` | technical QC | DB, storage, local binaries |
| `RenderRegistrar`, `CostRecorder`, `ErrorMapper` | persistence, cost, error mapping | DB, `amw_core` |
Dependency rule (27 §7.1): the package imports `amw_core` and the `FfmpegRunner` / `AdmissionProbe` Protocols only; concrete implementations are injected by the worker. No package imports another agent; hand-offs are contracts only.

---

## 5 Full system prompt
**MVP: 3A (statement only) · Tier 0. Agent 10 has no LLM step, so there is no system prompt, no prompt file under `prompts/agent_10_video_editor/` and no LLM adapter in its package. This section states why and what replaces the prompt.**

### 5.1 Statement
| Item | Statement |
|---|---|
| LLM steps | **none**. `max_llm_calls = 0` and `max_cost_micros = 0` are written into every Agent 10 Task Input by the orchestrator (03 §3.1 `resource_budget`); a nonzero value is `PERMANENT.INPUT_INVALID` (§7.4). |
| Prompt file | none exists. 27 §4 (prompt standard) and the prompt lint have nothing to check for this agent; CI asserts that `prompts/agent_10_video_editor/` contains no prompt file and that the package imports no LLM adapter (test S-09, §21). |
| Why no model | every Agent 10 decision is arithmetic on a plan, a manifest and measured tool output, or a measurement of a file (§6). A model would add cost, variance and an injection surface, and no 18 check that Agent 10 owns needs judgement of meaning. Deterministic checks run first (24 §3.3.4); nothing here replaces them. |
| What replaces the prompt | (a) the typed contracts of §7–§8; (b) the decision rules of §6, written so a test can recompute them; (c) the deterministic golden dataset `evals/agent_10_video_editor/deterministic_core/` (120 cases, §26); (d) the lavfi self-test fixtures of 18 §7.11 (§21 R-02). |
| Judged checks that touch this agent's files | `qc.watermark.visual`, `qc.visual.no_synthetic_presenter` (frame-sampling judge) and `edit.promise_alignment` are judged by **Agent 16** (it holds the LLM key and the rubric; CCR-058). Agent 10 supplies the evidence only: sampled frames of the final MP4 as `IMAGE` output refs with SHA-256 and the deterministic fallback result of 18 §7.10. Agent 10 records the judged part of those checks as `SKIPPED` with message `JUDGED_BY_AGENT_16`, never as `PASS`. `qc.subtitles.accuracy`: the SRT text is the script string by reference, so the deterministic word-overlap is 100 % by construction and the judge remainder is empty; the human spot check stays at final approval (18 §7.6). |
| Prompt-injection surface | none from a model. Untrusted text (script strings, asset metadata, filenames, tool stderr) is data: never placed on a command line, never evaluated, never logged (§19.3). |

### 5.2 If an LLM step is ever proposed
A change request (CHANGE_REQUESTS.md) is required, with the justification that no deterministic rule can decide the item; the step would then get a prompt file from `prompts/_TEMPLATE.v1.md`, a judged dataset of at least 20 cases and a new LLM key on the render worker, which today holds none (§19). None is proposed.

---

## 6 Decision engine
**MVP: 3A (all rules) · 3B (calibration of every value marked PROPOSAL or REQUIRES REVIEW) · Tier 0. Every decision of Agent 10 is deterministic code; this section fixes the rules so that tests (and the golden dataset) can recompute them.**

### 6.1 Deterministic vs LLM, and why
| Decision | Kind | Why |
|---|---|---|
| tenant and reference validation, hash checks | deterministic | exact equality; a model must never decide a tenancy question (08 §5.3) |
| upstream gate (plan `timing_basis = MEASURED`, manifest covers every shot and reveal still, audio master `PASSED`, script hash) | deterministic | contract fields |
| market-hours and night-window guard | deterministic | operational rule of D1 and ADR-012; clock and configuration only |
| frame quantisation, timeline compile, segment plan, segment key | deterministic | exact arithmetic; the render must be reproducible (NFR-4) |
| FFmpeg arguments | deterministic | built from a closed set of templates by `ArgvBuilder`; no text from inputs reaches an argument |
| SRT cues | deterministic | text by reference, timing from the narration timeline; wording is never touched |
| every QC measurement and verdict | deterministic | FFmpeg filters of INF-09 plus arithmetic; thresholds from configuration |
| gate results, `gate_verdict` echo and `remedy_stage_id` | deterministic | table of §6.5; the orchestrator decides the route (24 §3.3 rule 1) |
| judging frames for watermark or synthetic presenter | **not Agent 10** (Agent 16, LLM judge on Agent 10's evidence frames) | needs meaning; Agent 10 has no model |

### 6.2 Frame quantisation and the render timeline
Project frame rate `fps_num/fps_den` comes from configuration (`agent_10.render.fps_num`, `.fps_den`); it has **no default**: **REQUIRES REVIEW (Phase 1): owner footage and screen-recording frame rate (18 §6)**; an unset value is `PERMANENT.CONFIG_INVALID`.
1. `frame(t_ms) = (t_ms × fps_num + 500 × fps_den) // (1000 × fps_den)` (round half up, integers only).
2. Every shot boundary of the plan is quantised; durations are derived (`end_frame − start_frame`), so the tiling of the plan is preserved and `Σ frames = total_frames`. A shot that quantises to zero frames is `PERMANENT.INPUT_INVALID` (`ZERO_FRAME_SHOT`); a gap or overlap in the plan is `INPUT_INVALID` (`TILING_GAP`, `TILING_OVERLAP`): Agent 10 never repairs a plan.
3. `total_frames = frame(total_duration_ms)`; the expected render duration is `frames_to_ms(total_frames) = round_half_up(total_frames × 1000 × fps_den / fps_num)`; `qc.duration.vs_timeline` passes when `|actual_ms × fps_num − total_frames × 1000 × fps_den| ≤ 1000 × fps_den` (one frame).
4. Overlays (`BRAND_STING`, `LOWER_THIRD`, `CAPTION_CARD`, `CHAPTER_CARD`, `DISCLAIMER_CARD`, `END_SCREEN`) are quantised the same way and composited on the V2 track; they never change the length of V1.
5. A transition (`transition_in.duration_ms > 0`) is rendered inside the first frames of the incoming shot; the outgoing shot's last frame is held for the blend (no extra source material is read). **REQUIRES REVIEW (Phase 1): owner look check in 3B**; the plan's own `no fade to black` rule (agent_09 TE-33) is not changed here.
6. The **timeline `$T`** is canonical JSON (sorted keys, no insignificant whitespace, integers and strings only): fps, total frames, per shot `{shot_id, start_frame, end_frame, plan_start_ms, plan_end_ms, asset_id, asset_sha256, asset_uri, source_in_ms, crop, motion, transition_in, tier, change_events_ms[], reveal_steps[]}`, per overlay `{overlay_id, kind, start_frame, end_frame, template_asset_id, text_sha256s[]}`, `audio {master_sha256, duration_ms, codec_profile_sha256}`, `preset_key`, `render_kind`, `colour {primaries, transfer, matrix, range}` (item 9). Plan milliseconds are kept next to the frames because licence matching uses plan milliseconds (18 §7.9). `timeline_sha256 = SHA-256(canonical JSON)`; it is `renders.timeline_sha256` and the natural key of `render.master` (03 §9.2).
7. **Selection of the manifest entry.** The Agent 08 manifest holds one `shots[]` entry per (shot, aspect); Agent 10 selects the entry whose `shot_id` equals the plan's and whose `aspect_ratio` equals the payload `aspect_ratio`; entries of other aspects are ignored; no entry for the requested aspect is `MISSING_DEPENDENCY` (`NO_ASSET:<shot_id>`). Overlays: the plan's `template_ref` (URI) must equal the URI of the asset that the manifest's overlay entry (CCR-031: `overlays[]` of the manifest, keyed by `overlay_id`) names as `template_asset_id`; a difference is `INPUT_INVALID` (`TEMPLATE_MISMATCH:<overlay_id>`); `$T.template_asset_id` is that asset.
8. **Reveal steps of chart shots** (`RevealStepBuilder`; agent_08 §6 item 7, agent_09 §8.2 `change_events_ms`). Agent 09 gives a chart shot's reveal steps as `change_events_ms[]` (absolute plan ms, strictly inside the shot, strictly increasing); Agent 08 renders `len(change_events_ms) + 1` stills in order (progressively more bars) and lists them as the shot's reveal sequence in the manifest field `shots[].reveal_stills[]` (agent_08 §8.2, rule 9: ordered by `k`, each entry `{k, asset_id, asset_uri, sha256, start_ms, end_ms, licence_id, ledger_entry_ids}`, an empty array for a shot that is not a chart shot; one `IMAGE` ledger row per still, written at sourcing). Agent 10 realises the change events from those stills: `reveal_steps[k] = {start_frame, asset_id, asset_sha256, asset_uri}` (copied from `reveal_stills[k]`; `reveal_stills[k].start_ms` must equal the shot start for `k = 0` and `change_events_ms[k−1]` for `k ≥ 1`, else `INPUT_INVALID`, `REVEAL_COUNT:<shot_id>`) with `start_frame` = shot `start_frame` for `k = 0` and `frame(change_events_ms[k−1])` for `k ≥ 1`; each step is shown until the next step or the shot end. Rules: the still count must equal `len(change_events_ms) + 1` (`INPUT_INVALID`, `REVEAL_COUNT:<shot_id>`); two steps that quantise to the same frame or a step at the shot's end frame is `INPUT_INVALID` (`ZERO_FRAME_REVEAL:<shot_id>`); every still must carry an `assets` row with a ledger row (a still without one is `MISSING_DEPENDENCY`, `NO_ASSET:<shot_id>#<k>`); no still is generated or altered by Agent 10. For shots that are not charts, `change_events_ms` are plan-internal motion keyframes (no stills) and are copied into `$T` unchanged so that `edit.visual.cadence` can read shot boundaries and change events from `$T`. The manifest field is `shots[].reveal_stills[]` (agent_08 §8.2; contract test C-05 pins the name and its item fields).
9. **Colour tagging (18 §6 "Colour": SDR, primaries and transfer tagged in the stream; values fixed here).** Config keys `agent_10.render.color_primaries`, `.color_trc`, `.colorspace`, `.color_range`, **PROPOSAL: `bt709`, `bt709`, `bt709`, `tv`** for SDR 1080p (no HDR, 18 §6). **REQUIRES REVIEW (Phase 1): official YouTube confirmation of the tagging values for SDR uploads** (not in RESEARCH_LOG). `ArgvBuilder` sets the corresponding encoder output flags and the scale filter's matrix; `RenderProbe` reads `color_primaries`, `color_transfer`, `color_space`, `color_range` from ffprobe and the process check `a10.q.colour_tags` (§20.1 row 59) compares them with the configuration: a missing or different tag is `RESOURCE.RENDER_CRASH` (verification failure, §18), never silently accepted.

### 6.3 Segments, keys and resume
1. **Segment plan** (`SegmentPlanner.plan`): iterate shots in order; a segment closes at the first shot end where its accumulated frames are `>= target_frames` (`target_frames = ceil(agent_10.render.segment_target_ms × fps_num / (1000 × fps_den))`); shots are never split, so every segment starts on a shot boundary (**GOP-safe**: the encoder is forced to start each segment with an IDR frame and closed GOP); the last segment takes the remainder. Cases DC-14…DC-18.
2. **Segment key** = SHA-256 of canonical JSON `{slice_sha256, asset_sha256s[], args_sha256, ffmpeg_build_id}`; the segment blob is `jobs/<job>/renders/segments/<key>.mp4` (write-once, content-addressed, tenant-prefixed). The same key means the same bytes, so a finished segment is reused after a kill, a drain, a DLQ replay **and** across revision iterations when only other shots changed (cases DC-19, DC-20). Reuse always re-verifies size, SHA-256 and frame count.
3. **Resume** (`ResumeVerifier.verify`): for each planned segment in order: blob present and SHA-256 equal to the checkpoint state → skip; blob present but no checkpoint entry (killed between rename and checkpoint) → recompute SHA-256 and frame count with ffprobe, accept if the frame count equals the plan, then write the checkpoint; otherwise encode. The first unverified segment ends the skip run; nothing after it is trusted without verification.
4. **Drain**: before each segment `HeavyWorkGuard.may_start_segment` runs (§6.4). A segment in flight when the `DRAIN` control arrives, or when the self-drain timer reaches `act_by` (§6.4), is finished when its estimated end is before `act_by`; otherwise FFmpeg receives SIGTERM, the `.part` file in scratch is discarded and the task checkpoints (lost work at most one segment, NFR-2). A segment whose real duration overruns its estimate is stopped the same way when `act_by` arrives (FI-13).

### 6.4 Heavy-work guard (D1; ADR-012 §3.3; CCR-056; defence in depth over admission)
**Scope (CCR-056).** The guard applies to **every** `HEAVY_CPU` task of this agent: `agent_10.render`, `agent_10.subtitles` and `agent_10.technical_qc`, on every placement. Admission does not start them in market hours; the worker re-checks (a) at task start, (b) before every render segment and the mux, (c) before every QC check group and every evidence pass (a full-decode pass is one unit), (d) in the **self-drain timer** below.

`may_start_segment(now_local, est_segment_ms, placement, drain_flag, market_windows, night_window)` (the same function serves a QC group or evidence pass, with its own estimate) returns `(allowed, reason)`; reason order: `DRAIN` → `MARKET_HOURS` (the interval `[now, now + est)` intersects a market window; **every placement**; window intervals are half-open `[start, end)`, so a unit that starts exactly at a window's end is allowed, DC-88) → `OUTSIDE_NIGHT_WINDOW` (`VPS` only: `now` not inside 00:00–07:00) → `NIGHT_WINDOW_END` (`VPS` only: `now + est > 07:00 − drain.grace`). `est` is rounded up to whole minutes. A holiday is simply a day without a window in the calendar the function receives.

**Drain point and `act_by`.** `act_by` = the earlier of (i) the start of the next market window and (ii) on the `VPS` only, `07:00 − drain.grace` (this is the **drain point**; the 06:30 scheduler flag only stops new admission, 07 §8, and a running task may continue until `act_by`, ADR-012 §3.3). A new unit starts only if `now + est ≤ act_by`. `SelfDrainTimer` (pure function `act_by(now_local, placement, windows, night)` plus a timer in the worker) is armed at task start with `act_by`; when it fires it sets the internal drain flag: the task checkpoints at its next safe point; a segment or QC pass still running whose estimate was too low is SIGTERM-ed, its `.part` discarded and the task checkpoints before the window opens (`CHECKPOINTED / DRAIN`, T09; resume T15). The timer is independent of admission and of any external `DRAIN` control (FI-13).

**ETA.** On `VPS` an unset ETA calibration (`agent_10.render.eta_ms_per_output_s`) is `PERMANENT.CONFIG_INVALID` (fail closed); on the development placement an unset estimate uses the segment length × 1.0 (**ESTIMATE until NFR-1 is measured**); the timer makes a low estimate harmless. The market-hours calendar and the night-window values are operational configuration owned by 06_NIGHT_SCHEDULING.md (not yet written; keys `ops.market_windows`, `ops.night_window`, `drain.grace_ms`); **REQUIRES REVIEW (Phase 1): RESEARCH_LOG entry for the official exchange sessions and holidays**. **VPS placement is disabled in 3A (D8 rule 4)**; the VPS branches of the guard are implemented and tested with a fake `AdmissionProbe` only. Cases DC-86…DC-94, DC-105…DC-108.

### 6.5 QC verdict mapping, gate and advisory remedy
1. **Verdict mapping** (18 §7.0.4): a sourced threshold gives `PASS` / `FAIL` with `blocking = true`; an unsourced one gives the measured value, `threshold = null`, `WARN`, `blocking = false`. A check turns from WARN to blocking only when its configuration key is set (`qc.*`, 18 §13); no verdict logic changes.
2. **Safe failure** (NFR-14): a missing or unparseable measurement raises `MeasurementUnavailable` (mapped to `AGENT.CRASH`, or `RESOURCE.RENDER_CRASH` if the process died abnormally, 18 §7.0.3); it is never `PASS`, never defaulted.
3. **Gate** (`GateAggregator.decide`; CCR-001): every `qc.*` and `edit.*` result of `agent_10.technical_qc` is reported in `validation_results` with `gate: true`; a sourced blocking check carries `blocking: true` with **either** verdict (`PASS` and `FAIL` alike, 03 §5.3 rule 4; DC-40, DC-44, DC-45 …); `WARN` and `SKIPPED` are always `blocking: false`. The gate has **failed** (`gate_verdict = FAILED`) if any check of the profile (`qc.long_form` or `qc.shorts`, 18 §7.12) has no result, or has `gate: true`, `blocking: true`, `verdict = FAIL`; otherwise `PASSED`. The task is `SUCCEEDED` with `next_action = {type: CONTINUE, reason: "gate FAILED: …"}` when the gate failed (03 §5.3 rule 4). `a10.q.*` and `a10.sub.*` results are process-integrity checks with `gate: false`; a FAIL among them fails the task (rule 2). `failures[]` lists the failed checks in profile order (cases DC-83…DC-85, DC-117).
4. **`remedy_stage_id`** (contract field of 03 §5.3, CCR-001/002; the payload echo `failures[].remedy_stage` carries the same value) is set on every failing gate result, one of `s07_voice`, `s08_assets`, `s09_plan`, `s10_render` (the target and alternatives of `s10_qc` in 24 §7.1a / §7.2a). The orchestrator re-runs the earliest named stage (24 §3.3 rule 1):
| Check family | `remedy_stage_id` | Reason |
|---|---|---|
| `qc.video.resolution/codec_profile/pix_fmt/bitrate/cfr/fps_matches_project`, `qc.container.faststart`, `qc.audio.codec/sample_rate/channels/bitrate`, `qc.sync.*`, `qc.duration.vs_timeline`, `qc.subtitles.format/languages/sync` | `s10_render` | encoder or mux settings, the render itself |
| `qc.audio.true_peak`, `integrated_lufs`, `clipping`, `music_bed_offset`, `qc.audio.silence_mix`, `edit.dead_air`, `qc.duration.vs_script` (render shorter than narration) | `s07_voice` | narration and mastering (18 §7.2) |
| `qc.video.black_frames` | `s08_assets` | a black or empty asset on a listed shot |
| `qc.video.freeze`, `edit.*` (hook, cadence, interrupts, J/L, chapters, end screen), `qc.visual.tier_share_e`, `qc.visual.ai_video_budget` | `s09_plan` | plan structure and tier plan |
| `qc.licence.*`, `qc.watermark.*`, `qc.visual.ai_disclosure_recorded`, `chart_data_age`, `no_synthetic_presenter` | `s08_assets` | sourcing and licence records |
`a10.*` results have no remedy (process-integrity). Rule: a failure that re-rendering cannot fix is routed to the stage that can; the loop cap and its outcome are in §1.2. A gate result without a mappable check ID is `ConfigInvalid` (test C-08).

### 6.6 Revision behaviour
A new iteration is a new set of tasks (24 §3.3.1). Agent 10 reads `previous_render_ref` only to reuse content-addressed segments; it carries no judgement from the last iteration. `failures[]` of the last gate reach Agent 09/07/08 through the orchestrator (`revision_feedback`, agent_09 FR-17), not through Agent 10.

### 6.7 What Agent 10 never decides
Pacing, cuts, interrupts, tier choices, subtitle wording, loudness targets, whether to publish, whether a licence is acceptable (it only checks the records), whether a failed gate repeats (orchestrator).

---

## 7 Input schema
**MVP: 3A (render, subtitles, QC) · 3B (`music_bed` stays null until the owner decision D6) · 3C (`render_kind` PREVIEW/EXPORT, caption style, `qc.ad_spot`, `qc.dubbing`) · Tier 0. Payload names are `agent_10.render.input`, `agent_10.subtitles.input`, `agent_10.technical_qc.input` 1.0.0 (registered by being defined here, 03 §2.1, CCR-018). All three travel in the 03 §3 Task Input.**

### 7.1 Task Input mapping (03 §3.1)
| Field | Rule for Agent 10 |
|---|---|
| `org_id`, `job_id`, `task_id`, `project_id`, `channel_id` | must equal envelope and DB context; `project_id` and `channel_id` not null for `CHANNEL_LONG_FORM` and `SHORTS` |
| `agent_id` | `agent_10` |
| `source_agent` | `agent_01` |
| `priority` | as set by the orchestrator |
| `deadline` | optional; a render that cannot finish before it is not started (`PERMANENT.DEADLINE_EXCEEDED`) |
| `context_refs` | the upstream outputs, each `purpose = PRIOR_OUTPUT` with `schema` naming the producer payload: `agent_09.shot_plan.output` (plan blob), `agent_08.asset_sourcing.output` (manifest incl. overlays and reveal sequences), `agent_07.audio_master.output`, `agent_07.voice_synthesis.output` (narration timeline), and the script document (`schema = agent_05.script_document`; in a `SHORTS` v2 child job the script of `s05_shorts`); `BRAND_KIT` (fonts, overlay templates, brand sting); `TEMPLATE`; each with `sha256`. `s06_chart` is a graph dependency only (the chart facts are verified before the render); no ref of it is read. Exactly one ref per schema; zero or two is `INPUT_INVALID`. QC and subtitles add the render output and the SRT output refs |
| `resource_budget` | `max_cost_micros = 0`, `max_llm_calls = 0`, `max_wall_ms` set from the ETA calibration (**REQUIRES REVIEW (Phase 1): NFR-1**), `max_render_ms` = same as wall |
| `idempotency_key` | scope `task.<task_type>` (03 §9.2); inside the task `render.master` for the final file and `render.segment` per segment (CCR-015) |
| `schema_version` | `1.x.y` |

### 7.2 Payload `agent_10.render.input` 1.0.0
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:amw:schema:agent_10.render.input:1.0.0",
  "title": "agent_10.render input payload (payload.data of amw.task_input)",
  "type": "object",
  "additionalProperties": false,
  "required": ["render_kind", "preset_key", "aspect_ratio", "language", "iteration", "verified_script_sha256",
               "previous_render_ref", "music_bed"],
  "properties": {
    "render_kind": { "enum": ["MASTER"], "description": "3A: MASTER only (GLOSSARY §6.45); PREVIEW and EXPORT are 3C" },
    "preset_key": { "enum": ["yt_master_1080p", "yt_master_1440p", "shorts_9x16"] },
    "aspect_ratio": { "enum": ["16:9", "9:16"] },
    "language": { "type": "string", "pattern": "^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$", "description": "BCP 47; one language in the MVP" },
    "iteration": { "type": "integer", "minimum": 0 },
    "verified_script_sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$", "description": "the script_sha256 that Agent 06 verified (agent_06.claim_verification.output, CCR-049); must equal the script ref hash" },
    "previous_render_ref": { "oneOf": [ { "type": "null" }, { "$ref": "#/$defs/blob_ref" } ],
        "description": "only for content-addressed segment reuse (§6.3); never a source of decisions" },
    "music_bed": { "oneOf": [ { "type": "null" }, { "$ref": "#/$defs/music_bed" } ],
        "description": "adapter input, §7.5. Null in 3A (D6); non-null while agent_10.music_enabled is false is PERMANENT.INPUT_INVALID" }
  },
  "$defs": {
    "ast_id": { "type": "string", "pattern": "^ast_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$" },
    "lic_id": { "type": "string", "pattern": "^lic_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$" },
    "lcu_id": { "type": "string", "pattern": "^lcu_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$" },
    "music_bed": {
      "type": "object", "additionalProperties": false,
      "required": ["asset_id", "licence_id", "ledger_entry_ids", "music_stem", "voice_stem"],
      "properties": {
        "asset_id": { "$ref": "#/$defs/ast_id" },
        "licence_id": { "$ref": "#/$defs/lic_id" },
        "ledger_entry_ids": { "type": "array", "minItems": 1, "items": { "$ref": "#/$defs/lcu_id" } },
        "music_stem": { "$ref": "#/$defs/blob_ref" },
        "voice_stem": { "$ref": "#/$defs/blob_ref" }
      }
    },
    "blob_ref": { "type": "object", "additionalProperties": false, "required": ["uri", "sha256"],
      "properties": { "uri": { "type": "string", "maxLength": 1024 }, "sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" } } }
  }
}
```
Targets (−14 LUFS, −1 dBTP, 48 kHz, music band −20…−15 dB, bitrate floors) are **configuration keys**, never payload fields (as for Agent 07). The codec parameters of the audio encode come from Agent 07's typed `codec_profile` `{codec, profile, sample_rate_hz, channels, bitrate_bps, encoder, rate_mode}` (CCR-055), read from the audio master output, never from this payload.

### 7.3 Payloads `agent_10.subtitles.input` and `agent_10.technical_qc.input` 1.0.0
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:amw:schema:agent_10.subtitles.input:1.0.0",
  "title": "agent_10.subtitles input payload",
  "type": "object",
  "additionalProperties": false,
  "required": ["render_id", "language", "iteration", "verified_script_sha256", "caption_style"],
  "properties": {
    "render_id": { "type": "string", "pattern": "^rnd_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", "description": "the render the cues must fit (duration for the last-cue rule)" },
    "language": { "type": "string", "pattern": "^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$", "description": "BCP 47; one language in the MVP" },
    "iteration": { "type": "integer", "minimum": 0 },
    "verified_script_sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" },
    "caption_style": { "type": "null", "description": "3C (burned-in variant); must be null in 3A" }
  }
}
```
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:amw:schema:agent_10.technical_qc.input:1.0.0",
  "title": "agent_10.technical_qc input payload",
  "type": "object",
  "additionalProperties": false,
  "required": ["render_id", "render_sha256", "qc_profile", "iteration", "music_bed", "destination"],
  "properties": {
    "render_id": { "type": "string", "pattern": "^rnd_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$" },
    "render_sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$", "description": "must equal the render ref hash and renders.content_sha256 (a10.q.hash_chain)" },
    "qc_profile": { "enum": ["qc.long_form", "qc.shorts"], "description": "18 §8; a tenant may only be stricter (24 §2)" },
    "iteration": { "type": "integer", "minimum": 0 },
    "music_bed": { "oneOf": [ { "type": "null" }, { "$ref": "urn:amw:schema:agent_10.render.input:1.0.0#/$defs/music_bed" } ],
        "description": "stems for qc.audio.music_bed_offset (3B); null in 3A" },
    "destination": { "enum": ["MONETIZED_YOUTUBE", "NON_MONETIZED"], "description": "GLOSSARY §6.52 `licence_destination`, derived from `jobs.monetized_destination` (CCR-028; `true` = `MONETIZED_YOUTUBE`); 3A default `MONETIZED_YOUTUBE` (18 §2.2 note b)" }
  }
}
```
Context refs of the QC task: render output, subtitles output, timeline blob, plan, manifest, audio master output, narration timeline, script. A `qc_profile` of `qc.shorts` is allowed only for a job of type `SHORTS`.

### 7.4 Validation order (03 §7) and Agent 10 specifics
After the generic order (envelope, receipts, tenant transaction, refs and hashes, schema, tenant equality, context visibility, state, idempotency): (a) `resource_budget.max_cost_micros = 0` and `max_llm_calls = 0` else `INPUT_INVALID`; (b) exactly one context ref per required schema; (c) `verified_script_sha256` equals the script ref's SHA-256 (`SCRIPT_HASH_MISMATCH`); (d) `preset_key` ↔ `aspect_ratio` consistent; (e) `language` equals the plan's and the narration timeline's language; (f) configuration complete for this preset (fps, segment target, encoder, colour tags, bitrate keys) else `CONFIG_INVALID`. Every rejection is a structured rejection (03 §7.2) with violations by JSON Pointer.

### 7.5 `music_bed` as an adapter input (3B; owner decision D6)
The music bed is **not** sourced, planned, mixed or mastered by Agent 10 (CCR-007): Agent 08 sources it through the `music` adapter (capability `music_search`; `MUSIC_BED` ledger rows), Agent 09 plans the cue and ducking, Agent 07 mixes it in `s07_master` and produces the narration and music stems. All of it is **3B**, enabled by a new production-type version after the owner's D6 decision; in 3A technical runs `music_bed` is null and `qc.audio.music_bed_offset` is `SKIPPED`. What Agent 10 consumes is an **evidence-bearing input**: the licensed track's `asset_id`, its `licence_id`, the `licence_ledger` rows (`usage_kind = MUSIC_BED`, `licence_source_type = MUSIC_LIBRARY`) and the two stems from the same timeline, so that (a) `qc.licence.completeness` treats the music as a timeline element (18 §2.2 note c), (b) `qc.audio.music_bed_offset` measures `L_music − L_narration` over narration-active spans within −20…−15 dB (18 §5, §7.4), and (c) the render muxes Agent 07's master (which already contains the mix) unchanged. A render without a music bed is allowed technically (ADR-009), but it is never judged for scoring (D6). The owner's choice of a licensed source is **D6 in IMPLEMENTATION_PROGRESS.md** (candidates with recorded facts: PR-06 / PR-07; **no purchase without the owner**, rule 8); 3B golden samples are blocked until he decides (3B-BLOCKING, not 3A-BLOCKING).

---

## 8 Output schema
**MVP: 3A · Tier 0. Task Output is the 03 §5 envelope. All three tasks return `quality_score = null` (Agent 16 scores), `confidence = null`, `next_action` advisory, `resource_usage.llm_calls = 0`, `tokens_* = 0`, `provider_calls = 0`, `render_ms` set. Payload names `agent_10.render.output`, `agent_10.subtitles.output`, `agent_10.technical_qc.output` 1.0.0 (registered by being defined here, CCR-018). Common `$defs` used by the three schemas: `blob_ref {uri, sha256}`, `blob_ref_sized {uri, sha256, size_bytes}`, `rnd_id`, `ast_id` (UUIDv7 patterns as in §7.2).**

### 8.1 `agent_10.render.output`
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:amw:schema:agent_10.render.output:1.0.0",
  "type": "object", "additionalProperties": false,
  "required": ["render_id", "render_ref", "timeline_ref", "fps", "frame_count", "duration_ms", "segments", "encoder", "probe", "render_ms", "guards", "provenance"],
  "properties": {
    "render_id": { "type": "string", "pattern": "^rnd_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", "description": "pre-allocated before the first segment and stored in the first checkpoint" },
    "render_ref": { "$ref": "#/$defs/blob_ref_sized" },
    "timeline_ref": { "$ref": "#/$defs/blob_ref" },
    "fps": { "type": "object", "additionalProperties": false, "required": ["num", "den"],
      "properties": { "num": { "type": "integer", "minimum": 1 }, "den": { "type": "integer", "minimum": 1 } } },
    "frame_count": { "type": "integer", "minimum": 1 },
    "duration_ms": { "type": "integer", "minimum": 1 },
    "segments": { "type": "object", "additionalProperties": false, "required": ["planned", "encoded", "reused", "resumed_from_checkpoint"],
      "properties": { "planned": { "type": "integer", "minimum": 1 }, "encoded": { "type": "integer", "minimum": 0 },
                      "reused": { "type": "integer", "minimum": 0 }, "resumed_from_checkpoint": { "type": "boolean" } } },
    "encoder": { "type": "object", "additionalProperties": false,
      "required": ["ffmpeg_build_id", "video_encoder", "args_sha256", "preset_key", "gop", "colour", "audio_bitrate_nominal_bps"],
      "properties": {
        "ffmpeg_build_id": { "type": "string", "maxLength": 128 },
        "video_encoder": { "type": "string", "maxLength": 64 },
        "args_sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" },
        "preset_key": { "enum": ["yt_master_1080p", "yt_master_1440p", "shorts_9x16"] },
        "gop": { "type": "object", "additionalProperties": false, "required": ["gop_frames", "closed_gop", "idr_at_segment_start"],
          "properties": { "gop_frames": { "type": "integer", "minimum": 1 }, "closed_gop": { "type": "boolean" }, "idr_at_segment_start": { "type": "boolean" } },
          "description": "encoder GOP settings as recorded (18 §6: ffprobe does not prove a closed GOP)" },
        "colour": { "type": "object", "additionalProperties": false, "required": ["primaries", "transfer", "matrix", "range"],
          "properties": { "primaries": { "type": "string" }, "transfer": { "type": "string" }, "matrix": { "type": "string" }, "range": { "type": "string" } } },
        "audio_bitrate_nominal_bps": { "type": "integer", "minimum": 1, "description": "the configured nominal rate from the encoder arguments; stored as renders.audio_bitrate_bps and gated by qc.audio.bitrate (18 §7.1, CCR-055)" }
      } },
    "probe": { "type": "object", "additionalProperties": false,
      "required": ["width_px", "height_px", "video_codec", "audio_codec", "video_bitrate_bps", "audio_bitrate_avg_bps", "audio_sample_rate_hz", "channels"],
      "properties": {
        "width_px": { "type": "integer" }, "height_px": { "type": "integer" },
        "video_codec": { "type": "string" }, "audio_codec": { "type": "string" },
        "video_bitrate_bps": { "type": "integer" },
        "audio_bitrate_avg_bps": { "type": "integer", "description": "measured stream average (reported, not the gate, 18 §7.1)" },
        "audio_sample_rate_hz": { "type": "integer" },
        "channels": { "type": "integer", "description": "payload only: the renders table has no channels column (04 §5.18)" }
      } },
    "render_ms": { "type": "integer", "minimum": 0 },
    "guards": { "type": "object", "additionalProperties": false, "required": ["market_hours_checks", "night_window_checks", "drained"],
      "properties": { "market_hours_checks": { "type": "integer", "minimum": 0 }, "night_window_checks": { "type": "integer", "minimum": 0 }, "drained": { "type": "boolean" } } },
    "provenance": { "type": "object", "additionalProperties": false, "required": ["config_keys_family", "ffmpeg_version_string_sha256"],
      "properties": { "config_keys_family": { "const": "agent_10.*" }, "ffmpeg_version_string_sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" } },
      "description": "not part of any determinism hash" }
  },
  "$defs": {
    "blob_ref": { "type": "object", "additionalProperties": false, "required": ["uri", "sha256"],
      "properties": { "uri": { "type": "string", "maxLength": 1024 }, "sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" } } },
    "blob_ref_sized": { "type": "object", "additionalProperties": false, "required": ["uri", "sha256", "size_bytes"],
      "properties": { "uri": { "type": "string", "maxLength": 1024 }, "sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" }, "size_bytes": { "type": "integer", "minimum": 1 } } }
  }
}
```
`render_ref` is the final MP4 (`kind = VIDEO`, `media_type = video/mp4`), area `jobs/<job>/renders/rnd_<id>.mp4` (03 §8, GLOSSARY §5); `timeline_ref` the `$T` blob (`kind = DATA`) whose `sha256` = `renders.timeline_sha256`. `output_refs`: final MP4, `$T` blob, one `DATA` ref listing the per-segment keys and hashes (segment blobs are internal and content-addressed, not listed individually), render report (`REPORT`). `validation_results`: the `a10.q.*` checks of §20 with `gate: false`. Status mapping: all process checks pass → `SUCCEEDED`; a guard that closed or the self-drain timer → `SUSPENDED` with `next_action = WAIT / DRAIN`; any process-integrity failure → `FAILED` with the §18 code.

### 8.2 `agent_10.subtitles.output`
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:amw:schema:agent_10.subtitles.output:1.0.0",
  "type": "object", "additionalProperties": false,
  "required": ["srt", "warnings", "timeline_source", "sync_basis"],
  "properties": {
    "srt": { "type": "array", "minItems": 1, "items": { "type": "object", "additionalProperties": false,
      "required": ["language", "uri", "sha256", "size_bytes", "cue_count", "asset_id", "last_cue_end_ms"],
      "properties": {
        "language": { "type": "string", "pattern": "^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$" },
        "uri": { "type": "string", "maxLength": 1024 },
        "sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" },
        "size_bytes": { "type": "integer", "minimum": 1 },
        "cue_count": { "type": "integer", "minimum": 1 },
        "asset_id": { "type": "string", "pattern": "^ast_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$" },
        "last_cue_end_ms": { "type": "integer", "minimum": 1 } } },
      "description": "one entry per language (one in the MVP); kind = SUBTITLE, media_type = application/x-subrip" },
    "warnings": { "type": "array", "items": { "type": "string", "pattern": "^(OVERLONG_TOKEN|CUE_SHORTER_THAN_MIN):[A-Za-z0-9_.-]{1,32}$" } },
    "timeline_source": { "enum": ["PROVIDER_CLIPS", "OWNER_MARKS"], "description": "UNALIGNED is refused as INPUT_INVALID (§18); it cannot arrive in 3A (CCR-051)" },
    "sync_basis": { "const": "NARRATION_TIMELINE", "description": "cue timing is taken from the aligned narration timeline of Agent 07" }
  }
}
```
`validation_results` (`gate: false`): `a10.sub.format`, `a10.sub.coverage`, `a10.sub.text_from_script` (§20). `SUCCEEDED` only if all blocking ones pass. Timing is always taken from the aligned narration timeline: in 3A every narration (including a human recording) reaches `s07_voice` aligned or is refused there (CCR-051; 18 §7.6.2), so no HUMAN sync check exists in 3A; the HUMAN 5-point check of 18 §7.6 applies only to a later alignment-tool path (3C) and is then recorded by the owner's channel, never by Agent 10.

### 8.3 `agent_10.technical_qc.output`
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:amw:schema:agent_10.technical_qc.output:1.0.0",
  "type": "object", "additionalProperties": false,
  "required": ["gate_verdict", "failures", "render_id", "render_sha256", "profile", "iteration", "counts", "measurements", "tier_mix", "evidence", "selftest"],
  "properties": {
    "gate_verdict": { "enum": ["PASSED", "FAILED"], "description": "GLOSSARY §6.52 echo; the orchestrator decides from validation_results (03 §5.3 rule 4)" },
    "failures": { "type": "array", "items": { "type": "object", "additionalProperties": false,
      "required": ["check_id", "shot_ids", "measured", "threshold", "unit", "remedy_stage", "message"],
      "properties": {
        "check_id": { "type": "string", "pattern": "^[a-z0-9_.-]{3,96}$" },
        "shot_ids": { "type": "array", "items": { "type": "string", "pattern": "^sh[0-9]{2,4}$" } },
        "measured": { "type": ["number", "string", "null"] },
        "threshold": { "type": ["number", "string", "null"] },
        "unit": { "type": "string", "maxLength": 16 },
        "remedy_stage": { "enum": ["s07_voice", "s08_assets", "s09_plan", "s10_render"], "description": "echo of the result's remedy_stage_id" },
        "message": { "type": "string", "maxLength": 240, "description": "no script text" } } },
      "description": "empty when PASSED; shot IDs from the interval maps" },
    "render_id": { "type": "string", "pattern": "^rnd_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$" },
    "render_sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" },
    "profile": { "enum": ["qc.long_form", "qc.shorts"] },
    "iteration": { "type": "integer", "minimum": 0 },
    "counts": { "type": "object", "additionalProperties": false, "required": ["pass", "fail", "warn", "skipped"],
      "properties": { "pass": { "type": "integer", "minimum": 0 }, "fail": { "type": "integer", "minimum": 0 }, "warn": { "type": "integer", "minimum": 0 }, "skipped": { "type": "integer", "minimum": 0 } } },
    "measurements": { "type": "object", "additionalProperties": false,
      "required": ["integrated_lufs", "true_peak_dbtp", "lra_lu", "video_bitrate_bps", "audio_bitrate_nominal_bps", "audio_bitrate_avg_bps", "duration_ms", "expected_ms", "black_runs", "freeze_runs", "silence_runs", "scene_events"],
      "properties": {
        "integrated_lufs": { "type": "number" }, "true_peak_dbtp": { "type": "number" }, "lra_lu": { "type": "number" },
        "video_bitrate_bps": { "type": "integer" }, "audio_bitrate_nominal_bps": { "type": "integer" }, "audio_bitrate_avg_bps": { "type": "integer" },
        "duration_ms": { "type": "integer" }, "expected_ms": { "type": "integer" },
        "black_runs": { "type": "integer", "minimum": 0 }, "freeze_runs": { "type": "integer", "minimum": 0 },
        "silence_runs": { "type": "integer", "minimum": 0 }, "scene_events": { "type": "integer", "minimum": 0 } },
      "description": "numbers; also persisted to renders (integrated_lufs, true_peak_dbtp)" },
    "tier_mix": { "type": "object", "additionalProperties": false,
      "required": ["A_OWNER_REAL", "B_LICENSED_STOCK", "C_CODE_MOTION", "D_AI_VIDEO", "E_AI_STILL", "ai_video_ms"],
      "properties": {
        "A_OWNER_REAL": { "type": "integer", "minimum": 0, "maximum": 1000 }, "B_LICENSED_STOCK": { "type": "integer", "minimum": 0, "maximum": 1000 },
        "C_CODE_MOTION": { "type": "integer", "minimum": 0, "maximum": 1000 }, "D_AI_VIDEO": { "type": "integer", "minimum": 0, "maximum": 1000 },
        "E_AI_STILL": { "type": "integer", "minimum": 0, "maximum": 1000 }, "ai_video_ms": { "type": "integer", "minimum": 0 } },
      "description": "permille of visual frames (floor), qc.visual.tier_mix_report" },
    "evidence": { "type": "object", "additionalProperties": false, "required": ["manifest_ref", "contact_sheet_ref", "sample_frames_ref", "loudness_series_ref", "report_ref"],
      "properties": {
        "manifest_ref": { "$ref": "#/$defs/blob_ref", "description": "the single evidence manifest document `agent_10.evidence_manifest` (§8.3a); this is what Agent 16 receives as `frames_ref`" },
        "contact_sheet_ref": { "$ref": "#/$defs/blob_ref" },
        "sample_frames_ref": { "type": "array", "items": { "$ref": "#/$defs/blob_ref" } },
        "loudness_series_ref": { "$ref": "#/$defs/blob_ref" },
        "report_ref": { "$ref": "#/$defs/blob_ref" } },
      "description": "blobs under jobs/<job>/tasks/<task>/attempts/<att>/artifacts/ (03 §8); `sample_frames_ref[]` lists the same frame blobs as `manifest_ref` `frames[]` (same order); Agent 16 reads the frames through `manifest_ref`" },
    "selftest": { "type": "object", "additionalProperties": false, "required": ["ffmpeg_build_id", "selftest_ref", "passed"],
      "properties": { "ffmpeg_build_id": { "type": "string", "maxLength": 128 }, "selftest_ref": { "$ref": "#/$defs/blob_ref" }, "passed": { "type": "boolean" } } }
  },
  "$defs": {
    "blob_ref": { "type": "object", "additionalProperties": false, "required": ["uri", "sha256"],
      "properties": { "uri": { "type": "string", "maxLength": 1024 }, "sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" } } }
  }
}
```
Task status: a failed gate is **not** a failed task (03 §5.3 rule 4, CCR-001): `SUCCEEDED` with `gate: true` results, `next_action = {type: CONTINUE, reason: "gate FAILED: …"}` and the echo `gate_verdict = FAILED`. Process-integrity checks (`a10.q.*`: schema, tenant, tool completeness, hashes) keep `gate: false` and must pass for `SUCCEEDED`. A `gate: true` result is accepted because `s10_qc` is a registered blocking gate (24 §7.1a). `renders.status` becomes `QC_PASSED` or `QC_FAILED`.

### 8.3a Document `agent_10.evidence_manifest` 1.0.0
One JSON blob per `agent_10.technical_qc` task, written last (after every frame blob, so that its hashes exist), listed in `output_refs` (`kind = DATA`) and in `evidence.manifest_ref`. It is the document Agent 16 reads as `frames_ref` (agent_16 §7.3, §7.4: "sampled frames with time positions, contact sheet"). It carries IDs, hashes, numbers and enums only (no text). Frames are sampled by `agent_10.qc.sample_frames_per_min` at fixed positions on the frame grid (`frame_index` = `floor(k × total_frames / n)`; `t_ms` is the frame's time converted by §6.1, round half up), plus the first and last frame of every shot that Agent 10's deterministic watermark check compares.
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:amw:schema:agent_10.evidence_manifest:1.0.0",
  "type": "object",
  "additionalProperties": false,
  "required": ["render_id", "render_sha256", "timeline_sha256", "fps_num", "fps_den", "total_frames", "frames", "contact_sheet", "overlays"],
  "properties": {
    "render_id": { "type": "string", "pattern": "^rnd_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$" },
    "render_sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" },
    "timeline_sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" },
    "fps_num": { "type": "integer", "minimum": 1 },
    "fps_den": { "type": "integer", "minimum": 1 },
    "total_frames": { "type": "integer", "minimum": 1 },
    "frames": { "type": "array", "minItems": 1, "maxItems": 999,
      "description": "ordered by `frame_index`; `frame_id` is the ID Agent 16's frames judge cites (`frame_ids` pattern `^f[0-9]{2,3}$`)",
      "items": { "type": "object", "additionalProperties": false, "required": ["frame_id", "frame_index", "t_ms", "shot_id", "uri", "sha256"],
        "properties": {
          "frame_id": { "type": "string", "pattern": "^f[0-9]{2,3}$" },
          "frame_index": { "type": "integer", "minimum": 0 },
          "t_ms": { "type": "integer", "minimum": 0, "description": "time position of the frame on the render timeline" },
          "shot_id": { "oneOf": [ { "type": "null" }, { "type": "string", "pattern": "^sh[0-9]{2,4}$" } ], "description": "the shot of `$T` that contains the frame; null inside a deliberate hold or the end-screen segment" },
          "uri": { "type": "string", "maxLength": 1024 },
          "sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" } } } },
    "contact_sheet": { "$ref": "#/$defs/blob_ref" },
    "overlays": { "type": "array", "description": "the timeline's overlay list (from `$T`) that the watermark judge compares against",
      "items": { "type": "object", "additionalProperties": false, "required": ["overlay_id", "kind", "start_ms", "end_ms"],
        "properties": { "overlay_id": { "type": "string", "pattern": "^ov[0-9]{2,4}$" }, "kind": { "type": "string", "maxLength": 32 },
          "start_ms": { "type": "integer", "minimum": 0 }, "end_ms": { "type": "integer", "minimum": 1 } } } }
  },
  "$defs": { "blob_ref": { "type": "object", "additionalProperties": false, "required": ["uri", "sha256"],
    "properties": { "uri": { "type": "string", "maxLength": 1024 }, "sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" } } } }
}
```
Rules: `frame_id` values are `f01`, `f02`, … in `frame_index` order (a render needing more than 999 samples is a `CONFIG_INVALID` of `agent_10.qc.sample_frames_per_min`); every `frames[].sha256` equals the stored blob's hash (Agent 16 rejects a mismatch as `AGENT.CORRUPTED_OUTPUT`); `contact_sheet` equals `evidence.contact_sheet_ref`; `evidence.sample_frames_ref[i]` equals `frames[i]` (`uri`, `sha256`). Contract test C-02 pins the field names against agent_16 §7.3/§7.4 (`frames_ref`, `frame_ids`).

### 8.4 Result mapping
| Situation | Task result |
|---|---|
| render complete and verified | `SUCCEEDED`, `renders.status = COMPLETE` |
| guard closed, `DRAIN` or self-drain timer | `SUSPENDED`, `CHECKPOINTED / DRAIN` (T09) |
| upstream gate failed | `FAILED` / `REJECTED` per 03 §7, code from §18 |
| FFmpeg crash, OOM, disk full | `FAILED` with the §18 code, retried or suspended per 07 §2 |
| QC gate fails | `SUCCEEDED`, `gate: true` FAIL results, `gate_verdict = FAILED`, `failures[]` |

---

## 9 Python package and class architecture
**MVP: 3A (3B: calibration flags, `MusicBedPort` active after D6; 3C: caption variants) · Tier 0. Names follow 27 §7.2. No code exists in this phase; this is the structure the build ticket 3A-10 implements. The package imports `amw_core` and two Protocols only; `workers/render_worker` wires the concrete runner and probe.**

```text
agent_10_video_editor/                (code package; imports amw_core + FfmpegRunner/AdmissionProbe Protocols only)
├── __init__.py            RenderStage, SubtitleStage, QcStage   (typed Protocol implementations of the three task types)
├── contracts.py           Pydantic models = §7/§8 schemas; payload-local enums (guard_reason; `gate_verdict` per GLOSSARY §6.52; `remedy_stage_id` is a contract field)
├── config.py              AgentTenConfig (typed view of agent_10.* and qc.* keys; PERMANENT.CONFIG_INVALID when a required key is unset)
├── errors.py              typed exceptions mapped 1:1 to 07 §2 codes (§18)
├── scope.py               TenantScope, ScratchDir
├── gates.py               UpstreamGate, HeavyWorkGuard, SelfDrainTimer
├── timeline.py            FrameQuantiser, TimelineCompiler, RevealStepBuilder, TimelineHasher, TextBinder, FontCoverage
├── segments.py            SegmentPlanner, SegmentKey, ResumeVerifier, CheckpointWriter
├── ffmpeg.py              ArgvBuilder, FfmpegRunner (Protocol), ProcessFfmpegRunner (concrete, injected by the worker)
├── encode.py              SegmentEncoder, Muxer
├── probe.py               ProbeParser, Ebur128Parser, BlackdetectParser, SilencedetectParser, FreezedetectParser, SceneParser, CfrAnalyser, AtomOrderChecker, RenderProbe
├── registrar.py           RenderRegistrar, CostRecorder
├── subtitles.py           CueBuilder, SrtWriter, SrtParser, SrtValidator
├── qc/
│   ├── plan.py            QcPlan (profile → ordered check list, cheap first)
│   ├── checks_metadata.py checks_audio.py checks_video.py checks_timeline.py checks_licence.py checks_sync.py   (pure evaluators + runners)
│   ├── gate.py            GateAggregator, RemedyMapper
│   ├── evidence.py        EvidenceWriter (contact sheet, sample frames, loudness series)
│   ├── persist.py         QcPersister
│   └── selftest.py        QcSelfTest (lavfi fixtures)
├── music.py               MusicBedPort (validation of the §7.5 adapter input; 3B active)
├── readiness.py           ReadinessProbe
└── observability.py       metric and log event names (§22)
```
```mermaid
classDiagram
  class RenderStage { +run(task_input) TaskOutput }
  class SubtitleStage { +run(task_input) TaskOutput }
  class QcStage { +run(task_input) TaskOutput }
  class TenantScope
  class UpstreamGate
  class HeavyWorkGuard
  class SelfDrainTimer
  class TimelineCompiler
  class SegmentPlanner
  class SegmentEncoder
  class Muxer
  class RenderRegistrar
  class CueBuilder
  class SrtValidator
  class QcPlan
  class GateAggregator
  class FfmpegRunner { <<Protocol>> +run(argv, limits) ProcessResult }
  class AdmissionProbe { <<Protocol>> +now_local() +drain_flag() }
  RenderStage --> TenantScope
  RenderStage --> UpstreamGate
  RenderStage --> HeavyWorkGuard
  RenderStage --> TimelineCompiler
  RenderStage --> SegmentPlanner
  RenderStage --> SegmentEncoder
  RenderStage --> Muxer
  RenderStage --> RenderRegistrar
  SegmentEncoder --> FfmpegRunner
  Muxer --> FfmpegRunner
  HeavyWorkGuard --> AdmissionProbe
  SelfDrainTimer --> HeavyWorkGuard
  RenderStage --> SelfDrainTimer
  SubtitleStage --> HeavyWorkGuard
  QcStage --> HeavyWorkGuard
  SubtitleStage --> CueBuilder
  SubtitleStage --> SrtValidator
  QcStage --> QcPlan
  QcStage --> FfmpegRunner
  QcStage --> GateAggregator
```
Rules: no module reads environment variables or the clock directly (`amw_core.config`, `AdmissionProbe`); pure functions (quantiser, planner, cue builder, parsers, evaluators, aggregator, guard) have no I/O so the golden dataset can drive them; the only process spawn is `ProcessFfmpegRunner` (argument list, never a shell, §19).

---

## 10 Function-level specification
**MVP: 3A unless marked · Tier 0. Signatures are typed; "exceptions" are the typed errors of `errors.py` with their 07 §2 code. Every function logs through `amw_core.observability` with `org_id`, `correlation_id`, `job_id`, `task_id`, `attempt_id`, `actor = agent_10` and **never** script text, subtitle text, asset titles, paths of other tenants or keys. "Tests" lists the unit IDs of §21; the golden cases (DC-nn) drive the table-driven ones.**

| ID | Function | Signature (types) | Side effects | Exceptions (code) | Validation / rule | Tests |
|---|---|---|---|---|---|---|
| F-01 | `TenantScope.assert_consistent` | `(envelope_org, input_org, refs: list[Uri], payload_refs) -> None` | none | `TenantMismatch` (`PERMANENT.TENANT_MISMATCH`), `CrossTenantRef` (`PERMANENT.CROSS_TENANT_REF`, security event) | org of envelope, Task Input, every `context_refs[]` and payload ref equal; `platform` allowed read-only | U-01…U-04 |
| F-02 | `TenantScope.read_blob` | `(uri: Uri, sha256: str) -> bytes \| Path` | read via `amw_core.storage` into scratch | `CrossTenantRef`, `MissingDependency`, `CorruptedOutput` (`AGENT.CORRUPTED_OUTPUT`) | URI org = `app.org_id`; SHA-256 and size verified on every read; `..` and absolute segments rejected | U-05 |
| F-03 | `UpstreamGate.check_render` | `(plan, manifest, audio_master, timeline, script_ref, verified_sha, aspect_ratio) -> None` | none | `InputInvalid` (`PERMANENT.INPUT_INVALID`: `PLAN_NOT_MEASURED`, `SCRIPT_HASH_MISMATCH`, `AUDIO_COVERAGE`, `REVEAL_COUNT`, `TEMPLATE_MISMATCH`), `MissingDependency` (`NO_ASSET:<shot>`, `AUDIO_MASTER_NOT_PASSED`) | plan `timing_basis = MEASURED` (the only value accepted; no `final` flag exists and no estimated mode, CCR-051); every plan shot has a manifest entry **of the requested `aspect_ratio`** with `status ∈ {SOURCED, REUSED}` and an `asset_uri`; `unresolved_shot_ids` empty; audio master `gate_verdict = PASSED`, 48 kHz stereo, duration ≥ narration end; manifest and plan `shot_id`/`start_ms`/`end_ms` equal; reveal stills present for every chart shot (F-48) | U-06…U-10 (DC-112, DC-113, DC-119) |
| F-04 | `HeavyWorkGuard.may_start_segment` | `(now_local, est_segment_ms: int, placement: Placement, drain_flag: bool, windows, night) -> GuardResult(allowed, reason)` | none (pure) | `ConfigInvalid` (VPS without ETA calibration) | order and rounding of §6.4; the same function guards a QC group or evidence pass; cases DC-86…DC-94, DC-105, DC-106 | U-11…U-16 |
| F-05 | `FrameQuantiser.to_frame` | `(t_ms: int, fps_num: int, fps_den: int) -> int` | none | `InputInvalid` (negative, non-positive fps) | §6.2 formula | U-17, U-18 (DC-01…DC-05) |
| F-06 | `FrameQuantiser.frames_to_ms` | `(frames: int, fps_num: int, fps_den: int) -> int` | none | `InputInvalid` | `round_half_up(frames×1000×fps_den/fps_num)` | U-19 (DC-06) |
| F-07 | `TimelineCompiler.compile` | `(plan, manifest, audio, cfg, aspect_ratio) -> Timeline` | none (pure) | `InputInvalid` (`ZERO_FRAME_SHOT`, `TILING_GAP`, `TILING_OVERLAP`, `TEMPLATE_MISMATCH`), `MissingDependency` (`NO_ASSET`) | quantises boundaries (not durations); selects manifest entries by (`shot_id`, `aspect_ratio`) (§6.2 item 7); binds asset ID, SHA-256, URI, `source_in_ms`, crop, reveal steps (F-48), overlay `template_asset_id`; keeps plan ms and `change_events_ms`; overlays quantised; total frames = `frame(total_duration_ms)`; colour tags from config | U-20…U-24 (DC-07…DC-11) |
| F-08 | `TimelineHasher.canonical_json` / `.sha256` | `(timeline) -> bytes` / `-> str` | none | `InputInvalid` (float in the structure) | sorted keys, no whitespace, integers and strings only (03 §9.1 form) | U-25, U-26 (DC-12, DC-13) |
| F-09 | `TextBinder.bind` | `(overlays, script_strings) -> list[BoundText]` | none | `InputInvalid` (`TEXT_HASH_MISMATCH`, `TEXT_REF_MISSING`) | every `text_refs` entry resolves to a script string whose SHA-256 equals the plan's; no free text accepted | U-27…U-30 |
| F-10 | `FontCoverage.check` | `(font_asset, code_points: set[int]) -> None` | reads the font file | `InputInvalid` (`GLYPH_MISSING:<U+XXXX>`) | every code point of every bound text is in the brand font's cmap (Devanagari included); shaping availability is checked at readiness (§24.3) | U-31…U-33 |
| F-11 | `SegmentPlanner.plan` | `(shots: list[ShotFrames], target_frames: int) -> list[Segment]` | none | `ConfigInvalid` (`SEGMENT_TARGET_NOT_POSITIVE`) | §6.3.1 | U-34…U-38 (DC-14…DC-18) |
| F-12 | `SegmentKey.compute` | `(slice_sha, asset_shas, args_sha, build_id) -> str` | none | — | §6.3.2 | U-39, U-40 (DC-19, DC-20) |
| F-13 | `ResumeVerifier.verify` | `(segments, checkpoint, storage, probe) -> ResumePlan` | reads blobs, may call ffprobe, may write a checkpoint entry | `CorruptedOutput` is **not** raised: a bad blob is simply re-encoded | §6.3.3 | U-41…U-45 |
| F-14 | `CheckpointWriter.write` | `(task, attempt, step_key, state, completed_effects, progress) -> CheckpointId` | insert `checkpoints` row, `is_latest` flip, state blob write-once | `StorageUnavailable` (`INFRASTRUCTURE.STORAGE_UNAVAILABLE`), `DbTransient` | state holds IDs, keys, hashes, URIs only (§16) | U-46, U-47 |
| F-15 | `ArgvBuilder.segment_argv` | `(segment, timeline, cfg, paths) -> list[str]` | none | `InputInvalid` | argument list from fixed templates; inputs via staged scratch file names `in_<n>.<ext>`; `-protocol_whitelist file`; `-fps_mode cfr`; forced IDR at start, closed GOP (flags recorded in the output `encoder.gop`); colour tag flags from `agent_10.render.color_*` (§6.2 item 9); reveal stills as image inputs switched at the step frames; text via `textfile=` never inline; no value from payload text | U-48…U-52 |
| F-16 | `ArgvBuilder.mux_argv` | `(concat_list, master_wav, codec_profile, duration_ms, cfg) -> list[str]` | none | `InputInvalid` | video `-c copy`; audio encoded with the typed `codec_profile` of Agent 07 (`codec`, `profile`, `sample_rate_hz`, `channels`, `bitrate_bps`, `encoder`, `rate_mode`); the nominal `bitrate_bps` is recorded as `renders.audio_bitrate_bps`; pad audio to video length; `-movflags +faststart`; duration cap `-t` | U-53…U-56 |
| F-17 | `ProcessFfmpegRunner.run` | `(argv: list[str], limits: RunLimits) -> ProcessResult(exit, stderr_ref, wall_ms, killed_by)` | spawns one process (no shell), streams stderr to a scratch file, enforces timeout and rlimits | `RenderCrash` (`RESOURCE.RENDER_CRASH`), `Oom` (`RESOURCE.OOM`), `DiskFull` (`RESOURCE.DISK_FULL`), `Hang` (`AGENT.HANG`) | exit-code and signal mapping (§18); stderr stored as evidence, never logged | U-57…U-60 |
| F-18 | `ProbeParser.parse` | `(json_text) -> ProbeResult` | none | `MeasurementUnavailable` | required keys present; `r_frame_rate` and `avg_frame_rate` parsed as rationals; missing `bit_rate` falls back to `size×8/duration` | U-61 |
| F-19 | `Ebur128Parser.parse` | `(stderr) -> {integrated_lufs, lra_lu, true_peak_dbtp}` | none | `MeasurementUnavailable` | Summary block only (DC-33…DC-35) | U-62…U-64 |
| F-20 | `BlackdetectParser.parse` | `(stderr) -> list[Interval]` | none | `MeasurementUnavailable` (unparseable line) | decimal seconds to integer ms (DC-36) | U-65 |
| F-21 | `SilencedetectParser.parse` | `(stderr, stream_end_ms) -> list[Interval]` | none | `MeasurementUnavailable` | an unclosed run ends at the stream end (DC-37) | U-66 |
| F-22 | `FreezedetectParser.parse` | `(stderr, stream_end_ms) -> list[Interval]` | none | `MeasurementUnavailable` | start/duration/end triple; open freeze runs to the end (DC-38, DC-39) | U-67, U-68 |
| F-23 | `SceneParser.parse` | `(stderr) -> list[int]` | none | `MeasurementUnavailable` | `pts_time:` of each `showinfo` line to ms | U-69 |
| F-24 | `CfrAnalyser.evaluate` / `AtomOrderChecker.check` | `(interval_histogram, fps, tol) -> CheckResult` / `(file) -> CheckResult` | reads the head of the file | `MeasurementUnavailable` | CFR: every interval within `tol` of `1/fps` (DC-81, DC-82); faststart: `moov` precedes `mdat` in the box list (method **REQUIRES REVIEW (Phase 1): 18 §7.1**; the mux argument is the guarantee, this is the check) | U-70 |
| F-25 | `SegmentEncoder.encode` | `(segment, timeline, argv_builder, runner, storage) -> SegmentResult` | writes `.part` in scratch, ffprobes it, `amw_core.storage` atomic put at the content-addressed path | `RenderCrash`, `Oom`, `DiskFull`, `Hang`, `InputInvalid` (an input asset fails ffprobe: `ASSET_UNREADABLE:<asset_id>`) | frame count of the segment equals the plan, CFR, first frame is IDR; otherwise the `.part` is discarded | U-71…U-74 |
| F-26 | `Muxer.mux` | `(segment_blobs, master, codec_profile, ...) -> MuxResult` | scratch concat list, final `.part`, atomic put to `rnd_<id>.mp4` | as F-25 | final duration within one frame of the timeline; audio stream parameters equal the codec profile; atomic | U-75…U-78 |
| F-27 | `RenderProbe.verify` | `(final_blob, timeline, cfg) -> ProbeResult` | ffprobe | `RenderCrash`, `MeasurementUnavailable` | stream facts for the `renders` columns; colour tags equal config (`a10.q.colour_tags`); recorded GOP flags equal config (`a10.q.gop_settings`) | U-79, U-80 |
| F-28 | `RenderRegistrar.register` | `(tenant_tx, probe, refs, timeline_sha, job, script_id, worker_id) -> RenderId` | insert `renders` (`COMPLETE`), mark earlier renders of the same job/kind/preset `SUPERSEDED`, audit `render.completed` | `IdempotencyConflict` (`PERMANENT.IDEMPOTENCY_CONFLICT`), `DbTransient` | idempotent on `render.master` (job, timeline SHA-256, preset): an existing `COMPLETE` row with the same content SHA-256 is returned (replay) | U-81…U-83 |
| F-29 | `CueBuilder.build` | `(segment, limits) -> list[Cue]` | none | `InputInvalid` (`CUE_TOO_SHORT`) | §10.1 below (DC-24…DC-28) | U-84…U-88 |
| F-30 | `SrtWriter.format_time` / `.write` | `(ms) -> str` / `(cues) -> bytes` | none | — | `HH:MM:SS,mmm`; UTF-8 without BOM; LF; numbered cues (DC-21…DC-23) | U-89…U-91 |
| F-31 | `SrtParser.parse` | `(bytes) -> list[Cue]` | none | `InputInvalid` | strict parse used by the validator and the round-trip test | U-96 |
| F-32 | `SrtValidator.validate` | `(cues, video_duration_ms) -> list[str]` | none | — | reports **all** errors in cue order: numbering, empty text, non-positive duration, overlap, last cue after video end (DC-29…DC-32) | U-92…U-95 |
| F-33 | `SubtitleStage.run` | `(task_input) -> TaskOutput` | blob + `assets` row (`SUBTITLE`, `CODE_GENERATED`, `is_realistic_synthetic = false`, `depicts_real_person = false`, `attributes.language`; an existing row with the same `content_sha256` is reused, `UNIQUE (org_id, content_sha256)`), cost row, audit | `InputInvalid` (`TIMELINE_UNALIGNED`: a timeline with `source = UNALIGNED` is a contract violation, it cannot arrive in 3A, CCR-051), `MissingDependency` | one cue list per narration segment; text from the script by `segment_id`; timing from the aligned narration timeline | U-84…U-96, U-238 (DC-114), IT-02 |
| F-34 | `QcPlan.build` | `(profile, cfg, manifest_flags) -> list[CheckSpec]` | none | `ConfigInvalid` (profile unknown) | cheap checks first: ffprobe, parsers on existing files, DB checks, audio passes, then video decode passes; `SKIPPED` only for the listed cases (§20.1) | U-97 |
| F-35 | `QcStage.run` | `(task_input) -> TaskOutput` | runs the plan, writes `qc_results`, `renders.status`, evidence blobs, cost row, audit | `RenderCrash`, `Crash` (`AGENT.CRASH`) on unavailable measurements | §4.2 flow; never `PASS` for a missing measurement | IT-03, FI-06 |
| F-36 | check evaluators | `evaluate_<check>(measured, cfg, context) -> CheckResult(verdict, blocking, gate, measured, threshold, unit, offending, remedy_stage_id)` | none (pure) | `MeasurementUnavailable` | one function per check of §20.1; cases DC-40…DC-85, DC-95…DC-104, DC-115…DC-118, DC-120 | U-110…U-225 |
| F-37 | `GateAggregator.decide` | `(results, profile_check_ids) -> GateResult` | none | — | §6.5.3 (DC-83…DC-85) | U-98…U-100 |
| F-38 | `RemedyMapper.map` | `(check_id) -> RemedyStage` | none | `ConfigInvalid` (unmapped ID) | table of §6.5.4; every `check_id` of §20.1 mapped (test enumerates) | U-101 |
| F-39 | `EvidenceWriter.write` | `(final_blob, timeline, results) -> EvidenceRefs` | contact sheet (`tile` filter), sample frames, loudness series, report blobs under `jobs/<job>/tasks/<task>/attempts/<att>/artifacts/` (03 §8; stderr blobs likewise) | `RenderCrash` | sampling count **REQUIRES REVIEW (Phase 1)**; frames sampled at shot midpoints and hook window | U-231, IT-03 |
| F-40 | `QcPersister.persist` | `(tx, results, render_id) -> None` | insert `qc_results` rows, update `renders` (`status`, `integrated_lufs`, `true_peak_dbtp`) | `DbTransient` | one row per result; idempotent on (task, check_id) | U-232 |
| F-41 | `CostRecorder.record` | `(tx, attempt, render_ms) -> CostEntryId` | insert `cost_ledger`: `provider = ffmpeg` (the local executable, no vendor), `operation = render.ffmpeg` (closed list, GLOSSARY §6.52), `unit_kind = render_ms`, `units` = measured wall ms, `amount_micros = 0`, `currency` = the currency of the job's budget, `figure_kind = ESTIMATE` (the only non-`VERIFIED` kind; `MEASURED` was rejected, CCR-038) with the label `MEASURED` (`figure_label`, GLOSSARY §6.46) carried in the cost report | `DbTransient` | no provider spend; units = measured wall time | U-102 |
| F-42 | `ErrorMapper.map` | `(exception) -> AmwError` | none | — | one mapping per §18 row | U-103…U-109 |
| F-43 | `QcSelfTest.run` | `(runner) -> SelfTestRecord` | lavfi fixtures in scratch; writes the record blob | `RenderCrash` | each fixture's expected verdicts asserted (18 §7.11) | R-02 |
| F-44 | `ScratchDir.open` / `.clean` | `(org, task) -> Path` | creates `<scratch_root>/<org uuid>/<task>/`; cleans on completion and at worker start | `DiskFull` | path built by core, no payload text | S-03 |
| F-45 | `MusicBedPort.validate` | `(music_bed, ledger_rows, licences, cfg) -> MusicBedEvidence` | none | `InputInvalid` (non-null while `agent_10.music_enabled` false), `PermissionDenied` | licence row of `MUSIC_LIBRARY` type, `ACTIVE`, `covers_monetized_youtube` true, stems same length and rate | U-230 (3B) |
| F-46 | `ReadinessProbe.run` | `() -> ReadinessReport` | DB probe, storage probe, ffmpeg build check, shaping fixture | — | §24.3 | IT-06 |
| F-47 | `SelfDrainTimer.act_by` / `.arm` | `(now_local, placement, windows, night) -> LocalTime` / `(task, act_by) -> None` | `arm` starts a worker timer that sets the internal drain flag at `act_by` | `ConfigInvalid` (no calendar) | §6.4: earlier of the next market-window start and (VPS) `07:00 − drain.grace`; pure part driven by DC-107, DC-108 | U-233, U-234 (FI-13) |
| F-48 | `RevealStepBuilder.build` | `(shot, change_events_ms, stills, fps) -> list[RevealStep]` | none | `InputInvalid` (`REVEAL_COUNT`, `ZERO_FRAME_REVEAL`), `MissingDependency` (`NO_ASSET:<shot>#<k>`) | §6.2 item 8 (DC-109…DC-111) | U-235…U-237 |

### 10.1 `CueBuilder.build` (algorithm; cases DC-24…DC-28)
1. Input: one narration segment `{segment_id, start_ms, end_ms}` and its script text (by reference), limits `max_chars_per_cue` (**REQUIRES REVIEW (Phase 1): readability limits are not sourced, 18 §7.6; calibrate in 3B**; unset is `CONFIG_INVALID`).
2. Tokens: whitespace-separated words. Greedy fill: add a token to the current cue if `len(current) + 1 + len(token) ≤ max_chars_per_cue` (lengths in Unicode code points; grapheme-cluster counting for Devanagari is **REQUIRES REVIEW (Phase 1)**); a token longer than the limit forms its own cue and adds warning `OVERLONG_TOKEN`.
3. Timing: weights = code points of each cue; boundary `b_i = start_ms + round_half_up(duration × cum_i / total)`; first cue starts at the segment start, last cue ends at the segment end. A cue of zero or negative length is `INPUT_INVALID (CUE_TOO_SHORT)`; the builder never merges or drops silently.
4. One SRT per language; cue text is the script string itself; no case change, no punctuation change, no translation (3C `svc_s03`).

---

## 11 AI provider use
**MVP: 3A (none) · Tier 0.**
| Provider class | Used by Agent 10 | Notes |
|---|---|---|
| LLM (`llm` capability) | **no** | no key on the render worker; `max_llm_calls = 0` (§5) |
| TTS, image, video generation, stock search | **no** | assets and narration arrive as finished, hash-verified inputs; no re-sourcing (§1.3) |
| Music adapter | **no call**; consumes the evidence of a licensed music bed through the `music_bed` input (§7.5) | sourcing (Agent 08, `music_search`), cue (Agent 09) and mix (Agent 07) are 3B (CCR-007); D6 open |
| Vision judge for frames | **no**; Agent 16 judges the evidence frames Agent 10 writes | §5.1 |
Fallback providers, model routing (ADR-007), prompt caching, token and cost estimation: not applicable. Cost of this agent is `render_ms` of local worker time only (24 §6; 09 §5): `cost_ledger` rows with `unit_kind = render_ms`, `amount_micros = 0` (no per-call vendor fee, 09), so the per-video and pilot budgets of D1 are never reduced by Agent 10 and no budget reservation is needed (`resource_budget.max_cost_micros = 0`).

---

## 12 External APIs
**MVP: 3A · Tier 0. Agent 10 calls no network API. Its external dependencies are two local executables and the platform's database and storage.**

| Dependency | Use | Auth / scopes | Quota | Error signals and mapping | Fallback | Verified |
|---|---|---|---|---|---|---|
| FFmpeg (`ffmpeg`) | segment encode, mux, detector passes, contact sheet | none (local process, no credential) | none; CPU and memory under the worker's cgroup (INF-03, INF-04) | exit code, signal, stderr patterns → §18 | none; the pinned build is part of the image; a build change re-runs the self-test (18 §7.11) | INF-09 (filters `silencedetect`, `blackdetect`, `freezedetect`, `ebur128` incl. true peak), INF-10 (delivery encoding facts) |
| ffprobe | stream and container facts, packet timestamps | none | none | `-v error`; non-zero exit or unparseable JSON → `MeasurementUnavailable` | none | INF-09 (same documentation set; ffprobe options syntax-checked locally on FFmpeg 6.1.1 per 18 §7.0.2, **not a RESEARCH_LOG entry**) |
| `amw_core.storage`, `amw_core.tenancy` | blobs, DB | `amw_app` role, RLS (INF-11) | — | `INFRASTRUCTURE.STORAGE_UNAVAILABLE`, `TEMPORARY.DB_TRANSIENT`, `INFRASTRUCTURE.DB_UNAVAILABLE` | retries per 07 §3 | INF-11 |
| Network | **forbidden**: the worker's network policy allows DB and storage only; FFmpeg runs with `-protocol_whitelist file` and no `http`, `tcp`, `rtmp` input | — | — | a connection attempt is a test failure (S-09) | — | — |

Facts the design relies on, with their log status: H.264 (closed GOP), AAC-LC 48 kHz stereo 384 kbps, 8 Mbps floor at 1080p SDR, same frame rate as recorded: INF-10; the **High** profile and the 15–25 Mbps target come from directive §1A.5 / 18 §6 / 24 §4, not from INF-10. Filter existence and true-peak mode: INF-09. **Not in RESEARCH_LOG (all `REQUIRES REVIEW (Phase 1)`, to be added before 3A-10):** the pinned FFmpeg build and version (18 §7.0.2); the encoder and its licence terms for the pinned build (a GPL-licensed encoder in the image changes redistribution duties; no redistribution happens in 3A); availability of `drawtext` text shaping (needed for Devanagari conjuncts) and `-protocol_whitelist` on the pinned build; official YouTube confirmation of MP4 `faststart`, closed-GOP verification, SDR colour tagging values (§6.2 item 9, 18 §6); AAC average bitrate on the pinned build with speech material (18 §7.1, CCR-055); `astats` for independent clipping counts. A claim above that is not marked INF-nn is a design choice, not a fact.

---

## 13 DB tables
**MVP: 3A · Tier 0. Only tables of 04 are used; no table, column, enum or index is invented. All access through `amw_core.tenancy` under role `amw_app` (04 §3).**

### 13.1 Tables used
| Table (04 §) | Access | What Agent 10 does |
|---|---|---|
| `jobs`, `projects`, `channels` (5.3, 5.1) | read | identity, production type, preset, parent job for `SHORTS` |
| `tasks`, `task_attempts`, `task_queue`, `workers` (5.3, 5.4) | via worker framework only | state transitions, lease, heartbeat, worker registration (`render_ffmpeg`, `media_probe`, `HEAVY_CPU`); Agent 10 code writes none directly |
| `checkpoints` (5.7) | insert; read latest | resume points (§16) |
| `idempotency_keys` (5.9) | via `amw_core` | scopes `task.<type>`, `render.master`, `render.segment` (03 §9.2, CCR-015) |
| `scripts` (5.11) | read | script strings by `segment_id` for subtitles and overlay text; script SHA-256 |
| `brand_kits` (5.12) | read | font asset, overlay templates, brand sting (`intro_ref`, `lower_third_template_ref`, `outro_ref`, agent_09 §15.1) |
| `assets` (5.15) | read; insert one `SUBTITLE` row per SRT | tier, source type, licence, dimensions, `expires_at`, `status`; SRT row: `kind = SUBTITLE`, `source_type = CODE_GENERATED`, `visual_source_tier` null (CHECK applies to VIDEO/IMAGE/CHART only), `is_realistic_synthetic = false`, `depicts_real_person = false` (both NOT NULL), `attributes.language` (CCR-032); a later iteration that yields byte-identical SRT bytes finds the existing row (`UNIQUE (org_id, content_sha256)`) and reuses it |
| `licences`, `licence_ledger` (5.15) | **read only** | `qc.licence.*`, `qc.watermark.provenance`; rows are written before the render exists by Agent 08 (every shot incl. reveal stills, one `TEMPLATE` row per overlay interval, one whole-timeline `FONT` row per brand font; 3B `MUSIC_BED`) and Agent 07 (`VOICE`); **Agent 10 writes none** (CCR-031); matching uses `render_id = R OR (render_id IS NULL AND job_id = J)` (CCR-030) |
| `renders` (5.18) | insert; update `status` and measured columns | one `COMPLETE` row per final file; `QC_PASSED` / `QC_FAILED` and `integrated_lufs`, `true_peak_dbtp` after QC; earlier renders of the same job/kind/preset → `SUPERSEDED` |
| `qc_results` (5.17) | insert | one row per check result, `render_id` set |
| `cost_ledger` (5.14) | insert (via core) | `render_ms` rows, `amount_micros = 0`: `provider = ffmpeg`, `operation = render.ffmpeg`, `unit_kind = render_ms`, `figure_kind = ESTIMATE` (F-41) |
| `audit_log` (5.13) | insert (via core) | §22 audit actions |
| `memory_items` (5.10) | none | §14 |
Not touched: `approvals`, `quality_scores`, `compliance_verdicts`, `publications`, `budgets` (no spend), `oauth_tokens`, every YouTube table.

### 13.2 Row-level details
- **`renders`** (04 §5.18): `kind = MASTER`, `preset_key`, `version` = previous count for (job, kind, preset) + 1, `timeline_sha256`, `width_px`, `height_px`, `fps_num`, `fps_den`, `video_codec`, `audio_codec`, `video_bitrate_bps`, `audio_bitrate_bps`, `audio_sample_rate_hz`, `duration_ms`, `size_bytes`, `storage_ref`, `content_sha256`, `status`, `worker_id`, `script_id`. `audio_bitrate_bps` is the configured nominal rate (18 §7.1, CCR-055); the measured average is reported in the output. `integrated_lufs` and `true_peak_dbtp` are null at `COMPLETE` and filled by QC (they are measured on the final file). `UNIQUE (org_id, content_sha256)`: a replay that produces the same bytes finds the existing row.
- **`qc_results`**: columns of 04 §5.17; numbers go to `measured_num` / `threshold_num`, strings to the `_text` columns, `rule_id` is set for FIN-R checks (`FIN-R9` chart age, `FIN-R11` presenter), `evidence_ref` points to the stderr or evidence blob.

### 13.3 Gaps and their decisions (CONTRACT_CHANGE_REQUESTS.md §5, blueprint 10)
1. `renders.status = RENDERING` cannot be written during the render because `duration_ms`, `size_bytes`, `storage_ref`, `content_sha256` are NOT NULL; progress lives in `checkpoints`, the row is inserted at `COMPLETE`. No request: the owner did not ask for a visible in-progress row.
2. SRT language: `assets.attributes.language` (BCP 47, required for `SUBTITLE`) — **approved** (CCR-032).
3. Ledger rows exist before `render_id`: QC matches on `render_id = R OR (render_id IS NULL AND job_id = J)` — **approved** (CCR-030).
4. Render time is a cost unit: `cost_figure_kind` `MEASURED` was **rejected** (CCR-038); the row is `ESTIMATE` with units from measured wall time and the `figure_label` `MEASURED` in the report.

---

## 14 Memory
**MVP: 3A (none) · 3B (calibration lives in configuration) · Tier 0.**
| Scope (GLOSSARY §6.30) | Use by Agent 10 |
|---|---|
| `WORKING` | process memory of one attempt: parsed tool output, timeline, interval maps; never persisted |
| `TASK` | the checkpoint state blob (§16) only; no `memory_items` row |
| `PROJECT`, `CHANNEL`, `LONG_TERM` | **not read, not written.** The render is a function of the plan, manifest, master and configuration, so a remembered preference could change the bytes without appearing in the timeline hash. Learned thresholds and tolerances from the 3B pilot are configuration values (versioned snapshot, 18 §11 step 8), not memory |
Segment blobs are a content-addressed cache inside the tenant's own storage prefix (§6.3), not memory; they are deleted with the job's retention (04 §7). No vector index, no knowledge access, no cross-tenant cache.

---

## 15 Upstream and downstream contracts
**MVP: 3A · Tier 0. Contracts are 03 (envelopes), 24 (task graph) and the neighbours' blueprints (read for task-type names and §15 only); nothing here redefines them.**

### 15.1 Upstream (what Agent 10 receives)
| From | What | Mapping rule |
|---|---|---|
| Agent 09 `agent_09.shot_plan` (s09_plan) | plan blob: `shots[]` (incl. `held`, `change_events_ms`), `overlays[]` (`template_ref`), `audio_plan` (`deliberate_pauses[]`, music `NONE` in 3A), `deliberate_black[]` (always empty) and `deliberate_hold[] {start_ms, end_ms, shot_id, reason}` (CCR register, blueprint 09), `chapters[]`, `jl_cuts`, `interrupts`, `hook`, `timing_basis`, `total_duration_ms`, `narration_timeline_sha256`, `tier_budget` (`ai_video_limit_ms`) | quoted field names of agent_09 §8.1–8.2; `timing_basis = MEASURED` is the only accepted value (`s09_plan` depends on `s07_voice` in v1, v2 and Shorts v2, CCR-003/051; no estimated mode, no `rebase_plan` by Agent 10); Agent 10 compiles `$T` and owns frame quantisation (agent_09 §15.2); `deliberate_hold` = the intervals of shots with `held ≠ null`, as listed by the plan |
| Agent 08 `agent_08.asset_sourcing` (s08_assets) | manifest `shots[]` (one entry per shot **and** aspect: `shot_id`, `aspect_ratio`, `asset_id`, `asset_uri`, `media {width_px, height_px, duration_ms, source_in_ms, crop}`, `tier`, `source_type`, `licence_id`, `ledger_entry_ids`, `usage_kind`, `status`, `chart`, `disclosure`), the reveal sequences of chart shots (`shots[].reveal_stills[]`: `len(change_events_ms) + 1` stills, `IMAGE` assets, agent_08 §6 item 7 and §8.2 rule 9), `overlays[]` with `template_asset_id`, `ai_broll {clips, total_ms, cost_micros, currency}` (information only), `unresolved_shot_ids` | a shot without an asset is `PERMANENT.MISSING_DEPENDENCY` (agent_08 §15.2); selection by (`shot_id`, `aspect_ratio`); chart data end date from `chart` / `assets.attributes`; the AI B-roll limit is **not** in the manifest (it is `tier_budget.ai_video_limit_ms` of the plan, CCR-055) |
| Agent 07 `agent_07.audio_master` (s07_master) | `master {master_uri, sha256, duration_ms, sample_rate_hz = 48000, channels = 2}`, `codec_profile` (typed `{codec, profile, sample_rate_hz, channels, bitrate_bps, encoder, rate_mode}`, CCR-055), `measurements`, `gate_verdict`, `music` (null in 3A) | the master WAV is muxed (not the raw stem); audio is encoded with `codec_profile` (agent_07 §15.2); `PASSED` required; Agent 07 produces the stems, Agent 10 measures them (CCR-055) |
| Agent 07 `agent_07.voice_synthesis` | narration timeline: `timeline.source` (`PROVIDER_CLIPS` / `OWNER_MARKS` in 3A), per sentence `segment_id`, `start_ms`, `end_ms`, `deliberate pauses`; the narration stem (3B: music stem) | subtitle timing and `qc.duration.vs_script`; a timeline `UNALIGNED` is refused at `s07_voice` in 3A (CCR-051), so it never reaches Agent 10; if one arrives it is `INPUT_INVALID` (§18) |
| Agent 05 (script) via Agent 06 | script strings by `segment_id`, `scene_id` and index; chapters; verified script SHA-256 | text by reference only; hash gate |
| Brand kit (S11 → 13, 04 §5.12) | font asset, overlay templates, brand sting | read-only; template format **REQUIRES REVIEW (Phase 1): PROPOSAL: image plus geometry file; the brand-kit template format is not yet decided (CCR-034 covers the workspace kit only)** |
| Orchestrator | Task Input, controls (`DRAIN`, `CANCEL`, `PAUSE`, `RESUME`) | 03 §4.3 |
| Worker framework | `AdmissionProbe` (clock, drain flag, placement) | injected (§9) |

### 15.2 Downstream (what Agent 10 produces and who reads it)
| To | What it receives | Mapping rule |
|---|---|---|
| Orchestrator | Task Outputs; `gate: true` results with `remedy_stage_id`, `gate_verdict`, `failures[]` | routes REVISE per 24 §7.1a / §7.2a: target `s10_render`, alternatives `s07_voice`, `s08_assets`, `s09_plan`; earliest named stage wins (24 §3.3 rule 1, CCR-002) |
| `svc_s02.uniqueness_check` (s02u_unique, after `s10_qc`) | final render ref and SHA-256 | reads the file; a failure there revises `s05_script` (`s05_shorts` for the child job) |
| Agent 16 `compliance_gate`, `quality_score` | `renders` row, `qc_results` (licence line, AUDIO_QUALITY, EDITING_QUALITY and VISUAL_QUALITY deterministic parts), the evidence manifest `agent_10.evidence_manifest` (§8.3a; `evidence.manifest_ref` = Agent 16's `frames_ref`) with the sampled frames and their time positions for the judged checks | Agent 16 reads `qc_results` by `render_id` |
| S7 `FINAL_VIDEO` approval | subject = render `content_sha256` | the approval binds the file QC passed; a re-render creates a new subject |
| Agent 13 `file_delivery` (`s13_deliver`, after `s16_auth`) | final MP4 (16:9 of the parent job and, if produced, 9:16 of the `SHORTS` v2 child job), SRT | bundle items 1, 2, 4 (3A_SLICE_SPEC §4); the QC report (`qc_report` export preset, CCR-043) is built from `qc_results` |
| Agent 09 / 07 / 08 (via orchestrator) | `failures[]` as revision feedback; `remedy_stage_id` picks the stage | agent_09 FR-17; 24 §3.3 rule 7 |
| S4 | `render_ms` cost rows | 09 §12 per-stage report |
| Owner review (3B) | evidence pack (§22) | 18 §11 |

### 15.3 Contract items: status after the register (CONTRACT_CHANGE_REQUESTS.md §5, "Resolved for blueprint 10")
| # | Item | Decision | How this blueprint uses it |
|---|---|---|---|
| 1 | `s10_qc` revision targets | CCR-002 + CCR-003 (24 §7.1a, §7.2a): target `s10_render`, `alt_target_stage_ids` `s07_voice`, `s08_assets`, `s09_plan`; `remedy_stage_id` on results | §6.5.4 |
| 2 | licence matching without `render_id` | CCR-030 | §13.1, row 39 |
| 3 | payload schemas `agent_10.render/subtitles/technical_qc.input/.output` | approved as-is (CCR-018): registered by being defined | §7, §8 |
| 4 | `agent_10.*`, `a10.*` | approved; `qc.*` IDs are 18's, never new (CCR-019/020) | §20, §24.2 |
| 5 | `render.segment` scope | approved (CCR-015) | §16.2 |
| 6 | success rule for blocking gates | CCR-001 (`gate: true`, `remedy_stage_id`) | §6.5, §8.3 |
| 7 | `assets.attributes.language` | approved (CCR-032); `cost_figure_kind MEASURED` rejected (CCR-038) | §13.3 |
| 8 | music bed | 3B; Agent 08 sources, Agent 09 plans, Agent 07 mixes (CCR-007) | §7.5 |
| 9 | D6 | recorded in IMPLEMENTATION_PROGRESS (D6); 3B-BLOCKING | §7.5, §23 |
| 10 | `ESTIMATED` plan, `UNALIGNED` narration | refused upstream, Agent 10 refuses too (CCR-051) | §6.2, §18 |
| 11 | market hours for every `HEAVY_CPU` task, self-checkpoint | CCR-056 | §6.4 |
| 12 | review CCR-B…J | B → `BLOCKED_COMPLIANCE`; C, D, E, F, G → 18 edits (CCR-055); H → Agent 09 intervals; I → typed `codec_profile`; J → 27 §6.1 (CCR-024) | §1.2, §20 |
Names taken from the neighbouring blueprints (not contract requests): the Agent 08 manifest field `shots[].reveal_stills[]` (agent_08 §8.2) and Agent 09's `deliberate_black[]`/`deliberate_hold[]`; contract tests C-04/C-05 pin them. Operational names not in a contract yet: the `AMW_PLACEMENT` values (`DEV`/`VPS`) and the keys `ops.market_windows`, `ops.night_window`, `drain.grace_ms` belong to 06_NIGHT_SCHEDULING.md (not written).

---

## 16 State handling and checkpoints
**MVP: 3A · Tier 0. State machine: 03 §11; Agent 10 does not transition tasks, the worker framework does. Checkpoint rows: 04 §5.7. Resume rules: 07 §8, §10.**

### 16.1 State model
| Layer | Owner | Content | Lifetime |
|---|---|---|---|
| Task state (`RUNNING`, `CHECKPOINTED`, `RETRY_WAIT`, `COMPLETED`, `FAILED`…) | orchestrator and worker framework | T07–T15 | task |
| Step state | Agent 10, in the checkpoint `state_ref` blob | pre-allocated `render_id` and output blob paths; `timeline_sha256`; segment list with content-addressed keys, sizes, SHA-256 and frame counts of finished segments; guard counters; for QC: the results of finished groups | until the task ends |
| Working memory | Agent 10 process | parsed outputs, scratch files | attempt only |
Agent 10 is stateless between attempts. The `render_id`, the final blob path and every segment path are fixed **before** the first write and stored in the first checkpoint, so a resumed attempt writes to the same write-once paths (an orphan blob without a row is harmless and byte-identical on re-creation).

### 16.2 Checkpoints
| Task | Step keys (`checkpoints.step_key`) | `completed_effects` | Written |
|---|---|---|---|
| `agent_10.render` | `render.gated` (gates and IDs allocated), `render.timeline` (timeline blob written), `render.seg_<ordinal>` (one per finished segment), `render.mux` (final blob stored), `render.registered` (`renders` row, cost row) | `render.segment` effect keys (CCR-015), then `render.master` | after each atomic unit; `progress_ratio` = finished frames / total frames |
| `agent_10.subtitles` | `subs.cues` (cue list hash), `subs.registered` | `db.output` | after each |
| `agent_10.technical_qc` | `qc.probe`, `qc.audio`, `qc.video`, `qc.db`, `qc.persisted` | `db.output` | after each group, so a kill after the decode passes does not repeat them |

### 16.3 Atomic write unit and drain
| Aspect | Rule |
|---|---|
| Atomic unit | one segment blob, the timeline blob, the final MP4, one evidence blob, one DB transaction: written to a temporary file in the same storage area, flushed, atomically renamed to the write-once path (07 §8.1). A kill leaves no partial file at a final path (FI-03) |
| What is not atomic | the FFmpeg encode of a segment; it works in scratch and can be abandoned and redone (at most one segment lost, NFR-2) |
| `DRAIN` / guard closed / self-drain timer at `act_by` | between segments or QC groups: checkpoint, `SUSPENDED` with `WAIT / DRAIN`, lease released. Mid-segment (or mid-QC pass): finish if the estimated end is before `act_by`, else SIGTERM, discard `.part`, checkpoint (§6.3.4, §6.4) |
| Resume | a new attempt loads the latest checkpoint, re-checks tenant and upstream gates (a changed plan hash stops it as `INPUT_INVALID`), re-verifies every finished segment (§6.3.3), re-runs the guard, continues at the first unverified segment |
| Replay from DLQ | same Task Input and key (07 §5.2): finished segments and the final blob are reused after verification; `renders` row found by `render.master`; no second render, no second cost row for work already recorded |
| Max atomic-write time | config `limits.max_atomic_write_ms` for the render worker: **REQUIRES REVIEW (Phase 1): measured on the final-MP4 rename and the largest segment**; the service stop timeout (§24) must exceed it |
| Cancel | `CANCEL` control: abandon at the next safe point, delete scratch, keep finished content-addressed blobs (they are reusable and tenant-owned) |

---

## 17 Resource model
**MVP: 3A (formulas and limits) · 3B (measured values replace every ESTIMATE) · Tier 0 → Tier 1 (own render server) → Tier 3 (dedicated workers per tenant). Every figure below is an ESTIMATE derived by arithmetic from configuration or design, or `REQUIRES REVIEW (Phase 1)`. Nothing here is measured: the VPS audit is pending (A1) and no render has been run.**

| Resource | Rule or formula | Value |
|---|---|---|
| CPU | FFmpeg threads capped by config `agent_10.render.threads` and by the worker's cgroup (INF-03, INF-04); one render task per worker (`max_concurrency = 1`, ADR-012) | threads: **REQUIRES REVIEW (Phase 1): from the skeleton measurement** |
| Wall time per output minute | `a10_render_wall_ms_per_output_s` (NFR-1) | **REQUIRES REVIEW (Phase 1): MEASURED on the walking skeleton, dev environment and VPS** |
| Final file size | `bitrate × duration / 8`, video target 15–25 Mbps (18 §6) plus AAC 384 kbps | 1 minute of output: 15 Mb/s × 60 s / 8 = 112.5 MB … 25 Mb/s × 60 s / 8 = 187.5 MB (video only); a 10-minute video: about 1.1–1.9 GB (ESTIMATE, arithmetic; durations of real videos are **REQUIRES REVIEW (19)**) |
| Storage per render | segments (about 1× final) + final (1×) + SRT + evidence; segments are kept until job retention for reuse | about 2× final per iteration (ESTIMATE); each revision adds only changed segments |
| Scratch disk (peak) | one segment `.part` + one decoded input staging + mux staging + QC temp (no file larger than the final) | about 1× final + 2 segments (ESTIMATE) |
| Memory | segments are streamed; Python holds plans and parsed outputs only | **REQUIRES REVIEW (Phase 1)**; `MemoryHigh` / `MemoryMax` from the slice (INF-03) |
| QC decode passes | reference mode: ffprobe (no decode), packet scan (no decode), `ebur128` (audio), `silencedetect` ×2 (audio), blackdetect, freezedetect, scene (3 full video decodes); `agent_10.qc.single_pass` (default off) merges the three video passes into one filter chain, enabled only after R-02 proves equal results | video decodes: 3 (reference) or 1 (single-pass) |
| Detector ETA | QC wall time ≈ decodes × (video duration / decode speed) | decode speed **REQUIRES REVIEW (Phase 1)** |
| Segment length | `agent_10.render.segment_target_ms` = 60 000 (PROPOSAL; trades lost-work bound against per-segment overhead) | calibrate in 3B (P-02) |
| Retries | `resource` policy: 3 attempts, base 60 s, cap 30 min (07 §3.3); each retry resumes at the next unfinished segment | — |
| Cost | `render_ms` units, `amount_micros = 0` | no per-call fee |
| Window | never in market hours (D1), for all three tasks, on every placement; **3A runs on the development environment only (D8 rule 4)**; if the owner lifts it, on the VPS only 00:00–07:00 IST, scheduler drain flag 06:30, `act_by` = `07:00 − drain.grace`, stop 07:00 | guards §6.4 |
| Tier scaling | Tier 0 one worker; Tier 1 a render-only server before the first client (§1C.14, ADR-012); Tier 3 `workers.dedicated_org_id` | no code change to move (NFR-11) |
The ETA used by the guard is `remaining_output_s × a10_render_wall_ms_per_output_s`; until it is measured, VPS placement refuses to start (§6.4); in 3A only the development environment renders (D8 rule 4).

---

## 18 Errors and recovery
**MVP: 3A · Tier 0. Codes are the 07 §2 catalogue; none is added. Mapping lives in `ErrorMapper` (F-42; tests U-103…U-109).**

| Situation | Code | Disposition (07 §2) | Recovery |
|---|---|---|---|
| input fails schema | `PERMANENT.SCHEMA_INVALID` | FAIL, structured rejection | upstream fix |
| org mismatch across envelope, input, refs | `PERMANENT.TENANT_MISMATCH` | FAIL, L3 security | — |
| a ref of another tenant | `PERMANENT.CROSS_TENANT_REF` | FAIL + security event | — |
| plan `timing_basis ≠ MEASURED`, narration timeline `UNALIGNED` (contract violation, cannot occur in 3A), script hash mismatch, tiling gap or overlap, zero-frame shot or reveal step, reveal still count mismatch, template mismatch, glyph missing, text hash mismatch, nonzero LLM or cost budget, `music_bed` while disabled | `PERMANENT.INPUT_INVALID` | FAIL | revision upstream (the violation list names the shot or segment) |
| shot without asset (for the requested aspect), reveal still missing, unresolved shot in the manifest, audio master not `PASSED`, missing blob or row | `PERMANENT.MISSING_DEPENDENCY` | FAIL | upstream |
| required configuration unset (fps, segment target, encoder, ETA on VPS, limits) | `PERMANENT.CONFIG_INVALID` | FAIL, L3 operations | set configuration |
| input blob hash or size differs | `AGENT.CORRUPTED_OUTPUT` | RETRY (`agent`) | re-read; persistent mismatch escalates |
| same idempotency key, different request hash | `PERMANENT.IDEMPOTENCY_CONFLICT` | FAIL, L3 | — |
| deadline cannot be met | `PERMANENT.DEADLINE_EXCEEDED` | FAIL | — |
| FFmpeg killed by SIGKILL / OOM | `RESOURCE.OOM` | RETRY from checkpoint, reduced threads (`resource`) | next attempt halves `agent_10.render.threads` (floor 1) |
| FFmpeg abnormal exit, or segment frame count / CFR / IDR / colour-tag / GOP-setting verification fails | `RESOURCE.RENDER_CRASH` | RETRY from checkpoint (`resource`) | the bad `.part` is discarded; finished segments kept |
| an input asset fails ffprobe or decode on its own | `PERMANENT.INPUT_INVALID` (`ASSET_UNREADABLE:<asset_id>`) | FAIL | `remedy_stage_id = s08_assets` in the message |
| no space left | `RESOURCE.DISK_FULL` | SUSPEND `OPERATOR_PAUSE`, heavy admission paused (L3) | operator frees space |
| process exceeds its wall budget or heartbeat stale | `AGENT.HANG` | RETRY (`agent`) | resume |
| unparseable or missing measurement in QC | `AGENT.CRASH` (process ran) or `RESOURCE.RENDER_CRASH` (process died) | RETRY (`agent` / `resource`) | never `PASS` (18 §7.0.3) |
| host restart or worker lost mid-render | `INFRASTRUCTURE.HOST_RESTART`, `INFRASTRUCTURE.WORKER_LOST` | RETRY from checkpoint (`infra`) | reaper (07 §6) |
| storage or DB unavailable | `INFRASTRUCTURE.STORAGE_UNAVAILABLE`, `INFRASTRUCTURE.DB_UNAVAILABLE`, `TEMPORARY.DB_TRANSIENT` | RETRY | — |
| guard closed after claim (race with admission) or `DRAIN` | no error | `CHECKPOINTED / DRAIN` (T09) | resume next window (T15) |
| success claimed but 03 §5.3 rule fails | `AGENT.INCOMPLETE_OUTPUT` | RETRY once | — |
| the gate failed on every allowed iteration | no error code: the orchestrator completes the job with `outcome = BLOCKED_COMPLIANCE` (24 §3.3, 18 §7.0.4, CCR-002) | job outcome | owner decides |
| any hard cap of 07 §9 | `AGENT.LOOP_CAP_EXCEEDED` | FAIL | — |
Rules: no code path retries a `PERMANENT` error; a gate `FAILED` verdict (`gate: true` FAIL results) is not an error (task `SUCCEEDED`); an error object never carries script text, subtitle text, asset titles, paths or stderr (the stderr blob is referenced by `evidence_ref` only); every retry resumes at the smallest unit (one segment, one QC group); no infinite loop exists (segment loop is bounded by the segment list, retries by 07 §9). Tracebacks go to `dead_letter.traceback_ref`, redacted.

---

## 19 Security and permissions
**MVP: 3A · Tier 0 (designed for Tier 1+). Controls follow 08 §8 (five layers); this section states how Agent 10 enforces each.**

### 19.1 Tenant isolation — how Agent 10 enforces it
| Layer (08 §8) | Agent 10 control | Test |
|---|---|---|
| 1 App filter | every DB read and write goes through `amw_core.tenancy` (`SET LOCAL app.org_id`, `app.actor = agent_10`) with explicit `org_id` predicates; `TenantScope.assert_consistent` compares the `org_id` of envelope, Task Input, every context ref and every payload ref **before** any file is staged; plan, manifest, master, script, brand kit, checkpoints are resolved only inside that org; the worker never processes two tenants in one task and never batches tasks of different orgs in one FFmpeg run | S-01 |
| 2 RLS | connects as `amw_app` (no bypass, not table owner); unset tenant context returns zero rows, which fails closed as `MISSING_DEPENDENCY`; `FORCE RLS` on `renders`, `qc_results`, `checkpoints`, `assets`, `licence_ledger`, `cost_ledger` (INF-11) | 04 §3.7 suite; S-02 |
| 3 Storage URIs | every URI is compared with `app.org_id` before resolution (`platform` read-only: platform-held bytes only; the templates, glyph sets and fonts a render uses are tenant `TEMPLATE` / `FONT` asset rows with their own self-grant ledger rows, CCR-031, and are read under the tenant prefix); paths are built by `amw_core.storage` (`<root>/<org uuid>/…`) and never from payload, script or asset text; SHA-256 verified on every read; blobs write-once; segment cache and scratch are tenant-prefixed (`<scratch_root>/<org uuid>/<task>/`) and **never shared across tenants** (a content-addressed hit is looked up only under the tenant's own prefix) | S-03 |
| 4 Cache keys | no in-process or external cache holds tenant media across tasks; the segment cache is storage under the org prefix; any memo uses `amw_core.tenancy.cache_key()` (`amw:<org wire id>:a10:<hash>`), a key without the org part is refused | S-04 |
| 5 Logs and metrics | every line and metric carries `org_id`; no script text, subtitle text, asset titles, URIs of other tenants, stderr, keys or paths appear in logs; stderr is a blob under the tenant prefix referenced by hash | S-05 |
Further controls specific to this agent:
1. **No shell, no string commands.** FFmpeg is started with an argument list built from fixed templates by `ArgvBuilder`; inputs are staged under neutral names (`in_<n>.<ext>`, `seg_<nnn>.mp4`); overlay text goes through `textfile=` files (UTF-8 content, never inline); no payload, script or metadata string is ever an argument, a filter expression or a file name (S-06, injection fixtures).
2. **Untrusted media.** Every asset is probed before use; FFmpeg runs with `-protocol_whitelist file`, no network, as a non-root user in the worker container, with a timeout and rlimits; a decoder crash maps to `RENDER_CRASH`/`INPUT_INVALID`, never to a skipped shot.
3. **No network egress** beyond DB and storage; no LLM, TTS, stock or YouTube credential exists on the render worker (08 §3.2 inventory): only the DB login of `amw_app`, through the environment's secret mechanism (§24.2). Google OAuth does not exist in 3A (D1).
4. **Hash chain.** The final MP4's SHA-256 is the `FINAL_VIDEO` approval subject; the QC task refuses a render whose hash differs from `renders.content_sha256` (`a10.q.hash_chain`); nothing is overwritten.
5. **No personal data.** Agent 10 handles media and IDs; a clone-voice or person-bearing asset is Agent 16's compliance matter; Agent 10 only records `assets.depicts_real_person`/`is_realistic_synthetic` facts in the evidence.
6. **Spend is a permission.** Agent 10 cannot raise a budget, add a provider or make a paid call.
7. **Provenance and watermarks of sources** are verified from the ledger (`qc.watermark.provenance`), never by trusting asset names.

### 19.2 Permission matrix (agent identity `agent_10`; 08 §5.3)
| Action | Allowed |
|---|---|
| read `scripts`, `brand_kits`, `channels`, `jobs`, `assets`, `licences`, `licence_ledger`, `renders` of its own org; read plan, manifest, audio blobs of its own task chain | yes |
| insert `checkpoints`, `renders`, `qc_results`, one `assets` row of `kind = SUBTITLE`, `cost_ledger`, `audit_log` (via core), blobs under `jobs/<job>/renders/…` and its attempt path | yes |
| update `renders` (`status`, measured columns, `SUPERSEDED` of its own earlier rows) | yes |
| insert or update `licence_ledger`, `licences`, any other `assets`; update `quality_scores`, `compliance_verdicts`, `approvals`, `budgets`, `memory_items`; delete any row | **no** |
| create tasks, approve, change controls, publish, call providers | **no** |

### 19.3 Abuse cases
| Case | Defence |
|---|---|
| script or on-screen text containing shell or filter syntax (`'`, `:`, `%{…}`) | text only via `textfile=`; filter strings are fixed templates; fixture in S-06 |
| asset file crafted to make FFmpeg open a network or local path (playlist/concat tricks) | `-protocol_whitelist file`, staged neutral names, no user-supplied concat lists, probe before use |
| foreign `plan_ref` or asset URI | `CROSS_TENANT_REF`, security event, no read |
| plan edited after verification | script hash gate and plan SHA-256 verified on read |
| a render replaced after QC | write-once blobs; approval bound to SHA-256; `a10.q.hash_chain` |
| forged licence status | licence read through RLS at QC time; `ACTIVE`, monetisation, expiry evaluated on the current row, not on the manifest copy |
| disk-fill by a huge asset | declared size and duration checked against limits before staging; `DISK_FULL` suspends, never deletes other data |
| secret in stderr or logs | stderr stored as a blob and never logged; canary test S-05 |
| cross-tenant segment reuse | cache lookup only under the task's org prefix (S-04) |
| attempt to render, subtitle or QC in market hours by replay or manual claim, or a long-running task reaching a market window | worker-side guard and self-drain timer independent of admission (FI-08, FI-13) |

---

## 20 Quality criteria
**MVP: 3A (every check; WARN-until-set ones are non-blocking) · 3B (calibrated thresholds, owner scores, music-bed offset after D6) · 3C (burned-in captions, other profiles) · Tier 0. Every relevant §1A rule is a measurable requirement below. Each check is deterministic, appears in `validation_results` (and, for QC checks, in `qc_results`) with measured value and threshold, and has one pass and one fail fixture: row n has unit tests U-(108+2n) (pass) and U-(109+2n) (fail). `qc.*` and `edit.*` rows are reported with `gate: true` (and, on FAIL, `remedy_stage_id`, §6.5.4); `a10.*` rows are process-integrity checks with `gate: false` (03 §5.3 rules 2 and 4). "Blocking" is the default of the `qc.long_form` profile; a value marked "WARN until set" becomes blocking only when its configuration key is set (§6.5.1). Thresholds come from 18 §5–§7 and are configuration keys (§24.2), not literals.**

### 20.1 Checks owned by Agent 10
| # | check_id | §1A rule | Measurable criterion | Blocking | MVP |
|---|---|---|---|---|---|
| 1 | `a10.q.schema` | §3.3 | every output validates against its payload schema (§8) | yes | 3A |
| 2 | `a10.q.tenant` | rule 9 | org of envelope, input, every ref, every row read and written equal | yes | 3A |
| 3 | `a10.q.upstream` | §1A.6 | plan `timing_basis = MEASURED`; manifest covers every shot of the requested aspect; reveal still count = `len(change_events_ms) + 1` for every chart shot; audio master `PASSED`; script hash equals the verified one | yes | 3A |
| 4 | `a10.q.timeline_frames` | §1A.5 CFR | video packet count of the final file equals `total_frames` of `$T` | yes | 3A |
| 5 | `a10.q.segments_verified` | §3.3 | every segment verified (size, SHA-256, frame count, first frame IDR) before concat | yes | 3A |
| 6 | `a10.q.no_provider_call` | rule 8 | zero provider calls, `llm_calls = 0`, `cost_estimate_micros = 0`, no outbound connection | yes | 3A |
| 7 | `a10.q.hash_chain` | §1A.7 (approval binds the file) | every `output_refs` object exists with the stated SHA-256 and size; final blob SHA-256 equals `renders.content_sha256` | yes | 3A |
| 8 | `a10.sub.format` | §1A.5 SRT | UTF-8 (no BOM), numbered cues, `HH:MM:SS,mmm`, `start < end`, ordered, non-overlapping, no empty text, last cue ≤ video duration | yes | 3A |
| 9 | `a10.sub.coverage` | §1A.5 accessibility | every narration segment with text has at least one cue; cue count > 0 | yes | 3A |
| 10 | `a10.sub.text_from_script` | §1B.2 (no invented text) | concatenated cue text of each segment equals the script string of that `segment_id` (whitespace-normalised, byte-exact otherwise) | yes | 3A |
| 11 | `qc.video.resolution` | §1A.5 | 16:9: `width ≥ 1920` and `height ≥ 1080` (keys `qc.video.min_width_px`, `.min_height_px`); 9:16: per preset (1080×1920 PROPOSAL; official spec REQUIRES REVIEW → WARN) | yes | 3A |
| 12 | `qc.video.codec_profile` | §1A.5 | `codec_name = h264`, `profile = High`, `field_order = progressive` | yes | 3A |
| 13 | `qc.video.pix_fmt` | §1A.5 | `pix_fmt = yuv420p` (SDR) | yes | 3A |
| 14 | `qc.video.bitrate` | §1A.5, INF-10 | 15–25 Mbps PASS; 8–15 or above 25 WARN; below 8 FAIL (DC-40…DC-44) | FAIL band only | 3A |
| 15 | `qc.video.cfr` | §1A.5 | `r_frame_rate = avg_frame_rate` and all packet intervals within the tick tolerance of `1/fps` (DC-81, DC-82; tolerance REQUIRES REVIEW) | yes | 3A |
| 16 | `qc.video.fps_matches_project` | §1A.5, INF-10 | `r_frame_rate` equals `fps_num/fps_den` of `$T` | yes | 3A |
| 17 | `qc.container.faststart` | §1A.5 | `moov` before `mdat` | WARN until method confirmed | 3A |
| 18 | `qc.audio.codec` | §1A.4 | `aac`, profile `LC` | yes | 3A |
| 19 | `qc.audio.sample_rate` | §1A.4 | 48 000 Hz | yes | 3A |
| 20 | `qc.audio.channels` | §1A.4 | 2 | yes | 3A |
| 21 | `qc.audio.bitrate` | §1A.4, INF-10 | the **configured nominal** audio bitrate recorded for the render (`renders.audio_bitrate_bps`, from the encoder arguments) `≥ 384 000`; the measured stream average is recorded in `measured` of the report and is not the gate (18 §7.1, CCR-055; the native AAC average measured 200–243 kbps on synthetic signals, FFmpeg 6.1.1). **REQUIRES REVIEW (Phase 1): confirm on the pinned build with speech material** (DC-115, DC-116) | yes (nominal) | 3A |
| 22 | `qc.audio.true_peak` | §1A.4 | `true_peak_dbtp ≤ −1.0` (`ebur128=peak=true`; DC-33, DC-45, DC-46) | yes | 3A |
| 23 | `qc.audio.integrated_lufs` | §1A.4 | `|I − (−14.0)| ≤ qc.loudness.tolerance_lu` (DC-47…DC-49) | WARN until tolerance set | 3A |
| 24 | `qc.audio.lra_report` | §1A.4 | LRA recorded (information) | no | 3A |
| 25 | `qc.audio.clipping` | §1A.4 | 3A: Agent 07's recorded `clipping_samples = 0` for the master is cross-checked; independent count (`astats`, REQUIRES REVIEW) in 3C | yes | 3A (cross-check) · 3C |
| 26 | `qc.audio.music_bed_offset` | §1A.4 | `−20.0 ≤ L_music − L_narration ≤ −15.0` dB over narration-active spans (DC-69…DC-72); `SKIPPED` without a music stem (3A technical runs have none, CCR-007) | yes | 3B (SKIPPED in 3A) |
| 27 | `qc.audio.silence_mix` | §1A.6 dead air | no silence run ≥ `qc.silence.max_ms` outside the plan's `audio_plan.deliberate_pauses[]`; none at file start or end (DC-59…DC-62) | WARN until calibrated | 3A |
| 28 | `qc.audio.speech_spans` | §1A.6 | narration-active spans produced for the music and sync checks | no | 3A |
| 29 | `qc.video.black_frames` | §1A.6 | no `blackdetect` run outside the plan's `deliberate_black[]` (always empty in 3A, so every run counts); none at first or last frame (DC-55…DC-58) | WARN until `d` calibrated | 3A |
| 30 | `qc.video.freeze` | §1A.6 | no `freezedetect` run outside the plan's `deliberate_hold[] {start_ms, end_ms, shot_id, reason}` intervals (the held shots of the plan) | WARN until calibrated | 3A |
| 31 | `qc.sync.av_container` | §1A.6 | `|start_video − start_audio| ≤ tol_start`, `|duration_video − duration_audio| ≤ tol_dur`; any difference over one frame is recorded | WARN until set | 3A |
| 32 | `qc.subtitles.format` | §1A.5 | as row 8, re-run on the stored file with `ffmpeg -v error -i $S -f null -` and the strict parser (cue counts equal) | yes | 3A |
| 33 | `qc.subtitles.languages` | §1A.5 | one SRT per language of the job | yes | 3A |
| 34 | `qc.subtitles.sync` | §1A.6 (18 §7.6.2, CCR-055) | per narration segment: the **first** cue satisfies `|cue_start − segment_start| ≤ tol_sub_ms`, the **last** cue `|cue_end − segment_end| ≤ tol_sub_ms`, every interior cue boundary lies strictly inside the segment (DC-99…DC-101, DC-24) | WARN until calibrated | 3A |
| 35 | `qc.subtitles.accuracy` | §1A.6 | deterministic overlap with the script text = 100 % (by construction); judge not needed; human spot check at final approval | no | 3A |
| 36 | `qc.duration.vs_script` | §1A.6 (18 §7.7) | `|actual − expected| ≤ tol_dur_ms` with `expected_ms = Σ narration segment durations + Σ planned gaps and pauses (= the narration timeline end) + intro/end-screen segment lengths in $T`; a render shorter than the narration FAILs regardless (DC-118, DC-120) | shorter-than-narration FAIL; else WARN until set | 3A |
| 37 | `qc.duration.vs_timeline` | §1A.6 | `|actual_ms × fps_num − total_frames × 1000 × fps_den| ≤ 1000 × fps_den` (DC-50…DC-52) | yes | 3A |
| 38 | `qc.duration.in_bounds` | §1A.6 | within the production type's `duration_targets_ms` | `SKIPPED` until set (19) | 3A |
| 39 | `qc.licence.completeness` | §1A.1, §1A.6 (18 §2.2, §2.3, §7.9) | every timeline element (shots incl. each entry of `reveal_stills[]` with its own `IMAGE` row, overlays' templates, font, voice, music) has a ledger row (`render_id = R` or `render_id` null with the same job, CCR-030) covering its plan interval whose licence is `ACTIVE`, `covers_monetized_youtube = true`, unexpired, third-party permission not `UNKNOWN` for a non-holder; **the element's asset has `assets.status = ACTIVE`; an AI item (`D_AI_VIDEO`/`E_AI_STILL`) is recorded with `usage_kind = AI_OUTPUT`** (DC-63…DC-68, DC-95…DC-98) | yes | 3A |
| 40 | `qc.licence.expiry_window` | §1A.6 | no licence expires inside `qc.licence.expiry_warning_window`; an expired licence FAILs | expired FAIL; window WARN | 3A |
| 41 | `qc.watermark.provenance` | §1A.1, §1A.6 | every stock asset has a ledger row with `vendor_item_id` and an `ACTIVE` licence; no preview or trial item | yes | 3A |
| 42 | `qc.watermark.visual` | §1A.6 | deterministic fallback of 18 §7.10 (corner patch identical across ≥ 3 shots and absent from `$T`'s overlay list); the judged part is Agent 16's (`SKIPPED`, `JUDGED_BY_AGENT_16`) | WARN until method chosen | 3A |
| 43 | `qc.visual.tier_share_e` | §1A.1e | share of `E_AI_STILL` visual frames `< 50 %`; `share_permille = floor(frames × 1000 / total)`, so 299 of 600 frames is 498 permille; exactly 500 FAILs (DC-53, DC-54) | yes | 3A |
| 44 | `qc.visual.tier_mix_report` | §1A.1 | shares of tiers A–E written to the report | no | 3A |
| 45 | `qc.visual.ai_video_budget` | §1A.11 (18 §2.3, CCR-055) | `D_AI_VIDEO` milliseconds ≤ `tier_budget.ai_video_limit_ms` of the Agent 09 plan (set from the S4 reservation); a limit that is absent with `D` time > 0 FAILs (fail closed) (DC-102…DC-104). The manifest's `ai_broll` is the measured total reported in `tier_mix`, not the limit | yes | 3A |
| 46 | `qc.visual.ai_disclosure_recorded` | YT-06/07 (18 §2.3, CCR-055) | every `D_AI_VIDEO`/`E_AI_STILL` asset with `is_realistic_synthetic = true` has a `disclosure` record in the manifest (Agent 08); the `disclosure_decision` is checked by Agent 16 at `s16_comp`, after this stage | yes | 3A |
| 47 | `qc.visual.chart_data_age` | FIN-R9, IN-02 | every chart asset's `data_end_date` is older than `compliance.finance_sebi_in.price_data_lag_days` at check time | yes (finance channel) | 3A |
| 48 | `qc.visual.no_synthetic_presenter` | FIN-R11, YT-09 | metadata part: no `D`/`E` asset with `depicts_real_person = true` on a finance channel; frame-sample judge is Agent 16's | yes (finance channel) | 3A |
| 49 | `edit.hook.window` | §1A.2 | `hook.end_ms ≤ 30 000` and `hook.first_payoff_ms ≤ 30 000` (`qc.hook.window_ms`) | yes | 3A |
| 50 | `edit.hook.no_brand_intro` | §1A.2, §1A.8 | no `BRAND_STING` or logo overlay starts before the hook ends (DC-79, DC-80) | yes | 3A |
| 51 | `edit.visual.cadence` | §1A.2 | in every explanatory stretch the gap between change events (shot boundaries and the shots' `change_events_ms`, both read from `$T`; stretch ends included) ≤ 5 000 ms (DC-73…DC-76) | WARN until calibrated | 3A |
| 52 | `edit.visual.cadence_render_crosscheck` | §1A.2 | scene events of the rendered file agree with the timeline within a tolerance (threshold 0.3 PROPOSAL; REQUIRES REVIEW) | no | 3A |
| 53 | `edit.interrupt.first_dropoff` | §1A.2 | ≥ 1 interrupt element inside the configured first-drop-off window | WARN until set | 3A |
| 54 | `edit.interrupt.midpoint` | §1A.2 | ≥ 1 interrupt element within the window centred on 50 % of the duration | WARN until set | 3A |
| 55 | `edit.cuts.j_l` | §1A.2 | count of J and L cuts on the timeline ≥ the configured minimum rate | WARN until set | 3A |
| 56 | `edit.chapters` | §1A.2 | first chapter at 0, strictly increasing, each within ±1 000 ms of the section start (DC-77, DC-78) | yes | 3A |
| 57 | `edit.end_screen` | §1A.2 | the timeline ends with the reserved end-screen segment of the configured length and no other content in it | WARN until set | 3A |
| 58 | `edit.dead_air` | §1A.2 | as row 27 for the final mix | WARN until calibrated | 3A |
| 59 | `a10.q.colour_tags` | §1A.5 colour (18 §6) | the probed `color_primaries`, `color_transfer`, `color_space`, `color_range` equal the configured SDR tags (§6.2 item 9; values PROPOSAL bt709/bt709/bt709/tv, **REQUIRES REVIEW (Phase 1)**); run in `agent_10.render` after the mux; `gate: false` | yes | 3A |
| 60 | `a10.q.gop_settings` | §1A.5 GOP (18 §6) | the encoder settings recorded in the output (`encoder.gop`) equal the configured closed-GOP values: `closed_gop = true`, `gop_frames` as configured, `idr_at_segment_start = true` (ffprobe cannot prove a closed GOP; the recorded settings are the evidence); run in `agent_10.render`; `gate: false` | yes | 3A |
Profile `qc.shorts` (3A in the `SHORTS` v2 child job when the owner asks for the 9:16 cut; section-based items such as `edit.chapters` and the section-bound interrupt items are emitted `SKIPPED`, `blocking: false`, 24 §7.2a): the same set on the vertical preset; values `REQUIRES REVIEW (Phase 1)` (18 §10). Profiles `qc.ad_spot`, `qc.dubbing`, `qc.corporate`: 3C, Tier 1+ (18 §8).

### 20.2 Checks of 18 that Agent 10 does not run (owner named, to avoid double ownership)
`edit.hook.options`, `edit.hook.selection_valid`, `edit.hook.beats`, `edit.hook.beat_content` read the script payload: Agent 05 (`a05.*`; agent_05 S1) and Agent 16 (judge). `edit.promise_alignment`: Agent 16 (judge). `edit.editorial_contribution`: S7 and the publish guard. The score of 18 §9 and the compliance verdict: Agent 16. The judged parts of `qc.watermark.visual`, `qc.visual.no_synthetic_presenter`, `edit.promise_alignment` and `edit.hook.beat_content` run in Agent 16 (CCR-058).

### 20.3 §1A rule → requirement map
| §1A rule | Where it is a measurable requirement |
|---|---|
| §1A.1 visual hierarchy, licence per shot | rows 39–48; tier mix report; E share < 50 % |
| §1A.2 hook, cadence, interrupts, J/L, chapters, end screen | rows 49–58 |
| §1A.4 audio delivery (−14 LUFS, −1 dBTP, 48 kHz, AAC-LC at a nominal ≥ 384 kbps, music 15–20 dB under) | rows 18–26 |
| §1A.5 video delivery and SRT | rows 8–17, 32, 33, 59, 60 |
| §1A.6 automated QC | rows 4, 22–38 and the gate (§6.5) |
| §1A.7 100-point score, human approval | not Agent 10; row 7 binds the approved file to its hash |
| §1A.8 formats 16:9 / 9:16 | rows 11, 16; `shorts_9x16` values REQUIRES REVIEW (18 §10) |
| §1A.10 golden samples | 3B: calibration of every WARN-until-set value (SC-8) |
| D1 render window, no upload, no OAuth | guard (§6.4), FI-08, FI-09; no upload or OAuth code exists in the package |

---

## 21 Tests
**MVP: 3A (all categories) · 3B (calibration runs, music-stem cases after D6; the single owner-authorised live smoke is not needed: no provider) · Tier 0. No paid call exists in any Agent 10 test (27 §8). Media tests use `lavfi` synthetic sources and generated assets only; no real or tenant media.**

| Category | IDs | What |
|---|---|---|
| Unit | U-01…U-109, U-110…U-229, U-230…U-238 | one group per function of §10 (ranges in its "Tests" column; row n of §20.1 has U-(108+2n) pass and U-(109+2n) fail, rows 1–60 = U-110…U-229; U-230 `MusicBedPort` (3B), U-231 `EvidenceWriter`, U-232 `QcPersister`, U-233/U-234 `SelfDrainTimer`, U-235…U-237 `RevealStepBuilder`, U-238 subtitle timeline gate). Table-driven from `evals/agent_10_video_editor/deterministic_core/cases.jsonl` (R-01): U-11…U-16 (DC-86…DC-94, DC-105, DC-106), U-06…U-10 (DC-112, DC-113, DC-119), U-17…U-26 (DC-01…DC-13), U-34…U-40 (DC-14…DC-20), U-62…U-68 (DC-33…DC-39), U-84…U-96 (DC-21…DC-32), U-98…U-100 (DC-83…DC-85, DC-117), U-233/U-234 (DC-107, DC-108), U-235…U-237 (DC-109…DC-111), U-238 (DC-114), and the check evaluators U-110…U-229 (DC-40…DC-82, DC-95…DC-104, DC-115, DC-116, DC-118, DC-120). U-103…U-109: one test per row of the §18 mapping (exception → code, class, disposition). U-102: `CostRecorder` writes `provider = ffmpeg`, `operation = render.ffmpeg`, `unit_kind = render_ms`, `amount_micros = 0`, and the task input with `max_cost_micros ≠ 0` is rejected |
| Integration | IT-01 whole render on a synthetic plan (generated shots from `lavfi` colour/test sources incl. one chart shot with reveal stills, generated master, fake `AdmissionProbe`): output frames = timeline, colour tags and GOP settings as configured, final file passes `qc.long_form` (the audio-bitrate check reads the configured nominal rate, the measured average is only reported); IT-02 subtitles on a fixture script and timeline; IT-03 QC on IT-01's file: every check of §20.1 has a result and the evidence pack exists; IT-04 revision iteration reuses unchanged segments (`segments.reused` > 0, byte-identical keys); IT-05 `SHORTS` 9:16 render and `qc.shorts`; IT-06 `ReadinessProbe` passes and fails on each missing dependency; IT-07 the same worker image started with a different configuration (placement, DB, storage) renders the same SHA-256 (movability, NFR-11) |
| Contract | C-01 input schemas; C-02 output schemas (JSON Schema ⇄ Pydantic equality); C-03 Task Output envelope and success rule (03 §5); C-04 plan fields consumed (incl. `change_events_ms`, `held`, `deliberate_black[]`, `deliberate_hold[]`, `tier_budget.ai_video_limit_ms`) vs agent_09 §8.1–8.2; C-05 manifest fields (incl. the reveal sequence, overlays' `template_asset_id`, per-aspect entries) vs agent_08 §8.2; C-06 audio master and narration timeline vs agent_07 §8; C-07 `qc_results` and `renders` columns vs 04; C-08 every `check_id` matches `^[a-z0-9_.-]{3,96}$` and every gate check (`qc.*`, `edit.*`) has a `RemedyMapper` entry whose value is a target or alternative of `s10_qc` in 24 §7.1a / §7.2a |
| Regression (eval) | R-01 `deterministic_core` (120 cases, 100 % required, §26); R-02 QC self-test of 18 §7.11 on the pinned FFmpeg build, plus the **A/V content-sync calibration clip** of 18 §7.6 (a flash frame and a 1 kHz beep at known times; measured with `select` and `silencedetect`, run once per FFmpeg/render-image version and in the 3B pilot, not per video): lavfi fixtures (clean file passes every sourced check; true peak above −1 dBTP; black segment; frozen segment; silence run; 1-frame A/V start offset; SRT overlap; 12 Mbps) each with its asserted verdict, plus single-pass equals reference passes |
| Failure injection | FI-01 kill FFmpeg mid-segment → resume re-encodes only that segment, final SHA-256 equals an uninterrupted run; FI-02 kill the worker between segment rename and checkpoint → resume verifies the orphan blob and continues; FI-03 kill during the mux and during the final rename → no file at a final path other than a complete one; FI-04 `DRAIN` mid-render → `CHECKPOINTED / DRAIN`, resume completes; FI-05 DLQ replay of a completed render → no second row, no second cost row, same SHA-256; FI-06 a detector output truncated or missing its summary → never `PASS`, `AGENT.CRASH`; FI-07 disk full → `RESOURCE.DISK_FULL`, `OPERATOR_PAUSE`, no deletion of other data; FI-08 claim attempted inside market hours (every placement) → no segment starts; FI-09 VPS placement (fake probe only, D8 rule 4) at the drain point `07:00 − drain.grace` and after 07:00 → no new segment, graceful checkpoint; FI-10 OOM signal → retry with halved threads; FI-11 corrupt segment blob (flipped byte) → detected by SHA-256, re-encoded; FI-12 input asset corrupt → `INPUT_INVALID ASSET_UNREADABLE`, no skipped shot; FI-13 a segment estimate far too low (the encode is slower than the estimate) and a market window opening mid-segment, and the same for a QC decode pass of `agent_10.technical_qc` → the self-drain timer at `act_by` sends SIGTERM, discards the `.part`, writes the checkpoint before the window starts, the task is `CHECKPOINTED / DRAIN` and resumes later with the same final SHA-256 |
| Performance | P-01 render wall time per output minute on a synthetic 1080p project (records NFR-1; bound **REQUIRES REVIEW (Phase 1)** set from the skeleton); P-02 segment length vs total time and lost work (calibrates `segment_target_ms`); P-03 peak memory of the worker process and FFmpeg; P-04 scratch and storage footprint per output minute vs §17; P-05 QC wall time, reference vs single-pass |
| Security | S-01 cross-tenant refs of every kind rejected with the §18 code before any file is staged; S-02 RLS: unset context yields zero rows; the role has no bypass; S-03 storage and scratch paths only from core, `..` and absolute segments rejected; S-04 segment cache lookup only under the task's org; keys carry the org; S-05 log-leak canary: script text, subtitle text, asset titles, stderr, paths never appear in any log or metric; S-06 command-injection fixtures: script text and metadata containing quotes, `:`, `%{…}`, newlines and shell syntax never reach an argument; S-07 untrusted media: a crafted playlist or `concat` file and a network-protocol input are refused by the whitelist and the probe; S-08 permission matrix (§19.2): one test per cell, denied cells included; S-09 socket guard (no outbound connection except DB and storage), no LLM adapter import, no prompt file in `prompts/agent_10_video_editor/` |
| End to end | E-01 the 3A walking-skeleton path (27 §9): the upstream outputs `s07_master`, `s08_assets` (incl. reveal stills) and `s09_plan` that `UpstreamGate` needs are produced by the fake adapters of Agents 07, 08 and 09 (generated at test time; the skeleton path script → TTS → render has no other source of them), real FFmpeg on lavfi sources, kill-and-resume (27 §9 test 2), no render in market hours (test 6), QC report from `qc_results`; E-02 the 3B pilot: the three golden-sample renders on the owner's topics with the real upstream adapters (no paid call by Agent 10 itself), evidence pack reviewed by the owner (blocked for music-bed samples until D6) |
Coverage floor and CI gates: 27 §5 (ruff, mypy strict, pytest with coverage floor, eval gate on `deterministic_core` always, because the dataset is free and offline).

---

## 22 Observability
**MVP: 3A · Tier 0. Structured JSON logs through `amw_core.observability`; every metric carries `org_id` and `agent_id = agent_10`; no content, secrets or paths (NFR-13).**

| Kind | Name | Labels (besides `org_id`, `agent_id`) |
|---|---|---|
| Counter | `a10_segments_total` | `outcome` (`encoded`, `reused`, `discarded`) |
| Counter | `a10_guard_checks_total` | `task` (`render`, `subtitles`, `qc`), `result` (`allowed`, `denied`, `self_drain`), `reason` (`DRAIN`, `MARKET_HOURS`, `OUTSIDE_NIGHT_WINDOW`, `NIGHT_WINDOW_END`) |
| Counter | `a10_ffmpeg_runs_total` | `kind` (`segment`, `mux`, `probe`, `detector`, `evidence`), `outcome`, `error_code` |
| Counter | `a10_check_results_total` | `check_id`, `verdict` |
| Counter | `a10_gate_total` | `profile`, `gate_verdict`, `remedy_stage_id` |
| Counter | `a10_resume_total` | `reason` (`kill`, `drain`, `replay`, `host_restart`) |
| Histogram | `a10_segment_wall_ms`, `a10_mux_wall_ms`, `a10_qc_wall_ms`, `a10_render_wall_ms_per_output_s` | `preset_key` |
| Gauge (last value per job; `job_id` is a log field) | `a10_total_frames`, `a10_final_size_bytes`, `a10_integrated_lufs`, `a10_true_peak_dbtp`, `a10_video_bitrate_bps`, `a10_e_share_permille`, `a10_black_runs`, `a10_freeze_runs`, `a10_silence_runs` | — |
Log events (IDs, hashes, counts, check IDs only): `render.start`, `render.tenant_ok`, `render.upstream_ok`, `render.guard`, `render.timeline`, `render.segment_plan`, `render.segment_done`, `render.resume`, `render.drain`, `render.self_drain`, `render.mux`, `render.registered`, `subs.cues`, `subs.validated`, `qc.start`, `qc.group_done`, `qc.check`, `qc.gate`, `qc.evidence`, `qc.persisted`, `selftest.result`.
Audit actions (registered here, 08 §9.2 rule; written through `amw_core.audit`): `render.started`, `render.completed`, `render.superseded`, `render.guard_refused`, `subtitles.completed`, `qc.completed`, `qc.gate_failed`. `details` hold IDs, hashes and numbers only.
Traces: one span per task, child spans per segment, per detector pass and per check group. Alerts (proposed): guard denial on the development placement during market hours with a task claimed (should never occur; L3 operations), render crash rate rising, job outcome `BLOCKED_COMPLIANCE` after the revision cap (L3 quality), disk full (L3 operations), self-test failure after a build change (blocks readiness).
**Evidence kept per render (owner rule A.12; 18 §11 evidence package):** the evidence manifest (§8.3a: one document, `frames[]` with `frame_id`, `frame_index`, `t_ms`, `shot_id`, hashes), contact sheet of sampled frames (FFmpeg `tile`), the sampled frames themselves (for Agent 16's judged checks), loudness-over-time series from an extra `ebur128` pass with frame logging (downsampled to 1 Hz), tier-mix shares, the check table (measured vs threshold, PASS / WARN / FAIL / SKIPPED), detector run lists mapped to shot IDs, render and QC wall time. Agent 10 writes data and sample images only; the report tooling draws the charts from that data. The owner sees before-and-after evidence for every revision (the iteration's check table side by side).

---

## 23 Human approvals
**MVP: 3A (none inside the tasks) · 3B (owner scores and listening/viewing check) · Tier 0.**
| Human act | Who | When | Kind | MVP |
|---|---|---|---|---|
| `FINAL_VIDEO` approval of the exact file Agent 10 rendered, with ≥ 1 editorial contribution | owner | after `s16_score` | `FINAL_VIDEO` / `owner_one_tap` (24 §3.4); subject = render `content_sha256` | 3A |
| Owner scores of audio, editing and visual quality on the pilot renders (18 §9.2 human rows) and review of the evidence pack | owner | pilot review | HUMAN rows in `quality_scores` (Agent 16 / S7 record them; Agent 10 never does) | 3B (mandatory), sampled after |
| Setting the calibrated thresholds (detector parameters, tolerances, cadence and interrupt values, segment target, readability limits) | owner, on the evidence | end of pilot | configuration change (audited), then R-01 and R-02 re-run | 3B |
| Choice of the licensed music source (**D6** in IMPLEMENTATION_PROGRESS; Q-O8 of the CCR register) | owner | before 3B music-bed samples | owner decision recorded in IMPLEMENTATION_PROGRESS; no purchase without the owner; provisional default: no music bed, 3B blocked | 3B |
| Operator pause or resume of heavy admission, disk-full recovery | operator | on alert | `OPERATOR_PAUSE` wait reason | 3A |
| Approval channel on the owner's phone | owner | any | decisions, scores and editorial contributions recorded verbatim by the operator tool run by the assistant on his behalf (no CLI work by the owner); owned by S7 and the integrator, not by Agent 10 | 3A |
Agent 10 never approves, never records a human check, never waits for a human inside a task (a suspended task holds no worker, 03 §11.6).

---

## 24 Deployment
**MVP: 3A (development environment first; VPS only per ADR-012) · 3B (VPS sizing from measurement, INF-03 / INF-04) · Tier 0. No secret, host, address or port appears here (08 §11).**

### 24.1 Services
| Unit | Process | Task types | Capabilities | Window | Placement | MVP |
|---|---|---|---|---|---|---|
| Render worker | `workers/render_worker`, package `agent_10_video_editor` | `agent_10.render`, `agent_10.subtitles`, `agent_10.technical_qc` | `render_ffmpeg`, `media_probe` (GLOSSARY §6.20); resource class `HEAVY_CPU`; `max_concurrency = 1` (design default) | never in market hours (all three tasks, self-drain at `act_by`); on the VPS (disabled in 3A) 00:00–07:00 IST, scheduler drain flag 06:30, `act_by` `07:00 − drain.grace`, stop 07:00 | development environment (the only placement in 3A: D8 rule 4 allows nothing on the VPS); shared VPS night window only after the headroom rule (ADR-012 §1.1) **and** after the owner lifts D8 rule 4; render-only server if the rule fails; same image everywhere | 3A |
The package is a library; no HTTP server, no public port; FFmpeg and ffprobe are local binaries of the same image, pinned (18 §7.0.2).

### 24.2 Configuration and environment variables (names only; values never in this repository)
| Name | Kind | Purpose | Scope |
|---|---|---|---|
| `AMW_ENV` | plain | environment label | all services |
| `AMW_DB_APP_DSN_REF` / secret `AMW_DB_APP_PASSWORD` | reference / secret | login of role `amw_app` | workers |
| `AMW_STORAGE_ROOT_REF` | plain | storage backend reference (ADR-005) | workers |
| `AMW_SCRATCH_ROOT_REF` | plain | scratch directory reference (per-org subdirectories, cleaned at start) | render worker |
| `AMW_WORKER_LOGICAL_NAME`, `AMW_PLACEMENT` | plain | worker registration name (no host names) and placement (`DEV` / `VPS`; operational values owned by 06_NIGHT_SCHEDULING.md and ADR-012, not yet a contract), used by the guard | render worker |
No LLM, TTS, stock or YouTube key exists on this worker.
Config keys (family `agent_10.*` approved, CCR-019/020; values are proposals until calibrated), **required** at startup unless marked optional: `agent_10.render.fps_num`, `.fps_den` (no default), `.preset_key`, `.video_encoder`, `.video_bitrate_bps` (inside 15–25 Mbps, PROPOSAL midpoint 20 000 000), `.video_maxrate_bps`, `.gop_frames` (**REQUIRES REVIEW**), `.segment_target_ms` (60 000), `.threads`, `.eta_ms_per_output_s` (required on `VPS`), `.drain_finish_max_ms`; `agent_10.sub.max_chars_per_cue`, `.min_cue_ms` (optional); `agent_10.qc.single_pass` (false), `agent_10.qc.sample_frames_per_min`, `agent_10.qc.profile`; `agent_10.music_enabled` (false); `qc.*` of 18 §13 plus the new keys `qc.detect.black.{d,pic_th,pix_th,calibrated}`, `qc.detect.freeze.{n_db,d}`, `qc.detect.silence.{n_db,d}`, `qc.sync.tol_start_ms`, `.tol_dur_ms`, `.tol_sub_ms`, `qc.duration.tol_ms`; keys that 18 §13 does not list are kept in this agent's family: `agent_10.qc.scene_threshold`, `agent_10.qc.cfr_tolerance_s`, `agent_10.qc.hook_first_payoff_ms`; `ops.market_windows`, `ops.night_window`, `drain.grace_ms` (owner: 06_NIGHT_SCHEDULING.md, not yet written: `ops.*` is provisional here until that document and the 18 §13 registry declare it; `drain.grace_ms` exists in 07 §8); `limits.max_atomic_write_ms` for the render worker. Unset required key → `PERMANENT.CONFIG_INVALID`, the worker does not claim.

### 24.3 Health checks
| Check | Type | Passes when |
|---|---|---|
| liveness | process | the worker loop heartbeats the queue lease |
| readiness | dependency | DB reachable under `amw_app` with a probe transaction for a random org returning 0 rows; storage reachable; scratch writable and cleaned; `ffmpeg` and `ffprobe` present, the build ID equals the pinned one, required filters exist (`blackdetect`, `freezedetect`, `silencedetect`, `ebur128`, `select`, `showinfo`, `tile`, `drawtext` with text shaping); the self-test record for this build ID exists and passed (R-02); the Devanagari shaping fixture renders; required config keys set; `AdmissionProbe` answers; the worker's cgroup limits are present (INF-03, INF-04, proved by test 27 §9 on the VPS) |
| provider | not applicable | no provider |
A failed readiness check means the worker does not claim Agent 10 tasks.

### 24.4 Start and stop order
Start: database (migrations only by the deploy step) → storage → orchestrator and queue functions → shared services (S4 cost guard, audit) → render worker. Stop: stop claiming; finish the current atomic unit; checkpoint; release the lease; exit; then workers → services → orchestrator → database. The service stop timeout must exceed `limits.max_atomic_write_ms` (07 §8.3); on the VPS the stop signal arrives at 07:00 and the worker has already drained from 06:30.

### 24.5 Release and rollback
The FFmpeg build is part of the image; a build change re-runs R-02 and is part of the release (segment keys include the build ID, so no stale segment is reused across builds, DC-20). An engine or configuration change re-runs R-01. Rollback is the previous image and configuration; blobs are write-once and unaffected; a rolled-back worker refuses segments of an unknown build ID only by key mismatch (they are simply not reused).

---

## 25 Acceptance criteria
**MVP: 3A · Tier 0. Each criterion is testable and names its test. Pass = all green in CI (no paid call) and, for E-tests, the owner-authorised pilot.**

| # | Criterion | Test |
|---|---|---|
| A-01 | the final MP4 of a synthetic project passes the checks of §20.1 rows 11–22, 37, 59 and 60 (1920×1080 High 4:2:0, CFR equal to the project rate, bitrate band, AAC-LC 48 kHz stereo at a configured nominal ≥ 384 kbps, true peak ≤ −1 dBTP, duration within one frame, colour tags and GOP settings as configured) | IT-01, IT-03, R-02 |
| A-02 | output frame count equals the compiled frame count; the same inputs give the same timeline bytes and SHA-256 | U-17…U-26, a10.q.timeline_frames, R-01 |
| A-03 | killing FFmpeg or the worker mid-render and resuming yields a file byte-identical to an uninterrupted run, with only the interrupted segment re-encoded | FI-01, FI-02, FI-03 |
| A-04 | a drained render resumes in the next window without redoing finished segments | FI-04 |
| A-05 | a replay creates no second `renders` row, no second final blob, no second cost row | FI-05 |
| A-06 | no `HEAVY_CPU` unit of the three tasks starts inside a market window on any placement and a running unit checkpoints before the next window (`act_by`); on the VPS (disabled in 3A) none outside 00:00–07:00 or after the drain point `07:00 − drain.grace`; no new unit after the drain flag | FI-08, FI-09, FI-13, U-11…U-16, U-233, U-234, 27 §9 test 6 |
| A-07 | a missing or unparseable measurement is never `PASS` | U-62…U-70, FI-06 |
| A-08 | every check of the profile has a persisted `qc_results` row; a profile check without a result makes the gate `FAILED` | IT-03, U-98…U-100 |
| A-09 | each blocking check fails on its fail fixture and passes on its pass fixture; each fixture of the self-test yields its asserted verdict | U-110…U-225, R-02 |
| A-10 | a shot without an asset, an element without a covering active licence, an expired licence, an unknown monetisation field, an inactive asset and an AI item without `AI_OUTPUT` each fail the gate with the shot ID in `failures[]` | U-186, U-187 (row 39 fixtures), DC-63…DC-68, DC-95…DC-98, IT-03 |
| A-11 | tier E at exactly 50 % of visual frames fails; below passes | DC-53, DC-54 |
| A-12 | the SRT is UTF-8, numbered, ordered, non-overlapping, its text equals the script, its first/last cue match the segment edges and its last cue ends no later than the video | U-84…U-96, U-176, U-177, `a10.sub.*` |
| A-13 | the 9:16 cut renders with the `shorts_9x16` preset and `qc.shorts` in the `SHORTS` v2 child job when requested | IT-05 |
| A-14 | no outbound connection, no LLM call, no provider cost, no secret on the worker | S-09, U-102 |
| A-15 | tenant isolation: all five layers (§19.1) and the permission matrix | S-01…S-08 |
| A-16 | no render, QC or log line contains script text, subtitle text or paths | S-05 |
| A-17 | a failed gate returns `gate: true` FAIL results with `remedy_stage_id` and `failures[]` with check ID, shot IDs, measured, threshold and `remedy_stage`; the task stays `SUCCEEDED` | IT-03, U-98…U-101 |
| A-18 | movability: the same image on another placement renders the same SHA-256 | IT-07 |
| A-19 | every function of §10 has the listed tests and every gate `check_id` of §20.1 (`qc.*`, `edit.*`) has a `RemedyMapper` entry | C-08, coverage report |

---

## 26 Prompt and evaluation pack
**MVP: 3A · 3B (thresholds recalibrated on the golden samples) · Tier 0.**

### 26.1 Statement
Agent 10 has **no LLM step** (§5). It therefore has **no prompt file** (nothing is created under `prompts/agent_10_video_editor/`) and **no judged dataset or judge rubric**. As the engineering standard allows (27 §6, and as `agent_09.timeline_engine` does for its deterministic part), the evaluation pack is a **deterministic golden dataset**: input fixture description plus exact expected result, run by the eval gate at no cost.

### 26.2 Paths
| Item | Path |
|---|---|
| Prompt files | none |
| Deterministic golden dataset | `docs/v4/evals/agent_10_video_editor/deterministic_core/` — `README.md` (scope, reference rules, assertions T1–T6, thresholds), `cases.jsonl` (120 cases: POSITIVE 36, HARD_NEGATIVE 53, EDGE 31; function-level format of 27 §6.1, component prefix `DC-`, no `judge_min`), `rubric.md` (statement: no judge) |
| Media-level self-test | lavfi fixtures of 18 §7.11, specified in §21 R-02 (generated at test time, no stored media) |
| Judged datasets for checks that touch Agent 10's files | Agent 16's pack (`qc.watermark.visual`, `qc.visual.no_synthetic_presenter`, `edit.promise_alignment`) |

### 26.3 Deterministic checks and assertions
T1 exact equality of every expected value; T2 tiling invariant; T3 zero FFmpeg, network and LLM calls on error cases; T4 determinism (same input twice, same output); T5 no text or paths in outputs beyond the case's own fixtures; T6 a missing or unparseable measurement is never `PASS` (README §4). Check evaluators are the same functions as production (F-36), so a case failing is a defect of the function.

### 26.4 Pass thresholds (config `evals.agent_10.deterministic_core.*`)
| Threshold | Value |
|---|---|
| Overall case pass rate | 100 % |
| Error cases returning the expected code with zero tool calls | 100 % |
| R-02 self-test fixtures returning their asserted verdicts on the pinned build | 100 % |
| Cost and latency | no model, no media process for R-01; recorded latency only |
CI fails the PR if any threshold is missed.

### 26.5 Coverage summary
| Area | Cases |
|---|---|
| Frame grid, timeline, hash | DC-01…DC-13 (13) |
| Segments and keys | DC-14…DC-20 (7) |
| Subtitles (incl. sync rule, `UNALIGNED` refusal) | DC-21…DC-32, DC-99…DC-101, DC-114 (16) |
| Parsers | DC-33…DC-39 (7) |
| Check evaluators and gate | DC-40…DC-85, DC-95…DC-98, DC-102…DC-104, DC-115…DC-118, DC-120 (58) |
| Heavy-work guard and self-drain | DC-86…DC-94, DC-105…DC-108 (13) |
| Reveal steps, upstream gate | DC-109…DC-113, DC-119 (6) |
Hard negatives cover each safety rule: no render in market hours, no silent default for missing measurements, no unlicensed or unknown-licence shot, no repair of a bad plan, no merging of a too-short cue, no reuse of a segment across FFmpeg builds, no estimated plan, no AI video without a limit, no inactive asset.

### 26.6 Revisit
After the 3B pilot: replace test values by the calibrated configuration in the cases that use `calibrated`/tolerance fields (the cases state them explicitly, so only expected values at boundaries change), add one case per detector parameter promoted from WARN to blocking, and add the music-bed cases for D6 once a source exists. Any change of a decision rule in §6 changes the dataset in the same PR.
