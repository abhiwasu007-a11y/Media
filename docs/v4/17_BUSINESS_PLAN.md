# 17 — BUSINESS PLAN (owner channel first, then clients)

> **Integrator status (lane B2-1, 2026-11-18).** B-2 draft aligned with main: no upload and no Google OAuth in 3A (D1); the owner works from chat and has no CLI (D5/R14; decisions are recorded by the operator as `OWNER_CHAT_OPERATOR` evidence with a review code, CCR-010/CCR-100); the licensed music source is an open owner decision (D6); the repository is becoming private (D7). Facts without a `RESEARCH_LOG.md` ID carry the label `UNLOGGED` and are **not citable**: each is `REQUIRES REVIEW (Phase 1): log entry (official URL + date)`. Names that no Wave A contract defines carry their CCR number and status (filed and decided in CONTRACT_CHANGE_REQUESTS.md §4.7 (integrator pass 5)); this file changes no contract.

| Field | Value |
|---|---|
| Document status | DRAFT (documentation phase). Software status: **Planned** (no code). |
| Binding source | `MASTER_DIRECTIVE.md` §1B (items 0-8) and §1C.15 (tier gates). Owner decisions D1 (build order 3A → 3B → 3C, spend controls, no upload/OAuth in 3A) and D2 (fast-track) in `IMPLEMENTATION_PROGRESS.md`. |
| Contracts used (not redefined) | `GLOSSARY_AND_IDS.md` (FIN-R1..R13, enums), `04_DATABASE_ARCHITECTURE.md` (`cost_ledger`, `budgets`, `analytics_snapshots`, `experiments`, `plans`, `usage_events`, `invoices`), `24_PRODUCTION_TYPES.md` (§3.2 task types, §6 cost model), `09_COST_AND_BUDGET.md` (§9 cost formula), `00b_TECHNICAL_FEASIBILITY.md` (§3), `13_COMPLIANCE_YOUTUBE_POLICY.md` (§5 finance pack), `19_NICHE_BENCHMARKS.md` (§6-§8), `KNOWLEDGE_LIBRARY_PLAN.md` (§5). |
| Referred to by name only | `20_MULTI_TENANCY_AND_ENTERPRISE.md`, `21_PRICING_AND_PACKAGING.md`, `22_DATA_PROTECTION.md`, `25_ADVERTISING_COMPLIANCE.md`, `26_GROWTH_OPPORTUNITIES.md`, Agent 02 / 03 / 14 / 15 blueprints. |
| Date of all readings | **2026-11-18** |
| Open inputs | A6 (SEBI registration status, GST status, weekly review time, budget ceiling, narration choice, benchmark channels). See Appendix A. |

## 0. How to read the numbers in this document

| Label | Meaning | Where it may come from |
|---|---|---|
| **MEASURED** | read from our own system (ledger, analytics API) or a public page on a stated date | `cost_ledger`, `analytics_snapshots` (YT-14), `19_NICHE_BENCHMARKS.md` readings |
| **ESTIMATE** | arithmetic on verified unit prices × an assumed quantity; the quantity is named | RESEARCH_LOG PR-/INF- rows × a stated quantity |
| **PROJECTION** | a scenario output of the financial model (§8); never shown as an actual result | §8 formulas with owner-set or measured inputs |
| **ACTUAL** | booked money (AdSense statement, course sales, sponsor invoice) | owner's records (§8.4) |
| **SECONDARY** | third-party source, not official | none used in this document |
| **NOT CONFIRMED** | no official or measured value exists | — |

Rules: no RPM, CPM, subscriber growth, conversion rate, course price or competitor revenue figure is stated here, because none is in `RESEARCH_LOG.md` or measured. Where a number is needed it appears as a **named variable** with its source rule. Vendor prices are USD as published; the conversion to INR uses a recorded FX rate (**REQUIRES REVIEW (Phase 1): FX source and refresh rule**, same item as `09_COST_AND_BUDGET.md` §7).

## 1. Objective (§1B.0)

MVP scope: 3C (dashboard), with the objective fixed now. Tier 0.

1. **Target, never a promise:** a sustainable business pursuing **at least ₹1,00,000 per month** of net revenue across channels and clients, then multi-lakh. No document, video, sales page or client proposal states it as an expected or guaranteed result.
2. **No early YPP assumption.** The plan does not count AdSense in any month before the channel is actually admitted to YPP (§7). Before that, revenue comes only from own products and allowed sponsorships (§6).
3. **The target as a formula** (used by the dashboard, §8.3):

```
net_revenue_month = Σ_channels ( adsense_net + course_margin + atp_margin + sponsorship_net + membership_net )
                  + Σ_clients  ( client_fees − client_direct_cost )
                  − platform_fixed_cost_month
target_gap_month  = 100000 INR − net_revenue_month        (shown only as a gap, never as a forecast)
```

4. Each term is ACTUAL when booked, PROJECTION when produced by a scenario (§8.2). The two are never summed into one figure.

## 2. Business Discovery Engine (§1B.1)

MVP scope: method 3B (used once by hand for the language decision of channel 1, per `19_NICHE_BENCHMARKS.md` §8), stored workflow 3C (Agents 02 + 15). Tier 0; Tier 1-3 reuse the same method per client niche.

### 2.1 Unit of scoring
A **cell** = niche × language × target country (for channel 1: trading education × {Marathi, bilingual/Hinglish, Hindi, English} × India; cell codes C1-C4 as in `19_NICHE_BENCHMARKS.md` §2.1).

### 2.2 Criteria, scale and formula
Each criterion is scored 0-5 **with evidence attached** (source URL + date, or a MEASURED reading). A score without evidence is stored as `NULL` and lowers the confidence, never filled by a guess.

```
weighted_score(cell) = Σ_i ( w_i × s_i ) / Σ_i ( w_i ) × 20          (0-100; criteria with s_i = NULL are excluded from both sums)
confidence(cell)     = Σ_i ( w_i  where s_i has evidence ) / Σ_i w_i  (0-1; shown next to the score)
```

| # | Criterion (§1B.1) | Weight key (configuration, CCR-166) | Evidence rule | Direction |
|---|---|---|---|---|
| 1 | Genuine owner/human expertise | `business.discovery.weights.expertise` | owner statement + course/library existence | higher = better |
| 2 | Search demand | `…weights.search_demand` | official/primary demand data per language: **REQUIRES REVIEW (Phase 1): demand source** (19 §8) | higher = better |
| 3 | Audience size | `…weights.audience_size` | MEASURED benchmark subscriber/view readings (19 §4) | higher = better |
| 4 | Competition | `…weights.competition` | number and size of confirmed benchmarks per cell (19 §3, §6) | less competition = higher score |
| 5 | Advertiser demand / RPM | `…weights.advertiser_rpm` | **NOT CONFIRMED** (no official RPM-by-language source; directive sentence is not a verified fact, 19 §6) | higher = better |
| 6 | Monetization paths | `…weights.monetization_paths` | §6 of this document (same for all channel-1 cells: no broker affiliate, FIN-R8) | more allowed paths = higher |
| 7 | Evergreen share | `…weights.evergreen` | evergreen anchors (19 §4.5) | higher = better |
| 8 | Production cost per video | `…weights.production_cost` | `09_COST_AND_BUDGET.md` §9; TTS language support PR-04 | lower cost = higher score |
| 9 | Retention potential | `…weights.retention` | NOT CONFIRMED before publishing; then YT-14 metrics | higher = better |
| 10 | Policy/legal risk | `…weights.policy_risk` | rule packs that apply (`13_COMPLIANCE_YOUTUBE_POLICY.md`), YT-09 | lower risk = higher score |
| 11 | International scalability | `…weights.international` | language reach; YT-15 multi-language audio | higher = better |

**Weights are configuration**, set by the owner (no default weight ships; an unset weight blocks the ranking run). The weight set used, its version and the evidence for every score are **published in the shortlist output** (§2.4).

### 2.3 Knock-out rules (applied before scoring; a knocked-out cell is listed with its reason, not ranked)
1. **Trending alone never qualifies a niche.** A trend signal (`agent_02.trend_scan`) is not a criterion and cannot raise a score.
2. Niches the directive lists as "avoid as owner channels" (§1E): medical advice, kids' content, news/politics, and any template-repetitive niche (YPP inauthentic-content risk, YT-09).
3. A finance cell that would need an AI presenter persona (YT-09, FIN-R11) or regulated-entity income (FIN-R8, IN-01) to be viable.
4. No genuine human expertise available (criterion 1 = 0): YPP requires human editorial contribution on every video (`13_COMPLIANCE_YOUTUBE_POLICY.md` YTG-R4).

### 2.4 Ranked shortlist method (output)
1. Score every non-knocked-out cell; sort by `weighted_score`, then by `confidence`.
2. A cell with `confidence` below the owner-set floor (`business.discovery.min_confidence`, CCR-166) is shown as **"insufficient evidence"** below the ranked list, never above a scored cell.
3. Output table per run: rank · cell · weighted score · confidence · each criterion's score + evidence link · knock-out reasons · weight-set version.
4. **The owner decides.** The engine never launches a channel; the decision is an approval record (S7).
5. Storage: no table exists in `04_DATABASE_ARCHITECTURE.md`; written against `niche_scores` (CCR-166) and task type `agent_02.niche_score` (CCR-136), both Proposed, deferred to 3C.

## 3. Business feasibility report (§1B.1a) — outline

MVP scope: 3C (channel 1 is already fixed by the owner; the report is written for channel 2 and for client niches). Tier 0-1.

| # | Section | Content rule |
|---|---|---|
| 1 | Recommended niches | top cells from §2.4 with weights and evidence |
| 2 | Target audience | who, level (beginner / intermediate), language; evidence or NOT CONFIRMED |
| 3 | Countries | target country per cell; international scalability evidence |
| 4 | Language strategy | primary language, secondary audio/subtitles (YT-15), glossary source |
| 5 | Competitor analysis | `19_NICHE_BENCHMARKS.md` method; form only, never content |
| 6 | Production cost per video | `09_COST_AND_BUDGET.md` §9 terms; ESTIMATE until MEASURED |
| 7 | Monetization strategy | §6 order, filtered by the niche's rule packs |
| 8 | Operating requirements | owner's weekly review minutes (A6), cadence, VPS night-window capacity (00b §2) |
| 9 | Risks | policy (YT-09), regulatory (rule packs), copyright (IN-08), platform (YT-10 thresholds), capacity |
| 10 | 90-day launch plan | template of §12 |
| 11 | Validation gate | the channel must pass §10 before another is launched |

## 4. First channel (§1B.2)

MVP scope: content rules are **3A** (Agent 16 gates enforce them in every 3A run); revenue and presenter rules are 3A design inputs, applied at publishing (3C). Tier 0.

### 4.1 Identity
Stock-market **trading education**, Marathi-first (Marathi vs bilingual/Hinglish scored in 3B per §2), funnelling to the owner's Marathi trading course and the ATP platform. Candidate second channel: farming/orchard → BagMitra, launched only after channel 1 passes the scale rules (§10).

### 4.2 Content rules (blocking; Agents 03/05/06/16; full text in `13_COMPLIANCE_YOUTUBE_POLICY.md` §5)
**Allowed (education only):** concepts, chart reading and price-action theory, options mechanics, risk and position-size principles, trading psychology, journaling, backtest methodology, and case studies on historical data older than the prescribed lag, rendered as real charts by code.

| Rule | Never | Business consequence |
|---|---|---|
| FIN-R1 | buy/sell/hold call | no "stock of the week" or pick-style formats |
| FIN-R2 | entry/exit/stop-loss/target level for a current instrument | no level-based thumbnails or titles |
| FIN-R3 | "what to do tomorrow / this week" market view | no daily/weekly market-outlook series |
| FIN-R4 | live-market session, live trade screen-share | no live streams in any MVP scope |
| FIN-R5 | paid group giving ongoing market guidance | memberships may never sell tips (§6) |
| FIN-R6 | performance, profit or return claim | no win-rate or "X% return" marketing, for the course too |
| FIN-R7 | profit testimonial | course promotion without student-profit testimonials |
| FIN-R8 | broker referral/affiliate or paid association with a SEBI-regulated entity while unregistered (IN-01) | removes the broker-affiliate income line entirely |
| FIN-R9 | price data newer than the lag (30 days, IN-02) | case-study charts use data older than the lag at publish time |
| FIN-R10 | missing disclaimer; a disclaimer never turns advice into education | wording from the owner's lawyer ⚖ |
| FIN-R11 | AI presenter persona (YT-09) | owner's voice or neutral narration only (§4.4) |
| FIN-R12 | "our method" outside a labelled, historical, owner-released topic | method topics only after per-topic release (Q26) |
| FIN-R13 | forward-looking statement on a named security, even on historical charts (IN-03) | case studies are framed "how it looked / why it worked or failed then" |

### 4.3 Revenue rules (first channel)
- **Not allowed:** broker referral/affiliate income; any paid association with SEBI-regulated entities while the owner is unregistered (FIN-R8, IN-01); paid promotion of stock/investment products (IN-05: ASCI says BFSI influencers in stocks/investments should be SEBI-registered and state the number).
- **Allowed:** own course (pure education, no ongoing tips), ATP as a tool, sponsorships from **non-regulated** businesses, AdSense after YPP.
- Own course/ATP promotion is self-promotion, labelled transparently (IN-05 implication). Whether the course funnel keeps the "solely investor education" exemption of IN-01 is a ⚖ item (`13_COMPLIANCE_YOUTUBE_POLICY.md` §14 item 8).
- If the owner registers with SEBI (A6), FIN-R8 changes only through a new rule version and a `POLICY_CHANGE` approval; this plan's revenue lines are then re-scored.

### 4.4 Presenter
The owner's own voice/narration (including a clone of the owner's own voice, which YouTube does not require to be disclosed, YT-07) or neutral narration. **No AI persona** (FIN-R11, YT-09). Every video carries the owner's editorial input and approval (YTG-R4). Choice pending (A6 narration choice); default: neutral narration until the owner chooses.

### 4.5 Answer-key cases (gate tests, not rule text; `13_COMPLIANCE_YOUTUBE_POLICY.md` §5.12)
| Case | Verdict | Rule |
|---|---|---|
| "How a bullish RSI divergence looked on a past NIFTY chart and why it failed/worked" (data older than the lag, past tense) | ALLOWED | passes R1-R3, R9, R13 |
| "NIFTY looks weak, sell the 24,000 call this week" | BLOCKED | R1, R2, R3 |
| "My strategy made X% last month" | BLOCKED | R6 |
| "Open an account with broker Y via this link" | BLOCKED | R8 |

Business note: these cases are 100 %-pass eval cases (27). A single compliance failure on a published video triggers the stop rule in §10.2.

## 5. Trading Knowledge Library role (§1B.2a)

MVP scope: 3A subset (only the books the golden topics need, `KNOWLEDGE_LIBRARY_PLAN.md` §5.2), full library 3C. Tier 0.

- **Role in the business:** the library is the primary research source for channel 1 and the guarantee of **genuine expertise** (criterion 1, §2.2) and **originality** (YT-09). It is a production asset, not content to be republished.
- **Collections (Q34 default):** `pd_books`, `owner_strategies_notes` (restricted; secondary index, a concept found there must still cite collection 1 or 3), `owner_books`. All are private; titles are never listed in this public repo.
- **Use rule (Q35/Q36 default):** concept-only teaching in original words for **all** collections, public-domain or not; short attributed quotes only with reviewer approval; books credited as further reading. Q37: the three 133-byte stub files are excluded until real files are provided.
- **Funnel link:** each video ends with a pointer to the matching course chapter (Q24: the course map in the owner's private data is the source). This pointer is the measurable funnel step in §8 (`course_clicks`).
- **"Our method":** separate restricted material; appears only per topic after the owner's release (FIN-R12, Q26).
- **Consistency:** one shared Marathi glossary for course and channel (K7 pending).

## 6. Revenue streams, in the order they usually become available (§1B.3)

MVP scope: none built in 3A/3B (files only, no upload). Tracking 3C. Tier 0.

| Order | Stream | Available when | Channel-1 compliance condition | Revenue share / fact |
|---|---|---|---|---|
| 1 | Digital products / own apps: course, ATP (later BagMitra on channel 2) | from the first published video | pure education, no ongoing tips (FIN-R5), no return claims or profit testimonials (FIN-R6/R7) | margin = owner's price − delivery cost: **owner input** |
| 2 | Affiliate | when a compliant programme exists | **broker/regulated-entity affiliate prohibited** (FIN-R8); non-financial tools only, labelled (IN-05) | per programme; NOT CONFIRMED |
| 3 | Sponsorships / brand deals | when audience size attracts sponsors | non-regulated businesses only; no stock/investment products (IN-05); ASCI labels | per deal; NOT CONFIRMED |
| 4 | AdSense | after YPP admission (§7) | inauthentic-content rules apply channel-wide (YT-09) | creator receives **55 %** of net watch-page ad revenue and **45 %** of the allocated Shorts revenue (UNLOGGED-BIZ-01) |
| 5 | Memberships | after YPP (fan-funding features) | perks may never be ongoing market guidance (FIN-R5) | **70 %** of net revenue from memberships, Super Chat, Super Stickers, Super Thanks (UNLOGGED-BIZ-01) |

Ad revenue alone is not the plan. For channel 1, streams 1 and 3 carry the business until YPP.

## 7. YPP eligibility and the AdSense timeline (§1B.4)

MVP scope: tracking 3C (Agent 14/15). Tier 0.

### 7.1 Verified thresholds (YT-10, VERIFIED 2026-11-18)
| Tier | Requirement | Note |
|---|---|---|
| Current full YPP | 1,000 subscribers + 4,000 public watch hours in 12 months **or** 10M Shorts views in 90 days | ad revenue |
| Expanded tier (India included) | 500 subscribers + 3 uploads in 90 days + 3,000 h or 3M Shorts views | fan funding and Shopping features (UNLOGGED-BIZ-03), unchanged by the 2027 change |
| **From 2027-02-01, new creators** | 1,000 subscribers + **8,000 watch hours** **or 20M Shorts views** | existing members unaffected (YT-10; text on Help 12843009) |

### 7.2 Effect on the AdSense timeline
- Channel 1 has **no published video today** (D1: no upload in 3A; 3B golden samples come first). The plan therefore assumes channel 1 applies **as a new creator under the 2027 thresholds** (8,000 h or 20M Shorts views). This is the conservative reading of YT-10; whether an application filed before 2027-02-01 would be judged on the old threshold is **REQUIRES REVIEW (Phase 1): YouTube's rule for applications in progress on 2027-02-01**.
- The watch-hour requirement doubles (4,000 → 8,000 h); the subscriber requirement is unchanged. Time to AdSense is **longer** (00b §4 risk 5). The months-to-YPP figure is a PROJECTION computed as below, never a stated date.

```
watch_hours_12m(m) = Σ_{videos, last 12 months} views × avg_view_duration_h     (public long-form views; MEASURED via YT-14 after publishing)
months_to_YPP      = first month m where watch_hours_12m(m) ≥ 8000 AND subscribers(m) ≥ 1000
                     (or Shorts path: shorts_views_90d ≥ 20,000,000 AND subscribers ≥ 1000)
required_hours_per_month (flat PROJECTION) = 8000 / target_months
required_views_per_month = required_hours_per_month / avg_view_duration_h
```

### 7.3 Content mix decision
- **Long-form is the qualifying product**: 8,000 watch hours is the realistic path for an education channel; the 20M Shorts-views path is not planned on.
- **Shorts feed long-form**, never the only product (`SHORTS` production type, 24 §7.2, after the MVP). Shorts views do not count as watch hours (YT-10 lists them as a separate path).
- Duration is chosen by topic depth inside the provisional 8-20 min window (`19_NICHE_BENCHMARKS.md` §7), never padded for watch hours.
- Expanded-tier fan funding (500 subscribers, 3,000 h) can arrive earlier than ads; channel-1 use is limited by FIN-R5.

## 8. Financial model and dashboards (§1B.5)

MVP scope: 3A produces the **cost per stage** file per video (D1; `09_COST_AND_BUDGET.md` §12). Revenue side, scenarios and dashboards 3C. Tier 0 (own channel); Tier 2 per-client billing uses `usage_events` / `invoices`.

### 8.1 Variables
| Variable | Unit | Source | Label |
|---|---|---|---|
| `C_video` | INR per published video | §9.1 formula from `cost_ledger` | MEASURED (ESTIMATE before the pilot) |
| `C_fixed_month` | INR | subscriptions (stock, music), incremental server (INF-01), tools | ACTUAL from invoices |
| `T_review_min` | minutes per video | owner/reviewer time, reported separately (never in money totals) | MEASURED in 3B |
| `videos_month` | count | owner cadence (A6 weekly review time) | owner setting |
| `views_v` | views per video (lifetime or 28 d window) | `analytics_snapshots` (YT-14) | MEASURED |
| `avd_h` | average view duration (h) | YT-14 | MEASURED |
| `RPM_net` | INR per 1,000 views to the creator (after the 55 % share, UNLOGGED-BIZ-01) | AdSense / Studio revenue report | ACTUAL after YPP; **NOT CONFIRMED** before |
| `ctr_course` | course-page clicks / views | link tracking (**REQUIRES REVIEW (Phase 1): tracking method**) | MEASURED |
| `conv_course` | purchases / course-page clicks | course platform | ACTUAL |
| `margin_course` | INR per sale | owner price − fees − GST − delivery | owner input |
| `margin_atp` | INR per ATP subscriber-month | owner | owner input |
| `sponsor_net_v` | INR per sponsored video | invoice | ACTUAL |
| `wht_rate` | share withheld on US-viewer earnings | AdSense tax info (UNLOGGED-BIZ-02) | owner's tax adviser ⚖ |
| `build_cost` | INR | one-time platform build spend (API, tools) | ACTUAL from ledger |

### 8.2 Formulas
```
revenue_v      = views_v × RPM_net / 1000 × (1 − wht_share_v)
               + views_v × ctr_course × conv_course × margin_course
               + atp_attributed_v × margin_atp
               + sponsor_net_v
profit_v       = revenue_v − C_video − (C_fixed_month / videos_month)
cost_per_1000  = (C_video + C_fixed_month / videos_month) / views_v × 1000
revenue_month  = Σ_v revenue_v (published that month, attribution window stated)
MRR            = course instalments + ATP subscriptions + memberships + client retainers (recurring only)
ROI_month      = (revenue_month − cost_month) / cost_month
payback_months = build_cost / average(revenue_month − cost_month) over the last k months (only if the average > 0)
```
`wht_share_v` = share of that video's ad revenue from US viewers × `wht_rate`. Attribution window for funnel sales: owner setting (**REQUIRES REVIEW (Phase 1): window length**).

### 8.3 Scenarios (PROJECTION) vs ACTUAL
Scenarios differ only in **input values**, never in formulas. No value is filled in this document.

| Input | Conservative | Moderate | Aggressive | Rule for the value |
|---|---|---|---|---|
| `views_v` | P25 of the channel's own MEASURED videos | median | P75 | before publishing: none (benchmark medians in 19 §6 are other channels' data and are never used as our forecast) |
| `RPM_net` | 0 until YPP admission | 0 until YPP | 0 until YPP | after YPP: P25 / median / P75 of ACTUAL months |
| `ctr_course`, `conv_course` | P25 of MEASURED | median | P75 | none before measurement |
| `videos_month` | owner cadence | owner cadence | owner cadence | A6 |
| `C_video` | P75 of MEASURED (higher cost) | median | P25 | pilot ledger |

Display rules: every scenario number carries the badge **PROJECTION** and the date of its input data; ACTUAL figures are shown in a separate column; a projection is never drawn as a continuation of the actual line without a visible break.

### 8.4 Dashboards (3C; numbers first, green up / red down, explanations behind details)
| Panel | Content | Data source |
|---|---|---|
| Per video | cost per stage, `C_video`, views, AVD, retention (`relativeRetentionPerformance`), course clicks, revenue_v, profit_v, QC score | `cost_ledger`, `quality_scores`, `analytics_snapshots`, `revenue_entries` (CCR-152) |
| Per channel / month | revenue by stream (§6), cost, profit, MRR, ROI, cost per 1,000 views | same, aggregated |
| YPP progress | watch_hours_12m vs 8,000; subscribers vs 1,000; months_to_YPP (PROJECTION) | YT-14 |
| Target gap | net_revenue_month vs ₹1,00,000 (gap only) | §1 formula |
| Budget | per-video and pilot budget use, breaches | `budgets`, `budget_reservations` (09) |
| Stop/scale | status of each §10 rule | §10 |

Actual revenue has no table in `04_DATABASE_ARCHITECTURE.md` (`invoices` are platform-to-client bills, Tier 2). Written against **`revenue_entries` (CCR-152, Proposed, deferred to 3C)**: org, channel, publication (nullable), stream, amount_minor, currency, period, label ACTUAL, source document ref.

## 9. Unit economics (S4 / Agent 15)

MVP scope: 3A cost side (ledger), 3B first measured `C_video`, 3C revenue side. Tier 0.

### 9.1 Cost per video (identical to `09_COST_AND_BUDGET.md` §9 and 00b §3.1)
```
C_video = LLM + TTS + footage + music + ai_broll + infra_share     (+ review time, reported separately)
```
| Term | Verified unit price (ID) | Quantity | Status |
|---|---|---|---|
| LLM | Sonnet 5.5 $2/$10, Opus 5.5 $4/$20, Haiku 5.5 from $0.10/$0.50 per MTok (PR-01); Batch −50 %, cache read 0.05× on Opus/Sonnet 5.5 (PR-02) | tokens per stage | REQUIRES REVIEW (Phase 1): measured in the skeleton (00b §3.3) |
| TTS | $0.08 per 1K characters, Marathi on v4/v3 (PR-04) | characters × takes | ESTIMATE ≈ **$0.64-0.80 per take for 10 min of Marathi** (00b §3.3; character count unmeasured) |
| Footage | $21-30/month one channel, annual billing (PR-06) | ÷ videos_month | ESTIMATE; client work needs the Business licence (quote) |
| Music | not in HTML (PR-07) | ÷ videos_month | REQUIRES REVIEW (Phase 1): ADR-009 and the owner's licensed-music-source decision (D6, needed before 3B) |
| AI B-roll | credit-to-seconds mapping not read (PR-07) | seconds per video | REQUIRES REVIEW (Phase 1): ADR-009 |
| Infra | ₹0 incremental if headroom on the existing KVM 2; else render worker KVM 1 ₹599/month promotional (INF-01) | ÷ videos_month | depends on the VPS audit (A1) |
| Review time | — | minutes | MEASURED in 3B; never converted into money unless the owner sets an hourly value |

No total `C_video` is stated until the skeleton measures it (09 §9).

### 9.2 Break-even views per video
```
contrib_per_view = RPM_net / 1000 × (1 − wht_share) + ctr_course × conv_course × margin_course
BEV_video        = max(0, C_video + C_fixed_month / videos_month − sponsor_net_v) / contrib_per_view
```
- Before YPP, `RPM_net = 0`: break-even depends **only** on the funnel (course/ATP) and sponsorships. If `contrib_per_view = 0` (no measured funnel yet), BEV is shown as "undefined", never as a number.
- Shown per video next to its MEASURED views: green when views ≥ BEV, red otherwise.

### 9.3 Payback of the build cost
`payback_months` (§8.2) is reported only from ACTUAL months; while the average monthly profit is ≤ 0 it reads "no payback yet".

## 10. Stop / scale rules per channel

MVP scope: 3C (needs published videos). Tier 0; Tier 1+ per client channel with the client's own thresholds. All thresholds are **owner-set configuration** (no value ships; CCR-166 for the `business.*` keys).

### 10.1 Scale (all must hold)
| # | Condition | Parameter |
|---|---|---|
| S1 | N consecutive published videos beat the target retention | `business.scale.n_consecutive`, `business.scale.min_relative_retention` (YT-14 `relativeRetentionPerformance`) |
| S2 | the same N videos meet the cost/revenue ratio | `business.scale.max_cost_revenue_ratio` (ACTUAL revenue incl. funnel) |
| S3 | every one of them scored ≥ 85 and passed all compliance checks | fixed by §1A.7 (not configurable down) |
| S4 | owner review time per video within the owner's weekly budget | A6 weekly review time |

Scale actions (owner approves each): raise cadence within budgets; add the `SHORTS` line; add a second language track (YT-15); then the second channel (§11).

### 10.2 Pause / stop
| # | Trigger | Action |
|---|---|---|
| P1 | the channel misses S1 or S2 for M consecutive weeks | `business.pause.m_weeks`: pause new production; owner review of topics and format |
| P2 | any compliance failure found after publishing, a YouTube policy strike, or a regulator notice | immediate stop of publishing on that channel; owner + lawyer review ⚖ |
| P3 | budget breach (per-video, pilot, monthly) | S4 stops paid calls (09 §4); no automatic top-up |
| P4 | YT-09 inauthentic-content signal (e.g. monetization review) | stop and review the template variety of the last videos |

## 11. Expansion path and tier gates (§1B.6, §1C.15)

| Step | Gate to enter | What is built (only then) | Infra | MVP |
|---|---|---|---|---|
| **Tier 0 — internal** | now | multi-tenant schema, RBAC basics, audit log, `org_id` everywhere; owner's channel 1 | existing shared VPS within §1 limits | 3A-3C |
| Channel 1 proven | §10.1 holds; owner approval | it becomes the product's live case study (no performance claim about trading; only production metrics) | same | 3C |
| Channel 2 (BagMitra) | channel 1 passed §10.1 | farming/orchard channel; claims rule pack | same | 3C |
| **Tier 1 — first managed-service client** | a paying client signed; Google OAuth verification + YouTube API compliance audit passed (YT-11, YT-12); client portal approvals; licence ledger; **own server** for render/client data | OAuth per client channel, approvals portal, Business-class stock licence (PR-06) | own server, sized from measured per-video use; recommend, never purchase (rule 8) | 3C+ |
| **Tier 2 — self-serve clients** | demand from more than managed clients | onboarding, white-label, billing (`plans`, `subscriptions`, `usage_events`, `invoices`), quotas | per `20_MULTI_TENANCY_AND_ENTERPRISE.md` | later |
| **Tier 3 — enterprise** | an enterprise contract requires it | SSO/SCIM, API/webhooks, dedicated deployment, pen-test, formal SLA | dedicated option | later |

Client prices: `21_PRICING_AND_PACKAGING.md` (PROPOSAL until the owner approves). Other business lines: `26_GROWTH_OPPORTUNITIES.md` (scored, not built).

## 12. 90-day launch plan for channel 1 (relative days; no calendar dates)

Day 0 = the owner approves the three 3B golden samples (all ≥ 85, zero compliance failures). Before Day 0: 3A slice and 3B pilot (D1). Upload needs Agent 13 + OAuth (3C), so the plan starts only when 3C publishing is approved. MVP scope: 3C. Tier 0.

| Days | Work | Exit check |
|---|---|---|
| Before 0 | A5 channel account decision; A6 inputs; disclaimer wording ⚖; channel profile with `rp.youtube_general` + `rp.finance_sebi_in`; budgets set at providers and in S4 (09 §8) | all set; no paid call before |
| 0-14 | Publish the three golden samples (private → owner authorisation → public, YT-04); description: disclaimer, course chapter pointer, further-reading credits | each video passed Agent 16 + owner approval |
| 15-30 | Cadence per owner setting (A6) from the topic tree's beginner series; one evergreen concept per video | cost per stage file per video; QC ≥ 85 |
| 31-60 | First analytics review (YT-14 retention, CTR from Reporting API); title/thumbnail A/B in Studio by a human (YT-08); course-click tracking live | §8 per-video panel filled with MEASURED data |
| 61-90 | First §10 evaluation (S1/S2 over the published set); decide: continue / adjust format / pause; optional `SHORTS` cut-downs feeding long-form | owner decision recorded (approval) |

Cadence, number of videos and video length are **owner settings** (A6), not fixed here.

## 13. Legal / accounting checklist (§1B.8) — not legal advice ⚖

### 13.1 Owner
| # | Item | Status / source |
|---|---|---|
| L1 | Channel owned under the owner's own Google account / Brand Account | A5 pending owner answer |
| L2 | AdSense for YouTube account and **US tax info** submitted; without tax info Google may withhold at the maximum rate; treaty benefit to be checked with a tax adviser (UNLOGGED-BIZ-02) | at YPP |
| L3 | Income tax treatment of AdSense, course and sponsorship income in India | **REQUIRES REVIEW (Phase 1): owner's CA** ⚖ |
| L4 | GST registration status and whether YouTube/AdSense receipts and course sales need GST | A6 pending; **REQUIRES REVIEW (Phase 1): owner's CA** ⚖ |
| L5 | Music/footage licences stored with the licence ledger (04 §5.15); monetized-YouTube coverage confirmed in writing (PR-06d/e) | before first publish |
| L6 | SEBI disclaimer policy: wording, languages, placement, duration; registration statement only if true (FIN-R10) | lawyer ⚖ |
| L7 | AI disclosure policy: `containsSyntheticMedia` decision per video (YT-06/07); IT Rules SGI (IN-06) | 13 §9 |
| L8 | Book licences / public-domain status per edition (K2, K11) | owner ⚖ |
| L9 | Course terms: pure education, no ongoing tips, no return claims (FIN-R5/R6) | owner ⚖ |

### 13.2 Clients (Tier 1+)
| # | Item |
|---|---|
| C1 | Master service agreement and terms of service |
| C2 | Data processing agreement (platform as processor, IN-07; `22_DATA_PROTECTION.md`) |
| C3 | Content-ownership clause and approval-liability clause (client approves and owns the published content; platform still refuses non-compliant content) |
| C4 | GST registration of the platform business and GST on invoices (`invoices.tax_minor`) ⚖ |
| C5 | Third-party/agency licence coverage for stock, music, voice and AI providers (PR-05 NOT CONFIRMED, PR-06 Business licence) |
| C6 | Advertising work: ASCI rules (`25_ADVERTISING_COMPLIANCE.md`; IN-04, IN-05) |

## 14. MVP scope summary

| Section | 3A | 3B | 3C | Tier |
|---|---|---|---|---|
| 1 Objective | fixed | — | dashboard | 0 |
| 2 Discovery engine | — | language decision (manual) | stored workflow | 0 (1-3 per client) |
| 3 Feasibility report | — | — | yes | 0-1 |
| 4 First-channel rules | gates enforced | golden samples | publishing | 0 |
| 5 Knowledge library | subset | tuned | full | 0 |
| 6-7 Revenue, YPP | — | — | tracking | 0 |
| 8-9 Model, unit economics | cost per stage file | first measured `C_video` | revenue + scenarios | 0 (2 billing) |
| 10 Stop/scale | — | — | yes | 0+ |
| 11 Tiers | Tier 0 schema | — | Tier 1 only on a signed client | 0-3 |
| 12 Launch plan | — | Day 0 gate | Days 0-90 | 0 |
| 13 Checklist | L5-L7 design | L6 wording | all owner items; client items at Tier 1 | 0-1 |

## 15. Contract change requests (filed in CONTRACT_CHANGE_REQUESTS.md §4.7 (integrator pass 5); all Proposed, deferred to 3C)

| # | Needed | Proposed name |
|---|---|---|
| 1 | storage of niche scores, weights and evidence | table `niche_scores` (CCR-166) |
| 2 | task type for discovery scoring | `agent_02.niche_score` (CCR-136) |
| 3 | ACTUAL revenue records per stream | table `revenue_entries` + enum `revenue_stream` (CCR-152) |
| 4 | owner-set business thresholds and weights | config namespace `business.*` (CCR-166) |
| 5 | unit-economics / stop-scale evaluation task | `agent_15.unit_economics_report` (CCR-136) |

## Appendix A — Owner inputs needed

| # | Input | Why | Needed by |
|---|---|---|---|
| A6-a | SEBI registration status | FIN-R8, IN-05, disclaimer text | before publishing |
| A6-b | GST status | L4, client invoices | before first revenue |
| A6-c | Weekly review time | cadence, S4 scale rule | before Day 0 |
| A6-d | Budget ceiling (per video, pilot, monthly) | 09 §3, P3 | before any paid call (3A) |
| A6-e | Narration choice | §4.4 | before 3A voice tuning |
| A6-f | Benchmark channels | 19, discovery evidence | before 3B |
| B1 | Discovery weights (11 criteria) and minimum confidence | §2 | before the 3B language decision |
| B2 | Course price, fees, delivery cost; ATP price | `margin_course`, `margin_atp` | before 3C dashboards |
| B3 | Scale/pause thresholds N, M, retention, cost/revenue ratio | §10 | before Day 60 |
| B4 | Funnel attribution window and course-click tracking method | §8.2 | before Day 30 |
| B5 | Channel account (A5) and AdSense/tax adviser | L1-L3 | before Day 0 / at YPP |
| B6 | Lawyer/CA for ⚖ items L3, L4, L6, L8, L9, C1-C4 | compliance | before publishing / first client |

## Appendix B — Sources (2026-11-18)

RESEARCH_LOG IDs cited: YT-04, YT-06, YT-07, YT-08, YT-09, YT-10, YT-11, YT-12, YT-14, YT-15, INF-01, IN-01, IN-02, IN-03, IN-05, IN-06, IN-07, IN-08, PR-01, PR-02, PR-04, PR-05, PR-06, PR-06d/e, PR-07.

Facts read for this document that have no `RESEARCH_LOG.md` ID (UNLOGGED, not citable; **REQUIRES REVIEW (Phase 1): log entry (official URL + date)** for each, including the 55 % / 45 % / 70 % revenue shares, the US-tax withholding wording and the 2027 threshold text on Help 12843009):
| ID | Finding | Source | Status |
|---|---|---|---|
| UNLOGGED-BIZ-01 | YPP revenue shares: 55 % of net revenue from Watch Page ads; 45 % of the revenue allocated from the Shorts Creator Pool; 70 % of net revenue from channel memberships, Super Chat, Super Stickers, Super Thanks (Commerce Product Module) | [Help 72902](https://support.google.com/youtube/answer/72902) | VERIFIED 2026-11-18 |
| UNLOGGED-BIZ-02 | Google withholds US taxes on YouTube earnings from US viewers (ads, Premium, Super Chat/Stickers/Thanks, memberships); without tax info it "may be required to withhold taxes worldwide using the maximum tax rate"; treaty benefits can reduce the rate | [Help 10391362](https://support.google.com/youtube/answer/10391362) | VERIFIED 2026-11-18 (rate values not extracted) |
| UNLOGGED-BIZ-03 | The expanded YPP gives "earlier access to fan funding and Shopping features" | [Help 13429240](https://support.google.com/youtube/answer/13429240) | VERIFIED 2026-11-18 |
