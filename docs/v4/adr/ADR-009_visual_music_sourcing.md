# ADR-009 — Visual and music sourcing (stock footage, music, AI video)

| Field | Value |
|---|---|
| Status | **Proposed** (documentation). Software: **Planned**. |
| Date | 2026-11-18 |
| Directive | §1A.1 (visual sourcing hierarchy a–e), §1A.4 (licensed music and SFX only), §1A.6 (every shot has a licence record), §1A.11 (AI video is the most expensive item per second), §1C.8 (third-party use), §3.2a (provider-independent stock/video adapters) |
| Owner decisions | D1 (Agents 08/09 in 3A; spend controls; files delivered, no upload in 3A) |
| Contracts used | 04 §5.15 (`licences`, `licence_ledger`, `assets`), §5.14 (`cost_ledger`, `budgets`); GLOSSARY §6.17–6.22 (`licence_state`, `licence_source_type`, `visual_source_tier`, `capability`, `third_party_permission`, `licence_usage_kind`); 24 §3.2 (`agent_08.asset_sourcing`, `agent_09.shot_plan`, `agent_16.compliance_gate`), 24 §6 (cost model) |
| Research | PR-06, PR-06d/e, PR-07; RESEARCH_LOG "Blocked vendor hosts (wave 2)" |
| MVP scope | **3A** (hierarchy enforcement, licence ledger, code-made motion graphics, owner material, one stock source or none) · **3B** (visual-mix measurement on golden samples; AI B-roll only if a scene has no real/licensed option) · **3C** (multiple libraries, AI video adapter, reuse engine) |
| Enterprise tier | Tier 0: Individual-class licence, one channel. **Tier 1 (clients): Business-class licence required** (PR-06). |

## 1. Context
- §1A.1 order: (a) owner real material → (b) licensed real stock with commercial rights (prefer a paid library covering monetized YouTube, channel registration against claims, indemnification; free libraries only with the licence recorded per clip) → (c) code-made motion graphics → (d) AI video B-roll only where real footage does not exist, disclosed when realistic, never real identifiable people or fabricated events → (e) AI stills with motion last, never the majority of screen time. Encoded as `visual_source_tier` `A_OWNER_REAL` … `E_AI_STILL`.
- For the trading-education channel most screen time is charts from the owner's historical data (tier a/c, §1B.2a, subject to `FIN-R9`).
- **Storyblocks (PR-06, VERIFIED):** annual billing Essentials $21/mo · Unlimited All Access $30/mo · Small Business $40/mo (excludes agencies and production companies) · Business by quote. Individual / Small Business: $20k indemnity, 1 YouTube channel; Business: $1M indemnity, multiple channels, perpetual use. The Individual licence "does not cover … reliance on this license by any entity, company, or client"; the Business licence lets you "license Stock Files on behalf of a third-party client … in a completed project".
- **Storyblocks monetization / whitelisting (PR-06d/e, NOT CONFIRMED):** "Monetiz…" does not appear in the licence text (it permits "the internet"); there is no "whitelisting" term; Storyblocks "does not warrant against a platform like YouTube blocking a Customer Work".
- **Music (PR-07, PARTIAL):** Epidemic Sound FAQ: "no additional cost when you publish or monetize your content"; plan price not in HTML.
- **AI video (PR-07, PARTIAL):** Runway "from $12/month"; Luma Plus $30/mo (10,000 credits, "Commercial use"), Pro $90, Ultra $300; Kling price not in HTML. Credit-to-seconds mapping not read, so **AI video cost per second is unknown**.
- **Blocked vendor hosts (wave 2)** — facts **not** recorded, so these vendors cannot be compared yet: `artlist.io` (music/footage), `www.pond5.com`, `www.pexels.com`, `pixabay.com`, `www.shutterstock.com`, `openai.com`; plus `support.storyblocks.com` (no connection).

## 2. Decision
1. **The hierarchy is enforced in code, not left to the model.** `agent_08.asset_sourcing` searches tiers in order a → e per scene and records why each higher tier was skipped (no match / licence not usable / budget). `agent_09.shot_plan` and `agent_16.compliance_gate` reject a plan in which tier `E_AI_STILL` is the majority of screen time (§1A.1e); the share is computed from `licence_ledger.used_from_ms/used_to_ms`. Thresholds other than "majority" are config, calibrated in 3B.
2. **Every used item has a licence ledger row**, including owner-made and code-generated items (`OWNER_MADE` / `CODE_GENERATED` assets need no `licences` row by the `assets` CHECK, but each use still gets a `licence_ledger` row; because `licence_ledger.licence_id` is NOT NULL, such rows carry `licence_id` NULL only when the asset's `source_type` is `OWNER_MADE` or `CODE_GENERATED` **(pending CCR: nullable `licence_ledger.licence_id` for owner-made / code-generated assets)**). The 04 §5.15 insert guard applies: licence `ACTIVE`; platform-held licence used for another org only if `third_party_permission = PERMITTED`; monetized destination only if `covers_monetized_youtube = true`.
3. **Paid stock library — Storyblocks is the candidate**, not a purchase decision (rule 8):
   - Tier 0: an Individual-class plan is sufficient for one owner channel (PR-06).
   - Tier 1+: Business licence required (PR-06); quote **REQUIRES REVIEW (Phase 1)**.
   - `covers_monetized_youtube` and `channel_registration_supported` are stored as **NULL (unknown)** until Storyblocks confirms in writing (PR-06d/e). Under the insert guard, NULL blocks use in a monetized destination. 3A delivers files only (no upload), so 3A rendering is not blocked, but **publishing such a render to a monetized channel is blocked until confirmed**.
   - Alternative libraries are compared only after their hosts are reachable and facts are recorded (blocked list above).
4. **Free libraries (Pexels/Pixabay-type)** are allowed only with a per-clip licence record: `source_type = FREE_STOCK`, `indemnification = false`, `terms_ref` + `terms_sha256` snapshot of the licence page at download time, `source_url` and `vendor_item_id` on the ledger row (§1A.1b). Their current terms are **not recorded** (hosts blocked) → **REQUIRES REVIEW (Phase 1): Pexels and Pixabay licence text** before first use.
5. **Music and SFX**: licensed only (§1A.4); `source_type = MUSIC_LIBRARY` / `SFX_LIBRARY`, `usage_kind = MUSIC_BED` / `SFX`. Epidemic Sound is the only music candidate with a recorded fact (PR-07); its plan price, client-use terms and Content ID handling are **REQUIRES REVIEW (Phase 1)**. Artlist cannot be evaluated (blocked host). In 3A a render may use no music bed rather than unlicensed music.
6. **AI video B-roll (tier d)**: candidates Runway, Luma, Kling (PR-07). Not in 3A by default; enabled per scene only when tiers a–c have no option, with a per-video `video_ms` budget in S4 (§1A.11, 24 §6). Every AI clip sets `is_realistic_synthetic` and `depicts_real_person` on the asset (feeds the disclosure decision); `depicts_real_person = true` is rejected for AI output. Provider choice needs the credit-to-seconds mapping and commercial-use terms per plan → **REQUIRES REVIEW (Phase 1)**.
7. **Adapters**: `amw_adapters/stock_footage/`, `music/`, `video_gen/`, `image/` behind Protocols with fakes (SOURCE_LAYOUT); capabilities `stock_search`, `video_gen`, `image_gen` (GLOSSARY §6.20). Downloads and licences are idempotent side effects (07 §11).
8. **Cost**: each paid item writes `cost_ledger` (`operation = stock.license`, `unit_kind = items`; AI video `video_ms`); subscriptions are recorded as a subscription share per 24 §6 (method owned by 09_COST_AND_BUDGET.md).
9. **No source watermark or logo** in any shot (§1A.6); preview/comp files are never rendered into a deliverable.

## 3. Options considered (with evidence)
| Option | Evidence | Verdict |
|---|---|---|
| **Storyblocks Individual-class (Tier 0)** | PR-06: 1 channel, $20k indemnity, $21–30/mo annual | **Candidate for Tier 0**, purchase needs owner approval |
| Storyblocks Business (Tier 1+) | PR-06: multiple channels, $1M indemnity, client projects; price by quote | Required before client work |
| Storyblocks Small Business | PR-06: excludes agencies and production companies | Rejected for client work |
| Other paid libraries (Shutterstock, Pond5, Artlist) | Hosts blocked; no facts recorded | Not evaluated |
| Free libraries only | §1A.1b: no indemnification; terms not recorded | Allowed per clip with licence snapshot only |
| Epidemic Sound (music) | PR-07: no extra cost to publish/monetize; price not read | Candidate |
| AI video as main visual source | §1A.1d/e, §1A.11 (most expensive per second); cost per second unknown (PR-07) | Rejected; short B-roll only |

## 4. Consequences
- Positive: every shot in a render is traceable to a licence and a tier; licence gaps surface as blocking compliance results, not as Content ID claims later.
- Negative: until PR-06d/e is answered, Storyblocks footage cannot go to a monetized channel; the first channel relies mostly on owner/code-made visuals (tier a/c), which fits the chart-led education format.
- 3A-relevant contract gap: owner-made / code-generated uses in `licence_ledger` (pending CCR, §2.2). Until it is decided, the per-shot licence check of §1A.6 cannot pass for tier a/c shots.
- REQUIRES REVIEW (Phase 1): written answers from Storyblocks on monetized YouTube coverage and channel registration (PR-06d/e).
- REQUIRES REVIEW (Phase 1): AI video unit cost per second and per-plan commercial terms (PR-07).

## 5. Revisit trigger
- Storyblocks answers PR-06d/e, or a blocked host becomes reachable and a competitor's facts are recorded.
- 3B measurement shows a visual-mix problem (e.g. too little real footage for a topic class).
- First client contract (Tier 1 licence requirement).
- Price or licence-text change at re-verification (plan Q18).

## 6. Research IDs cited
PR-06, PR-06d/e, PR-07; RESEARCH_LOG blocked-host list (wave 2).
