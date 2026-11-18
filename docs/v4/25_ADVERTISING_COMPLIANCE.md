# 25 — Advertising Compliance (rule packs `rp.advertising_asci_in` and `rp.ad_sector_<sector>`)

| Field | Value |
|---|---|
| Status (documentation) | Draft - documentation. Software status: Planned |
| Owner agent / service | Agent 16 (Compliance & QA) evaluates the packs; Agent 17 (Ad brief, concepts, script/storyboard) supplies the claim list and the label proposal; Agent 06 extracts and verifies claims; Agent 13 delivers files. Rule content is owned by this document; rule-pack mechanics by 13_COMPLIANCE_YOUTUBE_POLICY.md |
| Depends on | GLOSSARY_AND_IDS.md (§6.15, 6.27–6.29, 6.37–6.43, rule-ID convention), 03_COMMUNICATION_STANDARD.md (validation results, §11 verdict routing), 04_DATABASE_ARCHITECTURE.md (rule_packs, compliance_verdicts, claims, assets, voices/voice_consents, approvals, brand_kits), 07_FAILURE_MANAGEMENT.md (§9 revision-loop cap), 24_PRODUCTION_TYPES.md (§3.2 task types, §7.3 `AD_SPOT`, §5 QC profiles), 27_ENGINEERING_STANDARDS.md, 13_COMPLIANCE_YOUTUBE_POLICY.md, 18_PRODUCTION_QUALITY_STANDARD.md, 08_SECURITY.md, 09_COST_AND_BUDGET.md |
| Facts cited from | RESEARCH_LOG.md: IN-01, IN-04, IN-05, IN-06, YT-06, YT-07, YT-09. One further source read on 2026-11-18 and not yet in the log: the ASCI Code (official page, Chapter I), see section 1.3 |
| Directive sections | §1D (all four points), §1C.7 (rule packs, tenants add rules and never remove platform gates), §1A.7 (compliance failure rejects), §0 rules 3, 4, 8 |
| Owner decisions | D1, D2 |
| MVP scope | **Whole document: 3C, enterprise Tier 1 (first ad client) and above.** Nothing in 3A or 3B produces an ad (D1: 3A is the owner-topic production line; `AD_SPOT` is a Tier 1+ production type, 24 §7). Section 11 lists the only 3A/3B touch points. |

**Not legal advice.** This document turns ASCI and IT Rules text into checks a machine can run. Every item marked ⚖ must be read by a lawyer before the first ad client. Where a fact is missing the text says "REQUIRES REVIEW (Phase 1): <what is needed>". The repository is public: nothing here describes any private method, course content or server detail.

---

## 1. Purpose, scope and legal basis

### 1.1 What this document covers
1. The advertising workflow end to end (section 2) and who does what.
2. Claim substantiation (section 3).
3. The two rule-pack families and their records (sections 4 and 5).
4. The disclosure-label decision (section 6).
5. Real-person, likeness, voice and brand releases (section 7).
6. Virtual presenters (section 8).
7. Ad-specific quality, delivery and usage-rights record (sections 9 and 10).
8. The blocking checks Agent 16 runs (section 4.3) and what is built when (section 11).

### 1.2 Who carries which responsibility
The client contract places claim truth and approval with the advertiser (directive §1D.3). The platform nevertheless refuses clearly misleading or prohibited ads: its gate can return `BLOCKED` even when the client has approved. The ASCI Code itself puts responsibility on "all who commission, create, place or publish any advertisement" (official ASCI Code page, section 1.3), which includes an agency or a producer such as this platform. ⚖ The contract wording and any indemnity are for the lawyer (see 08/21; **REQUIRES REVIEW (Phase 1): client contract terms on claim truth and indemnity**).

### 1.3 Facts used (nothing else is asserted)
| ID | Fact used here | Status in the log |
|---|---|---|
| IN-04 | ASCI "Guidelines for Responsible Labelling of Synthetically Generated Content in Advertising", signed 17 Sep 2026; in force "on the expiration of 3 months from the date of their publication" (about end Dec 2026 by computation; **not in force on 2026-11-18**). Prohibited even with a label: fabricated endorsements/testimonials, misleading exaggeration, non-existent locations depicted as real, unauthorised copyrighted work, deepfakes or a person's likeness without consent. Mandatory label where synthetic content is material to persuasion (examples include synthetically generated influencers and ambassadors, replicated real-person likeness or voice even with consent, fabricated events, demonstrating a product that does not exist, product-relevant sound effects). No label for minor enhancements, decorative background/ambient elements, obvious fantasy, text/administrative uses, accessibility. Example labels: "Audio/Video created using AI", "Audio/Video enhanced using AI". The text was re-read from the official PDF on 2026-11-18 and matches the log entry. | VERIFIED (effective date computed, not stated) |
| IN-05 | ASCI influencer guidelines (2021 + Addendum I + Addendum II): disclosure labels (Ad, Sponsored, Collaboration, Affiliate …); video label duration (≤15 s: at least 3 s; 15 s to 2 min: one third of the video; ≥2 min: the whole promoted section); virtual influencers must disclose they are not human; BFSI stock/investment endorsers should be SEBI-registered and state the number. | VERIFIED for that PDF; later revisions NOT CONFIRMED |
| IN-06 | IT Rules amendment 2026 (in force 20 Feb 2026): "synthetically generated information" (appears to be real); intermediaries label and embed provenance metadata "to the extent technically feasible"; significant social media intermediaries require a user declaration. | VERIFIED (corrigendum G.S.R. 148(E) not read) |
| IN-01 | SEBI association rule: no association with regulated entities while giving unregistered advice or return claims; relevant to the finance sector pack. | VERIFIED |
| YT-06 / YT-07 | `containsSyntheticMedia`; disclosure policy for realistic altered/synthetic content. | VERIFIED |
| ASCI Code, Chapter I (not yet in log) | Read on 2026-11-18 at https://www.ascionline.in/the-asci-code/ : advertisements must be truthful; "All descriptions, claims and comparisons, which relate to matters of objectively ascertainable fact, should be capable of substantiation"; advertisers and agencies produce substantiation when ASCI asks; where a claim is stated to rest on independent research "its source and date should be indicated in the advertisement"; no reference to a person, firm or institution without permission where it confers an unjustified advantage or brings it into ridicule; no distortion of facts or misleading "by implications or omissions"; no claim "so exaggerated as to lead to grave or widespread disappointment". The Code's definition of an advertisement is a paid-for communication to the public meant to promote sale or use of goods and services, and also covers communication "paid for, or owned or authorised by the advertiser". | OFFICIAL SOURCE READ, **log entry pending** (see contract_requests note at the end: a RESEARCH_LOG row is needed; until then cite as "ASCI Code, official page, 2026-11-18") |

### 1.4 Corrections to secondary claims (from IN-04)
Two circulating claims are **not** in the official text and are not used: "effective 1 Jan 2027" and "virtual influencers are prohibited". The official text requires a label for synthetically generated influencers and ambassadors (a label, not a ban) and gives a three-month period from publication.

### 1.5 Effective-date handling
IN-04 is not in force on 2026-11-18 and the exact date is computed. Design: the pack row carries `effective_from` (04 `rule_packs.effective_from`). Release rule: the pack is seeded `ACTIVE` with `effective_from` set by the owner after the lawyer confirms the date; the gate applies the label rules as written **from first use**, because applying them early is never wrong, and a missing label after the date would be. ⚖ **REQUIRES REVIEW (Phase 1): confirm the exact in-force date of IN-04 with ASCI before the first ad client.** Re-read IN-04, IN-05 and IN-06 (and the IN-06 corrigendum) before building the pack files.

---

## 2. Advertising workflow (directive §1D.1)

Production type `AD_SPOT` (24 §7.3) is the reference. `ECOMMERCE_PRODUCT` (24 §7.6) and any promotional output of a client channel type route through the same packs (section 4.4). MVP: 3C, Tier 1+.

| Step | Stage / task type (24 §3.2) | Actor | Approval / gate | Output used later |
|---|---|---|---|---|
| 1 Brief | `agent_17.brief_intake` | Agent 17, client | clarified brief; product category (drives sector packs); claim list inputs; releases; brand kit (24 §7.3 `required_inputs`) | brief, category |
| 2 Concept and variants | `agent_17.concept_variants` | Agent 17 | approval `CONCEPT` (`client_two_step`) | 3-5 variants (§1D.4) |
| 3 Script and storyboard | `agent_17.ad_script_storyboard` | Agent 17 | claim list handed to 06/16 | script, storyboard, **label proposal** (section 6) |
| 4 Claims | `agent_06.claim_extraction`, `agent_06.claim_verification` (both blocking) | Agent 06 | every claim needs substantiation (section 3) | `claims` rows with `substantiation_ref` |
| 5 Script approval | approvals `SCRIPT` and `STORYBOARD` (`client_two_step`) | client | decision bound to `subject_sha256` | locked script |
| 6 Production | `agent_07.voice_synthesis`, `agent_07.audio_master`, `agent_09.shot_plan`, `agent_08.asset_sourcing`, `agent_10.render`, `agent_10.subtitles`, `agent_10.technical_qc` | agents 07-10 | `qc.ad_spot` (section 9) | masters per aspect/duration |
| 7 Compliance gate | `agent_16.compliance_gate` | Agent 16 | blocking; evaluates `rp.advertising_asci_in` + sector packs (+ `rp.youtube_general` when published to YouTube) | verdict rows, disclosure decision |
| 8 Quality score | `agent_16.quality_score` | Agent 16 | publish/deliver at score ≥ 85; any compliance failure rejects (18, §1A.7) | 100-point report |
| 9 Client final approval | approval `FINAL_VIDEO` (`client_two_step`), logged before delivery | client | **blocking**: no delivery without it (rule ADV-R14) | approval record |
| 10 Authorisation and delivery | `agent_16.publication_authorisation` (final verdict, Q5), `agent_13.file_delivery` | Agent 16, 13 | re-checks date-dependent items at delivery time | masters, platform exports, captions, label decision record |
| 11 Usage-rights record | approval `USAGE_RIGHTS` (mandatory) | client + platform | section 10 | usage-rights record |

Revision loops follow 07 §9 (`limits.max_revision_loops`, default 3 per gate per job); after that the job ends `COMPLETED` with `BLOCKED_COMPLIANCE`. A `BLOCKED` verdict is a successful task, not a failure (03 §11).

---

## 3. Claim substantiation (directive §1D.3)

### 3.1 Principle
Every claim about a matter of objectively ascertainable fact needs a document from the client that supports it (ASCI Code Chapter I, section 1.3). The platform does **not** judge scientific or commercial truth. It checks that (a) a document exists, (b) it is attached to the claim, (c) it appears to cover the exact wording, and (d) the ad's wording and visuals do not go beyond it. Truth stays with the advertiser (section 1.2).

### 3.2 Which claims need a document
Claims are typed by Agent 06 with the existing enum `claim_type` (GLOSSARY §6.39). For `AD_SPOT` the following types require `claims.substantiation_ref` (04 claims table) and status `SUBSTANTIATED` (GLOSSARY §6.40):

| `claim_type` | Needs a client document | Notes |
|---|---|---|
| `PRODUCT_CLAIM` | yes | features, ingredients, performance, results, quantities, "first/best/only" |
| `COMPARATIVE` | yes | the compared product or brand must be named only with permission or on a substantiated factual basis (rule ADV-R6) |
| `STATISTICAL` | yes | source and date shown in the ad where the claim rests on independent research (rule ADV-R13) |
| `PERFORMANCE_CLAIM` | yes | results the product delivers; before/after visuals included (rule ADV-R3) |
| `TESTIMONIAL` | yes | a real, consenting person who actually used the product; see ADV-R2 and section 7 |
| `FACTUAL`, `HISTORICAL_MARKET` | yes when about the product, the advertiser or a competitor | |
| `OPINION`, `DEFINITION`, `HYPOTHETICAL_EXAMPLE` | no, but opinion must not be phrased as fact | |
| `RECOMMENDATION`, `FORWARD_VIEW`, `PRICE_LEVEL` | sector-dependent | in the finance sector these are blocked outright by the finance pack |

### 3.3 Status flow (existing enums only)
`EXTRACTED` → (`NEEDS_SUBSTANTIATION` when no document) → `SUBSTANTIATED` when the client document is attached and passes the checks below; `CONTRADICTED` or `UNVERIFIABLE` when the document does not support the wording; `REMOVED` when the claim is deleted from the script. Agent 06 proposes (`claims.proposed_verdict`); Agent 16 is the final authority (`claims.final_verdict`, Q5).

### 3.4 Checks on the document (rule ADV-R1)
| Check | Kind | Test |
|---|---|---|
| Present and attached | DETERMINISTIC | `substantiation_ref` not null and the object exists in the client's storage scope |
| Readable and dated | DETERMINISTIC | document type allowed, text extractable, a date and an issuer present; undated or unreadable gives `NEEDS_HUMAN_REVIEW` |
| Covers the wording | LLM_JUDGE (second independent judge on any `BLOCKING` fail) then HUMAN on disagreement | the document states the same thing as the claim: same product, same metric, same magnitude, same conditions; a stronger ad claim than the document is `CONTRADICTED` |
| Not stale | DETERMINISTIC | document date within the pack's recency limit; **REQUIRES REVIEW (Phase 1): recency limit per sector** (no official figure in the log) |
| Independent research cited in the ad | DETERMINISTIC | where the ad says it rests on independent research, source and date appear on screen (ADV-R13) |

Evidence stored: `claims.substantiation_ref`, `compliance_verdicts.evidence_ref` (excerpt location, not the whole document), `check_id` of the form `adv.r1.substantiation` (pattern `^[a-z0-9_.-]{3,96}$`).

### 3.5 What the platform refuses regardless of documents
The Code bars statements "which directly, or by implication or by omission or by ambiguity or by exaggeration, are likely to mislead" and exaggerated claims leading to "grave or widespread disappointment" (section 1.3). So a client document does not rescue: a visual that implies a result the document does not show (IN-04 1B example), a claim that is true only under conditions hidden from the viewer, or "free" offers with undisclosed cost (the Code's own example). These are rules ADV-R3 and ADV-R12.

---

## 4. Rule pack `rp.advertising_asci_in` (platform scope, every ad production type)

MVP: 3C. Enterprise: Tier 1+. Key and scope: GLOSSARY §6.37 (`PLATFORM`, "every ad production type", directive §1D).

### 4.1 Rule-pack record (04 §5.2 `rule_packs`, not redefined)
| Column | Value |
|---|---|
| `org_id` | NULL (platform) |
| `key` / `version` | `rp.advertising_asci_in` / 1 |
| `scope` | `PLATFORM` |
| `category` | `advertising` (04 category list) |
| `always_on` | false (04: true only for `rp.youtube_general`); it is attached by the production type's `rule_packs` field (24 §2), so it is mandatory for every ad type without being "always on" |
| `removable` | false (CHECK for PLATFORM) |
| `rules_ref` / `rules_sha256` | storage URI of the rule file (section 4.2) / SHA-256 of its canonical bytes (UTF-8, LF, keys sorted), exactly as 13 §2.1 |
| `status` | `DRAFT` until the lawyer has read it, then `ACTIVE`; a version is immutable once `ACTIVE`; a change is a new version (13 §2.1) |
| `effective_from` | set by the owner after IN-04 date confirmation (section 1.5) |

Linking: `compliance_profile_rule_packs.is_mandatory = true` is set by the system for the advertising pack when the project is of an ad production type; a tenant can add rules (`rp.tenant_brand_safety`) but cannot remove a platform pack (§1C.7; 04 trigger).

### 4.2 Rule file format (the object `rules_ref` points to)
Same shape as 13 §2.2 (that document owns the layout; this document adds no table, enum or column). Example entry:

```yaml
pack:
  key: rp.advertising_asci_in            # GLOSSARY §6.37
  version: 1
  legal_basis_ids: [IN-04, IN-05, IN-06, ASCI-CODE-CH1 (pending log id)]
  re_verify_before_release: true
rules:
  - rule_id: ADV-R5                      # prefix "ADV" (pending CCR)
    title: "No real person's likeness or voice, deepfake or unauthorised copyrighted work without consent"
    severity: BLOCKING                   # rule_severity
    applies_to: [script, storyboard, render, audio]
    evaluated_at: [agent_16.compliance_gate]
    check_kind: DETERMINISTIC            # pre-filter; LLM_JUDGE + HUMAN for lookalike/imitation
    config_keys: []
    test: "section 7.2"
    evidence: [asset_ids, release_refs, voice_consent_ids]
    escalation: BLOCKED                  # compliance_verdict
    lawyer_review: true
```

### 4.3 Rules and blocking checks (the §1D.3 list, as Agent 16 runs them)
Rule IDs follow the convention `<PACK>-R<n>` (GLOSSARY §1); the prefix `ADV` is **proposed** (pending CCR, see contract_requests). Severity: all BLOCKING unless stated. "Kind": DETERMINISTIC (D), LLM_JUDGE (J), HUMAN (H).

| Rule ID | Rule | Kind | Source | MVP |
|---|---|---|---|---|
| `ADV-R1` | Every factual, comparative, statistical or performance claim has a client substantiation document attached and checked (section 3.4) | D + J (+ H) | §1D.3, ASCI Code Ch. I | 3C |
| `ADV-R2` | No fabricated, altered or attributed endorsement or testimonial: the person really used and endorsed the product, and consented | D + H | IN-04 1A | 3C |
| `ADV-R3` | No exaggeration by claim or visual that gives a misleading impression of results or features (includes AI before/after imagery); routine enhancement is not exaggeration | J + H | IN-04 1B, 3A; ASCI Code Ch. I | 3C |
| `ADV-R4` | No non-existent location, facility or event presented as real | J + H | IN-04 1C, 2C | 3C |
| `ADV-R5` | No real person, celebrity, creator or lookalike, no voice imitation, no deepfake, no unauthorised copyrighted work, without a signed release or licence (section 7) | D + J + H | IN-04 1D; §1D.3 | 3C |
| `ADV-R6` | No competitor or third-party brand, firm or institution shown or named without permission or a substantiated factual basis for the comparison | D + J | ASCI Code Ch. I; §1D.3 | 3C |
| `ADV-R7` | Disclosure-label decision recorded by the risk test (section 6), with rationale | D | IN-04, IN-06, YT-06/07; §1D.3 | 3C |
| `ADV-R8` | Where the decision is `REQUIRED`, the label is present, readable, on screen for the required time and matches the recorded text | D (render analysis) + H sample | IN-04 §4; section 6.4 | 3C |
| `ADV-R9` | Any virtual or AI presenter, ambassador or influencer is identifiable as non-human, in the picture and in the label | D + H | IN-04 2A, IN-05 | 3C |
| `ADV-R10` | Paid endorsement by a creator or influencer carries the disclosure label with the IN-05 duration rule; BFSI stock/investment endorsers must be SEBI-registered with number stated (**blocks** an ad that uses an unregistered endorser for such a product) | D + H | IN-05 | 3C |
| `ADV-R11` | Legal super / disclaimer is present where a sector pack or claim requires it, legible and on screen long enough (values: section 9) | D | §1D.4; IN-04 §4 ("disclaimer guidelines") | 3C |
| `ADV-R12` | No omission or implication that misleads; conditions that change the meaning of a claim (price, "free", eligibility, results not typical) are visible with the claim | J + H | ASCI Code Ch. I | 3C |
| `ADV-R13` | A claim stated to rest on independent research shows its source and date in the ad | D | ASCI Code Ch. I | 3C |
| `ADV-R14` | Client final approval (`FINAL_VIDEO`, `client_two_step`) is logged against the exact render hash before delivery; the sector and ad-pack verdicts are bound to the same hash | D | §1D.1, §1D.3 | 3C |
| `ADV-R15` | Ad-specific technical items (section 9) pass; a failure in `qc.ad_spot` is blocking | D | §1D.4 | 3C |
| `ADV-R16` | WARNING: label proposed by Agent 17 differs from the gate's decision, or the label text is not localised for the ad language | D | section 6 | 3C |

Behaviour: a BLOCKING failure gives `check_verdict = FAIL` and `compliance_verdict = BLOCKED`; a rule that cannot be evaluated gives `NEEDS_HUMAN_REVIEW`, never `SKIPPED` (13 §2.3). A single LLM_JUDGE `ALLOWED` is never the only evidence for a BLOCKING rule on a flagged item: second independent judge or human (13 §1.4). Every verdict writes a `validation_results` item and a `compliance_verdicts` row with `rule_pack_id`, `rule_pack_version`, `rule_id`, `disclosure_decision` (for ADV-R7/R8), `rationale`, `evidence_ref`, `decided_by`, `is_final` (13 §1.3).

### 4.4 When the pack applies (routing test for promotional content)
24 §7 (`EXPLAINER_CORPORATE_TRAINING`) leaves the routing of promotional content to this document. Decision rule (⚖):
1. The pack is mandatory for `AD_SPOT` and `ECOMMERCE_PRODUCT`.
2. For any other production type, the pack is added when **either** (a) the client marks the job as promotion of its goods or services (a required boolean on the job input: **pending CCR**), **or** (b) Agent 06 extracts any `PROMOTION` claim (GLOSSARY §6.39) whose subject is a product, service or offer of the client. The Code's definition covers communication "paid for, or owned or authorised by the advertiser", so brand-owned channel content that promotes a product is in scope.
3. Ambiguous cases return `NEEDS_HUMAN_REVIEW`, never "not advertising".
4. The owner's own promotion of his course or the trading app on the owner's channel is not a third-party ad. It is governed by 13 (FIN rules, including the education-only exemption of IN-01 and IN-05's note) and is labelled transparently there; it does not load this pack in 3A/3B. ⚖ **REQUIRES REVIEW (Phase 1): lawyer to confirm that self-promotion is outside the ASCI definition for these cases.**

---

## 5. Sector rule packs `rp.ad_sector_<sector>`

Keys fixed by GLOSSARY §6.37: `health_wellness`, `food`, `financial_products`, `education_outcomes`, `real_estate`, `alcohol_tobacco_surrogate`. Scope `PLATFORM`; `category = ad_sector` (04); `always_on = false`; `removable = false`. MVP: 3C, Tier 1+ **each pack is built only when the first client in that sector exists** (§1C.15). Loaded by the product category given in the brief (`AD_SPOT.required_inputs`).

### 5.1 Status of sector content
The research log holds **no sector rule text** (no entry on health/food/education/real-estate/alcohol rules, drug and remedy advertising law, food-safety or real-estate regulator rules, or financial-product advertising). Nothing is invented here. Each pack is a stub that inherits `rp.advertising_asci_in` and states what must be read. Before a pack goes `ACTIVE`, a research-log row with official source and date is required for every rule.

| Pack | What the pack must cover (scope of research) | Known from the log | MVP / Tier | Status |
|---|---|---|---|---|
| `rp.ad_sector_health_wellness` | health, medical, supplement and wellness claims; cure/treatment claims; before/after results; endorsements by professionals; AI persona on health is not monetizable on YouTube (YT-09, 13 `YTG-R2`) | YT-09; IN-04 1B (before/after example) | 3C, Tier 1 (first health/wellness client) | DRAFT. **REQUIRES REVIEW (Phase 1): applicable ASCI chapters and statutory rules on health and wellness advertising** |
| `rp.ad_sector_food` | nutrition, health and "natural" claims, children, taste/pack depiction accuracy | none | 3C, Tier 1 | DRAFT. **REQUIRES REVIEW (Phase 1): applicable ASCI chapters and food-regulator advertising rules** |
| `rp.ad_sector_financial_products` | securities and investment products, loans, insurance, funds: return/performance claims, risk disclosures, endorser registration | IN-05 (BFSI endorser must be SEBI-registered and state the number); IN-01; the owner's own finance rules `FIN-R1..R13` are for the owner's channel, not a template for client ads | 3C, Tier 1 | DRAFT. **REQUIRES REVIEW (Phase 1): per-regulator advertising rules (SEBI, RBI, IRDAI) and mandatory risk wording** ⚖ |
| `rp.ad_sector_education_outcomes` | placement, rank, pass-rate, salary and income claims; "guaranteed" outcomes; faculty and topper endorsements | none | 3C, Tier 1 | DRAFT. **REQUIRES REVIEW (Phase 1): applicable ASCI chapter and consumer-protection rules on education claims** |
| `rp.ad_sector_real_estate` | RERA-registered claims, approvals, amenities depicted but not built (IN-04 2D example: a 3D model of an unbuilt housing complex needs a label), location/distance claims | IN-04 2D, 1C | 3C, Tier 1 | DRAFT. **REQUIRES REVIEW (Phase 1): real-estate regulator advertising requirements** |
| `rp.ad_sector_alcohol_tobacco_surrogate` | surrogate advertising of alcohol/tobacco brands | none | 3C; **default: platform declines the order until the owner decides** (a business decision, not a research fact) | DRAFT. **REQUIRES REVIEW (Phase 1): statute and ASCI rules; owner decision on whether to serve this sector** |

### 5.2 Record format
Each sector pack is one `rule_packs` row exactly as section 4.1 except `key = rp.ad_sector_<sector>`, `category = ad_sector`, and rule IDs with a per-sector prefix (proposed, pending CCR: `ADH` health_wellness, `ADF` food, `ADN` financial_products, `ADE` education_outcomes, `ADR` real_estate, `ADA` alcohol_tobacco_surrogate; rule IDs `ADH-R1` …). The rule file has the same YAML shape (section 4.2). Tenants may add `rp.tenant_brand_safety` rules; they cannot remove a sector pack that the brief's category requires.

### 5.3 Selection
Agent 17 records the product category in the brief; Agent 16 maps it to sector pack(s) deterministically. A product that fits two sectors (for example a nutrition supplement sold with an income claim) loads both. If the category is missing or unknown the job stays at validation (J02 requires the required inputs, 03 §11) and asks the client; the gate never defaults to "no sector".

---

## 6. Disclosure-label decision (directive §1D.2-3; IN-04, IN-06, YT-06/07)

### 6.1 Two different labels, one decision record
| Label | Meaning | Who sets it | Source |
|---|---|---|---|
| On-screen / in-audio AI label | tells the consumer that the ad contains synthetic content | creative, checked by Agent 16 (ADV-R8) | IN-04 §2 and §4 |
| Platform declaration `containsSyntheticMedia` | tells YouTube the video has realistic altered or synthetic content | Agent 13, copied from the decision | IN-06 (user declaration), YT-06, YT-07 |
| Paid-endorsement label (Ad, Sponsored, Collaboration …) | tells the consumer a creator is paid | creative, checked by ADV-R10 | IN-05 |

These are different obligations. An ad can need one, two or all three. The AI-label decision and the YouTube declaration use the single `disclosure_decision` enum (GLOSSARY §6.43) on the verdict row, as in 13 §3.3; Agent 13 copies it and never recomputes it.

### 6.2 The risk test (from IN-04 "assessment for labelling")
Agent 16 answers the three official questions per ad, using asset flags (`assets.is_realistic_synthetic`, `assets.depicts_real_person`, `voices.kind`) and the shot plan:
1. Is synthetic content central to the persuasive message or does it materially influence a purchase decision?
2. Does the way it is used mislead about the product's claims, performance or benefits if unlabelled?
3. Would the absence of a disclosure create a false impression of claims, benefits or performance?

Then the element table decides:

| Element in the ad | Label | Source |
|---|---|---|
| synthetic influencer, ambassador or presenter | REQUIRED | IN-04 2A |
| real person's likeness or voice replicated, even with consent | REQUIRED (and a release, section 7) | IN-04 2B |
| fabricated event, setting or situation that affects understanding of performance | REQUIRED | IN-04 2C |
| demonstration of a product or place that does not yet exist | REQUIRED | IN-04 2D |
| synthetic sound effects highly relevant to the product's core feature | REQUIRED | IN-04 2E |
| routine editing, colour correction, noise reduction, copy refinement, formatting | NOT_REQUIRED | IN-04 3A |
| decorative backgrounds, ambient music, jingles, unrelated sound effects | NOT_REQUIRED | IN-04 3B |
| obviously fantastical effects | NOT_REQUIRED | IN-04 3C |
| text and administrative uses (copy, audio description, documents in good faith) | NOT_REQUIRED | IN-04 3D |
| accessibility (subtitles, captions, translations, accurate audio description) | NOT_REQUIRED | IN-04 3E |
| a real person saying or doing something they did not; altered real events or places; realistic scenes that did not occur | REQUIRED for YouTube (declaration) | YT-07, IN-06 |
| cloning one's own voice (YouTube) | not required by YT-07 alone; **but an ad that replicates a real person's voice still follows IN-04 2B** | YT-07, IN-04 |
| anything prohibited in section 4.3 (ADV-R2..R5) | **label never cures it: BLOCKED** | IN-04 §1 |

Combination rule: the decision is the **stricter** of the ASCI result and the IT Rules/YouTube result for the destinations used. Missing flag, ambiguous realism or an element that fits no row: `NEEDS_HUMAN_REVIEW`, never `NOT_REQUIRED` (13 §3.3).

### 6.3 Why the IT Rules fit
IN-06 defines synthetically generated information as content artificially or algorithmically created or altered so that it appears real. YouTube is a significant social media intermediary, so the advertiser's duty at upload is the declaration (YT-06). The pipeline sets the declaration from the decision and keeps the record. The intermediary's own label and provenance metadata are the platform's duty; this system embeds provenance metadata in its masters where technically feasible (an ADR is needed: **pending CCR**; no ADR number is assigned for it today). ⚖ The corrigendum G.S.R. 148(E) of IN-06 has not been read.

### 6.4 Label execution (what the gate checks)
| Item | Value | Basis |
|---|---|---|
| Text | one of the official examples ("Audio/Video created using AI", "Audio/Video enhanced using AI") or an alternative that "accurately inform[s] the consumer"; localised to the ad language | IN-04 §4. Marathi/Hindi/other wording: **REQUIRES REVIEW (Phase 1): translator and lawyer sign-off** |
| Where applied | any ad that carries synthetic content classed REQUIRED; for audio-only elements a spoken or on-screen label is needed | IN-04 text says "Audio/Video"; spoken-label rule **REQUIRES REVIEW (Phase 1)** |
| Duration of an AI label | **not stated in IN-04**. Design default (platform choice, not a rule): the label is visible for at least as long as the REQUIRED content is on screen, and at the start of the spot. ⚖ | design choice |
| Duration of a paid-endorsement label | IN-05: ≤15 s video: at least 3 s; more than 15 s up to 2 min: one third of the video; ≥2 min: the whole promoted section. For the standard spot lengths (24 §4: 6, 15, 30, 60 s) this gives 3 s, 3 s, 10 s, 20 s as minimums. | IN-05 (derived arithmetic) ⚖ |
| Legibility, size, contrast, safe zone | **REQUIRES REVIEW (Phase 1): thresholds** (no official figure in the log); values go to `qc.ad_spot` (section 9) | |
| Disclaimers | follow "the ASCI Code on disclaimer guidelines where applicable" (IN-04 §4) | disclaimer-guideline text **REQUIRES REVIEW (Phase 1)** |

### 6.5 Decision record (stored, section 10)
Per ad: `disclosure_decision`, element table result (list of `asset_id` + element class), `rationale`, label text and language, label timing, platform declaration value, who decided (`decided_by`: Agent 16 or the human reviewer), `is_final`, `rule_pack_version`. It is stored as the `compliance_verdicts` row (04 §5.17) with the structured detail referenced by `evidence_ref`. A dedicated payload schema for the detail is **pending CCR** (see contract_requests).

---

## 7. Releases, likeness, voice and brands (§1D.3)

### 7.1 Records that already exist (04)
- `assets.depicts_real_person` and `assets.release_ref` (model/property release).
- `voices` with `kind` (`PROVIDER_STOCK`, `CONSENTED_CLONE`, `HUMAN_RECORDED`) and `voice_consents` (`state`, `scope_note`, `expires_at`, `withdrawn_at`; only `VERIFIED` voices may be rendered).
- `licences` and the licence ledger for stock and music.
- `approvals` kind `USAGE_RIGHTS`.

### 7.2 Check ADV-R5 (blocking)
| Step | Kind | Test |
|---|---|---|
| 1 Inventory | D | every asset with `depicts_real_person = true`, every voice with `kind = CONSENTED_CLONE`, every named person in script/storyboard/prompts |
| 2 Release exists | D | each has `release_ref` (assets) or a `VERIFIED` voice consent; not expired, not withdrawn |
| 3 Scope fits | H | the release covers this advertiser, medium (digital video/YouTube/other destinations), duration of use and the replication of face/voice by AI. Release content and minimum clauses: **REQUIRES REVIEW (Phase 1): lawyer-drafted release templates** ⚖ |
| 4 No unnamed imitation | J + H | no celebrity, creator or competitor lookalike or voice imitation in the script, shot plan, generation prompts or output. Image/video generation prompts must never name or describe a real identifiable person (rule for Agents 08/09 prompts; also 18 `D_AI_VIDEO` rule) |
| 5 Copyright | D | every shot and track has a licence ledger row (18/`qc.long_form` check); no unlicensed copyrighted work (IN-04 1D) |
| 6 Third-party brands and institutions | D + J | logos, names, packaging of non-client brands appear only with permission or as a substantiated comparison (ADV-R6) |

A real person with a release who is replicated by AI is **still labelled** (IN-04 2B). A deceased person, a minor, or a person in a sensitive profession: **REQUIRES REVIEW (Phase 1): lawyer position**; default `NEEDS_HUMAN_REVIEW`. Where personal data of models or voice owners is stored, 22_DATA_PROTECTION.md governs (IN-07 timelines).

### 7.3 Endorsements and testimonials (ADV-R2)
A testimonial must come from a real, identifiable consumer or professional who gave it and consented, recorded as a `claims` row of type `TESTIMONIAL` with a document attached (a recorded statement or signed testimonial). AI-written or AI-voiced "customer" quotes presented as real are blocked (IN-04 1A). A clearly fictional character in a dramatised ad is allowed only if the ad does not claim real use or real results; this is judged by ADV-R3/R12 and, when unclear, by a human.

---

## 8. Virtual and AI presenters

1. **Allowed for advertising**, with identification: ASCI requires a label for synthetically generated influencers and ambassadors (IN-04 2A) and the influencer guidelines require virtual influencers to disclose that they are not human (IN-05). They are **not banned** (section 1.4).
2. Check ADV-R9 (blocking): presenter kind is known (the field that records "neutral narration vs AI persona vs real person" is **pending CCR**, also asked by 13 `YTG-R2`); a persona requires (a) the label text/time of section 6.4 and (b) a visible or spoken statement that the presenter is not human (wording **REQUIRES REVIEW (Phase 1)**).
3. A virtual presenter may not be used to (a) fabricate a testimonial or endorsement (ADV-R2), (b) imitate a real person (ADV-R5), or (c) deliver claims about health or finance that the pack bars. On YouTube, a synthetic persona on health, legal, finance or politics is not monetizable (YT-09; 13 `YTG-R2`); an ad delivered to a client's channel is flagged to the client when this applies.
4. The owner's own trading channel never uses an AI persona (`FIN-R11`); this section does not change that.
5. 3C, Tier 1+.

---

## 9. Ad-specific quality (directive §1D.4; QC profile `qc.ad_spot`, 24 §5, 18)

`qc.ad_spot` = `qc.long_form` plus the checks below. Technical measurement is by Agent 10 (`agent_10.technical_qc`); the compliance reading of the same items is by Agent 16. Thresholds that the Wave A and B-1 documents mark **REQUIRES REVIEW (25)** are collected here; none has a figure in the research log, so each stays open and is not guessed.

| Check | Kind | Blocking | Value |
|---|---|---|---|
| Brand kit applied (logo, colours, fonts, lower thirds) | D | yes | brand kit version recorded against the render (`brand_kits.is_current`) |
| Product shown accurately; client's own footage/photos preferred; AI depiction of the product must not alter shape, colour, size or function | D (source tier) + J + H | yes (ties to ADV-R3) | visual hierarchy of 18: client material first; AI-made product visuals need client approval of the likeness |
| Logo and pack-shot rules | D | yes | clear space, minimum size, end-card duration: **REQUIRES REVIEW (25): values per client brand guideline; default = the client's own brand guide** |
| Legal super / disclaimer legibility | D | yes | minimum height as share of frame, contrast, minimum on-screen seconds: **REQUIRES REVIEW (25)** (the Code refers to disclaimer guidelines, not read) |
| Safe zones per platform | D | yes | per destination spec: **REQUIRES REVIEW (25): current YouTube, Meta, OTT specs, each verified from the platform's official page** |
| Exact duration per spot | D | yes | masters `ad_master_<ratio>_<seconds>`: 6, 15, 30, 60 s; 16:9, 9:16, 1:1, 4:5 (24 §4); tolerance **REQUIRES REVIEW (25)** |
| Audio | D | yes | −14 LUFS integrated, −1 dBTP, 48 kHz as `qc.long_form`, unless the destination spec differs |
| Variants for testing | D | warn | 3-5 variants per concept (§1D.4); each variant passes the gate separately |
| Captions | D | yes | SRT per language; accessibility captions need no AI label (IN-04 3E) |
| AI label present and legible | D | yes | ADV-R8 |
| Compliance failure | - | rejects regardless of score | 18 §1A.7 |

Cost: ad production is within the per-video and pilot budget guards of 09 (D1); variants multiply cost and are counted in the price model (21; **REQUIRES REVIEW (21)**).

---

## 10. Delivery, usage-rights and decision records

### 10.1 Delivery (§1D.1 final step)
Per order, deliverables (24 §7.3): masters and platform exports per ordered aspect/duration, captions, **disclosure label decision record**, **usage-rights record**, QC and compliance report. Delivery happens only after `FINAL_VIDEO` approval (ADV-R14) and `agent_16.publication_authorisation`. Upload to a client's YouTube channel, when ordered, follows 13 and sets `privacyStatus=private` explicitly (YT-04) and `containsSyntheticMedia` from the recorded decision (YT-06); that part is 3C and needs OAuth, which D1 excludes from 3A.

### 10.2 Usage-rights record (approval kind `USAGE_RIGHTS`)
Content the record must carry (documentation only; storage shape **pending CCR**, section 12): advertiser; ad and render hashes; every licensed element (stock, music, fonts) with its licence ledger id, territory, term and media scope as granted by the licence; every release (`release_ref`, voice consent id) with scope and expiry; the client's licence of its own material to the platform; the platform's grant to the client (usage scope, term, territory, media, edit/derivative rights; commercial terms **REQUIRES REVIEW (21)** ⚖); expiry dates that trigger a "pull the ad" notification (`notifications`, 04). A licence or release that expires before the end of the ad's term is a **warning at order time** and blocks delivery if the ordered term exceeds it.

### 10.3 Retention
Verdict rows, label decisions, substantiation documents, releases and approvals are retained under the tenant retention and offboarding rules of 22 and 04 (append-only audit, hash chain). Substantiation documents are the client's data: stored in the client's tenant scope only (rule 9); no cross-tenant sharing; export on offboarding.

---

## 11. Build scope (D1) and tier map

| Item | 3A | 3B | 3C | Tier |
|---|---|---|---|---|
| Rule-pack record format and loader (13 owns mechanics) | the loader is built for `rp.youtube_general` and `rp.finance_sebi_in`; ad packs reuse it unchanged | | seed `rp.advertising_asci_in` v1 and sector stubs | 0 (loader), 1+ (ad packs) |
| `rp.advertising_asci_in` rules ADV-R1..R16 | not built | not built | built and evaluated | 1+ |
| Sector packs | not built | not built | each when its first client exists | 1+ |
| Disclosure decision engine | **3A** (13 §3.3, for the owner's realistic AI B-roll); the ASCI element table and label execution (section 6.2, 6.4) are extensions | | extension built | 0 (decision), 1+ (ASCI extension) |
| Claim substantiation (`substantiation_ref`) | the column exists (04); no ad flow | | built with Agent 17 | 1+ |
| `AD_SPOT` / `ECOMMERCE_PRODUCT` production types | not enabled | | enabled for the first ad client | 1+ |
| Release and likeness checks | the voice-consent and asset-flag columns exist for the owner's own clone | | ADV-R5 built | 1+ |
| `qc.ad_spot` | not built | | built | 1+ |
| Client portal approvals (`client_two_step`) | none | | managed service at Tier 1; portal at Tier 2 | 1 / 2 |
| White-label agencies, API delivery of ads | | | | 2 / 3 |

**3A/3B touch points only:** (1) the owner's videos use the 13 disclosure decision for any realistic AI B-roll; no ASCI label applies because they are not advertisements; (2) the 3A QC report must not claim "advertising compliance" (not evaluated); (3) the owner's own course promotion inside videos is a 13 matter (section 4.4 point 4). Golden samples (3B) are three trading-education videos, not ads.

---

## 12. Open items (⚖ and REQUIRES REVIEW)

1. ⚖ Exact in-force date of the IN-04 guideline and whether ASCI issues a further revision before the first ad client (section 1.5).
2. ⚖ Lawyer read of the ASCI Code, IN-04, IN-05, IN-06 (and corrigendum G.S.R. 148(E)), client contract (truth, indemnity, approval) and release templates.
3. REQUIRES REVIEW (Phase 1): sector rule texts for every pack in section 5.1; recency limit of substantiation documents; label text in Marathi/Hindi/other; spoken-label rule; legibility, duration and safe-zone thresholds; later revisions of the ASCI influencer guidelines (IN-05 says later revisions NOT CONFIRMED).
4. REQUIRES REVIEW (Phase 1): positions on deceased persons, minors and sensitive professions in likeness use; AI-chat "Sponsored by [Brand]" recommendations (IN-04 2F) are outside this pipeline and not implemented.
5. Owner decision: whether to serve the alcohol/tobacco surrogate sector (default: decline).
6. Self-promotion of the owner's course/ATP and ASCI scope (section 4.4 point 4).

---

## 13. Maintenance
Re-verify IN-04, IN-05 and IN-06 from official sources before building the pack files and on every rule-pack version bump; any change is a new pack version (immutable once `ACTIVE`). Changes to this document after baseline go through CHANGE_REQUESTS.md (rule 11); contract gaps go through CONTRACT_CHANGE_REQUESTS.md.
