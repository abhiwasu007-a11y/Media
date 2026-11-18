# 04 — Database Architecture (PostgreSQL)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | S9 Tenant, Identity & Access (→ Agent 01) for tenancy/RLS; Agent 01 for work/queue tables; each table names its owning agent/service |
| Depends on | GLOSSARY_AND_IDS.md, 03_COMMUNICATION_STANDARD.md, 07_FAILURE_MANAGEMENT.md, 24_PRODUCTION_TYPES.md, RESEARCH_LOG.md (INF-05, INF-06, INF-11, YT-02, YT-03, YT-04, YT-06, YT-14) |
| Directive sections covered | §1 (Postgres queue), §1A.1/1A.7 (licences, editorial contribution, quality score), §1B.2a (knowledge library), §1C.1 (tenancy, org_id + RLS), §1C.4 (roles), §1C.5 (audit), §1C.7 (rule packs), §1C.8 (licence ledger), §1C.9 (billing, Tier 2), §1C.10 (export/erasure), §1C.12 (API, Tier 3), §3.2 (S4, S7, S8, S13), §3.3 (state machine, DLQ, idempotency, breakers, memory, learning loop, cost) |
| Not decided here | Queue library (ADR-001), auth library (ADR-003), vector store (agent_04 / ADR), DEK algorithm (08), retention durations (22) |

---

## 1. Principles
1. **One PostgreSQL database, shared schema, `org_id` on every tenant row** (§1C.1 research finding). RLS is the second line of defence; application code always filters by `org_id` explicitly as the first.
2. Every tenant table: `org_id uuid NOT NULL`, `ENABLE` + `FORCE ROW LEVEL SECURITY`, the standard tenant policy (§3.4). Global tables are few, carry no tenant data, and each is justified in §4.
3. Tenant-composite foreign keys: every tenant table has `UNIQUE (org_id, id)`; child tables reference `(org_id, parent_id) → parent(org_id, id)`, so a row can never point at another tenant's row even if RLS were bypassed.
4. Enum columns are `text` + `CHECK (col IN (…))` with the exact values of GLOSSARY §6 (additive migrations, no `ALTER TYPE`).
5. Money: `_minor bigint` + `currency char(3)`; per-call cost: `_micros bigint` (GLOSSARY §3). Durations `_ms bigint`. Timestamps `timestamptz` (UTC).
6. Large content (scripts, media, licence documents, tracebacks, Task Input/Output documents) lives in storage behind tenant-scoped URIs (03 §8); the DB stores the URI + SHA-256.
7. Append-only tables (audit_log, state_transitions, cost_ledger, licence_ledger, message_log, analytics_snapshots) have no UPDATE/DELETE grants and a trigger that rejects UPDATE/DELETE.
8. No secrets in clear text: OAuth tokens and webhook secrets are encrypted with a per-tenant data key (§5.19); API keys are stored as hashes.
9. PostgreSQL major version: **REQUIRES REVIEW (Phase 1): choose and record in RESEARCH_LOG.md; floor is 13 (Procrastinate, INF-05) or 14 (PgQueuer, INF-06) depending on ADR-001.**

## 2. Conventions used in the table definitions
- **Std columns** (present on every table unless stated): `id uuid PRIMARY KEY` (UUIDv7, GLOSSARY §2.1), `org_id uuid NOT NULL` (tenant tables), `created_at timestamptz NOT NULL DEFAULT now()`.
- **Mut columns** (mutable tables): `updated_at timestamptz NOT NULL DEFAULT now()`, `row_version int NOT NULL DEFAULT 1` (optimistic locking: `UPDATE … WHERE id = $1 AND row_version = $2`).
- `TFK → t` = tenant-composite foreign key `(org_id, col) REFERENCES t(org_id, id)`.
- `enum(x)` = `text` with `CHECK` against GLOSSARY enum `x`.
- **Scope**: `TENANT` (org_id + RLS), `GLOBAL` (no org_id), `SHARED-CATALOGUE` (nullable org_id: NULL = platform-owned row readable by all tenants, writable by none; §3.5).
- **Tier**: `T0` = first build (MVP/walking skeleton); `T0+` = Tier 0, built after the walking skeleton; `T1`/`T2`/`T3` = §1C.15 tiers. A table may exist from T0 even when its features are tiered, so the data model never needs a tenancy retro-fit.

## 3. Tenancy enforcement

### 3.1 Roles
| Role | Login | Owns objects | RLS | Purpose |
|---|---|---|---|---|
| `amw_owner` | NO | all tables, functions | n/a (owner; FORCE RLS still applies to it, INF-11) | Object ownership only. |
| `amw_migrator` | YES | member of `amw_owner` | — | Runs migrations; used by deploy only; never by running services. |
| `amw_app` | YES | none | enforced, `NOBYPASSRLS`, not superuser (INF-11) | API, orchestrator, agents, workers. DML grants per table. |
| `amw_publisher` | YES | none | enforced | Agent 13 publish worker only: the only role with `SELECT` on encrypted token columns of `oauth_tokens`. |
| `amw_auth` | YES | none | enforced | Identity tables (§5.1 users/auth refs/sessions); used by the auth component of ADR-003. |
| `amw_readonly` | YES | none | enforced | Reporting/analytics reads within a tenant context; `SELECT` only. |
| `amw_sysfn` | NO | the system functions of §3.6 only | `BYPASSRLS` | Owner of narrowly scoped `SECURITY DEFINER` functions that must see operational rows across tenants. Never granted to a login role directly. |

The app never connects as `amw_owner`, `amw_migrator` or a superuser. Credentials come from the environment (S6, 08); none are in the repository.

### 3.2 Tenant context function
```sql
-- Illustration (final DDL is written in the build phase).
CREATE FUNCTION amw_current_org() RETURNS uuid
  LANGUAGE sql STABLE
  AS $$ SELECT NULLIF(current_setting('app.org_id', true), '')::uuid $$;

CREATE FUNCTION amw_current_user() RETURNS uuid
  LANGUAGE sql STABLE
  AS $$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$;
```
- `current_setting(name, true)` returns NULL when unset (INF-11), so an unset context matches **no** rows (fail closed).
- Each transaction starts with `SET LOCAL app.org_id = '<uuid>'`, `SET LOCAL app.actor = '<actor_ref>'` and, for human requests, `SET LOCAL app.user_id = '<uuid>'`. `SET LOCAL` lasts until the end of the transaction (INF-11), so pooled connections never carry a tenant into the next transaction.
- `amw_core.tenancy` refuses to run a query outside a transaction that has `app.org_id` set (application-level guard).

### 3.3 Grants pattern
`amw_app`: `SELECT, INSERT, UPDATE` on mutable tenant tables; `SELECT, INSERT` on append-only tables; `DELETE` only where a table says so. No `TRUNCATE`, no DDL.

### 3.4 Standard tenant policy (every TENANT table)
```sql
-- Illustration.
ALTER TABLE <t> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <t> FORCE ROW LEVEL SECURITY;   -- owner is subject to RLS too (INF-11)
CREATE POLICY tenant_isolation ON <t>
  USING      (org_id = amw_current_org())
  WITH CHECK (org_id = amw_current_org());
```

### 3.5 Shared-catalogue policy (nullable `org_id`)
Used by `rule_packs`, `licences`, `gcp_projects`, `circuit_breakers`, `quota_usage`.
```sql
-- Illustration.
CREATE POLICY catalogue_read ON <t> FOR SELECT
  USING (org_id IS NULL OR org_id = amw_current_org());
CREATE POLICY catalogue_write ON <t> FOR ALL
  USING (org_id = amw_current_org())
  WITH CHECK (org_id = amw_current_org());   -- tenants can never create or change platform rows
```
Platform rows (`org_id IS NULL`) are written only by migrations or by `amw_sysfn` functions called by a `PLATFORM_OWNER` action, each audited in the platform owner org's audit chain.

### 3.6 System functions (cross-tenant operational access, identifiers only)
Some platform processes must find work before they know its tenant. They use `SECURITY DEFINER` functions owned by `amw_sysfn`, with a fixed `search_path`, that return **identifiers and envelopes only** — never content columns. The caller then opens a normal tenant transaction with `SET LOCAL app.org_id`.

| Function | Caller | Returns |
|---|---|---|
| `amw_queue_claim(worker_id, capabilities[], resource_classes[], n)` | worker | up to *n* `(queue item id, org_id, task_id, envelope)`, claimed with `FOR UPDATE SKIP LOCKED` (§1), ordered by the fair-share rule of 05 |
| `amw_due_retries(limit)` | scheduler | `(org_id, task_id)` in `RETRY_WAIT` with `next_attempt_at ≤ now()` |
| `amw_due_resumes(limit)` | scheduler | `(org_id, task_id, wait_reason)` in `CHECKPOINTED` whose condition may have cleared |
| `amw_expired_leases(limit)` | reaper | `(org_id, task_id, queue item id)` with `lease_expires_at < now()` |
| `amw_stuck_tasks(limit)` | reaper | `(org_id, task_id, state)` past the dwell limits of 07 §6 |
| `amw_quota_reserve(gcp_project_id, bucket, units)` / `amw_quota_release(…)` | publish worker | `ok` / `exhausted` for the PT day (§5.20) |
| `amw_breaker_record(provider, operation_class, credential_scope, outcome)` | adapters | new breaker state (§5.8) |
| `amw_platform_ops_summary()` (T1) | S8 platform-owner view | per-org aggregates only: queue depth, job counts by state, cost totals, DLQ counts — no content |

Every call is logged with the caller's actor; `amw_platform_ops_summary` calls are audited.

### 3.7 Cross-tenant test requirement (blocking CI gate)
`tests/tenancy/` must, for **every** TENANT and SHARED-CATALOGUE table:
1. Create orgs A and B with rows in each table (fixtures).
2. As `amw_app` with `app.org_id = A`: `SELECT` returns no B rows; `INSERT … org_id = B` fails `WITH CHECK`; `UPDATE`/`DELETE` targeting B rows affect 0 rows.
3. With `app.org_id` unset: `SELECT` returns 0 rows on every tenant table.
4. A tenant-composite FK from an A row to a B parent fails.
5. A catalogue test: tenant A cannot `UPDATE`/`DELETE` an `org_id IS NULL` row.
6. Catalogue check: a query over `pg_class` (`relrowsecurity`, `relforcerowsecurity`) asserts both flags on every table except the GLOBAL allow-list of §4; a new table without RLS fails CI.
7. Each §3.6 function is tested to return no content columns.
8. Storage, cache and log tests: a URI, cache key or log record of org B is rejected/absent in org A's context (03 §8).

## 4. Table catalogue

| § | Table | Scope | Tier | Owner | Notes |
|---|---|---|---|---|---|
| 5.1 | organisations | TENANT (policy on `id`) | T0 | S9 | tenant root |
| 5.1 | workspaces | TENANT | T0 | S9 | |
| 5.1 | channels | TENANT | T0 | S9 / 13 | |
| 5.1 | users | GLOBAL (identity; RLS on membership) | T0 | S9 | justified §5.1 |
| 5.1 | user_auth_refs | GLOBAL (RLS self) | T0 | S9 | ADR-003 |
| 5.1 | user_sessions | GLOBAL (RLS self) | T0 | S9 | ADR-003 |
| 5.1 | memberships | TENANT | T0 | S9 | roles §1C.4 |
| 5.1 | invitations | TENANT | T0+ | S9 | |
| 5.1 | org_controls | TENANT | T0 | S8 → 01 | S8 controls |
| 5.1 | platform_controls | GLOBAL | T0 | S8 → 01 | platform emergency stop |
| 5.2 | production_types | GLOBAL | T0 | 01 | registry rows |
| 5.2 | org_production_types | TENANT | T0 | 01 | enablement/overrides |
| 5.2 | rule_packs | SHARED-CATALOGUE | T0 | 16 | platform packs non-removable |
| 5.2 | compliance_profiles | TENANT | T0 | 16 | |
| 5.2 | compliance_profile_rule_packs | TENANT | T0 | 16 | |
| 5.3 | projects | TENANT | T0 | 01 / 03 | |
| 5.3 | jobs | TENANT | T0 | 01 | |
| 5.3 | tasks | TENANT | T0 | 01 | |
| 5.3 | task_dependencies | TENANT | T0 | 01 | |
| 5.3 | task_attempts | TENANT | T0 | 01 | |
| 5.4 | task_queue | TENANT | T0 | 01 | ADR-001 neutral |
| 5.4 | workers | GLOBAL | T0 | S5 → 01 | |
| 5.5 | message_log | TENANT (partitioned) | T0 | 01 | |
| 5.6 | state_transitions | TENANT (partitioned) | T0 | 01 | |
| 5.6 | state_transition_rules | GLOBAL | T0 | 01 | seed data |
| 5.7 | dead_letter | TENANT | T0 | 01 | |
| 5.7 | checkpoints | TENANT | T0 | 01 | |
| 5.8 | circuit_breakers | SHARED-CATALOGUE | T0 | 01 | |
| 5.9 | idempotency_keys | TENANT | T0 | 01 | |
| 5.10 | memory_items | TENANT | T0 | 04 / 01 | |
| 5.10 | knowledge_sources | TENANT | T0+ | 04 | text outside git |
| 5.10 | knowledge_chunks | TENANT | T0+ | 04 | |
| 5.11 | scripts | TENANT | T0 | 05 | |
| 5.11 | claims | TENANT | T0+ | 06 | |
| 5.11 | citations | TENANT | T0+ | 04 / 06 | |
| 5.12 | brand_kits | TENANT | T0+ | S11 → 13 | |
| 5.12 | voices | TENANT | T0 | 07 | |
| 5.12 | voice_consents | TENANT | T0+ | 07 / S7 | |
| 5.13 | audit_log | TENANT (partitioned, append-only, hash chain) | T0 | S6 → 16 | |
| 5.13 | audit_chain_heads | TENANT | T0 | S6 → 16 | |
| 5.14 | cost_ledger | TENANT (partitioned, append-only) | T0 | S4 → 15 | |
| 5.14 | budgets | TENANT | T0 | S4 → 15 | |
| 5.14 | budget_reservations | TENANT | T0 | S4 → 15 | |
| 5.15 | licences | SHARED-CATALOGUE | T0 | 08 / 16 | |
| 5.15 | licence_ledger | TENANT (append-only) | T0 | 08 / 16 | |
| 5.15 | assets | TENANT | T0 | 08 | |
| 5.15 | asset_fingerprints | TENANT | T0+ | 08 / S2 | |
| 5.16 | approvals | TENANT | T0 | S7 → 01 | |
| 5.16 | approval_steps | TENANT | T0 | S7 → 01 | |
| 5.16 | editorial_contributions | TENANT | T0 | S7 / 16 | |
| 5.17 | quality_scores | TENANT | T0 | 16 | |
| 5.17 | qc_results | TENANT | T0 | 10 / 16 | |
| 5.17 | compliance_verdicts | TENANT | T0 | 16 | |
| 5.18 | renders | TENANT | T0 | 10 | |
| 5.19 | gcp_projects | SHARED-CATALOGUE | T0 | 13 | |
| 5.19 | oauth_tokens | TENANT | T0 | 13 | encrypted |
| 5.19 | tenant_data_keys | TENANT | T0 | S6 → 16 | |
| 5.20 | quota_usage | SHARED-CATALOGUE | T0 | 13 / 01 | per GCP project per PT day |
| 5.21 | publications | TENANT | T0 | 13 | |
| 5.22 | analytics_snapshots | TENANT (partitioned, append-only) | T0+ | 14 | |
| 5.22 | experiments | TENANT | T0+ | 14 / 15 | |
| 5.23 | notifications | TENANT | T0 | S7 → 01 | |
| 5.23 | review_comments | TENANT | T2 | S11 → 13 | |
| 5.23 | community_comments | TENANT | T0+ | S13 → 14 | |
| 5.24 | data_requests | TENANT | T1 | S9 → 01 | DPDP (22) |
| 5.25 | plans | GLOBAL | T2 | S10 → 15 | |
| 5.25 | subscriptions | TENANT | T2 | S10 → 15 | |
| 5.25 | usage_events | TENANT (partitioned) | T2 | S10 → 15 | |
| 5.25 | invoices | TENANT | T2 | S10 → 15 | |
| 5.26 | api_keys | TENANT | T3 | S12 → 01 | |
| 5.26 | webhooks | TENANT | T3 | S12 → 01 | |
| 5.26 | webhook_deliveries | TENANT | T3 | S12 → 01 | |
| 5.26 | org_sso_connections | TENANT | T3 | S9 → 01 | |
| 5.26 | org_domains | TENANT | T3 | S9 → 01 | |

**GLOBAL allow-list (no `org_id`, justified):** `users`, `user_auth_refs`, `user_sessions` (one person can belong to several orgs; identity precedes tenant choice; RLS restricts each to self/memberships), `platform_controls` (platform-wide switches, no tenant data), `production_types` (product catalogue), `state_transition_rules` (static rules), `workers` (shared infrastructure registry, logical names only, no host details), `plans` (price catalogue, T2). Migration bookkeeping tables of the chosen tool are also global.

---

## 5. Table definitions

### 5.1 Tenancy, identity and controls

**organisations** — TENANT (policy `USING (id = amw_current_org())`) · T0 · Std (no `org_id`; `id` is the org) + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| name | text | no | 1–200 chars |
| slug | text | no | `UNIQUE`; `^[a-z0-9-]{3,63}$` |
| kind | enum(org_kind) | no | |
| status | enum(org_status) | no | default `ACTIVE` |
| tier | enum(tier) | no | default `TIER_0` |
| is_platform_owner | boolean | no | default false; partial `UNIQUE (is_platform_owner) WHERE is_platform_owner` (exactly one) |
| display_timezone | text | no | IANA zone, default `Asia/Kolkata` |
| data_location_note | text | yes | data-location statement (22) |
| plan_id | uuid | yes | FK → plans (T2) |
Creation: only through an audited `amw_sysfn` function (platform owner action; self-serve signup T2).

**workspaces** — TENANT · T0 · Std + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| name | text | no | |
| status | enum(workspace_status) | no | |
| white_label_ref | text | yes | T2 (S11) |
Keys: `UNIQUE (org_id, id)`, `UNIQUE (org_id, name)`.

**channels** — TENANT · T0 · Std + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| workspace_id | uuid | no | TFK → workspaces |
| platform | enum(channel_platform) | no | |
| external_channel_id | text | yes | set when connected |
| title | text | no | |
| language | text | no | BCP 47 primary language |
| category | text | no | drives mandatory rule packs (e.g. `finance`) |
| compliance_profile_id | uuid | yes | TFK → compliance_profiles; required before status `CONNECTED` (CHECK) |
| brand_kit_id | uuid | yes | TFK → brand_kits |
| gcp_project_id | uuid | yes | FK → gcp_projects |
| status | enum(channel_status) | no | |
| production_window | jsonb | yes | T1+ per-tenant window on a dedicated server (06) |
| connected_at | timestamptz | yes | |
Keys: `UNIQUE (org_id, id)`, `UNIQUE (org_id, platform, external_channel_id)`. Index `(org_id, workspace_id)`.

**users** — GLOBAL · T0 · Std (no org_id) + Mut. RLS: `USING (id = amw_current_user() OR EXISTS (SELECT 1 FROM memberships m WHERE m.user_id = users.id AND m.org_id = amw_current_org()))`; writes only by `amw_auth`.
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| email | citext | no | `UNIQUE`; personal data (22) |
| display_name | text | no | |
| status | enum(user_status) | no | |
| mfa_enrolled | boolean | no | default false; MFA enforcement per org policy (08) |
| last_login_at | timestamptz | yes | |

**user_auth_refs** — GLOBAL (RLS self) · T0 · Std
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| user_id | uuid | no | FK → users |
| provider | enum(auth_provider) | no | |
| external_subject | text | no | provider subject ID; `UNIQUE (provider, external_subject)` |
Credential storage (password hashes, MFA secrets) is owned by the ADR-003 auth component; **REQUIRES REVIEW (ADR-003)** whether it lives in this DB or a separate identity service. Never hand-rolled crypto (§1C.4).

**user_sessions** — GLOBAL (RLS self) · T0 · Std
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| user_id | uuid | no | FK → users |
| active_org_id | uuid | yes | FK → organisations; must have an `ACTIVE` membership (trigger) |
| mfa_verified_at | timestamptz | yes | |
| expires_at | timestamptz | no | |
| revoked_at | timestamptz | yes | |
| user_agent_hash | bytea | yes | SHA-256, no raw value |
Index `(user_id, expires_at)`.

**memberships** — TENANT · T0 · Std + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| user_id | uuid | no | FK → users |
| role | enum(role) | no | `PLATFORM_OWNER` only in the org with `is_platform_owner` (trigger) |
| status | enum(membership_status) | no | |
| workspace_ids | uuid[] | yes | NULL = all workspaces; restricts Producer/Reviewer/Client Guest scope |
Keys: `UNIQUE (org_id, user_id)`. Permission matrix per role: 08_SECURITY.md.

**invitations** — TENANT · T0+ · Std + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| email | citext | no | |
| role | enum(role) | no | not `PLATFORM_OWNER` |
| token_hash | bytea | no | SHA-256 of the single-use token; `UNIQUE` |
| state | enum(invitation_state) | no | |
| invited_by | uuid | no | FK → users |
| expires_at | timestamptz | no | |

**org_controls** — TENANT · T0 · Std + Mut (S8 controls, §3.2 S8)
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| key | text | no | one of: `agent_enabled.<agent_id>`, `production_schedule`, `daily_production_limit`, `publishing_enabled`, `emergency_stop`, `ip_allowlist` (T3) |
| value | jsonb | no | validated per key by `amw_core.config` |
| updated_by | text | no | actor ref |
Keys: `UNIQUE (org_id, key)`. Every change audited (`control.<key>.changed`).

**platform_controls** — GLOBAL · T0 · Std + Mut: `key text UNIQUE`, `value jsonb`, `updated_by text`. Keys: `platform_emergency_stop`, `admission_paused`. Written only by `PLATFORM_OWNER` via `amw_sysfn`; audited in the platform owner org's chain.

### 5.2 Registry and compliance catalogue

**production_types** — GLOBAL · T0 · Std
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| key | enum(production_type_key) | no | |
| version | int | no | ≥ 1 |
| status | enum(feature_status) | no | |
| tier | enum(tier) | no | first tier in which the type is offered |
| record | jsonb | no | registry record (24 §2), validated against `amw.production_type` record schema |
| record_sha256 | bytea | no | |
Keys: `UNIQUE (key, version)`. Rows are immutable; a change is a new version.

**org_production_types** — TENANT · T0 · Std + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| production_type_key | enum(production_type_key) | no | |
| enabled_version | int | no | FK `(production_type_key, enabled_version)` → production_types(key, version) |
| enabled | boolean | no | |
| overrides | jsonb | no | default `{}`; only fields marked overridable in 24 §2 |
Keys: `UNIQUE (org_id, production_type_key)`.

**rule_packs** — SHARED-CATALOGUE · T0 · Std + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| org_id | uuid | yes | NULL = platform pack |
| key | text | no | GLOSSARY §6.37 |
| version | int | no | |
| scope | enum(rule_pack_scope) | no | CHECK `(scope = 'PLATFORM') = (org_id IS NULL)` |
| category | text | no | `youtube_general`, `finance`, `health`, `kids`, `political_news`, `advertising`, `ad_sector`, `brand_safety` |
| always_on | boolean | no | true only for `rp.youtube_general` |
| removable | boolean | no | false for every PLATFORM pack (CHECK) |
| rules_ref | text | no | storage URI of the rule text (13/25 own the content) |
| rules_sha256 | bytea | no | |
| status | enum(rule_pack_status) | no | |
| effective_from | timestamptz | no | |
Keys: `UNIQUE (coalesce(org_id, '00000000-0000-0000-0000-000000000000'), key, version)` (expression index).

**compliance_profiles** — TENANT · T0 · Std + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| workspace_id | uuid | no | TFK → workspaces |
| name | text | no | |
| version | int | no | |
| status | enum(rule_pack_status) | no | |

**compliance_profile_rule_packs** — TENANT · T0 · Std
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| profile_id | uuid | no | TFK → compliance_profiles |
| rule_pack_id | uuid | no | FK → rule_packs |
| is_mandatory | boolean | no | set by the system for PLATFORM packs required by the channel category |
Keys: `UNIQUE (org_id, profile_id, rule_pack_id)`. Trigger: a link with `is_mandatory = true` cannot be deleted or set to false by `amw_app`; creating a profile auto-inserts `rp.youtube_general` (§1C.7: tenants add rules, never remove platform gates).

### 5.3 Work: projects, jobs, tasks

**projects** — TENANT · T0 · Std + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| workspace_id | uuid | no | TFK → workspaces |
| channel_id | uuid | yes | TFK → channels |
| name | text | no | |
| kind | enum(project_kind) | no | |
| status | enum(project_status) | no | |
| default_production_type | enum(production_type_key) | yes | |

**jobs** — TENANT · T0 · Std + Mut (state columns use `state_version`, not `row_version`)
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| workspace_id | uuid | no | TFK → workspaces |
| project_id | uuid | yes | TFK → projects |
| channel_id | uuid | yes | TFK → channels |
| parent_job_id | uuid | yes | TFK → jobs (e.g. Shorts from long-form) |
| production_type_key | enum(production_type_key) | no | |
| production_type_version | int | no | FK → production_types(key, version) |
| language | text | no | BCP 47 |
| state | enum(job_state) | no | default `PENDING` |
| state_version | int | no | default 1 |
| state_changed_at | timestamptz | no | |
| outcome | enum(job_outcome) | yes | CHECK `(state = 'COMPLETED') = (outcome IS NOT NULL)` |
| priority | smallint | no | 0–4 (GLOSSARY §6.5) |
| deadline | timestamptz | yes | |
| correlation_id | uuid | no | |
| idempotency_key | text | no | scope `job.create` (03 §9.2) |
| requested_by | text | no | actor ref |
| input_ref | text | yes | storage URI of job inputs (brief, source video) |
| task_count | int | no | default 0; ≤ config `limits.max_tasks_per_job` (checked in code) |
| cost_estimate_micros | bigint | no | default 0 (rolled up from cost_ledger ESTIMATE) |
| cost_verified_micros | bigint | no | default 0 (VERIFIED) |
| currency | char(3) | no | |
| failed_task_id | uuid | yes | TFK → tasks |
| completed_at | timestamptz | yes | |
Keys: `UNIQUE (org_id, id)`, `UNIQUE (org_id, idempotency_key)`. Indexes: `(org_id, state) WHERE state NOT IN ('COMPLETED','CANCELLED')`, `(org_id, channel_id, created_at DESC)`, `(org_id, correlation_id)`. Trigger: transition check against `state_transition_rules` (§5.6).

**tasks** — TENANT · T0 · Std (+ `state_version` instead of `row_version`)
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| job_id | uuid | no | TFK → jobs |
| task_type | text | no | `^(agent_(0[1-9]|1[0-7])|svc_s(0[1-9]|1[0-3]))\.[a-z0-9_]+$` |
| agent_id | text | no | executor ID; must be the prefix of `task_type` (CHECK) |
| iteration | int | no | default 0; revision loop number; ≤ `limits.max_revision_loops` (code) |
| is_required | boolean | no | default true |
| state | enum(task_state) | no | default `PENDING` |
| wait_reason | enum(wait_reason) | yes | CHECK `(state = 'CHECKPOINTED') = (wait_reason IS NOT NULL)` |
| state_version | int | no | default 1 |
| state_changed_at | timestamptz | no | |
| priority | smallint | no | 0–4 |
| resource_class | enum(resource_class) | no | |
| required_capabilities | text[] | no | values from GLOSSARY §6.20 |
| idempotency_key | text | no | 03 §9 |
| input_ref / input_sha256 | text / bytea | yes | set at T02 |
| output_ref / output_sha256 | text / bytea | yes | set at T08 |
| input_schema_version | text | yes | `amw.task_input` version |
| payload_schema / payload_schema_version | text / text | no | named payload schema |
| resource_budget | jsonb | no | `amw.common#/resource_budget` |
| attempt_count | int | no | default 0; CHECK `attempt_count <= max_attempts` |
| max_attempts | int | no | from retry policy at creation; CHECK `BETWEEN 1 AND 10` (hard ceiling, 07 §9) |
| next_attempt_at | timestamptz | yes | required when `RETRY_WAIT` (CHECK) |
| deadline | timestamptz | yes | |
| cancel_requested_at / cancel_reason | timestamptz / text | yes | |
| resume_checkpoint_id | uuid | yes | TFK → checkpoints |
| approval_id | uuid | yes | TFK → approvals (when `AWAITING_APPROVAL`) |
| error_code / error_class | text / enum(failure_class) | yes | last error |
| last_error | jsonb | yes | `amw.error` |
| completed_at | timestamptz | yes | |
Keys: `UNIQUE (org_id, id)`, `UNIQUE (org_id, idempotency_key)`. Indexes: `(org_id, job_id)`, `(next_attempt_at) WHERE state = 'RETRY_WAIT'`, `(state_changed_at) WHERE state IN ('VALIDATING','FAILED','CHECKPOINTED')` (stuck detection). Trigger: transition check (§5.6).

**task_dependencies** — TENANT · T0 · (no `id`) `org_id`, `task_id` TFK → tasks, `depends_on_task_id` TFK → tasks, `created_at`. PK `(org_id, task_id, depends_on_task_id)`; CHECK `task_id <> depends_on_task_id`. Acyclicity is guaranteed by materialising only DAGs validated from the registry (24 §3).

**task_attempts** — TENANT · T0 · Std
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| task_id | uuid | no | TFK → tasks |
| attempt_no | int | no | ≥ 1; `UNIQUE (org_id, task_id, attempt_no)` |
| worker_id | uuid | yes | FK → workers |
| result | enum(attempt_result) | no | default `RUNNING` |
| started_at / ended_at | timestamptz | no / yes | |
| heartbeat_at | timestamptz | yes | |
| duration_ms | bigint | yes | |
| resumed_from_checkpoint_id | uuid | yes | TFK → checkpoints |
| is_replay | boolean | no | default false (DLQ replay) |
| output_ref | text | yes | `amw.task_output` document |
| resource_usage | jsonb | yes | `amw.task_output#/resource_usage` |
| error_code | text | yes | |
| error | jsonb | yes | `amw.error` |

### 5.4 Queue and workers

**task_queue** — TENANT · T0 · Std. Logical shape neutral to ADR-001 (Procrastinate INF-05 / PgQueuer INF-06 / own table).
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| task_id | uuid | no | TFK → tasks |
| job_id | uuid | no | TFK → jobs |
| queue_name | text | no | `light`, `ai`, `render`, `publish` (maps to resource classes; 05) |
| status | enum(queue_item_status) | no | default `READY` |
| priority | smallint | no | 0–4 |
| resource_class | enum(resource_class) | no | |
| required_capabilities | text[] | no | |
| scheduled_at | timestamptz | no | not claimable before (quota / window / backoff) |
| claimed_at / claimed_by | timestamptz / uuid | yes | FK → workers |
| lease_expires_at | timestamptz | yes | required when `CLAIMED` (CHECK) |
| heartbeat_at | timestamptz | yes | |
| fair_share_key | text | no | `<org wire id>` (+ plan weight from config, 05) |
| resume_checkpoint_id | uuid | yes | TFK → checkpoints |
| envelope | jsonb | no | `amw.envelope` (03 §4) |
Indexes: `(queue_name, priority, scheduled_at) WHERE status = 'READY'`; `(lease_expires_at) WHERE status = 'CLAIMED'`; partial `UNIQUE (org_id, task_id) WHERE status IN ('READY','CLAIMED')` (one live row per task). Claim: `amw_queue_claim` (§3.6) using `FOR UPDATE SKIP LOCKED`; wake-up by LISTEN/NOTIFY (§1). Completed rows (`DONE`/`CANCELLED`) are deleted after `retention.queue_done_ms` (history lives in `task_attempts` and `state_transitions`).
**ADR-001 constraint — REQUIRES REVIEW (Phase 1 / ADR-001):** the chosen library's own job table must carry `org_id` with FORCE RLS and support claiming through the `SECURITY DEFINER` function, or the factory keeps this table and uses the library only for its worker loop. ADR-001 must confirm which is possible for Procrastinate (INF-05) and PgQueuer (INF-06).

**workers** — GLOBAL · T0 · Std + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| logical_name | text | no | `UNIQUE`; e.g. `render-1`; no host names or addresses |
| capabilities | text[] | no | GLOSSARY §6.20 |
| resource_classes | text[] | no | |
| max_concurrency | int | no | ≥ 1 (config, 05) |
| status | enum(worker_status) | no | |
| software_version | text | no | |
| heartbeat_at | timestamptz | yes | |
| drain_requested_at | timestamptz | yes | |
| dedicated_org_id | uuid | yes | T3 dedicated deployments; NULL = shared pool |

### 5.5 Messages

**message_log** — TENANT · T0 · append-only · partitioned by month on `sent_at`. Columns mirror the envelope: `id` (= `message_id`), `org_id`, `sender text`, `receiver text`, `job_id uuid NULL`, `task_id uuid NULL`, `payload_schema text`, `payload_uri text`, `payload_sha256 bytea`, `priority smallint`, `sent_at timestamptz`, `correlation_id uuid`, `schema_version text`, `processed_at timestamptz NULL` (the only column updated, once, by the receiver — implemented as a separate `message_receipts(org_id, message_id, processed_at)` insert to keep the log append-only). PK `(id, sent_at)`. Index `(org_id, task_id)`.

### 5.6 State history and rules

**state_transitions** — TENANT · T0 · append-only · partitioned by month on `occurred_at`
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| entity_kind | enum(entity_kind) | no | |
| entity_id | uuid | no | job or task |
| transition_id | text | no | `T01`–`T20`, `J01`–`J12` (03 §11) |
| from_state | text | yes | NULL for creation |
| to_state | text | no | |
| wait_reason | enum(wait_reason) | yes | |
| actor_kind / actor_ref | enum(actor_kind) / text | no | |
| authority | text | no | role or policy ID |
| error_code | text | yes | |
| state_version_after | int | no | |
| correlation_id | uuid | no | |
| occurred_at | timestamptz | no | |
| audit_seq | bigint | no | `audit_log.seq` of the matching audit row |
PK `(id, occurred_at)`. Index `(org_id, entity_id, occurred_at)`.

**state_transition_rules** — GLOBAL · T0 · seed data from 03 §11.3/§11.5, one row per allowed (from, to) pair: `entity_kind`, `transition_id`, `from_state text NULL`, `to_state text`, `allowed_actor_kinds text[]`. PK `(entity_kind, transition_id, coalesce(from_state,'∅'))`; `UNIQUE (entity_kind, from_state, to_state, transition_id)`. A `BEFORE UPDATE OF state` trigger on `jobs` and `tasks` raises an exception when `(OLD.state, NEW.state)` has no row (defence in depth for 03 §11.1).

### 5.7 Recovery

**dead_letter** — TENANT · T0 · Std + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| task_id | uuid | no | TFK → tasks (one row per dead-lettering event) |
| job_id | uuid | no | TFK → jobs |
| failure_class | enum(failure_class) | no | |
| error_code | text | no | 07 §2 |
| reason | text | no | human-readable |
| error | jsonb | no | last `amw.error` |
| payload_ref | text | no | Task Input URI |
| payload_sha256 | bytea | no | |
| retry_history | jsonb | no | array of `{attempt_no, started_at, ended_at, worker_id, error_code}` |
| traceback_ref | text | yes | redacted traceback blob |
| last_attempt_id | uuid | yes | TFK → task_attempts |
| last_run_at | timestamptz | yes | |
| recovery_status | enum(dlq_recovery_status) | no | default `NEW` |
| escalation_level | enum(escalation_level) | no | |
| replay_count | int | no | default 0; ≤ `limits.max_replays_per_item` (code) |
| replay_approval_id | uuid | yes | TFK → approvals (kind `DLQ_REPLAY`) |
| triaged_by | uuid | yes | FK → users |
| root_cause_note | text | yes | required before `REPLAY_APPROVED` (CHECK) |
| resolved_at | timestamptz | yes | |
Index `(org_id, recovery_status, created_at)`.

**checkpoints** — TENANT · T0 · Std
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| task_id | uuid | no | TFK → tasks |
| attempt_id | uuid | no | TFK → task_attempts |
| seq | int | no | `UNIQUE (org_id, task_id, seq)` |
| step_key | text | no | agent-defined resume point |
| state_ref | text | no | storage URI of the checkpoint state |
| state_sha256 | bytea | no | |
| completed_effects | text[] | no | idempotency keys already completed in this task |
| progress_ratio | numeric(4,3) | yes | 0–1 |
| is_latest | boolean | no | partial `UNIQUE (org_id, task_id) WHERE is_latest` |

### 5.8 Circuit breakers

**circuit_breakers** — SHARED-CATALOGUE · T0 · Std + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| org_id | uuid | yes | NULL = platform-held credential; set for tenant-owned credentials (e.g. client GCP project) |
| provider | text | no | adapter provider key |
| operation_class | text | no | e.g. `llm.completion`, `youtube.upload` |
| credential_scope | text | no | `platform` or `gcp_<wire id>` |
| state | enum(circuit_state) | no | |
| window_started_at | timestamptz | no | |
| window_calls / window_failures | int / int | no | |
| consecutive_failures | int | no | |
| opened_at / open_until | timestamptz | yes | |
| open_count | int | no | consecutive openings (for back-off of the open duration) |
| half_open_in_flight | int | no | |
| last_error_code | text | yes | |
Keys: `UNIQUE (provider, operation_class, credential_scope)`. Updated only via `amw_breaker_record` (§3.6). Rules: 07 §4.

### 5.9 Idempotency

**idempotency_keys** — TENANT · T0 · (no `id`) PK `(org_id, key)`
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| key | text | no | `^idk_[0-9a-f]{64}$` |
| scope | text | no | 03 §9.2 |
| request_sha256 | bytea | no | hash of the effect's request |
| status | enum(idempotency_status) | no | |
| task_id | uuid | yes | TFK → tasks |
| result_ref | text | yes | URI or entity ref of the result |
| locked_until | timestamptz | yes | for `IN_PROGRESS` |
| completed_at | timestamptz | yes | |
| expires_at | timestamptz | yes | NULL for `upload.*` / `publish.*` scopes (never expire) |
| created_at | timestamptz | no | |

### 5.10 Memory and knowledge

**memory_items** — TENANT · T0 · Std + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| scope | enum(memory_scope) | no | |
| workspace_id | uuid | no | TFK → workspaces |
| channel_id | uuid | yes | TFK → channels; required for `CHANNEL`, `LONG_TERM` |
| project_id | uuid | yes | TFK → projects; required for `PROJECT` |
| job_id | uuid | yes | TFK → jobs; required for `TASK`, `WORKING` |
| task_id | uuid | yes | TFK → tasks; required for `TASK`, `WORKING` |
| key | text | no | |
| value | jsonb | yes | small values |
| value_ref | text | yes | large values; CHECK exactly one of value / value_ref |
| provenance_ref | text | no | source output, chunk or approval it came from |
| confidence | numeric(4,3) | yes | |
| created_by | text | no | actor ref |
| expires_at | timestamptz | yes | required for `WORKING`, `TASK`, `PROJECT` (CHECK) |
| review_after | timestamptz | yes | for `CHANNEL`, `LONG_TERM` |
| superseded_by | uuid | yes | TFK → memory_items |
Index `(org_id, scope, channel_id, key)`.
Rules: (1) retrieval always filters `org_id` and the narrowest scope chain of the requesting task: `TASK`/`WORKING` of the same task → `PROJECT` of the same project → `CHANNEL` and `LONG_TERM` of the same channel; never another channel or project (§3.3 Memory). (2) Defaults (config): `WORKING` expires at attempt end; `TASK` with job retention; `PROJECT` when the project is archived + `memory.project_ttl_ms`. (3) Agent writes to `LONG_TERM` require provenance; changes to critical policies never come from memory (§3.3 Learning loop).

**knowledge_sources** — TENANT · T0+ · Std + Mut (§1B.2a; content never in git)
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| channel_id | uuid | no | TFK → channels (channel-isolated library) |
| kind | enum(knowledge_source_kind) | no | |
| title / author / edition | text | no / yes / yes | |
| language | text | no | |
| ownership | enum(source_ownership) | no | `UNKNOWN` blocks ingestion until the owner answers (Q25) |
| storage_ref | text | no | private factory storage URI |
| content_sha256 | bytea | no | `UNIQUE (org_id, channel_id, content_sha256)` |
| size_bytes | bigint | no | |
| status | enum(knowledge_source_status) | no | |
| ingest_version | int | no | |
| reliability_score | numeric(4,3) | yes | Agent 04 |
| release_approval_id | uuid | yes | TFK → approvals (`KNOWLEDGE_RELEASE`, Q26) |
| credit_in_description | boolean | no | default true (further reading credit) |

**knowledge_chunks** — TENANT · T0+ · Std
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| channel_id | uuid | no | TFK → channels |
| source_id | uuid | no | TFK → knowledge_sources |
| chunk_no | int | no | `UNIQUE (org_id, source_id, chunk_no)` |
| chapter / section | text | yes | |
| page_from / page_to | int | yes | |
| language | text | no | |
| body | text | no | confidential; never logged, never sent to another tenant's prompts |
| body_sha256 | bytea | no | |
| search_tsv | tsvector | yes | keyword index (GIN); text-search configuration per language **REQUIRES REVIEW (agent_04 blueprint)** |
| embedding_ref | text | yes | vector store reference; store choice **REQUIRES REVIEW (ADR on vector store)** |
| token_count | int | yes | |
Indexes: GIN `(search_tsv)`; `(org_id, channel_id, source_id)`. Every query also filters `channel_id` (channel isolation).

### 5.11 Scripts, claims, citations

**scripts** — TENANT · T0 · Std
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| job_id | uuid | no | TFK → jobs |
| channel_id | uuid | yes | TFK → channels |
| language | text | no | |
| version | int | no | `UNIQUE (org_id, job_id, language, version)` |
| iteration | int | no | revision loop |
| parent_script_id | uuid | yes | TFK → scripts |
| status | enum(script_status) | no | |
| body_ref | text | no | segmented script document |
| content_sha256 | bytea | no | |
| segment_count / word_count | int | no | |
| est_duration_ms | bigint | yes | |
| created_by_task_id | uuid | no | TFK → tasks |
| prompt_id | text | yes | e.g. `agent_05/script_draft.v1` |

**claims** — TENANT · T0+ · Std + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| script_id | uuid | no | TFK → scripts |
| job_id | uuid | no | TFK → jobs |
| segment_id | text | no | |
| char_start / char_end | int | no | CHECK `char_end > char_start` |
| quote | text | no | exact substring of the segment |
| normalized_claim | text | no | |
| claim_type | enum(claim_type) | no | |
| time_reference_kind | enum(time_reference_kind) | no | |
| status | enum(claim_status) | no | |
| rule_flags | jsonb | no | array of `{rule_id, severity, evidence}` |
| proposed_verdict | enum(compliance_verdict) | no | Agent 06 |
| final_verdict | enum(compliance_verdict) | yes | Agent 16 (final authority, Q5) |
| requires_citation | boolean | no | |
| substantiation_ref | text | yes | ad claims: client document (§1D.3) |
| extracted_by_task_id | uuid | no | TFK → tasks |
Index `(org_id, script_id)`.

**citations** — TENANT · T0+ · Std
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| claim_id | uuid | no | TFK → claims |
| knowledge_chunk_id | uuid | yes | TFK → knowledge_chunks |
| external_url | text | yes | verified external reference |
| research_log_id | text | yes | e.g. `YT-09` |
| support | enum(citation_support) | no | |
| accessed_at | timestamptz | yes | required with `external_url` |
CHECK exactly one of `knowledge_chunk_id`, `external_url` is not null.

### 5.12 Brand kits, voices, consents

**brand_kits** — TENANT · T0+ · Std
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| workspace_id | uuid | no | TFK → workspaces |
| version | int | no | `UNIQUE (org_id, workspace_id, version)` |
| is_current | boolean | no | partial `UNIQUE (org_id, workspace_id) WHERE is_current` |
| logo_asset_id | uuid | yes | TFK → assets |
| colours / fonts | jsonb | no | fonts reference licensed font assets |
| lower_third_template_ref / intro_ref / outro_ref | text | yes | |
| voice_id | uuid | yes | TFK → voices |
| tone_rules | jsonb | no | |
| banned_words | text[] | no | |

**voices** — TENANT · T0 · Std + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| display_name | text | no | |
| kind | enum(voice_kind) | no | |
| provider | text | yes | NULL for `HUMAN_RECORDED` |
| provider_voice_ref | text | yes | from config; never hard-coded |
| languages | text[] | no | |
| consent_id | uuid | yes | TFK → voice_consents; CHECK `kind <> 'CONSENTED_CLONE' OR consent_id IS NOT NULL` |
| pronunciation_dict_ref | text | yes | |
| status | enum(asset_status) | no | |

**voice_consents** — TENANT · T0+ · Std + Mut (§1A.3, §1C.8)
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| voice_owner_name | text | no | personal data |
| voice_owner_user_id | uuid | yes | FK → users |
| consent_document_ref / consent_recording_ref | text | no / yes | |
| verification_method | text | no | |
| verified_by | uuid | yes | FK → users |
| verified_at | timestamptz | yes | |
| scope_note | text | no | permitted uses/channels |
| third_party_use | boolean | no | |
| state | enum(consent_state) | no | only `VERIFIED` voices may be rendered (Agent 07 check) |
| expires_at / withdrawn_at | timestamptz | yes | |

### 5.13 Audit (append-only, tamper-evident per tenant)

**audit_log** — TENANT · T0 · append-only · partitioned by month on `occurred_at`
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| id | uuid | no | `aud_` |
| org_id | uuid | no | |
| seq | bigint | no | gap-free per org, assigned under the chain-head lock |
| occurred_at | timestamptz | no | |
| actor_kind | enum(actor_kind) | no | human **and** agent actions (§1C.5) |
| actor_ref | text | no | |
| on_behalf_of | uuid | yes | user under whose authority an agent/service acted |
| authority | text | no | role or policy ID |
| action | text | no | dotted event name (e.g. `task.completed`, `approval.decided`, `control.emergency_stop.changed`) |
| target_kind | text | no | |
| target_id | uuid | yes | |
| job_id | uuid | yes | |
| correlation_id | uuid | yes | |
| details | jsonb | no | no secrets; personal data minimised (22) |
| prev_hash | bytea | no | 32 bytes; genesis = 32 zero bytes |
| row_hash | bytea | no | SHA-256(`prev_hash` ‖ canonical JSON of all columns above except `row_hash`), computed in `amw_core.audit` |
PK `(org_id, seq, occurred_at)`. Index `(org_id, target_kind, target_id)`, `(org_id, action, occurred_at)`.
Rules: `amw_app` has `INSERT` only; a trigger rejects `UPDATE`/`DELETE` for every role. Export as CSV/JSON per tenant (§1C.5). A daily verification job recomputes the chain; a mismatch is an L3 security incident. The current head hash of each org is copied with the off-server backup so truncation is detectable. Retention: partitions are exported then detached only by `amw_migrator`, after writing an `audit.retention_applied` entry; durations per plan **REQUIRES REVIEW (Phase 1): retention schedule from 22_DATA_PROTECTION / 21_PRICING_AND_PACKAGING.**

**audit_chain_heads** — TENANT · T0 · PK `org_id`; `last_seq bigint`, `last_hash bytea`, `updated_at`. The writer takes `SELECT … FOR UPDATE` on the head, inserts the row, updates the head, in the same transaction (serialises audit writes per tenant; throughput is measured in the pilot).

### 5.14 Cost and budgets (S4)

**cost_ledger** — TENANT · T0 · append-only · partitioned by month on `occurred_at`
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| job_id / task_id / attempt_id | uuid | yes | TFKs |
| channel_id | uuid | yes | TFK → channels |
| agent_id | text | yes | executor ID |
| provider | text | no | |
| model | text | yes | from config, recorded per call |
| operation | text | no | e.g. `llm.completion`, `tts.synthesize`, `stock.license`, `youtube.quota` |
| billing_mode | enum(billing_mode) | yes | LLM calls |
| tokens_in / tokens_out / tokens_cached_in | int | yes | |
| units | numeric(20,6) | yes | non-token units |
| unit_kind | text | yes | `characters`, `audio_ms`, `images`, `video_ms`, `render_ms`, `quota_units`, `items` |
| amount_micros | bigint | no | ≥ 0 |
| currency | char(3) | no | |
| fx_rate / fx_source | numeric(18,8) / text | yes | |
| figure_kind | enum(cost_figure_kind) | no | |
| price_ref | text | yes | pricing config version used for an ESTIMATE |
| estimate_entry_id | uuid | yes | TFK → cost_ledger; a VERIFIED row points to the ESTIMATE it confirms; estimates are never overwritten |
| verification_ref | text | yes | provider usage export / invoice reference |
| idempotency_key | text | yes | scope `llm.call` etc.; `UNIQUE (org_id, idempotency_key, figure_kind, occurred_at)` |
| occurred_at | timestamptz | no | |
PK `(id, occurred_at)`. Indexes `(org_id, job_id)`, `(org_id, occurred_at)`.

**budgets** — TENANT · T0 · Std + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| scope_kind | enum(budget_scope_kind) | no | |
| scope_id | uuid | yes | NULL for `ORG`; else workspace/channel ID; production type key in `scope_key` |
| scope_key | text | yes | for `PRODUCTION_TYPE` |
| period | enum(budget_period) | no | |
| limit_minor | bigint | no | ≥ 0; values set by the owner/tenant (rule 8), never defaulted silently |
| currency | char(3) | no | |
| soft_limit_ratio | numeric(4,3) | no | warning threshold 0–1 |
| state | enum(budget_state) | no | |
| non_critical_suspend | boolean | no | default true: auto-suspend new non-critical paid jobs when exceeded (S4) |

**budget_reservations** — TENANT · T0 · Std + Mut: `budget_id` TFK → budgets, `task_id` TFK → tasks, `amount_micros bigint`, `currency`, `status enum(reservation_status)`, `released_at`. Index `(org_id, budget_id, status)`.

### 5.15 Licences and assets

**licences** — SHARED-CATALOGUE · T0 · Std + Mut (org_id NULL = platform-held, e.g. the platform's stock library account)
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| org_id | uuid | yes | |
| licence_key | text | no | |
| vendor | text | no | |
| source_type | enum(licence_source_type) | no | |
| licence_name | text | no | vendor's licence name/version |
| covers_monetized_youtube | boolean | yes | NULL = unknown → blocks monetized use |
| third_party_permission | enum(third_party_permission) | no | |
| indemnification | boolean | yes | |
| channel_registration_supported | boolean | yes | §1A.1b |
| territory | text | yes | |
| starts_at / expires_at | timestamptz | no / yes | |
| state | enum(licence_state) | no | |
| terms_ref / terms_sha256 | text / bytea | no | snapshot of the terms |
| verified_by / verified_at | uuid / timestamptz | yes | |

**licence_ledger** — TENANT · T0 · append-only · Std (org_id = the tenant the item was used for, §1C.8)
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| asset_id | uuid | no | TFK → assets |
| licence_id | uuid | no | FK → licences |
| job_id | uuid | no | TFK → jobs |
| render_id | uuid | yes | TFK → renders |
| usage_kind | enum(licence_usage_kind) | no | |
| source_url / vendor_item_id | text | yes | |
| used_from_ms / used_to_ms | bigint | yes | position in the render |
| client_permission_ref | text | yes | evidence for third-party/client use |
| expiry_at | timestamptz | yes | |
| recorded_by | text | no | actor ref |
Trigger (insert guard): licence `state = 'ACTIVE'`; if the licence is platform-held (`org_id IS NULL`) and this org is not the platform owner org, then `third_party_permission = 'PERMITTED'`; if the job publishes to a monetized destination, `covers_monetized_youtube = true`. Index `(org_id, job_id)`, `(org_id, licence_id)`.

**assets** — TENANT · T0 · Std + Mut (per-tenant library; never shared across tenants, rule 9)
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| workspace_id | uuid | yes | TFK → workspaces |
| kind | enum(asset_kind) | no | |
| visual_source_tier | enum(visual_source_tier) | yes | required for VIDEO/IMAGE/CHART (CHECK) |
| title | text | yes | |
| storage_ref / content_sha256 | text / bytea | no | `UNIQUE (org_id, content_sha256)` |
| size_bytes | bigint | no | |
| media_type | text | no | |
| duration_ms / width_px / height_px | bigint / int / int | yes | |
| source_type | enum(licence_source_type) | no | |
| source_url / vendor_item_id | text | yes | |
| licence_id | uuid | yes | FK → licences; required unless `OWNER_MADE`/`CODE_GENERATED` (CHECK) |
| is_realistic_synthetic | boolean | no | feeds the disclosure decision (YT-06/07) |
| depicts_real_person | boolean | no | |
| release_ref | text | yes | model/property release (§1D.3) |
| allowed_channel_ids | uuid[] | yes | NULL = all channels of this org (reuse engine channel permission) |
| expires_at | timestamptz | yes | licence expiry copy |
| status | enum(asset_status) | no | |

**asset_fingerprints** — TENANT · T0+ · Std: `asset_id` TFK → assets, `algo enum(fingerprint_algo)`, `value bytea`, `frame_ms bigint NULL`. Index `(org_id, algo, value)`. Matching runs only inside one tenant (S2 uniqueness, reuse engine).

### 5.16 Approvals and editorial contribution (S7)

**approvals** — TENANT · T0 · Std + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| job_id | uuid | yes | TFK → jobs |
| kind | enum(approval_kind) | no | |
| subject_kind | text | no | `script`, `render`, `thumbnail`, `metadata`, `concept`, `brief`, `budget`, `dead_letter`, `experiment`, `comment_reply`, `knowledge_source`, … |
| subject_id | uuid | no | |
| subject_sha256 | bytea | yes | binds the decision to exact content |
| state | enum(approval_state) | no | |
| workflow_key | text | no | approval workflow from the production type (24) |
| current_step | int | no | |
| managed_service | boolean | no | true only when the client contracted managed service (rule 10) |
| requested_by | text | no | actor ref |
| decided_at / expires_at | timestamptz | yes | |
Index `(org_id, state, kind)`.

**approval_steps** — TENANT · T0 · Std + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| approval_id | uuid | no | TFK → approvals |
| step_no | int | no | `UNIQUE (org_id, approval_id, step_no)` |
| required_role | enum(role) | no | e.g. `REVIEWER_APPROVER`, `CLIENT_GUEST` (T2 client reviewer → client final approver) |
| assignee_user_id | uuid | yes | FK → users |
| state | enum(approval_step_state) | no | |
| decided_by | uuid | yes | FK → users; must be a human with an `ACTIVE` membership in this org holding `required_role` (trigger) |
| decided_at | timestamptz | yes | |
| comment | text | yes | |

**editorial_contributions** — TENANT · T0 · Std
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| job_id | uuid | no | TFK → jobs |
| approval_id | uuid | yes | TFK → approvals |
| contributor_user_id | uuid | no | FK → users (a human; agents cannot write this table — grant via the API role path only, enforced by trigger checking `app.actor` is a `usr_` actor) |
| type | enum(editorial_contribution_type) | no | |
| description | text | no | ≥ 20 chars (meaningful; threshold configurable) |
| target_ref | text | yes | script segment / shot / thumbnail |
Index `(org_id, job_id)`.

### 5.17 Quality, QC and compliance

**quality_scores** — TENANT · T0 · Std: `job_id` TFK, `subject_kind text`, `subject_id uuid`, `subject_sha256 bytea`, `rubric_version text`, `dimension enum(quality_dimension)`, `max_points smallint` (CHECK equals the dimension's points, GLOSSARY §6.45), `points numeric(5,2)` (CHECK `0 ≤ points ≤ max_points`), `scorer_kind enum(check_kind)`, `scorer_ref text`, `evidence_ref text NULL`. Index `(org_id, job_id, subject_id)`. The total per subject is a view; per dimension the `HUMAN` row wins over `LLM_JUDGE` (§1A.7). Publish threshold (85) is config `quality.publish_min_score`.

**qc_results** — TENANT · T0 · Std (persisted `validation_results`): `job_id` TFK, `task_id` TFK, `render_id` TFK NULL, `check_id text`, `kind enum(check_kind)`, `verdict enum(check_verdict)`, `blocking boolean`, `rule_id text NULL`, `measured_num numeric NULL`, `measured_text text NULL`, `threshold_num numeric NULL`, `threshold_text text NULL`, `unit text NULL`, `message text`, `evidence_ref text NULL`. Index `(org_id, job_id, check_id)`.

**compliance_verdicts** — TENANT · T0 · Std
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| job_id | uuid | no | TFK → jobs |
| subject_kind / subject_id / subject_sha256 | text / uuid / bytea | no | |
| rule_pack_id | uuid | no | FK → rule_packs |
| rule_pack_version | int | no | |
| rule_id | text | yes | NULL = pack-level / overall verdict |
| verdict | enum(compliance_verdict) | no | |
| disclosure_decision | enum(disclosure_decision) | yes | for disclosure rules (YT-06/07) |
| rationale | text | no | |
| evidence_ref | text | yes | |
| decided_by | text | no | actor ref (Agent 16 or human) |
| is_final | boolean | no | true only for Agent 16's publication authorisation or a human override (Q5) |
Index `(org_id, job_id, is_final)`.

### 5.18 Renders

**renders** — TENANT · T0 · Std + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| job_id | uuid | no | TFK → jobs |
| script_id | uuid | yes | TFK → scripts |
| kind | enum(render_kind) | no | |
| preset_key | text | no | export preset (24 §4) |
| version | int | no | |
| timeline_sha256 | bytea | no | |
| width_px / height_px | int | no | |
| fps_num / fps_den | int | no | |
| video_codec / audio_codec | text | no | |
| video_bitrate_bps / audio_bitrate_bps | bigint | yes | |
| audio_sample_rate_hz | int | yes | |
| duration_ms | bigint | no | |
| integrated_lufs / true_peak_dbtp | numeric(5,2) | yes | measured (INF-09) |
| size_bytes | bigint | no | |
| storage_ref / content_sha256 | text / bytea | no | persistent storage only |
| status | enum(render_status) | no | |
| worker_id | uuid | yes | FK → workers |
Keys: `UNIQUE (org_id, content_sha256)`.

### 5.19 YouTube access, tokens, data keys

**gcp_projects** — SHARED-CATALOGUE · T0 · Std + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| org_id | uuid | yes | NULL = platform project; set for a client-owned project (§1C.3 enterprise option) |
| ownership | enum(gcp_ownership) | no | CHECK `(ownership = 'PLATFORM') = (org_id IS NULL)` |
| project_label | text | no | display label; the project identifier itself is configuration, not stored here |
| oauth_verification_status | enum(google_review_status) | no | Tier 1 gate (YT-12) |
| api_audit_status | enum(google_review_status) | no | Tier 1 gate (YT-11) |
| quota_limits | jsonb | no | per bucket; defaults from YT-02, confirmed from the Console (A4) |

**oauth_tokens** — TENANT · T0 · Std + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| channel_id | uuid | no | TFK → channels |
| gcp_project_id | uuid | no | FK → gcp_projects |
| scopes | text[] | no | minimum scopes (§1C.3; YT-12) |
| granted_by_user_id | uuid | no | FK → users |
| access_token_ct / access_token_nonce | bytea | yes | AEAD ciphertext + nonce |
| refresh_token_ct / refresh_token_nonce | bytea | no | |
| data_key_id | uuid | no | TFK → tenant_data_keys |
| expires_at | timestamptz | yes | access token expiry |
| status | enum(oauth_token_status) | no | |
| last_refreshed_at / revoked_at | timestamptz | yes | |
Keys: partial `UNIQUE (org_id, channel_id) WHERE status = 'ACTIVE'`. Column grants: `*_ct`, `*_nonce` readable only by `amw_publisher`. Never logged.

**tenant_data_keys** — TENANT · T0 · Std: `wrapped_key bytea` (DEK encrypted by the key-encryption key), `kek_ref text` (reference to the KEK in the environment/KMS, never its value), `algorithm text` (chosen in 08), `status enum(data_key_status)`, `rotated_at timestamptz NULL`. Crypto-shredding: destroying an org's DEKs makes its tokens unreadable (supports erasure, 22).

### 5.20 YouTube quota

**quota_usage** — SHARED-CATALOGUE · T0 · (no `id`) PK `(gcp_project_id, pt_date, bucket)`
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| org_id | uuid | yes | NULL for platform projects, else the owning tenant |
| gcp_project_id | uuid | no | FK → gcp_projects |
| pt_date | date | no | US Pacific date (YT-03; GLOSSARY §4) |
| bucket | enum(quota_bucket) | no | YT-02, YT-05 |
| units_used | bigint | no | |
| units_reserved | bigint | no | reserved before a call, settled after |
| units_limit | bigint | no | snapshot of the configured limit for that day |
| updated_at | timestamptz | no | |
Updated only through `amw_quota_reserve/release` (§3.6). Per-tenant attribution of shared-project units is in `cost_ledger` (`operation = 'youtube.quota'`, `unit_kind = 'quota_units'`).

### 5.21 Publications and deliveries

**publications** — TENANT · T0 · Std + Mut
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| job_id | uuid | no | TFK → jobs |
| channel_id | uuid | yes | TFK → channels; required for `YOUTUBE` |
| render_id | uuid | no | TFK → renders |
| render_sha256 | bytea | no | copy of the render's hash |
| destination_kind | enum(destination_kind) | no | |
| state | enum(publish_state) | no | |
| privacy_status | enum(privacy_status) | yes | upload always `private` (YT-04) |
| external_video_id | text | yes | YouTube video ID; `UNIQUE (org_id, external_video_id)` |
| upload_session_ct / upload_session_nonce | bytea | yes | resumable session URI, encrypted with the tenant DEK |
| contains_synthetic_media | boolean | yes | required for `YOUTUBE` (CHECK); from Agent 16's disclosure decision (YT-06) |
| disclosure_verdict_id | uuid | yes | TFK → compliance_verdicts |
| approval_id | uuid | no | TFK → approvals |
| authorisation_verdict_id | uuid | no | TFK → compliance_verdicts (`is_final`, verdict `ALLOWED`) |
| gcp_project_id | uuid | yes | FK → gcp_projects |
| scheduled_publish_at / published_at | timestamptz | yes | |
| verification_state | enum(verification_state) | no | default `NOT_CHECKED` |
| verified_at | timestamptz | yes | |
| verification_details | jsonb | yes | compared fields (privacy, title, disclosure flag) |
| idempotency_key | text | no | scope `upload.youtube` / `delivery.file`; `UNIQUE (org_id, idempotency_key)` |
Keys: partial `UNIQUE (org_id, channel_id, render_sha256) WHERE destination_kind = 'YOUTUBE' AND state <> 'FAILED'` (duplicate prevention).
**Publish guard trigger** (on insert and on any change of `state` to `UPLOADING`, `SCHEDULED` or `PUBLISHED`): the approval is `APPROVED`, of kind `FINAL_VIDEO` or `PUBLISH`, with `subject_sha256 = render_sha256`; at least one `editorial_contributions` row exists for the job; the authorisation verdict is final `ALLOWED` for the same subject hash; `contains_synthetic_media` is not null for `YOUTUBE`. The quality threshold (≥ 85, config) is checked by Agent 16 before it writes the authorisation verdict. This enforces "never publish an unapproved video" (rule 5) in the DB as well as in code.
Also kids handling: **REQUIRES REVIEW (Phase 1): verify the YouTube "made for kids" status field on the official `videos` resource page before adding a column.**

### 5.22 Analytics and learning loop

**analytics_snapshots** — TENANT · T0+ · append-only · partitioned by month on `fetched_at`
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| channel_id | uuid | no | TFK → channels |
| publication_id | uuid | yes | TFK → publications (NULL = channel-level) |
| source | enum(analytics_source) | no | YT-14: retention via Analytics API, impressions/CTR via Reporting API |
| report_type | text | no | |
| metric_date | date | no | time zone **REQUIRES REVIEW** (GLOSSARY §4) |
| dimensions / metrics | jsonb | no | only values returned by the API; never fabricated (rule 4) |
| report_ref | text | yes | raw report blob |
| fetched_at | timestamptz | no | |
PK `(id, fetched_at)`. Index `(org_id, publication_id, metric_date)`.

**experiments** — TENANT · T0+ · Std + Mut (§3.3 learning loop)
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| channel_id | uuid | yes | TFK → channels |
| kind | enum(experiment_kind) | no | |
| hypothesis | text | no | |
| baseline / variants | jsonb | no | |
| primary_metric | text | no | |
| sample_size_target | int | no | |
| duration_target_ms | bigint | no | |
| state | enum(experiment_state) | no | |
| result | jsonb | yes | measured values only |
| confidence | numeric(4,3) | yes | no significance claim without sufficient data (§3.3) |
| decision | enum(experiment_decision) | no | default `NONE` |
| approval_id | uuid | yes | TFK → approvals (`EXPERIMENT`); required for `APPROVED_TO_RUN` and `APPLIED` |
| started_at / ended_at | timestamptz | yes | |
| created_by | text | no | actor ref |

### 5.23 Notifications, review comments, community comments

**notifications** — TENANT · T0 · Std + Mut: `user_id` FK → users, `channel enum(notification_channel)`, `template_key text`, `subject_kind text`, `subject_id uuid`, `status enum(notification_status)`, `sent_at`, `read_at`, `error_code text NULL`, `idempotency_key text` (`UNIQUE (org_id, idempotency_key)`). Email first (§1C.6).

**review_comments** — TENANT · T2 · Std + Mut (client portal time-coded comments): `job_id` TFK, `subject_kind text`, `subject_id uuid`, `subject_version int`, `timecode_ms bigint NULL`, `author_user_id` FK → users, `body text`, `resolved_at`, `resolved_by`.

**community_comments** — TENANT · T0+ · Std + Mut (S13)
| Column | Type | Null | Constraint / note |
|---|---|---|---|
| channel_id | uuid | no | TFK → channels |
| publication_id | uuid | yes | TFK → publications |
| external_comment_id | text | no | `UNIQUE (org_id, external_comment_id)` |
| author_display | text | no | personal data (22 retention) |
| body | text | no | |
| triage_class | enum(comment_triage_class) | no | |
| triage_confidence | numeric(4,3) | yes | |
| reply_draft | text | yes | |
| reply_state | enum(reply_state) | no | `POSTED` requires an `APPROVED` approval (trigger) |
| reply_approval_id | uuid | yes | TFK → approvals (`COMMENT_REPLY`) |
| reply_verdict_id | uuid | yes | TFK → compliance_verdicts (finance pack applies) |
| fetched_at | timestamptz | no | |

### 5.24 Data protection

**data_requests** — TENANT · T1 · Std + Mut: `kind enum(data_request_kind)`, `status enum(data_request_status)`, `requested_by uuid` FK → users, `subject_note text`, `artefact_ref text NULL` (export bundle URI), `completed_at`. Export = every row of the org + its storage prefix (03 §8.1); erasure = delete rows + storage prefix + destroy DEKs, except records that must be retained (22).

### 5.25 Billing and metering (Tier 2)
| Table | Scope | Columns (beyond Std + Mut) |
|---|---|---|
| **plans** | GLOBAL | `key text UNIQUE`, `name text`, `limits jsonb` (concurrency, daily videos, render minutes, spend caps, audit retention), `price_minor bigint NULL` — **REQUIRES REVIEW (Phase 1): prices from 21_PRICING_AND_PACKAGING (PROPOSAL until owner approval)**, `currency char(3)`, `status enum(plan_status)` |
| **subscriptions** | TENANT | `plan_id` FK → plans, `status enum(subscription_status)`, `period_start`, `period_end`, `gateway_ref text NULL` (ADR-010) |
| **usage_events** | TENANT, partitioned by month | `meter enum(usage_meter)`, `quantity numeric(20,6)`, `unit text`, `job_id uuid NULL`, `cost_entry_id uuid NULL`, `occurred_at`; append-only; source = S4 cost tracking (§1C.9) |
| **invoices** | TENANT | `number text` (`UNIQUE (org_id, number)`), `period_start`, `period_end`, `amount_minor`, `tax_minor` (GST), `currency`, `status enum(invoice_status)`, `gateway_ref`, `pdf_ref`, `idempotency_key` |

### 5.26 Integration API and enterprise identity (Tier 3)
| Table | Scope | Columns (beyond Std + Mut) |
|---|---|---|
| **api_keys** | TENANT | `name`, `key_prefix text` (display), `key_hash bytea` (algorithm per 08), `scopes text[]`, `status enum(api_key_status)`, `expires_at`, `last_used_at`, `created_by` |
| **webhooks** | TENANT | `url text`, `events text[]` (`job.finished`, `approval.needed`, `published`, `failed`; §1C.12), `secret_ct bytea`, `secret_nonce bytea`, `data_key_id` TFK → tenant_data_keys, `status` |
| **webhook_deliveries** | TENANT | `webhook_id` TFK, `event text`, `event_id uuid`, `payload_ref text`, `attempt int`, `status enum(webhook_delivery_status)`, `response_status int NULL`, `next_attempt_at`, `idempotency_key` |
| **org_sso_connections** | TENANT | `protocol text` (`SAML`/`OIDC`), `metadata_ref text`, `scim_token_hash bytea NULL`, `enforced boolean`, `status` |
| **org_domains** | TENANT | `domain text` (`UNIQUE (domain)` among verified rows — **REQUIRES REVIEW (08)**: global uniqueness reveals that a domain is claimed; decide in 08), `verification_token_hash`, `verified_at` |

---

## 6. Partitioning
| Table | Partition key | Granularity | Reason |
|---|---|---|---|
| audit_log | `occurred_at` | month | append-heavy; retention by partition |
| state_transitions | `occurred_at` | month | one row per transition |
| message_log | `sent_at` | month | one row per message |
| cost_ledger | `occurred_at` | month | one row per paid call |
| analytics_snapshots | `fetched_at` | month | daily ingestion |
| usage_events (T2) | `occurred_at` | month | metering |
Declarative range partitioning; partitions created ahead by a maintenance task (`sys_migrator`). Primary keys include the partition key (shown per table). Volumes per month are ESTIMATE until the pilot measures them; Tier 0 volumes may not need partitioning yet, but the keys are designed now so it can be enabled without a schema change.

## 7. Retention (configuration; values REQUIRES REVIEW)
| Data class | Rule | Value |
|---|---|---|
| Audit log | per plan; export before detach | **REQUIRES REVIEW (Phase 1): 22 + 21** |
| Jobs, tasks, attempts, transitions, messages | job retention per plan | **REQUIRES REVIEW (Phase 1): 22** |
| Queue rows `DONE`/`CANCELLED` | deleted after `retention.queue_done_ms` | design default 7 days (ESTIMATE; operational, not legal) |
| Idempotency keys | `upload.*`, `publish.*` never; others with job retention | — |
| Cost ledger, invoices | statutory accounting retention | **REQUIRES REVIEW (Phase 1): owner's accountant / 22** |
| Personal data (users, comments, consents) | DPDP retention/erasure | **REQUIRES REVIEW (Phase 1): 22 + lawyer** |
| Finished media | until the tenant deletes or offboards; never only in temp | — |

## 8. Migrations
1. Forward-only, ordered, checksummed migration files under `migrations/`; each runs in one transaction as `amw_migrator`. Tool: plain SQL files with a small runner, or a pinned tool chosen in 27 §3 — **REQUIRES REVIEW (Phase 1): record the chosen tool and version in RESEARCH_LOG.md.**
2. Every migration that adds a table adds its RLS policy in the same file; the CI catalogue check (§3.7.6) fails otherwise.
3. Seed data (`state_transition_rules`, platform `rule_packs`, `production_types`) is versioned with the migrations.
4. The same migrations build a dedicated single-tenant stack (§1C.1 premium option): no fork.

## 9. MVP (Tier 0) summary
- Built in the first build: all `T0` tables in §4, with full RLS and the cross-tenant test suite, even though only one tenant (platform owner) and one channel exist.
- `T0+` tables are created when their agent is built (after the walking skeleton), still before any client.
- `T1` (`data_requests`, platform-owner cross-tenant summary) before the first external client; `T2` billing and review comments; `T3` API keys, webhooks, SSO, domains — each only when the tier gate of §1C.15 is reached.
