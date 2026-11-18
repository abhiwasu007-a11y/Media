# Unfiled contract requests from the B-2 ADR and business drafts (lane B2-1)

Status: **filed and decided** in `CONTRACT_CHANGE_REQUESTS.md` §4.7 (integrator pass 5, 2026-11-18): rows B1-1…B1-20 in table order → CCR-135…167 (mapping table there); kept as the lane's input record. Lane B2-1 may not edit `CONTRACT_CHANGE_REQUESTS.md` or a Wave A contract; the integrator files, decides or rejects each line. Line numbers are in the files of this branch. Format: `file:line | what | proposed text`.

Looked up in the register: none of the names below exists in 03, 04, 07, 24, 27 or GLOSSARY on main. The old markers "pending CCR-3A-n" do not occur in these ten files (they occur in the blueprints and shared docs of other lanes; CCR-003, 006, 017 and 043 applied them).

Also open for the integrator: these files cite documents that are still unmerged B-2 drafts (05, 14, 16, 20, 22). References such as "14 §3.10" or "16 §2" are to those drafts.

| file:line | what | proposed text |
|---|---|---|
| adr/ADR-003_auth.md:83 | credential storage table | New GLOBAL (RLS self) table `user_credentials`, accessible only to role `amw_auth`: `user_id` FK, `password_hash`, `hash_params`, `mfa_secret_ref`, `updated_at`; section 04 §5.1 and the allow-list in §3 |
| adr/ADR-003_auth.md:83 | session token hash | Column `user_sessions.token_hash bytea NOT NULL UNIQUE` (SHA-256 of the opaque cookie token) |
| adr/ADR-003_auth.md:83 | per-org MFA enforcement | `org_controls` key `mfa_required` (boolean, default false) |
| adr/ADR-003_auth.md:88 | session policy and IP allow-list storage | Home for session lifetime and IP allow-list per org (08 §7.2, §7.4); table or `org_controls` keys |
| adr/ADR-006_monitoring.md:42 | S5 resource samples | Table or time series for S5 samples with retention; until filed, samples are ephemeral and only threshold events go to `audit_log` |
| adr/ADR-010_payment_gateway.md:56 | idempotency scope | `idempotency_keys.scope` value `billing.webhook` (key = gateway event ID) and a `billing.charge` family for refunds (04 §5.9, GLOSSARY) |
| adr/ADR-010_payment_gateway.md:58 | reconciliation job | System job type `billing.reconcile_invoices` (scheduled, idempotent) in 24 / GLOSSARY |
| adr/ADR-010_payment_gateway.md:64 | credit note and buyer tax details | Storage shape for credit notes (own number, links to the invoice) and for buyer GST details in 04 §5.25 |
| adr/ADR-010_payment_gateway.md:74,77 | dunning and gateway-route config | Config keys for reminder cadence, grace period and billing route per org; **no default value** (owner and legal decision) |
| adr/ADR-010_payment_gateway.md:79 and adr 21_PRICING:130 | `pricing.gateway_fee_rate` | Config key, unset until the owner has a written fee quote |
| adr/ADR-011_n8n.md:45 | S12 outbound webhook task | Task type `svc_s12.webhook_deliver` (tables `webhooks`, `webhook_deliveries` already exist in 04 §5.26) |
| 17_BUSINESS_PLAN.md:86,392 | niche score storage | Table `niche_scores` (org, cell, criteria values, weights version, evidence, confidence) |
| 17_BUSINESS_PLAN.md:86,393 | discovery task | Task type `agent_02.niche_score` |
| 17_BUSINESS_PLAN.md:265,395 | actual revenue records | Table `revenue_entries` (org, channel, publication nullable, stream, amount_minor, currency, period, label ACTUAL, source document ref) and enum `revenue_stream` |
| 17_BUSINESS_PLAN.md:59,83,300,396 | owner-set business thresholds and weights | Config namespace `business.*` (for example `business.discovery.min_confidence`); no value ships |
| 17_BUSINESS_PLAN.md:396 | unit-economics task | Task type `agent_15.unit_economics_report` |
| 21_PRICING_AND_PACKAGING.md:258 (REQ-21-1) | plan limits keys | Document `plans.limits` jsonb keys `credits_per_period`, `rollover_periods`, `overage_mode`, `channels`, `seats`, `credit_weights` in 04 §5.25 (04 line 1166 lists limits without these) |
| 21_PRICING_AND_PACKAGING.md:259 (REQ-21-2) | credits meter | Add `CREDITS` to `usage_meter` (GLOSSARY §6) or confirm credits are derived from `VIDEOS` x tier at invoice time |
| 21_PRICING_AND_PACKAGING.md:260 (REQ-21-3) | catalogue keys and config | Labels `length_band`, `quality_tier` (no change to presets or QC) and config keys `pricing.target_gross_margin`, `pricing.gateway_fee_rate` |
| 26_GROWTH_OPPORTUNITIES.md:42,170 | growth weights | Config keys `business.growth.weights.{demand,price,margin,reuse,compliance,sales}`; an unset weight blocks the ranking run |

## Not a CCR, handled in the drafts
- `hi-Latn` (19:39): a valid BCP 47 tag; GLOSSARY §6 lists tags only as examples. No request.
- ADR-003 and ADR-004 3A text: no web login, no OAuth, no dashboard in 3A (D1); owner decisions come from chat through the operator (D5, CCR-010, CCR-100). The drafts now say so; nothing to file.
- RESEARCH_LOG entries (not contracts): UNLOGGED-AUTH-01 to -12 (ADR-003), UNLOGGED-PG-01 to -08 (ADR-010), UNLOGGED-BIZ-01 to -03 (17), UNLOGGED-BM-01 to -05 (19), ADR-002 E1 and E2, ADR-004 E1 to E10, ADR-011 section 1.1 (n8n licence and queue-mode pages). Each needs a log ID with official URL and date before its ADR can be Accepted.
