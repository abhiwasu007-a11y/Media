# Unfiled contract requests from the Wave B-2 shared documents (integrator pass B2-2)

Status: **filed and decided** in `CONTRACT_CHANGE_REQUESTS.md` §4.7 (integrator pass 5, 2026-11-18): requests 1–40 (S-1…S-40) and part B → CCR-135…167 (mapping table there); part C → ticket P5-05 (§9). Kept as the lane's input record.

Scope: docs 01, 02, 05, 06, 10, 11, 12, 14, 15, 16, 20, 22, 25 as integrated on branch `claude/v4-b2-shared`. None of these is in `CONTRACT_CHANGE_REQUESTS.md` (this lane may not edit it or any Wave A contract). Each line: `file:line | what | proposed text`. The documents write against the proposed names and mark them `(pending CCR)`; the `CCR-A`/`CCR-20-nn`-style labels inside the documents are local labels, not register IDs. Line numbers are those of the branch head and may shift.

Requests already applied elsewhere were removed from the documents (CCR-3A-1/2/3 = CCR-003/006/043/017; `PILOT_TOTAL`/`PROVIDER` = CCR-035; `agent_04.knowledge_ingest` = CCR-014; `presenter_kind` = CCR-027; `Clock` Protocol exists as built).

## A. Contract requests

| # | file:line | What | Proposed text |
|---|---|---|---|
| 1 | 02:171, 05:388, 14:373 | Scheduled system jobs (S4 reconciliation, S5 sampling, S1 `svc_s01.audience_rollup`, S10 `svc_s10.usage_rollup`, S6 permission review) have no canonical task type or execution/audit rule in 24 §3.2 | Add a system-job family to 24 §3.2 (`NO_DELIVERABLE`, like `agent_04.knowledge_ingest`) with task types `svc_s01.audience_rollup`, `svc_s10.usage_rollup` (Tier 2) and a rule that other scheduled checks run as `sys_scheduler` with audited `system_job.*` events |
| 2 | 05:388 | Resource samples / threshold events table | Table `resource_samples` (GLOBAL, 3C, non-tenant); until applied only ephemeral metrics plus audit entries (05 §9.4) |
| 3 | 06:393 | Night-run record and window events | Table `night_runs` (`scope`, `scope_id`, `window_start`, `window_end`, `drain_started_at`, `closed_at`, `report_ref` blob kind `REPORT`); audit events `night.window_opened`, `night.drain_started`, `night.window_closed` |
| 4 | 06:394 | Tenant-wide window default | Column `organisations.production_window jsonb` (04 has `channels.production_window` only) and the window-document schema of 06 §12.2 in GLOSSARY or 03 |
| 5 | 10:357 | Deployment placement key | Configuration key `deployment.profile`, values `shared_vps` / `own_server` / `dedicated_tenant` in GLOSSARY (config key, not a DB enum) |
| 6 | 10:358 | Worker/core version check | Rule in 03 §11 T07 admission or worker registration: refuse a worker whose `workers.software_version` is incompatible with the core release |
| 7 | 12:456 | Backup actor | Add `backup` to `sys_<name>` (GLOSSARY §2.3, actor_ref regex note) |
| 8 | 12:457 | Backup DB role | 04 §3.1: role `amw_backup`, login, no owned objects, `SELECT` on all tables, `BYPASSRLS`, never granted to services (RLS hides all rows from `amw_app`/`amw_readonly`, INF-11) |
| 9 | 12:458 | Backup error codes | 07 §2: `INFRASTRUCTURE.BACKUP_FAILED` (RETRY next window), `INFRASTRUCTURE.BACKUP_STALE`, `INFRASTRUCTURE.RESTORE_TEST_FAILED` (L3 operations) |
| 10 | 12:459 | Backup run record | Table `backup_runs` (GLOBAL, prefix `bkr`; `kind`, `status`, `started_at`, `finished_at`, `size_bytes`, `manifest_sha256`, `verified_at`, `error_code`); enums `backup_kind` (`DB`,`BLOB`,`CONFIG`,`AUDIT_HEADS`,`RESTORE_TEST`), `backup_run_status` (`RUNNING`,`SUCCEEDED`,`FAILED`) |
| 11 | 12:460 | Backup audit names | 08 §9.2: `backup.completed`, `backup.failed`, `restore_test.completed`, `restore_test.failed`, `restore.performed` |
| 12 | 14:374 | Comment triage task types and capability | 24 §3.2: `svc_s13.comment_triage`, `svc_s13.reply_draft`; decide reuse of `publish_youtube` or a new comment capability |
| 13 | 14:375, 14:106 | Native-speaker QC approval kind | GLOSSARY §6.15 `approval_kind` `NATIVE_SPEAKER_QC` (alternative: reuse `SCRIPT`) |
| 14 | 14:376 | Webhook delivery task | 24 §3.2: `svc_s12.webhook_deliver` (bounded retries per 07) |
| 15 | 14:377 | Compliance subject kinds | `agent_16.compliance_gate` accepts `comment_reply` and `translated_script` |
| 16 | 15:245 | Experiment transition table | State transition table and guard trigger for `experiment_state` (15 §7) |
| 17 | 15:246 | Learning task types | 24 §3.2: `agent_14.insight_analysis`, `agent_14.experiment_proposal`, `agent_14.experiment_readout` |
| 18 | 15:247 | Insight storage | Table `insights` plus `experiments.insight_id`, `experiments.applied_change_ref`; or keep in `memory_items` / `result` jsonb (owner/integrator decision) |
| 19 | 15:248 | Config keys | `learning.min_sample_size`, `learning.min_duration_ms`, `learning.guard_metrics` (values REQUIRES REVIEW) |
| 20 | 16:557 | Permission keys | 08 §5.2: `ops.resume` (03 T15 uses it; same roles as `control.write`), `revenue.read` (`PLATFORM_OWNER`, `ORG_OWNER`, `FINANCE`); `control.write` row to name `production_schedule` and `daily_production_limit` |
| 21 | 16:558 | Ops summary columns | 04 §3.6 `amw_platform_ops_summary()`: add pending approvals count, open breaker count, worker counts by `worker_status`, org label and `org_status`, oldest queue age per org (aggregates only) |
| 22 | 16:559 | `org_controls` value schemas | Value schema per key for `agent_enabled.<agent_id>`, `production_schedule`, `daily_production_limit`, `publishing_enabled`, `emergency_stop` in 04 §5.1 and `amw_core.config` |
| 23 | 16:560 | Audit names | 08 §9.2: `delivery.bundle_downloaded`, `audit.exported`, `budget.changed`, `ops.resumed`; for the 3C web path `editorial.contribution.added` and a human-score import event |
| 24 | 16:292, 16:453 | Revenue storage | Table `revenue_entries` (17 §8.4 is a Wave B-2 draft not merged yet; file with it) |
| 25 | 20:542 | Support grants | Table `support_grants` (TENANT, Tier 1): `granted_by`, `grantee_user_id`, `scope_note`, `starts_at`, `expires_at`, `revoked_at`; events `support.grant.created/used/revoked` |
| 26 | 20:543 | Client channel connect guard | Trigger/CHECK: for `CLIENT`/`AGENCY` orgs, `channels.status = 'CONNECTED'` requires the project's `oauth_verification_status = PASSED` and `api_audit_status = PASSED` (04 §5.1, §5.19) |
| 27 | 20:544 | Org policy keys | `org_controls` keys `mfa_required` (Tier 1), `session_policy` (Tier 3) |
| 28 | 20:545 | Onboarding progress | Table `org_onboarding_steps` (TENANT, Tier 2) or an `org_controls` key |
| 29 | 20:546 | Permission keys | 08 §5.2: `compliance.rulepack.write`, `branding.write`, `billing.read`, `billing.manage`, `sso.manage`, `api_key.manage`, `webhook.manage`, `support.grant`, `channel.connect` |
| 30 | 20:547 | Audit names | 08 §9.2: `tenant.created`, `membership.role_changed`, `channel.connected/disconnected/reauth_required`, `licence.client_use_recorded`, `voice_consent.verified/withdrawn`, `compliance.tenant_rule.changed`, `tier.gate_opened`, `subscription.suspended` |
| 31 | 20:548 | Domain purpose | `org_domains.purpose` (`SSO` / `WHITE_LABEL`) (04 §5.26) |
| 32 | 20:551 | Referenced, owned elsewhere | org IP allow-list storage (08 §14 item 8); `plans.limits` keys and the `CREDITS` meter (21 §10) |
| 33 | 22:337 | DPA / notice acceptance | Tables `dpa_acceptances`, `notice_acceptances` (TENANT): accepted version and date per org / user |
| 34 | 22:338 | Breach record | Table `breach_incidents` (incident ID, time aware, classes, counts, notification records) |
| 35 | 22:339 | Break-glass | Permission key `data.break_glass` (reason-bound, time-limited) and its audit event (may be merged with request 25) |
| 36 | 22:340 | Retention config and legal hold | `retention.*` config keys per data class; `legal_hold` flag on orgs / jobs / data requests |
| 37 | 25:139, 25:153, 25:202 | Rule-ID prefixes | GLOSSARY §1: `ADV` (advertising pack) and sector prefixes `ADH`, `ADF`, `ADN`, `ADE`, `ADR`, `ADA` |
| 38 | 25:179 | Promotion flag | Required boolean on the job input of non-ad production types marking promotion of the client's goods or services (24 / 03 job input) |
| 39 | 25:327 | Ad licence / release record | Storage shape for the per-ad licence and release record (25 §10) |
| 40 | 11:476 (as built) | `Clock` Protocol | `SOURCE_LAYOUT.md` lists no `amw_core.interfaces.clock`; add it (exists as built) |

## B. Enum values / terms used by the drafts that are missing in GLOSSARY_AND_IDS.md

| Value | Where | Note |
|---|---|---|
| `approval_kind` `NATIVE_SPEAKER_QC` | 14:106, 14:296 | request 13 |
| `backup_kind` (`DB`,`BLOB`,`CONFIG`,`AUDIT_HEADS`,`RESTORE_TEST`), `backup_run_status` (`RUNNING`,`SUCCEEDED`,`FAILED`) | 12:459 | request 10 |
| `usage_meter` `CREDITS` | 20:336 | gap noted in 20 and 21 §10 |
| `org_domains.purpose` `SSO` / `WHITE_LABEL` | 20:548 | request 31 |
| `deployment.profile` values | 10:357 | request 5 (config key) |
| `UNVERIFIED` (status of a backup set) | 12:113, 12:323 | derived from `backup_runs.verified_at`; not an enum unless request 10 is filed with it |
| Admission reasons `MARKET_HOURS`, `OUTSIDE_WINDOW`, `AGENT_DISABLED`, `ORG_EMERGENCY_STOP`, `DAILY_PRODUCTION_LIMIT` | 16:194, 16:309-313 | payload-local reasons of the Agent 01 blueprint (not on main); add an `admission_reason` enum or keep payload-local |
| Reason codes `NOT_METHOD_TOPIC`, `RELEASE_MISSING`, `RELEASE_NOT_APPROVED` | 11:200 | payload-local to blueprints 04 / 08 |

## C. RESEARCH_LOG entries still needed (facts without an ID in these docs)

- 22:43-47: DPDP Rule texts used (Rules 3, 6, 7, 15; the 72 h report) are read from the Gazette PDF of IN-07 but only milestones are logged; the document marks them REQUIRES REVIEW and says the entry is to be added.
- 12, 06, 10: no external fact without an ID found; facts without a source are marked REQUIRES REVIEW (Phase 1) in the text.
