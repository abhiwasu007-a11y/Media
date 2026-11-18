# 08 — Security and Audit (S6)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | S6 Security & Audit → Agent 16 (§3.2). Identity, roles and tenancy mechanics stay with S9 (→ Agent 01) |
| Depends on | GLOSSARY_AND_IDS.md, 03_COMMUNICATION_STANDARD.md (§8 storage URIs), 04_DATABASE_ARCHITECTURE.md (§3 roles/RLS, §5.13 audit, §5.19 tokens/keys, §5.26 enterprise identity), 07_FAILURE_MANAGEMENT.md (§2 codes, §7 escalation), 27_ENGINEERING_STANDARDS.md (§3 CI gates, §9 walking skeleton), RESEARCH_LOG.md (INF-11, IN-07, YT-11, YT-12) |
| Directive sections covered | §1C.4 (identity and access), §1C.5 (audit), §1C.13 (security assurance path), §3.2 S6, §0 rules 5, 8, 9 |
| Decisions applied | D1 (secrets only through the environment's secret mechanism; 3A has no Google OAuth and no upload; paid calls only inside owner-set limits), D2 |
| Not decided here | Auth library (ADR-003), scanner/crypto library choices (REQUIRES REVIEW, §13), retention durations (22) |

**Scope key.** Build scope: **3A** (production line) / **3B** (golden samples) / **3C** (everything else). Enterprise tier: **T0–T3** (GLOSSARY §6.47). Every control below states both. Where a value is unknown the text says "REQUIRES REVIEW (Phase 1): <need>". Nothing here is legal advice; items marked ⚖ go to the owner's lawyer (see IN-07).

---

## 1. Principles

1. **Isolation is absolute** (rule 9): a defect in one layer must not leak a tenant. Five independent layers (§8) — app filter, RLS, storage URIs, cache keys, logs — each tested.
2. **Fail closed.** Unset tenant context matches no rows (04 §3.2); an unknown permission is denied; an unreadable secret stops the process.
3. **Least privilege everywhere**: DB roles (§4), human roles (§5), agent/service actors (§5.3), CI tokens (§10).
4. **No secrets in git, logs, shared environment variables or prompts** (D1). Detected by scanning (§10), prevented by design (§3).
5. **Humans and agents are both audited** (§1C.5). An agent never acts without a named authority.
6. **No invented security claims.** No certification (SOC 2, ISO 27001) or "secure" statement is made until a contract requires it and evidence exists (§1C.13, §12).
7. **Public repository**: this document contains no secrets, hostnames, addresses, key names with values, private method or owner data (§11).

---

## 2. Scope by build phase

| Control | 3A | 3B | 3C | Tier |
|---|---|---|---|---|
| Secrets from the environment secret mechanism; startup refusal when missing (§3) | **yes** | yes | yes | T0 |
| Spend-limit precondition before any paid call (§3.4) | **yes** | yes | yes | T0 |
| DB roles `amw_owner/migrator/app/readonly` + FORCE RLS + tenancy CI suite (§4) | **yes** (one org: the platform owner org; model is multi-tenant) | yes | yes | T0 |
| Audit log with hash chain, daily verification (§9) | **yes** (includes task transitions, approvals, cost events, control changes) | yes | yes | T0 |
| Storage URI / cache key / log tenant rules (§8) | **yes** | yes | yes | T0 |
| CI: secret scan, dependency scan, container scan, lock-file integrity (§10) | **yes** | yes | yes | T0 |
| Permission matrix enforced in the API (§5) — 3A: owner is the only human user | minimal | minimal | full | T0 |
| Incident runbook (§12), drilled once on the walking skeleton | draft | yes | full | T0 |
| OAuth token encryption with per-tenant data keys (§6); roles `amw_publisher`, `amw_auth` | **no** (no OAuth in 3A, D1) | no | **yes** | T0 design / T1 live |
| Permission review job, MFA enforcement, session policy (§5.5–5.6) | no | no | yes | T0/T1 |
| Client portal guest controls (§5.4) | no | no | yes | T1 |
| API keys, webhook signing, rate limits (§7.3) | no | no | yes | T3 |
| SSO (SAML/OIDC), SCIM, domain verification, IP allow-list (§7) | no | no | no | **T3** |
| External penetration test, questionnaire pack, SOC 2 / ISO 27001 readiness (§13) | no | no | no | **T3** (pack T1) |

---

## 3. Secrets management

### 3.1 Rules (3A, T0)
1. **Source of truth**: the environment's secret mechanism (D1). A secret reaches a process only as an environment value injected at start from that mechanism, or as a file mounted from it. The concrete mechanism per deployment target (development environment, VPS) is **REQUIRES REVIEW (Phase 1): ADR for secret delivery; the choice must satisfy rules 2–7 below and must not be recorded in this public repository with host details.**
2. Never in git (any branch, any history), never in `docs/`, fixtures, prompts, eval datasets, screenshots, issue or PR text.
3. Never in logs, error objects, `message_log`, `audit_log.details`, task output or traces. `amw_core.observability` applies a redaction filter on key names and on known secret patterns, and the log-leak test (§8.5) injects a canary secret and asserts it never appears.
4. Never in **shared** environment variables: a secret is scoped to the single service that needs it (e.g. only the adapter process holds a provider key; the renderer holds none). A secret is not placed in a variable inherited by all containers or in a global profile.
5. Never in the database in clear text. Tenant-held credentials (OAuth tokens, webhook secrets) are encrypted (§6); API keys are stored as hashes (§7.3).
6. No hard-coded keys, models or providers (rule 5): adapters read key *references* from configuration and values from the secret mechanism.
7. Startup check: a service lists the secret names it requires; a missing or unreadable one fails startup with `PERMANENT.CONFIG_INVALID` (07 §2). The service never prints the value, its length or a prefix.

### 3.2 Inventory (names only; values never documented)
| Secret class | Used by | Phase | Rotation owner |
|---|---|---|---|
| Database login credentials for `amw_app`, `amw_readonly` (and `amw_publisher`, `amw_auth` when they exist) | services | 3A (app, readonly) / 3C | Platform Owner |
| Migration credentials `amw_migrator` | deploy only, never a running service (04 §3.1) | 3A | Platform Owner |
| LLM / TTS / stock / image provider keys | adapters | 3A | Platform Owner |
| Key-encryption key (KEK) reference and material for tenant data keys | `amw_core.crypto` | 3C | Platform Owner |
| Google OAuth client credentials | Agent 13 | **3C only** (D1: none in 3A) | Platform Owner |
| Webhook signing secrets, SCIM tokens | S12 / S9 | T3 | Org Owner (tenant-held) |

### 3.3 Rotation, leak response
- Every secret has an owner and a rotation procedure written before first use. Rotation interval per class: **REQUIRES REVIEW (Phase 1): interval per provider policy; owner decision.**
- A suspected leak is an incident (§12): revoke at the provider first, then rotate, then purge from history if it reached git. Purging history does not make a leaked secret safe; revocation does.

### 3.4 Spend-limit precondition (D1, rule 8)
Paid provider calls are enabled only after the owner has set spending limits at each provider. The cost ledger (S4, 15) enforces the **per-video budget and the total pilot budget** and stops on breach (`resource_budget.max_cost_micros`, 07 §9: SUSPEND `AWAITING_BUDGET`). This is also a security control: a leaked provider key is bounded by the provider-side limit, and a runaway agent by the ledger. Adapter keys are therefore never created without a provider-side limit. The provider-side limits themselves are owner inputs (A7) — **REQUIRES REVIEW (Phase 1): owner-set limits per provider.**

---

## 4. Database least privilege (04 §3)

Roles are defined in 04 §3.1 and not redefined here. Security requirements on them:

| Role | Security requirement | Phase |
|---|---|---|
| `amw_owner` | `NOLOGIN`; owns objects; `FORCE ROW LEVEL SECURITY` applies to it (INF-11) | 3A |
| `amw_migrator` | Login only from the deploy step; credential absent from running services; every migration run writes an audit entry (`sys_migrator`) | 3A |
| `amw_app` | `NOBYPASSRLS`, not superuser, no DDL, no `TRUNCATE`; `INSERT`-only on append-only tables; grants per table (04 §3.3) | 3A |
| `amw_readonly` | `SELECT` only, tenant context mandatory | 3A |
| `amw_sysfn` | `NOLOGIN`; owns only the §3.6 functions; fixed `search_path`; functions return identifiers and envelopes, never content columns | 3A (queue claim) |
| `amw_publisher` | The **only** role with `SELECT` on `oauth_tokens.*_ct` / `*_nonce`; used by Agent 13 only | 3C |
| `amw_auth` | Identity tables only (ADR-003) | 3C |

Controls:
1. **Grant drift test (CI, blocking)**: a catalogue query lists every privilege of every `amw_*` role and compares it with a checked-in expected list; any difference fails the build.
2. **No superuser or `amw_owner` connection** from any application path; a startup check refuses to run if `current_user` is a superuser or has `BYPASSRLS` (except via `amw_sysfn` functions).
3. **Tenant-context guard**: `amw_core.tenancy` refuses queries outside a transaction with `app.org_id` set (04 §3.2). The 04 §3.7 suite (8 checks) is a blocking CI gate.
4. **Connection transport**: database connections inside the host are not exposed to the public network; encryption in transit between components that cross a host boundary. Network layout is **REQUIRES REVIEW (Phase 1): deployment ADR / 00_REPO_AND_SERVER_AUDIT Part C** (no host details here).
5. **Backups** contain the same data as the database and are protected like it (encrypted, access-limited, per-tenant restore tested; 22). Audit chain heads are stored with the off-server copy (§9.3).

---

## 5. Identity, roles and permissions (§1C.4)

### 5.1 Roles
The role enum is `role` (GLOSSARY §6.44): `PLATFORM_OWNER`, `ORG_OWNER`, `ORG_ADMIN`, `PRODUCER`, `REVIEWER_APPROVER`, `FINANCE`, `VIEWER`, `CLIENT_GUEST`. `PLATFORM_OWNER` exists only in the org flagged `is_platform_owner` (04 §5.1 trigger). Authentication uses a proven library chosen in ADR-003; **no hand-rolled crypto** (§1C.4). Credential storage location: REQUIRES REVIEW (ADR-003), per 04 §5.1.

### 5.2 Permission matrix
Permission keys below are owned by this document. `dlq.replay`, `dlq.discard` and `job.cancel` already appear in 03 §11.3 and keep their names. Other keys are written against this document as the single definition. Legend: **Y** allowed; **–** denied; **own** only for the actor's own objects. Anything not listed is denied.

| Permission key | PLATFORM_OWNER | ORG_OWNER | ORG_ADMIN | PRODUCER | REVIEWER_APPROVER | FINANCE | VIEWER | CLIENT_GUEST |
|---|---|---|---|---|---|---|---|---|
| `job.create` | Y | Y | Y | Y | – | – | – | – |
| `job.cancel` (03 T19) | Y | Y | Y | own | – | – | – | – |
| `approval.decide` (needs the `required_role` of the step, 04 §5.16) | Y | Y | Y | – | Y | – | – | Y (guest steps only) |
| `comment.write` | Y | Y | Y | Y | Y | – | – | Y |
| `dlq.replay` / `dlq.discard` (03 T17/T18) | Y | Y | Y | – | – | – | – | – |
| `control.write` (emergency stop, publishing on/off, agent enable) | Y (platform controls) | Y | Y | – | – | – | – | – |
| `budget.write` (S4 limits) | Y | Y | – | – | – | Y | – | – |
| `cost.read` | Y | Y | Y | – | – | Y | Y | – |
| `audit.read` / `audit.export` | Y | Y | Y (read) | – | – | – | – | – |
| `member.manage` (invite, role change, suspend) | Y | Y | Y (not Owner roles) | – | – | – | – | – |
| `secret.manage` (connect/revoke channel credential) | Y | Y | Y | – | – | – | – | – |
| `data.export` / `data.erase` request | Y | Y | – | – | – | – | – | – |
| `content.read` | Y (own org) | Y | Y | Y | Y | – | Y | assigned items |
| `platform.ops_summary` (cross-tenant aggregates, §3.6 of 04) | Y | – | – | – | – | – | – | – |

Rules:
1. **Server-side only.** Permission checks run in the API/service layer on every request and again at the state-machine guard (03 §11.3). A hidden button is not a control.
2. **Platform Owner is not a tenant super-user.** Inside a client tenant the platform owner sees only platform-level causes and aggregates (rule 10; 07 §7). Any platform-owner access to a client tenant's content is an explicit, time-boxed, audited support grant — **REQUIRES REVIEW (Phase 1): support-access policy; owner decision + ⚖**.
3. **Separation of duty**: the user who requests a spend increase or a policy exception cannot be its only approver; an agent can never be an `approval.decide` actor (04 §5.16 trigger already requires a human `usr_` actor).
4. In 3A the only human is the owner; the matrix is still enforced so 3C adds users without rewriting checks.

### 5.3 Agent and service identities
- Actors follow GLOSSARY §2.3 (`agent_NN`, `svc_sNN`, `sys_*`). Every audited action carries `actor_ref`, `authority` (role or policy ID) and, when acting for a person, `on_behalf_of` (04 §5.13).
- Agents hold **capabilities**, not user roles: an agent can only run the task types its registry entry lists (24 §3.2) and only touch tables its DB grants allow. An agent cannot approve, change budgets, controls, memberships or credentials.
- LLM output is never an authority: a tool call or instruction produced by a model is validated against the task's schema and the permission matrix before any effect. Prompt-injection from retrieved content (knowledge chunks, web pages, subtitles, comments) cannot widen permissions because permission checks are in code, not in prompts. Injection test cases belong in each agent's eval pack (27 §6).

### 5.4 Client guests (Tier 1)
`CLIENT_GUEST` is approve/comment only (§1C.4), limited by `allowed_channel_ids` / assigned items (04 §5.16). Links given to guests are single-purpose tokens stored as hashes (`token_hash`, 04 §5.1), expire, and are revoked on membership removal.

### 5.5 Authentication hardening (T0 design, 3C live)
Email + password with MFA, Google sign-in, organisation invites (§1C.4). Per-org MFA enforcement flag (`mfa_enrolled`, 04 §5.1). Password and MFA mechanics, hashing parameters, lockout and rate-limit values: **REQUIRES REVIEW (Phase 1): ADR-003 and the chosen library's documented defaults; record in RESEARCH_LOG.** Session cookies are `HttpOnly`, `Secure`, `SameSite`; sessions are server-revocable (`user_sessions`).

### 5.6 Permission audit (S6)
1. **Continuous**: every grant, role change, membership change, control change and credential action writes an audit entry (§9.2).
2. **Periodic review** (3C, T0): a scheduled S6 job produces, per org, the list of members with role, last login, MFA state and unused-for-N-days flag, and writes it as an `audit_log` entry with action `security.permission_review` (no new table). The Org Owner (and the Platform Owner for the platform org) acknowledges it as an `approval.decide`-style human action. N and cadence: **REQUIRES REVIEW (Phase 1): owner decision.**
3. **Database-level**: the grant drift test (§4.1) is the permission audit for DB roles.
4. **Anomaly flags** (S6 rules, deterministic): permission denials above a threshold for one actor, role escalation outside business flow, export of audit/data, credential connect/revoke. Thresholds: REQUIRES REVIEW (Phase 1): set from pilot measurements. Flags route as L3 security (07 §7).

---

## 6. OAuth token and tenant-secret encryption (3C; Tier 0 design, live at Tier 1)

Not built in 3A (no Google OAuth, D1). Design is fixed now so the schema (04 §5.19) does not change later.

1. **Envelope encryption.** Each org has a data encryption key (DEK) stored wrapped in `tenant_data_keys.wrapped_key`; the wrapping key (KEK) is referenced by `kek_ref` and held outside the database in the environment/secret mechanism (§3). The database alone never allows decryption.
2. **Authenticated encryption (AEAD)** with a fresh unique nonce per value, stored beside the ciphertext (`*_ct`, `*_nonce`, 04 §5.19). The org id and column name are bound as associated data so a ciphertext copied to another tenant or column fails to decrypt. **Algorithm and library: REQUIRES REVIEW (Phase 1): select a maintained, audited library; verify its documentation and record version, licence and date in RESEARCH_LOG; fill `tenant_data_keys.algorithm`.**
3. **Read path.** Only `amw_publisher` can `SELECT` ciphertext columns (04 §5.19). Decryption happens in memory in the publish worker; plaintext is never logged, cached, checkpointed or placed in an envelope/task output.
4. **Rotation.** DEK rotation creates a new `ACTIVE` key, re-encrypts values in a tenant transaction, marks the old key `RETIRED`; KEK rotation re-wraps DEKs. Both write audit entries. Interval: REQUIRES REVIEW (Phase 1).
5. **Revocation and re-consent.** Disconnecting a channel revokes the token at Google, sets `oauth_token_status = REVOKED`, and wipes ciphertext. `REFRESH_FAILED` raises `PERMANENT.AUTH_INVALID` and an L3 security-routed notification (07 §7); the channel moves to `NEEDS_REAUTH` (`channel_status`). Minimum scopes only (§1C.3; YT-12: sensitive/restricted classification NOT CONFIRMED, so verification effort is assumed until confirmed).
6. **Crypto-shredding.** Erasure destroys the org's DEKs (`data_key_status = DESTROYED`), making tokens and webhook secrets unreadable (04 §5.19, 22).
7. **Client-owned GCP project** (enterprise option, §1C.3): the client's OAuth credentials are tenant secrets handled by this section; the breaker `credential_scope` keeps their failures isolated (07 §4).
8. **Google reviews** (OAuth verification, YouTube API audit) are Tier 1 gates (YT-11, YT-12; 04 `google_review_status`); they are compliance gates, not part of this document's controls.

---

## 7. Enterprise items (Tier 1–3; all outside 3A–3C unless a paying client needs them, §1C.15)

### 7.1 Tier map
| Item | Tier | Source | Notes |
|---|---|---|---|
| Email+password with MFA, Google sign-in, invites, 8 roles | T0 design / T1 live | §1C.4 | §5 |
| Security questionnaire answer pack | **T1** | §1C.13 | Built from this document and 22; every answer cites a control and its test or is marked "not implemented" |
| Single-purpose guest tokens for client reviewers | T1 | §1C.6 | §5.4 |
| API keys, scoped permissions, rate limits, webhook signatures and retries | T3 | §1C.12; 04 §5.26 | §7.3 |
| **SSO (SAML 2.0 / OIDC) per organisation** | **T3** | §1C.4 | §7.2 |
| **SCIM provisioning / deprovisioning** | **T3** | §1C.4 | §7.2 |
| Domain verification, session policies | T3 | §1C.4 | §7.2 |
| **IP allow-list** per organisation | **T3** | §1C.4 | §7.4 |
| Dedicated single-tenant deployment | T3 | §1C.1, §1C.15 | Same code and migrations, own DB/server; the controls of §4 and §8 apply unchanged |
| **External penetration test** before the first enterprise contract | **T3** | §1C.13 | §13 |
| SOC 2 / ISO 27001 readiness | only if a client contract requires it | §1C.13 | §13 |

### 7.2 SSO, SCIM, domains (T3)
- Tables are in 04 §5.26 (`org_sso_connections`, `org_domains`). `auth_provider` includes `SAML`, `OIDC` (GLOSSARY §6.44).
- Enforced SSO (`enforced = true`): password login for that org's members is refused; break-glass for the Org Owner is **REQUIRES REVIEW (Phase 1): policy + ⚖**.
- SCIM token stored as `scim_token_hash`; deprovisioning sets `membership_status = SUSPENDED`/`REMOVED`, revokes sessions and API keys of that member, and writes an audit entry.
- **Domain uniqueness decision (closes the open item in 04 §5.26).** A verified domain is unique among verified rows platform-wide, because SSO routing needs one owner per domain. To avoid revealing which domains are customers, the API answers a conflicting claim with a generic "cannot be verified" message and does not name the claiming org; the platform owner can see the conflict in the audit chain. A verification token is a hash-stored, single-use value (`verification_token_hash`). Takeover disputes go to the platform owner (manual, audited). This keeps the 04 §5.26 column and uniqueness as written; no schema change.
- Sign-in library support for SAML/OIDC/SCIM is an ADR-003 selection criterion; **REQUIRES REVIEW (Phase 1): ADR-003 must record SSO/SCIM support and RAM footprint.**

### 7.3 API keys and webhooks (T3)
- Key format: random value shown once; stored as `key_prefix` (display) + `key_hash`. **Hash algorithm: REQUIRES REVIEW (Phase 1): select a fast keyed or unkeyed cryptographic hash suitable for high-entropy random tokens (not a password hash); verify and record in RESEARCH_LOG; fill 04's "algorithm per 08".** Scopes, expiry, `last_used_at`, revocation; keys inherit no more than the creating user's permissions.
- Webhook payloads are signed with the per-webhook secret (encrypted with the tenant DEK, §6); signature includes a timestamp and `event_id` to resist replay; receivers get the verification procedure in the integration docs; delivery retries use `idempotency_key` (04 §5.26). Outbound webhook URLs are validated against private-network and loopback targets (SSRF guard). Rate-limit values: REQUIRES REVIEW (Phase 1).

### 7.4 IP allow-list (T3)
Per-org list of permitted networks for interactive sign-in and API keys. Fail closed when the list is non-empty and the source address is absent; changes need `ORG_OWNER`, are audited, and cannot lock out the break-glass path (§7.2). Behaviour behind proxies (trusted-proxy header handling): REQUIRES REVIEW (Phase 1): deployment ADR. Storage of the list: 04 defines no column or table for it — proposed `org_ip_allowlist` (pending CCR).

---

## 8. Tenant isolation, end to end (rule 9, §1C.1)

Five independent layers. A request or job is acceptable only if all five agree.

| Layer | Control | Failure code / event | Phase |
|---|---|---|---|
| 1. **App filter** | Every query goes through `amw_core.tenancy`, which sets `SET LOCAL app.org_id` / `app.actor` / `app.user_id` and adds explicit `org_id` predicates; no raw cursor outside it (lint rule). The API derives `org_id` from the authenticated membership, never from a request field. Envelope, input and context org IDs must agree. | `PERMANENT.TENANT_MISMATCH` (L3 security) | 3A |
| 2. **RLS** | `ENABLE` + `FORCE ROW LEVEL SECURITY` on every TENANT/SHARED-CATALOGUE table; app roles `NOBYPASSRLS`; tenant-composite foreign keys; unset context = 0 rows (04 §3.2–3.5, INF-11). | CI gate 04 §3.7 | 3A |
| 3. **Storage URIs** | `amw-blob://<org wire id>/…` and `amw-entity://<org wire id>/…`; the backend path begins `<root>/<org uuid>/`; the reader compares URI org to `app.org_id` (or `platform`, read-only) before resolving; every input carries SHA-256 verified on read; blobs are write-once (03 §8). No path is built from user input without normalisation; `..` and absolute segments are rejected. | `PERMANENT.CROSS_TENANT_REF` (security event, L3) | 3A |
| 4. **Cache keys** | `amw:<org wire id>:<area>:<key>` (GLOSSARY §2.4); the org part is mandatory. A cache wrapper in `amw_core` refuses a key without it and refuses a hit whose stored org differs. Vector indices and memory are per tenant (§1C.1). Prompt-caching of shared system prompts holds **no tenant data** in the shared prefix; tenant content comes after it. | cache test | 3A |
| 5. **Logs and metrics** | Every log line and metric carries `org_id` (platform-wide: `"platform"`); no secrets, tokens, knowledge-chunk text or personal data in logs (27 §3). Tenant-visible log or audit views filter on `org_id` at the query layer and by RLS. | log-leak test | 3A |

### 8.1 Further controls
1. **System functions** (04 §3.6) return identifiers and envelopes only; test 04 §3.7(7) proves no content column leaks. `amw_platform_ops_summary()` calls are audited.
2. **Queue fairness is also isolation**: per-tenant concurrency, spend and render-minute caps (§1C.2) stop one tenant starving another (T1+ enforced; the platform owner's own channels are the only tenant in 3A).
3. **Shared catalogues** (`org_id IS NULL`) are readable by all, writable by none except migrations or audited `amw_sysfn` calls by `PLATFORM_OWNER` (04 §3.5).
4. **Licensed provider accounts**: the licence ledger records which tenant each asset served (04 §5.15); client work needs licences that permit it (§1C.8). This is a compliance control, enforced by Agent 16.
5. **Exports and erasure**: a tenant export or erasure addresses one storage prefix plus rows (03 §8.1, 04 §5.24); the export bundle is written under `exports/<dtr>/` and its link is single-tenant and expiring (expiry: REQUIRES REVIEW (22)).
6. **Test fixtures** never use real tenant data.

### 8.2 Required security tests (blocking CI, marker `security` / `tenancy`)
1. 04 §3.7 items 1–8.
2. API: a user of org A requesting org B's job/asset/audit by ID gets not-found, not forbidden (no existence oracle), and the attempt is logged as `PERMISSION_DENIED`/`CROSS_TENANT_REF`.
3. Storage: a task in org A given a URI of org B is rejected before any read.
4. Cache: a key without org is rejected; a poisoned entry from org B is not returned to A.
5. Logs: canary secret and canary org content never reach another org's log view or any log.
6. Agent prompts: an eval case where retrieved text asks the agent to reveal another tenant's data or a secret; expected outcome is refusal and no tool call (27 §6).
7. Role/permission matrix: one test per cell of §5.2 (denied cells included).
8. Grant drift (§4.1).

---

## 9. Audit log and tamper evidence (§1C.5, 04 §5.13)

### 9.1 What the table guarantees (defined in 04; not redefined)
Append-only, per-tenant, partitioned; `seq` gap-free per org; `prev_hash`/`row_hash` chain (SHA-256 over previous hash and the canonical row JSON); writer locks `audit_chain_heads`; `amw_app` has `INSERT` only; a trigger rejects `UPDATE`/`DELETE` for every role; human **and** agent actions with `actor_kind`, `actor_ref`, `on_behalf_of`, `authority`.

### 9.2 What must be audited (S6 owns the list; each emitting service owns its writes)
| Group | Examples of `action` (dotted names) | Phase |
|---|---|---|
| Task / job lifecycle | `task.completed`, `task.cancelled` (03 §11 transitions) | 3A |
| Approvals and publication authorisation | `approval.decided` | 3A (files-only) / 3C |
| Controls | `control.<key>.changed`, `control.emergency_stop.changed` | 3A |
| Budget and cost breaches | budget suspension events (S4) | 3A |
| Secrets and credentials | connect, revoke, rotate (no values) | 3C |
| Identity | login failure thresholds, role change, MFA change, member invite/suspend | 3C |
| Data | export, erasure, `audit.retention_applied` | 3C |
| Platform | platform controls, `amw_platform_ops_summary` calls, support grants, migrations | 3A |
| Security | `security.permission_review`, anomaly flags, `audit.chain_mismatch` | 3C |

`details` holds no secrets and minimal personal data (22). New action names are registered in the emitting document's table, not invented ad hoc.

### 9.3 Tamper evidence and verification
1. **Daily verification job** recomputes each org's chain and compares with `audit_chain_heads`; a mismatch is an **L3 security incident** (07 §7; runbook §12). 3A: runs on the platform owner org.
2. **Off-server head copy**: the current head hash per org is copied with the off-server backup so truncation or wholesale replacement is detectable (04 §5.13). Where the copy is stored: REQUIRES REVIEW (Phase 1): backup design (22 / DR).
3. **Limits stated honestly**: a hash chain proves internal consistency, not who tampered; an attacker with full database ownership who also recomputes every later hash can forge a chain unless a head copy exists elsewhere. Hence the external head copy and, optionally, a customer-held head receipt for T3 clients (REQUIRES REVIEW (Phase 1): decision at T3).
4. **Export**: CSV/JSON per tenant (`audit.export`), includes `seq`, `prev_hash`, `row_hash` so the recipient can verify independently. Streaming to a client SIEM is later (§1C.5): T3.
5. **Retention and detach**: only `amw_migrator`, after exporting and writing `audit.retention_applied` (04 §5.13). Durations: REQUIRES REVIEW (Phase 1): 22 + 21.
6. **Performance**: chain head serialisation limits per-tenant audit throughput; measured in the pilot (04 §5.13). High-volume events (per-token, per-frame) are never audited individually; they go to metrics.

---

## 10. CI and supply-chain security (§1C.13; 27 §3, §5)

All gates below are **blocking** and active from the first ticket (3A) unless stated.

| Gate | What it checks | Fails when | Source |
|---|---|---|---|
| Pre-commit secret scan | staged diff for keys, tokens, private-key blocks, `.env`-like files | any finding | 27 §3 |
| CI secret scan | full tree and the PR's commit range, plus the repository history on a schedule | any finding that is not an approved, documented false positive | §1C.13 |
| Dependency scan | lock-file against a vulnerability database, including transitive dependencies | vulnerability at or above the severity threshold (**REQUIRES REVIEW (Phase 1): threshold and allowed-exception expiry; owner decision**) | 27 §5 |
| Container image scan | each image built by CI (OS packages and language packages) | same threshold | §1C.13 |
| Lock-file integrity | one workspace lock file, exact versions, hashes where supported; install in CI is from the lock file only | drift between manifest and lock | 27 §3 |
| Licence check | dependency licences against an allow-list (compatibility with the planned use incl. client work) | unknown or disallowed licence: **REQUIRES REVIEW (Phase 1): licence allow-list** | 27 §3 |
| Grant drift and tenancy suite | §4.1, §8.2 | any difference | 04 §3.7 |
| Migration checks | forward-only, transactional, every new table has its policy (04 §3.7(6)) | violation | 27 §5 |
| Static analysis | linter rules banning raw DB cursors outside `amw_core.tenancy`, `subprocess` with shell and unsanitised input, `eval`/unsafe deserialisation, logging of objects named `*token*`/`*secret*` | violation | 27 §3 |
| Base-image / dependency freshness | scheduled (not per-PR) scan so newly published advisories surface without a code change | new finding opens a ticket per the threshold | §1C.13 |

Rules:
1. **Tool choices** (secret, dependency, container scanners; SBOM generator if used) are recorded with version, licence and date in RESEARCH_LOG.md **before ticket 1** (27 §3, "Tool choices pending"): **REQUIRES REVIEW (Phase 1): choose; each must work without paid accounts or with an owner-approved cost (rule 8).** No tool is named here because none is verified yet.
2. **CI credentials** are the minimum: the pipeline cannot read production secrets; live-provider tests are opt-in (`live` marker, 27 §8.4) and use limit-capped keys (§3.4). Pull requests from forks never receive secrets.
3. **Third-party code and actions** are pinned to an immutable version or digest; updates by ticket with changelog review (27 §3).
4. **Release artefacts**: images are built in CI only; a build records its source commit and lock-file hash; deployment pulls the recorded artefact. Image signing: REQUIRES REVIEW (Phase 1): decide when more than one deployment target exists.
5. **Container hardening (design)**: non-root user, read-only root filesystem where the service allows, no host-network, no privileged mode, resource limits (aligned with the systemd slice, INF-03), no secrets baked into images, no build-time secrets left in layers. Verified by the container scan plus a policy check where the chosen scanner supports it.
6. **Input safety for media**: uploaded or fetched files are untrusted: size and duration limits, type sniffing, probe before render, run FFmpeg/image tools with bounded resources and without network, never `shell=True` with a filename. Limits: REQUIRES REVIEW (Phase 1): from measured render profile.
7. **External fetches** (web research, provider downloads) go through an adapter with an allow-list per task type, redirect and size limits, and a block on private/loopback addresses (SSRF).

---

## 11. Public-repository rule

1. This repository is public. Never commit: secrets, key values, hostnames, IP addresses, server paths beyond the documented project layout, credentials in screenshots, private method / book / course content, owner personal data, client data, real tenant IDs.
2. Documents, fixtures, evals, prompts and logs committed here use synthetic data only (no mock data presented as working, rule 7).
3. Security findings about this project are written without exploit detail until fixed; the owner decides disclosure. A **vulnerability reporting contact** and policy for a public repo: **REQUIRES REVIEW (Phase 1): owner decision on contact and policy text.**
4. A pre-merge reviewer checks each diff against this rule; the secret-scan gate (§10) is the machine backstop, not the only check.
5. If a secret or private item is committed: treat as an incident (§12): revoke/rotate, remove from the working tree and history, record in the incident log without the value.

---

## 12. Incident runbook

### 12.1 Severity and routing
Aligned to escalation levels (07 §7). Security signals that always raise **L3 → Platform Owner and the tenant's Org Owner**: `CROSS_TENANT_REF`, `TENANT_MISMATCH`, `PERMISSION_DENIED` above threshold, `AUTH_INVALID`, audit-chain mismatch, secret scan hit in a protected branch, suspected credential leak, unexpected spend spike (S4). Response targets (time to acknowledge/contain): **REQUIRES REVIEW (Phase 1): owner-set; a single-operator reality must be reflected (§1C.11: publish only commitments the infrastructure and staffing can meet).**

### 12.2 Phases
| Phase | Actions | Evidence |
|---|---|---|
| 1. Detect | alert from S6 rules, CI, audit verification, owner report | alert ID, first-seen time |
| 2. Triage | classify (secret leak / tenant breach / audit tamper / account takeover / malicious content / provider compromise / availability); decide whether tenant data is involved | note in incident log |
| 3. Contain | in this order as applicable: **emergency stop** (`platform_emergency_stop`, 04 §5.1) and `admission_paused`; revoke the leaked secret at the provider; suspend the affected membership/session/API key; set affected org `SUSPENDED` if needed (`org_status`); disable the affected channel connection; preserve logs and database state (no destructive "fix") | audit entries (control changes) |
| 4. Eradicate | rotate credentials (§3.3, §6.4); patch or revert the cause through a normal PR with the CI gates; purge secrets from history if committed | PR, rotation record |
| 5. Recover | re-enable in stages; replay only through controlled DLQ replay (`dlq.replay`, 07 §5); verify audit chain and tenancy suite pass; verify no unapproved video was published (publish guard, 04 §5.21) | verification output |
| 6. Notify | tenant Org Owner for any tenant impact; regulator/data principal notifications where the law requires: **⚖ REQUIRES REVIEW (Phase 1): breach-intimation duties under DPDP (IN-07: security and breach rules apply from about May 2027), who must be told, within what time; decision by owner's lawyer; platform acts as processor for client data** | notification record |
| 7. Review | blameless post-incident review within a period set by the owner; new test or control added to CI; update this document | review note; change request if a contract changes |

### 12.3 Playbooks (short)
- **Leaked provider key**: revoke at the provider, replace, check provider usage for the window, check cost ledger for anomalies, review where it leaked (log, commit, prompt).
- **Cross-tenant event**: stop admission, identify the code path and the rows/objects touched, determine which tenants saw what from the audit and storage logs, notify per 6, fix and add the missing test to §8.2 before re-enabling.
- **Audit chain mismatch**: freeze writes for that org's affected partition if feasible, compare with the off-server head copy, determine tamper vs defect, restore from the last verified backup if tampered; do not repair the chain by editing rows.
- **Account takeover**: revoke sessions and tokens, force MFA re-enrolment, review audit trail of that user's actions, rollback or cancel affected jobs through `job.cancel`.
- **Poisoned content / prompt injection suspected**: quarantine the source document or knowledge chunk, cancel affected tasks, review outputs before any approval, add an eval hard-negative (27 §6).
- **Unapproved publication suspected**: should be impossible (04 publish guard); treat as critical, emergency stop, verify the guard and the approvals row.

### 12.4 Runbook hygiene
The runbook is drilled once on the walking skeleton (27 §9) before the first paid call, using synthetic data, and again before the first client (T1). Contact details of the owner are not stored in this repository (§11).

---

## 13. Security assurance path (§1C.13)

| Step | Content | When |
|---|---|---|
| 1 | CI scanning gates (§10), tenancy suite (§8.2), audit verification (§9.3) | from the first ticket (3A) |
| 2 | Security questionnaire answer pack: standard enterprise questions answered from this document, 04, 22, with evidence links; unimplemented controls stated as such | before the first external client (T1) |
| 3 | Own-server move for client data (§1C.14) and encrypted backups with tested per-tenant restore (22) | before the first external client (T1) |
| 4 | **External penetration test** by an independent party; scope, provider and cost: **REQUIRES REVIEW (Phase 1): owner decision, rule 8 (no spend without the owner)**. Findings tracked to closure | before the first enterprise contract (**T3**) |
| 5 | **SOC 2 / ISO 27001 readiness** | **only when a client's contract requires it**; effort and cost: REQUIRES REVIEW (Phase 1) |

No claim of compliance with any standard appears in sales or product text until the evidence exists.

---

## 14. Open items

| # | Item | Needed from | Blocks 3A? |
|---|---|---|---|
| 1 | Secret delivery mechanism per deployment target (§3.1) | ADR + owner | Needed before first paid call; ADR; does not change the 3A design |
| 2 | Owner-set spend limits at each provider (§3.4) | owner (A7) | Blocks paid calls, not design |
| 3 | Scanner and crypto library choices, recorded in RESEARCH_LOG (§6.2, §7.3, §10) | Phase 1 research | Scanners: before ticket 1. Crypto: 3C |
| 4 | Vulnerability severity threshold and exception expiry (§10) | owner | Needed for CI gate configuration |
| 5 | Support-access policy for the platform owner in client tenants (§5.2) | owner + ⚖ | No (T1) |
| 6 | Permission review cadence, rotation intervals, anomaly thresholds (§3.3, §5.6) | owner / pilot | No |
| 7 | Breach-notification duties and timelines (§12.2) | ⚖ | No |
| 8 | Storage for the IP allow-list (§7.4) | contract request below | No (T3) |
| 9 | Vulnerability reporting contact/policy for the public repo (§11) | owner | No |

3A design impact: none of the above changes a 3A design decision.
