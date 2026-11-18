# Eval set — Agent 02 deterministic core (no LLM)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** (3C) |
| Owner | Agent 02 Market Intelligence |
| Depends on | agents/agent_02_market_intelligence.md §6 (formulas and parameters), §10 (function specs), §12 (quota), §19 (public-data filter), 27 §6.1, evals/README.md |
| Directive sections covered | §3.1 row 02 (evidence and confidence arithmetic; public/authorised data filter; source fetch limits), §1B.1 (published weights and evidence; trending alone never qualifies), YT-02, Developer Policies 30-day storage limit (blueprint §12.2), FIN-R1…R13 (lexical floor) |
| Files | `cases.jsonl` (65 cases) |

## 1. Scope
These steps use no model, so there is no prompt and no judge. The dataset pins the arithmetic and the filters with exact expected values. Parameters are the design defaults of blueprint §6.8 (ESTIMATE; they are configuration, and a change of a default requires regenerating the affected `expected` values in the same PR). Expected values were computed from the reference formulas of blueprint §6 and rounded as stated there (3 decimals; opportunity score 2 decimals). Each case records the function name and its keyword arguments in `input`.

## 2. Case coverage
| Function | Cases | Behaviour pinned |
|---|---|---|
| `velocity` | 4 | views per hour with an age floor |
| `cohort_percentile` | 4 | mid-rank percentile, minimum cohort |
| `trajectory` | 8 | median incremental velocity ratio, thresholds, minimum pairs, ignored pairs |
| `confidence` | 8 | component arithmetic, caps, bands, agreement |
| `opportunity` | 8 | score, breakdown, disqualifiers (trending alone never qualifies) |
| `quota_plan` | 7 | search and default-bucket planning, partial and blocked states |
| `lexical_screen` | 7 | code-side floor of the topic screen |
| `tighten` | 4 | monotone merge of model screen and code screen |
| `public_data_filter` | 6 | public/authorised source rule, forbidden fields, cross-tenant reference |
| `validate_retention` | 4 | 30-day maximum on stored public API data |
| `sanitize_title` | 5 | control and zero-width removal, whitespace, Devanagari-safe truncation |
Distribution: HARD_NEGATIVE 9, POSITIVE 18, EDGE 38.

## 3. Case and `expected` format
`input = {"function": <name>, "args": {…}}`; `expected` is the exact return value (JSON). Floats compare equal after rounding as stated in the function's spec; strings, lists and booleans compare exactly.

## 4. Assertions
| ID | Assertion |
|---|---|
| D1 | the function returns exactly `expected` for `args` |
| D2 | the function is pure: the same call twice gives the same result and mutates no argument |
| D3 | error cases return the stated structured error and raise no exception (`validate_retention`, `public_data_filter`) |
| D4 | property checks run beside the cases (hypothesis, 27 §8): confidence is within 0–1 and never exceeds a cap that applies; `tighten` never lowers severity; `cohort_percentile` is within 0–1; `quota_plan` never exceeds a cap |

## 5. Thresholds
All cases must pass (100 %); a deterministic step has no tolerance. CI marker `unit` plus `contract`.

## 6. Open points
- LEX-06 documents that the lexical floor is strict (a "learning target" title hits the price-target pattern). That is deliberate: the floor can only tighten; Agent 03 or the human reviewer can re-frame. The pattern lists are config and **REQUIRES REVIEW (Phase 1)** with 13_COMPLIANCE_YOUTUBE_POLICY before 3C build.
- The parameter defaults are not measured; they are calibrated against the golden-sample pilot and later analytics (blueprint §20).
