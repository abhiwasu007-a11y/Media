# ADR-012 — Render worker placement: development environment or VPS night window; movable worker; never in market hours

| Field | Value |
|---|---|
| Status | **Proposed** (documentation). Software: **Planned** |
| Decider | Owner (Abhi). Any new server is a recommendation only; the owner decides and purchases (rule 8) |
| Depends on | 00b_TECHNICAL_FEASIBILITY.md §2.1, §2.2; 04_DATABASE_ARCHITECTURE.md §5.4 (`task_queue`, `workers`), §5.18 (`renders`); 03_COMMUNICATION_STANDARD.md §11 (T07, T09, T15); 07_FAILURE_MANAGEMENT.md §2, §6, §8, §10; GLOSSARY_AND_IDS.md §4, §6.3, §6.6, §6.20; 24_PRODUCTION_TYPES.md (`agent_10.render`, `agent_10.subtitles`, `agent_10.technical_qc` = `HEAVY_CPU`); 27_ENGINEERING_STANDARDS.md §9; ADR-001; ADR-005 |
| Directive sections covered | §1 Heavy work (FFmpeg as a separately configurable worker that can move without code change; do not assume the shared VPS can render at scale), §1 Deployment isolation and Isolation mechanism, §1 Production window; §3.2a; §3.3 Migration; §1C.14 (infrastructure by tier); owner decision D1 (Rendering) |
| Research IDs | INF-01, INF-02, INF-03, INF-04, INF-09 |
| MVP scope | **3A**: movable worker, development-environment placement, market-hours guard, night-window guard. **3A/3B (conditional)**: VPS night-window placement after the headroom rule passes. **3C**: separate render server (if the rule fails), scheduler hardening. |
| Enterprise tier | Tier 0 dev environment / shared VPS → Tier 1 own server or render-only worker before the first external client (§1C.14) → Tier 3 dedicated workers per tenant (`workers.dedicated_org_id`, 04 §5.4) |

## 1. Context
- The render worker (FFmpeg) is the CPU-heavy component and "the main risk on 2 vCPU" (00b §2.1). The shared server is a KVM 2 plan: 2 vCPU / 8 GB / 100 GB NVMe (INF-01), Ubuntu 26.04 with cgroup v2 only (INF-02).
- Isolation tools: systemd `CPUWeight=`, `IOWeight=`, `MemoryHigh=`, `MemoryMax=`, `TasksMax=`, `CPUQuota=`, `Slice=` (INF-03). Compose limits (`cpus`, `mem_limit`, `pids_limit`, `cgroup_parent`) are documented, but the docs do not state that deploy limits apply under plain `docker compose up` nor that `cgroup_parent` can target a systemd slice (INF-04, PARTIAL) → both layers must be proved by test at build (27 §9 "Isolation" row).
- Technical QC runs on stock FFmpeg filters (`silencedetect`, `blackdetect`, `freezedetect`, `ebur128`; INF-09) and is also `HEAVY_CPU` (24 §7.1 stage table: `s10_render`, `s10_subs`, `s10_qc`).
- **Owner decision D1 (binding):** rendering happens in the development environment, or in the VPS night window under the §1 limits. **Never during market hours.** 27 §9 acceptance test 6: no render starts during market hours when run on the VPS.
- Night window: 00:00–07:00 `Asia/Kolkata` while sharing the server (GLOSSARY §4); drain from 06:30, graceful stop at 07:00 (07 §8).
- No resource figure of the VPS or of a render is measured yet: VPS audit pending (A1, 00_REPO_AND_SERVER_AUDIT.md), per-component RAM/CPU REQUIRES REVIEW (Phase 1) (00b §2.1).

### 1.1 Headroom rule (00b §2.2, binding formula)
```
available_for_factory = measured_total − peak(trading app + BagMitra + OS) − safety_margin
```
- `measured_total`, `peak(...)`: REQUIRES REVIEW (Phase 1) — VPS audit, 24 h sampling including the 00:00–07:00 IST window.
- `safety_margin`: configuration, proposed in 05_RESOURCE_MANAGEMENT.md.
- Rule: if the factory's measured peak need (walking skeleton) ≤ `available_for_factory` inside the night window → shared VPS under slice caps; otherwise move **only the render worker** to a separate small server.

## 2. Options considered (with evidence)

| Option | Fits D1 | Effect on existing apps | Cost | Evidence / open items |
|---|---|---|---|---|
| **A. Development environment** | Yes (D1 names it) | None: not on the shared VPS | Inside the existing development setup; no new purchase | Its CPU/RAM/disk are not measured. REQUIRES REVIEW (Phase 1): measure render time per minute of output there (24 §6 `render_ms`, MEASURED in pilot) |
| **B. Shared VPS, night window, slice caps** | Yes, only inside the window, only under §1 limits, never in market hours | Kernel favours existing apps (low `CPUWeight`/`IOWeight`) and hard caps (`MemoryMax`, `TasksMax`, `CPUQuota`) (INF-03) | None | Allowed only if the §1.1 headroom rule passes; cgroup placement proved by test (INF-04) |
| C. Separate render-only server | Yes (any time except market hours, per the guard below) | None | INF-01: KVM 1 ₹599/mo or KVM 2 ₹779/mo, promotional 24-month prices, excl. GST; re-check before any decision | Recommendation only (rule 8). Needs remote DB + storage access (§4) |
| D. Render in daytime on the shared VPS | **No** (D1, §1 window) | Competes with the trading app | — | Rejected |
| E. External render service | Not proposed by the directive (§1 keeps FFmpeg as own worker) | None | Unknown | Not researched; not considered (owner rule A.5) |

## 3. Decision (Proposed)

### 3.1 One movable worker, placement by configuration
- `workers/render_worker/` (SOURCE_LAYOUT.md) is a separate process/container. It registers in `workers` (04 §5.4) with a `logical_name` such as `render-1` (no host names or addresses), `capabilities` ⊇ {`render_ffmpeg`, `media_probe`} (GLOSSARY §6.20), `resource_classes` = {`HEAVY_CPU`} (GLOSSARY §6.6) and `max_concurrency` from configuration (start at 1, design default, ESTIMATE, until measured).
- It claims only through `amw_queue_claim` (ADR-001), reads/writes blobs only through `amw_core.storage` (ADR-005), and reads DB URL, storage backend and limits from configuration and the environment's secret mechanism (D1). Moving it = new configuration on the target machine, no code change (§1 Heavy work, §3.3 Migration).
- Same image and pinned runtime on every placement (27 §2 "Why pin").

### 3.2 Placement by phase
| Phase | Placement | Condition |
|---|---|---|
| 3A | **A. Development environment** (default) | Owner-set provider limits and secrets in place (D1); market-hours guard on |
| 3A / 3B on the VPS | **B. Shared VPS, night window** | A1 audit received; §1.1 rule passes with measured skeleton figures; cgroup/slice placement test green (INF-04, 27 §9); owner approves the first VPS run |
| If §1.1 fails | **C. Separate render-only server** | Owner decision and purchase (rule 8); ADR-005 object-storage backend or an approved access path in place |
| Before the first external client | Own server for the platform, or at least render workers and client data (§1C.14) | Tier 1 gate |

### 3.3 Time guards (admission, T07)
Admission (03 §11 T07 guard "admission allows (window …)") refuses to let a render worker claim, and `scheduled_at` (04 §5.4) keeps `HEAVY_CPU` rows unclaimable, unless **both** guards allow:
1. **Market-hours guard (D1):** no `HEAVY_CPU` task starts during market hours. The market-hours calendar is operational configuration (GLOSSARY §4: only operational settings are time-based). **REQUIRES REVIEW (Phase 1): record the official exchange session hours and holiday calendar source as a RESEARCH_LOG entry; 06_NIGHT_SCHEDULING.md owns the configuration key.** Provisional default: the guard is enforced on **every** placement, including the development environment (the stricter reading of D1; 27 §9 test 6 tests it on the VPS).
2. **Night-window guard (VPS placement only):** claims only inside 00:00–07:00 IST; from 06:30 no new `HEAVY_CPU` admission and no task whose estimated remaining time exceeds the time left to 07:00; at 07:00 graceful stop (07 §8.2–8.3). Interrupted renders checkpoint (T09, `wait_reason = DRAIN`) and resume next window (T15; 07 §10).
- A render already running when a guard closes follows the drain path above (checkpoint at the next safe point); it is never killed mid-write (07 §8.1, service stop timeout > `limits.max_atomic_write_ms`).

### 3.4 Limits on the VPS
Every factory container carries its own CPU/memory/pids limits **and** runs under the factory systemd slice with low `CPUWeight`/`IOWeight`, `MemoryHigh`/`MemoryMax`, `TasksMax` (§1, INF-03, INF-04). Values are configuration, set from measurement (05); none is fixed in this ADR.

## 4. Consequences
- **Positive.** D1 is met by construction (two independent guards); existing apps are protected by both the window and the kernel caps; the decision to buy a server is driven by a measured formula, not by assumption (§1, 00b §2.2).
- **Remote placement needs two access paths.** (a) Database: internal services bind to localhost or the private Compose network (§1 Deployment isolation), so a worker on another machine needs an approved, encrypted network path — design in 10_DEPLOYMENT_AND_MIGRATION.md / 08; reverse-proxy or network changes only with owner approval (§1). (b) Storage: the local-disk backend is not reachable from another machine; ADR-005 trigger 1 then requires the object-storage backend or an equivalent path. Both: **REQUIRES REVIEW (Phase 1)** before option C.
- **Throughput limit.** On option B the factory renders only inside the window minus drain; videos per night is unknown until measured (24 §6 `render_ms`, MEASURED in pilot). REQUIRES REVIEW (Phase 1).
- **Failure handling** unchanged from 07: `RESOURCE.RENDER_CRASH` / `RESOURCE.OOM` retry from checkpoint; `INFRASTRUCTURE.WORKER_LOST` via the reaper; kill-mid-render acceptance test (27 §9 test 2).
- **Tests.** 27 §9 tests 2 and 6; cgroup files read by the acceptance test (INF-04); a claim attempt outside the window or inside market hours returns no rows; a render with remaining-time estimate beyond 07:00 is not admitted after 06:30.

## 5. Status
**Proposed.**

## 6. Revisit triggers
1. A1 VPS audit arrives → evaluate §1.1 with real figures.
2. Walking-skeleton or pilot measurements show the render need exceeds `available_for_factory`, or S5 reports contention with existing apps.
3. First external client (Tier 1, §1C.14).
4. Measured renders per night do not meet the owner's production target (05/06).

## 7. Cited research IDs
INF-01, INF-02, INF-03, INF-04, INF-09.
