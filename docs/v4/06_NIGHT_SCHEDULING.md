# 06 — Night Scheduling

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 01 (CEO & Master Orchestrator), service `workers/scheduler` (night scheduler, morning shutdown). Failure-safety of drain and stop: 07 §8. Quota ledger writes: Agent 13 (`amw_quota_reserve/release`, 04 §3.6) |
| Depends on | GLOSSARY_AND_IDS.md (§4 time zones, §6.1 `task_state`, §6.3 `wait_reason`, §6.5 `priority`, §6.6 `resource_class`, §6.42 `quota_bucket`), 03_COMMUNICATION_STANDARD.md (§4.3 control command, §11 T07/T09/T15), 04_DATABASE_ARCHITECTURE.md (§5.4 `task_queue.scheduled_at`, §5.7 `checkpoints`, §5.20 `quota_usage`, `channels.production_window`), 07_FAILURE_MANAGEMENT.md (§3, §8), 3A_SLICE_SPEC.md (§6.4), adr/ADR-001, adr/ADR-012, 09_COST_AND_BUDGET.md (batch, S4), 01_MASTER_ARCHITECTURE.md (container `workers/scheduler`), RESEARCH_LOG.md (YT-01, YT-02, YT-03, YT-05, INF-01, INF-03, INF-04) |
| Directive sections covered | §1 Production window (00:00–07:00 Asia/Kolkata, 06:30 admission stop, 07:00 graceful stop, scheduler/monitor may stay up, YouTube quota reset on the US Pacific day); §1 Isolation mechanism and Queue (context); §1C.2 fair sharing (window part only); §3.1 Agent 01 (night scheduler, morning shutdown); D1 (render never in market hours) |
| Tier | Tier 0 for the shared-server window. Per-tenant window configuration is Tier 1+ (dedicated server); weighted fair sharing across tenants inside a window is Tier 2 |
| MVP scope | **3A:** only the two admission guards of ADR-012 (market-hours guard on every placement; night-window guard on the VPS placement) and cooperative drain/checkpoint already required by 07 §8. **3C:** the `workers/scheduler` service, night report, quota-aware scheduling, per-tenant windows. 3B uses the 3A guards unchanged |

All numeric values below that are not an external fact are **design defaults (ESTIMATE)** held in configuration. External facts are cited by RESEARCH_LOG ID only.

---

## 1. Purpose

The factory shares one VPS with existing applications (INF-01: 2 vCPU / 8 GB class; sizing from measurement only). Heavy work is therefore confined to a fixed daily window, and every task must be able to stop and resume without loss. This document defines:

1. the window and its three moments (open, drain, stop);
2. what admission lets in at each moment, per `resource_class`;
3. how running work is checkpointed and stopped;
4. the night report;
5. what may stay up outside the window (Q7);
6. quota-aware scheduling against the YouTube quota day (YT-03);
7. the market-hours guard required by D1;
8. per-tenant window configuration for a dedicated server.

It does **not** define retry policy, DLQ or breakers (07), the budget guard (09), or the queue implementation (ADR-001).

## 2. Binding inputs (what this document is built on)

| # | Input | Source |
|---|---|---|
| B1 | Window 00:00–07:00 `Asia/Kolkata`; at 06:30 stop admitting heavy jobs, finish or checkpoint running ones, persist state and outputs, write the night report; at 07:00 heavy workers stop gracefully, never killed mid-write | Directive §1; GLOSSARY §4 |
| B2 | Only the scheduler/monitor may stay up, only if its measured footprint is safe | Directive §1; plan Q7 |
| B3 | Q7 provisional default: stoppable by configuration, ESTIMATE footprint, **OFF in daytime until the pilot measures it** | 00_EXECUTION_PLAN Q7 |
| B4 | Daily YouTube quotas reset at midnight Pacific Time; the scheduler tracks quota by PT day, not IST day | YT-03; GLOSSARY §4 `pt_date` |
| B5 | Quota amounts: `videos.insert` 1 unit in its own bucket, 100 calls/day default; 10,000 units/day for other endpoints; `thumbnails.set` 50, `videos.update` 50, `playlistItems.insert` 50, `captions.insert` 400 | YT-01, YT-02, YT-05 |
| B6 | D1: render in the development environment, or in the VPS night window under the §1 limits; **never during market hours**; paid calls only within owner-set limits (S4 stops on breach) | IMPLEMENTATION_PROGRESS D1 |
| B7 | The window is operational configuration; no chart-reading rule may depend on day, date, session or clock time | GLOSSARY §4 (owner rule C.4) |
| B8 | Task state machine: T07 admission guard, T09 (`RUNNING → CHECKPOINTED`), T15 (`CHECKPOINTED → QUEUED`); `wait_reason` values `DRAIN`, `AWAITING_QUOTA`, `AWAITING_BUDGET`, `OPERATOR_PAUSE` | 03 §11; GLOSSARY §6.3 |
| B9 | Control command `DRAIN` with `act_by` = 07:00 minus `drain.grace_ms` | 03 §4.3; 07 §8.2 |
| B10 | Atomic write unit: temporary file, flush, atomic rename to a write-once path; workers never interrupt it; service stop timeout must exceed `limits.max_atomic_write_ms` | 07 §8.1, §8.3 |
| B11 | Admission isolation of the render worker: ADR-012 §3.3 (two independent guards) | ADR-012 |

## 3. Time model

| Rule | Detail |
|---|---|
| Storage | All instants are `timestamptz` UTC (GLOSSARY §4). The window is **evaluated** in the zone configured for the window (default `Asia/Kolkata`); never by adding fixed offsets in code |
| Window zone | Default `Asia/Kolkata` while sharing the server (B1). On a dedicated server the zone and hours come from per-tenant configuration (§12) |
| Quota day | `pt_date = (ts AT TIME ZONE 'America/Los_Angeles')::date` (GLOSSARY §4). Reset = midnight PT (YT-03) |
| Zone data | Offsets between IST and PT change when US Pacific moves between daylight and standard time. Always compute through the IANA zone database; never hard-code 12:30 or 13:30 (YT-03 gives both only as the two results) |

### 3.1 Where the night window sits on the Pacific quota day (derived from YT-03)

YT-03: the reset is 12:30 IST while Pacific is on daylight time (UTC−7) and 13:30 IST on standard time (UTC−8). The offsets are therefore IST = PT + 12:30 (daylight) and IST = PT + 13:30 (standard).

| Moment (IST) | PT clock, Pacific daylight | PT clock, Pacific standard | PT date |
|---|---|---|---|
| 00:00 (window opens) | 11:30 | 10:30 | previous calendar date (IST date − 1) |
| 06:30 (drain) | 18:00 | 17:00 | same |
| 07:00 (stop) | 18:30 | 17:30 | same |
| 12:30 / 13:30 (reset, YT-03) | 00:00 of the next PT date | — | new PT date starts |

**Consequences (derived, not external facts):**

1. The whole night window always falls inside **one** PT day. The scheduler never sees a reset happen while the window is open (B4).
2. The reset happens in the daytime, when only the scheduler/monitor may be up (B2). A task that hit `AWAITING_QUOTA` during the night cannot continue at the reset; it resumes at the **next window opening that follows the reset** (§10.4). This is the central scheduling rule of this document.
3. Each window therefore starts with a fresh quota for the PT day that contains it. The nightly quota budget is one PT day's allowance, shared by all tenants using the same GCP project (YT-01 note, 04 `gcp_projects`).

## 4. Window timeline

All times are in the window zone (§3). `window_end` = 07:00; `drain_start` = `window_end` − `night.drain_lead_ms` (default 1,800,000 ms = 30 minutes; the directive states 06:30).

| Moment | Event | Actor | Effect |
|---|---|---|---|
| T-open (00:00) | Window opens | scheduler | Clears the drain flag. Tasks in `CHECKPOINTED` with `wait_reason = DRAIN` become eligible (T15, §6.4). Tasks held by `scheduled_at` ≤ now become claimable. `AWAITING_QUOTA` tasks are released if a new PT day has started since they were suspended (§10.4) |
| Open → drain | Normal admission | admission (T07) | Claims allowed per §5 |
| T-drain (06:30) | Drain starts | scheduler | Sets the drain flag; admission narrows (§5.2); sends `DRAIN` control to workers running heavy tasks with `act_by` = `window_end` − `drain.grace_ms`; starts the night report (§8) |
| Drain → stop | Drain period | workers | Each worker reaches its next safe point, writes a checkpoint, T09 with `wait_reason = DRAIN`, releases its lease (§6) |
| T-stop (07:00) | Graceful stop | scheduler + service manager | Heavy workers receive the service stop signal; they finish the current atomic unit, checkpoint, release the lease and exit (07 §8.3). Night report is finalised and persisted. Scheduler/monitor continue per §9 |
| After stop | Closed | scheduler (if up) | No claims. Time-based releases are computed for the next opening (§7.2) |

**Invariants**

- I1. A process is never killed mid-write: the stop signal precedes any forced kill, and the service stop timeout exceeds `limits.max_atomic_write_ms` (B10).
- I2. No output appears at a final path unless its atomic rename finished (07 §8.1, §8.4).
- I3. The drain flag is persisted in the database, not held in memory, so a scheduler restart inside the drain period does not re-open admission (§13.2).
- I4. A missed 06:30 (scheduler down) does not extend the window: admission itself compares the current time with `window_end` and refuses a claim that cannot finish (§5.3). The scheduler is the notifier, admission is the guard.

## 5. Admission rules

Admission is the T07 guard "admission allows (window, tenant concurrency, fair share, resource class)" (03 §11). It is evaluated at claim time and again when `scheduled_at` is assigned (04 §5.4: a row is not claimable before its `scheduled_at`). The queue layer holds no other scheduling logic (ADR-001).

### 5.1 Before the drain (window open, flag clear)

| `resource_class` (GLOSSARY §6.6) | Admitted when |
|---|---|
| `LIGHT` | Always (including outside the window only if the scheduler is allowed up, §9) |
| `AI_IO` | Window open; budget guard S4 allows; provider breaker not `OPEN` (07 §4) |
| `HEAVY_CPU` | Window open **and** market-hours guard allows (§11) **and** S4 allows |
| `PUBLISH` | Window open; quota bucket has units (§10); 3C only |

### 5.2 After the drain starts (06:30 ≤ now < 07:00)

07 §8.2 leaves open whether classes other than `HEAVY_CPU` are included. **Decision of this document:**

| `resource_class` | Admission after 06:30 | Reason |
|---|---|---|
| `HEAVY_CPU` | **Stopped.** No new claim of any kind | Directive §1 and 07 §8.2 |
| `AI_IO` | Admitted **only** if `estimated_remaining_ms` ≤ time left to `window_end` − `drain.grace_ms` | The AI worker is stopped at 07:00 (§9); a call that cannot finish would only produce a checkpoint without value. Short calls (classification, SEO, QC judge) still fit |
| `PUBLISH` (3C) | Same rule as `AI_IO`; never starts a resumable upload that cannot finish before `window_end` − `drain.grace_ms` | Resumable upload chunk is an atomic unit (07 §8.1); resume across windows is supported by checkpoint (07), not by starting late |
| `LIGHT` | Admitted if the executing service is up (§9) | DB/logic only |

`estimated_remaining_ms` for a task is the median MEASURED duration of its task type from the pilot (09 / 24 §6 `render_ms` and equivalents) times a configured safety factor `night.admission_safety_factor`. Until measured it is an ESTIMATE held in the registry config; **REQUIRES REVIEW (Phase 1): the per-task-type duration estimates are only available after the 3B golden-sample measurements (3A/3B: unknown, so the 3A guard falls back to the conservative rule "HEAVY_CPU not admitted after drain start; AI_IO admitted only for task types flagged `short` in config")**.

### 5.3 Self-protecting guard (I4)

At every claim, regardless of whether the scheduler is alive, admission computes `time_left = window_end − now` in the window zone and refuses the claim when:

- `resource_class = HEAVY_CPU` and `now ≥ drain_start`; or
- `estimated_remaining_ms > time_left − drain.grace_ms`.

A refused claim leaves the row `READY`; `scheduled_at` is moved to the next window opening that satisfies all guards (§7.2). No task is dropped and no error is raised (a refusal is not a failure; it carries no attempt count).

### 5.4 Priority inside the window

Claim order follows `priority` (GLOSSARY §6.5: `CRITICAL` 0 … `BACKGROUND` 4) then `scheduled_at` (04 §5.4 index). In the final hour before drain, the scheduler may raise `scheduled_at` ordering for tasks whose job has a deadline; it **never** changes `priority` of a task and never invents a priority value. Fair sharing between tenants (per-tenant concurrency, weighted fair queueing, render-minute quotas, §1C.2) is enforced by the same admission guard; it is **Tier 2** and out of 3A/3C-tier-0 scope except the single-tenant concurrency cap.

## 6. Checkpoint and drain procedure

### 6.1 What triggers a checkpoint

| Trigger | Mechanism | State result |
|---|---|---|
| 06:30 drain | `DRAIN` control (03 §4.3), `act_by` = `window_end` − `drain.grace_ms` | T09: `RUNNING → CHECKPOINTED`, `wait_reason = DRAIN` |
| 07:00 stop signal (late or missed `DRAIN`) | Service stop signal (07 §8.3) | Same T09 at the next safe point |
| Quota exhausted mid-task (3C) | Worker returns `SUSPENDED` | T09, `wait_reason = AWAITING_QUOTA` |
| Budget guard S4 | Suspension at any hour (09) | T09, `wait_reason = AWAITING_BUDGET` (independent of the window) |
| Operator pause / emergency stop | S8 / operator tool | T09, `wait_reason = OPERATOR_PAUSE` |

### 6.2 Worker obligations

1. On `DRAIN`, a worker stops starting new sub-steps, completes the current atomic unit, writes a `checkpoints` row (04 §5.7: `step_key`, `state_ref`, `state_sha256`, `completed_effects`, `progress_ratio`, `is_latest`), then performs T09 and releases the lease.
2. `completed_effects` lists the idempotency keys of side effects already completed (paid calls, uploads), so a resume never repeats a paid or irreversible call (03 §9; 09 cost ledger).
3. Resumable work is declared per task type in the registry (24 §3.2). A task type that cannot checkpoint is declared **non-resumable**; it is admitted only when `estimated_remaining_ms` fits the time left (§5.3) and it must complete within the window or restart cleanly at T15.
4. A render (`HEAVY_CPU`) checkpoints at its next safe point (3A: segment or chunk boundary, decided by Agent 10; ADR-012 §3.3). It never abandons a half-written output file; the final file appears only through the atomic rename (I2).

### 6.3 Idempotency and cost on resume

A resumed task reuses prior paid results through `completed_effects` and idempotency keys (03 §9). Resume does not create a second reservation for work already settled; the S4 reservation held at T03 stays valid across `DRAIN` (09). A budget stop during drain is independent of the window (09).

### 6.4 Resume at window open

At T-open the scheduler (or, in 3A, the claim guard) releases every `CHECKPOINTED` task with `wait_reason = DRAIN` by T15 → `QUEUED`, creating a new `READY` queue row carrying `resume_checkpoint_id` (04 §5.4). Release order: `priority`, then original `created_at`, so earlier work finishes first. Release is bounded by the admission rules and the per-tenant concurrency cap; the scheduler never releases more than `night.release_batch_size` rows per tick (ESTIMATE default, config) to avoid a thundering herd on the worker pool.

### 6.5 What the 3A guard does without the scheduler

In 3A there is no `workers/scheduler` (01 container table). The claim guard of ADR-012 §3.3 enforces the market-hours guard and, on the VPS placement, the night-window guard (claim only in the window; no `HEAVY_CPU` after drain start; no task that cannot finish). `DRAIN` control is sent through the operator tool (run by the assistant on the owner's chat instruction, D5) or by the service stop sequence at 07:00. This is enough to satisfy 27 §9 tests 2 and 6 and D1.

## 7. Graceful stop at 07:00 and crash behaviour

### 7.1 Stop sequence

1. T-stop: the service manager sends the stop signal to the heavy workers and to the AI worker (§9 explains why the AI worker also stops).
2. Each worker: stop claiming → finish the current atomic unit → checkpoint → release lease → exit with status 0.
3. The stop timeout of the service must exceed the largest `limits.max_atomic_write_ms` of any worker type (B10). **REQUIRES REVIEW (Phase 1): service stop timeout value; defined in 10_DEPLOYMENT_AND_MIGRATION.md and must be set from the largest measured atomic unit.**
4. If a worker has not exited after the stop timeout, the service manager escalates to a forced kill. By I1/I2 the kill leaves no corrupt final file (temporary files are never renamed). The event is recorded as `INFRASTRUCTURE.WORKER_LOST` / `HOST_RESTART` (07 §8.4) and appears in the night report.

### 7.2 Computing the next window opening

`next_window_open(now, window)` is a pure function of the window configuration and the zone database. It is used for:

- moving `scheduled_at` of refused rows (§5.3);
- shifting `RETRY_WAIT` times that fall outside the window (07 §3.1, §8.5);
- releasing tasks that wait on `AWAITING_QUOTA` (§10.4).

It must handle: window end before start (a window that crosses midnight in its zone), zones with daylight-time changes, and an empty window configuration (no window means the task is never claimable and an operations alert is raised, §14).

### 7.3 Dead processes (07 §8.4)

A process killed outside the stop sequence leaves a lease. The reaper expires the lease and the task resumes from its latest checkpoint at the next window. At most `limits.max_attempts_per_task` (07 §9) apply; a window stop is **not** a failed attempt and is not counted against retries (a drain is a T09 suspension, not a T10 failure).

## 8. Night report

Written by the scheduler at drain start (draft, refreshed) and finalised at 07:00 (3C). In 3A the same content is produced by the operator command `report` for the last run, from `state_transitions`, `task_attempts`, `cost_ledger` and `checkpoints`; no new table is needed for that.

| Section | Content | Source |
|---|---|---|
| Header | Window start and end (UTC and window zone), window source (default / tenant config), placement, report schema version | scheduler config |
| Throughput | Jobs completed, tasks completed, tasks by terminal state; per task type: count, median and p95 duration (MEASURED) | `state_transitions`, `task_attempts` |
| Checkpointed | Each task in `CHECKPOINTED` with `wait_reason` (`DRAIN`, `AWAITING_QUOTA`, `AWAITING_BUDGET`, `AWAITING_APPROVAL`, `OPERATOR_PAUSE`), `progress_ratio`, next eligible window | `tasks`, `checkpoints` |
| Failures | New `FAILED` / `DEAD_LETTER` items with error code and escalation level (07 §7) | `dead_letter`, `state_transitions` |
| Stop quality | Number of graceful stops, number of forced kills, `limits.max_atomic_write_ms` observed maximum; any incomplete temporary file found and cleaned | worker logs, storage |
| Cost | Money cost per stage and per job in the window; remaining per-video and pilot budget; breaches (S4) | `cost_ledger`, 09 |
| Quota (3C) | Units used and reserved per `quota_bucket` for the PT date of the window; units left; next reset instant in the window zone | `quota_usage` |
| Resource | Peak CPU / memory of the factory slice during the window (MEASURED when the monitor exports it) and any throttling (INF-03 MemoryHigh/CPUQuota events) | S5 monitor |
| Guards | Count and reasons of admission refusals: after-drain, market-hours, budget, breaker, quota | admission log |
| Next window | Count of tasks waiting for it, ordered by priority; estimated work in ms | queue |
| Owner actions | Items that need a human: approvals waiting, DLQ items, budget raises, owner calendar inputs | approvals, DLQ |

**Format and delivery.** A JSON document (blob of `output_ref_kind = REPORT`, GLOSSARY enum `output_ref_kind`) plus a short text summary for the operator; shown in the Command Center (3C, S8) and listed by the operator tool (3A). Content is in English (specs and UI strings); a Marathi summary line for the owner is produced by the same template with a translation string table, not by an LLM at report time (no paid call is made to write a night report). The report is **tenant-scoped**: a tenant sees only its own jobs; the platform view aggregates (§12, §14).

**Persistence.** The report must survive restarts and be addressable by window date. The existing contract has no table for it; see CCR-A in §16.

## 9. What may stay up outside the window (Q7)

Directive §1: after 07:00 only the scheduler/monitor may stay up, and only if its measured footprint is safe. Plan Q7 default: **OFF in daytime until the pilot measures it.**

| Component | After 07:00 on the shared VPS | Rule |
|---|---|---|
| `workers/render_worker`, `workers/ai_worker`, `workers/publish_worker` | **Stopped** | Heavy and AI workers are stopped (B1). The AI worker is low CPU, but the directive allows only the scheduler/monitor; this document does not widen that |
| `workers/scheduler` | **Default OFF** (Q7). May be switched ON by configuration only after the footprint is MEASURED and the owner approves | Footprint figure: **ESTIMATE until measured; REQUIRES REVIEW (Phase 1): measurement at pilot (A1 audit supplies the host baseline)**. No figure is given here |
| Monitor (metrics endpoint + lightweight host agent) | Per ADR-006 (not started). 3A: JSON logs + metrics endpoint only (27 §7.3.6) | Same rule: stoppable by configuration |
| PostgreSQL, blob storage | Not part of the window. The database is the system of record and stays up; it is the existing Compose project's data service. Its caps are slice limits (INF-03, INF-04) | Measured at 3A walking skeleton |
| Operator tool (3A) | On demand only | Runs only when the assistant starts it on the owner's chat instruction (D5) |

### 9.1 Configuration

| Key (config, never code) | Default | Meaning |
|---|---|---|
| `night.scheduler.daytime_enabled` | `false` | Q7: scheduler/monitor stay up after `window_end` |
| `night.scheduler.daytime_footprint_limit_mb` | unset | Hard cap when enabled (applied as cgroup `MemoryMax`, INF-03). **REQUIRES REVIEW (Phase 1): set only from a measured footprint** |
| `night.scheduler.daytime_tasks` | `[]` | What the daytime scheduler may do. Allowed values (closed set): `timekeeping` (open/close flag, report finalisation) and `quota_release_check`. It never claims `HEAVY_CPU`, `AI_IO` or `PUBLISH` work |

### 9.2 Without a daytime scheduler

If the scheduler is OFF in the daytime (the default), its duties are done by a **systemd timer or equivalent** (10 defines the unit) that starts the scheduler process at `window_start`, so no resident process exists in the daytime. Admission still protects the window on its own (I4), so nothing depends on the scheduler being present at 06:30 or 07:00; the scheduler improves reporting and ordering, it does not carry safety. The exact mechanism (timer, resident process with a small footprint, or both) is a deployment decision recorded in 10 and in an ADR if it becomes contested (not started).

## 10. Quota-aware scheduling (3C; the 3A line has no upload and no OAuth, D1)

### 10.1 Inputs

- Per bucket limits and costs: YT-01, YT-02, YT-05 (`VIDEO_UPLOADS`, `SEARCH`, `BATCH_GET_STATS`, `DEFAULT`; GLOSSARY §6.42).
- Ledger: `quota_usage` per `(gcp_project_id, pt_date, bucket)` with `units_used`, `units_reserved`, `units_limit`; written only through `amw_quota_reserve/release` (04 §3.6, §5.20). The configured limit is a snapshot: **the Cloud Console value is the authority**; the owner's screenshot (input A4) is pending, so no project limit is assumed (owner rule A.2).
- Per-tenant attribution of shared-project units: `cost_ledger` rows with `operation = 'youtube.quota'`, `unit_kind = 'quota_units'`, `amount_micros = 0` (09).

### 10.2 Quota plan per video (derived from YT-02)

A planned publication consumes, per video: 1 unit in `VIDEO_UPLOADS` (`videos.insert`), 50 for `thumbnails.set`, plus 50 per `videos.update`, plus 50 per `playlistItems.insert` and 400 per `captions.insert` track, all in `DEFAULT` (YT-02). Agent 13 computes the plan before admission and stores it on the task as `quota_units_required` per bucket. **Caption tracks are the largest consumer** (YT-02 implication), so a job with several subtitle languages is scheduled against the PT-day allowance before it is admitted. The plan is an ESTIMATE of cost (from YT-02 prices); the **actual** use is read back from `quota_usage` after the calls.

### 10.3 Admission by quota (PUBLISH class)

1. `amw_quota_reserve(gcp_project_id, bucket, units)` returns `ok` or `exhausted` for the PT day (04 §3.6).
2. On `ok`: units are reserved before the call and settled after (`units_reserved` → `units_used`). Reservation is part of the same transaction as the claim of the publishing task.
3. On `exhausted`: the task is **not retried** (no error attempt). It performs T09 with `wait_reason = AWAITING_QUOTA` and error code `PUBLISHING.QUOTA_EXHAUSTED` (07 §3: SUSPEND, no retry). L1 notice; L3 after `quota.max_wait_days` (07).
4. A **reserve** of a multi-step publication (upload + thumbnail + captions) is taken as a whole before starting: a video must not be left uploaded without its thumbnail or captions because the quota ended mid-way. If the whole plan does not fit the remaining units of the PT day, the whole publication waits; partially done publications resume with their `completed_effects` (idempotency, 03 §9).

### 10.4 Release after the reset

Because the reset falls outside the window (§3.1), the scheduler computes for each `AWAITING_QUOTA` task:

```
reset_instant      = first instant with a new pt_date after suspension
next_open          = next_window_open(reset_instant, window)
scheduled_at       = max(next_open, now)
```

At release (T15) the task goes `QUEUED` with that `scheduled_at`; at claim, `amw_quota_reserve` is attempted again. Releasing earlier than `next_open` has no value on the shared server, because no `PUBLISH` worker may run in the daytime (§9). The condition "PT-day quota reset" of T15 is therefore evaluated by the scheduler at window open (or by claim admission in 3A) rather than at the reset instant.

### 10.5 Scheduling publication time versus working time

A publication has `scheduled_publish_at` (04 `publications`). It is a **YouTube-side** time chosen by Agent 13 and the approver; the window only decides when the **upload work** is done. Uploading at night and scheduling the visible publish time later is therefore possible without a daytime worker. **REQUIRES REVIEW (Phase 1): confirm on the official `videos` resource page (YT-06 source) the field and allowed `privacyStatus` values used for scheduled publication before Agent 13 is blueprinted** (GLOSSARY §6 already marks the `privacyStatus` list as pending). Upload always sets `privacyStatus` explicitly (YT-04) and publication happens only after the recorded approval (publish guard trigger, 04 §5.21).

### 10.6 Multiple GCP projects and tenants

- Quota is per GCP project and PT day (`quota_usage` key). A tenant on its own project (enterprise option, Tier 3) has its own allowance; tenants on a shared project consume the same allowance.
- Fair share of a shared allowance across tenants is by configured per-tenant daily quota budgets (`night.quota.tenant_share_pct`, Tier 2). In Tier 0 there is one tenant; no share logic is built.
- **No quota-extension assumption.** Increased quota requires an audit (YT-11, partial). No design depends on extended quota.

### 10.7 What is **not** scheduled by quota

LLM, TTS and image calls are limited by provider limits and the S4 budget (09), not by the YouTube quota. Overnight LLM batch work (50 percent price, 09) is submitted inside the window by `AI_IO` tasks; **REQUIRES REVIEW (Phase 1): the provider batch completion time and how long results remain available (not in RESEARCH_LOG); until verified, batch eligible tasks are only those flagged `batch_eligible` in config and results are collected in the next window (`AWAITING_EXTERNAL`)**.

## 11. Market-hours guard (D1)

D1 (binding): **render never in market hours**, on every placement (ADR-012 §3.3; 3A_SLICE_SPEC §6.4).

| Item | Rule |
|---|---|
| Applies to | Every `HEAVY_CPU` task: render, audio master, subtitles, technical QC (3A_SLICE_SPEC §6.4; 18 §7). Not to `AI_IO`, `LIGHT` |
| Enforcement | Admission (T07) and `scheduled_at`: no claim and no `scheduled_at` assignment inside a market-hours interval. The guard is evaluated for the **start**; a render already running when the market opens is not killed: it follows the drain path and checkpoints at its next safe point (§6) |
| Independence | The market-hours guard and the night-window guard are independent. The factory runs a render only when **both** allow (ADR-012 §3.3). On the dev environment only the market-hours guard applies |
| Configuration key (owned here, per ADR-012) | `night.market_hours.calendar` (reference to the calendar record: sessions per weekday, holidays, time zone), `night.market_hours.guard_enabled` (default `true`; setting it to `false` is not allowed in production and raises an alert), `night.market_hours.pre_margin_ms` and `night.market_hours.post_margin_ms` (ESTIMATE defaults: unset, owner decision O7) |
| Fail closed | **No calendar configured ⇒ no `HEAVY_CPU` admission** (R9 in 3A_SLICE_SPEC §12). The calendar is owner-supplied (O7) |
| Facts | Exchange session hours and holiday calendar are **REQUIRES REVIEW (Phase 1): record the official exchange session hours and holiday calendar source as a RESEARCH_LOG entry** (ADR-012 §3.3). This document does not state any session time |
| Independence from the window | This document does not assume how the 00:00–07:00 IST window relates to market hours; each guard is evaluated on its own configuration |
| Chart-reading | The guard is an operational setting. It is never an input to chart reading or any content rule (B7) |
| Test | 27 §9 test 6 and ADR-012 tests: a claim during a market-hours interval returns no rows; a render admitted just before the interval closes at its next safe point; calendar absent ⇒ no admission |

## 12. Per-tenant window configuration (dedicated server)

Directive §1: on a dedicated platform server the window becomes per-tenant configuration. Scope: **Tier 1+** (first managed-service client with own server, §1C.15); not built in 3A or 3C-Tier-0.

### 12.1 Where configuration lives

| Level | Field | Status |
|---|---|---|
| Per channel | `channels.production_window jsonb` (04: "T1+ per-tenant window on a dedicated server (06)") | Exists in the contract |
| Per tenant (organisation) | **No field exists**; a tenant-wide default is needed so every channel of a tenant need not repeat the window | CCR-B (pending CCR): `organisations.production_window` |
| Platform default | Config key `night.window.default` = the directive window (`Asia/Kolkata`, 00:00–07:00, drain lead 30 minutes) | New config key (owned here) |

Resolution order for a task: channel window → organisation window → platform default. Jobs that are not tied to a channel (analytics ingest, internal) use the organisation window.

### 12.2 Window document (shape proposed; schema pending CCR)

```json
{
  "timezone": "Asia/Kolkata",
  "windows": [ { "start": "00:00", "end": "07:00" } ],
  "drain_lead_ms": 1800000,
  "always_open": false,
  "market_hours_guard": true
}
```

- `timezone`: an IANA zone; `start`/`end` are local wall times; `end` earlier than `start` means the window crosses midnight in that zone.
- `windows`: one or more intervals per day (a dedicated server may allow 24 hours with a maintenance gap). An operational setting only; no chart logic depends on it.
- `always_open: true` is accepted **only** for a tenant on a dedicated server (no neighbours). It requires a deployment marker `deployment.dedicated = true` (config; Tier 1+). On the shared VPS it is refused at validation (`CONFIG_INVALID`).
- `market_hours_guard` may be `false` only when the render runs on a dedicated server **and** the owner has recorded that decision for that tenant. D1 is stated for the owner's workload on the shared VPS; its extension to client tenants is a decision to confirm (CCR-B text).
- Validation: `end` ≠ `start`; `drain_lead_ms` < window length; at least one window unless `always_open`; unknown keys rejected. A window that fails validation is `CONFIG_INVALID` (07) and admission treats it as **closed** (fail closed).

### 12.3 Behaviour that must hold per tenant

1. Window evaluation is **per task**, using the window resolved for that task's tenant and channel. Two tenants on one dedicated server can have different windows; a drain applies to each task by its own window.
2. The `DRAIN` control carries the task's own `act_by` (03 §4.3); there is no global drain flag when tenant windows differ. The drain flag becomes `(scope, scope_id)` state: `platform` for the shared VPS, `org` for a tenant window (persistence: CCR-A).
3. Night report is generated **per tenant window** and a platform-level report aggregates windows (§8).
4. Tenant isolation (rule 9): a tenant's window configuration, report and queued task counts are visible only to that tenant (RLS on `org_id`); the platform scheduler reads them with the scheduler's system role and writes `audit_log` entries for every window change (`org_id`, who, old/new value).
5. Fair sharing (1C.2): per-tenant concurrency, weighted queueing and render-minute quotas apply inside each window. **Tier 2**.
6. Quota (§10) remains per GCP project and PT day regardless of tenant windows. A tenant whose window never overlaps the reset still follows `next_window_open` (§10.4).

### 12.4 Placement interaction

Render worker placement is ADR-012. If the render worker is moved to a separate server, the window that governs it is the window of **that server**, not of the VPS where the other workers run: a `required_capabilities`-based claim sends `HEAVY_CPU` rows to the render server, and the guard (§5, §11) is evaluated with the render server's configuration. Mixed placements need ADR-012's access path to storage (ADR-005 trigger) and are 3C.

## 13. Operational design

### 13.1 Scheduler loop (3C, deterministic, no LLM)

A bounded periodic loop (`night.scheduler.tick_ms`, ESTIMATE default; the tick period is configuration): evaluate window state for each scope → persist drain flag changes → send `DRAIN` controls → release eligible `CHECKPOINTED` tasks (§6.4, §10.4) → refresh the night report draft → emit metrics. Every action is idempotent; a re-run after a restart produces the same state. No agent loop and no LLM call is involved (rule 5).

### 13.2 Restart safety

The scheduler reads window state from the database and the clock; it does not rely on memory. After a restart inside the drain period it re-sends `DRAIN` only to workers whose lease is still held and whose task has no `DRAIN` mark. After a restart across the window boundary it opens or closes the window by comparing now with the configuration.

### 13.3 Clock and time source

Decisions use the database clock (`now()`) in UTC converted through the IANA zone database. Clock skew between host and database is monitored; a skew above `night.clock_skew_alert_ms` (ESTIMATE default, config) raises an operations alert (L2) and the guard uses the more conservative result (the earlier of the two clocks for window close, the later for window open).

### 13.4 Emergency override

An operator can set `OPERATOR_PAUSE` (S8 / operator tool) at any time: running tasks checkpoint, queue rows are held. There is no "extend the window" control on the shared VPS: extending would take capacity from the neighbouring apps (§1). The only manual window change is a configuration change (audited).

## 14. Alerts and observability

| Signal | Level (07 §7) | Condition |
|---|---|---|
| `night.window_opened` / `night.drain_started` / `night.window_closed` (event names pending CCR-A) | info | Each moment, with counts |
| Forced kill at stop | L2 | Worker not exited at stop timeout |
| Task still `RUNNING` after `window_end` + stop timeout | L2 | Missed stop |
| Admission refusals high | L1 | Refused claims above config threshold in a window |
| `AWAITING_QUOTA` tasks older than `quota.max_wait_days` | L3 (07) | Per 07 §3 |
| Window configuration invalid or empty | L2 | Admission fails closed |
| Clock skew | L2 | §13.3 |
| Night report not written by `window_end` + grace | L2 | Report job failed |

Metrics: tasks admitted and refused by guard and class; checkpoints per window; checkpoint age at resume; stop duration; render minutes used per window; quota units reserved and used per PT date and bucket.

## 15. Tests (specified here; written at build with 11 / 27 §9)

| # | Test | Pass condition |
|---|---|---|
| N1 | Window boundaries with a fake clock for the default window and for a window crossing midnight | claim allowed inside, refused outside, next opening computed correctly |
| N2 | Drain at 06:30 with running render | `DRAIN` sent with the correct `act_by`; worker checkpoints at next safe point; state `CHECKPOINTED` + `DRAIN`; no corrupt file |
| N3 | Stop at 07:00 with a worker in an atomic write | write completes before exit; no forced kill; no temporary file left at a final path |
| N4 | Forced kill after stop timeout | no corrupt final file; lease expires; resume from latest checkpoint next window; not counted as retry |
| N5 | Task with `estimated_remaining_ms` beyond the time left after 06:30 | not admitted; `scheduled_at` moved to next opening; no error |
| N6 | Scheduler OFF during the drain (3A path) | admission alone refuses `HEAVY_CPU` after 06:30 |
| N7 | Market-hours guard: claim in an interval, claim with no calendar, running render at interval start | no claim; no claim; checkpoint, no kill |
| N8 | Quota exhausted mid-publication | `AWAITING_QUOTA`, no retry attempt consumed, resumes at the first window after the reset with `completed_effects` intact |
| N9 | PT-date computation across both daylight and standard offsets (fixtures built from the zone database, not hard-coded 12:30/13:30) | `pt_date` and reset instant correct |
| N10 | Per-tenant windows: two tenants with different windows | each task evaluated by its own window; no cross-tenant read |
| N11 | Invalid window configuration | `CONFIG_INVALID`, admission closed, alert raised |
| N12 | Night report | contains every section of §8 with counts equal to the database; per-tenant visibility holds |
| N13 | Q7: `daytime_enabled = false` | no scheduler or worker process runs after 07:00 in the cgroup listing (INF-04 test method) |

## 16. Contract gaps (this document writes against the proposed names; listed in `audit/b2_unfiled_ccr_requests_shared.md` for the integrator to file (not yet in CONTRACT_CHANGE_REQUESTS.md))

| ID | Needed | Proposal (pending CCR) |
|---|---|---|
| CCR-A | A persisted record of night runs (drain flag by scope, window start/end, report blob reference, counts) and the event names for window moments | Table `night_runs` (pending CCR) with columns scope, scope_id, window_start, window_end, drain_started_at, closed_at, report_ref (blob of kind `REPORT`); events `night.window_opened`, `night.drain_started`, `night.window_closed` (pending CCR) |
| CCR-B | Tenant-wide window default | Column `organisations.production_window jsonb` (pending CCR); schema of the window document of §12.2 added to GLOSSARY or 03 |

Until the CCRs are decided, the 3A guards need neither: the guards read configuration and the clock only.

## 17. Scope by phase and tier

| Item | 3A | 3B | 3C | Tier |
|---|---|---|---|---|
| Market-hours guard on every placement; fail closed with no calendar | Yes | Yes | Yes | 0 |
| Night-window guard on the VPS placement (claim only in window, no `HEAVY_CPU` after drain, no non-fitting task) | Yes (after A1, ADR-012 rule, owner approval) | Yes | Yes | 0 |
| Cooperative drain and checkpoint (07 §8) | Yes | Yes | Yes | 0 |
| Operator `report` command (night-report content, from existing tables) | Yes | Yes | Yes | 0 |
| `workers/scheduler`, persisted drain flag, `night_runs`, night report in the Command Center | No | No | Yes | 0 |
| Quota-aware scheduling and `AWAITING_QUOTA` release at window open | No (no upload) | No | Yes (with Agent 13) | 0 design, 1 for client projects |
| Daytime scheduler/monitor (Q7) | OFF | OFF until pilot measures | Optional after measurement | 0 |
| Per-tenant window configuration, window crossing midnight, multiple windows | No | No | Design only unless a Tier 1 client exists | 1+ |
| Fair share, weighted queueing, render-minute quotas per tenant | No | No | No | 2 |
| Client-owned GCP project quota | No | No | No | 3 (option) |

## 18. Open items

| ID | Item | Blocks |
|---|---|---|
| O-1 | Exchange session hours and holiday calendar source (R9/O7); RESEARCH_LOG entry | First render under any guard (fail closed) |
| O-2 | Measured scheduler/monitor footprint; decision on daytime operation (Q7) | Nothing in 3A |
| O-3 | Measured task durations for `estimated_remaining_ms` | Precise admission after 06:30 (3A uses the conservative fallback) |
| O-4 | Service stop timeout and `limits.max_atomic_write_ms` per worker type | Deployment (10) |
| O-5 | `videos` resource field list for scheduled publication and `privacyStatus` values | Agent 13 blueprint (3C) |
| O-6 | Provider batch completion time and result retention | Overnight LLM batch (3C) |
| O-7 | Project quota limit from the Cloud Console (owner input A4) | Quota plan numbers (3C) |
| O-8 | CCR-A and CCR-B decisions | `workers/scheduler`, per-tenant windows |

## 19. Cited RESEARCH_LOG IDs

YT-01, YT-02, YT-03, YT-05, YT-06 (source page for O-5), YT-11, INF-01, INF-03, INF-04. Facts not found there are marked **REQUIRES REVIEW (Phase 1)** in the text above.
