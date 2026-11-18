# ADR-001 — Job queue: own Postgres table vs Procrastinate vs PgQueuer

| Field | Value |
|---|---|
| Status | **Proposed** (documentation). Software: **Planned** |
| Decider | Owner (Abhi), on the lead's recommendation |
| Depends on | 04_DATABASE_ARCHITECTURE.md §1, §3.1, §3.2, §3.6, §3.7, §5.4; 03_COMMUNICATION_STANDARD.md §11 (T03, T07, T09–T12, T15, T17); 07_FAILURE_MANAGEMENT.md §3, §6, §8; GLOSSARY_AND_IDS.md §6.5–6.7, §6.20; 27_ENGINEERING_STANDARDS.md §2, §9 |
| Directive sections covered | §1 Queue; §3.2a (queue: Postgres-backed unless an ADR proves Redis + Celery is needed); §3.3 Migration (workers with declared capabilities) |
| Research IDs | INF-05, INF-06, INF-11 |
| MVP scope | **3A** (walking skeleton needs claim, lease, reaper: 27 §9). Fair-share weights by plan: **3C**. |
| Enterprise tier | Tier 0 (one tenant, shared pool) → Tier 1–2 (same table, fair-share key active) → Tier 3 (`workers.dedicated_org_id`, 04 §5.4) |

## 1. Context
- §1 prefers a PostgreSQL-backed queue (`FOR UPDATE SKIP LOCKED`, LISTEN/NOTIFY) over Redis/RabbitMQ/Celery, to avoid extra resident services on the shared 2 vCPU / 8 GB server (INF-01) and to keep transactional state, DLQ and replay in the same database. Both candidate libraries meet that headline:
  - Procrastinate v3.11.0, MIT, Python ≥ 3.10, PostgreSQL 13+, retries, periodic tasks, async, LISTEN/NOTIFY, SKIP LOCKED (INF-05).
  - PgQueuer v2.0.0, MIT, Python ≥ 3.11, PostgreSQL 14+, SKIP LOCKED, LISTEN/NOTIFY, cron scheduling, retry/backoff, asyncio (INF-06).
- The Wave A contracts add four hard constraints that any option must meet:
  1. **Tenancy.** Every tenant table has `org_id`, `ENABLE` + `FORCE ROW LEVEL SECURITY` (04 §1.2, §3.4). The app role `amw_app` is `NOBYPASSRLS` and non-owner (04 §3.1, INF-11). With `app.org_id` unset, a tenant table returns **no rows** (fail closed, 04 §3.2). The queue row carries the `amw.envelope`, which is tenant data, so `task_queue` is a TENANT table (04 §5.4); a GLOBAL table may carry no tenant data (04 §1.2).
  2. **Claim before tenant is known.** A worker does not know the tenant of the next job. 04 §3.6 solves this with `amw_queue_claim(worker_id, capabilities[], resource_classes[], n)`: a `SECURITY DEFINER` function owned by `amw_sysfn` (`BYPASSRLS`, never granted to a login role), fixed `search_path`, returning identifiers and the envelope only, claiming with `FOR UPDATE SKIP LOCKED`, ordered by the fair-share rule of 05. The worker then opens a normal tenant transaction with `SET LOCAL app.org_id`.
  3. **One state authority.** Task states, retries and DLQ are owned by the 03 §11 state machine and 07: T07 claim (capabilities ⊇ `required_capabilities`, admission, breaker), T10 → `RETRY_WAIT` with `next_attempt_at` (07 §3), T12 new queue row `READY`, T14 DLQ, T17 controlled replay, reaper on `lease_ms` / `heartbeat_ms` (07 §6). Window drain uses `CHECKPOINTED` + `wait_reason = DRAIN` (07 §8).
  4. **Capability routing.** Workers declare `capabilities` and `resource_classes` (04 §5.4 `workers`, GLOSSARY §6.20, §6.6), so render/AI workers can move to other machines (§3.3 Migration).
- 04 §5.4 records the open point: *"the chosen library's own job table must carry `org_id` with FORCE RLS and support claiming through the `SECURITY DEFINER` function, or the factory keeps this table and uses the library only for its worker loop."*

## 2. Options considered (with evidence)

| Criterion | A. Own table `task_queue` + `amw_queue_claim` (04 §5.4) | B. Procrastinate (INF-05) | C. PgQueuer (INF-06) |
|---|---|---|---|
| No extra resident service (§1) | Yes: PostgreSQL only | Yes: PostgreSQL only (INF-05) | Yes: PostgreSQL only (INF-06) |
| SKIP LOCKED + LISTEN/NOTIFY | Written in `amw_queue_claim` (04 §3.6) | Yes (INF-05) | Yes (INF-06) |
| Job row carries `org_id` with FORCE RLS (constraint 1) | Yes, by design (04 §5.4) | **Not shown in RESEARCH_LOG.** REQUIRES REVIEW (Phase 1): read the library's schema/migrations and record whether its job table can take an extra `org_id` column + FORCE RLS policy | **Not shown in RESEARCH_LOG.** REQUIRES REVIEW (Phase 1): same check |
| Fetch through the `SECURITY DEFINER` claim function (constraint 2) | Yes, by design | **Not shown.** REQUIRES REVIEW (Phase 1): whether the fetch query/function is replaceable | **Not shown.** REQUIRES REVIEW (Phase 1): same check |
| Single state authority (constraint 3) | Yes: queue rows are created/removed only by 03 §11 transitions | Library has its own retry feature (INF-05); it would have to be disabled so that 07 §3 stays the only retry policy | Library has its own retry/backoff (INF-06); same |
| Capability + resource-class routing, fair share (constraint 4) | Yes: claim filters on `required_capabilities`, `resource_class`, `fair_share_key` | REQUIRES REVIEW (Phase 1): not in INF-05 | REQUIRES REVIEW (Phase 1): not in INF-06 |
| Code the factory must own | Claim function, worker loop, LISTEN wake-up, lease renewal; reaper already specified (07 §6) | Adapter layer + any parts disabled | Adapter layer + any parts disabled |
| Version floors | None beyond the PostgreSQL major chosen in 04 §1.9 | PostgreSQL 13+, Python ≥ 3.10 (INF-05) | PostgreSQL 14+, Python ≥ 3.11 (INF-06) |
| Licence | Own code | MIT (INF-05) | MIT (INF-06) |
| Redis + Celery (§3.2a fallback) | Not considered further: adds resident services, which §1 asks to avoid; no requirement found that a Postgres queue cannot meet | — | — |

**Logical consequence of constraints 1 + 2 (from 04, not from library internals).** If a library queries its own job table directly as `amw_app`, then either (a) that table is a FORCE RLS tenant table and the fetch, running before `app.org_id` is set, sees no rows (04 §3.2); or (b) the table is GLOBAL and holds the envelope, which 04 §1.2 forbids; or (c) the worker connects with `BYPASSRLS`, which 04 §3.1 forbids. A library therefore fits only if its fetch can be routed through `amw_queue_claim`. Whether that is possible is the open REQUIRES REVIEW item above.

## 3. Decision (Proposed)
1. **Option A for 3A:** the factory keeps `task_queue` (04 §5.4) as the only queue table and claims only through `amw_queue_claim` (04 §3.6). `amw_core.queue` (SOURCE_LAYOUT.md) provides:
   - **Enqueue** inside the same tenant transaction as T03 / T12 / T15 / T17 (insert one `READY` row; the partial unique index allows one live row per task, 04 §5.4).
   - **Claim** via `amw_queue_claim`, which sets `CLAIMED`, `claimed_by`, `claimed_at`, `lease_expires_at` in the same statement; then the worker opens a tenant transaction (`SET LOCAL app.org_id`, 04 §3.2) and applies T07.
   - **Wake-up** by LISTEN/NOTIFY. The NOTIFY payload carries no tenant content (identifiers-only rule of 04 §3.6); a missed notification is covered by a periodic claim attempt (interval is configuration, ESTIMATE until measured).
   - **Lease and heartbeat** per 07 §6 (`lease_ms`, `heartbeat_ms`); expired leases are found by `amw_expired_leases` (04 §3.6) and handled by the reaper.
   - **Retries, DLQ, replay, drain** are not implemented in the queue layer; they stay in the 03 §11 / 07 machinery. The queue holds no scheduling logic other than `scheduled_at` (not claimable before quota / window / backoff, 04 §5.4).
2. **Procrastinate / PgQueuer are not adopted for 3A.** A verification spike (Phase 1) reads each library's schema and fetch path. If one of them can (i) take `org_id` + FORCE RLS on its job table and (ii) fetch only through `amw_queue_claim`, and the remaining factory code would be smaller, this ADR is reopened (revisit trigger 1). Otherwise A stands.
3. **Redis / RabbitMQ / Celery: rejected for Tier 0** (§1, §3.2a).

## 4. Consequences
- **Positive.** One state authority (03 §11); tenancy enforced by the same RLS + composite keys as every other table (04 §1); the cross-tenant suite covers the queue like any table (04 §3.7, items 2, 3, 7); no extra resident process; workers on another machine need only DB access and configuration (§3.3 Migration).
- **Negative.** The factory owns and tests the claim function, worker loop and wake-up code. Mitigation: 27 §3 coverage floor for `amw_core` (≥ 90 %) and the failure-injection tests of 27 §9 (kill the render worker mid-render; DLQ replay creates no duplicate).
- **Version floors.** With option A, INF-05/INF-06 no longer set the PostgreSQL floor (04 §1.9) or the Python floor (27 §2). Those choices remain REQUIRES REVIEW (Phase 1) in their own documents; this ADR does not change them.
- **Throughput.** Queue throughput on the shared VPS is not measured. REQUIRES REVIEW (Phase 1): measure claim latency and queue-table bloat in the walking skeleton (27 §9); `retention.queue_done_ms` (04 §7) bounds table size.
- **Tests (27 §9 "Queue" row).** Claim with SKIP LOCKED under two concurrent workers returns disjoint rows; lease expiry → reaper → `INFRASTRUCTURE.WORKER_LOST` (07 §6); `amw_queue_claim` returns no content columns (04 §3.7.7); tenant B cannot see tenant A's queue rows (04 §3.7.2).

## 5. Status
**Proposed.** Owner approval needed before 3A code (D2: slice approval).

## 6. Revisit triggers
1. The Phase 1 spike shows Procrastinate or PgQueuer meets constraints 1–4 with less factory code.
2. Measured claim latency or queue load on PostgreSQL breaches an S5 threshold (05) in the pilot.
3. A Tier 3 dedicated deployment needs a queue that cannot be a table in the shared database. 04 §8.4 states that the same migrations build a dedicated stack, so the table design carries over.

## 7. Cited research IDs
INF-01, INF-05, INF-06, INF-11.
