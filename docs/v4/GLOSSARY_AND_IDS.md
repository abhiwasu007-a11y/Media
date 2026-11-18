# GLOSSARY_AND_IDS — Terms, identifiers, units, time zones and every status enum

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Shared library `amw_core` (owned by Agent 01; tenancy parts by S9 → 01) |
| Depends on | MASTER_DIRECTIVE.md, 00_EXECUTION_PLAN.md (Q1–Q20), IMPLEMENTATION_PROGRESS.md (Q21–Q26), RESEARCH_LOG.md (YT-02, YT-03, YT-06, YT-08, YT-14, INF-11) |
| Directive sections covered | §1C.1 (hierarchy), §1C.4 (roles), §1C.15 (tiers), §3.1, §3.2, §3.3 (contracts, states, failure taxonomy, escalation, memory, learning loop), §3.4, rule 4 (labels), rule 7 (feature status) |
| Binding for | Every other V4.0 document. A term, ID prefix or enum value that is not defined here must not be used elsewhere; request it through `CONTRACT_CHANGE_REQUESTS.md`. |

---

## 1. Terms

| Term | Definition | Key / table |
|---|---|---|
| **Platform** | The AMW AI Media Factory software and its operator. | — |
| **Platform owner** | The person who operates the platform (directive "owner"). Holds role `PLATFORM_OWNER`. Is also a tenant (Tier 0). | `organisations.kind = PLATFORM_OWNER` |
| **Organisation (org, tenant)** | The unit of isolation. Every tenant-scoped row, queue row, file path, cache key, log line and metric carries `org_id` (§1C.1). "Tenant" and "organisation" are synonyms; code and schemas use `org`. | `organisations` |
| **Workspace** | A brand or client-account area inside an organisation (directive "Workspaces/Brands"). An agency org has one workspace per end-client brand. A workspace owns brand kits, channels and projects. | `workspaces` |
| **Brand** | The identity a workspace presents. Not a separate entity; the brand's look is its **brand kit**. | — |
| **Brand kit** | Versioned brand identity: logo, colours, fonts, lower-thirds, intro/outro, voice, tone rules, banned words (§1C.6). | `brand_kits` |
| **Channel** | A publishing destination account (YouTube channel first) owned by a workspace. | `channels` |
| **Project** | A container of jobs with one purpose: a series, a campaign, a client order or an internal job group. | `projects` |
| **Production type** | A registry entry that defines one product the platform makes: stages, inputs, approvals, templates, QC, rule packs, deliverables, cost model (§3.4). | `production_types`, 24_PRODUCTION_TYPES.md |
| **Job** | One production run of one production type that produces one deliverable set (e.g. one long-form video). A job owns a task graph. | `jobs` |
| **Task** | One unit of work run by one agent stage or service in one job. A task is what the queue carries and what the state machine governs. | `tasks` |
| **Task type** | The kind of work of a task, named `<agent_id>.<task_name>` (e.g. `agent_06.claim_extraction`) or `<service_id>.<task_name>` (e.g. `svc_s03.translate_script`). One task type = one input payload schema + one output payload schema + (if LLM) one prompt file. | — |
| **Stage** | A pipeline position owned by one of the 17 agents (§2: agents are pipeline stages). A stage contains one or more task types. Stage key = agent ID (e.g. `agent_06`). | — |
| **Attempt** | One execution of a task by a worker. Retries and replays create new attempts of the same task. | `task_attempts` |
| **Agent** | One of the 17 pipeline stages of §3.1. No other agent may be created (§2). | IDs `agent_01` … `agent_17` |
| **Shared service** | One of S1–S13 of §3.2, a module with a named owning agent; not an LLM agent unless an ADR justifies it. Owners: S1→14, S2→16, S3→05, S4→15, S5→01, **S6→16, S7→01, S8→01** (plan Q4), S9→01, S10→15, S11→13, S12→01, S13→14. | IDs `svc_s01` … `svc_s13` |
| **Orchestrator** | Agent 01's workflow engine. The only component that decides the next task (§2: control flow in code). | `amw_orchestrator` |
| **Worker** | A process that claims queue rows and runs tasks. It registers declared capabilities (§3.3 Migration). | `workers` |
| **Capability** | A named ability a worker declares; a task lists the capabilities it needs. See §6.20. | — |
| **Resource class** | The admission class of a task (§6.6). The night window and per-tenant limits act on it. | — |
| **Gate** | A blocking check whose failure stops progression (e.g. originality gate, compliance gate, QC gate, approval gate). | — |
| **Approval** | A recorded human decision on an exact subject (bound by content hash), possibly multi-step. | `approvals`, `approval_steps` |
| **Editorial contribution** | A recorded, meaningful human creative input to a job: angle, example, opinion or correction (§1A.7). At least one is required before publish. | `editorial_contributions` |
| **Rule pack** | A versioned set of compliance rules (§1C.7). Platform rule packs cannot be removed by tenants. | `rule_packs` |
| **Compliance profile** | The set of rule packs attached to a channel or workspace. | `compliance_profiles` |
| **Licence** | The terms under which an asset may be used (vendor, scope, third-party permission, expiry). | `licences` |
| **Licence ledger** | One row per use of a licensed item for a tenant, job and render (§1C.8). | `licence_ledger` |
| **Asset** | Any media item (footage, image, music, SFX, font, voice track, chart render) in a tenant's asset library. | `assets` |
| **Knowledge source / chunk** | A document in a tenant's private, channel-isolated knowledge library and its indexed parts (§1B.2a). | `knowledge_sources`, `knowledge_chunks` |
| **Memory item** | A stored piece of context with a scope (§6.30) and an expiry. | `memory_items` |
| **Checkpoint** | A durable snapshot of a task's progress from which it can resume without redoing completed side effects. | `checkpoints` |
| **Dead letter (DLQ item)** | A parked failed task with payload, reason, retry history, traceback, last run and recovery status (§3.3). | `dead_letter` |
| **Idempotency key** | A deterministic key on every external side effect so a retry or replay never duplicates it. | `idempotency_keys` |
| **Circuit breaker** | Per-provider guard with states CLOSED/OPEN/HALF_OPEN. | `circuit_breakers` |
| **Correlation ID** | ID shared by every message, log line, metric and audit row of one job (and its child jobs). | — |
| **Envelope** | The message wrapper exchanged between components (03 §4). | — |
| **Actor** | Whoever causes an action: human user, agent, shared service or system process. See §2.3. | — |
| **Night window** | 00:00–07:00 Asia/Kolkata production window while sharing the server (§1); drain from 06:30; graceful stop at 07:00. Detail in 06_NIGHT_SCHEDULING.md. | — |
| **PT day** | The calendar day in US Pacific time, used for YouTube quota accounting; quotas reset at midnight PT (YT-03). | `quota_usage.pt_date` |
| **Quota bucket** | A separately counted YouTube API quota (YT-02, YT-05). See §6.42. | — |
| **Tier** | Build tier of §1C.15. See §6.47. | — |
| **MVP** | Tier 0 first build: 1 tenant (platform owner), 1 channel, 1 language, with the multi-tenant data model and `org_id` everywhere. | — |
| **Golden dataset** | The fixed eval case set of one LLM step (§3.5.3). | `evals/<agent>/<task>/` |
| **Walking skeleton** | First build ticket: thinnest end-to-end path through real components (§3.5.7; 27 §9). | — |

## 2. Identifiers

### 2.1 Decision: UUIDv7, stored as native `uuid`, shown with a type prefix

| Option | For | Against |
|---|---|---|
| **UUIDv7 (chosen)** | Time-ordered (new rows append to the right of B-tree indexes, good insert locality); 128-bit; fits PostgreSQL's native 16-byte `uuid` type, so no custom type and no text-key bloat; standard format that every driver and tool reads. | Not lexicographically short in text form. |
| ULID | Time-ordered, short 26-char text. | No native PostgreSQL type: stored either as `text` (larger keys, slower joins) or converted to `uuid` anyway; adds a second encoding to maintain. |

Rules:
1. **Storage:** every entity primary key is `uuid` holding a UUIDv7 value, generated in application code by `amw_core.ids.new_id(entity)` (never by the DB default, so IDs are known before insert and are identical across DB versions). The generator implementation (standard library or pinned package) is chosen in 27 §3; **REQUIRES REVIEW (Phase 1): record the UUIDv7 specification (RFC 9562) and the chosen generator's support in RESEARCH_LOG.md — the official hosts were blocked in this session (rfc-editor.org, docs.python.org, postgresql.org).**
2. **Wire / log / UI form:** `<prefix>_<canonical lowercase UUID>`, e.g. `job_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e9f`. Regex per entity: `^<prefix>_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`.
3. The prefix is **not** stored in the DB. It is added on output and checked and stripped on input; a wrong prefix is `PERMANENT.INPUT_INVALID` (07 §2).
4. IDs are never reused, never derived from personal data and never meaningful beyond time order.
5. External IDs (YouTube video ID, channel ID, provider request IDs) are stored as `text` in columns named `external_*` and are never used as primary keys.
6. Registry keys (production types, rule packs, task types, config keys) are human-readable slugs, not UUIDs (§2.4).

### 2.2 Prefix table (every entity)

| Prefix | Entity | Table |
|---|---|---|
| `org` | Organisation (tenant) | organisations |
| `wsp` | Workspace (brand / client account) | workspaces |
| `chn` | Channel | channels |
| `usr` | User | users |
| `mbr` | Membership | memberships |
| `ses` | User session | user_sessions |
| `uar` | User auth reference | user_auth_refs |
| `ivt` | Invitation | invitations |
| `prj` | Project | projects |
| `job` | Job | jobs |
| `tsk` | Task | tasks |
| `att` | Task attempt | task_attempts |
| `stt` | State transition record | state_transitions |
| `qit` | Queue item | task_queue |
| `dlq` | Dead-letter item | dead_letter |
| `ckp` | Checkpoint | checkpoints |
| `cbk` | Circuit breaker | circuit_breakers |
| `msg` | Message (envelope) | message_log |
| `cor` | Correlation ID | (column only) |
| `aud` | Audit log entry | audit_log |
| `cst` | Cost ledger entry | cost_ledger |
| `bgt` | Budget | budgets |
| `bgr` | Budget reservation | budget_reservations |
| `lic` | Licence | licences |
| `lcu` | Licence ledger entry (use) | licence_ledger |
| `ast` | Asset | assets |
| `afp` | Asset fingerprint | asset_fingerprints |
| `vce` | Voice | voices |
| `vcn` | Voice consent | voice_consents |
| `bkt` | Brand kit | brand_kits |
| `cpf` | Compliance profile | compliance_profiles |
| `rpk` | Rule pack (row) | rule_packs |
| `cvd` | Compliance verdict | compliance_verdicts |
| `kcl` | Knowledge collection (CCR-011) | knowledge_collections |
| `ksr` | Knowledge source | knowledge_sources |
| `kch` | Knowledge chunk | knowledge_chunks |
| `mem` | Memory item | memory_items |
| `scr` | Script (version row) | scripts |
| `clm` | Claim | claims |
| `cit` | Citation | citations |
| `apr` | Approval | approvals |
| `aps` | Approval step | approval_steps |
| `edc` | Editorial contribution | editorial_contributions |
| `oie` | Owner instruction evidence (CCR-010) | owner_instruction_evidence |
| `qsc` | Quality score line | quality_scores |
| `qcr` | QC result | qc_results |
| `rnd` | Render | renders |
| `pub` | Publication / delivery | publications |
| `oat` | OAuth token | oauth_tokens |
| `dek` | Tenant data key | tenant_data_keys |
| `gcp` | GCP project registration | gcp_projects |
| `ans` | Analytics snapshot | analytics_snapshots |
| `exp` | Experiment | experiments |
| `ntf` | Notification | notifications |
| `rvc` | Review comment (client portal) | review_comments |
| `cmt` | Community comment (S13) | community_comments |
| `ctl` | Control setting | org_controls |
| `dtr` | Data request (export / erasure) | data_requests |
| `wkr` | Worker | workers |
| `prt` | Production type row | production_types |
| `opt` | Org production-type setting | org_production_types |
| `key` | API key (Tier 3) | api_keys |
| `whk` | Webhook (Tier 3) | webhooks |
| `whd` | Webhook delivery (Tier 3) | webhook_deliveries |
| `pln` | Plan (Tier 2) | plans |
| `sub` | Subscription (Tier 2) | subscriptions |
| `use` | Usage event (Tier 2) | usage_events |
| `ivc` | Invoice (Tier 2) | invoices |
| `sso` | SSO connection (Tier 3) | org_sso_connections |
| `dom` | Verified domain (Tier 3) | org_domains |
| `run` | Eval run | (eval result files, 27 §6) |

### 2.3 Actor reference (`actor_ref`)
Used in `source_agent`, `sender`, `receiver`, audit and transition rows.

| Kind (`actor_kind`) | Format | Example |
|---|---|---|
| `AGENT` | `agent_NN`, NN = 01–17 | `agent_06` |
| `SERVICE` | `svc_sNN`, NN = 01–13 | `svc_s04` |
| `HUMAN` | user wire ID | `usr_0192…` |
| `SYSTEM` | `sys_<name>`, name ∈ {`scheduler`, `reaper`, `dlq_handler`, `migrator`, `api`, `operator`} | `sys_reaper` |

`sys_operator` (CCR-010, decision D5) is the operator tool through which the assistant records owner decisions, scores and editorial contributions **on the owner's behalf**. It is never an approver itself: every row it writes names the owner's `usr_` ID as the decision maker and references an `owner_instruction_evidence` row (04 §5.16).

Regex: `^(agent_(0[1-9]|1[0-7])|svc_s(0[1-9]|1[0-3])|usr_<uuidv7>|sys_[a-z_]{3,32})$`; the exact pattern is `amw.common#/$defs/actor_ref` (03 §3.2).

### 2.4 Registry keys and derived keys

| Key | Format | Example |
|---|---|---|
| Task type | `<agent_id or service_id>.<snake_case>` | `agent_06.claim_extraction` |
| Payload schema name | `<task_type>.input` / `<task_type>.output` | `agent_06.claim_extraction.output` |
| Step schema name (CCR-018) | `<task_type>.<step>.input` / `<task_type>.<step>.output`, one pair per LLM step inside a task type; `<step>` is a short snake-case step key declared in the blueprint and used unchanged in the prompt header, the `llm.<task_type>.<step>.*` config keys and the eval folder | `agent_09.shot_plan.direction.output` |
| Agent document schema (CCR-018) | `<agent_id>.<snake_case>`: a blob document owned by one agent that is not a task payload (e.g. a script document, a pronunciation dictionary) | `agent_05.script_document` |
| External reference ID (CCR-044) | `ext_` + 24 lowercase hex = the first 24 hex characters of SHA-256 over the canonical `{"org_id": …, "url": <normalised URL>}`; the org part makes the ID tenant-specific; never a primary key. **URL normalisation** (CCR-066), applied in this order: scheme must be `https` (lowercase); host lowercased and IDNA-encoded (punycode), trailing dot removed; port `443` removed; fragment removed; percent-encodings of unreserved characters (RFC 3986: `A–Z a–z 0–9 - . _ ~`) decoded and all remaining percent-encodings uppercased; dot-segments (`.`/`..`) removed; an empty path becomes `/`; any other trailing slash is kept as given; query parameters sorted by name, then by value, keeping duplicates and empty values; nothing else is removed or rewritten | `ext_3f9a…` |
| Contract schema name | `amw.common`, `amw.task_input`, `amw.task_output`, `amw.envelope`, `amw.error`, `amw.control`, `amw.owner_topic` (03; CCR-006); `amw.production_type` (registry record, 24 §2) | — |
| Schema `$id` | `urn:amw:schema:<schema name>:<semver>` | `urn:amw:schema:amw.task_input:1.0.0` |
| Production type key | `UPPER_SNAKE` (§6.48) + integer version | `CHANNEL_LONG_FORM` v1 |
| Rule pack key | `rp.<snake_case>` (§6.37) + integer version | `rp.finance_sebi_in` v1 |
| Rule ID | `<PACK>-R<n>` | `FIN-R6` |
| Prompt ID | `<agent_id>/<task>.v<N>`; file `prompts/<agent package>/<task>.v<N>.md` (package names 27 §7.2) | `agent_06/claim_extraction.v1` → `prompts/agent_06_fact_checker/claim_extraction.v1.md` |
| Idempotency key | `idk_` + 64 lowercase hex = SHA-256 of the canonical key material (03 §9) | `idk_9f2c…` |
| Config key | dotted snake case; namespaces in 27 §4.2 (CCR-019) | `retry.temporary.max_attempts` |
| Check ID | `^[a-z0-9_.-]{3,96}$` (03 §5.2); namespaces in 18 §13 (CCR-020): `qc.*` / `edit.*` owned by 18, `aNN.*` owned by blueprint NN | `qc.audio.integrated_lufs` |
| Storage URI | 03 §8 | `amw-blob://org_…/jobs/job_…/renders/rnd_….mp4` |
| Cache key | `amw:<org wire id>:<area>:<key>` — the org part is mandatory (§1C.1) | `amw:org_…:kb:kch_…` |
| Metric label | every factory metric carries label `org_id` (platform-wide metrics use `org_id="platform"`) | — |

## 3. Units

| Quantity | Unit / representation | Column suffix / JSON field rule |
|---|---|---|
| Money (budgets, prices, invoices, plan limits) | **Integer minor units** of an ISO 4217 currency (INR → paise) + `currency` (3 uppercase letters) | `_minor` (`bigint`), always paired with `currency char(3)` |
| Per-call cost (cost ledger, reservations) | **Integer micros** = 10⁻⁶ of the currency's major unit, because single LLM calls cost fractions of a minor unit; converted to minor units with round-half-up only at aggregation/reporting | `_micros` (`bigint`) + `currency` |
| FX conversion | Rate stored per ledger row with its source reference; never implied | `fx_rate numeric(18,8)`, `fx_source text` — **REQUIRES REVIEW (Phase 1): FX source to use (09_COST_AND_BUDGET)** |
| Durations, timeouts, backoff, media length | **Milliseconds**, integer | `_ms` (`bigint`); JSON field `duration` of Task Output is ms (name fixed by §3.3) |
| Calendar periods | ISO 8601 duration strings only in config (`P1D`) | — |
| Loudness | LUFS (integrated), decimal with 2 places | `_lufs numeric(5,2)` |
| True peak / relative level | dBTP / dB, decimal with 2 places | `_dbtp`, `_db numeric(5,2)` |
| Sizes | Bytes, integer | `_bytes bigint` |
| Bitrate | Bits per second, integer | `_bps bigint` |
| Sample rate | Hz, integer | `_hz int` |
| Frame rate | Rational numerator/denominator | `fps_num int`, `fps_den int` |
| Resolution | Pixels | `width_px`, `height_px int` |
| Tokens | Integer counts per call: input, output, cached input | `tokens_in`, `tokens_out`, `tokens_cached_in int` |
| Ratios / probabilities / confidence | Decimal 0.0–1.0 | `confidence numeric(4,3)` |
| Quality score | 0–100 points (§1A.7) | `numeric(5,2)` |
| YouTube quota | Units per bucket (YT-02) | `units bigint` |
| Language | BCP 47 tag (e.g. `mr`, `mr-IN`, `hi`, `en-IN`) | `language text` |
| Country | ISO 3166-1 alpha-2 | `country char(2)` |
| Aspect ratio | String `W:H` from §6.50 | — |

Labels for figures (rule 4, §1B): `ESTIMATE`, `MEASURED` (with date), `PROJECTION`, `ACTUAL`, `PROPOSAL`, `VERIFIED` (cost figure confirmed by provider usage/invoice). Enum `figure_label` §6.46.

## 4. Time zones

| Rule | Detail |
|---|---|
| Storage | Every timestamp is `timestamptz` stored in UTC. JSON timestamps are RFC 3339 / ISO 8601 with `Z` (e.g. `2026-01-01T00:00:00.000Z` in examples only). |
| Display | Default display zone `Asia/Kolkata` (owner, IST). `organisations.display_timezone` overrides per tenant (Tier 1+). |
| Night window | Evaluated in `Asia/Kolkata` while sharing the server (§1); becomes per-tenant config on a dedicated server. |
| YouTube quota day | US Pacific time; IANA zone `America/Los_Angeles`. `pt_date = (ts AT TIME ZONE 'America/Los_Angeles')::date`. Reset = midnight PT (YT-03). |
| Budget periods | Day/month boundaries in the org's `display_timezone` (default `Asia/Kolkata`). |
| Analytics report dates | **REQUIRES REVIEW (Phase 1): confirm which time zone the YouTube Analytics / Reporting APIs use for report dates (YT-14 pages) before Agent 14 stores `metric_date`.** |
| Chart-reading logic | No chart-reading rule may depend on day, date, session or clock time (owner rule C.4). Only operational settings (window, quota day, budget period) are time-based. |

## 5. Naming conventions
- DB: `snake_case`, plural table names, enum values stored as `text` with `CHECK (col IN (...))` (not PostgreSQL `ENUM` types, so adding a value is an additive migration).
- JSON: `snake_case` keys; enum values `UPPER_SNAKE` except values that mirror an external API (e.g. YouTube `privacyStatus` values), which keep the external spelling.
- Booleans start with `is_`, `has_` or a verb (`contains_synthetic_media` mirrors YT-06).

---

## 6. Status and value enums (master list)

Every enum used anywhere in V4.0 is defined here. Values are exact.

### 6.1 `task_state` (§3.3 state machine; transitions in 03 §11.3)
| Value | Meaning | Terminal |
|---|---|---|
| `PENDING` | Created; waiting for dependencies. | no |
| `VALIDATING` | Input contract, tenant, idempotency and budget pre-checks running. | no |
| `QUEUED` | Has a `READY` queue row; waiting for admission and a worker. | no |
| `RUNNING` | Claimed by a worker under a lease. | no |
| `CHECKPOINTED` | Suspended with a durable checkpoint; holds no worker; waits for its `wait_reason` to clear. | no |
| `RETRY_WAIT` | Last attempt failed with a retryable error; waits until `next_attempt_at`. | no |
| `COMPLETED` | Output validated and persisted. | **yes** |
| `FAILED` | Failure decided (non-retryable or attempts exhausted); DLQ hand-off pending. | no (only exits: `DEAD_LETTER`, `CANCELLED`) |
| `DEAD_LETTER` | Parked in the DLQ; only a human replay or discard moves it. | **yes** for automation (human exits only) |
| `CANCELLED` | Stopped by a recorded cancel decision. | **yes** |

### 6.2 `job_state`
Same value set as `task_state` **without `RETRY_WAIT`** (retries are task-level only). Derivation rules: 03 §11.5.

### 6.3 `wait_reason` (sub-status, only when state = `CHECKPOINTED`; NULL otherwise)
| Value | Set by | Clears when |
|---|---|---|
| `DRAIN` | Night-window drain / graceful stop (06) | window open again and admission allows |
| `AWAITING_APPROVAL` | Approval gate reached | linked approval decided (any final state) |
| `AWAITING_QUOTA` | YouTube quota bucket exhausted (YT-02/03) | PT-day reset or quota freed |
| `AWAITING_BUDGET` | S4 budget guard suspended the task | budget raised/reset or human release |
| `AWAITING_EXTERNAL` | External processing pending (e.g. destination processing) | external status ready, or wait timeout |
| `OPERATOR_PAUSE` | Emergency stop / manual pause (S8) | human resume |

### 6.4 `job_outcome` (set only when `job_state = COMPLETED`)
`PUBLISHED` · `DELIVERED` (files delivered to the requester, owner or client; CCR-043) · `BLOCKED_COMPLIANCE` (a blocking gate refused and the revision cap was reached) · `REJECTED_BY_APPROVER` · `NO_DELIVERABLE` (internal jobs such as analytics ingestion).

### 6.5 `priority`
| Value | Queue integer |
|---|---|
| `CRITICAL` | 0 |
| `HIGH` | 1 |
| `NORMAL` | 2 |
| `LOW` | 3 |
| `BACKGROUND` | 4 |

### 6.6 `resource_class`
`LIGHT` (DB/logic only) · `AI_IO` (waits on external AI APIs, low CPU) · `HEAVY_CPU` (FFmpeg render, media analysis) · `PUBLISH` (uploads/quota-using calls). The 06:30 drain stops admitting `HEAVY_CPU` (06 defines whether `AI_IO` is included).

### 6.7 `queue_item_status`
`READY` · `CLAIMED` · `DONE` · `CANCELLED`.

### 6.8 `attempt_result`
`SUCCEEDED` · `FAILED_RETRYABLE` · `FAILED_FINAL` · `SUSPENDED` · `LEASE_EXPIRED` · `CANCELLED` · `RUNNING` (open attempt).

### 6.9 `output_status` (Task Output `status`)
`SUCCEEDED` · `FAILED` · `SUSPENDED` · `REJECTED` (input refused at validation).

### 6.10 `next_action_type` (Task Output `next_action.type`)
`CONTINUE` · `WAIT` · `RETRY` · `ESCALATE` · `STOP`. Advisory only; the orchestrator decides (03 §5.3).

### 6.11 `feature_status` (rule 7; display strings exact)
| DB value | Display |
|---|---|
| `PLANNED` | Planned |
| `IN_DEVELOPMENT` | In Development |
| `IMPLEMENTED` | Implemented |
| `TESTED` | Tested |
| `PRODUCTION_READY` | Production Ready |

### 6.12 `doc_status` (documentation track, docs/v4/README.md)
`Not started` · `Draft` · `Partial (blocked)` · `Complete` · `Audited`.

### 6.13 `approval_state`
`PENDING` · `APPROVED` · `REJECTED` · `CHANGES_REQUESTED` · `EXPIRED` · `WITHDRAWN`. Final: all except `PENDING`.

### 6.14 `approval_step_state`
`NOT_STARTED` · `PENDING` · `APPROVED` · `REJECTED` · `CHANGES_REQUESTED` · `SKIPPED`.

### 6.15 `approval_kind`
`TOPIC` · `BRIEF` · `CONCEPT` · `SCRIPT` · `STORYBOARD` · `VOICE_SAMPLE` · `ROUGH_CUT` · `FINAL_VIDEO` · `THUMBNAIL` · `METADATA` · `PUBLISH` · `SPEND` · `NEW_CHANNEL` · `NEW_CATEGORY` · `SENSITIVE_CLAIM` · `COPYRIGHT_DOUBT` · `UNUSUAL_PUBLISH` · `POLICY_CHANGE` · `DLQ_REPLAY` · `EXPERIMENT` · `COMMENT_REPLY` · `KNOWLEDGE_RELEASE` (Q26: owner releases private method material per topic) · `USAGE_RIGHTS` (ads, §1D.1).

### 6.16 `editorial_contribution_type` (§1A.7)
`ANGLE` · `EXAMPLE` · `OPINION` · `CORRECTION`.

### 6.17 `licence_state`
`PENDING_VERIFICATION` · `ACTIVE` · `EXPIRING` (inside the warning window set in config) · `EXPIRED` · `REVOKED` · `REJECTED`.

### 6.18 `licence_source_type`
`OWNER_MADE` · `CLIENT_SUPPLIED` · `PAID_STOCK` · `FREE_STOCK` · `CODE_GENERATED` · `AI_GENERATED` · `MUSIC_LIBRARY` · `SFX_LIBRARY` · `FONT` · `TTS_PROVIDER` · `VOICE_CLONE` · `HUMAN_NARRATION`.

### 6.19 `visual_source_tier` (§1A.1 hierarchy a–e)
`A_OWNER_REAL` · `B_LICENSED_STOCK` · `C_CODE_MOTION` · `D_AI_VIDEO` · `E_AI_STILL`.

### 6.20 `capability` (worker / task)
`llm` · `tts` · `image_gen` · `video_gen` · `stock_search` · `music_search` (CCR-007; 3B) · `render_ffmpeg` · `media_probe` · `doc_extract` (CCR-014; document text extraction for `agent_04.knowledge_ingest`) · `web_fetch` (CCR-015; allow-listed HTTPS reference fetch) · `publish_youtube` · `file_delivery` · `analytics_ingest` · `notify_email`. New capabilities are additive via CCR.

### 6.21 `third_party_permission`
`PERMITTED` · `NOT_PERMITTED` · `UNKNOWN`. `UNKNOWN` blocks use for any tenant other than the licence holder's own channels (§1C.8).

### 6.22 `licence_usage_kind`
`SHOT` · `IMAGE` · `MUSIC_BED` · `SFX` · `VOICE` · `FONT` · `TEMPLATE` · `AI_OUTPUT`.

### 6.23 `publish_state` (`publications.state`)
| Value | YouTube | File delivery |
|---|---|---|
| `DRAFT` | yes | yes |
| `UPLOADING` | yes (resumable session open) | yes |
| `UPLOADED_PRIVATE` | yes (always uploaded with `privacyStatus=private`, YT-04) | — |
| `PROCESSING` | yes | — |
| `READY_PRIVATE` | yes | — |
| `SCHEDULED` | yes | — |
| `PUBLISHED` | yes | — |
| `DELIVERED` | — | yes |
| `VERIFIED` | yes | yes (client acknowledgement) |
| `FAILED` | yes | yes |
| `REMOVED` | yes | — |

### 6.24 `privacy_status` (mirrors YouTube `status.privacyStatus`)
`private` · `public` (YT-04) · `unlisted` — **REQUIRES REVIEW (Phase 1): confirm the full allowed value list on the official `videos` resource page (YT-06 source) before Agent 13 is blueprinted.**

### 6.25 `verification_state`
`NOT_CHECKED` · `MATCH` · `MISMATCH`.

### 6.26 `destination_kind`
`YOUTUBE` · `FILE_DELIVERY`. Others are added by CCR (Tier 2+).

### 6.27 `check_verdict` (one deterministic / judge / human check)
`PASS` · `FAIL` · `WARN` · `SKIPPED`.

### 6.28 `check_kind`
`DETERMINISTIC` · `LLM_JUDGE` · `HUMAN`.

### 6.29 `compliance_verdict`
`ALLOWED` · `BLOCKED` · `NEEDS_HUMAN_REVIEW`.

### 6.30 `memory_scope` (§3.3 Memory)
`WORKING` (inside one attempt) · `TASK` · `PROJECT` · `CHANNEL` · `LONG_TERM` (tenant knowledge). Isolation and expiry rules: 04 §5.10.

### 6.31 `failure_class` (§3.3 taxonomy; codes in 07 §2)
`TEMPORARY` · `PERMANENT` · `RESOURCE` · `AGENT` · `INFRASTRUCTURE` · `PUBLISHING`.

### 6.32 `circuit_state`
`CLOSED` · `OPEN` · `HALF_OPEN`.

### 6.33 `dlq_recovery_status`
`NEW` · `TRIAGED` · `REPLAY_REQUESTED` · `REPLAY_APPROVED` · `REPLAYED` · `RESOLVED` · `DISCARDED`.

### 6.34 `escalation_level`
`L1` (automatic recovery) · `L2` (orchestrator intervention) · `L3` (human).

### 6.35 `experiment_state` (§3.3 learning loop)
`PROPOSED` · `APPROVED_TO_RUN` · `RUNNING` · `COMPLETED` · `INCONCLUSIVE` · `VALIDATED` · `REJECTED` · `APPLIED` · `ABORTED`.

### 6.36 `experiment_decision` / `experiment_kind`
Decision: `ADOPT` · `REJECT` · `EXTEND` · `NONE`. Kind: `TITLE_THUMBNAIL_STUDIO_TEST` (human-in-Studio, YT-08) · `PROMPT_VARIANT` · `TEMPLATE_VARIANT` · `SCHEDULE_VARIANT` · `FORMAT_VARIANT`.

### 6.37 Rule pack keys and `rule_pack_scope`, `rule_severity`
Scope: `PLATFORM` (cannot be removed by tenants) · `TENANT`. Severity: `BLOCKING` · `WARNING`.

| Key | Scope | Always on | Source section |
|---|---|---|---|
| `rp.youtube_general` | PLATFORM | yes, every YouTube destination | §1, §1C.7, YT-06/07/09 |
| `rp.finance_sebi_in` | PLATFORM | when the channel/category is finance | §1, §1B.2 |
| `rp.health` | PLATFORM | by category | §1C.7 |
| `rp.kids` | PLATFORM | by category | §1C.7 |
| `rp.political_news` | PLATFORM | by category | §1C.7 |
| `rp.advertising_asci_in` | PLATFORM | every ad production type | §1D |
| `rp.ad_sector_<sector>` | PLATFORM | by ad category; sectors: `health_wellness`, `food`, `financial_products`, `education_outcomes`, `real_estate`, `alcohol_tobacco_surrogate` | §1D.3 |
| `rp.tenant_brand_safety` | TENANT | tenant-defined | §1C.7 |

### 6.38 Finance rule IDs (`rp.finance_sebi_in`) — identifiers for directive clauses §1 and §1B.2
Full rule text, examples and enforcement detail are owned by 13_COMPLIANCE_YOUTUBE_POLICY.md; the IDs are fixed here so prompts, evals and DB rows agree.

| Rule ID | Directive clause |
|---|---|
| `FIN-R1` | No buy/sell/hold call. |
| `FIN-R2` | No entry, exit, stop-loss or target level for a current instrument. |
| `FIN-R3` | No "what to do tomorrow / this week" market view (forward view on a current market). |
| `FIN-R4` | No live-market session, live trade screen-share or "live strategy" session. |
| `FIN-R5` | No paid group giving ongoing market guidance. |
| `FIN-R6` | No performance, profit or return claim. |
| `FIN-R7` | No profit testimonial. |
| `FIN-R8` | No broker referral/affiliate or any paid association with a SEBI-regulated entity while the owner is unregistered. |
| `FIN-R9` | Market price data only when older than the prescribed lag (config `compliance.finance_sebi_in.price_data_lag_days` = **30**, applied at publish time; IN-02: SEBI circular 8 May 2026, effective 1 Jul 2026). |
| `FIN-R10` | Every finance video carries the required disclaimer; a disclaimer never turns advice into education. |
| `FIN-R11` | No AI presenter persona on a finance channel (§1, YT-09). |
| `FIN-R12` | "Our method" content only on historical charts, clearly labelled, only from material the owner released (§1B.2a, Q26). |
| `FIN-R13` | No forward-looking statement about the future direction of a named security, **even when the chart uses historical data older than the lag** (IN-03: SEBI final order of 23 Oct 2026 bars "historical data which provides future directional movement for a specified security"). |

### 6.38a YouTube general rule IDs (`rp.youtube_general`, CCR-040)
Rule text, tests and evidence are owned by 13 §3; the IDs are fixed here.

| Rule ID | Rule (short) |
|---|---|
| `YTG-R1` | Inauthentic / mass-produced content gate |
| `YTG-R2` | No AI persona presenting a sensitive topic |
| `YTG-R3` | Synthetic/altered-media disclosure decision recorded |
| `YTG-R4` | Human editorial contribution and human approval on every video |
| `YTG-R5` | Reused / third-party content only with a recorded right |
| `YTG-R6` | Licence completeness and validity for every asset, music and font |
| `YTG-R7` | Made-for-kids handling |
| `YTG-R8` | Publication defaults: `privacyStatus` explicit |
| `YTG-R9` | Source-library copyright: no reproduction or close paraphrase |
| `YTG-R10` | IT Rules synthetic-information declaration and provenance label |
Prefixes `HLT` (`rp.health`), `KID` (`rp.kids`), `POL` (`rp.political_news`), `ASC` (`rp.advertising_asci_in`) are reserved; their IDs are fixed by CCR when each pack is written.

### 6.39 `claim_type` (Agent 06)
`FACTUAL` · `STATISTICAL` · `DEFINITION` · `HISTORICAL_MARKET` · `HYPOTHETICAL_EXAMPLE` · `RECOMMENDATION` · `FORWARD_VIEW` · `PRICE_LEVEL` · `PERFORMANCE_CLAIM` · `TESTIMONIAL` · `PROMOTION` · `QUOTED_THIRD_PARTY` · `PRODUCT_CLAIM` · `COMPARATIVE` · `OPINION`.

### 6.40 `claim_status`
`EXTRACTED` · `VERIFIED` · `CONTRADICTED` · `UNVERIFIABLE` · `NEEDS_SUBSTANTIATION` · `SUBSTANTIATED` · `REMOVED`.

### 6.41 `time_reference_kind`
`HISTORICAL` · `CURRENT` · `FUTURE` · `TIMELESS` · `UNSPECIFIED`.

### 6.42 `quota_bucket` (YouTube Data API, YT-02, YT-05)
`VIDEO_UPLOADS` · `SEARCH` · `BATCH_GET_STATS` · `DEFAULT` (all other endpoints).

### 6.43 `disclosure_decision` (YT-06/07; IT Rules / ASCI labels per 25)
`REQUIRED` · `NOT_REQUIRED` · `NEEDS_HUMAN_REVIEW`.

### 6.44 Identity and tenancy enums
| Enum | Values |
|---|---|
| `role` (§1C.4) | `PLATFORM_OWNER` · `ORG_OWNER` · `ORG_ADMIN` · `PRODUCER` · `REVIEWER_APPROVER` · `FINANCE` · `VIEWER` · `CLIENT_GUEST` |
| `org_kind` | `PLATFORM_OWNER` · `CLIENT` · `AGENCY` |
| `org_status` | `ACTIVE` · `SUSPENDED` · `OFFBOARDING` · `DELETED` |
| `workspace_status`, `project_status` | `ACTIVE` · `ARCHIVED` |
| `project_kind` | `SERIES` · `CAMPAIGN` · `CLIENT_ORDER` · `INTERNAL` |
| `user_status` | `ACTIVE` · `DISABLED` · `DELETED` |
| `membership_status` | `INVITED` · `ACTIVE` · `SUSPENDED` · `REMOVED` |
| `invitation_state` | `PENDING` · `ACCEPTED` · `EXPIRED` · `REVOKED` |
| `auth_provider` | `LOCAL_PASSWORD` · `GOOGLE` · `SAML` (Tier 3) · `OIDC` (Tier 3) |
| `channel_platform` | `YOUTUBE` |
| `channel_status` | `DRAFT` · `CONNECTED` · `NEEDS_REAUTH` · `PAUSED` · `DISCONNECTED` |
| `audience_kind` (CCR-081) | `GENERAL` · `KIDS` (the channel-setup decision of 13 §3.7, made by a human; NULL = not decided) |
| `oauth_token_status` | `ACTIVE` · `REFRESH_FAILED` · `REVOKED` · `EXPIRED` |
| `data_key_status` | `ACTIVE` · `RETIRED` · `DESTROYED` |
| `gcp_ownership` | `PLATFORM` · `CLIENT_OWNED` |
| `google_review_status` (OAuth verification, API audit) | `NOT_STARTED` · `IN_REVIEW` · `PASSED` · `FAILED` |
| `actor_kind` | `HUMAN` · `AGENT` · `SERVICE` · `SYSTEM` |
| `consent_state` (voice) | `PENDING_VERIFICATION` · `VERIFIED` · `WITHDRAWN` · `EXPIRED` · `REJECTED` |
| `voice_kind` | `PROVIDER_STOCK` · `CONSENTED_CLONE` · `HUMAN_RECORDED` |
| `presenter_kind` (CCR-027, **provisional until the owner answers 3A R4**) | `NEUTRAL_NARRATION` (voice only, no persona, no named presenter) · `OWNER_VOICE` (the owner's own recording or a consented clone of the owner's own voice) · `SYNTHETIC_PERSONA` (a synthetic voice or face presented as a named person; blocked on finance, health and political channels by FIN-R11 / YTG-R2) |
| `approval_channel` (CCR-010, D5) | `OWNER_CHAT_OPERATOR` (3A: the owner's chat message recorded by the operator tool, `sys_operator`, with an `owner_instruction_evidence` row) · `WEB_DASHBOARD` (3C: the owner acts in the authenticated dashboard) · `CLIENT_PORTAL` (Tier 2) |
| `evidence_state` (CCR-010) | `PENDING_VERIFICATION` · `VERIFIED` · `CONFIRMED` · `REFUSED` (04 §5.16 `owner_instruction_evidence`) |
| `evidence_record_kind` (CCR-010) | `STEP_DECISION` · `CONTRIBUTION` · `HUMAN_SCORE` · `COMPLIANCE_DECISION` · `OWNER_TOPIC` · `DATASET_INTAKE` · `KNOWLEDGE_RELEASE_REQUEST` |
| `evidence_verification_kind` (CCR-059; the rule set per record kind, 03 §11.6 table) | `DECISION` (`STEP_DECISION`, `COMPLIANCE_DECISION`, `KNOWLEDGE_RELEASE_REQUEST`) · `CONTENT` (`CONTRIBUTION`, `OWNER_TOPIC`, `DATASET_INTAKE`) · `SCORE` (`HUMAN_SCORE`) |
| `instruction_source_kind` (CCR-010) | `OWNER_CHAT_MESSAGE` (the only value that can back a human record) · `TOOL_RESULT` · `SUBAGENT_MESSAGE` · `NOTIFICATION` · `DOCUMENT` (refused sources, stored only on refused evidence rows for audit) |
| `data_request_kind` / `data_request_status` | `EXPORT` · `ERASURE` / `RECEIVED` · `IN_PROGRESS` · `COMPLETED` · `REJECTED` |

### 6.45 Content, media and operations enums
| Enum | Values |
|---|---|
| `script_status` | `DRAFT` · `IN_REVIEW` · `APPROVED` · `REJECTED` · `SUPERSEDED` |
| `render_kind` | `MASTER` · `EXPORT` · `PREVIEW` |
| `render_status` | `RENDERING` · `COMPLETE` · `QC_PASSED` · `QC_FAILED` · `SUPERSEDED` |
| `asset_kind` | `VIDEO` · `IMAGE` · `AUDIO_MUSIC` · `AUDIO_SFX` · `AUDIO_VOICE` · `FONT` · `CHART` · `SUBTITLE` · `TEMPLATE` · `DOCUMENT` |
| `asset_status` | `ACTIVE` · `QUARANTINED` · `EXPIRED` · `DELETED` |
| `fingerprint_algo` | `SHA256` · `PERCEPTUAL_FRAME` · `AUDIO` (algorithms chosen in agent_08 blueprint) |
| `knowledge_source_kind` | `BOOK` · `COURSE_NOTES` · `OWNER_NOTES` · `WEB_REFERENCE` · `OFFICIAL_DOCUMENT` · `CLIENT_DOCUMENT` |
| `knowledge_source_status` | `REGISTERED` · `INGESTING` · `INDEXED` · `FAILED` · `RETIRED` |
| `extraction_method` (CCR-013) | `TEXT_LAYER` · `OCR` |
| `source_ownership` | `OWNED_COPY` · `LICENSED` · `OWNER_AUTHORED` · `PUBLIC_OFFICIAL` · `UNKNOWN` (Q25: owner item) |
| `citation_support` | `SUPPORTS` · `PARTIAL` · `CONTRADICTS` |
| `quality_dimension` (§1A.7, max points) | `RESEARCH_ACCURACY` 20 · `STORYTELLING` 15 · `AUDIENCE_VALUE` 15 · `VISUAL_QUALITY` 15 · `AUDIO_QUALITY` 10 · `EDITING_QUALITY` 10 · `THUMBNAIL_METADATA` 10 · `COMPLIANCE` 5 |
| `analytics_source` | `ANALYTICS_API` · `REPORTING_API` (YT-14) |
| `notification_channel` | `EMAIL` · `IN_APP` · `WHATSAPP` (Tier 2+) · `SLACK` (Tier 2+) |
| `notification_status` | `QUEUED` · `SENT` · `FAILED` · `READ` |
| `comment_triage_class` (S13) | `QUESTION` · `SPAM` · `ABUSE` · `LEAD` · `UNCLASSIFIED` (classifier could not decide; always routed to a human — added so no comment is silently dropped) |
| `reply_state` (S13) | `NONE` · `DRAFTED` · `APPROVED` · `REJECTED` · `POSTED` (only after a human approval; never auto-posted) |
| `worker_status` | `STARTING` · `IDLE` · `BUSY` · `DRAINING` · `STOPPED` · `LOST` |
| `idempotency_status` | `IN_PROGRESS` · `COMPLETED` · `FAILED` |
| `budget_scope_kind` | `ORG` · `WORKSPACE` · `CHANNEL` · `PRODUCTION_TYPE` · `PROVIDER` (CCR-035: owner-declared provider cap, `scope_key` = provider config key; a start gate for that provider's calls) |
| `budget_period` | `DAY` · `MONTH` · `PER_VIDEO` · `PER_JOB` · `PILOT_TOTAL` (CCR-035: cumulative, never resets) |
| `budget_state` | `ACTIVE` · `SUSPENDED_EXCEEDED` · `DISABLED` |
| `reservation_status` | `HELD` · `CONSUMED` · `RELEASED` |
| `cost_figure_kind` | `ESTIMATE` · `VERIFIED` |
| `billing_mode` (LLM calls, §3.3 cost levers) | `STANDARD` · `BATCH` · `CACHED_PROMPT` |
| `rule_pack_status` | `DRAFT` · `ACTIVE` · `RETIRED` |
| `production_type_status` | uses `feature_status` |
| `api_key_status` (Tier 3) | `ACTIVE` · `REVOKED` · `EXPIRED` |
| `webhook_delivery_status` (Tier 3) | `PENDING` · `DELIVERED` · `RETRYING` · `FAILED_FINAL` |
| `subscription_status` (Tier 2) | `ACTIVE` · `PAST_DUE` · `SUSPENDED` · `CANCELLED` |
| `invoice_status` (Tier 2) | `DRAFT` · `ISSUED` · `PAID` · `OVERDUE` · `VOID` |
| `plan_status` (Tier 2) | `PROPOSAL` · `ACTIVE` · `RETIRED` |
| `usage_meter` (Tier 2) | `VIDEOS` · `VIDEO_MINUTES` · `RENDER_MINUTES` · `AI_SPEND` · `STORAGE_BYTES` |
| `entity_kind` (transition rows) | `JOB` · `TASK` |

### 6.46 `figure_label`
`ESTIMATE` · `MEASURED` · `PROJECTION` · `ACTUAL` · `PROPOSAL` · `VERIFIED`.

### 6.47 `tier` (§1C.15)
| Value | Meaning |
|---|---|
| `TIER_0` | Internal: platform owner only; multi-tenant schema, RBAC basics, audit log, `org_id` everywhere (MVP). |
| `TIER_1` | First managed-service client: OAuth verification + YouTube audit passed, client portal approvals, licence ledger, own server. |
| `TIER_2` | Self-serve clients: onboarding, white-label, billing, quotas. |
| `TIER_3` | Enterprise: SSO/SCIM, API/webhooks, dedicated deployment, pen-test, formal SLA. |

### 6.48 `production_type_key` (§3.4; records in 24)
`CHANNEL_LONG_FORM` · `SHORTS` · `AD_SPOT` · `EXPLAINER_CORPORATE_TRAINING` · `ECOMMERCE_PRODUCT` · `DUBBING_LOCALISATION`.

### 6.49 Ad spot durations
`6`, `15`, `30`, `60` seconds (stored as `duration_target_ms` 6000/15000/30000/60000).

### 6.50 `aspect_ratio`
`16:9` · `9:16` · `1:1` · `4:5`.

### 6.51 `refusal_reason` (LLM step refusal / escalation, 27 §4)
`INSUFFICIENT_INPUT` · `RULE_WOULD_BE_BROKEN` · `OUT_OF_SCOPE` · `CONFLICTING_INSTRUCTIONS` · `UNSAFE_CONTENT`.

### 6.52 Contract-local value sets (defined here so no document invents its own)
| Enum | Values | Used in |
|---|---|---|
| `control_command` | `DRAIN` · `CANCEL` · `PAUSE` · `RESUME` | 03 §4.3 |
| `context_ref_purpose` | `KNOWLEDGE` · `MEMORY` · `PRIOR_OUTPUT` · `BRAND_KIT` · `COMPLIANCE_PROFILE` · `RULE_PACK` · `ASSET` · `APPROVAL` · `TEMPLATE` · `CLIENT_INPUT` | 03 §3.2 |
| `output_ref_kind` | `SCRIPT` · `AUDIO` · `VIDEO` · `IMAGE` · `SUBTITLE` · `METADATA` · `REPORT` · `DATA` · `CHECKPOINT_STATE` | 03 §5.2 |
| `payload_ref_schema` | `amw.task_input` · `amw.task_output` · `amw.control` | 03 §4.2 |
| `rule_flag_severity` | same as `rule_severity`: `BLOCKING` · `WARNING` | prompts, `claims.rule_flags` |
| `gate_on_fail_action` | `REVISE` · `STOP` | 24 §3.1 |
| `parent_input` | `NONE` · `PARENT_JOB` · `SOURCE_VIDEO` | 24 §2 |
| `language_mode` | `SINGLE` · `MULTI` | 24 §2 |
| `input_provider` | `OWNER` · `CLIENT` · `SYSTEM` | 24 §2 `required_inputs` |
| `approval_workflow_key` | `owner_one_tap` · `client_two_step` · `owner_sensitive` | 24 §3.4 |
| `data_age_vs_lag` | `OLDER_THAN_LAG` · `WITHIN_LAG` · `UNKNOWN` (`UNKNOWN` is treated as within the lag). Closed set: a chart with no market data (schematic) carries `null`, not a new value (CCR-042) | `agent_06.claim_extraction.input`, `agent_08.asset_sourcing.output` |
| `data_age_basis` (CCR-004) | `MEASURED` (computed from the dataset end date) · `CONSTRAINT` (a requirement the chart path must meet; Agent 08 fails the shot `DATA_WITHIN_LAG` otherwise; re-verified by `qc.visual.chart_data_age` and `s16_comp`) | `agent_06.claim_extraction.input` `chart_data_refs[]` |
| `sebi_registration_status` | `UNREGISTERED` (v1 supports only this; values for registered intermediaries **REQUIRES REVIEW (Phase 1): owner input A6 and 13**) | `agent_06.claim_extraction.input` |
| `citation_input_kind` | `KNOWLEDGE_CHUNK` · `EXTERNAL_REFERENCE` | `agent_06.claim_extraction.input` |
| `eval_case_category` | `ANSWER_KEY` · `HARD_NEGATIVE` · `EDGE` · `REFUSAL` · `POSITIVE` | evals/README.md |
| `ccr_status` | `Proposed` · `Needs owner` · `Approved` · `Rejected` · `Applied` | CONTRACT_CHANGE_REQUESTS.md |
| `cost_unit_kind` | `characters` · `audio_ms` · `images` · `video_ms` · `render_ms` · `quota_units` · `items` · `bytes` | `cost_ledger.unit_kind`, 24 §6 |
| `cost_operation` (CCR-057; closed list of adapter operation names) | `llm.completion` · `llm.count_tokens` · `llm.batch` (3C) · `tts.synthesize` · `tts.list_voices` · `stock.search` · `stock.license` · `music.search` · `music.license` · `image.generate` · `video.generate` · `web.fetch` · `render.ffmpeg` · `delivery.file` · `storage.bytes` · `youtube.quota`. A `cost_ledger` row is written for every operation that costs money or consumes quota; free operations write none | `cost_ledger.operation`, adapter fakes |
| `error_disposition` (CCR-057) | `RETRY` · `SUSPEND` · `FAIL` · `NO_ATTEMPT` (one spelling everywhere, CCR-062) | 07 §2 |
| `retry_policy` (CCR-057) | `temporary` · `rate_limited` · `db` · `resource` · `agent` · `agent_parse` · `infra` · `publish_resume` | 07 §3.3, config `retry.<policy>.*` |
| `queue_name` | `light` · `ai` · `render` · `publish` | `task_queue.queue_name` |
| `transition_id` | `T01`–`T20` (task), `J01`–`J12` (job) | 03 §11.3, §11.5 |
| `gate_verdict` (CCR-001) | `PASSED` · `FAILED` (optional payload echo of a gate stage; the orchestrator decides from `validation_results`, 03 §5.3) | gate stage payloads (`agent_07.audio_master`, `agent_10.technical_qc`, …) |
| `llm_model_tier` (CCR-019) | `SMALL` · `MID` · `TOP` (ADR-007 §2.3; resolved to provider + model by config `llm.tiers.<tier>.*`) | `llm.<task_type>[.<step>].model_tier` |
| `video_kind` (CCR-006) | `GENERAL` · `METHOD_TOPIC` (a topic that uses the owner's released method material; FIN-R12) | `amw.owner_topic`, `agent_04.research_pack.input`, `agent_05.script_draft.input` |
| `owner_reference_kind` (CCR-006) | `EXTERNAL_URL` · `KNOWLEDGE_SOURCE` | `amw.owner_topic` |
| `factcheck_verify_mode` (CCR-042) | `EVIDENCE` · `CHART_FACTS` · `SKIPPED` · `CODE_ONLY` | `agent_06.claim_verification.output` |
| `factcheck_assessment` | `SUPPORTED` · `PARTIALLY_SUPPORTED` · `CONTRADICTED` · `NOT_FOUND` · `UNCLEAR` | `agent_06.claim_verification.*` |
| `factcheck_certainty` | `HIGH` · `MEDIUM` · `LOW` | `agent_06.claim_verification.*` |
| `verification_reason_code` | `NO_EVIDENCE_CANDIDATES` · `SKIPPED_BY_POLICY` · `QUOTE_NOT_ATTRIBUTABLE` · `NO_CHART_FACTS` · `CHART_PENDING` (chart claim deferred to `s06_chart`, CCR-004) · `RESTRICTED_NOT_RELEASED` · `CITATION_UNRESOLVABLE` · `LOW_RELIABILITY_ONLY` · `NUMBER_NOT_IN_EVIDENCE` · `EVIDENCE_CONFLICT` · `NO_SCRIPT_CITATION` · `OVERREACH` · `CONTRADICTED_BY_EVIDENCE` · `NOT_FOUND_IN_EVIDENCE` · `MODEL_UNCERTAIN` · `MODEL_REFUSED` · `INJECTED_EVIDENCE_DISCARDED` · `SPAN_INVALID` · `CLAIM_CONFLICT` | `claims.status_reasons`, `agent_06.claim_verification.output` |
| `discrepancy_kind` | `NUMBER` · `UNIT` · `ENTITY` · `DIRECTION` · `TIME_SCOPE` · `NEGATION` · `QUANTIFIER` · `CAUSATION` · `SCOPE` · `DEFINITION` | `agent_06.claim_verification.*` |
| `claim_conflict_kind` | `NUMBER` · `DIRECTION` · `DEFINITION` · `ENTITY` · `TIME_SCOPE` · `NEGATION` | `agent_06.claim_verification.output` |
| `revision_action` | `ADD_CITATION` · `CORRECT_CLAIM` · `PROVIDE_EVIDENCE` · `RESOLVE_CONFLICT` · `REMOVE_OR_REWORD` | `agent_06.claim_verification.output`, 24 §3.3 revision mapping |
| `revision_feedback_source` (CCR-009) | `CLAIM_EXTRACTION` · `CLAIM_VERIFICATION` · `UNIQUENESS` · `COMPLIANCE` · `QUALITY_SCORE` · `APPROVER` | `agent_05.script_draft.input` `revision.feedback[]` |
| `evidence_source_kind` | `KNOWLEDGE_CHUNK` · `EXTERNAL_REFERENCE` · `CHART_FACT` | `agent_06.claim_verification.*` |
| `passage_flag` | `INJECTION_SUSPECTED` · `UNREADABLE` | `agent_06.claim_verification.*` |
| `licence_destination` | `MONETIZED_YOUTUBE` · `NON_MONETIZED` (derived from `jobs.monetized_destination`, CCR-028) | `agent_08.asset_sourcing.*` |
| `visual_skip_reason` | `NOT_APPLICABLE_INTENT` · `NO_CANDIDATE` · `NO_ACCEPTABLE_FIT` · `LICENCE_ABSENT` · `LICENCE_NOT_USABLE` · `TIER_DISABLED` · `PROHIBITED_DEPICTION` · `BUDGET` · `REUSE_LIMIT` · `NO_TEMPLATE_CONTENT` · `TIER_SHARE_LIMIT` · `PROVIDER_REFUSED` · `CANDIDATE_INVALID` | `agent_08.asset_sourcing.output` `skips[]`, `qc_results.message` |
| `shot_unresolved_reason` | `NO_DATASET` · `NO_CHART_CASE` · `METHOD_NOT_RELEASED` · `DATA_WITHIN_LAG` · `NO_TEMPLATE_CONTENT` · `NO_SOURCE_IN_ANY_TIER` · `UNSAFE_CONTENT` (a refused depiction with no safe tier-C fallback) | `agent_08.asset_sourcing.output`, `s08_assets` routing (24 §7.1a) |
| `shot_sourcing_status` | `SOURCED` · `REUSED` · `UNRESOLVED` | `agent_08.asset_sourcing.output` |
| `sourcing_warning` | `FOOTAGE_INTENT_DOWNGRADED_TO_GRAPHIC` · `LICENCE_EXPIRING` · `NO_INDEMNIFICATION` · `NEAR_DUPLICATE_OF_OWNED_ASSET` · `CROPPED_TO_ASPECT` · `RELEASE_RECORD_ABSENT` · `REUSED_RECENTLY_USED_ASSET` | `agent_08.asset_sourcing.output` |
| `chart_data_kind` | `REAL_HISTORICAL` · `SCHEMATIC` | `agent_05.script_draft.output` `chart_requests[]`, `agent_08.asset_sourcing.output` |
| `shot_intent_kind` | `FOOTAGE` · `CHART` · `DIAGRAM` · `TEXT_CARD` | `agent_09.shot_plan.output`, `agent_08.asset_sourcing.output` |
| `reuse_kind` | `EXACT` · `NEAR_DUPLICATE` | `agent_08.asset_sourcing.output` |
| `crop_mode` | `NONE` · `CENTER_CROP` · `ANCHOR_CROP` | `agent_08.asset_sourcing.output`, `agent_10.render.input` |
| `subject_anchor` | `CENTER` · `UPPER_THIRD` · `LOWER_THIRD` · `LEFT` · `RIGHT` | `agent_09.shot_plan.output` `vertical`, `agent_08.asset_sourcing.output` |
| `compliance_judge_finding` (CCR-069) | `VIOLATION` · `NO_VIOLATION` · `UNCERTAIN` | `agent_16.compliance_gate.policy.output` |
| `paraphrase_decision` (CCR-069) | `OWN_WORDS` · `CLOSE_PARAPHRASE` · `UNCERTAIN` | `agent_16.compliance_gate.paraphrase.output` |
| `text_item_surface` (CCR-069) | `SCRIPT_SEGMENT` · `ON_SCREEN_TEXT` · `THUMBNAIL_TEXT` · `TITLE` · `DESCRIPTION` | `agent_16.compliance_gate.policy.input`, metric label `surface` |
| `cross_video_status` (CCR-069) | `COMPARED` · `SKIPPED` · `NOT_BUILT` | `svc_s02.uniqueness_check.output` |
| `authorised_action` (CCR-069) | `DELIVERY` (3A) · `UPLOAD_PRIVATE` · `PUBLISH` (3C) | `agent_16.publication_authorisation.*` |
| `frame_finding` (CCR-069) | `WATERMARK_PRESENT` · `PRESENTER_PRESENT` · `NONE_FOUND` · `UNCERTAIN` · `NOT_EVALUATED` | `agent_16.compliance_gate.frames.output`, gate output `frame_checks[]` |
| `score_scaling_mode` (CCR-085) | `NONE` · `PRO_RATA` | config `quality.machine_scaling` (provisional default `NONE`, owner Q-O2) |
| `score_gate_mode` (CCR-085) | `REPORT_ONLY` · `BLOCKING` | config `quality.score_gate_mode` (provisional default `REPORT_ONLY` until the 3B judge calibration; `BLOCKING` with `NONE` is refused at startup) |
| `source_path_class` (CCR-076) | `data_pack` (the owner-approved course data pack, Q22; any other class is rejected) | `assets.attributes.source_path_class` (04 §5.15) |

Rule (CCR-042): a value set read by more than one agent, by the orchestrator, by the DB or by the owner's report is listed here. A set used only inside one agent's own step payloads, and read by no other component, may stay payload-local, but it must be a closed `enum` in that payload schema and must not reuse a name listed here with other values.
