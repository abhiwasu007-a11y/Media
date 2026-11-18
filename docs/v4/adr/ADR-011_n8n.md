# ADR-011 — n8n: not adopted; the factory's code-controlled orchestrator and Postgres queue cover every requirement

| Field | Value |
|---|---|
| Status | **Draft - documentation** (proposed outcome: **Not needed**). Software: **Planned** (nothing to build for n8n) |
| Decider | Owner (Abhi). Spend, new services and any licence agreement are owner decisions (rule 8) |
| Owner agent / service | Agent 01 CEO / Orchestrator (state machine, scheduling, S7 approvals; S5 signals). No n8n component exists |
| Depends on | MASTER_DIRECTIVE.md §3.2a; ADR-001 (queue), ADR-012 (render placement); 03_COMMUNICATION_STANDARD.md §11 (state machine, §11.6 approval waits); 04_DATABASE_ARCHITECTURE.md §5.4 (`task_queue`, `workers`), §5.26 (`webhooks`, `webhook_deliveries`); 07_FAILURE_MANAGEMENT.md; 08_SECURITY.md; 09_COST_AND_BUDGET.md; 14_SHARED_SERVICES.md (S7, S12); 24_PRODUCTION_TYPES.md §3.2; 27_ENGINEERING_STANDARDS.md; GLOSSARY_AND_IDS.md |
| Directive sections covered | §3.2a ("n8n only if an ADR shows a need code cannot cover"; simplest option that meets the requirement wins); §1 (shared VPS, deployment isolation, Postgres-backed queue); §0 rules 4, 5, 8, 9; §1C.12 (integrations, T3) |
| Research IDs | INF-01, INF-05, INF-06 (repo log); n8n facts below are **not yet in RESEARCH_LOG.md** (see §1.2) |
| MVP scope | **3A**: none (no n8n). **3B**: none. **3C**: nothing planned; revisit only on a trigger in §6 |
| Enterprise tier | Tier 0 not needed. Tier 1/2 not needed. Tier 3 (integration API / webhooks, S12) is built in code; n8n is not a Tier 3 dependency |

## 1. Context
- §3.2a lists n8n as allowed "only if an ADR shows a need code cannot cover". The default is therefore **not adopted**, and this ADR must name a concrete requirement that code cannot meet to change that.
- The directive fixes the control plane: 17 stages under a **code-controlled orchestrator, a state machine** (not LLM-to-LLM), with tasks, retries, DLQ and approval waits defined in 03 §11 and 07, executed from a Postgres-backed queue (§1; ADR-001; INF-05, INF-06).
- Hard constraints any workflow tool would have to meet: tenant isolation with `org_id` and RLS (rule 9; 04 §1.2, §3.4), one state authority (03 §11), no uncontrolled loops or silently dropped jobs (rule 5), no hard-coded keys or providers (§0), shared server of 2 vCPU / 8 GB with caps (INF-01), market-hours and night-window guards (ADR-012).

### 1.1 What n8n is (official sources, fetched 2026-11-18 via curl)
| Fact | Source |
|---|---|
| Licence is the **Sustainable Use License v1.0** (fair-code, not open source) for everything except files with `.ee.` in the name or `.ee` in the directory, which need an n8n Enterprise License | https://raw.githubusercontent.com/n8n-io/n8n/master/LICENSE.md ; https://docs.n8n.io/sustainable-use-license/ |
| Use or modification only for **own internal business purposes or non-commercial/personal use**; distribution only free of charge for non-commercial purposes | same |
| The licence FAQ says internal business use is acceptable, "not making n8n available to your customers for them to connect their accounts and build workflows"; other uses need a separate commercial agreement with n8n | https://docs.n8n.io/sustainable-use-license/ |
| Default database is SQLite; PostgreSQL is supported; with PostgreSQL the data directory still holds encryption keys, logs and other files | https://docs.n8n.io/hosting/installation/docker/ |
| **Queue mode** (scaling) needs a main instance, **Redis** for the execution queue, and worker instances (each its own Node.js process); the encryption key must be shared with all workers; SQLite with queue mode is not recommended | https://docs.n8n.io/hosting/scaling/queue-mode/ |
| n8n does not limit data per node; executions can run out of memory; memory-heavy nodes include Code; the docs advise adding memory or restructuring workflows | https://docs.n8n.io/hosting/scaling/memory-errors/ |

### 1.2 Facts not available
- **RAM and CPU of an n8n instance: REQUIRES REVIEW (Phase 1): an official minimum or typical resident-memory figure for n8n (single instance and queue mode); the pages above give none. Until measured, no figure is stated.**
- The n8n facts above are read from the official pages on the date shown but have no `RESEARCH_LOG.md` ID. **REQUIRES REVIEW (Phase 1): lead to add them to RESEARCH_LOG.md (licence terms, queue-mode architecture) with ID and date; this ADR cites them by URL until then.**
- Whether the owner's use (own channels, then paying clients) counts as "internal business purposes" under the licence is a legal question. **REQUIRES REVIEW (Phase 1): owner / legal confirmation; the licence FAQ points to license@n8n.io for doubtful cases.**

## 2. Requirement-by-requirement test (can code cover it?)
| Requirement | Where it is already covered in code/design | Needs n8n? |
|---|---|---|
| Stage sequencing, branching, retries, DLQ, replay | Orchestrator + state machine (03 §11; 07 §3, §6; ADR-001). Task types are canonical (24 §3.2) | No |
| Scheduling and night-window drain | Admission guards (T07), `scheduled_at`, ADR-012 §3.3; periodic jobs from the queue library (INF-05, INF-06) | No |
| Human approval waits | `svc_s07.request_approval` (S7, 3A) and 03 §11.6 | No |
| Budget stop on breach, per-video and pilot budgets | S4 inline library at T03 (14; 09) | No |
| Provider calls (LLM, TTS, image, stock) | Provider-independent adapters (§3.2a; ADR-007 to ADR-009). n8n's own integrations would bypass the adapters, the cost ledger and the secret mechanism | No |
| Notifications (L1-L3, owner) | Part of the 07 §7 alerting design and S7; a channel adapter is code | No |
| Outbound client webhooks (T3) | S12 `svc_s12.webhook_deliver` (pending CCR in 14), tables `webhooks` / `webhook_deliveries` (04 §5.26), signed payloads and SSRF guard (08 §7) | No |
| Multi-tenant isolation | `org_id` + FORCE RLS on every tenant table (04). n8n has its own workflow/credential store that is not under factory RLS | Would add a gap |
| Rendering, QC, media work | Workers with capabilities and resource classes (ADR-012); n8n is not a media engine | No |
| Rapid editing of simple automations by a non-developer | Not a stated requirement in the directive or owner decisions D1/D2 | Not requested |

No row shows a need that code cannot cover.

## 3. Options considered (with evidence)
| Option | Fit to §3.2a and contracts | Cost / risk | Verdict |
|---|---|---|---|
| **A. No n8n; orchestrator, queue and adapters in code** | Meets every row in §2; one state authority; RLS intact | No new service, no new licence question | **Proposed** |
| B. n8n as the pipeline engine | Duplicates 03 §11 and 07 with a second state/retry system; stage data outside RLS; keys in a second secret store (§1.1 shared encryption key) | Violates "one state authority" (ADR-001 constraint 3); licence question for client use (§1.2); extra resident Node.js process and, for scaling, Redis (§1.1), against §1 "avoid extra resident services" | Rejected |
| C. n8n for side automations only (notifications, glue) | Each is a small adapter in code (§2) | A second service, UI, credential store and update stream to secure and keep patched for no capability gain; RAM unknown (§1.2) | Rejected for now |
| D. n8n as a client-facing automation feature | Licence FAQ excludes making n8n available to customers to connect accounts and build workflows (§1.1) | Needs a commercial agreement; owner decision | Rejected; not requested |

## 4. Decision (Draft)
1. **n8n is not adopted** in 3A, 3B or 3C. Nothing in the factory depends on it. This satisfies §3.2a: no need that code cannot cover is shown.
2. Every capability in §2 is delivered by the components already specified; no n8n-shaped contract, table, enum or task type is created (no contract requests from this ADR).
3. If a future need appears, it is raised as a change request (rule 11, CHANGE_REQUESTS.md) and this ADR is revisited; the decision is not made in code or in a deployment.
4. Documentation consistency: references to n8n in other documents are to be read as "not used". The adr/README.md row is updated by the lead, not by this file.

## 5. Consequences
- **Positive.** No extra service, port, credential store, licence obligation or patch stream on the shared server; no Redis dependency from a workflow tool; tenant isolation and the state machine stay single-source; one fewer item in 08_SECURITY.md scope.
- **Negative.** Every integration or glue step is code with tests (27) rather than a visual workflow; a non-developer cannot edit automations without a code change. Accepted: the owner stated no such requirement (owner rule A.5).
- **Failure handling** unchanged from 07; no additional failure class.
- **Tests.** None specific. Acceptance: the dependency and Compose inventory (10_DEPLOYMENT_AND_MIGRATION.md) lists no n8n service.

## 6. Status
**Draft - documentation.** Proposed outcome: not needed. Awaiting owner acceptance; software status Planned (no work).

## 7. Revisit triggers
1. A measured requirement that code cannot meet in reasonable effort, named as a row in §2, with the failed code option documented.
2. An owner request for non-developer-editable automations (needs an owner decision, A.5, and a tenant-isolation design first).
3. The licence terms change, or counsel confirms the owner's use is within "internal business purposes" and a concrete need exists (§1.2).
4. A Phase 1 measurement of n8n's RAM/CPU becomes available and a concrete need exists (§1.2).

## 8. Cited research IDs and sources
INF-01, INF-05, INF-06 (RESEARCH_LOG.md). n8n official URLs listed in §1.1, fetched 2026-11-18; not yet logged (REQUIRES REVIEW, §1.2).
