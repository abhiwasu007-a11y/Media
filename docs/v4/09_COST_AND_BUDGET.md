# 09 — Cost and Budget (S4 Financial Controller + Budget Guard, owner Agent 15)

| Field | Value |
|---|---|
| Directive sections | §2 S4, §3.3 (AI providers, cost levers), §1A.11, §1B.7 (metering), rule 8 |
| Binding contracts | `GLOSSARY_AND_IDS.md` (enums), `03_COMMUNICATION_STANDARD.md` (state machine T03/T05/T09/T15, `resource_budget`), `04_DATABASE_ARCHITECTURE.md` §5.14, `07_FAILURE_MANAGEMENT.md` (`RESOURCE.BUDGET_EXHAUSTED`), `24_PRODUCTION_TYPES.md` §3.2/§6/§7.1, `27_ENGINEERING_STANDARDS.md` (config keys, §9 skeleton) |
| Owner decisions | D1 (spend controls, secrets, render window), D2 |
| Documentation status | Draft for review (software status: Planned) |
| Items marked "(pending CCR)" | depend on the requests in §14; written against the proposed name |

MVP scope tags: **3A** = needed for the production line; **3B** = needed for the golden samples; **3C** = everything else. Enterprise tiers 0-3 as in directive §1C.

## 1. Purpose and non-goals

S4 answers four questions: what will this work cost (ESTIMATE), what did it cost (ESTIMATE then VERIFIED), may it start or continue (budget guard), and what is the cost per finished video and per stage (report).

Non-goals: S4 never raises a limit, never buys anything, never deletes work, and never decides pricing for clients (S10, Tier 2, 3C). Rule 8: no spend without the owner; D1: paid calls start only after the owner has set spending limits at each provider.

| Capability | MVP | Tier |
|---|---|---|
| Cost ledger writes per paid call (ESTIMATE) | 3A | 0 |
| Per-video and pilot budget, stop on breach | 3A | 0 |
| Provider-limit acknowledgement gate (§8) | 3A | 0 |
| Cost-per-stage report in the delivery bundle (§12) | 3A | 0 |
| ESTIMATE-to-VERIFIED reconciliation (§6) | 3B | 0 |
| Daily and monthly budgets, soft-limit warnings | 3B | 0 |
| Per-channel and per-production-type budgets, critical/non-critical classes | 3C | 0-1 |
| Usage metering for client plans (S10) | 3C | 2 |

## 2. Where S4 runs (design)

S4 is a library plus a scheduled system job inside the orchestrator process model, not an LLM agent. It makes no model call; every decision is deterministic code over `budgets`, `budget_reservations` and `cost_ledger`. There are three enforcement points (defence in depth; any one of them can stop spend):

| Point | Where | What it checks | On failure |
|---|---|---|---|
| E1 Admission | state machine T03 (VALIDATING to QUEUED) | reserves `resource_budget.max_cost_micros` against every applicable budget | T05: `CHECKPOINTED`, `wait_reason = AWAITING_BUDGET`, event `task.suspended` |
| E2 Per call | provider adapter, before each paid call | remaining task budget (`max_cost_micros`, `max_tokens_in/out`, `max_llm_calls`) and budget state | `RESOURCE.BUDGET_EXHAUSTED` (07): SUSPEND, no attempt consumed |
| E3 Post call | ledger write after each paid call | actual ESTIMATE pushes a budget over its limit | budget `state = SUSPENDED_EXCEEDED`; no new non-critical paid task admitted (E1) |

Suspensions are waits, not retries (07 §3.4): they consume no attempt and hold no worker (03 §11.4).

## 3. Budget model

Uses only the `budgets` / `budget_reservations` columns and enums of 04 §5.14 and GLOSSARY §2.

### 3.1 Budget kinds

| Budget | Row (`scope_kind` / `period`) | Meaning | MVP |
|---|---|---|---|
| Per video | `ORG` (or `PRODUCTION_TYPE`) / `PER_VIDEO` | cap on summed ledger cost of one job | 3A |
| Per job | `ORG` / `PER_JOB` | cap on a non-video job (e.g. a system job) | 3C |
| Pilot total | `ORG` / `PILOT_TOTAL` (CCR-035, applied) | non-resetting cap across the whole pilot (D1) | 3A |
| Daily | `ORG` or `CHANNEL` / `DAY` | cap per calendar day in the tenant's time zone (GLOSSARY units/time zones) | 3B |
| Monthly | `ORG` or `CHANNEL` / `MONTH` | cap per month | 3B |
| Per production type | `PRODUCTION_TYPE` + `scope_key` / any period | cap for one type, e.g. AI B-roll heavy types | 3C |
| Provider limit | `PROVIDER` (CCR-035, applied) / `PILOT_TOTAL` or `MONTH` | owner's declared cap set at the provider (§8) | 3A |

`limit_minor` is set only by the owner or tenant (04: "never defaulted silently"). All values are **REQUIRES REVIEW (Phase 1): owner sets per-video, pilot, daily and monthly limits and the currency** (rule 8; open owner input A6 "budget ceiling"). The system ships with no non-zero default: a budget row with no owner-set limit means "no paid call may start".

### 3.2 States

`budget_state`: `ACTIVE` -> `SUSPENDED_EXCEEDED` (E3 or E1 finds `committed` (§3.3) >= limit; never for `PER_VIDEO` / `PER_JOB`, CCR-107) -> `ACTIVE` only by (a) the period rolling over (DAY/MONTH), or (b) an owner/Finance action that raises `limit_minor` or releases it (audited, permission-gated, never automatic). `DISABLED` = budget not enforced; permitted only for non-paid system tasks and only by the platform owner; a paid task with no `ACTIVE` applicable budget is refused at E1 (fail closed).

**Per-job caps (CCR-107).** `PER_VIDEO` and `PER_JOB` budgets have no job-level state: their row stays `ACTIVE` and the cap is evaluated per job (`committed` = that job's ledger rows and holds, §3.3). A job that reaches its cap is stopped alone: E1 refuses the job's new paid tasks (T05, `AWAITING_BUDGET`), E2 refuses the job's calls whose estimate would take the job's ledger spend above the cap, E3 writes the audit event `budget.job_cap_reached` (never `budget.suspended`). Other jobs are unaffected. Release is by raising `limit_minor` (audited); resume through T15 re-runs E1 (B6).

`non_critical_suspend` (default true): when true, an exceeded budget suspends **new** non-critical paid jobs. In 3A every paid task is treated as non-critical, so the per-video and pilot limits are hard stops. A critical class is **(pending CCR)** (§14, request 3) and is 3C.

### 3.3 Consumed amount (single definition)

```
committed(budget) = Σ cost_ledger.amount_micros in scope and period
                    counting, per call, the VERIFIED row if one exists, else the ESTIMATE row
                  + Σ over HELD reservations r of the budget of
                      max(0, r.amount_micros − Σ cost_ledger.amount_micros of r.task_id
                                               in the same scope and period, same row selection)
remaining(budget) = limit_minor (converted to micros) − committed(budget)
```
A VERIFIED row replaces its ESTIMATE in the sum through `estimate_entry_id`; both rows stay in the ledger (§6). A HELD reservation counts only its **unspent** part, so a running task's spend is never counted twice (CCR-106; a task that has spent 6 of a hold of 10 commits 10, not 16). For a `PER_VIDEO` / `PER_JOB` budget the sums are restricted to the job (CCR-107).

**Currency (CCR-133, CCR-111).** `limit_minor` is converted to micros with the ISO 4217 minor-unit exponent of the budget currency (config `finance.currency_minor_exponent`, CCR-133: map currency → exponent, no code default; a currency with no entry is refused, `PERMANENT.CONFIG_INVALID`). A ledger row in currency X counts against a budget in currency Y only when `"X/Y"` is listed in config `finance.fx_pairs` (list of strings `"<row currency>/<budget currency>"`, e.g. `"USD/INR"`; default empty = no conversion), as `ceil(amount_micros × fx_rate)` with `fx_rate` = units of Y per unit of X (04 §5.14). A pair not listed, or a row without `fx_rate`, refuses the evaluation with `PERMANENT.CONFIG_INVALID`; a rate is never guessed. Values: **REQUIRES REVIEW (owner / Finance)** (Q-O12, Q-O13).

### 3.4 Reservation lifecycle (03 T03)

| Step | Event | `reservation_status` |
|---|---|---|
| 1 | T03 admission reserves `resource_budget.max_cost_micros` on every applicable budget, in one transaction | `HELD` |
| 2 | task completes; actual ledger sum recorded | `CONSUMED` (amount may be below the hold; the difference returns to remaining) |
| 3 | task fails permanently, is cancelled or dead-lettered | `RELEASED` (`released_at` set); cost already incurred stays in the ledger |
| 4 | retry of the same task | reuses the HELD reservation; retries never reserve twice |

If any applicable budget cannot cover the hold, no reservation is made on any of them (all-or-nothing), the task goes to T05. A task's `max_cost_micros` is set per task type (07 §9; 27 §3 key `llm.<task_type>.cost_budget_micros`); the values are **REQUIRES REVIEW (Phase 1): set from measured cost in the skeleton, then confirmed by the owner**.

## 4. Behaviour on breach

| Rule | Behaviour |
|---|---|
| B1 | (For a per-job cap: only that job's, CCR-107.) New non-critical paid tasks are not admitted; they wait in `CHECKPOINTED` / `AWAITING_BUDGET` with durable progress. |
| B2 | A task already running continues only to its next safe point inside its own HELD reservation; E2 stops any call that would exceed it. Its partial output is checkpointed. |
| B3 | **Completed work is never deleted**: artifacts, ledger rows, checkpoints and approvals stay. Suspension changes scheduling only. |
| B4 | Non-paid work (deterministic QC, assembly of already-paid assets, delivery of an already-finished bundle) is not blocked by a paid-budget breach. |
| B5 | Breach raises an L3 notice to the tenant's Finance role (07 §6) through S7 (01); wording and recipient list are in the S7 doc. For the owner's own tenant, the owner. |
| B6 | Resume only through T15 after a human action or a period roll-over; resume re-runs E1. No automatic spend increase (07: `RESOURCE.BUDGET_EXHAUSTED`, rule 8). |
| B7 | A soft limit (`soft_limit_ratio`) raises a warning notice only; it never blocks. |
| B8 | The 3A acceptance test is 27 §9 test 4: a budget breach stops further paid calls and the job shows `AWAITING_BUDGET`. |

## 5. Per-call cost capture

Each paid call writes one `cost_ledger` row with `figure_kind = ESTIMATE` at response time (columns exactly as 04 §5.14; none added here).

| Ledger column | Filled from |
|---|---|
| `job_id`, `task_id`, `attempt_id`, `channel_id`, `agent_id` | the task envelope |
| `provider`, `model` | adapter and config at call time (no hard-coded model; rule 5) |
| `operation` | e.g. `llm.completion`, `tts.synthesize`, `stock.license`, `youtube.quota` (04) |
| `billing_mode` | `STANDARD`, `BATCH` or `CACHED_PROMPT` (GLOSSARY) |
| `tokens_in`, `tokens_out`, `tokens_cached_in` | provider response usage block, not a local count |
| `units`, `unit_kind` | non-token usage: `characters`, `audio_ms`, `images`, `video_ms`, `render_ms`, `quota_units`, `items`, `bytes` (GLOSSARY `cost_unit_kind`) |
| `amount_micros`, `currency` | usage x unit price from the pricing config |
| `price_ref` | version of the pricing config used (so an ESTIMATE can be recomputed) |
| `idempotency_key` | per call; `UNIQUE (org_id, idempotency_key, figure_kind, occurred_at)` makes a replayed write a no-op |

Rules:
1. The ledger write and the task result are committed in the same transaction as the artifact record, or the write is retried by the idempotency key; a paid call must never exist without a ledger row (the adapter writes a `PENDING` intent first is **not** used: a lost row is repaired by reconciliation, §6.3).
2. A failed call that the provider still billed is recorded; a failed call the provider did not bill is not.
3. Retries produce one row each (each is a real call). Caching and Batch are recorded in `billing_mode` and the cached-token column, so levers can be measured (§10).
4. Prices are pricing configuration, not code: a table keyed by provider, model/operation, unit, `price_ref` and effective date, with a source ID. **The config schema is a 3A implementation detail owned by the adapter layer (ADR-007, REQUIRES REVIEW); S4 only reads it.**
5. Non-money capacity (`quota_units`, YouTube) is recorded with `amount_micros = 0`; it never counts against a money budget (24 §6, YT-02). It is used in 3C only (no upload in 3A).

## 6. Estimate vs verified

| Aspect | ESTIMATE | VERIFIED |
|---|---|---|
| Source | tokens/units from the provider response x pricing config | provider usage export or invoice line |
| Written | at call time | by reconciliation, after the provider publishes usage |
| `figure_kind` | `ESTIMATE` | `VERIFIED` |
| Link | — | `estimate_entry_id` -> the ESTIMATE it confirms; `verification_ref` = export/invoice reference |
| Mutability | append-only; never overwritten | append-only; never overwritten |

6.1 Never mix the two in one number without saying so: every figure shown in S8, in reports and in the delivery bundle carries its `figure_kind`. A job total is "ESTIMATE" until every row has a VERIFIED partner; otherwise it is labelled "partly verified (n of m rows)".
6.2 Variance = VERIFIED − ESTIMATE per provider and per month. If |variance| exceeds a threshold (config `finance.variance_alert_ratio`, **REQUIRES REVIEW (Phase 1): owner/finance sets it**), the pricing config is flagged for review; past ESTIMATE rows are not edited.
6.3 A VERIFIED amount with no matching ESTIMATE (missed call) is written without `estimate_entry_id` and flagged as a leak to Finance.
6.4 Which providers expose a usage export or API usable for reconciliation is **REQUIRES REVIEW (Phase 1): not yet researched for Anthropic, ElevenLabs, stock library**; until then 3A stays ESTIMATE-only and the bundle says so. VERIFIED reconciliation is therefore 3B.
6.5 During 3A the owner's provider dashboard remains the authority; S4 never presents an ESTIMATE as an invoice.

## 7. Unit prices

Prices live in the pricing config (§5.4). The table lists the values verified in the research log; nothing is added from memory. Currency of vendor prices is USD as published; infrastructure is INR (INF-01). A conversion to the budget currency uses a recorded `fx_rate` / `fx_source` (**REQUIRES REVIEW (Phase 1): FX source and refresh rule**).

| Item | Verified value | ID |
|---|---|---|
| `claude-fable-5-2` | $8 in / $40 out per MTok | PR-01 |
| `claude-opus-5-5` | $4 / $20 per MTok | PR-01 |
| `claude-sonnet-5-5` | $2 / $10 per MTok | PR-01 |
| `claude-haiku-5-5` | from $0.10 in / $0.50 out per MTok, tiered by prompt length; exact tiers not extracted | PR-01 (**REQUIRES REVIEW (Phase 1): exact Haiku tiers**) |
| Batch | 50 percent discount on input and output tokens | PR-02 |
| Cache write | 1.25x (5-min TTL) or 2x (1-hour) of input price | PR-02 |
| Cache read | 0.1x generally; 0.05x on Opus 5.5 and Sonnet 5.5; 0.025x on Fable 5.2 | PR-02 |
| Multipliers | stack with Batch | PR-02 |
| API vs subscription | API is billed separately from a Claude subscription | PR-03 |
| ElevenLabs TTS (Marathi-capable models: v4, v3) | $0.08 per 1K characters (v4, v3, Multilingual v2); $0.04 per 1K for v4 Turbo / v3 Conversational / Flash; Marathi is supported on v4, v4 Turbo, v3, v3 Conversational, not on Multilingual v2 or Flash v2.5 | PR-04 |
| Stock footage, one channel | $21 to $30 per month on annual billing (Essentials / Unlimited); Business licence by quote | PR-06 |
| Gemini TTS (candidate) | $0.50 per 1M text tokens in, $9 per 1M audio tokens out to 2026-12-31; $1 / $18 from 2027-01-01 | PR-07 (Preview; Marathi support not established) |
| Shared VPS | KVM 2 incl. ₹779/month promotional (₹1,199 renewal); separate render worker option KVM 1 ₹599 | INF-01 |
| Music subscription | REQUIRES REVIEW (Phase 1): ADR-009 | PR-07 (plan price not in HTML) |
| AI video B-roll, per second | REQUIRES REVIEW (Phase 1): ADR-009 (credit-to-seconds mapping not read) | PR-07 |
| Storage, render time | render = MEASURED worker time; storage REQUIRES REVIEW (Phase 1) | 24 §6 |

Derived per-MTok figures for planning (arithmetic on the rows above, not new facts): Sonnet 5.5 Batch $1 in / $5 out; Sonnet 5.5 cache read $0.10 in; Sonnet 5.5 cache write (5-min) $2.50 in. Whether the cache and Batch multipliers apply to a given model beyond those listed is read from the pricing config at build time, not assumed here.

## 8. Provider spending limits (D1) and the start gate

D1: paid API calls start only after the owner has set spending limits at each provider. S4 cannot see a provider's console limit, so it requires an explicit owner acknowledgement as a precondition (3A):

| Step | Rule |
|---|---|
| 8.1 | For each paid provider adapter enabled in config (LLM, TTS, stock, any AI B-roll), a `budgets` row with `scope_kind = PROVIDER` (CCR-035, applied), `scope_key = <provider>`, `limit_minor` = the cap the owner set at the provider, must exist and be `ACTIVE`. Creating it is the owner's acknowledgement that the provider-side limit is set. |
| 8.2 | Missing or `DISABLED` row: the adapter refuses every paid call with `RESOURCE.BUDGET_EXHAUSTED` before any network request (fail closed). Free local steps are unaffected. |
| 8.3 | Our internal pilot and per-video limits must be at or below the owner's provider limits; S4 warns when a configured limit exceeds the provider row. The owner may set them lower, never silently higher. |
| 8.4 | Keys reach adapters only through the environment's secret mechanism; never in git, logs, ledger rows, reports or shared environment variables (D1, rule 5). Ledger and report contain provider names, not credentials or account identifiers. |
| 8.5 | A Claude subscription is not API access (PR-03); the owner supplies a separately billed API account (input A7, needed at build). Not needed in this documentation phase. |
| 8.6 | No automatic top-up, no card-on-file assumption, no spend above a limit even if the provider would allow it. |
| 8.7 | Eval and live-smoke paid runs have their own caps (27 §5.3 `evals.max_run_cost_micros`, `live_smoke.max_cost_micros`); values are **REQUIRES REVIEW (Phase 1): owner sets caps**, and those runs are charged to the pilot budget unless the owner states otherwise. |

## 9. Cost-per-video formula

From 00b §3.1 (kept identical so the two documents never diverge), with the ledger as the data source:

```
cost_per_video = LLM + TTS + footage + music + ai_broll + infra_share      (+ review time, reported separately)

LLM        = Σ_stages (input_tokens × price_in + output_tokens × price_out) × batch_factor     [PR-01, PR-02]
             (cache reads and writes priced per PR-02 rows; recorded via billing_mode)
TTS        = characters_narrated × takes × price_per_1k_chars / 1000                           [PR-04]
footage    = stock_subscription_per_month / videos_per_month                                    [PR-06]
music      = music_subscription_per_month / videos_per_month                                    [REQUIRES REVIEW]
ai_broll   = seconds_of_ai_video × price_per_second                                            [REQUIRES REVIEW]
infra_share= incremental_server_cost_per_month / videos_per_month                               [INF-01]
```

How each term is obtained:

| Term | Measured (ledger) | Allocated (not a per-call cost) |
|---|---|---|
| LLM, TTS, AI B-roll, per-item stock | SUM of `cost_ledger` rows of the job, by `operation` | — |
| footage / music subscription | — | monthly subscription / videos produced that month; booked as a monthly allocation row when the month closes (ESTIMATE), `operation = 'stock.license'` for the stock part; allocation row design for music is part of the CCR review if the ledger needs `unit_kind` for it (REQUIRES REVIEW (Phase 1)) |
| infra_share | `render_ms` rows (MEASURED) | VPS monthly cost / videos; INR; ₹0 incremental if headroom allows on the existing KVM 2 (00b §3.2, INF-01) |
| human review | minutes, reported separately; ESTIMATE until the pilot | never added into money totals |

Quantities that are not known and must come from the skeleton and pilot (00b §3.3): tokens per stage per video, characters and takes per video, videos per month and length, music choice, AI B-roll seconds, review minutes. All **REQUIRES REVIEW (Phase 1)**. The only computable line today is TTS for a 10-minute Marathi narration at about $0.64 to $0.80 per take (ESTIMATE; PR-04, character count unmeasured). **No total per-video cost is stated in this document; it is produced by the skeleton measurement (§11) and the report (§12).**

## 10. Cost levers

### 10.1 Model routing (3A design, 3B tuned)

Rule (directive §3.3): each stage uses the cheapest tier that passes its quality gate; selection is config (`llm.<task_type>.model_tier`, 27 §3), never code. The starting assignment below is a **design hypothesis to be confirmed by the eval gate (27 §5)**, not a measured result. Tier names are descriptive; model IDs come from config and PR-01.

| Task type (24 §3.2) | Starting tier hypothesis | Basis |
|---|---|---|
| `agent_06.claim_extraction`, QA and classification checks | small (Haiku class) | PR-01 states Haiku for classification/SEO/QA checks |
| `agent_04.research_pack`, `agent_09.shot_plan`, `agent_08.asset_sourcing` (AI parts) | mid (Sonnet class) | PR-01: Sonnet for most writing |
| `agent_05.script_draft` (Marathi) | mid, escalate to top only if the eval fails | quality measured; Marathi quality unproven (REQUIRES REVIEW (Phase 1): eval) |
| `agent_06.claim_verification`, `agent_16.compliance_gate`, `agent_16.quality_score` | mid; top only where measured quality needs it; deterministic checks first (24 §3.3) | gates must not be weakened for cost |
| `agent_11.thumbnail_variants` | REQUIRES REVIEW (Phase 1): image-model choice (ADR-009) | |
| `agent_07.voice_synthesis` | TTS model that supports Marathi (v4 or v3 class, PR-04) | Marathi is not on Multilingual v2 or Flash |

A tier change is a config change that must pass the eval gate; it is never made at runtime by S4 to hide a breach. S4 may only report cost and propose.

### 10.2 Prompt caching (PR-02)

Stable prefixes (system prompt, rule packs, channel context) are marked cacheable (`llm.<task_type>.cache_system_prompt`, 27). Cache write costs more than a plain input token (PR-02), so caching pays only when a prefix is reused enough within its TTL. Break-even reuse count: **REQUIRES REVIEW (Phase 1): compute from measured prefix sizes in the skeleton**. S4 reports `tokens_cached_in` per stage so the lever is judged on data. 3A: enabled per task type only where the measurement shows a gain.

### 10.3 Batch (PR-02)

Non-urgent, overnight LLM work (`llm.<task_type>.batch_eligible`) is billed at 50 percent of standard, stacking with caching (PR-02). Eligible candidates: bulk or post-hoc work (3C analytics, evals, translation). Interactive 3A stages that the owner waits on are not batch candidates. Batch latency and limits: **REQUIRES REVIEW (Phase 1): not in the research log**. 3A: not used unless measured useful; 3C: scheduled jobs.

### 10.4 Other levers (design, 3A)

| Lever | Rule |
|---|---|
| Visual hierarchy (§1A.1) | owner/real, then licensed stock, then code-made graphics before AI B-roll; AI B-roll is per-video budgeted (§1A.11) |
| No wasted regeneration | revision loops capped (`limits.max_revision_loops` 3, 24); deterministic gates first so paid judges run only on candidates that pass cheap checks |
| Idempotent replay | same idempotency key never pays twice (03 §9; ledger unique key) |
| Reuse | stored artifacts are reused across revisions where the input hash is unchanged |
| Render on own CPU | `render_ms` costs no per-call vendor fee (INF-01); heavy work stays in the night window and never in market hours (D1) |

## 11. Devanagari token measurement

Marathi text tokenizes heavier than English (directive §3.3). No ratio is stated here: none is verified in the research log.

| Step | Specification |
|---|---|
| M1 What is measured | tokens per Devanagari character and tokens per word for each model in use, input and output, compared with an English text of equal meaning, per stage |
| M2 Source of the numbers | `tokens_in`, `tokens_out`, `tokens_cached_in` from the **provider response usage** per call (ledger) plus the character count of the stored input/output artifact; a provider token-count facility, if available and free, may be used offline for pre-estimates (REQUIRES REVIEW (Phase 1): availability and cost) |
| M3 Samples | the skeleton run (27 §9) and the 3B golden samples; sample size and text mix recorded with the result; the label is MEASURED with the sample count, never a general claim |
| M4 Per model | a new model or tokenizer change invalidates the previous ratio; ratios are stored with model ID and date |
| M5 Use | (a) set `max_tokens_in/out` and `max_cost_micros` per task type (§3.4); (b) pre-admission estimate of E1 reservations; (c) the cost-per-video formula (§9) |
| M6 Until measured | estimates use a configurable safety multiplier (config `finance.devanagari_token_factor`); value **REQUIRES REVIEW (Phase 1): set only from M3**; until set, reservations come from the first measured run and the first skeleton run is capped by the owner's pilot limit |
| M7 Output | a measurement table in the 3A pilot report: stage, model, language, chars, tokens in/out, tokens per char, cost, sample count, MEASURED |

## 12. Cost-per-stage report (3A delivery bundle)

D1 requires the cost per stage in each run's downloadable bundle (27 §9: bundle contains MP4, SRT, QC report, cost-per-stage report). The report is generated by S4 from the ledger at bundle time by `agent_13.file_delivery`; the file name and manifest entry belong to that task's payload (Agent 13 blueprint). S4 defines the **content**.

Grouping: ledger rows to `task_id` to `tasks.task_type` to `stage_id` through the production type graph (24 §7.1, e.g. `s05_script` = `agent_05.script_draft`). Rows are not re-labelled; a task type with no stage in the graph is shown under its task type.

### 12.1 Header
| Field | Content |
|---|---|
| Job ID, production type key and version, topic reference | from the job |
| Budget | per-video limit, pilot limit, pilot committed so far, remaining; currency |
| Figure kind summary | "ESTIMATE", or "partly verified (n of m rows)" |
| Prices | `price_ref` versions used and their research IDs |
| Generated at | timestamp; run mode (development or VPS night window) |

### 12.2 Table (numbers first, owner rule D.2)
| Column | Meaning |
|---|---|
| stage_id / task_type | as in 24 §7.1 |
| provider / model | from ledger (config-driven) |
| calls | number of paid calls incl. retries |
| tokens in / out / cached | sums |
| units (unit_kind) | e.g. characters, images, video_ms |
| cost | sum of `amount_micros`, with currency |
| figure kind | ESTIMATE / VERIFIED / mixed |
| share of video total | percent |
| revision loops | iterations of that stage (cost of rework visible) |
| wasted cost | cost of attempts whose output was discarded by a gate |

Rows end with: total, per-term split of §9 (LLM, TTS, footage, music, AI B-roll, infra), human review minutes (separate, not money), and budget status per limit (colour by meaning: within limit green, soft limit exceeded amber, breached red; supporting text, not colour alone).

### 12.3 Rules
1. Totals equal the SQL sum of the ledger rows used; the report states the query scope (`job_id`).
2. Allocated items (subscriptions, infra share) are shown on separate lines marked "allocated", not mixed with per-call rows.
3. Unknown values print as `REQUIRES REVIEW (Phase 1): <need>`, never as zero.
4. Available as JSON and a human-readable view; also exported with the audit export (27 §9 "Records").
5. Contains no keys, account IDs, server addresses or prompt text.
6. S8 shows the same data (cost so far per job, API usage, spend vs budgets) read-only; the cost cockpit layout belongs to the S8 doc.

## 13. Security, tenancy, audit, failures

| Topic | Rule |
|---|---|
| Tenancy | every S4 table carries `org_id`; RLS applies (04 §3). A budget never spans tenants; the platform owner sees a client tenant's spend only as platform-level causes allow (07 §6, rule 10). |
| Permissions | reading cost: Finance, Org Admin, Owner. Changing a `limit_minor`, releasing a suspended budget, or setting `DISABLED`: Owner/Finance only; each is audited with before/after (permission keys **REQUIRES REVIEW (Phase 1): GLOSSARY permission list**). Agents and workers cannot write `budgets`. |
| Append-only | `cost_ledger` has no UPDATE/DELETE (04 rule 7). A wrong ESTIMATE is corrected by a VERIFIED row, or a compensating row with a note; never edited. |
| Failure codes | uses `RESOURCE.BUDGET_EXHAUSTED` (SUSPEND `AWAITING_BUDGET`, no retry, L3 finance). A missing or invalid price or FX config is `CONFIG_INVALID`-class (07) and fails closed: no paid call without a known price. |
| Ledger write failure | the adapter retries by idempotency key; persistent failure fails the task before further paid calls (no unmetered spend). |
| Timezone | DAY/MONTH periods follow the tenant time zone (GLOSSARY); YouTube quota resets by Pacific day and is separate (YT-03). |
| Drain / night window | S4 enforcement runs at any hour; suspension does not depend on the window. Render itself is limited per D1 (never in market hours; VPS night window). |

## 14. Contract change requests (pending)

Needed items that do not exist in Wave A. This document is written against the proposed names, marked "(pending CCR)". Filed by the integrator from the structured return, not edited here.

Decisions (CONTRACT_CHANGE_REQUESTS.md, 2026-11-18): #1 and #2 = **CCR-035, approved and applied** (GLOSSARY §6.45, 04 §5.14). #3 = **CCR-036, rejected for 3A** (in 3A every paid task is treated as non-critical, §4; refile with 3C scheduling).

| # | Needed | Why | Proposed change | Target doc |
|---|---|---|---|---|
| 1 | `budget_period` value `PILOT_TOTAL` | D1 requires a total pilot budget that does not reset; DAY, MONTH, PER_VIDEO, PER_JOB all reset or are per item | add `PILOT_TOTAL`: non-resetting cumulative cap for the scope | GLOSSARY §2 enums; 04 §5.14 |
| 2 | `budget_scope_kind` value `PROVIDER` (`scope_key` = provider) | D1: paid calls only within owner-set provider limits; S4 must hold the owner's declared provider cap as a start gate | add `PROVIDER` | GLOSSARY §2 enums; 04 §5.14 |
| 3 | Task criticality for budget suspension | 04 `non_critical_suspend` and 03 T05 refer to "non-critical" but no field says which task is critical | add optional boolean `critical` (default false) to `resource_budget`, or a per-task-type attribute in 24 | 03 `resource_budget`; 24 |

## 15. Open items (all REQUIRES REVIEW (Phase 1))

| Need | Needed for | Phase |
|---|---|---|
| Owner sets per-video, pilot, daily, monthly limits and currency; provider caps set at each provider | §3, §8 | 3A (before any paid call) |
| Per-task-type `max_cost_micros`, token caps | §3.4 | 3A, from skeleton |
| Tokens per stage, Devanagari ratio, characters and takes per video | §9, §11 | 3A skeleton / 3B |
| Exact Haiku price tiers | §7 | 3A |
| Usage export / invoice source per provider for VERIFIED rows | §6.4 | 3B |
| FX source and rule | §7 | 3A if multi-currency |
| Variance threshold | §6.2 | 3B |
| Music and AI B-roll unit prices | §9 | ADR-009 |
| Batch latency and limits; cache break-even | §10 | 3A measurement / 3C |
| Eval and live-smoke caps | §8.7 | 3A |
| Pricing config schema | §5.4 | ADR-007 |
| Client usage metering and plan limits | S10 | 3C, Tier 2 |
