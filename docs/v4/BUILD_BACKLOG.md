# BUILD BACKLOG — 3A walking skeleton, milestones, 3B / 3C epics (Wave C)

Status: **Draft** (Wave C, docs only). As-built state read from `origin/main` at commit `5e70135` and from the open PR branches #48–#66. Nothing here is code; nothing here changes a contract (contract needs go to `CONTRACT_CHANGE_REQUESTS.md`).

Binding inputs: owner decisions D1 (3A / 3B / 3C order, no upload, no OAuth), D5 (owner chat → operator records), D6 (music blocks 3B), D8 (partial code start, lanes, one integrator), R-SYNC (contract change ships with its code sync) in `IMPLEMENTATION_PROGRESS.md`; `3A_SLICE_SPEC.md` §2–§14; `24_PRODUCTION_TYPES.md` §7.1a / §7.2a; `27_ENGINEERING_STANDARDS.md` §9–§10; `CONTRACT_CHANGE_REQUESTS.md` §4.7, §8, §9.

**Estimates.** All sizes are `ESTIMATE`, relative only (no hours, no tokens). Basis: lines of Python on `origin/main` and in the open branches, measured with `wc -l` / `git diff --stat`:
- **S** = a pass-4 follow-up PR (measured diffs 377–831 lines: #61, #65, #58).
- **M** = a small package (measured: `amw_adapters` 1,306 and `amw_evals` 1,301 source lines).
- **L** = an agent package (measured: 4,258 source lines for agent 11 up to 8,989 for agent 10, plus 2,000–5,800 test lines).

## 0. Findings that change the plan (verified against the repo)

1. **Ledger is stale.** `IMPLEMENTATION_PROGRESS.md` still says "Software: Planned. Nothing implemented". In fact core and the agent packages 04–11 and 16 are merged (§1). The ledger owner should update it. This document does not edit the ledger.
2. **Nothing executes a graph yet.** `packages/amw_orchestrator/src/amw_orchestrator/__init__.py` holds only a docstring. `workers/` and `apps/` do not exist. Every agent is a library tested against fakes. No agent stage has been called by a queue consumer.
3. **Only fakes exist for adapters.** Each `amw_adapters/<kind>/` has `protocol.py` + `fake.py` only (llm, tts, image, music, stock_footage, video_gen, web_fetch, file_delivery). There is no real LLM, TTS, web-fetch or file-delivery implementation.
4. **Agent persistence is in-memory.** Agents 08, 09 and 11 state it in their READMEs. Their ports (`ThumbnailRepository`, asset / licence / script stores) have no SQL implementation. Only `amw_core` has `pg.py` modules (audit, budget_guard, cost, job_store, queue, retries, system_functions).
5. **T0+ tables of 3A are missing.** Migrations create 60 tables, including `claims` (0054, #60). The tables `knowledge_collections`, `knowledge_sources`, `knowledge_chunks`, `citations`, `brand_kits`, `asset_fingerprints` (and `voice_consents`, needed only for a consented clone) are not created. 04 §9 creates T0+ tables "when their agent is built", and agents 04, 06, 08 and 11 are built. Agent 04's `library/sql.py` is tested against a scratch schema written from 04 §5.10, not against real migrations (its README says so).
6. **Blueprints for Agent 01 (orchestrator) and Agent 13 (delivery) are not on `main`.** They exist only as unmerged drafts on `claude/v4-wave-b2` (`agent_01_ceo_orchestrator.md`, `agent_13_publishing_delivery.md`). D8 rule 1 requires a fresh blueprint check before coding. **REQUIRES REVIEW (owner): does D8 (a) "minimal shared core" cover `amw_orchestrator`, `workers/*`, `svc_s07` and `agent_13.file_delivery`?** D8 lists contracts, state machine, job store, cost ledger, budget guard, audit, tenancy and adapters, and says "Not covered: the rest of the slice". Provisional default: these four need the owner's written go (one message can cover them) after their blueprint sections pass a fresh check.
7. **Migration number collision in open PRs.** `0055` is used by #54 (and #51, which merges #54) as `0055_evidence_review_code.sql` and by #61 as `0055_breaker_probe_timeout_bound.sql`. #58 uses `0056`. Whichever PR merges second must renumber above every merged number (04 §8 rule 5: merged migrations are never edited).
8. **Open PRs overlap on files** (the D8 rule 6 risk):
   - `agent_10_video_editor/qc/stage.py`: #56 (P4-12) and #59 (P4-21).
   - `amw_core/retries/pg.py`: #61 (P4-05) and #65 (P4-06).
   - `amw_core/interfaces/__init__.py`: #61 and #64 (P4-17).
   - `amw_core/owner_evidence_verifier.py`: #48 (P4-09), #54 (P4-01) and #51 (P4-19).
   - `CONTRACT_CHANGE_REQUESTS.md`: #51, #59 and #61.
   The merge order in §5 handles them.
9. **`amw_core.rulepacks` does not exist** (SOURCE_LAYOUT §2 rule 6 places rule-pack loading there). Agent 16 loads packs in its own `packs.py`, and agent 11 takes injected `Lexicons`. Rule-pack files with production content are 13 / rule-pack work and are not in the repo.

## 1. Status of the 3A tickets (`3A_SLICE_SPEC.md` §14)

Legend: **Done** = merged on `main`, acceptance met as far as the PR states. **Done (lib)** = library merged and tested against fakes; not wired into a graph run. **Follow-up open** = merged, with open follow-up PRs or listed gaps. **Partial** = some contents merged. **Not started**.

| # | Ticket | Status | Evidence | What is missing |
|---|---|---|---|---|
| 3A-01 | Walking skeleton | **Partial** | Scaffold #10; Step 0 contracts, Protocols and fakes #13; L1a tenancy, RLS, state machine, job store, queue #40; L1b cost ledger, budget guard, breakers, audit, idempotency #44; migrations 0001–0010, 0050, 0051, 0054; CI `.github/workflows/ci.yml` (PostgreSQL 18 service) | minimal orchestrator, workers, one real LLM call and one real TTS call (blocked by O1/O2), render on a render worker, approval + delivery, end-to-end 27 §9 tests 1–6 |
| 3A-02 | Core hardening | **Follow-up open** | `tests/failure_injection/` (breaker, DLQ replay, dispositions), `core_services/test_reaper.py`, `test_budget_guard.py`, `core_services_db/` | #65 P4-06 (audited breaker transitions, locked DLQ save, RECONCILE renewal), #61 P4-05 (probe bound), #63 P4-07 (currency exponent), P4-20 (stale "PROPOSED" wording still in `budget_guard/core.py` lines 6 and 14), P5-01 (`org_controls` value validation), P5-02 (`amw_platform_ops_summary()`, not in any migration) |
| 3A-03 | Registry and job intake | **Partial** | `amw_core/contracts/production_type.py` (`validate_production_type`, DAG checks), `contracts/owner_topic.py`, `tests/contract/test_ccr_rules.py` parses the 24 §7.1a / §7.2a tables | no `production_types` seed rows for `CHANNEL_LONG_FORM` v2 / `SHORTS` v2 (no INSERT in any migration), no job intake (J01–J03), no operator tool |
| 3A-04 | Agent 04 | **Follow-up open** | #35; `packages/agents/agent_04_research_knowledge/` | #55 P4-14; knowledge T0+ migrations (finding 5); PDF / EPUB / DOCX extraction "needs a library decision" (README); real model runs |
| 3A-05 | Agent 05 | **Done (lib)** | #33 | P4-10 `PRIOR_OUTPUT` input builder (orchestrator); LLM datasets are plumbing only (README) |
| 3A-06 | Agent 06 | **Done (lib)** | #32 | extraction fixtures hand-authored, judge J1–J4 not run (README) |
| 3A-07 | Agent 07 | **Follow-up open** | #37 | #66 P4-15; #59 P4-21 files CCR-175 (exact NFC matching kept for the pronunciation dictionary; no agent 07 code change); P4-17 TTS `capabilities()` / pace / emotion (#64) |
| 3A-08 | Agent 09 | **Follow-up open** | #29 | #49 P4-11; "not yet wired to the worker, DB or a real provider" (README) |
| 3A-09 | Agent 08 | **Partial** | #31 (title says "partial") | #62 P4-19 part; #59; SQL persistence, checkpoint persistence, budget / cost-ledger calls, `QueryPlanner` / `CandidateRanker` LLM wrappers, Devanagari shaping U-13 (README "Open items") |
| 3A-10 | Agent 10 | **Follow-up open** | #42; pinned FFmpeg build recorded in its README | #56 P4-12; #59; `font_reader` is `None` by default, so a render with on-screen text fails `FONT_COVERAGE_UNAVAILABLE` (`render.py` `_bind_text`); no market calendar ⇒ `NO_MARKET_CALENDAR` (fail closed, `guard.py`) |
| 3A-11 | Agent 11 | **Follow-up open** | #39, #50 (P4-16 merged) | resume from checkpoints (README open item 4); memory digest; OFL Devanagari font asset not chosen (item 7); package-local repository (item 2) |
| 3A-12 | Agent 16 gates | **Follow-up open** | #43 | #53 P4-13 |
| 3A-13 | Approvals (S7) | **Partial** | DB side: `0007_approvals_quality_delivery.sql`, `0009_owner_evidence.sql`; `amw_core/owner_evidence_*.py` with an in-memory `FakeEvidenceDatabase`; open #48, #54, #51 | no `svc_s07.request_approval` code (no match in `packages/`); no real session-record adapter (`interfaces/owner_evidence.py` docstring: "only the in-memory fake exists, and 3A approvals recorded through it are not production-verified"); P4-18 expiry; operator tool |
| 3A-14 | Full delivery bundle | **Partial** | `amw_adapters/file_delivery/` (Protocol + fake); `amw_core/cost/report.py` (file 6 data); `agent_16_compliance_qa/report.py` (QC-report section data) | no `agent_13.file_delivery` package, no manifest writer, no real bundle writer over `amw_core.storage` |
| 3A-15 | 9:16 cut | **Partial** | #33 `agent_05.shorts_adaptation`; `qc.shorts` profile in `agent_10/qc/gate.py`; vertical references in agents 08, 09, 10 | child-job creation (orchestrator, 24 §7.1a "child jobs"); `shorts_9x16` end-to-end run; linked bundle |
| 3A-16 | End-to-end acceptance | **Not started** | — | everything above |

## 2. The walking skeleton (D1)

**Target (D1):** owner topic → final MP4 16:9 (+ 9:16 where wanted) + 3 thumbnail options + SRT + QC report with the 100-point score + cost per stage + manifest, delivered as downloadable files. No YouTube upload, no Google OAuth.

The 27 §9 skeleton (script → TTS → render → QC → approval → delivery) yields no thumbnails and no 100-point score. The D1 bundle needs `s11_thumbs` and `s16_score`, and 3A keeps every blocking gate (`3A_SLICE_SPEC.md` §1). The smallest path that produces the D1 bundle is therefore the **`CHANNEL_LONG_FORM` v2 graph of 24 §7.1a with `s12_meta` disabled and `a_script` off**, plus the `SHORTS` v2 child job only when `shorts_wanted = true`. The skeleton is built in two steps:
- **WS-A:** the 27 §9 path, as 3A-01's acceptance.
- **WS-B:** the full v2 graph.

### 2.1 Stages, agents and readiness

| Stage (24 §7.1a) | Task type | Class / worker | Library | Adapter in the dry run | Real adapter needed for the first real run |
|---|---|---|---|---|---|
| intake | `amw.owner_topic` → job J01–J03 | operator tool | contract only | — | — |
| s04_research | `agent_04.research_pack` | AI_IO / ai_worker | merged | llm fake, web_fetch fake | llm, web_fetch |
| s05_script | `agent_05.script_draft` | AI_IO | merged | llm fake | llm |
| s06_claims, s06_verify | `agent_06.*` | AI_IO | merged | llm fake | llm |
| s07_voice | `agent_07.voice_synthesis` | AI_IO | merged | tts fake (synthetic narration) | tts, or the owner's recording (O4) |
| s07_master | `agent_07.audio_master` | HEAVY_CPU / render_worker | merged | local FFmpeg | — (local tool) |
| s09_plan | `agent_09.shot_plan` | AI_IO | merged | llm fake | llm |
| s08_assets | `agent_08.asset_sourcing` | AI_IO | partial (charts, code graphics, owner footage) | none (stock / AI tiers `TIER_DISABLED`) | none in 3A (stock only if bought, ADR-009) |
| s06_chart | `agent_06.claim_verification` `CHART_FACTS` | AI_IO | merged | llm fake | llm |
| s10_render, s10_subs, s10_qc | `agent_10.*` | HEAVY_CPU / render_worker | merged | local FFmpeg; font reader; market calendar | — |
| s11_thumbs | `agent_11.thumbnail_variants` | AI_IO | merged (needs Raqm and the system `libfribidi`) | llm fake | llm |
| s02u_unique, s16_comp, s16_score | `svc_s02.uniqueness_check`, `agent_16.*` | AI_IO | merged | llm fake | llm |
| a_final | `svc_s07.request_approval` `FINAL_VIDEO` | LIGHT | **missing** | fake session source (synthetic test org only) | real session-record adapter |
| s16_auth | `agent_16.publication_authorisation` | LIGHT | merged | — | — |
| s13_deliver | `agent_13.file_delivery` | LIGHT | **missing** | file_delivery fake → local storage | local-storage bundle writer |

### 2.2 Missing pieces as tickets

Lanes follow D8: **L1** is the only writer of `amw_core`, `migrations/` and contract-generated code. Each other lane owns one package. Lane names marked *new* are proposals.

| ID | Title | Depends on | Packages / files touched | Lane | Acceptance test | Size (ESTIMATE) | Risks |
|---|---|---|---|---|---|---|---|
| WS-00 | Merge the blocking open follow-ups (§5) in the order of §7.2; renumber the second `0055` | — | as each PR | L1 integrator + reviewer pool | `main` green after each merge (R-SYNC); `migrate` applies 0001…latest on PostgreSQL 18 | S per PR | rebase conflicts on the files of finding 8 |
| WS-01 | T0+ migrations for 3A: `knowledge_collections`, `knowledge_sources`, `knowledge_chunks`, `citations`, `brand_kits`, `asset_fingerprints` (`voice_consents` only if O4 = clone) | WS-00 | `migrations/00NN_*.sql`, generated enums if any (R-SYNC), `tests/tenancy/` | L1 | cross-tenant suite covers each new table; agent 04 `test_sql_integration.py` runs against the real migrations | M | 04 §5.10 Devanagari search config (ADR-013 `simple` fallback) |
| WS-02 | SQL implementations of the core repository Protocols (P4-17 #64: scripts, claims, assets / licences, renders, qc_results, quality_scores, compliance_verdicts, memory_items, knowledge reader, subject documents) and the shared font / template asset registry (`amw_core.storage`, SOURCE_LAYOUT §2 rule 6) | #64, WS-01 | `packages/amw_core/` (new `pg` modules), `tests/core_services_db/` | L1 | each repository passes the same contract tests as its fake, on PostgreSQL with RLS (`amw_app`) | L | agent-local ports (agent 11 `ThumbnailRepository`, agent 08 `testing/memory.py`) must move to the core Protocols; one lane edit per agent package |
| WS-03 | Registry seed and job intake (3A-03): load `CHANNEL_LONG_FORM` v2 / `SHORTS` v2 as `production_types` rows, J01–J03 checks (inputs, `DRAFT` channel, profile `rp.youtube_general` + `rp.finance_sebi_in`, `ACTIVE` budgets), minimal `amw_core.rulepacks` loader | WS-00 | `migrations/` (seed) or a registry loader, `amw_core/contracts`, `amw_core/rulepacks/` | L1 | graph DAG validation on the seeded record; J02 refuses a job with missing inputs or no budget (3A-03 acceptance) | M | rule-pack production content (FIN / YTG lists) is 13 work: tests use fixtures only |
| WS-04 | Orchestrator: a minimal DAG runner and state-machine driver (3A-01 part, 3A-02 part) that creates tasks and dependencies from the registry record, enqueues READY tasks, applies gate results and REVISE routes capped by `max_revision_loops`, derives J01–J12, parks approvals as `CHECKPOINTED / AWAITING_APPROVAL`, creates the `SHORTS` child job; input builders incl. P4-10 | WS-03; blueprint 01 check + owner go (finding 6) | `packages/amw_orchestrator/` (new code), `tests/orchestrator/` | *L-ORCH (new)* | graph run on fakes reaches `COMPLETED / DELIVERED`; a gate FAIL routes to its remedy stage; the 4th loop ends `BLOCKED_COMPLIANCE`; a replay creates no duplicate task | L | LLM-to-LLM control is forbidden (§2): every route must come from the registry record; scope creep into 3C hardening |
| WS-05 | Workers: `workers/ai_worker` and `workers/render_worker` entry points (claim via `amw_queue_claim`, lease / heartbeat, capability registration in `workers`, DI wiring of the agent stages, concrete adapters, SQL repositories); render worker wires `ProcessFfmpegRunner`, the market-hours guard and the font reader | WS-02, WS-04 | `workers/ai_worker/`, `workers/render_worker/` (new) | *L-WRK (new)* | kill a worker mid-render: the reaper re-queues it and the render resumes byte-identically (agent 10 FI-01 on the worker); a render outside the configured calendar is refused | L | `libfribidi` system dependency (agent 11 README); FFmpeg build pin (18 §7.0) |
| WS-06 | Font reader port and font asset: a cmap reader (fontTools, already pinned by agent 11) behind a core Protocol, wired into agent 10 `deps.font_reader` and agent 11 `FontProvider`; one OFL font with Devanagari coverage registered as a `FONT` asset with its licence text | WS-02; owner Q-O6 / R21 (provisional yes, OFL) | `amw_core` (Protocol, L1), `workers/render_worker` (wiring), font asset by the operator tool | L1 + L-WRK | a render with Marathi on-screen text passes F-09 / F-10; a missing glyph fails closed | S | the specific font is **REQUIRES REVIEW (owner)**: no font is named in RESEARCH_LOG; agent 08 charts still lack shaping (WS-11) |
| WS-07 | Approvals S7 (3A-13): `svc_s07.request_approval` (`owner_one_tap`, `owner_sensitive`, `SCRIPT` optional, `FINAL_VIDEO`), editorial contribution and human scores recorded by the operator with owner evidence, P4-18 expiry, verifier service under the `amw_verifier` role | WS-00 (#48, #54, #51), WS-04 | S7 code location **REQUIRES REVIEW** (provisional: `packages/amw_orchestrator/approvals/`, because S7 → 01); `amw_core` only through L1 | *L-S7 (new)* | the publish guard refuses delivery without approval and contribution (3A-13 acceptance); text from tool results is refused as evidence | M | the R14 rules are strict (role, origin, verbatim quote, review code, second confirmed event): do not weaken them for convenience |
| WS-08 | Real session-record adapter implementing `SessionEventSource` (R14) | WS-07 | `packages/amw_adapters/session_record/` (new) | L-S7 | a verified `CONFIRMED` evidence row from a real recorded owner message; a forged or paraphrased message is refused | M | **REQUIRES REVIEW**: which record of the owner's session the adapter reads, and how it authenticates it, is not specified in a merged doc; needed only for the first real run |
| WS-09 | Delivery bundle (3A-14): `agent_13.file_delivery` (files 1–7 of `3A_SLICE_SPEC.md` §4, one `publications` row per file, `delivery.file` idempotency), manifest with SHA-256, QC report and cost-per-stage report rendered from the merged report data, real bundle writer over `amw_core.storage`; operator export command | WS-02, WS-07; blueprint 13 check + owner go (finding 6) | `packages/agents/agent_13_publishing_delivery/` (file delivery only), `amw_adapters/file_delivery/` (real backend) | *L-A13 (new)* | bundle complete and verified; secret scan of the bundle finds nothing; a DLQ replay of `s13_deliver` writes no second bundle (27 §9 test 3) | M | the publish guard trigger (04 §5.21) must accept `FILE_DELIVERY` rows as written |
| WS-10 | Operator tool: create a job from `amw.owner_topic`, record approvals / contributions / scores, intake of owner material and datasets (R20), export the bundle and the audit / cost JSON | WS-03, WS-07, WS-09 | location **REQUIRES REVIEW** (provisional `apps/operator/`; SOURCE_LAYOUT lists no operator tool) | L-S7 | every command writes an audit row; there is no web endpoint | M | the owner does no CLI work (D5): only the operator runs it |
| WS-11 | Close the agent gaps on the skeleton path: agent 08 checkpoint persistence, budget / cost-ledger calls and Devanagari shaping in charts (U-13); agent 11 resume (FI-08); agents 08 / 09 / 11 switched to the core repositories | WS-02, WS-06 | agent 08, 09, 11 packages (one lane each) | L5 / L6 / L7 (existing agent lanes) | each agent's README "Open" list shrinks to items outside 3A; U-13 shaping test passes | M per agent | the agent 08 shaping library is not chosen (needs a dependency decision and RESEARCH_LOG entry) |
| WS-12 | Real adapters: one LLM provider (ADR-007), one TTS provider (ADR-008), `web_fetch` (CCR-015 caps); each with recorded fixtures and one `live`-marked smoke test under `live_smoke.max_cost_micros` | WS-00; ADR-007 / ADR-008 status | `packages/amw_adapters/llm/`, `tts/`, `web_fetch/` | *L-ADP (new)* | conformance tests shared with the fakes; the socket guard blocks every non-`live` call; a missing `PROVIDER` budget row refuses the call before any network request (09 §8.1) | M each | no live smoke may run before Q-O15 and O1 / O2 |
| WS-13 | 9:16 cut end to end (3A-15) | WS-04, WS-09 | orchestrator (child job), agents 09 / 10 (vertical templates) | L-ORCH + agent lanes | `qc.shorts` run; bundle linked by `parent_job_id` | M | Shorts spec R11 (1080×1920 is a PROPOSAL; "not validated for upload") |
| WS-14 | End-to-end acceptance (3A-16): 27 §9 tests 1–6 re-run on the full graph; evidence (before / after screenshots of the bundle and the QC report) for the owner | all above | `tests/e2e/` (new) | reviewer pool | the owner reviews the evidence; 3B may start | M | heavy CI time (§6) |

## 3. Milestones

### M1 — DRY RUN with fakes (proves the wiring, spends nothing)
- **Scope:** WS-00…WS-07, WS-09…WS-11 and WS-13, on the full v2 graph.
- **Components:** real PostgreSQL with RLS and real local FFmpeg / ffprobe. Every adapter is a fake. Narration is synthetic (TTS fake or a `lavfi`-generated signal, as the agent 10 integration tests already do). No network.
- **Tenant:** the synthetic test org only. The approval is recorded through the fake session source and is marked "not production-verified".
- **Proves:** every stage is reached through the queue. Gates and REVISE routes work. The budget breach stops the job. Audit and ledger exports verify. The bundle is complete. The cross-tenant suite passes.
- **Does not prove:** model quality, narration quality or real cost (all ledger rows are `ESTIMATE` 0), and nothing about the 100-point score's meaning. `s16_score` stays `REPORT_ONLY`, CCR-085.

| Owner input for M1 | Needed? |
|---|---|
| D8 coverage of orchestrator, workers, S7 and agent 13 (finding 6) | **yes**: one written go |
| Budgets, provider limits, keys | no. Test budget rows exist in the synthetic org; no paid call is possible |
| Topic | no. A synthetic fixture topic is used; the D8 item 7 provisional topic may be used as text only |
| Voice, music (D6) | no. Synthetic narration; no bed (`qc.audio.music_bed_offset` `SKIPPED`) |
| Market-hours calendar | no. A clearly labelled test-fixture calendar in test config. The guard still fails closed without one |
| VPS audit | no (development environment only) |

### M2 — FIRST REAL RUN (one owner topic, development environment)
- **Scope:** M1 plus WS-08 and WS-12. One owner topic goes through the v2 graph with real LLM and TTS calls, on the owner's tenant, with a real owner approval recorded per D5 / R14.
- **Exit:** the bundle is delivered, and the cost per stage carries `VERIFIED` rows where the provider reports usage.

| Owner input for M2 | Ref | Blocks |
|---|---|---|
| Spending limit set at each paid provider (LLM, TTS) | O1, D1, rule 8 | any paid call |
| Per-video and total pilot budget amounts and their currency | O1, R15, Q-O12 | the budget start gate |
| API keys through the environment's secret mechanism, from a separately billed API account | O2, A7, PR-03 | WS-12 live use |
| Live-smoke and eval caps | Q-O15 | the live smoke test of WS-12 |
| Topic confirmed (all `amw.owner_topic` fields; whether a 9:16 cut is wanted) | O3, D8 item 7 | job intake |
| Voice choice: TTS voice, consented clone, or the owner's recording | O4, R16, A6 | `s07_voice` |
| Market-hours sessions and holiday calendar | O7, R9 | every HEAVY_CPU task |
| FIN-R10 disclaimer draft text | R5 | `s16_comp` on a finance topic |
| FIN-R9 day basis (calendar or trading days) | R6 | chart data age |
| Provider data-retention terms decision | R19, Q-O5 | sending any material to a provider |
| Devanagari font (OFL default) | R21, Q-O6 | on-screen Marathi text |
| Course `data_pack` release for charts, if the topic uses a real chart | R20, Q22 | `s08_assets` chart path |
| `NEW_CHANNEL` decision for `audience_kind` | Q-O17 | otherwise YTG-R7 goes to `NEEDS_HUMAN_REVIEW` |
| VPS audit output and approval of a first VPS run | O6, A1, ADR-012 | **only** if rendering on the VPS (night window); otherwise not needed |
| Licensed music source | D6, Q-O8 | **not** M2 (technical run without a bed); blocks 3B |

## 4. 3B and 3C backlog (epic level)

### 3B — three golden samples scored by the owner (`3A_SLICE_SPEC.md` §10; 18 §11)

| Epic | Contents | Entry blockers |
|---|---|---|
| 3B-E1 Licensed music | Agent 08 `music_search` adapter for the chosen source, `MUSIC_BED` ledger rows, Agent 09 cue, Agent 07 mix; new registry version enabling the bed | **D6 / Q-O8** (owner purchase decision) |
| 3B-E2 Backup before keepable outputs | R10 off-server backup; CCR-143 (`sys_backup`, `amw_backup`, error codes, `backup_runs`) with its migration and code (P5-06) | R10 (owner purchase); CCR-143 trigger "before the first 3B golden-sample run" |
| 3B-E3 ESTIMATE → VERIFIED reconciliation | S4 reconciliation as a scheduled system job | **CCR-135** trigger (mechanism for scheduled system jobs) |
| 3B-E4 Runs and scoring | Three owner topics (D8 item 7 provisional: pullback basics, credit spread, position sizing). The owner scores each at `FINAL_VIDEO` with at least one editorial contribution | M2 done; budgets; narration choice + pronunciation dictionary v1; QC self-test (18 §7.11) |
| 3B-E5 Calibration | Judge calibration (`quality.score_gate_mode` `REPORT_ONLY` → `BLOCKING` decision, CCR-085, Q-O2); detector tolerances; uniqueness thresholds R7; prompt / template tuning with versioned evals; regression re-runs of topics 1–2; freeze | E4 scores |
| 3B-E6 Real-model evals | Recorded outputs for the LLM-step datasets (agents 05, 06, 08, 11 READMEs: plumbing-only today); judge J1–J4 runs within the eval cap | Q-O15; O1 / O2 |

### 3C — everything else (D1), with the deferred CCR triggers

| Epic | Contents | Deferred CCRs (DEFERRED-3C rows, §4.7) and trigger |
|---|---|---|
| 3C-E1 Orchestrator hardening and night scheduling | Agent 01 admission, night window, drain, `workers/scheduler`; S5 pressure gate; worker version check | CCR-135 / 136 (scheduled jobs, task types), CCR-137 (S5 samples: S5 gate built), CCR-138 (night-run record: Agent 01 night scheduler), CCR-142 (worker version: first worker from a separate image or host); P5-03 |
| 3C-E2 Publishing (Agent 13) | Private upload to a test channel first (27 §9), publish, verify; Google OAuth, `gcp_projects`, `oauth_tokens`; FIN-R9 / YTG-R8 re-check at publish | CCR-153 (client channel `CONNECTED`: first client connect, Tier 1); A4 / A5 |
| 3C-E3 Metadata, analytics, learning | Agents 12, 14; experiments; insights | CCR-146 (experiment transitions), CCR-147 (insight storage), CCR-152 (revenue entries) |
| 3C-E4 Strategy and growth | Agents 02, 03, 15, 17 | CCR-166 (`niche_scores`, `business.*`) |
| 3C-E5 Command Center, auth, portal | S8 dashboard, ADR-003 auth, ADR-004 stack | CCR-154 (credentials, sessions: ADR-003 accepted), CCR-156 (permission keys: each feature) |
| 3C-E6 Enterprise tiers | Onboarding, white label, SSO, DPA / notice / breach records | CCR-155 (onboarding, Tier 2), CCR-157 (`org_domains.purpose`), CCR-158 (DPA / breach: first client, Tier 1) |
| 3C-E7 Billing | S10 metering, invoices, gateway | CCR-163 (billing idempotency: ADR-010 accepted); owner questions Q-O20 / Q-O21 (CCR-164 / 165 NEEDS OWNER) |
| 3C-E8 Ads line and other production types | `AD_SPOT`, corporate, dubbing | CCR-160 (sector rule prefixes: each sector pack), CCR-161 (promotion flag, ad licence: first ad client) |
| 3C-E9 Localisation | S3 translation, native-speaker check as `SCRIPT` approval | P5-04 (CCR-144 / 145, applied or rejected; no trigger) |

Rule for every deferred CCR (P5-06): it is applied only with its migration, `ids.Prefix` / `ids.SystemActor` / `errors.CATALOGUE` entries and generated enums in the same change (R-SYNC).

## 5. Open P4 / P5 follow-ups and walking-skeleton blockers

PR numbers are from the open PR list (2026-11-19). "Blocks WS" = needed before M1 (dry run) or M2 (first real run).

| Ticket | PR | Change | Blocks WS? |
|---|---|---|---|
| P4-01 | #54 | evidence review code, migration 0055 | **M1** (S7 evidence, WS-07) |
| P4-02 | #58 | `channels.audience_kind` via `NEW_CHANNEL`, migration 0056 | M2 (Q-O17); M1 can run with NULL ⇒ `NEEDS_HUMAN_REVIEW` |
| P4-03 | — | breaker credential-scope CHECK | no (3C, first tenant credential) |
| P4-04 | #60 merged | `claims` table | done |
| P4-05 | #61 | breaker probe bound, migration 0055 (**collides**) | M1 (worker breaker admission) |
| P4-06 | #65 | audited breaker transitions, locked DLQ save, RECONCILE renewal | **M1** (failure-injection acceptance of 3A-02) |
| P4-07 | #63 | currency exponent as config data only | **M1** (the budget start gate fails closed without the currency entry) |
| P4-08 | #52 | confusables | no (quality of matching) |
| P4-09 | #48 | A6 quote in the owner-authored part | **M2** (real evidence); M1 only if WS-07 tests use it |
| P4-10 | — (not started) | input builders `previous_timeline_ref`, `PRIOR_OUTPUT` | **M1**: part of WS-04 |
| P4-11 | #49 | agent 09 reads `previous_timeline_ref` | M1 (revision path), with P4-10 |
| P4-12 | #56 | agent 10 narration asset, shot hash, finance decision from channel | **M1** (agent 10 inputs from real upstream outputs) |
| P4-13 | #53 | FIN-R6 mapping | no for wiring; yes for M2 correctness |
| P4-14 | #55 | agent 04 released chunks, `ext_` IDs | **M1** (s04 with real repositories) |
| P4-15 | #66 | agent 07 dataset edits | no |
| P4-16 | #50 merged | agent 11 text normalise | done |
| P4-17 | #64 | core Protocols, `ExecContext`, TTS capabilities, payload registry | **M1** (WS-02 builds on it) |
| P4-18 | — (not started) | `PENDING` → `EXPIRED` approvals | M2 (part of WS-07) |
| P4-19 | #51, #62 | owner-evidence and `asset_intake.*` audit verbs | **M2** (D5 audit); M1 for the WS-10 audit test |
| P4-20 | — (not started) | stale "PROPOSED" docstrings in `budget_guard/core.py` | no (cosmetic) |
| P4-21 | #59 | lexicon matching via `text_normalise` in agents 08 and 10; agent 07 kept on exact NFC matching through proposed CCR-175 | no for wiring |
| P5-01 | — | `org_controls` per-key validation | **M1** (J02 admission reads `org_controls`) |
| P5-02 | — | `amw_platform_ops_summary()` | no (S8, 3C) |
| P5-03 / P5-04 | — | blueprint items (Agent 01, lane 16) | P5-03 enters WS-04 if blueprint 01 is merged |
| P5-05 | — | DPDP Rules RESEARCH_LOG entry | no |
| P5-06 | — | rule for deferred CCRs | process rule |

## 6. Test-infrastructure debt

| # | Debt | Evidence | Effect | Proposed fix (ticket) | Size |
|---|---|---|---|---|---|
| T1 | **Shared-cluster contention of the cluster-role tests.** Migrations 0001, 0010 and 0051 create and re-grant cluster-global roles. Parallel sessions on one cluster fail with "tuple concurrently updated" or "must be able to SET ROLE" | `tests/pg_fixtures.py` `_one_migration_at_a_time` (host-wide file lock) | The lock serialises migrations only between processes on **one host**; lanes sharing a cluster from different worktrees wait on each other; the definer-hardening suites (`tests/tenancy/test_definer_hardening*.py`) assert on cluster-wide role state | TI-1: one PostgreSQL cluster per lane (several local PostgreSQL 16 clusters exist on the dev machine for this), and document it in the test README; keep the lock as a second line | S |
| T2 | **Host-dependent thumbnail determinism.** The agent 11 canary hash is recorded for Pillow 13.0.0 with Raqm 0.11.0, HarfBuzz 14.5.0 and FreeType 2.14.3. Raqm loads the system `libfribidi` | `tests/agents/agent_11_thumbnail_design/test_composer.py` `CANARY_SHA256`; agent 11 README "System dependency" | a different host library set changes the hash, so the test is not reproducible across hosts or CI images; the real-font test is skipped where no Devanagari system font exists | TI-2: pin the shaping stack in the worker image (and CI), record the library versions next to the hash and compare versions first (a version mismatch is an explicit failure, not a silent re-record); a committed OFL test font after WS-06 | S |
| T3 | **PostgreSQL 16 locally, 18 in CI** | `IMPLEMENTATION_PROGRESS.md` build facts; `ci.yml` `postgres:18`; agent 04 `test_sql_integration.py` "needs a local PostgreSQL 16" | a behaviour that differs between majors is seen only in CI; the 04 §1.9 major version is the target to confirm | TI-3: install PostgreSQL 18 locally (one cluster per lane) or make CI the only authority for DB suites and say so in each lane brief. **REQUIRES REVIEW**: the production major on the VPS (A1) | S |
| T4 | Agent coverage is measured per package (`coveragerc` in each agent folder; agent 08 README: "the root config does not measure agent packages") | agent READMEs | CI's single `pytest --cov` run does not enforce the 80 % agent floor of 27 §3 | TI-4: add the per-package coverage runs to CI (one job, still ≤ 3 heavy jobs) | S |
| T5 | FFmpeg integration tests take minutes (agent 10 README: "~5 min") and are skipped where FFmpeg is missing | agent 10 README "Tests" | heavy CI load; silent skip on a host without FFmpeg | TI-5: CI installs the pinned FFmpeg and runs the `integration` marker in its own job; a skip in CI fails the job | S |
| T6 | GitHub Actions pinned by tag, not SHA | `ci.yml` `TODO(ci-pin)` | supply-chain risk (27 §5) | TI-6: pin by commit SHA once the API host is reachable | S |

## 7. Critical path and parallelisation

### 7.1 Critical path
WS-00 (blocking subset of §5) → WS-03 and WS-01 (L1, serial) → WS-02 (L1) → WS-04 (orchestrator) → WS-05 (workers) → WS-07 + WS-09 + WS-10 → **M1 dry run** → WS-08 + WS-12 + owner inputs of §3 M2 → **M2 first real run** → WS-13 → WS-14 → 3B.

The critical path runs through **L1** (WS-00 merges, WS-01, WS-02, WS-03 are all shared core) and then through the new orchestrator lane. Owner gates sit at two points: finding 6 (before WS-04 / WS-07 / WS-09 code) and the M2 inputs.

### 7.2 Merge order of the open PRs (WS-00)
1. **L1 core, serial:** #63 (P4-07) → #52 (P4-08) → #48 (P4-09) → #54 (P4-01, migration 0055) → #51 (P4-19, contains #54) → #61 (P4-05: renumber its migration above the merged numbers; rebase `retries/pg.py` and `interfaces/__init__.py`) → #65 (P4-06, rebase on #61 for `retries/pg.py`) → #58 (P4-02, renumber if needed) → #64 (P4-17, rebase on #61 for `interfaces/__init__.py`).
2. **Agent PRs, in parallel (each lane owns its package):** #55 (04), #49 (09), #53 (16), #66 (07), #62 (08). Then #56 (10) **before** #59 (08 / 10, plus CCR-175), because both edit `agent_10/qc/stage.py`; #59 also touches agent 08, so it goes after #62.
3. Each merge needs CI fully green **and** a separate reviewer pass (D8 rule 5).

### 7.3 Lanes and concurrency
Rules applied: one integrator for shared core (L1), no two lanes on one module, at most **3 heavy CI jobs at once** on the 4-CPU dev machine (heavy = the full `pytest` with PostgreSQL, or the FFmpeg `integration` marker).

| Wave | L1 (core, serial) | Parallel lanes (one package each) | Heavy jobs at once |
|---|---|---|---|
| W1 | WS-00 core merges in the §7.2 order | agent PR rebases / merges 04, 09, 16, 07, 08, then 10 → #59; TI-1 / TI-3 set-up | ≤ 3: L1 + two agent lanes; the rest run affected tests only (`pytest -q` on their package) |
| W2 | WS-03, then WS-01 | blueprint 01 and 13 fresh checks (docs); L-ADP starts WS-12 against fakes and recorded fixtures (no live call) | ≤ 3: L1 + L-ADP + one reviewer run |
| W3 | WS-02 | L-ORCH WS-04 (after the owner's go); L-S7 WS-07 (after #48 / #54 / #51) | 3 |
| W4 | WS-06 (Protocol) | L-WRK WS-05; L-A13 WS-09; agent lanes WS-11 run affected tests only | 3: the full suites of L-WRK, L-A13 and L1; agent lanes wait their turn for a full run |
| W5 | integration fixes only | WS-10, WS-13; **M1 dry run** | 2: e2e plus one lane |
| W6 | — | WS-08, WS-12 live smoke (after Q-O15, O1, O2); **M2** | 1–2 |

Each lane runs its full suite once per wave (CLAUDE.md token discipline). Between full runs a lane runs only the affected tests. The reviewer pool reads diffs and needs no heavy job.

## 8. Open items of this backlog (REQUIRES REVIEW)
1. D8 coverage of the orchestrator, workers, S7 and Agent 13 code (finding 6). **Owner.**
2. Location of the S7 code and of the operator tool (WS-07, WS-10). Provisional defaults: `amw_orchestrator/approvals/` and `apps/operator/`. This is a SOURCE_LAYOUT decision for L1.
3. What the real session-record adapter reads, and how it authenticates it (WS-08). It is not specified in a merged document.
4. The agent 08 Devanagari shaping library and the OFL font (WS-06, WS-11). Both need RESEARCH_LOG entries.
5. Agent 04 document-extraction library (PDF / EPUB / DOCX) for the books (K1 answered). Not on the skeleton path: course notes and attached sources are the default (R8).
6. Blueprints 01 and 13 are on an unmerged branch; their Wave C verification is a prerequisite for WS-04 and WS-09.
