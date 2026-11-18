# Eval set — `agent_03.topic_selection` step `gap analysis` (deterministic, no LLM)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** (3C) |
| Owner | Agent 03 Content Strategy |
| Depends on | blueprint §6.5 (algorithm), §10 `compute_gaps`, evals/README.md, 27_ENGINEERING_STANDARDS.md §6, GLOSSARY_AND_IDS.md §6.38, §6.51, agents/agent_03_content_strategy.md |
| Directive sections covered | §3.1 row 03 (content gap analysis), §1B.2a (course pointer coverage) |
| Files | `cases.jsonl` (22 cases), `rubric.md` |

## 1. Scope
`compute_gaps(nodes, coverage, targets, course_chapter_ids)` is pure code. Coverage values: `COVERED`, `IN_FLIGHT` count as used; `NONE`, `BLOCKED_COOLDOWN` and a missing key do not. Keys in `coverage` for nodes not in the tree are ignored.

## 2. Algorithm under test
1. `used` = nodes with coverage `COVERED` or `IN_FLIGHT`. `uncovered_node_ids` = all other nodes, ordered by numeric node number.
2. For each pillar in `targets.pillar_share`: `actual_share` = used nodes of that pillar / all used nodes (0.0 if none used), rounded to 4 decimals; `deficit` = max(0, target - actual) rounded to 4 decimals. Sorted by deficit descending, then pillar ID.
3. For each ID in `course_chapter_ids` with at least one mapped node: `videos` = used nodes mapped to it; `deficit` = max(0, `chapter_min_videos` - videos); only deficits above 0 are listed, sorted by deficit descending then chapter ID. A chapter with no mapped node is in `orphan_chapter_ids` (sorted).

## 3. Case coverage
Positive (6), edge (13), hard negative (3: cooldown is not coverage, case-study and mistake nodes count, in-flight counts). Includes numeric-not-lexical ordering, rounding, empty tree, zero minimum, orphan chapter, tie-breaks.

## 4. Assertions and thresholds
| ID | Assertion |
|---|---|
| A1 | output equals `expected` exactly (all four lists) |
| A2 | function is pure: same input twice gives equal output; input not mutated |
| A3 | runs in under `evals.agent_03.gap_analysis.max_ms` (no threshold until measured) |
Pass threshold: **100 % of cases** (mandatory). No judge, no cost.

## Recording fields (per case per run; 27 §6.4)
`run_id`, `prompt_id`, `prompt_sha256`, `rule_pack_versions`, `config_key`, `provider`, `model`, `case_id`, `passed`, `assertions` (id to pass/fail + detail), `judge_scores`, `judge_prompt_id`, `tokens_in`, `tokens_out`, `tokens_cached_in`, `cost_micros`, `currency`, `latency_ms`, `started_at`, `figure_kind` (`ESTIMATE` until reconciled with provider usage).
