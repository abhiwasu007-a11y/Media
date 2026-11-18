# 07 — Failure Management

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 01 (orchestrator) with `amw_core.retries`; S5 (→ 01) for resource signals; Agent 13 for publishing reconciliation |
| Depends on | GLOSSARY_AND_IDS.md (§6.1, 6.3, 6.31–6.34), 03_COMMUNICATION_STANDARD.md (§6 Error, §9 idempotency, §11 state machine), 04_DATABASE_ARCHITECTURE.md (§5.3, 5.4, 5.7, 5.8, 5.9), 06_NIGHT_SCHEDULING.md (window detail, not yet written), RESEARCH_LOG.md (YT-02, YT-03, YT-04) |
| Directive sections covered | §3.3 Failure taxonomy, Recovery, Escalation; §1 production window (06:30 drain, 07:00 graceful stop); rule 5 (no infinite retries, no silent drops, no uncontrolled loops); §3.5.2 (parse failure: retry once, then DLQ) |
| Tier | All **MVP (Tier 0)**. Per-tenant breakers for client-owned credentials are Tier 1+ (same mechanism). |

All numeric defaults in this document are **design defaults (ESTIMATE)**, stored in configuration and recalibrated against measured behaviour in the golden-sample pilot. None is an external fact.

---

## 1. Principles
1. Every failure is classified into exactly one `failure_class` (GLOSSARY §6.31) by its error code (§2). The class decides retry, suspension or failure — not the component that raised it.
2. Permanent errors are never retried (rule 5). Retryable errors have bounded attempts with exponential backoff and jitter (§3).
3. Nothing is dropped: every `FAILED` task reaches `DEAD_LETTER` (T14) or is cancelled by a recorded human decision (T19); the reaper finishes interrupted hand-offs (§6).
4. A replay never duplicates an external effect: every side effect has an idempotency key (03 §9) and a reconciliation procedure (§11).
5. Recovery restarts the smallest failed unit — one attempt of one task — from its latest checkpoint (§10).
6. Loops are impossible by construction: the orchestrator only follows registry DAGs; revisions are bounded counters; every repetition has a hard cap (§9).

## 2. Error code catalogue
Format `<CLASS>.<CODE>` (03 §6). Disposition: **RETRY** → `RETRY_WAIT` (T10) if the policy allows, else `FAILED`; **SUSPEND:<reason>** → `CHECKPOINTED` (T09) with that `wait_reason`; **FAIL** → `FAILED` (T11 / T06) → `DEAD_LETTER`; **NO-ATTEMPT** → the attempt never started and is not counted.

| Code | Meaning | Disposition | Retry policy (§3) | Breaker counts | Escalation |
|---|---|---|---|---|---|
| `TEMPORARY.NETWORK` | connection reset/refused, DNS failure | RETRY | `temporary` | yes | L1 |
| `TEMPORARY.TIMEOUT` | provider or internal call timed out | RETRY | `temporary` | yes | L1 |
| `TEMPORARY.RATE_LIMITED` | HTTP 429 or provider rate-limit code | RETRY (honour `retry_after_ms`) | `rate_limited` | yes | L1 |
| `TEMPORARY.UPSTREAM_5XX` | HTTP 5xx from a provider | RETRY | `temporary` | yes | L1 |
| `TEMPORARY.DB_TRANSIENT` | serialization failure, deadlock, connection blip | RETRY | `db` | no | L1 |
| `TEMPORARY.LOCK_CONFLICT` | optimistic-lock mismatch on a transition (03 §11.4) | NO-ATTEMPT: re-read and re-evaluate | `caps.lock_conflict_reevaluations` | no | L1 |
| `PERMANENT.SCHEMA_INVALID` | contract or payload failed its schema | FAIL | never | no | L2 |
| `PERMANENT.SCHEMA_VERSION_UNSUPPORTED` | version outside the supported set | FAIL | never | no | L2 |
| `PERMANENT.INPUT_INVALID` | semantically invalid input (wrong ID prefix, impossible values) | FAIL | never | no | L2 |
| `PERMANENT.CONFIG_INVALID` | missing/invalid configuration (model, provider, limit) | FAIL | never | no | L3 (operations) |
| `PERMANENT.UNSUPPORTED_TASK` | task type not registered for the executor | FAIL | never | no | L2 |
| `PERMANENT.MISSING_DEPENDENCY` | referenced row/blob absent | FAIL | never | no | L2 |
| `PERMANENT.AUTH_INVALID` | provider credential rejected (HTTP 401/403, not refreshable) | FAIL | never | no | L3 (security/ops) |
| `PERMANENT.PERMISSION_DENIED` | actor lacks the permission (RBAC) | FAIL | never | no | L3 (security) |
| `PERMANENT.TENANT_INACTIVE` | org suspended/offboarding | FAIL | never | no | L3 (business) |
| `PERMANENT.TENANT_MISMATCH` | org IDs disagree across envelope/input/context | FAIL | never | no | L3 (security) |
| `PERMANENT.CROSS_TENANT_REF` | a URI/ref of another tenant | FAIL + security event | never | no | L3 (security incident) |
| `PERMANENT.IDEMPOTENCY_CONFLICT` | same key, different request hash | FAIL | never | no | L3 (data integrity) |
| `PERMANENT.INVALID_TRANSITION` | state transition not allowed (03 §11.3) | FAIL | never | no | L2; L3 if repeated |
| `PERMANENT.DEADLINE_EXCEEDED` | deadline passed or wait timed out | FAIL | never | no | L2 |
| `PERMANENT.PROVIDER_REFUSAL` | provider refused the content (safety/policy) | FAIL (after configured fallback provider inside the attempt, if any) | never | no | L2 → L3 if a compliance question |
| `PERMANENT.INSUFFICIENT_INPUT` | LLM step returned a refusal `INSUFFICIENT_INPUT` (27 §4) | FAIL | never | no | L2 (orchestrator re-plans upstream) |
| `RESOURCE.OOM` | process killed for memory | RETRY with reduced concurrency (05) | `resource` | no | L1 → L2 |
| `RESOURCE.CPU_SATURATION` | task aborted under CPU pressure | RETRY | `resource` | no | L1 → L2 |
| `RESOURCE.DISK_FULL` | write failed: no space | SUSPEND:`OPERATOR_PAUSE` + heavy admission paused | none | no | L3 (operations) |
| `RESOURCE.RENDER_CRASH` | FFmpeg exited abnormally | RETRY from checkpoint | `resource` | no | L1 → L2 |
| `RESOURCE.BUDGET_EXHAUSTED` | S4 refused the spend | SUSPEND:`AWAITING_BUDGET` | none | no | L3 (finance; rule 8: no automatic spend increase) |
| `AGENT.CRASH` | unhandled exception in stage code | RETRY | `agent` | no | L1 → L2 |
| `AGENT.HANG` | heartbeat stale / wall budget exceeded | RETRY | `agent` | no | L1 → L2 |
| `AGENT.INVALID_JSON` | LLM output not parseable | RETRY once with the parse error appended (§3.5.2) | `agent_parse` | no | L2 after cap |
| `AGENT.OUTPUT_SCHEMA_INVALID` | parsed output fails the Pydantic/JSON schema | RETRY once with the validation error (§3.5.2) | `agent_parse` | no | L2 after cap |
| `AGENT.CORRUPTED_OUTPUT` | output blob hash/size mismatch | RETRY | `agent` | no | L2 |
| `AGENT.INCOMPLETE_OUTPUT` | success claimed but 03 §5.3 rule failed | RETRY once | `agent_parse` | no | L2 |
| `AGENT.QUALITY_REPEATED_FAILURE` | the step's own deterministic checks failed on every allowed attempt | FAIL | never (already capped) | no | L3 (quality) |
| `AGENT.LOOP_CAP_EXCEEDED` | any hard cap of §9 reached | FAIL | never | no | L3 |
| `INFRASTRUCTURE.HOST_RESTART` | host or container restarted mid-attempt | RETRY from checkpoint | `infra` | no | L1 |
| `INFRASTRUCTURE.DB_UNAVAILABLE` | database unreachable | RETRY (worker stops claiming until DB is back) | `infra` | no | L1 → L3 if > `infra.db_outage_alert_ms` |
| `INFRASTRUCTURE.QUEUE_UNAVAILABLE` | queue functions unavailable | RETRY | `infra` | no | L1 → L3 |
| `INFRASTRUCTURE.STORAGE_UNAVAILABLE` | storage backend unreachable | RETRY | `infra` | no | L1 → L3 |
| `INFRASTRUCTURE.NETWORK_OUTAGE` | all outbound calls failing | RETRY | `infra` | yes | L1 → L3 |
| `INFRASTRUCTURE.CIRCUIT_OPEN` | breaker for the required provider is `OPEN` | NO-ATTEMPT: stay/return to `RETRY_WAIT` until `open_until` | — | — | L1; L2 if open > `open_ms_max` |
| `INFRASTRUCTURE.WORKER_LOST` | lease expired and the worker's heartbeat is stale | RETRY from checkpoint | `infra` | no | L1 |
| `PUBLISHING.UPLOAD_INTERRUPTED` | resumable upload broke mid-transfer | RETRY by resuming the stored session (§11) | `publish_resume` | no | L1 |
| `PUBLISHING.UPLOAD_REJECTED` | destination rejected the file/metadata | FAIL | never | no | L3 (publishing) |
| `PUBLISHING.QUOTA_EXHAUSTED` | YouTube quota bucket used up for the PT day (YT-02, YT-03) | SUSPEND:`AWAITING_QUOTA` until the next PT-day reset | none | no | L1; L3 if still exhausted after `quota.max_wait_days` |
| `PUBLISHING.OAUTH_REVOKED` | token revoked by the channel owner | FAIL; channel → `NEEDS_REAUTH` | never | no | L3 (publishing) |
| `PUBLISHING.OAUTH_REFRESH_FAILED` | refresh failed (not a revocation) | RETRY | `temporary` | yes | L3 after cap; channel → `NEEDS_REAUTH` |
| `PUBLISHING.PROCESSING_FAILED` | destination processing failed or timed out | FAIL | never | no | L3 (publishing) |
| `PUBLISHING.VERIFICATION_MISMATCH` | post-publish read-back differs (privacy, title, disclosure flag) | FAIL; publication not marked `VERIFIED` | never | no | L3 (publishing) |
| `PUBLISHING.DUPLICATE_DETECTED` | reconciliation found the video already uploaded | NO new upload; link existing video; task continues if consistent, else FAIL | never | no | L3 (data integrity) if inconsistent |
| `PUBLISHING.NOT_AUTHORISED` | publish guard failed (approval, editorial contribution, authorisation verdict; 04 §5.21) | FAIL | never | no | L3 (publishing; should never happen) |
| `PUBLISHING.DESTINATION_UNAVAILABLE` | destination returns 5xx/outage | RETRY | `temporary` | yes | L1 |

New codes are additive and require a CCR (CONTRACT_CHANGE_REQUESTS.md).

## 3. Retry policies

### 3.1 Formula (backoff + jitter)
For the *k*-th retry of a task within one class (*k* = failed attempts of that class so far, *k* ≥ 1):

```
d_k     = min(cap_ms, base_ms × multiplier^(k−1))
wait_k  = d_k × (1 − jitter) + U × d_k × jitter          U ~ Uniform[0, 1)
if retry_after_ms present:   wait_k = max(wait_k, retry_after_ms)
if retry_after_ms > rate_limited.retry_after_max_ms:  disposition → SUSPEND:AWAITING_EXTERNAL (resume at retry time), escalate L2
next_attempt_at = now + wait_k
if deadline is set and next_attempt_at > deadline:  disposition → FAIL with PERMANENT.DEADLINE_EXCEEDED
```
Window interaction: if `next_attempt_at` is outside the admissible window for the task's resource class, the requeued row's `scheduled_at` is the next window opening (06).

### 3.2 Retry allowed only when all hold
1. The code's disposition is RETRY.
2. `tasks.attempt_count < tasks.max_attempts` (task ceiling ≤ 10, DB CHECK, 04 §5.3).
3. Failures of this class for this task < the policy's `max_attempts`.
4. No hard cap of §9 is reached.

### 3.3 Policy table (config `retry.<policy>.*`; design defaults, ESTIMATE)
| Policy | base_ms | multiplier | cap_ms | jitter | max_attempts (class) | Used by |
|---|---|---|---|---|---|---|
| `temporary` | 2,000 | 2 | 300,000 | 0.5 | 5 | network, timeout, 5xx, OAuth refresh, destination 5xx |
| `rate_limited` | 10,000 | 2 | 900,000 | 0.5 | 6 (`retry_after_max_ms` 3,600,000) | 429 |
| `db` | 200 | 2 | 10,000 | 0.5 | 5 | DB transient |
| `resource` | 60,000 | 2 | 1,800,000 | 0.5 | 3 | OOM, CPU, render crash |
| `agent` | 5,000 | 2 | 120,000 | 0.5 | 3 | crash, hang, corrupted output |
| `agent_parse` | 0 (immediate, error appended to the prompt) | — | — | — | 2 (one retry, §3.5.2) | invalid JSON, schema invalid, incomplete |
| `infra` | 30,000 | 2 | 900,000 | 0.5 | 8 | host restart, DB/queue/storage/network outage, worker lost |
| `publish_resume` | 15,000 | 2 | 600,000 | 0.5 | 5 | upload interrupted |

### 3.4 Never retried
Every `PERMANENT.*` code; `AGENT.QUALITY_REPEATED_FAILURE`; `AGENT.LOOP_CAP_EXCEEDED`; `PUBLISHING.UPLOAD_REJECTED`, `OAUTH_REVOKED`, `PROCESSING_FAILED`, `VERIFICATION_MISMATCH`, `NOT_AUTHORISED`. Suspensions (`QUOTA_EXHAUSTED`, `BUDGET_EXHAUSTED`, `DISK_FULL`) are waits, not retries, and consume no attempt.

## 4. Circuit breakers (per external provider)

### 4.1 Key and storage
Key = `(provider, operation_class, credential_scope)` in `circuit_breakers` (04 §5.8). `credential_scope` separates the platform's credential from a client-owned one (e.g. a client GCP project, Tier 1+), so one tenant's bad credential never opens the breaker for others. State is shared by all workers through the DB (`amw_breaker_record`).

### 4.2 Configuration (`breaker.<provider>.<operation_class>.*`; design defaults, ESTIMATE)
| Key | Default | Meaning |
|---|---|---|
| `window_ms` | 60,000 | rolling window for the failure ratio |
| `min_calls` | 5 | minimum calls in the window before the ratio applies |
| `failure_ratio` | 0.5 | open when counted failures / calls ≥ this |
| `consecutive_failures` | 5 | open on this many counted failures in a row, regardless of the window |
| `open_ms` | 30,000 | first open duration |
| `open_ms_max` | 900,000 | ceiling for repeated openings |
| `half_open_max_probes` | 1 | concurrent trial calls allowed in `HALF_OPEN` |
| `half_open_successes_to_close` | 2 | consecutive probe successes to close |

Counted failures: codes marked "Breaker counts: yes" in §2 only. Client-side errors (`PERMANENT.*`) never count, so bad input cannot open a breaker.

### 4.3 Transitions
| From | To | Rule | Side effect |
|---|---|---|---|
| `CLOSED` | `OPEN` | `window_calls ≥ min_calls` and ratio ≥ `failure_ratio`, or `consecutive_failures` reached | `opened_at = now`, `open_until = now + min(open_ms × 2^open_count, open_ms_max)`, `open_count += 1`; S8 alert (L1 info) |
| `OPEN` | `HALF_OPEN` | first check with `now ≥ open_until` | allow up to `half_open_max_probes` calls |
| `HALF_OPEN` | `CLOSED` | `half_open_successes_to_close` consecutive probe successes | reset window counters and `open_count = 0` |
| `HALF_OPEN` | `OPEN` | any counted failure of a probe | reopen with the doubled duration |
While `OPEN`, the adapter rejects calls without network I/O (`INFRASTRUCTURE.CIRCUIT_OPEN`, no attempt consumed). If configuration names a fallback adapter for the operation and the stage's quality gate permits it, the adapter uses the fallback inside the same attempt and records the provider used in `cost_ledger` (§3.3 AI providers). An `OPEN` state lasting longer than `open_ms_max` in total escalates to L2. Breaker transitions are logged and audited (platform owner org's chain for platform credentials; the tenant's chain for tenant credentials).

## 5. Dead-letter queue and controlled manual replay

### 5.1 DLQ record
Written at T14 in `dead_letter` (04 §5.7): payload ref + SHA-256, reason, last error object, retry history (every attempt with error code, times, worker), redacted traceback ref, last attempt and last run time, `recovery_status = NEW`, escalation level. The job moves to `DEAD_LETTER` (J09) when the task is required.

### 5.2 Recovery workflow
| Step | Status | Who | Rule |
|---|---|---|---|
| 1 | `NEW` | system | notification per escalation level (§7) |
| 2 | `TRIAGED` | Org Admin / Platform Owner (`dlq.triage`) | root-cause note required |
| 3 | fix | human | config change, credential renewal, code deploy or upstream input fix — outside the DLQ |
| 4 | `REPLAY_REQUESTED` | human (`dlq.replay`) | replay = same Task Input, same idempotency key |
| 5 | `REPLAY_APPROVED` | human | tasks with external side effects in `upload.*`, `publish.*`, `billing.*`, `stock.license` scopes, or any paid task above `dlq.replay_cost_review_micros`, need an `approvals` row of kind `DLQ_REPLAY` |
| 6 | `REPLAYED` | system (T17) | reconciliation (§11) runs first for side-effect scopes; attempt counters reset is recorded in the DLQ row; `replay_count += 1` ≤ `limits.max_replays_per_item` |
| 7 | `RESOLVED` or back to `NEW` | system | `RESOLVED` when the replayed task completes; a new failure creates a new DLQ row |
| alt | `DISCARDED` | human (`dlq.discard`, T18) | reason recorded; job cancelled if the task was required |

Rules: (1) A replay never edits the input. If the input must change, the item is discarded and the orchestrator creates a new revision task (new `iteration`, new idempotency key). (2) Bulk replay of items with the same `error_code` is allowed after one triage, in batches of at most `dlq.bulk_replay_max`, each item audited individually. (3) DLQ items are never auto-deleted while unresolved.

## 6. Stuck-job detection (reaper, `sys_reaper`)
The reaper runs every `reaper.interval_ms` (default 15,000) using the identifier-only functions of 04 §3.6.

| Condition | Default threshold (config) | Action |
|---|---|---|
| `RUNNING`, queue lease expired, worker heartbeat fresh | `lease_ms` 60,000 (worker renews every `heartbeat_ms` 15,000) | `AGENT.HANG` → T10/T11 |
| `RUNNING`, lease expired, worker heartbeat stale | worker heartbeat older than 3 × `heartbeat_ms` | `INFRASTRUCTURE.WORKER_LOST` → T10/T11; worker → `LOST` |
| `RUNNING` beyond `resource_budget.max_wall_ms` | per task | worker self-aborts at the next safe point; else reaper → `AGENT.HANG` |
| `VALIDATING` too long | 300,000 | re-run validation once, then `PERMANENT.DEADLINE_EXCEEDED` → FAILED |
| `FAILED` without a DLQ row | 60,000 | complete T14 |
| `RETRY_WAIT` past `next_attempt_at` | 300,000 overdue | alert (scheduler health), L2 |
| `QUEUED` beyond class wait | `queue.<class>.max_wait_ms` | alert only (fair-share / capacity signal to S5), no transition |
| `CHECKPOINTED` by `wait_reason` | `DRAIN`: none (resume next window) · `AWAITING_APPROVAL`: none, reminders every `approval.reminder_ms`, L3 after `approval.escalate_ms` · `AWAITING_QUOTA`: resume after the PT reset; L3 after `quota.max_wait_days` · `AWAITING_BUDGET`: none, L3 notice to Finance · `AWAITING_EXTERNAL`: `wait.awaiting_external.timeout_ms` → T16 · `OPERATOR_PAUSE`: none | as stated |
| Job `RUNNING` with no task transition | `job.max_idle_ms` | L2 |

## 7. Escalation levels
| Level | Who | Triggers | Allowed actions | Never |
|---|---|---|---|---|
| **L1** automatic | `amw_core.retries`, adapters, reaper | any retryable code; breaker events; checkpoint resume; reconciliation | retry with backoff, breaker gating, resume from checkpoint, fallback adapter from config | change config, prompts, policies; spend beyond budgets; publish |
| **L2** orchestrator | Agent 01 (deterministic rules) | attempts exhausted for TEMPORARY/RESOURCE/AGENT/INFRASTRUCTURE codes; the same `error_code` on ≥ `escalation.systemic_threshold` (default 3) tasks within `escalation.systemic_window_ms`; breaker open beyond `open_ms_max`; stuck-detector alerts | pause admission for the affected task type/provider; reduce concurrency (05); switch to the configured fallback provider; reschedule to the next window; re-plan a job branch from the registry's alternatives; dead-letter with a recommendation | invent new task types; loop; change critical policies; approve anything |
| **L3** human | per class below, via S7 notifications and the S8 approvals inbox | business, security, publishing and data-integrity failures (§3.3); anything L2 could not resolve | triage, fix, replay, discard, re-authorise, raise a budget (rule 8: owner authorisation) | — |

L3 routing: security (`CROSS_TENANT_REF`, `TENANT_MISMATCH`, `PERMISSION_DENIED`, `AUTH_INVALID`, audit-chain mismatch) → Platform Owner and the tenant's Org Owner; publishing (`PUBLISHING.*` L3 codes) → tenant Org Admin + Reviewer/Approver; budget → tenant Finance; data integrity (`IDEMPOTENCY_CONFLICT`, `DUPLICATE_DETECTED` inconsistent) → Platform Owner; operations (`CONFIG_INVALID`, `DISK_FULL`, prolonged infrastructure outage) → Platform Owner. Inside a client tenant the platform owner is informed only of platform-level causes (rule 10).

## 8. Night-window interaction (06 owns the schedule; this section owns failure-safety)
1. **Atomic write unit:** the smallest operation that leaves storage consistent: write to a temporary file in the same storage area, flush, then atomic rename to the final write-once path; one DB transaction; one resumable-upload chunk. Workers never interrupt an atomic unit. Each worker type declares `limits.max_atomic_write_ms`.
2. **06:30 drain:** the scheduler sets the drain flag. Admission stops claiming `HEAVY_CPU` tasks (06 decides whether other classes are included) and refuses any task whose estimated remaining time exceeds the time left to 07:00. A `DRAIN` control (03 §4.3, `act_by` = 07:00 minus `drain.grace_ms`) goes to every worker running heavy tasks. At the next safe point each worker writes a checkpoint, transitions T09 (`wait_reason = DRAIN`) and releases its lease. Finished outputs are persisted; the night report is written (06).
3. **07:00 graceful stop:** heavy workers receive the service stop signal: stop claiming, finish the current atomic unit, checkpoint, release the lease, exit. The service stop timeout (10) must exceed `limits.max_atomic_write_ms` of that worker type.
4. **If a process dies anyway** (hard kill, host restart): its temporary file is never renamed, so no corrupt output exists at a final path; the lease expires; the reaper resumes the task from its latest checkpoint at the next window (`INFRASTRUCTURE.HOST_RESTART` / `WORKER_LOST`).
5. Tasks in `DRAIN` resume (T15) only when the window opens and admission allows. `RETRY_WAIT` times falling outside the window shift to the next opening (§3.1).

## 9. Hard caps (no uncontrolled loops)
| Cap (config key) | Default (ESTIMATE) | Enforced at | On breach |
|---|---|---|---|
| `limits.max_attempts_per_task` | 10 ceiling (DB CHECK); per-task `max_attempts` from policy | T10 guard | FAIL `AGENT.LOOP_CAP_EXCEEDED` |
| `limits.max_revision_loops` (per gate per job) | 3 | orchestrator before creating a revision task | job `COMPLETED` with `BLOCKED_COMPLIANCE` / FAIL L3 |
| `limits.max_tasks_per_job` | 200 | T01 guard | FAIL `AGENT.LOOP_CAP_EXCEEDED` |
| `limits.max_child_jobs_per_job` | 10 | job creation | refuse creation, L2 |
| `limits.max_replays_per_item` | 3 | T17 guard | replay refused; L3 |
| `resource_budget.max_llm_calls` | per task type (agent blueprint) | adapter | FAIL `AGENT.LOOP_CAP_EXCEEDED` |
| `resource_budget.max_cost_micros` | per task type | adapter + S4 reservation | SUSPEND `AWAITING_BUDGET` |
| `limits.max_job_active_ms` (excludes `CHECKPOINTED` time) | 86,400,000 | reaper | L2, then L3 |
| `caps.lock_conflict_reevaluations` | 5 per transition | state machine | FAIL `PERMANENT.INVALID_TRANSITION` |
| LLM self-repair | 1 retry with the validation error | `agent_parse` policy | DLQ |
Structural guarantees: only the orchestrator creates tasks; graphs come from the registry and are validated as DAGs at load (24 §3); revision edges are bounded counters, not cycles; no task type may enqueue another task.

## 10. Checkpoint, resume and restart-only-the-failed-component
1. Long tasks (render, multi-segment TTS, batch LLM, uploads) write checkpoints at safe points (`checkpoints`, 04 §5.7): resume key, state blob, completed idempotency keys.
2. A new attempt starts from `resume_checkpoint_id` (or the latest checkpoint) and skips effects listed in `completed_effects`.
3. Only the failed attempt is redone. Completed tasks are never re-run (T04 idempotent hit). A failure in one task never restarts the job or other tasks.
4. Components are independent processes: the orchestrator is stateless between transactions (all state in the DB), so its restart resumes from the DB; a crashed worker affects only its claimed tasks (reaper); container restart policies are per service (10).

## 11. Idempotent side effects — a replay never duplicates a video
Keys and scopes: 03 §9. Publishing procedure (Agent 13 implements; its blueprint adds API detail):
1. Before any API call, insert the `publications` row (`DRAFT`) with key `upload.youtube` = (channel, render SHA-256); the partial unique index blocks a second live row for the same render (04 §5.21).
2. Open the resumable session; store the session reference encrypted **before** sending the first chunk; set `UPLOADING`. Upload always with `privacyStatus = private` (YT-04).
3. On `UPLOAD_INTERRUPTED`: resume the stored session (same key).
4. If the session is invalid and the outcome is unknown: run **reconciliation** — Agent 13 checks the channel's own uploads for this publication's marker. Only a definite "not found" permits a new session under the same key; "found" links the existing video (`DUPLICATE_DETECTED` handled as success if consistent). The exact lookup method and its quota cost: **REQUIRES REVIEW (Phase 1): verify the list/search method and cost on the official YouTube API pages (YT-02) when writing the agent_13 blueprint.**
5. Changing privacy to public or scheduling is a separate effect (`publish.youtube`) gated by the publish guard (04 §5.21), followed by read-back verification (`VERIFICATION_MISMATCH` on difference).
6. Every other paid or external effect follows the same pattern: key → `IN_PROGRESS` → effect → `COMPLETED` with result ref; reconciliation before any repeat of an `IN_PROGRESS` effect whose lock expired.

## 12. Observability and tests
- Metrics (all labelled `org_id`, `agent_id`, `error_code`): attempts, retries, DLQ inflow and age, breaker state, stuck detections, escalations by level, replays.
- Every failure log line carries `org_id`, `correlation_id`, `job_id`, `task_id`, `attempt_id`, `error_code`, `error_class`.
- Failure-injection tests (11 / 27): one test per error code proving its disposition; kill-during-render (resume, no corrupt file); kill-during-upload (resume, single video); breaker open/half-open/close; DLQ replay with reconciliation; drain at a simulated 06:30 and stop at 07:00; every hard cap of §9 reached once.
