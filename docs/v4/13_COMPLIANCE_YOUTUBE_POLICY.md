# 13 — Compliance and YouTube Policy (rule packs)

| Field | Value |
|---|---|
| Status (documentation) | Draft for owner review. Software status: Planned |
| Depends on | GLOSSARY_AND_IDS.md (§6.2, 6.15, 6.29, 6.37, 6.38, 6.39–6.43), 03_COMMUNICATION_STANDARD.md (validation_results, §11 compliance verdict routing), 04_DATABASE_ARCHITECTURE.md (§5.2 rule_packs, §5.17 compliance_verdicts, §5.16 editorial_contributions), 07_FAILURE_MANAGEMENT.md (§9), 24_PRODUCTION_TYPES.md (§3.2, §3.3), 27_ENGINEERING_STANDARDS.md |
| Facts cited from | RESEARCH_LOG.md: YT-04, YT-06, YT-07, YT-09, IN-01, IN-02, IN-03, IN-05, IN-06, IN-08 |
| Directive sections | §1, §1A.7, §1B.2, §1B.2a, §1C.7 |
| Owner decisions | D1 (3A/3B/3C), D2 |

**Not legal advice.** This document turns platform policy and the rules in RESEARCH_LOG into checks a machine can run. Every item marked ⚖ must be read by the owner's lawyer before the first public video and again before the first client. Where a value is unknown the text says "REQUIRES REVIEW (Phase 1): <need>". Nothing here is invented: a rule without a research ID is a platform design choice and says so.

Nothing in this document describes private method content. The repository is public.

---

## 1. How rule packs work

### 1.1 Principles
1. A rule pack is a versioned set of rules, each with an ID, a severity, a test and the evidence the gate must store. Keys and scopes are fixed by GLOSSARY §6.37; finance rule IDs by §6.38.
2. Platform packs (`scope = PLATFORM`) cannot be disabled, removed, weakened or bypassed by any tenant (section 11). Tenants may only **add** rules (`rp.tenant_brand_safety`), never remove platform gates (§1C.7).
3. A gate never "fixes" content silently. A failing rule returns a verdict with the rule ID and a rationale. The orchestrator routes it: revision loop up to `limits.max_revision_loops` (07 §9), then the job completes with `outcome = BLOCKED_COMPLIANCE`. A blocked video is never published (03 §11.5, 24 §3.3).
4. A compliance verdict `BLOCKED` is a successful task whose payload says blocked; it is not a failure (03 §11 item 3).
5. Agent 16 is the sole final authority for publication authorisation (plan Q5). Agents 03, 05 and 06 enforce the same rules earlier, so a violation is caught where it is cheapest to fix.
6. A disclaimer never converts advice into education (FIN-R10; IN-03: an educational label does not save a communication that independently has the character of a recommendation).
7. Doubt resolves to `NEEDS_HUMAN_REVIEW`, never to `ALLOWED`. A human override is recorded as a verdict row with `is_final = true` and `decided_by` set to the human actor.

### 1.2 Where each rule is evaluated
Stage names are the canonical task types of 24 §3.2. "Gate" = `agent_16.compliance_gate`.

| Stage | Role in compliance | MVP |
|---|---|---|
| `agent_03` (topic planning) | Rejects topics that can only be answered with a forbidden output (e.g. "NIFTY prediction for next week") | 3C |
| `agent_04.research_pack` | Source-use rules (section 8): library chunks are references, not text to reproduce | 3A |
| `agent_05.script_draft` | Writer receives the active rules in context (`context_ref_purpose = RULE_PACK`) and must not produce forbidden claim types | 3A |
| `agent_06.claim_extraction` | Tags every claim with `claim_type`, `time_reference_kind` and `rule_flags` (GLOSSARY §6.39, 6.41, `rule_flag_severity`). Blocking | 3A |
| `agent_06.claim_verification` | Verifies factual claims; does not decide policy | 3A |
| `agent_10.technical_qc` | Deterministic extraction of the chart/price dates actually rendered (input to FIN-R9) | 3A |
| `svc_s02.uniqueness_check` | Input to YTG-R1 (originality) | 3C |
| `agent_12.metadata` | Title/description/tags are checked by the same rules (a title can itself be a call) | 3C |
| `agent_16.compliance_gate` | Evaluates all active packs on script, claims, render metadata, thumbnails, metadata; records one verdict row per pack and per failed rule | 3A |
| `agent_16.publication_authorisation` | Final verdict (`is_final`); re-runs the date-dependent checks at the real publish time (FIN-R9) | 3C (no upload in 3A, D1) |
| `agent_13.*` publication stages | Sets `privacyStatus` and `containsSyntheticMedia` from the recorded verdicts; never decides policy | 3C |

### 1.3 Evidence stored per check
Every check writes a `validation_results` item (03 schema: `check_id`, `kind`, `verdict`, `blocking`, `rule_id`, `measured`, `threshold`, `message`, `evidence_ref`) and a `compliance_verdicts` row (04 §5.17: `rule_pack_id`, `rule_pack_version`, `rule_id`, `verdict`, `disclosure_decision`, `rationale`, `evidence_ref`, `decided_by`, `is_final`). `subject_sha256` binds the verdict to the exact script/render it judged; a changed subject needs a new verdict.

`check_id` naming used in this document: lower-case, dot-separated, e.g. `fin.r9.price_lag` (matches the 03 pattern `^[a-z0-9_.-]{3,96}$`).

### 1.4 Check kinds
`DETERMINISTIC` (code: dates, counts, lists, metadata fields) is preferred wherever possible. `LLM_JUDGE` is used only where meaning must be read (is this sentence a call?) and is always paired with a deterministic pre-filter and a hard-negative eval set (27 §prompt/eval standards). `HUMAN` is the reviewer's recorded decision. A single LLM_JUDGE `ALLOWED` is never the only evidence for a BLOCKING finance rule on a script that contains a flagged claim: those go to a second independent check or to a human (section 5.4).

---

## 2. Rule-pack record format

### 2.1 Database row (04 §5.2 `rule_packs`, not redefined here)
Columns: `org_id` (NULL for platform), `key`, `version`, `scope`, `category`, `always_on`, `removable`, `rules_ref`, `rules_sha256`, `status`, `effective_from`. Constraints from 04: `(scope = 'PLATFORM') = (org_id IS NULL)`; `removable = false` for every PLATFORM pack; `always_on = true` only for `rp.youtube_general`.

| key | scope | category | always_on | removable | status at first release | effective_from |
|---|---|---|---|---|---|---|
| `rp.youtube_general` v1 | PLATFORM | `youtube_general` | true | false | ACTIVE | at release; owner sets |
| `rp.finance_sebi_in` v1 | PLATFORM | `finance` | false | false | ACTIVE | at release (circulars already in force, IN-02: 1 Jul 2026) |
| `rp.health` v1 | PLATFORM | `health` | false | false | DRAFT (stub, section 6) | not set |
| `rp.kids` v1 | PLATFORM | `kids` | false | false | DRAFT (stub) | not set |
| `rp.political_news` v1 | PLATFORM | `political_news` | false | false | DRAFT (stub) | not set |
| `rp.tenant_brand_safety` v1 | TENANT | `brand_safety` | false | tenant-set | tenant-set | tenant-set |

`rp.advertising_asci_in` and `rp.ad_sector_<sector>` belong to 25_ADVERTISING_COMPLIANCE.md and are not defined here.

`rules_ref` is a storage URI of the rule file (04 rule 6: content lives in storage, the DB holds URI + SHA-256). `rules_sha256` is the SHA-256 of the canonical bytes of that file (UTF-8, LF line endings, keys sorted). A pack whose stored file does not hash to `rules_sha256` is refused at load time and the job fails to start with an operator alert; the gate never runs against an unverified pack.

Seed data: platform packs are seeded by the versioned migrations (04 §11 item 3). A pack version is immutable once `ACTIVE`; a change is a new `version`; the old one becomes `RETIRED` but stays readable so old verdicts remain explainable (`compliance_verdicts.rule_pack_version`).

### 2.2 Rule file (the object `rules_ref` points to)
Every pack file has this shape (JSON or YAML; shown as YAML). The rule-file layout is documentation content owned by this document; it adds no table, enum or column. Fields use existing enums only.

```yaml
pack:
  key: rp.finance_sebi_in          # GLOSSARY §6.37
  version: 1
  legal_basis_ids: [IN-01, IN-02, IN-03, IN-05]   # RESEARCH_LOG ids
  re_verify_before_release: true   # circulars/orders can change; see section 12
rules:
  - rule_id: FIN-R9                # GLOSSARY §6.38 (fixed IDs)
    title: "Price data older than the prescribed lag"
    severity: BLOCKING             # rule_severity
    applies_to: [script, render, thumbnail, metadata]
    evaluated_at: [agent_16.compliance_gate, agent_16.publication_authorisation]
    check_kind: DETERMINISTIC      # check_kind
    config_keys: [compliance.finance_sebi_in.price_data_lag_days]
    test: "<precise test, section 5>"
    evidence: [chart_data_end_date, publish_date, computed_age_days]
    pass_examples: [...]
    fail_examples: [...]
    escalation: BLOCKED            # compliance_verdict
    lawyer_review: true            # the warning sign in this document
```

### 2.3 Verdict mapping
`compliance_verdict`: `ALLOWED` / `BLOCKED` / `NEEDS_HUMAN_REVIEW`. `check_verdict`: `PASS` / `FAIL` / `WARN` / `SKIPPED`. A BLOCKING rule that fails gives `FAIL` + `BLOCKED`. A WARNING rule gives `WARN` and does not block but appears in the QC report. `SKIPPED` is permitted only when the rule's precondition is false (e.g. no chart in the video) and the precondition itself is recorded as evidence. A rule that cannot be evaluated (missing data) is `NEEDS_HUMAN_REVIEW`, never `SKIPPED`.

---

## 3. Pack `rp.youtube_general` (always on, every YouTube destination)

MVP: **3A** (evaluated by the gate on files, with no upload); publication-time items 3C. Enterprise: Tier 0.

Rule IDs in this pack use the prefix `YTG` (pending CCR: GLOSSARY §6.2 defines the `<PACK>-R<n>` form but fixes only the `FIN` IDs; see contract_requests).

| Rule ID (pending CCR) | Severity | Rule | Basis |
|---|---|---|---|
| `YTG-R1` | BLOCKING | Inauthentic / mass-produced content gate | YT-09 |
| `YTG-R2` | BLOCKING | No AI persona presenting a sensitive topic (health, legal, finance, politics) | YT-09 |
| `YTG-R3` | BLOCKING | Synthetic/altered-media disclosure decision recorded | YT-06, YT-07 |
| `YTG-R4` | BLOCKING | Human editorial contribution and human approval on every video | §1A.7, YT-09 |
| `YTG-R5` | BLOCKING | Reused / third-party content: nothing used without a recorded right | REQUIRES REVIEW (Phase 1) |
| `YTG-R6` | BLOCKING | Licence completeness and validity for every asset, music and font | §1A.1, 04 `licences` |
| `YTG-R7` | BLOCKING | Made-for-kids handling | REQUIRES REVIEW (Phase 1) |
| `YTG-R8` | BLOCKING | Publication defaults: `privacyStatus` explicit, never unset | YT-04 |
| `YTG-R9` | BLOCKING | Source-library copyright: no reproduction or close paraphrase | IN-08, §1B.2a (section 8) |
| `YTG-R10` | BLOCKING | IT Rules synthetic-information declaration and provenance label | IN-06 (section 9) |

### 3.1 YTG-R1 Inauthentic content (YPP)
- **Fact.** YouTube renamed "repetitious content" to "inauthentic content" on 2025-07-15. It is applied to the channel as a whole; interchangeable videos cannot monetize; "AI-generated content made with generic or unoriginal templates giving the impression of mass production" is listed as not allowed (YT-09).
- **Test.** Input: `svc_s02.uniqueness_check` output (similarity of the script, structure, visuals and thumbnail to the channel's own recent videos and to the template's skeleton) plus the recorded editorial contributions (YTG-R4). Blocks when (a) the uniqueness gate returns FAIL, or (b) the video has no recorded human contribution, or (c) the script's structure and shot plan are identical to the production-type template except for the topic noun. Threshold values: **REQUIRES REVIEW (Phase 1): uniqueness thresholds are set from the golden samples in 3B and the S2 design (doc 16); no number is invented here.**
- **Evidence.** Uniqueness report URI, the compared video IDs, the contribution rows.
- **3A scope.** The deterministic part (b) and (c) runs in 3A. The cross-video similarity needs S2 and a back catalogue and is 3C; in 3A the check records `SKIPPED` with the precondition "no prior videos on the channel" for the first three samples, and `NEEDS_HUMAN_REVIEW` thereafter.
- ⚖ Whether a given workflow counts as "interchangeable" is YouTube's judgement and can change; the rule is a risk reducer, not a guarantee of monetization.

### 3.2 YTG-R2 No AI persona on sensitive topics
- **Fact.** AI personas on sensitive topics (health, legal, finance, politics) are not monetizable (YT-09). For the first channel this is `FIN-R11` as well.
- **Test.** Deterministic: the production type's `presenter_kind` and the voice/visual assets. Blocks when the video presents a synthetic human face or a synthetic voice presented as a named person on a channel whose compliance profile includes `rp.finance_sebi_in`, `rp.health` or `rp.political_news`. Allowed: the owner's own voice (including a clone of the owner's own voice, YT-07 says cloning one's own voice does not by itself need disclosure) and neutral narration with no persona. A persona is detected from the script (first-person identity claims such as a named presenter) and from the asset list (`is_realistic_synthetic` on a person image/video, 04 asset table).
- **REQUIRES REVIEW (Phase 1):** the field that records "neutral narration vs persona" on a production type or job input. It is not in the Wave A contracts reviewed for this document (contract_requests).

### 3.3 YTG-R3 Synthetic or altered content disclosure
- **Fact.** Disclosure is required for realistic altered or synthetic content: a real person saying or doing something they did not, altered real events or places, realistic scenes that did not occur. Not required: unrealistic content, minor edits, script/title/thumbnail assistance, captions, cloning one's own voice. Penalties include removal and YPP suspension. Disclosure alone does not limit monetization (YT-07). The API field `status.containsSyntheticMedia` is writable on insert and update (YT-06).
- **Decision (Agent 16).** Enum `disclosure_decision` = `REQUIRED` / `NOT_REQUIRED` / `NEEDS_HUMAN_REVIEW` (GLOSSARY §6.43). Inputs: every asset's `is_realistic_synthetic` flag (04), the `source_type` of each asset, the shot plan's description of realism.
  - `REQUIRED` when any asset is realistic AI video B-roll or a realistic AI still depicting a scene that did not occur, or a realistic synthetic person.
  - `NOT_REQUIRED` when every AI-touched element falls in the YT-07 "not required" list (code-made charts and motion graphics, owner voice, captions, editing).
  - `NEEDS_HUMAN_REVIEW` when the flag is missing or the shot's realism is ambiguous.
- **Record.** The decision is stored on the verdict row (`compliance_verdicts.disclosure_decision`) and is the single source for `publications.contains_synthetic_media` (04: required for YOUTUBE, linked through `disclosure_verdict_id`). Agent 13 copies it; it does not recompute it.
- **3A scope.** The decision and its rationale are produced and shown in the QC report. No upload happens in 3A (D1), so the owner applies the label by hand in Studio; the report says so in plain words. Setting the API field is 3C (Agent 13).
- ⚖ The boundary between "realistic" and "unrealistic" is a judgement; counsel should review the working definition before the first AI B-roll video.

### 3.4 YTG-R4 Human editorial contribution and approval
- **Fact.** YPP inauthentic-content enforcement looks for meaningful human creative input (directive §1; YT-09). The directive requires one-tap approve/reject per video with at least one recorded contribution (§1A.7).
- **Test.** Deterministic: at least one `editorial_contributions` row for the job, `description` ≥ 20 characters (configurable; 04 §5.16), written by a human (the DB trigger already rejects agent writers); type in `ANGLE` / `EXAMPLE` / `OPINION` / `CORRECTION` (GLOSSARY §6.16). An approval row of kind `FINAL_VIDEO` (or `PUBLISH`) in state `APPROVED` with `subject_sha256` equal to the render hash. A rendered video that changed after approval needs a new approval.
- **Quality guard.** A contribution that is a copy of the same sentence across videos (checked by exact and near-duplicate match against that channel's previous contributions) is flagged WARNING and shown to the approver. Near-duplicate threshold: **REQUIRES REVIEW (Phase 1): set from observed data.**
- **3A scope.** In 3A the owner reviews and scores each sample; the contribution record and the approval are still required in the data model so the rule is proven before 3C. The owner's score does not replace the approval record.
- **Honesty note.** This rule documents that human input exists. It does not prove YouTube will judge it as meaningful; that depends on the actual content (⚖ for any client-facing promise).

### 3.5 YTG-R5 Reused content
- The official YouTube reused-content text is **not in RESEARCH_LOG**. **REQUIRES REVIEW (Phase 1): read the official YouTube reused-content / inauthentic-content help page and add a YT-xx entry.** Until then this rule is the conservative platform design rule and is labelled so:
  - Every video, clip, image, audio or text in the final render must trace to a recorded source with a right (owner-made, code-generated, licensed with a ledger entry, or AI-generated by a recorded provider call). An asset with no source is a BLOCKED verdict.
  - No third-party YouTube video, film clip, TV or news footage is used unless a licence record covers it. "Fair use" is never assumed; Indian fair dealing is narrow (IN-08).
  - Commentary or review content that quotes third-party footage is `NEEDS_HUMAN_REVIEW` and the approval kind `COPYRIGHT_DOUBT` is raised.
- **Test.** Deterministic cross-check: asset manifest of the render vs `assets.licence_id` / `source_type` (04). 3A: yes (the assets come from the 3A asset agent and stock/own sources).

### 3.6 YTG-R6 Licence completeness
- **Test.** Every asset used in the final render has `licence_id` unless `source_type` is `OWNER_MADE` or `CODE_GENERATED` (the 04 CHECK already enforces this); the licence is `ACTIVE` at the evaluation time and at the publish time (not `EXPIRED`, `REVOKED`, `REJECTED`, `PENDING_VERIFICATION`; `EXPIRING` is a WARNING). Licence terms must cover the use (monetized online video, commercial) — the licence record's `uses` flags are checked; vendor text that does not state monetized use is `NEEDS_HUMAN_REVIEW` (RESEARCH_LOG PR-06d/e records that one vendor's text does not say it and names no whitelisting feature).
- **Evidence.** Licence ledger entries, vendor item IDs, the licence text hash.
- ⚖ Each vendor licence for the commercial-use boundary.

### 3.7 YTG-R7 Made-for-kids handling
- The YouTube `madeForKids` / `selfDeclaredMadeForKids` field details are **not verified** in RESEARCH_LOG, and 04 §5.21 already says so. **REQUIRES REVIEW (Phase 1): verify the field on the official `videos` resource page; then add a research ID and a column request.**
- Platform rule (design): every channel has a recorded `audience_kind` decision at channel setup; a video is declared made-for-kids only by a human approval, never by an agent. A channel whose profile includes `rp.kids` follows section 6. A video whose script or visuals target children (animation aimed at children, nursery content) on a channel not marked kids is `NEEDS_HUMAN_REVIEW`. The platform does not set the YouTube field in 3A or 3B.
- ⚖ Children's data rules (DPDP notice for children, IN-07, ~May 2027) are owned by doc 22.

### 3.8 YTG-R8 Publication defaults
- **Fact.** An unset `privacyStatus` is not treated as private; the private-lock for unverified projects was removed (YT-04).
- **Rule.** Publication tasks always set `privacyStatus` explicitly, in the first upload request, to `private`; going public is a separate step after authorisation, and a read-back verifies the stored value (04 `verification_details`). **3C** (Agent 13). 3A has no upload and so no data path for this rule; the rule is listed so the 3C build cannot omit it.

---

## 4. Platform vs tenant packs: what a tenant may and may not do

| Action | Platform pack | Tenant pack (`rp.tenant_brand_safety`) |
|---|---|---|
| Add a pack to a profile | Yes (e.g. add health) | Yes |
| Remove a pack that is mandatory | **No** (section 11) | Yes |
| Disable a rule inside a pack | **No** | Own rules only |
| Lower a rule's severity BLOCKING → WARNING | **No** | Own rules only |
| Add a stricter rule | Yes, as a tenant rule | Yes |
| Change a threshold config (e.g. lag days) | Only to a **stricter** value (larger lag); never smaller than the pack value | n/a |
| Override with human approval | A human override records `is_final` and an `approval_kind = POLICY_CHANGE` or `SENSITIVE_CLAIM` decision; it does not edit the pack | Same |

Tenant packs are checked **after** the platform packs. Their rules may add BLOCKING checks; if a tenant rule contradicts a platform rule, the platform rule wins and the contradiction is logged. MVP: tenant packs **3C**, Tier 1 (first managed-service client) at the earliest; REQUIRES REVIEW (Phase 1): the exact tier gate from §1C.15.

---

## 5. Pack `rp.finance_sebi_in` (finance / securities, India)

MVP: **3A** for all rules that act on a script, claims or render (FIN-R1, R2, R3, R6, R7, R9 check on the files, R10, R11, R12, R13); **3C** for rules that act on channel business, live activities, publication time or revenue (R4, R5, R8 are checked at channel/profile setup and at publication). Enterprise: Tier 0 (the owner's first channel); reused by any client in finance at Tier 1+.

Active when the channel or category is finance (24: `rp.finance_sebi_in` for the first channel). Source: directive §1 and §1B.2; IDs fixed in GLOSSARY §6.38.

### 5.0 Facts the pack rests on
| ID | What it says (summary) |
|---|---|
| IN-01 | Regulated entities may not associate with a person who gives unregistered advice or makes return claims; an investor-education-only person is exempt only if they do neither, directly or indirectly. |
| IN-02 | SEBI circular of 8 May 2026, effective 1 Jul 2026: price data for education must lag by 30 days; an education-only person should not use market price data of the preceding thirty days "to speak/talk/display the name of any security". |
| IN-03 | A communication that independently has the characteristics of advice or a buy/sell/target/stop-loss recommendation is not saved by an educational label. The final order of 23 Oct 2026 (Avadhut Sathe Trading Academy) says the person shall not use "live or historical data which provides future directional movement for a specified security". The 2 Dec 2024 order concerned unregistered buy/sell/hold calls. |
| IN-05 | ASCI influencer rules: in BFSI related to stocks or investments, the influencer should be registered with SEBI and state the registration number; paid promotions need disclosure labels. |

All values labelled VERIFIED in RESEARCH_LOG except where the log says SECONDARY or NOT CONFIRMED (the RA Regulations definitions are known only through the order, IN-03). ⚖ Counsel must read the circulars, regulations and orders directly.

Owner's registration status is **unknown** (owner input A6 pending). The pack assumes **not registered** (FIN-R8 text: "while the owner is unregistered"). REQUIRES REVIEW (Phase 1): the owner's SEBI registration status and any plan to register. ⚖

### 5.1 Rule table
| Rule ID | Severity | Rule (full text) | Primary test | Check kind | Stage(s) |
|---|---|---|---|---|---|
| FIN-R1 | BLOCKING | No buy, sell or hold call on any instrument | `claim_type = RECOMMENDATION` in claims; wording and imperative/modal scan | LLM_JUDGE + DETERMINISTIC pre-filter | 05, 06, 16 (03, 12 in 3C) |
| FIN-R2 | BLOCKING | No entry, exit, stop-loss or target level, strike or trigger price for a **current** instrument | `claim_type = PRICE_LEVEL` and `time_reference_kind` in `CURRENT`, `FUTURE`, `UNSPECIFIED` | LLM_JUDGE + DETERMINISTIC | 05, 06, 16 |
| FIN-R3 | BLOCKING | No "what to do tomorrow / this week" market view; no forward view on a current market | `claim_type = FORWARD_VIEW` | LLM_JUDGE | 03, 05, 06, 16 |
| FIN-R4 | BLOCKING | No live-market session, live trade screen-share, or "live strategy" session | Production type / destination check; metadata scan for "live" formats | DETERMINISTIC | profile/production-type setup (3C), 16 |
| FIN-R5 | BLOCKING | No paid group giving ongoing market guidance | Funnel/CTA scan (script, description, pinned comment text) against paid-group offers | LLM_JUDGE + DETERMINISTIC | 05, 12, 16 |
| FIN-R6 | BLOCKING | No performance, profit or return claim (including one's own strategy or students) | `claim_type = PERFORMANCE_CLAIM` | LLM_JUDGE + DETERMINISTIC | 05, 06, 16 |
| FIN-R7 | BLOCKING | No profit testimonial | `claim_type = TESTIMONIAL` with a financial outcome | LLM_JUDGE | 05, 06, 16 |
| FIN-R8 | BLOCKING | No broker referral/affiliate income and no paid association with a SEBI-regulated entity while the owner is unregistered | `claim_type = PROMOTION` to a regulated entity; link/URL list; sponsor field | DETERMINISTIC + LLM_JUDGE | 05, 12, 16 |
| FIN-R9 | BLOCKING | Market price data only when older than `compliance.finance_sebi_in.price_data_lag_days` (30), applied at publish time | Last-bar date of every chart and every dated price vs publish date | DETERMINISTIC | 10 (extract), 16 (evaluate), 16 auth (3C re-check) |
| FIN-R10 | BLOCKING | Every finance video carries the required disclaimer; a disclaimer never turns advice into education | Presence and placement of the disclaimer text; no rule is waived because of it | DETERMINISTIC | 05, 10, 12, 16 |
| FIN-R11 | BLOCKING | No AI presenter persona on a finance channel | See YTG-R2 | DETERMINISTIC | 05, 08, 16 |
| FIN-R12 | BLOCKING | "Our method" content only on historical charts, clearly labelled, only from material the owner released | `KNOWLEDGE_RELEASE` approval for the source chunk; label present; chart data end date older than the lag | DETERMINISTIC | 04, 05, 16 |
| FIN-R13 | BLOCKING | No forward-looking statement about the future direction of a named security, even when the chart uses data older than the lag | See 5.5 | LLM_JUDGE + DETERMINISTIC + human | 03, 05, 06, 16 |

The word "instrument" here follows the directive: an index, a stock, an option or any tradable item. Whether an index (e.g. NIFTY) is a "specified security" under IN-03 is **not settled in RESEARCH_LOG**: the pack treats a named index like a named security (stricter). ⚖

### 5.2 FIN-R1 No buy/sell/hold call
- **Blocks.** Any statement that tells the viewer, or implies, to buy, sell, hold, enter, exit, add, accumulate, avoid, or "go long/short" a named instrument; a title or thumbnail doing the same; a rhetorical form ("would you buy here?" accompanied by a conclusion).
- **Allows.** Defining what a buy signal is in a generic indicator; describing what a past trader could have seen on a past chart, in the past tense, with no present application.
- **Evidence.** Claim IDs flagged, the sentence, `claim_type`, rationale.
- **Source.** IN-03 (an educational label does not save a call); 2 Dec 2024 order (unregistered buy/sell/hold calls).

### 5.3 FIN-R2 No levels for a current instrument
- **Blocks.** Any price, strike, expiry-specific strike choice, trigger, stop or target for a currently trading instrument, in speech, on-screen text, thumbnail or description; an annotated chart whose horizontal lines are located at levels that are still relevant to the current price (checked by the last-bar test of FIN-R9 and by FIN-R13).
- **Allows.** Levels on a historical chart with a data end older than the lag, labelled historical, where the narration describes what happened.
- **Evidence.** Extracted numbers with context, instrument name, `time_reference_kind`.

### 5.4 FIN-R3 / FIN-R13: forward views and the Sathe bar (see 5.5 for cases)
- FIN-R3 stops views about "now/tomorrow/this week". FIN-R13 is wider: it stops forward-looking statements about a **named** security in any frame, including a historical case study.
- The deterministic pre-filter flags sentences with a named instrument plus a future-tense/modal/expectation marker ("will", "should", "likely to", "target", "next move", "again", "repeat", "same setup now"). Because an LLM judge can miss subtle phrasing, **a flagged claim with any future marker is `NEEDS_HUMAN_REVIEW` at minimum, never `ALLOWED` on an LLM verdict alone**.
- **The two-part test for a historical case study.** (1) *Frame*: the narration is in the past tense about what the chart showed and what happened next; (2) *Purpose*: the segment teaches the concept ("how the pattern was identified, why it worked or failed") and does not leave the viewer with an expectation about where that security goes next. If either part is not met: BLOCKED (FIN-R13). The case study is described as "how the concept looked, why it worked or failed then", with no forward-looking statement about the security (RESEARCH_LOG IN-03, rule-pack addition).

### 5.5 FIN-R9 Price-data lag (IN-02)
- **Rule.** `publish_date − latest_price_date_in_video ≥ price_data_lag_days` (config `compliance.finance_sebi_in.price_data_lag_days`, default **30**, from IN-02). The platform may raise it, never lower it (section 4).
- **What is a "price date".** The date of the last bar in every chart; the dates attached to any quoted price, index level, percentage change or "today's close"; the dates in any table. All are extracted deterministically: chart renders come from code (§1A.1a), so the last bar date is known from the data, not read from pixels. A text price without a date is `NEEDS_HUMAN_REVIEW`.
- **At publish time.** The check is evaluated at the intended publish date, not the script date. The gate stores `evaluated_publish_date` and the age in days. If the publish date moves later, the age only grows (safe); if a scheduled publish is brought forward, the check is re-run by `agent_16.publication_authorisation` and again by Agent 13 immediately before the upload/publish step (3C).
- **3A (no upload).** The QC report states the latest price date in the video and the **earliest compliant publish date** (latest price date + lag). The owner uploads by hand; an upload before that date is the owner's responsibility and the report states this. Calendar days are assumed; whether the 30 days count calendar days or trading days is **REQUIRES REVIEW (Phase 1): confirm from the circular's text; ⚖**.
- **Which instruments.** IN-02's quoted wording covers "any security" for the preceding thirty days. Non-price data (volume, fundamentals) are not addressed by the log: **REQUIRES REVIEW ⚖**.
- **Evidence.** Per-chart data end date, `publish_date`, `lag_days`, computed age, source dataset hash.
- **Re-verify before build.** RESEARCH_LOG IN-02 notes that "no later change" was checked by search only; re-read the circular before release (section 12).

### 5.6 FIN-R10 Disclaimer
- **Rule.** Each finance video carries the required disclaimer: spoken (at the start and the end, or as the owner's lawyer decides), on screen for the duration set by the lawyer, and in the description. Missing or unreadable disclaimer = BLOCKED.
- **Wording, duration and placement:** **REQUIRES REVIEW (Phase 1): the exact disclaimer text in each language (Marathi, English), minimum on-screen time and font size, from the owner's lawyer. ⚖** No text is invented here.
- **Deterministic tests.** The disclaimer asset is a versioned text per language; the render must contain it (on-screen text overlay check from the render manifest; description contains the same text hash); the audio script contains the spoken form. The QC checks legibility against the same readability checks as other overlay text (INF-09 family, doc 18).
- **Never.** A disclaimer is not used as a reason to pass a failing rule: the gate evaluates every other rule as if the disclaimer were absent (IN-03).
- **Education-only statement.** The disclaimer should state that the content is educational and that the owner is not a SEBI-registered adviser **if and only if** that is true on the date (owner input A6 pending). ⚖

### 5.7 FIN-R4, R5 Channel activities (profile-level)
- **FIN-R4.** The production type registry has no live-session production type and the gate refuses a `LIVE` format; metadata that announces "live trading", "live strategy" or a live screen-share is BLOCKED. A live stream is not in any MVP scope.
- **FIN-R5.** A paid group or membership whose benefit is ongoing market guidance is BLOCKED wherever it is advertised in the video, thumbnail, description or pinned comment. The owner's own course (pure education, no ongoing tips) is allowed (§1B.2). Course material that contains ongoing tips would be outside this rule's allowance; the check on the course itself is outside this system (REQUIRES REVIEW ⚖).
- Both are checked at channel creation (profile attached) and on every video's text.

### 5.8 FIN-R6, R7 No performance claims, no testimonials
- **FIN-R6.** Blocks any claim of past, present or hypothetical-but-presented-as-achievable profit or return ("my strategy made X% last month", "this approach doubles money", "win rate of N%"), including a number shown on a backtest screen when it is presented as a performance claim. A **backtest-methodology lesson** (how to build and read a backtest) is allowed only if no result figure is presented as evidence that the method works or will work; results shown as numbers need `HYPOTHETICAL_EXAMPLE` framing and a human review. Whether any hypothetical result display is acceptable is a ⚖ question; the default is `NEEDS_HUMAN_REVIEW`.
- **FIN-R7.** Blocks any testimonial of profit by a student or follower (spoken, on screen, in comments pinned by the channel).
- **Evidence.** The figure, its context, `claim_type`.

### 5.9 FIN-R8 No regulated-entity association; BFSI influencer rule (IN-01, IN-05)
- **Blocks.** Broker referral links, affiliate links, referral codes, sponsored mentions of a broker, exchange or other SEBI-regulated entity; "open an account via this link"; any paid association that IN-01 describes (money or money's worth, client referral, IT-system interaction).
- **Also blocks (IN-05).** Paid promotion of stock/investment products by the channel while the owner is unregistered: ASCI says BFSI influencers in stocks/investments should be registered with SEBI and state the number. The owner's own course/ATP promotion is self-promotion, not an influencer ad; it is labelled transparently anyway (IN-05 implication in the log). ⚖
- **Allowed (directive).** Own course, ATP as a tool, sponsorship by non-regulated businesses, AdSense after YPP.
- **Test.** Deterministic: URL domain list (maintained per channel; regulated-entity domains are a platform-maintained list: **REQUIRES REVIEW (Phase 1): source and upkeep of the regulated-entity list**); sponsor/PROMOTION claims; description link audit. LLM judge on spoken endorsements. Unknown domain with a referral parameter = `NEEDS_HUMAN_REVIEW`.
- **Registration condition.** If the owner registers, this rule's text changes via a new version and a `POLICY_CHANGE` approval; it is never switched off for a tenant (REQUIRES REVIEW ⚖).

### 5.10 FIN-R11 No AI persona
- Evaluated as YTG-R2 (a synthetic person presented as a presenter). The owner's own voice (including a clone of the owner's own voice, YT-07) or neutral narration is allowed. Also blocks stock "spokesperson" avatars and a named virtual host.

### 5.11 FIN-R12 "Our method" content
- **Rule.** Content that teaches the owner's own entry conditions appears only (a) as a clearly labelled "our method" topic, (b) on historical charts that satisfy FIN-R9 and FIN-R13, (c) from material the owner explicitly released for that topic (approval kind `KNOWLEDGE_RELEASE`, plan Q26; `knowledge_sources.release_approval_id`, 04), and (d) never mixed into a general-concept video and never as a current-market instruction.
- **Test.** Deterministic: every script segment carrying a method label cites a source chunk whose release approval exists and is `APPROVED`; the video contains the label overlay; an unlabelled segment citing a method chunk is BLOCKED. Segment citing a chunk with no release is BLOCKED. The method itself is not described in this document and is never copied here.

### 5.12 Answer-key cases (directive §1B.2; used as eval hard cases)
The four cases below are tests for the gate, not rule text.

| # | Input | Expected verdict | Rule(s) | Reason |
|---|---|---|---|---|
| A1 | "How a bullish RSI divergence looked on a past NIFTY chart and why it failed/worked", chart data older than the lag, past tense, no current application | **ALLOWED** (with disclaimer) | passes R1–R3, R9, R13 | Historical, lagged, no current call; passes the two-part test (5.4) |
| A2 | "NIFTY looks weak, sell the 24,000 call this week" | **BLOCKED** | R1, R2, R3 | A current call with a strike and a forward view |
| A3 | "My strategy made X% last month" | **BLOCKED** | R6 | A return claim |
| A4 | "Open an account with broker Y via this link" | **BLOCKED** | R8 | Regulated-entity association |

### 5.13 Sathe-type cases (IN-03; the order's wording belongs in the hard negatives)
These are test cases written for the gate. The order is described only as stated in RESEARCH_LOG IN-03.

| # | Input | Expected | Rule | Why |
|---|---|---|---|---|
| S1 | A chart of a named stock older than the lag, narrated "this pattern formed here, and this is why the price usually goes up from such a setup, so watch for it again" | BLOCKED | R13 (also R3) | Historical data used to give future direction for a named security; the data age does not rescue it |
| S2 | Same chart narrated "the price rose 12% after this pattern; it can do the same in future" | BLOCKED | R13 | Forward statement attached to a named security (and a figure; R6 checked) |
| S3 | Same chart narrated "this is how the pattern was identified, why the entry condition triggered, and why the trade failed when momentum weakened" | ALLOWED | passes R13 | Concept explanation in the past tense, no expectation about the future |
| S4 | A video titled "Is NIFTY ready to fall? Chart says yes" with a lagged chart | BLOCKED | R13, R3 | A directional conclusion in the title; the chart's age is irrelevant |
| S5 | Generic chart with unnamed, synthetic or anonymised prices, narration of a general rule | ALLOWED if no named security and labelled as an example | passes R13 | IN-03 speaks of a "specified security"; ⚖ whether anonymised real data is acceptable |
| S6 | Cut-away showing today's chart for "context" while explaining a concept | BLOCKED | R9 | Data not older than the lag |
| S7 | A mention of a named stock's past event by name in a lesson without any direction | `NEEDS_HUMAN_REVIEW` | R9 / R13 | IN-02 says a named security's data of the last thirty days cannot be spoken or displayed; older data is allowed; human checks that nothing implies direction |

### 5.14 Finance pack data inputs to the gate
- `claims` (04 §5.11) with `claim_type`, `time_reference_kind`, `rule_flags`.
- Render manifest: charts with data end dates and source dataset hashes; overlay texts; thumbnail text.
- Metadata: title, description, tags, pinned comment text, links.
- Channel profile: attached packs, owner registration flag (REQUIRES REVIEW), regulated-entity link list.
- Config: `compliance.finance_sebi_in.price_data_lag_days` (30).

### 5.15 Evals required for this pack (27)
The ≥ 20 golden cases for Agent 16's compliance prompt must include: the four answer-key cases (A1–A4); S1–S7; the wording of the 23 Oct 2026 order quoted in IN-03 as a hard negative; ten more per rule with at least one near-miss ALLOWED example for R1, R2, R3 and R13 each (so the judge is not tuned only to block); a Marathi-language set and an English set (the channel is Marathi-first). The eval packs live at `evals/agent_16/compliance_gate/` and `evals/agent_06/claim_extraction/` per the naming convention in REPO_MAP. Exact case counts: **REQUIRES REVIEW (Phase 1): fixed in the Agent 16 blueprint (26 §)**. Marathi legal-term mapping to the English rules: ⚖.

### 5.16 What the pack does not do
It does not decide whether the owner needs SEBI registration, whether the owner's course complies, or whether a certain activity is "investment advice" in law. It applies conservative, written, testable rules, and sends doubtful cases to a human and then to the lawyer. ⚖

---

## 6. Stub packs (tier-marked)

Stubs: only a skeleton exists; rule text is **REQUIRES REVIEW (Phase 1)** with no research ID yet. They are `DRAFT` and cannot be attached to a profile until `ACTIVE` (a profile that needs a stub category is refused with a clear message, not silently allowed).

| Pack | MVP | Enterprise tier | What is known | Skeleton checks |
|---|---|---|---|---|
| `rp.health` | 3C | Tier 1 (first client in a health niche) | YT-09: AI persona on health is not monetizable. §1D.3 names a `rp.ad_sector_health_wellness` for ads (doc 25). | No AI persona (YTG-R2); medical-claim extraction through `claim_type = PRODUCT_CLAIM` and `FACTUAL`; sensitive-claim approval kind `SENSITIVE_CLAIM`; no diagnosis/cure/treatment claims, no dosage advice. **REQUIRES REVIEW (Phase 1): YouTube medical misinformation policy text and Indian rules (e.g. drugs and magic remedies, ASCI health codes) as RESEARCH_LOG entries. ⚖** |
| `rp.kids` | 3C | Tier 2 | Made-for-kids field details not verified (04 §5.21; YTG-R7). DPDP children's rules in force about May 2027 (IN-07). | Audience-kind declaration, no targeted engagement features, no personal data of children. **REQUIRES REVIEW (Phase 1): COPPA/YouTube kids policy and field names; ⚖** |
| `rp.political_news` | 3C | Tier 2 | YT-09: AI persona on politics is not monetizable. SGI rules (IN-06) apply strongly to realistic depictions of real people. | No synthetic depiction of a real person; election-period rules; news claim verification at higher threshold. **REQUIRES REVIEW (Phase 1): Indian election-period rules, YouTube news/elections policy text; ⚖** |

A stub pack key is reserved so that profiles, production types (24 `rule_packs` by category) and DB seeds can refer to it. Its rule IDs (`HLT-R`, `KID-R`, `POL-R`) are pending CCR.

---

## 7. Tenant brand-safety pack (`rp.tenant_brand_safety`)
Tenant-defined additions: banned topics, banned words and phrases, required disclaimers, competitor mentions. Stored as a tenant-scope `rule_packs` row (`org_id` set, `scope = TENANT`, `category = brand_safety`). Rule-file shape as 2.2; severity BLOCKING or WARNING chosen by the tenant, but a tenant rule can never override a platform rule. **3C**; Tier 1. The tenant's own legal responsibility for its brand rules is a contract term (⚖, MSA in §1B.8).

---

## 8. Copyright for the knowledge library (YTG-R9; IN-08, §1B.2a)

MVP: **3A** (Agents 04, 05 and the gate apply it). Enterprise: Tier 0; applies to client libraries at Tier 1 too.

- **Fact.** Indian copyright protects expression, not ideas. Fair dealing is narrow: s.52(1)(a) private use/research, criticism or review, reporting current events; s.52(1)(i) reproduction by a teacher or pupil in the course of instruction; s.52(1)(h) short passages in instructional collections. There is no general "education" head for public online video (IN-08). IN-08 is SECONDARY-only (statute read through a mirror). ⚖ Counsel to read the Act and current case law.
- **Rules.**
  1. Videos teach concepts in the producer's **own words**, with original examples and charts.
  2. No reading out, on-screen display, or close paraphrase of source passages.
  3. No scanned pages, figures, diagrams, tables, or covers; no reproduction of a book's chapter structure or sequence of ideas.
  4. A short attributed quotation only when essential and approved by the human reviewer (`COPYRIGHT_DOUBT` approval kind).
  5. Sources are credited as further reading in the description.
  6. Library text and extracts are never committed to git, never appear in public documents, logs, prompts examples or eval fixtures in this repo. They live in private, channel-isolated storage (ADR-013).
  7. Concepts with no source in the library or a verified external reference are flagged, not invented (§1B.2a).
- **Tests.**
  - *Deterministic, near-copy:* for each script sentence, compare against the cited source chunks with an n-gram overlap and a longest-common-substring check; a hit above the threshold is BLOCKED. Thresholds: **REQUIRES REVIEW (Phase 1): set on measured data with the owner's real source samples; no number is invented here.**
  - *LLM judge, close paraphrase:* a judge sees the sentence and its cited chunk(s) and answers "same structure, same examples, same sequence, only synonyms changed?" A yes is BLOCKED; an uncertain answer is `NEEDS_HUMAN_REVIEW`. The judge runs inside the private worker; the chunk text is never written to the verdict (only the chunk ID and rationale).
  - *Structure check:* the sequence of sub-topics is compared to the cited chapter's table of contents; identical order of five or more consecutive sub-topics (threshold REQUIRES REVIEW) is WARNING for human review.
  - *Visual check:* the asset manifest contains no asset with `source_type` of a scanned book page or screenshot of a source; any such asset is BLOCKED.
- **Evidence.** Chunk IDs, scores, rationale (not text).
- ⚖ Close-paraphrase boundary; whether the owner's own course text and the owner's own books are treated differently (the owner owns his own expression); third-party books are never exempt.

---

## 9. IT Rules: synthetic information declaration and labelling (YTG-R10; IN-06)

MVP: decision in **3A**; machine-readable label, provenance embedding and API field in **3C**. Enterprise: Tier 0.

- **Fact.** The IT (Intermediary Guidelines) Amendment Rules 2026 (G.S.R. 120(E), notified 10 Feb 2026, in force 20 Feb 2026) define synthetically generated information as content "artificially or algorithmically created, generated, modified or altered … in a manner that such information appears to be real". Intermediaries must label prominently and embed provenance "to the extent technically feasible". Significant social media intermediaries must require users to **declare** (IN-06). The corrigendum G.S.R. 148(E) was **not read**; read it before build. ⚖
- **Mapping.** YouTube is treated as the intermediary; the user-side duty is the **declaration**, which maps to the same decision as YTG-R3 (YT-06/07) and sets `containsSyntheticMedia` (3C). The decision is made once per video by Agent 16 and used for both purposes.
- **Rules.**
  1. The disclosure decision (section 3.3) is recorded for every video with `rationale`; it is never left empty.
  2. When `REQUIRED`: the platform declares through the YouTube field on upload (3C); and for files delivered to a client (3A and managed-service delivery) the QC report states in plain words that the video contains synthetic realistic content and must be declared when published elsewhere.
  3. Where technically feasible the render carries provenance metadata (content credentials, C2PA-style) — design in an ADR; **REQUIRES REVIEW (Phase 1): whether the chosen encoder/container preserves it and which standard**. The README of the delivery bundle lists the metadata present.
  4. Where an on-video visible label is needed (ASCI ads, doc 25, e.g. "Audio/Video created using AI", IN-04), that is owned by the advertising pack, not this one.
  5. Images of real persons, voices of real persons other than the owner, and fabricated news-like scenes are `BLOCKED` unless a consent and licence record exists (also in `rp.political_news`).
- ⚖ Which of the platform's duties and which of the producer's duties apply; label wording; whether the owner's use of AI B-roll is "appears to be real".

---

## 10. Human approval requirement (summary)

| Requirement | Where enforced | MVP |
|---|---|---|
| ≥ 1 human editorial contribution per video | YTG-R4 (`editorial_contributions`, written only by a human actor) | 3A (record), 3C (blocking at publication) |
| Human approval `FINAL_VIDEO` bound to the render hash | Publish guard trigger (04 §5.21) and YTG-R4 | 3A (record in the review), 3C (guard) |
| Sensitive claims, copyright doubts, knowledge release, policy changes need human approval kinds | `SENSITIVE_CLAIM`, `COPYRIGHT_DOUBT`, `KNOWLEDGE_RELEASE`, `POLICY_CHANGE` (GLOSSARY §6.15) | 3A for release and copyright doubt; others 3C |
| No auto-publication | `agent_16.publication_authorisation` + approval | 3C (no publication in 3A) |

An agent can never write an approval or an editorial contribution (actor-type trigger in 04). A client guest approving on a managed-service client's behalf is recorded with `managed_service` as in 04.

---

## 11. Why a tenant cannot disable platform packs (defence in depth)

1. **Schema.** `rule_packs.removable = false` for every `PLATFORM` pack (CHECK); `(scope = 'PLATFORM') = (org_id IS NULL)` (CHECK); `always_on = true` only for `rp.youtube_general`.
2. **Link trigger.** `compliance_profile_rule_packs`: a link with `is_mandatory = true` cannot be deleted or set to false by `amw_app`; creating a profile auto-inserts `rp.youtube_general`; the system sets `is_mandatory` for the platform packs required by the channel category (04 §5.2).
3. **Row-level security.** `rule_packs` is a SHARED-CATALOGUE table: tenants read platform rows and their own; no tenant role can write a PLATFORM row. Changes to platform packs are made only by versioned migration or by the Platform Owner role with a `POLICY_CHANGE` approval, with the audit log recording it.
4. **Production types.** `org_production_types.overrides` may only add to `rule_packs` ("add only", 24 §2, 04): any override that removes a pack is rejected at validation.
5. **Job validation.** State transition J02 checks "compliance profile attached" before a job starts; a profile missing a mandatory pack fails validation (03 §state machine).
6. **Gate behaviour.** The gate computes the set of packs from the channel category itself (not only from the profile), so a profile row missing by error cannot lower protection; a mismatch raises an alert and the gate evaluates the union.
7. **Thresholds.** Config keys for platform rules (e.g. the price-data lag) have a floor in the pack file; tenant override can only tighten it.
8. **Tests.** Required tests (27 test standards): attempt to delete the mandatory link as tenant admin → rejected; attempt to update a platform pack as tenant → rejected by RLS; attempt to attach a production-type override removing a pack → validation fail.
9. **Human override** is the only exception path: a recorded `is_final` human verdict with rationale, an `approval_kind` of `POLICY_CHANGE` or `SENSITIVE_CLAIM`, visible to the audit log, and never able to override FIN-R13 or R9 for a finance channel without lawyer sign-off (policy proposal, REQUIRES REVIEW ⚖).

MVP: schema, triggers and tests are **3A for the core tables used by the gate**; tenant-level enforcement tests are **3C** (Tier 0 single tenant has no tenant admin to attack the rule, but the constraints are built in from day one, per 04).

---

## 12. Change control for rules

- Rule text, circulars and orders change. Each pack file lists `legal_basis_ids` (RESEARCH_LOG IDs); before every release and every quarter the owner's process re-verifies each against the official source. **REQUIRES REVIEW (Phase 1): who performs the check and how often is set with the owner.**
- A change to a pack is a new `version`. The effective date is set explicitly and `status` moves `DRAFT → ACTIVE`; the old version `RETIRED`. A `POLICY_CHANGE` approval is recorded.
- A new law or order arriving mid-run applies at the next gate evaluation; videos already `APPROVED` but unpublished are re-evaluated before publication (FIN-R9 and others at `agent_16.publication_authorisation`).
- Rules are never relaxed because the pipeline repeatedly blocks content; the fix is in the script prompts. Rule changes follow the change-request process (directive rule 11).
- Method rules (anything about the owner's own trading method) are never written here; the finance pack only restricts how method content may appear (FIN-R12).

---

## 13. MVP scope and enterprise tier summary

| Item | 3A | 3B | 3C | Tier |
|---|---|---|---|---|
| `rp.youtube_general` rules on files (YTG-R1(b,c), R2, R3 decision, R4 record, R5, R6, R9, R10 decision) | yes | yes (scored) | — | 0 |
| Cross-video uniqueness (YTG-R1 a) | no | no | yes | 0 |
| Publication defaults, `containsSyntheticMedia`, publish-time re-check (YTG-R8, R3 field) | no | no | yes | 0 |
| `rp.finance_sebi_in` content rules R1, R2, R3, R6, R7, R9, R10, R11, R12, R13 | yes | yes | — | 0 |
| FIN-R4, R5, R8 (profile and publication level) | profile data checked in the gate | — | full | 0 |
| Stub packs health / kids / political_news | no | no | yes (as the first client needs them) | 1–2 |
| Tenant brand-safety pack | no | no | yes | 1 |
| Platform-pack tamper-proofing (constraints and triggers) | core | — | tenant tests | 0 (built), 1 (proved by tests) |

The three golden samples (3B) are all evaluated through the pack; the owner's scoring includes a check that no rule was waived.

---

## 14. Items for the owner's lawyer ⚖ (collected)
1. Exact disclaimer wording, languages, placement and duration; whether to state registration status (FIN-R10).
2. Whether a named index is a "specified security" (IN-03) and whether anonymised real or synthetic data is acceptable (S5).
3. Calendar vs trading days for the 30-day lag; treatment of non-price data (FIN-R9; IN-02).
4. Owner registration status and consequences for FIN-R8 and IN-05; the paid-promotion boundary for the owner's own course and ATP.
5. Backtest-methodology videos: whether showing any hypothetical result is a "performance claim" (FIN-R6).
6. Close-paraphrase boundary and fair dealing for library material (IN-08; read the Act and case law, not the mirror).
7. Definition of "realistic" synthetic content, the YouTube declaration, the IT Rules SGI obligations and the corrigendum (IN-06).
8. Whether the "education only" exemption (IN-01) is preserved by the course funnel and by any advertising.
9. Vendor licences for monetized online use (YTG-R6).
10. Made-for-kids and children's data obligations (YTG-R7; IN-07).
11. Client-facing promises and liability when a client's channel uses these packs (MSA, §1B.8).

## 15. Open items (REQUIRES REVIEW, Phase 1)
- Official text for the YouTube reused-content policy and made-for-kids API field (add RESEARCH_LOG entries).
- Uniqueness, near-copy and near-duplicate thresholds (set from golden samples and measured data).
- Regulated-entity domain list: source and upkeep.
- Rule-file storage location and the hash procedure in the build (ADR if needed).
- Rule ID prefixes for packs other than finance; presenter-kind field (contract_requests).
- Provenance metadata standard and encoder support (ADR).
