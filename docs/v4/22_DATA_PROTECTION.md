# 22 — Data Protection (DPDP, DPA, privacy notice, export, erasure, retention, breach response)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | S6 Security & Audit → Agent 16 (§3.2) for controls, breach runbook and access review; S9 Tenant, Identity & Access → Agent 01 for `data_requests` workflow; platform owner (Abhi) as the Data Fiduciary / processor decision-maker |
| Depends on | GLOSSARY_AND_IDS.md (IDs `dtr`, `dek`, `vcn`; enums `data_request_kind`, `data_request_status`, `org_status`), 03_COMMUNICATION_STANDARD.md (§8 storage URIs and prefix layout), 04_DATABASE_ARCHITECTURE.md (§5.24, §7 retention, §5.19 keys, §5.13 audit), 07_FAILURE_MANAGEMENT.md (§7 escalation), 08_SECURITY.md (§3 secrets, §6 token encryption, §12 incident runbook), 12_DISASTER_RECOVERY.md (§6.7, §10), 13_COMPLIANCE_YOUTUBE_POLICY.md, 09_COST_AND_BUDGET.md, adr/ADR-005_storage.md, KNOWLEDGE_LIBRARY_PLAN.md (by name only) |
| Directive sections covered | §1C.10 (data protection), §1C.1 (per-tenant data), §1C.5 (audit), §1C.11 (backups with per-tenant restore/export), §1C.14–15 (tier gates), §0 rules 3, 4, 9 |
| Decisions applied | D1 (3A: no Google OAuth, no upload, owner-given topics; keys only through the environment secret mechanism), D2 |
| Facts | RESEARCH_LOG.md **IN-07** (DPDP Rules 2025); rule text read from the official Gazette PDF listed in IN-07 on 2026-11-18 (see §2) |
| Not decided here | Retention **durations** and notification wording — owner's lawyer ⚖ and accountant; auth library (ADR-003); crypto library (08 §6); backup tool and destination (ADR-005 §3.4, 12) |

> **Not legal advice.** This document is a design and a checklist for the owner's lawyer. Items marked **⚖** need the lawyer's decision before they are used with a client or published. Nothing here is to be presented to a client as a legal commitment until the lawyer has approved it.

**Scope key.** Build scope: **3A** (production line) / **3B** (golden samples) / **3C** (everything else). Enterprise tier: **T0** (owner's own channel) → **T1** (first managed-service client) → **T2** (self-serve) → **T3** (enterprise) (GLOSSARY §6.47).

---

## 1. Principles and scope

1. **Minimise first.** The platform stores personal data only where a feature needs it (§3). 3A stores almost none: the owner's own account and the owner-given topic.
2. **Design now, switch on at the tier gate.** The tenant-scoped layout (every row has `org_id`, every blob lives under `<org>/…`, 03 §8 rule 1) already makes export and erasure a prefix-and-rows operation. The workflow (`data_requests`, 04 §5.24) is **T1**, due before the first external client.
3. **Role split (to be confirmed ⚖).** IN-07 defines a Data Fiduciary as the party that "determines the purpose and means" and a Data Processor as one that "processes personal data on behalf of a Data Fiduciary". Working assumption, from the directive §1C.10: for **client data** (client's staff, client's audience comments, client's voice owners) the platform owner acts as **processor**; for the **platform's own** data (its users' sign-in data, billing contacts, its own prospects and course leads, the owner's own channel audience data) it acts as **fiduciary**. The split is a legal conclusion ⚖.
4. **No private data in this repository** (public repo rule, 08 §11). This document names data classes, not data.
5. **Tenant isolation is absolute** (rule 9). Export and erasure run under the tenant context and can never touch another tenant (08 §8).

| Capability | 3A | 3B | 3C | Tier |
|---|---|---|---|---|
| Personal-data inventory (§3), data-location statement (§12), secrets handling (§9) | **yes** | yes | yes | T0 |
| Audit of access to personal data (§10) | yes (owner org) | yes | yes | T0 |
| Breach runbook drilled once with synthetic data (§8, 08 §12.4) | draft | **drilled** | yes | T0 |
| `data_requests` export / erasure workflow and test (§6, §7) | no | no | **built** | T1 gate |
| DPA template, privacy notice, retention values approved by lawyer (§4, §5, §11) | no | no | drafts | T1 gate |
| Grievance and rights channel published (§5.3) | no | no | yes | T1 (T0 if the owner's own audience data is processed after May 2027 ⚖) |
| Dedicated-stack deletion / data residency options (§12.3) | no | no | no | T3 |

---

## 2. Legal baseline (facts and what is not known)

**Source.** RESEARCH_LOG **IN-07**: DPDP Rules 2025, G.S.R. 846(E), Gazette 13 Nov 2025 (PIB says 14 Nov). Rules 1, 2, 17–21 in force on publication; Rule 4 (consent managers) one year later (~**13 Nov 2026**); **Rules 3, 5–16, 22, 23 after 18 months (~13 May 2027)**. Status VERIFIED for the milestones; "no later amendment" was **not** confirmed against the Gazette.

**Date position on the day of writing (2026-11-18).** The first milestone (~13 Nov 2026) has passed; it concerns consent managers (Rule 4) and does not create a duty for this platform. The substantive duties start ~**13 May 2027**. The design is therefore to be in place before the first client (T1) and before that date, whichever is earlier.

**What the Rules text says on the points this document uses** (read from the official Gazette PDF cited in IN-07 on 2026-11-18; the Act itself was not re-read; amendments after publication not checked — **REQUIRES REVIEW (Phase 1): confirm against the current Gazette and any later amendment before the lawyer finalises** ⚖). To be added to RESEARCH_LOG as a follow-up entry by the owner of that file (this document does not edit it).

| Rule | Content relevant here | Used in |
|---|---|---|
| 3 | Notice must be understandable independently, in clear and plain language, give an **itemised description** of the personal data and the **specified purposes** and the goods/services or uses enabled; give the link to the website/app and describe how to **withdraw consent** (as easy as giving it), **exercise rights** and **complain to the Board** | §5 privacy notice |
| 6 | "Reasonable security safeguards" at minimum: encryption/obfuscation/masking/virtual tokens; access control to computer resources of the fiduciary **and its processor**; logs, monitoring and review to detect unauthorised access; backups for continued processing; **retain logs and personal data for one year** for detection/investigation unless another law requires otherwise; contract with the processor providing for safeguards | §9, §10, §4 |
| 7 | Breach: tell each affected Data Principal without delay (nature, extent, timing, consequences, mitigation, safety steps, contact); tell the Board **without delay** and again **within 72 hours** (or longer if the Board allows in writing) with detailed facts, mitigation, findings on the person who caused it, remedial measures and a report on the intimations to Data Principals | §8 |
| 8 | Erasure after the purpose is served applies to the classes in the Third Schedule (large e-commerce, online gaming, social-media intermediaries over stated user counts; 3 years); 48-hour advance warning before such erasure; **minimum one-year retention of personal data, traffic data and processing logs** for the purposes of the Seventh Schedule, unless other law requires longer. Whether the platform falls in a Third Schedule class: expected not, but ⚖ | §11 |
| 9 | Publish contact information of the DPO (if applicable) or a person who can answer questions about processing | §5 |
| 10, 12 | Verifiable parental consent for children's data; exemptions by class | §3 (the platform does not target children; "made for kids" channels, §1C.7, are a risk to be assessed ⚖) |
| 14 | Publish how Data Principals make rights requests and what identifier is needed; grievance redressal with response **within a reasonable period not exceeding 90 days**; nomination of another person | §5.3, §6 |
| 15 | Transfer outside India allowed, subject to requirements the Central Government may specify for particular foreign States or entities | §12 |

**Not known and left to the lawyer ⚖:** whether the platform is a Significant Data Fiduciary (no); how the "processor contract" duties apply to each client type; how the one-year retention minimum interacts with a tenant's erasure request and with backups; what counts as a "personal data breach" notification threshold in practice; whether voice recordings and voice-owner records need special handling; the treatment of YouTube audience data fetched through Google APIs (Google's own terms also apply, §3.3).

---

## 3. Personal-data inventory (what exists, where, why)

Principle: record **classes and columns**, never values. Source tables are in 04; column notes marked "personal data (22)" in 04 are covered here.

| # | Class | Where (04 / 03) | Whose data | Purpose | Role (⚖) | Scope · Tier |
|---|---|---|---|---|---|---|
| P1 | User identity: email, display name, status, MFA flag, last login, provider subject (`users`, `user_auth_refs`, `user_sessions`) | 04 §5.1 | Platform users of any tenant | Sign-in, access control, audit | Fiduciary (platform account); processor for the client's staff accounts | 3A (owner only) · T0 |
| P2 | Credentials (password hashes, MFA secrets) | ADR-003 auth component (location **REQUIRES REVIEW (ADR-003)**) | Users | Authentication | Fiduciary | 3C · T0 |
| P3 | Audit entries: actor, action, target; `details` kept minimal (04 §5.13 "personal data minimised") | `audit_log` | Users, agents | Accountability, tamper evidence | Both | 3A · T0 |
| P4 | Voice-owner records and consent evidence: name, linked user, consent document/recording references (`voice_consents`, blobs `consents/<vcn>/`) | 04 §5.12 area; 03 §8 | Voice owners (staff, hired voice talent, clients) | Proof of consent for synthetic voice (§1C.8) | Processor for clients; fiduciary for the owner's own voice | 3C · T0+ |
| P5 | Community comments: `author_display`, body, triage class, draft reply (`community_comments`) | 04 §5.23 | Public YouTube commenters | Triage into question/spam/abuse/lead; replies only with approval (S13) | Fiduciary for the owner's channel; processor for clients | 3C · T0+ |
| P6 | Review comments and client-portal guest data (`review_comments`, `client_guest` single-purpose tokens stored as hashes) | 04 §5.23, §5.16 | Client reviewers | Approvals | Processor | 3C · T2 |
| P7 | Notifications: recipient user, template, status (`notifications`) | 04 §5.23 | Users | Alerts | Both | 3A · T0 |
| P8 | Analytics snapshots (aggregate channel metrics via YouTube APIs, YT-14) | `analytics_snapshots` | Aggregate; no individual viewer data intended (S1 makes no claims about individual viewers) | Learning loop, reporting | Not personal data if truly aggregate — confirm ⚖ | 3C · T0 |
| P9 | OAuth tokens and webhook secrets (ciphertext) | 04 §5.19 | Channel owners | Publishing (not in 3A) | Processor | 3C · T0 design, T1 live |
| P10 | Billing contacts, invoices, GST details (`subscriptions`, invoices) | 04 §5.25 | Client staff | Billing | Fiduciary (statutory accounting) | 3C · T2 |
| P11 | Owner-supplied or client-supplied source material (own footage, scripts, brand kits, knowledge-library documents) that may contain personal data of third parties | blobs `assets/`, `knowledge/`, `jobs/` | Third parties appearing in material | Production | Processor for clients | 3A (owner's own material) · T0 |
| P12 | Operational logs (structured logs carry `org_id`; **must not** carry content or secrets, 08 §3.1, §10) | host logs | Users (IP/user agent if logged — **REQUIRES REVIEW (Phase 1)**: what the proxy and app log) | Operations, Rule 6 detection | Both | 3A · T0 |
| P13 | Backups of all of the above (12 §6) | off-server backup | All | Recovery | Same as source | 3C · T1 gate |

### 3.1 Data the platform does not collect
No viewer-level profiles. No payment-card data (a payment gateway holds it; the gateway is chosen in an ADR, §1C.9; the gateway's own terms are for the lawyer ⚖). No biometric templates: a voice recording stored as consent evidence is evidence, not an identification feature, and is not used to train anything (**decision for the owner; ⚖ for the legal characterisation**).

### 3.2 AI provider data flow
Prompts and files sent to AI providers (ADR-007 routing, ADR-008 TTS) can contain personal data when a client's material does. Rules: (1) personal data is not put in prompts unless the step needs it; (2) the provider list per tenant is recorded so the DPA sub-processor list (§4) is generated, not hand-written; (3) provider data-use, retention and training terms for each provider are **REQUIRES REVIEW (Phase 1): read each provider's current official terms and record in RESEARCH_LOG before any client material is sent**; (4) for the owner's own channel in 3A the owner-given topic carries no third-party personal data by design.

### 3.3 Google / YouTube data
YouTube API data and OAuth tokens are governed by Google's own terms as well as DPDP. Google's API policies on storage, refresh and deletion of API data: **REQUIRES REVIEW (Phase 1): confirm the current YouTube API Services policy on stored API data and user-initiated deletion (13_COMPLIANCE_YOUTUBE_POLICY.md covers the audit; no RESEARCH_LOG ID for this point exists)**. 3A has no Google OAuth (D1), so this starts at 3C / T1.

---

## 4. DPA template outline (Data Processing Agreement) — T1 gate, 3C

A template for the platform (processor) and a client (fiduciary). **Outline only; ⚖ for every clause.** It is attached to the client agreement; version-controlled; the accepted version and date are recorded per org (pending CCR-A in §14).

| § | Clause | Content to settle with the lawyer ⚖ |
|---|---|---|
| 1 | Parties, definitions | Use IN-07 definitions (Data Fiduciary, Data Processor, Data Principal, personal data breach) as the Act defines them ⚖ |
| 2 | Subject matter, nature, purpose, duration | Processing only to produce and deliver the client's video content and run the client's channels; duration = contract term plus export window (§7) |
| 3 | Data classes and data subjects | From §3 (P1, P4–P6, P9, P11); client confirms nothing outside the list is supplied without notice |
| 4 | Instructions | Processing only on the client's documented instructions (the job request, brand kit and compliance profile are the instructions); the platform tells the client when an instruction looks unlawful ⚖ |
| 5 | Confidentiality of staff | Access by role (§10); named staff list is not kept in the repo |
| 6 | Security safeguards | Reference to §9 and 08: encryption of tokens/secrets (08 §6), access control, logging and monitoring, backups, **retention of logs for the period the law requires (IN-07 Rule 6: one year)**; the contract must say that these safeguards apply (Rule 6(1)(f)) |
| 7 | Sub-processors | List generated from the provider ledger: AI/LLM, TTS, stock-media, hosting, storage, payment gateway, e-mail. Change notice period and objection right: **REQUIRES REVIEW ⚖** |
| 8 | Data location and transfers | Statement from §12; IN-07 Rule 15 (transfer outside India subject to conditions the government may specify) ⚖ |
| 9 | Data-principal requests | The platform forwards requests to the client and helps within the times in §6; it does not answer data principals directly for client data ⚖ |
| 10 | Breach | The platform tells the client **without undue delay** (target hours: **REQUIRES REVIEW ⚖ / owner**, single-operator reality, 08 §12.1) with the facts the client needs for its own Rule 7 intimations (nature, extent, timing, likely consequences, mitigation) |
| 11 | Audit and information | Client may receive the audit export (CSV/JSON, 08 §9) and the security questionnaire answer pack (§1C.13); on-site audit: **REQUIRES REVIEW ⚖** (not a commitment at T1) |
| 12 | Return and deletion at end | Export bundle (§7), then erasure (§6); backups age out (§11.3); a statement on what must be retained by law |
| 13 | Liability, limits, governing law, jurisdiction | ⚖ entirely |
| 14 | Annexes | A: data classes; B: sub-processors; C: security measures (from 08); D: contact points; E: data location |

**Reverse position.** Where the platform is the fiduciary (its own users), the sign-up terms and the privacy notice (§5) apply instead of a DPA.

---

## 5. Privacy notice outline (platform as fiduciary; and a template for client-facing notices)

Rule 3 content (IN-07, official text): plain language; understandable on its own; itemised personal data; specified purposes and the services or uses enabled; the website/app link; how to withdraw consent, exercise rights and complain to the Board. Notice and consent duties start ~**13 May 2027**; present the notice at sign-up in the language of the interface (Marathi and English first; other languages follow the locale rollout, S3).

### 5.1 Outline (3C · T1 gate; ⚖ approves the text)
1. Who we are and how to reach the person who answers questions (Rule 9). Contact address is **not** stored in this repo; it is set in deployment configuration.
2. What data we process, itemised (from §3: account, access/audit records, comments handled for a channel, voice-consent records, billing contacts).
3. Why, per purpose, and what each purpose enables (one row per purpose; no "other purposes" catch-all).
4. Where it is processed and stored (the data-location statement, §12).
5. Who receives it (sub-processor categories; named list in an annex or link).
6. How long we keep it (retention table, §11, once approved ⚖).
7. Your rights and how to use them (§5.3) and how to withdraw consent.
8. How to complain: first to us, then to the Data Protection Board (Rule 3(c)(iii)).
9. Children: the platform is not for children; handling of "made for kids" channels follows the YouTube compliance profile (13) and the lawyer's view on children's data (Rules 10, 12) ⚖.
10. Changes: version, effective date, notice of change. The accepted version is stored per user (pending CCR-A).

### 5.2 Consent
Consent is requested per purpose, withdrawable as easily as given (Rule 3(c)(i)). Records of consent (what text, which version, when) are kept as an audit event. Whether a given purpose rests on consent or another lawful ground under the Act is ⚖.

### 5.3 Rights and grievance channel
Publish: the means to request access/correction/erasure/nomination, the identifier needed to find the person, and a grievance channel with a response time **not exceeding 90 days** (IN-07 Rule 14). The internal target is shorter and is an owner decision. For client data the platform routes the request to the client (§4 clause 9).

### 5.4 Client-facing notices (the client's audience)
A client may need its own notice to commenters or voice owners. The platform provides a notice **template** and a consent form for voice owners (links to `voice_consents`, §1A.3) but the client owns them ⚖.

---

## 6. Per-tenant erasure (3C · T1 gate)

Workflow object: `data_requests` (`dtr`), `kind = ERASURE`, statuses `RECEIVED → IN_PROGRESS → COMPLETED / REJECTED` (GLOSSARY §6; 04 §5.24). Permission `data.export` / `data.erase` is `PLATFORM_OWNER` and `ORG_OWNER` only (08 §5.2). Erasure = delete rows + the org's storage prefix + destroy DEKs, **except records that must be retained** (04 §5.24; this document, §11).

### 6.1 Steps
| # | Step | Mechanism | Evidence |
|---|---|---|---|
| 1 | Receive and verify the requester is an `ORG_OWNER` (or the platform owner at offboarding); second confirmation by e-mail to the registered owner address | `data_requests` row, `requested_by` | audit entry |
| 2 | Offer and, if wanted, produce the **export bundle first** (§7); tenant confirms in writing | `EXPORT` request | bundle manifest |
| 3 | Stop new work: `org_status = OFFBOARDING`; cancel queued jobs (`job.cancel`); disconnect channels; revoke OAuth tokens at Google (08 §6.5) | existing controls | audit entries |
| 4 | Delete tenant rows under the tenant context, in dependency order; rows that must be kept (§11.2) are **moved to a retained-records form** that carries the minimum identifiers, not the content | migrator-owned procedure behind the workflow (**REQUIRES REVIEW (Phase 1)**: procedure design and the ordering with FKs, 04 §5) | row counts per table |
| 5 | `delete_prefix(org)` on blob storage, behind the workflow only (ADR-005 §3.1); never used by agents | storage interface | prefix listing empty |
| 6 | Destroy the org's DEKs (`data_key_status = DESTROYED`): tokens and webhook secrets become unreadable even if a copy survives (08 §6.6) | 08 §6 | key status |
| 7 | Remove the tenant's vector/knowledge index and memory entries (per-tenant, §1C.1) | agent 04 / 14 interfaces | index drop log |
| 8 | Write the **erasure ledger** entry (the `dtr` ID) outside the database with each later backup so a restore re-applies the erasure (12 §10.5) | 12 §6.5 | ledger file |
| 9 | `org_status = DELETED`; `data_requests.status = COMPLETED`, `completed_at` set; certificate of erasure to the tenant listing what was deleted, what was retained and why, and the backup age-out date | document | audit entry |

### 6.2 Individual data-principal erasure inside a tenant
A commenter or a voice owner asks to delete their data (P4, P5): handled as a `data_requests` row (`subject_note` describes the subject; no secrets). Deletes the comment/consent records for that person, with exceptions in §11.2 (for example a voice consent that proves a voice already used in a published video: ⚖ whether it can be erased while the video is live; default is to flag the video for owner review and not to delete silently).

### 6.3 Not allowed
Erasure never "fixes" the audit chain by editing rows (08 §12.3). Audit entries about personal data keep identifiers and hashes only; their retention is §11.

---

## 7. Per-tenant export (3C · T1 gate; exercised on the owner org at T0)

Defined by 12 §10.1 (not redefined here): database export of every `TENANT`-scope row filtered by `org_id`, the tenant's whole storage prefix, the audit export with `seq`, `prev_hash`, `row_hash`, and a manifest with SHA-256 and size per file, schema version, export time and chain head. **Excluded**: secrets and token ciphertext, other tenants' data, platform-private rule-pack source. Written to `exports/<dtr>/`; it is itself a write-once blob.

Additions from this document:
1. **Requester check and delivery.** Only an `ORG_OWNER`; delivery by a single-purpose expiring link, bundle encrypted in transit and at rest; size and expiry limits: **REQUIRES REVIEW (Phase 1): 08 §5.4**.
2. **Format** is documented and versioned so the tenant can read it without the platform.
3. **Portability promise** is limited to what the bundle holds; it does not promise import into another vendor's tool ⚖.
4. **Test.** DR-T4 (12 §11) is the acceptance test; one test per release exports and restores a synthetic tenant (T0: owner org).
5. **Time.** The service commitment (days to deliver) is a plan item (21) and a lawyer item ⚖; the rights-request outer limit to publish is in §5.3.

---

## 8. Breach-response runbook (personal data)

Extends 08 §12 (incident runbook). It does not replace it. The seven phases (detect, triage, contain, eradicate, recover, notify, review) are in 08 §12.2; this section adds the **personal-data decision points** and the notification steps that 08 left to this document (08 §12.2 step 6).

### 8.1 What is a personal-data breach here ⚖
Working definition for triage: any unauthorised processing or accidental disclosure, acquisition, sharing, use, alteration, destruction or loss of access to personal data that compromises its confidentiality, integrity or availability. The exact statutory wording and the line between a security incident and a notifiable breach: ⚖ (the Act text was not re-read in this pass).

### 8.2 Clock and roles
| Item | Rule |
|---|---|
| **"Becoming aware"** | The time of the first alert or report that, on triage, involves personal data. Recorded in the incident log (alert ID, first-seen time, 08 §12.2). |
| **To the Board** | Without delay: description (nature, extent, timing, location, likely impact). **Within 72 hours** of becoming aware (or longer if the Board allows in writing on request): updated detail, broad facts and reasons, mitigation, findings on who caused it, remedial measures, report on the intimations to data principals (IN-07 Rule 7(2), official text read 2026-11-18). Applies from ~13 May 2027. |
| **To each affected data principal** | Without delay, by account or registered contact: description, consequences relevant to them, mitigation, steps they can take, business contact (Rule 7(1)). |
| **Who sends** | The fiduciary. For client data the **client** is the fiduciary; the platform informs the client (DPA clause 10) so the client can meet Rule 7. For platform-own data the platform owner sends. Whether the platform must also notify the Board for client data ⚖. |
| **Decision-maker** | Platform owner, with the lawyer on call: **REQUIRES REVIEW (Phase 1): named contacts and response targets (single-operator reality, 08 §12.1); contact details are not stored in this repo (08 §12.4)** |

### 8.3 Steps (personal-data overlay)
| # | Step | Detail |
|---|---|---|
| 1 | Contain first | As 08 §12.2 step 3, in that order: emergency stop and `admission_paused`; revoke leaked secret at the provider; suspend sessions/memberships/API keys; set the org `SUSPENDED` if needed; disable the channel connection; **preserve evidence** (no destructive fix) |
| 2 | Scope | From the audit log, storage access logs and queue/state logs: which orgs, which classes (§3), how many data principals, what time window. Logs must exist for this: IN-07 Rule 6 expects logs and monitoring to detect unauthorised access, retained one year |
| 3 | Encryption check | Were the data in ciphertext (token columns, 08 §6) or plain? A leaked token ciphertext without the KEK/DEK is a lower impact than leaked plain comments; record the reasoning |
| 4 | Classify | Notifiable or not (⚖ decides in doubt; **default when unsure: treat as notifiable and ask the lawyer the same day**) |
| 5 | Draft the notices | From the templates in 8.4; one consolidated message per recipient group (Board, client, data principals) |
| 6 | Notify | Client first (platform-as-processor), then the Board and data principals as the fiduciary decides; record **who, when, how, what** in the notification record (pending CCR-B for a structured `breach_incidents` record) |
| 7 | Within 72 h | Send the detailed report to the Board including the report on intimations (Rule 7(2)(b)) |
| 8 | Recover | As 08 §12.2 step 5; verify audit chain and tenancy tests; confirm no unapproved video was published |
| 9 | Review | Blameless review; new control or CI test; update this document and the DPA annex if needed; record in `CHANGE_REQUESTS.md` if a contract changes |

### 8.4 Notice templates (outline)
- **To the client:** what happened, when we became aware, what data classes and which of its data principals might be affected, what we did, what we advise, what we need from the client, our contact.
- **To the Board:** the items listed in §8.2.
- **To data principals:** concise, plain language, Rule 7(1)(a)–(e).
Templates are drafted by the lawyer ⚖ and stored as documents without names or contact details.

### 8.5 Drill
Drilled once on the walking skeleton with synthetic data before the first paid call (08 §12.4; 27 §9) and again before the first client (T1). The drill includes the 72-hour timeline using fake data and a notification dry-run. Scope: **3A draft, 3B drilled**.

---

## 9. Encryption in transit and at rest

| Data | In transit | At rest | Owner doc | Scope · Tier |
|---|---|---|---|---|
| Secrets (provider keys, KEK reference, signing secrets) | not in the repo or logs; delivered through the environment's secret mechanism only (D1; 08 §3.1) | held in the environment/secret mechanism, never in the database in clear (08 §3.1 rule 5); leak = incident, **revoke first** (08 §3.3) | 08 §3 | **3A** · T0 |
| OAuth tokens, webhook secrets | decrypted in memory in the publish worker only | **envelope encryption** with a per-tenant DEK wrapped by a KEK held outside the database; AEAD with unique nonce and org id + column bound as associated data; algorithm and library chosen after review (08 §6; **REQUIRES REVIEW (Phase 1)**) | 08 §6 | 3C · T0 design / T1 live |
| API keys, guest tokens, SCIM tokens | shown once | stored as hashes (08 §7.3, 04 §5.16) | 08 | 3C · T3 / T1 |
| Passwords and MFA secrets | by the auth component | by the auth component, never hand-rolled crypto (ADR-003) | ADR-003 | 3C · T0 |
| Database connections | inside the host not exposed publicly; **encryption in transit when a connection crosses a host boundary** (08 §4 item 4) | Disk/database-level encryption: **REQUIRES REVIEW (Phase 1): hosting capability and cost; owner purchase decision (rule 8)** | 08 §4, 10 | 3C · T1 gate |
| Web and API traffic | TLS for every public endpoint; certificate handling: **REQUIRES REVIEW (Phase 1): deployment ADR** | — | 10 | 3C |
| Blob storage (media, consents, exports) | TLS to any off-host backend | At-rest encryption depends on the backend (ADR-005 local disk first, S3-compatible later): **REQUIRES REVIEW (Phase 1)** | ADR-005 | 3C · T1 |
| Backups | encrypted for transfer off the server | encrypted, access-limited, per-tenant restore tested (08 §4 item 5; 12 §6) | 12 | 3C · T1 gate |
| Voice-consent recordings | as blobs | as blobs, with access limited to roles that handle consent (§10) | 03 §8 | 3C |

**Rule:** the database alone must never allow decryption of tenant secrets (08 §6.1). No cipher name, key length or library is fixed in this document; none is verified in RESEARCH_LOG yet.

---

## 10. Least-privilege staff and agent access to personal data

Built on 08 §4 (database roles), §5 (roles and matrix), §5.3 (agent identities), §9 (audit).

1. **Humans.** Roles are the eight in 08 §5.1. Only `PLATFORM_OWNER` and `ORG_OWNER` may raise `data.export` / `data.erase` (08 §5.2). `CLIENT_GUEST` is approve/comment only and limited to assigned items.
2. **Platform staff see no tenant content by default.** The platform-owner cross-tenant view is a summary (`amw_platform_ops_summary()`; 08 §8.1: functions return identifiers and envelopes, never content columns). Opening tenant content as the platform owner is **break-glass**: a recorded reason, time-limited, and an audit entry visible to the tenant. Needs a permission key not yet in 08: see pending CCR-C.
3. **Agents** act under their own identities with only the tables and storage areas they need (08 §5.3). Only the publish worker reads token ciphertext.
4. **Database.** Roles per 04 §3 (`amw_app`, `amw_publisher`, `amw_auth`, `amw_sysfn`, migrator); RLS with `FORCE` as second line (08 §8).
5. **Access logging.** Reads of personal-data classes P1, P4–P6, P11 by a human other than the data's own tenant members are audited (08 §9.2); the audit list lives in 08. IN-07 Rule 6 expects visibility on access to personal data "through appropriate logs, monitoring and review".
6. **Periodic access review.** The permission audit (S6, 08 §5.6) lists who and what has access; the owner reviews it; interval: **REQUIRES REVIEW (Phase 1): owner-set**.
7. **Laptop/phone hygiene** for the owner's accounts (MFA, device lock) is the owner's action; not specified here.
8. **Offboarding of a person** (staff, reviewer): disable membership and sessions at once, revoke tokens, keep their audit entries (§11).

---

## 11. Retention schedule

**Principle.** Durations are **not decided in this document**. 04 §7 says each value is REQUIRES REVIEW and points here. What this document does is (a) give the classes, (b) give the fixed legal anchors that are VERIFIED, (c) give a **proposal column** the lawyer and accountant confirm. No proposal is to be implemented until approved. Retention is **configuration** (`retention.*` keys, pending CCR-D), not code constants (27 §3 principle: no hard-coded policy).

### 11.1 Table
| Data class (04 §7 row) | Trigger / rule | Fixed anchor (VERIFIED) | Proposal until approved | Decided by |
|---|---|---|---|---|
| Queue rows `DONE`/`CANCELLED` | deleted after `retention.queue_done_ms` | none (operational) | 7 days, as 04 §7 (ESTIMATE; not legal) | owner |
| Jobs, tasks, attempts, transitions, messages | per plan, tied to job retention | none | **REQUIRES REVIEW**: per plan (21); keep as long as the tenant needs re-runs and audit evidence | owner + ⚖ |
| Idempotency keys | `upload.*`, `publish.*` never; others with job retention | none | as 04 §7 | — |
| Finished media | until the tenant deletes or offboards; never only in temp | none | as 04 §7 | owner |
| Audit log | per plan; export before detach; detach by partition, only `amw_migrator`, writes `audit.retention_applied` (04 §5.13, §6; 08 §9.3) | IN-07 Rule 6(1)(e): logs retained **one year** for detection/investigation unless another law requires otherwise; Rule 8(3): minimum one year for personal data, traffic data and processing logs | **at least one year** (floor from the Rules) plus plan setting | ⚖ + 21 |
| Cost ledger, invoices | statutory accounting retention | **REQUIRES REVIEW (Phase 1): owner's accountant; no RESEARCH_LOG entry** | — | accountant ⚖ |
| User identity (P1) | while the account is active; after closure: only what is needed for the retained records | Rule 8(3) one-year floor for processing records | **REQUIRES REVIEW ⚖** | ⚖ |
| Community comments (P5) | per tenant channel setting | none | **REQUIRES REVIEW ⚖**; keep triage outcome without author name when the purpose is served | ⚖ |
| Voice consent records (P4) | while the voice is in use plus period for claims | none | **REQUIRES REVIEW ⚖** | ⚖ |
| Review comments (P6) | with the job | none | as jobs | ⚖ |
| Notifications (P7) | short | none | **REQUIRES REVIEW** | owner |
| Tokens (P9) | until channel disconnect; then ciphertext wiped (08 §6.5) | none | as 08 | — |
| Operational logs (P12) | rotated | Rule 6(1)(e): one year for logs needed for detection | at least one year for security-relevant logs | ⚖ |
| Backups (P13) | several generations; a backup newer than the last restore test is never the only one (12 §6.7) | none | **REQUIRES REVIEW: 22 + 21 + ⚖ (12 §6.7)**; cannot exceed what the privacy notice states | ⚖ |
| Export bundles (`exports/<dtr>/`) | delete after tenant collects, or after an expiry | none | **REQUIRES REVIEW** short window | owner |
| Billing contacts (P10) | statutory | accountant | — | accountant ⚖ |

### 11.2 What survives an erasure request ⚖
List of records that may have to be retained despite a request: accounting records (P10), the erasure-request record itself and its ledger entry, audit entries about the erasure, records for which a law requires keeping (Rule 8(3) minimum one year). Each retained item holds the minimum identifiers. The lawyer approves the list; the certificate of erasure (§6.1 step 9) states what is retained and why.

### 11.3 Backups and erasure
Per 12 §6.7 and §10.5: erasure deletes live data and destroys the DEKs; copies in older backups **age out** with backup retention; a restore re-applies completed erasures from the off-database ledger. The statement that goes into the privacy notice ("erased from live systems at once, from backups within N days") is a lawyer item ⚖. N equals the backup retention, so the retention value drives the statement.

### 11.4 Mechanics
Scheduled maintenance task (system role) applies `retention.*`: row deletes in batches, partition detach for large tables, prefix cleanup for exports. Each run writes an audit entry with counts, never content. Dry-run mode first. The task never deletes final media or anything held for an open `data_requests` or open incident (**legal hold flag**: pending CCR-D).

---

## 12. Data-location statement

### 12.1 Facts available today
- Compute and primary database: the shared VPS plan stated in RESEARCH_LOG INF-01 / INF-02 (hosting company and plan only; **the data-centre location of the plan is not in the research log: REQUIRES REVIEW (Phase 1): confirm from the hosting provider's official documentation or the owner's account page**). No server address or private detail appears in this repository (08 §11).
- Blob storage: local disk first, S3-compatible later (ADR-005; provider and region **REQUIRES REVIEW (Phase 1)**).
- Backups: off-server destination not yet chosen (12 §6, ADR-005 §3.4; owner purchase decision, rule 8).
- External services receive data when used: AI/LLM and TTS providers (ADR-007, ADR-008), stock-media sources (ADR-009), Google/YouTube APIs, payment gateway, e-mail. Their processing locations: **REQUIRES REVIEW (Phase 1): read each provider's official data-location and data-use terms before first use with client data; record in RESEARCH_LOG**.

### 12.2 Statement outline (to publish after the facts above are filled in; ⚖)
1. Where primary data are stored (country; provider type), and that a backup copy is kept in (country).
2. Which categories of processors outside India may receive which data classes (from the sub-processor list, §4).
3. What the platform does not send abroad (secrets, token ciphertext, DEKs, audit chain heads: not applicable to external AI providers by design).
4. How a client can ask for a different arrangement (T3 dedicated stack, §12.3).
5. Legal basis for transfers: IN-07 Rule 15 allows transfers subject to requirements the Central Government may specify; **whether any such requirement applies now: REQUIRES REVIEW ⚖** (not found in the official Rules text; later orders not checked).

### 12.3 Dedicated stack (T3)
The same migrations build a single-tenant deployment (04 §8 rule 4; §1C.1). A client that must keep data in a specific place gets its own server/region under the dedicated option; price and availability are 21 and 17 items, not promises here.

### 12.4 Move to an own server before the first client
Per §1C.14 client data moves to its own server before the first external client (T1). The location statement is re-issued then.

---

## 13. Build plan, tests, acceptance

| Item | Scope · Tier | Acceptance |
|---|---|---|
| Inventory (§3) kept current: every new column that holds personal data is tagged "personal data (22)" in 04 | 3A · T0 | CI check lists tagged columns and fails if a new table has a personal-data field with no row in §3 (**proposal**; design in 27) |
| Logs carry no content or secrets | 3A · T0 | 08 §10 scans pass; log-format test |
| Export (§7) | 3C · T1 | DR-T4 on a synthetic tenant; manifest verifies; excluded items absent |
| Erasure (§6) | 3C · T1 | After erasure: no rows with `org_id`, empty prefix, DEKs `DESTROYED`, tokens unreadable, erasure ledger written; restore test re-applies the erasure (12 §10.5) |
| Cross-tenant | 3C | Request for tenant A cannot read or delete B (08 §8.2) |
| Retention task (§11.4) | 3C · T1 | dry-run and real run on synthetic data; legal hold respected |
| Breach drill (§8.5) | 3B draft→drilled; T1 re-drilled | timeline within the owner-set target |
| Break-glass (§10.2) | 3C · T1 | opening tenant content writes a tenant-visible audit entry |
| DPA, notice, location statement approved | T1 gate | lawyer sign-off recorded outside the repo |

**Tier 0–3 summary.** T0: items in §1 table marked T0 (inventory, secrets, audit, location facts, breach runbook draft). T1: workflow, DPA, notice, grievance channel, retention values, tested export/erasure, own server. T2: client-portal data (P6), billing data (P10), per-plan retention. T3: SSO/SCIM data, API keys, dedicated stack/residency options.

---

## 14. Contract requests and open items

### 14.1 Pending contract change requests (not edited into other docs; listed in `audit/b2_unfiled_ccr_requests_shared.md` for the integrator to file (not yet in CONTRACT_CHANGE_REQUESTS.md); CCR-A…D are local labels, not register IDs)
| Ref | Needed | Target doc |
|---|---|---|
| CCR-A (pending CCR) | `dpa_acceptances` / `notice_acceptances` (TENANT): which DPA/notice version a org or user accepted and when | 04 |
| CCR-B (pending CCR) | `breach_incidents` (TENANT or PLATFORM): incident ID, time aware, classes, counts, notification records | 04, 08 §12 |
| CCR-C (pending CCR) | permission key `data.break_glass` (reason-bound, time-limited tenant-content access) and its audit event | 08 §5.2, §9.2 |
| CCR-D (pending CCR) | `retention.*` configuration keys per data class and a `legal_hold` flag on orgs/jobs/data requests | 04 §7 |

### 14.2 Open items for the owner's lawyer ⚖
1. Fiduciary vs processor split per data class (§1 item 3, §3).
2. Notifiability threshold, who notifies the Board for client data, and the owner's response targets (§8).
3. Retention values, the retained-records list, the backup age-out statement (§11).
4. DPA clauses, sub-processor change rules, audit rights, liability (§4).
5. Privacy notice text, consent grounds per purpose, children and "made for kids" handling (§5).
6. Transfers outside India: any requirement under Rule 15 that applies (§12).
7. Voice recordings and consent evidence: legal characterisation and erasure rules (§3.1, §6.2).
8. Whether the platform falls in any Third Schedule class (§2) and the effect of any later amendment to the Rules.

### 14.3 Open facts (REQUIRES REVIEW, Phase 1)
Hosting data-centre location; each provider's data-use terms; YouTube API stored-data and deletion policy; accounting retention period; disk/database encryption options and cost; crypto library (08 §6); log content actually produced by the proxy and app; Rules text re-read against the Gazette for later amendments.
