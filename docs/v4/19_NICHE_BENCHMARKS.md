# 19 — NICHE BENCHMARKS (first niche: stock-market trading education)

| Field | Value |
|---|---|
| Document status | DRAFT (documentation phase). Software status: Planned (no code). |
| Binding source | `MASTER_DIRECTIVE.md` §1A.9 (benchmark), §1B.1 (scoring), §1B.2 (first channel). Owner decisions D1, D2 (`IMPLEMENTATION_PROGRESS.md`). |
| Consumers | `18_PRODUCTION_QUALITY_STANDARD.md` (duration bounds, tier share, first drop-off window, Shorts values), `24_PRODUCTION_TYPES.md` §7.1 (`duration_targets_ms`), Agents 02/03 (topic plan), 05, 08, 09 (edit and visuals), 12 (thumbnail/metadata), 15 (economics), `17_BUSINESS_PLAN.md` (niche score). |
| Reading date | **2026-11-18** (all public-page readings below). |
| MVP scope | 3A: this document is a static input (values go into config). 3B: calibration against the three golden samples. 3C: Agent 02/15 refresh and the stored scoring workflow. Enterprise Tier 0 (own channel). Tiers 1-3 only reuse the method per client niche. |
| Open inputs | A6 (benchmark channels from the owner; SEBI status; weekly review time; budget ceiling; narration choice). See Appendix A. |

## 0. How to read the numbers in this document

- Every figure was read by the author from a **public YouTube page** (the channel's "Videos" tab and search results) on 2026-11-18. Label: **MEASURED (public page read)**. The page shows **rounded** counts (e.g. "20K", "1.12M subscribers", "13d ago"); the search page shows some exact view counts. Source URL pattern: `https://www.youtube.com/@<handle>/videos` (the handle is in the tables).
- A **sample** = the first 30 items of a channel's "Videos" tab (newest first, long-form; Shorts are listed separately by YouTube) at the reading time. A sample is a snapshot, not an analytics dataset. It says nothing about revenue, RPM, retention, impressions or audience geography. Those are **NOT CONFIRMED** (not public).
- "Derived" values (medians, quartiles, views-per-subscriber) are computed from the sample and labelled **DERIVED from MEASURED**.
- Statements about spoken language, pacing, structure and visual mix need someone to **watch** the videos. The author read titles, durations and thumbnails only. Those fields are therefore **NOT CONFIRMED: not yet watched** (Section 3, template in Section 9).
- No third-party analytics site (SECONDARY) was used. No RPM or revenue figure appears here.

## 1. Purpose and boundaries

1. Directive §1A.9: before automation, pick the top 3-5 channels per niche/language, record structure, pacing, video length, visual mix and thumbnail style, and set measurable targets against them.
2. Benchmarks calibrate **form** (length, pacing, visual mix, thumbnail grammar, cadence reference). They never supply **content**. We do not copy a channel's scripts, titles, thumbnails, graphics or structure beyond generic format conventions (originality and uniqueness are blocking gates: YT-09; `13_COMPLIANCE_YOUTUBE_POLICY.md`).
3. **Compliance filter on every benchmark (blocking for the method).** The first channel is SEBI-compliant education (FIN-R1..R13, `GLOSSARY_AND_IDS.md`). Patterns seen on benchmark channels that our rules forbid are recorded as "do not emulate", not as targets: profit or win-rate claims in titles/thumbnails (FIN-R6, FIN-R7), live trading sessions (FIN-R4), forward market views on named securities or indices (FIN-R3, FIN-R13), broker account/referral promotion (FIN-R8), AI presenter persona (FIN-R11). A channel may still be a format benchmark if its other videos are education.
4. This document does not choose the niche or the language. It supplies evidence for the owner's decision (directive §1B.1: weights are configuration, evidence is published, the owner decides). MVP scope for the decision itself: 3C business plan (`17_BUSINESS_PLAN.md`); for 3A the owner has already fixed the first channel (directive §1B.2), and the language question stays open (Marathi-first; Marathi vs bilingual/Hinglish to be scored).

## 2. Method (directive §1A.9)

MVP scope: method 3A (used once by hand for the first niche) / automated refresh 3C (Agent 02/15). Tier 0.

### 2.1 Cells

One benchmark set per **niche x language x country** cell. For the first niche, country = India (owner's channel; SEBI context) and the four language cells are:

| Cell | Label in this doc | Language tag (BCP 47, `GLOSSARY_AND_IDS.md` §language) |
|---|---|---|
| C1 | Marathi | `mr` |
| C2 | Hindi | `hi` |
| C3 | Bilingual / Hinglish (Hindi grammar with English trading terms; Latin or mixed script) | `hi-Latn` (pending CCR: not in the glossary examples) |
| C4 | English (India-facing or global) | `en-IN` / `en` |

Language of a channel is assigned by **what is spoken**. Until someone listens, the assignment is provisional and based on title/thumbnail script only (flag `language_basis = TITLE_ONLY`).

### 2.2 Candidate discovery (repeatable steps)

1. **Owner list first.** Channels the owner already admires (A6). Always included as candidates; the owner decides.
2. **Search sweep.** Run YouTube searches for the cell in the cell's language and in English: beginner course, price action, candlestick, technical analysis, support/resistance, risk management, trading psychology, options mechanics. Record query text and date.
3. **Channel tab read.** For each candidate open `/@handle/videos` and record the header (subscribers, video count) and the first 30 long-form items (title, duration, rounded views, age).
4. **Shortlist rule.** Keep the top 3-5 per cell by the ranking in 2.3.

### 2.3 Inclusion criteria and ranking (method parameters; values are configuration, owner-set, **not** research facts)

| # | Criterion | Rule | Evidence field |
|---|---|---|---|
| I1 | Topic fit | At least 60% of the sample titles are education on trading/markets concepts (not daily market calls, not news, not motivation) | topic-fit count of 30 |
| I2 | Language fit | Spoken language matches the cell (verified by listening to 3 videos) | `language_basis` |
| I3 | Active | At least 1 upload in the last 90 days in the Videos tab | newest age |
| I4 | Audience proof | Subscribers and median views of the sample both recorded; ranking by median views of the sample, not by subscribers | derived median |
| I5 | Compliance-clean format | Format can be reproduced without breaking FIN-R1..R13 | compliance note |

Placeholder thresholds: topic-fit **60%** and activity window **90 days** are starting values for the owner to confirm (config), not sourced facts.

A channel failing I1-I3 may still be listed as **adjacent** (format reference only), clearly marked, and does not count toward the top 3-5.

### 2.4 Data to record

| Group | Field | How obtained | Status in this doc |
|---|---|---|---|
| Identity | handle, URL, language cell, `language_basis`, reading date | public page | filled |
| Size | subscribers, total video count (as shown, rounded) | channel header | filled |
| Length | duration of each sample video; median, Q1, Q3; share per length band | Videos tab | filled |
| Public views | rounded views per sample video; sample median, min, max; median views / subscribers | Videos tab | filled |
| Cadence | uploads in the last 30 / 90 days within the sample (capped at 30) | age labels | filled (lower bound when the sample is exhausted) |
| Thumbnail style | focal subject, text (language, word count), colour, presence of chart, claim elements | look at 4+ thumbnails per channel | filled for 8 channels (Section 5) |
| Structure | hook pattern (first 30 s), chapter use, recap/CTA placement, end screen | watch 3 videos per channel | NOT CONFIRMED: not yet watched |
| Pacing | cuts per minute, seconds per visual, speech rate, pattern-interrupt timing | watch with a stopwatch on 3 windows per video (start, mid, end) | NOT CONFIRMED: not yet watched |
| Visual mix | share of screen time per visual tier `A_OWNER_REAL` / `B_LICENSED_STOCK` / `C_CODE_MOTION` / `D_AI_VIDEO` / `E_AI_STILL` (tier names from `GLOSSARY_AND_IDS.md`) | classify on watched videos | NOT CONFIRMED: not yet watched |
| Audio | loudness, music-bed level | optional; needs the audio | NOT CONFIRMED |
| Not obtainable | RPM, impressions, CTR, retention, revenue | not public | NOT CONFIRMED (never estimated here) |

Automated downloading of competitor video files is **not** part of the method (YouTube terms; legal review not done: **REQUIRES REVIEW (Phase 1): whether any automated frame analysis of public videos is permitted**). Pacing and visual mix are measured by manual watching.

### 2.5 Refresh

Re-read before 3B calibration, at each channel stop/scale review, and whenever the owner changes the benchmark list. The interval is configuration (**REQUIRES REVIEW (Phase 1)**: owner preference).

## 3. Candidate discovery log (2026-11-18)

Queries run (text, YouTube search page): "share market marathi", "marathi trading education channel", "technical analysis marathi candlestick", "candlestick patterns marathi", "options trading marathi", "price action trading hindi beginners", "technical analysis hindi full course", "stock market for beginners hindi", "stock market hinglish trading explained", "price action trading english beginners", "support resistance trading explained", "technical analysis india nifty english education". Some queries returned a page the parser could not read (the search page layout differs); those are not counted.

Findings that the data **shows** (limited to these queries and this date):
- Marathi channels returned with more than 1M subscribers were all **broader finance/investing/business** channels, not chart-based trading education (see 4.1). Marathi channels returned with a trading focus were small (26.4K to 45.7K subscribers).
- Hindi and English cells contain several education channels with over 1.8M subscribers.
- No channel could be assigned to the bilingual/Hinglish cell by **spoken** language. The Hinglish-titled results in the search were very small channels (single or double-digit views per the search page) and are not benchmarks.

What the data **does not show**: whether a larger Marathi chart-based trading channel exists that these queries missed. **NOT CONFIRMED: owner to supply benchmark channels (A6).**

## 4. Measured benchmark readings

All rows: **MEASURED (public page read) / DERIVED**, 2026-11-18, n = 30 sample items per channel (long-form Videos tab). "v/sub" = sample median views divided by subscribers (DERIVED; indicative only, because the sample mixes old and new videos and shows rounded counts). Duration bands are minutes.

### 4.1 C1 Marathi (provisional shortlist; role marked)

| Channel (URL `youtube.com/@...`) | Role | Subs / videos | Duration med (Q1-Q3) | Bands <5 / 5-10 / 10-20 / 20-40 / 40+ | Views med (min-max) | v/sub | Uploads <=30 d / <=90 d in sample | Language basis |
|---|---|---|---|---|---|---|---|---|
| CA Rachana Ranade (Marathi) `@CARachanaRanadeMarathi` | topic-adjacent: investing/markets education | 1.27M / 521 | 17.2 (14.9-19.6) | 0 / 0 / 23 / 7 / 0 | 45K (7.4K-236K) | 3.5% | 9 / 13 | TITLE_ONLY (titles mostly English with "(Marathi)") |
| Bharti Share Market - Marathi `@Bharti_Share_Market_Marathi` | topic-adjacent: beginner share-market basics | 1.12M / 616 | 5.5 (4.2-9.8) | 11 / 12 / 5 / 2 / 0 | 20.5K (1.2K-164K) | 1.8% | 3 / 11 | TITLE_ONLY (Marathi script with English terms) |
| Marathi Sanket `@MarathiSanket` | adjacent: personal finance/business/market commentary | 2.45M / 1.1K | 10.1 (8.3-11.8) | 0 / 14 / 14 / 2 / 0 | 83K (12K-401K) | 3.4% | 23 / 30 (sample spans 60 days) | TITLE_ONLY |
| The Marathi Trader `@The_Marathi_Trader-hz9mq` | trading-focused (small) | 37.7K / 1K | 10.5 (8.0-14.4) | 0 / 14 / 15 / 1 / 0 | 2.55K (705-41K) | 6.8% | 4 / 10 | TITLE_ONLY |
| Marathi trader2.0 `@Marathitrader2.0` | trading course lectures (small) | 26.4K / 47 | 9.7 (6.2-54.4) | 4 / 11 / 5 / 0 / 10 | 7K (754-34K) | 26.5% | 1 / 1 | TITLE_ONLY |

Notes:
- Only 2 of 5 here are topic-adjacent to chart-based trading education and none of the five is yet confirmed by listening; the C1 top-3-5 is therefore **provisional** and is replaced or confirmed by the owner (A6).
- Marathi trader2.0 shows 10 items of 40+ minutes (course-style recordings: titles "Day-2 ... Day-7", about 53-63 min each).
- Titles on The Marathi Trader in the sample include "Live Trading Results", "85% Win Rate" and a broker-trust guide; these are patterns that FIN-R4/R6/R8 forbid for our channel (do not emulate).
- Rejected as non-benchmarks (reason): Chart Commando Marathi `@ChartCommandoMarathi` (185K; newest sample item 5 months old; recent titles are personal-finance/self-improvement, not trading), ShahanPan `@ShahanPan` (1.34M; motivation content), a small channel whose recent titles centre on a forex broker/platform how-to (`@MarathiTraderAbhi`, 45.7K; content is account/platform guidance and short clips, not an education benchmark), Learning Market With MG (Marathi) (daily "Nifty prediction" analysis: forbidden form, FIN-R3).

### 4.2 C2 Hindi

| Channel | Role | Subs / videos | Duration med (Q1-Q3) | Bands <5 / 5-10 / 10-20 / 20-40 / 40+ | Views med (min-max) | v/sub | Uploads <=30 d / <=90 d | Language basis |
|---|---|---|---|---|---|---|---|---|
| Neeraj joshi `@Neerajjoshi` | trading/technical-analysis education | 5.36M / 1.3K | 15.6 (12.2-19.2) | 0 / 2 / 22 / 5 / 1 | 169K (38K-398K) | 3.2% | 27 / 30 (sample spans 60 days) | TITLE_ONLY (English titles with Hindi script in thumbnails) |
| Pushkar Raj Thakur `@PushkarRajThakurOfficial` | trading education + market news/crypto/lifestyle mix | 15.5M / 2.9K | 10.8 (8.9-15.5) | 0 / 11 / 15 / 1 / 3 | 195.5K (3K-441K) | 1.3% | 30 / 30 (sample spans 14 days) | TITLE_ONLY |
| Trade with Purab `@tradewithpurab` | beginner trading education | 3.22M / 707 | 18.0 (13.8-27.4) | 0 / 4 / 16 / 6 / 4 | 447.5K (91K-6.7M) | 13.9% | 0 / 0 (newest sample item is 1 year old) | TITLE_ONLY |

Note: Pushkar Raj Thakur's recent items include market-prediction and live-trading titles (FIN-R3/R4/R13 forms; do not emulate); its education items are the format reference.

### 4.3 C3 Bilingual / Hinglish

| Channel | Role | Subs / videos | Duration med (Q1-Q3) | Bands <5 / 5-10 / 10-20 / 20-40 / 40+ | Views med (min-max) | v/sub | Uploads <=30 d / <=90 d | Language basis |
|---|---|---|---|---|---|---|---|---|
| CA Rachana Ranade `@CARachanaRanade` | adjacent: markets/investing explainers (English titles) | 5.42M / 1.8K | 15.5 (13.6-17.4) | 0 / 0 / 27 / 2 / 1 | 85K (9.5K-406K) | 1.6% | 13 / 21 | NOT CONFIRMED: spoken language not listened to |

No channel is confirmed in C3. **NOT CONFIRMED: owner to supply benchmark channels (A6)** for Hinglish. Neeraj joshi (4.2) is a candidate for C3 if listening shows Hindi grammar with English terms; classification pending.

### 4.4 C4 English

| Channel | Role | Subs / videos | Duration med (Q1-Q3) | Bands <5 / 5-10 / 10-20 / 20-40 / 40+ | Views med (min-max) | v/sub | Uploads <=30 d / <=90 d | Language basis |
|---|---|---|---|---|---|---|---|---|
| The Trading Geek `@TheTradingGeek` | trading education (price action, market structure) | 1.88M / 1.4K | 32.4 (25.9-43.8) | 2 / 0 / 1 / 19 / 8 | 94K (31K-1.2M) | 5.0% | 14 / 24 | TITLE_ONLY |
| TradingLab `@TradingLabOfficial` | trading education, short tight videos | 2.06M / 244 | 9.6 (8.1-10.9) | 0 / 18 / 12 / 0 / 0 | 99K (20K-1.4M) | 4.8% | 4 / 7 | TITLE_ONLY |
| The Trading Channel `@thetradingchannel` | long-form education | 2.88M / 423 | 23.7 (18.9-28.9) | 0 / 0 / 10 / 17 / 3 | 193.5K (72K-1.9M) | 6.7% | 0 / 0 (newest sample item 2 years old) | TITLE_ONLY |

### 4.5 Evergreen anchors (exact view counts shown on the YouTube search page, 2026-11-18)

| Video (language cell) | Duration | Views (exact, as shown) | Age shown | Channel |
|---|---|---|---|---|
| Basic of Stock Market for Beginner in Marathi (C1) | 11:58 | 2,344,030 | 4y | Bharti Share Market - Marathi |
| Share market basics in Marathi, 52 min (C1) | 52:38 | 1,527,140 | 8y | Shambhuraj Khamkar |
| Basics of Stock Market Marathi, part 7 (C1) | 11:46 | 950,633 | 4y | CA Rachana Ranade (Marathi) |
| Price Action Free Masterclass (C2) | 30:54 | 4,155,522 | 4y | Pushkar Raj Thakur |
| Price Action Masterclass for beginners, Hindi (C2) | 19:18 | 819,222 | 2y | Neeraj joshi |
| Candlestick Trading Full Course (C2, title language mixed) | 54:32 | 7,535,363 | 2y | Trade with Purab |
| Ultimate Beginners Guide to Price Action Trading, full course (C4) | 49:19 | 490,288 | 2y | The Trading Channel |
| The Only Technical Analysis Video You Will Ever Need (C4) | 1:17:35 | 26,631,849 | 5y | The Trading Channel |

Observation (shows): the highest view counts on all four language pages sit on **beginner full-course / basics videos of 12-77 minutes** that are several years old. Whether such videos are evergreen search traffic or promoted traffic is **NOT CONFIRMED** (traffic source is not public).

## 5. Thumbnail style (observed by eye, 2026-11-18)

Read: the 4 newest thumbnails of each of 8 channels (CA Rachana Ranade Marathi, Bharti Share Market Marathi, Marathi Sanket, The Marathi Trader, Pushkar Raj Thakur, Neeraj joshi, TradingLab, The Trading Geek) = 32 images. Word counts and colour statements are approximate (counted by eye).

| Element | Observation | Use as target? |
|---|---|---|
| Layout | One large presenter face/torso on one side, big headline on the other; or one diagram/chart as the focal subject (TradingLab, The Trading Geek) | Yes: a single focal subject |
| Headline text | About 2-7 words; Marathi/Hindi channels use native script with English terms (e.g. loanwords such as "Trading", "Investment", "Chart Pattern") | Yes: short headline, native script with English term in the same line |
| Colour | High-contrast dark or saturated background with one bright text colour (yellow/white/red/green); candlestick or line-chart backdrop on many Indian channels | Yes: high contrast; chart backdrop allowed only from code-rendered or owner-owned charts |
| Charts | Annotated schematic charts (arrows, labelled swings) on English education channels | Yes: code-rendered schematic (visual tier `C_CODE_MOTION`) |
| Claim elements | Several thumbnails carry profit, win-rate or "10 lakh" style figures or a live P&L screenshot | **No** (FIN-R6, FIN-R7) |
| Named-company/IPO/prediction headlines | Present on market-news style videos | **No** (FIN-R3, FIN-R13) |
| Presenter face | Real person on almost all Indian channels | Owner decision (narration choice, A6). FIN-R11: no AI persona. Owner's own face is allowed; neutral design without a face is allowed |

Thumbnail targets are measurable only against `18_PRODUCTION_QUALITY_STANDARD.md` thumbnail checks (3 variants, size/format, contrast/legibility, promise alignment). Items in the table above are **inputs to the Agent 12 thumbnail template design**, not additional checks. Any thumbnail size or small-preview legibility threshold beyond Doc 18: **REQUIRES REVIEW (Phase 1)**: official YouTube thumbnail specification (owner of that value is Doc 18).

## 6. What the language comparison shows (and does not)

DERIVED from the readings above:

| Cell | Channels read | Sample median views (range of channel medians) | Typical duration median | Observation |
|---|---|---|---|---|
| C1 Marathi | 5 (2 adjacent large, 3 mixed/small) | 2.55K to 83K | 5.5 to 17.2 min | The two large Marathi finance channels are adjacent topics. Trading-focused Marathi channels in the sample are 26K-38K subscribers |
| C2 Hindi | 3 | 169K to 447.5K | 10.8 to 18.0 min | Large audiences; one channel not uploading for a year in the Latest tab |
| C3 Bilingual | 1 (unconfirmed) | 85K | 15.5 min | No confirmed benchmark |
| C4 English | 3 | 94K to 193.5K | 9.6 to 32.4 min | Wide spread of formats (short and tight vs 30+ min) |

Shows: absolute views in the Hindi and English samples are higher than in the Marathi sample; competition for chart-based trading education in Marathi, as visible through the queries run, looks thinner than in Hindi/English.

Does **not** show: demand per language, RPM or advertiser value per language, audience growth for a new channel, or whether a smaller language market limits revenue. The directive's research finding that English/bilingual earns more than Hindi than regional languages is **REQUIRES REVIEW (Phase 1): official or primary RPM-by-language source for India finance niche** (owner: `17_BUSINESS_PLAN.md`; no RESEARCH_LOG entry exists). Do not use the directive sentence as a verified fact.

## 7. Measurable targets derived from the benchmarks

Rule: a target is derived from the **owner-confirmed** top 3-5 in the chosen cell, never from the whole table. The values below are **provisional**, computed from the current reading, and replaced after A6 and 3B calibration. Marked 3A (config value used by the 3A QC) unless stated.

| Target | Derivation rule | Provisional value now | Status | Feeds | MVP |
|---|---|---|---|---|---|
| Long-form duration window | Union of Q1..Q3 of the confirmed benchmarks, rounded to whole minutes; hard bounds from Doc 18 stay in force | **8-20 min** (contains the interquartile range of 3 of the 4 Marathi-cell trading/finance channels with a median above 9 min; Bharti's 4.2-9.8 is partly outside) | PROVISIONAL, owner confirms; duration is chosen by topic depth, not padded | Doc 24 §7.1 `duration_targets_ms` bounds; Doc 18 duration check | 3A |
| Beginner full-course format | Count of 40+ min videos in the sample | exists in 7 of 12 channels read (Section 4); no target set | NOT CONFIRMED: owner decision whether to produce long course-style videos (cost, QC time) | Agent 03 | 3C |
| Hook window | Directive §1A.2 fixes 30 s | 30 s (not benchmark-derived) | FIXED by directive | Doc 18 `edit.hook.*` | 3A |
| Visual-change interval | Directive §1A.2: every 3-5 s in explanatory stretches. Benchmark channels' actual cuts per minute | NOT CONFIRMED: not yet watched | Measure on watched samples in 3B | Doc 18 pacing checks | 3B |
| First drop-off zone window | Doc 18 awaits this value | NOT CONFIRMED: needs watched samples; after publishing, retention data (YT-14) replaces it | owner-set config until then | `edit.interrupt.first_dropoff` | 3B/3C |
| Max share of `E_AI_STILL` screen time | Directive: never the majority. Benchmark shows how much real/chart material the channels use | NOT CONFIRMED: not yet watched. Doc 18 limit of 50% stays | stricter target after watching | `qc.visual.tier_share_e` | 3B |
| Thumbnail headline length | Median and range of headline words in the benchmark thumbnails | about 2-7 words observed; provisional target **<= 6 words** | PROVISIONAL (by-eye count of 32 images) | Agent 12 template | 3A (template design), 3B (calibrate) |
| Upload cadence reference | Uploads in the last 30 days in sample | C1: 1-23; C2: 0-30; C4: 0-14 (very wide) | **No target.** Cadence is an operational setting set from the owner's weekly review time and budget (A6) | Agent 13/scheduler | 3C |
| Public view reference | Median views per subscriber of the sample | 1.3%-26.5% across channels | **Monitoring reference only, not a goal or promise.** Compare the first channel's own analytics after publishing (YT-14) | Agent 14/15 | 3C |
| Shorts values | Doc 18 awaits Shorts benchmarks | NOT CONFIRMED: Shorts were not read (the Videos tab excludes them) | Read the Shorts tab of confirmed benchmarks in 3B | Doc 18 `qc.shorts` | 3B/3C |

All targets are **configuration values**, never hard-coded. The quality score thresholds (publish at >= 85, compliance failure rejects) are not changed by this document.

## 8. Niche scoring (directive §1B.1): weights placeholder

Weights are configuration and are **not set by this document**. The scoring workflow is owned by Agents 02 + 15 (3C); the first-channel niche is already fixed (§1B.2), so in 3A this table is used only for the Marathi vs bilingual/Hinglish language decision (3B/3C).

Scale placeholder: score 0-5 per criterion, evidence mandatory; weighted score = sum(weight x score) / sum(weight) x 100. Weights sum rule: any positive numbers (normalised). "Trending alone never qualifies a niche": a trend signal is not an input.

| # | Criterion (§1B.1) | Weight (placeholder) | Evidence available now for C1-C4 | Status |
|---|---|---|---|---|
| 1 | Genuine owner/human expertise | `W1 = TBD (owner)` | Owner facts: trading education method; Marathi course exists (A6 partly covered) | Owner to score; same for all cells except language fluency |
| 2 | Search demand | `W2 = TBD` | NOT CONFIRMED: search-volume data per language not collected | REQUIRES REVIEW (Phase 1): demand source |
| 3 | Audience size | `W3 = TBD` | Subscriber counts of benchmarks (Section 4) | Partial |
| 4 | Competition | `W4 = TBD` | Number and size of confirmed benchmarks per cell (Section 3, 6) | Partial |
| 5 | Advertiser demand / RPM | `W5 = TBD` | NOT CONFIRMED | REQUIRES REVIEW (Phase 1): primary source |
| 6 | Monetization paths | `W6 = TBD` | Own course, ATP, non-regulated sponsors, AdSense after YPP (directive §1B.2); no broker affiliate (FIN-R8) | Same for all cells |
| 7 | Evergreen share | `W7 = TBD` | Evergreen anchors (Section 4.5) show old beginner videos still viewed; traffic source not public | Partial |
| 8 | Production cost per video | `W8 = TBD` | Depends on voice/TTS language support and visuals: `09_COST_AND_BUDGET.md`; TTS support for Marathi/Hindi per PR-04 | Per cell, from Doc 09 |
| 9 | Retention potential | `W9 = TBD` | NOT CONFIRMED (not public) | Measured after publishing |
| 10 | Policy/legal risk | `W10 = TBD` | Same SEBI/YPP rules for all cells (FIN-R1..R13, YT-09); ASCI/IT-rule items per IN-04..IN-06 if ads | Same for all cells |
| 11 | International scalability | `W11 = TBD` | NOT CONFIRMED | Qualitative |

Output: a ranked table per cell with weights and evidence shown; the owner decides. Storage of weights and scores: contract request below (no table exists yet).

## 9. Templates (ready to fill)

### 9.1 Channel registry (one row per candidate)

| cell | handle / URL | read date | subs (as shown) | videos (as shown) | role (benchmark / adjacent / rejected) | language_basis (SPOKEN / TITLE_ONLY) | I1 topic fit (n of 30) | I2 | I3 newest age | I5 compliance note | owner decision |
|---|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | | | |
| NOT CONFIRMED: owner to supply benchmark channels (A6) | | | | | | | | | | | |

### 9.2 Sample statistics (one row per channel)

| handle | n | dur med | Q1 | Q3 | <5 | 5-10 | 10-20 | 20-40 | 40+ | views med | views min | views max | v/sub | up <=30 d | up <=90 d |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | | | | | | | |

### 9.3 Watch sheet (3 videos per channel; manual)

| handle | video URL | length | hook pattern (first 30 s; text) | seconds to first payoff | chapters (Y/N) | cuts/min start / mid / end | seconds per visual | pattern-interrupt times | visual mix A / B / C / D / E (% screen time) | music-bed present (Y/N) | CTA / end screen | compliance flags (FIN-R) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | | | | |

### 9.3a Thumbnail sheet (4+ thumbnails per channel)

| handle | video URL | focal subject | headline text | words | language of text | background / palette | chart present | claim element (Y/N; if Y: do not emulate) | presenter face (Y/N) |
|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | |

### 9.4 Target derivation

| target | benchmark channels used (owner-confirmed) | derived value | method | config value set by owner | date | owner approval |
|---|---|---|---|---|---|---|
| | | | | | | |

### 9.5 Niche score sheet (per cell)

| cell | criterion # | weight | score 0-5 | evidence (source ID / URL / date) | scored by | date |
|---|---|---|---|---|---|---|
| | | | | | | |

## 10. Limits and risks of this reading

1. Rounded public counts and a 30-item sample window. Different channels cover very different time spans (e.g. 14 days for one channel, 3 years for another), so view medians are not like-for-like.
2. Topic fit and language are inferred from titles and thumbnails; not listened to.
3. YouTube's page layout can change; readings are a dated snapshot. A refresh must redo the reading, not reuse these numbers.
4. Reading a public page is not an official API. No official quota or terms apply here beyond the site's public pages; automation of this reading at scale is a 3C decision (**REQUIRES REVIEW (Phase 1): terms for automated reading of public channel pages; official alternative is the YouTube Data API, with the quota rules of YT-01/YT-02**).
5. Benchmarks measure what others do, not what works for a new channel; the golden samples (3B) and later analytics (YT-14) are the real test.

## 11. MVP scope summary

| Section | Scope | Tier |
|---|---|---|
| 2 Method (manual) | 3A | 0 |
| 3-5 Readings (this file) | 3A input | 0 |
| 7 Targets to config | 3A (values), 3B (calibration) | 0 |
| 8 Scoring weights and workflow | 3C (3B for the language decision) | 0 (Tier 1-3 per client niche) |
| Refresh automation | 3C | 0-1 |

## Appendix A — Owner inputs needed

| # | Input | Why | Needed by |
|---|---|---|---|
| A6-1 | Benchmark channels the owner admires (any language, with the reason) | Replaces the provisional shortlist; I1-I5 still checked | before 3B |
| A6-2 | Narration choice (own voice / neutral TTS; own face or none) | Presenter and thumbnail style (FIN-R11) | before 3A script/voice tuning |
| A6-3 | Weekly review time and budget ceiling | Cadence and per-video cost (Doc 09) | before 3C scheduler |
| A6-4 | SEBI registration status and GST status | Compliance profile and revenue rules (FIN-R8) | before publishing |
| A6-5 | Confirmation of language cells to compare (Marathi vs bilingual/Hinglish; Hindi/English as reference) | Scope of scoring | before 3B |
| A6-6 | Confirmation of provisional values (duration window, topic-fit and activity thresholds, thumbnail word limit) | Targets | before 3B |
| A6-7 | Time (about 3 videos per channel) to watch or approve someone to watch benchmark videos for the watch sheet, or permission for the team to do it | Pacing, structure, visual mix | 3B |

## Appendix B — Sources and readings (2026-11-18)

Primary pages read (public, no login). All dated 2026-11-18, label MEASURED (public page read):
- YouTube search results pages for the queries listed in Section 3: `https://www.youtube.com/results?search_query=<query>`.
- Channel Videos tabs: `https://www.youtube.com/@CARachanaRanadeMarathi/videos`, `@Bharti_Share_Market_Marathi`, `@MarathiSanket`, `@The_Marathi_Trader-hz9mq`, `@Marathitrader2.0`, `@Neerajjoshi`, `@PushkarRajThakurOfficial`, `@tradewithpurab`, `@CARachanaRanade`, `@TheTradingGeek`, `@TradingLabOfficial`, `@thetradingchannel` (each `https://www.youtube.com/@<handle>/videos`); rejected candidates `@ChartCommandoMarathi`, `@ShahanPan`, `@MarathiTraderAbhi`, `@marketpulseapp` (small Hindi course channel, 74.8K subscribers, mixed durations to 5.7 hours; not used).
- Thumbnail images: public thumbnail URLs of the listed videos (viewed, not stored in the repo).

Cross-references to existing records (RESEARCH_LOG IDs): YT-09 (inauthentic content, channel level), YT-14 (analytics available after publishing), YT-01/YT-02 (API quota), IN-03 (advice/forward statements), IN-04..IN-06 (ads and synthetic content), PR-04 (TTS language support). Not verified and not cited: any RPM, CPM or revenue figure.

New facts for `RESEARCH_LOG.md` (to be added by the lead; also listed in the structured return): BM-01 to BM-05.
