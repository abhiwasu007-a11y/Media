# 14 — Shared Services S1–S13

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** (every service below has feature status Planned, GLOSSARY §6.11) |
| Owner agent / service | Each service has the owning agent of directive §3.2 (S6 → 16, S7 → 01, S8 → 01 by plan Q4); section 2 lists them. This document is kept by the documentation lead; conflicts with the registry (02 §4) go to the owner, never decided locally |
| Depends on | MASTER_DIRECTIVE.md §3.2 and the sections listed below; GLOSSARY_AND_IDS.md (IDs, enums, FIN-R1…R13 in §6.38); 03_COMMUNICATION_STANDARD.md (task contract, state machine §11, approval waits §11.6); 04_DATABASE_ARCHITECTURE.md (tables); 07_FAILURE_MANAGEMENT.md; 24_PRODUCTION_TYPES.md (§3.2 task types, §3.4 approval workflows); 27_ENGINEERING_STANDARDS.md; 02_AGENT_REGISTRY.md §4; 3A_SLICE_SPEC.md; 13_COMPLIANCE_YOUTUBE_POLICY.md; 08_SECURITY.md (S6); 09_COST_AND_BUDGET.md (S4); 05_RESOURCE_MANAGEMENT.md (S5 thresholds); 18_PRODUCTION_QUALITY_STANDARD.md; agents/agent_01_ceo_orchestrator.md. Referred to by name only (may change): 16_COMMAND_CENTER.md, 20_MULTI_TENANCY_AND_ENTERPRISE.md, 21_PRICING_AND_PACKAGING.md, 22_DATA_PROTECTION.md, ADR-003, ADR-004, ADR-010 |
| Directive sections covered | §3.2 (S1–S13 and owners), §2 (services are modules, control flow in code, no new agents), §3.3 (learning loop, quality, memory), §1B.2 (finance rules for S13 replies), §1C.1 (tenancy), §1C.4 (identity), §1C.5 (audit), §1C.6 (client experience), §1C.9 (billing and metering), §1C.12 (integration API), §1C.15 (tiers), §1E.3 (dubbing), §0 rules 5, 8, 9, 10 |
| Decisions applied | D1 (3A production line; no YouTube upload, no Google OAuth in 3A; paid calls only within owner-set provider limits; per-video + pilot budgets, stop on breach; keys only through the environment secret mechanism; render never in market hours), D2 |
| Facts cited | RESEARCH_LOG: YT-09, YT-12, YT-14, YT-15, IN-03, IN-07, INF-07, INF-08, INF-11, PR-03 |
| Marking | **3A / 3B / 3C** = the owner's build stages (D1). **Tier 0–3** = enterprise tiers (GLOSSARY §6.47). `(pending CCR)` = name not in Wave A, listed in section 14. `REQUIRES REVIEW (Phase 1): <need>` = value unknown, none invented. Public repository: no private method, book titles, course content or server details |

---

## 1. What a shared service is, and the rules that hold for all of them [3A / 3B / 3C · Tier 0–3]

1. A shared service is **a module with a named owning agent, not an LLM agent** (directive §2, §3.2; GLOSSARY §1). Where a step needs an LLM, it is a named task type with one prompt file and one eval pack (27 §4, §6), and the decision split is stated per service below. No ADR currently justifies an autonomous LLM service, so none is one.
2. Services never call agents. Hand-offs are task contracts executed by Agent 01 (02 §1.2). A service exposes (a) a **library interface** called in-process by the orchestrator or an agent, or (b) a **canonical task type** `svc_sNN.<task>` (24 §3.2), or (c) a **scheduled system job**. The Wave A contracts name task types only for S2, S3 and S7; every other task type here is `(pending CCR)`.
3. Every service row, task, queue item, file path, cache key, log line and metric carries `org_id` (rule 9, directive §1C.1). Code filters by tenant explicitly; RLS (04 §3, INF-11) is the second line. A service that must read across tenants does so only through the `amw_sysfn` functions of 04 §3.6 (identifiers and aggregates only) and every such call is audited.
4. Deterministic checks run first; an LLM score is never the only gate; an incomplete output is never marked successful (02 §1.6).
5. A service never approves anything, never writes `editorial_contributions`, never raises a budget and never changes a control. Only a human with the right role does (08 §5.3; 04 §5.16 triggers).
6. Failures use the codes of 07 §2. No infinite retries, no silently dropped job, no uncontrolled loops. A service that cannot decide records `NEEDS_HUMAN_REVIEW` or `UNCLASSIFIED`; it never guesses.
7. Models, providers, limits and thresholds live in configuration (27 §7.3.1, ADR-007), never in code (rule 5). Every numeric threshold below is a configuration key whose value is **REQUIRES REVIEW (Phase 1)** unless a document already fixes it.
8. Every state-changing action writes `audit_log` (04 §5.13). Event names in this document are proposals; the register is the S6 list in 08 §9.2.
9. Documentation status and software status are reported separately (rule 6). All services below: software **Planned**.

### 1.1 Field legend used in section 3
| Field | Meaning |
|---|---|
| Purpose | what the service is for (directive §3.2 wording first) |
| Owner / scope | owning agent; build stage (3A/3B/3C) and enterprise tier |
| Contracts | inputs and outputs through 03 contracts; task types; execution mode |
| Tables | 04 tables read / written (names only; columns are 04's) |
| Deterministic vs LLM | what is rule-based, what is a model judgement, and why |
| Tenant isolation | how rule 9 holds for this service |
| Human approvals | `approval_kind` / `workflow_key` used (GLOSSARY §6.15; 24 §3.4) |
| Acceptance | testable criteria (27 §9; tests that block CI are marked **blocking**) |

---

## 2. Overview [3A / 3B / 3C · Tier 0–3]

| S | Service | Owner | Mode | Build stage | Tier | Task type (24 §3.2) | LLM? |
|---|---|---|---|---|---|---|---|
| S1 | Audience Intelligence | 14 | scheduled job + library | 3C | T0 | `svc_s01.audience_rollup` (pending CCR) | narration only (optional) |
| S2 | Uniqueness Auditor | 16 | task type | **3A** parts (b), (c); part (a) 3C | T0 | `svc_s02.uniqueness_check` | no |
| S3 | Localisation, Translation & Dubbing | 05 | task types | 3C | **T1** | `svc_s03.translate_script`, `svc_s03.dub_timing_fit`, `svc_s03.native_speaker_qc` | translation only |
| S4 | Financial Controller + Budget Guard | 15 | inline library + system job | **3A** | T0 | none (inline at T03) | no |
| S5 | Infrastructure Intelligence + resource monitor | 01 | scheduled job | 3C (3A emits signals only) | T0 | none | no |
| S6 | Security & Audit | 16 | library + scheduled jobs | **3A** controls; 3C rest | T0 → T1–T3 | none | no |
| S7 | Human Approval & Governance | 01 | task type | **3A** | T0 (T1/T2 client workflows) | `svc_s07.request_approval` | no |
| S8 | Executive Command Center | 01 | web app over the API | 3C | T0 owner view; T1+ tenant / platform views | none | no |
| S9 | Tenant, Identity & Access | 01 | library + auth component | **3A** core; 3C UI | T0 → T1; T3 SSO | none | no |
| S10 | Billing, Metering & Plans | 15 | library + scheduled job | 3C | **T2** | `svc_s10.usage_rollup` (pending CCR) | no |
| S11 | Client Portal, Brand Kits & White-label | 13 | app + library | 3A minimal brand kit; 3C portal | T0 kit; T1 approvals; T2 white-label | none | no |
| S12 | Integration API & Webhooks | 01 | API + task type | 3C | **T3** | `svc_s12.webhook_deliver` (pending CCR) | no |
| S13 | Community & Comments | 14 | task types | 3C | T0+ | `svc_s13.comment_triage`, `svc_s13.reply_draft` (pending CCR) | triage + drafting |

Sources: directive §3.2; 02 §4; 01 §5. Where a row differs from 02 §4, 02 wins and a CCR is filed (section 14).

---

## 3. Services

### 3.1 S1 Audience Intelligence [3C · Tier 0]

| Field | Specification |
|---|---|
| Purpose | Turn aggregate, authorised audience data into insights for content strategy (Agents 03, 14, 05 through memory and experiments). **No claim about any individual viewer**; no profiling, no re-identification (directive §3.2) |
| Owner / scope | Agent 14. 3C (needs published videos and the Agent 13 YouTube path; nothing in 3A, which has no upload). Tier 0 |
| Contracts | Scheduled system job `svc_s01.audience_rollup` (pending CCR; same scheduled-job gap as 02 open item 3 and 05 §12). Input: `{channel_id, window, report_types}` and rows already fetched by `agent_14.analytics_ingest` (24 §3.2). Output envelope (03) with `status` and a payload that references the rollup as a tenant blob URI and the `memory_items` keys written. S1 does **not** call the YouTube API itself; ingestion stays with Agent 14 |
| Data available | YT-14: the Analytics API gives retention (`audienceWatchRatio`, `relativeRetentionPerformance`); impressions and CTR come from the Reporting API. Which **audience dimensions** (age, geography, device, traffic source) the API returns, their minimum cohort sizes and any usage limits: **REQUIRES REVIEW (Phase 1): official YouTube Analytics API dimension list and policy on aggregate audience data** |
| Tables | Reads `analytics_snapshots` (04 §5.22; "only values returned by the API; never fabricated"), `publications`, `channels`. Writes `memory_items` with scope `CHANNEL` or `LONG_TERM` (04 §5.10: needs `provenance_ref`, `confidence`, `review_after`); proposes `experiments` rows only through Agent 14 and the `EXPERIMENT` approval. No new table |
| Deterministic vs LLM | **Deterministic**: aggregation, cohort-size suppression (any cell below `s01.min_cohort` is dropped, never reported; value REQUIRES REVIEW), comparison against the channel baseline, confidence from sample size (no significance claim without enough data, directive §3.3). **LLM (optional, 3C, one task type to be added with Agent 14's blueprint)**: wording of an insight from the computed numbers only. The model receives numbers, never rows; its text is checked against the computed numbers (every number in the text must exist in the input) |
| Tenant isolation | Per-tenant only. Insights are never pooled across tenants, never used to train or tune anything for another tenant. A cross-tenant "benchmark" product is **out of scope** (would need aggregated consent; not in the directive) |
| Human approvals | None to read. Any change that S1's insight suggests (strategy, calendar, thresholds, experiments) is a proposal that needs the existing approvals (`EXPERIMENT`, `POLICY_CHANGE`); S1 and Agent 14 never apply a policy change automatically (§3.3 learning loop) |
| Personal data | Aggregates carry no viewer identity. Comment authors are S13's data, not S1's. DPDP posture: IN-07; retention by 22 (REQUIRES REVIEW) |
| Acceptance | (1) Every reported figure traces to an `analytics_snapshots` row (`provenance_ref`); a figure with no source is rejected (**blocking** unit test). (2) A cohort below `s01.min_cohort` never appears in any output (**blocking**). (3) Cross-tenant suite: S1 run for org A leaves no `memory_items` readable by org B (**blocking**, 04 §3.7). (4) With fewer snapshots than the configured minimum the job returns `status = SUCCEEDED` with an explicit "insufficient data" payload, never an invented insight. (5) The text-vs-numbers check rejects a seeded wrong number |

### 3.2 S2 Uniqueness Auditor [3A parts (b), (c) · 3C part (a) · Tier 0]

| Field | Specification |
|---|---|
| Purpose | Gate input for the originality / inauthentic-content rule YTG-R1 (13 §3.1; YT-09: inauthentic content is judged at channel level; mass-produced template content cannot monetize). S2 **measures**; the authority to block is `agent_16.compliance_gate` (02 §4 note 2) |
| Owner / scope | Agent 16. **3A**: parts (b) and (c). **3C**: part (a). Tier 0 |
| Parts | (a) similarity of script, structure, visuals and thumbnail to the channel's own recent videos (needs a back catalogue); (b) at least one recorded human editorial contribution (`editorial_contributions`, YTG-R4); (c) the script's structure and the shot plan are not identical to the production-type template except for the topic noun |
| Contracts | Task type `svc_s02.uniqueness_check` (24 §3.2; stage `s02u_unique`, blocking, `on_fail REVISE → s05_script`, 24 §3.3). Input payload (field list; schema file created with the code, 27 §7): `job_id`, `script_ref` + `script_sha256`, `shot_plan_ref`, `thumbnail_refs[]`, `production_type_key` + registry version, `channel_id`, `parts[]` (which of a/b/c to run). Output payload: per part `{part, check_verdict (PASS/FAIL/WARN/SKIPPED), precondition, compared_ids[], metrics{}}`, `report_ref` (tenant blob, SHA-256), `overall`. The output is then an input of `agent_16.compliance_gate`, which records the `compliance_verdicts` row (04 §5.17) |
| 3A behaviour | (b) runs and fails if no contribution row exists for the job. (c) runs against the registry skeleton. (a) returns `SKIPPED` with precondition "no prior videos on the channel" for the first three samples, and `NEEDS_HUMAN_REVIEW` thereafter until part (a) is built (13 §3.1, §13; 3A_SLICE_SPEC §2.4) |
| Tables | Reads `scripts`, `editorial_contributions`, `production_types`, `org_production_types`, `assets`, `asset_fingerprints` (04 §5.15; T0+), `renders`, `publications`. Writes only its output envelope and the report blob; the verdict row belongs to Agent 16 |
| Deterministic vs LLM | **Fully deterministic; no LLM** (02 §3: deterministic S2 parts). Similarity method and measures (token shingles, structural signatures, perceptual fingerprints, embeddings): **REQUIRES REVIEW (Phase 1): method choice**; an embedding model would need its own ADR and cost line. **Thresholds are not invented here**: they are set from the 3B golden samples (13 §3.1; 02 §4) and held as configuration (`s02.<part>.*`) |
| Tenant isolation | Compares only within the tenant and, for part (a), within the channel. No cross-tenant comparison, ever (it would leak content between tenants). Fingerprints are tenant rows with `org_id` |
| Human approvals | None created by S2. A `NEEDS_HUMAN_REVIEW` from the gate inserts an approval through S7 (24 §3.3). A human cannot waive a BLOCKING rule on a mandatory pack for another tenant (13 §11) |
| Acceptance | (1) Seeded fixtures: a script identical to the template except the topic noun fails (c); a job without a contribution row fails (b) (**blocking**). (2) Same input and same config give the same output and `report_ref` hash (determinism). (3) Part (a) never returns `PASS` without compared IDs; with no back catalogue it returns `SKIPPED` plus its precondition, never `PASS`. (4) A cross-tenant seeded duplicate in org B is not found when auditing org A (**blocking**). (5) `FAIL` routes to REVISE within `max_revision_loops` (07 §9), then the job ends `BLOCKED_COMPLIANCE` (03 §11.5) |

### 3.3 S3 Localisation, Translation & Dubbing [3C · Tier 1]

| Field | Specification |
|---|---|
| Purpose | Translated scripts; dubbed voice tracks with timing fit; per-language subtitles and metadata; a native-speaker QC step; YouTube multi-language audio tracks (directive §3.2, §1E.3) |
| Owner / scope | Agent 05 (directive). **3C, Tier 1** (the dubbing production type is Tier 1, 24 header). Not used in 3A. The Marathi / Hindi / English writing of the scriptwriter is Agent 05's own work, not S3 |
| Contracts | `svc_s03.translate_script` (LLM; input: source `script_id` + SHA-256, target language, glossary and pronunciation references; output: new `scripts` row, `parent_script_id` = source). `svc_s03.dub_timing_fit` (deterministic; input: translated script, the `agent_07.voice_synthesis` audio per segment; output: per-segment fit report and the adjustments allowed). `svc_s03.native_speaker_qc` (human approval gate, executed through S7). Graph order is fixed by 24 §4 (dubbing): translate → `agent_06.claim_extraction` on the translation (blocking) → native-speaker QC → voice → timing fit → master → subtitles → QC → metadata per language → compliance gate → `FINAL_VIDEO` approval → authorisation → delivery |
| Facts | YT-15: multi-language audio is an Advanced-features capability; the creator uploads their own dubs. Whether the Data API can upload additional audio tracks, and its quota: **REQUIRES REVIEW (Phase 1): official API support** (24 §4 `dub_audio_track_<lang>` carries the same flag). Until known, a dubbed track is delivered as a file (`agent_13.file_delivery`) |
| Tables | `scripts` (language, `parent_script_id`; 04 §5.11), `voices`, `voice_consents` (04 §5.12; a cloned voice needs a verified consent record, directive §1C.8), `claims`, `approvals`, `approval_steps`, `renders`. No new table: a language is a column value, not a new table |
| Deterministic vs LLM | **LLM**: translation (one prompt, eval pack with Marathi / Hindi / English golden cases; the glossary is injected, never paraphrased from memory). **Deterministic**: timing fit (duration arithmetic, speed-change limits `s03.max_tempo_change`, value REQUIRES REVIEW), subtitle length and reading-speed limits (18), language-tag checks, banned-phrase checks. The meaning-must-not-change rule is enforced by re-running claim extraction and the finance pack on the translation, not by a model's self-assessment |
| Tenant isolation | Translation memory, glossaries and cloned voices are per tenant (`org_id`); a voice or glossary of tenant A is never an input for tenant B. Provider calls carry no other tenant's text |
| Human approvals | `svc_s03.native_speaker_qc` is a **mandatory** human step per language (24 §4). Approval kind for it does not exist in GLOSSARY §6.15: `NATIVE_SPEAKER_QC` (pending CCR; alternative: reuse `SCRIPT`). Workflow `owner_one_tap` at Tier 0/1; reviewer role `REVIEWER_APPROVER`. `FINAL_VIDEO` is also mandatory per language set |
| Acceptance | (1) A translated script that introduces a finance-pack violation absent from the source is `BLOCKED` by the compliance gate (answer-key fixtures, 13 §5.12) (**blocking**). (2) No dubbed asset reaches `agent_13` without an `APPROVED` native-speaker approval for that language and SHA-256. (3) Timing fit never exceeds the configured tempo change; an over-limit segment returns to translation for shortening, bounded by `max_revision_loops`. (4) A voice without an `ACTIVE` consent record cannot be used (**blocking**). (5) Eval pack of at least 20 golden cases (27 §6) |

### 3.4 S4 Financial Controller + Budget Guard [3A · Tier 0] — specified in 09_COST_AND_BUDGET.md

Not repeated here. Pointers: where S4 runs (09 §2), budget kinds and states (09 §3), reservation at T03 (09 §3.4; 03 §11.3), breach behaviour (09 §4), cost capture and estimate vs verified (09 §5–6), provider limits and start gate (09 §8), cost-per-stage report (09 §12), pending CCRs (09 §14).

| Field | Specification |
|---|---|
| Owner / scope | Agent 15; **3A**, Tier 0. Library plus scheduled system job; no model call; no task type (02 §4) |
| Tables | `cost_ledger`, `budgets`, `budget_reservations` (04 §5.14) |
| Integration with other services (this document's only addition) | S10 meters from `cost_ledger` only (3.10); S8 shows spend from it (3.8); S7 `SPEND` approval is the only way a budget increase is proposed, and the increase is a human action (rule 8); S6 audits every budget change (3.6) |
| Acceptance | As stated in 09. Integration criteria: a task with a non-zero `resource_budget` cannot leave `QUEUED` without a reservation; S10 and S8 never write to S4 tables; no service raises a limit |

### 3.5 S5 Infrastructure Intelligence + resource monitor [3C · Tier 0] — thresholds in 05_RESOURCE_MANAGEMENT.md §9

Signals, level scheme, actions by level, persistence and the monitoring-tool boundary are in 05 §9 and are not repeated. Monitoring tool choice is ADR-006 (not started).

| Field | Specification |
|---|---|
| Owner / scope | Agent 01. **3C**, Tier 0. 3A only emits the signals S5 will read: ADR-012 render guards, the cgroup acceptance test RM-T1 (05 §5.3), JSON logs and a metrics endpoint (27 §7.3.6) |
| Contracts | Scheduled system job; no task type exists. Sampling job and sample storage: `(pending CCR)` already requested in 05 §12 item 1. Outputs: threshold events to `audit_log` and `notifications`; recommendation records (never actions) |
| Tables | `workers` (GLOBAL, 04 §5.4), `task_queue`, `circuit_breakers` (read), `notifications`, `audit_log`. Reads through `amw_readonly` |
| Deterministic vs LLM | **Fully deterministic**; no LLM. Scaling or migration is a **recommendation** only; any purchase is the owner's decision (rule 8) |
| Tenant isolation | Host signals carry no tenant data; queue and usage signals are labelled by tenant and a tenant sees only its own; cross-tenant aggregates only through `amw_platform_ops_summary()` (04 §3.6; audited) |
| Human approvals | Recommendation to buy or move a server: owner decision, `SPEND` approval if money is involved |
| Acceptance | As in 05 §13. Integration criteria: S5 never kills a process or touches another application (05 §9.3); a CRIT closes the admission gate for the affected class and Agent 01 applies it; S5's own footprint stays within its container limit (INF-07, INF-08: unknown until measured) |

### 3.6 S6 Security & Audit [3A controls · 3C rest · Tier 0 → T3] — specified in 08_SECURITY.md

Not repeated here. Pointers: scope by build phase (08 §2), secrets and the spend-limit precondition (08 §3, §3.4), DB roles and RLS (08 §4), permission audit (08 §5.6), tenant isolation tests (08 §8.2), audit log and tamper evidence (08 §9), CI and supply chain (08 §10), incident runbook (08 §12).

| Field | Specification |
|---|---|
| Owner / scope | **Agent 16** (plan Q4). `amw_core.audit` + `services/s06_*`. 3A controls; 3C periodic permission review and MFA; Tier 0 → T1–T3 (08 §7) |
| Tables | `audit_log`, `audit_chain_heads`, `tenant_data_keys`, `oauth_tokens` (encrypted; read only by `amw_publisher`) |
| Integration with other services | Every other service in this document emits audit events (section 9). S6 owns the event list (08 §9.2); no service writes `audit_log` rows by hand, only through `amw_core.audit` (hash chain). Identity and tenancy mechanics stay with S9, not S6 |
| Acceptance | As in 08 §8.2 and §13. Integration criterion: the audit-event list of section 9 is a subset of the 08 §9.2 list at the time the service is built, or a change to that list is made first |

### 3.7 S7 Human Approval & Governance [3A · Tier 0 (T1/T2 client workflows)]

| Field | Specification |
|---|---|
| Purpose | Every human gate is a recorded decision bound to the exact content: new channel, new category, sensitive / financial claims, copyright doubt, unusual publish, policy change, large spend (directive §3.2) plus the other kinds of GLOSSARY §6.15 |
| Owner / scope | Agent 01 (plan Q4). **3A**: `FINAL_VIDEO` mandatory; `SCRIPT` optional; `SENSITIVE_CLAIM`, `COPYRIGHT_DOUBT`, `KNOWLEDGE_RELEASE` when inserted; workflow `owner_one_tap` and `owner_sensitive`. 3C: remaining kinds as their agents arrive. Tier 1/2: `client_two_step` (Tier 1 through managed service, Tier 2 via portal, S11) |
| Contracts | Task type `svc_s07.request_approval`; **input schema is owned by the Agent 01 blueprint (§7.2) and not restated here**. Lifecycle (03 §11.6): the gate task creates an `approvals` row bound to the subject SHA-256 and returns `SUSPENDED` (`AWAITING_APPROVAL`, T09); each step decision is recorded; at a final `approval_state` S7 triggers T15 and the gate task completes with the decision (T08); the orchestrator routes (continue, REVISE to an allowed stage, stop). A changed subject SHA-256 makes the old approval `WITHDRAWN` and a new one is requested. Rejection at a mandatory approval ends the job `REJECTED_BY_APPROVER` (24 §3.3) |
| Workflows | `owner_one_tap` (1 step: `REVIEWER_APPROVER`), `client_two_step` (client reviewer → client final approver), `owner_sensitive` (step 2 `ORG_OWNER` for the finance channel or a financial claim) — GLOSSARY §6.44; 24 §3.4. S7 enforces; it does not define new workflows |
| Tables | `approvals`, `approval_steps`, `editorial_contributions` (04 §5.16); `notifications` (04 §5.23; in 3A in-app rows read by the operator tool, no outbound sender: 3A_SLICE_SPEC §2.1, §9); reads `jobs`, `tasks`, `renders`, `compliance_verdicts`, `quality_scores` for the evidence list |
| Deterministic vs LLM | **Fully deterministic; no LLM**. Which approvals are mandatory comes from the production type, never from a model. An LLM never writes a decision |
| Rules enforced in code and by DB triggers (04) | (1) A step decision is by a human with an `ACTIVE` membership and the required role (trigger). (2) A `FINAL_VIDEO` approval needs at least one `editorial_contributions` row for the job before `APPROVED` (24 §3.4; YTG-R4; enforced again by the publish guard, 04 §5.21; the guard is 3C because 3A has no publication). (3) The decision is bound to `subject_sha256`. (4) Inside a client tenant the approvers are that tenant's users; the platform owner approves only when `approvals.managed_service = true` (rule 10). (5) `expires_at` and reminder timing: **REQUIRES REVIEW (Phase 1): owner decision**; expiry sets `EXPIRED`, never auto-approves |
| Tenant isolation | `approvals` rows are TENANT; the approver's membership is checked against the approval's `org_id`; evidence URIs of another tenant fail with `PERMANENT.CROSS_TENANT_REF` (07 §2). Notifications are addressed to users of the same org |
| Human approvals | This service **is** the approval mechanism. Kinds by service: see section 7 |
| Acceptance | (1) An agent or service actor cannot write an approval decision or an editorial contribution (**blocking**, actor-type trigger test). (2) Changing the subject after request leaves the old approval `WITHDRAWN` and no publication or delivery can use it (**blocking**). (3) `FINAL_VIDEO` cannot reach `APPROVED` without a contribution row. (4) A user of org A cannot decide an org B approval (**blocking**). (5) Each decision writes `approval.decided` to the audit chain with `authority` = role. (6) Suspending and resuming across a worker restart preserves state (03 §11 tests) |

### 3.8 S8 Executive Command Center [3C · Tier 0 owner view; T1+ tenant and platform views]

| Field | Specification |
|---|---|
| Purpose | One responsive, mobile-first dashboard: live operations; channels; business; approvals inbox; controls; drill-down; role-based access; audit of every control action; platform-owner cross-tenant view and tenant view limited to its own organisation (directive §3.2) |
| Owner / scope | Agent 01 (plan Q4). **3C**, Tier 0 owner view; tenant view and cross-tenant platform view Tier 1+. **Out of 3A**: the owner works through the operator command-line tool (3A_SLICE_SPEC §2.1, R14). UI stack: ADR-004 (not started). Detailed design: 16_COMMAND_CENTER.md (planned) |
| Contracts | `apps/dashboard` talks only to `apps/api`, which uses `amw_app` in a tenant context; the dashboard has no database access and creates no task type. Control writes go through the audited path of Agent 01 FR22. Approvals shown are S7's; decisions are posted to S7 and recorded by it |
| Tables | Reads `jobs`, `tasks`, `task_queue`, `workers`, `cost_ledger`, `budgets`, `publications`, `analytics_snapshots`, `approvals`, `notifications`, `audit_log`. Writes only `org_controls` and `platform_controls` (04 §5.1: keys `agent_enabled.<agent_id>`, `production_schedule`, `daily_production_limit`, `publishing_enabled`, `emergency_stop`, `ip_allowlist` (T3); platform keys `platform_emergency_stop`, `admission_paused`), each change audited as `control.<key>.changed`. Revenue, profit and ROI figures: from Agent 15's figures only (labels ESTIMATE / MEASURED / PROJECTION, rule 4); none are shown if no verified source exists |
| Deterministic vs LLM | Deterministic; no LLM. Any narrative on the page comes from Agent 14 / 15 outputs already stored, with their labels |
| Tenant isolation | Tenant view: tenant context set per request (S9). Platform-owner cross-tenant view: only the aggregate function `amw_platform_ops_summary()` (04 §3.6, T1), which returns counts and totals, no content; each call audited. Drill-down into another tenant's job content is not possible from the platform view (the platform owner acts in a tenant only as a member of it, or with `managed_service`, rule 10) |
| Human approvals | Control changes are role-checked human actions (08 §5.2 matrix), not approvals. Raising a budget limit is a S4 / S7 `SPEND` flow. Emergency stop needs no approval to engage; resuming is a human action that is audited |
| Acceptance | (1) Every control change writes `control.<key>.changed` with actor, authority and old / new value (**blocking**). (2) A `VIEWER` cannot change a control; a tenant user cannot see another tenant's data (**blocking**, 08 §8.2). (3) With `emergency_stop` set, no new task is claimed for that tenant (and, for the platform key, for any tenant); running tasks stop at the next safe point as defined by Agent 01. (4) Phone-width layout with no horizontal overflow and readable contrast (owner rule D.3; screenshot evidence at build). (5) No figure without a stored source |

### 3.9 S9 Tenant, Identity & Access [3A core · 3C UI · Tier 0 → T1; SSO T3]

| Field | Specification |
|---|---|
| Purpose | Organisation → workspace → channel hierarchy; memberships and the eight roles; per-transaction tenant context; invitations; sessions; later SSO / SCIM (directive §1C.1, §1C.4) |
| Owner / scope | Agent 01. **3A**: tenancy model, `amw_core.tenancy` (`SET LOCAL app.org_id / app.actor / app.user_id`, 04 §3.2), RLS on every table, one real tenant plus a synthetic test org for the cross-tenant suite. **3C**: tenancy and identity UI; email + password with MFA and Google sign-in (Tier 0 design, live Tier 1; auth library by ADR-003, never hand-rolled crypto). **Tier 3**: SAML / OIDC, SCIM, domain verification (08 §7.2) |
| Contracts | Library interface used by the API, orchestrator and workers; no task type. Organisation creation only through an audited `amw_sysfn` function by the platform owner (04 §5.1); self-serve signup is Tier 2. Detailed design: 20_MULTI_TENANCY_AND_ENTERPRISE.md (planned); permissions and auth hardening: 08 §5 |
| Tables | `organisations`, `workspaces`, `channels`, `users`, `user_auth_refs`, `user_sessions`, `memberships`, `invitations`, `org_controls` (S8); T1 `data_requests` (export and erasure, DPDP, 22); T3 `org_sso_connections`, `org_domains` |
| Deterministic vs LLM | Fully deterministic; no LLM |
| Tenant isolation | This service **is** the isolation mechanism: roles of 04 §3.1 (`amw_app` is `NOBYPASSRLS`, never owner or superuser; INF-11 `FORCE ROW LEVEL SECURITY`), the GLOBAL allow-list of 04 §4 (identity tables only, RLS to self / memberships), and the blocking cross-tenant test of 04 §3.7 |
| Human approvals | Creating an organisation or changing a role is an audited human action under the 08 §5.2 matrix; no approval kind. Offboarding / erasure follows 22 (REQUIRES REVIEW) |
| Acceptance | As in 08 §8.2 (tenancy tests, **blocking**). Integration criteria: a query without tenant context returns no rows (not an error that leaks existence); every table in 04 §4 has a policy or is on the GLOBAL allow-list; a `CLIENT_GUEST` limited to `allowed_channel_ids` cannot read other channels' rows; membership removal revokes sessions and guest tokens (08 §5.4) |

### 3.10 S10 Billing, Metering & Plans [3C · Tier 2]

| Field | Specification |
|---|---|
| Purpose | Usage metering from S4 cost tracking, plans and credits, invoices with Indian GST, a payment-gateway adapter, dunning, plan limits enforced in the queue (directive §1C.9; §1B.7) |
| Owner / scope | Agent 15. **3C, Tier 2** (09 lists it as a non-goal for 3A; no table of 04 §5.25 is created before then). The platform owner's own spending still follows rule 8 |
| Contracts | Scheduled system job `svc_s10.usage_rollup` (pending CCR) turns `cost_ledger` entries into `usage_events`; library calls for plan-limit checks used by admission (05 §7.1: `plans.limits` is the single source). Gateway adapter and webhooks: ADR-010 (not written; Indian gateway first, international later). Detailed design: 20_MULTI_TENANCY_AND_ENTERPRISE.md and 21_PRICING_AND_PACKAGING.md (planned) |
| Tables | `plans` (GLOBAL), `subscriptions`, `usage_events` (partitioned), `invoices` (04 §5.25); reads `cost_ledger`, `budgets` |
| Deterministic vs LLM | Fully deterministic; **no LLM may compute, round or explain an amount**. Money in minor units, currency code per row (GLOSSARY §3 units). Prices, GST rates and invoice rules: **REQUIRES REVIEW (Phase 1): 21_PRICING_AND_PACKAGING (PROPOSAL until the owner approves) and a chartered accountant / owner's lawyer check ⚖** |
| Tenant isolation | `subscriptions`, `usage_events`, `invoices` are TENANT; a tenant sees only its own. `plans` is a price catalogue without tenant data. Cross-tenant revenue totals only via the platform aggregate function |
| Human approvals | A plan or price change is a `POLICY_CHANGE` approval by `ORG_OWNER` of the platform org; a credit or refund is a `SPEND` approval. Plan limits are never changed by a service |
| Acceptance | (1) Re-running the rollup over the same ledger range yields no duplicate `usage_events` (idempotency key, 03 §9.2) (**blocking**). (2) Sum of an org's `usage_events` of a meter equals its `cost_ledger` consumed amount for the period (reconciliation test). (3) A tenant over its plan limit is held at admission with a clear reason, not failed silently. (4) Invoice numbers are unique per org; an invoice is never edited after issue (a credit note is a new row). (5) Cross-tenant suite for all four tables |

### 3.11 S11 Client Portal, Brand Kits & White-label [3A minimal kit · 3C portal · T0 kit; T1 approvals; T2 white-label]

| Field | Specification |
|---|---|
| Purpose | Brand kit (logo, colours, fonts, lower-thirds, intro / outro, voice, tone rules, banned words); client portal (calendar, script and video review with time-coded comments, multi-step approvals, version history, one-click approve, mobile-friendly); white-label per agency tenant; email notifications first (directive §1C.6) |
| Owner / scope | Agent 13. **3A**: a minimal `brand_kits` row and its use by Agents 05, 09, 10, 11 (the owner's own kit); no portal. **3C**: portal approvals at **Tier 1** (via managed service), onboarding wizard, white-label and branded reports at **Tier 2**. Stack: ADR-004 (not started) |
| Contracts | `apps/api` + portal pages over the same API as S8; no task type. Approvals use `client_two_step` through S7; comments are rows, not messages. Guest access uses single-purpose, expiring, hash-stored tokens (08 §5.4) |
| Tables | `brand_kits` (T0+; versioned, one current per workspace), `review_comments` (T2), `approvals`, `approval_steps`, `notifications`, `assets`, `voices` |
| Deterministic vs LLM | Fully deterministic; no LLM. A brand kit is data: `banned_words` and `tone_rules` are enforced by the agents' deterministic checks. Branded PDF / email reports: tooling **REQUIRES REVIEW (Phase 1): not decided** |
| Tenant isolation | Brand kit, fonts (licensed font assets) and voices belong to one tenant; white-label settings never expose another tenant's branding; a portal guest sees only assigned items |
| Human approvals | Client approvals are S7 `client_two_step` (reviewer then final approver). Changing a brand kit is an audited action by a user with the right role; a kit change does not retroactively alter an approved render |
| Acceptance | (1) Exactly one current kit per workspace (partial unique index, 04 §5.12). (2) A render records the kit version it used. (3) A `CLIENT_GUEST` cannot see another channel or an unassigned item (**blocking**). (4) A comment on a superseded version is shown as such. (5) Phone-layout review of every portal page (owner rule D.3) |

### 3.12 S12 Integration API & Webhooks [3C · Tier 3]

| Field | Specification |
|---|---|
| Purpose | Versioned REST API with per-tenant API keys / OAuth clients, scoped permissions, rate limits; webhooks for `job.finished`, `approval.needed`, `published`, `failed`, signed and retried (directive §1C.12) |
| Owner / scope | Agent 01. **3C, Tier 3**, built only when a paying enterprise client needs it (§1C.15). The `JobIntake` model of Agent 01 §7.1 becomes a public wire contract only then, through a CCR (agent 01 §7) |
| Contracts | `apps/api` endpoints call the same library paths as the operator tool and S8 (`job.create` is idempotent, 03 §9.2). Webhook delivery is a task type `svc_s12.webhook_deliver` (pending CCR; Agent 01 FR24 names the delivery task) with a bounded retry schedule from 07 (no infinite retries; maximum attempts: configuration, REQUIRES REVIEW) |
| Tables | `api_keys`, `webhooks`, `webhook_deliveries`, `tenant_data_keys` (04 §5.26, §5.19) |
| Deterministic vs LLM | Fully deterministic; no LLM |
| Tenant isolation | An API key is bound to one org and inherits no more than its creator's permissions (08 §7.3); the key resolves the tenant context before any query. Webhook secrets are encrypted with the tenant data key; payloads are built inside the tenant transaction and contain identifiers and states only, no media or personal data unless the client's scope allows it. Outbound URLs pass the SSRF guard (private and loopback targets rejected, 08 §7.3) |
| Human approvals | Creating or revoking a key and registering a webhook are audited actions by `ORG_ADMIN` or `ORG_OWNER`; no approval kind. An API caller can never approve a `FINAL_VIDEO` on behalf of a human unless it is a human actor under the workflow (agents and keys are not approvers) |
| Acceptance | (1) Key shown once; only prefix and hash stored; hash algorithm per 08 §7.3 (REQUIRES REVIEW). (2) Signature includes timestamp and `event_id`; replay is rejected. (3) A delivery retried after failure carries the same `idempotency_key` and event. (4) Tenant A's key against tenant B's resource returns not found, never forbidden-with-detail (**blocking**). (5) Rate limits enforced; values REQUIRES REVIEW (Phase 1) |

### 3.13 S13 Community & Comments [3C · Tier 0+; never auto-post]

| Field | Specification |
|---|---|
| Purpose | Triage comments into question / spam / abuse / lead; **draft** replies for human approval only; never auto-post; the finance rule pack applies so no reply can become advice (directive §3.2; IN-03: no calls, levels or forward-looking statements on named securities, FIN-R1, R2, R3) |
| Owner / scope | Agent 14. **3C**, needs Agent 13's YouTube path first (no upload and no OAuth in 3A). Tier 0+ |
| Contracts | `svc_s13.comment_triage` and `svc_s13.reply_draft` (pending CCR). Fetching and posting go through Agent 13's adapter (the only holder of channel tokens); S13 never sees a token. The capability for comment read / write: reuse `publish_youtube` or add one (pending CCR). The OAuth scope and the quota cost of comment calls: **REQUIRES REVIEW (Phase 1): official YouTube Data API comments methods, scope and quota cost** (YT-12 confirms scope names only; YT-02 / YT-05 are the quota facts for other calls) |
| Flow | fetch (deterministic) → dedupe by `external_comment_id` → deterministic pre-filter (blocklist, link patterns, length) → LLM triage into `comment_triage_class` with `triage_confidence` → below `s13.triage_min_confidence` the class is `UNCLASSIFIED` and goes to a human → for `QUESTION` / `LEAD` only, LLM reply draft (`reply_state = DRAFTED`) → `agent_16.compliance_gate` with the channel's packs on the **draft** (`reply_verdict_id`; subject kind `comment_reply`, pending CCR) → S7 `COMMENT_REPLY` approval → post by Agent 13 only when `reply_state = APPROVED`; then `POSTED` |
| Tables | `community_comments` (04 §5.23; `reply_state = POSTED` requires an `APPROVED` approval, enforced by trigger), `approvals`, `compliance_verdicts`, `publications`, `channels` |
| Deterministic vs LLM | **Deterministic**: fetch, dedupe, blocklist, state machine, posting guard, rate limit on drafts. **LLM**: triage and draft only; the model's output is data, never an instruction. Comment text is untrusted input and may contain prompt injection (08 §5.3): it is passed as quoted data, no tool calls, and the injection cases are in the eval pack. Abuse is flagged to the human, never actioned (hide, report, ban are human actions). A `LEAD` is recorded and routed to the owner as a notification; no direct message is sent |
| Tenant isolation | Comments, drafts and verdicts are TENANT rows; the triage prompt holds no other tenant's text; per-tenant draft rate limits so one channel cannot starve others (05 §7). Author display names are personal data (22; IN-07) with the retention of 22 |
| Human approvals | `COMMENT_REPLY` through `owner_one_tap`; on a finance channel a reply touching a financial claim goes through `owner_sensitive` (24 §3.4). No reply is ever approved by a service |
| Acceptance | (1) No path posts a comment without an `APPROVED` approval: a direct `POSTED` update fails at the DB (**blocking**). (2) Finance answer-key cases (13 §5.12): a drafted reply that gives a buy / sell / hold view or a level for a current instrument is `BLOCKED` (**blocking**). (3) A low-confidence or unparseable triage is `UNCLASSIFIED` and visible to a human, never dropped. (4) A comment containing an instruction to the model does not change behaviour (seeded injection set). (5) Duplicate fetches create one row. (6) Eval pack of at least 20 golden cases (27 §6) |

---

## 4. Decision split summary [3A / 3B / 3C · Tier 0–3]

| Service | Rule-based (code) | LLM judgement (named task type, one prompt, one eval pack) |
|---|---|---|
| S1 | aggregation, cohort suppression, baselines, confidence | optional insight wording from computed numbers |
| S2 | all parts | none |
| S3 | timing fit, length and language checks, gating of the translation | translation |
| S4 | all (09: no model call) | none |
| S5 | all sampling and thresholds | none |
| S6 | all | none |
| S7 | all | none |
| S8 | all | none (shows stored narratives) |
| S9 | all | none |
| S10 | all | none |
| S11 | all | none |
| S12 | all | none |
| S13 | fetch, dedupe, pre-filter, state machine, posting guard | triage, reply drafting |

---

## 5. Tenant isolation, shared tests [3A / 3C · Tier 0–3]

1. Every service in this document adds its tables to the **blocking cross-tenant suite** (04 §3.7; 08 §8.2) when it is built. A service with no such test is not "Implemented" (rule 7).
2. Cache keys use `cache_key()` with `org_id` (27 §7.3.3); logs and metrics carry `org_id`; storage paths are tenant-prefixed (03 §8).
3. A service job that runs across tenants (S1, S5, S10 rollups) iterates tenants and opens **one tenant transaction per tenant**; it never holds a connection that spans two tenants.
4. Aggregates for the platform owner leave a service only through the functions of 04 §3.6, and each such call is audited.

---

## 6. Failure behaviour [3A / 3C · Tier 0]

| Situation | Behaviour (codes from 07 §2) |
|---|---|
| S4 refuses a reservation | `RESOURCE.BUDGET_EXHAUSTED`; task `SUSPENDED` `AWAITING_BUDGET`; no automatic increase (rule 8) |
| S2 returns `FAIL` | gate `BLOCKED`; REVISE up to `max_revision_loops`; then `BLOCKED_COMPLIANCE`; never delivered |
| S7 approval `REJECTED` / `EXPIRED` | `REJECTED_BY_APPROVER`, or the job stays suspended with a notification; never auto-approved |
| S3 native-speaker QC rejected | return to translation; bounded by `max_revision_loops` |
| S12 receiver down | bounded retries with the same idempotency key, then recorded as failed delivery visible to the tenant; never infinite |
| S13 provider or API failure | `EXTERNAL` class retry per 07; comments stay in their last state; none is lost |
| Any service finds a cross-tenant reference | `PERMANENT.CROSS_TENANT_REF`, security event, L3 (07 §7) |
| S1 / S5 / S10 job fails | no data written for the failed window; next run re-computes; failure surfaced as an alert, not silently skipped |

---

## 7. Approvals by service (S7 as the single mechanism) [3A / 3C · Tier 0–3]

| `approval_kind` (GLOSSARY §6.15) | Requested by | Workflow | Build / tier |
|---|---|---|---|
| `FINAL_VIDEO` | orchestrator gate `a_final` (24 §3.3) | `owner_one_tap`; `client_two_step` for client types | **3A** mandatory; T1/T2 client |
| `SCRIPT` | gate `a_script` | `owner_one_tap` | **3A** optional |
| `SENSITIVE_CLAIM`, `COPYRIGHT_DOUBT`, `KNOWLEDGE_RELEASE` | Agents 06 / 16 / 04 on `NEEDS_HUMAN_REVIEW` | `owner_sensitive` | 3A when inserted |
| `COMMENT_REPLY` | S13 | `owner_one_tap` / `owner_sensitive` | 3C |
| `EXPERIMENT` | Agent 14 (from S1 insights) | `owner_one_tap` | 3C |
| `SPEND` | S4 / S10 / S5 recommendations | `owner_sensitive` | 3A (budget), 3C |
| `POLICY_CHANGE` | S10 plan change; rule or threshold change (13 §12) | `owner_sensitive` | 3C |
| Native-speaker QC | S3 | `owner_one_tap` | 3C T1; kind `NATIVE_SPEAKER_QC` (pending CCR) |
| `NEW_CHANNEL`, `NEW_CATEGORY`, `UNUSUAL_PUBLISH`, `DLQ_REPLAY`, `PUBLISH`, others | Agents 01, 03, 13 | per 24 §3.4 | 3C |

S7 never invents a kind or a workflow; this table lists use only.

---

## 8. Configuration keys (names; values REQUIRES REVIEW) [3A / 3C · Tier 0–3]

`s01.min_cohort`, `s01.min_snapshots`; `s02.<part>.*` (thresholds from 3B); `s03.max_tempo_change`; `s05.*` (05 §9); `s07.approval_expiry_ms`, `s07.reminder_ms`; `s12.rate_limit.*`, `s12.webhook.max_attempts`; `s13.triage_min_confidence`, `s13.draft_rate_limit`; model routing `llm.<task_type>.*` (27 §6; ADR-007). Names follow 27 §7.3.1 and are proposals until the config schema is built. No value is stated in this document.

---

## 9. Audit events emitted (proposal; register is 08 §9.2) [3A / 3C · Tier 0–3]

`approval.requested`, `approval.decided`, `approval.withdrawn`, `approval.expired` (S7); `control.<key>.changed` (S8); `membership.changed`, `role.changed`, `session.revoked` (S9); `uniqueness.checked` (S2); `translation.created`, `native_qc.decided` (S3); `comment.triaged`, `comment.reply_drafted`, `comment.reply_posted` (S13); `plan.changed`, `invoice.issued` (S10); `api_key.created`, `api_key.revoked`, `webhook.registered` (S12); `insight.written` (S1); `resource.threshold` (S5; 05 §9.4). S4 and S6 events are listed in 09 and 08.

---

## 10. Build-stage and tier matrix [3A / 3B / 3C · Tier 0–3]

| Service | 3A | 3B | 3C | T0 | T1 | T2 | T3 |
|---|---|---|---|---|---|---|---|
| S1 | no | no | yes | yes | | | |
| S2 | parts (b), (c) | thresholds set from three samples | part (a) | yes | | | |
| S3 | no | no | yes | | yes (dubbing) | | |
| S4 | yes | tuning | | yes | | | |
| S5 | signals only | | yes | yes | | | |
| S6 | 3A controls | | rest | yes | MFA, review | | pen-test, SSO controls |
| S7 | `FINAL_VIDEO`, `SCRIPT` opt., sensitive kinds | | remaining kinds | yes | `client_two_step` managed | portal | |
| S8 | no (operator tool) | no | yes | owner view | tenant view | | platform view |
| S9 | core + RLS + test org | | UI | yes | roles, guests | self-serve signup | SSO / SCIM |
| S10 | no | no | yes | | | yes | |
| S11 | minimal brand kit | | portal | kit | portal approvals | white-label | |
| S12 | no | no | yes | | | | yes |
| S13 | no | no | yes | yes | | | |

3B adds no new service (02 §5); it tunes S2 thresholds and the prompts of the 3A agents.

---

## 11. Acceptance summary for this document [3A / 3B / 3C]

1. Each service has a purpose, owner, tier, contracts, tables, deterministic / LLM split, tenant isolation, approvals and acceptance criteria (sections 3.1–3.13). S4 and S6 reference 09 and 08.
2. No contract, table, enum or task type is defined here that is not in Wave A or listed in section 14.
3. The 3A set (S2 b/c, S4, S6 controls, S7, S9 core, S11 minimal kit) is consistent with 3A_SLICE_SPEC §2.4 and 02 §5.
4. Every threshold and external fact not in RESEARCH_LOG is marked REQUIRES REVIEW (section 13).

---

## 12. Cited research IDs

YT-09 (inauthentic content, S2 and YTG-R1), YT-12 (OAuth scope names, S13), YT-14 (analytics data, S1), YT-15 (multi-language audio, S3), IN-03 (no advice / forward statements, S13), IN-07 (DPDP, S1 / S13), INF-07 and INF-08 (monitoring footprint unknown, S5), INF-11 (RLS, S9), PR-03 (API billed separately from subscriptions; S4 and S3 translation costs go through S4). YT-02 and YT-05 are quota facts for other calls and are not extended to comments.

---

## 13. Open items (all REQUIRES REVIEW, Phase 1)

| # | Need | Where |
|---|---|---|
| 1 | Official YouTube Analytics API audience dimensions, minimum cohort and usage policy | S1 |
| 2 | S2 similarity method and thresholds (set from the 3B golden samples) | S2; 13 §3.1 |
| 3 | Whether the Data API can upload additional audio tracks; quota | S3; 24 §4 |
| 4 | Tempo-change limit for dubbing | S3 |
| 5 | YouTube comments methods: scope, quota cost, moderation constraints | S13 |
| 6 | Approval expiry and reminder timing | S7 |
| 7 | Plan prices, GST handling, invoice rules (owner + accountant / lawyer) | S10 |
| 8 | Webhook retry maximum, API rate limits | S12 |
| 9 | Branded report tooling; portal stack (ADR-004) | S11 |
| 10 | Retention of comment authors and aggregates (22) | S1, S13 |

---

## 14. Contract requests (pending CCR; not edited into Wave A or B-1 here)

Reported to the integrator in the structured summary of this task. This document is written against the proposed names where marked "(pending CCR)".

1. Scheduled system job mechanism and task types `svc_s01.audience_rollup`, `svc_s10.usage_rollup` (same gap as 02 open item 3 and 05 §12).
2. Task types `svc_s13.comment_triage`, `svc_s13.reply_draft`; comment-fetch / post capability decision (reuse `publish_youtube` or add one).
3. `approval_kind` `NATIVE_SPEAKER_QC` for `svc_s03.native_speaker_qc`.
4. Task type `svc_s12.webhook_deliver`.
5. `agent_16.compliance_gate` accepted subject kinds `comment_reply` and `translated_script`.
