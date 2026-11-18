# Deterministic golden dataset — Agent 08 non-LLM core (`agent_08.asset_sourcing`)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 08 Visual Assets |
| Depends on | blueprint `agents/agent_08_visual_assets.md` §6, §9, §10, §16, §19, §20; 07 §2; 08 §8; 18 §2, §7.9; 13 §1.3, §5; ADR-009; 27 §6.1 |
| Why this dataset exists | The decisions of Agent 08 that matter most for compliance, licensing, cost and isolation are **deterministic**: the tier cascade, the chart data-age guard (FIN-R9), the licence guard, the reuse engine, fingerprints, the AI budget gate, the tier-E share guard, the ledger rows, the overlay validator (FIN-R13), the safety floor over model output, tenant guards and replay safety. They have their own golden dataset in addition to the two LLM-step datasets (`search_query_plan`, `candidate_rank`). No model is called; the LLM adapter is a scripted fake. |
| MVP scope | **3A** (all cases) · Tier 0; `TG-*` and `RE-02` are part of the Tier 1 cross-tenant suite already at Tier 0 |
| Files | `cases.jsonl` (139 cases; no judge) |

## 1. Case format
evals/README §2 with `input = {component, fixture}`: `component` is the unit under test (class names of blueprint §9) and `fixture` describes its data; `expected` is the exact deterministic result; `judge_min` is always `null`. Days are **offsets relative to the sourcing day** (0 = the day the task runs; negative = earlier); no calendar date appears anywhere. Values such as the lag (30; a test value that mirrors the configured `compliance.finance_sebi_in.price_data_lag_days`, IN-02), the near-duplicate distance threshold (6), the tier-E limit (0.5), the licence warning window (14 days) and the lexicon `lex_a08_test_v1` are **test values**, not product defaults: the product values are config and several are **REQUIRES REVIEW (Phase 1)** (blueprint §17, §24). `fixture.destination` values are the payload-local set of blueprint §7.1. In `TierCascade` fixtures, `graphic_content` means "tier C is applicable and renderable for this shot" (blueprint §6.3 item 5: on-screen text or diagram spec, or the plan's fallback template when the plan did not mark the shot as needing AI video); `prohibited_depiction` means a query-plan `NO_SAFE_QUERY` or a plan `depiction.realistic_event_depiction = true`.

## 2. Coverage
| Prefix | Component | Cases |
|---|---|---|
| CL | `ChartLagGuard` | 12 |
| EP | `EarliestPublishDate` | 2 |
| TC | `TierCascade` | 23 |
| LG | `LicenceGuard` | 12 |
| RE | `ReuseEngine` | 10 |
| FP | `FingerprintDHash` | 5 |
| FP | `FingerprintDistance` | 2 |
| BG | `AiBudgetGate` | 7 |
| TS | `TierShareGuard` | 5 |
| CV | `CoverageVerifier` | 5 |
| LB | `LedgerRowBuilder` | 6 |
| EM | `AdapterErrorMapper` | 7 |
| TG | `TenantGuard` | 8 |
| PC | `AiPromptComposer` | 6 |
| DF | `DisclosureFlags` | 4 |
| SF | `SafetyFloor` | 5 |
| TB | `TieBreaker` | 5 |
| CH | `ChartSpecHasher` | 5 |
| AN | `AnnotationValidator` | 7 |
| CR | `CheckpointResume` | 3 |
Categories: {'POSITIVE': 43, 'EDGE': 51, 'HARD_NEGATIVE': 45}.

Highlights: tier cascade over every skip reason and the rule that a chart request never falls to stock or AI (TC-14…TC-21); lag boundary arithmetic including the bar-END rule for weekly and monthly data (CL-02, CL-03, CL-07…CL-09); licence NULL-coverage blocking (LG-07); cross-tenant invisibility (RE-02, TG-02, TG-03, TG-08); the strict 50 percent limit for stills (TS-03); the single covering ledger row rule of 18 §7.9 (CV-02, CV-03); forward-looking overlays rejected (AN-02…AN-05); model output cannot override safety (SF-01…SF-05); no duplicate effect on replay (CR-02, CR-03).

## 3. Assertions
Each case: the component, given `fixture`, returns exactly `expected` (deep equality; list order significant where the blueprint says so: `skips` in tier order, `order` as ranked). Error cases assert the 07 code and, where stated, that a security event is emitted.

## 4. Thresholds
| Threshold | Value |
|---|---|
| Pass rate | **100 %** (deterministic units; any failure is a bug in code or in the dataset) |
| Mutation check (3B) | each rule of blueprint §20 has at least one case that fails when the rule's code is removed |
CI runs this dataset on every PR (no cost).

## 5. Open points
- Several expected values depend on test values listed in §1; if a product value differs, the unit tests use the test value through config injection, the product value is only used in the integration suite.
- `LB-*` rows assume the self-grant licence mechanism of blueprint §13.3 (`licence_ref = self_grant:<source_type>`); if the integrator decides otherwise (nullable `licence_id`, ADR-009), LB-01, LB-02 and CV rows change by a dataset version.
- `EM-04` (`PERMANENT.PROVIDER_REFUSAL` for a safety refusal by a video-generation provider) assumes the provider returns a recognisable policy signal; the signal names are provider facts **REQUIRES REVIEW (Phase 1)** and are mapped inside the adapter, not here.
