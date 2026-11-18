# Agent 09 — Video Director (blueprint)

| Field | Value |
|---|---|
| Status | Draft — documentation, aligned with the contract register pass 1 (CONTRACT_CHANGE_REQUESTS.md §5 "Resolved for blueprint 09"). Software: **Planned** (rule 6, rule 7) |
| Owner | Agent 09 Video Director; integration owner: Agent 01 (orchestrator) |
| Package | `agent_09_video_director` (27 §7.2); prompt: `prompts/agent_09_video_director/shot_direction.v1.md` (one LLM step, §5); evals `evals/agent_09_video_director/shot_direction/` (LLM step, judged) and `evals/agent_09_video_director/timeline_engine/` (deterministic engine), §26 |
| Directive sections covered | §3.1 row 09 (scene/shot plan, timeline, cinematic editing intelligence: pacing, B-roll, music, transitions), §1A.1 (visual hierarchy: planning side), §1A.2 (retention-driven edit rules), §1A.8 (formats, brand sting after the hook, 9:16 cut plan), §1A.11 (AI B-roll is budgeted), §1A.4 and §1A.6 (planning side of the music bed, dead air and licence-per-shot), §1B.2 (finance content rules as they touch pictures), §3.3 (contracts, failures, quality, observability, AI providers), §3.5 (prompt, eval and code standards), §4 (26 sections) |
| Owner decisions applied | D1 (3A production line with Agents 04–11 and the Agent 16 gates; topic owner-given; outputs are files: MP4 16:9 (+ 9:16 where applicable), thumbnail options, SRT, QC report with the 100-point score, cost per stage; no YouTube upload, no Google OAuth; paid calls only inside owner-set provider limits; per-video and pilot budgets enforced by the cost ledger, stop on breach; keys only through the environment's secret mechanism; render never in market hours), D2 (full blueprint for 3A agents; `REQUIRES REVIEW` does not block 3A unless it changes a 3A design decision) |
| Binding contracts | GLOSSARY_AND_IDS.md (§2 IDs, §3 units, §6.6, §6.19–6.20, §6.27–6.31, §6.37–6.38, §6.44–6.45, §6.50–6.52), 03_COMMUNICATION_STANDARD.md (§3–§9, §11), 04_DATABASE_ARCHITECTURE.md (§3, §5.7, §5.9, §5.10, §5.11, §5.12, §5.13, §5.14), 07_FAILURE_MANAGEMENT.md (§2–§4, §8–§10), 24_PRODUCTION_TYPES.md §3.2 (`agent_09.shot_plan`), §3.3 (gates, revision routing), §5, §7.1, §7.1a, §7.2a (`s09_plan`), 27_ENGINEERING_STANDARDS.md (§3–§8, §9) |
| Shared docs referenced by name/§ only | 18_PRODUCTION_QUALITY_STANDARD.md (§2 hierarchy and licence record, §3 retention criteria, §9.2 rubric, §10 formats, §13 config keys), 13_COMPLIANCE_YOUTUBE_POLICY.md (FIN-R rules, §3.3 disclosure), 09_COST_AND_BUDGET.md (§3, §8, §10), 08_SECURITY.md (§3 secrets, §5.3 permissions, §8 tenant isolation), 3A_SLICE_SPEC.md (§2.4, §3, item 3A-08, 3A-15), ADR-007 (LLM routing), ADR-009 (visual and music sourcing), ADR-012 (render placement), agent_05_scriptwriter.md (script document), agent_06_fact_checker.md (stage verdict), agent_07_voice_production.md (narration timeline), agent_08 prompts (`search_query_plan.v1`, `candidate_rank.v1`: consumers of this plan) |
| Facts cited | RESEARCH_LOG PR-01 (model tiers and prices), PR-02 (batch and prompt caching), INF-03 / INF-04 (resource caps), INF-09 (FFmpeg `blackdetect`, `freezedetect`, `silencedetect`), INF-11 (RLS), IN-02 / IN-03 (SEBI data lag and forward-looking bar), YT-06 / YT-07 (synthetic-media disclosure), YT-09 (no AI persona on finance) |
| Marking | Every section states its **MVP** in the first line: 3A / 3B / 3C (owner build stages of D1) and Tier 0–3 (GLOSSARY §6.47) |
| Conventions | Every contract name used here is a real name of the merged contracts (the former provisional names are decided in the register; none remains open). `REQUIRES REVIEW (Phase 1): <need>` = unknown value; none is invented. A value called **PROPOSAL** is a design default of this document (no source, calibrated in 3B), not a fact. Config keys are registered by this blueprint's §24.2 in `amw_core.config` (CCR-019). Payload-local value sets (for example `intent_kind`, `interrupt_device`, `framing`) are defined only inside this agent's own payload schemas (GLOSSARY §6.52 pattern, as in agent_05 and agent_08) and are not shared enums. No book text, private method or server detail appears here. No dates or clock times appear in rules (owner rule C.4); the only time-based values are operational config and millisecond positions on the video's own timeline. Check IDs `a09.*` are owned by this blueprint and listed in §20 (CCR-020); 18 IDs (`edit.*`, `qc.*`) are cited as they are and never invented. |

---

## 1 Identity and mission
**MVP: 3A (task `agent_09.shot_plan`, all deterministic engines, one LLM step, 16:9 plan and the 9:16 plan for the child job; no music) · 3B (thresholds, pacing profile, interrupt windows and J/L values calibrated on the golden samples; owner look-and-feel scores; the music-bed cue and ducking range, gated on the owner's licensed-source decision, D6, CCR-007) · 3C (SFX cue plan with a licensed library, parent-shot reuse tuning, other production types). Tier 0 designed for Tier 1+.**

### 1.1 Mission
Agent 09 is the director and the editor's plan. It turns a verified script and the measured narration into the **shot plan**: an exact, millisecond-timed list of what is on screen at every moment of the video, how it changes, where the pattern interrupts, J/L cuts, brand sting, chapters and end screen fall, and what kind of picture every shot needs. It does one job on one script version (`agent_09.shot_plan`, stage `s09_plan`):

1. **Build the timing skeleton by code.** From the narration timeline (Agent 07) and the script's scenes (Agent 05) it computes the shot slots so that a visual change happens at least every 3–5 s in explanatory stretches (§1A.2), the hook is covered inside the first 30 s with no logo or channel intro, pattern interrupts sit at the first drop-off zone and the midpoint, J/L cuts are placed on sentence boundaries, the brand sting starts only after the hook, chapters follow the script's sections, and a reserved end-screen segment closes the video (18 §3).
2. **Direct each slot with one LLM step** (`shot_direction`): the model proposes, per slot, what the camera should see (a filmable description in plain words), the framing and motion, which interrupt device to use when the slot is an interrupt, and which text from the script appears on screen. It never chooses times, counts, sources, licences or compliance outcomes.
3. **Validate and assemble by code.** Every model proposal passes deterministic guards (finance-safe imagery, no real identifiable person, no invented on-screen text, tier budgets, vocabulary). A rejected proposal is re-asked once, then replaced by a code-made fallback that is always renderable. The final plan is checked against 24 deterministic checks (§20) and written once.
4. **Plan the 9:16 cut** as a re-edit: for the Shorts child job (a separate script from `agent_05.shorts_adaptation`, which has `scenes[]` and no `sections[]`) it plans vertical framing per shot; it is never a crop of the 16:9 plan (18 §10).

The plan is the contract between four neighbours: Agent 08 sources one asset per shot (in the hierarchy order of §1A.1), Agent 10 renders and measures it, Agent 11 reads it for thumbnail subjects, and Agent 16 scores and gates it.

### 1.2 Where it sits
Stage `s09_plan` (class `AI_IO`, queue `ai`, capability `llm`; 24 §3.1, §7.1). In the 24 graphs (§7.1, §7.1a `CHANNEL_LONG_FORM` v2, §7.2a `SHORTS` v2) it depends on `s06_verify` **and `s07_voice`** (CCR-003: the plan is timed on the measured narration; there is no estimated-timing mode, CCR-051). In the 3A flow: `s06_verify` → (`a_script`) → `s07_voice` → **`s09_plan`** → `s08_assets` → `s06_chart` → `s10_render` (`s07_master` runs beside the plan); `s11_thumbs` reads the plan and the sourced assets. The stage is the REVISE target of `s08_assets` (unresolved plan-fixable shots), of `s16_score`, and an `alt_target_stage_ids` entry of `s10_qc`; `a_final` `CHANGES_REQUESTED` may name it (24 §3.3 rules 1 and 3). Each revision is a new iteration (new idempotency key) with the failing results as feedback and the previous iteration's plan as a `PRIOR_OUTPUT` context ref (24 §3.3 rule 6, CCR-008; FR-17). A new iteration of `s07_voice` re-runs this stage too, as a dependent (24 §3.3 rule 1). The Shorts child job (created after the parent's `s06_verify`) runs the same stage on the child script with `aspect_ratio = 9:16`.

### 1.3 Authority boundaries
| Agent 09 **decides** | Agent 09 **does not decide** (owner of the decision) |
|---|---|
| shot boundaries, durations, order, transitions and the J/L offsets on the video timeline | the narration, its wording, pace and emotion, or the sentence timing (Agent 05, Agent 07); Agent 09 reads the timeline and never moves a sentence |
| what kind of picture each shot needs (`intent_kind`), a filmable description, framing, motion, and which tiers the shot may use | which asset fills a shot, the source, price and licence (Agent 08; the hierarchy order is enforced in Agent 08's code, ADR-009 §2.1) |
| where the pattern interrupts, brand sting, chapter cards, lower-thirds and the end-screen segment sit | whether the finished video is compliant or may be delivered (Agent 16; S7 human approval) |
| the worst-case share of `E_AI_STILL` and the AI-video seconds the plan *allows* (planning side of §1A.1e and §1A.11) | the budget amounts and the spend itself (S4; owner sets the amounts, rule 8); the real tier mix of the render (Agent 08 result, Agent 10 measurement) |
| the proposed chapter list from the script's sections and the measured section starts | the chapter text published on a destination (Agent 12, 3C) |
| the music-bed cue and the ducking range it asks for (3B) | which track is used and its licence (Agent 08, `music_search`, `MUSIC_BED` ledger rows) and the mix (Agent 07, `s07_master`) |
| the plan-side picture guards (no direction imagery, no AI presenter, no real identifiable person, no invented text) | the narration's legality (Agent 06/16); Agent 09's guards are a second line, never the first |
It never creates tasks, never approves, never edits the script or a budget row, never downloads, generates or licenses media, never renders, never calls YouTube (zero quota units), never uploads (D1), and never sends anything to the LLM provider except the sanitised slot data of one tenant (§11, §19).

### 1.4 Success criteria (measurable; targets are config and are set in 3B)
| ID | Criterion | Measure |
|---|---|---|
| SC-1 | Every moment of the video has exactly one planned main-track shot | 100 % tiling: first shot starts at 0 ms, each shot starts where the previous ends, last shot ends at `content_end_ms` (`a09.q.tiling`, blocking) |
| SC-2 | Visual change at least every 3–5 s in explanatory stretches | max gap between change events ≤ `qc.visual.max_change_gap_ms` (5 000 ms, directive; the one source of the limit, 18 §13) in 100 % of explanatory stretches; exemptions listed with a reason and inside `agent_09.held.max_ms` (`a09.q.cadence`, mirrors `edit.visual.cadence`) |
| SC-3 | Hook inside the first 30 s with no logo, channel intro or sting before it ends | hook end ≤ `qc.hook.window_ms`; 0 brand elements starting before hook end (`a09.q.hook_window`, `a09.q.hook_no_brand`; `edit.hook.*`); for 9:16 the hook is the `SHORT_HOOK` beats |
| SC-4 | Pattern interrupts at the first drop-off zone and around the midpoint | ≥ 1 interrupt in each window once the windows are set; until then ≥ 1 in each script-planned scene (`a09.q.interrupt_first`, `a09.q.interrupt_mid`) |
| SC-5 | J/L cuts present at the configured rate; chapters (long form) and end screen present | `a09.q.jl`, `a09.q.chapters` (`SKIPPED` for 9:16), `a09.q.end_screen` |
| SC-6 | Visual hierarchy respected in the plan | worst-case planned `E_AI_STILL` share < `qc.visual.tier_e_max_share` (0.50); allowed AI-video ms ≤ budget; 0 shots without a code-made fallback (`a09.q.tier_plan`) |
| SC-7 | No picture or text the rules forbid enters the plan | 0 shots with direction imagery, market-data screens, AI presenter, real identifiable person, brand/logo; 0 on-screen words not taken from the script (`a09.q.visual_guard`, `a09.q.text_provenance`; mandatory test thresholds, §26) |
| SC-8 | The plan is reproducible | same inputs, same model outputs ⇒ same plan SHA-256 (`a09.q.determinism`); replay creates no second paid call |
| SC-9 | No cross-tenant read or write; no script or narration text in any log | 0 occurrences in the tenancy and log-leak suites |
| SC-10 | LLM cost per plan stays within `resource_budget` | 0 breaches; breach ⇒ suspend (09, D1) |
| SC-11 | The owner finds the pictures relevant and the rhythm natural on the pilot set | HUMAN rows of VISUAL_QUALITY and EDITING_QUALITY (18 §9.2), 3B mandatory |

---

## 2 Functional requirements
**MVP: 3A for every row unless marked · Tier 0. Trigger of the task: the orchestrator creates it when `s07_voice` and `s06_verify` are `COMPLETED` (03 §11; 24 §7.1a, §7.2a).**

### 2.1 Requirements
| ID | Requirement | Why (rule) | When | Inputs | Outputs | Dependants | MVP |
|---|---|---|---|---|---|---|---|
| FR-01 | Validate the Task Input and tenant context: schema, ID prefixes, org equality across envelope, input, context refs and payload refs; refuse unsupported `aspect_ratio` / production-type pairs | rule 9; 03 §7 | first step | Task Input | pass or `PERMANENT.*` | all | 3A |
| FR-02 | **Script gate**: the script blob hash equals the hash the verification stage saw (`agent_06.claim_verification.output` `script_sha256`, copied by the orchestrator into `verification_ref.verified_script_sha256`, CCR-049), and the stage verdict (`overall.proposed_verdict`) is `ALLOWED` (or `NEEDS_HUMAN_REVIEW` with the linked `SENSITIVE_CLAIM` approval `APPROVED`); the same gate runs for the Shorts child script (its `s06_verify`, 24 §7.2a); no plan on an unchecked or blocked script | §1B.2; the plan must show what Agents 06/16 judged | before any model call | script ref + SHA-256, Agent 06 output ref, approval ref | pass or `PERMANENT.INPUT_INVALID` | 08, 10, 16 | 3A |
| FR-03 | **Narration time map**: load the narration timeline (`agent_07.voice_synthesis.output` `timeline`), verify it covers every script segment exactly once, in order, without overlap, with an integer `start_ms`/`end_ms` for every segment, and build the `TimeMap` (segment → start/end); a timeline with `source = UNALIGNED` or any null time is refused `PERMANENT.INPUT_INVALID` `TIMELINE_UNALIGNED` (in 3A it never arrives: it is refused at `s07_voice`, CCR-051; the check is the second line) | §1A.2: cadence and hook are measured on real audio | after FR-02 | narration timeline ref + SHA-256 | `TimeMap` | FR-05…FR-13 | 3A |
| FR-04 | **Hook analysis**: find the hook segments (`HOOK_PROOF`, `HOOK_WHY`, `HOOK_COVERS`; for 9:16 the `SHORT_HOOK` segments), hook end, first payoff time; fail the task with `INPUT_INVALID` when the hook ends after `qc.hook.window_ms` | §1A.2 hook = first 30 s | after FR-03 | `TimeMap`, script segments | `HookInfo` | FR-05, FR-09, 05 (revise) | 3A |
| FR-05 | **Slot grid**: per scene compute the number and boundaries of shots from the cadence limits, the pacing profile of the scene's beat, the script's `change_beats` and sentence boundaries (§6.2); held and chart scenes get change events inside one shot | §1A.2 visual change every 3–5 s | after FR-04 | `TimeMap`, scenes, config | slot list | FR-06…FR-08 | 3A |
| FR-06 | **Chart shots**: for every script `chart_request` plan one `CHART` shot covering its scene, with reveal steps as change events; chart content is never described by the model | §1A.1c; FIN-R9, FIN-R13 (data and framing are Agent 08/10/16) | with FR-05 | `chart_requests`, scenes | chart slots (not sent to the model) | 08 | 3A |
| FR-07 | **Pattern-interrupt placement**: ensure ≥ 1 interrupt slot in the first-drop-off window and in the midpoint window; honour the script's planned interrupts; the model chooses the device, code guarantees presence | §1A.2 | after FR-05 | slots, windows, script interrupts | slot roles | FR-08 | 3A |
| FR-08 | **Shot direction (LLM)**: send the slots in batches; receive per slot kind, description, framing, motion, device, text IDs, depiction flags; parse into the Pydantic model; never best-effort parse | §3.5.2 | after FR-07 | slot batches, rule packs | `Direction` per slot | FR-09 | 3A |
| FR-09 | **Guards and repair**: lexical and flag guards on every direction (§6.5); one re-ask per failing batch; then the code-made fallback shot (`C_CODE_MOTION` template; always renderable, no invented text) | rule 5 (no loops), §1B.2, YT-09 | after FR-08 | directions | accepted directions | FR-10 | 3A |
| FR-10 | **Assembly**: transitions, J/L cut offsets, overlays (lower-thirds and caption cards from script text only, chapter cards, disclaimer card), brand sting **after** the hook, end-screen segment | §1A.2, §1A.8 | after FR-09 | accepted directions, brand kit | shots, overlays | FR-11…FR-14 | 3A |
| FR-11 | **Tier plan**: `allowed_tiers` per shot in hierarchy order; planned worst-case `E_AI_STILL` share and AI-video seconds inside the limits; a code-made fallback per shot | §1A.1, §1A.11 | with FR-10 | directions flags, config, budgets | tier fields, `tier_budget` | 08, 16 | 3A |
| FR-12 | **Chapters** from the script's sections with measured starts (first at 0 ms, strictly increasing); a Shorts script has no sections, so `chapters = []` and the check is `SKIPPED` | §1A.2 chapters | with FR-10 | sections, `TimeMap` | `chapters[]` | 10, 12 (3C) | 3A |
| FR-13 | **Audio cue plan**: in 3A no music bed and no SFX (`bed = NONE`); in 3B, when `limits.music_library_enabled` (the owner's licensed-source decision, D6, CCR-007), a bed request `REQUESTED` with the ducking range of 18 §5 (−20.0…−15.0 dB; Agent 08 sources the track, Agent 07 mixes it); SFX cues for interrupts only when a licensed SFX library is enabled (3C); never an unlicensed cue | §1A.4, ADR-009, D6 | with FR-10 | config, `limits`, interrupts | `audio_plan` | 08, 07, 10 | 3A (none) · 3B (music bed) · 3C (SFX) |
| FR-14 | **Vertical plan** (`aspect_ratio = 9:16`): anchor and safe-area class per shot, vertical template variants for overlays, parent-shot reuse mapping (nullable) | §1A.8; 18 §10 | for the Shorts child job | child script, optional parent plan (`parent_plan_ref`) | `vertical` per shot | 08, 10 | 3A (plan) · 3B (reuse tuning) |
| FR-15 | **Validation battery** (§20) and Task Output: `SUCCEEDED` only when every `blocking: true` result is `PASS` (03 §5.3.2); a result that cannot be computed or is `WARN` is emitted `SKIPPED`/`WARN` with `blocking: false` (CCR-001); this stage is not a gate, so no result carries `gate: true`; the plan blob is written once | §3.3 Quality | last step | all above | plan blob, `validation_results` | 01, 16 | 3A |
| FR-16 | **Rebase** the previous plan to a changed narration timeline (pure function, shot IDs kept) — runs inside this task at iteration ≥ 1 when the narration timeline hash differs from the previous plan's `narration_timeline_sha256` (a new `s07_voice` iteration re-runs this stage as a dependent); never called by another agent, never a substitute for the measured timeline (CCR-051) | NFR-2, 24 §3.3 | iteration ≥ 1 | `previous_plan_ref`, new timeline | rebased plan (start point of FR-17) | 16 | 3A |
| FR-17 | **Revision iteration**: on `REVISE → s09_plan` take the failing check IDs and shot IDs as `revision_feedback`, read the previous plan from `previous_plan_ref` (`PRIOR_OUTPUT`, 24 §3.3 rule 6; no `TASK` memory read), keep shot IDs of untouched shots stable, change only what the feedback names, and report `a09.q.revision_addressed` | 24 §3.3 rules 1, 6 | iteration ≥ 1 | `revision_feedback[]`, `previous_plan_ref` | new plan | 16 | 3A |
| FR-18 | **Cost and audit**: check before every call that the task's `resource_budget` and the S4 reservation made for the job at task creation (3A_SLICE_SPEC §3 rule 1) cover the worst case; the agent draws on that reservation and never opens a second hold; one ledger row per call, audit rows for start, completion and failure | rule 8, D1 | throughout | `resource_budget`, S4 | ledger, audit | S4, 16 | 3A |
| FR-19 | **Checkpoint and resume** after the skeleton, after each accepted batch and after assembly; a kill never repeats a completed LLM call | 07 §10 | throughout | — | `checkpoints` rows | 01 | 3A |
| FR-20 | **Hand-off views** for neighbours: the Agent 08 shot list, the Agent 11 subject list and the Agent 16 realism list are views of the same plan (no second source of truth); item schemas in §8.1 | rule 5 | at output | plan | views inside the payload | 08, 11, 16 | 3A |

### 2.2 Triggers and non-triggers
| Trigger | Result |
|---|---|
| Task `agent_09.shot_plan` created by the orchestrator (`source_agent = agent_01`) | executes FR-01…FR-20 |
| `s16_score` REVISE to `s09_plan` | new iteration, new idempotency key (03 §9.2 `task.agent_09.shot_plan` with `iteration`) |
| New `s07_voice` iteration | orchestrator re-runs the stage as a dependent (new iteration, 24 §3.3 rule 1); FR-16 keeps shot IDs |
| DRAIN control | finish the in-flight call, checkpoint, release the lease (`CHECKPOINTED` / `DRAIN`) |
No other trigger. The package has no scheduler, no HTTP server and no public port.

---

## 3 Non-functional requirements
**MVP: 3A for every row unless marked · Tier 0. Numbers are design defaults (ESTIMATE / PROPOSAL) or `REQUIRES REVIEW`; none is a measured fact.**

| ID | Requirement | Target / rule | Verified by | MVP |
|---|---|---|---|---|
| NFR-1 | Determinism of the engine | the skeleton, assembly and checks are pure functions: same input, same config, same accepted directions ⇒ byte-identical plan (canonical JSON, sorted keys) apart from the provenance block | U-19…U-26, TE dataset, `a09.q.determinism` | 3A |
| NFR-2 | Idempotency | one LLM call per (`task_id`, `step_key = "direction.bNN"`, `call_seq`) (03 §9.2 `llm.call`; the batch is part of the step key, nothing is added to the 03 key); DLQ replay creates no second call or ledger row; the plan blob is write-once (`db.output`) | FI-03, FI-09 | 3A |
| NFR-3 | Cost safety | no model call without a reservation covering `max_output_tokens` worst case, an `ACTIVE` provider budget row and a closed breaker (09 §8, ADR-007 §2.8); zero network calls otherwise | FI-05…FI-07 | 3A |
| NFR-4 | Tenant isolation | §19; every DB access in a tenant transaction; every URI org-checked; every cache key org-scoped | tenancy and security suites | 3A |
| NFR-5 | No content or secrets in logs | no narration text, `intent_text`, on-screen text or key in any log, metric label, error or audit row (counts, IDs, hashes only; 27 §7.3.6) | S-05 | 3A |
| NFR-6 | Resumability | resume from the latest checkpoint without repeating an accepted batch; no half-written blob at a final path | FI-10, FI-11 | 3A |
| NFR-7 | Wall time | one LLM call per batch (sequential, concurrency from config) plus milliseconds of local compute; budget `resource_budget.max_wall_ms` set from measurement | **REQUIRES REVIEW (Phase 1): MEASURED in the 3A skeleton** | 3B |
| NFR-8 | Resource class | `AI_IO`: low CPU, no FFmpeg, no media decoding, no render; runs in the AI worker at any time; honours `DRAIN` (24 §3.1, GLOSSARY §6.6) | acceptance 27 §9 test 4 | 3A |
| NFR-9 | Output size | the payload carries the summary and views and stays inside `contracts.inline_payload_max_bytes` (03 §3.3); the plan blob is an `output_refs` entry (`kind = DATA`); arithmetic: ≈ one shot per 3–5 s ⇒ ≈ 120–200 shots per 10 minutes; at a few hundred bytes of JSON per shot the blob is of the order of 100 kB (arithmetic, not measured) | P-02 | 3A |
| NFR-10 | Configurability | models, tiers, limits, windows, offsets, templates and caps are config (rule 5); no literal in code or prompt | config lint | 3A |
| NFR-11 | Language | scripts in `mr-IN`, `hi-IN`, `en-IN` (agent_05); `intent_text` is English (stock queries are English, agent_08 prompt); on-screen text stays in the script's language and is only referenced | `a09.q.text_provenance`, U-92 | 3A |
| NFR-12 | Provider portability | the LLM sits behind the `LlmAdapter` Protocol (ADR-007); no provider or model name in code or prompt | contract test | 3A |
| NFR-13 | Reports are numbers first | the plan's report block shows measured values versus thresholds per check, no colour-only meaning (owner rule D.2) | report fixture review | 3A |
| NFR-14 | Bounded loops | at most `agent_09.llm.max_repairs_per_batch` re-asks per batch (design default 1, 27 §7.3.2), at most `agent_09.max_slots` slots (a per-agent structural cap declared here, 07 §9 row of CCR-022 → `AGENT.LOOP_CAP_EXCEEDED`, checked before any paid call), hard caps of 07 §9 apply | FI-08 | 3A |

---

## 4 Internal architecture
**MVP: 3A · Tier 0. The task runs as library code inside `workers/ai_worker` (SOURCE_LAYOUT); no HTTP server, no public port, no FFmpeg.**

### 4.1 Task flow
```mermaid
flowchart TD
  IN["Task Input (03 §7 validated)"] --> P1["P1 TenantScope: org, channel, refs under RLS"]
  P1 --> P2["P2 ScriptGate: script SHA-256 = verified SHA-256, stage verdict allows"]
  P2 --> P3["P3 NarrationTimeline: load, verify coverage, build TimeMap"]
  P3 --> P4["P4 HookAnalyzer: hook end at most window, else INPUT_INVALID"]
  P4 --> P5["P5 SlotGrid + ChartPlanner: slots tile 0 to content end"]
  P5 --> P6["P6 InterruptPlacer: windows, script-planned interrupts, slot roles"]
  P6 --> G1{"budget row ACTIVE, reservation covers worst case, breaker not OPEN"}
  G1 -- "no" --> SUS["SUSPENDED AWAITING_BUDGET or NO-ATTEMPT CIRCUIT_OPEN (no network call)"]
  G1 -- "yes" --> P7["P7 Direction loop per batch: render prompt, LLM call, parse, VisualGuard"]
  P7 --> R{"guards pass?"}
  R -- "no, repair left" --> P7
  R -- "no, repairs used" --> FB["FallbackBuilder: code-made C_CODE_MOTION shot"]
  R -- "yes" --> P8
  FB --> P8["P8 Assembly: transitions, J/L, overlays, brand sting after hook, end screen, chapters"]
  P8 --> P9["P9 TierPlanner + AudioCuePlanner + VerticalPlanner"]
  P9 --> P10["P10 PlanChecks (24 checks) + hash, write-once blobs, Task Output"]
  SUS -. "resume from checkpoint" .-> P7
  DR["DRAIN control"] -.-> P7
  P5 -. "checkpoint" .-> CK[("checkpoints")]
  P7 -. "checkpoint per accepted batch" .-> CK
  P8 -. "checkpoint" .-> CK
```

### 4.2 Interaction with neighbours (one stage, one direction of data)
```mermaid
sequenceDiagram
  participant O as Orchestrator (01)
  participant A as Agent 09 (ai_worker)
  participant C as amw_core (tenancy, S4 cost, audit, storage)
  participant L as LlmAdapter (ADR-007)
  participant N as Agent 08 / 10 / 11 / 16
  O->>A: Task Input agent_09.shot_plan (script ref, narration timeline ref, brand kit ref)
  A->>C: open tenant transaction, verify refs and SHA-256
  A->>A: gate, time map, hook, slot grid, interrupt roles (pure code)
  A->>C: check budget row and the job's reservation (worst case)
  loop per batch of slots
    A->>L: shot_direction.v1 (one tenant, sanitised slots)
    L-->>A: JSON (schema checked)
    A->>C: ledger row, checkpoint
  end
  A->>A: guards, fallback, assembly, 24 checks
  A->>C: write plan blob once, audit, Task Output
  A-->>O: SUCCEEDED + plan ref and SHA-256
  O->>N: s08_assets reads the plan; s10_render compiles the timeline; s11 and s16 read views
```

### 4.3 Components and boundaries
| Component | Responsibility | Talks to |
|---|---|---|
| `TenantScope` | one place that checks org, channel and URI ownership; opens tenant transactions via `amw_core.tenancy` | DB, storage |
| `InputValidator`, `ScriptGate` | schema, ID prefixes, hash and verdict gate (deterministic, before any model call) | DB (RLS), storage |
| `NarrationTimeline` (`TimeMap`) | load and verify the narration timeline; segment ↔ ms | storage |
| `HookAnalyzer`, `PacingProfile`, `SlotGrid`, `ChartPlanner`, `InterruptPlacer` | the timing skeleton (pure functions) | config |
| `DirectionBatcher`, `PromptRenderer`, `DirectionClient` (over `LlmAdapter`), `DirectionParser` | the one LLM step | adapter, S4 cost module, breaker |
| `VisualGuard`, `InjectionScanner`, `DirectionRepair`, `FallbackBuilder` | accept, re-ask or replace a direction | config, rule-pack text |
| `TransitionPlanner`, `JlPlanner`, `OverlayPlanner`, `EndScreenPlanner`, `ChapterBuilder`, `TierPlanner`, `AudioCuePlanner`, `VerticalPlanner` | deterministic assembly | brand kit, config |
| `PlanAssembler`, `PlanChecks` | final plan, `validation_results` | — |
| `PlanWriter`, `CheckpointStore`, `MemoryAccess`, `ErrorMapper` | persistence, resume, error mapping | DB, storage |
Dependency rule (27 §7.1): the package imports `amw_core` and the `LlmAdapter` Protocol only; the concrete adapter is injected by the worker. No package imports another agent; hand-offs are contracts only.

---

## 5 Full system prompt
**MVP: 3A (prompt v1 released for the pilot after the eval gate) · 3B (tuning on the golden samples; any change is `v2`) · Tier 0. Agent 09 has exactly one LLM step.**

| Item | Value |
|---|---|
| Step | `shot_direction` of task type `agent_09.shot_plan` (step-level prompt; the task type is unchanged, same pattern as `agent_08/search_query_plan.v1`) |
| Prompt file (real text) | [`prompts/agent_09_video_director/shot_direction.v1.md`](../prompts/agent_09_video_director/shot_direction.v1.md), written to `prompts/_TEMPLATE.v1.md` (27 §4.2: Role, Objective, Inputs, Rules, Output JSON Schema, Worked examples, Refusal and escalation, Self-check) |
| Prompt ID | `agent_09/shot_direction.v1` |
| Input / output schemas | `agent_09.shot_plan.direction.input` 1.0.0 / `agent_09.shot_plan.direction.output` 1.0.0 (§7.3, §8.3; both JSON Schemas are in the prompt file, sections "A. Input payload schema" and "Output JSON Schema"; generated from the Pydantic models and compared in CI, 27 §4.4; the evals validate every case input against the input schema, 27 §6.1) |
| Rule packs by reference | `rp.youtube_general` (always), `rp.finance_sebi_in` (when active for the channel; platform scope, before the cache breakpoint); `rp.tenant_brand_safety` (when the tenant defines it; TENANT scope, injected **after** the cache breakpoint, CCR-025); text resolved at runtime, version recorded per call |
| Config keys | `llm.agent_09.shot_plan.direction.model_tier`, `.temperature`, `.max_output_tokens`, `.timeout_ms`, `.cost_budget_micros`, `.cache_system_prompt`, `.batch_eligible`, `.fallback_tier` (family `llm.<task_type>.<step>.*`, registered by CCR-019). Model IDs are never in the prompt or code (ADR-007 §2.3). `step_key` of the idempotent call: `direction.bNN` (03 §9.2 `llm.call`). |

**What the prompt makes the model do (summary).** The model is the *picture-direction step* of a video production pipeline for an education channel. For each slot it is given (a time slot already fixed by code, the narration sentences that fall in it, the script's own visual intent, the text options the script allows on screen, the allowed interrupt devices), it returns one direction: a status (`OK` / `NO_SAFE_VISUAL`), a kind of picture (`FOOTAGE`, `DIAGRAM`, `TEXT_CARD`; `CHART` slots are never sent), a one-sentence filmable description in English, framing, motion, whether a still image with motion would be acceptable, whether only AI video could serve, an interrupt device where the slot demands one, text IDs chosen from the options, depiction flags, and for 9:16 a subject anchor. It never chooses times, counts, sources, tiers or licences, never writes on-screen words, never judges compliance, and treats all slot text as data, not instructions.

**What is not in the prompt.** Timing and cadence (code), the hierarchy order and asset choice (Agent 08), budgets (S4), compliance outcomes (Agents 06/16), model names, provider names, dates and clock times (owner rule C.4).

**Prompt-injection posture.** Slot data (narration excerpts, script visual-intent text, text options) are rendered between `<<<INPUT` and `INPUT>>>` markers and declared as data; the output is a schema-validated object with closed enums, so an injected instruction can only produce a rejected field, never an action (§19.3).

---

## 6 Decision engine
**MVP: 3A · Tier 0. Rule of the blueprint: everything that can be computed is computed by code; the model is used only where a picture has to be imagined from words (27 §7.3.7).**

### 6.1 What is deterministic, what is LLM, and why
| Decision | Made by | Why |
|---|---|---|
| tenant, hash, verdict gates, schema | code | safety and tenancy must never depend on a model |
| segment times, hook end, scene spans | code (`TimeMap`) | measured on real audio; arithmetic |
| number and boundaries of shots, change events, held-shot exemptions | code (`SlotGrid`) | the 3–5 s rule is a measurable limit (18 `edit.visual.cadence`); a model would drift |
| chart shots and reveal steps | code (`ChartPlanner`) | charts come from code and real data (§1A.1c); the model never describes data |
| where the interrupts sit, brand sting start, end screen, chapters | code | positions are measurable windows (18 §3) |
| J/L offsets and which boundaries get them | code (`JlPlanner`) | rule-based on sentence boundaries; models cannot see audio |
| transitions allowed, durations, bans (no dip to black) | code (`TransitionPlanner`) | `blackdetect` / `freezedetect` QC (INF-09) must not fire |
| tier permissions, planned E share, AI-video seconds | code (`TierPlanner`) | budget and hierarchy rules (§1A.1, §1A.11) |
| **what the picture shows** (filmable description), framing, motion, interrupt device, which allowed on-screen text to use | **LLM** (`shot_direction`) | creative judgement from words to a picture; the only step that needs language understanding |
| accept, re-ask or replace a direction | code (`VisualGuard`, `DirectionRepair`, `FallbackBuilder`) | guards are lexical and flag tests; the model never audits itself |
| final approval of the video and of the plan's look | human (owner at `FINAL_VIDEO`; 3B scores) | §1A.7 |

### 6.2 `SlotGrid.build` (the algorithm, so that tests can recompute it)
Per scene, in order. Notation: all times in integer ms, `round_half_up`.
1. **Span.** `t0` = start of the scene's first segment (0 for the first scene); `t1` = start of the next scene's first segment (`content_end_ms` for the last scene); `D = t1 − t0`. Pauses and gaps of the narration timeline are inside `D`, so shots tile without holes.
2. **Limits.** `g_min = agent_09.cadence.min_gap_ms` (3 000, directive), `g_max = qc.visual.max_change_gap_ms − agent_09.cadence.safety_margin_ms` (5 000 − margin; `qc.visual.max_change_gap_ms` is the one source of the limit, 18 §13; margin **REQUIRES REVIEW (Phase 1): calibrate in 3B**, unset = 0), `g_target` from the pacing profile of the scene's beat (§6.3).
3. **Count.** `n_min = ceil(D / g_max)`; `n_tgt = round_half_up(D / g_target)`; `n_cap = max(1, floor(D / g_min))`; `n = max(n_min, min(n_tgt, n_cap))`. The hard limit `g_max` always wins over the 3 s floor (a 5.002 s scene gets two 2.501 s shots).
4. **Boundaries.** `b_k = t0 + round_half_up(k·D / n)` for `k = 1…n−1`.
5. **Snap.** For each `b_k` take the nearest sentence boundary within `agent_09.snap.tolerance_ms` (ties: earlier); accept it only if both neighbouring slots then lie inside `[agent_09.snap.min_slot_ms, g_max]`, else keep `b_k`.
6. **Script floor.** If the script's `change_beats` exceeds `n` and `D / change_beats ≥ g_min`, raise `n` to `change_beats` (the script's intent is a minimum, never ignored when feasible).
7. **Chart and held scenes.** A scene with a `chart_id` becomes one `CHART` shot with `m = max(change_beats, ceil(D / g_max))` reveal steps; change events at `t0 + round_half_up(j·D / m)`, `j = 1…m−1`. A scene with `explanatory = false` and no chart becomes one held shot; it is exempt from cadence only with a reason and only up to `agent_09.held.max_ms` (**REQUIRES REVIEW (Phase 1): exemption length, calibrate in 3B**; unset = no exemption, so the engine splits it like an explanatory scene).
8. **Disclaimer segments** (`kind = DISCLAIMER`) become a `TEXT_CARD` slot whose span is at least the segment's narration span; its text comes from the disclaimer template (FIN-R10 wording is Agent 05/13's).

### 6.3 Pacing profile (cinematic pacing)
`PacingProfile.target_gap(beat, role) -> ms`: a table in config keyed by the script scene `beat` and slot role. Defaults derive from the directive's window: `explain` = midpoint of 3 000–5 000 = 4 000 (arithmetic), `hook` = `agent_09.pacing.hook_gap_ms` (default = `g_min`, because the hook is where retention is decided), `recap` = `explain`. Values are overridable per channel through CHANNEL memory (§14) after the owner approves an experiment (3C). Unset keys fall back to the directive's window; nothing is invented.

### 6.4 Interrupts, J/L cuts, transitions, brand sting
1. **Windows.** `W1` = first drop-off window (`agent_09.interrupt.first_dropoff.start_ms/end_ms`, **REQUIRES REVIEW (Phase 1): 19 niche benchmarks, then retention data (YT-14)**); `W2` = `[0.5·content_end − h, 0.5·content_end + h]`, `h = agent_09.interrupt.midpoint.half_width_ms` (**REQUIRES REVIEW (Phase 1): calibrate in 3B**). A slot is an interrupt when the script marks its scene (`interrupt` non-null) or when it is chosen for a window. For 9:16 the midpoint window and the "scene holding the midpoint" fallback use `scenes[]` (no sections).
2. **Choice.** For each window without an interrupt slot, pick the slot whose centre is nearest the window centre (ties: earlier) and set its role `INTERRUPT_REQUIRED`. While a window is unset, only script-planned interrupts exist and the check is emitted `WARN` with `blocking: false` (18: WARN until set; CCR-001).
3. **Device.** The model picks `interrupt_device` ∈ {`CUTAWAY_BROLL`, `GRAPHIC`, `ZOOM`, `SOUND_CUE`, `ANGLE_CHANGE`} (§1A.2 list) from the `allowed_devices` of the slot (`SOUND_CUE` only when a licensed SFX library is enabled; none in 3A). If the answer is missing or not allowed, code sets `ZOOM` with `motion = PUNCH_IN` (always renderable).
4. **Distinct from its neighbour.** An interrupt must differ from the preceding shot in kind or framing, or be a `ZOOM`/`PUNCH_IN` of the same shot's picture (check `a09.q.interrupt_*`).
5. **J/L.** Eligible boundaries are sentence-aligned scene or section boundaries that are not the hook end, not adjacent to a `DISCLAIMER` segment, not at a shot with `intent_kind = CHART` whose first narrated segment starts at that boundary for a J-cut (the chart must be visible when it is discussed; L is used instead). Eligible boundary number `k` (from 1) with `k mod agent_09.jl.every_nth = 0` gets the next cut in the alternation J, L, J, L… with offset `agent_09.jl.offset_ms`: a **J-cut** moves the visual cut to `B + offset` (the next sentence is heard while the old picture is still up), an **L-cut** to `B − offset` (the new picture appears while the previous sentence finishes). The shift is applied only if both neighbouring shots stay within `[snap.min_slot_ms, g_max]`; otherwise the boundary stays a straight cut with reason `GAP_LIMIT`. Defaults **PROPOSAL (no source; calibrate in 3B): `agent_09.jl.offset_ms = 400`, `agent_09.jl.every_nth = 2`**; 18 `edit.cuts.j_l` is `WARN` until the rate is set.
6. **Transitions.** Allowed kinds: `CUT`, `CROSS_DISSOLVE`, `PUSH`, `ZOOM_THROUGH`; never a dip to black. This is a design rule of this plan, not a claim about the detector: 18 §7.3 lets a deliberate black fade of a few frames pass, but the plan keeps `deliberate_black` empty (§8.1) so that any black detection (`qc.video.black_frames`, INF-09) is a defect to see. Default `CUT`; `CROSS_DISSOLVE` at a section boundary without a J/L shift; a model `transition_hint` is honoured only when it is in the allowed set and its duration ≤ `agent_09.transition.max_ms` and ≤ 20 % of the shorter neighbour (**REQUIRES REVIEW (Phase 1): max duration**; unset = `CUT` only).
7. **Brand sting.** Only when the brand kit has `intro_ref`; placed on track V2 starting exactly at `hook_end_ms`, never earlier (§1A.8, `edit.hook.no_brand_intro`); duration = the template's, capped by `agent_09.sting.max_ms` (**REQUIRES REVIEW (Phase 1): cap**). No logo, channel name or intro element is planned before `hook_end_ms`, and the first shot starts at 0 ms.

### 6.5 Guards on every model direction (`VisualGuard`; any hit rejects the direction)
| Guard | Rule | Source |
|---|---|---|
| G1 vocabulary | `intent_text` ≤ `max_intent_chars`, English only (no Devanagari), no digits, no URLs, no names of people, brands, companies, products, instruments, indices or tickers, no `banned_subjects` word | Agent 08 query rules (the plan feeds them) |
| G2 flags | `real_person`, `identifiable_person`, `brand_or_logo` all false; `ai_presenter` false (FIN-R11, YT-09); `market_data_screen` false; on a finance channel `market_direction_imagery` false | §1A.1, §1B.2, FIN-R11, 18 §2.3 |
| G3 text provenance | every `text_ids[]` entry exists in the slot's `text_options`; the plan carries IDs and resolved script strings, never model-written words | rule: no text the script did not carry |
| G4 capability | `needs_ai_video` only when `ai_video_allowed`; `still_ok` only when `still_allowed`; `interrupt_device` ∈ `allowed_devices` | §1A.11, ADR-009 §6 |
| G5 kind | `intent_kind` ≠ `CHART`; `NO_SAFE_VISUAL` carries a `reason_code` and no description | design |
| G6 injection | no instruction-like phrase, no echo of an instruction found in the input | §19.3 |
| G7 realism | `realistic_event_depiction` is a flag for Agent 16's disclosure decision (13 §3.3, YT-06/07): it never blocks, it is recorded | disclosure input |
A rejected direction is re-asked once per batch with the guard messages (IDs only, no content); a still rejected slot gets the `FallbackBuilder` shot: a brand-kit abstract motion template (`C_CODE_MOTION`), or a `TEXT_CARD` made from a script text option when one exists; never invented words.

### 6.6 Tier plan (`TierPlanner`)
`allowed_tiers` per shot, always in hierarchy order and always ending with a tier-C fallback: `FOOTAGE` → `[A_OWNER_REAL, B_LICENSED_STOCK, C_CODE_MOTION]`; `CHART` / `DIAGRAM` / `TEXT_CARD` → `[C_CODE_MOTION]` (a code-rendered chart from real data is tier C with `assets.kind = CHART`, CCR-045; `A_OWNER_REAL` is not listed for charts). `D_AI_VIDEO` is appended only for `needs_ai_video` slots when `agent_09.tier.d_enabled` is true (3A default false, ADR-009 §6) and the running total of allowed D milliseconds stays ≤ `agent_09.tier.d_max_ms` (derived from the S4 per-video AI-B-roll budget; **REQUIRES REVIEW (Phase 1): owner sets the budget**). `E_AI_STILL` is appended for `still_ok` slots in time order while the running worst-case share stays ≤ `qc.visual.tier_e_max_share × agent_09.tier.e_plan_fraction` (unset fraction = tier E not allowed). Granting stops when the budget is used; later slots keep tiers A–C. The planned worst-case shares are written to `tier_budget`.

### 6.7 Revision logic
Iteration ≥ 1: the previous plan (shot IDs, content keys, accepted directions) is read from `previous_plan_ref`, a `PRIOR_OUTPUT` context ref set by the orchestrator (24 §3.3 rule 6, CCR-008; hash verified, same org); no `TASK` memory is read. If the narration timeline hash differs from the previous plan's, FR-16 first rebases the previous plan. Shots not named in `revision_feedback[].shot_ids` keep ID, direction and timing (unless the timeline hash changed); named shots are re-directed with the feedback check IDs as hints (IDs and numbers only). `a09.q.revision_addressed` verifies that every feedback item is no longer violated by the new plan. A feedback item with no `shot_ids` (a whole-plan result) re-directs no shot by itself: it is checked against the new plan's measured values only.

### 6.8 Failure to plan
If a blocking check cannot pass after the allowed repairs: input-caused (hook after the window, timeline gap) → `PERMANENT.INPUT_INVALID` with `details.violations[]` (orchestrator re-plans upstream, L2); agent-caused → `AGENT.QUALITY_REPEATED_FAILURE` (L3). A partial plan is never returned as success (03 §5.3).

---

## 7 Input schema
**MVP: 3A · Tier 0. Task Input is the 03 §3 envelope; this section defines `payload` of `agent_09.shot_plan.input` 1.0.0 and the step input of the LLM step.**

### 7.1 Task Input mapping (03 §3.1)
| Field | Value for this task |
|---|---|
| `agent_id` / `source_agent` | `agent_09` / `agent_01` |
| `channel_id` | required (owner channel); null only for client types without a channel (3C) |
| `context_refs` | `PRIOR_OUTPUT` (script document, Agent 06 verification output, narration timeline, and at iteration ≥ 1 this stage's previous plan, 24 §3.3 rule 6), `BRAND_KIT`, `COMPLIANCE_PROFILE`, `RULE_PACK` (one per active pack), `APPROVAL` (when the verdict is `NEEDS_HUMAN_REVIEW`), `MEMORY` (channel pacing overrides, 3C); each with SHA-256, schema, version |
| `resource_budget` | `max_cost_micros`, `max_llm_calls`, `max_tokens_in/out`, `max_wall_ms`; no render fields |
| `idempotency_key` | scope `task.agent_09.shot_plan` (`job_id`, task type, `iteration`) |
| `payload` | `{payload_schema: "agent_09.shot_plan.input", payload_schema_version: "1.0.0", data}` |

### 7.2 Payload `agent_09.shot_plan.input` 1.0.0
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:amw:schema:agent_09.shot_plan.input:1.0.0",
  "type": "object", "additionalProperties": false,
  "required": ["production_type_key", "aspect_ratio", "script_ref", "verification_ref", "narration_timeline_ref", "brand_kit_ref",
               "channel_category", "active_rule_packs", "iteration", "previous_plan_ref"],
  "$defs": {
    "hashed_ref": { "type": "object", "additionalProperties": false, "required": ["uri", "sha256"],
      "properties": { "uri": { "$ref": "urn:amw:schema:amw.common:1.0.0#/$defs/storage_uri" },
                      "sha256": { "$ref": "urn:amw:schema:amw.common:1.0.0#/$defs/sha256_hex" } } }
  },
  "properties": {
    "production_type_key": { "enum": ["CHANNEL_LONG_FORM", "SHORTS"] },
    "aspect_ratio": { "enum": ["16:9", "9:16"], "description": "9:16 only for SHORTS, 16:9 only for CHANNEL_LONG_FORM" },
    "script_ref": { "type": "object", "additionalProperties": false, "required": ["script_id", "version", "uri", "sha256"],
      "properties": { "script_id": { "type": "string", "pattern": "^scr_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$" }, "version": { "type": "integer", "minimum": 1 },
                      "uri": { "$ref": "urn:amw:schema:amw.common:1.0.0#/$defs/storage_uri" },
                      "sha256": { "$ref": "urn:amw:schema:amw.common:1.0.0#/$defs/sha256_hex" } } },
    "verification_ref": { "type": "object", "additionalProperties": false, "required": ["uri", "sha256", "verified_script_sha256", "stage_verdict"],
      "properties": { "uri": { "$ref": "urn:amw:schema:amw.common:1.0.0#/$defs/storage_uri" },
                      "sha256": { "$ref": "urn:amw:schema:amw.common:1.0.0#/$defs/sha256_hex" },
                      "verified_script_sha256": { "$ref": "urn:amw:schema:amw.common:1.0.0#/$defs/sha256_hex" },
                      "stage_verdict": { "enum": ["ALLOWED", "NEEDS_HUMAN_REVIEW"] },
                      "approval_id": { "type": ["string", "null"], "pattern": "^apr_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$" } },
      "description": "built by the orchestrator from agent_06.claim_verification.output of s06_verify: verified_script_sha256 = script_sha256, stage_verdict = overall.proposed_verdict (CCR-049); a BLOCKED verdict never reaches this task" },
    "narration_timeline_ref": { "$ref": "#/$defs/hashed_ref", "description": "the narration timeline of agent_07.voice_synthesis.output (timeline_uri, timeline_sha256); required, there is no estimated-timing mode (CCR-051)" },
    "brand_kit_ref": { "$ref": "#/$defs/hashed_ref", "description": "amw-entity:// URI of the current brand_kits row with the SHA-256 of its canonical JSON" },
    "channel_category": { "type": "string", "maxLength": 40 },
    "active_rule_packs": { "type": "array", "items": { "type": "string", "pattern": "^rp\\.[a-z0-9_]{2,40}$" }, "minItems": 1 },
    "parent_plan_ref": { "oneOf": [ { "type": "null" }, { "$ref": "#/$defs/hashed_ref" } ], "description": "SHORTS child job only: the parent job's plan; used for the nullable parent_shot_id mapping" },
    "iteration": { "type": "integer", "minimum": 0 },
    "previous_plan_ref": { "oneOf": [ { "type": "null" }, { "$ref": "#/$defs/hashed_ref" } ],
      "description": "PRIOR_OUTPUT of this stage's previous iteration (24 §3.3 rule 6); null exactly when iteration = 0" },
    "revision_feedback": { "type": "array", "maxItems": 64, "items": { "type": "object", "additionalProperties": false,
      "required": ["check_id", "severity", "shot_ids", "measured", "threshold"],
      "properties": { "check_id": { "type": "string", "pattern": "^[a-z0-9_.-]{3,96}$" }, "severity": { "enum": ["BLOCKING", "WARNING"] },
                      "source_stage_id": { "type": "string", "pattern": "^[as][0-9a-z_]{2,24}$" },
                      "shot_ids": { "type": "array", "items": { "type": "string", "pattern": "^sh[0-9]{2,4}$" } },
                      "measured": { "type": ["number", "null"] }, "threshold": { "type": ["number", "null"] } } } },
    "limits": { "type": "object", "additionalProperties": false,
      "properties": { "ai_video_allowed_ms": { "type": "integer", "minimum": 0 }, "ai_still_allowed": { "type": "boolean" },
                      "sfx_library_enabled": { "type": "boolean" }, "music_library_enabled": { "type": "boolean" } },
      "description": "copied by the orchestrator from S4 budgets and capability config; absent = not allowed" }
  },
  "allOf": [
    { "if": { "properties": { "production_type_key": { "const": "SHORTS" } } },
      "then": { "properties": { "aspect_ratio": { "const": "9:16" } } },
      "else": { "properties": { "aspect_ratio": { "const": "16:9" }, "parent_plan_ref": { "type": "null" } } } },
    { "if": { "properties": { "iteration": { "const": 0 } } },
      "then": { "properties": { "previous_plan_ref": { "type": "null" } } },
      "else": { "properties": { "previous_plan_ref": { "$ref": "#/$defs/hashed_ref" } } } }
  ]
}
```
Fields **read from the referenced script document** (agent_05 §8.3): `sections[]`, `scenes[]` (`scene_id`, `section_id`, `beat`, `segment_ids`, `on_screen_text[]`, `visual_intent {tier_hint, description, change_beats}`, `interrupt`, `deliberate_pause_ms`, `explanatory`, `chart_id`, `method_label`), `segments[]` (`segment_id`, `kind`, `text`, `scene_id`, `chart_ref`), `chart_requests[]`, `chapters[]`, `disclaimer_slots[]`, `language`. A Shorts script (agent_05 §8.4) has `scenes[]` and no `sections[]`; its hook segments are `SHORT_HOOK` and its segments may carry `parent_segment_ids[]`. **Read from the narration timeline** (agent_07 §8 `timeline`): `source` (`PROVIDER_CLIPS` or `OWNER_MARKS`; `UNALIGNED` is refused), per segment `segment_id`, `start_ms`, `end_ms`; the stem duration. **Read from the brand kit**: `lower_third_template_ref`, `intro_ref`, `outro_ref`, `banned_words`, `tone_rules` (04 §5.12).

### 7.3 Step input `agent_09.shot_plan.direction.input` 1.0.0 (assembled by code, never by the model)
The JSON Schema of this step input is section "A. Input payload schema" of the prompt file (single source; the evals validate every case input against it, 27 §6.1; CI compares it with the Pydantic model, 27 §4.4).
| Variable | Type | Source |
|---|---|---|
| `batch_id` | `bNN` | `DirectionBatcher` |
| `language` | BCP 47 of the script | script |
| `channel_category` | string | channel record |
| `aspect_ratio` | `16:9` / `9:16` | payload |
| `banned_subjects` | array of short strings | brand kit `banned_words` and compliance profile |
| `limits` | `{max_intent_chars, max_rationale_chars}` | config `agent_09.llm.*` |
| `capabilities` | `{ai_video_allowed, still_allowed, sound_cue_available}` | payload `limits` and config |
| `previous_tail` | up to 2 `{slot_id, intent_kind, framing}` of the previous batch | accepted directions |
| `slots` | array of `{slot_id (slNN), scene_id, section_kind (agent_05 value or null for a Shorts script), role (HOOK / EXPLAIN / RECAP / INTERRUPT_REQUIRED / SECTION_OPENER), duration_ms, narration_excerpt, scene_visual_intent {tier_hint, description}, text_options[{text_id, text}], allowed_devices[]}` | skeleton + script |
`narration_excerpt` is the text of the sentences overlapping the slot (the only narration the model sees). Chart, disclaimer and fallback slots are never in `slots`.

### 7.4 Validation order (03 §7)
Schema and `schema_version` → ID prefixes → org equality (envelope, input, context refs, payload refs) → refs resolve under the tenant and their SHA-256 matches → `ScriptGate` → timeline coverage (`TIMELINE_UNALIGNED` / `TIMELINE_INCOMPLETE`) → config completeness → budget and reservation check. Each failure maps to a code of §18 before any model call. These preconditions are reported as non-scored `a09.pre.*` results (§20.1).

---

## 8 Output schema
**MVP: 3A · Tier 0. Task Output is the 03 §5 envelope: `status`, `payload` (below), `output_refs` (plan blob, `kind = DATA`, SHA-256), `quality_score = null`, `confidence = null`, `validation_results` (§20; none with `gate: true`, because `s09_plan` is not a gate stage, 03 §5.3 rule 4), `resource_usage` (tokens, calls, cost entry IDs), `next_action`, `downstream_agent = agent_08`.**

### 8.1 Payload `agent_09.shot_plan.output` 1.0.0
Top-level fields (the full plan lives in the blob; the payload carries the summary and the views, or the plan itself when below `contracts.inline_payload_max_bytes`, 03 §3.3):
| Field | Type | Meaning |
|---|---|---|
| `plan_ref` | `{uri, sha256, schema: "agent_09.shot_plan.output", schema_version: "1.0.0"}` | write-once plan blob (`jobs/<job>/tasks/<task>/attempts/<att>/output.json` area, 03 §8); the same four fields are what Agent 08's `shot_plan_ref` requires, so the orchestrator copies it unchanged |
| `script_id`, `script_version`, `script_sha256`, `language`, `aspect_ratio`, `iteration` | values | identity |
| `timing_basis` | const `MEASURED` | Agent 10 requires it; there is no estimated mode (CCR-051) |
| `narration_timeline_sha256` | hex | the timeline the plan was timed on |
| `content_end_ms`, `total_duration_ms` | integers | narration end; total including the end-screen segment |
| `hook` | `{start_ms: 0, end_ms, first_payoff_ms, segment_ids[]}` | hook window facts; 16:9: `first_payoff_ms` = end of `HOOK_PROOF`; 9:16: hook = the `SHORT_HOOK` beats and `first_payoff_ms` = `end_ms` |
| `shots[]` | §8.2 | main visual track V1, tiling `[0, content_end_ms]` |
| `overlays[]` | §8.2 | track V2: brand sting, lower-thirds, caption cards, chapter cards, end screen |
| `audio_plan` | `{music: {bed: NONE / REQUESTED, start_ms, end_ms, offset_db_range: [-20.0, -15.0] (18 §5), asset_hint: null}, sfx_cues[], deliberate_pauses[{start_ms, end_ms, reason}]}` | 3A: `bed = NONE`, `sfx_cues = []`, `start_ms`/`end_ms` null. 3B with `limits.music_library_enabled`: `bed = REQUESTED`, span `[0, total_duration_ms]` (**PROPOSAL**, calibrated on the golden samples); the track is Agent 08's, the mix Agent 07's. SFX stays 3C |
| `chapters[]` | `{section_id, start_ms, title_local}` | first at 0, strictly increasing; `[]` for 9:16 |
| `deliberate_hold[]` | `{start_ms, end_ms, shot_id, reason}` | one entry per shot with `held` non-null (`reason` = `held.reason`); read by Agent 10 for `qc.video.freeze` (18 §7.8); names exactly as 18 |
| `deliberate_black[]` | `[]` | always empty: the plan has no dip to black; read by Agent 10 for `qc.video.black_frames` (18 §7.3) |
| `interrupts[]` | `{shot_id, device, window: FIRST_DROPOFF / MIDPOINT / SCRIPT_PLANNED}` | summary |
| `jl_cuts[]` | `{boundary_ms, kind: J / L, offset_ms, from_shot_id, to_shot_id}` and skipped boundaries with `reason` | summary |
| `tier_budget` | `{worst_case_e_share_permille, e_limit_permille, ai_video_allowed_ms, ai_video_limit_ms}` | planning side of 18 §2.3 |
| `views` | `{agent_08_shots[], agent_11_subjects[], agent_16_realism[]}` | FR-20; item schemas in §8.1.1 |
| `stats` | `{slot_count, llm_slot_count, fallback_count, repaired_count, change_events_total, max_gap_ms, min_gap_ms}` | numbers first |
| `refusal` | null or the 27 §4.3 object | last step-level refusal that degraded a batch (declared mapping, §8.4) |
| `provenance` | `{prompt_id, prompt_sha256, rule_pack_versions, config_key_families, calls[{step_key, provider, model, tokens_in, tokens_out, tokens_cached_in, cost_entry_id}]}` | not part of the determinism hash |

### 8.1.1 View items (payload-local; `$defs` of `urn:amw:schema:agent_09.shot_plan.output:1.0.0`)
```json
{
  "agent_08_shot": { "type": "object", "additionalProperties": false,
    "required": ["shot_id", "scene_id", "start_ms", "end_ms", "duration_ms", "aspect_ratio", "tier_hint", "intent_kind", "intent_text", "on_screen_text",
                 "chart_id", "allowed_tiers", "fallback_template_key", "content_key", "allows_hold", "change_events_ms", "vertical_anchor",
                 "realistic_event_depiction", "parent_shot_id"],
    "properties": { "shot_id": { "type": "string", "pattern": "^sh[0-9]{2,4}$" }, "scene_id": { "type": "string" },
      "start_ms": { "type": "integer", "minimum": 0 }, "end_ms": { "type": "integer", "minimum": 1 }, "duration_ms": { "type": "integer", "minimum": 1 },
      "aspect_ratio": { "enum": ["16:9", "9:16"] }, "tier_hint": { "enum": ["A_OWNER_REAL", "B_LICENSED_STOCK", "C_CODE_MOTION", "D_AI_VIDEO"] },
      "intent_kind": { "enum": ["FOOTAGE", "CHART", "DIAGRAM", "TEXT_CARD"] }, "intent_text": { "type": "string", "maxLength": 240 },
      "on_screen_text": { "type": "array", "items": { "type": "string" }, "description": "resolved from text_refs (script strings)" },
      "chart_id": { "type": ["string", "null"] }, "allowed_tiers": { "type": "array", "items": { "type": "string" }, "minItems": 1 },
      "fallback_template_key": { "type": "string" }, "content_key": { "type": "string", "pattern": "^[0-9a-f]{64}$" },
      "allows_hold": { "type": "boolean", "description": "held is non-null" }, "change_events_ms": { "type": "array", "items": { "type": "integer" } },
      "vertical_anchor": { "enum": [null, "CENTER", "UPPER_THIRD", "LOWER_THIRD", "LEFT", "RIGHT"] },
      "realistic_event_depiction": { "type": "boolean" }, "parent_shot_id": { "type": ["string", "null"] } } },
  "agent_11_subject": { "type": "object", "additionalProperties": false, "required": ["hint_id", "shot_id", "shot_role", "intent_text", "framing"],
    "properties": { "hint_id": { "type": "string", "pattern": "^hn[0-9]{2}$" }, "shot_id": { "type": "string", "pattern": "^sh[0-9]{2,4}$" },
      "shot_role": { "enum": ["HOOK", "PROOF"] }, "intent_text": { "type": "string", "maxLength": 240 },
      "framing": { "enum": ["WIDE", "MEDIUM", "CLOSE_UP", "DETAIL", "TOP_DOWN", "NONE"] } } },
  "agent_16_realism": { "type": "object", "additionalProperties": false, "required": ["shot_id", "realistic_event_depiction", "schematic", "origin", "refusal_reason"],
    "properties": { "shot_id": { "type": "string", "pattern": "^sh[0-9]{2,4}$" }, "realistic_event_depiction": { "type": "boolean" }, "schematic": { "type": "boolean" },
      "origin": { "enum": ["MODEL", "REPAIRED", "FALLBACK", "CODE_CHART", "CODE_DISCLAIMER"] },
      "refusal_reason": { "enum": [null, "RULE_WOULD_BE_BROKEN", "UNSAFE_CONTENT"], "description": "set when the shot is a fallback because its batch was refused (§8.4)" } } }
}
```
`agent_11_subjects[]` holds at most 4 items: the hook shot(s) (`shot_role = HOOK`) and the shot(s) of the first payoff beat (`PROOF`; for 9:16 the same as the hook), `hint_id` = `hn01…` in time order. The Agent 08 view lists exactly the fields Agent 08's `ShotPlanReader` consumes (agent_08 §7, FR-02); both lists are views of the shot objects and may not differ from them (contract test C-05).

### 8.2 Shot and overlay objects (payload-local field names; 18 §2.2 asks this blueprint to fix them)
```json
{
  "$comment": "$defs/shot of urn:amw:schema:agent_09.shot_plan.output:1.0.0",
  "type": "object", "additionalProperties": false,
  "required": ["shot_id", "seq", "scene_id", "section_id", "start_ms", "end_ms", "duration_ms", "segment_ids", "intent_kind",
               "intent_text", "framing", "motion", "allowed_tiers", "tier_hint", "fallback_template_key", "explanatory", "held",
               "change_events_ms", "interrupt", "transition_in", "cut_offset_ms", "jl_kind", "chart_id", "text_refs",
               "depiction", "origin", "content_key", "vertical", "parent_shot_id"],
  "properties": {
    "shot_id": { "type": "string", "pattern": "^sh[0-9]{2,4}$" },
    "seq": { "type": "integer", "minimum": 1 },
    "scene_id": { "type": "string" }, "section_id": { "type": ["string", "null"], "description": "null for a Shorts script (no sections)" },
    "start_ms": { "type": "integer", "minimum": 0 }, "end_ms": { "type": "integer", "minimum": 1 }, "duration_ms": { "type": "integer", "minimum": 1 },
    "segment_ids": { "type": "array", "items": { "type": "string", "pattern": "^s[0-9]{1,4}$" } },
    "intent_kind": { "enum": ["FOOTAGE", "CHART", "DIAGRAM", "TEXT_CARD"] },
    "intent_text": { "type": "string", "maxLength": 240, "description": "English, filmable, no digits/names; empty for CHART" },
    "framing": { "enum": ["WIDE", "MEDIUM", "CLOSE_UP", "DETAIL", "TOP_DOWN", "NONE"] },
    "motion": { "enum": ["STATIC", "SLOW_PUSH_IN", "SLOW_PULL_OUT", "PAN_LEFT", "PAN_RIGHT", "PUNCH_IN"] },
    "allowed_tiers": { "type": "array", "items": { "enum": ["A_OWNER_REAL", "B_LICENSED_STOCK", "C_CODE_MOTION", "D_AI_VIDEO", "E_AI_STILL"] }, "minItems": 1 },
    "tier_hint": { "enum": ["A_OWNER_REAL", "B_LICENSED_STOCK", "C_CODE_MOTION", "D_AI_VIDEO"], "description": "from the script scene" },
    "fallback_template_key": { "type": "string", "description": "brand-kit or platform template key, tier C, always renderable" },
    "explanatory": { "type": "boolean" },
    "held": { "oneOf": [ { "type": "null" }, { "type": "object", "additionalProperties": false, "required": ["reason", "max_ms"],
                         "properties": { "reason": { "enum": ["CHART_REVEAL", "DELIBERATE_PAUSE", "DISCLAIMER", "SCRIPT_NON_EXPLANATORY"] }, "max_ms": { "type": "integer" } } } ] },
    "change_events_ms": { "type": "array", "items": { "type": "integer" }, "description": "internal change events (keyframes, chart steps), absolute ms, strictly inside the shot" },
    "interrupt": { "oneOf": [ { "type": "null" }, { "type": "object", "additionalProperties": false, "required": ["device", "window"],
                  "properties": { "device": { "enum": ["CUTAWAY_BROLL", "GRAPHIC", "ZOOM", "SOUND_CUE", "ANGLE_CHANGE"] }, "window": { "enum": ["FIRST_DROPOFF", "MIDPOINT", "SCRIPT_PLANNED"] } } } ] },
    "transition_in": { "type": "object", "additionalProperties": false, "required": ["kind", "duration_ms"],
                       "properties": { "kind": { "enum": ["CUT", "CROSS_DISSOLVE", "PUSH", "ZOOM_THROUGH"] }, "duration_ms": { "type": "integer", "minimum": 0 } } },
    "cut_offset_ms": { "type": "integer", "description": "signed distance of this shot's start from the sentence boundary; > 0 J-cut, < 0 L-cut, 0 straight" },
    "jl_kind": { "enum": ["J", "L", null] },
    "chart_id": { "type": ["string", "null"], "pattern": "^chart_[0-9a-z_]{1,32}$" },
    "text_refs": { "type": "array", "items": { "oneOf": [
                   { "type": "object", "additionalProperties": false, "required": ["scene_id", "index", "sha256"],
                     "properties": { "scene_id": { "type": "string" }, "index": { "type": "integer", "minimum": 0 }, "sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" } } },
                   { "type": "object", "additionalProperties": false, "required": ["disclaimer_slot_id", "sha256"],
                     "properties": { "disclaimer_slot_id": { "type": "string" }, "sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" } } } ] },
                   "description": "script on_screen_text by scene and index, or a disclaimer slot (agent_05 §8.3 slot_id, text_sha256); never free text" },
    "depiction": { "type": "object", "additionalProperties": false, "required": ["realistic_event_depiction", "schematic"],
                   "properties": { "realistic_event_depiction": { "type": "boolean" }, "schematic": { "type": "boolean" } } },
    "origin": { "enum": ["MODEL", "REPAIRED", "FALLBACK", "CODE_CHART", "CODE_DISCLAIMER"] },
    "content_key": { "type": "string", "pattern": "^[0-9a-f]{64}$", "description": "sha256 of scene_id, slot ordinal, intent_text; lets Agent 08 reuse across iterations" },
    "vertical": { "oneOf": [ { "type": "null" }, { "type": "object", "additionalProperties": false, "required": ["subject_anchor", "safe_area_class"],
                  "properties": { "subject_anchor": { "enum": ["CENTER", "UPPER_THIRD", "LOWER_THIRD", "LEFT", "RIGHT"] }, "safe_area_class": { "enum": ["DEFAULT"] } } } ] },
    "parent_shot_id": { "type": ["string", "null"], "pattern": "^sh[0-9]{2,4}$" }
  }
}
```
`overlays[]` item: `{overlay_id (ov01…), kind: BRAND_STING / LOWER_THIRD / CAPTION_CARD / CHAPTER_CARD / DISCLAIMER_CARD / END_SCREEN, start_ms, end_ms, template_ref (or null), text_refs[], vertical_variant: bool}`; every `text_refs` entry points to a script string by `scene_id`, `index` and SHA-256, or to a disclaimer slot by `disclaimer_slot_id` and SHA-256 (no free text). `safe_area_class = DEFAULT` is a placeholder until the official Shorts overlay zones are logged (**REQUIRES REVIEW (Phase 1): official Shorts UI overlay zones, 18 §10**).

Determinism hash: SHA-256 of the canonical JSON of the plan without `provenance` and without `plan_ref`.

### 8.3 Step output `agent_09.shot_plan.direction.output` 1.0.0
The exact JSON Schema is in the prompt file (§Output JSON Schema). Fields per direction: `slot_id`, `status` (`OK` / `NO_SAFE_VISUAL`), `reason_code`, `intent_kind` (`FOOTAGE` / `DIAGRAM` / `TEXT_CARD` / null), `intent_text`, `framing`, `motion`, `still_ok`, `needs_ai_video`, `interrupt_device`, `transition_hint`, `text_ids[]`, `subject_anchor`, `depiction {real_person, identifiable_person, market_direction_imagery, market_data_screen, brand_or_logo, ai_presenter, realistic_event_depiction, schematic}`, `rationale`; plus `batch_id` and `refusal`.

### 8.4 Refusal and status mapping (27 §4.3 declared item-level mapping, CCR-023)
Agent 09 is not a compliance gate: its payload carries no compliance verdict. It declares the item-level mapping that 27 §4.3 allows. Guard hits and refusals never become a `PASS` (rule 4 of that paragraph).
| Step result | Task result |
|---|---|
| all directions `OK` or repaired/fallback | `SUCCEEDED` if every `blocking: true` result is `PASS` |
| `refusal.reason = INSUFFICIENT_INPUT` | `FAILED`, `PERMANENT.INSUFFICIENT_INPUT` (27 §4.3) |
| `refusal.reason = RULE_WOULD_BE_BROKEN` | the batch's slots become fallback shots (`origin = FALLBACK`); one result `a09.q.visual_guard.refusal` with verdict `WARN`, `blocking: false`, `rule_id` = the `violated_rule_ids`; the shots appear in `views.agent_16_realism[]` with `refusal_reason`; Agent 16 sees them (27 §4.3 rule 3) |
| `refusal.reason = UNSAFE_CONTENT` | the same degradation and `WARN` result with `refusal_reason = UNSAFE_CONTENT`; `NEEDS_HUMAN_REVIEW` is Agent 16's verdict, so Agent 09 only surfaces the item |
| `OUT_OF_SCOPE`, `CONFLICTING_INSTRUCTIONS` | `FAILED`, `PERMANENT.INPUT_INVALID` |
| task-level failure condition | when the share of model slots that ended as fallback exceeds `agent_09.fallback.max_share_permille`, the task fails `AGENT.QUALITY_REPEATED_FAILURE` (L3) even though each item degraded legitimately |

---

## 9 Python package and class architecture
**MVP: 3A · Tier 0. Package `agent_09_video_director` (27 §7.2), typed, mypy strict, ruff; imports only `amw_core` and adapter Protocols.**

```text
agent_09_video_director/
  __init__.py            # exports VideoDirector (Protocol) and ShotPlanStep
  protocol.py            # VideoDirector Protocol: run(task_input, ctx) -> TaskOutput
  contracts.py           # Pydantic models: ShotPlanInput, ShotPlanOutput, Shot, Overlay, Direction, DirectionBatchInput/Output
  config.py              # Agent09Config (pydantic-settings via amw_core.config), required-key check
  errors.py              # typed exceptions -> 07 §2 codes (ErrorMapper)
  step.py                # ShotPlanStep: the orchestration of P1..P10
  gates.py               # TenantScope use, InputValidator, ScriptGate
  timeline/
    timemap.py           # NarrationTimeline, TimeMap
    hook.py              # HookAnalyzer
    pacing.py            # PacingProfile
    grid.py              # SlotGrid, ChartPlanner
    interrupts.py        # InterruptPlacer
    jl.py                # JlPlanner
    transitions.py       # TransitionPlanner
    overlays.py          # OverlayPlanner (sting, lower-thirds, caption/chapter/disclaimer cards), EndScreenPlanner
    chapters.py          # ChapterBuilder
    tiers.py             # TierPlanner
    audio.py             # AudioCuePlanner
    vertical.py          # VerticalPlanner
    rebase.py            # rebase_plan (called inside this task only, FR-16)
  direction/
    batcher.py           # DirectionBatcher
    prompt.py            # PromptRenderer (loads prompts/agent_09_video_director/shot_direction.v1.md, injects rule packs)
    client.py            # DirectionClient over LlmAdapter: budget, breaker, idempotency, ledger
    parser.py            # DirectionParser (Pydantic, one retry with the validation error)
    guard.py             # VisualGuard, InjectionScanner
    repair.py            # DirectionRepair, FallbackBuilder
  assemble.py            # PlanAssembler (+ canonical JSON, determinism hash)
  checks.py              # PlanChecks: 24 a09.q.* checks + a09.pre.* preconditions -> ValidationResult
  persistence.py         # PlanWriter, CheckpointStore, MemoryAccess, AuditEmitter
```
Key types (signatures in §10):
```python
class VideoDirector(Protocol):
    def run(self, task_input: TaskInput[ShotPlanInput], ctx: StepContext) -> TaskOutput[ShotPlanOutput]: ...
```
Dependency injection (27 §7.1): `ShotPlanStep.__init__(self, *, llm: LlmAdapter, cost: CostGuard, storage: BlobStore, repo: PlanRepository, clock: Clock, prompts: PromptStore, config: Agent09Config)`. Only `workers/ai_worker` wires concrete objects. Pure engine classes (everything in `timeline/`, `guard.py`, `repair.py` fallback, `assemble.py`, `checks.py`) take plain data and config, hold no I/O and no clock, so they run in unit tests without fakes.

---

## 10 Function-level specification
**MVP: 3A · Tier 0. "Pure" = no I/O, no clock, no randomness. Exceptions are typed and map 1:1 to 07 §2 codes (§18). Logging = structured JSON via `amw_core.observability`, fields `org_id`, `correlation_id`, `job_id`, `task_id`, `attempt_id`, `actor = agent_09`; never narration text, `intent_text` or on-screen text (counts, IDs, hashes only).**

| ID | Function / method | Signature (types) | Side effects | Raises | Validation and rules | Log event | Tests |
|---|---|---|---|---|---|---|---|
| F-01 | `TenantScope.assert_consistent` | `(envelope, task_input, refs: list[Uri]) -> None` | none | `TenantMismatch`, `CrossTenantRef` | org of envelope = Task Input = context refs = payload refs; every URI org equals `app.org_id` | `plan.tenant_ok` | U-01, U-02 |
| F-02 | `InputValidator.validate` | `(task_input) -> ShotPlanInput` | none | `SchemaInvalid`, `SchemaVersionUnsupported`, `InputInvalid` | §7.2 schema; ID prefixes; `aspect_ratio 9:16 ⇒ production_type SHORTS`; `limits` non-negative | `plan.input_valid` | U-03, U-04 |
| F-03 | `ScriptGate.check` | `(script: ScriptDoc, script_sha: str, ver: VerificationRef, approvals: ApprovalReader) -> GateResult` | DB read (RLS) | `InputInvalid` (`details.violations`), `MissingDependency` | `sha256(script blob) == ver.verified_script_sha256 == script_ref.sha256` (`verified_script_sha256` = `script_sha256` of Agent 06's output; same for the Shorts child script); `stage_verdict` (= `overall.proposed_verdict`) is `ALLOWED`, or `NEEDS_HUMAN_REVIEW` with the same-org `SENSITIVE_CLAIM` approval `APPROVED`; no claim of the script version has `final_verdict` (else `proposed_verdict`) = `BLOCKED`; `scripts.status` not `REJECTED`/`SUPERSEDED` | `plan.script_gate` | U-05…U-08 |
| F-04 | `NarrationTimeline.load` / `TimeMap.build` | `(uri, sha256, segments) -> TimeMap` | storage read, hash verify | `MissingDependency`, `CorruptedOutput`, `InputInvalid(TIMELINE_INCOMPLETE / TIMELINE_UNALIGNED)` | `source ∈ {PROVIDER_CLIPS, OWNER_MARKS}` (`UNALIGNED` or any null `start_ms`/`end_ms` ⇒ `TIMELINE_UNALIGNED`); every script `segment_id` exactly once, order equals script order, `start < end`, no overlap, monotonic; `content_end_ms = max(end_ms)`; extra IDs rejected | `plan.timemap` | U-09…U-12, U-115 |
| F-05 | `ConfigResolver.resolve` | `(cfg: Agent09Config) -> ResolvedLimits` | none | `ConfigInvalid` | required keys set (§24.2): `agent_09.cadence.min_gap_ms`, `qc.visual.max_change_gap_ms`, `snap.*`, `max_slots`, `llm.*`, hook window; unset optional keys resolve to documented "off" behaviour (§6) | `plan.config` | U-13, U-14 |
| F-06 | `HookAnalyzer.analyze` | `(segments, timemap, window_ms) -> HookInfo` (pure) | none | `InputInvalid(HOOK_WINDOW_EXCEEDED / HOOK_BEATS_MISSING)` | hook segments = kinds `HOOK_PROOF`, `HOOK_WHY`, `HOOK_COVERS` (long form) or `SHORT_HOOK` (9:16), contiguous from the first segment; `hook_end ≤ window_ms`; long form `first_payoff_ms = end of HOOK_PROOF`, 9:16 `first_payoff_ms = hook_end` (end of the `SHORT_HOOK` beats) | `plan.hook` | U-15…U-17, U-116 |
| F-07 | `PacingProfile.target_gap` | `(beat: str, role: SlotRole, cfg) -> int` (pure) | none | `ConfigInvalid` | lookup then directive-window fallback (§6.3) | — | U-18 |
| F-08 | `SlotGrid.build` | `(scene, span: Span, g: GapLimits, boundaries: list[int]) -> list[Slot]` (pure) | none | `LoopCapExceeded` (more than `max_slots` in total) | algorithm §6.2 steps 1–8; slots contiguous, durations ≤ `g_max`; deterministic | `plan.slots` (count) | U-19…U-26 |
| F-09 | `ChartPlanner.plan` | `(chart_requests, scenes, timemap, g) -> list[Slot]` (pure) | none | `InputInvalid(CHART_REQUEST_UNMATCHED)` | each `chart_request.first_segment_id` lies in a scene with that `chart_id`; steps `m` per §6.2.7; `must_be_historical` must be `true` | `plan.charts` | U-27…U-29 |
| F-10 | `InterruptPlacer.place` | `(slots, windows, script_interrupts, devices) -> list[Slot]` (pure) | none | none | §6.4.1–2; at most one forced slot per window; ties earlier | `plan.interrupts` | U-30…U-33 |
| F-11 | `DirectionBatcher.make_batches` | `(slots, size: int) -> list[Batch]` (pure) | none | none | only slots with `origin = MODEL` (no chart, disclaimer or fallback); order preserved; batch size from config | — | U-34, U-35 |
| F-12 | `PromptRenderer.render` | `(prompt: PromptFile, batch: BatchInput, packs: dict[str, PackText]) -> RenderedPrompt` (pure) | none | `ConfigInvalid` | every `{{variable}}` declared; the data block between `<<<INPUT` and `INPUT>>>`; rule-pack text injected with version; marker strings inside data are escaped | — | U-36, U-37 |
| F-13 | `DirectionParser.parse` | `(raw: str) -> DirectionBatchOutput` (pure) | none | `InvalidJson`, `OutputSchemaInvalid` | Pydantic model = prompt schema; coverage: every input slot once, same order; no extra fields; one retry with the validation error is the caller's | — | U-38, U-39 |
| F-14 | `VisualGuard.scan` | `(direction, slot, ctx: GuardContext) -> list[GuardHit]` (pure) | none | none | G1…G7 of §6.5; hits carry guard ID and slot ID only | `plan.guard` (counts) | U-40…U-43 |
| F-15 | `DirectionRepair.plan_repairs` / `FallbackBuilder.build` | `(rejected, repairs_left) -> RepairAction` / `(slot, brand, text_options) -> Shot` (pure) | none | none | one re-ask per batch (`max_repairs_per_batch`), then fallback: `origin = FALLBACK`, template key from the brand kit or platform, `TEXT_CARD` only with an existing script text option | `plan.repair` | U-44…U-46 |
| F-16 | `TransitionPlanner.plan` | `(shots, hints, cfg) -> list[Transition]` (pure) | none | none | allowed set, no dip to black, ≤ `transition.max_ms` and ≤ 20 % of the shorter neighbour; section boundary dissolve unless J/L | — | U-47, U-48 |
| F-17 | `JlPlanner.plan` | `(shots, timemap, segments, hook: HookInfo, cfg) -> JlResult` (pure) | none | none | §6.4.5; result lists applied cuts and skipped boundaries with reason (`HOOK_END`, `DISCLAIMER`, `GAP_LIMIT`, `NOT_SENTENCE_ALIGNED`) | `plan.jl` | U-49…U-53 |
| F-18 | `TierPlanner.plan` | `(shots, directions, limits, cfg) -> TierPlan` (pure) | none | none | §6.6; always a tier-C fallback; planned worst-case shares | `plan.tiers` | U-54…U-58 |
| F-19 | `OverlayPlanner.plan` | `(shots, hook, brand, scenes, disclaimer_slots, sections, cfg) -> list[Overlay]` (pure) | none | `InputInvalid(TEXT_NOT_IN_SCRIPT)` | brand sting at `hook_end_ms` only if `intro_ref`; lower-thirds and caption cards only from `scenes[].on_screen_text` (by SHA-256); the disclaimer card by `disclaimer_slot_id` and `text_sha256`; chapter cards at section starts (optional, config); disclaimer card covers at least its segment span | `plan.overlays` | U-59…U-63 |
| F-20 | `EndScreenPlanner.plan` | `(content_end_ms, cfg, brand) -> EndScreen or None` (pure) | none | none | length from `agent_09.end_screen.length_ms`; unset ⇒ `None` and check `WARN`; no new content (template only); tail silence listed in `deliberate_pauses` with `reason = END_SCREEN` | `plan.end_screen` | U-64, U-65 |
| F-21 | `ChapterBuilder.build` | `(sections, timemap) -> list[Chapter]` (pure) | none | `InputInvalid(CHAPTER_ORDER)` | first at 0, strictly increasing, start = measured start of the section's first segment; no sections (Shorts script) ⇒ `[]` | — | U-66, U-67, U-116 |
| F-22 | `AudioCuePlanner.plan` | `(interrupts, limits, cfg) -> AudioPlan` (pure) | none | none | 3A: `music.bed = NONE`, no SFX; 3B with `limits.music_library_enabled`: `music.bed = REQUESTED`, range −20.0…−15.0 dB (18 §5), span `[0, total_duration_ms]`; 3C with `limits.sfx_library_enabled`: one cue per `SOUND_CUE` interrupt | — | U-68, U-69 |
| F-23 | `VerticalPlanner.plan` | `(shots, aspect, directions, parent_plan) -> list[VerticalInfo]` (pure) | none | `InputInvalid(VERTICAL_ANCHOR_MISSING)` | for `9:16`: anchor on every shot, overlay `vertical_variant = true`, `parent_shot_id` from segment overlap with `parent_segment_ids` (nullable); none for 16:9 | — | U-70…U-72 |
| F-24 | `rebase_plan` | `(plan, timeline: NarrationTimeline) -> ShotPlan` (pure; called by `ShotPlanStep` at iteration ≥ 1 only, FR-16) | none | `InputInvalid(REBASE_LIMIT)` | recompute every start/end from segment anchors of the new timeline; keep shot IDs, content keys and directions; re-run the cadence and J/L steps; fail if a hard limit cannot hold | `plan.rebase` | U-73…U-75 |
| F-25 | `PlanAssembler.assemble` | `(parts) -> ShotPlan` (pure) | none | none | canonical JSON (sorted keys, ints only), determinism hash, shot IDs `sh01…` by `seq` (stable while the slot structure is unchanged) | — | U-76, U-77 |
| F-26 | `PlanChecks.run_all` | `(plan, inputs, cfg) -> list[ValidationResult]` (pure) | none | none | the 24 checks of §20; a measurement that cannot be computed is never `PASS`: it is `SKIPPED`/`WARN` with `blocking: false` (CCR-001); no result has `gate: true`; `deliberate_hold[]` derived from `held`, `deliberate_black = []` | `plan.checks` | U-78…U-101, U-117, U-118, U-120 |
| F-27 | `ShotPlanStep.run` | `(task_input, ctx) -> TaskOutput` | all below, in order | any of §18 | P1…P10 of §4.1; `SUCCEEDED` only when every `blocking: true` result is `PASS`; at iteration ≥ 1 reads `previous_plan_ref` and calls F-24 when the timeline hash changed (`previous_plan_ref` null at iteration ≥ 1 ⇒ `InputInvalid`); declared refusal mapping of §8.4; resumable | `plan.start`, `plan.done` | IT-01…IT-06, U-119, U-121 |
| F-28 | `CheckpointStore.save` / `load` | `(ctx, state) -> CheckpointRef` / `(ctx) -> State or None` | INSERT `checkpoints`; blob write-once | `StorageUnavailable`, `CorruptedOutput` | state holds slot list, accepted directions, batch cursor, `call_seq`; SHA-256 verified on load | `plan.checkpoint` | U-102, U-103 |
| F-29 | `DirectionClient.complete` | `(rendered, batch_id, call_seq) -> RawResponse` | S4 reservation check (draws on the job's reservation, no second hold), breaker check, adapter call with `step_key = "direction." + batch_id`, `cost_ledger` row `operation = llm.completion` (idempotency scope `llm.call`) | `BudgetExhausted`, `CircuitOpen`, `RateLimited`, `Timeout`, `Upstream5xx`, `AuthInvalid`, `ProviderRefusal`, `IdempotencyConflict` | no call without an `ACTIVE` provider budget row, reservation ≥ worst case, closed breaker; completed key ⇒ stored result, no call | `plan.llm_call` | U-104…U-106, FI-03…FI-07 |
| F-30 | `PlanWriter.persist` | `(ctx, plan) -> OutputRef` | blob write-once (scope `db.output`), SHA-256 | `StorageUnavailable`, `IdempotencyConflict` | path built by `amw_core.storage`; existing blob with the same hash ⇒ returned, different hash ⇒ conflict | `plan.persisted` | U-107, U-108 |
| F-31 | `MemoryAccess.read_channel` | `(ctx) -> ChannelStyle` | SELECT `memory_items` (scope `CHANNEL`, own channel) | `MissingDependency` | key names `a09.pacing_overrides` (3C), `a09.visual_dont_list` (3B); no cross-channel read; no write and no `TASK` read (revision context is `previous_plan_ref`, CCR-008) | `plan.memory` | U-109, U-110 |
| F-32 | `InjectionScanner.scan` | `(text: str) -> list[str]` (pure) | none | none | flags instruction-like phrases, URLs, markup, marker strings, control characters; returns pattern IDs only | — | U-111, U-112 |
| F-33 | `RevisionContext.apply` | `(feedback, prev_plan, plan_new) -> list[Unaddressed]` (pure) | none | none | every feedback item maps to a check that now passes for the named shots; used by `a09.q.revision_addressed` | `plan.revision` | U-113, U-114 |
Cross-cutting rules: (1) every function that reads a URI calls `TenantScope` first; (2) nothing in `timeline/` imports `direction/` or an adapter; (3) no function returns partial results as success; (4) time is passed in as data, never read from a clock inside a pure function.

---

## 11 AI provider use
**MVP: 3A (one step, one provider through the adapter) · 3B (tier chosen by the eval gate) · 3C (batch eligibility, second provider only by ADR amendment). Tier 0.**

| Aspect | Decision |
|---|---|
| Adapter | `LlmAdapter` Protocol of ADR-007 (`complete`, batch submit/poll, token count). Agent 09 imports the Protocol only; the worker injects the adapter. Fake and redacted recorded fixtures exist for tests (27 §8). |
| Task-type routing | `llm.agent_09.shot_plan.direction.model_tier` starting at `MID` (Sonnet class; 09 §10 assigns `agent_09.shot_plan` to the mid tier, PR-01); moves to `SMALL` only if the golden dataset passes at the cheaper tier (ADR-007 §2.4). Model IDs live in `llm.tiers.<tier>.model` only. |
| Calls per plan | `ceil(model_slot_count / agent_09.llm.batch_slots)` plus at most one re-ask per failing batch; chart, disclaimer and fallback slots are never sent. Formula only; **REQUIRES REVIEW (Phase 1): MEASURED slots per 10-minute video and tokens per batch in the 3A skeleton** |
| Prompt caching | the stable prefix is the prompt file plus platform-scope rule-pack text; tenant data and the tenant-scope pack `rp.tenant_brand_safety` are placed after the cache breakpoint (CCR-025); `.cache_system_prompt = true` (PR-02: cache read costs a fraction of input price). The cached prefix therefore contains no tenant data (§19.1 layer 4). |
| Batch API | `.batch_eligible = false` in 3A (owner-triggered, short runs; ADR-007 §2.6); 3C may enable it for scheduled night work (PR-02: 50 % discount) — a batch result after the task `deadline` fails `PERMANENT.DEADLINE_EXCEEDED`. |
| Temperature and limits | config only: `.temperature`, `.max_output_tokens`, `.timeout_ms`, `.cost_budget_micros` (family `llm.<task_type>.<step>.*`, CCR-019). Low temperature is expected for a closed-enum output; the value is set by the eval gate, not here. |
| Structured output | Pydantic parse; `AGENT.INVALID_JSON` / `AGENT.OUTPUT_SCHEMA_INVALID` retried once with the validation error appended (07 §3.3 `agent_parse`), then the task fails and goes to the DLQ (27 §7.3.2). |
| Cost capture | one `cost_ledger` row per call (`provider`, resolved `model`, `operation = llm.completion`, `billing_mode`, tokens, `amount_micros`, `figure_kind = ESTIMATE`, `price_ref`, `idempotency_key`); a later `VERIFIED` row points to it (ADR-007 §2.7). Cost per plan = Σ calls; price rows come from the pricing config (PR-01 lists the current tier prices; none is hard-coded). |
| Fallback | tier or provider fallback only inside the attempt and only when configured (`llm.agent_09.shot_plan.direction.fallback_tier`, `llm_model_tier` `SMALL`·`MID`·`TOP`, CCR-019); a deterministic in-stage fallback (the code-made fallback shots) after `CIRCUIT_OPEN`, `PROVIDER_REFUSAL` or a parse failure after the retry exists only when `agent_09.llm.fallback_on_unavailable` is true (default false, owner enables; 07 §3.5, CCR-023) and never for a suspension, a permanent input code or a tenancy code; the fallback result passes the same parser and guards. A second provider needs an ADR amendment. |
| No tools | the call carries no tool definitions, no browsing and no file access: the model can only return the JSON object. |
| Data sent | slot data of one tenant: narration excerpts, scene intent text, text options, banned subjects. No IDs of persons, no keys, no server details, no other tenant's data. Provider-side retention and training terms: **REQUIRES REVIEW (Phase 1): provider terms (Tier 1 gate)**. |
| Subscription vs API | a Claude subscription is not API access (rule 5, PR-03); the API key is a separate secret. |

---

## 12 External APIs
**MVP: 3A · Tier 0.**

| API | Used? | Auth / scopes | Quotas and error codes | Fallback | Fact source |
|---|---|---|---|---|---|
| LLM provider API (through `LlmAdapter`) | **yes**, the only external call of this agent | API key from the environment's secret mechanism (`AMW_LLM_PROVIDER_KEY`, the same secret name as agent_05 §24, held by the AI worker only); no OAuth, no scopes | provider rate and spending limits are set by the owner at the provider before the first paid call (D1); HTTP 429 → `TEMPORARY.RATE_LIMITED` (honour `retry_after_ms`), 5xx → `TEMPORARY.UPSTREAM_5XX`, timeout → `TEMPORARY.TIMEOUT`, 401/403 → `PERMANENT.AUTH_INVALID`, safety refusal → `PERMANENT.PROVIDER_REFUSAL` (ADR-007 §2.10, 07 §2); per-provider circuit breaker (07 §4) | configured tier fallback inside the attempt; otherwise `RETRY_WAIT` or `CHECKPOINTED` (§18) | PR-01 (models and prices), PR-02 (caching and batch), ADR-007; numeric rate limits per tier **REQUIRES REVIEW (Phase 1): not in the research log** |
| YouTube Data / Analytics API | **no** | — | zero quota units (D1: no upload, no OAuth) | — | YT-01…YT-05 not applicable |
| Stock, music, SFX, image and video generation APIs | **no** (Agent 08 owns them, ADR-009) | — | — | — | — |
| FFmpeg / ffprobe | **no** (this agent decodes no media) | — | — | — | INF-09 is used by Agent 10 on the render |
Agent 09 makes no network call other than the one above. The socket guard of the test runner enforces this in CI (27 §8.1).

---

## 13 Database tables
**MVP: 3A · Tier 0. Only tables of 04_DATABASE_ARCHITECTURE.md are used; no table, column or enum is added. Every access runs inside a tenant transaction (`SET LOCAL app.org_id`, 04 §3.2) as role `amw_app`, with an explicit `org_id` predicate as well (RLS is the second line).**

### 13.1 Tables used
| Table (04 §) | Access | Used for | MVP |
|---|---|---|---|
| `tasks`, `task_attempts`, `jobs`, `projects`, `task_dependencies` (5.3) | SELECT (own task), status written by the orchestrator through core | task context, iteration | 3A |
| `task_queue` (5.4), `state_transitions` (5.6) | via `amw_core` only | claim, lease, heartbeat, transitions; never written by agent code directly | 3A |
| `checkpoints` (5.7) | INSERT, SELECT | resume state (§16) | 3A |
| `dead_letter` (5.7) | none by the agent | the orchestrator dead-letters on `FAILED` | 3A |
| `idempotency_keys` (5.9) | via `amw_core` | scopes `llm.call`, `db.output`, `task.agent_09.shot_plan` | 3A |
| `memory_items` (5.10) | SELECT (`CHANNEL`) | owner's unwanted subjects (3B), pacing overrides (3C); no write; revision context is `previous_plan_ref`, not memory (CCR-008) | 3B · 3C |
| `scripts` (5.11) | SELECT | `body_ref`, `content_sha256`, `status`, `language`, `version` | 3A |
| `claims` (5.11) | SELECT (counts only, optional) | cross-check that no claim of the verified script version has `final_verdict` (else `proposed_verdict`) = `BLOCKED` (`BLOCKED` is a `compliance_verdict`, not a `claim_status`) | 3A |
| `channels` (5.1), `workspaces` (5.1) | SELECT | category, workspace for the brand kit | 3A |
| `brand_kits` (5.12) | SELECT (current row) | `lower_third_template_ref`, `intro_ref`, `outro_ref`, `banned_words`, `tone_rules` | 3A |
| `compliance_profiles`, `compliance_profile_rule_packs`, `rule_packs` (5.2) | SELECT | active packs and their text/version for the prompt | 3A |
| `org_production_types`, `production_types` (5.2) | SELECT | stage settings and limits (`max_revision_loops`) | 3A |
| `approvals`, `approval_steps` (5.16) | SELECT | the `SENSITIVE_CLAIM` approval when the verdict is `NEEDS_HUMAN_REVIEW` (`subject_kind`, `subject_id`, `subject_sha256` read) | 3A |
| `cost_ledger`, `budgets`, `budget_reservations` (5.14) | via S4 (`amw_core.cost`) | one row per LLM call; reservation before the call | 3A |
| `audit_log`, `audit_chain_heads` (5.13) | via `amw_core.audit` | audit actions of §22 | 3A |
| `message_log`, `message_receipts` (5.5) | via core | envelope dedupe | 3A |
### 13.2 What Agent 09 does **not** touch
`assets`, `licences`, `licence_ledger`, `asset_fingerprints` (Agent 08 and 16 own them; the plan holds no asset IDs), `renders`, `qc_results`, `quality_scores`, `compliance_verdicts` (Agents 10 and 16 write them; Agent 09's check results travel in `validation_results` of the Task Output and are persisted by the orchestrator/core as `qc_results` rows where 04 §5.17 provides), `voices`, `voice_consents`, `publications`, YouTube tables.
### 13.3 Gaps
None. The plan itself is a blob (03 §8), referenced from `output_refs`; no `shot_plans` table is needed. If 3C needs queryable shots (analytics of pacing against retention), that is a change request, not a local table.

---

## 14 Memory
**MVP: 3A (no durable memory; revision context travels as `previous_plan_ref`) · 3B (owner's unwanted subjects) · 3C (channel pacing overrides) · Tier 0. Scopes and isolation as GLOSSARY §6.30 and 04 §5.10. `TASK` memory is not used: each revision iteration is a new task and 04 §5.10 rule 1 limits `TASK` items to the same task (CCR-008); the previous plan is a `PRIOR_OUTPUT` context ref (24 §3.3 rule 6).**

| Scope | Key | Content | Reader / writer | Expiry | MVP |
|---|---|---|---|---|---|
| `WORKING` | — | in-attempt data only (slot list, directions); lost at attempt end; durable state goes to checkpoints | Agent 09 | attempt | 3A |
| `CHANNEL` | `a09.pacing_overrides` | per-beat target gaps and interrupt-window values accepted by the owner after an approved experiment | read by Agent 09; written by the learning loop (Agent 14/01) after approval (§3.3 learning loop; no automatic change to critical policies) | `review_after` | 3C |
| `CHANNEL` | `a09.visual_dont_list` | subjects the owner marked as unwanted (extends `banned_subjects`) | read; written by the operator tool | `review_after` | 3B |
| `PROJECT`, `LONG_TERM` | — | not used | — | — | — |
Rules: (1) memory is read only inside the tenant transaction and only for the task's `channel_id`; a row of another channel or org is invisible (RLS) and, if referenced by a context ref, `CROSS_TENANT_REF`; (2) a memory value never overrides a guard or a hard limit: overrides are clamped to the directive window (3–5 s) and the config caps; (3) memory content is data, never instructions: it passes the same `InjectionScanner` before reaching a prompt; (4) no narration text is stored in memory (hashes and IDs only).

---

## 15 Upstream and downstream contracts
**MVP: 3A · Tier 0. Contracts are 03 (envelopes), 24 (task graph) and the neighbours' blueprints; nothing here redefines them.**

### 15.1 Upstream (what Agent 09 receives)
| From | What | Mapping rule |
|---|---|---|
| Agent 05 `agent_05.script_draft` / `shorts_adaptation` | script document: `sections`, `scenes` (with `visual_intent`, `interrupt`, `explanatory`, `deliberate_pause_ms`, `on_screen_text`, `chart_id`), `segments`, `chart_requests`, `chapters`, `disclaimer_slots`, `parent_segment_ids` (9:16) | read-only; the script gives *intent*; times, shots and cadence are Agent 09's (agent_05 §15.2) |
| Agent 06 `agent_06.claim_verification` (`s06_verify`) | `overall.proposed_verdict` (stage verdict) and `script_sha256` (CCR-049); script ID/version | the orchestrator copies them into `verification_ref.stage_verdict` / `.verified_script_sha256`; `ScriptGate` (F-03). The Shorts child job has its own `s06_verify` (24 §7.2a). Chart claims are verified later at `s06_chart` and do not gate this stage |
| Agent 07 `agent_07.voice_synthesis` | narration timeline: start, end per sentence, in ms from stem start | the `TimeMap`; "planned shot lengths use measured narration" (agent_07 §15.2). `s09_plan` depends on `s07_voice` (24 §7.1, §7.1a, §7.2a; CCR-003). An `UNALIGNED` timeline is refused at `s07_voice` (CCR-051) and never reaches this task |
| Brand kit (S11 → 13, 04 §5.12) | `intro_ref` (sting), `lower_third_template_ref`, `outro_ref`, `banned_words`, `tone_rules` | read-only |
| Agent 08 / 10 / 16 and the approver (revision) | failing results (check IDs, shot IDs, measured values) whose `remedy_stage_id` or routing names `s09_plan` (24 §3.3 rule 1), plus the previous plan | built by the orchestrator into `revision_feedback[]` and `previous_plan_ref`, FR-17 |
| Orchestrator | `limits` (AI-video ms, still allowed, library flags) from S4 budgets and capability config | copied into the payload |
| Parent job (SHORTS) | parent plan reference | optional `parent_plan_ref` `{uri, sha256}` |

### 15.2 Downstream (what Agent 09 produces and who reads it)
| To | What it receives | Mapping rule |
|---|---|---|
| Agent 08 `agent_08.asset_sourcing` | `views.agent_08_shots[]` (§8.1.1: the fields Agent 08's `ShotPlanReader` consumes, including `held` as `allows_hold`, `vertical_anchor`, `realistic_event_depiction`, `change_events_ms`, `tier_hint`, `scene_id`, start/end) and the `plan_ref` `{uri, sha256, schema, schema_version}` which the orchestrator copies into Agent 08's `shot_plan_ref` | exactly the shot object fields of `agent_08/search_query_plan.v1` (`{shot_id, intent_kind, intent_text, on_screen_text[], aspect_ratio, duration_ms}`) and `candidate_rank.v1` (`{shot_id, intent_text, aspect_ratio, duration_ms}`), plus the tier fields; only `FOOTAGE` shots reach Agent 08's model steps; Agent 08 writes the asset and licence rows and may use only `allowed_tiers` |
| Agent 10 `agent_10.render` | the plan blob (`shots`, `overlays`, `audio_plan`, `chapters`, `jl_cuts`, `deliberate_hold`, `deliberate_black`, `end_screen`, `timing_basis = MEASURED`) with its SHA-256 | Agent 10 binds assets by `shot_id` and compiles the render timeline JSON (`renders.timeline_sha256`, 18 §3); Agent 10 owns frame quantisation |
| Agent 10 `agent_10.subtitles` / `agent_10.technical_qc` | `chapters`, `hook`, `interrupts`, `jl_cuts`, `deliberate_pauses`, `deliberate_hold[]`, `deliberate_black[]` (always empty), `held` reasons | evidence for `edit.*`, `qc.video.black_frames`, `qc.video.freeze` and `qc.visual.*` checks |
| Agent 07 `agent_07.audio_master` (3B) | `audio_plan.music` (bed request, −20.0…−15.0 dB range) | the mix is Agent 07's; the stage order for it comes with the 3B production-type version after the owner's licensed-source decision (D6, CCR-007); not part of the 3A graphs |
| Agent 08 music sourcing (3B) | `audio_plan.music` | Agent 08 sources the track (`music_search`, `MUSIC_BED` ledger rows); 3A has no music |
| Agent 11 `agent_11.thumbnail_variants` | `views.agent_11_subjects[]` (§8.1.1: `{hint_id, shot_id, shot_role, intent_text, framing}`, at most 4; the hook and the proof beat) | thumbnails repeat the promise (`edit.promise_alignment`); Agent 11 never reads narration from this plan |
| Agent 16 `agent_16.compliance_gate` / `quality_score` | `views.agent_16_realism[]`: per shot `{shot_id, realistic_event_depiction, schematic, origin}`; `tier_budget`; check results | disclosure decision input ("the shot plan's description of realism", 13 §3.3); `EDITING_QUALITY` and `VISUAL_QUALITY` deterministic parts |
| Orchestrator | Task Output, `next_action`, advisory | `CONTINUE` to `agent_08` on success; the orchestrator decides (03 §5.3.1) |
| Agent 12 (3C) | `chapters[]` as the chapter source | chapter text and publication rules are Agent 12's |

### 15.3 Contract decisions applied (CONTRACT_CHANGE_REQUESTS.md §5, "Resolved for blueprint 09")
| Former request | Decision as used here |
|---|---|
| `s09_plan.depends_on += s07_voice` | approved in 24 §7.1, §7.1a, §7.2a (CCR-003); the `ESTIMATED` fallback and `rebase_plan` by Agent 10 are rejected (CCR-003, CCR-051) |
| schema names `agent_09.shot_plan.input/.output`, `.direction.input/.output` | approved as-is by GLOSSARY §2.4 (CCR-018) |
| `agent_09.*`, `llm.agent_09.shot_plan.direction.*`, `a09.q.*`, `a09.pre.*` | approved (CCR-019, CCR-020); listed in §24.2 and §20; one source for the cadence limit: `qc.visual.max_change_gap_ms` |
| not-computable checks | `SKIPPED`/`WARN` with `blocking: false` (CCR-001) |
| revision digest | `previous_plan_ref`, a `PRIOR_OUTPUT` context ref (CCR-008) |
| verified script hash and stage verdict | Agent 06 `script_sha256` and `overall.proposed_verdict` (CCR-049) |
| Shorts | claim verification exists (24 §7.2a); `section_id` nullable, chapters empty and `SKIPPED`; hook = `SHORT_HOOK` beats (CCR-003) |
| 18 IDs and intervals | `qc.video.black_frames`, `qc.video.freeze`, `qc.audio.music_bed_offset`; `deliberate_hold[]`, `deliberate_black[]` (R10 CCR-H) |
| music | cue plan is 3B (CCR-007) |
| refusal mapping, `max_slots`, eval prefixes | declared item-level mapping (CCR-023); 07 §9 per-agent cap row (CCR-022); `POS-`/`TE-` (CCR-024) |

---

## 16 State handling and checkpoints
**MVP: 3A · Tier 0. State machine and transitions are 03 §11; this section states what the agent does at each.**

| Task state | Agent 09 behaviour |
|---|---|
| `PENDING` → `VALIDATING` | the orchestrator runs the 03 §7 validation, tenant and idempotency checks and the budget pre-check; the agent adds F-01…F-05 in `RUNNING` only if the orchestrator did not (never twice with different results) |
| `RUNNING` | P1…P10 under a lease with heartbeat (`heartbeat_ms`, 07 §6); the wall budget is `resource_budget.max_wall_ms` |
| `CHECKPOINTED` (`AWAITING_BUDGET`) | S4 refused the reservation: the task suspends before the first call; resumes when the budget is released (rule 8: no automatic increase) |
| `CHECKPOINTED` (`DRAIN`) | on a DRAIN control: finish the in-flight call, save a checkpoint, release the lease |
| `RETRY_WAIT` | after a retryable error (§18); resumes from the latest checkpoint |
| `COMPLETED` | output validated and persisted |
| `FAILED` → `DEAD_LETTER` | permanent errors and exhausted retries; replay by a human (07 §5) |

**Checkpoints** (`checkpoints` row + write-once blob under `jobs/<job>/checkpoints/`, 03 §8):
| Checkpoint | After | Holds | Resume effect |
|---|---|---|---|
| `CK1_SKELETON` | P6 | slot list, hook info, time map hash, interrupt roles | skip P1–P6 recompute only if hashes of inputs are unchanged, else recompute (cheap) |
| `CK2_BATCH_n` | each accepted batch | accepted/repaired directions of batch `n`, `call_seq`, cost entry IDs | skip completed batches; no call repeated (idempotency scope `llm.call`) |
| `CK3_ASSEMBLED` | P9 | assembled plan, check results | go directly to persist |
Rules: (1) a checkpoint is valid only if its `timeline_sha256`, script SHA-256 and config version equal the current ones; otherwise it is discarded and the stage recomputes (the paid calls already recorded stay reusable by key); (2) no half-written blob at a final path: blobs are written to a temp name and moved atomically, SHA-256 verified on read (07 §10); (3) one writer: the lease holder; a `LEASE_EXPIRED` attempt's late write is rejected by the key check; (4) a replay from the DLQ re-runs with the same keys: LLM calls skipped, rows found, output identical (NFR-2); (5) iteration ≥ 1 never reuses a checkpoint of an earlier iteration, only the previous plan from `previous_plan_ref` (§6.7).

---

## 17 Resource model
**MVP: 3A (formulas) · 3B (measured values) · Tier 0. All figures are ESTIMATE until measured, or `REQUIRES REVIEW`; arithmetic is labelled as arithmetic.**

| Resource | Model | Value |
|---|---|---|
| Class, queue, capability | `AI_IO`, `ai`, `llm` (24 §3.1; GLOSSARY §6.6, §6.20) | fixed |
| LLM calls per plan | `ceil(M / agent_09.llm.batch_slots) + R`, `M` = slots sent to the model, `R` ≤ number of batches (one re-ask each) | cap: `resource_budget.max_llm_calls` and 07 §9 caps |
| Slots per video (arithmetic) | `≈ content_ms / g_target` for explanatory stretches (a shot every ≈ 4 s ⇒ ≈ 150 per 10 minutes, fewer when charts hold) | **REQUIRES REVIEW (Phase 1): MEASURED slots per finished minute in the pilot** |
| Tokens | input = prompt prefix (cached) + Σ slot data; output = Σ directions (closed enums + one short description each); Marathi excerpts cost more tokens than English (ADR-007 §2.9, measured in 3B) | **REQUIRES REVIEW (Phase 1): MEASURED tokens in and out per slot** |
| Cost per plan | `Σ calls (tokens_in × price_in + tokens_out × price_out)` with cache-read tokens at the cached rate; price rows from config (PR-01 lists tier prices, PR-02 the cache and batch multipliers); integer micros | ESTIMATE until the ledger reconciles; owner sets `resource_budget.max_cost_micros` (worst case = `max_output_tokens` × calls) |
| Wall time | `Σ call latency` (sequential unless `agent_09.llm.concurrency > 1`) + local compute | **REQUIRES REVIEW (Phase 1): MEASURED** |
| CPU | small: pure Python over a few hundred slots | **REQUIRES REVIEW (Phase 1): MEASURED** |
| Memory | holds the script document and the plan in memory (a few MB of JSON; arithmetic, not measured) | **REQUIRES REVIEW (Phase 1): MEASURED**; `RESOURCE.OOM` per 07 |
| Disk | plan blob ≈ 100 kB per 10 minutes (arithmetic, NFR-9), checkpoints similar; write-once | negligible |
| Network | outbound HTTPS to the LLM provider only | — |
| Concurrency | `agent_09.llm.concurrency` = 1 until provider limits are verified; one task per job at a time | design |
| Window | any time; honours `DRAIN`; not a `HEAVY_CPU` task, so the night-window drain does not stop its admission unless 06 says `AI_IO` is included | D1 |
| Retention | plan blobs are final job artefacts and never deleted by retention while the job's deliverables exist (04 §7); checkpoints expire with the job | **REQUIRES REVIEW (Phase 1): retention values** |

---

## 18 Errors and recovery
**MVP: 3A · Tier 0. Codes are exactly the 07 §2 catalogue; none is invented. Retry decisions belong to the policy engine (07 §3).**

| Situation | Code | Disposition |
|---|---|---|
| envelope or payload fails schema | `PERMANENT.SCHEMA_INVALID` / `SCHEMA_VERSION_UNSUPPORTED` | FAIL, L2 |
| wrong ID prefix; script hash differs from the verified hash; stage verdict blocked or approval missing; `aspect_ratio` not allowed for the type; hook ends after the window; timeline does not cover the script exactly or is `UNALIGNED` (second line, CCR-051); `previous_plan_ref` null at iteration ≥ 1; chart request unmatched; text not found in the script; chapter order broken | `PERMANENT.INPUT_INVALID` with `details.violations[]` (codes `SCRIPT_HASH_MISMATCH`, `VERDICT_NOT_ALLOWED`, `HOOK_WINDOW_EXCEEDED`, `TIMELINE_INCOMPLETE`, `TIMELINE_UNALIGNED`, `CHART_REQUEST_UNMATCHED`, `TEXT_NOT_IN_SCRIPT`, `CHAPTER_ORDER`, `VERTICAL_ANCHOR_MISSING`, `VERTICAL_ON_LANDSCAPE`, `REBASE_LIMIT`, `PREVIOUS_PLAN_MISSING`) | FAIL, L2 (orchestrator re-plans upstream) |
| org IDs disagree | `PERMANENT.TENANT_MISMATCH` | FAIL, L3 security |
| URI of another tenant (script, timeline, brand kit, memory, checkpoint) | `PERMANENT.CROSS_TENANT_REF` | FAIL + security event, L3 |
| script, narration timeline, brand kit, rule pack, approval or `previous_plan_ref` target row/blob absent | `PERMANENT.MISSING_DEPENDENCY` | FAIL, L2 |
| required config key unset (caps, windows, LLM keys), prompt file missing, or secret unreadable | `PERMANENT.CONFIG_INVALID` | FAIL, L3 operations |
| provider key rejected | `PERMANENT.AUTH_INVALID` | FAIL, L3 |
| provider refused the content | `PERMANENT.PROVIDER_REFUSAL` | FAIL, L2 → L3 if a compliance question |
| unsupported production type for this executor | `PERMANENT.UNSUPPORTED_TASK` | FAIL, L2 |
| same key, different request hash | `PERMANENT.IDEMPOTENCY_CONFLICT` | FAIL, L3 |
| LLM step returned `INSUFFICIENT_INPUT` | `PERMANENT.INSUFFICIENT_INPUT` | FAIL, L2 |
| `OUT_OF_SCOPE` / `CONFLICTING_INSTRUCTIONS` | `PERMANENT.INPUT_INVALID` | FAIL, L2 |
| `RULE_WOULD_BE_BROKEN` / `UNSAFE_CONTENT` for a batch | no error: declared item-level mapping (§8.4): fallback shots, `WARN` result `a09.q.visual_guard.refusal` with `blocking: false`, item surfaced to Agent 16 | `SUCCEEDED` unless the fallback share limit is exceeded |
| network, timeout, 5xx, 429 | `TEMPORARY.*` | RETRY (resume from checkpoint; completed calls skipped) |
| breaker `OPEN` | `INFRASTRUCTURE.CIRCUIT_OPEN` | NO-ATTEMPT until `open_until` |
| no `ACTIVE` provider budget row; estimate above the reservation | `RESOURCE.BUDGET_EXHAUSTED` | SUSPEND `AWAITING_BUDGET`; zero network calls when raised before the call |
| out of memory, disk full | `RESOURCE.OOM` / `RESOURCE.DISK_FULL` | per 07 |
| output not parseable / schema-invalid | `AGENT.INVALID_JSON` / `AGENT.OUTPUT_SCHEMA_INVALID` | RETRY once with the error appended, then DLQ |
| blob hash mismatch on a checkpoint or output | `AGENT.CORRUPTED_OUTPUT` | RETRY |
| success claimed but 03 §5.3 rule failed (a `SKIPPED`/`WARN` result emitted `blocking: true`, or `gate: true` from this non-gate stage) | `AGENT.INCOMPLETE_OUTPUT` | RETRY once |
| unhandled exception, stale heartbeat | `AGENT.CRASH` / `AGENT.HANG` | RETRY |
| a `blocking: true` check still failing after repairs and fallbacks; fallback share above `agent_09.fallback.max_share_permille` | `AGENT.QUALITY_REPEATED_FAILURE` | FAIL, L3 quality |
| any cap reached (`agent_09.max_slots`, a per-agent structural cap of 07 §9 declared in §24.2; batches, repairs, attempts, revision loops) | `AGENT.LOOP_CAP_EXCEEDED` | FAIL, L3 |
| host restart, worker lost, storage or DB outage | `INFRASTRUCTURE.*` | RETRY from checkpoint |
Safe defaults: when a measurement cannot be computed the check is never `PASS`; when a tenant, hash or verdict is unknown, deny. The plan is never "best effort": a failed guard replaces the shot with a fallback, a failed hard limit fails the task.

---

## 19 Security and permissions
**MVP: 3A · Tier 0 (designed for Tier 1+). Controls follow 08 §8 (five layers); Agent 09 states how it enforces each.**

### 19.1 Tenant isolation — how Agent 09 enforces it
| Layer (08 §8) | Agent 09 control | Test |
|---|---|---|
| 1 App filter | every DB read and write goes through `amw_core.tenancy` (`SET LOCAL app.org_id`, `app.actor = agent_09`); queries also carry explicit `org_id` predicates; `TenantScope.assert_consistent` compares the `org_id` of envelope, Task Input, every context ref and every payload ref before any step; script, verification output, narration timeline, previous plan, parent plan, brand kit, memory and checkpoints are resolved only inside that transaction | U-01, U-02, S-01 |
| 2 RLS | connects as `amw_app` (no bypass, not table owner); an unset tenant context returns zero rows, so a missing context fails closed as `MISSING_DEPENDENCY`, never as a read of another org | 04 §3.7 suite incl. `scripts`, `brand_kits`, `memory_items`, `checkpoints`, `cost_ledger`; S-02 |
| 3 Storage URIs | every URI read or written is compared with `app.org_id` before resolution (a `platform` URI only read-only); paths are built by `amw_core.storage` (`<root>/<org uuid>/…`), never from payload or script text; SHA-256 verified on every read; blobs write-once; Agent 09 handles no media files | S-03 |
| 4 Cache keys | any memo or clip of the LLM client uses `amw_core.tenancy.cache_key()` (`amw:<org wire id>:a09:<hash>`); a key without the org part is refused; the provider-side prompt cache prefix contains only the prompt file and platform-scope rule-pack text, never tenant data (tenant data and the tenant-scope pack `rp.tenant_brand_safety` follow the cache breakpoint, CCR-025), so a cache hit can never reveal another tenant's content | S-04, U-36 |
| 5 Logs and metrics | every line and metric carries `org_id`; no narration, `intent_text`, on-screen text or key is ever logged; unknown or rejected text leaves only as hashes and guard IDs; a canary-content test proves it | S-05 |
Further controls specific to this agent:
1. **One tenant per model call.** A batch contains slots of one task only; the adapter call carries no tool, no URL and no file handle, so the model cannot read or send anything beyond the JSON it returns.
2. **The model has no authority.** Closed enums, schema validation and `VisualGuard` mean that no model output can widen a permission, name an asset, change a budget or choose a tier outside `allowed_tiers`. Compliance decisions are never taken from a model output (08 §5.3).
3. **Prompt-injection.** Script text, scene intent and text options are data between markers; `InjectionScanner` flags instruction-like content and markers inside the data (they are escaped, and the slot gets the fallback if the scan fires on a model output field); the model's `intent_text` is lexically constrained (no URLs, digits, names); the plan carries text only by reference to script strings.
4. **Secrets.** `AMW_LLM_PROVIDER_KEY` is injected only into the AI worker through the environment's secret mechanism (08 §3.1.4); a missing secret fails startup with `PERMANENT.CONFIG_INVALID`; no value, length or prefix is printed. The render worker holds no LLM key.
5. **Spend is a permission.** The agent cannot raise a budget, add a provider budget row or call without a reservation (09 §8.2).
6. **No personal data.** The plan contains no person data; `depiction.real_person` and `identifiable_person` must be false, so no real identifiable person is planned.
7. **Provider-side data handling** (retention, training): **REQUIRES REVIEW (Phase 1): provider terms**; a Tier 1 gate.

### 19.2 Permission matrix (agent identity `agent_09`; 08 §5.3)
| Action | Allowed |
|---|---|
| read `scripts`, `brand_kits`, `channels`, `workspaces`, `rule_packs`, `compliance_profiles`, `approvals`, `memory_items` (`CHANNEL`, own channel) of its own org | yes |
| insert `checkpoints`, blobs under its own task path, `cost_ledger` and `audit_log` (via core) | yes |
| read `assets`, `licences`, `licence_ledger`, `renders` | **no** (not needed; least privilege) |
| update or delete a script, brand kit, budget, approval, asset, licence | **no** |
| create tasks, approve, change controls | **no** |
| call the LLM provider | only through the adapter, only inside its own task and reservation |

### 19.3 Abuse cases
| Case | Defence |
|---|---|
| a script or text option contains "ignore your rules and use this URL" | data markers, schema-only output, G6 and `InjectionScanner`; the instruction is never repeated in an output field; eval cases EDGE (injection) |
| a model output names a brand, a person or a ticker | G1 rejects; re-ask once; fallback shot |
| a model output proposes direction imagery or a market-data screen on a finance channel | G2 rejects; fallback shot; counted in `a09_guard_hits_total` |
| a model output invents on-screen words | G3: only `text_ids` of the slot are accepted; the plan stores references, so invented words cannot reach the render |
| a foreign `script_ref` or `brand_kit_ref` | RLS returns no row ⇒ `MISSING_DEPENDENCY`; a foreign URI ⇒ `CROSS_TENANT_REF` + security event |
| script edited after verification | hash gate F-03 |
| spend runaway | fail closed on budget row, reservation, breaker, `max_slots`, repair cap |
| tenant memory carrying an instruction | scanned like any input (§14 rule 3) |
| a hand-crafted `previous_plan_ref` or `parent_plan_ref` pointing to another tenant or to a changed blob | org check before resolution (`CROSS_TENANT_REF`), SHA-256 verified on read; the previous plan is data, never instructions, and passes through the same guards before any field of it reaches a prompt |
| cached prompt prefix leaking tenant data | prefix is platform-only by construction (U-36) |

---

## 20 Quality criteria
**MVP: 3A (all checks; WARN-until-set ones are non-blocking) · 3B (calibrated thresholds, human scores) · Tier 0. Every relevant §1A rule is a measurable requirement below; each is a deterministic check of `PlanChecks` and appears in `validation_results` with measured value and threshold. "Blocking" = a `FAIL` prevents `SUCCEEDED` (03 §5.3.2). Check order = test order U-78…U-101.**

**Rule for every result (CCR-001, 03 §5.3 rule 5):** a result whose verdict is `SKIPPED` (not computable, for example at iteration 0 or without a calibrated value) or `WARN` (WARN-until-set) is emitted with `blocking: false`; `blocking: true` is used only where a `PASS`/`FAIL` is computable. `s09_plan` is not a gate stage (24 §7.1a), so no result carries `gate: true`; a failing `blocking: true` result fails the task (§18). The default `blocking` column below is the value once the check is computable.

| # | check_id | §1A rule | Measurable criterion | Mirrors (18) | Blocking | MVP |
|---|---|---|---|---|---|---|
| 1 | `a09.q.schema` | §3.3 | output validates against `agent_09.shot_plan.output` 1.0.0 | — | yes | 3A |
| 2 | `a09.q.refs` | §1A.6 | `shot_id`s unique; every `segment_id`, `scene_id`, `section_id`, `chart_id`, `text_refs` entry exists in the script; every shot has `allowed_tiers` and a `fallback_template_key` (licence record needs a shot position, 18 §2.2) | `qc.licence.completeness` (position part) | yes | 3A |
| 3 | `a09.q.tiling` | §1A.6 dead air / black | main track tiles `[0, content_end_ms]` with no gap or overlap; `duration_ms = end − start`; `Σ duration = content_end_ms`; `total_duration_ms = content_end_ms + end_screen length` | `edit.dead_air`, `qc.duration.vs_timeline` | yes | 3A |
| 4 | `a09.q.cadence` | §1A.2 visual change every 3–5 s | in every `explanatory` stretch the gap between consecutive change events (shot starts and `change_events_ms`) ≤ `qc.visual.max_change_gap_ms` − margin; reports min and max gap; held exemptions listed with reason and ≤ `agent_09.held.max_ms` (unset ⇒ no exemption) | `edit.visual.cadence` (WARN until calibrated in 18) | yes for the max-gap limit in the plan (the plan can always meet it); the calibration remains Agent 10's WARN | 3A |
| 5 | `a09.q.hook_window` | §1A.2 hook = first 30 s | hook end ≤ `qc.hook.window_ms` (30 000); first payoff (end of `HOOK_PROOF`) ≤ 30 000 | `edit.hook.window` | yes (fails the task `INPUT_INVALID`) | 3A |
| 6 | `a09.q.hook_no_brand` | §1A.2 no logo/channel intro; §1A.8 sting after the hook | 0 elements of kind `BRAND_STING`, logo card or channel intro with `start_ms < hook_end_ms`; the sting (if any) starts at `hook_end_ms` | `edit.hook.no_brand_intro` | yes | 3A |
| 7 | `a09.q.first_shot` | §1A.2 | first shot starts at 0 ms, is not a `TEXT_CARD` made from brand or title material, and is a picture of the hook's proof beat (`HOOK_PROOF` segments inside it; for 9:16 the first `SHORT_HOOK` segment) | `edit.hook.window` | yes | 3A |
| 8 | `a09.q.interrupt_first` | §1A.2 interrupt at the first drop-off zone | ≥ 1 interrupt shot with `window = FIRST_DROPOFF` inside `[first_dropoff.start_ms, end_ms]` when set; while unset ≥ 1 `SCRIPT_PLANNED` interrupt in the first half (emitted `WARN`, `blocking: false`); device in the §1A.2 list | `edit.interrupt.first_dropoff` | no (`WARN`, `blocking: false`) until set; yes once set | 3A |
| 9 | `a09.q.interrupt_mid` | §1A.2 interrupt around the midpoint | ≥ 1 interrupt within `0.5·content_end ± half_width_ms` when set; else ≥ 1 script-planned in the section holding the midpoint | `edit.interrupt.midpoint` | no (`WARN`, `blocking: false`) until set; yes once set | 3A |
| 10 | `a09.q.jl` | §1A.2 J-cuts / L-cuts | applied J/L cuts ≥ `floor(eligible_boundaries / every_nth)`; each has `cut_offset_ms ≠ 0` and `jl_kind` consistent with its sign; skipped boundaries carry a reason | `edit.cuts.j_l` | no (`WARN`, `blocking: false`) until the rate is set; yes once set | 3A |
| 11 | `a09.q.end_screen` | §1A.2 end screen; §1A.8 | the last overlay is `END_SCREEN` starting at `content_end_ms`, length = config, containing only template content (no shot, no new text); tail silence listed as `deliberate_pause` | `edit.end_screen` | no (`WARN`, `blocking: false`) until the length is set; yes once set | 3A |
| 12 | `a09.q.chapters` | §1A.2 chapters | first chapter at 0 ms, strictly increasing, one per script section, each within ±1 000 ms of the section's measured start (exactly equal by construction); for 9:16 (no sections) `chapters = []` and the result is `SKIPPED`, `blocking: false` | `edit.chapters` (self-consistency part) | yes (long form) | 3A |
| 13 | `a09.q.tier_plan` | §1A.1 hierarchy; §1A.1e; §1A.11 | `allowed_tiers` in hierarchy order, tier C always present; planned worst-case `E_AI_STILL` share < `qc.visual.tier_e_max_share` (0.50, directive "never the majority"); planned `D_AI_VIDEO` ms ≤ `limits.ai_video_allowed_ms`; D/E absent when disabled | `qc.visual.tier_share_e`, `qc.visual.ai_video_budget` (planning side) | yes | 3A |
| 14 | `a09.q.charts` | §1A.1c charts by code from real data | every script `chart_request` has exactly one `CHART` shot whose span contains its `first_segment_id`; `chart_id` unique; no `CHART` shot without a request; `intent_text` empty (the model never describes data) | `qc.visual.chart_data_age` (data age is measured on the render by Agents 10/16) | yes | 3A |
| 15 | `a09.q.text_provenance` | no invented words | 100 % of `text_refs` resolve to a script `on_screen_text` or disclaimer slot string with the same SHA-256; 0 overlay or shot text outside references | FIN rules on on-screen text (13) | yes | 3A |
| 16 | `a09.q.disclaimer` | FIN-R10 (planning side) | each `DISCLAIMER` segment is covered by a `DISCLAIMER_CARD` or `TEXT_CARD` whose span ⊇ the segment span; no J/L shift moves it | FIN-R10 | yes (finance) | 3A |
| 17 | `a09.q.visual_guard` | §1A.1, §1B.2, YT-09 | 0 shots with `real_person`, `identifiable_person`, `brand_or_logo`, `ai_presenter` or `market_data_screen` true; on finance channels 0 with `market_direction_imagery` true; `intent_text` passes G1 | `qc.visual.no_synthetic_presenter` (planning side) | yes | 3A |
| 18 | `a09.q.vertical` | §1A.8 9:16 cut plan | for `9:16`: 100 % of shots have `vertical.subject_anchor` and overlays have `vertical_variant = true`; for `16:9`: `vertical = null`; numeric safe-zone check `SKIPPED` until the official zones are logged | `qc.shorts` (plan side) | yes (presence); the sub-result `a09.q.vertical.safe_zone` is `SKIPPED`, `blocking: false` | 3A |
| 19 | `a09.q.transitions` | §1A.6 no black / freeze | 0 `DIP_TO_BLACK`; `deliberate_black = []`; every transition in the allowed set; duration ≤ `transition.max_ms` and ≤ 20 % of the shorter neighbour; no static hold beyond the cadence limit without change events; `deliberate_hold[]` equals the intervals of the shots with `held` non-null (so Agent 10's `qc.video.freeze` has every planned hold) | `qc.video.black_frames`, `qc.video.freeze` (INF-09; 18 §7.3, §7.8) | yes | 3A |
| 20 | `a09.q.audio_plan` | §1A.4 music bed, licensed only | 3A: `music.bed = NONE`, `sfx_cues = []`; 3B: `bed = REQUESTED` only when `limits.music_library_enabled`, with the range −20.0…−15.0 dB; SFX cues (3C) only when `limits.sfx_library_enabled`; every cue references a licensed library flag in `limits` | `qc.audio.music_bed_offset` (18 §5; measured by Agent 10 on the stems; `SKIPPED` in 3A) | yes | 3A (none) · 3B (music) · 3C (SFX) |
| 21 | `a09.q.injection_scan` | §19.3 | 0 output strings with scanner hits (URL, instruction phrase, marker, control character) | — | yes | 3A |
| 22 | `a09.q.cost` | rule 8, §1A.11 | Σ ledger micros of the task ≤ `resource_budget.max_cost_micros`; calls ≤ `max_llm_calls` | S4 | yes | 3A |
| 23 | `a09.q.determinism` | NFR-1 | re-running the engine on the stored accepted directions reproduces the plan hash | — | yes | 3A |
| 24 | `a09.q.revision_addressed` | 24 §3.3 rules 1, 6 | at iteration ≥ 1 every `revision_feedback` item is resolved for its shot IDs; unchanged shots keep their IDs and `content_key`s; `SKIPPED` with `blocking: false` at iteration 0 | — | yes at iteration ≥ 1 | 3A |
### 20.1 Preconditions (`a09.pre.*`, not scored)
Evaluated before any model call (§7.4); a failure ends the task with the code shown and names the check ID in `details.violations[]` (§18). They are not part of the 24 quality checks and not scored:
| check_id | Precondition | Failure code |
|---|---|---|
| `a09.pre.tenant` | org equality of envelope, input, refs; every URI org-checked | `TENANT_MISMATCH` / `CROSS_TENANT_REF` |
| `a09.pre.refs` | every ref resolves under the tenant and its SHA-256 matches; `previous_plan_ref` present at iteration ≥ 1 | `MISSING_DEPENDENCY` / `INPUT_INVALID` |
| `a09.pre.script_gate` | script hash = verified hash; stage verdict allows (F-03) | `INPUT_INVALID` |
| `a09.pre.timeline` | narration timeline aligned and covering every segment (F-04), hook inside the window (F-06) | `INPUT_INVALID` |
| `a09.pre.config` | required config keys readable (F-05) | `CONFIG_INVALID` |
| `a09.pre.budget` | active provider budget row, reservation covers the worst case, breaker closed | `BUDGET_EXHAUSTED` / `CIRCUIT_OPEN` |
Sub-results: `a09.q.vertical.safe_zone` (check 18, `SKIPPED`), `a09.q.visual_guard.refusal` (check 17, `WARN` per refused batch, `blocking: false`, §8.4).

Scores outside this agent (Agent 16): VISUAL_QUALITY (15) and EDITING_QUALITY (10) deterministic parts read Agent 10's measurements; this agent supplies the plan evidence (18 §9.2). Human rows (owner look-and-feel, edit feel) are the owner's; the human score wins on conflict (§1A.7).
**Not a quality claim:** the plan guarantees only that the *planned* rhythm meets the limits; the rendered file's cadence is verified on the MP4 by `edit.visual.cadence_render_crosscheck` (Agent 10).

---

## 21 Tests
**MVP: 3A (all categories) · 3B (live smoke, calibration runs) · Tier 0. No paid call in any test except the single owner-authorised live smoke (27 §8). Numbers refer to rows of §10 and §20.**

| Category | IDs | What |
|---|---|---|
| Unit | U-01…U-121 | one group per function of §10 (group ranges in the "Tests" column); U-115 `UNALIGNED` or null-time narration timeline refused `TIMELINE_UNALIGNED`; U-116 Shorts script: `SHORT_HOOK` hook end, `chapters = []`, chapters check `SKIPPED` with `blocking: false`, `section_id` null; U-117 `deliberate_hold[]` equals the `held` intervals and `deliberate_black = []`; U-118 `views.*` items equal the shot objects and validate against §8.1.1; U-119 `previous_plan_ref` required exactly at iteration ≥ 1, rebase keeps shot IDs when the timeline hash changed; U-120 every `SKIPPED`/`WARN` result has `blocking: false`, no result has `gate: true`; U-121 refusal mapping of §8.4 (`RULE_WOULD_BE_BROKEN`, `UNSAFE_CONTENT` ⇒ fallback + `WARN`; fallback share above the limit ⇒ `AGENT.QUALITY_REPEATED_FAILURE`); U-19…U-26, U-30…U-33, U-49…U-58, U-64…U-67, U-73…U-75 and U-115…U-120 are table-driven from `evals/agent_09_video_director/timeline_engine/cases.jsonl` (TE-01…TE-39); U-78…U-101 are one pass and one fail fixture per check of §20 (U-78 = `a09.q.schema` … U-101 = `a09.q.revision_addressed`) |
| Integration | IT-01 whole task on the fake LLM adapter with a 16:9 sample script; IT-02 9:16 child plan with parent reference; IT-03 revision iteration with feedback (shot IDs of untouched shots stable); IT-04 the plan consumed by the Agent 08 query-plan input builder (field-level contract); IT-05 the plan consumed by a stub Agent 10 timeline compiler (tiling, overlays, chapters); IT-06 revision iteration after a changed narration timeline (`previous_plan_ref`, rebase inside the task, shot IDs kept) | `FakeLlmAdapter` with scripted responses; real PostgreSQL with RLS, two orgs |
| Contract | C-01 input schema; C-02 output schema (JSON Schema ⇄ Pydantic equality); C-03 step schemas equal the prompt file's schema (27 §4.4); C-04 Task Output envelope (03 §5, success rule); C-05 shot object fields vs `agent_08/search_query_plan.v1` and `candidate_rank.v1` inputs; C-06 chapters vs agent_05 `chapters[]` shape; C-07 `plan_ref` equals Agent 08's `shot_plan_ref` fields and `views.agent_11_subjects[]` equals Agent 11's `subject_hints` items | schema tests, no network |
| Regression (eval) | R-01 `shot_direction` golden dataset (judged, §26); R-02 `timeline_engine` dataset (deterministic) | eval gate, 27 §5–6 |
| Failure injection | FI-01 invalid JSON → one retry with the error → `AGENT.INVALID_JSON`; FI-02 schema-invalid output; FI-03 replay of a completed call → no second call, no second ledger row; FI-04 lost response after the call (unknown outcome) → re-sent once under the same key; FI-05 no `ACTIVE` budget row → zero network calls; FI-06 reservation below the estimate → `AWAITING_BUDGET`; FI-07 breaker `OPEN` → no attempt; FI-08 repair cap and `max_slots` → fallback / `LOOP_CAP_EXCEEDED`; FI-09 DLQ replay → identical plan hash; FI-10 kill after batch 2 → resume without repeating a call; FI-11 kill during the blob write → no partial file at a final path; FI-12 429 with `retry_after_ms` honoured, 5xx retried | 07 §12 patterns |
| Performance | P-01 engine time on a long synthetic script (a few thousand segments) stays inside a config bound (bound **REQUIRES REVIEW (Phase 1): set from the skeleton**); P-02 plan blob size per 10 minutes; P-03 memory of the engine; no LLM involved | pytest benchmarks, offline |
| Security | S-01 cross-tenant refs of every kind rejected with the §18 code; S-02 RLS: unset context yields zero rows, no superuser/BYPASSRLS role; S-03 storage paths built only by core; S-04 cache keys carry the org, prefix contains no tenant canary; S-05 log-leak: canary narration, `intent_text` and on-screen text never appear in logs, metrics, errors or audit; S-06 injection corpus in script, text options and memory never changes a field outside the schema; S-07 secret absent from config files, logs and fixtures; S-08 no network call other than the adapter (socket guard) | 04 §3.7 suite, 08 §8 |
| End to end | E-01 the 3A walking-skeleton path with a real script and the fake adapter, plan consumed by render (27 §9 tests 1, 2); E-02 pilot (3B): one owner-authorised capped run with the real adapter on the golden-sample topics; the owner reviews plan statistics and the rendered cadence | owner-authorised |
Coverage floor and CI gates: 27 §5 (ruff, mypy strict, pytest with coverage floor, prompt lint, eval gate when the prompt, tier or a rule pack changes).

---

## 22 Observability
**MVP: 3A · Tier 0. All logs are structured JSON through `amw_core.observability`; all metrics carry `org_id` and `agent_id = agent_09`; no content, secrets or person data (NFR-5).**

| Kind | Name | Labels (besides `org_id`, `agent_id`) |
|---|---|---|
| Counter | `a09_llm_calls_total` | `outcome` (`ok`, `retry`, `error`), `error_code`, `provider`, `model_ref` |
| Counter | `a09_llm_tokens_total` | `direction` (`in`, `out`, `cached_in`) |
| Counter | `a09_guard_hits_total` | `guard` (G1…G7) |
| Counter | `a09_repairs_total`, `a09_fallback_shots_total` | `reason` |
| Counter | `a09_budget_refusals_total` | `where` (`start_gate`, `reservation`) |
| Counter | `a09_check_results_total` | `check_id`, `verdict` |
| Counter | `a09_jl_skipped_total` | `reason` |
| Histogram | `a09_llm_latency_ms`, `a09_plan_wall_ms` | `provider` |
| Gauge (last value per job; `job_id` is a log field) | `a09_slots`, `a09_max_gap_ms`, `a09_min_gap_ms`, `a09_e_share_permille`, `a09_ai_video_ms`, `a09_jl_applied`, `a09_interrupts` | — |
Log events (fields: IDs, hashes, counts, check IDs): `plan.start`, `plan.tenant_ok`, `plan.script_gate`, `plan.timemap`, `plan.hook`, `plan.slots`, `plan.interrupts`, `plan.llm_call`, `plan.guard`, `plan.repair`, `plan.jl`, `plan.tiers`, `plan.checks`, `plan.checkpoint`, `plan.persisted`, `plan.done`.
Audit actions (registered here, 08 §9.2 rule; written through `amw_core.audit`): `shot_plan.started`, `shot_plan.completed`, `shot_plan.failed`, `shot_plan.guard_fallback`, `shot_plan.rebased`. `details` hold IDs, hashes and numbers only.
Traces: one span per task, child spans per LLM call and per engine phase. Alerts (proposed): guard hits rising on one channel (quality), fallback share above a config threshold (prompt or tier needs review), budget refusal (L3 finance), breaker open beyond `open_ms_max` (07 §7), `AGENT.QUALITY_REPEATED_FAILURE` (L3).
Evidence kept per plan (owner rule A.12; 18 §11 evidence package): the plan blob and a numbers-first statistics block (`stats`, `tier_budget`, `jl_cuts`, `interrupts`); the report tooling renders a timeline chart (shot lengths over time, interrupts, J/L marks) from that data. Agent 09 draws no chart itself.

---

## 23 Human approvals
**MVP: 3A (none inside the task) · 3B (owner scores of the plan's look and rhythm) · Tier 0.**

| Human act | Who | When | Kind | MVP |
|---|---|---|---|---|
| Optional script approval that precedes the plan | owner | before `s07_voice` in the 3A graph | `SCRIPT` / `owner_one_tap` (24 §3.4), upstream of this task; as every approval in 3A it is recorded by the operator from the owner's chat answer (D5) | 3A (optional) |
| Licensed-source decision for the music bed | owner | before 3B scoring (D6) | operator action enabling `limits.music_library_enabled` through a new production-type version (CCR-007); audited | 3B |
| Owner-set limits that shape the plan: AI-video seconds, whether AI stills are allowed, library flags, interrupt windows, J/L values, end-screen length | owner | before the pilot | operator action creating config / budget rows (audited) | 3A (limits) · 3B (calibration) |
| Visual and edit look-and-feel scores (VISUAL_QUALITY 3 points, EDITING_QUALITY 2 points, 18 §9.2) | owner | at `FINAL_VIDEO` approval | HUMAN rows in `quality_scores` | 3B (mandatory), sampled after |
| `FINAL_VIDEO` approval with ≥ 1 editorial contribution (the owner may contribute a visual angle or example) | owner | after `s16_score` | `FINAL_VIDEO` / `owner_one_tap` | 3A |
| `NEEDS_HUMAN_REVIEW` of a realism or copyright doubt raised on a plan view | owner | inserted by the orchestrator on Agent 16's verdict | `COPYRIGHT_DOUBT` / `owner_sensitive` | 3A |
| Rubric of the pilot's pacing (3B tuning of windows and gaps) | owner | pilot review | recorded in the evidence package; changes via config, then the eval gate | 3B |
Agent 09 never approves, never records a human check, and never waits for a human inside a task (a suspended task holds no worker, 03 §11.6).

---

## 24 Deployment
**MVP: 3A (development environment first; VPS only per ADR-012) · 3B (VPS sizing from measurement, INF-03/INF-04) · Tier 0. No secret, host, address or port appears here (08 §11).**

### 24.1 Services
| Unit | Process | Task types | Capabilities | Window | Placement | MVP |
|---|---|---|---|---|---|---|
| Plan executor | inside `workers/ai_worker`, package `agent_09_video_director` | `agent_09.shot_plan` | `llm` | any time (light CPU, external API); obeys `DRAIN` | the factory Compose project | 3A |
The package is a library; no HTTP server, no public port; no render worker is involved.

### 24.2 Configuration and environment variables (names only; values never in this repository)
| Name | Kind | Purpose | Scope |
|---|---|---|---|
| `AMW_ENV` | plain | environment label | all services |
| `AMW_DB_APP_DSN_REF` / secret `AMW_DB_APP_PASSWORD` | reference / secret | login of role `amw_app` | workers |
| `AMW_LLM_PROVIDER_KEY` | secret | LLM provider key (the same secret name as agent_05 §24) | `ai_worker` only |
| `AMW_STORAGE_ROOT_REF` | plain | storage backend reference (ADR-005) | workers |
Config keys (not env; registered by this blueprint in `amw_core.config`, which rejects duplicates, CCR-019), **required** at startup unless marked optional: `agent_09.cadence.min_gap_ms` (3 000), `agent_09.cadence.safety_margin_ms` (optional), `agent_09.snap.tolerance_ms`, `agent_09.snap.min_slot_ms`, `agent_09.max_slots` (per-agent structural cap, 07 §9), `agent_09.llm.batch_slots`, `agent_09.llm.max_repairs_per_batch` (1), `agent_09.llm.concurrency` (1), `agent_09.llm.max_intent_chars` (240), `qc.hook.window_ms` (30 000), `qc.visual.max_change_gap_ms` (5 000; the one source of the cadence limit, owned by 18 §13; this blueprint defines no second key for it), `qc.visual.tier_e_max_share` (0.50); optional (feature off when unset): `agent_09.held.max_ms`, `agent_09.interrupt.first_dropoff.start_ms/end_ms`, `agent_09.interrupt.midpoint.half_width_ms`, `agent_09.jl.offset_ms` (PROPOSAL 400), `agent_09.jl.every_nth` (PROPOSAL 2), `agent_09.transition.max_ms`, `agent_09.sting.max_ms`, `agent_09.end_screen.length_ms`, `agent_09.pacing.hook_gap_ms`, `agent_09.tier.d_enabled` (false), `agent_09.tier.d_max_ms`, `agent_09.tier.e_plan_fraction`, `agent_09.chapter_cards.enabled`, `agent_09.fallback.max_share_permille` (**PROPOSAL** 500; calibrate in 3B), `agent_09.llm.fallback_on_unavailable` (false); model keys `llm.agent_09.shot_plan.direction.*`; eval keys `evals.agent_09.*`. Startup check: each required key and secret name must be readable, else `PERMANENT.CONFIG_INVALID`; no value, length or prefix is printed.

### 24.3 Health checks
| Check | Type | Passes when |
|---|---|---|
| liveness | process | the worker loop heartbeats the queue lease |
| readiness | dependency | DB reachable under `amw_app` with a probe transaction for a random org returning 0 rows; storage reachable; required config keys set; the `LlmAdapter` loads; the prompt file `shot_direction.v1` exists, its SHA-256 equals the recorded one and its schema equals the Pydantic model (27 §4.4); `current_user` is not a superuser or `BYPASSRLS` |
| provider | not a worker health check | outages are handled by the breaker (07 §4) |
A failed readiness check means the worker does not claim `agent_09.shot_plan` tasks.

### 24.4 Start and stop order
Start: database (migrations only by the deploy step) → storage → orchestrator and queue functions → shared services (S4 cost guard, audit) → AI worker. Stop: stop claiming; at `DRAIN` finish the in-flight call, checkpoint, release the lease; then workers → services → orchestrator → database.

### 24.5 Release and rollback
A released prompt is immutable; any prompt, tier or rule-pack change is `v<N+1>` or a config change and runs the eval gate (27 §5) before merge. Engine changes (config defaults, algorithm) re-run the `timeline_engine` dataset. Rollback is the previous package, prompt and config version; written blobs are write-once and unaffected. No migration is written in this phase; this agent needs none.

---

## 25 Acceptance criteria
**MVP: 3A · Tier 0. Each criterion is testable and names its test. Pass = all green in CI (no paid call) and, for E-tests, the owner-authorised capped run.**

| ID | Criterion (rule) | Test |
|---|---|---|
| AC-01 | A plan is produced only for the script version Agents 06/16 checked (hash and verdict); a blocked or edited script yields `INPUT_INVALID` and no model call (§1B.2) | U-05…U-08, TE-27 |
| AC-02 | Shots tile the timeline exactly: first at 0 ms, no gap or overlap, last ends at the narration end (§1A.6 dead air/black) | U-80, TE-10 |
| AC-03 | In every explanatory stretch, the gap between change events is ≤ 5 000 ms (≤ the directive limit minus margin); held exemptions are listed with a reason (§1A.2 visual change every 3–5 s) | U-19…U-26, U-81, TE-01…TE-09, TE-31, TE-32 |
| AC-04 | The hook ends within 30 000 ms or the task fails `INPUT_INVALID` with `HOOK_WINDOW_EXCEEDED`; first shot starts at 0 ms (§1A.2 hook) | U-15…U-17, U-82, U-84, TE-11, TE-12 |
| AC-05 | No brand sting, logo or channel intro starts before the hook ends; the sting starts at `hook_end_ms` when the brand kit has one (§1A.2, §1A.8) | U-59, U-83, TE-13, TE-14 |
| AC-06 | A pattern interrupt exists in the first drop-off window and at the midpoint once the windows are set, and in the script-planned scenes before; the device is from the §1A.2 list; a failing model answer is replaced by a code-made `ZOOM` (§1A.2) | U-30…U-33, U-85, U-86, TE-15, TE-16 |
| AC-07 | J/L cuts are applied on eligible sentence boundaries with the configured offset; never at the hook end, next to a disclaimer or before a chart (J), and never past the gap limit (§1A.2) | U-49…U-53, U-87, TE-17…TE-22 |
| AC-08 | A reserved end-screen segment closes the timeline, with no new content (§1A.2, §1A.8) | U-64, U-65, U-88, TE-23 |
| AC-09 | Chapters come from the script's sections, first at 0 ms, strictly increasing, equal to measured section starts (§1A.2) | U-66, U-67, U-89, TE-24 |
| AC-10 | Every shot lists `allowed_tiers` in hierarchy order with a tier-C fallback; worst-case tier-E share < 0.50; AI-video ms ≤ the owner-set budget; D and E absent when disabled (§1A.1, §1A.11) | U-54…U-58, U-90, TE-25, TE-26 |
| AC-11 | Charts are planned only from script chart requests, one `CHART` shot each, never described by the model (§1A.1c) | U-27…U-29, U-91, TE-31 |
| AC-12 | No on-screen word exists that is not a script string (by SHA-256); the model cannot write text (§1B.2; 13) | U-40…U-43, U-92, R-01 |
| AC-13 | No planned shot contains direction imagery (finance), a market-data screen, an AI presenter, a real identifiable person, or a brand/logo (§1A.1, §1B.2, FIN-R11, YT-09) | U-40…U-43, U-94, R-01 (mandatory thresholds) |
| AC-14 | The 9:16 plan is a re-edit with an anchor on every shot and vertical overlay variants; the 16:9 plan has none (§1A.8, 18 §10) | U-70…U-72, U-95, TE-30, IT-02 |
| AC-15 | No dip to black; transitions only from the allowed set and within the duration limits (§1A.6) | U-47, U-48, U-96, TE-33 |
| AC-16 | In 3A the plan requests no music and no SFX; in 3B a music bed is requested only when `limits.music_library_enabled` and with the −20.0…−15.0 dB range; any SFX cue (3C) references a licensed library (§1A.4, ADR-009, D6) | U-68, U-69, U-97, TE-38 |
| AC-17 | One LLM call per (`task_id`, `step_key = direction.bNN`, `call_seq`); replay creates no second call or ledger row; the plan blob is write-once (03 §9.2) | U-104, FI-03, FI-09 |
| AC-18 | No LLM call without an `ACTIVE` provider budget row, a covering reservation and a closed breaker; zero network calls in those cases (D1, 09 §8) | U-105, FI-05…FI-07 |
| AC-19 | Kill during a run resumes from the checkpoint with no repeated call and no partial file at a final path (07 §8) | FI-10, FI-11 |
| AC-20 | Cross-tenant refs of every kind are rejected with the §18 code and a security event; nothing of another tenant is read, cached or logged (rule 9, 08 §8) | S-01…S-04, U-01, U-02 |
| AC-21 | No narration, `intent_text`, on-screen text or key in logs, errors, metrics or audit (NFR-5) | S-05, S-07 |
| AC-22 | A revision iteration changes only the shots named in the feedback and keeps the other shot IDs; the feedback is resolved (24 §3.3.1) | U-113, U-114, U-101, IT-03 |
| AC-23 | Every output validates against its §8 schema; `SUCCEEDED` only when every blocking check passes (03 §5.3) | C-01…C-04, U-78 |
| AC-24 | Datasets of §26 pass at the §26.4 thresholds | R-01, R-02 |
| AC-25 | Models, providers, thresholds, windows, offsets and keys appear only as config or secrets (rule 5) | config lint, S-07 |
| AC-26 | The owner's look-and-feel and rhythm scores are recorded for each golden sample (§1A.10, 3B) | E-02, 18 §11 |
| AC-27 | A narration timeline with `source = UNALIGNED` or a null segment time is refused `PERMANENT.INPUT_INVALID` `TIMELINE_UNALIGNED` with no model call; there is no estimated mode (CCR-051) | U-115, TE-34 |
| AC-28 | A Shorts plan has `section_id = null`, `chapters = []`, chapters check `SKIPPED` (`blocking: false`), and its hook is the `SHORT_HOOK` beats (CCR-003) | U-116, TE-35, TE-36, IT-02 |
| AC-29 | `deliberate_hold[]` lists every planned hold and `deliberate_black[]` is empty, with the names of 18 §7.3, §7.8 | U-117, TE-37 |
| AC-30 | Every `SKIPPED` or `WARN` result has `blocking: false`; no result has `gate: true`; `SUCCEEDED` only when every `blocking: true` result is `PASS` (03 §5.3) | U-120, TE-39 |
| AC-31 | A revision iteration reads the previous plan from `previous_plan_ref` only (no `TASK` memory); `previous_plan_ref` is null exactly at iteration 0 (24 §3.3 rule 6) | U-119, IT-03, IT-06 |
| AC-32 | A refused batch degrades to fallback shots with a `WARN` result and a view entry for Agent 16; the fallback-share limit fails the task `AGENT.QUALITY_REPEATED_FAILURE` (27 §4.3 declared mapping) | U-121, REF-24…REF-28 |

---

## 26 Prompt and evaluation pack
**MVP: 3A (prompt v1, datasets, deterministic checks) · 3B (thresholds calibrated on the golden samples; owner scores) · 3C (judge regression extended) · Tier 0.**

### 26.1 Statement
Agent 09 has **one LLM step** (`shot_direction`), so it has a prompt file and a judged golden dataset (27 §6). Its deterministic engine is also covered by a second, fully deterministic dataset, because most of the plan's quality rules are computed by code (§6). Both datasets run in CI without paid calls: the LLM dataset's online run happens only at the eval gate (27 §5) under the owner-authorised cap `evals.max_run_cost_micros`; its deterministic assertions can be re-run offline on stored outputs.

### 26.2 Paths
| Item | Path |
|---|---|
| Prompt file (v1) | `docs/v4/prompts/agent_09_video_director/shot_direction.v1.md` (prompt ID `agent_09/shot_direction.v1`) |
| LLM golden dataset | `docs/v4/evals/agent_09_video_director/shot_direction/` (`README.md`, `cases.jsonl` with 30 cases, `rubric.md`) |
| Deterministic engine dataset | `docs/v4/evals/agent_09_video_director/timeline_engine/` (`README.md`, `cases.jsonl` with 39 cases, `rubric.md` = statement that no judge is used; function-level dataset, 27 §6.1) |
| Judge prompt | `agent_09/shot_direction_judge.v1` — to be written with the first eval run (as for agent_06); **REQUIRES REVIEW (Phase 1): judge prompt and its human-labelled calibration subset** |

### 26.3 Deterministic checks and assertions
`shot_direction` (assertions A1–A14 listed in its README): schema validity, slot coverage and order, status equality, allowed intent kinds, vocabulary (no digits, URLs, names, Devanagari), depiction flags on finance channels, text IDs inside the slot's options, interrupt device inside `allowed_devices`, capability flags (`ai_video_allowed`, `still_allowed`), `subject_anchor` presence by aspect, refusal consistency, banned phrase absence, no injection echo. A case passes only if every assertion passes and every judge score meets `judge_min`. `timeline_engine`: exact expected slot counts and boundaries, tiling, hook verdict, J/L offsets and skipped reasons, tier allowances, error codes.

### 26.4 Pass thresholds (config `evals.agent_09.*`; design defaults, recalibrated after the golden-sample pilot)
| Threshold | `shot_direction` | `timeline_engine` |
|---|---|---|
| Answer-key case (historical-chart slot is never described by the model; call-like narration is not illustrated) | 100 % (mandatory) | — |
| Guard cases (direction imagery, market-data screen, real person, brand, invented text, injection) accepted although forbidden | **0** (mandatory) | — |
| Overall case pass rate | ≥ 0.90 (≥ 27 of 30) | **100 %** (a failing case is a defect, not noise) |
| False `NO_SAFE_VISUAL` on hard-negative cases (a safe picture exists) | ≤ 1 of 6 | — |
| Refusal cases (REF) returning the expected `refusal.reason` | 100 % | — |
| Mean judge score per criterion | J1 and J3 ≥ 4.0; J2 and J4 ≥ 3.5 | — |
| Cost and latency | recorded per case (p50 / p95, total cost per run; no threshold until measured, ESTIMATE) | — |
CI fails the PR if any mandatory threshold or any other threshold is missed. Recording fields per case per run: 27 §6.4.

### 26.5 Coverage summary
| Dataset | Cases | Categories |
|---|---|---|
| `shot_direction` | 30 | answer key (AK), positive paths in Marathi, Hindi and English, hard negatives (safe pictures that look unsafe), edge cases (interrupt slots, 9:16 anchors, capability flags, injection, empty text options, multi-slot batches with variety and continuity), refusals (all five reasons) |
| `timeline_engine` | 39 | slot counts and snapping, charts and held shots, hook (long form and Shorts), sting, interrupts, J/L, tiers, end screen, chapters, rebase, vertical, transitions, input gates (including `UNALIGNED`), deliberate intervals, music request, blocking-flag rule |

### 26.6 Revisit
When the 3B pilot changes windows, offsets or gaps, the `timeline_engine` cases that embed those values are updated in the same PR; when the pilot shows a recurring fallback pattern, the cases that reproduce it are added to `shot_direction`; when a concrete adapter exists, recorded provider fixtures (redacted, 27 §8.2) are added as extra cases.
