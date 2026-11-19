# 21 — PRICING AND PACKAGING (client plans; every price is a PROPOSAL)

> **Integrator status (lane B2-1, 2026-11-18).** B-2 draft aligned with main: no upload and no Google OAuth in 3A (D1); the owner works from chat and has no CLI (D5/R14; decisions are recorded by the operator as `OWNER_CHAT_OPERATOR` evidence with a review code, CCR-010/CCR-100); the licensed music source is an open owner decision (D6); the repository is becoming private (D7). Facts without a `RESEARCH_LOG.md` ID carry the label `UNLOGGED` and are **not citable**: each is `REQUIRES REVIEW (Phase 1): log entry (official URL + date)`. Names that no Wave A contract defines carry their CCR number and status (filed and decided in CONTRACT_CHANGE_REQUESTS.md §4.7 (integrator pass 5)); this file changes no contract.

| Field | Value |
|---|---|
| Document status | DRAFT (documentation phase). Software status: **Planned** (no code). |
| Binding source | `MASTER_DIRECTIVE.md` §1B.7 (pricing and packaging), §1B.6 (expansion path), §1C.9 (billing and metering), §1C.15 (tier gates). Owner decisions D1, D2 in `IMPLEMENTATION_PROGRESS.md`. |
| Contracts used (not redefined) | `GLOSSARY_AND_IDS.md` (money = integer minor units + `currency`; `plan_status`, `subscription_status`, `invoice_status`, `usage_meter`; FIN-R1..R13), `04_DATABASE_ARCHITECTURE.md` (`plans`, `subscriptions`, `usage_events`, `invoices`, `cost_ledger`, `budgets`), `24_PRODUCTION_TYPES.md` (§3.2 task types, §4 presets, §5 QC profiles, §7 `default_price` rows that point here), `09_COST_AND_BUDGET.md` (§9 cost formula, §12 cost report), `00b_TECHNICAL_FEASIBILITY.md` (§3). |
| Read for scope | `17_BUSINESS_PLAN.md` (§9.1 cost per video, §11 tier gates, §13.2 client legal items). |
| Referred to by name only | `20_MULTI_TENANCY_AND_ENTERPRISE.md`, `22_DATA_PROTECTION.md`, `25_ADVERTISING_COMPLIANCE.md`, the payment-gateway ADR (`subscriptions` row references ADR-010), Agent 15 blueprint. |
| Date of all readings | **2026-11-18** |
| Prices in this document | **None of ours.** Every price of ours is "PROPOSAL - REQUIRES REVIEW (Phase 1): needs measured cost per video and owner approval". Competitor figures are readings, not recommendations. |

## 0. How to read the numbers

| Label | Meaning in this document |
|---|---|
| **MEASURED** | read by us from the vendor's own public page on 2026-11-18 (curl + text extraction), or from our own ledger |
| **SECONDARY** | third-party source (guide, blog, directory): not official, not verified against the provider |
| **ESTIMATE** | arithmetic on verified numbers × a named assumption |
| **PROJECTION** | scenario output; never an actual result |
| **NOT CONFIRMED** | could not be read or verified; no number is stated |

Rules: no price of ours is stated; no competitor revenue, subscriber count or conversion rate is stated; vendor prices are USD as published (not converted: FX source and refresh rule are **REQUIRES REVIEW (Phase 1)**, same item as `09_COST_AND_BUDGET.md` §7). Some pages show promotional first-month or annual-billing prices; plan name, billing basis and promotion are recorded with each reading. Vendor prices change without notice: a reading older than 30 days is re-read before it is used for a decision (research-log re-verification rule).

## 1. Purpose and scope

- Define what we sell to paying clients and the method that turns **measured cost per video** into a price. No price is set until two inputs exist: (a) measured cost per video from the 3A skeleton and the 3B golden samples (`09` §9, §12), and (b) the owner's approval (rule 8).
- The owner's own channel is not priced (`24` §7.1 `default_price`: n/a). Client pricing starts at **Tier 1** (first managed-service client) and is billed by the platform at **Tier 2** (`17` §11).
- Build scope: this document is **3C / Tier 1-2**. In 3A and 3B nothing is billed; 3A only produces the inputs (cost per stage, `09` §12). Plan rows exist as `PROPOSAL` status only (`plan_status` = `PROPOSAL`).
- Non-goals: legal terms (MSA, DPA: `17` §13.2, ⚖ the owner's lawyer), GST treatment (⚖ owner's CA; A6-b), payment-gateway choice (separate ADR).

## 2. Research method (repeatable; re-run before approval)

| Step | How | Output |
|---|---|---|
| R1 Select | Two families: **(a) done-for-you human or hybrid services** (editing subscriptions, channel-management agencies, creative subscriptions) and **(b) AI video platforms** (credit-based subscriptions). Add a competitor only with a stated reason (same buyer, same deliverable, or same pricing model). | competitor list |
| R2 Read official page | `curl -sL` with a generic browser user-agent on the vendor's pricing page; convert HTML to text; record plan name, price, billing basis (monthly / annual / quarterly), unit of allowance (credits, minutes, videos), limits, rollover, overage/top-up, minimum term. WebFetch does not work in this environment. | MEASURED row |
| R3 Page blocked or price rendered by script | Do not infer. Record NOT CONFIRMED. A search snippet or guide is recorded only as SECONDARY with its URL. | NOT CONFIRMED / SECONDARY row |
| R4 Normalise | Compare per finished video of a stated length only where the unit is the same. Credits are never compared across vendors unless the vendor states a credits-to-output mapping on the page. | comparison |
| R5 Compare scope | For every reading note what is **not** included versus our deliverable (`3A_SLICE_SPEC.md`: script, fact-check, voice, visuals, edit, thumbnails, SRT, QC report with 100-point score, cost per stage). | scope gap |
| R6 Log | New facts go into `RESEARCH_LOG.md` (PRC-01 … PRC-14 are logged on main; Appendix B). | log entries |
| R7 Refresh | Re-run R2-R6 before the owner approves any price and every 90 days afterwards (**REQUIRES REVIEW (Phase 1)**: owner may set another cadence). | dated readings |

## 3. Readings (2026-11-18)

### 3.1 Done-for-you / human-in-the-loop services

| Vendor | Plan / unit | Price (USD, as published) | What the page says | Label / source |
|---|---|---|---|---|
| Vidpros | Starter | $1,000 / month | 20-40 short-form OR 5-10 long-form (or mix); unlimited revisions (each round counts toward monthly output); stock video and music, AI captions; cancel anytime | MEASURED, [vidpros.com/pricing](https://www.vidpros.com/pricing) (PRC-01) |
| Vidpros | Growth | $2,000 / month | 40-80 short-form OR 10-20 long-form; dedicated editor and project manager | MEASURED, same page |
| Vidpros | Scale | $4,000 / month | 80-160 short-form OR 20-40 long-form; same-day delivery | MEASURED, same page |
| Vidpros | definitions | Short-form = up to 60 s. Long-form = up to 15 min, edited from up to 60 min of raw footage. Output resets monthly, no rollover. Trial week $100. | | MEASURED, same page |
| Vidchops | Weekly | $495 / month | 4 credits; 1 credit = 1 long-form edit (page: 5 to 60 min) or 4 short-form; 3 revisions per video; subtitles extra ($95 / month); FAQ: no voice-overs, no 2D/3D animation | MEASURED, [vidchops.com/pricing](https://www.vidchops.com/pricing) (PRC-02) |
| Vidchops | Pro | $995 / month | 8 credits; unlimited revisions per video; dedicated account manager | MEASURED, same page |
| Tasty Edits | per video (horizontal) | $327 (1 video); $305 per video (4 videos, 7% discount); thumbnail add-on $43 | edit price list | MEASURED, [tastyedits.com/pricing](https://www.tastyedits.com/pricing/) (PRC-03) |
| Tasty Edits | YouTube Channel Management | Starter (operations and logistics) $1,490 / month paid quarterly, $1,266 / month paid yearly; Pro (strategy and growth) $2,370 / month paid quarterly | | MEASURED, same page |
| Superside | creative subscription | Flex: minimum $15,000 / month on an annual term plus $1,000 / month software fee; Dedicated: from $30,000 / month, 12-month term, same fee; Quick Start $20,000 | enterprise creative bench (not YouTube-specific) | MEASURED, [superside.com/pricing](https://www.superside.com/pricing) (PRC-04) |
| Full-service YouTube agencies (market range) | monthly retainer | "$3,000-$10,000+ / month" full-service; strategy-only $2,000-$5,000; packaging-only $500-$2,000; enterprise / multi-channel $10,000-$30,000+ | guide statement, not an agency's own page | **SECONDARY**, [outlierkit.com guide](https://outlierkit.com/resources/hire-youtube-agency/) (PRC-05) |
| Syllaby done-for-you | not readable | page returned HTTP 403 | | **NOT CONFIRMED** ([page](https://syllaby.io/done-for-you-page/)) (PRC-13) |
| Other full-service agencies (script + production + publishing) | not read | no official price page read | | **NOT CONFIRMED**; REQUIRES REVIEW (Phase 1): owner or lead names 3-5 agencies to read directly (A-P2) |

Scope gap versus our deliverable: the editing services take client footage or scripts; Vidchops states no voice-overs and no animation. None of the readings state research, fact-check, compliance gating, a QC score or a cost-per-stage report as part of the price. Our package covers more stages but serves a niche with blocking compliance checks, so price alone is not a like-for-like comparison.

### 3.2 AI video platforms

| Vendor | Plan | Price (USD, as published) | Allowance on the page | Label / source |
|---|---|---|---|---|
| Synthesia | Basic | $0 | 500 credits / month; watermark; Syren videos capped at 3 minutes | MEASURED, [synthesia.io/pricing](https://synthesia.io/pricing) (PRC-06) |
| Synthesia | Starter | $19 / month (first-month promo shown $9); $14 / month billed yearly ($168) | 1,250 credits / month (15,000 / year) | MEASURED, same page |
| Synthesia | Pro | $89 / month (first-month promo $49) | 6,000 credits / month; credit-pack steps shown (12,000 credits at $178) | MEASURED, same page |
| HeyGen | Free / Creator / Pro / Business | $0 / $29 / $49 / $149 per month | Free: 3 videos a month, up to 1 minute, watermarked. Credits: Creator 600, Pro 1,000, Business 1,500 (videos up to 60 min). Credits roll over one month | MEASURED, [heygen.com/pricing](https://heygen.com/pricing) (PRC-07) |
| InVideo | Starter / Plus / Max | $10 / $30 / $75 per seat per month billed annually (page shows $20 / $60 / $150 monthly basis) | 400 / 2,000 / 5,000 credits per seat per month; unused credits do not roll over | MEASURED, [invideo.io/pricing](https://invideo.io/pricing) (PRC-08) |
| Runway | Standard / Pro / Max | $12 / $28 / $76 per month billed annually ($15 / $35 / $95 monthly basis) | 625 / 2,250 / 9,500 credits per month; page maps 625 credits to 52 s of its newest video model; top-up credits; Max rolls over 1 month | MEASURED, [runwayml.com/pricing](https://runwayml.com/pricing) (PRC-09) |
| Descript | Hobbyist / Creator / Business | $16 / $24 / $50 per person per month annual ($24 / $35 / $65 monthly basis) | 10 / 30 / 40 media hours and 400 / 800 / 1,500 AI credits per month; top-ups | MEASURED, [descript.com/pricing](https://www.descript.com/pricing) (PRC-10) |
| OpusClip | Starter / Pro | Starter $15 / month (monthly only); Pro $14.5 / month billed annually ($174) | Starter 150 credits / month; Pro 3,600 credits over 12 months, unused credits roll over 2 months | MEASURED, [opus.pro/pricing](https://www.opus.pro/pricing) (PRC-11) |
| Fliki | Standard / Premium | **price not present in the page text** | 180 / 600 credits per month; videos up to 15 / 40 min | allowance MEASURED, price **NOT CONFIRMED**, [fliki.ai/pricing](https://fliki.ai/pricing) (PRC-12) |
| Pictory | not readable | page returned HTTP 403 | | **NOT CONFIRMED** (PRC-13) |

### 3.3 Structural observations (facts from the readings only; no number recommended)

| # | Observation | Basis |
|---|---|---|
| O1 | Editing services sell a **monthly output block** with a stated unit (long-form up to 15 min; short-form up to 60 s), capped or unlimited revisions, no rollover (Vidpros) or a credit unit (Vidchops: 1 credit = 1 long-form or 4 shorts). | §3.1 |
| O2 | Per-video list prices exist beside monthly blocks (Tasty Edits). | §3.1 |
| O3 | AI platforms sell **credits** with a monthly allowance, annual-billing discount, top-ups and on some plans a 1-2 month rollover; a credit-to-output mapping is stated only for some models. | §3.2 |
| O4 | Free or low tiers carry watermarks and length caps (HeyGen 1 minute, Synthesia 3 minutes); paid tiers lift them. | §3.2 |
| O5 | Enterprise creative contracts carry a monthly minimum, an annual or 12-month term and a separate software fee (Superside). | §3.1 |
| O6 | None of the services read is a Marathi finance-education production line with compliance gates; no like-for-like price exists. | §3.1-3.2 |

## 4. Plan structure (PROPOSAL; three families)

Pricing is held in the `plans` catalogue (`limits jsonb`, `price_minor`, `currency`, `status` = `PROPOSAL` until approved). Plan keys below are working names; final keys are set on owner approval (REQUIRES REVIEW (Phase 1)).

| Plan family | Buyer | Unit sold | Billing | Includes | Scope / tier |
|---|---|---|---|---|---|
| **P1 Managed service per channel per month** | a client with a channel who wants a done-for-you line | one channel; a monthly **video allowance** expressed in credits by length and quality tier (§6); human review and client approvals | monthly (annual prepay is a config switch) | production types of `24` §7 enabled for the client (initially `CHANNEL_LONG_FORM`, `SHORTS`); QC report and cost-per-stage report per video; client approval before any publish; revision loops up to the production-type limit (`24` §7.1 `max_revision_loops` 3) | 3C, **Tier 1** |
| **P2 Credits per finished video** | self-serve client or occasional buyer | a **credit** pack or monthly allowance; each finished video consumes credits by length band × quality tier (§6) | prepaid packs and/or monthly allowance with a rollover rule (§8) | same deliverables as P1 per consumed credit; no dedicated review time promised | 3C, **Tier 2** |
| **P3 Enterprise contract** | several channels, brand/compliance needs, SLA | committed monthly minimum, pooled allowances across channels, tenant rule packs, SSO/SCIM, API, formal SLA (Tier 3 items only when a contract requires them, `17` §11) | annual contract, invoiced | P1/P2 allowances pooled + Tier 3 items as separate line items | **Tier 3** (later) |

Not a plan: any add-on that removes or weakens a platform-level gate. The general YouTube policy pack and the finance pack (FIN-R1..R13) are always on and are not sold as options; tenants may add rules, never remove them (`MASTER_DIRECTIVE.md` §1C.7).

Other production types (`AD_SPOT`, `EXPLAINER_CORPORATE_TRAINING`, `ECOMMERCE_PRODUCT`, `DUBBING_LOCALISATION`) carry `default_price` "REQUIRES REVIEW (21)" in `24`; they receive credit weights only when a paying client needs them (`17` §11). Ads also follow `25_ADVERTISING_COMPLIANCE.md`.

## 5. Price formula (the only way a price is set)

```
direct_cost(tier)    = LLM + TTS + footage + music + ai_broll + render/infra_share   (09 §9, 00b §3.1; MEASURED from cost_ledger after 3A)
labour_cost(tier)    = review_minutes(tier) × review_rate                            (09 reports review time separately; here it is priced)
fixed_alloc          = licence / subscription allocation per video                   (stock Business licence, music, voice; 09 §9)
rework_allowance     = measured share of videos needing a revision loop or regeneration

cost_per_video(tier) = direct_cost + labour_cost + fixed_alloc + rework_allowance

price_ex_tax(tier)   = cost_per_video(tier) / (1 − target_gross_margin − gateway_fee_rate)
price_invoiced       = price_ex_tax + GST       (GST goes on the invoice as invoices.tax_minor; never inside the margin)
```

The directive form is price = cost / (1 − margin); the gateway fee is carried as a separate config variable so that the stated margin stays the margin after payment fees. With `gateway_fee_rate` = 0 the formula is exactly the directive's.

| Variable | Source | Status |
|---|---|---|
| `direct_cost(tier)` | measured `cost_ledger` rows per job, aggregated by tier (`09` §9, §12). Today only TTS for a 10-minute Marathi narration is computable: about $0.64 to $0.80 per take (ESTIMATE, PR-04). No total per-video cost exists. | **REQUIRES REVIEW (Phase 1): measured cost per video from 3A/3B** |
| `labour_cost` | `review_minutes` from the pilot (`09` §9: ESTIMATE until the pilot); `review_rate` = cost per hour of the reviewer | **REQUIRES REVIEW (Phase 1): pilot minutes; A6-c weekly review time; reviewer rate (owner)** |
| `fixed_alloc` | stock footage is $21-$30 / month on annual billing for one channel but Small Business **excludes agencies and production companies** and Business is by quote (PR-06); the voice provider's agency/client clause is NOT CONFIRMED (PR-05) | **REQUIRES REVIEW (Phase 1): Business/agency licences for stock, music, voice, AI B-roll; quoted prices enter here** |
| `rework_allowance` | retry and revision counts from the ledger and `07` | **REQUIRES REVIEW (Phase 1): measure in 3B** |
| `target_gross_margin` | **config variable** `pricing.target_gross_margin` (CCR-165, needs owner Q-O21), per plan family; no default value is proposed | **REQUIRES REVIEW (Phase 1): owner sets** |
| `gateway_fee_rate` | **config variable** `pricing.gateway_fee_rate` (CCR-165, needs owner Q-O21) | **REQUIRES REVIEW (Phase 1): payment-gateway ADR** |
| FX | USD vendor prices to INR | **REQUIRES REVIEW (Phase 1): FX source and refresh rule** |

Rules:
1. The margin is configuration, never hard-coded. A change affects quotes from that moment, never an issued invoice (invoices are records, not recomputed).
2. Money is computed in integer minor units; per-call costs stay in micros until aggregation; round-half-up only at the final step (GLOSSARY money rule).
3. A tier whose cost has a missing term is **not quotable**: its plan stays `PROPOSAL` and no price is shown to a client. No provisional number is displayed.
4. Re-price trigger: when the measured cost per video of a tier moves beyond a configured percentage over a configured window (**REQUIRES REVIEW (Phase 1): window and percentage**), Agent 15 raises a review item for the owner. Prices are never changed automatically (rule 8).
5. Margin multiplier reference (arithmetic only, not a recommendation; gateway fee excluded): price = cost × 1/(1−m). m = 50 % gives 2.00×; 60 % gives 2.50×; 70 % gives 3.33×; 80 % gives 5.00×.
6. Approval: the owner approves each plan row; only then `plans.status` moves `PROPOSAL` → `ACTIVE` and `price_minor` is filled.

## 6. Credits per finished video (P2, and the allowance unit inside P1)

A credit is an internal unit of **cost-weighted output**, not a currency. A finished video consumes credits by **length band** and **quality tier**; the weight is derived from measured cost so every tier carries the same margin.

```
credit_weight(length_band, quality_tier) = cost_per_video(length_band, quality_tier) / cost_per_video(base)
base             = the cheapest sellable combination (owner decides after 3B)
price_per_credit = cost_per_video(base) / (1 − target_gross_margin − gateway_fee_rate)
```

| Dimension | Values (PROPOSAL; catalogue keys CCR-165, Q-O21) | Anchored to |
|---|---|---|
| Length band | short-form (`SHORTS`); standard long-form; extended long-form. Boundaries: **REQUIRES REVIEW (Phase 1): `19_NICHE_BENCHMARKS.md` and the measured cost curve** (Vidpros uses up to 60 s / up to 15 min; Vidchops 5-60 min: SECONDARY context only) | `24` §7.1, §7.2 `duration_targets_ms` |
| Quality tier | **Standard**: 1080p master, SRT, thumbnail set, QC at the publish threshold. **Premium**: adds 1440p where render budget allows, more thumbnail variants or extra languages. The 100-point score, the publish threshold (≥ 85) and every compliance gate are **identical in all tiers**; a tier never lowers a gate | `24` §4 presets `yt_master_1080p`, `yt_master_1440p`, `srt_per_language`, `thumbnail_set`; `18_PRODUCTION_QUALITY_STANDARD.md` |
| Add-ons | 9:16 cut (`shorts_9x16`; spec REQUIRES REVIEW), extra language (`metadata_per_language`; dubbing is a separate production type), archive master (`client_master_mezzanine`) | `24` §4 |

Rules: a credit is consumed when the job reaches the state that the platform defines as delivered to the client (**REQUIRES REVIEW (Phase 1): exact state from the `03` state machine**), never at start; a job that ends failed, cancelled, or rejected by a platform gate without client fault releases its reservation (reserve-then-settle as in `09` §3.4). Rework caused by a client brief change is settled per §8.

## 7. Usage limits per plan (PROPOSAL; held in `plans.limits`)

`plans.limits` already carries concurrency, daily videos, render minutes, spend caps and audit retention (`04` §5.25). Limits are enforced **in the queue** (`MASTER_DIRECTIVE.md` §1C.9), not only on the invoice.

| Limit | Meaning | Source of value | P1 | P2 | P3 |
|---|---|---|---|---|---|
| Videos / credits per period | included allowance | owner, from measured cost (§5) | per channel | per pack | contract |
| Concurrency | jobs in flight per tenant | existing key; from measured render capacity (`05_RESOURCE_MANAGEMENT.md`) | yes | yes | yes |
| Daily videos | cap per day | existing key | yes | yes | yes |
| Render minutes | per period; render only in the night window, never in market hours | existing key; meter `RENDER_MINUTES` | yes | yes | yes |
| AI spend cap | upper bound on paid provider spend per tenant per period; hard stop on breach as in `09` §4 | existing key; meter `AI_SPEND` | yes | yes | yes |
| Revisions | loops per video | ceiling `24` §7.1 `max_revision_loops` 3 | included | included | contract |
| Channels | channels per tenant | **(CCR-165, Q-O21: new `limits` key)** | 1 per unit | n/a | contract |
| Approver seats | named client users | **(CCR-165, Q-O21: new `limits` key)** | few | few | contract |
| Storage / retention | stored assets, audit retention | existing keys; meter `STORAGE_BYTES` | yes | yes | contract |
| Languages | per video | MVP single language (`24` §7.1) | 1 | 1 | contract |

All numeric values: **PROPOSAL - REQUIRES REVIEW (Phase 1): needs measured capacity and owner approval.** Night-window and admission rules (`06_NIGHT_SCHEDULING.md`) apply to every tenant: a plan can buy a larger allowance, never a render inside market hours or beyond the shared-server caps.

## 8. Overage rules (PROPOSAL)

| Situation | Rule |
|---|---|
| Allowance exhausted | Admission of new jobs stops; in-flight jobs finish. The client chooses a top-up pack, an upgrade (effective at next admission) or waits for the next period. **No automatic purchase and no silent overage billing.** |
| AI-spend cap reached | Hard stop of paid provider calls for that tenant, visible to client and owner; same behaviour as a per-video budget breach (`09` §4). |
| Top-up | Fixed packs at the §6 `price_per_credit`, optionally with a volume step set by the owner; invoiced or prepaid via the gateway. |
| Rollover | Unused allowance **expires at period end** by default; a rollover window is a plan config value. Readings differ: none (Vidpros, InVideo), one month (HeyGen, Runway Max), two months (OpusClip). **REQUIRES REVIEW (Phase 1): owner decides.** |
| Client rework beyond the revision ceiling | Each extra round consumes a stated fraction of the video's credit weight (**REQUIRES REVIEW (Phase 1): fraction from measured rework cost**). |
| Platform-side failure or gate rejection not caused by the client | No credit consumed; re-run inside the tenant budget or close the job (`07`: no infinite retries, no silently dropped jobs). |
| Content refused on compliance grounds (e.g. a finance script with a call or return claim) | The refusal is explained in the report; credits are consumed only for work product delivered; a platform gate cannot be bought off. |
| Late payment | `subscriptions.status` `PAST_DUE` → `SUSPENDED`; read access to files kept for a grace period (**REQUIRES REVIEW (Phase 1): `22_DATA_PROTECTION.md` retention and grace**). |
| Enterprise overage | Contracted rate card or pre-agreed top-up; never open-ended. |

## 9. Constraints that shape packaging

| # | Constraint | Effect | Source |
|---|---|---|---|
| C1 | Stock Small Business licence excludes agencies and production companies; Business by quote | managed service cannot use the personal plan; the quoted price is a `fixed_alloc` term; P1/P2 stay unpriced until quoted | PR-06 |
| C2 | Voice provider's agency/client use NOT CONFIRMED; voice cloning needs the voice owner's verifiable consent | client voice work blocked until confirmed; no clone sold without a consent record | PR-05; `MASTER_DIRECTIVE.md` §1C.8 |
| C3 | Every licensed asset is recorded per tenant (licence ledger) | delivery bundle carries the licence rows per video | `MASTER_DIRECTIVE.md` §1C.8 |
| C4 | Human editorial contribution and approval on every `FINAL_VIDEO`; channel-level inauthentic-content enforcement | price includes a review step; a "fully automatic, no review" plan is **not offered** | `24` §3.4, §7.1; YT-09 |
| C5 | Client channels belong to the client; Google OAuth verification and API compliance audit must pass before any upload | plans sell production deliverables; publishing is Tier 1-gated; no upload in 3A | `17` §11; YT-11, YT-12; D1 |
| C6 | Finance clients: SEBI-aligned rules regardless of plan | finance packaging says "education only"; no calls, levels or return claims; no contracting around FIN-R1..R13 | `13` §5; GLOSSARY FIN-R1..R13 |
| C7 | GST on invoices; owner's GST status unknown | prices quoted ex-tax; `invoices.tax_minor`; ⚖ owner's CA | `17` §13.2 C4; A6-b |
| C8 | Tenant isolation is absolute; no tenant material trains or prompts work for another tenant | stated in plan text; no "shared learning" discount | `MASTER_DIRECTIVE.md` §0 rule 9 |

## 10. Metering and data mapping (design only)

| Need | Existing contract | Gap |
|---|---|---|
| Plan catalogue and limits | `plans` (`key`, `name`, `limits`, `price_minor`, `currency`, `status`) | `limits` keys for credits, rollover, overage mode, channels, seats, weights: **(CCR-165, Q-O21)** |
| Subscription | `subscriptions` | none |
| Usage | `usage_events` meters `VIDEOS`, `VIDEO_MINUTES`, `RENDER_MINUTES`, `AI_SPEND`, `STORAGE_BYTES`; source = S4 cost tracking | `CREDITS` meter **(CCR-165, Q-O21)**; alternative: derive credits from `VIDEOS` × tier at invoice time |
| Cost per video per tenant | `cost_ledger` | none |
| Invoices | `invoices` (`amount_minor`, `tax_minor`, `currency`, `status`, `idempotency_key`) | none |
| Per-video margin view (owner only; never shown to the client) | derived: price consumed vs `cost_per_video` | format in the Agent 15 blueprint |

## 11. MVP scope

| Item | Scope | Enterprise tier |
|---|---|---|
| Cost-per-stage inputs that feed this document | **3A** | Tier 0 |
| Three golden samples measure cost and review minutes per tier | **3B** | Tier 0 |
| Competitor and agency price re-read (§2) | 3B, before any client conversation | n/a |
| Plan rows as `PROPOSAL` (no price) | 3C | Tier 1 |
| P1 managed service for the first client, quoted by the owner from §5 | 3C | **Tier 1** |
| Metering, queue quotas, invoices with GST, gateway | 3C | **Tier 2** |
| P2 credit packs and top-ups | 3C (after P1 proven) | Tier 2 |
| P3 enterprise items (SSO/SCIM, API, SLA) | later; only when a contract requires them | **Tier 3** |

## 12. Approval procedure (before any price is shown to anyone)

1. 3B produced three golden samples with measured `cost_per_video` and review minutes (`09` §12 report).
2. Licence costs (C1, C2) quoted or confirmed; FX rule set.
3. Owner sets `pricing.target_gross_margin` and `review_rate`.
4. Competitor readings (§3) re-read (R7).
5. Each tier is computed with §5; the owner approves the rows; `plans.status` becomes `ACTIVE`.
6. Terms (MSA, DPA, ToS) and GST treatment reviewed by the owner's lawyer and CA (⚖) before the first invoice.

## 13. Open items (all REQUIRES REVIEW (Phase 1))

| # | Open item |
|---|---|
| 1 | Measured cost per video per tier (3A/3B) |
| 2 | Review minutes and reviewer rate |
| 3 | Business/agency licences: stock, music, voice (PR-05, PR-06), AI B-roll; music and AI B-roll prices (`09` §7) |
| 4 | Target gross margin per plan family; rollover; top-up volume steps |
| 5 | Length-band boundaries and Premium tier definition |
| 6 | Payment-gateway fee rate (gateway ADR) |
| 7 | FX source and refresh rule |
| 8 | Direct reading of 3-5 full-service YouTube agencies' own price pages (only SECONDARY ranges exist) |
| 9 | Fliki prices; Pictory and Syllaby pages (blocked or script-rendered) |
| 10 | Exact "delivered" state that consumes a credit (`03` state machine) |
| 11 | GST rate and registration treatment (⚖ CA) |

## 14. Contract change requests (filed as CCR-165, needs owner Q-O21; CONTRACT_CHANGE_REQUESTS.md §4.7 (integrator pass 5))

| # | Target | Need |
|---|---|---|
| REQ-21-1 | `04_DATABASE_ARCHITECTURE.md` §5.25 `plans.limits` | document the jsonb keys `credits_per_period`, `rollover_periods`, `overage_mode`, `channels`, `seats`, `credit_weights` |
| REQ-21-2 | `GLOSSARY_AND_IDS.md` `usage_meter` | add `CREDITS` (or confirm credits are derived from `VIDEOS` × tier) |
| REQ-21-3 | `GLOSSARY_AND_IDS.md` / `24_PRODUCTION_TYPES.md` | pricing catalogue keys `length_band` and `quality_tier` (labels only; no change to presets or QC profiles) and config keys `pricing.target_gross_margin`, `pricing.gateway_fee_rate` |

## Appendix A — Owner inputs needed

| # | Input | Why |
|---|---|---|
| A6-b | GST status | invoices; price ex-tax |
| A6-c | Weekly review time and reviewer cost per hour | `labour_cost`; capacity of P1 |
| A6-d | Budget ceiling (per video, pilot, monthly) | spend control; AI-spend cap per plan |
| A-P1 | Target gross margin per plan family | §5 |
| A-P2 | 3-5 agencies or competitors the owner wants benchmarked | §3.1 NOT CONFIRMED rows |
| A-P3 | First client profile (niche, language, monthly volume, channel owner) | P1 allowance and production types |
| A-P4 | Rollover and top-up policy; minimum term (monthly vs contract) | §8 |
| A-P5 | Annual prepay and trial offers (competitors show trial weeks and annual discounts) | §4 |
| B6 | Lawyer and CA for MSA, DPA, GST items | §12 |

## Appendix B — Sources and new facts (read 2026-11-18)

RESEARCH_LOG IDs cited: PR-04, PR-05, PR-06, YT-09, YT-11, YT-12.

The competitor and vendor price rows below are logged on main as PRC-01 … PRC-14 (RESEARCH_LOG, PR #7 backfill; same numbering). Prices are as published on 2026-11-18 and may be promotional or annual-billing as noted; the log entry is the citable source.

| ID | Finding | Source |
|---|---|---|
| PRC-01 | Vidpros: Starter $1,000 / month (20-40 short-form or 5-10 long-form), Growth $2,000 (40-80 / 10-20), Scale $4,000 (80-160 / 20-40); short-form up to 60 s, long-form up to 15 min; revisions count toward output; no rollover; $100 trial week | https://www.vidpros.com/pricing |
| PRC-02 | Vidchops: Weekly $495 / month (4 credits), Pro $995 (8); 1 credit = 1 long-form (5-60 min) or 4 short-form; subtitles $95 / month extra; no voice-overs or animation | https://www.vidchops.com/pricing |
| PRC-03 | Tasty Edits: horizontal video $327 (1) / $305 (4); thumbnail add-on $43; channel management Starter $1,490 / month quarterly ($1,266 yearly), Pro $2,370 quarterly | https://www.tastyedits.com/pricing/ |
| PRC-04 | Superside: minimum $15,000 / month on an annual term plus $1,000 / month software fee; Dedicated from $30,000 / month, 12-month term | https://www.superside.com/pricing |
| PRC-05 | SECONDARY: full-service YouTube agency $3,000-$10,000+ / month; strategy-only $2,000-$5,000; packaging-only $500-$2,000; enterprise $10,000-$30,000+ (guide, not verified) | https://outlierkit.com/resources/hire-youtube-agency/ |
| PRC-06 | Synthesia: Basic $0 (500 credits), Starter $19 / month ($14 yearly; 1,250 credits), Pro $89 (6,000 credits); first-month promos shown | https://synthesia.io/pricing |
| PRC-07 | HeyGen: Free (3 videos, 1 min), Creator $29 (600 credits), Pro $49 (1,000), Business $149 (1,500; videos up to 60 min); credits roll over one month | https://heygen.com/pricing |
| PRC-08 | InVideo: Starter / Plus / Max $10 / $30 / $75 per seat per month billed annually; 400 / 2,000 / 5,000 credits; no rollover | https://invideo.io/pricing |
| PRC-09 | Runway: Standard / Pro / Max $12 / $28 / $76 per month billed annually; 625 / 2,250 / 9,500 credits; top-ups | https://runwayml.com/pricing |
| PRC-10 | Descript: Hobbyist / Creator / Business $16 / $24 / $50 per person per month annual; 10 / 30 / 40 media hours | https://www.descript.com/pricing |
| PRC-11 | OpusClip: Starter $15 / month (150 credits); Pro $14.5 / month billed annually ($174; 3,600 credits per year; 2-month rollover) | https://www.opus.pro/pricing |
| PRC-12 | Fliki: 180 / 600 credits per month (Standard / Premium); price not in page text (NOT CONFIRMED) | https://fliki.ai/pricing |
| PRC-13 | Pictory pricing page and Syllaby done-for-you page returned HTTP 403 (NOT CONFIRMED) | https://pictory.ai/pricing ; https://syllaby.io/done-for-you-page/ |
| PRC-14 | Pattern across readings: AI platforms sell credits with monthly allowance, annual discount and top-ups; done-for-you editing services sell monthly output blocks | PRC-01 to PRC-11 |
