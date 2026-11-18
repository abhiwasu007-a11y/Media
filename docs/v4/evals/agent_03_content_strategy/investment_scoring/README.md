# Eval set — `agent_03.topic_selection` step `content investment engine` (deterministic, no LLM)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** (3C) |
| Owner | Agent 03 Content Strategy |
| Depends on | blueprint §6.3 (gates, formula), §10 `rank_candidates`, evals/README.md, 27_ENGINEERING_STANDARDS.md §6, GLOSSARY_AND_IDS.md §6.38, §6.51, agents/agent_03_content_strategy.md |
| Directive sections covered | §3.1 row 03 (content investment decision engine), §1B.1 (weights are configuration, evidence published, trending alone never qualifies), §1B.2 (education only), FIN-R12 |
| Files | `cases.jsonl` (25 cases), `rubric.md` |

## 1. Scope
`rank_candidates(candidates, context)` is pure code. Weights, support map, multiplier and `top_k` are carried in every case, so the dataset stays valid when configuration changes (config `planning.invest.*`; values are design defaults to be calibrated in 3B).

## 2. Algorithm under test
1. Gates, evaluated for every candidate, all failing gates listed in this fixed order: `COMPLIANCE_EXCLUDED` (screen `EXCLUDED`), `NOT_EVERGREEN` (`evergreen_required` and time sensitivity not `EVERGREEN`), `ALREADY_USED` (`IN_FLIGHT` or `COVERED`), `COOLDOWN` (`BLOCKED_COOLDOWN`), `PREREQUISITE_UNMET`, `METHOD_NOT_RELEASED` (method topic and `release_approved` not true), `NO_COURSE_POINTER` (`pointer_required` and no pointer), `NO_LIBRARY_SUPPORT` (support `NONE`).
2. Eligible candidates: `expertise_fit` = `support_map[support_level]`; present factors = weight above 0 and value not null (external factors from `factors`, plus `expertise_fit`). `score` = sum(weight x value) / sum(weight) over present factors, rounded to 6 decimals; multiplied by `reframe_multiplier` (and re-rounded) when the screen is `REFRAME_AS_EDUCATION`. `evidence_completeness` = present weights / all positive weights, 4 decimals.
3. Ranking: score descending, then `funnel_fit` descending (missing = 0), then numeric node number ascending. `selected_node_id` is the first (or null); `shortlist_node_ids` the first `top_k`. `excluded` sorted by node number.

## 3. Case coverage
Positive (8), hard negative (8: demand without library support, excluded, event-driven, unreleased method twice, no pointer, used/cooldown, prerequisites), edge (9: multiple gates, nothing eligible, empty list, tie-breaks, multiplier, zero weight, numeric order, sparse evidence, thin support).

## 4. Assertions and thresholds
| ID | Assertion |
|---|---|
| A1 | output equals `expected` exactly (`ranked`, `excluded`, `selected_node_id`, `shortlist_node_ids`) |
| A2 | pure and deterministic: same input, same output; input not mutated |
| A3 | no excluded node appears in `ranked` |
Pass threshold: **100 %** (mandatory); in particular HN-09, HN-10, HN-11, HN-12, HN-13 must never rank a gated node.

## Recording fields (per case per run; 27 §6.4)
`run_id`, `prompt_id`, `prompt_sha256`, `rule_pack_versions`, `config_key`, `provider`, `model`, `case_id`, `passed`, `assertions` (id to pass/fail + detail), `judge_scores`, `judge_prompt_id`, `tokens_in`, `tokens_out`, `tokens_cached_in`, `cost_micros`, `currency`, `latency_ms`, `started_at`, `figure_kind` (`ESTIMATE` until reconciled with provider usage).
