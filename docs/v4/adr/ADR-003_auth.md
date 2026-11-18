# ADR-003 — Authentication and identity: in-process proven libraries for Tier 0–2; self-hosted identity service only for Tier 3

| Field | Value |
|---|---|
| Status | **Draft - documentation** (ADR status when complete: Proposed). Software: **Planned** |
| Decider | Owner (Abhi), on the lead's recommendation |
| Owner agent / service | S9 Tenant, Identity & Access (→ Agent 01); S6 Security & Audit (→ Agent 16) for audit, MFA policy review and the permission review |
| Depends on | GLOSSARY_AND_IDS.md §2.1 (UUIDv7), §6.44 (`role`, `user_status`, `membership_status`, `invitation_state`, `auth_provider`); 04_DATABASE_ARCHITECTURE.md §3.1 (role `amw_auth`), §3.2 (`app.user_id`), §5.1 (`users`, `user_auth_refs`, `user_sessions`, `memberships`, `invitations`, `org_controls`), §5.26 (`org_sso_connections`, `org_domains`); 08_SECURITY.md §2, §5.1–5.6, §6, §7.2, §9.2, §12.3; 20_MULTI_TENANCY_AND_ENTERPRISE.md §6 (MT-4.x); 22_DATA_PROTECTION.md (P2 credentials); 3A_SLICE_SPEC.md R14; ADR-002 (tenancy), ADR-004 (dashboard stack, HttpOnly cookie) |
| Directive sections covered | §1C.4 (identity and access: Tier 1 email + password + MFA, Google sign-in, org invites, 8 roles; Tier 3 SAML/OIDC SSO, SCIM, domain verification, session policies, IP allow-list; "proven auth library or self-hosted identity service chosen in an ADR by RAM footprint and SSO/SCIM support — never hand-rolled crypto"); §1C.15 (tier gates); §1 (shared VPS, low resident footprint); §3.2a (simplest option that meets the requirement); rule 9 (tenant isolation) |
| Research IDs | INF-01 (shared 2 vCPU / 8 GB VPS). New evidence in §2.1 (checked 2026-11-18, official pages / PyPI JSON), **to be recorded in RESEARCH_LOG.md as AUTH-01 … AUTH-12 (pending; this ADR does not edit the log)** |
| MVP scope | **3A: none** (no web login, no Google OAuth, D1; owner acts through the operator CLI, 3A_SLICE_SPEC R14). **3B: none.** **3C:** live email + password + TOTP MFA, Google sign-in, invites, sessions, roles. |
| Enterprise tier | Tier 0 design (one human: the platform owner) → **Tier 1 live** (first client: invites, `CLIENT_GUEST`, MFA) → Tier 2 (self-serve sign-up on the same component) → **Tier 3** (per-org SAML/OIDC SSO, SCIM, domain verification, session policy, IP allow-list) |

## 1. Context
- §1C.4 requires a proven library or a self-hosted identity service, selected by **RAM footprint** and **SSO/SCIM support**, and forbids hand-rolled crypto. 08 §5.5 and §7.2 leave password/MFA mechanics, credential storage and the SSO/SCIM library to this ADR; 04 §5.1 and 22 (P2) leave the **credential storage location** to this ADR.
- The factory shares one 2 vCPU / 8 GB VPS with existing apps (INF-01); every extra resident service competes with them (05). The backend is Python + FastAPI (27 §1, SOURCE_LAYOUT `apps/api`); the Tier 0 dashboard is server-rendered with an HttpOnly session cookie (ADR-004).
- The identity model already exists in the contracts and must not be redefined: `users`, `user_auth_refs` (`provider` = `auth_provider` enum, `external_subject`), `user_sessions` (`active_org_id`, `mfa_verified_at`, `expires_at`, `revoked_at`), `memberships` (`role`, `workspace_ids`), `invitations` (`token_hash`, `expires_at`, single use), DB role `amw_auth` (04 §3.1, §5.1). Permission checks are server-side against the 08 §5.2 matrix.
- Enterprise items (SAML/OIDC SSO, SCIM, domains) are **Tier 3 only**, built when a paying client needs them (§1C.15, 08 §2). 3A has no auth component at all (D1, R14).

## 2. Options considered (with evidence)

### 2.1 Evidence collected for this ADR (2026-11-18; pending RESEARCH_LOG entries)
| Proposed ID | Fact (as stated by the official source) | Source |
|---|---|---|
| AUTH-01 | Keycloak: "The base memory usage for a Pod including caches of Realm data and 10,000 cached sessions is 1250 MB of RAM"; "approximately 300 MB of non-heap-based memory"; "For each 15 password-based user logins per second, allocate 1 vCPU". Docs list release 26.8.2. | [Keycloak sizing](https://www.keycloak.org/high-availability/single-cluster/concepts-memory-and-cpu-sizing) |
| AUTH-02 | Keycloak features list: `scim-api:v1` ("Exposes a SCIM API for managing realm resources on a per-realm basis") under "supported features that are enabled by default"; also `passkeys:v1`, `recovery-codes:v1`, `web-authn:v1`. SCIM is switched on per realm. Keycloak "can also authenticate users with existing OpenID Connect or SAML 2.0 Identity Providers" and offers social login. Keycloak is a CNCF incubation project. | [features](https://www.keycloak.org/server/features), [server admin guide](https://www.keycloak.org/docs/latest/server_admin/index.html), [home](https://www.keycloak.org/), [community](https://www.keycloak.org/community) |
| AUTH-03 | authentik Docker Compose: "for test setups and small-scale production setups"; requirement "A host with at least 2 CPU cores and 2 GB of RAM". Docs show 2026.5 and 2026.8 (pre-release). | [authentik compose install](https://docs.goauthentik.io/install-config/install/docker-compose/) |
| AUTH-04 | authentik has a SCIM **source** ("allows other applications to directly create users and groups within authentik"), a SAML source (authentik as SAML service provider) and a Google identity source. "authentik Enterprise adds features for identity provisioning, security, compliance…" via a licence key; which features are Enterprise-only is not shown on the pages read. | [SCIM source](https://docs.goauthentik.io/users-sources/sources/protocols/scim/), [SAML source](https://docs.goauthentik.io/users-sources/sources/protocols/saml/), [Google](https://docs.goauthentik.io/users-sources/sources/social-logins/google/), [Enterprise](https://docs.goauthentik.io/enterprise/) |
| AUTH-05 | ZITADEL "itself requires approximately 512MB of RAM and can operate with less than one CPU core"; the database "utilizes about one CPU core per 100 requests per second … and 4GB of RAM per core"; "We recommend to have 4 CPU cores available" for password hashing. SCIM v2.0 is labelled **Preview**. Docs list v4.20. | [production setup](https://zitadel.com/docs/self-hosting/manage/production), [SCIM v2](https://zitadel.com/docs/apis/scim2) |
| AUTH-06 | Ory Kratos: login/registration, social sign-in, MFA (TOTP), account recovery. Ory organizations (OIDC/SAML SSO, SCIM): "SAML is available exclusively on select Enterprise plans" (Ory Network page). Ory Polis (formerly BoxyHQ Jackson) is an "Enterprise Single Sign-On (SSO) service for SAML and OIDC identity providers". | [Kratos intro](https://www.ory.sh/docs/kratos/ory-kratos-intro), [organizations](https://www.ory.sh/docs/kratos/organizations), [Polis](https://www.ory.sh/docs/polis/) |
| AUTH-07 | Authelia "is a companion of reverse proxies"; payloads never reach it, only the authentication pieces. | [architecture](https://www.authelia.com/overview/prologue/architecture/) |
| AUTH-08 | Authlib 1.9.9, BSD-3-Clause, Python ≥ 3.10, "Production/Stable"; "building OAuth and OpenID Connect servers and clients". | [PyPI authlib](https://pypi.org/project/authlib/) |
| AUTH-09 | argon2-cffi 25.1.0, MIT, Python ≥ 3.8, "Production/Stable". pwdlib 0.4.2, MIT, Python ≥ 3.11, "Beta". | [PyPI argon2-cffi](https://pypi.org/project/argon2-cffi/), [PyPI pwdlib](https://pypi.org/project/pwdlib/) |
| AUTH-10 | pyotp 2.12.0, MIT, Python ≥ 3.10, "Production/Stable". webauthn 3.0.1, BSD-3-Clause, Python ≥ 3.10, "Production/Stable". | [PyPI pyotp](https://pypi.org/project/pyotp/), [PyPI webauthn](https://pypi.org/project/webauthn/) |
| AUTH-11 | fastapi-users 15.0.5, MIT: "This project is now in maintenance mode … security updates and dependency maintenance, no new features". | [PyPI fastapi-users](https://pypi.org/project/fastapi-users/) |
| AUTH-12 | SAML/SCIM Python libraries: python3-saml 1.16.0 (MIT, last upload 2023-10-09); pysaml2 7.5.5 (upload 2026-09-17; licence not in PyPI metadata); scim2-server 0.8.6 (Apache-2.0, "Beta"); scim2-models 0.12.4 (Apache-2.0, "Beta", Python ≥ 3.11). | PyPI: [python3-saml](https://pypi.org/project/python3-saml/), [pysaml2](https://pypi.org/project/pysaml2/), [scim2-server](https://pypi.org/project/scim2-server/), [scim2-models](https://pypi.org/project/scim2-models/) |

Not obtained (GitHub hosts return HTTP 403 in this session): licences of Keycloak, authentik (open-source core), ZITADEL, Ory Kratos, Ory Polis; RAM of Kratos and Polis; whether fastapi-users has built-in MFA. **REQUIRES REVIEW (Phase 1): read each licence file and record it before any service option is adopted.** Development-status classifiers are the authors' own declarations.

### 2.2 Comparison
| Criterion | A. In-process libraries in `apps/api` (Authlib + argon2-cffi + pyotp; webauthn optional) | B. fastapi-users | C. Keycloak | D. authentik | E. ZITADEL | F. Ory Kratos (+ Polis) |
|---|---|---|---|---|---|---|
| Extra resident service on the VPS | **None** (runs inside the API process) | None | Yes; base 1250 MB (AUTH-01) | Yes; host ≥ 2 GB RAM (AUTH-03) | Yes; ~512 MB + DB load (AUTH-05) | Yes; RAM **REQUIRES REVIEW** |
| Password + MFA (§1C.4 Tier 1) | argon2 hashing (AUTH-09), TOTP (AUTH-10); flows written by the factory on these primitives | Password flows; MFA **REQUIRES REVIEW** | Yes, incl. passkeys, recovery codes (AUTH-02) | Yes (MFA mechanics **REQUIRES REVIEW**) | Yes (**REQUIRES REVIEW**: mechanics) | TOTP MFA (AUTH-06) |
| Google sign-in | Authlib OIDC client (AUTH-08) | OAuth client (**REQUIRES REVIEW**) | Social login (AUTH-02) | Google source (AUTH-04) | **REQUIRES REVIEW** | Social sign-in (AUTH-06) |
| Org invites, 8 roles, `org_id` model | Native: 04 §5.1 tables used as written | Needs custom code anyway | Realm/group model must be mapped to `memberships`; double source of truth | Same mapping issue | Same mapping issue | Same mapping issue |
| Tier 3 SAML / OIDC SSO | OIDC via Authlib; SAML via pysaml2 / python3-saml (AUTH-12, maturity concern) | — | Yes (AUTH-02) | SAML source (AUTH-04) | **REQUIRES REVIEW** | Enterprise plans only / Polis (AUTH-06) |
| Tier 3 SCIM (inbound) | scim2-* "Beta" (AUTH-12) + own endpoint | — | Supported, per realm (AUTH-02) | SCIM source (AUTH-04) | Preview (AUTH-05) | Via organizations (AUTH-06) |
| Maintenance status | Production/Stable primitives (AUTH-08..10) | **Maintenance mode** (AUTH-11) | Active (26.8.2) | Active | Active | **REQUIRES REVIEW** |
| Hand-rolled crypto risk | None if only library primitives are used (rules in §3.3) | None | None | None | None | None |

Rejected without further scoring: **Authelia** — a reverse-proxy companion (AUTH-07), not a user/org/invite store for a multi-tenant product. **B. fastapi-users** — maintenance mode, no new features (AUTH-11); the org/invite/role model is custom anyway.

## 3. Decision (Draft)

### 3.1 3A and 3B: no authentication component
No web login, no public endpoint, no Google OAuth (D1). The owner is the only human and acts through the operator CLI inside the factory environment, which writes `actor_ref = usr_<owner id>` (3A_SLICE_SPEC R14). `user_sessions`, `user_auth_refs`, `invitations` stay unused (3A_SLICE_SPEC §2). The 08 §5.2 matrix is still enforced in code (08 §5.2 rule 4).

### 3.2 3C, Tier 0–2: Option A (in-process proven libraries)
Simplest option that meets §1C.4 Tier 1 with **zero extra resident RAM** on the shared VPS (INF-01, §3.2a). Every service option adds a resident process of hundreds of MB to over 1 GB (AUTH-01, -03, -05) and a second user store that must be kept in sync with `memberships`.
| Function | Library (pinned exact version at build, 27) | Contract used |
|---|---|---|
| Password hashing | argon2-cffi, Argon2 (AUTH-09). Parameters: **REQUIRES REVIEW (Phase 1): official Argon2 / library recommended parameters, recorded in RESEARCH_LOG; then measured on the VPS (hash time and memory per login)** | credential row (pending CCR, §3.4) |
| MFA | TOTP via pyotp (AUTH-10) + single-use recovery codes stored as hashes; WebAuthn/passkeys via webauthn (AUTH-10) optional, 3C+ | `users.mfa_enrolled`, `user_sessions.mfa_verified_at` (04 §5.1) |
| Google sign-in | Authlib OIDC client (AUTH-08), scopes for sign-in only (`openid`, `email`, `profile`); a **separate** Google client from the per-channel YouTube OAuth of 08 §6. Whether this client needs Google verification: **REQUIRES REVIEW (Phase 1)** | `user_auth_refs (provider = GOOGLE, external_subject)` |
| Sessions | Server-side rows; cookie `HttpOnly`, `Secure`, `SameSite` (08 §5.5); CSRF per ADR-004; revocable (`revoked_at`); MFA step recorded | `user_sessions`; opaque token hash (pending CCR, §3.4) |
| Invitations | Random single-use token from a CSPRNG (standard library; **REQUIRES REVIEW (Phase 1): record the official reference**), stored as SHA-256 `token_hash`, expiry, revoked on membership removal (08 §5.4); acceptance creates `memberships` row `ACTIVE`; `PLATFORM_OWNER` never invitable (04 §5.1) | `invitations`, `memberships` |
| Roles | `role` enum (GLOSSARY §6.44) on `memberships`; checks against 08 §5.2 in the API and at the state-machine guard | `memberships.role`, `workspace_ids` |
| Tenant context | After login, the request sets `app.user_id` and `app.org_id = user_sessions.active_org_id` with `SET LOCAL` (04 §3.2); `active_org_id` must have an `ACTIVE` membership (04 trigger) | 04 §3.2, ADR-002 |
| Audit | login failure thresholds, role change, MFA change, invite/suspend (08 §9.2); account-takeover playbook (08 §12.3) | `audit_log` |

Lockout, rate-limit and session-lifetime values: **REQUIRES REVIEW (Phase 1): owner policy + measured; recorded as configuration** (08 §5.5). All auth code lives in S9 (`apps/api` + `amw_core`), connects as DB role `amw_auth` for identity tables only (04 §3.1, 08 §4), and is covered by the 08 §8.2 security/tenancy CI markers.

### 3.3 No hand-rolled crypto (binding rules for Option A)
1. Hashing, TOTP, WebAuthn, OIDC token validation and random generation use only the libraries above; the factory writes **flows**, never primitives.
2. No custom token formats or signatures; session and invite tokens are opaque random values stored only as hashes.
3. MFA secrets at rest are encrypted with the crypto library chosen in 08 §6 (choice REQUIRES REVIEW there); keys from the environment secret mechanism (08 §3).
4. An external security review of the auth flows is required before Tier 1 (08 §13 pack).

### 3.4 Credential storage location (closes 04 §5.1 / 22 P2 REQUIRES REVIEW)
In the factory PostgreSQL, in a GLOBAL (RLS self) table readable/writable only by `amw_auth`, **not** in a separate identity service. The table does not exist in 04 yet: written here as **`user_credentials` (pending CCR)**; `user_sessions` needs an opaque-token hash column, written as **`user_sessions.token_hash` (pending CCR)**, because the UUIDv7 row id is time-ordered (GLOSSARY §2.1) and must not serve as a bearer secret. Per-org MFA enforcement is written as **`org_controls` key `mfa_required` (pending CCR)**; 04 today has only the per-user `mfa_enrolled` flag.

### 3.5 Tier 3: SSO / SCIM decided when a paying client needs it
- OIDC SSO per org can stay in Option A (Authlib, AUTH-08). SAML and inbound SCIM in-process rely on less mature libraries (AUTH-12).
- **Default for Tier 3:** a self-hosted identity broker **only on the dedicated or own server of that tier** (04 §8.4), never on the shared VPS; it federates the client's IdP and forwards an OIDC login to the factory, which keeps `users` / `memberships` / `org_sso_connections` / `org_domains` as the system of record (08 §7.2). Candidate with the strongest documented SAML + SCIM support: Keycloak (AUTH-01, AUTH-02); alternatives ZITADEL (SCIM Preview, AUTH-05) and Ory Polis (AUTH-06). Final pick by a Phase 1 spike: licence (REQUIRES REVIEW), measured RAM, SCIM deprovisioning → `membership_status = SUSPENDED/REMOVED` + session and API key revocation (MT-4.7), enforced SSO with audited break-glass (MT-4.6).
- Session policies and IP allow-list follow 08 §7.2 / §7.4 (storage pending CCR there).

## 4. Consequences
- **Positive.** No extra resident service at Tier 0–2; one identity store (04 §5.1) under the same RLS and tenancy tests; no sync between an external user store and `memberships`.
- **Negative.** The factory owns login, MFA, recovery and invite flows (more code and review). Mitigation: §3.3 rules, 27 §3 coverage floor, 08 §8.2 security tests, external review before Tier 1.
- **Tier 3 cost.** A second deployment (identity broker) is needed for SAML/SCIM; it is outside 3A–3C.
- **Resource.** Argon2 hashing costs CPU and memory per login (Keycloak and ZITADEL docs both flag hashing CPU, AUTH-01, AUTH-05); values ESTIMATE until measured on the VPS (05).

## 5. Required tests (3C; marker `security` / `tenancy`, 08 §8.2)
1. Password login with wrong password N times → lockout and audit entry; no user enumeration in responses.
2. MFA-required org: session without `mfa_verified_at` cannot call any write permission key.
3. Revoked session (`revoked_at`) and expired session are refused on the next request.
4. Invitation token: single use, expired token refused, `PLATFORM_OWNER` role refused, revoked on membership removal.
5. Google sign-in: `user_auth_refs (GOOGLE, external_subject)` uniqueness; an unverified email cannot attach to an existing user.
6. `active_org_id` without an `ACTIVE` membership is refused; user A cannot read org B rows (04 §3.7).
7. `amw_app` cannot read credential rows; only `amw_auth` can (08 §4.1 grant drift test).

## 6. Status
**Draft - documentation.** Nothing here blocks 3A (no auth in 3A). Owner approval needed before 3C auth code; the three pending CCRs must be accepted first.

## 7. Revisit triggers
1. Measured RAM headroom on the VPS or on a Tier 1 own server makes a service option affordable and the in-process flow code is larger than expected.
2. A paying client requires SAML or SCIM (Tier 3 spike, §3.5).
3. A chosen library leaves production/stable status, enters maintenance mode, or has an unpatched security advisory (27 dependency scanning, 08 §10).
4. An external security review finds a flaw in the in-process flows that a service option would avoid.

## 8. Cited research IDs
INF-01. Pending RESEARCH_LOG entries: AUTH-01 … AUTH-12 (§2.1).
