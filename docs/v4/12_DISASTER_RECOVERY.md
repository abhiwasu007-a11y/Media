# 12 — Disaster Recovery (backups, persistent media, restore, VPS-restart recovery, credential recovery, RTO/RPO, status page, incidents)

| Field | Value |
|---|---|
| Status | **Draft - documentation**. Software: **Planned** (nothing in this document is implemented, scheduled, restored or measured) |
| Owner agent / service | **S6 Security & Audit** (owner Agent 16, plan Q4) owns the backup job, restore tests and the audit-head copy; **Agent 01** (orchestrator) owns admission control, scheduling of the backup in the night window and the restart/resume behaviour; **S5 Infrastructure Intelligence** (owner Agent 01) owns health signals; **S7** (owner Agent 01) delivers alerts and notifications (02_AGENT_REGISTRY.md) |
| Depends on | MASTER_DIRECTIVE.md §1 (Server, Deployment isolation, Production window), §1C.5, §1C.10, §1C.11, §1C.14, §1C.15, §3.2a (storage, off-server backup from day one, monitoring), §3.3 (Disaster recovery, Recovery, Migration); GLOSSARY_AND_IDS.md (IDs, `org_status`, `data_request_kind/status`, `data_key_status`, `actor_ref`); 03_COMMUNICATION_STANDARD.md §5.3, §8, §9, §11; 04_DATABASE_ARCHITECTURE.md §3.1, §3.6, §5.1, §5.7, §5.13, §5.19, §5.24, §6, §7, §8; 07_FAILURE_MANAGEMENT.md §2, §5, §6, §7, §8, §10, §12; 05_RESOURCE_MANAGEMENT.md §6.4; 08_SECURITY.md §3, §6, §9.3, §12; 10_DEPLOYMENT_AND_MIGRATION.md §4, §9, §13, §14; 09_COST_AND_BUDGET.md; 3A_SLICE_SPEC.md (R10); ADR-005 (storage, §3.4 backup), ADR-012 (render worker placement); KNOWLEDGE_LIBRARY_PLAN.md (by name only) |
| Directive sections covered | §1C.11 (reliability commitments: honest SLAs, status page, health checks, incident process, backups with tested per-tenant restore/export, RTO/RPO per plan); §1C.10 (per-tenant export and deletion); §3.3 Disaster recovery (DB + config backups, persistent media storage, restore tests, VPS-restart recovery, credential recovery, stated RTO/RPO); §3.2a (off-server backup from day one); §1 Deployment isolation (own volumes, storage, backups); §1C.14 / §1C.15 (infrastructure and tier gates); owner decisions D1 (3A files out, no upload/OAuth, secrets only via the environment mechanism, render never in market hours, spend limits) and D2 |
| Research IDs | INF-01 (plan size, single VPS), INF-03 (`IOWeight`, slice limits), INF-11 (RLS: owners and `BYPASSRLS` roles), IN-07 (DPDP phases). No backup tool, object-storage product, status-page product or restore-time figure is recorded in RESEARCH_LOG.md: every such item is marked REQUIRES REVIEW (Phase 1) |
| MVP scope | **3A**: persistent-media rules, atomic writes and VPS-restart recovery (already in 07 §8 / ADR-005), the backup and restore **design** with a local scratch restore test on synthetic data in the development environment, the credential-recovery inventory. **3B**: off-server backup destination configured and the first real restore test **before** the golden samples are kept (3A_SLICE_SPEC R10). **3C**: scheduled backups and restore tests under the night window, health signals, dashboard backup-age display, per-tenant export job. Per-section markings below. |
| Enterprise tier | **Tier 0** owner's own channels on the shared VPS: best effort, no published commitment. **Tier 1** before the first external client: own server, tested per-tenant restore/export, stated (measured) RTO/RPO, status page. **Tier 2** self-serve plans with plan-level objectives. **Tier 3** dedicated stack, formal SLA only after a pen-test and measured RTO/RPO (§1C.11, §1C.13; 10 §13). |

> **Rules for this document.**
> 1. Documentation only. No backup script, schedule, Compose file, tool or destination is written or chosen here (10 §1 rule 1). 
> 2. No number in this document was measured. Where a value is needed it is a **design proposal marked ESTIMATE** for the owner to set, or **REQUIRES REVIEW (Phase 1)**. No RTO or RPO is promised to anyone by this document (§12).
> 3. The repository is PUBLIC: no host names, addresses, paths other than the directive's root, credentials, provider account details, book titles or private method appear here (08 §11).
> 4. No Wave A contract is redefined. Needs that do not fit are in §16 **(pending CCR)** and used under the proposed name only where marked.
> 5. Documentation status is separate from software status (rule 6). Everything here is **Planned**.

---

## 1. Purpose and boundary [3A / 3B / 3C · Tier 0-3]

**What this document defines.** What is backed up, where it must live, how it is restored (whole platform, one tenant, one blob), how the platform comes back after a restart, how credentials are recovered, how often the restore path is proven, what recovery objectives can honestly be stated per tier, and how outages and data-loss incidents are communicated (status page, incident process).

**What it does not define.** The backup tool, destination, encryption method, price and schedule values (ADR-005 §3.4 leaves them to Phase 1 and the owner's purchase decision, rule 8); retention periods for personal data (22_DATA_PROTECTION.md, planned, with the owner's lawyer ⚖); the secret-delivery mechanism (08 §3.1, a separate ADR); limit and weight values (05); the security incident runbook itself (08 §12; this document only adds the availability and data-loss side and refers to 08 for everything security-related).

**The honest premise (§1C.11).** The factory runs on one shared VPS (INF-01 records the plan size only) that also hosts the owner's other applications. One machine, one disk, one provider account is a **single point of failure by construction**. This document does not hide that: it makes the loss **bounded and recoverable** (off-server copies, tested restores, resume from checkpoint) and states recovery objectives as measured, not as availability promises. High availability is not offered at any tier below Tier 3, and even there only after measurement.

---

## 2. Facts and what is not known [3A / 3B · Tier 0]

| Item | State |
|---|---|
| Server plan | KVM 2, 2 vCPU / 8 GB / 100 GB NVMe, shared with existing apps (INF-01). Free disk, I/O and measured per-video size: **REQUIRES REVIEW (Phase 1): VPS audit, A1** (waiting; 00b §2.3) |
| Backup destination, tool, encryption, price | **REQUIRES REVIEW (Phase 1)** and owner purchase decision (ADR-005 §3.4; R10; rule 8). Not in RESEARCH_LOG.md |
| Provider-side snapshots or maintenance behaviour of the VPS provider | **REQUIRES REVIEW (Phase 1): official provider documentation.** No snapshot product is assumed to exist; none is relied on |
| Database durability and crash-recovery settings of the chosen PostgreSQL version | **REQUIRES REVIEW (Phase 1): record the official documentation and version in RESEARCH_LOG.md** (04 §8.1 requires the same for the migration tool) |
| Restore time of a database or of N GB of blobs on this host | **Unknown.** Measured only by the restore rehearsal (§11, DR-T5; 10 §14.3 step 3) |
| Size of a finished video set, daily DB growth | **Unknown** until the skeleton and pilot measure it (00b §2.3; 04 §6) |
| Retention of backups, audit and personal data | **REQUIRES REVIEW (Phase 1): 22 + lawyer ⚖** (04 §7) |
| Status-page product / hosting | **REQUIRES REVIEW (Phase 1)**; no product is recorded; purchase is the owner's (rule 8) |

---

## 3. Recovery model: terms and the shape of an honest objective [3A design · Tier 0-3]

| Term | Meaning in this document |
|---|---|
| **RPO** (recovery point objective) | The longest period of recent change that may be lost. For a backup-based design it is **at most the time since the last successful, verified off-server copy of that data class**. It is a property of the backup schedule, not of the infrastructure |
| **RTO** (recovery time objective) | The time from "declared disaster" to "the platform accepts and runs jobs again". Sum of: detection + decision + provisioning (if the machine is lost) + download of backups + restore + verification (§7.5) + start order (10 §9.1) |
| **Data class** | DB (state, queue, audit, ledger), blobs (media and documents), config, secrets. Each has its own RPO because each has its own backup path (§6) |
| **Durability levels of a file** | **D0** temporary file (never an output; 07 §8.4). **D1** published to the write-once final path on the local storage root, SHA-256 verified (ADR-005 §3.3). **D2** D1 **plus** a verified copy off the machine (§5.3) |

**Rules.**
1. RPO and RTO are stated **per data class and per tier**, and the stated figure is always the **measured** value from a rehearsal plus a margin, never a target taken from a template.
2. Until a rehearsal has run, the objective for that tier reads "**not committed**" and no external statement quotes a figure.
3. Backup-based recovery cannot give an RPO below the backup interval. A lower RPO needs a continuous-copy method (e.g. database write-ahead-log archiving); whether the chosen tool offers it, its cost and its restore procedure are **REQUIRES REVIEW (Phase 1)** and are not assumed.

---

## 4. What is protected [3A / 3B / 3C · Tier 0-3]

| # | Asset | Where it lives (design) | Loss impact | Backed up? | Restored by | Scope |
|---|---|---|---|---|---|---|
| A1 | **Database**: all tables of 04 (jobs, tasks, queue, state transitions, approvals, `renders` rows, cost ledger, idempotency keys, audit log and chain heads, tenancy, wrapped data keys) | the factory's own PostgreSQL in its own Compose project (10 §4) | Platform state lost; queue and budgets wrong; audit chain unverifiable | **Yes** (logical dump, §6.2) | §7.2 | 3A design, 3B live |
| A2 | **Blobs**: finished masters and renders, thumbnails, SRT, QC and cost reports, assets, licence documents, consent records, evidence, exports, checkpoints, Task Input/Output documents (03 §8 areas) | local storage root, `<root>/<org uuid>/<area>/<path>` (ADR-005 §3.1) | A finished video lost = the money spent on its paid calls is lost (D1 cost per video) | **Yes** (§6.3) | §7.2 / §7.3 / §7.4 | 3A design, 3B live |
| A3 | **Configuration without secrets**: non-secret environment values, the names-only env example, Compose project definition, slice settings, the pinned image identifiers in use, the applied migration version, worker capability registrations | repository (`deploy/`, SOURCE_LAYOUT.md) plus the running deployment's non-secret values | Cannot rebuild the same deployment | **Yes** (§6.4); the repository is the source for everything that is in git | §7.2 step 3 | 3A |
| A4 | **Secrets** (provider keys, DB passwords, backup credential, KEK) | **only** the environment's secret mechanism (D1; 08 §3.1) | Services cannot start; tokens unreadable | **Never inside the backup set** (ADR-005 §3.4, 08 §3.1). Recovery by §9 | §9 | 3A |
| A5 | **Tenant data keys** (wrapped DEKs, `tenant_data_keys`) | in the DB (A1); the KEK that unwraps them is outside the DB (08 §6.1) | DB backup alone never allows decryption; KEK lost = tenant tokens and webhook secrets unreadable | DEKs: with A1. KEK: §9 | §9 | 3C design, Tier 1 live |
| A6 | **Audit chain head copy** per org | copied with each off-server backup (04 §5.13, 08 §9.3) | Without it, truncation or replacement of the audit log is undetectable | **Yes**, stored separately from the DB dump set (§6.5) | §7.5 | 3A |
| A7 | **Knowledge index** (chunks, embeddings; derived data) | DB / storage (Agent 04, ADR-013) | Re-ingestion cost and time; no original is lost | With A1/A2 (it is simply data). It is **rebuildable** from its sources, so a lost index is a cost, not a loss | rebuild (night job) or §7.2 | 3A subset, 3C full |
| A8 | **Knowledge sources** (the owner's book and notes collections named in KNOWLEDGE_LIBRARY_PLAN.md: `pd_books`, `owner_strategies_notes`, `owner_books`; provisional defaults Q34-Q37) | **outside** the factory, mounted read-only from a configured path outside git (10 §18 item 11) | The factory's copy of record is not the original | **Not** in the factory backup unless the owner approves factory-side copies (KNOWLEDGE_LIBRARY_PLAN.md K8); then they are blobs like A2, encrypted, never in git | owner's own sources; §7.2 if copies exist | 3A subset, 3C |
| A9 | **Logs** | factory log volume, rotated (10 §4) | Diagnostics only | **No** (rotating logs are not business data). Security-relevant events live in `audit_log` (A1) | — | 3A |
| A10 | **Scratch / temp** | scratch volume (10 §4) | None: never an output | **No**, never counted as output (ADR-005 §3.3) | — | 3A |
| A11 | **Source code, prompts, evals, docs** | the git repository (this repo and its remote) | Rebuild only | Git is the copy of record; protecting the git account itself is the owner's (§9.5) | clone | 3A |
| A12 | **YouTube-side state** (uploaded videos, channel, OAuth grants) | at the provider | Not the factory's data | Not applicable. A restored DB may disagree with it: §7.6 | §7.6 | 3C only (no upload in 3A) |

---

## 5. Persistent media storage: a finished video is never only in temp [3A · Tier 0-3]

Directive §3.3 and 03 §8 rule 2 are binding. This section states how they combine with the backup so that "persistent" also means "survives the machine".

### 5.1 Write path (already contracted; restated for DR)
1. A worker writes a temporary file (D0) in the same storage area, flushes, atomically renames it to the final write-once path (D1) (07 §8.1; ADR-005 §3.1). A hard kill leaves no corrupt file at a final path (07 §8.4).
2. A task is `SUCCEEDED` only if every `output_refs[]` object exists with the stated SHA-256 and size (03 §5.3). A final render is therefore **already at D1 before the job can reach a deliverable state**.
3. The `renders` row stores `storage_ref` and `content_sha256` (04 §5.18; persistent storage only). A render pointing to a temp or scratch location is invalid by contract.
4. A render worker on another machine (ADR-012 §4) writes to persistent storage through the object-storage backend or the approved access path before the task succeeds; a worker's local scratch is never the only copy.

### 5.2 Delivery in 3A (D1)
The owner receives the MP4 (16:9, plus 9:16 where applicable), thumbnail options, SRT, the QC report with the 100-point score and the cost per stage **as downloadable files**. A 3A run's outputs are **disposable** until the backup destination exists: the downloaded bundle is the owner's copy (3A_SLICE_SPEC R10; ADR-005 §3.4).

### 5.3 Rule for outputs that must be kept (from the first golden sample, 3B)
1. **Keep = D2.** An output the owner or a tenant must keep (3B golden samples, every Tier 1+ deliverable) is not considered safe until its blob and the DB rows that reference it are covered by a **verified off-server backup** (§6). 
2. **Copy triggered by completion, not by the calendar.** Because blobs are write-once (a new version has a new path, 03 §8 rule 2), the blob backup is **incremental by listing**: after a job reaches a terminal state the next backup run copies every blob not yet in the destination manifest and verifies its SHA-256 there. The blob RPO is therefore the time from job completion to the end of that run, not the DB interval.
3. **Report it.** The job's delivery report states each deliverable's durability level (D1 or D2). A deliverable stays "D1 only" until the verified copy exists. How this is shown (a field in the existing report vs. a new column) is a build decision; a new column or table would need a CCR (§16, item 4 proposes the one table this document needs).
4. **Disk pressure never deletes deliverables.** Retention never removes final media (04 §7); disk admission (05 §6.4) pauses heavy work before a write fails; `RESOURCE.DISK_FULL` suspends with `OPERATOR_PAUSE` and escalates L3 (07 §2). Intermediate (non-final) blobs follow configured retention and may be removed only after the job's final blobs are D2 **(proposal; owner confirms)**.
5. **The backup staging area is capped** and lives on its own volume so a backup can never fill the storage volume (10 §4); a failed or stalled backup raises `INFRASTRUCTURE.BACKUP_FAILED` (pending CCR) and never blocks job execution by itself, but **backup age beyond the configured limit pauses admission of new jobs for tenants with kept-output obligations** (Tier 1+; Tier 0 raises an L3 notice only) **(proposal)**.

---

## 6. Backup design [3A design · 3B live · 3C scheduled · Tier 0-3]

### 6.1 Principles
1. **Off-server from day one** (§3.2a, ADR-005 §3.4): at least one copy of every backed-up class exists outside the machine that runs the factory, and outside the VPS provider account where the owner's budget allows **(recommendation; REQUIRES REVIEW (Phase 1): destination, owner purchase)**. A backup on the same disk is a convenience copy, not a backup.
2. **Encrypted before it leaves the machine**; the backup key comes from the secret mechanism and is **not stored in the backup** (§9.2).
3. **Tenant prefixes preserved** so one tenant can be restored or exported alone (§1C.11; ADR-005 §3.4).
4. **The backup job is a factory service** in the factory's own Compose project and slice, class `LIGHT`, limited by its own cgroup caps and a low `IOWeight` (INF-03; 05 §9), never touching other applications' volumes (§1 Deployment isolation; 10 §5.1 `backup` job).
5. **It runs inside the night window** on the shared VPS (06 owns the schedule; 05 notes backups are scheduled in the window by this document and 06). Verification passes that hash large numbers of blobs are I/O and CPU heavy; they are treated like heavy work and are **never run during market hours** (conservative design choice for the shared host; owner confirms).
6. **The audit trail covers it.** Backup and restore actions are audited by the backup job's `SYSTEM` identity `sys_backup` **(pending CCR: GLOSSARY §2.3 lists only five `sys_` names)** with audit actions `backup.completed`, `backup.failed`, `restore_test.completed`, `restore_test.failed`, `restore.performed` (names proposed for the S6 audit list, 08 §9.2).
7. **A backup is `UNVERIFIED` until a restore test has succeeded** (§11). Nothing in an RTO/RPO statement relies on an unverified backup.

### 6.2 Database backup [3A design / 3B live]
| Aspect | Design |
|---|---|
| Method | **Logical dump** of the factory database (ADR-005 §3.4; 10 §14.2 step 2), consistent as of a single point in time, plus the schema/migration version recorded beside it. Physical or continuous methods are REQUIRES REVIEW (Phase 1) (§3 rule 3) |
| Role | RLS applies to table owners and is bypassed only by superusers and `BYPASSRLS` roles (INF-11). A dump taken by `amw_app` or `amw_readonly` would therefore contain **no rows**. The dump needs a dedicated **read-only role with `BYPASSRLS`** used by the backup job only: **`amw_backup` (pending CCR)**. Alternative (no new role): the dump runs under the administrative database credential held by the deploy mechanism, never by a running service. The choice is a Phase 1 decision between the two; neither is used by agents or API |
| Content | Every table, including the platform-scope and catalogue tables. Seed data is also recreated by migrations (04 §8.3), but is dumped anyway so the restored state equals the dumped state |
| Frequency | Interval is the DB RPO (§3). **Design proposal (ESTIMATE): Tier 0 once per night window**; Tier 1 and above shorter, set from the measured dump duration and growth. Owner sets (REQUIRES REVIEW (Phase 1)) |
| Extra dumps | Before every migration or upgrade (10 §14.2 step 2), before a host move (10 §14.3 step 4), and on the owner's command |
| Queue rows | Included. After a restore the queue is reconciled (§7.5, §7.6); `DONE`/`CANCELLED` queue rows older than `retention.queue_done_ms` are already deleted (04 §7) |
| Size/time | Unknown (§2). Measured in DR-T2 / DR-T5 |
| Failure | `INFRASTRUCTURE.BACKUP_FAILED` (pending CCR); next window retries; stale beyond the limit → L3 to Platform Owner (07 §7 operations routing) |

### 6.3 Blob backup [3A design / 3B live]
| Aspect | Design |
|---|---|
| Method | Incremental by **manifest**: for each blob under the storage root, a manifest line `{uri, sha256, size_bytes}` (design file, produced and verified by the backup job; not a platform contract). New or changed manifest lines are uploaded; every uploaded object is read back or checksum-verified at the destination before the line is marked copied |
| Why incremental is safe | Blobs are write-once; a path never changes content (03 §8 rule 2). A path whose hash differs from the manifest is corruption (`AGENT.CORRUPTED_OUTPUT`, 07 §2) and is reported, never silently re-uploaded over the old copy |
| Layout | The destination keeps `<org uuid>/<area>/<path>` unchanged so one tenant = one prefix for restore and export (03 §8 rule 1). The `platform` area is backed up as its own prefix (mapping pending CCR in ADR-005 §3.1) |
| Order | Blobs first, then the DB dump, then the head copy (§6.5), so every row in the dump refers to blobs that are already in the destination. After a restore this makes "row without blob" impossible for the dump's own point in time; "blob without row" (orphan) is possible and is reported (§7.5 step 9) |
| Not included | Scratch/temp (never outputs, ADR-005 §3.3) and rotating logs |
| Large files | Upload of multi-GB masters must be resumable and chunked; tool capability REQUIRES REVIEW (Phase 1). A killed upload leaves no partial object at the final key (equivalent of the atomic rename; ADR-005 §3.2 item 3) |

### 6.4 Configuration backup [3A]
The backup set contains the **non-secret** deployment record: the Compose project definition and non-secret environment values actually in use, the names-only env example, the factory slice settings, the image identifiers (pinned) in use, the applied migration version, the worker capability registrations and `max_concurrency` values (10 §4, §8). Where the repository already holds a file, the record stores the **commit identifier** instead of a copy. **Secrets are never part of it** (08 §3.1 rules 2-5). A scan (the secret-scanning CI gate, 08 §10) is run over the config set before upload.

### 6.5 Audit chain head copy [3A]
Each backup run writes the current `audit_chain_heads` value (`org_id`, `last_seq`, `last_hash`) of every org as a small separate file and stores it **at a location with separate credentials from the DB dump** where feasible (08 §9.3 item 3: an attacker who owns the database and recomputes the chain can only be detected by an external head copy). The same file records the **IDs of completed `ERASURE` data requests** so a restore cannot silently bring erased tenants back (§10.5). Location and separation: REQUIRES REVIEW (Phase 1) (08 §9.3 item 2 defers to this document).

### 6.6 Encryption and backup-key recovery
- Encrypt client-side before upload; the key is delivered by the secret mechanism to the backup job only (08 §3.1 rule 4).
- **The key is a single point of failure for every backup**: the backups are unreadable without it. The owner keeps an **offline, separately stored copy of the backup key (and of the KEK material, §9.3) that is independent of the VPS and of the secret mechanism's own host** — a recovery precondition, not an option. How it is stored is the owner's decision and is not written in this repository.
- Algorithm, tool and key-rotation interval: REQUIRES REVIEW (Phase 1): select a maintained, audited tool; verify its official documentation; record version, licence and date in RESEARCH_LOG.md (same rule as 08 §6.2).

### 6.7 Backup retention (proposal, owner and lawyer decide)
1. Several generations are kept so that a corruption noticed late is still recoverable; **a backup newer than the last successful restore test is never the only one kept**.
2. Retention periods: **REQUIRES REVIEW (Phase 1): 22 + 21 + lawyer ⚖** (04 §7). Backups containing personal data cannot be kept longer than the retention the privacy notice states.
3. **Erasure and backups:** a tenant erasure (`data_requests`, kind `ERASURE`, 04 §5.24) deletes live rows and the storage prefix and destroys the DEKs (crypto-shredding of tokens and webhook secrets, 08 §6.6); copies of that data inside older backups **age out with backup retention**. The consequence for DPDP statements is for the lawyer ⚖ (IN-07: erasure/retention rules apply from the Rules' later phase). The procedure here guarantees only that a restore never re-activates erased data without re-applying the erasure (§10.5).

### 6.8 Backup health signals (S5 / S7)
`backup_age_db`, `backup_age_blob`, `backup_last_status`, `restore_test_age`, `audit_head_copy_age`, `backup_staging_free_bytes`. Thresholds are configuration (REQUIRES REVIEW (Phase 1)); breach raises an alert to the Platform Owner through S7. A signal that is absent counts as a breach (fail closed).

---

## 7. Restore [3A design · 3B first real test · 3C routine · Tier 0-3]

### 7.1 Scenarios and responses
| # | Scenario | First detection | Response | Expected data loss | Scope / tier |
|---|---|---|---|---|---|
| S1 | Worker or service process crash | reaper: lease expiry / stale heartbeat (07 §6) | Automatic: attempt resumes from checkpoint (07 §10); temp file never renamed (07 §8.4) | none | 3A · T0 |
| S2 | Container or **VPS restart** (planned or not) | services down, `INFRASTRUCTURE.HOST_RESTART` | §8 | in-flight work since the last checkpoint only | 3A · T0 |
| S3 | Database corrupted or lost; volume intact otherwise | `INFRASTRUCTURE.DB_UNAVAILABLE` beyond `infra.db_outage_alert_ms` (07 §2) | §7.2 database part | up to the DB RPO | 3B · T0 |
| S4 | Storage volume or disk lost | `INFRASTRUCTURE.STORAGE_UNAVAILABLE`, hash mismatch | §7.2 (blob part) | blobs: up to blob RPO (blobs completed since the last copy) | 3B · T0 |
| S5 | **Whole machine lost** (host failure, account problem, unrecoverable disk) | all health signals lost | §7.2 on a new machine; needs provisioning (owner purchase, rule 8) | DB RPO / blob RPO | 3B · T0; T1 own server |
| S6 | Bad migration or accidental deletion by an operator | migrate step fails (10 §9.1 step 2) or user report | restore the pre-migration dump (10 §14.2 step 4) or §7.3 for one tenant | since the pre-change dump | 3A · T0 |
| S7 | Malicious change, ransomware, **audit chain mismatch** | daily chain verification (08 §9.3) | Contain per 08 §12 first; restore from the **last verified** backup into scratch; compare with the head copy (§6.5); never repair the chain by editing rows (08 §12.3) | up to the DB RPO or more (the last *good* backup) | 3A design · T0 |
| S8 | Credential lost, revoked or leaked | provider 401/403, startup `PERMANENT.CONFIG_INVALID` (08 §3.1 rule 7) | §9 | none | 3A · T0 |
| S9 | One tenant's data damaged or deleted | tenant report / `data_requests` | §7.3 | up to the DB RPO for that tenant | 3C · T1 |
| S10 | Backup destination unreachable or lost | `INFRASTRUCTURE.BACKUP_FAILED` / stale | Re-establish a destination, take a **full** new backup immediately, run DR-T1 against it. Until then the platform is **not protected**; L3 notice | none now; protection gap | 3B · T0 |
| S11 | Backup key or KEK lost | restore test or startup failure | §9.2 / §9.3: there is no technical recovery without the offline copy | backups unusable / tenant tokens unreadable | 3B · T0 |

### 7.2 Full-platform restore (S3, S4, S5, S7 after containment) — runbook outline
Documented here, rehearsed by DR-T5. Each step lists the proof to keep.

| Step | Action | Proof / gate |
|---|---|---|
| 1 | **Declare** the incident (§14), set `admission_paused` and, if security-related, `platform_emergency_stop` (04 §5.1 `platform_controls`) through the control path; note start time (RTO clock) | incident record |
| 2 | Provision the target if the machine is lost: the factory's own Compose project under its own root, same isolation structure (10 §14.3 step 1); **no non-factory object is touched** (10 §9.4) | deployment record |
| 3 | Restore the **non-secret configuration** from the repository commit and the config set (§6.4); re-provision **secrets** from the secret mechanism and the owner's offline copies (§9). Missing secret → startup fails closed (08 §3.1 rule 7) | startup check passes |
| 4 | Start only `postgres` (10 §9.1 step 1); restore the chosen DB dump into an **empty** database as the admin path; do not start any service role | restore log |
| 5 | Verify the schema version equals the dump's recorded version; run the **RLS catalogue check** (04 §3.7.6) | check output |
| 6 | Restore blobs: read the destination manifest; copy back **tenant by tenant** (prefix) or all; verify **every** `renders.content_sha256` blob and a sample of the rest (§11 DR-T1); log mismatches | hash report |
| 7 | Reconcile **DB vs blobs** (§7.5): rows without a blob (must be zero for a consistent set), blobs without a row (orphans, reported) | reconciliation report |
| 8 | **Audit verification**: recompute every org's chain and compare with the head copy (§6.5, 08 §9.3). Any mismatch: stay in containment (08 §12.3) | verification output |
| 9 | Rotate what the restore may have resurrected: database role passwords (`amw_*`), **invalidate all sessions**, treat provider keys as compromised if S7 (§9.4) | rotation record |
| 10 | Start in 10 §9.1 order (migrate must report "up to date", never "apply" on a restored DB without owner consent), workers register, reaper recovers expired leases (07 §6) | health OK |
| 11 | Run the **post-restore holds** of §7.6 (spend, publication) while admission is still paused | hold record |
| 12 | Run a **canary task** (10 §14.2 step 5); then release `admission_paused`; note end time (measured RTO) | canary result |
| 13 | Notify tenants as §14 requires; open the post-incident review (08 §12.2 phase 7) | review note |

### 7.3 Single-tenant restore (S9) [3C design · Tier 1 gate]
Goal: restore **one tenant** without touching others (rule 9).
1. Restore the relevant DB dump and the tenant's blob prefix into a **scratch** database and root (never into the live ones first).
2. Verify inside the scratch copy as that tenant: row counts per table, SHA-256 of the tenant's blobs, tenant audit chain (head copy for that org).
3. Produce the tenant-scoped export of the repaired state (§10, the same exporter as per-tenant export: every `TENANT`-scope table filtered by `org_id`, under the tenant context).
4. With admission paused **for that tenant only**, import into the live system in a single transaction per table family, in foreign-key order, with the tenant context set; existing live rows that the owner chooses to keep are never overwritten silently: conflicts are listed for a human decision (L3). The `exports/<dtr>/` area holds the bundle (03 §8 areas).
5. Re-run the tenancy suite subset (04 §3.7) and the audit-chain check for that org. Write an audit entry in that org's chain (`restore.performed`, pending CCR for the name list).
6. Full-database tools must not be used as "tenant restore": a whole-DB restore over a live database would roll back every tenant (10 §14.4: never a whole-database copy into another tenant's stack).

### 7.4 Single-blob restore (S4 partial)
A blob whose hash no longer matches (`AGENT.CORRUPTED_OUTPUT`) is replaced by fetching the same URI from the destination, verifying the SHA-256 recorded in the DB, and writing it with the normal atomic publish. Because the path is write-once, the corrupt copy is first moved to a quarantine area, never overwritten in place. An audit entry records who restored what.

### 7.5 Post-restore verification (every restore, every scope)
1. DB schema version = dump version; no pending migration applied unasked.
2. RLS catalogue check and the tenancy test suite pass (04 §3.7; blocking CI suite re-run against the restored instance).
3. SHA-256 of all `renders` blobs and of a configured sample of the rest.
4. Audit chains recompute equal to the head copy.
5. Queue sanity: no task `RUNNING` with a live lease; the reaper moves expired ones (07 §6); `CHECKPOINTED` tasks keep their `wait_reason`.
6. Idempotency table intact: `publish.*` and `upload.*` keys never expire (03 §9, 04 §7), so a replay finds them **if the row survived the restore point** (§7.6 covers the case it did not).
7. Disk free above the admission threshold (05 §6.4).
8. Cost ledger totals compared with provider-side usage (§7.6).
9. Orphan report: blobs with no referencing row. They are **not** auto-registered; a human (L3, Platform Owner) decides, because registering a blob is a data decision.

### 7.6 Post-restore holds: what a restore can silently get wrong
A restored database is **older** than the real world. Three things in the real world are ahead of it:

| Real-world fact ahead of the DB | Risk | Rule |
|---|---|---|
| **Paid provider calls made after the restore point** | The cost ledger under-counts; the per-video and pilot budgets (D1) could be exceeded without the ledger knowing | Do not release admission until spend is reconciled against each provider's own usage (the provider-side spend limits set under 08 §3.4 are the backstop). The reconciled figure is written as an explicit adjustment entry (S4 owns the form), never by editing history |
| **A video uploaded or published after the restore point** (3C; none in 3A) | The DB may lack the `IN_PROGRESS`/`COMPLETED` idempotency key and replay the publish, creating a **duplicate video** | Before any `publish.*` / `upload.*` task is allowed to run, a **human reconciles the channel's actual uploads** against the restored jobs (the "reconciliation procedure" of 03 §9.1 item 3 / 07 §11, owned by Agent 13). These tasks stay `OPERATOR_PAUSE` until reconciled. No unapproved video is ever published (rule 5) |
| **YouTube quota already used that Pacific day** (YT-03) | Wrong quota arithmetic | Resume after the next quota reset or re-read usage from the provider console; never assume the restored counter is right |

Also: revoked sessions, rotated passwords and revoked OAuth tokens come back as they were at the restore point. Step 9 of §7.2 re-applies the rotation; an OAuth token revoked after the restore point simply fails to refresh and moves the channel to `NEEDS_REAUTH` (08 §6.5), which is the safe outcome.

---

## 8. VPS-restart recovery [3A · Tier 0-3]

This section is the operational view of contracts that already exist: 07 §8.4, §6, §10; 10 §9.1, §9.3 rule 3, §5.2 rule 6.

### 8.1 What happens by itself
| Event | Mechanism | Result |
|---|---|---|
| Host or container restarts | container restart policy per service (10 §5.2 rule 6); start order and gates (10 §9.1) | `postgres` first, `migrate` (a no-op if current), orchestrator + reaper, workers, API |
| A task was running | temp file never renamed (07 §8.4); lease expires (default 60 s, 07 §6); `INFRASTRUCTURE.HOST_RESTART` / `WORKER_LOST` | resumed from the latest checkpoint at the next window (07 §8.4, §10); completed effects are skipped via `completed_effects` |
| Restart inside market hours | market-hours guard binds start, not only run (10 §9.3 rule 1) | `HEAVY_CPU` workers stay idle; no render starts |
| Restart outside the night window on the shared VPS | night-window guard (10 §9.3 rule 2) | no heavy claim until the window opens; tasks wait (`DRAIN`/`RETRY_WAIT` times shift to the next opening, 07 §8.5) |
| Database restarts | `INFRASTRUCTURE.DB_UNAVAILABLE`: workers stop claiming until it is back (07 §2); the orchestrator is stateless between transactions (07 §10) | resumes from DB state; L3 only if the outage exceeds `infra.db_outage_alert_ms` |
| Restart during an upload (3C) | checkpoint + idempotency key + reconciliation (07 §11) | single video, no duplicate |

### 8.2 What an operator checks after an unplanned restart (checklist, S5 shows the signals)
1. All factory services healthy in 10 §9.1 order; no non-factory container touched (10 §9.4).
2. Free disk on the storage and backup-staging volumes; no `RESOURCE.DISK_FULL`.
3. `backup_age_*` and the last backup status: a restart during the backup run leaves a partial staging set; the next run starts clean and the partial set is discarded, never uploaded as complete.
4. Reaper activity: expired leases recovered; the DLQ contains nothing unexpected (07 §5).
5. Audit chain verification of the day ran or is re-run.
6. Window status: how many nights of work are pending; the owner is told when a night was lost (§12.4).

### 8.3 Database crash recovery
The database's own crash recovery (replaying its write-ahead log after an unclean stop) is a property of PostgreSQL and its durability settings. The official documentation of the chosen version and the settings the factory uses is **REQUIRES REVIEW (Phase 1)** (§2); this document does not describe or rely on its internals. The factory's side of the contract is: every state change is one DB transaction (07 §8.1), and the stop order ends with a clean `postgres` shutdown (10 §9.2 step 7).

### 8.4 Planned restarts
Use the stop order of 10 §9.2: stop admission, drain to checkpoint, stop workers, run or confirm the backup, stop `postgres` last. A planned reboot is preceded by a backup when one is not already current.

---

## 9. Credential recovery [3A · Tier 0-3]

**Principle (08 §3, D1).** The environment's secret mechanism is the single source of truth. Secrets are never in git, logs, shared environment variables, the database in clear text, or the backup set. The recovery of a credential is therefore always **re-provisioning**, not restoring.

### 9.1 Inventory and recovery action (names only; 08 §3.2 owns the list)
| Secret class | Used by | If lost or exposed | Impact if unrecoverable | Scope |
|---|---|---|---|---|
| LLM / TTS / stock / image provider keys | adapters | Revoke at the provider first, issue a new key, update the secret mechanism, restart the one adapter service (08 §3.3, §12.3). The **provider-side spend limit** stays in force (08 §3.4) | Provider paused until a key exists | 3A |
| DB credentials (`amw_app`, `amw_readonly`, later `amw_publisher`, `amw_auth`, and `amw_backup` pending CCR) | services | Set new passwords inside the database through the migration/admin path, update the secret mechanism, restart services in 10 §9.1 order | Platform down until set | 3A |
| `amw_migrator` credential | deploy only (04 §3.1) | Same; it is never present in a running service | Cannot migrate; platform keeps running | 3A |
| **Backup credential** (destination access) | backup job | Create a new credential at the destination; update the mechanism. Backups already stored stay readable with the backup key | No new backups; L3 | 3B |
| **Backup encryption key** | backup job, restore | **No recovery without the owner's offline copy** (§6.6). If both are lost, every existing backup is unreadable; take a new full backup under a new key immediately and record the incident | Total loss of backup history | 3B |
| **KEK for tenant data keys** | `amw_core.crypto` (08 §6.1) | Recover from the owner's offline copy / the secret mechanism's own backup. Without it, wrapped DEKs cannot be unwrapped | Tenant OAuth tokens and webhook secrets unreadable → every channel to `NEEDS_REAUTH`, every webhook re-registered. Media and DB content are unaffected (they are not encrypted by the DEK) | 3C design · T1 live |
| Google OAuth client credentials | Agent 13 | Re-create in the Google Cloud console (owner action) | Publishing blocked until re-created | **3C only** (D1) |
| Per-channel OAuth tokens (tenant data) | Agent 13 | Re-consent flow: `NEEDS_REAUTH` (08 §6.5) | Tenant must reconnect | 3C · T1 |
| Webhook signing secrets, SCIM tokens | S12 / S9 | Rotate and re-issue to the tenant (08 §7) | Integration re-setup | T3 |
| Owner accounts (VPS panel, provider consoles, git host, domain, e-mail) | the owner | **Outside the factory.** Provider-side recovery with MFA recovery codes held by the owner offline | The owner can lose control of the machine or the repository | Owner action, T0 |

### 9.2 Restore and credentials together
A restore (§7.2 step 3) needs the secrets **before** any service can start; the order is: secret mechanism available → configuration → postgres → restore. If the secret mechanism itself lives only on the lost machine, its content must be recoverable from the owner's offline copy; **where the mechanism lives for the VPS is REQUIRES REVIEW (Phase 1): secret-delivery ADR** (08 §3.1 rule 1). The DR design requires one property of that ADR: *the platform's secrets can be re-created on a new machine without the old machine*.

### 9.3 KEK / data-key discipline (3C, Tier 1)
Wrapped DEKs live in the DB (and are in every backup); the KEK is outside it (04 §5.19, 08 §6.1). A DB backup alone therefore never allows decryption, **and a KEK that exists only on the lost machine makes tokens permanently unreadable**. The KEK must have an independent offline copy before the first client token is stored. Rotation re-wraps DEKs (08 §6.4) and the offline copy is updated at the same time.

### 9.4 After a suspected compromise
Treat every secret that was on the affected machine as exposed: revoke at the provider first, then replace (08 §3.3); the incident process in 08 §12 applies; a restore after a security incident also rotates database role passwords and invalidates sessions (§7.2 step 9).

### 9.5 Source repository
Code, prompts, evals and documents are recovered by cloning the repository. Protecting the git account (MFA, recovery codes) is the owner's action; branch protection and secret scanning are 08 §10. The **private** method repositories named in REPO_MAP are not part of this system's backup and are not described here.

---

## 10. Per-tenant export and restore (§1C.10, §1C.11) [3C · Tier 1 gate]

At Tier 0 the single tenant is the platform owner's organisation; the same exporter is exercised on it so that the Tier 1 gate ("tested per-tenant export and restore") is not a first run.

### 10.1 Export bundle (output of a `data_requests` row, kind `EXPORT`; 04 §5.24)
| Part | Content | Source |
|---|---|---|
| Database export | every row of every `TENANT`-scope table filtered by `org_id`, under the tenant context, in a documented, versioned layout (CSV and/or JSON) | 04 §5.24 "every row of the org" |
| Blobs | the tenant's whole storage prefix (`list_prefix`, ADR-005 §3.1) | 03 §8 rule 1 |
| Audit export | CSV/JSON including `seq`, `prev_hash`, `row_hash` so the recipient can verify independently (08 §9.3 item 4) | 04 §5.13 |
| Manifest | every file with SHA-256 and size; schema version; export time; the org's chain head | design file |
| **Excluded** | secrets and token ciphertext (`tenant_data_keys.wrapped_key`, OAuth/webhook `*_ct` columns), other tenants' data, platform-private rule-pack source if not the tenant's | 08 §6; rule 9 |

The bundle is written to `exports/<dtr>/` (03 §8 areas) and is itself a blob (write-once, hashed, backed up). **How the tenant receives it** (single-purpose expiring link, size limits, encryption of the bundle in transit) is REQUIRES REVIEW (Phase 1): 22 and 08 §5.4.

### 10.2 Restore from a bundle
A bundle restores a tenant into (a) the same platform after a loss (§7.3) or (b) a **dedicated single-tenant stack** built with the same migrations (04 §8 rule 4; 10 §11). It is the offboarding and the "premium dedicated option" path (§1C.1). Because a bundle contains no wrapped keys, restored tenants get **new** data keys and must re-consent OAuth channels.

### 10.3 Export is not a backup
The export is for the tenant's portability and recovery of a single tenant; it does not replace the platform backup (it excludes the platform tables and secrets). Both exist.

### 10.4 Offboarding
Export, owner/tenant confirmation, then erasure (`delete_prefix(org)` behind the data-request workflow, ADR-005 §3.1) and DEK destruction (08 §6.6); `org_status` follows `OFFBOARDING` → `DELETED`. Backup copies age out (§6.7).

### 10.5 Erasure ledger across restores
Because a restore can bring back a tenant that was erased after the backup, the completed `ERASURE` data-request IDs are written outside the database with each backup run (§6.5). After any restore, the runbook step "re-apply erasures" compares this list with the restored `data_requests` rows and re-executes the erasure for any missing one before the platform is released (inserted into §7.2 before step 12 at Tier 1+; **proposal**, with the legal effect for the lawyer ⚖).

---

## 11. Restore tests [3A design / 3B first live / 3C scheduled · Tier 0-3]

> A backup that has never been restored is not a backup. The status of a backup set is `UNVERIFIED` until DR-T1 and DR-T2 have passed on **that** set.

| ID | Test | Pass criteria | Evidence kept | Scope · tier |
|---|---|---|---|---|
| DR-T1 | **Blob restore + hash**: restore a sample (and always all `renders` blobs) into a scratch root | every SHA-256 equals the DB value / manifest; none missing | hash report | 3A (dev, synthetic) · 3B live · T0 |
| DR-T2 | **DB restore into a scratch database** (never the live one) | restores without error; schema version matches; RLS catalogue check (04 §3.7.6) passes; the cross-tenant suite (04 §3.7) passes; row counts of key tables equal the dump manifest | run log, counts | 3A · 3B live · T0 |
| DR-T3 | **Audit chain vs head copy** (08 §9.3) on the restored data | every org's recomputed head equals the copy; a deliberately truncated copy is detected (negative test) | verification output | 3A · T0 |
| DR-T4 | **Single-tenant restore** (§7.3) of a synthetic tenant while a second tenant exists | tenant A restored to the pre-damage state; tenant B's rows and blobs byte-identical before/after; cross-tenant read returns nothing | diff report | 3C · T1 gate |
| DR-T5 | **Full rebuild drill on a clean machine** (S5): from the repository, the secret mechanism, the offline key copies and the off-server backup only | platform runs a canary job; total elapsed time **recorded as the measured RTO**; gaps in this document are filed as corrections | timed log | 3B (on the dev environment) · Tier 1 on the own server · repeated per tier |
| DR-T6 | **Credential-only access**: backup access using only credentials from the secret mechanism | works; no secret found in the backup set by the secret scan | scan output | 3B · T0 |
| DR-T7 | **Key-loss tabletop** (S11): walk the offline-copy procedure with the owner | owner can show where the offline copies are, without revealing them here | note (no secret) | 3B · T0; repeated at T1 for the KEK |
| DR-T8 | **Kill and restart tests** (07 §12): kill during render, during DB write, container restart, host-restart simulation | resume from checkpoint; no corrupt file at a final path; no duplicate side effect; market-hours guard holds on start | test report | 3A (blocking) · T0 |
| DR-T9 | **Post-restore hold test**: restore an older dump while a later (simulated) provider spend and a later (fake) publication exist | admission stays paused until spend reconciled; publish tasks stay held until the reconciliation step is recorded | test report | 3A for spend; 3C for publish |
| DR-T10 | **Disk-full test**: fill the storage volume in a test deployment | `RESOURCE.DISK_FULL` pauses heavy admission; no partial file at a final path; deliverables not deleted | test report | 3A |

**Cadence (proposal; owner sets, REQUIRES REVIEW (Phase 1)).** DR-T1/T2/T3 on every new backup *kind* and then on a regular schedule in the night window (the interval is a configuration value); DR-T5 before the first external client, after every host move and whenever the architecture of the backup changes; DR-T4 before the first external client and after every schema change that touches tenant export. Restore tests are scheduled by S6 and results are shown by S5; **a missed or failed test is an alert, not silence** (§6.8). Scratch restores run only inside the factory's resource limits and never in market hours on the shared host.

---

## 12. Recovery objectives per tier and plan [stated, not promised · Tier 0-3]

### 12.1 What may and may not be said
1. The factory shares one VPS with other applications (INF-01; §1). **No availability percentage, uptime guarantee or "high availability" claim is made at Tier 0, 1 or 2.** (§1C.11.)
2. A promise is published only if (a) the infrastructure can meet it, (b) a rehearsal measured the underlying time, and (c) the owner approved it (§1C.11; 10 §13).
3. Objectives are stated in terms of **what is lost and how long recovery takes**, not "the service is always up".
4. The platform is by design a **batch production system**: the night window is 00:00–07:00 IST with admission closing at 06:30 (06, 07 §8). An outage in the daytime has no effect on production; an outage in the window delays work to the next window (§8.1). Statements to clients are therefore in **windows and deliverables**, not in hours of uptime **(proposal)**.

### 12.2 Objectives by tier (the "plan" mapping)
The pricing plans do not exist yet (`plans` is Tier 2 and 21_PRICING_AND_PACKAGING.md is a PROPOSAL, planned). Until they do, "plan" means the **service class implied by the tier gate** (§1C.15). When 21 fixes the plan names, each plan maps to exactly one row here; a plan never gets an objective better than the infrastructure of its tier has been measured to give.

| Tier / service class | Infrastructure (§1C.14, 10 §13) | DB RPO (proposal) | Blob RPO (proposal) | RTO | What is stated to the customer |
|---|---|---|---|---|---|
| **Tier 0** — owner's own channels | shared VPS, one machine | **Not committed.** Design proposal (ESTIMATE): not worse than the backup interval, one nightly dump | blobs: until the next incremental copy after job completion (§5.3) | **Not committed.** Measured by DR-T5 and recorded as information only | Nothing external. Internal: "recoverable from the last verified backup; lost work is regenerable at the cost of the paid calls" |
| **Tier 1** — first managed-service client | **own server**, tested per-tenant restore/export (§1C.14, 10 §13) | measured dump interval, shorter than Tier 0 (value from DR-T2 and growth); continuous-copy option evaluated (§3 rule 3) | after each completed job (event-driven, §5.3) | **measured value from DR-T5 on the own server + margin**; until measured: not committed | "Backups off-server, restore tested [last test date]. Recovery objective: [measured figure, rehearsed]." Best-effort support, no uptime percentage |
| **Tier 2** — self-serve plans | same server class, quotas | per plan: **plan-level**, tied to the backup frequency that plan's price covers | same | per plan: measured, never better than Tier 1's measured figure | as Tier 1 plus the plan's stated retention and export rights |
| **Tier 3** — enterprise / dedicated stack | dedicated single-tenant stack or workers (10 §11) | **contractual, from measurement** | **contractual** | **contractual, from measurement on that stack** | A **formal SLA only after** the external pen-test and measured RTO/RPO (§1C.11, §1C.13; 10 §13); any availability figure additionally needs a redundancy design that is **not** part of this document: REQUIRES REVIEW (Phase 1) |

Figures marked "proposal" are inputs to the owner's decision, not commitments.

### 12.3 RTO build-up (what the DR-T5 stopwatch must split)
Detect → decide (owner availability: the platform is operated by one person; no response time is promised at Tier 0–2, §14.2) → provision (if S5; owner purchase, rule 8) → fetch backup → restore DB → restore blobs → verify (§7.5) → release holds (§7.6) → canary. DR-T5 records each leg; the stated RTO is their sum with a margin, and the **longest leg is reported to the owner** because that is where to invest.

### 12.4 Honest limits
| Limit | Consequence |
|---|---|
| One machine, one provider account | A whole-machine failure means a rebuild (hours at best), not a failover. The fix is a second machine or a standby, recommended (never purchased) when a paying client needs better (rule 8, §1C.15) |
| One operator | Recovery depends on the owner being reachable; no 24/7 response is promised |
| Shared with other apps | Contention can slow or stop the factory (the factory is the lowest-priority tenant of the host by design, 05 §5); the factory does not protect the other apps, and they do not protect the factory |
| External dependencies | LLM, TTS, stock, storage and YouTube outages are handled by breakers, retries and DLQ (07 §3-§5), not by DR. Their availability is the provider's |
| Backup is only as good as its last test | §11 |
| Window-bound work | A lost night is lost capacity, not lost data; the owner is told (§8.2) |

---

## 13. Health checks and status page [3C · Tier 0-3]

### 13.1 Health checks (S5; REQUIRES REVIEW (Phase 1): stack per ADR-006)
| Check | Kind | Fails when |
|---|---|---|
| Liveness per service | process up, heartbeat fresh (workers: 3 × `heartbeat_ms`, 07 §6) | process dead / heartbeat stale |
| Readiness | DB reachable; storage root writable (a canary write-once object); queue claim works | any of them fails (`INFRASTRUCTURE.DB_UNAVAILABLE`, `STORAGE_UNAVAILABLE`) |
| Disk | free space on storage, backup-staging and DB volumes vs threshold (05 §6.4) | below threshold → heavy admission paused |
| Backup freshness | `backup_age_db`, `backup_age_blob`, `audit_head_copy_age` | older than configured limit |
| Restore-test freshness | `restore_test_age`, last result | too old or last failed |
| Audit verification | last daily chain verification result (08 §9.3) | not run or mismatch (L3 security) |
| Window state | window open/closed, drain flag, market-hours guard | informational |
| Spend state | budget headroom (S4), provider breakers (07 §4) | informational / alerts |

Checks never expose tenant data; metrics carry `org_id` only where tenant-scoped (§1C.1).

### 13.2 Status page
| Tier | Design |
|---|---|
| **Tier 0** | No public page. The owner's dashboard (3C, `16_COMMAND_CENTER.md` planned) shows the signals above; a notification (S7) reaches the owner |
| **Tier 1+** | A **separate, independently hosted** status page: it must stay reachable when the factory machine is down, so it cannot run on the factory VPS. It is updated **by hand by the owner** (a deliberate single-operator choice), with an optional automatic "factory unreachable" probe from outside. Hosting and product: REQUIRES REVIEW (Phase 1) and the owner's purchase decision (rule 8) |

Content: component status (production line, review portal, publishing), **planned maintenance** (the night window), current incident with plain-language impact, the time of the next update. **Never** published: tenant names, technical error details, security internals, credentials, hostnames (08 §11). Past incidents stay listed with their post-incident summary.

---

## 14. Incident process (availability and data loss) [3A drill · 3C live · Tier 0-3]

Security incidents follow **08 §12** (detect, triage, contain, eradicate, recover, notify, review); the signals, severity routing and playbooks there are binding and are not repeated. This section adds the DR-specific parts. Escalation levels are L1-L3 of 07 §7; **no new severity scale is created**.

### 14.1 Declaring a disaster
A **disaster** is declared by the Platform Owner when any of S3-S7, S10, S11 (§7.1) occurs, or when an L3 operations alert on storage, database or disk persists beyond its configured limit. Declaration starts the RTO clock and the incident record.

### 14.2 Phases and roles (single-operator reality)
| Phase | Action | Output |
|---|---|---|
| 1 Detect | S5 signal, tenant report, owner observation | alert ID / first-seen time |
| 2 Declare | Platform Owner decides: stop admission (`admission_paused`) and, if integrity is in doubt, `platform_emergency_stop` (04 §5.1) | incident ID in the private incident log |
| 3 Assess | what failed; **data-loss window** (time of the last verified backup vs now); which tenants; whether personal data or credentials are involved (then 08 §12 phase 6 applies ⚖) | assessment note |
| 4 Communicate (first) | status page (Tier 1+) and tenant Org Owners: what is affected, that data recovery is in progress, next-update time; **no cause guess, no promised finish time** | notice |
| 5 Recover | §7.2 / §7.3 / §8 / §9 as applicable | runbook proof |
| 6 Verify | §7.5 and §7.6 | verification output |
| 7 Close | release holds; canary; resume admission; final notice stating the **actual data-loss window** and what must be redone | closing notice |
| 8 Review | blameless review in a period the owner sets (08 §12.2); the new test or control is added (§11 or 27 §6); corrections to this document are filed | review note |

The roles are the platform's: **Platform Owner** (decides, communicates), tenant **Org Owner** (receives), S7 (delivers). No on-call rota exists and none is promised; **response and acknowledgement targets are owner-set (REQUIRES REVIEW (Phase 1); 08 §12.1) and must not exceed what one person can honour**.

### 14.3 Client notification content (Tier 1+)
Plain language: what is affected; since when; what data window may be lost; what the client must do (re-approve, re-connect a channel, nothing); next-update time; contact. Legal notification duties for personal-data incidents (DPDP; IN-07: breach rules apply in the Rules' later phase, about May 2027 per 08 §12.2) are for the lawyer ⚖ — the platform acts as processor for client data (§1C.10).

### 14.4 Incident record
A private incident log (not in this repository, 08 §11): ID, times (detect, declare, recover, close), scenario code (§7.1), data-loss window, tenants affected, actions, who decided, links to evidence, review outcome. No secret, no tenant content. **Where it lives is REQUIRES REVIEW (Phase 1)**; a table for it would need a CCR and is not proposed because the log must stay readable when the database is the thing that failed.

### 14.5 Drills
The DR drill is DR-T5 plus one tabletop (S5 and S11) before the first paid call that creates a kept output (3B) and before the first client (Tier 1); the security drill is 08 §12.4. Both use synthetic data.

---

## 15. Scope summary

| Capability | 3A | 3B | 3C | Tier |
|---|---|---|---|---|
| Atomic write, write-once, hash check, persistent media rule, resume after restart (§5, §8) | design + tests DR-T8, DR-T10 | yes | yes | 0 |
| Delivery as downloadable files; outputs disposable until backup (§5.2) | **yes** | — | — | 0 |
| Backup/restore **design**, restore tests on synthetic data in the development environment (DR-T1-T3) | **yes** | — | — | 0 |
| Off-server destination configured; first verified backup and restore test; credential-only access; key-loss tabletop | — | **yes (before the golden samples are kept)** | — | 0 |
| Blob/DB/config/head-copy backup job scheduled in the night window; health signals; dashboard display | — | manual | **yes** | 0 |
| Per-tenant export/restore (DR-T4), erasure ledger | — | — | design + build | 1 gate |
| Own-server rebuild drill DR-T5 with measured RTO | — | on the dev environment | **before the first client** | 1 |
| Status page; client notifications | — | — | design | 1 |
| Plan-level objectives; per-plan retention | — | — | — | 2 |
| Dedicated stack DR, contractual objectives, formal SLA | — | — | — | 3 |

---

## 16. Contract requests (pending CCR; not edited into Wave A or B-1 here)

| # | Needed | Reason | Proposed change | Target |
|---|---|---|---|---|
| 1 | `sys_backup` SYSTEM actor name | Backup, restore-test and head-copy actions need an `actor_ref` that is not an agent, service or human; GLOSSARY §2.3 allows only `scheduler`, `reaper`, `dlq_handler`, `migrator`, `api` | Add `backup` to the `sys_<name>` set and to the actor_ref regex note | GLOSSARY_AND_IDS.md |
| 2 | `amw_backup` database role | A dump by `amw_app`/`amw_readonly` returns no rows because RLS applies (INF-11); a backup needs a read-only role with `BYPASSRLS`, used only by the backup job | Add to 04 §3.1: login, no owned objects, `SELECT` on all tables, `BYPASSRLS`, never granted to services | 04_DATABASE_ARCHITECTURE.md |
| 3 | Error codes `INFRASTRUCTURE.BACKUP_FAILED`, `INFRASTRUCTURE.BACKUP_STALE`, `INFRASTRUCTURE.RESTORE_TEST_FAILED` | The 07 catalogue has no code for a failed or stale backup or a failed restore test; they are operations signals routed to the Platform Owner | Add to 07 §2 with disposition RETRY next window for `BACKUP_FAILED`, L3 (operations) for the other two; no job-state effect except the Tier 1+ admission rule of §5.3 item 5 | 07_FAILURE_MANAGEMENT.md |
| 4 | `backup_runs` table (GLOBAL scope, ID prefix `bkr`) with enums `backup_kind` (`DB`, `BLOB`, `CONFIG`, `AUDIT_HEADS`, `RESTORE_TEST`) and `backup_run_status` (`RUNNING`, `SUCCEEDED`, `FAILED`) | S5 and the dashboard need last-success time, size and verification state without reading the off-server destination; per-tenant exports use the existing `data_requests` | One table: `kind`, `status`, `started_at`, `finished_at`, `size_bytes`, `manifest_sha256`, `verified_at NULL`, `error_code NULL`, `schema_version`; no tenant content; append-only | 04 and GLOSSARY |
| 5 | Audit action names `backup.completed`, `backup.failed`, `restore_test.completed`, `restore_test.failed`, `restore.performed` | 08 §9.2 (S6) owns the list of audited events | Add to the list | 08_SECURITY.md (Wave B-1) |

Use of these names in this document is marked **(pending CCR)** and is conditional on their approval; if rejected, the matching design item (§6.1 item 6, §6.2, §6.8, §5.3) is re-expressed with existing names.

---

## 17. Open items (all REQUIRES REVIEW (Phase 1) unless stated)

1. Backup destination, tool, encryption method, interval, retention, price; owner purchase decision (ADR-005 §3.4; R10).
2. Whether a continuous database copy (write-ahead-log archiving) is offered by the chosen tool and affordable (sets any DB RPO below one interval).
3. VPS audit (A1): free disk, I/O, size per finished video; staging-volume cap; log rotation.
4. Official PostgreSQL durability and crash-recovery documentation for the chosen version (RESEARCH_LOG entry).
5. Where the secret mechanism lives on the VPS and how it is re-created on a new machine (secret-delivery ADR; §9.2).
6. Location and credential separation of the audit-head copy and the erasure ledger (08 §9.3; §6.5).
7. Retention periods for backups, audit, personal data; erasure vs backup statement (22; lawyer ⚖).
8. Status-page hosting and product; incident-log location (§13.2, §14.4).
9. Owner-set acknowledgement targets that a single operator can honour (08 §12.1).
10. Measured RTO/RPO: DR-T5 on the development environment (3B) and on the own server (Tier 1).
11. Whether provider-side snapshots exist and are usable as an additional convenience copy (not a substitute for §6).
12. Tenant export delivery method and bundle layout version (22; 08 §5.4).
13. Owner approval of factory-side copies of the knowledge sources (KNOWLEDGE_LIBRARY_PLAN.md K8), which decides whether A8 enters the backup set.

---

## 18. Revisit triggers
1. The VPS audit (A1) delivers real disk/I/O figures (sets staging cap, backup window length).
2. The first DR-T5 result (replace every "not committed" with a measured figure).
3. A backup tool and destination are chosen (fills §6).
4. ADR-012 puts the render worker on a second machine (blob path and D1/D2 definition, §5.1 item 4).
5. First external client (Tier 1): own server, status page, DR-T4, DR-T5, contractual wording.
6. Any change to the secret mechanism, KEK handling (08 §6) or erasure rules (22).
7. 21_PRICING_AND_PACKAGING.md approved: map each plan to a row of §12.2.

---

## 19. Cited research IDs
INF-01, INF-03, INF-11, IN-07, YT-03. Every other external fact (backup tools, object storage, status-page products, database durability behaviour, provider snapshot behaviour) is **REQUIRES REVIEW (Phase 1)** because no entry exists in RESEARCH_LOG.md.
