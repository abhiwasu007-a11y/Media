# ADR-002 — Tenancy model: shared database + shared schema + `org_id` + FORCE RLS

> **Integrator status (lane B2-1, 2026-11-18).** B-2 draft aligned with main: no upload and no Google OAuth in 3A (D1); the owner works from chat and has no CLI (D5/R14; decisions are recorded by the operator as `OWNER_CHAT_OPERATOR` evidence with a review code, CCR-010/CCR-100); the licensed music source is an open owner decision (D6); the repository is becoming private (D7). Facts without a `RESEARCH_LOG.md` ID carry the label `UNLOGGED` and are **not citable**: each is `REQUIRES REVIEW (Phase 1): log entry (official URL + date)`. Names that no Wave A contract defines are marked `(unfiled CCR)` and listed in `audit/b2_unfiled_ccr_requests_adr_business.md`; this file changes no contract.

| Field | Value |
|---|---|
| Status | **Draft - documentation**. ADR status: **Proposed**. Software: **Planned** |
| Decider | Owner (Abhi), on the lead's recommendation. Any change to tenancy needs the owner (CONTRACT_CHANGE_REQUESTS.md step 3) |
| Owner agent / service | S9 Tenant, Identity & Access (Agent 01; 14_SHARED_SERVICES.md S9). Code: `amw_core.tenancy` (SOURCE_LAYOUT.md) |
| Depends on | 04_DATABASE_ARCHITECTURE.md §1, §2, §3.1–§3.7, §4, §5.1, §5.4, §8, §9; 03_COMMUNICATION_STANDARD.md §7.1, §8; GLOSSARY_AND_IDS.md §2.4, `org_kind`, `role`, tier enum; 07_FAILURE_MANAGEMENT.md (`PERMANENT.TENANT_MISMATCH`, `PERMANENT.CROSS_TENANT_REF`); 08_SECURITY.md §8; 11_TESTING_STRATEGY.md (L5 `tenancy`); 20_MULTI_TENANCY_AND_ENTERPRISE.md §3; 10_DEPLOYMENT_AND_MIGRATION.md §11, §14; ADR-001 (queue); ADR-005 (storage); ADR-012 (render-worker placement, by name) |
| Directive sections covered | §0 rule 9 (tenant isolation is absolute); §1C.1 (tenancy model, hierarchy, `org_id` everywhere, RLS as second line, cross-tenant tests, dedicated option "not a fork"); §1C.2 (fair sharing, via ADR-001 / 05); §1C.15 (tier gates); §3.3 Migration (DB abstraction, workers that can move) |
| Research IDs | INF-11 (VERIFIED). Two official sources checked for this ADR on 2026-11-18 and not in RESEARCH_LOG.md (E1, E2 in §7 are UNLOGGED; **REQUIRES REVIEW (Phase 1): log entry (official URL + date)**) |
| MVP scope | **3A**: the full model (roles, FORCE RLS on every tenant table, `SET LOCAL` per transaction, tenant-composite keys, the 04 §3.7 suite as a blocking CI gate), even with one tenant. **3B**: the same suite re-run on the pilot database. **3C**: tenancy UI, second real tenant, platform cross-tenant summary. |
| Enterprise tier | Tier 0 (platform owner = only tenant, synthetic test org B in tests) → Tier 1 (first client org, same database) → Tier 2 (many self-serve orgs, same database) → Tier 3 (dedicated workers per org, or a dedicated single-tenant stack built by the same migrations) |

## 1. Context

- **Rule 9 and §1C.1.** Tenant isolation is absolute. Every table, queue row, file path, cache key, index, log line and metric carries `org_id`. Application code always filters by tenant explicitly; RLS (`ENABLE` + `FORCE ROW LEVEL SECURITY`, tenant set per transaction) is the second line of defence, never the only one. Automated tests must prove that cross-tenant reads return nothing.
- **§1C (low-cost principle).** Design for enterprise from day one, build enterprise features by tier. Retro-fitting tenancy later is expensive. The first tenant is the platform owner (`organisations.kind = PLATFORM_OWNER`, GLOSSARY); clients come at Tier 1+.
- **Infrastructure.** One shared VPS (2 vCPU / 8 GB, INF-01) running one PostgreSQL instance for the factory (10 §4). Every extra database, server or resident process costs RAM on that machine.
- **PostgreSQL behaviour that the design relies on (INF-11, VERIFIED):** table owners bypass RLS unless the table has `FORCE ROW LEVEL SECURITY`; superusers and `BYPASSRLS` roles always bypass RLS; `SET LOCAL` lasts until the end of the transaction; `current_setting(name, missing_ok)` returns NULL when the setting is missing.
- **Already fixed by Wave A.** 04 §1–§3 already define the shared schema, `org_id NOT NULL` on every TENANT table, roles (`amw_owner`, `amw_migrator`, `amw_app`, `amw_publisher`, `amw_auth`, `amw_readonly`, `amw_sysfn`), `amw_current_org()`, the standard tenant policy, the shared-catalogue policy, the `SECURITY DEFINER` system functions and the cross-tenant CI suite. This ADR records **why** that model was chosen over the alternatives and what it implies for the other ADRs. It does not change 04.
- **Open evidence gap** recorded in 20 §2 and 20 §3.3: the directive's statements that shared-schema + RLS is the "standard default for B2B SaaS" and that schema-per-tenant "bloats the catalog at scale" have no RESEARCH_LOG entry. §2 below records what the official sources checked for this ADR do and do not show.

## 2. Options considered (with evidence)

### 2.1 Evidence used

| Ref | Source (official) | What it states (checked 2026-11-18) | What it does **not** state |
|---|---|---|---|
| INF-11 | PostgreSQL docs: RLS, SET, admin functions | Owner bypass unless FORCE; superuser / `BYPASSRLS` bypass; `SET LOCAL` is transaction-scoped; `current_setting(…, true)` | Anything about tenancy models |
| E1 | Microsoft Azure Architecture Center, "Multitenancy and Azure Database for PostgreSQL" (page dated 2026-11-16) | Comparison of three models. **Server per tenant:** data isolation high, performance isolation high, operational complexity high, resource cost high; the only model that can apply server-level controls (own key, own region, own restore) to one tenant. **Database or schema per tenant:** data isolation medium (database permissions), operational complexity medium ("apply schema changes to each tenant's objects"), cost low-medium; "as your system adds more tenants, the number of databases or schemas increases"; with transaction pooling the app sets `search_path` per transaction with `SET LOCAL`. **Shared tables:** data isolation low ("your application and row security policies separate tenants"), deployment and operational complexity low, cost low, "supports the largest number of tenants"; "set the tenant context within each transaction, and review which roles can bypass row security policies"; backups apply to the whole server, so restoring one tenant means restoring to a new server and copying that tenant's data back. Noisy-neighbour risk for both shared models. | That shared tables are "the standard default for B2B SaaS" (it names B2C SaaS as the common case). A figure for catalogue growth per schema |
| E2 | Microsoft Azure Architecture Center, "Architectural approaches for storage and data in multitenant solutions" (page dated 2026-08-21) | A shared multitenant database "provides the highest density of tenants to infrastructure, so it tends to come at the lowest financial cost" and "often reduces the management overhead because there's a single database … to manage, back up, and secure". Drawbacks: scale limits of one resource, noisy neighbours, per-tenant consumption must be measured by the application, tenants may need different security/backup/location settings. With RLS, "the user's identity and tenant identity [must be] propagated through the application and into the data store with each query", which is "complex to design, implement, test, and maintain". Avoid per-tenant schema customisation and manual schema changes | Same gaps as E1 |

E1 and E2 are vendor guidance for Azure services; the statements used here are about PostgreSQL models in general (roles, schemas, RLS, backups), not about Azure features. No Azure service is proposed.

### 2.2 Comparison

| Criterion | **A. Shared DB + shared schema + `org_id` + FORCE RLS** (04 §1) | **B. Schema per tenant** (one PostgreSQL database, one schema per org) | **C. Database per tenant** (one database per org on the shared server) | **D. Dedicated single-tenant stack** (own DB / server per client; §1C.1 premium option) |
|---|---|---|---|---|
| Data isolation | Low at the engine level (E1): rows are separated by policy. In this design four more layers sit on top: app filter, tenant-composite FKs, storage URIs, cache keys, logs (08 §8; 04 §1.3) | Medium (E1): per-schema permissions | Medium (E1): per-database permissions | High (E1): own server |
| Fails closed when the tenant is not set | Yes: `amw_current_org()` NULL → 0 rows (04 §3.2, INF-11) | Only if the default `search_path` resolves to no tenant objects; REQUIRES REVIEW (Phase 1) if ever chosen | Connection is tenant-bound | Only one tenant exists |
| Extra resident resources on the shared VPS (INF-01) | None | None per tenant beyond catalogue rows; size not measured | Each database adds its own catalogue and connections; not measured | A whole stack per tenant: not affordable on the shared VPS; Tier 3 only |
| Migrations | One run (04 §8) | One run per schema (E1 "apply schema changes to each tenant's objects") | One run per database | One run per stack, same files (04 §8.4) |
| Connection pooling | `SET LOCAL app.org_id` per transaction works with transaction pooling (INF-11; E1 states the same pattern for `search_path`) | `SET LOCAL search_path` per transaction (E1) | A pool per database (E1: PgBouncer pools per user/database pair) | Own pool |
| Queue claim before the tenant is known (ADR-001 constraint 2) | One `task_queue` table + `amw_queue_claim` (04 §3.6) | One queue per schema, or a global queue holding envelopes, which 04 §1.2 forbids | Same as B, across databases | Own queue (same table design) |
| Fair share across tenants (§1C.2, 05 §7.2) | In one claim function | Needs a cross-schema scan | Needs a cross-database scan | Not needed (one tenant) |
| Per-tenant restore | Not by native backup (E1: restore whole server, copy tenant back). This design restores one tenant by per-tenant export/import of rows + one storage prefix (ADR-005, 10 §11, 12) | Per-schema dump possible | Per-database dump possible | Native (E1) |
| Per-tenant key, region, compliance boundary | Per-tenant data key for secrets only (04 §5.19); not per-tenant disk encryption | No | No | Yes (E1: "the only model that can apply server-level controls to a single tenant") |
| Scale at many small tenants (Tier 2) | Largest tenant count (E1) | Schema count grows with tenants (E1). "Catalogue bloat" figure: REQUIRES REVIEW (Phase 1): official source with numbers | Database count grows with tenants (E1) | Not for small tenants (cost high, E1) |
| Main risk | One missing filter or a bypass role leaks data (E1, E2) | Operational drift between schemas (E2: avoid per-tenant schema changes) | Same as B plus more connections | Cost and operations per stack |

### 2.3 Options not considered further
- **Hybrid B + A** (schema per large tenant, shared tables for small ones; E1 notes "a system can implement more than one model"): rejected for Tier 0–2 because it creates two code paths for one contract set (04 is the single source; CCR rule), and no tenant needs it yet. Tier 3 needs are covered by D.
- **Separate database per environment purpose** (e.g. a split analytics database): not a tenancy question; out of scope.

## 3. Decision (Proposed)

1. **Model A is the tenancy model for Tier 0–2** (3A onwards): one PostgreSQL database, one shared schema, `org_id uuid NOT NULL` on every TENANT row, `ENABLE` + `FORCE ROW LEVEL SECURITY` on every TENANT and SHARED-CATALOGUE table, exactly as 04 §1–§3 define it.
2. **Roles (04 §3.1, INF-11).** Objects are owned by the non-login role `amw_owner`; migrations run as `amw_migrator`; every running service connects as a **non-owner, non-superuser, `NOBYPASSRLS`** role (`amw_app`, `amw_publisher`, `amw_auth`, `amw_readonly`). The only `BYPASSRLS` role is `amw_sysfn`, which owns the identifier-only `SECURITY DEFINER` functions of 04 §3.6 and is never granted to a login role.
3. **Tenant context per transaction (04 §3.2, INF-11).** Every transaction starts with `SET LOCAL app.org_id` (and `app.actor`, plus `app.user_id` for human requests). `SET LOCAL`, never session-level `SET`, so a pooled connection cannot carry a tenant into the next transaction. `amw_core.tenancy` refuses a query outside such a transaction; a static check bans raw cursors outside it (11 L5 item 6; 08 §10).
4. **First line stays in code (§1C.1).** Application queries carry explicit `org_id` predicates; the API derives `org_id` from the authenticated membership only (08 §8 layer 1; 20 MT-1.3). RLS is the safety net, not the filter.
5. **Tenant-composite keys (04 §1.3)** on every tenant table, so a row cannot point at another tenant's row even if RLS were bypassed.
6. **Options B and C are not used** for the shared platform.
7. **Option D (dedicated single-tenant stack) is the Tier 3 premium option**, built only when an enterprise contract requires it (§1C.15): same repository, same images, same migrations, one organisation row, **RLS stays on** (10 §11; 04 §8.4). An intermediate Tier 3 step is dedicated workers on the shared stack (`workers.dedicated_org_id`, 04 §5.4). Nothing in 3A–3C builds D; 3A–3C only keep the design from preventing it (20 MT-1.6).

## 4. Consequences

### 4.1 General
- **Positive.** Lowest resource use on the shared VPS (no per-tenant database or schema; E1, E2); one migration run (04 §8); one queue and one fair-share function (ADR-001, 05 §7.2); a tenant-count limit is not set by the model (E1).
- **Negative.** The engine-level boundary is a policy, not a permission boundary (E1 "low"). Mitigations, all already contracted: five independent layers (08 §8), composite FKs (04 §1.3), the blocking 04 §3.7 suite (11 L5), grant-drift test (08 §8.2 item 8), `pg_class` flag check so a new table without RLS fails CI (04 §3.7.6, §8.2).
- **Complexity cost (E2).** Tenant identity must flow through every query path. This is why `amw_core.tenancy` has a 100 % coverage floor for the 04 §3.7 rows (11 §"Shape"; 27 §3).
- **Noisy neighbours (E1, E2).** Handled by queue fair share and per-tenant caps, not by the tenancy model: ADR-001, 05 §7.2, 08 §8.1 item 2. Enforced from Tier 1; in 3A the owner is the only real tenant.
- **Per-tenant consumption (E2).** Measured by the application (cost ledger, 04 §5.14; 09), not by the database.
- **Per-tenant restore (E1).** Native backups are whole-database. Restoring or exporting one tenant uses rows filtered by `org_id` plus one storage prefix (ADR-005; 10 §11; 12 §10). The per-tenant restore test is a Tier 1 gate (§1C.11; ADR-005 header).
- **Clients needing their own key, region or restore boundary** are routed to option D (E1), not served by customising the shared schema (E2: avoid per-tenant schema changes).
- **Connection pooler.** None is chosen yet. Any pooler must keep `SET LOCAL` semantics, which transaction pooling does (INF-11; E1 pattern). REQUIRES REVIEW (Phase 1): if a pooler is added, record its name, version and mode in RESEARCH_LOG.md and add a pooled-connection case to the tenancy suite (§4.4 item 4).

### 4.2 Queue (ADR-001)
- `task_queue` is a TENANT table (it carries the envelope; 04 §5.4) with FORCE RLS. A worker does not know the next job's tenant, so claiming goes only through `amw_queue_claim` (owned by `amw_sysfn`, identifiers + envelope only), then the worker opens a normal tenant transaction with `SET LOCAL app.org_id` (ADR-001 §1 constraint 2, §3).
- This decision is the reason ADR-001 rejects any library that reads its own job table directly as `amw_app`, uses a GLOBAL job table holding envelopes, or needs `BYPASSRLS` on a worker login (ADR-001 §2 "Logical consequence").
- LISTEN/NOTIFY payloads carry no tenant content (ADR-001 §3). Fair share runs inside the claim function on identifiers and counters only (05 §7.2).
- Tier 3: `workers.dedicated_org_id` restricts a worker to one organisation inside the shared queue; a dedicated stack has its own `task_queue` built by the same migrations (ADR-001 revisit trigger 3).

### 4.3 Storage (ADR-005)
- The database stores tenant-scoped URIs + SHA-256 only (04 §1.6). URIs are `amw-blob://<org wire id>/…`; the backend path begins `<root>/<org uuid>/`, so one tenant is one prefix (03 §8; ADR-005 §1).
- The storage reader compares the URI org with `app.org_id` (set by this ADR's per-transaction context) before resolving; mismatch → `PERMANENT.CROSS_TENANT_REF` (03 §8.3; ADR-005 §3 `put`).
- Per-tenant export and erasure = rows by `org_id` + `list_prefix` / `delete_prefix(org)` (ADR-005 §3; 04 §5.24, Tier 1). Off-server backup keeps per-tenant prefixes (ADR-005 §3.4).
- Tier 3 dedicated stack: own storage root or bucket, own backup destination, own key-encryption key (10 §11; ADR-005 header).

### 4.4 Cross-tenant tests (blocking; 04 §3.7, 08 §8.2, 11 L5, 20 MT-1.1–MT-1.7)
1. **3A:** the eight 04 §3.7 checks run on every push against PostgreSQL, for every TENANT and SHARED-CATALOGUE table, with a synthetic org B (fixtures never use real tenant data, 08 §8.1 item 6). Fixtures are generated from the 04 §4 catalogue so a new table is covered automatically (11 L5).
2. **3A:** role checks: `amw_app` is not owner, not superuser, `NOBYPASSRLS` (20 MT-1.2); grant drift (08 §8.2 item 8); the `amw_sysfn` functions return no content columns (04 §3.7.7).
3. **3A:** queue rows of org B are invisible to org A; concurrent claims return disjoint rows (ADR-001 §4 "Tests"). Storage, cache and log checks of 04 §3.7.8 and 11 L5 items 2–4.
4. **3A design, run when a pooler exists:** a tenant context set in one transaction is absent in the next transaction on the same pooled connection (follows from `SET LOCAL`, INF-11).
5. **3B:** the suite is re-run on the pilot database before the golden samples (20 MT-1.5, "re-run on every release").
6. **3C / Tier 1:** two real tenants run concurrent jobs (20 MT-1.5 extended with a real client org); API existence-oracle test (11 L5 addition 1).
7. **Tier 3:** a dedicated stack built from empty with the same migrations passes the migration and tenancy tests (20 MT-14.3); a tenant export imports into it (20 MT-14.4).

### 4.5 Scope by build phase and tier

| Item | 3A | 3B | 3C | Tier |
|---|---|---|---|---|
| Roles, FORCE RLS, `SET LOCAL`, composite FKs, `amw_core.tenancy` guard | Build | Re-verify | — | 0 |
| 04 §3.7 suite as blocking CI gate | Build | Re-run on pilot DB | Extend (API oracle) | 0 → 1 |
| Second real tenant, tenancy UI, `amw_platform_ops_summary()` | — | — | Build | 1 |
| Per-tenant export / restore test | Design kept | — | Build | 1 |
| Many self-serve orgs on the same schema | — | — | Design only | 2 |
| `workers.dedicated_org_id`; dedicated single-tenant stack | Design kept (no hard-coded host/tenant) | — | — | 3 (on contract) |

## 5. Status
**Proposed.** Owner approval needed before the first migration (20 §8 item 2: "ADR-002 desirable before the first migration"). Under D2 this ADR belongs to the 3A slice approval, because 3A builds the full RLS model and its CI gate.

## 6. Revisit triggers
1. A client requires its own encryption key, data location or restore boundary that model A cannot meet → offer option D (Tier 3), do not change the shared model.
2. Measured database load or connection count on the shared instance breaches an S5 threshold (05) in a way that per-tenant caps and fair share cannot fix.
3. Tier 2 tenant count makes a single database reach a measured scale limit (E2 "scale limits"); then evaluate sharding by `org_id` (E2 Sharding pattern), keeping the same schema and migrations.
4. A regulation or contract term applicable to a tenant requires database-level separation (REQUIRES REVIEW (Phase 1): 22_DATA_PROTECTION.md, lawyer).
5. A pooler or driver is found that does not preserve `SET LOCAL` semantics, or a needed library requires a `BYPASSRLS` or owner login (would breach §3 item 2).
6. A cross-tenant test fails in CI or production: stop, treat as an L3 security incident (08), and re-review this ADR.

## 7. Cited research
| Ref | Source | Status |
|---|---|---|
| INF-11 | RESEARCH_LOG.md (PostgreSQL RLS, SET, admin functions) | VERIFIED |
| INF-01 | RESEARCH_LOG.md (VPS plan) | VERIFIED |
| E1 | https://learn.microsoft.com/en-us/azure/architecture/guide/multitenant/service/postgresql (page "Last updated 2026-11-16"; fetched 2026-11-18, HTTP 200) | Checked for this ADR; **UNLOGGED; REQUIRES REVIEW (Phase 1): log entry (official URL + date)** |
| E2 | https://learn.microsoft.com/en-us/azure/architecture/guide/multitenant/approaches/storage-data (page "Last updated 2026-08-21"; fetched 2026-11-18, HTTP 200) | Checked for this ADR; **UNLOGGED; REQUIRES REVIEW (Phase 1): log entry (official URL + date)** |
| — | "Standard default for B2B SaaS" and "schema-per-tenant bloats the catalog" (directive §1C.1) | **Not confirmed** by E1/E2 (E1 names B2C SaaS as the common case for shared tables and gives no catalogue figure). The decision does not depend on these statements; it rests on rule 9, INF-01, INF-11, E1, E2 and the ADR-001 claim constraint. REQUIRES REVIEW (Phase 1): official source with figures, if the claim is to be kept in 20 / 17 |
