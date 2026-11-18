# 10 — Deployment and Migration (own Compose project, isolation, ports, start/stop order, movable workers, dedicated stack, infrastructure by tier)

| Field | Value |
|---|---|
| Status | **Draft - documentation**. Software: **Planned** (nothing in this document is implemented, deployed or measured) |
| Owner agent / service | Agent 01 (orchestrator, deployment configuration and worker registration) with S5 Infrastructure Intelligence (`s05_infrastructure_intelligence`, owner Agent 01; 02_AGENT_REGISTRY.md) and S6 Security & Audit (secret delivery, hardening). Slice and limit values are owned by 05_RESOURCE_MANAGEMENT.md; this document owns where and how the pieces are deployed and moved |
| Depends on | MASTER_DIRECTIVE.md §1 (Server, Deployment isolation, Isolation mechanism, Queue, Heavy work, Production window), §1C.1 (dedicated option), §1C.14, §1C.15, §3.2a (Docker Compose deployment, storage, monitoring), §3.3 (Migration); 00b_TECHNICAL_FEASIBILITY.md §2.1, §2.2; GLOSSARY_AND_IDS.md §4, §6.6, §6.20; 03_COMMUNICATION_STANDARD.md §11; 04_DATABASE_ARCHITECTURE.md §3.1, §3.6, §5.4, §7, §8; 05_RESOURCE_MANAGEMENT.md; 07_FAILURE_MANAGEMENT.md §2, §8; 08_SECURITY.md §3; 3A_SLICE_SPEC.md §6, §7; 01_MASTER_ARCHITECTURE.md §4; SOURCE_LAYOUT.md; ADR-001, ADR-005, ADR-012; KNOWLEDGE_LIBRARY_PLAN.md and ADR-013 (knowledge collections, by name only) |
| Directive sections covered | §1 Server; §1 Deployment isolation; §1 Isolation mechanism; §1 Heavy work; §1 Production window; §1C.1 (premium dedicated option); §1C.14 (infrastructure by tier); §1C.15 (tier gates); §3.2a (Docker Compose deployment, storage behind S3-compatible interface, off-server backup, lightweight monitoring); §3.3 (Migration); owner decisions D1 (secrets, spend limits, render never in market hours, no upload/OAuth in 3A) and D2 |
| Research IDs | INF-01, INF-02, INF-03, INF-04, INF-05, INF-06, INF-07, INF-08, INF-09 (by reference) |
| MVP scope | **3A**: the factory's own Compose project (development environment first), env-driven configuration, secrets through the environment's secret mechanism, start/stop order, movable render worker by configuration, no inbound network exposure. **3B**: first VPS night-window run (only after the gates of §12), measured values replace every placeholder, backup destination configured. **3C**: scheduler-driven start/stop, dashboard and API exposure (reverse proxy, owner-approved), remote worker path, object-storage backend on trigger. |
| Enterprise tier | **Tier 0** shared VPS under slice caps. **Tier 1** own server (or render-only worker plus client data) before the first external client (§1C.14, recommendation only, rule 8). **Tier 2** per-tenant quotas on that server. **Tier 3** dedicated single-tenant stack and dedicated workers (`workers.dedicated_org_id`). |

> **Rules for this document.** (1) Documentation only: no Compose file, systemd unit, env file or script is written here; those are 3A build deliverables under `deploy/` (SOURCE_LAYOUT.md). (2) No value in this document was measured: the VPS audit (A1, 00_REPO_AND_SERVER_AUDIT.md) has not been received. Every limit, weight, path size and timing reads **"REQUIRES REVIEW (Phase 1): VPS measurement"** or is marked ESTIMATE. (3) This repository is PUBLIC: no host names, addresses, ports in use, credentials, existing-app names or server details appear here. (4) The factory never modifies, restarts or removes anything that is not its own (§1). (5) Owner rule A.2: nothing is assumed from code defaults; unknown live settings are written as unknown.

---

## 1. Purpose and boundary [3A / 3B / 3C · Tier 0-3]

**What this document defines.** The deployment unit (one explicit Compose project under `/opt/amw-media-factory/`), what it owns, how it is isolated from the existing apps on the shared server, how ports are chosen, when (and only when) a reverse proxy is touched, the order in which things start and stop, how configuration and secrets reach each process, how a worker moves to another machine, how a single-tenant stack is deployed from the same code, and the infrastructure recommendation by tier.

**What it does not define.** Limit values and slice weights (05_RESOURCE_MANAGEMENT.md); the night schedule itself (06_NIGHT_SCHEDULING.md, planned); backup tool, destination, RPO/RTO (ADR-005 §3.4, 12_DISASTER_RECOVERY.md, planned); the secret-delivery mechanism (08_SECURITY.md §3.1 rule 1: an ADR, open); monitoring tool (ADR-006, not started); table definitions (04); queue library (ADR-001).

**Phase placement (owner decision D1).**

| Phase | Deployment content |
|---|---|
| **3A** | Development-environment deployment of the same Compose project; the minimal core (database, orchestrator, AI worker, render worker, operator tool). **No inbound network exposure, no reverse proxy, no Google OAuth, no upload** (D1). Render worker is the movable one (ADR-012). |
| **3B** | The first run on the shared VPS in the night window, only after the gates of §12 pass; backup destination configured before the first kept output (ADR-005 §3.4). |
| **3C** | Scheduler-driven night window, API and dashboard (reverse-proxy decision, §7), publish worker, remote-worker path, object-storage backend when its trigger fires, per-tier steps of §13. |

## 2. Facts and what is not known [3A · Tier 0]

| Item | Fact or status | Source |
|---|---|---|
| Server plan the owner reports | Matches Hostinger KVM 2: 2 vCPU / 8 GB / 100 GB NVMe / 8 TB, ₹779/mo on a 24-month promotional term, renews ₹1,199/mo (excl. GST) | INF-01 (VERIFIED, page at check time) |
| Operating system | Ubuntu 26.04 LTS, released 2026-04-23, standard support to May 2031; **cgroup v2 only** (cgroup v1 removed) | INF-02 (VERIFIED) |
| systemd resource control | `CPUWeight=`, `IOWeight=`, `MemoryHigh=`, `MemoryMax=`, `TasksMax=`, `CPUQuota=`, `Slice=` documented | INF-03 (VERIFIED) |
| Compose limits and slice placement | Fields `cpus`, `mem_limit`, `pids_limit`, `cgroup_parent`, `deploy.resources.limits` documented; the docs **do not state** that deploy limits apply under plain `docker compose up`, nor that `cgroup_parent` can target a systemd slice. Docker Engine 29.10.0 (2026-11-16). Compose version not obtained | INF-04 (**PARTIAL**) |
| Real VPS free RAM/CPU/disk, swap, existing apps' peak, ports in use, existing proxy | **Not known.** Audit Part C pending | A1; REQUIRES REVIEW (Phase 1): VPS measurement |
| Compose project-name mechanism (`name` key or `-p` option), network and volume naming behaviour, healthcheck and `depends_on` conditions, stop-timeout fields | Not in RESEARCH_LOG.md | REQUIRES REVIEW (Phase 1): official Docker Compose source entry before the Compose file is written |
| Official figures for monitoring footprint | None (INF-07: no RAM figure; INF-08: Grafana 512 MB evaluation minimum only) | measure before ADR-006 |

Consequence: this document fixes **rules and structure**; every number is configuration filled in from measurement (05 §8).

## 3. Isolation rules (directive §1, binding) [3A · Tier 0]

| # | Rule | How it is met | Checked by |
|---|---|---|---|
| I1 | Everything lives under `/opt/amw-media-factory/` | One root directory; nothing of the factory is placed elsewhere on the host except its systemd units and the factory slice definition (§4.2) | Deployment review (§14 DT-1) |
| I2 | Own Compose project with an **explicit project name** | The name is set explicitly (never derived from a directory name); the mechanism is confirmed against the official Compose docs (§2). Every operational command in runbooks passes the project name; none runs without it | DT-2 |
| I3 | Own network, volumes, database, env file, logs, storage, backups | See the ownership table in §4 | DT-1, DT-2 |
| I4 | **Never modify, restart or remove** existing Compose projects, containers, volumes, networks, databases or reverse-proxy configuration | The factory's tooling addresses only objects labelled with the factory project; commands that act on "all containers", "all volumes", `prune`-style cleanup of the whole host, or restart of the Docker daemon are **forbidden** in factory runbooks. Docker daemon restarts are the owner's decision, not a factory step | DT-3; code review rule in 27 §3 |
| I5 | **Discover ports in use before choosing any**; bind internal services to localhost or the private Compose network | §6 | DT-4 |
| I6 | CPU and memory limits on **every container** | 05 §5.1; a container with no reviewed limit does not start on the VPS (fail closed) | DT-5 (RM-T1) |
| I7 | Own systemd slice (or equivalent cgroup v2 limits) with low `CPUWeight`/`IOWeight`, `MemoryHigh`/`MemoryMax`, `TasksMax` | 05 §4; slice placement is proved, not assumed (INF-04) | RM-T1 (05 §5.3) |
| I8 | Reverse-proxy integration only after inspecting the existing config and with owner approval | §7 | DT-6 |
| I9 | Read-only on the host until the owner approves the first VPS run | The audit script is read-only (rule 2); the first write on the VPS is the owner-approved creation of the factory's own directory, project and slice (§12) | owner approval record |
| I10 | Never touch the trading app or BagMitra | No factory container mounts their volumes, joins their networks, reads their databases or files, or uses their credentials | DT-3 |

## 4. Ownership map of the factory deployment [3A · Tier 0]

Names are **design proposals**; they are configuration, not contracts. No host path other than the directive's root is written here.

| Object | Factory-owned form | Notes |
|---|---|---|
| Root directory | `/opt/amw-media-factory/` | Directive §1. Contains only factory files |
| Compose project | one project, explicit name | I2 |
| Network | one private Compose network (internal only; no published ports in 3A) | No attachment to any existing network (I4) |
| Volumes | named volumes owned by the project: database data, blob storage root (local backend, ADR-005 §3.1), logs, scratch/temp for renders, backup staging | Separate volumes so disk admission (05 §6.4) can measure each; scratch is never counted as output (ADR-005 §3.3) |
| Database | the factory's own PostgreSQL instance in the project (INF-05/06 queues live inside it, ADR-001) | Not the existing apps' database servers. Roles per 04 §3.1: `amw_app`, `amw_readonly`, `amw_migrator` (deploy only), `amw_publisher` and `amw_auth` when they exist |
| Env file | one file of **names and non-secret values**, plus secrets injected per service by the secret mechanism (§8) | `deploy/env.example` holds names only (SOURCE_LAYOUT.md) |
| Logs | JSON logs to the factory's log volume with rotation; correlation IDs and `org_id` on every line (27 §7.3.6); no secrets, chunk text or personal data | Rotation size/age: REQUIRES REVIEW (Phase 1): VPS measurement of free disk |
| Storage | `amw-blob://` tenant-prefixed, write-once, SHA-256 (ADR-005) | Local disk first |
| Backups | staging inside the project; destination **outside the machine** (ADR-005 §3.4) | Destination, tool, encryption, price: REQUIRES REVIEW (Phase 1) and owner purchase decision (rule 8) |
| systemd | factory slice units (`amw-factory.slice` and children, 05 §4.1) and, if used, units that start the project | Slice names are configuration |

Planned repository placement (SOURCE_LAYOUT.md): `deploy/compose/` (project definition), `deploy/systemd/` (slice), `deploy/env.example` (names only). Created in the 3A build, not now.

## 5. Compose project design [3A / 3C · Tier 0]

### 5.1 Services (from 01_MASTER_ARCHITECTURE.md §4.2; not redefined)

| Service | Phase | `resource_class` / capabilities (GLOSSARY §6.6, §6.20) | Exposed? | Slice (05 §4.1) | Holds secrets |
|---|---|---|---|---|---|
| `postgres` (factory's own) | 3A | data plane | No (private network only) | core | its own admin credential, via secret mechanism |
| `migrate` (one-shot job, not a service) | 3A | deploy only | No | core | `amw_migrator` credential, **never a running service** (08 §3.2) |
| `orchestrator` | 3A minimal | LIGHT | No | core | DB (`amw_app`) |
| `ai_worker` | 3A | AI_IO; `llm`, `tts`, `stock_search`, `image_gen` when an adapter is live; `file_delivery` in 3A by provisional default (01 §4.2 note 1) | No (outbound to providers only) | jobs | provider keys of the adapters it runs, DB, storage |
| `render_worker` | 3A | HEAVY_CPU; `render_ffmpeg`, `media_probe` | No | render | **DB and storage only; no provider key** (3A_SLICE_SPEC §6.4) |
| `scheduler` | 3C (3A: guards only, inside admission) | LIGHT | No | core | DB |
| `api` | 3C | — | Only through the §7 decision | core | DB, auth |
| `dashboard` | 3C | — | Only through the §7 decision | core | none |
| `publish_worker` | 3C | PUBLISH; `publish_youtube`, `file_delivery` | No (outbound only) | jobs | `amw_publisher` credential and OAuth data keys (08 §6) |
| `monitoring` | 3A: metrics endpoint + JSON logs; agent 3C (ADR-006 not started) | none | No (localhost/private network) | core | none |
| `backup` job | before first kept run | LIGHT | No | core | backup destination credential |

### 5.2 Per-service rules

1. **Limits.** Every service declares CPU, memory and pids limits (INF-04 field set) from configuration; values come from the measured walking-skeleton report (05 §5.1, §8.4). No default exists for an unmeasured container on the VPS (fail closed); in the development environment limits are advisory (05 §5.1).
2. **Slice placement.** `cgroup_parent` (or the fallback chosen if RM-T1 fails, 05 §5.4) places each container in its slice. Until RM-T1 passes, the factory does not run on the shared VPS (05 §5.2).
3. **Hardening** (08): non-root user, read-only root filesystem where possible, no privileged mode, no host network mode, no Docker socket mounted, no bind mount of host paths outside the factory root.
4. **Images.** Same image and pinned runtime on every placement (ADR-012 §3.1; 27 §2). Image tags are pinned; floating tags are not used. Image scan is a CI gate (27 §5; 08 §10).
5. **Health.** Every long-lived service exposes a health signal used by start order (§9) and by S5. Workers heartbeat into `workers.heartbeat_at` (04 §5.4); a stale heartbeat triggers `INFRASTRUCTURE.WORKER_LOST` handling (07 §2).
6. **Restart policy.** A container that exits unexpectedly is restarted by the project's restart policy **only for services whose restart is safe** (workers are safe: leases expire and the reaper resumes from checkpoints, 07 §8.1). `render_worker` is not auto-restarted outside an open window (guards of §9.3).
7. **Resource-class queues.** The AI worker and the render worker claim from different queues (`ai`, `render`; 04 §5.4), so the render worker can be absent without blocking AI-only tasks.
8. **Process model in 3A.** Whether the light worker is merged with the AI worker is decided in ADR-001 / SOURCE_LAYOUT (05 §5.1); this document is neutral.

## 6. Port discovery rules [3A / 3B · Tier 0]

The directive requires: discover ports in use before choosing any; bind internal services to localhost or the private Compose network.

1. **Default: publish nothing.** In 3A no factory service needs an inbound port: the operator tool (run by the assistant, not by the owner, D5) reaches the database over the project's private network as role `amw_operator` (01 §4.2 "Operator tool"). Provider calls are outbound only.
2. **Discovery before any publish.** A port is published to the host only when a documented need exists (3C: API/dashboard; remote worker path, §10). Before choosing one, a **read-only** listing of listening sockets on the host and of the ports published by existing containers is taken (the read-only audit script, `audit/vps_readonly_audit.sh`, is the tool; the output is stored outside git because it is server detail).
3. **Selection rules.** Choose a port that is (a) absent from the listing, (b) outside any range the existing apps use, (c) not a well-known port, (d) recorded in the factory's configuration (not in the public docs). A port conflict at start is a failed deployment (`PERMANENT.CONFIG_INVALID`, 07 §2), never a reason to stop or reconfigure another app.
4. **Binding.** Any published port binds to the **loopback address** of the host (or to a private interface the owner approves), never to all interfaces. The firewall is not modified by the factory (an existing host firewall is an owner-controlled item); a firewall change is a recommendation to the owner.
5. **Re-check.** The listing is repeated at every deployment that changes published ports and after any host restart, because other apps may have moved.
6. **No port numbers in this repository.** Chosen ports live in the host's configuration only (public-repo rule, 08 §11).
7. REQUIRES REVIEW (Phase 1): VPS measurement — the current listening-socket picture (A1).

## 7. Reverse proxy [3C · Tier 0 → Tier 1]

| Step | Rule |
|---|---|
| 1 | **Not needed in 3A and 3B.** No HTTP surface exists (§6.1). |
| 2 | Needed only when the API/dashboard (S8) or the client portal must be reached from a browser (3C; portal Tier 1/2). |
| 3 | Before any integration: **inspect** the existing proxy's configuration read-only (which software, how sites are declared, TLS handling, how an app is added without touching existing sites). Record the findings outside git. |
| 4 | **Owner approval** of the exact change is required before it is made (directive §1). The approval names the host name, the upstream (loopback port of §6), TLS source and the file to be added. |
| 5 | The change is **additive only**: a new, separate configuration unit for the factory; no edit to an existing site block, no restart of the existing proxy beyond what the owner approves, and a validated configuration test before any reload. |
| 6 | Alternatives that need **no** existing-proxy change (for example a reachability path that does not publish a port) are options to evaluate with the owner; none is chosen here. REQUIRES REVIEW (Phase 1): owner decision on how the dashboard is reached. |
| 7 | Authentication (08 §5.5), TLS and rate limits must exist before the dashboard is reachable from outside the machine. |
| 8 | On an own server (Tier 1+) the factory may run its own proxy inside its own project; the same rules apply to the host. |

## 8. Environment-driven configuration and secrets [3A · Tier 0]

1. **All variability is configuration** read only by `amw_core.config` (27 §7.3.1): providers, models, limits, window times, market-hours calendar, concurrency, retention, storage backend and root, queue names, worker capabilities and `max_concurrency`, DB endpoint, backup destination reference. No package reads environment variables directly.
2. **Three kinds of input.**

| Kind | Where it lives | Example classes (no values) |
|---|---|---|
| Non-secret configuration | env file / config files under the factory root; `deploy/env.example` lists names only | `resource_class` limits, window times, backend selector, worker `logical_name`, capability list |
| Secrets | **only** the environment's secret mechanism (D1; 08 §3.1), injected per service at start or mounted as a file | DB passwords per role, provider keys, backup credential, key-encryption key reference (3C) |
| Deployment profile | one configuration value that selects the placement (shared VPS, own server, dedicated tenant stack); the allowed set of values is **(pending CCR)** `deployment.profile` (see §17) | — |

3. **Secret scoping.** A secret reaches only the service that uses it (08 §3.1 rule 4): the render worker has no provider key; the orchestrator holds no provider key; `amw_migrator` is used only by the one-shot `migrate` job. No secret in a variable shared by all containers, no secret in logs, images, git or the database in clear text.
4. **Startup check.** Each service lists the secret names it requires; a missing or unreadable one fails startup with `PERMANENT.CONFIG_INVALID` (08 §3.1 rule 7); the value, its length and prefix are never printed.
5. **Spend limits first (D1, rule 8).** Provider keys are enabled for paid calls only after the owner has set spending limits at each provider; the cost ledger enforces the per-video budget and the total pilot budget and stops on breach (08 §3.4; 09). Deployment therefore has a precondition: keys are not injected into `ai_worker` until the owner confirms the provider-side limits (owner input A7).
6. **Concrete secret mechanism per target** (development environment, VPS): REQUIRES REVIEW (Phase 1): ADR for secret delivery (08 §3.1 rule 1). It blocks only a VPS run, not the development-environment default (3A_SLICE_SPEC §6.5). Nothing about the mechanism's host-level detail is recorded in this public repository.
7. **Configuration changes are audited** (05 §4.4 rule 6): a changed limit or window is a configuration change with an audit entry, never a code change.
8. **Time zones.** All timestamps in storage are UTC; window logic uses `Asia/Kolkata` and the quota day uses US Pacific (GLOSSARY §4; YT-03). The container time-zone setting never carries business meaning.

## 9. Start and stop order [3A / 3C · Tier 0]

### 9.1 Start order (dependencies first)

| Step | Action | Gate to continue |
|---|---|---|
| 0 | Preconditions: factory slice present and RM-T1 evidence current (VPS); secrets resolvable; free-disk admission threshold satisfied (05 §6.4) | any failure stops the start; nothing partial is left running |
| 1 | `postgres` | health check passes |
| 2 | `migrate` one-shot as `amw_migrator` (forward-only, checksummed, RLS policy in the same file, 04 §8) | exits success; catalogue check of RLS passes (04 §3.7.6). A failed migration leaves the services stopped |
| 3 | Seed data versioned with migrations (state-transition rules, platform rule packs, production types, 04 §8.3) | present |
| 4 | `orchestrator` (and `scheduler` in 3C) | health OK; reaper started so expired leases are recovered (07 §8) |
| 5 | Workers: `ai_worker` first, then `render_worker` (render only inside the guards of §9.3) | each registers in `workers` with its declared capabilities and `max_concurrency` and heartbeats |
| 6 | `api`, `dashboard` (3C) | health OK; reachable only per §7 |
| 7 | `monitoring` / metrics consumers; `backup` job schedule | signals visible to S5 |

### 9.2 Stop order (graceful; the reverse, with draining)

| Step | Action | Rule |
|---|---|---|
| 1 | Stop **admission** of new heavy work (scheduler or an operator flag); at the window end this is 06:30 (07 §8) | no new `HEAVY_CPU` claim |
| 2 | Request drain: set `workers.drain_requested_at` (04 §5.4); running tasks reach their next safe point and checkpoint (T09, `wait_reason = DRAIN`) | never killed mid-write (07 §8.1) |
| 3 | Stop `render_worker`, then `ai_worker`, once idle or checkpointed | service stop timeout **greater than** `limits.max_atomic_write_ms` (ADR-012 §3.3; value REQUIRES REVIEW (Phase 1)) |
| 4 | Stop `api`/`dashboard` (3C) | |
| 5 | Stop `orchestrator`/`scheduler`; the night report is written first (07 §8, 06) | state persisted |
| 6 | Run or confirm the backup job when planned | restore-test rules: ADR-005 §3.4 |
| 7 | Stop `postgres` last, with a clean shutdown | |

At 07:00 IST on the shared VPS, heavy workers stop gracefully; only the scheduler/monitor may stay, and only if its measured footprint is safe (directive §1). The daytime-stoppable group is the core slice per Q7 (05 §4.1).

### 9.3 Guards that bind start, not just run

1. **Market-hours guard (D1):** no `HEAVY_CPU` task starts during market hours on **any** placement; the calendar is configuration (ADR-012 §3.3; source REQUIRES REVIEW (Phase 1)). A render worker that is started during market hours stays idle; claims return no rows.
2. **Night-window guard (VPS placement only):** claims only 00:00–07:00 IST; no new `HEAVY_CPU` admission from 06:30; no task whose estimated remaining time exceeds the time left to 07:00.
3. **Host restart or crash:** services restart per §5.2 rule 6; leases expire; the reaper resumes from checkpoints at the next window (`INFRASTRUCTURE.HOST_RESTART`, `INFRASTRUCTURE.WORKER_LOST`, 07 §2).

### 9.4 Never during start/stop

No command on the host restarts, stops or reconfigures any non-factory container, the Docker daemon, or the proxy as part of a factory start/stop (I4).

## 10. Workers with declared capabilities moving to another machine [3A design · 3C exercise · Tier 0 → Tier 3]

### 10.1 Principle (directive §1 Heavy work, §3.3 Migration)

A worker is a **process with declared capabilities**, not a host. Moving it is **new configuration on the target machine, no code change** (ADR-012 §3.1). The worker registers itself in `workers` (04 §5.4) with: `logical_name` (e.g. `render-1`; no host names or addresses), `capabilities` (GLOSSARY §6.20), `resource_classes` (GLOSSARY §6.6), `max_concurrency` (configuration), `software_version`, heartbeat. It claims only through `amw_queue_claim` (ADR-001) and reads/writes blobs only through `amw_core.storage` (ADR-005).

| Worker | Capabilities it declares | Needs on a remote machine | Does **not** need |
|---|---|---|---|
| `render_worker` (movable first, ADR-012) | `render_ffmpeg`, `media_probe` | DB access, storage access, the pinned image, its limits | any provider key |
| `ai_worker` | `llm`, `tts`, `stock_search`, `image_gen` | DB, storage, the keys of its adapters | — |
| `publish_worker` (3C) | `publish_youtube`, `file_delivery` | DB as `amw_publisher`, storage, OAuth data keys | — |

### 10.2 Two access paths a remote worker needs (ADR-012 §4)

| Path | Problem | Options (none chosen) | Owner approval |
|---|---|---|---|
| Database | The factory DB is bound to the private Compose network / loopback (§6); a worker elsewhere cannot reach it | (a) an encrypted network path of the owner's choosing between the two machines, (b) a database endpoint on the own server when the whole core moves (Tier 1) | Yes: any host-network change (§7, directive §1) |
| Storage | The local-disk backend is not reachable from another machine | The S3-compatible backend (ADR-005 trigger 1) or an equivalent approved access path; atomic-publish and write-once semantics must be verified in the provider's official documentation (ADR-005 §3.2.3) | Yes: provider choice and spend (rule 8) |

REQUIRES REVIEW (Phase 1): both paths before any remote-worker option is exercised; neither is needed in 3A (development environment hosts the whole project).

Transport requirements regardless of option: encrypted in transit; least-privilege DB role (`amw_app`, never `amw_migrator`); credentials via the secret mechanism; a stable `logical_name` per worker; no inbound port opened on the worker machine.

### 10.3 Move procedure (render worker as the model)

| Step | Action |
|---|---|
| 1 | Decision recorded: the headroom rule of ADR-012 §1.1 failed, or Tier 1 requires it; the owner approves and purchases any server (rule 8) |
| 2 | Prepare the target: the same pinned image; configuration with `deployment.profile` (pending CCR), DB and storage endpoints, limits (05 §8 formula re-run on the new host), market-hours calendar; secrets injected for DB and storage only |
| 3 | Register under a **new** `logical_name` (never reuse a name still registered elsewhere) and let it heartbeat; confirm the capability set |
| 4 | Drain the old worker: set `drain_requested_at`; tasks checkpoint and the lease expires or is released cleanly (T09/T15; 07 §10) |
| 5 | Verify: a canary render task is claimed by the new worker; the output's SHA-256 is verified through `amw_core.storage`; `renders.content_sha256` stored (04 §5.18) |
| 6 | Retire the old registration (`workers.status`); stop and remove the old worker container (factory-owned objects only, I4) |
| 7 | Record the move in the audit log and the deployment record; update the headroom figures (05 §8) |

Rollback: re-enable the old worker with its registration; no data moved, because tasks and blobs were never owned by the worker.

### 10.4 What stays unchanged

The task contract, queue, state machine, checkpoints, cost ledger, tenancy and storage URIs do not change when a worker moves. The market-hours guard still applies; the night-window guard is a property of the **shared** server and becomes per-tenant configuration on a platform server (directive §1; 04 `plans` `production_window`, T1+).

## 11. Dedicated-stack option for a single tenant [Tier 3 design · built only when a paying client requires it, §1C.15]

Directive §1C.1: "same code deployed as a single-tenant stack (own DB/server) for clients who require it — enabled by the existing migration design, not a fork."

| Aspect | Rule |
|---|---|
| Code | The **same repository and images**. No fork, no tenant-specific branch (04 §8.4). |
| Database | A fresh database built by the **same migrations** (04 §8.4). RLS stays on; one organisation row exists. The platform's multi-tenant safeguards are not removed in a dedicated stack. |
| Compute | Own Compose project (same shape as §4) on its own server, or dedicated workers on shared infrastructure (`workers.dedicated_org_id`, 04 §5.4; non-null means the worker serves only that organisation). |
| Storage / backups / keys | Own storage root or bucket, own backup destination, own key-encryption key and secret set; nothing shared with other tenants. |
| Configuration | Production window becomes per-tenant configuration (`plans`/`production_window`, 04); the shared-VPS 00:00–07:00 window does not apply to a platform server (directive §1). |
| Compliance | The tenant's compliance profile still sits on top of the always-on platform gates; a dedicated stack cannot remove them (§1C.7). |
| Data-location statement and DPA | Per 22_DATA_PROTECTION.md (planned); REQUIRES REVIEW (Phase 1): data-location statement per hosting choice. |
| Upgrade path | A dedicated stack runs the same released version; upgrades follow §14 with the client's agreed maintenance window. |
| Move in/out | Export one tenant with `list_prefix` and per-tenant database export (ADR-005 §3.1; §1C.10); import into the dedicated database through the same schema. Tenant erasure from the shared stack only through the data-request workflow (04 §5.24). |
| Ownership | Whether the dedicated stack is operated by the platform owner or the client: REQUIRES REVIEW (Phase 1): commercial decision, not a technical one. |

Gate: Tier 3 (enterprise, §1C.15). Nothing in 3A–3C builds it; 3A–3C only keep the design from preventing it (no hard-coded host, tenant or provider; migrations reproducible from empty).

## 12. Gates before the first run on the shared VPS [3A / 3B · Tier 0]

All must hold (3A_SLICE_SPEC §7; ADR-012 §3.2; 05 §5.2):

1. A1 audit output received and the headroom formula `available_for_factory = measured_total − peak(trading app + BagMitra + OS) − safety_margin` evaluated on measured figures (00b §2.2; 05 §8). If the factory's measured peak need exceeds it, move **only the render worker** (ADR-012 option C): a recommendation, not a purchase.
2. RM-T1 (05 §5.3) green: slice placement and limits are real (INF-04).
3. Port discovery done (§6); no conflict.
4. The secret-delivery ADR resolved for the VPS (08 §3.1 rule 1) and owner-set provider limits confirmed (D1).
5. Backup destination configured before the first output the owner must keep (ADR-005 §3.4).
6. The owner approves the first VPS run, in writing, naming what will be created (directory, project, slice, volumes).

Until then 3A runs in the development environment (D1).

## 13. Infrastructure plan by tier [recommendation only; rule 8; no purchase]

| Tier | Placement | Trigger | What changes (recommendation) |
|---|---|---|---|
| **0** (now) | The owner's own channel on the **existing shared VPS** within §1 limits; 3A in the development environment | — | Own Compose project, own slice, night window, market-hours guard, local-disk storage, off-server backup, lightweight monitoring (ADR-006 pending). |
| **1** | **Before the first external client:** move the platform, or at minimum its render workers and client data, to **its own server**, because client SLAs must not depend on capacity shared with the trading app and BagMitra (§1C.14). Prefer adding a cheap render-only worker over one expensive large server; size from **measured** per-video resource use | First paying managed-service client (§1C.15 Tier 1) | Re-run 05 §8 on the new host; per-tenant production window (04 `plans`); object-storage backend likely needed (ADR-005 trigger 1); backup restore test per tenant (§1C.11); Prometheus + Grafana become an option on a server with room for them (INF-08: Grafana alone states 512 MB minimum). |
| **2** | Same server(s); more workers by configuration | Self-serve clients | Per-tenant quotas and fair sharing exercised (05 §7); billing/metering. |
| **3** | Dedicated stack or dedicated workers per tenant (§11) | Enterprise contract | Separate stack per client; formal SLA only after pen-test and measured RTO/RPO (§1C.11, §1C.13). |

A single shared VPS cannot honestly promise high availability (§1C.11); no SLA is published at Tier 0.

### 13.1 Hostinger plan facts (INF-01, VERIFIED at check time; promotional prices excl. GST)

| Plan | vCPU | RAM | Storage | Bandwidth | Price | Renewal |
|---|---|---|---|---|---|---|
| KVM 1 | 1 | 4 GB | 50 GB NVMe | 4 TB | ₹599/mo | not stated in the log |
| **KVM 2** (matches the owner-reported spec) | 2 | 8 GB | 100 GB NVMe | 8 TB | ₹779/mo (24-month term) | ₹1,199/mo |
| KVM 4 | 4 | 16 GB | 200 GB | 16 TB | ₹1,099/mo | ₹2,399/mo |
| KVM 8 | 8 | 32 GB | 400 GB | 32 TB | ₹2,199/mo | ₹4,399/mo |

Use in this plan: these figures feed the "separate render-only worker / own server" **options** (ADR-012 option C; 00b) as cost context only. They are promotional prices on the page at check time; **re-check before any decision**. Nothing is purchased by this document; the owner decides and purchases (rule 8). Whether a given plan is "enough" is **not** concluded here: it depends on the measured per-video need (REQUIRES REVIEW (Phase 1): walking-skeleton and pilot measurement).

## 14. Migration [3A / 3B / 3C · Tier 0-3]

"Migration" covers three different things; they are kept apart.

### 14.1 Database schema migrations (04 §8)
Forward-only, ordered, checksummed, one transaction each, run as `amw_migrator` by the one-shot `migrate` job, never by a running service. Each new table ships with its RLS policy in the same file. Rollback of a schema change is a **new forward migration**, not a down-migration. Tool and version: REQUIRES REVIEW (Phase 1): record in RESEARCH_LOG.md (04 §8.1). Release rule: services of version N start only after migrations of version N have completed; a worker on another machine must be the same released version as the core (`workers.software_version`); a mismatch is refused at registration (REQUIRES REVIEW (Phase 1): enforcement point, orchestrator admission).

### 14.2 Deployment upgrades (new release on the same host)

| Step | Action |
|---|---|
| 1 | Announce stop of admission (§9.2 step 1); drain workers |
| 2 | Take a backup (DB logical dump + config; blobs are write-once and already in the backup set) |
| 3 | Pull the new pinned images; compare configuration names against `deploy/env.example` (a new required name is a documented change) |
| 4 | Run `migrate`; on failure stop and restore from step 2 |
| 5 | Start in §9.1 order; verify health, RM-T1 evidence still valid (limits unchanged), canary task |
| 6 | Keep the previous images until the canary passes; roll back by re-pointing to them when no incompatible migration was applied |

Upgrades run in a window the owner approves; on the shared VPS only inside the night window and never during market hours for any step that starts `HEAVY_CPU` work.

### 14.3 Host-to-host migration (shared VPS → own server, Tier 1)

| Step | Action |
|---|---|
| 1 | Provision the target (owner purchases, rule 8); install only what the factory needs; apply the same isolation structure (own project, slice or its equivalent, limits from 05 §8 on the new host) |
| 2 | Restore the **latest backup** into a scratch database/root on the target and verify: SHA-256 sample of blobs, audit-chain verification (ADR-005 §3.4; 08 §9.3) |
| 3 | Rehearse the cut-over once with a copy; measure the stop time (this sets RTO figures: REQUIRES REVIEW (Phase 1): owner sets RPO/RTO) |
| 4 | Cut over: stop admission and drain on the old host; final backup; restore on the target; start in §9.1 order; canary task |
| 5 | Re-register workers under the new configuration; retire old registrations (§10.3) |
| 6 | Keep the old deployment stopped (not deleted) for an owner-set period; then remove only factory-owned objects (I4) |
| 7 | Update the deployment record and the data-location statement (22) |

Blob storage backend change (local disk → S3-compatible): code above `amw_core.storage` does not change (ADR-005 §3.2); a copy-and-verify of every blob by SHA-256 precedes the switch, and tenant prefixes are preserved so one tenant can be moved alone.

### 14.4 Per-tenant export / move
Exports use `list_prefix` for blobs and tenant-scoped database export, never a whole-database copy into another tenant's stack (rule 9; ADR-005 §3.1).

## 15. Deployment acceptance tests [3A / 3B · Tier 0]

| ID | Test | Pass criterion |
|---|---|---|
| DT-1 | Ownership audit | Every file, volume and network created by the factory is under the factory root / project; nothing outside it was written |
| DT-2 | Project naming | All factory objects carry the explicit project name; removing the project removes only factory objects (verified in the development environment first) |
| DT-3 | Non-interference | Before/after listing of non-factory containers, volumes, networks, proxy files: identical (read-only comparison; owner rule A.12: evidence) |
| DT-4 | Port discipline | No published port in 3A; any later published port is loopback-bound and absent from the earlier discovery listing |
| DT-5 | Limits and placement | RM-T1 (05 §5.3) steps 1-10 |
| DT-6 | Proxy | No existing proxy file changed; the factory's added unit is separate and validated before reload |
| DT-7 | Start/stop | Start in §9.1 order from empty; stop in §9.2 order with a render checkpointed, not killed (27 §9 test 2); restart resumes from the checkpoint |
| DT-8 | Guards | No render starts in market hours (27 §9 test 6); claims outside the window return no rows on the VPS |
| DT-9 | Secrets | Missing secret fails startup with `PERMANENT.CONFIG_INVALID`; canary secret never appears in logs (08 §8.5); the render worker holds no provider key |
| DT-10 | Movable worker | A render worker started from configuration only (second environment) registers, claims a canary render and delivers a byte-identical output hash |
| DT-11 | Backup/restore | Restore into a scratch location verifies blob hashes and audit chain (ADR-005 §3.4) |
| DT-12 | Reproducible schema | An empty database built from the migrations passes the catalogue RLS check (the basis of the dedicated stack, §11) |

## 16. Scope summary

| Section | 3A | 3B | 3C | Tier |
|---|---|---|---|---|
| §3-§5 Isolation, ownership, Compose design | development environment; project structure and limits | VPS run after §12 | scheduler-driven | 0 |
| §6 Port discovery | no published ports | discovery before any publish | API/dashboard | 0 |
| §7 Reverse proxy | not needed | not needed | owner-approved, additive | 0 → 1 |
| §8 Configuration and secrets | yes | measured values replace placeholders | OAuth/KEK secrets | 0 |
| §9 Start/stop | manual, guards in admission | manual, night window | scheduler | 0 |
| §10 Movable workers | design; render worker movable by configuration | optional | exercised | 0 → 3 |
| §11 Dedicated stack | design only | — | — | 3 |
| §13 Tier plan | recommendation | recommendation | recommendation | 0-3 |
| §14 Migration | schema migrations, upgrades | backup/restore rehearsal | host move | 0 → 1 |

## 17. Contract requests (pending CCR; not edited into Wave A here)

| # | Needed | Proposed |
|---|---|---|
| 1 | A fixed value set for the deployment placement configuration key `deployment.profile` (pending CCR), so tools and runbooks name it identically | Values `shared_vps`, `own_server`, `dedicated_tenant`; documented as a configuration key (not a database enum), in GLOSSARY_AND_IDS.md |
| 2 | Registration check of worker software version against the core release (§14.1) | A rule in 03 §11 admission (T07 guard) or `workers` registration: refuse a worker whose `software_version` is incompatible; no new column (uses 04 §5.4 `software_version`) |

Both are listed in `audit/b2_unfiled_ccr_requests_shared.md` for the integrator to file (not yet in CONTRACT_CHANGE_REQUESTS.md). This document does not depend on them for 3A: the profile can be a free configuration string until the CCR is decided.

## 18. Open items (all REQUIRES REVIEW (Phase 1) unless stated)

1. VPS audit (A1): free resources, existing apps' peak, ports, swap, existing proxy software and layout, Docker and Compose versions.
2. Official Docker Compose source entry in RESEARCH_LOG.md: project name mechanism, volume/network naming, health and dependency ordering, stop timeout, restart policy.
3. Secret-delivery ADR for the VPS (08 §3.1 rule 1).
4. Backup destination, tool, encryption, frequency, RPO/RTO; owner purchase decision (ADR-005 §3.4; 12_DISASTER_RECOVERY.md).
5. Remote-worker DB and storage paths (ADR-012 §4); object-storage provider entry.
6. Dashboard reachability method and reverse-proxy decision (§7).
7. Market-hours calendar source (ADR-012 §3.3; owner of the key: 06_NIGHT_SCHEDULING.md).
8. Migration tool and version (04 §8.1).
9. Log rotation sizes and age from measured disk.
10. Owner-approved tolerance of contention on existing apps (05 §5.3 step 10).
11. Book and knowledge collections (`pd_books`, `owner_strategies_notes`, `owner_books`; provisional defaults Q34-Q37): KNOWLEDGE_LIBRARY_PLAN.md section 5 was not present in this tree when this document was written, so the locations are **not** documented here. Rule for deployment only: the collections are mounted **read-only** into the ingestion job as a configured source path outside git, never copied into this repository or into images, and never published through any port; the real locations stay in configuration and the owner's private notes (public-repo rule). REQUIRES REVIEW (Phase 1): align with that section once it exists.

## 19. Revisit triggers

1. A1 audit received (evaluate §2, §6, §12 on real figures).
2. RM-T1 fails (05 §5.4 fallbacks change §3 I7 and §5).
3. Walking-skeleton or pilot measurements exceed `available_for_factory` (§10 move).
4. First external client (Tier 1, §13).
5. A dedicated-stack request (§11).
6. ADR-006 (monitoring) or the secret-delivery ADR is decided.

## 20. Cited research IDs
INF-01, INF-02, INF-03, INF-04, INF-05, INF-06, INF-07, INF-08, INF-09.
