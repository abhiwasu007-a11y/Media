# 00b — Technical Feasibility (incl. infrastructure requirements and cost estimates)

| Field | Value |
|---|---|
| Status | **Draft, partial.** Capability verdicts are complete. The server-capacity verdict and per-video totals are **REQUIRES REVIEW (Phase 1)**. |
| Depends on | `00_REPO_AND_SERVER_AUDIT.md` Part C (VPS measurement, pending owner run), `RESEARCH_LOG.md` (wave 1 + wave 2), business plan (videos per month, video length) |
| Directive | §1 (server, isolation, queue, heavy work, window, YouTube), §1A.11, §3.2a, §3.3 (AI providers, cost levers), §5.0 |
| Rule | No number below is invented. Unit prices cite research-log IDs. Quantities that are not yet measured stay as named variables. |

## 1. Capability feasibility (can each required function be done?)

| Function | Needed for | Verdict | Evidence |
|---|---|---|---|
| Private upload, scheduled publish, synthetic-media flag | Agent 13 | **Feasible** | YT-01, YT-04 (always set `privacyStatus=private` explicitly), YT-06 |
| Upload capacity for Tier 0 (one channel) | Agent 13 | **Feasible**: 100 uploads/day default vs a few per week needed | YT-01, YT-02 |
| Quota for captions in several languages | Agent 13, S3 | Feasible; captions.insert costs 400 units, so a 10,000-unit day fits about 20 caption tracks plus the other calls | YT-02 |
| Retention and CTR analytics | Agent 14 | **Feasible via two APIs**: Analytics API (retention) + Reporting API (impressions/CTR) | YT-14 |
| Title/thumbnail A/B test | Agent 11/12/14 | **Feasible only as a human-in-Studio step** (no API found) | YT-08 |
| Marathi + Hindi narration | Agent 07 | **Feasible** with ElevenLabs v3/v4-class models (Marathi is not on Multilingual v2/Flash) | PR-04 |
| Owner voice clone | Agent 07 | Feasible with a recorded consent; YouTube does not require disclosure for one's own cloned voice | PR-04, YT-07 |
| Automated technical QC (loudness, black, freeze, silence) | Agent 10 | **Feasible** with stock FFmpeg filters | INF-09 |
| Delivery spec (H.264, AAC-LC 48 kHz 384 kbps) | Agent 10 | Feasible; video at YouTube's encoder target (8 Mbps at 1080p 24–30 fps), owner decision D10 / ADR-014 (the directive's 15–25 Mbps band is withdrawn, Q-D10-1) | INF-10, INF-12 |
| Postgres queue without Redis | Agent 01 | **Feasible**: two maintained MIT libraries with SKIP LOCKED + LISTEN/NOTIFY | INF-05, INF-06 |
| Tenant isolation in the DB | all | **Feasible** with FORCE RLS + non-owner app role + `SET LOCAL` | INF-11 |
| Hard caps for the factory on the shared server | Agent 01/S5 | **Feasible in principle** (cgroup v2 only on 26.04; systemd slice directives). Compose-to-slice placement is **not confirmed by docs**, so it must be proved by an acceptance test | INF-02, INF-03, INF-04 |
| Licensed stock footage for one owner channel | Agent 08 | Feasible (Individual-class licence, 1 channel) | PR-06 |
| Licensed stock footage for clients | Agent 08 (Tier 1) | Requires Business licence (quote) | PR-06 |
| Explicit monetized-YouTube cover / channel whitelisting for stock | Agent 08 | **Not confirmed** in official licence text; get written confirmation before purchase | PR-06d/e |
| SEBI-compliant price-data use | Agent 05/06/08/16 | Feasible: 30-day lag rule enforced at publish time; no forward-looking statements on named securities | IN-02, IN-03 |

**Conclusion (capabilities): the MVP is technically feasible with external APIs.** No required function lacks a verified path. Three items need action before they are relied on: Compose-to-slice placement (test), stock-licence monetization wording (vendor confirmation), and OAuth scope classification (Console, A4).

## 2. Infrastructure requirements

### 2.1 Components (Tier 0)
| Component | Runs | Resident? | Resource profile | Basis |
|---|---|---|---|---|
| PostgreSQL (factory's own instance) | always during the window; daytime per Q7 | yes | memory-bound, small | own DB per §1 isolation |
| API + dashboard | window; daytime only if the measured footprint is safe (Q7) | yes | light | §3.2a |
| Scheduler/monitor | window; daytime per Q7 | yes | very light | §1 |
| AI worker (LLM/TTS/image calls) | window | no (job-driven) | I/O-bound, light CPU | §1 heavy work external |
| **Render worker (FFmpeg)** | window | no | **CPU-heavy; the main risk on 2 vCPU** | §1 "do not assume the shared VPS can render at scale" |
| Monitoring | lightweight agent + own metrics endpoint | yes | footprint to be measured (no official figure) | INF-07, INF-08 |

Per-component RAM/CPU numbers are **REQUIRES REVIEW (Phase 1)**: they will be measured in the walking skeleton. The directive forbids designing from assumed numbers.

### 2.2 Headroom rule (decides shared VPS vs separate render worker)
```
available_for_factory = measured_total − peak(trading app + BagMitra + OS) − safety_margin
```
- `measured_total`, `peak(...)`: **REQUIRES REVIEW (Phase 1)**, from the VPS audit (24 h sampling, incl. the 00:00–07:00 IST window).
- `safety_margin`: configuration; proposed in `05_RESOURCE_MANAGEMENT.md`.
- Decision:
  1. If the factory's measured peak need (skeleton) is at most `available_for_factory` **inside the night window**, run on the shared VPS under the slice caps.
  2. Otherwise, move **only the render worker** to a separate small server (the code is the same; §3.3 Migration). Per INF-01, the options on the owner's current provider are KVM 1 (₹599/mo, 24-month term) or KVM 2 (₹779/mo); prices are promotional and need re-checking. **Recommendation only. Rule 8: the owner decides and purchases.**
- Before the **first external client**, a dedicated server is required regardless (§1C.14).

### 2.3 Storage
Finished masters, renders and assets are kept on persistent storage with an off-server backup from day one (§3.2a). Size per finished video is **REQUIRES REVIEW (Phase 1)** (measured in the pilot). The audit's `df` output gives the free space.

## 3. Cost estimate per published video (MVP, ESTIMATE)

### 3.1 Formula
```
cost_per_video = LLM + TTS + footage + music + ai_broll + infra_share (+ review time, tracked separately)

LLM        = Σ_stages (input_tokens × price_in + output_tokens × price_out) × batch_factor   [PR-01, PR-02]
TTS        = characters_narrated × takes × price_per_1k_chars / 1000                         [PR-04]
footage    = stock_subscription_per_month / videos_per_month                                  [PR-06]
music      = music_subscription_per_month / videos_per_month                                  [REQUIRES REVIEW]
ai_broll   = seconds_of_ai_video × price_per_second                                          [REQUIRES REVIEW]
infra_share= incremental_server_cost_per_month / videos_per_month                            [INF-01]
```

### 3.2 Verified unit prices
| Input | Value | Source |
|---|---|---|
| Sonnet 5.5 tokens | $2 in / $10 out per MTok | PR-01 |
| Haiku 5.5 tokens | from $0.10 / $0.50 per MTok | PR-01 |
| Opus 5.5 tokens | $4 / $20 per MTok | PR-01 |
| Batch discount | 50% | PR-02 |
| Cache read (Sonnet/Opus 5.5) | 0.05× input price | PR-02 |
| Marathi TTS (v3/v4) | $0.08 per 1K characters | PR-04 |
| Stock footage, one channel | $21–30/month (annual billing) | PR-06 |
| Shared VPS, incremental | ₹0 if headroom allows (existing KVM 2); else render worker ₹599–779/month | INF-01 |

### 3.3 Quantities still needed
| Variable | Status |
|---|---|
| tokens per stage per video (Devanagari tokenizes heavier, §3.3) | **REQUIRES REVIEW (Phase 1)**: measure in the walking skeleton |
| characters narrated per video, takes per video | **REQUIRES REVIEW**: from the pilot (ESTIMATE in PR-04: ≈8–10K characters per 10 minutes of Marathi) |
| videos per month, video length | **REQUIRES REVIEW**: business plan (§1B) |
| music library choice and price | **REQUIRES REVIEW**: ADR-009 (Epidemic Sound price not in HTML; Artlist blocked) |
| AI B-roll seconds per video and price per second | **REQUIRES REVIEW**: ADR-009 (credit-to-seconds mapping not read). Directive §1A.11: budget it per video and prefer real/licensed footage |
| human review minutes per video | **REQUIRES REVIEW**: pilot |

The only line that can be computed now is **TTS for a 10-minute Marathi narration ≈ $0.64–0.80 per take (ESTIMATE, PR-04)**. A full per-video total will be given in the completion report after the skeleton measures tokens.

## 4. Top feasibility risks
1. **Render CPU on 2 shared vCPUs** (unmeasured). Mitigation: render worker can move; measure first.
2. **Compose-to-slice placement not documented** (INF-04). Mitigation: per-container limits + acceptance test of the cgroup files.
3. **Stock licence wording** for monetized YouTube/client work not explicit (PR-06d/e, PR-05). Mitigation: written vendor confirmation before purchase.
4. **SEBI strictness** (IN-03): historical case studies must avoid forward-looking statements on named securities. A design rule, not a technical blocker.
5. **YPP 2027 threshold** (YT-10) lengthens time to AdSense. A business risk, handled in the business plan.
