# 26 — GROWTH OPPORTUNITIES (six business lines and own-channel niche candidates; scored, not built)

> **Integrator status (lane B2-1, 2026-11-18).** B-2 draft aligned with main: no upload and no Google OAuth in 3A (D1); the owner works from chat and has no CLI (D5/R14; decisions are recorded by the operator as `OWNER_CHAT_OPERATOR` evidence with a review code, CCR-010/CCR-100); the licensed music source is an open owner decision (D6); the repository is becoming private (D7). Facts without a `RESEARCH_LOG.md` ID carry the label `UNLOGGED` and are **not citable**: each is `REQUIRES REVIEW (Phase 1): log entry (official URL + date)`. Names that no Wave A contract defines carry their CCR number and status (filed and decided in CONTRACT_CHANGE_REQUESTS.md §4.7 (integrator pass 5)); this file changes no contract.

| Field | Value |
|---|---|
| Document status | DRAFT (documentation phase). Software status: **Planned** (no code). |
| Binding source | `MASTER_DIRECTIVE.md` §1E (candidate lines and niches), §1B.1 (scoring), §1C.15 (tier gates). Owner decisions D1 (3A → 3B → 3C, no upload / OAuth in 3A, spend limits) and D2 in `IMPLEMENTATION_PROGRESS.md`. |
| Contracts used (not redefined) | `GLOSSARY_AND_IDS.md` (FIN-R1..R13, enums), `24_PRODUCTION_TYPES.md` (§3.2 task types, §4 presets, §5 QC profiles, §7.1-§7.6 records), `07_FAILURE_MANAGEMENT.md`, `27_ENGINEERING_STANDARDS.md` |
| Read, referred to by name | `17_BUSINESS_PLAN.md` (§2 scoring formula, §9 unit economics, §11 tier gates), `19_NICHE_BENCHMARKS.md` (§6), `09_COST_AND_BUDGET.md` (§9, §12), `13_COMPLIANCE_YOUTUBE_POLICY.md` (§5, rule-pack list), `KNOWLEDGE_LIBRARY_PLAN.md` (§5), `02_AGENT_REGISTRY.md` (S3, Agent 17). Not yet written, by name only: `20_MULTI_TENANCY_AND_ENTERPRISE.md`, `21_PRICING_AND_PACKAGING.md`, `22_DATA_PROTECTION.md`, `25_ADVERTISING_COMPLIANCE.md`. |
| Date of all readings | **2026-11-18** |
| MVP scope | This document is analysis only. **3A: nothing here is built or needed.** 3B: no line. **3C+ / Tier 1-3**: each line enters only through the gates in §6. |

## 0. Reading rules

1. **Scores are a framework with evidence columns.** A cell is scored only where a repository document or a logged fact supports it; otherwise it is **NOT CONFIRMED** and stored as `NULL` (same rule as `17_BUSINESS_PLAN.md` §2.2). No guess fills a cell.
2. **No price, demand, RPM, margin, client count or competitor figure is stated** unless it is in `RESEARCH_LOG.md` or measured. Where a number would be needed it is a named variable.
3. **Labels** on every figure: ESTIMATE (verified unit price × a named quantity) / MEASURED (read from our system or a public page on a stated date) / PROJECTION (scenario output) / SECONDARY (third party). **DESIGN-DERIVED** marks an ordinal read from our own design documents (not market evidence).
4. Owner facts used: channel 1 = Marathi-first stock-market trading education, funnel to the owner's Marathi course and ATP, no broker affiliate income; owner unregistered with SEBI; A6 inputs pending (Appendix A).
5. Nothing here changes a contract. Proposed names not yet in a Wave A document carry their CCR number (CONTRACT_CHANGE_REQUESTS.md §4.7 (integrator pass 5)).

## 1. Framework

### 1.1 Six criteria (business lines, directive §1E)

| # | Criterion | Direction | What counts as evidence | Evidence available today |
|---|---|---|---|---|
| D | Demand evidence | higher = better | official / primary data on buyers or search demand for the line in the target languages, or a signed pilot | **none logged** for any line (NOT CONFIRMED) |
| P | Price the buyer will pay | higher = better | a quote, a competitor price page read on a date, or a signed order | **none logged** (`21_PRICING_AND_PACKAGING.md` not written; every `default_price` in 24 reads REQUIRES REVIEW (21)) |
| M | Margin at measured cost per deliverable | higher = better | `C_video` from the cost ledger (09 §9, §12) against P | **none**: `C_video` is not stated until the 3A skeleton measures it (17 §9.1, 09 §9). Only ESTIMATE components exist (§3) |
| R | Reuse of the existing pipeline | higher = better | components a line needs beyond the owner-channel production line | **DESIGN-DERIVED** (§2) |
| C | Compliance risk | lower risk = higher score | count of regimes from the research log that apply to the line | **DESIGN-DERIVED** count (§2); severity per regime NOT CONFIRMED |
| S | Sales effort | lower effort = higher score | owner's network, pilot conversations, sales cycle | **none**: owner input (Appendix A) |

### 1.2 Scale and formula (identical to `17_BUSINESS_PLAN.md` §2.2)

Each criterion 0-5 with evidence attached, otherwise `NULL`.
```
weighted_score(line) = Σ ( w_i × s_i ) / Σ ( w_i )  × 20      (criteria with s_i = NULL excluded from both sums)
confidence(line)     = Σ ( w_i where s_i has evidence ) / Σ ( w_i )
```
Weights are configuration set by the owner; **none ships by default and an unset weight blocks the ranking run** (17 §2.2). Weight keys for the six criteria: `business.growth.weights.{demand,price,margin,reuse,compliance,sales}` (CCR-166, Proposed, deferred to 3C). The result is a ranked shortlist with the weight set, its version and the evidence for every cell published beside it; the owner decides (§1B.1). Trending alone never qualifies a line or niche (17 §2.3).

**Consequence today:** only R and C have evidence, so **no weighted score and no ranking is computed**. §5 gives a gate-based sequencing proposal instead, and says so.

## 2. DESIGN-DERIVED cells (reuse R and compliance C)

### 2.1 Rubrics (so another reader gets the same number)
- **R = 5 − n**, minimum 0, where *n* = number of components the line needs that the owner-channel line (`CHANNEL_LONG_FORM`, 24 §7.1, Agents 04-16 and S-services as planned in 02) does **not** already contain. Components are counted from the 24 §7 records and 17 §11 gates.
- **C = 5 − k**, minimum 0, where *k* = number of distinct regimes that apply, counted from `RESEARCH_LOG.md` and the 13 rule-pack list. The count is **not severity-weighted**; it is a load indicator.

### 2.2 Per line

| Line | New components (n) → R | Regimes that apply (k) → C |
|---|---|---|
| **L1** Done-for-you channels (24 §7.1 / §7.2 for a client) | 4: client approval portal (`client_two_step`, S7/S11); per-client OAuth with Google verification and API audit (YT-11, YT-12); client-scoped knowledge library; Business-class stock licence (PR-06) → **R = 1** | 5: YT-09 (channel-level inauthentic-content test now applies to the client's channel); YT-06/YT-07 and IN-06 (synthetic-media disclosure); IN-07 (platform is processor of client data); IN-08 + PR-06 (copyright, stock licence); sector pack per client (`rp.health` for clinics, finance pack for CA/tax, 13 §5) → **C = 0** |
| **L2** AI ads for SMEs / regional brands (24 §7.3, §7.5) | 5: Agent 17 (`agent_17.brief_intake`, `concept_variants`, `ad_script_storyboard`); rule packs `rp.advertising_asci_in` + sector packs (25, pending); `qc.ad_spot` and multi-ratio / multi-duration masters (24 §4); `client_two_step` approvals incl. `USAGE_RIGHTS` record; claim-substantiation intake (§1D.3) → **R = 0** | 6: IN-04 (ASCI synthetic-content labels; not in force on 2026-11-18, ≈ end Dec 2026 by computation); IN-05 (influencer / UGC-style ads); IN-06; IN-07; IN-08 + PR-06; claims and sector packs → **C = 0** |
| **L3** Localisation / dubbing (24 §7.6) | own content: 3 (S3 translate / timing / native-speaker QC; `SOURCE_VIDEO` intake; `qc.dubbing`) → **R = 2**. Client content: + client approvals = 4 → **R = 1** | own content: 3 (IN-08 rights in the source; synthetic-voice disclosure YT-06/IN-06; voice consent PR-04); client content: + IN-07, + PR-05 (agency use of the TTS output NOT CONFIRMED) = 5 → **C = 2 (own) / 0 (client)** |
| **L4** Corporate / e-learning video (24 §7.4) | owner's own course: 1 (`agent_17.brief_intake`; the course library already exists, KNOWLEDGE_LIBRARY_PLAN §5) → **R = 4**. External client: 3 (brief intake, client library, client approvals) → **R = 2** | own course: 2 (IN-08 for any third-party material; IN-06). External: + IN-07, + promotional routing to the ad pack (decision rule REQUIRES REVIEW (25), 24 §7.4) = 4 → **C = 3 (own) / 1 (external)** |
| **L5** White-label licensing to agencies (Tier 2/3) | ≥ 5: all of L1/L2 components plus onboarding, white-label, billing (`plans`, `subscriptions`, `usage_events`, `invoices`), quotas, SSO/SCIM at Tier 3 (17 §11) → **R = 0** | inherits every regime of the lines the agency sells, plus tenant brand-safety pack; per-agency count NOT CONFIRMED → **C = NULL** |
| **L6** Agri content and ads for agri-input / farm-tech firms | L2 components + agri claims pack (content REQUIRES REVIEW (Phase 1): agri-input advertising and claims rules; none in `RESEARCH_LOG.md`) + BagMitra funnel integration → **R = 0** | L2's six + the agri sector pack → **C = 0** (count is a lower bound until the agri rules are researched) |

## 3. Margin: what can and cannot be said

Margin M needs `C_video` measured in 3A/3B (09 §9, §12) and a price P from doc 21. Neither exists, so **M = NOT CONFIRMED for every line**.

Only ESTIMATE components are verified:

| Component | Value | Label | ID | Limit |
|---|---|---|---|---|
| TTS, Marathi or Hindi on Eleven v3/v4 | $0.08 per 1K characters; a 10-minute Marathi script ≈ 8-10K characters ≈ **$0.64-0.80 per take** | ESTIMATE (character count unmeasured) | PR-04 | one take; excludes retakes, LLM, footage, review time |
| Dubbing per extra language, TTS only | same rate × the translated script's characters; per language per take ≈ the line above if the script length is similar | ESTIMATE (translated length unmeasured; Marathi and Hindi expand differently from the source) | PR-04 | excludes human native-speaker QC (a mandatory approval step, 24 §7.6), timing fit, client rights check |
| LLM | Sonnet 5.5 $2 / $10, Opus 5.5 $4 / $20 per MTok; Batch −50 % | ESTIMATE (tokens per stage unmeasured) | PR-01, PR-02 | |
| Stock footage | $21-30 per month (one channel, annual billing) | ESTIMATE | PR-06 | **does not cover client work**; Business licence is by quote (REQUIRES REVIEW (Phase 1): quote) |
| AI B-roll, music | not read | NOT CONFIRMED | PR-07 | REQUIRES REVIEW (Phase 1): ADR-009 |
| Human time per deliverable | measured in 3B | MEASURED later | 17 §9.1 | never converted to money unless the owner sets an hourly value |

For L2 (ads) the cost driver is likely the number of variants and aspect ratios per order (24 §7.3 lists 3-5 variants, 4 ratios, 4 durations). Cost per deliverable is therefore a function of an order matrix, not a single `C_video` (**REQUIRES REVIEW (Phase 1): cost model per ordered combination, 24 §7.3 and 21**).

## 4. Line cards

Each card: what is sold, pipeline path (24 §3.2 names), gates, evidence rows, what is NOT CONFIRMED.

### 4.1 L1 Done-for-you YouTube channels (businesses and educators: coaching institutes, schools, CA/tax firms, real-estate developers; clinics only with the health pack)
- **MVP / tier:** 3C+, **Tier 1** (first managed-service client, 17 §11).
- **Path:** `CHANNEL_LONG_FORM` / `SHORTS` records with the client as tenant: 04 → 05 → 06 → 07 → 08 → 09 → 10 → 11 → 12 → 16 → approval → 13 (`agent_13.upload_private`, `publish`).
- **Gates before the first order:** Google OAuth verification and YouTube API compliance audit (YT-11, YT-12); client portal approvals; own server for client data (17 §11); Business-class stock licence (PR-06); written confirmation of TTS output for client use (PR-05 NOT CONFIRMED); DPDP posture before about 13 May 2027 (IN-07); master service agreement and approval-liability clauses (17 §13.2, ⚖).
- **Risk specific to this line:** channel-level YPP test (YT-09): "channels where content feels interchangeable from video to video are not allowed to monetize". A client channel produced on our templates carries that risk for the client, not only for us. Mitigation is design (human editorial contribution and the S2 uniqueness gate), not a promise.
- **Ongoing load:** a channel is a continuing service (approvals every video), unlike a one-off file order. The owner's weekly review time (A6) is the first constraint and is unknown.
- **NOT CONFIRMED:** demand, price per channel per month, margin, sales cycle, how many such businesses publish video in Marathi/Hindi.

### 4.2 L2 AI ad production for SMEs and regional brands (festival and seasonal variants, regional-language versions of one master ad, e-commerce and UGC-style product videos)
- **MVP / tier:** 3C+, Tier 1 for the first ad client. Delivery is `FILE_DELIVERY` (24 §7.3), so **no client OAuth is needed** unless the contract includes upload.
- **Path:** `agent_17.brief_intake` → `concept_variants` → `CONCEPT` approval → `ad_script_storyboard` → `agent_06.claim_extraction` and `claim_verification` (blocking: every claim needs substantiation) → script/storyboard approval → 07 → 09 → 08 → 10 → `qc.ad_spot` → 16 → `FINAL_VIDEO` approval (24 §7.3).
- **Gates:** `25_ADVERTISING_COMPLIANCE.md` and the ASCI pack (IN-04: label "Audio/Video created using AI" where synthetic content is material; prohibited even with a label: fabricated endorsements, deepfakes or likeness without consent; in force around end of Dec 2026, **not in force on 2026-11-18**); IN-05 for creator/UGC-style formats; signed releases for any real person; destination specs and legal-super legibility (REQUIRES REVIEW (Phase 1): 25).
- **Why the compliance count is high:** every ad claim is the client's claim, and the client's product category adds a sector pack. The design makes substantiation documents a required input (24 §7.3).
- **NOT CONFIRMED:** demand from SMEs, price per spot/variant, margin per ordered combination, competing agency and AI-tool prices, destination platform specs.

### 4.3 L3 Localisation and dubbing into Indian languages (creators, educators, companies)
- **MVP / tier:** 3C, S3 (not used in 3A, 02 registry). First use can be the **owner's own content (Tier 0)**: the owner is the rights holder, `owner_one_tap` approval applies (24 §7.6), and no client OAuth or agreement is needed. Paying clients: Tier 1.
- **Path:** `svc_s03.translate_script` → `agent_06.claim_extraction` on the translation (blocking: meaning must not change into a rule violation) → `svc_s03.native_speaker_qc` (human approval per language) → 07 → `svc_s03.dub_timing_fit` → `agent_07.audio_master` → `agent_10.subtitles` → `technical_qc` (`qc.dubbing`) → metadata per language → delivery.
- **Platform facts (labelled):**
  - **YT-15 (YouTube's own figure, VERIFIED 2026-11-18):** "Creators who uploaded Multi-language audio tracks saw over 25% of their watch time come from views in the video's non-primary language." The YouTube blog words it as "on average, creators uploading Multi-language Audio tracks to their videos saw over 25% of their watch time come from views in the video's non-primary language" ([Help 13338784](https://support.google.com/youtube/answer/13338784), [blog](https://blog.youtube/news-and-events/multi-language-audio/)). **Label: YouTube's own claim.** It is an average over creators who chose to upload tracks; it does not state which languages, which channels, or any revenue effect, and says nothing about finance education or about a new channel. It is not a forecast for any channel of ours.
  - **GRW-01 (RESEARCH_LOG, VERIFIED 2026-11-18):** the feature is "currently available to creators with access to Advanced features"; the creator uploads own audio tracks in Studio on desktop (audio-only file, "roughly the same length as your video"); it "does not automatically create these tracks"; if an automatic dub exists in that language it must be deleted first; a track may be removed if different copyrighted content is detected. The page advises focusing "on one or two languages" and says a good candidate "already has viewership from multiple geographies or frequent comments in different languages" ([Help 13338784](https://support.google.com/youtube/answer/13338784)). API support for uploading tracks is NOT CONFIRMED (24 §4), so the fallback is a human Studio step scheduled by S7.
  - **GRW-02 (RESEARCH_LOG, VERIFIED 2026-11-18): YouTube's own automatic dubbing is a free alternative.** Its official table lists, for English as the original language: Arabic, Bengali, Dutch, French, German, Hebrew, Hindi, Indonesian, Italian, Japanese, Korean, Malayalam, Polish, Portuguese, Punjabi, Russian, Spanish, Tamil, Telugu, Ukrainian. For Hindi as original: Bengali, English. Tamil, Telugu, Malayalam, Punjabi, Bengali, Urdu originals: English. **Marathi does not appear as an original or a target language in the table.** The page says support is "gradually expanding", that the exact languages per video are on the Languages page in Studio, and that videos are ineligible for reasons such as length above 120 minutes, little speech, unsupported or undetected source language, too-fast speech, or copyrighted content ([Help 15569972](https://support.google.com/youtube/answer/15569972)). The table is a dated snapshot and can change.
  - **PR-04:** Marathi and Hindi are supported on the ElevenLabs v3/v4 class models (not Multilingual v2 / Flash v2.5 for Marathi). So Marathi is technically producible by our TTS path while YouTube's automatic dubbing does not list it on 2026-11-18.
- **What this shows and does not show:** it shows that (a) for pairs YouTube auto-dubs, a free platform feature competes with a paid service; (b) Marathi is absent from that table today. It does **not** show that anyone will pay for Marathi dubbing, how many creators need it, what quality native speakers will accept, or that the gap persists.
- **NOT CONFIRMED:** demand, price per language-minute, margin (TTS ESTIMATE only, §3), native-speaker reviewer cost and availability, Studio upload API support, per-language pronunciation-dictionary effort.

### 4.4 L4 Corporate and e-learning videos (training, onboarding, product explainers, course-to-video conversion for coaches)
- **MVP / tier:** the owner's own course is the first case and runs at **Tier 0** (the owner is client and approver; library already planned, KNOWLEDGE_LIBRARY_PLAN §5). External clients: Tier 1.
- **Path:** `EXPLAINER_CORPORATE_TRAINING` (24 §7.4): `agent_17.brief_intake` → `BRIEF` approval → `agent_04.research_pack` (client library only) → 05 → 06 → `SCRIPT` approval → 07 → 09 → 08 → 10 → `qc.corporate` → `FINAL_VIDEO` approval; YouTube optional.
- **Rules:** finance content for the owner's course follows the first-channel rules (education only, no calls, no return claims; 13 §5). Any third-party book material is not reproduced (directive §1B.2a). Client source documents go only to that client's isolated library (tenant isolation, rule 9).
- **Why first:** the only line whose first customer is the owner, so demand and price are an owner decision, not a market bet; the delivered files double as the product's case study (production metrics only, no performance claim about trading, 17 §11).
- **NOT CONFIRMED:** external demand, price per finished minute, margin, whether coaches want Marathi, English or bilingual output.

### 4.5 L5 White-label licensing to marketing agencies
- **MVP / tier:** Tier 2/3, after Tier 1 is running; **gate:** "demand from more than managed clients" (17 §11). Needs `20_MULTI_TENANCY_AND_ENTERPRISE.md` and `21_PRICING_AND_PACKAGING.md`.
- **Dependencies verified:** PR-05 (TTS output for agency/client use: NOT CONFIRMED, written confirmation or enterprise agreement needed); PR-06 (Small Business stock plan "excludes agencies and production companies"; Business licence by quote); YT-11 (API quota audit "to show that your project is in compliance with the YouTube API Services Terms of Service"); IN-07 (processor duties).
- **NOT CONFIRMED:** everything on the demand and price side. This line is the most dependent on the others: it sells what L1-L4 prove.

### 4.6 L6 Agri-sector content and ads for agri-input and farm-tech firms (BagMitra as the funnel)
- **MVP / tier:** 3C+; depends on the second channel (farming/orchard channel, 17 §11, launched only after channel 1 passes the scale rules) and on the ad pack.
- **Compliance:** ASCI and IT-rule regimes as L2; **agri-input advertising and claims rules REQUIRES REVIEW (Phase 1)** (no entry in `RESEARCH_LOG.md`; not written from memory). A claims rule pack is required by the directive.
- **Funnel note:** BagMitra is an owner product; promoting it is self-promotion, labelled transparently (as for ATP, IN-05 note). Promoting third-party agri products is paid advertising and follows the ad pack.
- **NOT CONFIRMED:** demand, price, margin, buyer segment size, who the buyer is (input firm, dealer, farm-tech start-up).

## 5. Proposed order (a sequencing proposal, not a ranking)

Basis: only R, C and the gate list are evidenced (§2, §4). The order below therefore sequences by **gate load and reuse**, and says so. When demand (D), price (P), margin (M) and sales effort (S) are filled and the owner sets weights, the ranking run in §1.2 replaces this table. **The owner decides.**

| Step | Line | Why here (evidence) | Entry condition |
|---|---|---|---|
| 0 | Channel 1 (own, trading education) | the live case study; Tier 0; D1 build order | 3A → 3B pass; 17 §10 scale rules |
| 1 | **L4 own-course conversion** | highest reuse (R = 4), customer is the owner, no client OAuth, no agreement | 3B golden samples scored; owner approves the course material for video |
| 2 | **L3 dubbing of owner content** | R = 2 with no client gates (Tier 0); tests S3 and native-speaker QC; Marathi gap vs YouTube auto-dub (GRW-02) is a hypothesis to test, not a demand finding | S3 built (3C); native speaker found (owner input); the owner's channel has viewers in other languages (YouTube's own advice, GRW-01) |
| 3 | **L3 and L4 for paying clients** (file delivery first) | both can be delivered as files without per-client OAuth (24 §7.4, §7.6); first Tier 1 test of client approvals and agreements | Tier 1 gate (17 §11): signed client, own server, DPDP posture (IN-07), PR-05 written confirmation |
| 4 | **L1 done-for-you channels** | R = 1, C = 0: most gates (OAuth verification, audit, licence), continuing service, channel-level YPP exposure on the client's channel (YT-09) | Tier 1 gates + YT-11/YT-12 passed; manual capacity known (A6) |
| 5 | **L2 ads** | R = 0, C = 0: needs Agent 17, the ASCI pack and sector packs; IN-04 not yet in force on 2026-11-18 | doc 25 written and approved; IN-04 final effective date confirmed; substantiation process agreed |
| 6 | **L6 agri** | depends on L2 and on agri rules not yet researched | second channel launched; agri claims research done |
| 7 | **L5 white-label** | sells what L1-L4 prove | Tier 2/3 gate: demand from more than managed clients |

L2 sits after L1 only on the evidence of component count and unwritten rule packs. If Phase 1 finds real SME demand for ads and a manageable rule pack, this order changes.

## 6. Own-channel niche candidates (scored by §1B.1 after channel 1 proves out)

Unit of scoring is niche × language × country (17 §2.1). Seven candidates from directive §1E. Four columns are filled from our documents; every market column is NOT CONFIRMED because no benchmark was read for these niches (`19_NICHE_BENCHMARKS.md` covers trading education only).

| Candidate | Knock-out check (17 §2.3; YT-09) | Rule packs / limits that apply | Owner expertise (criterion 1) | Demand, audience, competition, RPM, retention (criteria 2-5, 9) | MVP |
|---|---|---|---|---|---|
| Personal-finance basics (education only) | passes; same finance rules as channel 1 | `rp.finance` rules FIN-R1..R13, IN-01..IN-03; no AI persona on finance (YT-09, YTG-R2); no broker association (IN-01) | partly shared with channel 1 (owner statement needed for scope) | NOT CONFIRMED | 3C+ |
| AI-tools tutorials (Marathi/Hindi) | passes; **template-repetitive risk** if every video is the same screen-recording format (YT-09) | `rp.youtube_general`; third-party product claims are the creator's responsibility; no pack specific | NOT CONFIRMED (owner input) | NOT CONFIRMED | 3C+ |
| Farming / orchard technology (Marathi) | passes | claims pack (agri claims REQUIRES REVIEW (Phase 1)); already the planned channel 2 with BagMitra (17 §11) | owner product BagMitra exists; domain expertise statement needed | NOT CONFIRMED | 3C |
| State competitive-exam preparation (e.g. MPSC) | passes; **formulaic series risk** (YT-09) | copyright of coaching / textbook material (IN-08); same no-reproduction rule as the book rule (§1B.2a); exam-fact accuracy through Agent 06 | NOT CONFIRMED | NOT CONFIRMED | 3C+ |
| Government-scheme explainers (farmers, small businesses) | passes; **formulaic series risk** | official sources only (directive §1E); facts go stale, so each script needs a source date and an expiry (Agent 04/06 design); no advice on eligibility for a person | NOT CONFIRMED | NOT CONFIRMED | 3C+ |
| Small-business how-to (Marathi) | passes | legal / tax content needs an accuracy check, not advice (⚖, REQUIRES REVIEW (Phase 1): rule pack scope) | NOT CONFIRMED | NOT CONFIRMED | 3C+ |
| Maharashtra history / culture storytelling | passes only if kept away from news/politics (knock-out list) | source copyright (IN-08), image licences (PR-06 limits); sensitive-topic review by the human approver | NOT CONFIRMED | NOT CONFIRMED | 3C+ |
| **Knocked out** (directive §1E): medical advice, kids' content, news/politics, any template-repetitive niche | listed with reason, not ranked | `rp.health` / `rp.kids` are platform stubs for clients only (13) | n/a | n/a | n/a |

Evidence note: the only cell-level benchmark in the repository is C1-C4 for trading (19 §6), which shows lower visible competition for chart-based trading education in Marathi than in Hindi / English and does **not** show demand, RPM or growth. It must not be read across to other niches.

## 7. Open points and what the next phase must fill

| Gap | Needed to fill | Owner |
|---|---|---|
| D for L1-L6 and niches | official or primary demand data per language, or signed pilots | Agent 02 research, owner |
| P for L1-L6 | competitor price pages read on a date (done-for-you YouTube production, AI ad production, dubbing per minute, corporate video); doc 21 | doc 21 |
| M | measured `C_video` per production type from 3A/3B; per-order cost model for L2 | 09, 3B |
| S | owner's network, pilot conversations | owner |
| Weights and keys | `business.growth.weights.*` (CCR-166) | owner |
| Agri-input claims and advertising rules | official text | Phase 1 |
| API support for multi-language audio upload and for auto-dub deletion | official API reference | Phase 1 (24 §4) |
| Marathi in YouTube auto-dubbing | re-read the table before any L3 decision (the table changes) | Phase 1 |

## Appendix A — Owner inputs needed

| # | Input | Why | Needed by |
|---|---|---|---|
| A6-a | SEBI registration status | finance lines (L4 course, personal-finance niche), IN-01, IN-05 | before any finance-related client or sponsor work |
| A6-b | GST status | any paid line (L1-L6) | before first revenue |
| A6-c | Weekly review time | L1 is a continuing service; S criterion | before choosing L1 |
| A6-d | Budget ceiling (per video, pilot, monthly) | D1 spend controls; M criterion | before any paid call (3A) |
| A6-e | Narration choice | L3 voice policy and consent (PR-04) | before 3A voice tuning |
| A6-f | Benchmark channels | niche scoring evidence | before 3B |
| G1 | Which lines the owner wants evaluated first, and weights (`business.growth.weights.*`) | the ranking run is blocked without weights | before any ranking |
| G2 | Owner's existing contacts or leads for each line (coaches, institutes, SMEs, creators, agencies) | S and D evidence; a pilot is stronger evidence than any desk figure | before Tier 1 planning |
| G3 | Is the owner's Marathi course content cleared by the owner for video (what may be shown) and its price and delivery cost | L4 first case; `margin_course` (17 B2) | before L4 |
| G4 | Native speakers and reviewers for dubbing languages (Hindi, English, others) | L3 mandatory human QC | before L3 |
| G5 | Which niche candidates the owner has real expertise in | criterion 1 | before the second-niche run |
| G6 | Willingness to take client work at all, and the Tier 1 timing | gates in §5 | before Tier 1 |

## Appendix B — Sources (2026-11-18)

RESEARCH_LOG IDs cited: YT-06, YT-07, YT-09, YT-11, YT-12, YT-15, IN-01, IN-03, IN-04, IN-05, IN-06, IN-07, IN-08, PR-01, PR-02, PR-04, PR-05, PR-06, PR-07.

GRW-01 and GRW-02 are logged on main. Any other fact in this document without a `RESEARCH_LOG.md` ID is **REQUIRES REVIEW (Phase 1): log entry (official URL + date)**:
| ID | Finding | Source | Status |
|---|---|---|---|
| GRW-01 | Multi-language audio mechanics and conditions (Advanced features; own tracks, desktop Studio; not automatic; auto dub must be deleted first; copyrighted-content removal; advice to focus on one or two languages) | [Help 13338784](https://support.google.com/youtube/answer/13338784) | VERIFIED 2026-11-18 |
| GRW-02 | YouTube automatic dubbing language table (Marathi absent as source and target; Hindi → Bengali, English; English → 20 listed languages incl. Hindi, Tamil, Telugu, Malayalam, Punjabi); ineligibility reasons; support "gradually expanding" | [Help 15569972](https://support.google.com/youtube/answer/15569972) | VERIFIED 2026-11-18 (snapshot; changes) |

Checked and not used: third-party guides on YouTube auto-dubbing (language counts conflict between them; SECONDARY, not cited for any figure).
