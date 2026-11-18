# ADR-005 — Storage interface: S3-compatible API, local disk first, off-server backup from day one

| Field | Value |
|---|---|
| Status | **Proposed** (documentation). Software: **Planned** |
| Decider | Owner (Abhi), on the lead's recommendation; any paid backup/object-storage service needs the owner's purchase decision (rule 8) |
| Depends on | 03_COMMUNICATION_STANDARD.md §5.3 (success rule), §8 (storage URIs), §9 (idempotency); 04_DATABASE_ARCHITECTURE.md §1.6, §3.7.8, §5.18, §7; 07_FAILURE_MANAGEMENT.md §2, §8.1, §10; GLOSSARY_AND_IDS.md (Storage URI); 00b_TECHNICAL_FEASIBILITY.md §2.3; SOURCE_LAYOUT.md (`amw_core/storage/`) |
| Directive sections covered | §3.2a (storage behind an S3-compatible interface, local disk backend first, object storage later, off-server backup from day one); §1 Deployment isolation (own volumes, storage, backups); §3.3 Disaster recovery, Migration (external storage config); §1C.10, §1C.11 (per-tenant export/erasure, tested restore) |
| Research IDs | None of the storage/backup products is researched yet (see §2). INF-01 (disk size of the current plan) only. |
| MVP scope | Interface + local-disk backend + tenant check + SHA-256 verify: **3A**. Off-server backup: **3A prerequisite** before the first run whose outputs must be kept (see §3.4). S3-compatible object-storage backend: **3C** (or earlier if ADR-012 moves the render worker off-server). |
| Enterprise tier | Tier 0 local disk + backup → Tier 1 per-tenant export/restore test (§1C.11) → Tier 3 dedicated stack with its own storage root (04 §8.4) |

## 1. Context
- Large content (scripts, media, licence documents, tracebacks, Task Input/Output documents) lives in storage; the DB stores the URI + SHA-256 (04 §1.6).
- URIs are tenant-scoped and fixed by 03 §8: `amw-blob://<org wire id>/<area>/<path>`, `amw-blob://platform/<area>/<path>` (read-only), and `amw-entity://…` for DB rows; GLOSSARY example `amw-blob://org_…/jobs/job_…/renders/rnd_….mp4`. Areas are listed in 03 §8.
- 03 §8 rules: (1) `amw_core.storage` maps a URI to the backend as `<root>/<org uuid>/<area>/<path>`, org segment first, so one tenant = one prefix for export/erasure; (2) blobs are write-once, final media is never only in temp; (3) the reader checks URI org = `app.org_id`, else `PERMANENT.CROSS_TENANT_REF` + L3; (4) every consumed input carries a SHA-256 the reader verifies.
- 07 §8.1: atomic write unit = write a temporary file in the same storage area, flush, atomic rename to the final write-once path. A killed process leaves no corrupt file at a final path (07 §8.4).
- 03 §5.3: `SUCCEEDED` requires every `output_refs[]` object to exist with the stated SHA-256 and size, else `AGENT.INCOMPLETE_OUTPUT`; a hash/size mismatch is `AGENT.CORRUPTED_OUTPUT` (07 §2).
- Storage failures: `INFRASTRUCTURE.STORAGE_UNAVAILABLE` (RETRY, L1 → L3), `RESOURCE.DISK_FULL` (SUSPEND `OPERATOR_PAUSE`, heavy admission paused, L3) (07 §2).
- The current server plan has 100 GB NVMe shared with the existing apps (INF-01). Free space and size per finished video are REQUIRES REVIEW (Phase 1) (00b §2.3; VPS audit pending, A1).
- 3A delivers MP4, thumbnail options, SRT, QC report and cost-per-stage report as downloadable files (D1). Those are blobs under `jobs/<job>/…`.

## 2. Options considered (with evidence)

| Option | Fits 03 §8 / 07 §8.1 | Resident footprint on shared VPS | Cost | Evidence status |
|---|---|---|---|---|
| **A. Own interface (S3-compatible operations) + local-disk backend now; object-storage backend later by configuration** | Yes: rename is native on one file system; prefix = directory | None beyond the disk | Disk only | Directive §3.2a states this path; no external fact needed for the local backend |
| B. Self-hosted S3-compatible server on the VPS from day one | Yes via the S3 API; the atomic-write equivalent must be checked | Adds a resident service, against the §1 reasoning used for the queue (avoid extra resident services) | Disk only | **No RESEARCH_LOG entry.** REQUIRES REVIEW (Phase 1): product, licence, RAM footprint (measured), if ever proposed |
| C. External object storage as the primary store from day one | Yes via the S3 API; atomic-write equivalent must be checked | None | Paid per GB/requests | **No RESEARCH_LOG entry.** REQUIRES REVIEW (Phase 1): provider, region, price, egress, S3-compatibility; owner purchase (rule 8) |
| D. No interface; agents write paths directly | **No**: breaks rule 1/3 of 03 §8 and §3.3 Migration | None | — | Rejected by contract |

## 3. Decision (Proposed)

### 3.1 Interface (`amw_core.storage`, one implementation per backend)
Operations, all taking an `amw-blob://` URI and running inside a tenant context:

| Operation | Behaviour (contract source) |
|---|---|
| `put(uri, stream) → (sha256, size_bytes)` | Refuses if the URI's org ≠ `app.org_id` (`PERMANENT.CROSS_TENANT_REF`, 03 §8.3; 04 §3.7.8) or the path already exists (write-once, 03 §8.2). Writes temp → flush → atomic publish to the final path (07 §8.1). Computes SHA-256 while writing. |
| `get(uri, expected_sha256) → stream` | Tenant check (03 §8.3); verifies SHA-256 and size; mismatch → `AGENT.CORRUPTED_OUTPUT` (07 §2). `platform` URIs are read-only (03 §8). |
| `head(uri) → (exists, sha256, size_bytes)` | Used by the 03 §5.3 success rule before `SUCCEEDED`. |
| `list_prefix(org, area)` | Export of one tenant / one job (§1C.10, `exports/<dtr>/`). |
| `delete_prefix(org)` | Tenant erasure/offboarding only, behind the data-request workflow (04 §5.24, Tier 1); never used by agents. Finished media is otherwise kept until the tenant deletes or offboards (04 §7). |

- Backend choice, root path and credentials come only from configuration and the environment's secret mechanism (D1, §3.3 Migration, S6); none are in the repository. No server paths are written in public docs.
- The local backend's `<root>` is a factory-owned volume inside the factory's own Compose project (§1 Deployment isolation).
- Physical mapping follows 03 §8 rule 1 (`<root>/<org uuid>/<area>/<path>`). The mapping for `amw-blob://platform/…` is not stated in 03 §8; this ADR uses `<root>/platform/<area>/<path>` **(pending CCR)**.

### 3.2 Backend order
1. **3A: local disk** (option A).
2. **Object storage backend (S3-compatible):** added when one of the revisit triggers fires (§6), chosen by a researched provider entry in RESEARCH_LOG.md and owner approval. Code above the interface does not change (§3.3 Migration).
3. For the S3 backend, the equivalent of the atomic rename (upload complete before the object becomes visible at the final key) and the write-once guarantee must be verified against the chosen provider's official documentation: **REQUIRES REVIEW (Phase 1)**.

### 3.3 Integrity and disk safety
- Every `renders` row stores `storage_ref` + `content_sha256`, `UNIQUE (org_id, content_sha256)` (04 §5.18); every Task Output blob carries a SHA-256 (03 §8.4).
- Temporary files that were never published are removed by a cleanup task; they never count as outputs (07 §8.4).
- Admission checks free disk space before `HEAVY_CPU` work; the threshold is configuration in 05 (value REQUIRES REVIEW (Phase 1): from the VPS audit `df` output and measured size per video, 00b §2.3). On a write failure for lack of space: `RESOURCE.DISK_FULL` (07 §2).

### 3.4 Off-server backup from day one
- **What:** the factory database (logical dump) and configuration (without secrets), and every blob under the storage root (finished masters, renders, assets, licence documents, consents, evidence). Secrets are backed up only through the environment's secret mechanism, never in the backup set.
- **Where:** a destination outside the machine that runs the factory. **REQUIRES REVIEW (Phase 1): backup destination, tool, encryption method, price, and the owner's purchase decision (rule 8).** No product is chosen in this ADR because none is in RESEARCH_LOG.md.
- **Rules:** encrypted before it leaves the machine (key via the secret mechanism); per-tenant prefixes preserved so one tenant can be restored or exported alone (§1C.11); backup runs only inside the factory's resource limits and never touches other apps' volumes (§1 Deployment isolation).
- **Restore test:** a scheduled restore into a scratch database/root, with SHA-256 verification of a sample of blobs and the audit-chain check (§3.3 Disaster recovery). Frequency, RPO and RTO: **REQUIRES REVIEW (Phase 1)** (owner sets them; 10_DEPLOYMENT_AND_MIGRATION.md records them).
- **3A:** the first run whose outputs the owner must keep (3B golden samples at the latest) requires the backup destination to be configured; until then 3A outputs are delivered as downloadable files (D1).

## 4. Consequences
- **Positive.** Contracts 03 §8 and 07 §8.1 are met with no extra service; tenant isolation is enforced at the storage layer as well as in the DB (rule 9, 04 §3.7.8); moving to object storage is a configuration change.
- **Negative.** Local disk ties blobs to one machine. A render worker on another machine (ADR-012) cannot read or write the local root directly; it needs the object-storage backend or another access path (see ADR-012 §4).
- **Disk pressure.** 100 GB is shared with other apps (INF-01). Retention of intermediate blobs (non-final attempts) is configuration; final media is never deleted by retention (04 §7).
- **Tests.** Cross-tenant URI read/write rejected (04 §3.7.8); write-once violation rejected; kill during `put` leaves no file at the final path (07 §8.4); SHA mismatch detected; restore test passes.

## 5. Status
**Proposed.**

## 6. Revisit triggers
1. ADR-012 places the render worker on a machine other than the one holding the storage root.
2. Measured free disk falls below the 05 admission threshold during the pilot.
3. First external client (Tier 1, §1C.14): platform data moves to its own server; storage root moves with it.
4. A backup destination is researched and approved (fills §3.4).

## 7. Cited research IDs
INF-01. (No storage, object-storage or backup product is recorded in RESEARCH_LOG.md; every such fact above is marked REQUIRES REVIEW.)
