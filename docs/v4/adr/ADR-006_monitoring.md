# ADR-006 — Monitoring: lightweight agent + factory metrics endpoint on the shared VPS vs Prometheus + Grafana on a dedicated server; measure before choosing

> **Integrator status (lane B2-1, 2026-11-18).** B-2 draft aligned with main: no upload and no Google OAuth in 3A (D1); the owner works from chat and has no CLI (D5/R14; decisions are recorded by the operator as `OWNER_CHAT_OPERATOR` evidence with a review code, CCR-010/CCR-100); the licensed music source is an open owner decision (D6); the repository is becoming private (D7). Facts without a `RESEARCH_LOG.md` ID carry the label `UNLOGGED` and are **not citable**: each is `REQUIRES REVIEW (Phase 1): log entry (official URL + date)`. Names that no Wave A contract defines are marked `(unfiled CCR)` and listed in `audit/b2_unfiled_ccr_requests_adr_business.md`; this file changes no contract.

| Field | Value |
|---|---|
| Status | **Draft** (documentation). Software: **Planned** |
| Decider | Owner (Abhi). Any new server or paid service is a recommendation only; the owner decides and purchases (rule 8) |
| Owner agent / service | S5 Infrastructure Intelligence + resource monitor (`s05_infrastructure_intelligence`, owner Agent 01; MASTER_DIRECTIVE §3.2 S5). The monitoring tool itself is infrastructure, not an agent |
| Depends on | 05_RESOURCE_MANAGEMENT.md §9 (S5 signals, thresholds, §9.5 tool-neutral design), §4 limit layers, §12 (unfiled CCR); 00b_TECHNICAL_FEASIBILITY.md §2.1 (monitoring row), §2.2 (headroom rule); 07_FAILURE_MANAGEMENT.md §12 (metrics, all labelled `org_id`); GLOSSARY_AND_IDS.md (metric label `org_id`, platform-wide metrics `org_id="platform"`); 27_ENGINEERING_STANDARDS.md §7.3.6 (log fields), §9 (isolation acceptance tests); 08_SECURITY.md; 09_COST_AND_BUDGET.md; 3A_SLICE_SPEC.md (`observability` module); ADR-012 (render worker placement, option C trigger) |
| Directive sections covered | §3.2a (Monitoring: start lightweight plus the factory's own metrics endpoint; move to Prometheus/Grafana on a dedicated server); §3.2 S5 (RAM, CPU, load, disk, I/O, network, queue, API latency, worker health; recommendations at measured thresholds); §1 Deployment isolation and Isolation mechanism; §1 Production window (monitor may stay up after 07:00 only if its measured footprint is safe); §1C.11 (status page, health checks); §1C.14 (infrastructure by tier); rule 9 (tenant isolation); rule 8 (no spend without the owner); owner decision D1 |
| Research IDs | INF-07, INF-08 (both unresolved: no official RAM figure for either option); INF-01, INF-03, INF-04 (host and isolation facts) |
| MVP scope | **3A**: structured logs and the factory's own metrics endpoint design only; no monitoring tool, no S5. **3B**: footprint measurement on the VPS (the decision rule in §4). **3C**: S5 sampling, thresholds and the chosen tool. |
| Enterprise tier | **Tier 0**: lightweight, on the shared VPS (directive §3.2a). **Tier 1**: own server for the platform before the first external client (§1C.14); Prometheus + Grafana becomes eligible there. **Tier 2-3**: per-tenant dashboards, SLA/status reporting (§1C.11) |

## 1. Context
- The factory shares a KVM 2 VPS (2 vCPU / 8 GB, INF-01) with the owner's existing apps, under its own systemd slice with low weights and hard caps (INF-03, INF-04). A monitor must not become a noticeable load on the existing apps (directive §1).
- 05 §9 already defines what S5 reads: cgroup memory and CPU files, host PSI, disk, pids, queue depth, worker heartbeats, API latency. These come from the kernel and from the factory's own tables, so any tool can expose them (05 §9.5).
- Directive §3.2a gave expected sizes ("tens of MB" for a Beszel-type agent, "hundreds of MB to ~1 GB" for Prometheus + Grafana). The research log shows neither is officially supported:
  - **INF-07:** Beszel's README and docs say "lightweight" with **no RAM figure**. Per-container Docker stats and alerts are confirmed. MIT licence. Status PARTIAL (RAM NOT CONFIRMED).
  - **INF-08:** no official total exists for Prometheus + Grafana. Grafana documents "at a minimum 512 MB of memory and 1 CPU core", for evaluation only. Prometheus documents disk sizing, not RAM. Status UNVERIFIED.
- Consequence: neither footprint is a fact. The comparison below uses only what the log supports, and the choice is made by measurement (§4).
- No resource figure of the VPS, the existing apps or the factory is measured yet (audit pending, 00_REPO_AND_SERVER_AUDIT.md; 05 §8.5).

## 2. Options considered

| Option | Where it runs | What the evidence says | Effect on existing apps | Cost | Fit |
|---|---|---|---|---|---|
| **A. Lightweight agent + factory metrics endpoint** (Beszel-class agent for host and container stats; S5 and workers expose their own endpoint) | Shared VPS, inside the factory's own slice | Per-container stats and alerts confirmed; **RAM unknown** (INF-07) | Depends on the measured footprint; sits under the slice caps (`MemoryMax`, `CPUWeight`) | No licence cost (MIT). Disk and bandwidth only | Directive default for Tier 0 |
| **B. Prometheus + Grafana, on the shared VPS** | Shared VPS | Grafana floor alone is 512 MB and 1 CPU core (evaluation figure, INF-08); Prometheus RAM undocumented | Highest risk of contention with the trading app and BagMitra | None | Not supported by the evidence at Tier 0 |
| **C. Prometheus + Grafana on a dedicated server** | Separate server | Floor of 512 MB for Grafana alone (INF-08) fits a small server; total unknown | None on the shared VPS except exporter and scrape traffic | New server: owner decision and purchase (rule 8). Price: INF-01 gives KVM 1 and KVM 2 prices, re-check before any decision | Directive target after Tier 0 |
| D. Logs only, no metrics | n/a | n/a | None | None | Rejected: S5 needs the signals in 05 §9.1 and the directive requires resource monitoring |

Hosted monitoring services were not researched and are not proposed (owner rule A.5).

## 3. Decision (Draft)

### 3.1 Always, at every tier: the factory's own metrics endpoint [3A design, 3C build]
- Every factory process exposes its own metrics, and S5 reads the kernel files directly (05 §9.1). The endpoint is the contract between the factory and any tool, so the tool can be swapped without code change (provider-independence principle, directive §3.2a).
- Every metric carries label `org_id`; platform-wide metrics use `org_id="platform"` (GLOSSARY). Host signals carry no tenant data (05 §9.1). 07 §12 metrics (attempts, retries, DLQ inflow and age, breaker state, stuck detections, escalations, replays) are exposed on the same endpoint with `agent_id` and `error_code`.
- The endpoint binds to localhost or the private Compose network only, never a public port (directive §1 Deployment isolation; 08_SECURITY.md). Reverse-proxy or network changes need owner approval (§1).
- Storage of samples: S5 samples have no table in the Wave A contracts. Until a request is applied, samples live only in the endpoint (ephemeral) and only threshold events go to `audit_log` and notifications (05 §9.4). **Contract request:** table for S5 samples (unfiled CCR, same gap as 05 §12 item 1; see the audit file).

### 3.2 Tool choice: rule-based, not preselected
| Phase | Tool | Condition |
|---|---|---|
| 3A | **None.** Structured JSON logs (27 §7.3.6) and the ADR-012 guards only | No monitoring tool is installed in 3A |
| 3B | Measure candidate A on the VPS (§4); no commitment | Owner approval for the first VPS action; read-only audit first |
| 3C, Tier 0 | **Option A**, if the §4 rule passes | Measured footprint within the allowance |
| 3C, Tier 0, rule fails | Do not run any agent on the shared VPS. Rely on the factory endpoint plus cgroup reads by S5 itself, and recommend option C | Owner decision (rule 8) |
| Tier 1 (own server, before first external client, §1C.14) | **Option C** becomes eligible; recommendation only | Owner decision and purchase; measured need (per-tenant dashboards, retention, alerting) |

## 4. Decision rule: measure on the VPS before choosing
No tool is installed on the production VPS to "try it". The measurement is done in this order, and each step needs owner approval for any VPS action (rule 2: read-only until then).
1. **Baseline.** Use the existing read-only audit (00_REPO_AND_SERVER_AUDIT.md Part C) to record `measured_total` and `peak(trading app + BagMitra + OS)` over 24 h including the 00:00-07:00 IST window (00b §2.2). REQUIRES REVIEW (Phase 1): VPS measurement.
2. **Candidate footprint.** Run candidate A for at least 24 h with a container memory and CPU cap and record its resident memory, CPU use and disk growth, idle and under a render. Use the cgroup counters of its own container. Label the result **MEASURED** with date and host class. REQUIRES REVIEW (Phase 1): VPS measurement.
3. **Allowance.** The monitor's measured peak must fit inside `available_for_factory` (05 §8; 00b §2.2) after the heavy slice's own need, leaving the safety margin set in 05. The allowance value is configuration, REQUIRES REVIEW (Phase 1): set after step 1.
4. **Pass:** option A stays on the VPS under its own container limits. **Fail:** option A is not run on the shared VPS; S5 uses the endpoint and cgroup reads, and option C is recommended to the owner.
5. **Prometheus + Grafana is not measured on the shared VPS.** The INF-08 Grafana floor of 512 MB alone is an evaluation figure for a single component; the log notes that it already confirms a full stack does not fit next to the existing apps. Option C is evaluated only if the owner approves a dedicated server.
6. **Daytime.** After 07:00 the monitor may stay up only if its measured footprint is safe (directive §1 Production window). Whether it is daytime-stoppable follows open question Q7.

## 5. Consequences
- **Positive.** No unsupported number enters the design. The decision is driven by the same measure-first formula as ADR-012. The metrics endpoint keeps the tool replaceable, so moving to option C changes configuration, not code.
- **Negative.** Until step 2 completes, the tool for Tier 0 is a default, not a decision. 3A runs without any monitoring dashboard; operators see only logs and the night report.
- **Security.** A monitoring agent reads host and container data. It must not mount the Docker socket writable, expose a public port, or read other apps' data beyond resource counters. Details belong to 08_SECURITY.md. REQUIRES REVIEW (Phase 1): confirm the agent's required privileges from its official documentation before step 2.
- **Cost.** Option A has no licence cost. Option C has a server cost and needs the owner's purchase decision (rule 8). The cost goes to 09_COST_AND_BUDGET.md only if the owner approves it.
- **Tests.** (a) Every metric carries `org_id` (27 §9 isolation tests); (b) the endpoint refuses non-local connections; (c) the monitor's container stays within its limits while a render saturates the heavy slice (INF-04 acceptance test, 27 §9); (d) a missing monitor must not stop production (S5 failure is WARN, not a task failure).

## 6. Status
**Draft.** The choice between A and C is open until the §4 measurement exists.

## 7. Revisit triggers
1. The VPS audit (Part C) arrives, so step 1 can be evaluated.
2. The step 2 measurement completes: record the figures here and in the RESEARCH_LOG as MEASURED, then close INF-07 and INF-08 as measured-here (not as official figures).
3. S5 reports sustained contention, or the owner approves a dedicated server (ADR-012 option C or the Tier 1 move).
4. First external client (Tier 1, §1C.14): per-tenant dashboards and a status page are needed.
5. Beszel or Grafana publish an official resource figure (re-verify INF-07 and INF-08).

## 8. Cited research IDs
INF-07, INF-08, INF-01, INF-03, INF-04.
