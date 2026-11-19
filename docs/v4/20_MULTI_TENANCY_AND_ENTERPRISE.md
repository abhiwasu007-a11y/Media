# 20 — Multi-Tenancy and Enterprise

| Field | Value |
|---|---|
| Status | **Draft - documentation** (rule 6). Software: **Planned** (rule 7). |
| Owner agent / service | Agent 01 (S9 Tenant, Identity & Access; S12 Integration API; S8 controls). Contributing owners: Agent 16 (S6 Security & Audit, rule packs, licence gate), Agent 15 (S4 cost, S10 Billing), Agent 13 (S11 Client Portal and brand kits; YouTube access). |
| Depends on | `MASTER_DIRECTIVE.md` §1C; Wave A: `GLOSSARY_AND_IDS.md`, `03_COMMUNICATION_STANDARD.md`, `04_DATABASE_ARCHITECTURE.md`, `07_FAILURE_MANAGEMENT.md`, `24_PRODUCTION_TYPES.md`, `27_ENGINEERING_STANDARDS.md`; Wave B-1: `08_SECURITY.md`, `09_COST_AND_BUDGET.md`, `13_COMPLIANCE_YOUTUBE_POLICY.md`, `3A_SLICE_SPEC.md`, `adr/*`; other documents by name only: `05_RESOURCE_MANAGEMENT.md`, `10_DEPLOYMENT_AND_MIGRATION.md`, `12_DISASTER_RECOVERY.md`, `14_SHARED_SERVICES.md`, `17_BUSINESS_PLAN.md`, `21_PRICING_AND_PACKAGING.md`, `22_DATA_PROTECTION.md` (planned), `KNOWLEDGE_LIBRARY_PLAN.md`. |
| Directive sections covered | §1C items 1-15 (all); §0 rules 8, 9; §1 (shared VPS); §1B.7 (plans, via 21); §1C.15 (tier gates). |
| MVP scope | 3A: tenancy core, RLS and its tests, audit, budgets, licence ledger (T0 tables only). 3B: none new. 3C and later: everything else, each only when its tier gate is reached (§17). Marked per section as **[3A / 3B / 3C · Tier n]**. |
| Owner decisions applied | D1 (3A: no YouTube upload, no Google OAuth; paid calls only within owner limits; render never in market hours), D2 (fast-track without lowering quality). |

---

## 1. Purpose, boundary and the one rule [3A / 3C · Tier 0-3]

This document specifies, item by item, the enterprise multi-tenant layer of the platform (directive §1C): what each item is, which tier it belongs to, which service owns it and how it is accepted. It does **not** redefine any contract: tables and columns are in `04`, enums and IDs in `GLOSSARY_AND_IDS.md`, the permission matrix in `08 §5.2`, the failure taxonomy in `07`. Where this document needs something that does not exist, it names it with its CCR number and lists it in §19.

**The one rule (directive §1C, first paragraph).** Design for enterprise from day one (data model, isolation, audit, permissions); **build** enterprise features in tiers, each tier only when a paying client needs it (§1C.15). Retrofitting tenancy later is expensive; shipping unused enterprise features early is waste. In practice:

| Built in 3A (Tier 0, one real tenant + one synthetic test org) | Designed now, built at its gate |
|---|---|
| `org_id` on every table, RLS with `FORCE`, tenant context per transaction, cross-tenant test suite, audit log with hash chain, budgets and cost ledger, licence ledger, role enum and permission checks (only the owner is a human user) | Client portal, onboarding wizard, white-label, billing, SSO/SCIM, API and webhooks, dedicated stack, client OAuth, tenant rule packs, status page, penetration test |

**No-spend rule.** Nothing in this document is a purchase or a commitment to purchase. Servers, licences, tests, audits and gateways are **recommended** with a trigger; the owner decides (rule 8).

**Public-repository rule.** This document contains no private method, book titles, course content, server details or secrets (`08 §11`).

## 2. Facts and what is not known [3A / 3C · Tier 0-3]

| Fact | Status | Source |
|---|---|---|
| Table owners bypass RLS unless `FORCE ROW LEVEL SECURITY`; superusers and `BYPASSRLS` roles always bypass; `SET LOCAL` lasts to the end of the transaction | VERIFIED | INF-11 |
| Quota above the YouTube default needs an audit; the individual checks are not listed on the official page | PARTIAL (check list: NOT CONFIRMED) | YT-11 |
| Whether the YouTube OAuth scopes are sensitive/restricted | NOT CONFIRMED; design assumes **sensitive, verification required** | YT-12 |
| Service accounts with the YouTube Data API | NOT CONFIRMED; design rule is per-channel user OAuth regardless | YT-13 |
| `videos.insert`: 1 unit in its own bucket, default 100 calls/day per project; quota day resets at Pacific midnight | VERIFIED | YT-01, YT-02, YT-03 |
| Unverified-project uploads are **no longer** forced private; an unset `privacyStatus` defaults to public | VERIFIED (reverses the directive's §1C.3 "may be held private" wording) | YT-04 |
| ElevenLabs output for client/agency use: ToS gives commercial use and output ownership, **no explicit client/agency clause** | NOT CONFIRMED | PR-05 |
| Storyblocks: Individual licence does not cover reliance by a client; Business licence lets the holder license files to a third-party client in a completed project; Business is by quote | VERIFIED (price: REQUIRES REVIEW) | PR-06 |
| DPDP Rules 2025: Rules 3, 5-16, 22, 23 (notice, security, breach, rights, children) apply after 18 months (about May 2027); the platform is a processor for client data | VERIFIED (milestones computed) ⚖ | IN-07 |
| One shared KVM 2 VPS; no availability promise is honest on it | VERIFIED (plan), design consequence | INF-01, `12 §12` |
| Why shared-schema + `org_id` + RLS is the default for B2B SaaS, and schema-/database-per-tenant trade-offs | **Directive research finding; no RESEARCH_LOG entry yet.** REQUIRES REVIEW (Phase 1): record the official source(s) when ADR-002 is written. | — |
| SSO/SCIM/MFA/RBAC/audit-export as enterprise buyer tests | **Directive research finding; no RESEARCH_LOG entry yet.** REQUIRES REVIEW (Phase 1): record the source when ADR-003 is written. | — |

Everything marked REQUIRES REVIEW is collected in §20. None changes a 3A design decision.

---

## 3. Item 1 — Tenancy model and RLS [3A core · 3C UI · Tier 0 → Tier 1 proofs]

**Owning service:** S9 Tenant, Identity & Access (Agent 01). **Contracts:** `04 §3` (roles, context function, policies, system functions, test requirement), `04 §5.1`; ADR-002 (not yet written).

### 3.1 Model

Shared database, shared schema, `org_id` on every row, PostgreSQL RLS as the database safety net (directive §1C.1, INF-11). Application code **always** filters by tenant explicitly; RLS is the second line of defence, never the only one (`08 §8`, five layers: app filter, RLS, storage URIs, cache keys, logs and metrics).

| Level | Table (04) | Notes |
|---|---|---|
| Organisation (tenant) | `organisations` | `kind` (`PLATFORM_OWNER` / `CLIENT` / `AGENCY`), `status`, `tier`, `is_platform_owner` (exactly one), `data_location_note`, `plan_id` (T2) |
| Workspace / brand | `workspaces` (+ `brand_kits`, 04 §5.12) | A "brand" is a workspace with its current brand kit; one current kit per workspace |
| Channel | `channels` | `compliance_profile_id` required before `CONNECTED`; `gcp_project_id`; per-tenant `production_window` (T1+) |
| Project / job | `projects` (`project_kind`: `SERIES`, `CAMPAIGN`, `CLIENT_ORDER`, `INTERNAL`), `jobs`, `tasks` | |

Every table, queue row, file path, cache key, index, log line and metric carries `org_id`: tables by `04 §3.4`; storage by `amw-blob://<org wire id>/…` and the backend prefix `<root>/<org uuid>/` (03 §8); cache keys `amw:<org wire id>:…` (GLOSSARY §2.4); logs and metrics per `08 §8` layer 5.

### 3.2 Per-tenant objects (directive §1C.1 list mapped to tables)

| Per-tenant object | Table(s) | Scope tag |
|---|---|---|
| Knowledge library and vector index | `knowledge_sources`, `knowledge_chunks`, `citations` (index per tenant; storage prefix `knowledge/`) | T0+; library plan in `KNOWLEDGE_LIBRARY_PLAN.md` |
| Memory | `memory_items` (`memory_scope`) | T0 |
| Asset library and licence ledger | `assets`, `asset_fingerprints`, `licence_ledger` (`licences` is a shared catalogue) | T0 |
| Brand kit | `brand_kits` | T0 (owner's kit, 3A minimal) |
| Voices and consent records | `voices`, `voice_consents` | T0 / T0+ |
| Compliance profile | `compliance_profiles`, `compliance_profile_rule_packs` | T0 |
| Budgets | `budgets`, `budget_reservations`, `cost_ledger` | T0 (3A) |
| YouTube OAuth tokens (encrypted, per-tenant data key) | `oauth_tokens`, `tenant_data_keys` | T0 design, live Tier 1 (`08 §6`) |
| Analytics | `analytics_snapshots`, `experiments` | T0+ |

A tenant's knowledge, asset, voice and analytics data is **never** used for another tenant: no shared memory, no shared vector index, no cross-tenant learning-loop input. (Prompt caching of shared system prompts holds no tenant content, `08 §8` layer 4.)

### 3.3 Why not the alternatives (summary; ADR-002 holds the evidence)

| Option | Position in this design |
|---|---|
| Schema-per-tenant | Not used (catalogue growth with tenant count: directive finding; source to be recorded in ADR-002) |
| Database-per-tenant | Reserved for the **dedicated stack** (item 1 premium option, §16.3): same code and same migrations, one organisation row, RLS still on (`10 §11`, 04 §8.4); never a fork |

### 3.4 Acceptance criteria

| ID | Criterion | Blocking | Scope · Tier |
|---|---|---|---|
| MT-1.1 | The eight checks of `04 §3.7` pass for every TENANT and SHARED-CATALOGUE table (cross-tenant read returns nothing; cross-tenant insert fails `WITH CHECK`; unset context returns 0 rows; tenant-composite FK rejects cross-tenant parent; catalogue rows not writable by tenants; `pg_class` flags check; system functions return no content; storage/cache/log tests) | **Yes** (CI gate) | 3A · T0 |
| MT-1.2 | `amw_app` is not owner and not superuser; `NOBYPASSRLS`; `FORCE ROW LEVEL SECURITY` on every table except the GLOBAL allow-list of `04 §4` (INF-11) | Yes | 3A · T0 |
| MT-1.3 | A request that supplies a foreign `org_id` field is ignored: the API derives `org_id` from the authenticated membership only (`08 §8` layer 1) | Yes | 3A · T0 |
| MT-1.4 | A new table without an RLS policy (or a GLOBAL justification) fails CI (`04 §8.2`) | Yes | 3A · T0 |
| MT-1.5 | Two real tenants (owner + synthetic test org) run concurrent jobs; no artefact (file, cache entry, log line, metric label) of org B is readable in org A's context (`08 §8.2` items 2-5) | Yes | 3A · T0; re-run on every release; extended with a real client org at Tier 1 |
| MT-1.6 | The same migrations build an empty single-tenant database (dedicated option); no hard-coded host, tenant or provider exists in code | Yes (migration test, `10 §15`) | 3A · design kept; build Tier 3 |
| MT-1.7 | Platform-level rows (`org_id IS NULL`) are written only by migrations or audited `amw_sysfn` functions called by a `PLATFORM_OWNER` action (`04 §3.5`) | Yes | 3A · T0 |

**Tier 1 addition (before the first client):** the test suite is run against the production-shaped database on the client-facing server, and the result is stored as gate evidence (§17).

---

## 4. Item 2 — Fair sharing (noisy-neighbour control) [3A design · 3C exercise · Tier 0 → Tier 2]

**Owning service:** Agent 01 (queue claim, S5 signals) with S4 (spend caps). **Contract of record:** `05_RESOURCE_MANAGEMENT.md` §7 (caps, ordering rule in `amw_queue_claim`, threat table). This document states the **requirements** and tiers; it does not restate the ordering formula.

| Control (directive §1C.2) | Where defined | Enforced at | Tier |
|---|---|---|---|
| Per-tenant concurrency limits | `plans.limits` (04 §5.25); platform-owner config | queue claim check (05 §6.3) | defined 3A; enforced from **Tier 1** for external tenants |
| Weighted fair queueing by plan | `fairshare.plan_weight.<plan_key>` (config), ordering in `amw_queue_claim` | claim | Tier 1+ (one tenant in 3A) |
| Per-tenant daily video cap | `plans.limits` | job creation (orchestrator) | **Tier 2** |
| Per-tenant spend cap | `budgets` (`budget_scope_kind = ORG`), S4 reservation | S4 (09) | **Tier 0 for the owner (3A)**; external tenants Tier 1+ |
| Render-minute quota | `plans.limits`; usage from `resource_usage.render_ms` | admission of `HEAVY_CPU` | **Tier 2** |
| One tenant's backlog never starves another or the platform owner's channels | `fairshare.owner_min_weight`, work-conserving `fairshare.max_slot_fraction` | claim | Tier 1+ |

Limit values and weights are configuration; **REQUIRES REVIEW (Phase 1): 21 and owner decision** (05 §7.2).

### Acceptance criteria

| ID | Criterion | Blocking | Scope · Tier |
|---|---|---|---|
| MT-2.1 | Fair-share test: tenant B submits a burst; tenant A's (or the owner's) next task is claimed before B's later tasks once B has reached its share; an idle host is never left idle for fairness (work-conserving) | Yes | 3C · Tier 1 gate |
| MT-2.2 | The platform owner's org is never starved by an external tenant's backlog (`owner_min_weight`) | Yes | 3C · Tier 1 gate |
| MT-2.3 | A tenant over its per-day video or render-minute quota is held at admission with a stated reason, not failed silently (07 principle; 14 S10 criterion 3) | Yes | 3C · Tier 2 |
| MT-2.4 | A tenant cannot raise its own queue `priority` through any input field (05 §7.2 open item closed by a test) | Yes | 3C · Tier 1 gate |
| MT-2.5 | Queue wait per class and per tenant is visible to the platform owner as aggregates only (`amw_platform_ops_summary`, 04 §3.6) | No | 3C · Tier 1 |

---

## 5. Item 3 — YouTube access for client channels (highest platform risk) [3C · Tier 1 gate; none in 3A]

**Owning service:** Agent 13 (publishing, OAuth flow) with S9 (tenant binding) and `08 §6` (encryption). **D1: no Google OAuth and no YouTube upload in 3A.** The design is fixed now so the schema (`04 §5.19`) never changes later.

### 5.1 Rules

1. **Per-channel user OAuth.** Each client authorises its **own** channel through Google OAuth with the minimum scopes needed: upload, manage own videos, read own analytics. **No service accounts**: not confirmed for YouTube (YT-13), and uploads must act as the channel owner regardless. Scope names that exist: `youtube`, `youtube.force-ssl`, `youtube.upload`, `yt-analytics.readonly` (YT-12). The mapping of each API call to its narrowest scope: **REQUIRES REVIEW (Phase 1): Agent 13 blueprint; record in RESEARCH_LOG.**
2. **Verification before the first external client (Tier 1 gate).** Complete Google OAuth app verification for the requested scopes and the YouTube API Services compliance audit. The official page does not list the audit's individual checks (YT-11); the scope classification is not confirmed (YT-12, assumed sensitive). Recorded per GCP project as `gcp_projects.oauth_verification_status` and `api_audit_status` (`google_review_status`: `NOT_STARTED` · `IN_REVIEW` · `PASSED` · `FAILED`).
3. **Private-hold is not available as a safety net.** The directive text says uploads may be held private until the audit is passed; the official page now says unverified-project uploads are **not** restricted to private (YT-04, revision of 2026-11-02). Therefore the platform always sets `privacyStatus = private` explicitly (YT-04) and no design depends on Google forcing private.
4. **Quota is a per-project resource.** Default `videos.insert` is 100 calls/day per project in its own bucket (YT-01, YT-02); quota above the default needs the audit (YT-11). All tenants on the platform's GCP project share that bucket, so per-tenant attribution is recorded in `cost_ledger` (`operation = 'youtube.quota'`, 04 §5.20) and fair sharing applies to publish tasks (§4). The quota day is Pacific time (YT-03).
5. **Enterprise option: client supplies its own Google Cloud project.** `gcp_projects.ownership = CLIENT_OWNED` with `org_id` set (CHECK in 04 §5.19). The client's credentials are tenant secrets (`08 §6.7`); breaker `credential_scope` isolates its failures (07 §4). Quota, verification and audit status belong to that project.
6. **Token lifecycle.** Tokens are envelope-encrypted with the tenant data key; only `amw_publisher` can read ciphertext (`08 §6`, `04 §3.1`). Flows:

| Flow | Behaviour | State change |
|---|---|---|
| Connect | Client (as `ORG_OWNER`/`ORG_ADMIN`, `secret.manage`) completes consent; scopes recorded; compliance profile must already be attached | `channel_status`: `DRAFT` → `CONNECTED`; `oauth_token_status = ACTIVE` |
| Refresh failure / revoked at Google | `PERMANENT.AUTH_INVALID`; L3 security-routed notification (07 §7); no publish attempt | `REFRESH_FAILED` / `REVOKED`; channel `NEEDS_REAUTH` |
| Re-consent | Same connect flow; old ciphertext wiped; audit entry | `NEEDS_REAUTH` → `CONNECTED` |
| Disconnect | Token revoked at Google, ciphertext wiped, queued publish tasks for the channel cancelled with a reason | `DISCONNECTED`; `REVOKED` |
| Pause | Owner/admin stops publishing for a channel without revoking | `PAUSED` |

7. **Publish verification per channel.** After every upload Agent 13 re-reads the published video and compares privacy, title and the `containsSyntheticMedia` flag (YT-06); the result is `publications.verification_state` (`MATCH`/`MISMATCH`); a `MISMATCH` raises a human task and is never silently accepted (04 §5.21).
8. **A client can only publish approved content.** The publish guard of 04 §5.21 (approval `APPROVED` bound to `render_sha256`, an editorial contribution, an `ALLOWED` authorisation verdict) applies to client tenants unchanged. A client approval never replaces the platform's compliance verdict (`13 §10`).
9. **YouTube API Services policy mapping (Tier 1 gate).** YT-11 states the audit checks are not listed and links the Developer Policies. **REQUIRES REVIEW (Phase 1): read the Developer Policies in full and produce a table "policy item → platform control → test" before the first audit submission.** Until then no statement of audit readiness is made.

### 5.2 Acceptance criteria

| ID | Criterion | Blocking | Scope · Tier |
|---|---|---|---|
| MT-3.1 | No code path in 3A requests a Google OAuth token or calls `videos.insert` (D1); a CI search for the client library import and the scope strings finds none | Yes | 3A |
| MT-3.2 | A channel whose org is `CLIENT`/`AGENCY` cannot reach `CONNECTED` unless its `gcp_projects` row has `oauth_verification_status = PASSED` and `api_audit_status = PASSED` (guard CCR-153, Proposed, deferred to 3C, §19 CCR-20-02) | Yes | 3C · **Tier 1 gate** |
| MT-3.3 | Disconnect revokes at Google, wipes ciphertext, cancels queued publishes, writes audit entries | Yes | 3C · Tier 1 |
| MT-3.4 | `REFRESH_FAILED` moves the channel to `NEEDS_REAUTH` and routes an L3 notification; no publish is attempted | Yes | 3C · Tier 1 |
| MT-3.5 | A decrypt attempt by `amw_app` of `*_ct` columns fails at the grant level; ciphertext copied to another org or column fails AEAD authentication (`08 §6.2`) | Yes | 3C · Tier 1 |
| MT-3.6 | Upload sets `privacyStatus = private` explicitly and sets `containsSyntheticMedia` from the disclosure decision; verification compares both | Yes | 3C · Tier 1 |
| MT-3.7 | Quota reservation is per GCP project per Pacific day through `amw_quota_reserve`; exhausted quota defers the publish to the next window, never drops it (04 §5.20, 07) | Yes | 3C · Tier 1 |
| MT-3.8 | Client-owned project: its breaker and quota are isolated from the platform project (07 §4) | Yes | 3C · Tier 3 option |

---

## 6. Item 4 — Identity and access [3A model · 3C UI and live auth · Tier 1 live · SSO/SCIM Tier 3]

**Owning service:** S9 (Agent 01). **Contracts:** roles `GLOSSARY §6.44`, tables `04 §5.1`, permission matrix and authentication hardening `08 §5`, SSO/SCIM/IP allow-list design `08 §7`. Auth library or identity service: **ADR-003 (not yet written)**, chosen by RAM footprint and SSO/SCIM support; **never hand-rolled crypto** (§1C.4).

### 6.1 Roles (enum `role`, GLOSSARY §6.44; matrix in `08 §5.2`, not repeated)

| Role | Purpose | Notes |
|---|---|---|
| `PLATFORM_OWNER` | Runs the platform | Exists only in the org flagged `is_platform_owner` (trigger); **not a tenant super-user**: access to a client's content is an explicit, time-boxed, audited support grant (`08 §5.2` rule 2; policy: REQUIRES REVIEW, owner + ⚖) |
| `ORG_OWNER` / `ORG_ADMIN` | Tenant administration | Admin cannot manage Owner roles |
| `PRODUCER` | Creates and runs jobs | |
| `REVIEWER_APPROVER` | Reviews and decides approval steps | Never an agent (04 §5.16 trigger) |
| `FINANCE` | Budgets and cost views | |
| `VIEWER` | Read-only | |
| `CLIENT_GUEST` | Approve/comment only | Limited by `allowed_channel_ids`/assigned items; single-purpose expiring hash-stored tokens (`08 §5.4`) |

### 6.2 Tiers

| Capability | Tier / scope | Source |
|---|---|---|
| Role model, permission checks server-side, tenant context | **3A · T0** (only the owner is a human user; the matrix is enforced so 3C adds users without rewriting checks, `08 §5.2` rule 4) | 08 |
| Email + password with MFA, Google sign-in, organisation invites | design T0; **live 3C · Tier 1** (mechanics: ADR-003, REQUIRES REVIEW) | §1C.4, 08 §5.5 |
| Org MFA enforcement | Tier 1; storage of the org-level flag: CCR-154 (Proposed, deferred to 3C) §19 CCR-20-03 (04 holds only `users.mfa_enrolled`) | |
| Client Guest tokens | Tier 1 | 08 §5.4 |
| SAML 2.0 / OIDC SSO per organisation, SCIM, domain verification, session policies, IP allow-list | **Tier 3** (`org_sso_connections`, `org_domains`; allow-list storage exists: `org_controls.ip_allowlist`, 04 §5.1, CCR-154) | 08 §7 |

Separation of duty (`08 §5.2` rule 3): the user who requests a spend increase or policy exception cannot be its only approver; an agent can never be an `approval.decide` actor.

### 6.3 Acceptance criteria

| ID | Criterion | Blocking | Scope · Tier |
|---|---|---|---|
| MT-4.1 | One automated test per cell of the permission matrix (`08 §8.2` item 7), denied cells included | Yes | 3A · T0 |
| MT-4.2 | A user of org A requesting org B's job/asset/audit by ID receives not-found (no existence oracle) and the attempt is logged | Yes | 3A · T0 |
| MT-4.3 | Membership removal revokes sessions and guest tokens in the same transaction | Yes | 3C · Tier 1 |
| MT-4.4 | A `CLIENT_GUEST` cannot read another channel's rows or an unassigned item (14 S11 criterion 3) | Yes | 3C · Tier 1 |
| MT-4.5 | `PLATFORM_OWNER` cannot read client tenant content without an active, time-boxed, audited support grant; the grant and every access are in the **client's** audit chain | Yes | 3C · Tier 1 (table: CCR-151, needs owner Q-O18, §19 CCR-20-01) |
| MT-4.6 | With enforced SSO, password login for that org's members is refused; break-glass path exists and is audited (policy ⚖) | Yes | 3C · Tier 3 |
| MT-4.7 | SCIM deprovisioning suspends the membership, revokes sessions and API keys, writes audit entries (`08 §7.2`) | Yes | 3C · Tier 3 |

---

## 7. Item 5 — Audit and governance [3A core · 3C export and verification at scale · Tier 0 → Tier 3 streaming]

**Owning service:** S6 Security & Audit (Agent 16). **Contracts of record:** `04 §5.13` (`audit_log`, `audit_chain_heads`), `08 §9` (what is audited, tamper evidence). Not redefined here.

| Requirement (directive §1C.5) | Design | Scope · Tier |
|---|---|---|
| Append-only, tamper-evident, per tenant | Hash chain `prev_hash`/`row_hash`, gap-free `seq` per org, `INSERT`-only grant plus trigger rejecting `UPDATE`/`DELETE` for every role | **3A · T0** |
| Human **and** agent actions | `actor_kind`, `actor_ref`, `on_behalf_of`, `authority` (role or policy ID), `action`, `target_kind/id` | 3A · T0 |
| Daily verification, mismatch = L3 incident | Verification job; off-server head copy with the backup | 3A (owner org) · all tenants Tier 1 |
| Exportable CSV/JSON | `audit.export` includes `seq`, `prev_hash`, `row_hash` so the recipient can verify independently; permission `audit.export` is `PLATFORM_OWNER`/`ORG_OWNER` only | 3C · Tier 1 |
| Streamable later | Streaming to a client SIEM | **Tier 3** (`08 §9.3` item 4) |
| Retention configurable per plan | Detach by partition only after export and an `audit.retention_applied` entry; durations **REQUIRES REVIEW (Phase 1): 22 + 21** | 3C · Tier 2 (plans) |
| Platform-owner actions in client tenants | Support grants and `amw_platform_ops_summary` calls are audited; support access appears in the client's chain | Tier 1 |

Limits stated honestly (`08 §9.3` item 3): a hash chain proves internal consistency, not authorship; the external head copy and an optional customer-held head receipt close the "recompute every later hash" attack. No "immutable" or "tamper-proof" claim is made in sales text.

### Acceptance criteria

| ID | Criterion | Blocking | Scope · Tier |
|---|---|---|---|
| MT-5.1 | Every action in the 3A rows of `08 §9.2` writes an entry; an agent action carries `on_behalf_of` or a policy `authority` (never empty) | Yes | 3A · T0 |
| MT-5.2 | `UPDATE`/`DELETE` on `audit_log` is rejected for `amw_app`, `amw_migrator` and the owner role (trigger) | Yes | 3A · T0 |
| MT-5.3 | Altering one row in a test copy is detected by the verification job; head-copy comparison detects truncation | Yes | 3A · T0 |
| MT-5.4 | Exported file verifies independently with a documented procedure (an external script recomputes the chain from the export) | Yes | 3C · Tier 1 |
| MT-5.5 | Audit read of org B from org A's context returns nothing (cross-tenant suite) | Yes | 3A · T0 |
| MT-5.6 | High-volume events (per token, per frame) are not audited individually (`08 §9.3` item 6) | No | 3A |

---

## 8. Item 6 — Client experience (agency features) [3A minimal kit only · 3C build · Tier 1 approvals · Tier 2 rest]

**Owning service:** S11 Client Portal, Brand Kits & White-label (Agent 13), over the same API as S8, with S7 approvals (Agent 01). **Contract of record:** `14_SHARED_SERVICES.md` §3.11. Stack: ADR-004 (not yet written; a phone-friendly server-rendered UI is a candidate, decided there by RAM footprint, plan Q15).

| Feature (directive §1C.6) | What it is | Tier | Data |
|---|---|---|---|
| Onboarding wizard | Steps: connect channel, brand kit (logo, colours, fonts, lower-thirds, intro/outro, voice, tone rules, banned words), niche/topics, compliance profile, approval workflow, budget | **Tier 2** (Tier 1: the owner onboards the first client by hand with the same records) | existing tables; wizard progress storage (CCR-155, Proposed, deferred to 3C, §19 CCR-20-04) |
| Content calendar | Per-channel calendar of planned/approved/scheduled items | Tier 1 (read-only view) / Tier 2 | `projects`, `jobs`, `publications` |
| Script and video review with time-coded comments | Reviewer comments tied to a version and a timecode | **Tier 2** (`review_comments`, 04 §5.23). At Tier 1 a reviewer's comment is the `comment` of the approval step | `review_comments` |
| Multi-step approvals | Client reviewer → client final approver (`workflow_key = client_two_step`, S7) | **Tier 1** (managed service, `approvals.managed_service = true`) | `approvals`, `approval_steps` |
| Version history | Every script/render version retained; comments on a superseded version are shown as such | Tier 1 | `scripts`, `renders` (write-once blobs) |
| One-click approve | Binds the decision to `subject_sha256` | Tier 1 | 04 §5.16 |
| Mobile-friendly | Phone layout reviewed for every portal page (owner rule D.3) | Tier 1 | — |
| White-label | Platform branding replaceable per agency tenant (`workspaces.white_label_ref`); custom domain later; branded PDF/email reports | **Tier 2** (custom domain: later; report tooling: REQUIRES REVIEW) | `workspaces` |
| Notifications | Email first; WhatsApp and Slack later through adapters (`notification_channel`) | Email Tier 1; WhatsApp/Slack **Tier 2+** (adapters, no hard-coded provider) | `notifications` |

**3A:** only the owner's minimal brand kit (used by Agents 05, 09, 10, 11); no portal, no guests. **Rules:** a brand-kit change never alters an already approved render (render records the kit version); white-label never exposes another tenant's branding; a client approval is a human act under S7 and cannot be performed by an agent or API key (14 S12).

### Acceptance criteria

| ID | Criterion | Blocking | Scope · Tier |
|---|---|---|---|
| MT-6.1 | Exactly one current brand kit per workspace; each render records the kit version used | Yes | 3A · T0 |
| MT-6.2 | Two-step client approval: step 2 cannot be decided before step 1; the deciding user is human, ACTIVE in this org and holds `required_role` (04 §5.16 trigger) | Yes | 3C · Tier 1 |
| MT-6.3 | Approval is bound to the exact render hash; a newer render invalidates the earlier approval | Yes | 3C · Tier 1 |
| MT-6.4 | Guest isolation (MT-4.4) holds on every portal page | Yes | 3C · Tier 1 |
| MT-6.5 | Phone-layout review (overflow, contrast, cut-off text) is recorded as evidence for each portal page, with screenshots (owner rules A.12, D.3) | Yes (release gate) | 3C · Tier 1 |
| MT-6.6 | White-label settings of tenant A never appear in tenant B's pages, emails or PDFs | Yes | 3C · Tier 2 |
| MT-6.7 | Notification adapters are interchangeable; a failed email send is retried within `07` limits and visible, never dropped | Yes | 3C · Tier 1 |

---

## 9. Item 7 — Compliance profiles (rule packs) per channel [3A on files · 3C tenant packs · Tier 0 → Tier 2]

**Owning service:** Agent 16 (gate). **Contract of record:** `13_COMPLIANCE_YOUTUBE_POLICY.md` (§3 general YouTube pack, §4 platform vs tenant packs, §5 finance pack, §6 stub packs, §7 tenant brand-safety pack, §11 why a tenant cannot disable platform packs). Tables `04 §5.2`. This document does not restate rule text.

| Pack | Status | Scope · Tier |
|---|---|---|
| `rp.youtube_general` | Always on, every YouTube destination, **cannot be disabled by any tenant** | 3A · T0 |
| `rp.finance_sebi_in` (FIN-R1..R13, GLOSSARY §6.38) | Mandatory for category `finance`; no forward-looking statement on a named security even in historical case studies (IN-03, FIN-R13) | 3A · T0 |
| `rp.health`, `rp.kids`, `rp.political_news` | **Stubs**, `DRAFT`, cannot be attached until `ACTIVE`; rule text REQUIRES REVIEW (Phase 1) with ⚖ | 3C · Tier 1 (health), Tier 2 (kids, political/news) per 13 §6, as the first client needs them |
| `rp.tenant_brand_safety` | Tenant-defined banned topics/words, required disclaimers, competitor mentions; severity chosen by tenant; checked **after** platform packs | 3C · Tier 1 |

Rules (directive §1C.7): tenants may **add** rules and packs, never remove or weaken platform-level gates; a tenant rule that contradicts a platform rule loses and the contradiction is logged (13 §4). A profile is required before a channel can be `CONNECTED` (04 §5.1 CHECK). A finance-category client channel is bound to the finance pack and its profile-level rules (FIN-R4, R5, R8) like the owner's. A client wanting a niche whose pack is still a stub is told so and the job is refused with a clear reason, not run unchecked (13 §6).

### Acceptance criteria

| ID | Criterion | Blocking | Scope · Tier |
|---|---|---|---|
| MT-7.1 | A tenant (any role) cannot delete, retire, disable or downgrade a platform pack or rule; constraints and triggers reject it (13 §13 "tamper-proofing", tested) | Yes | 3A built · Tier 1 proved by tenant tests |
| MT-7.2 | Tenant pack checked after platform packs; a contradicting tenant rule is overruled and logged | Yes | 3C · Tier 1 |
| MT-7.3 | A channel with category `finance` cannot be connected or published without the finance pack in its profile | Yes | 3A · T0 |
| MT-7.4 | A profile naming a `DRAFT` stub pack is refused with an explanatory message | Yes | 3C · Tier 1 |
| MT-7.5 | A human override records `is_final` and an approval of kind `POLICY_CHANGE` or `SENSITIVE_CLAIM`; it never edits the pack (13 §4) | Yes | 3C · Tier 1 |
| MT-7.6 | Tenant A's brand-safety rules never apply to or appear in tenant B (RLS on `rule_packs` tenant rows) | Yes | 3C · Tier 1 |

---

## 10. Item 8 — Licensing for client work [3A ledger · Tier 1 gate for client use]

**Owning service:** Agent 16 (licence gate) with Agent 08 (assets) and Agent 07 (voice). **Contracts:** `04 §5.15` (`licences`, `licence_ledger`, `assets`), `04 §5.12` (`voices`, `voice_consents`), `13 §3.6` (YTG-R6 licence completeness), ADR-009 (stock/music sourcing, Proposed).

**Requirement:** every stock footage, music, image, voice and AI-provider licence used for a client must explicitly permit producing content for third parties/clients (an agency or API/end-user licence, not a personal seat). The licence ledger records which tenant each licensed asset was used for. Voice cloning only with a recorded, verifiable consent of the voice owner.

| Provider class | What is known | Tier 0 (owner's channel) | Tier 1 gate (client work) |
|---|---|---|---|
| Stock footage (Storyblocks) | Individual-class licence covers work for one's own clients but not "reliance on this license by any entity, company, or client"; **Business** licence allows licensing files to a third-party client in a completed project; Business by quote (PR-06). Monetized-YouTube and channel-whitelisting terms: PR-06d/e (no explicit text; claim-assistance only) | Individual-class is enough for one channel (PR-06) | **Business licence required**; price REQUIRES REVIEW (Phase 1) |
| Voice (ElevenLabs) | Commercial use and output ownership stated; **no explicit client/agency clause** (PR-05, NOT CONFIRMED) | Own channel | **Written confirmation or an enterprise agreement before any client voice work** (PR-05); until then `licences.third_party_permission` is not `PERMITTED` and the ledger trigger blocks client use |
| LLM/AI video/image providers | Terms for producing for third parties: **REQUIRES REVIEW (Phase 1): read each selected provider's terms (ADR-007, ADR-009 candidates) and record in RESEARCH_LOG** | Own channel | Per provider, same rule: explicit permission or the provider is excluded for client jobs |
| Music, fonts, templates | Same requirement; per-source terms REQUIRES REVIEW (ADR-009) | Own channel | Same |
| Client-supplied material | Client warrants rights; evidence stored (`client_permission_ref`); `visual_source_tier` highest class when it is the client's real material | n/a | Required; treated as `OWNER`-class material of that tenant only |

**Mechanism (already contracted, 04 §5.15):** `licences.third_party_permission` (enum) and `covers_monetized_youtube` (NULL = unknown, blocks monetized use) describe the licence; the `licence_ledger` insert trigger rejects a platform-held licence for a non-platform-owner org unless `third_party_permission = 'PERMITTED'`; `client_permission_ref` holds the evidence; expiry is tracked. A licence a client brings is a tenant-scoped `licences` row (`org_id` set). Asset libraries are **never shared across tenants** (`assets`, rule 9). Voice: only `consent_state = VERIFIED` voices may be rendered (04 §5.12, Agent 07 check); `third_party_use` and `scope_note` must cover the use; withdrawal or expiry blocks new renders.

### Acceptance criteria

| ID | Criterion | Blocking | Scope · Tier |
|---|---|---|---|
| MT-8.1 | A render for tenant X cannot be released if any used asset lacks an `ACTIVE` licence ledger row for X (YTG-R6) | Yes | 3A · T0 |
| MT-8.2 | Using a platform-held licence for a non-owner org with `third_party_permission <> 'PERMITTED'` is rejected by the trigger | Yes | 3A built · Tier 1 proved |
| MT-8.3 | `covers_monetized_youtube IS NULL` blocks use on a monetized destination | Yes | 3A · T0 |
| MT-8.4 | The Tier 1 gate checklist holds written evidence for PR-05 (voice) and the Business-class stock licence (PR-06) before the first client job | Yes (gate) | Tier 1 |
| MT-8.5 | A `CONSENTED_CLONE` voice without a `VERIFIED` consent cannot be selected (CHECK + Agent 07 check); a withdrawn consent blocks subsequent renders and is audited | Yes | 3A design · 3C live · Tier 1 |
| MT-8.6 | Offboarding or licence expiry marks assets `EXPIRED`/`QUARANTINED`; a re-render of an old job shows the licence state, never silently reuses an expired asset | Yes | 3C · Tier 1 |

---

## 11. Item 9 — Billing and metering [3C · Tier 2]

**Owning service:** S10 Billing, Metering & Plans (Agent 15). **Contracts:** tables `04 §5.25` (`plans`, `subscriptions`, `usage_events`, `invoices`), enums `usage_meter`, `subscription_status`, `invoice_status`, `plan_status` (GLOSSARY §6.45), `14 §3.10`, plans and prices `21_PRICING_AND_PACKAGING.md` (**PROPOSAL until the owner approves**; no price appears here). No table of 04 §5.25 is created before Tier 2.

| Requirement (directive §1C.9) | Design |
|---|---|
| Metering from S4 | A scheduled system job rolls `cost_ledger` into `usage_events` (meters `VIDEOS`, `VIDEO_MINUTES`, `RENDER_MINUTES`, `AI_SPEND`, `STORAGE_BYTES`); rollup is idempotent; `CREDITS` meter or derived credits: CCR-165, needs owner Q-O21 (21 §14) |
| Plans and credits | `plans.limits` is the single source for admission checks (05 §7.1); plan families P1/P2/P3 are in 21 |
| Invoices with Indian GST | `invoices.amount_minor` + `tax_minor`, unique number per org; GST registration, rates and invoice content: **REQUIRES REVIEW (Phase 1): chartered accountant / owner's lawyer ⚖** (17 §13.2 C4) |
| Payment gateway adapter | ADR-010 (not written): Indian gateway first, international later; adapter behind an interface, no provider hard-coded |
| Dunning | `subscription_status`: `ACTIVE` → `PAST_DUE` → `SUSPENDED` → `CANCELLED`. Suspension holds **new admission** with a stated reason; running jobs finish; data is never deleted by dunning; reminder schedule and grace periods: REQUIRES REVIEW (Phase 1): owner + ⚖ |
| Plan limits enforced in the queue | Held at admission, not failed (§4, MT-2.3) |

**Rules.** Money in minor units with a currency code per row (GLOSSARY §3). **No LLM may compute, round or explain an amount.** Client billing is a platform feature; the platform owner's own spending still follows rule 8 and the budgets of 09. A plan or price change is a `POLICY_CHANGE` approval by the platform org's `ORG_OWNER`; credits/refunds are `SPEND` approvals (14 §3.10). Per-video margin is an owner-only view, never shown to the client.

### Acceptance criteria

| ID | Criterion | Blocking | Scope · Tier |
|---|---|---|---|
| MT-9.1 | Re-running the rollup over the same ledger range creates no duplicate `usage_events` (idempotency key, 03 §9.2) | Yes | 3C · Tier 2 |
| MT-9.2 | For each org and period, the sum of a meter equals the corresponding `cost_ledger` consumed amount (reconciliation test) | Yes | 3C · Tier 2 |
| MT-9.3 | Invoice numbers are unique per org; an issued invoice is never edited (corrections are new documents) | Yes | 3C · Tier 2 |
| MT-9.4 | Gateway webhook/callback processing is idempotent and signature-checked; a duplicate callback does not double-credit | Yes | 3C · Tier 2 |
| MT-9.5 | A tenant sees only its own subscription, usage and invoices; cross-tenant revenue totals exist only through the platform aggregate function | Yes | 3C · Tier 2 |
| MT-9.6 | Past-due suspension holds admission with a visible reason and loses no data or in-flight job | Yes | 3C · Tier 2 |

---

## 12. Item 10 — Data protection (pointer) [3C · Tier 1 gate]

**The specification is `22_DATA_PROTECTION.md` (planned; directive §1C.10 requires it). This section only states what the tenancy layer must provide to it and what is a gate.** Not legal advice; every item marked ⚖ goes to the owner's lawyer.

| Item | Requirement on this layer | Where designed | Tier |
|---|---|---|---|
| Role of the platform | For client data the platform is usually a **data processor** under a written agreement (IN-07: processor processes on behalf of a fiduciary) ⚖ | 22; 17 §13.2 C2 | Tier 1 |
| DPDP milestones | Core obligations (notice, security, breach, rights, children) apply from about May 2027 (IN-07); design now, in place **before the first client** | 22 | Tier 1 gate |
| DPA template, privacy notice, retention schedules, breach-response runbook | Documents, not code | 22, `08 §12` | Tier 1 gate |
| Per-tenant export and erasure | `data_requests` (`EXPORT`/`ERASURE`), one storage prefix plus rows; export bundle under `exports/<dtr>/`, single-tenant expiring link; erasure includes crypto-shredding of the tenant data keys | `04 §5.24`, `12 §10`, `08 §6.6` | **3C · Tier 1** |
| Encryption in transit and at rest for secrets/tokens | Envelope encryption per tenant | `08 §6` | Tier 1 live |
| Least-privilege staff access | Roles `04 §3.1`; support grants (§6) | 08 | Tier 1 |
| Data-location statement | `organisations.data_location_note`; value per hosting choice | 22, `10 §11` | Tier 1 |

### Acceptance criteria

| ID | Criterion | Blocking | Scope · Tier |
|---|---|---|---|
| MT-10.1 | Export of org A contains every row of A and its storage prefix and nothing of B (tested with the synthetic org) | Yes | 3C · Tier 1 gate |
| MT-10.2 | Erasure of a test tenant removes rows and blobs, destroys its data keys, and appears in the erasure ledger so a later restore re-applies it (`12 §10.5`) | Yes | 3C · Tier 1 gate |
| MT-10.3 | The audit log of an erased tenant is handled per the retention rule decided in 22 (REQUIRES REVIEW ⚖); the decision is recorded before the first client | Yes (gate) | Tier 1 |
| MT-10.4 | DPA, privacy notice and breach runbook exist and are reviewed by the owner's lawyer before the first client contract | Yes (gate) | Tier 1 |

---

## 13. Item 11 — Reliability commitments [3A design · 3C live · Tier 0-3]

**Contract of record:** `12_DISASTER_RECOVERY.md` §12 (objectives by tier), §13 (health checks, status page), §14 (incident process), §7.3 and §10 (per-tenant restore and export). This document states the **publication rule**, not the numbers.

1. **Publish only what the infrastructure can meet** (§1C.11). The factory shares one VPS (INF-01): **no availability percentage, uptime guarantee or "high availability" claim at Tier 0, 1 or 2** (12 §12.1).
2. A promise is published only if (a) the infrastructure can meet it, (b) a rehearsal measured the underlying time, and (c) the owner approved it.
3. The platform is a **batch production system** (night window; admission stops at 06:30; graceful stop at 07:00 on the shared VPS). Statements to clients are in **windows and deliverables**, not hours of uptime (12 §12.1 item 4, proposal).
4. RTO/RPO per tier: Tier 0 not committed; Tier 1 from the measured restore drill on the own server plus margin; Tier 2 per plan, never better than Tier 1's measured figure; Tier 3 contractual from measurement on that stack (12 §12.2). A formal SLA only after the pen-test and measured RTO/RPO (§15, §17).
5. **Status page, health checks, incident process** are 3C items (12 §13, §14); client incident notification content from Tier 1 (12 §14.3).
6. **Backups with tested per-tenant restore/export** are a Tier 1 gate (12 §7.3, §10).
7. Single-operator reality: no 24/7 response is promised (12 §12.4).

### Acceptance criteria

| ID | Criterion | Blocking | Scope · Tier |
|---|---|---|---|
| MT-11.1 | A restore drill measures each leg of the RTO (12 §12.3); the figure quoted to a client is the measured sum plus margin, owner-approved | Yes (gate) | Tier 1 |
| MT-11.2 | Per-tenant restore from backup (single tenant, others untouched) succeeds on a test tenant and passes the post-restore verification (12 §7.5) | Yes (gate) | 3C · Tier 1 |
| MT-11.3 | A published-claims review: no document, page or contract draft contains an availability figure not backed by MT-11.1 and owner approval | Yes (gate) | Tier 1 |
| MT-11.4 | Status page and health checks show platform state without exposing any tenant's data | Yes | 3C · Tier 1 |

---

## 14. Item 12 — Integration API [3C · Tier 3]

**Owning service:** S12 Integration API & Webhooks (Agent 01). **Contracts:** tables `04 §5.26` (`api_keys`, `webhooks`, `webhook_deliveries`), design `08 §7.3`, service sheet `14 §3.12`. The `JobIntake` model becomes a public wire contract **only then, through a CCR** (14 §3.12). Built only when an enterprise client's contract needs it (§1C.15).

| Requirement (directive §1C.12) | Design |
|---|---|
| Versioned REST API | Version in the path; breaking changes only in a new version; deprecation policy and support period: REQUIRES REVIEW (Phase 1): owner + contract terms |
| Per-tenant API keys / OAuth clients | Random value shown once; prefix + hash stored (hash algorithm: REQUIRES REVIEW, `08 §7.3`); key bound to one org; inherits no more than its creator's permissions; expiry, revocation, `last_used_at` |
| Scoped permissions | `scopes text[]`; scope list derives from the permission matrix (08 §5.2); an API caller can never approve a `FINAL_VIDEO` (agents and keys are not approvers) |
| Rate limits | Per key and per tenant; values REQUIRES REVIEW (Phase 1) |
| Webhooks | Events `job.finished`, `approval.needed`, `published`, `failed` (04 §5.26); payload = identifiers and states only; signature with timestamp and `event_id` (replay-resistant); retries with the same `idempotency_key`; bounded schedule per 07 (no infinite retries); outbound URL SSRF guard; secret encrypted with the tenant data key |
| Idempotent writes | `job.create` is idempotent (03 §9.2) |

### Acceptance criteria

| ID | Criterion | Blocking | Scope · Tier |
|---|---|---|---|
| MT-12.1 | Key shown once; only prefix and hash stored | Yes | 3C · Tier 3 |
| MT-12.2 | Tenant A's key against tenant B's resource returns not-found, never forbidden-with-detail | Yes | 3C · Tier 3 |
| MT-12.3 | Webhook signature includes timestamp and `event_id`; a replayed delivery is rejected by the documented verification | Yes | 3C · Tier 3 |
| MT-12.4 | A failed delivery is retried with the same `idempotency_key` and event up to the configured maximum, then ends `FAILED_FINAL` and surfaces to the tenant; nothing is dropped silently | Yes | 3C · Tier 3 |
| MT-12.5 | SSRF guard rejects private-network and loopback targets | Yes | 3C · Tier 3 |
| MT-12.6 | Rate limits are enforced and return a documented error; one key cannot starve another tenant (fairness §4) | Yes | 3C · Tier 3 |

---

## 15. Item 13 — Security assurance path [3A scanning · Tier 1 pack · Tier 3 pen-test]

**Contract of record:** `08 §13` (steps), `08 §10` (CI and supply chain), `08 §12` (incident runbook). Restated as a gate sequence, not redefined:

| Step | Content | When | Tier |
|---|---|---|---|
| 1 | CI gates: dependency and container scanning, secret scanning, tenancy suite, audit verification | from the first ticket | **3A · T0** |
| 2 | Security questionnaire answer pack: standard enterprise questions answered from `08`, `04`, `22` with evidence links; **unimplemented controls are stated as not implemented** | before the first external client | **Tier 1** |
| 3 | Own-server move for client data and encrypted backups with tested per-tenant restore (§16, §13) | before the first external client | Tier 1 |
| 4 | **External penetration test** by an independent party; scope, provider and cost: owner decision (rule 8); findings tracked to closure | before the first enterprise contract | **Tier 3** |
| 5 | **SOC 2 / ISO 27001 readiness** | **only when a client's contract requires it**; effort and cost: REQUIRES REVIEW (Phase 1) | on demand |

No claim of compliance with any standard appears in sales or product text until the evidence exists (`08 §13`).

### Acceptance criteria

| ID | Criterion | Blocking | Scope · Tier |
|---|---|---|---|
| MT-13.1 | CI fails on a seeded vulnerable dependency, a seeded secret and a missing RLS policy (canaries) | Yes | 3A · T0 |
| MT-13.2 | Each questionnaire answer cites a control and a test, or says "not implemented" | Yes (gate) | Tier 1 |
| MT-13.3 | Pen-test report received, every finding closed or accepted in writing by the owner, before the first enterprise contract is signed | Yes (gate) | Tier 3 |
| MT-13.4 | A repo-wide check finds no certification claim (SOC 2, ISO 27001) unless an audit report exists | Yes | all |

---

## 16. Item 14 — Infrastructure by tier [recommendation only · rule 8 · 3A on dev environment]

**Contract of record:** `10_DEPLOYMENT_AND_MIGRATION.md` §13 (plan by tier), §11 (dedicated stack), §14.3 (host-to-host migration), ADR-012 (render-worker placement), ADR-005 (storage). The owner currently does not want a bigger VPS; the design respects that and recommends, never purchases.

### 16.1 Placement by tier

| Tier | Placement | Trigger | Notes |
|---|---|---|---|
| **0** (now) | Owner's own channel on the existing shared VPS within §1 limits (own Compose project, own slice, night window, market-hours guard); 3A in the development environment (D1) | — | Plan facts INF-01 as cost context only (`10 §13.1`) |
| **Before the FIRST external client** | Move the platform, **or at least its render workers and client data**, to **its own server**, because client SLAs must not depend on capacity shared with the trading app and BagMitra | First paying managed-service client (Tier 1 gate) | Size from **measured** per-video resource use (3B golden samples, `00b`); prefer adding a cheap render-only worker over one expensive large server (ADR-012); host-to-host migration per `10 §14.3`; **recommend, never purchase** |
| **2** | Same server(s); more workers by configuration | Self-serve clients | Quotas and fair sharing exercised (05 §7) |
| **3** | Dedicated stack or dedicated workers per tenant (`workers.dedicated_org_id`) | Enterprise contract | §16.3 |

### 16.2 What the own-server move must include (Tier 1 checklist)

1. Measured per-video resource use from the pilot, and a sizing note derived from it (formula in 05 §8); no sizing from guesses.
2. Production window becomes per-tenant configuration (`channels.production_window`); the shared-VPS 00:00-07:00 window does not apply to a platform server (10 §11).
3. Off-server encrypted backups and a restore drill on the new host (12).
4. Own KEK and secret set on the new host; keys only via the environment secret mechanism (D1; `08 §3`).
5. Tenancy suite (MT-1.1) re-run on the new host; results stored as gate evidence.
6. The trading app and BagMitra are untouched (rule 2); nothing of theirs is migrated or read.

### 16.3 Dedicated option (premium, Tier 3)

Same repository and images, fresh database built by the same migrations, RLS on, one organisation row, own storage root/bucket, own backup destination, own KEK; compliance gates cannot be removed (§9). Who operates it (owner or client): commercial decision, REQUIRES REVIEW (Phase 1).

### Acceptance criteria

| ID | Criterion | Blocking | Scope · Tier |
|---|---|---|---|
| MT-14.1 | No external client job runs while client data or client SLA depends on the shared VPS; the gate checklist shows the own-server evidence | Yes (gate) | Tier 1 |
| MT-14.2 | Sizing note cites measured figures (label MEASURED) and the owner's purchase decision; nothing is bought by the platform or its agents | Yes (gate) | Tier 1 |
| MT-14.3 | A dedicated stack is built from empty with the same migrations and passes the migration and tenancy tests | Yes | Tier 3 |
| MT-14.4 | A tenant export imports into a dedicated database through the same schema (`10 §11`, `12 §10.2`) | Yes | Tier 3 |

---

## 17. Item 15 — Tier gates 0-3 [3A / 3B / 3C · Tier 0-3]

The same table is kept in `17_BUSINESS_PLAN.md` §11 (directive §1C.15: "write in the business plan"); this section adds the evidence required. **A gate opens only on the owner's decision (rule 8, §1C.15); an agent never advances a tier.** `organisations.tier` (`TIER_0`..`TIER_3`, GLOSSARY §6.47) records the tier of each org.

| Tier | Entry condition | Built only then | Evidence required before opening (stored with the owner's approval) |
|---|---|---|---|
| **Tier 0 — internal** | now | Multi-tenant schema, RBAC basics, audit log, `org_id` everywhere; owner's channel(s); budgets; licence ledger | MT-1.1..1.7, MT-4.1..4.2, MT-5.1..5.3, MT-8.1, MT-8.3, MT-13.1; D1 3A deliverables |
| **Tier 1 — first managed-service client** | A paying client is signed; **Google OAuth verification and YouTube API compliance audit passed** (YT-11, YT-12); client portal approvals; licence ledger and client-use licences; **own server** | OAuth per client channel (§5); approvals portal (§8); live auth with MFA and guests (§6); tenant brand-safety pack and needed stub packs (§9); export/erasure (§12); per-tenant restore and status basics (§13); security questionnaire pack (§15); fair-share enforcement (§4) | MT-2.1/2.2/2.4, MT-3.2..3.7, MT-4.3..4.5, MT-5.4, MT-6.2..6.5, MT-7.1/7.2/7.4..7.6, MT-8.2/8.4..8.6, MT-10.1..10.4, MT-11.1..11.4, MT-13.2, MT-14.1/14.2; DPA and privacy notice lawyer-reviewed (⚖); written confirmation for PR-05; Business-class stock licence (PR-06); Developer Policies mapping (§5.1 item 9) |
| **Tier 2 — self-serve clients** | Demand from more than managed clients; Tier 1 stable | Onboarding wizard, white-label, billing (`plans`, `subscriptions`, `usage_events`, `invoices`), quotas, time-coded comments, kids/political packs as needed | MT-2.3, MT-6.6, MT-9.1..9.6; ADR-010 accepted; GST/invoice rules reviewed (⚖); prices owner-approved (21 §12); self-serve signup threat review |
| **Tier 3 — enterprise** | An enterprise contract requires it | SSO/SCIM, API and webhooks, dedicated deployment, SIEM streaming, pen-test, formal SLA | MT-4.6, MT-4.7, MT-12.1..12.6, MT-13.3, MT-14.3, MT-14.4; measured RTO/RPO on the contracted stack; external pen-test closed |

### 17.1 Rules for every gate

1. **Build when needed, not before** (§1C): a later tier's tables are not created early (`04 §9`); a design that prevents a later tier is a defect, a built-but-unused feature is waste.
2. **No tier skipping**: a client needing a Tier 3 item before Tier 1 is complete means Tier 1 is completed first.
3. **A gate item that cannot be met is reported, not waived.** A waiver is an owner decision recorded as `POLICY_CHANGE` with its reason; platform compliance gates (§9) are never waivable.
4. **Gate review is by checklist with evidence** (test run ids, written confirmations, screenshots for UI items per owner rule A.12), kept in the repository's gate record (format: REQUIRES REVIEW, lead).

---

## 18. Scope summary

| Item | 3A | 3B | 3C | Tier |
|---|---|---|---|---|
| 1 Tenancy and RLS | **Core, tests, synthetic org** | re-run | UI, real second tenant | 0 → 1 proof |
| 2 Fair sharing | Design; spend cap (owner) | — | Enforcement and tests | 1 (caps), 2 (quotas) |
| 3 YouTube for clients | **None (D1)**; schema fixed | — | OAuth, flows, verification | **1 gate** |
| 4 Identity and access | Model + checks (owner only) | — | Live auth, guests | 1; SSO/SCIM 3 |
| 5 Audit | **Chain, verification** | — | Export, all tenants | 0; streaming 3 |
| 6 Client experience | Owner's brand kit | — | Portal, wizard, white-label | 1 approvals; 2 rest |
| 7 Compliance profiles | **Platform + finance packs** | scored | Tenant and stub packs | 0 → 2 |
| 8 Licensing | **Ledger + gate** | — | Client-use evidence | 1 gate |
| 9 Billing | — | — | Metering, invoices, gateway | 2 |
| 10 Data protection | — | — | Export/erasure per 22 | 1 gate |
| 11 Reliability | Backup basics (12) | first restore test | Status page, drills | 1 measured |
| 12 Integration API | — | — | API, webhooks | 3 |
| 13 Security assurance | **CI scanning** | — | Questionnaire | 1; pen-test 3 |
| 14 Infrastructure | Dev environment / VPS night window | measure | Own server | 1; dedicated 3 |
| 15 Tier gates | Tier 0 evidence | — | per tier | 0-3 |

---

## 19. Contract requests (filed in CONTRACT_CHANGE_REQUESTS.md §4.7, pass 5; not edited into Wave A or B-1 here)

Proposed names carry their CCR number wherever used above; all are filed in CONTRACT_CHANGE_REQUESTS.md §4.7 (integrator pass 5): CCR-20-01 → CCR-151 (needs owner, Q-O18), CCR-20-02 → CCR-153, CCR-20-03 → CCR-154, CCR-20-04 → CCR-155, CCR-20-05 → CCR-156 (deferred to 3C), CCR-20-06 and CCR-20-08 (`tier.gate_opened`) → CCR-150 (names registered by this document per 08 §9.2), CCR-20-07 → CCR-157 (deferred to 3C). The IDs `CCR-20-nn` used in this document are local labels, not register IDs.

| Request | Needed | Reason | Proposed change | Target |
|---|---|---|---|---|
| CCR-20-01 | Platform-owner support access grant | `08 §5.2` rule 2 requires an explicit, time-boxed, audited grant but no table holds it | Table `support_grants` (TENANT, Tier 1): `granted_by` (org member with `ORG_OWNER`), `grantee_user_id`, `scope_note`, `starts_at`, `expires_at`, `revoked_at`; RLS standard; audit events `support.grant.created/used/revoked` | 04 §5.1, 08 §5.2 |
| CCR-20-02 | Client-channel connect guard | MT-3.2 | Trigger/CHECK: for orgs of kind `CLIENT`/`AGENCY`, `channels.status = 'CONNECTED'` requires `gcp_projects.oauth_verification_status = 'PASSED'` and `api_audit_status = 'PASSED'` of the channel's project | 04 §5.1, §5.19 |
| CCR-20-03 | Org-level policy keys | `04 §5.1` holds only `users.mfa_enrolled`; org MFA enforcement and session policy (Tier 3) need a home | Add `org_controls` keys `mfa_required` (Tier 1) and `session_policy` (Tier 3) with validation in `amw_core.config` | 04 §5.1 `org_controls` |
| CCR-20-04 | Onboarding progress | Wizard needs per-step state (Tier 2) | Table `org_onboarding_steps` (TENANT, Tier 2): `step_key`, `state`, `completed_by`, `completed_at`; or an `org_controls` key if the owner prefers | 04 §5.1 |
| CCR-20-05 | Permission keys | Matrix lacks keys for features above | Add to `08 §5.2`: `compliance.rulepack.write` (tenant pack), `branding.write`, `billing.read`, `billing.manage`, `sso.manage`, `api_key.manage`, `webhook.manage`, `support.grant`, `channel.connect` (today under `secret.manage`) | 08 §5.2 |
| CCR-20-06 | Audit event names | `08 §9.2` requires new action names to be registered | Register: `tenant.created`, `membership.role_changed`, `channel.connected/disconnected/reauth_required`, `licence.client_use_recorded`, `voice_consent.verified/withdrawn`, `compliance.tenant_rule.changed`, `tier.gate_opened`, `subscription.suspended` | 08 §9.2 |
| CCR-20-07 | Custom-domain purpose | White-label custom domain (later) is not SSO domain verification | `org_domains.purpose` (`SSO` / `WHITE_LABEL`); keep uniqueness decision of 08 §7.2 | 04 §5.26 |
| CCR-20-08 | Tier gate record | §17.1 item 4 needs evidence kept per org | Either a repo document per gate or `audit_log` event `tier.gate_opened` with `details` evidence refs (lead decides; no new table preferred) | 08 §9.2 / 17 |

Existing pending requests referenced, not repeated: org IP allow-list storage (`08 §14` item 8); `plans.limits` keys and `CREDITS` meter (`21 §10`); `svc_s10.usage_rollup` and `svc_s12.webhook_deliver` task types (`14`).

---

## 20. Open items (all REQUIRES REVIEW (Phase 1) unless stated)

| # | Item | Needed from | Blocks 3A? |
|---|---|---|---|
| 1 | Record the sources for the shared-schema + RLS default and for the enterprise buyer tests (SSO/SCIM/MFA/RBAC/audit export) in RESEARCH_LOG when ADR-002/003 are written | Phase 1 research | No |
| 2 | ADR-002 (tenancy), ADR-003 (auth), ADR-004 (portal stack), ADR-010 (gateway) not yet written | lead | ADR-002 desirable before the first migration; others no |
| 3 | Narrowest OAuth scope per YouTube API call; Developer Policies → control → test table (YT-11, YT-12) | Agent 13 blueprint | No (D1) |
| 4 | Real classification of the OAuth scopes (sensitive/restricted) from the Cloud Console consent screen | owner (A4) | No |
| 5 | Written confirmation for client/agency voice use (PR-05); Business-class stock licence quote (PR-06); client-use terms of each selected LLM, image, video and music provider | owner + vendors | No (Tier 1 gate) |
| 6 | Support-access policy for the platform owner in client tenants | owner + ⚖ | No |
| 7 | Limit values, weights, `owner_min_weight`, `max_slot_fraction` | owner (21, 05) | No |
| 8 | Audit and data retention durations; erasure vs audit-log treatment | `22` + lawyer ⚖ | No |
| 9 | GST registration and invoice content; DPA/MSA templates; breach-notification duties | owner + lawyer/accountant ⚖ | No |
| 10 | Dunning schedule and grace periods | owner + ⚖ | No |
| 11 | API versioning and deprecation terms; rate-limit values | owner, enterprise contract | No |
| 12 | Who operates a dedicated stack; data-location statement | owner (commercial), ⚖ | No |
| 13 | Pen-test provider and cost; SOC 2 / ISO 27001 cost | owner (rule 8) | No |
| 14 | Report tooling for branded PDF reports | ADR | No |
| 15 | Gate record format (§17.1 item 4) | lead | No |

3A design impact: none of the above changes a 3A design decision.

## 21. Revisit triggers

1. A second real tenant appears before Tier 1 is formally opened: re-run MT-1.x and §4 before it runs jobs.
2. YouTube API policy or quota pages change (YT-02, YT-04, YT-11 are re-verified if older than 30 days when used for a decision).
3. A provider's terms change on third-party use (PR-05, PR-06) or a new provider is selected.
4. DPDP Rules milestone or amendment (IN-07 re-check "no later amendment").
5. The measured per-video resource use or a pilot restore drill changes the §16 sizing recommendation.
6. An enterprise client asks for a dedicated stack, SSO or an SLA: open the Tier 3 checklist, do not build ad hoc.

## 22. Cited research IDs

INF-01, INF-11, YT-01, YT-02, YT-03, YT-04, YT-06, YT-11, YT-12, YT-13, PR-05, PR-06 (incl. PR-06d/e), IN-03, IN-07.
