# Agent 02 — Market Intelligence (blueprint)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** (rule 6, rule 7) |
| Owner | Agent 02 Market Intelligence; integration owner: Agent 01 (orchestrator) |
| Package | `agent_02_market_intelligence` (27 §7.2); prompts `prompts/agent_02_market_intelligence/`; evals `evals/agent_02_market_intelligence/` |
| Directive sections covered | §3.1 row 02 (trend discovery, predictive content intelligence with confidence and evidence, competitor early-warning from public/authorised data only), §1B.1 (Business Discovery Engine, owned by Agent 02 + 15; trending alone never qualifies), §1E (growth lines: evidence supply only), §3.3 (contracts, memory, failures, observability, AI providers), §3.5 (prompt, eval, code standards), §4 (26 sections) |
| Owner decisions applied | D1 (Agent 02 is **not** in 3A: the owner supplies the topic; Agent 02 is built in **3C**; no OAuth and no upload ever needed by this agent; paid calls only within owner-set limits; keys only through the secret mechanism), D2 (full blueprint now; `REQUIRES REVIEW` items do not block 3A) |
| Binding contracts | GLOSSARY_AND_IDS.md (§2 IDs, §6.30 memory scopes, §6.37–6.38 rule packs and FIN-R1…R13, §6.42 quota buckets, §6.51 refusal reasons), 03_COMMUNICATION_STANDARD.md (task input/output, error object, §9 idempotency, §11 state machine), 04_DATABASE_ARCHITECTURE.md (§3 tenancy, §5.3, §5.7, §5.9, §5.10, §5.14, §5.20, §5.22), 07_FAILURE_MANAGEMENT.md, 24_PRODUCTION_TYPES.md (§3.2 `agent_02.trend_scan`; stage `s02_trends`), 27_ENGINEERING_STANDARDS.md |
| Shared docs referenced by name/§ only | 02_AGENT_REGISTRY.md §3.3, 05_RESOURCE_MANAGEMENT.md, 06_NIGHT_SCHEDULING.md, 08_SECURITY.md §3, §5.3, §8, 09_COST_AND_BUDGET.md, 13_COMPLIANCE_YOUTUBE_POLICY.md, 17_BUSINESS_PLAN.md §2, 3A_SLICE_SPEC.md, ADR-001, ADR-005, ADR-007, KNOWLEDGE_LIBRARY_PLAN.md (not used: this agent reads no book or library content) |
| Facts cited | RESEARCH_LOG YT-02 (search.list own bucket, 100 calls/day; call costs), YT-03 (quota reset at midnight PT), YT-05 (granular buckets), YT-09 (inauthentic content), YT-11 (quota extension audit), IN-02/IN-03 (price-data lag; forward-direction ban), PR-01/PR-02/PR-03 (LLM models, batch and caching, API vs subscription), INF-01/03/04 (shared VPS, resource caps), INF-05 (queue), INF-11 (RLS). Facts verified for this blueprint and **not yet in the log**: §12.2 (proposed entries) |
| Marking | Every section ends its first line with **MVP** (3A / 3B / 3C, GLOSSARY §6.47 tier 0–3). 3A, 3B, 3C are the owner's build stages of D1. **Every section of this blueprint is 3C unless it says otherwise** (the agent has no 3A or 3B code); 3A/3B only own the design and the golden datasets |
| Conventions | `(pending CCR)` = a contract item not in Wave A, listed in the structured return for the integrator. `REQUIRES REVIEW (Phase 1): <need>` = unknown value; none is invented. Numeric parameters are **design defaults, ESTIMATE**, held in configuration (key `trends.*`), never in code. No book text, private method, server detail or secret appears in this document |

---

## 1 Identity and mission
**MVP: 3C · Tier 0 (owner channel). Tier 1+ reuses the same code per client org; nothing in this agent is Tier 2/3-specific.**

### 1.1 Mission
Agent 02 looks outward at **public** market signals (what viewers on YouTube are watching and searching for in the channel's field and languages) and at the channel's **own authorised** analytics (read from the database, never from the API), and turns them into three kinds of output: (1) **trend discovery**: clusters of videos that serve one audience need, with measured momentum; (2) **predictive content intelligence**: a bounded, evidence-backed *content-demand* outlook (rising, steady, fading or unknown) with a computed confidence; (3) **competitor early-warning**: unusual moves of watched public channels (a breakout video, a new topic, a format shift, a series, a cadence change). It never predicts markets, prices or securities: "prediction" means the future of **audience demand for a topic**, labelled `PROJECTION`, always with its evidence and a confidence that code computes from that evidence.

### 1.2 Where it sits
Stage `s02_trends` of `CHANNEL_LONG_FORM` (24 §7.1): task `agent_02.trend_scan`, class `AI_IO`, **optional** (`required: false`), no dependency, feeding `s03_topic` "if enabled". It can also run as a scheduled system job (`NO_DELIVERABLE`, like Agents 14/15, 24 §7) so that a fresh scan exists when Agent 03 plans. In 3A the stage is absent (3A_SLICE_SPEC §1: the owner gives the topic). Downstream: Agent 03 (reads the signals), later Agent 15 and the Business Discovery Engine (evidence only), S8 (display). Neighbours never call Agent 02 directly; the orchestrator creates tasks (07 §9).

### 1.3 Authority boundaries
| Agent 02 **decides** | Agent 02 **does not decide** (owner of the decision) |
|---|---|
| which public sources to query and how many calls to spend, inside the quota and budget plan | the topic, angle, series slot or calendar (Agent 03; the owner in 3A) |
| which videos are evidence, how they group, how strong the momentum is (code), and the confidence (code formula) | whether a topic is allowed to be published (Agents 03, 05, 06 at planning, writing, claims; **Agent 16 is the sole final authority**, plan Q5) |
| whether a signal is **screened** `CLEAR`, `REFRAME_AS_EDUCATION` or `EXCLUDED` as advisory input (the screen can only be tightened by code, never loosened) | niche choice and ranking (17 §2 and `agent_02.niche_score` (pending CCR, §2.4); the owner decides) |
| whether a signal *qualifies for the topic pool* (deterministic rule, trending alone never qualifies) | any market, price, index or security forecast: **none is ever produced** (FIN-R3, FIN-R13) |
| the retention class of its stored public data (30 days maximum) | budgets, controls, approvals, credentials (S4, S8, S7, S6); job routing, retries, revision loops (orchestrator, 07 §9) |
It never creates tasks, never approves, never spends outside `resource_budget` and the quota plan, never writes outside its tables, never scrapes or uses an unofficial endpoint, never reads comments or any personal data of viewers, never uses OAuth (own analytics come from `analytics_snapshots` written by Agent 14), never uploads (D1), and gives the model **no tools**: the LLM returns JSON that code validates (08 §5.3).

### 1.4 Success criteria (measurable; targets are config; calibration in 3C)
| ID | Criterion | Measure |
|---|---|---|
| SC-1 | Every returned signal and warning carries at least one evidence item with `raw_ref` and `raw_sha256` that resolves in the tenant's storage | 100 % (deterministic, blocking) |
| SC-2 | No cross-tenant or cross-channel read or write; no shared cache of search results between tenants | 0 occurrences in the tenancy suite and in production logs |
| SC-3 | No record from a source outside the public/authorised list (§19.3) reaches clustering or the model | 0 (filter P2; also a refusal rule in both prompts) |
| SC-4 | No signal text contains a market forecast, price view, buy/sell/hold wording, recommendation, URL or title copy of 40 characters or more | 0 (checks S5–S7, C5–C6) |
| SC-5 | Every `confidence` and every `opportunity.score` is reproducible by the §6 formulas from the stored components and weights version | 100 % (recomputed in CI replay) |
| SC-6 | No YouTube call without a prior quota reservation; no tenant exceeds its configured daily share; platform buckets never exceeded by this agent | 0 breaches (§12.3) |
| SC-7 | No stored public API data (raw, features, output, memory pointer) is older than 30 days | 0 (retention job + CHECK on config; §19.5) |
| SC-8 | Outlook calibration: share of `RISING` outlooks whose later paired ratio is at least the rising threshold, per confidence band | measured in 3C once ≥ 8 scans per channel exist; thresholds **REQUIRES REVIEW (3C): owner sets after the first measurement** (no significance claim without data, directive §3.3 learning loop) |
| SC-9 | Cost of a scan stays within `resource_budget` | 0 breaches; breach ⇒ suspend (09, D1) |
| SC-10 | Replays create no duplicate memory pointer and spend no quota twice | 1 pointer per (job, iteration); 0 repeated paid calls (idempotency scope `trend.fetch`, pending CCR) |

---

## 2 Functional requirements
**MVP: all 3C unless marked. Tier 0.**

### 2.1 Task types
| Task type | Status | Purpose | Trigger | MVP |
|---|---|---|---|---|
| `agent_02.trend_scan` | canonical (24 §3.2: "optional topic signals with evidence") | one scan: trend discovery, predictive outlook and/or competitor early-warning, selected by `payload.scan_modes` | (a) orchestrator creates it when stage `s02_trends` becomes ready in a job whose production type enables it; (b) scheduled system job, interval from config (`trends.schedule.interval`), placed in the night window by default (06); (c) owner "scan now" request (S8 → orchestrator) | 3C |
| `agent_02.niche_score` | **pending CCR** (named in 17_BUSINESS_PLAN §2.4 and §15, not defined in Wave A) | Business Discovery Engine scoring (§1B.1) — see §2.4; **not designed beyond its interface here** | owner request | 3C (late) |
No other task type is created. Modes are payload values, not task types (§7.1).

### 2.2 Requirements
| ID | Requirement | Why | When / trigger | Inputs → outputs | Dependants | MVP |
|---|---|---|---|---|---|---|
| FR-1 | Validate the task (envelope, tenant context, payload schema, channel language and category equal the `channels` row, `agent_enabled.agent_02` control) before any external call | tenant isolation, fail closed | every task | task input → accept or `REJECTED` | all | 3C |
| FR-2 | Reuse a recent scan when allowed: if `reuse = ALLOW_CACHE` and the channel's `trend.scan.latest` pointer is younger than `trends.cache.reuse_ttl_ms`, return it (`coverage_status = CACHED`) without any API call | save quota and cost | before planning | memory pointer → output | Agent 03 | 3C |
| FR-3 | Plan the collection from seed topics, regions, languages, modes and the quota/budget room (§6.7) | stay inside YT-02 buckets | after FR-2 | payload + quota state → plan | FR-4 | 3C |
| FR-4 | Collect public data through the YouTube Data API only: `search.list` per seed topic (SEARCH bucket), `videos.list` for statistics, `videos.list chart=mostPopular` per region (optional), and for watched competitors `channels.list` (once, cached) + `playlistItems.list` + `videos.list` | evidence for trends and competitors | after FR-3 | plan → raw blobs | FR-5 | 3C |
| FR-5 | Filter and normalise: public/authorised source rule, forbidden-field stripping, title sanitising, language tagging from API fields (`und` when absent), exclude-terms, de-duplication by video ID, region/language filter | privacy, injection control | after FR-4 | raw → item list | FR-6 | 3C |
| FR-6 | Compute features in code: views per hour, cohort percentile per query group, baseline, anomalies per competitor (§6.3) | numbers never come from the model | after FR-5 | items → features | FR-7, FR-8 | 3C |
| FR-7 | LLM step 1 `synthesis`: cluster items by audience need across Marathi, Hindi and English; interpretation; intent; seed match; advisory screen (prompt `trend_scan_synthesis.v1`) | semantic grouping of multilingual titles is not a rule | mode TREND_DISCOVERY or PREDICTIVE_INTELLIGENCE | features → clusters | FR-9 | 3C |
| FR-8 | LLM step 2 `competitor`: label flagged anomalies, relevance, advisory screen (prompt `trend_scan_competitor.v1`) | meaning of an anomaly (new topic vs known topic) needs reading titles | mode COMPETITOR_WATCH | anomalies → warnings | FR-9 | 3C |
| FR-9 | Score in code: cluster metrics, trajectory from paired snapshots, confidence with caps, opportunity score with published weights, topic-pool qualification, code-side lexical screen that can only tighten (§6) | explainable, reproducible, no over-claim | after FR-7/8 | clusters + history → signals | FR-10 | 3C |
| FR-10 | Assemble the output, write raw/feature blobs and the memory pointer (`CHANNEL` scope, `expires_at` ≤ 30 days), record cost and quota ledger rows, emit audit and metrics | durable, auditable, minimal | end | signals → output | Agent 03, S8 | 3C |
| FR-11 | Early-warning of **own-channel** movement from `analytics_snapshots` (authorised data, 3C after Agent 14): used only as a prior (own-channel velocity), never exported | "authorised data" in the directive | mode PREDICTIVE_INTELLIGENCE, if Agent 14 data exists | DB rows → priors | FR-9 | 3C (needs Agent 14) |
| FR-12 | Never exceed quota or budget: reserve before each call, settle after, stop and degrade to partial coverage (§12.3, §18) | rule 8, YT-02 | continuous | — | S4, 13, 14 | 3C |
| FR-13 | Idempotent resume after any crash from checkpoints without repeating a paid call (§16) | 07 §10 | resume | checkpoint → continue | orchestrator | 3C |
| FR-14 | Publish the scoring weights and component values with every signal (`weights_version`, `confidence_components`, `opportunity.breakdown`) | directive §1B.1: publish weights and evidence | every output | — | owner, Agent 03 | 3C |

**Product decision recorded here (competitor early-warning).** A competitor breakout on a topic the channel may not cover (for example a call-style video) is **still reported** as a warning, because the competitor's behaviour is the early warning, but its screen is `EXCLUDED`, its relevance is `LOW`, and it can never enter the topic pool. The owner may reverse this by a CCR.

### 2.3 Out of scope (explicit)
Topic or title writing; any market, price or security view; named-security tips; comment, sentiment or viewer-level analysis (S1 Audience Intelligence is aggregate and owned by 14); scraping, unofficial endpoints (including search auto-complete) and any platform other than YouTube (no other source is in RESEARCH_LOG: `REQUIRES REVIEW (Phase 1)` before one is added by ADR); Google Trends until the API leaves alpha for this account (§12.1); any OAuth flow; any upload; any claim about competitors' revenue, subscribers or private analytics; automatic copying of a competitor's video (originality gates belong to S2 and Agent 16, YT-09).

### 2.4 Business Discovery Engine hook (`agent_02.niche_score`, pending CCR)
Directive §1B.1 gives niche scoring to Agent 02 + 15; 17_BUSINESS_PLAN §2 specifies the method (criteria, owner-set weights with no shipped default, knock-out rules, ranked shortlist, evidence per score). This blueprint adds only the constraints that follow from Agent 02's design: (1) arithmetic and ranking are **deterministic code**, no LLM; (2) a trend signal from `agent_02.trend_scan` is **never a scoring criterion and cannot raise a score** (17 §2.3 rule 1); (3) it reuses this agent's quota guard, collectors, evidence store, tenancy and retention rules; (4) storage is `niche_scores` (pending CCR, 17 §15) — Agent 02 creates no table. Everything else is owned by 17 and the Agent 15 blueprint. **MVP: 3C (late), Tier 0.**

### 2.5 Suggestions for the owner (not built; owner rule D.1, A.5)
One-tap "dismiss" or "pin" of a signal in S8; a weekly digest through S7 notifications; a per-signal "why" panel showing the component bars (momentum, fit, gap, evidence, trajectory) with colour by meaning. None is in scope until the owner decides.

---

## 3 Non-functional requirements
**MVP: 3C. Values are design defaults (ESTIMATE) until measured in 3C.**
| Area | Requirement |
|---|---|
| Latency | a scan of ≤ 300 items and ≤ 10 competitors finishes within `max_wall_ms` (design 600,000 ms); a cache hit within 2,000 ms |
| Throughput | one scan per channel at a time; ≤ 2 scans in parallel platform-wide (`trends.max_parallel_scans`); typical load one scan per channel per `trends.schedule.interval` |
| Cost | no LLM price is written here (09 applies PR-01); bounded by `resource_budget.max_cost_micros`, `max_llm_calls` (design 12), tier chosen per ADR-007 |
| Quota | per scan ≤ `trends.youtube.search_calls_per_scan` (10) SEARCH calls and ≤ `trends.youtube.default_units_per_scan` (60) DEFAULT units; per tenant per PT day ≤ 40 SEARCH and ≤ 500 DEFAULT units; the platform buckets are 100 and 10,000 per day (YT-02) and are shared with Agents 12, 13 and 14 |
| Determinism | all arithmetic pure and unit-tested; LLM temperature from config (design 0); same input + same recorded model output ⇒ same signals |
| Idempotency | every paid call and every write has an idempotency key (03 §9); replay-safe |
| Availability | optional stage: its failure never blocks a production job (24 §3.1); degraded (`PARTIAL`) output is preferred to no output when a minimum of items exists (§18) |
| Reliability of the claim | a signal is never shown without its evidence, confidence and weights version |
| Privacy | no personal data collected; titles ≤ 120 characters; channel names replaced by pseudonymous refs before any LLM call (§19.4) |
| Tenant isolation | absolute; §19.1 |
| Language | inputs Marathi, Hindi, English and mixed script; outputs in English with optional `label_local` in the channel language; UI strings elsewhere |
| Retention | ≤ 30 days for stored public API data (§12.2, §19.5) |
| Observability | §22 |
| Portability | no provider or model in code; YouTube reader behind a Protocol with a fake and recorded fixtures (27 §8) |

---

## 4 Internal architecture
**MVP: 3C · Tier 0.** The task is a code-controlled workflow; the model has two bounded steps and no tools.
```mermaid
flowchart TD
  IN[Task input and envelope] --> V[P1 validate: tenant, schema, channel row, control]
  V -->|invalid| REJ[REJECTED or FAILED with 07 code]
  V --> CH{ALLOW_CACHE and fresh pointer?}
  CH -->|yes| OUTC[Output CACHED]
  CH -->|no| PL[Plan: seeds, regions, quota and budget room]
  PL --> QR[Reserve quota and budget per call]
  QR --> COL[Collect via YouTubeSignalSource: search, videos, chart, competitors]
  COL --> CK1[(Checkpoint + raw blobs)]
  COL --> FIL[Filter and normalise: public/authorised rule, strip fields, sanitise titles]
  FIL --> FEA[Features in code: velocity, percentile, baseline, anomalies]
  FEA --> SYN[[LLM step synthesis]]
  FEA --> CMP[[LLM step competitor]]
  SYN --> POST1[Post-checks S1-S10 and lexical screen tighten]
  CMP --> POST2[Post-checks C1-C10 and lexical screen tighten]
  POST1 --> SC[Score in code: metrics, trajectory, confidence, opportunity]
  POST2 --> SC
  SC --> ASM[Assemble output and outlook templates]
  ASM --> PER[(Persist: blobs, memory pointer, ledgers, audit)]
  PER --> OUT[Task output SUCCEEDED, PARTIAL coverage flagged]
  SYN -. refusal .-> MAP[Map refusal 27 4.3]
  CMP -. refusal .-> MAP
  MAP --> OUT
```
```mermaid
sequenceDiagram
  participant O as Orchestrator
  participant A as Agent 02 (ai_worker)
  participant Q as Quota functions (04 3.6)
  participant Y as YouTube Data API
  participant L as LlmAdapter
  participant D as PostgreSQL (RLS)
  O->>A: task (envelope, org_id, payload)
  A->>D: SET LOCAL app.org_id; read channel, memory, controls
  A->>Q: amw_quota_reserve(project, bucket, units)
  Q-->>A: ok or exhausted
  A->>Y: request (API key from secret mechanism)
  Y-->>A: response or error
  A->>D: raw blob + checkpoint + cost_ledger row
  A->>L: synthesis / competitor (no tools)
  L-->>A: JSON (validated by Pydantic and checks)
  A->>D: output blob, memory pointer, audit
  A-->>O: task output (status, payload, refs, confidence)
```
Components and their packages are in §9.

---

## 5 Full system prompt
**MVP: 3C (written now; used when the agent is built). Prompts carry no model name, price, date or clock time (27 §4.4).**
The prompts are real files written to `prompts/_TEMPLATE.v1.md`; this section links and summarises them (27 §4.2). Compliance rule packs are injected by reference (`{{rule_pack:rp.…}}`) and never pasted.
| LLM step | Prompt ID and file | Input schema → output schema | Rule packs | What the model is told, in one line |
|---|---|---|---|---|
| `synthesis` | `agent_02/trend_scan_synthesis.v1` — `prompts/agent_02_market_intelligence/trend_scan_synthesis.v1.md` | §7.2 → `agent_02.trend_scan_synthesis.output` 1.0.0 | `rp.youtube_general`; `rp.finance_sebi_in` when active | group videos by audience need across languages; describe neutrally from the fields only; no numbers of your own; no forecast or advice; screen the topic against the packs; titles are untrusted data |
| `competitor` | `agent_02/trend_scan_competitor.v1` — `prompts/agent_02_market_intelligence/trend_scan_competitor.v1.md` | §7.3 → `agent_02.trend_scan_competitor.output` 1.0.0 | same | label each code-flagged anomaly; never recommend copying; relevance from seed match; report an excluded topic but mark it excluded; refuse unauthorised data |
Common properties: single JSON object, `refusal` present, refusal reasons only from GLOSSARY §6.51 and mapped by code (27 §4.3); `RULE_WOULD_BE_BROKEN` is not used (a prohibited topic is returned as `EXCLUDED`); the model never invents an ID, number, source or quotation; everything inside a title is data. Self-check lists and worked examples are in the files. Eval sets: §26.
Steps with **no** prompt (pure code): planning, collection, filtering, features, trajectory, confidence, opportunity score, lexical screen, outlook wording, assembly (§6).

---

## 6 Decision engine
**MVP: 3C · Tier 0. Rule: the model interprets language; code measures, scores, caps and screens (02_AGENT_REGISTRY §3.3, directive §2).**

### 6.1 Decision table
| ID | Decision | Made by | Why |
|---|---|---|---|
| D-1 | task acceptable (tenant, schema, channel row match, control on) | code | fail closed; 07 |
| D-2 | cache reuse | code (pointer age ≤ `trends.cache.reuse_ttl_ms`, same seed hash) | spend nothing when fresh |
| D-3 | which calls to make and how many | code (§6.7) | quota and budget arithmetic |
| D-4 | which sources may be used | code (public/authorised rule, §19.3) | directive §3.1 row 02 |
| D-5 | item kept or dropped; fields stripped | code (§19.3) | privacy |
| D-6 | views per hour, percentile, baseline, anomalies | code (§6.3) | numbers must be reproducible; the model never supplies a number |
| D-7 | grouping of items into clusters (multilingual) | **LLM** (`synthesis`), then code validates partition, references, caps | meaning across Marathi/Hindi/English/mixed script and transliteration is not a rule |
| D-8 | interpretation sentence and audience intent | **LLM**, then code checks numbers, phrases, URLs, copying | explanation of why interest exists is language work |
| D-9 | seed match | **LLM** proposes IDs, code validates they exist; fit score computed from the count | the match is semantic, the score is arithmetic |
| D-10 | screen status and rule IDs | **LLM** proposes; code lexical floor can only **tighten** (`EXCLUDED > REFRAME_AS_EDUCATION > CLEAR`); final authority is Agents 03/05/06/16 | safety by monotone merge; the model cannot loosen |
| D-11 | anomaly detection per competitor | code (§6.3) | thresholds against the competitor's own baseline |
| D-12 | anomaly label (new topic vs known), relevance, description | **LLM** (`competitor`), then code checks (C1–C10) | needs reading titles against history |
| D-13 | momentum, saturation, trajectory | code (§6.3–6.4) | arithmetic over stored snapshots |
| D-14 | confidence and band | code (§6.5) | no model-made probabilities; caps prevent over-claim |
| D-15 | opportunity score and topic-pool qualification | code (§6.6) | weights published and configurable; trending alone never qualifies |
| D-16 | outlook sentence | code templates (§6.9) | a sentence that can never say more than the numbers say |
| D-17 | partial vs complete vs suspend | code (§18) | quota is a hard constraint |
| D-18 | retention date | code (≤ 30 days, hard validator) | Developer Policies (§12.2) |

### 6.2 Why this split
Language-dependent steps (D-7…D-10, D-12) have no practical rule set across three languages and two scripts, so they are model steps with schema-validated output and a deterministic post-check that can only reject or tighten. Everything that produces a number, a date, a limit or a safety floor is code with golden tests (`deterministic_core`). The registry summary lists "prediction wording" under the LLM; this blueprint deliberately moves the **outlook sentence into code templates** (D-16) because a model-worded forecast can over-claim; the model still writes the *interpretation*. **Deviation noted for the integrator (02_AGENT_REGISTRY §3.3 row 02).**

### 6.3 Features (pure functions; reference values in `deterministic_core`)
Let `now` be the retrieval instant of the scan and `age_hours = max(hours since publication, min_age_hours)`.
| Name | Definition |
|---|---|
| `vph` | `views / max(age_hours, min_age_hours)`, rounded to 3 decimals |
| `cohort_percentile` | within one query group: `(count(vph_c < vph) + 0.5 · count(vph_c = vph)) / n`; `null` when `n < min_cohort` |
| `baseline_vph` | median `vph` of all items kept in the scan |
| `momentum_ratio` (cluster) | `median(vph of members) / baseline_vph`; `null` if the baseline is 0 |
| `age_trend_ratio` (cluster) | median `vph` of the youngest third of members ÷ median `vph` of the oldest third; needs ≥ 6 members; `null` otherwise or if the older median is 0 |
| `breadth_channels` | number of distinct channel refs among members |
| `saturation_index` | `min(1, member_count / saturation_full)` |
| competitor `views_vs_baseline` | `views / baseline.median_views` of that competitor (baseline from its own recent uploads; `sample_size` stored) |
| competitor anomaly kinds | `BREAKOUT_VIDEO` if `views_vs_baseline ≥ trends.competitor.breakout_ratio`; `CADENCE_CHANGE` if the ratio of recent uploads per week to baseline uploads per week is ≥ `cadence_hi` or ≤ `cadence_lo`; `NEW_TOPIC_CANDIDATE` if no title in `history_titles` shares the upload's topic key (normalised content tokens, Jaccard < `topic_overlap_max`); `FORMAT_SHIFT_CANDIDATE` if the share of one `duration_bucket` among recent uploads differs from history by ≥ `format_shift_min`; `SERIES_CANDIDATE` if ≥ 2 recent uploads carry numbered-part markers for the same topic key |
Threshold values: §6.8 (ESTIMATE).

### 6.4 Trajectory (needs a prior scan)
Pairs are items seen in both this scan and the previous scan (`trend.scan.latest` pointer, still inside retention) with a gap of at least `trends.trajectory.min_gap_hours`. For a pair: `prev_vph = prev_views / max(prev_age, min_age_hours)`, `delta_views = views_now − views_prev`, `delta_hours` = gap. Pair ratio = `(delta_views / delta_hours) / prev_vph`. `paired_ratio` = median of pair ratios (pairs with `prev_vph ≤ 0` or `delta_hours ≤ 0` are ignored). With fewer than `min_pairs` usable pairs the trajectory is `UNKNOWN`; else `RISING` if `paired_ratio ≥ hi`, `FADING` if `≤ lo`, else `STEADY`. A first scan therefore has no outlook: that is honest, not a defect.

### 6.5 Confidence (producer confidence, 03 §5.1; never a gate on its own)
Components, each in 0–1: `E = min(1, evidence_items / E_full)`, `B = min(1, breadth_channels / B_full)`, `T = min(1, paired_items / P_full)`, `A` = agreement: for each available indicator among `momentum_ratio`, `age_trend_ratio`, `paired_ratio`, direction is `up` (≥ `up`), `down` (≤ `down`) or `flat`; `A = (count of the most common direction) / (number of available indicators)`, 0 if none (ties resolved by indicator order above). `raw = wE·E + wB·B + wT·T + wA·A`. Caps: no prior pairs ⇒ `min(raw, cap_no_history)`; only one source family (YouTube public) ⇒ `min(·, cap_single_source)`. Round to 3 decimals; band `LOW` < `band_low`, `HIGH` ≥ `band_high`, else `MEDIUM`. With a single source family and no history the confidence cannot pass 0.40; **while only YouTube public data is used it cannot pass 0.60, so `HIGH` is unreachable until a second independent source family exists** (own analytics, or Google Trends if later enabled). Task-level `confidence` = median of the signals' confidences, `null` if there is no signal.

### 6.6 Opportunity score and topic-pool rule (published weights, directive §1B.1)
`M = min(1, momentum_ratio / m_cap)` (0 if null); `F = min(1, matched_seed_count / f_full)`; `G = 1 − saturation_index`; `Ev = min(1, evidence_items / E_full)`; `D` = 1.0 RISING, 0.5 STEADY, 0.3 UNKNOWN, 0.0 FADING. `score = 100 · (wM·M + wF·F + wG·G + wEv·Ev + wD·D)`, 2 decimals, with `weights_version` (`trends.weights.vN`) and the breakdown in every signal. A signal `qualifies_for_topic_pool` only if it has **none** of the disqualifiers: `EXCLUDED_BY_SCREEN`, `NO_SEED_FIT`, `EVIDENCE_BELOW_MIN`, `BREADTH_BELOW_MIN`, `FADING`. High momentum without a seed fit never qualifies ("trending alone never qualifies", 17 §2.3). `REFRAME_AS_EDUCATION` qualifies but travels with its flag to Agent 03.

### 6.7 Quota and call plan
Inputs: number of seeds, regions, competitors, uncached competitors, chart on/off, caps and today's usage (PT day). `search_calls = min(seeds, per_scan_cap, max(0, per_day_cap − used_today))`; `videos_list_calls = ceil(search_calls · search_max_results / ids_per_call)`; `chart_calls = number of regions` if chart enabled; DEFAULT-bucket room = `min(default_per_scan, max(0, default_per_day − default_used_today))`. If chart does not fit it is dropped; search calls are reduced until `videos_list_calls + chart_calls` fit; competitors are reduced until `videos_list_calls + chart_calls + competitors + uncached + ceil(competitors · uploads_per_competitor / ids_per_call)` fits. Status `COMPLETE` (everything planned), `PARTIAL` (anything reduced), `BLOCKED` (no call possible).

### 6.8 Parameters (configuration; design defaults, ESTIMATE; a changed default regenerates `deterministic_core` expectations in the same PR)
| Key | Default | Key | Default |
|---|---|---|---|
| `trends.min_age_hours` | 1 | `trends.confidence.E_full` / `B_full` / `P_full` | 10 / 5 / 8 |
| `trends.min_cohort` | 5 | `trends.confidence.wE` / `wB` / `wT` / `wA` | 0.30 / 0.20 / 0.30 / 0.20 |
| `trends.trajectory.min_pairs` / `hi` / `lo` | 3 / 1.25 / 0.6 | `trends.confidence.cap_no_history` / `cap_single_source` | 0.40 / 0.60 |
| `trends.trajectory.min_gap_hours` | 12 | `trends.confidence.band_low` / `band_high` | 0.35 / 0.65 |
| `trends.direction.up` / `down` | 1.1 / 0.9 | `trends.opportunity.wM` / `wF` / `wG` / `wEv` / `wD` | 0.30 / 0.25 / 0.15 / 0.15 / 0.15 |
| `trends.opportunity.m_cap` / `saturation_full` / `f_full` | 3.0 / 12 / 2 | `trends.opportunity.min_evidence` / `min_breadth` | 4 / 2 |
| `trends.youtube.search_calls_per_scan` / `per_day_per_tenant` | 10 / 40 | `trends.youtube.default_units_per_scan` / `per_day_per_tenant` | 60 / 500 |
| `trends.youtube.ids_per_call` / `search_max_results` | 50 / 25 | `trends.youtube.uploads_per_competitor` | 20 |
| `trends.synthesis.max_items` / `max_clusters` | 150 / 8 | `trends.copy_guard_chars` / `trends.title_max_chars` | 40 / 120 |
| `trends.competitor.breakout_ratio` / `cadence_hi` / `cadence_lo` | 3.0 / 2.0 / 0.5 | `trends.competitor.topic_overlap_max` / `format_shift_min` | 0.2 / 0.5 |
| `trends.retention.days` (validator ≤ 30) | 30 | `trends.cache.reuse_ttl_ms` / `trends.min_items_for_scan` | 86,400,000 / 30 |
| `trends.max_parallel_scans` / `trends.max_competitors` | 2 / 20 | `trends.horizon_days_default` | 14 |
| `trends.evidence.max_per_signal` / `trends.competitor.per_call` | 10 / 5 | `trends.schedule.interval` (ISO 8601, config only) | P7D |
| `trends.synthesis.banned_phrases`, `trends.competitor.banned_phrases` | lists (config; finance packs add theirs) | `trends.lexicon.<pack>` | pattern lists per rule ID, **REQUIRES REVIEW (Phase 1)** with 13 |
Weights are published with every output as `weights_version`; changing any weight requires a new version string and, because it changes behaviour, the regression run of §26.

### 6.9 Outlook wording (code templates; English; never market words)
`RISING`: "Viewing of recent videos on this topic is running above their earlier average (ratio {paired_ratio}); outlook for the next {horizon_days} days: rising. Confidence {band} ({confidence}); basis: {evidence_items} videos from {breadth_channels} channels." `STEADY`: "… within their earlier range (ratio {paired_ratio}); outlook …: steady. …" `FADING`: "… below their earlier average (ratio {paired_ratio}); outlook …: fading. …" `UNKNOWN`: "Not enough earlier snapshots to estimate a direction (paired videos: {paired_items}); no outlook is given. Confidence {band} ({confidence})." Every outlook object carries `figure_label = PROJECTION`.

---

## 7 Input schema
**MVP: 3C · Tier 0. Schemas are JSON Schema 2020-12; the Pydantic models are generated from them (CI check, 27 §4.4).**

### 7.1 Task payload `agent_02.trend_scan.input` 1.0.0 (inside Task Input `payload.data`; envelope and `org_id`, `channel_id`, `job_id` come from 03 §3)
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:amw:schema:agent_02.trend_scan.input:1.0.0",
  "type": "object",
  "additionalProperties": false,
  "required": ["scan_modes", "channel_profile", "seed_topics", "exclude_terms", "regions", "languages", "lookback_hours", "horizon_days", "competitors", "reuse", "max_signals"],
  "properties": {
    "scan_modes": {
      "type": "array",
      "minItems": 1,
      "uniqueItems": true,
      "items": {"enum": ["TREND_DISCOVERY", "PREDICTIVE_INTELLIGENCE", "COMPETITOR_WATCH"]}
    },
    "channel_profile": {
      "type": "object",
      "additionalProperties": false,
      "required": ["language", "category", "active_rule_packs"],
      "properties": {"language": {"type": "string", "pattern": "^[a-z]{2,3}(-[A-Z]{2})?$"}, "category": {"type": "string", "pattern": "^[a-z_]{2,32}$"}, "active_rule_packs": {"type": "array", "maxItems": 8, "uniqueItems": true, "items": {"type": "string", "pattern": "^rp\\.[a-z0-9_]{2,48}$"}}}
    },
    "seed_topics": {
      "type": "array",
      "maxItems": 50,
      "items": {"type": "object", "additionalProperties": false, "required": ["seed_id", "label", "language"], "properties": {"seed_id": {"type": "string", "pattern": "^sd_[0-9]{1,3}$"}, "label": {"type": "string", "minLength": 1, "maxLength": 120}, "language": {"type": "string", "pattern": "^[a-z]{2,3}(-[A-Z]{2})?$"}}}
    },
    "exclude_terms": {
      "type": "array",
      "maxItems": 50,
      "items": {"type": "string", "maxLength": 60}
    },
    "regions": {
      "type": "array",
      "minItems": 1,
      "maxItems": 5,
      "uniqueItems": true,
      "items": {"type": "string", "pattern": "^[A-Z]{2}$"}
    },
    "languages": {
      "type": "array",
      "minItems": 1,
      "maxItems": 5,
      "uniqueItems": true,
      "items": {"type": "string", "pattern": "^[a-z]{2,3}(-[A-Z]{2})?$"}
    },
    "lookback_hours": {
      "type": "integer",
      "minimum": 24,
      "maximum": 2160
    },
    "horizon_days": {
      "type": "integer",
      "minimum": 1,
      "maximum": 90
    },
    "competitors": {
      "type": "array",
      "maxItems": 20,
      "items": {"type": "object", "additionalProperties": false, "required": ["competitor_ref", "external_channel_id", "label"], "properties": {"competitor_ref": {"type": "string", "pattern": "^cmp_[0-9]{1,3}$"}, "external_channel_id": {"type": "string", "pattern": "^UC[A-Za-z0-9_-]{22}$"}, "label": {"type": "string", "maxLength": 60}}}
    },
    "reuse": {
      "enum": ["ALLOW_CACHE", "FORCE_REFRESH"]
    },
    "max_signals": {
      "type": "integer",
      "minimum": 1,
      "maximum": 50
    }
  }
}
```
Notes. `scan_modes` selects the work (`TREND_DISCOVERY`: clusters and metrics; `PREDICTIVE_INTELLIGENCE`: adds trajectory, confidence and outlook; `COMPETITOR_WATCH`: the `competitor` step). `channel_profile` is built by the orchestrator from the `channels` row and **re-read and compared by Agent 02** (mismatch ⇒ `PERMANENT.INPUT_INVALID`). `seed_topics` come from the owner or Agent 03's pillars through a `MEMORY` context ref (**REQUIRES REVIEW (Agent 03 blueprint)**: key name). `competitors` come from the tenant's own `memory_items` key `trend.competitor_watchlist` (written only by a human actor, §19.2). `lookback_hours` and `horizon_days` are operational parameters (not chart logic, owner rule C.4). Task input is time-agnostic: no calendar dates.

### 7.2 Step input `agent_02.trend_scan_synthesis.input` 1.0.0 (built by code from §7.1 after filters P1–P6; sent to the model)
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:amw:schema:agent_02.trend_scan_synthesis.input:1.0.0",
  "type": "object",
  "additionalProperties": false,
  "required": ["channel_language", "channel_category", "active_rule_packs", "seed_topics", "exclude_terms", "max_clusters", "items"],
  "properties": {
    "channel_language": {
      "type": "string",
      "pattern": "^[a-z]{2,3}(-[A-Z]{2})?$"
    },
    "channel_category": {
      "type": "string",
      "pattern": "^[a-z_]{2,32}$"
    },
    "active_rule_packs": {
      "type": "array",
      "maxItems": 8,
      "uniqueItems": true,
      "items": {"type": "string", "pattern": "^rp\\.[a-z0-9_]{2,48}$"}
    },
    "seed_topics": {
      "type": "array",
      "maxItems": 50,
      "items": {"type": "object", "additionalProperties": false, "required": ["seed_id", "label"], "properties": {"seed_id": {"type": "string", "pattern": "^sd_[0-9]{1,3}$"}, "label": {"type": "string", "minLength": 1, "maxLength": 120}}}
    },
    "exclude_terms": {
      "type": "array",
      "maxItems": 50,
      "items": {"type": "string", "maxLength": 60}
    },
    "max_clusters": {
      "type": "integer",
      "minimum": 1,
      "maximum": 20
    },
    "items": {
      "type": "array",
      "maxItems": 300,
      "items": {"type": "object", "additionalProperties": false, "required": ["item_id", "title", "channel_ref", "age_hours", "views", "views_per_hour", "cohort_percentile", "language", "query_group", "source"], "properties": {"item_id": {"type": "string", "pattern": "^it_[0-9]{1,4}$"}, "title": {"type": "string", "minLength": 1, "maxLength": 120}, "channel_ref": {"type": "string", "pattern": "^ch_[0-9]{1,4}$"}, "age_hours": {"type": "number", "minimum": 0}, "views": {"type": "integer", "minimum": 0}, "views_per_hour": {"type": "number", "minimum": 0}, "cohort_percentile": {"oneOf": [{"type": "number", "minimum": 0, "maximum": 1}, {"type": "null"}]}, "language": {"oneOf": [{"type": "string", "pattern": "^[a-z]{2,3}(-[A-Z]{2})?$"}, {"const": "und"}]}, "query_group": {"type": "string", "pattern": "^qg_[0-9]{1,3}$"}, "source": {"type": "string", "maxLength": 32}}}
    }
  }
}
```
`item_id` and `channel_ref` are per-scan pseudonyms (`it_N`, `ch_N`); the real video and channel IDs never reach the model. `source` stays an open string on purpose so that a non-allowed value can be refused (and is normally removed earlier by P2).

### 7.3 Step input `agent_02.trend_scan_competitor.input` 1.0.0
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:amw:schema:agent_02.trend_scan_competitor.input:1.0.0",
  "type": "object",
  "additionalProperties": false,
  "required": ["channel_language", "channel_category", "active_rule_packs", "seed_topics", "competitors"],
  "properties": {
    "channel_language": {
      "type": "string",
      "pattern": "^[a-z]{2,3}(-[A-Z]{2})?$"
    },
    "channel_category": {
      "type": "string",
      "pattern": "^[a-z_]{2,32}$"
    },
    "active_rule_packs": {
      "type": "array",
      "maxItems": 8,
      "uniqueItems": true,
      "items": {"type": "string", "pattern": "^rp\\.[a-z0-9_]{2,48}$"}
    },
    "seed_topics": {
      "type": "array",
      "maxItems": 50,
      "items": {"type": "object", "additionalProperties": false, "required": ["seed_id", "label"], "properties": {"seed_id": {"type": "string", "pattern": "^sd_[0-9]{1,3}$"}, "label": {"type": "string", "minLength": 1, "maxLength": 120}}}
    },
    "competitors": {
      "type": "array",
      "maxItems": 20,
      "items": {"type": "object", "additionalProperties": false, "required": ["competitor_ref", "label", "source_class", "baseline", "history_titles", "recent_uploads", "anomalies"], "properties": {"competitor_ref": {"type": "string", "pattern": "^cmp_[0-9]{1,3}$"}, "label": {"type": "string", "maxLength": 60}, "source_class": {"enum": ["PUBLIC", "AUTHORISED_OWN", "UNAUTHORISED"]}, "baseline": {"type": "object", "additionalProperties": false, "required": ["median_views", "uploads_per_week", "sample_size"], "properties": {"median_views": {"type": "number", "minimum": 0}, "uploads_per_week": {"type": "number", "minimum": 0}, "sample_size": {"type": "integer", "minimum": 0}}}, "history_titles": {"type": "array", "maxItems": 40, "items": {"type": "string", "maxLength": 120}}, "recent_uploads": {"type": "array", "maxItems": 40, "items": {"type": "object", "additionalProperties": false, "required": ["item_id", "title", "age_hours", "views", "views_vs_baseline", "duration_bucket", "language"], "properties": {"item_id": {"type": "string", "pattern": "^cu_[0-9]{1,4}$"}, "title": {"type": "string", "minLength": 1, "maxLength": 120}, "age_hours": {"type": "number", "minimum": 0}, "views": {"type": "integer", "minimum": 0}, "views_vs_baseline": {"oneOf": [{"type": "number", "minimum": 0}, {"type": "null"}]}, "duration_bucket": {"enum": ["SHORT", "MID", "LONG"]}, "language": {"oneOf": [{"type": "string", "pattern": "^[a-z]{2,3}(-[A-Z]{2})?$"}, {"const": "und"}]}}}}, "anomalies": {"type": "array", "maxItems": 20, "items": {"type": "object", "additionalProperties": false, "required": ["anomaly_id", "kind", "item_ids", "metric", "value"], "properties": {"anomaly_id": {"type": "string", "pattern": "^an_[0-9]{1,3}$"}, "kind": {"enum": ["BREAKOUT_VIDEO", "CADENCE_CHANGE", "NEW_TOPIC_CANDIDATE", "FORMAT_SHIFT_CANDIDATE", "SERIES_CANDIDATE"]}, "item_ids": {"type": "array", "maxItems": 10, "items": {"type": "string", "pattern": "^cu_[0-9]{1,4}$"}}, "metric": {"type": "string", "maxLength": 40}, "value": {"type": "number"}}}}}}
    }
  }
}
```

### 7.4 Context references used (03 §3.2 `context_refs`)
| purpose | URI form | Used for |
|---|---|---|
| `MEMORY` | `amw-entity://org_…/memory_item/mem_…` | watch-list, previous scan pointer, seed topics |
| `RULE_PACK` | `amw-entity://org_…/rule_pack/…` (platform rows `platform`) | packs named in `active_rule_packs` |
| `COMPLIANCE_PROFILE` | tenant URI | confirms which packs apply to the channel |
Every URI must belong to `org_id` or `platform` (03 §8); anything else ⇒ `PERMANENT.CROSS_TENANT_REF` before any read.

### 7.5 Validation order (03 §7.1)
V1 envelope and task input schema → V2 `agent_id = agent_02` and task type registered → V3 `org_id` equal across envelope, input, DB context and every ref (`PERMANENT.TENANT_MISMATCH`) → V4 org active (`PERMANENT.TENANT_INACTIVE`) → V5 payload schema and semantic checks (regions ISO, languages BCP 47, ≤ `trends.max_competitors`, seeds unique, `external_channel_id` pattern) → V6 channel row equals `channel_profile` → V7 control `agent_enabled.agent_02` and no emergency stop → V8 budget pre-check → V9 secrets present (startup check, 08 §3.1). Failures use 07 §2 codes; rejections at validation have `attempt_no = 0`.

---

## 8 Output schema
**MVP: 3C · Tier 0.**

### 8.1 Task output payload `agent_02.trend_scan.output` 1.0.0
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:amw:schema:agent_02.trend_scan.output:1.0.0",
  "type": "object",
  "additionalProperties": false,
  "required": ["scan_summary", "signals", "competitor_warnings", "excluded_topics", "weights_version", "retention"],
  "properties": {
    "scan_summary": {
      "type": "object",
      "additionalProperties": false,
      "required": ["modes_run", "coverage_status", "cache_hit", "sources", "items_collected", "items_after_filter", "prior_snapshots_used"],
      "properties": {"modes_run": {"type": "array", "items": {"enum": ["TREND_DISCOVERY", "PREDICTIVE_INTELLIGENCE", "COMPETITOR_WATCH"]}}, "coverage_status": {"enum": ["COMPLETE", "PARTIAL", "CACHED"]}, "cache_hit": {"type": "boolean"}, "sources": {"type": "array", "items": {"type": "object", "additionalProperties": false, "required": ["source", "status", "items", "quota_units"], "properties": {"source": {"enum": ["YT_SEARCH", "YT_MOST_POPULAR", "YT_COMPETITOR_UPLOAD", "OWN_ANALYTICS"]}, "status": {"enum": ["OK", "SKIPPED_QUOTA", "SKIPPED_BUDGET", "SKIPPED_DISABLED", "ERROR"]}, "items": {"type": "integer", "minimum": 0}, "quota_units": {"type": "integer", "minimum": 0}}}}, "items_collected": {"type": "integer", "minimum": 0}, "items_after_filter": {"type": "integer", "minimum": 0}, "prior_snapshots_used": {"type": "integer", "minimum": 0}}
    },
    "signals": {
      "type": "array",
      "maxItems": 50,
      "items": {"$ref": "#/$defs/signal"}
    },
    "competitor_warnings": {
      "type": "array",
      "maxItems": 40,
      "items": {"$ref": "#/$defs/competitor_warning"}
    },
    "excluded_topics": {
      "type": "array",
      "maxItems": 50,
      "items": {"type": "object", "additionalProperties": false, "required": ["label", "screen"], "properties": {"label": {"type": "string", "maxLength": 80}, "screen": {"$ref": "#/$defs/screen"}}}
    },
    "weights_version": {
      "type": "string",
      "pattern": "^trends\\.weights\\.v[0-9]{1,3}$"
    },
    "retention": {
      "type": "object",
      "additionalProperties": false,
      "required": ["evidence_expires_after_days"],
      "properties": {"evidence_expires_after_days": {"type": "integer", "minimum": 1, "maximum": 30}}
    }
  },
  "$defs": {
    "screen": {
      "type": "object",
      "additionalProperties": false,
      "required": ["status", "rule_ids", "note"],
      "properties": {"status": {"enum": ["CLEAR", "REFRAME_AS_EDUCATION", "EXCLUDED"]}, "rule_ids": {"type": "array", "maxItems": 13, "uniqueItems": true, "items": {"type": "string", "pattern": "^[A-Z]{2,8}-R[0-9]{1,3}$"}}, "note": {"type": "string", "maxLength": 200}},
      "if": {"properties": {"status": {"const": "CLEAR"}}},
      "then": {"properties": {"rule_ids": {"maxItems": 0}}}
    },
    "signal": {
      "type": "object",
      "additionalProperties": false,
      "required": ["signal_id", "label", "label_local", "interpretation", "audience_intent", "matched_seed_ids", "metrics", "outlook", "confidence", "confidence_band", "confidence_components", "caps_applied", "evidence", "screen", "opportunity", "qualifies_for_topic_pool", "disqualifiers"],
      "properties": {"signal_id": {"type": "string", "pattern": "^sg_[0-9]{1,3}$"}, "label": {"type": "string", "maxLength": 80}, "label_local": {"oneOf": [{"type": "string", "maxLength": 80}, {"type": "null"}]}, "interpretation": {"type": "string", "maxLength": 300}, "audience_intent": {"enum": ["LEARN_CONCEPT", "HOW_TO", "NEWS_EVENT", "OPINION_REACTION", "ENTERTAINMENT", "OTHER"]}, "matched_seed_ids": {"type": "array", "items": {"type": "string", "pattern": "^sd_[0-9]{1,3}$"}}, "metrics": {"type": "object", "additionalProperties": false, "required": ["evidence_items", "breadth_channels", "momentum_ratio", "age_trend_ratio", "saturation_index", "paired_items", "paired_ratio"], "properties": {"evidence_items": {"type": "integer", "minimum": 0}, "breadth_channels": {"type": "integer", "minimum": 0}, "momentum_ratio": {"oneOf": [{"type": "number"}, {"type": "null"}]}, "age_trend_ratio": {"oneOf": [{"type": "number"}, {"type": "null"}]}, "saturation_index": {"type": "number", "minimum": 0, "maximum": 1}, "paired_items": {"type": "integer", "minimum": 0}, "paired_ratio": {"oneOf": [{"type": "number"}, {"type": "null"}]}}}, "outlook": {"oneOf": [{"type": "null"}, {"type": "object", "additionalProperties": false, "required": ["trajectory", "horizon_days", "statement", "figure_label"], "properties": {"trajectory": {"enum": ["RISING", "STEADY", "FADING", "UNKNOWN"]}, "horizon_days": {"type": "integer", "minimum": 1}, "statement": {"type": "string", "maxLength": 300}, "figure_label": {"const": "PROJECTION"}}}]}, "confidence": {"oneOf": [{"type": "number", "minimum": 0, "maximum": 1}, {"type": "null"}]}, "confidence_band": {"oneOf": [{"enum": ["LOW", "MEDIUM", "HIGH"]}, {"type": "null"}]}, "confidence_components": {"oneOf": [{"type": "null"}, {"type": "object", "additionalProperties": false, "required": ["evidence", "breadth", "history", "agreement"], "properties": {"evidence": {"type": "number"}, "breadth": {"type": "number"}, "history": {"type": "number"}, "agreement": {"type": "number"}}}]}, "caps_applied": {"type": "array", "items": {"enum": ["NO_HISTORY", "SINGLE_SOURCE"]}}, "evidence": {"type": "array", "minItems": 1, "maxItems": 100, "items": {"type": "object", "additionalProperties": false, "required": ["evidence_id", "source", "external_ref", "retrieved_at", "raw_ref", "raw_sha256", "views_at_retrieval", "age_hours_at_retrieval"], "properties": {"evidence_id": {"type": "string", "pattern": "^ev_[0-9]{1,4}$"}, "source": {"enum": ["YT_SEARCH", "YT_MOST_POPULAR", "YT_COMPETITOR_UPLOAD", "OWN_ANALYTICS"]}, "external_ref": {"type": "string", "pattern": "^[A-Za-z0-9_-]{11}$"}, "retrieved_at": {"type": "string", "format": "date-time", "pattern": "Z$"}, "raw_ref": {"type": "string", "maxLength": 1024}, "raw_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}, "views_at_retrieval": {"type": "integer", "minimum": 0}, "age_hours_at_retrieval": {"type": "number", "minimum": 0}}}}, "screen": {"$ref": "#/$defs/screen"}, "opportunity": {"type": "object", "additionalProperties": false, "required": ["score", "breakdown"], "properties": {"score": {"type": "number", "minimum": 0, "maximum": 100}, "breakdown": {"type": "object", "additionalProperties": false, "required": ["momentum", "fit", "gap", "evidence", "trajectory"], "properties": {"momentum": {"type": "number", "minimum": 0, "maximum": 1}, "fit": {"type": "number", "minimum": 0, "maximum": 1}, "gap": {"type": "number", "minimum": 0, "maximum": 1}, "evidence": {"type": "number", "minimum": 0, "maximum": 1}, "trajectory": {"type": "number", "minimum": 0, "maximum": 1}}}}}, "qualifies_for_topic_pool": {"type": "boolean"}, "disqualifiers": {"type": "array", "items": {"enum": ["EXCLUDED_BY_SCREEN", "NO_SEED_FIT", "EVIDENCE_BELOW_MIN", "BREADTH_BELOW_MIN", "FADING"]}}}
    },
    "competitor_warning": {
      "type": "object",
      "additionalProperties": false,
      "required": ["warning_id", "competitor_ref", "pattern", "description", "strength", "relevance", "matched_seed_ids", "evidence", "screen"],
      "properties": {"warning_id": {"type": "string", "pattern": "^w[0-9]{1,2}$"}, "competitor_ref": {"type": "string", "pattern": "^cmp_[0-9]{1,3}$"}, "pattern": {"enum": ["NEW_TOPIC_ENTRY", "BREAKOUT_VIDEO", "FORMAT_SHIFT", "SERIES_LAUNCH", "CADENCE_CHANGE", "OTHER"]}, "description": {"type": "string", "maxLength": 300}, "strength": {"enum": ["STRONG", "MODERATE", "WEAK"]}, "relevance": {"enum": ["HIGH", "MEDIUM", "LOW"]}, "matched_seed_ids": {"type": "array", "items": {"type": "string", "pattern": "^sd_[0-9]{1,3}$"}}, "evidence": {"type": "array", "minItems": 1, "maxItems": 10, "items": {"type": "object", "additionalProperties": false, "required": ["evidence_id", "external_ref", "retrieved_at", "raw_ref", "raw_sha256"], "properties": {"evidence_id": {"type": "string", "pattern": "^ev_[0-9]{1,4}$"}, "external_ref": {"type": "string", "pattern": "^[A-Za-z0-9_-]{11}$"}, "retrieved_at": {"type": "string", "format": "date-time", "pattern": "Z$"}, "raw_ref": {"type": "string", "maxLength": 1024}, "raw_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}}}, "screen": {"$ref": "#/$defs/screen"}}
    }
  }
}
```
Notes. `signals` are sorted by `opportunity.score` descending then `signal_id`; at most `max_signals`. Competitor `strength` is computed in code (`STRONG` ≥ 2× the breakout threshold with `sample_size ≥ 10`; `MODERATE` ≥ the threshold; `WEAK` otherwise, including any warning whose baseline `sample_size < 5`). Evidence per signal is capped at `trends.evidence.max_per_signal` (10) by highest `vph`; all member refs stay in the features blob. `outlook`, `confidence`, `confidence_band`, `confidence_components` are `null` unless mode `PREDICTIVE_INTELLIGENCE` ran. `excluded_topics` lists excluded clusters by label only (no evidence) so the owner can see what was screened out.

### 8.2 Task Output envelope values (03 §5; the envelope fields are not redefined)
| Field | Value |
|---|---|
| `status` | `SUCCEEDED` (also for `PARTIAL` or `CACHED` coverage and for a code-set `EXCLUDED` screen); `FAILED` / `SUSPENDED` / `REJECTED` per §18 |
| `payload` | §8.1 (`payload_schema = agent_02.trend_scan.output`, version `1.0.0`; inline up to 262,144 bytes, else `data_ref`) |
| `output_refs` | `DATA` blobs: `trend/raw/<source>/<seq>.json` (raw API captures), `trend/features.json` (items with features; contains titles) — all with SHA-256, tenant URI, retention class `PUBLIC_API_30D` (pending CCR) |
| `quality_score` | `null` (this step does not score quality; the 100-point rubric belongs to Agent 16) |
| `confidence` | median of signal confidences, or `null` |
| `validation_results` | one row per check (§10.6), `check_id` `agent_02.<step>.<id>` (e.g. `agent_02.synthesis.s2_partition`), `kind = DETERMINISTIC`, `blocking` true for schema, partition, reference, safety and retention checks; `WARN` (non-blocking) for `coverage_partial` and `no_prior_snapshot` |
| `resource_usage` | CPU, RSS, tokens in/out/cached, `llm_calls`, `provider_calls` (YouTube calls), `cost_estimate_micros`, `cost_entry_ids` |
| `next_action` / `downstream_agent` | `CONTINUE` / `agent_03` (advisory, 03 §5.3) |

### 8.3 Illustrative output (one signal; values invented for illustration, labelled ESTIMATE, not measured)
```json
{ "scan_summary": {"modes_run": ["TREND_DISCOVERY", "PREDICTIVE_INTELLIGENCE"], "coverage_status": "COMPLETE", "cache_hit": false,
    "sources": [{"source": "YT_SEARCH", "status": "OK", "items": 180, "quota_units": 8}, {"source": "YT_MOST_POPULAR", "status": "OK", "items": 50, "quota_units": 1}],
    "items_collected": 230, "items_after_filter": 171, "prior_snapshots_used": 1},
  "signals": [{"signal_id": "sg_1", "label": "RSI divergence explained", "label_local": "RSI डायव्हर्जन म्हणजे काय", "interpretation": "Uploads in three languages explain one indicator concept from the same angle.",
    "audience_intent": "LEARN_CONCEPT", "matched_seed_ids": ["sd_1"],
    "metrics": {"evidence_items": 9, "breadth_channels": 6, "momentum_ratio": 2.1, "age_trend_ratio": 1.3, "saturation_index": 0.75, "paired_items": 5, "paired_ratio": 1.4},
    "outlook": {"trajectory": "RISING", "horizon_days": 14, "statement": "Viewing of recent videos on this topic is running above their earlier average (ratio 1.4); outlook for the next 14 days: rising. Confidence MEDIUM (0.6); basis: 9 videos from 6 channels.", "figure_label": "PROJECTION"},
    "confidence": 0.6, "confidence_band": "MEDIUM", "confidence_components": {"evidence": 0.9, "breadth": 1.0, "history": 0.625, "agreement": 1.0}, "caps_applied": ["SINGLE_SOURCE"],
    "evidence": ["…up to 10 items with evidence_id, external_ref, retrieved_at, raw_ref, raw_sha256…"], "screen": {"status": "CLEAR", "rule_ids": [], "note": "Concept education."},
    "opportunity": {"score": 65.75, "breakdown": {"momentum": 0.7, "fit": 0.5, "gap": 0.25, "evidence": 0.9, "trajectory": 1.0}}, "qualifies_for_topic_pool": true, "disqualifiers": []}],
  "competitor_warnings": [], "excluded_topics": [], "weights_version": "trends.weights.v1", "retention": {"evidence_expires_after_days": 30} }
```

---

## 9 Python package and class architecture
**MVP: 3C · Tier 0. Structure per SOURCE_LAYOUT.md and 27 §7: one package per agent, typed Protocols, constructor injection, no globals; the agent imports `amw_core` and adapter Protocols only.**
```text
packages/agents/agent_02_market_intelligence/
├── __init__.py            # exports TrendScanService and the Protocols
├── protocols.py           # YouTubeSignalSource, QuotaGuard, SignalStore, ScanMemory (+ LlmAdapter from amw_adapters)
├── models.py              # Pydantic models generated from §7/§8 schemas (TrendScanInput/Output, SynthesisInput/Result, CompetitorInput/Warnings)
├── service.py             # TrendScanService.run(task) — the only entry point (registered in the ai_worker)
├── validation.py          # V1–V9, channel/profile equality, control check
├── planner.py             # ScanPlanner: seeds → query groups; quota_plan (pure)
├── collect.py             # Collector: calls YouTubeSignalSource under QuotaGuard, writes raw blobs and checkpoints
├── filtering.py           # public_data_filter, sanitize_title, exclude_terms, dedupe, language tagging (pure)
├── features.py            # velocity, cohort_percentile, baseline, anomalies (pure)
├── synthesis.py           # SynthesisStep: builds step input, calls LlmAdapter, parses, repairs once, runs S1–S10
├── competitor.py          # CompetitorStep: same pattern, runs C1–C10
├── screen.py              # lexical_screen, tighten (pure; lexicon from rule-pack config)
├── scoring.py             # cluster_metrics, trajectory, confidence, opportunity, strength (pure)
├── outlook.py             # templates §6.9 (pure)
├── assemble.py            # SignalAssembler: output payload, ordering, caps, validation_results
├── persist.py             # blobs, memory pointer, cost and quota ledger rows, audit events (via amw_core)
├── retention.py           # validate_retention, expiry computation, expiry sweep job
├── errors.py              # mapping to 07 codes (no new codes)
└── config.py              # pydantic-settings model for the trends.* keys of §6.8
```
Adapter package (shared, not part of the agent): `amw_adapters/youtube_data/` (read-only Data API client with API key, a fake, and redacted recorded fixtures). It is distinct from the OAuth publishing adapter of Agent 13 and holds no OAuth code (pending CCR: capability `youtube_data_read`).

### 9.1 Protocols and collaborators
| Protocol | Methods (typed, async) | Implemented by |
|---|---|---|
| `YouTubeSignalSource` | `search(query, region, language, published_after, max_results, page_token) -> SearchPage`; `videos(ids) -> list[VideoRecord]`; `most_popular(region, category_id) -> list[VideoRecord]`; `channel_uploads_playlist(external_channel_id) -> str`; `playlist_items(playlist_id, max_results) -> list[str]` | `amw_adapters.youtube_data` (real, fake) |
| `QuotaGuard` | `reserve(bucket, units, idem_key) -> Reservation`; `settle(reservation, units_used)`; `tenant_used_today(bucket) -> int` | wraps `amw_quota_reserve/release` (04 §3.6) and `cost_ledger` |
| `LlmAdapter` | as ADR-007 (complete, count tokens, batch) | `amw_adapters.llm` |
| `SignalStore` | `put_blob(kind, key, data, retention_class) -> OutputRef`; `get_blob(uri) -> bytes` | `amw_core.storage` (tenant-checked) |
| `ScanMemory` | `latest_pointer(channel_id) -> MemoryItem or None`; `write_pointer(...)`; `watchlist(channel_id) -> list[Competitor]` | `amw_core` memory repository (RLS) |
Ambient services through `amw_core`: `tenancy`, `audit`, `cost`, `config`, `observability`, `ids`, `retries`.

### 9.2 Class responsibilities
`TrendScanService` orchestrates steps and checkpoints and holds no logic of its own; `ScanPlanner`, `Collector`, `SynthesisStep`, `CompetitorStep`, `SignalAssembler`, `RetentionPolicy` have single responsibilities; all arithmetic lives in pure functions (`features`, `scoring`, `screen`, `outlook`, `filtering`) so it can be property-tested. No class reads the environment or a secret directly: keys arrive through adapter constructors from `amw_core.config`.

---

## 10 Function-level specification
**MVP: 3C · Tier 0. Every function is typed (mypy strict), logs through `amw_core.observability` with `org_id`, `correlation_id`, `job_id`, `task_id`, `attempt_id`, `actor = agent_02`, and never logs titles, seed or watch-list labels (hashed refs only), keys or tokens.**

### 10.1 Orchestration
| Function | Signature | Effects | Raises | Validation | Tests |
|---|---|---|---|---|---|
| `TrendScanService.run` | `async (task: TaskInput) -> TaskOutput` | opens tenant transaction, runs steps in order, writes output | maps every exception to an `amw.error` (§18) | V1–V9 | T-I01…T-I12 |
| `validate_task` | `(task, db: TenantDb) -> ValidatedTask` | reads `channels`, `org_controls` | `PERMANENT.TENANT_MISMATCH`, `INPUT_INVALID`, `SCHEMA_INVALID`, `TENANT_INACTIVE`, `PERMISSION_DENIED` | §7.5 | T-U01…T-U06 |
| `reuse_cached` | `(validated, memory: ScanMemory, now) -> Output or None` | reads pointer only | none | pointer org/channel equal; age ≤ TTL; `seed_hash` equal | T-U07 |

### 10.2 Plan and collect
| Function | Signature | Effects | Raises | Validation | Tests |
|---|---|---|---|---|---|
| `quota_plan` | `(seeds:int, regions:list[str], n_competitors:int, uncached_competitors:int, use_chart:bool, caps:QuotaCaps) -> CallPlan` | pure | none | §6.7 | `deterministic_core` QTA-01…07 |
| `Collector.collect` | `async (plan, source, quota, store, ckpt) -> list[RawCapture]` | for each call: reserve → call → settle → write blob → ledger row → checkpoint | `TEMPORARY.RATE_LIMITED`, `UPSTREAM_5XX`, `TIMEOUT`, `NETWORK`; `PERMANENT.AUTH_INVALID`; `PUBLISHING.QUOTA_EXHAUSTED` (reused meaning, §18); `INFRASTRUCTURE.CIRCUIT_OPEN`; `AGENT.LOOP_CAP_EXCEEDED` | idempotency key `trend.fetch` (pending CCR) = SHA-256 of `{org_id, task_id, step_key, request_sha256}`; page caps | T-I03…T-I08, T-F01…T-F08 |
| `YouTubeSignalSource.*` | see §9.1 | HTTPS GET with API key header/query from secret, fixed generic client identity, response size and time caps | as above | `regionCode` ISO; `maxResults` 0–50 (verified, §12.2); `publishedAfter` RFC 3339 UTC | adapter contract tests with recorded fixtures |

### 10.3 Filter and features
| Function | Signature | Effects | Raises | Notes | Tests |
|---|---|---|---|---|---|
| `public_data_filter` | `(rec: Record, task_channel_id: UUID) -> FilterResult` | pure | none (returns `ERROR` object) | allowed sources `YT_SEARCH`, `YT_MOST_POPULAR`, `YT_COMPETITOR_UPLOAD`, `OWN_ANALYTICS`; strips `comment_text`, `author_channel_id`, `author_display_name`, `email`, `description`; `OWN_ANALYTICS` of another channel ⇒ `PERMANENT.CROSS_TENANT_REF` by the caller | PUB-01…06 |
| `sanitize_title` | `(t: str, max_chars: int) -> str` | pure | none | NFC; control and zero-width removed; ZWJ/ZWNJ kept; whitespace collapsed; truncation never leaves a dangling combining mark | SAN-01…05 |
| `velocity`, `cohort_percentile` | `(views, age_hours, …) -> float` / `(value, cohort, min_cohort) -> float or None` | pure | none | §6.3 | VEL-01…04, PCT-01…04 |
| `detect_anomalies` | `(competitor: CompetitorData, params) -> list[Anomaly]` | pure | none | §6.3 kinds | T-U20…T-U27 (cases extend `deterministic_core` when built) |
| `pseudonymise` | `(items, competitors) -> (PseudoItems, Mapping)` | pure; the mapping stays in memory and in the features blob | none | `it_N`, `ch_N`, `cmp_N`, `cu_N`, `an_N` | T-U30 |

### 10.4 LLM steps
| Function | Signature | Effects | Raises | Validation | Tests |
|---|---|---|---|---|---|
| `SynthesisStep.run` | `async (inp: SynthesisInput, llm: LlmAdapter, budget) -> SynthesisResult` | reserves cost, one call (+1 repair on parse or schema failure), writes `cost_ledger` row (`llm.completion`, idempotency scope `llm.call`) | `AGENT.INVALID_JSON`, `AGENT.OUTPUT_SCHEMA_INVALID`, `PERMANENT.PROVIDER_REFUSAL`, `RESOURCE.BUDGET_EXHAUSTED`, `TEMPORARY.*`, `AGENT.QUALITY_REPEATED_FAILURE` | checks S1–S10 (§10.6) | T-U40…, eval gate |
| `CompetitorStep.run` | `async (inp: CompetitorInput, llm, budget) -> CompetitorWarnings` | as above, ⌈competitors ÷ `trends.competitor.per_call`⌉ calls (default 5 per call) | as above | checks C1–C10 | T-U50…, eval gate |
| `map_refusal` | `(refusal) -> ErrorOrVerdict` | pure | none | 27 §4.3: `INSUFFICIENT_INPUT` → `FAILED PERMANENT.INSUFFICIENT_INPUT`; `OUT_OF_SCOPE`, `CONFLICTING_INSTRUCTIONS` → `FAILED PERMANENT.INPUT_INVALID`; `UNSAFE_CONTENT` → `SUCCEEDED` with the cluster dropped and the case logged for human review (L3 via S7) | T-U60 |

### 10.5 Scoring, assembly, persistence
| Function | Signature | Effects | Raises | Tests |
|---|---|---|---|---|
| `cluster_metrics` | `(members, baseline, params) -> Metrics` | pure | none | T-U70 |
| `trajectory` | `(pairs, min_pairs, hi, lo) -> TrajectoryResult` | pure | none | TRJ-01…08 |
| `confidence` | `(evidence_items, breadth, paired_items, indicators, source_types, params) -> ConfidenceResult` | pure | none | CNF-01…08 |
| `opportunity` | `(momentum_ratio, matched_seeds, member_count, evidence_items, breadth, traj, screen_status, params) -> Opportunity` | pure | none | OPP-01…08 |
| `lexical_screen`, `tighten` | `(text, lexicon, active_packs) -> Screen`; `(a, b) -> Screen` | pure | none | LEX-01…07, TGT-01…04 |
| `render_outlook` | `(traj, horizon_days, paired_ratio, paired_items, band, confidence, evidence_items, breadth) -> str` | pure | none | T-U80 |
| `SignalAssembler.assemble` | `(clusters, warnings, scores, plan, usage) -> TrendScanOutput` | builds §8.1; sorts; caps; computes `validation_results` | `AGENT.INCOMPLETE_OUTPUT` | T-U90 |
| `persist_outputs` | `async (output, captures, ctx) -> list[OutputRef]` | write-once blobs with SHA-256, `memory_items` pointer, cost rows, audit `agent_02.scan.completed`; idempotency scope `db.output` | `INFRASTRUCTURE.STORAGE_UNAVAILABLE`, `TEMPORARY.DB_TRANSIENT` | T-I09 |
| `validate_retention` | `(days:int, max_days:int=30) -> RetentionResult` | pure | `PERMANENT.CONFIG_INVALID` (by caller) | RET-01…04 |
| `sweep_expired` | `async (now) -> int` | deletes expired blobs and pointers of this agent (per org; system function lists ids only) | `INFRASTRUCTURE.*` | T-I10 |

### 10.6 Post-check lists (referenced by the prompt files)
**Synthesis S1–S10:** S1 schema valid · S2 partition (every input item exactly once; clusters ≥ 2 members; count ≤ `max_clusters`) · S3 member and seed IDs exist · S4 `CLEAR` has no rule IDs; no `FIN-*` ID when `rp.finance_sebi_in` is inactive · S5 numbers in `label`/`interpretation`/`note` appear in the input (Devanagari digits normalised) · S6 no forward-looking or recommendation phrase (config `trends.synthesis.banned_phrases`, finance packs add theirs) · S7 no URL and no 40-character copy of a title · S8 lexical floor merged with `tighten` (status can only rise) · S9 exclude-term items are unclustered · S10 refusal consistent (refusal ⇒ no clusters, no unclustered). Blocking: all; a failure triggers one repair call with the violation list, then `AGENT.QUALITY_REPEATED_FAILURE`.
**Competitor C1–C10:** C1 schema · C2 competitor, anomaly and evidence IDs exist and belong together · C3 every anomaly covered · C4 pattern ↔ anomaly kind (`NEW_TOPIC_ENTRY`↔`NEW_TOPIC_CANDIDATE`, `BREAKOUT_VIDEO`↔`BREAKOUT_VIDEO`, `FORMAT_SHIFT`↔`FORMAT_SHIFT_CANDIDATE`, `SERIES_LAUNCH`↔`SERIES_CANDIDATE`, `CADENCE_CHANGE`↔`CADENCE_CHANGE`; `OTHER` free; one match among referenced anomalies suffices) · C5 no copy/recommend verbs (list `trends.competitor.banned_phrases`: copy, replicate, clone, re-upload, guaranteed, "will go viral", and sentence-initial imperatives such as "make", "post", "upload", "use") · C6 no 40-character title copy, no URL · C7 `HIGH` relevance requires a matched seed; `EXCLUDED` ⇒ `LOW` · C8 lexical floor with `tighten` · C9 no `FIN-*` when the finance pack is inactive · C10 refusal consistent.

---

## 11 AI provider use
**MVP: 3C (Anthropic via adapter, ADR-007) · tier tuning in 3C after the eval gate exists · Tier 0.**
| Item | Design (ADR-007; PR-01, PR-02, PR-03) |
|---|---|
| Adapter | `LlmAdapter` Protocol only; first provider Anthropic API; key from the environment's secret mechanism (D1). A Claude subscription is not API access (PR-03). No model name, price or provider appears in code or prompt files |
| Calls per scan | `synthesis`: 1 (+1 repair); `competitor`: ⌈competitors ÷ 5⌉ (+1 repair each). Hard cap `resource_budget.max_llm_calls` (design 12); exceeding ⇒ `AGENT.LOOP_CAP_EXCEEDED`. Input is bounded by `trends.synthesis.max_items` (150): when more items exist, code keeps those with the highest cohort percentile, then `vph` — the model is never asked to read an unbounded list |
| Tier | start `MID` for both steps (ADR-007 §2.4, multilingual compliance screening); run each golden set one tier cheaper (`SMALL`) and move down only if **all** thresholds pass (27 §6.3). A tier change is a config change and triggers the eval gate (27 §5) |
| Output | JSON parsed to Pydantic; one retry with the validation error appended; then DLQ (27 §7.3.2; 07 `agent_parse` policy) |
| Caching | stable prefix = system prompt + rule-pack text (no tenant data); seeds, items and watch-list follow it; `.cache_system_prompt` per step; TTL class from config (PR-02) |
| Batch | scheduled scans in the night window may use Batch (`.batch_eligible = true`, 50 % discount, PR-02) when no interactive deadline exists; owner "scan now" and stage `s02_trends` inside a job use the interactive path. A batch result after `deadline` ⇒ `PERMANENT.DEADLINE_EXCEEDED` |
| Budget | reservation before every call from `resource_budget.max_cost_micros` and the owner-set per-video/pilot/org budgets (D1, 09); breach ⇒ `RESOURCE.BUDGET_EXHAUSTED` ⇒ `CHECKPOINTED / AWAITING_BUDGET`; each call writes one `cost_ledger` row. Prices are applied by 09 from PR-01: **no price is written here** |
| Language cost | tokens recorded per call; Marathi/Hindi titles vs an English control are measured in 3C (ADR-007 §2.9); label `MEASURED` |
| Fallback | none at first (`llm.<step>.fallback_tier` unset); a provider outage retries per 07 §3 and then waits (`AWAITING_EXTERNAL`) |
| Data governance | The model receives **public video titles and per-scan pseudonyms** plus the tenant's seed-topic labels and competitor labels (business information). **3C-BLOCKING — REQUIRES REVIEW (Phase 1): (a) the provider's retention and training terms for API inputs are not in RESEARCH_LOG (PR-03 covers billing separation only); (b) YouTube API Services Terms / Developer Policies on sending API-obtained data to a third-party AI provider are not in RESEARCH_LOG (§12.2 covers storage age only). The owner (and counsel ⚖) must accept both before the first live scan.** Until then 3C runs on fixtures only |
| No tool use | the model cannot call tools, browse or write; permission checks are in code (08 §5.3) |

---

## 12 External APIs
**MVP: 3C · Tier 0. All external facts cite RESEARCH_LOG or §12.2 (read on the official page on the stated date).**

### 12.1 Services
| # | Service | Auth and scopes | Quotas and limits | Error mapping (07 §2) | Fallback | Verification | MVP |
|---|---|---|---|---|---|---|---|
| 1 | LLM provider via `LlmAdapter` | API key from the secret mechanism; no OAuth | provider rate limits: **REQUIRES REVIEW (Phase 1): not in RESEARCH_LOG**; spend limits set by the owner at the provider (D1) | 429 → `TEMPORARY.RATE_LIMITED` (honour `retry_after_ms`); 5xx → `TEMPORARY.UPSTREAM_5XX`; timeout → `TEMPORARY.TIMEOUT`; 401/403 → `PERMANENT.AUTH_INVALID`; safety refusal → `PERMANENT.PROVIDER_REFUSAL`; bad JSON → `AGENT.INVALID_JSON` / `AGENT.OUTPUT_SCHEMA_INVALID` | wait (`AWAITING_EXTERNAL`) | PR-01, PR-02, PR-03 | 3C |
| 2 | YouTube Data API v3, **public data, API key only, no OAuth, no scope**: `search.list` | API key from the secret mechanism (`AMW_YT_DATA_API_KEY`, §24) | **own bucket, 100 calls/day per project, 1 unit each, "Search Queries quota bucket"** (YT-02; F-A); reset midnight PT (YT-03); `maxResults` 0–50, default 5 (F-C) | HTTP 429 → `TEMPORARY.RATE_LIMITED`; 5xx → `TEMPORARY.UPSTREAM_5XX`; network/timeout → `TEMPORARY.NETWORK`/`TIMEOUT`; 401/403 not quota-related → `PERMANENT.AUTH_INVALID`; **quota-exceeded 403 → `PUBLISHING.QUOTA_EXHAUSTED` (existing meaning "YouTube quota bucket used up for the PT day", reused; class-neutral code requested in CCR-Q)**; the provider's error `reason` strings: **REQUIRES REVIEW (Phase 1): the errors guide page (URL tried returned 404) was not read** | reduce to fewer seeds; partial coverage; wait for PT reset | YT-02, YT-03, YT-05; F-A, F-B, F-C | 3C |
| 3 | YouTube Data API: `videos.list` (`id` list; `chart=mostPopular` with `regionCode`, `videoCategoryId`) | same | DEFAULT bucket, 1 unit per call (YT-02; F-D); chart `maxResults` 0–50; ID-list batch limit: **REQUIRES REVIEW (Phase 1): not read; default `ids_per_call` = 50 is an ESTIMATE until verified** | as row 2 (`videoChartNotFound` 400 → `PERMANENT.INPUT_INVALID`, F-D) | drop chart | YT-02; F-D | 3C |
| 4 | YouTube Data API: `channels.list`, `playlistItems.list` (competitor uploads) | same | DEFAULT bucket, 1 unit each (YT-02 lists `playlistItems.list` 1; F-E; `channels.list` 1 per the quota page) | as row 2 | drop competitors | F-E | 3C |
| 5 | Google Trends API (alpha) | application and approval needed ("accepting applications for alpha testers"; F-G) | alpha; rolling 5-year window (F-G); quotas not stated | — | none | **not used until the account is accepted; REQUIRES REVIEW (Phase 1): terms, quota, GA status, data-use limits** | 3C (conditional) |
| 6 | Any other source (social platforms, news, marketplaces, scraped pages) | — | — | — | — | **REQUIRES REVIEW (Phase 1): no research entry exists; excluded by §2.3 until an ADR adds one with its facts in the log** | none |
| 7 | PostgreSQL, storage | `amw_app` role, tenant context (04 §3) | — | `TEMPORARY.DB_TRANSIENT`, `INFRASTRUCTURE.DB_UNAVAILABLE`, `STORAGE_UNAVAILABLE` | — | — | 3C |

### 12.2 Facts verified for this blueprint (official pages read 2026-11-18; **proposed RESEARCH_LOG entries**, IDs to be assigned by the integrator)
| Ref | Fact | Source | Status |
|---|---|---|---|
| F-A | `search.list` quota impact: "100 calls per day. A call to this method has a quota cost of 1 unit in the Search Queries quota bucket." (agrees with YT-02) | [search.list](https://developers.google.com/youtube/v3/docs/search/list) | VERIFIED |
| F-B | `order` default is `relevance`; date ordering "relies on the search index" and may show indexing delays or incomplete sets; **for a channel's most recent uploads use `playlistItems.list`, not `search.list`**; other orders combined with `publishedAfter` may return smaller or incomplete result sets | same | VERIFIED |
| F-C | `search.list` parameters used: `maxResults` 0–50 (default 5); `publishedAfter` RFC 3339; `regionCode` ISO 3166-1 alpha-2; `relevanceLanguage` (ISO 639-1); `videoCategoryId`; results can be fewer than `maxResults`, rely on `nextPageToken` | same | VERIFIED |
| F-D | `videos.list`: quota cost 1 unit; `chart=mostPopular` with `regionCode` and `videoCategoryId`; error `videoChartNotFound` (400) | [videos.list](https://developers.google.com/youtube/v3/docs/videos/list) | VERIFIED |
| F-E | `playlistItems.list` quota cost 1 unit (and `channels.list` 1) in the quota table; `maxResults` 0–50 | [determine_quota_cost](https://developers.google.com/youtube/v3/determine_quota_cost), [playlistItems.list](https://developers.google.com/youtube/v3/docs/playlistItems/list) | VERIFIED |
| F-F | YouTube API Services Developer Policies (refreshing, storing, displaying API data): non-authorised data may be stored only temporarily, **not longer than 30 calendar days, after which it must be deleted or refreshed**; statistics such as subscriber counts retrieved as non-authorised data must not be stored for more than 30 days without the owner's authorisation; quota extensions require an API Compliance Audit and use only for the approved use case | [Developer Policies](https://developers.google.com/youtube/terms/developer-policies) | VERIFIED (reading of "temporary storage" for derived aggregates: **REQUIRES REVIEW (Phase 1) with counsel**) |
| F-G | Google Trends API is an **alpha** for approved testers; rolling window of the last 5 years; daily/weekly/monthly/yearly aggregation; regions and sub-regions | [Trends API alpha](https://developers.google.com/search/apis/trends) | VERIFIED (availability to this project: not known) |
Not verified and therefore not relied on: the YouTube API Services Terms of Service (attribution, branding, restrictions on use with AI providers), the per-reason error strings, the `ids` batch limit, any rate limit other than the daily buckets.

### 12.3 Quota arithmetic and fairness
1. **Reserve before every call**: `amw_quota_reserve(gcp_project_id, bucket, units)` (04 §3.6; caller list extended to `agent_02`, **pending CCR-Q**), settle after, release what was not used. `quota_usage` is per project and PT day (04 §5.20); the PT date is `(ts AT TIME ZONE 'America/Los_Angeles')::date` (GLOSSARY §4). Night-window work (00:00–07:00 IST) falls inside one PT day (the reset is 12:30 or 13:30 IST, YT-03), so a night scan consumes one day's counters.
2. **Per-tenant share**: because the platform project's buckets are shared by all tenants and by Agents 12, 13, 14, each tenant's daily use is capped (`trends.youtube.search_calls_per_day_per_tenant` 40 of 100; `default_units_per_day_per_tenant` 500 of 10,000). Tenant usage is summed from `cost_ledger` rows (`operation = youtube.quota`, `unit_kind = quota_units`, `occurred_at` in the PT day) with the bucket recorded (convention pending CCR-Q). Queue fairness is also isolation (08 §8.1).
3. **Typical scan**: ≤ 10 search units and ≤ ~60 default units; one scan per channel per interval (design weekly) leaves most of the bucket to publishing. All figures are ESTIMATE until measured.
4. **Quota extension** is a compliance audit with a stated use case (YT-11, F-F): out of scope for Tier 0; needed only if the measured demand exceeds the default buckets.
5. **No quota circumvention**: one project and one key per platform deployment as set by the owner; Agent 02 never rotates keys or projects to obtain more quota.

---

## 13 Database tables
**MVP: 3C · Tier 0; every row carries `org_id`, RLS forced (04 §3). Only tables that exist in 04 are used.**
Agent 02 owns **no table** and creates none. A signal history table was considered and rejected for 3C (the scan output blob plus the memory pointer is enough; a queryable table is considered only if cross-scan calibration needs it: **REQUIRES REVIEW (3C)**).
| Table (04 §) | Columns used | Agent 02 access | Notes |
|---|---|---|---|
| `channels` (5.1) | `id, workspace_id, language, category, status` | SELECT | equality check against `channel_profile`; no write |
| `org_controls` (5.1) | `key = agent_enabled.agent_02`, `emergency_stop` | SELECT | V7 |
| `rule_packs`, `compliance_profiles`, `compliance_profile_rule_packs` (5.2) | pack keys and versions | SELECT | which packs apply; versions recorded per LLM call |
| `tasks`, `task_attempts`, `task_queue` (5.3–5.4) | state via `amw_core.state_machine` | through the library only | no direct DML by the agent |
| `checkpoints` (5.7) | `step_key, state_ref, state_sha256, completed_effects, progress_ratio, is_latest` | INSERT, SELECT | §16 |
| `dead_letter` (5.7) | — | none (the orchestrator writes) | |
| `idempotency_keys` (5.9) | scopes `llm.call`, `db.output`, `trend.fetch` (pending CCR) | INSERT, SELECT, UPDATE of own rows | |
| `memory_items` (5.10) | `scope, workspace_id, channel_id, key, value_ref, provenance_ref, confidence, created_by, expires_at, review_after, superseded_by` | INSERT, SELECT | keys `trend.scan.latest` (written), `trend.competitor_watchlist` and seed topics (read only; written by humans or Agent 03) |
| `analytics_snapshots` (5.22) | `channel_id, source, report_type, metric_date, metrics` | SELECT (3C, after Agent 14) | own-channel prior; same channel only |
| `quota_usage` (5.20) | — | **only through** `amw_quota_reserve/release` | no direct DML |
| `cost_ledger` (5.14) | `provider, model, operation, tokens_*, units, unit_kind, amount_micros, figure_kind, price_ref, idempotency_key` | INSERT (append-only), SELECT own tenant | rows `llm.completion` and `youtube.quota` |
| `audit_log` (5.13) | — | through `amw_core.audit` only | events §22 |
Agent 02 has no grant on `approvals`, `budgets`, `oauth_tokens`, `publications`, `knowledge_*`, `scripts`, `claims`, `citations`, and no direct DML on `audit_log`.
**Pending contract items:** see §15.3 and the structured return (CCR-C capability, CCR-I idempotency scope, CCR-Q quota caller and bucket attribution, CCR-J scheduled system job, CCR-R retention class).

---

## 14 Memory
**MVP: 3C · Tier 0. Rules: 04 §5.10 and directive §3.3; isolation by tenant, channel and project.**
| Scope (GLOSSARY §6.30) | What Agent 02 keeps there | Expiry / retention | Retrieval rule | MVP |
|---|---|---|---|---|
| `WORKING` | item lists, prompts and responses in flight; memory only | end of the attempt | same attempt | 3C |
| `TASK` | checkpoint state (plan, completed effect keys, blob URIs, no titles inline) | job retention but never beyond the 30-day class (§19.5) | same task; resume | 3C |
| `PROJECT` | optional pointer `trend.scan.<job>` for the job that consumed the scan | `expires_at` ≤ 30 days (CHECK requires it for PROJECT) | Agent 03 in the same project | 3C |
| `CHANNEL` | `trend.scan.latest` pointer (`value_ref` to the output blob, `provenance_ref` = task output, `confidence` = task confidence) with `expires_at` ≤ 30 days and `review_after`; older pointers are superseded (`superseded_by`) until they expire | ≤ 30 days | same channel only; used for cache reuse and prior pairs | 3C |
| `LONG_TERM` | nothing from public API data (30-day rule). Human-written `trend.competitor_watchlist` and seed topics are tenant configuration, not scan data | until a human changes them | same org and channel | 3C |
- Never stored in memory: another tenant's data, raw titles inline, personal data, any value older than the retention class.
- Calibration facts (which outlooks came true) are derived from later scans' paired ratios and from Agent 14's measured metrics; they are summaries with provenance, written to `CHANNEL` scope only when a human-approved experiment records them (learning loop, §3.3: no automatic change to critical policy; weights change only by a new `weights_version` through the eval gate).
- Prior-scan reuse reads the previous pointer only if its `org_id` and `channel_id` equal the task's.

---

## 15 Upstream and downstream contracts
**MVP: 3C · Tier 0.**

### 15.1 Upstream
| Source | What Agent 02 consumes | Contract |
|---|---|---|
| Orchestrator (01) | Task Input envelope with `agent_02.trend_scan` payload, `context_refs`, `resource_budget`, `deadline`, `idempotency_key` | 03 §3; 24 §3.2 |
| Owner / Agent 03 | seed topics (labels, languages); excludes | §7.1 via `MEMORY` ref |
| Owner (human) | competitor watch-list (`trend.competitor_watchlist`, human-written) | §19.2 |
| Agent 14 (3C) | `analytics_snapshots` rows of the same channel (read via DB, not a task output) | 04 §5.22 |
| Agent 16 / rule packs | `rp.*` text by reference, versions recorded | 04 §5.2 |
| YouTube Data API | public records (§12) | §12 |

### 15.2 Downstream
| Consumer | What it takes | How |
|---|---|---|
| Agent 03 (3C) | `signals[]` that `qualifies_for_topic_pool`, their evidence, screen flags, confidence and weights version; `competitor_warnings[]`; `excluded_topics[]` | orchestrator passes the output pointer as a `PRIOR_OUTPUT` or `MEMORY` context ref; Agent 03 must treat `REFRAME_AS_EDUCATION` as a constraint and `EXCLUDED` as final for that topic (it may re-screen; it may not loosen) |
| Agent 15 / Business Discovery Engine | evidence only; a trend is never a criterion (17 §2.3) | read of the stored output within retention |
| S8 Command Center | display: numbers first, component bars, colour by meaning (owner rule D.2); signal evidence expands on demand | API read, tenant filtered |
| Agent 14 | none directly; its measured results are the later calibration input | §20 |
| Orchestrator | task output (status, payload, refs, confidence, advisory `next_action = CONTINUE`, `downstream_agent = agent_03`) | 03 §5 |
Compatibility rule: the output payload is versioned (`1.0.0`); a breaking change bumps MAJOR and goes through the contract-compatibility CI gate (27 §5).

### 15.3 Contract requests (all additive; filed in the structured return, not edited here)
| Ref | Needed | Reason | Proposed change | Target doc |
|---|---|---|---|---|
| CCR-C | worker capability `youtube_data_read` | the reader needs egress to the Data API without OAuth; `publish_youtube` means OAuth publishing | add the value to GLOSSARY §6.20; the `ai_worker` registers `llm` + `youtube_data_read` | GLOSSARY §6.20 |
| CCR-I | idempotency scope `trend.fetch` | a replay after a crash must not repeat a quota-spending call | row in 03 §9.2: natural key `task_id`, `step_key`, request SHA-256; effect "YouTube Data API read call" | 03 §9.2 |
| CCR-Q | quota caller and bucket attribution | `amw_quota_reserve/release` lists only the publish worker; per-tenant attribution needs the bucket | allow caller `agent_02`; `cost_ledger` rows of `youtube.quota` carry the bucket (nullable `quota_bucket` column, or operation suffix); a class-neutral code `RESOURCE.QUOTA_EXHAUSTED` is preferred over reusing `PUBLISHING.QUOTA_EXHAUSTED` | 04 §3.6, §5.14; 07 §2 |
| CCR-J | scheduled system job for `agent_02.trend_scan` | trend scans should run on a schedule outside a production job (24 §7 mentions 14/15 only) | record or note a `NO_DELIVERABLE` system-job kind that runs a single task type | 24 §7 |
| CCR-R | retention class for stored public API data | Developer Policies limit (F-F) needs a storage-level expiry, not only a pointer expiry | blob attribute `retention_class = PUBLIC_API_30D` with enforced maximum 30 days; sweep by the storage layer | 03 §8, 04 §7, ADR-005 |
Also referenced, already pending elsewhere: `agent_02.niche_score` and `niche_scores` (17_BUSINESS_PLAN §15).

---

## 16 State handling and checkpoints
**MVP: 3C · Tier 0. Task states and transitions are 03 §11 (not redefined); checkpoint table is 04 §5.7.**
| Step key | Checkpoint written after | State blob contains | Effects recorded (`completed_effects`) |
|---|---|---|---|
| `plan` | quota/budget reservation made | plan, reservation IDs, seed hash | `quota.reserve.<n>` |
| `collect.search.<group>` | each search page stored | blob URIs, page tokens, units used | `trend.fetch.<sha>` per call |
| `collect.videos`, `collect.chart`, `collect.competitors` | each batch stored | same | `trend.fetch.<sha>` |
| `features` | features blob written | URI + SHA-256 | — |
| `synthesis.<n>`, `competitor.<n>` | model output validated | validated result blob | `llm.call.<sha>` |
| `score` | signals computed | signal list | — |
| `persist` | output blob and pointer written | refs | `db.output.<sha>` |
Rules. (1) A new attempt starts from the latest checkpoint and skips recorded effects, so no paid call is repeated and no quota is spent twice. (2) Unused reservations are released at the end of the attempt or by the reaper after lease expiry. (3) `CHECKPOINTED` with `wait_reason`: `AWAITING_QUOTA` (all sources blocked until the PT reset), `AWAITING_BUDGET`, `AWAITING_EXTERNAL` (provider `retry_after` above the cap). (4) Control commands `DRAIN`/`PAUSE`/`CANCEL` (03 §4.3) are honoured at the next checkpoint; a cancelled scan writes no pointer. (5) Replays are safe: the idempotent `db.output` scope gives one output and one pointer per (job, iteration). (6) The task output is written once; the pointer is the last write, so a reader never sees a pointer to a missing blob.

---

## 17 Resource model
**MVP: 3C. ESTIMATE until measured in 3C (05, INF-01/03/04). Resource class `AI_IO` (GLOSSARY §6.6); queue `ai`.**
| Resource | ESTIMATE per scan (≤ 300 items, ≤ 10 competitors) | Basis |
|---|---|---|
| CPU | ≤ 10 s of CPU, one core, no native extensions | pure Python arithmetic over ≤ 300 items |
| RAM | ≤ 256 MB peak RSS | item lists and one model response in memory |
| Network | ≤ ~40 HTTPS calls to the Data API, 2–6 to the LLM provider | §6.7, §11 |
| Storage | ≤ 2 MB raw and feature blobs, ≤ 100 KB output; all expire ≤ 30 days | response sizes not yet measured |
| LLM tokens | synthesis ≈ 10–20 k in, ≈ 3 k out; competitor ≈ 4–8 k in per call, ≈ 1 k out | ≈ 150 titles + prompt + schema; ESTIMATE |
| YouTube quota | ≤ 10 SEARCH units and ≤ ~60 DEFAULT units | §6.7 |
| Wall time | ≤ 10 min (`max_wall_ms` 600,000); cache hit < 2 s | network-bound |
| Concurrency | 1 scan per channel; ≤ 2 platform-wide | `trends.max_parallel_scans` |
| Money | bounded by `resource_budget.max_cost_micros`; no figure written here | 09 applies PR-01 |
The agent adds no resident process: it runs inside the `ai_worker` under the factory's slice limits (INF-03/04: hard caps from the audit); it holds no GPU and does no render, so the night-window and market-hours render rules do not apply to it. Scheduled scans are placed in the night window by default to keep daytime capacity for the other applications on the shared host; an owner request can run any time subject to admission (06). Measurement plan: record per-scan CPU, RSS, tokens, bytes, calls and wall time in 3C and replace this table (label `MEASURED`).

---

## 18 Errors and recovery
**MVP: 3C · Tier 0. Only 07 §2 codes are used; retry policies are 07 §3; escalation levels are 07 §2.**
| Situation | Code | Disposition (07) | Escalation |
|---|---|---|---|
| org/envelope/context mismatch; a ref of another tenant | `PERMANENT.TENANT_MISMATCH`; `PERMANENT.CROSS_TENANT_REF` (+ security event) | FAIL | L3 security |
| payload invalid; channel row differs from `channel_profile`; too many competitors | `PERMANENT.SCHEMA_INVALID` / `INPUT_INVALID` | FAIL (`REJECTED` at validation) | L2 |
| agent disabled by control or emergency stop reaching the task | `PERMANENT.PERMISSION_DENIED` (`REJECTED`) | FAIL | L2 |
| missing key or secret at start | `PERMANENT.CONFIG_INVALID` | FAIL | L3 operations |
| `trends.retention.days` above 30 | `PERMANENT.CONFIG_INVALID` | FAIL at startup | L3 |
| Data API 429, 5xx, timeout, network | `TEMPORARY.RATE_LIMITED`, `UPSTREAM_5XX`, `TIMEOUT`, `NETWORK` | RETRY with `temporary`/`rate_limited` policy | L1 |
| Data API 401/403 not quota-related | `PERMANENT.AUTH_INVALID` | FAIL | L3 security/ops |
| quota exhausted (bucket or tenant share) | `PUBLISHING.QUOTA_EXHAUSTED` (meaning reused; CCR-Q asks for a neutral code) | if ≥ `trends.min_items_for_scan` items were collected: **continue as `PARTIAL`** (warning check `coverage_partial`); else SUSPEND `AWAITING_QUOTA` until the PT reset | L1; L3 beyond `quota.max_wait_days` |
| breaker open for `youtube_data` | `INFRASTRUCTURE.CIRCUIT_OPEN` | NO-ATTEMPT until `open_until` | L1; L2 if long |
| LLM parse / schema failure | `AGENT.INVALID_JSON`, `AGENT.OUTPUT_SCHEMA_INVALID` | one retry with the error; then DLQ | L2 |
| post-check failure after repair | `AGENT.QUALITY_REPEATED_FAILURE` | FAIL | L3 quality |
| LLM refusal | per 27 §4.3 (`INSUFFICIENT_INPUT` → `PERMANENT.INSUFFICIENT_INPUT`; `OUT_OF_SCOPE`/`CONFLICTING_INSTRUCTIONS` → `PERMANENT.INPUT_INVALID`; `UNSAFE_CONTENT` → drop and flag for review) | per mapping | L2/L3 |
| provider safety refusal | `PERMANENT.PROVIDER_REFUSAL` | FAIL | L2 |
| budget refusal | `RESOURCE.BUDGET_EXHAUSTED` | SUSPEND `AWAITING_BUDGET` (no automatic increase, rule 8) | L3 finance |
| cap reached (LLM calls, API pages, items) | `AGENT.LOOP_CAP_EXCEEDED` | FAIL | L3 |
| crash, hang, worker lost, host restart | `AGENT.CRASH`, `AGENT.HANG`, `INFRASTRUCTURE.WORKER_LOST`/`HOST_RESTART` | RETRY from checkpoint | L1 |
| storage / DB unavailable | `INFRASTRUCTURE.STORAGE_UNAVAILABLE`, `DB_UNAVAILABLE`, `TEMPORARY.DB_TRANSIENT` | RETRY | L1 → L3 |
| blob hash or size mismatch | `AGENT.CORRUPTED_OUTPUT` | RETRY | L2 |
| deadline passed | `PERMANENT.DEADLINE_EXCEEDED` | FAIL | L2 |
Because the stage is optional, a failed or dead-lettered scan does not stop the production job (24 §3.1 `required: false`); the exact orchestrator behaviour is owned by the Agent 01 blueprint (**REQUIRES REVIEW (Agent 01)**). Recovery never repeats a paid call (idempotency), never retries a PERMANENT code, and never increases a budget or quota by itself.

---

## 19 Security and permissions
**MVP: 3C · Tier 0 design; the same controls serve Tier 1+ without change (08 §8).**

### 19.1 Tenant isolation (rule 9, directive §1C.1) — how Agent 02 enforces it
Agent 02 handles tenant-confidential business information (seed topics, competitor watch-lists, scan results) and public data collected **on behalf of** one tenant. It enforces isolation in all five layers of 08 §8 and adds four agent-specific controls:
1. **App filter.** Every database access goes through `amw_core.tenancy` (`SET LOCAL app.org_id`, `app.actor = agent_02`) with explicit `org_id` predicates; `org_id` of envelope, task input, channel row and every `context_refs[]`/`data_ref` URI must agree before the first read (V3, `PERMANENT.TENANT_MISMATCH`; a foreign URI ⇒ `PERMANENT.CROSS_TENANT_REF` plus a security event). The agent takes `org_id` only from the envelope, never from payload text or model output.
2. **RLS.** All tables it touches (§13) are TENANT or SHARED-CATALOGUE with `ENABLE` + `FORCE ROW LEVEL SECURITY`; the role is `amw_app` (`NOBYPASSRLS`); unset context returns no rows. `quota_usage` is reached only through the `amw_quota_*` functions that return identifiers and counts, never content (04 §3.6).
3. **Storage URIs.** Raw captures, features and outputs are written to `amw-blob://<org>/jobs/<job>/tasks/<task>/…` with SHA-256, write-once; a read compares the URI's org with the context first (03 §8). Paths are built by `amw_core.storage` only; `..` and absolute segments are rejected.
4. **Cache keys.** Any cache entry is `amw:<org wire id>:trend:<key>`; the wrapper refuses a key without an org and a hit whose stored org differs. **There is deliberately no cross-tenant cache of public search results**, although the data is public: which topics or competitors a tenant queries is itself confidential, and a shared cache would reveal it. The price of this choice is repeated quota use, which is why scans are cached per channel (FR-2) and shared-bucket use is capped per tenant (§12.3).
5. **Logs and metrics** carry `org_id`; competitor and seed labels, titles and watch-list contents never enter logs (only salted-hash refs such as `cmp_ref_hash`); no secrets (27 §3).
6. **Model context isolation.** A model call contains only that tenant's data. The shared, cacheable prompt prefix holds no tenant data (08 §8 layer 4). The model sees pseudonyms (`it_N`, `ch_N`, `cmp_N`), never real channel IDs; the mapping stays in code and in the tenant's features blob.
7. **Fairness is isolation.** A tenant's quota use is capped per day and per scan (§12.3), and parallel scans are limited platform-wide, so one tenant cannot exhaust the shared Data API buckets for others (08 §8.1.2).
8. **Authorised data of the same channel only.** `OWN_ANALYTICS` rows are accepted only if `channel_id` equals the task's channel (`public_data_filter`); another channel's row is `PERMANENT.CROSS_TENANT_REF` (tests PUB-05).
Tests: §21 (security) re-run the 04 §3.7 suite for every table of §13 and the agent-specific cases above.

### 19.2 Permissions
Agent 02 holds capabilities `llm` and `youtube_data_read` (pending CCR-C), runs only `agent_02.trend_scan`, and has only the DML of §13. It cannot approve, change budgets, controls, memberships or credentials, cannot create tasks, and cannot write any `memory_items` key other than `trend.scan.*`. The competitor watch-list key `trend.competitor_watchlist` is created and changed only by a **human actor** (S8, audited `control.watchlist.changed`); an entry must be a public channel ID, and adding one records the human's attestation that the data to be read is public. Role matrix cells for the watch-list: `ORG_OWNER`, `ORG_ADMIN`, `PRODUCER` may edit; `VIEWER` may read (08 §5.2, **REQUIRES REVIEW (08)** for the exact matrix row).

### 19.3 Public and authorised data only (directive §3.1 row 02)
Allowed source tags: `YT_SEARCH`, `YT_MOST_POPULAR`, `YT_COMPETITOR_UPLOAD` (public Data API data), `OWN_ANALYTICS` (the tenant's own channel, read from `analytics_snapshots`). Everything else is dropped at P2 and refused by the prompts. Never collected: comments and their authors, viewer-level data, descriptions, subscriber counts of other channels, private or unlisted video data, data obtained by scraping, unofficial endpoints, purchased lists or another tenant's analytics.

### 19.4 Prompt-injection and data minimisation
Titles are untrusted text. Controls: only title, a pseudonymous channel ref and numeric fields go to the model (no description, no comments, no URLs); titles are sanitised and capped at 120 characters; the model has no tools and its output is schema-validated and checked (S1–S10, C1–C10), so an injected instruction can at most change a cluster label, which the checks bound (no URL, no copy, no numbers, no phrases, partition, references). Eval cases EDGE-18 (synthesis) and EDGE-16 (competitor) test this, and a hidden-instruction case is part of the security tests.

### 19.5 Secrets, retention, audit
- Secrets: the Data API key and the LLM key are read only through the secret mechanism, scoped to the single `ai_worker` service (08 §3.1); never in git, logs, prompts, fixtures or shared variables; startup fails with `PERMANENT.CONFIG_INVALID` if one is missing.
- Retention: all stored public API data (raw captures, features, output blob, pointers) has `retention_class = PUBLIC_API_30D` (pending CCR-R) and an enforced maximum of **30 days** (F-F). `validate_retention` rejects a configured value above 30; `sweep_expired` deletes or the next scan refreshes; Agent 03 must not copy API statistics into its own long-lived records (**REQUIRES REVIEW (Agent 03 blueprint, 13, counsel)**: whether topic labels and rationales derived from the data may be kept longer).
- Personal data: none collected on purpose; channel titles of individual creators may identify a person: **REQUIRES REVIEW (Phase 1): 22_DATA_PROTECTION / DPDP (IN-07)**. Erasure/export of a tenant addresses its storage prefix and rows (03 §8.1, 04 §5.24).
- Audit (via `amw_core.audit`, append-only): `agent_02.scan.started`, `agent_02.scan.completed` (counts, coverage, quota units, cost), `agent_02.quota.reserved`/`settled`, `agent_02.screen.excluded` (counts by rule ID, no titles), `agent_02.retention.swept`, `security.cross_tenant_ref`.
- Compliance: this agent never states that a topic is allowed to publish; Agent 16 alone authorises (Q5). `FIN-R3` and `FIN-R13` are respected by construction (no market or security forecast is produced, §6.9).

---

## 20 Quality criteria
**MVP: 3C (calibration needs real scans) · Tier 0. All thresholds are configuration (design defaults, ESTIMATE) and are recalibrated after the first measurements.**
| ID | Criterion | Measure | Threshold | Gate |
|---|---|---|---|---|
| Q-1 | Schema validity of both model steps and of the task output | validation pass rate in the eval sets and in production | 100 % (blocking) | S1/C1, 03 §5.3 |
| Q-2 | Partition and reference integrity | S2, S3, C2, C3 pass rate | 100 % | blocking |
| Q-3 | Safety floor: call-style or prohibited topics never `CLEAR` | false `CLEAR` on cases expected `EXCLUDED` (both datasets) | 0 | eval gate, mandatory |
| Q-4 | No forecast, advice, URL, number invention or title copy in any text field | S5–S7, C5–C6 violations | 0 | blocking |
| Q-5 | Confidence honesty: no `HIGH` band while one source family only; every value reproducible | CI replay of §6 on every stored output | 100 % match | blocking in CI |
| Q-6 | Cluster coherence and grounding (judge) | mean J1, J2 | ≥ 4.0 (≥ 3.5 for J3, J4) | eval gate |
| Q-7 | Deterministic core | `deterministic_core` | 100 % pass | CI |
| Q-8 | Calibration of the outlook (3C, measured) | for each confidence band: share of `RISING` signals whose next paired ratio ≥ `hi`; and of `FADING` whose next ratio ≤ `lo` | **REQUIRES REVIEW (3C): owner sets minimums after ≥ 8 scans per channel; until then the outlook is shown with its band and the words "not yet calibrated"** | monitored, not a CI gate |
| Q-9 | Usefulness to Agent 03 (3C pilot) | share of qualifying signals that Agent 03 or the owner actually uses as a topic input | **REQUIRES REVIEW (3C): owner defines after the first pilot** | review |
| Q-10 | Resource discipline | scans within `resource_budget`, quota share, wall time | 100 % | monitored |
Quality of a signal is shown, never hidden: `confidence_components`, caps and `weights_version` accompany every value, and trending alone never qualifies a topic (§6.6).

---

## 21 Tests
**MVP: tests are written with the 3C build; markers per 27 §8; no paid calls (fakes and recorded fixtures); one opt-in `live` smoke test with a hard budget and quota cap per adapter.**
| Kind | ID range | What it proves | Marker |
|---|---|---|---|
| Unit | T-U01…T-U09 | validation V1–V9, cache reuse, channel equality | `unit` |
| Unit (pure functions) | `deterministic_core` (65 cases) + T-U20…T-U27 anomaly detection + T-U30 pseudonymisation + T-U70/80/90 metrics, outlook, assembly + property tests (hypothesis): confidence ∈ [0,1] and never above an applicable cap, `tighten` never lowers severity, `cohort_percentile` ∈ [0,1], `quota_plan` never exceeds a cap, `sanitize_title` is idempotent and never leaves a dangling combining mark | `unit` |
| Unit (steps with a fake LLM) | T-U40…T-U60 | step builds the input, parses, repairs once, runs S/C checks, maps refusals, writes a cost row | `unit` |
| Integration | T-I01…T-I12 | full scan with fake YouTube source and fake LLM against PostgreSQL with RLS: plan → collect → checkpoint → synthesis → score → persist; cache hit; PARTIAL coverage; pointer supersession; sweep of expired data; ledger rows; audit events | `integration` |
| Contract | T-C01…T-C08 | payload and output examples validate against §7/§8 schemas; Pydantic = schema; prompt output schema = Pydantic; 24 §3.2 name; envelope compatibility; MINOR/PATCH changes accept old examples | `contract` |
| Regression | eval gate | `trend_scan_synthesis` (33 cases), `trend_scan_competitor` (28), `deterministic_core` (65) re-run when a prompt, an `llm.agent_02.*` config key, a rule pack or a weights version changes (27 §5) | `eval` |
| Failure injection (07 §12) | T-F01…T-F10 | 429 with `retry_after`; 5xx burst opens the breaker; timeout; quota-exhausted mid-scan ⇒ PARTIAL or `AWAITING_QUOTA`; invalid JSON then valid; schema-invalid twice ⇒ DLQ; DB blip during persist; worker killed after collect ⇒ resume without a second paid call and without a second quota reservation; storage unavailable; budget refusal ⇒ `AWAITING_BUDGET` | `failure_injection` |
| Performance | T-P01…T-P03 | 300 items and 10 competitors within the wall budget and RSS estimate with fakes; no per-item database call; checks linear in items | `performance` (nightly) |
| Security (08 §8.2) | T-S01…T-S12 | 04 §3.7 items 1–8 for every table in §13; foreign `context_refs` rejected before read; storage URI of org B in org A's task rejected; cache key without org rejected; canary secret and canary title never in logs; **no tenant's seed or watch-list label appears in another tenant's model input, output, cache or log**; injection titles (visible and zero-width) do not change safety fields; `OWN_ANALYTICS` of another channel rejected; retention above 30 days rejected; no OAuth code path exists in the package (import lint) | `security`, `tenancy` |
| End-to-end (3C) | T-E01 | stage `s02_trends` in `CHANNEL_LONG_FORM` on a test tenant with fakes: scan → output pointer → Agent 03 receives qualifying signals only; failure of the scan does not block the job | `e2e` |
Coverage floors are the shared floors of 27 §3; the pure modules (`features`, `scoring`, `screen`, `filtering`, `outlook`, `retention`) require branch coverage of 100 %.

---

## 22 Observability
**MVP: 3C · Tier 0. Shared mechanics: `amw_core.observability` (27 §7.3.6).**
- **Logs** (JSON): `org_id`, `correlation_id`, `job_id`, `task_id`, `attempt_id`, `actor = agent_02`, `step_key`, counts, durations, codes, `prompt_id`, `prompt_sha256`, rule-pack versions, `weights_version`; never titles, labels, keys or watch-list content (hashed refs).
- **Metrics** (all with label `org_id`): `amw_agent02_scan_duration_ms`, `…_items_collected`, `…_items_kept`, `…_quota_units{bucket}`, `…_youtube_calls{endpoint,status}`, `…_llm_tokens{direction}`, `…_cost_micros`, `…_coverage{status}`, `…_signals_total`, `…_signals_qualifying_total`, `…_screen_total{status}`, `…_check_failures{check_id}`, `…_cache_hits_total`, `…_retention_swept_total`, `…_confidence_hist`.
- **Traces**: one span per step (`plan`, `collect`, `features`, `synthesis`, `competitor`, `score`, `persist`) with the correlation ID.
- **Alerts** (design; thresholds ESTIMATE): tenant SEARCH share ≥ 80 % of its daily cap; two consecutive `PARTIAL` scans; any `security.cross_tenant_ref` (L3); any check-failure rate above the eval baseline; sweep overdue (data older than 29 days exists); calibration drift (3C).
- **Dashboards** (S8, owner rule D.2): numbers first, tables, components shown as small bars, colour by meaning (green rising, red fading, amber partial or reframe, grey unknown); phone layout checked for overflow, contrast and cut-off text (owner rule D.3); details hidden behind expanders.
- **Cost and quota visibility**: per scan, per week and per tenant from `cost_ledger`; estimates are `ESTIMATE` until reconciled (09).

---

## 23 Human approvals
**MVP: 3C · Tier 0.**
Agent 02 has **no approval gate**: no approval kind exists for a scan in GLOSSARY §6.15 and none is proposed, because the agent produces advisory input, not a publication or a spend. Human involvement is limited to: (1) **inputs the human owns**: seed topics, the competitor watch-list (audited human edits with the public-data attestation, §19.2), the on/off control `agent_enabled.agent_02` (S8); (2) **review of output**: the owner reads signals in S8 and decides what Agent 03 may use (Agent 03's own topic approval, if any, is its blueprint); (3) **weights**: the opportunity and confidence weights change only by a new `weights_version`, an eval-gated PR, and the owner's decision (directive §3.3 learning loop; no automatic policy change); (4) **unsafe content**: an `UNSAFE_CONTENT` refusal is logged and notified (S7 notification), not an approval (**REQUIRES REVIEW (Agent 01 / S7)** for the exact route). The `owner_sensitive` workflow is never triggered by this agent.

---

## 24 Deployment
**MVP: 3C · Tier 0 (own Compose project and systemd slice per INF-03/04; no new service).**
| Item | Design |
|---|---|
| Service | runs inside the `ai_worker` process (SOURCE_LAYOUT) with capabilities `llm` and `youtube_data_read` (pending CCR-C), queue `ai`, resource class `AI_IO`; a scheduled scan is created by the `scheduler`/orchestrator, never by the worker |
| Environment variable names (**names only; values come from the secret mechanism, never documented**) | `AMW_YT_DATA_API_KEY` (Data API key, scoped to the ai_worker only), `AMW_LLM_API_KEY` (adapter; same variable as the other LLM agents), `AMW_DB_APP_DSN` (`amw_app` login). Final names: `deploy/env.example` and 10_DEPLOYMENT (**REQUIRES REVIEW (10)**) |
| Configuration (not environment) | all `trends.*` keys of §6.8, `llm.agent_02.<step>.*`, retention, schedule interval, per-tenant caps; validated at startup by pydantic-settings (`PERMANENT.CONFIG_INVALID` on failure) |
| Feature switch | `org_controls` key `agent_enabled.agent_02` (S8); off by default until the owner turns it on; platform emergency stop respected |
| Health checks | liveness: worker heartbeat (04 §5.4); readiness: secrets present, DB reachable under `amw_app`, storage writable, prompt files present with matching SHA-256; **no readiness probe calls the Data API** (every call costs quota); an optional daily synthetic canary of one `videos.list` unit runs under the platform org and is counted |
| Start order | PostgreSQL → storage → queue functions → `ai_worker` (registers capabilities) → scheduler. Agent 02 has no startup side effects beyond the config and secret check |
| Stop order | `DRAIN` (03 §4.3): stop claiming, finish or checkpoint the current step, release unused quota reservations, deregister; then stop. The 06:30/07:00 window rules apply to scheduled scans (no admission after the drain time) |
| Migration / rollback | no table, no migration. Roll back by turning the control off and pinning the previous prompt version; stored outputs remain readable (versioned schema) |
| Sizing | inside the `ai_worker` limits (05); no extra memory slice |
| Promotion | `deterministic_core` 100 %, both eval sets at threshold, security and tenancy suites green, the two 3C-blocking review items of §11 closed by the owner |

---

## 25 Acceptance criteria
**MVP: 3C · Tier 0. The agent is "Implemented" only when all are met (rule 7 status words apply).**
| ID | Criterion | Evidence |
|---|---|---|
| AC-1 | A scan on a test tenant with fakes returns a schema-valid output for each mode and for a cache hit | T-I01…T-I04, T-C01 |
| AC-2 | No call without reservation; a replay after a crash makes no second paid call | T-F07, T-I06 |
| AC-3 | Every signal has evidence with resolvable `raw_ref` and matching SHA-256; every number is reproducible by §6 | T-I02, CI replay |
| AC-4 | Both eval sets meet every mandatory threshold of their READMEs (answer-key 100 %, false `CLEAR` 0, refusals 100 %, injection control, coverage 100 %) | eval run record |
| AC-5 | `deterministic_core` passes 100 % | CI |
| AC-6 | Tenant isolation: the 04 §3.7 suite and T-S01…T-S12 pass; no cross-tenant read in any test | security run |
| AC-7 | Only allowed sources reach clustering; forbidden fields never stored; no OAuth path in the package | T-U10…, import lint |
| AC-8 | No stored public API data older than 30 days after the sweep; configuration above 30 is refused | T-I10, RET cases |
| AC-9 | Quota: per-tenant daily share and per-scan cap enforced; PARTIAL and `AWAITING_QUOTA` behave as §18 | T-F04, T-F05 |
| AC-10 | Cost per scan recorded for every call and within `resource_budget`; no budget increase happens automatically | T-I07, T-F10 |
| AC-11 | The output never contains a market, price or security forecast, advice, URL or title copy; `HIGH` confidence impossible with one source family | S5–S7, Q-5 tests |
| AC-12 | The two 3C-blocking review items (§11 data governance) are accepted by the owner in writing before the first live scan; research facts F-A…F-G are entered in RESEARCH_LOG | owner decision record |

---

## 26 Prompt and evaluation pack
**MVP: 3C for running; the files below are written now (documentation) and are the build input. Standard: 27 §4 and §6; format: evals/README.md.**

### 26.1 Steps, prompts and datasets
| Step (task `agent_02.trend_scan`) | LLM? | Prompt file (versioned, immutable once released) | Golden dataset | Cases |
|---|---|---|---|---|
| `synthesis` | yes | `prompts/agent_02_market_intelligence/trend_scan_synthesis.v1.md` | `evals/agent_02_market_intelligence/trend_scan_synthesis/` (`README.md`, `cases.jsonl`, `rubric.md`) | 33: 4 answer-key, 8 hard negatives, 18 edge, 3 refusal |
| `competitor` | yes | `prompts/agent_02_market_intelligence/trend_scan_competitor.v1.md` | `evals/agent_02_market_intelligence/trend_scan_competitor/` (`README.md`, `cases.jsonl`, `rubric.md`) | 28: 4 answer-key, 5 positive, 6 hard negatives, 10 edge, 3 refusal |
| planning, collection, filtering, features, trajectory, confidence, opportunity, lexical screen, outlook wording, retention, assembly | **no LLM** | none (pure code, §6, §10) | `evals/agent_02_market_intelligence/deterministic_core/` (`README.md`, `cases.jsonl`; no rubric: nothing subjective) | 65 across 11 functions |
Answer-key coverage: the four cases of directive §1B.2 are present in both LLM datasets (applied to trend clusters and to competitor breakouts); `agent_06` owns the claim-level answer key itself.

### 26.2 Deterministic checks first
Schema validity; partition and references; refusal mapping; cluster and seed expectations; screen status and rule IDs after the code floor; forbidden rule IDs (including no `FIN-*` when the finance pack is inactive); number provenance; phrase and URL and 40-character copy checks; anomaly coverage; pattern ↔ anomaly kind; relevance ↔ seed match; injection control. The full lists are assertions A1–A16 (synthesis), B1–B14 (competitor), D1–D4 (deterministic) in the dataset READMEs; they run before any judge.

### 26.3 Judge rubric
Criteria and 1–5 anchors are in each `rubric.md` (synthesis: J1 cluster coherence, J2 interpretation grounding, J3 label quality, J4 screen-note quality; competitor: J1 pattern accuracy, J2 description grounding and neutrality, J3 relevance reasoning, J4 screen-note quality). The judge scores subjective quality only and never decides a screen, a partition or a verdict. The judge prompt `agent_02/trend_scan_judge.v1` is **not yet written** (listed in the structured return); it is written with the first build ticket of the step, regression-tested against a human-labelled calibration subset (≥ 10 cases, ±1 point on ≥ 90 % of scores) before it gates CI.

### 26.4 Pass thresholds (summary; authoritative text in the READMEs)
| Dataset | Mandatory (any miss fails CI) | Other |
|---|---|---|
| synthesis | answer-key 4/4; false `CLEAR`/`REFRAME` on expected `EXCLUDED` = 0; refusals 3/3; injection control (A15) | overall ≥ 0.90; false `EXCLUDED` on hard negatives ≤ 1 of 8; judge means ≥ 4.0 (J1, J2) and ≥ 3.5 (J3, J4) |
| competitor | answer-key 4/4; copy/recommendation phrases = 0; false `CLEAR`/`REFRAME` on expected `EXCLUDED` = 0; anomaly coverage 100 %; refusals 3/3 | overall ≥ 0.90; judge means as above |
| deterministic_core | 100 % of cases | — |
Cost and latency are recorded per case (27 §6.4) and reported as p50/p95 and total; no threshold until measured (ESTIMATE). An eval run is capped by `evals.max_run_cost_micros` (owner-authorised, rule 8); offline runs (schema validation of every case input, replay of stored outputs) are free and run on every CI.

### 26.5 Versioning and change control
A prompt change is `v2` (never an edit of `v1` once Released); a change of `llm.agent_02.*` keys, of an injected rule pack or of `weights_version` re-runs the affected dataset (27 §5). New failure patterns found in production become new cases (regression) before the fix. Prompt lint (27 §4.4) checks sections, variable declarations, schema equality with the Pydantic model, example validity, and the absence of model names, prices, dates and clock times.
