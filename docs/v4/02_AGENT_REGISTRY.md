# 02 — Agent Registry (the single registry other documents reference)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** (every agent and service below has feature status Planned, GLOSSARY §6.11) |
| Owner | Agent 01 (registry loader and execution); registry content kept by the documentation lead. Conflicts with the directive are decided by the owner, never locally |
| Depends on | MASTER_DIRECTIVE.md §3.1, §3.2, §2, §3.5.5; GLOSSARY_AND_IDS.md (§2.2 prefixes, §6.20 capabilities, §6.47 tier); 03_COMMUNICATION_STANDARD.md (task contract, state machine); 04_DATABASE_ARCHITECTURE.md; 07_FAILURE_MANAGEMENT.md; 24_PRODUCTION_TYPES.md §3.2 (task types, name-bound); 27_ENGINEERING_STANDARDS.md §7.2 (package names); 3A_SLICE_SPEC.md; IMPLEMENTATION_PROGRESS.md D1, D2; 00_EXECUTION_PLAN.md Q4 |
| Directive sections covered | §3.1 (core agent registry, binding), §3.2 (shared services S1–S13 and owners), §2 (stages are code-controlled; every service has a named owner; no new autonomous agents), §3.5.5 (one package per agent), §1C.15 (tiers) |
| Facts cited | RESEARCH_LOG: YT-09 (YPP inauthentic content, no AI persona on finance), IN-03 (no forward-looking statements on named securities), IN-08 (copyright posture), PR-01 / PR-03 (model routing; API billed separately from subscription), INF-01 (shared VPS) |
| Marking | **3A / 3B / 3C** = the owner's build stages (D1). **Tier 0–3** = enterprise tiers (GLOSSARY §6.47). Every row carries both |
| Conventions | `(pending CCR)` = name not in Wave A, filed by the integrator. `REQUIRES REVIEW (Phase 1): <need>` = value unknown, none invented. Public repository: no private method, book titles, course content or server details |

---

## 1. Purpose and rules of this registry

1. This is the one place that says **which agent or service exists, who owns what, which canonical task types it executes, and in which build stage it is built**. Other documents refer to it by agent ID and do not restate it.
2. The 17 agents are **pipeline stages of a code-controlled orchestrator (a state machine), not autonomous agents** (directive §2). No agent calls another agent; hand-offs are task contracts executed by Agent 01 (27 §7.1, SOURCE_LAYOUT §2).
3. **No new agents** beyond the 17 (§2). Support functions are shared services S1–S13 with a named owning agent (§3.2, plan Q4). A service is not an LLM agent unless an ADR justifies it.
4. Task type names are contract-bound (24 §3.2). This registry lists them as they are; it creates none. A blueprint that needs another one files a CCR (CONTRACT_CHANGE_REQUESTS.md).
5. Each agent's decision split (deterministic vs LLM) is **stated here in summary only**; the binding, row-level decision table is section 6 of its blueprint (directive §4, §2: "each stage states which decisions are deterministic rules and which are LLM judgements, and why"). Where this registry and a blueprint differ on that split, the blueprint decision table wins and this registry is corrected.
6. Principle that applies to all rows (§3.3 Quality): deterministic checks run first; an LLM score is never the only gate; an incomplete output is never marked successful. Models, providers and limits live in config (ADR-007), never in code (rule 5).
7. Conflict list required by directive §3.1 ("if the repo already has a registry with a different mapping, do not overwrite"): **none found**. The repository has no earlier agent registry; the only prior mapping is plan Q4 (S6 → 16, S7 → 01, S8 → 01), which this document adopts (section 4).

## 2. Build-stage and tier legend

| Mark | Meaning | Source |
|---|---|---|
| **3A** | Video production line: minimal shared core plus Agents 04–11 and the Agent 16 gates. Owner supplies the topic. Output is downloadable files: MP4 16:9 (+9:16 where applicable), thumbnail options, SRT, QC report with the 100-point score, cost per stage. **No YouTube upload, no Google OAuth.** | D1 |
| **3B** | Golden samples: three videos on owner-given topics, scored by the owner; prompts and templates tuned until all three reach the threshold. No new agent is first built in 3B. | D1 |
| **3C** | Everything else: orchestrator hardening, scheduler / night window, Agent 13 publishing, 14 analytics, 02 / 03 strategy, tenancy UI, client portal, billing. | D1 |
| **Tier 0–3** | Enterprise tier at which the capability is needed: 0 internal (platform owner only), 1 first managed-service client, 2 self-serve, 3 enterprise. Built only when a paying client needs it (§1C.15). | GLOSSARY §6.47 |

Constraints that hold for every row: paid calls only within owner-set provider limits with per-video and pilot budgets enforced and a stop on breach (09 §8); keys only through the environment secret mechanism (08 §3); render never in market hours (ADR-012).

## 3. Core agent registry (directive §3.1, binding)

### 3.1 The binding table

Rows 01–17 are the directive §3.1 table. The "Owns" column is reproduced as written there (summarised only by joining wording).

| ID | Agent | Owns (incl. merged enhancement capabilities) |
|---|---|---|
| 01 | CEO & Master Orchestrator | workflow engine, scheduling, priorities, dependencies, resource admission, night scheduler, morning shutdown, workflow optimisation proposals |
| 02 | Market Intelligence | trend discovery, predictive content intelligence (with confidence + evidence), competitor early-warning (public/authorised data only) |
| 03 | Content Strategy | pillars, personas, channel positioning, topic clusters, intelligent multi-channel calendar, content gap analysis, content investment decision engine |
| 04 | Research & Knowledge | source discovery, reliability scoring, evidence store, citation tracking |
| 05 | Scriptwriter | narrative, hooks, scene-level script, retention-informed writing, Marathi/Hindi/English |
| 06 | Fact Checker | claim extraction, independent verification, contradiction detection, approval |
| 07 | Voice Production | TTS adapters, pronunciation dictionaries, audio mastering engine (loudness, clipping, silence, noise, sync) |
| 08 | Visual Assets | generation, licensed sourcing, provenance, asset library + reuse engine (fingerprints, licence, expiry, channel permission) |
| 09 | Video Director | scene/shot plan, timeline, cinematic editing intelligence (pacing, B-roll, music, transitions) |
| 10 | Video Editor | FFmpeg render pipeline, resumable rendering, subtitles + accessibility, automated video inspection (integrity, duration, resolution, fps, aspect, black frames, missing audio, A/V and subtitle sync) |
| 11 | Thumbnail Design | concepts, variants, brand consistency, Test & Compare workflow |
| 12 | SEO & Metadata | keywords, titles, descriptions, chapters, SEO validation |
| 13 | Publishing & Delivery | destination adapters (YouTube first; client file delivery with masters + platform-specific exports; other platforms later), OAuth, resumable upload (private first), approval gate, scheduling, duplicate prevention, publish verification, synthetic-media disclosure/labels per destination |
| 14 | Analytics | ingestion, retention/CTR/watch-time analysis, retention intelligence, attribution, autonomous learning loop data |
| 15 | Growth & Revenue | revenue intelligence, production economics, sponsorship/affiliate tracking, channel profitability |
| 16 | Compliance & QA | copyright/licence records, originality gate, YPP inauthentic-content gate, disclosure check, compliance rule packs incl. advertising (§1D), editorial quality gate, publication authorisation |
| 17 | Brief & Creative Strategy | client/campaign brief intake and clarification questions, audience and objective, creative concepts and variants, ad scripts and storyboards per format, claim list sent to 06/16 for substantiation, usage-rights and talent/likeness checklist, client approval of concept before production (only used for client and ad Production Types; owner channels use 03) |

### 3.2 Per-agent registry record

Columns: **Package** = 27 §7.2 (also the `prompts/` and `evals/` folder name). **Task types** = 24 §3.2 exactly; "none" = no canonical task type exists in 24 §3.2 for this agent (internal function of the orchestrator or a non-task component). **Build** = D1 stage and enterprise tier of the first usable version. **Blueprint** = path under `docs/v4/`; only `agent_04_research_knowledge.md` exists at the time of writing, the others are planned at the stated path (directive §4).

| ID | Package (27 §7.2) | Canonical task types (24 §3.2) | Build | Blueprint |
|---|---|---|---|---|
| 01 | `agent_01_ceo_orchestrator` (code package `amw_orchestrator`) | none as an executed task. Materialises and runs every graph (03 §11.3 T01–T19); hosts `svc_s07.request_approval` (S7 → 01) | **3A** minimal DAG runner, ADR-012 guards, Tier 0. **3C** hardening, scheduler, night window, admission, morning shutdown | `agents/agent_01_ceo_orchestrator.md` (planned, Wave B-2) |
| 02 | `agent_02_market_intelligence` | `agent_02.trend_scan` (optional) | **3C**, Tier 0 (owner channel). Not in 3A (owner gives the topic, D1) | `agents/agent_02_market_intelligence.md` (planned) |
| 03 | `agent_03_content_strategy` | `agent_03.topic_selection` | **3C**, Tier 0. In 3A the owner's topic replaces the `s03_topic` stage (3A_SLICE_SPEC §2.5, CCR-3A-1 pending) | `agents/agent_03_content_strategy.md` (planned) |
| 04 | `agent_04_research_knowledge` | `agent_04.research_pack`; `agent_04.knowledge_ingest` (pending CCR, ADR-013) | **3A**, Tier 0 | `agents/agent_04_research_knowledge.md` (exists) |
| 05 | `agent_05_scriptwriter` | `agent_05.script_draft`; `agent_05.shorts_adaptation` (9:16 cut only) | **3A**, Tier 0 | `agents/agent_05_scriptwriter.md` (planned) |
| 06 | `agent_06_fact_checker` | `agent_06.claim_extraction`; `agent_06.claim_verification` | **3A**, Tier 0 | `agents/agent_06_fact_checker.md` (planned) |
| 07 | `agent_07_voice_production` | `agent_07.voice_synthesis`; `agent_07.audio_master` | **3A**, Tier 0 | `agents/agent_07_voice_production.md` (planned) |
| 08 | `agent_08_visual_assets` | `agent_08.asset_sourcing` | **3A**, Tier 0 (asset library and reuse engine grows in 3B / 3C; licence-ledger row per shot is 3A) | `agents/agent_08_visual_assets.md` (planned) |
| 09 | `agent_09_video_director` | `agent_09.shot_plan` | **3A**, Tier 0 | `agents/agent_09_video_director.md` (planned) |
| 10 | `agent_10_video_editor` | `agent_10.render`; `agent_10.subtitles`; `agent_10.technical_qc` | **3A**, Tier 0 (render per ADR-012: dev environment or VPS night window, never market hours) | `agents/agent_10_video_editor.md` (planned) |
| 11 | `agent_11_thumbnail_design` | `agent_11.thumbnail_variants` | **3A**, Tier 0 (3 variants, YT-08) | `agents/agent_11_thumbnail_design.md` (planned) |
| 12 | `agent_12_seo_metadata` | `agent_12.metadata` | **3C**, Tier 0. Optional stage in the 3A graph; not used in 3A (3A_SLICE_SPEC §2.4) | `agents/agent_12_seo_metadata.md` (planned) |
| 13 | `agent_13_publishing_delivery` | `agent_13.file_delivery` (**3A**); `agent_13.upload_private`, `agent_13.publish`, `agent_13.verify_publication` (**3C**) | **3A** file delivery only, Tier 0. **3C** YouTube path, OAuth (Tier 0 design, live at Tier 1 for client channels, 08 §2) | `agents/agent_13_publishing_delivery.md` (planned) |
| 14 | `agent_14_analytics` | `agent_14.analytics_ingest` | **3C**, Tier 0 | `agents/agent_14_analytics.md` (planned) |
| 15 | `agent_15_growth_revenue` | none in 24 §3.2. Owns S4 (budget guard, 09) and S10 | **3A** only through S4 (budget enforcement); the agent's own revenue functions **3C**, Tier 0 | `agents/agent_15_growth_revenue.md` (planned) |
| 16 | `agent_16_compliance_qa` | `agent_16.compliance_gate`; `agent_16.quality_score`; `agent_16.publication_authorisation`; plus S2 `svc_s02.uniqueness_check` (S2 → 16) | **3A** the gates (deterministic part of authorisation; delivery is authorised, not publication). **3C** publish-time re-checks, cross-video uniqueness. Tier 0 | `agents/agent_16_compliance_qa.md` (planned) |
| 17 | `agent_17_brief_creative_strategy` | `agent_17.brief_intake`; `agent_17.concept_variants`; `agent_17.ad_script_storyboard` | **3C**, **Tier 1+** (built when the first client or ad customer is signed, 24 header; plan Q17). Not used in 3A | `agents/agent_17_brief_creative_strategy.md` (planned) |

### 3.3 Decisions: deterministic vs LLM, and neighbours

Summary only (rule in section 1.5). "Det." = pure code with a unit test. "LLM" = a model call whose output is parsed into a schema and then validated by code (27 §4). Upstream and downstream are the task-graph neighbours in the 3A graph (3A_SLICE_SPEC §3) and the directive's pipeline; the orchestrator is always the actual caller.

| ID | Deterministic decisions | LLM decisions | Upstream | Downstream |
|---|---|---|---|---|
| 01 | state machine and every transition, admission (window, concurrency, resource class), retries and DLQ hand-off, scheduling, budget pre-check call, graph routing on gate results (24 §3.3). Source of truth: 03 §11, 07 | only "workflow optimisation proposals" (directive §3.1), as a proposal that a human approves; no model controls flow (§2). Model use beyond that: **REQUIRES REVIEW (Phase 1): decided in the Agent 01 blueprint** | owner or API (job creation); S7 decisions | every stage |
| 02 | source fetch limits, evidence and confidence arithmetic, public / authorised data filter | trend interpretation and prediction wording, always with evidence and confidence | external public data | 03 (3C) |
| 03 | calendar slotting rules, series-slot constraints, tenant and channel scoping | pillars, angles, topic proposals, gap analysis, investment ranking proposals | 02 (optional), 14 (3C), owner | 04 (topic enters job) |
| 04 | tenant and collection scope, retrieval (full-text search), reliability tier and score, restricted-chunk gate, note validation, coverage, budget stop (blueprint §6.1 D-1…D-14) | concept decomposition and evidence needs; note wording in original words | owner topic (3A) or 03 (3C) | 05, 06, 16 / S2 |
| 05 | schema, length and structure checks, language and banned-phrase checks, hook count (≥ 3 options, §1A.2) | narrative, hooks, scene-level script, Marathi / Hindi / English writing | 04 | 06, 07, 09, 12 (3C), S3 (3C) |
| 06 | claim records and status arithmetic, rule-pack matching (FIN-R1…R13 are in GLOSSARY §6.38), time-reference checks, contradiction flags from stored evidence | claim extraction from script text; independent verification judgement against evidence | 05, 04 | 05 (revise), 16, S7 on `NEEDS_HUMAN_REVIEW` |
| 07 | loudness, true peak, clipping, silence, sync measurements (18); pronunciation dictionary lookup; provider routing by config | none for mastering. Pronunciation suggestions: **REQUIRES REVIEW (Phase 1): decided in the Agent 07 blueprint** | 05 (checked script) | 09, 10 |
| 08 | tier order of sourcing (§1A.1), licence ledger rows, fingerprint and expiry checks, channel permission | selection and relevance judgement among candidates; generation prompts (only where no real or licensed option exists, ADR-009) | 09 (shot plan) | 10, 16 |
| 09 | timeline arithmetic, shot duration and visual-change cadence rules (§1A.2), template constraints | scene / shot planning, B-roll choice and pacing intent | 05, 06 | 08, 10, 11 |
| 10 | all FFmpeg commands, render presets, resumability, all `technical_qc` probes and thresholds (INF-09; 18 owns values). **Never an LLM gate** | none | 07, 08, 09 | 16, 13 |
| 11 | template and safe-area layout, brand-kit application, file limits, variant count | concept and text options for variants | 05, 09 | 16, 13 |
| 12 | length and character limits, chapter timestamp derivation, SEO validation checks | keyword framing, titles, description drafts | 05 | 13 |
| 13 | destination adapter calls, idempotency, duplicate prevention, privacy default (`private`, YT-04), quota buckets, delivery bundle assembly with SHA-256 manifest | none | 10, 11, 12, 16 (authorisation) | 14 (3C), owner (files) |
| 14 | API ingestion, aggregation, retention / CTR arithmetic, experiment bookkeeping | insight narration and hypothesis proposals; no automatic policy change (§3.3 learning loop) | 13 | 03, 15, S1 |
| 15 | cost, revenue and margin arithmetic, S4 limits and reservations (09: no model call) | none in S4; narrative reporting only in the agent's own revenue functions, if any: **REQUIRES REVIEW (Phase 1): Agent 15 blueprint** | cost ledger, 14 | 03 (3C), owner |
| 16 | licence completeness, disclosure decision, rule-pack matching, 100-point arithmetic, publish at ≥ 85 (`quality.publish_min_score`), any compliance failure rejects, deterministic S2 parts (b) and (c) (13 §3.1) | rubric judgement only where 18 defines a judge dimension; never the only gate. No LLM overrides a deterministic `BLOCKED` | 06, 10, 11, 08, 07 | 01 (routing), 13, S7 |
| 17 | brief completeness checks, format and duration matrices (24 §3.2, §4) | clarification questions, concepts, variants, ad scripts and storyboards | owner or client | 06, 16 (claim list), 05 |

(Rows 02, 03, 12, 14, 15, 17 are not written yet; their cells state the split the directive's wording implies and are confirmed or corrected by each blueprint section 6.)

## 4. Shared services S1–S13 (directive §3.2) with owners

Owners S6 → 16, S7 → 01, S8 → 01 resolve the "no owning agent" gap recorded in plan Q4; the other owners are as written in directive §3.2. Packages follow 27 §7.2. A service owner is accountable for the service's tables, tests and acceptance; the service itself is a module, not an LLM agent (§2).

| S | Service | Owner | Package (27 §7.2) | Task types (24 §3.2) | Build / tier | Blueprint or design doc |
|---|---|---|---|---|---|---|
| S1 | Audience Intelligence (aggregate, authorised data; no claims about individual viewers) | 14 | `s01_audience_intelligence` | none | **3C**; tier set in 14_SHARED_SERVICES.md (not yet written) | `14_SHARED_SERVICES.md` (planned) |
| S2 | Uniqueness Auditor | 16 | `s02_uniqueness_auditor` | `svc_s02.uniqueness_check` | **3A** deterministic parts (b), (c) only; cross-video similarity **3C** (needs a back catalogue); Tier 0. Thresholds: REQUIRES REVIEW (Phase 1): set from 3B golden samples (13 §3.1) | `14_SHARED_SERVICES.md`; gate semantics in `13_COMPLIANCE_YOUTUBE_POLICY.md` §3.1 |
| S3 | Localisation, Translation & Dubbing (owner 05 per directive; native-speaker QC step) | 05 | `s03_localisation_dubbing` | `svc_s03.translate_script`; `svc_s03.dub_timing_fit`; `svc_s03.native_speaker_qc` | **3C**, Tier 1 (dubbing production type is Tier 1, 24 header). Not used in 3A | `14_SHARED_SERVICES.md` |
| S4 | Financial Controller + Budget Guard | 15 | `s04_financial_controller` | none (invoked inline at T03 budget reservation, 03 §11.3; no model call) | **3A**: per-video + pilot budgets, provider-limit start gate, stop on breach; Tier 0. S10 is separate (below) | `09_COST_AND_BUDGET.md` |
| S5 | Infrastructure Intelligence + resource monitor | 01 | `s05_infrastructure_intelligence` | none | **3C**, Tier 0. 3A has only the ADR-012 render guards and the cgroup acceptance test (INF-03, INF-04) | `05_RESOURCE_MANAGEMENT.md`, `14_SHARED_SERVICES.md` (planned) |
| S6 | Security & Audit | **16** (Q4) | `s06_security_audit` | none | **3A** controls in 08 §2 (secrets, spend-limit precondition, DB roles + RLS, audit hash chain, tenancy CI suite); **3C** permission review, MFA; Tier 0 → Tier 1–3 per 08 §2 and §7 | `08_SECURITY.md` |
| S7 | Human Approval & Governance | **01** (Q4) | `s07_human_approval` | `svc_s07.request_approval` (S7 → 01) | **3A**: `FINAL_VIDEO` approval mandatory, `SCRIPT` optional, `SENSITIVE_CLAIM` / `COPYRIGHT_DOUBT` when inserted; Tier 0 (`owner_one_tap`, `owner_sensitive`). Client two-step workflow Tier 1 / 2 | `14_SHARED_SERVICES.md`; workflows in 24 §3.4 |
| S8 | Executive Command Center | **01** (Q4) | `s08_command_center` | none | **3C**, Tier 0 owner view; tenant view and platform-owner cross-tenant view Tier 1+. 3A_SLICE_SPEC §9 lists it out of 3A | `16_COMMAND_CENTER.md` (planned) |
| S9 | Tenant, Identity & Access | 01 | `s09_tenant_identity_access` | none | **3A** tenancy model, RLS and `org_id` everywhere (one tenant); **3C** tenancy UI; Tier 0 → Tier 1 roles; SSO / SCIM Tier 3 (08 §7) | `20_MULTI_TENANCY_AND_ENTERPRISE.md` (planned), `08_SECURITY.md` §5 |
| S10 | Billing, Metering & Plans | 15 | `s10_billing_metering` | none | **3C**, **Tier 2** (09 non-goal for 3A) | `20_MULTI_TENANCY_AND_ENTERPRISE.md`, `21_PRICING_AND_PACKAGING.md` (planned) |
| S11 | Client Portal, Brand Kits & White-label | 13 | `s11_client_portal` | none | **3C**; portal approvals Tier 1, white-label Tier 2 (24 §3.4). Brand-kit table exists from Tier 0 (04 §5.12) | `20_MULTI_TENANCY_AND_ENTERPRISE.md` (planned) |
| S12 | Integration API & Webhooks | 01 | `s12_integration_api` | none | **3C**, **Tier 3** (§1C.15; 08 §7.3) | `20_MULTI_TENANCY_AND_ENTERPRISE.md` (planned) |
| S13 | Community & Comments (triage into question / spam / abuse / lead; draft replies for human approval only; never auto-post; finance rule pack applies) | 14 | `s13_community_comments` | none | **3C**; tier set in 14_SHARED_SERVICES.md. Needs Agent 13's YouTube path first | `14_SHARED_SERVICES.md` (planned) |

Notes on the service table:
- S3 is owned by Agent 05 in the directive (§3.2). Its task types are named `svc_s03.*` (24 §3.2), and 24's header lists "S3 → 05 (dubbing)" as a content owner.
- S2's `svc_s02.uniqueness_check` output is an input to `agent_16.compliance_gate` (13 §3.1), so S2 → 16 is a gate input, not a separate authority.
- S4 and the budget start gate (owner acknowledges provider-side limits before the first paid call) are the 3A spend control of D1 (09 §8). S4 is "a library plus a scheduled system job inside the orchestrator process model" (09 §2), owned by 15.
- S6 → 16 means Agent 16 holds accountability for the security and audit controls in 08; identity and tenancy mechanics stay with S9 → 01 (08 header).

## 5. Build-stage view (what D1 builds when)

| Stage | Agents | Services | Task types executed |
|---|---|---|---|
| **3A** | 01 (minimal runner), 04, 05, 06, 07, 08, 09, 10, 11, 16 (gates), 13 (`file_delivery` only), 15 (via S4) | S2 (b, c), S4, S6 (3A controls), S7, S9 (one tenant) | `agent_04.research_pack`, `agent_04.knowledge_ingest` (pending CCR), `agent_05.script_draft`, `agent_05.shorts_adaptation`, `agent_06.claim_extraction`, `agent_06.claim_verification`, `agent_07.voice_synthesis`, `agent_07.audio_master`, `agent_08.asset_sourcing`, `agent_09.shot_plan`, `agent_10.render`, `agent_10.subtitles`, `agent_10.technical_qc`, `agent_11.thumbnail_variants`, `svc_s02.uniqueness_check`, `agent_16.compliance_gate`, `agent_16.quality_score`, `svc_s07.request_approval`, `agent_16.publication_authorisation`, `agent_13.file_delivery` |
| **3B** | no new agent. Prompt, template and threshold tuning of the 3A agents on three golden samples; adapters beyond the first (AI video B-roll, music library) only at the earliest here (ADR-007, 008, 009) | none new | same as 3A |
| **3C** | 01 hardening, 02, 03, 12, 13 (YouTube path), 14, 15, 17; 16 publish-time re-checks | S1, S3, S5, S6 (rest), S8, S10, S11, S12, S13; S2 cross-video | `agent_02.trend_scan`, `agent_03.topic_selection`, `agent_12.metadata`, `agent_13.upload_private`, `agent_13.publish`, `agent_13.verify_publication`, `agent_14.analytics_ingest`, `agent_17.*`, `svc_s03.*` |

Source for the 3A list: 3A_SLICE_SPEC §2.4. Source for what is out of 3A: §9 of the same document.

## 6. Enterprise tier view (GLOSSARY §6.47)

| Tier | Needs these registry items (first usable) | Note |
|---|---|---|
| **Tier 0** (owner only, MVP: 1 tenant, 1 channel, 1 language, multi-tenant data model) | all rows marked Tier 0 above: Agents 01–16 (16 incl. gates), S2, S4, S5, S6 (core), S7, S8 owner view, S9 core | `org_id` on every table and RLS from day one (rule 9) |
| **Tier 1** (first managed-service client) | Agent 17, S3 (dubbing), client approvals in S7 (`client_two_step` via managed service), S11 portal approvals, Agent 13 OAuth live for client channels | OAuth verification and YouTube audit (§1C.15) |
| **Tier 2** (self-serve) | S10 billing and metering, S11 white-label and onboarding | |
| **Tier 3** (enterprise) | S12 integration API and webhooks, S9 SSO / SCIM, dedicated deployment, pen-test | 08 §7 |

## 7. How other documents use this registry

1. Blueprints (`agents/agent_NN_*.md`) take ID, package, task types and tier from sections 3 and 4. A blueprint that finds a mismatch files a CCR; it does not redefine the row.
2. `24_PRODUCTION_TYPES.md` stage objects name `task_type` values from 24 §3.2; this registry shows which agent executes them.
3. `BUILD_BACKLOG.md` tickets carry the owning agent or service ID and the 3A / 3B / 3C mark of the row here.
4. Agent enable / disable, daily limits and similar controls (S8) act on the agent IDs of this registry; the `org_controls` store is 04 §5.1.
5. Changes to this registry after baseline go through CHANGE_REQUESTS.md (rule 11); contract-level changes through CONTRACT_CHANGE_REQUESTS.md.

## 8. Open items

| # | Item | Status |
|---|---|---|
| 1 | Blueprints 01–03, 05–17 not yet written (only Agent 04 exists). Rows marked "planned" are paths per directive §4. | Wave B-2 and the 3A blueprints, per D2 |
| 2 | The decision split for Agents 01, 02, 03, 07, 12, 14, 15, 17 in section 3.3 is the directive-implied split. Each blueprint section 6 confirms it. | pending blueprints |
| 3 | Scheduled system jobs of services (S4 reconciliation, S5 resource sampling, S6 permission review) have no canonical task type in 24 §3.2. How they are executed and audited is undefined in the contracts. | contract request below (pending CCR) |
| 4 | Tier for S1 and S13 is not stated in the directive. | REQUIRES REVIEW (Phase 1): set in 14_SHARED_SERVICES.md |
| 5 | `agent_04.knowledge_ingest` and CCR-3A-1 (production type v2 with owner-topic input and `FILE_DELIVERY`) are used by 3A and are pending CCRs filed by other documents. | pending CCR |

## 9. Cited RESEARCH_LOG IDs
YT-09, YT-04, YT-08, IN-03, IN-08, PR-01, PR-03, INF-01, INF-03, INF-04, INF-09.
