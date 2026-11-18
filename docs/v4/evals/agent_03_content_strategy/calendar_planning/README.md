# Eval set — `agent_03.topic_selection` step `calendar planner` (deterministic, no LLM)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** (3C) |
| Owner | Agent 03 Content Strategy |
| Depends on | blueprint §6.4 (algorithm), §10 `plan_calendar`, evals/README.md, 27_ENGINEERING_STANDARDS.md §6, GLOSSARY_AND_IDS.md §6.38, §6.51, agents/agent_03_content_strategy.md |
| Directive sections covered | §3.1 row 03 (intelligent multi-channel calendar), rule 9 (tenant isolation), owner rule C.4 (relative weeks only, no dates) |
| Files | `cases.jsonl` (22 cases), `rubric.md` |

## 1. Scope
`plan_calendar(channels, org_videos_per_week_max, weeks, prerequisites, pillar_of, pillar_max_consecutive)` is pure code. The calendar uses **relative week numbers** only; mapping weeks to dates and times is the scheduler's job (06), never this agent's.

## 2. Algorithm under test
1. Input validation: a node ID that appears in two channels' queues is an error `DUPLICATE_NODE_ACROSS_CHANNELS` (channel isolation); nothing is planned.
2. For week 1 to `weeks`, for each channel in input order, for position 1 to `cadence`: if the org's planned count for the week has reached `org_videos_per_week_max`, record the slot in `capacity_deferred`. Otherwise eligible nodes are the channel's remaining queue entries whose prerequisites are all already scheduled **in the same channel**. None eligible: record `unfilled` with reason `NO_ELIGIBLE_NODE`. Else take the first eligible node that does not make `pillar_max_consecutive + 1` same-pillar videos in a row in that channel's sequence; if every eligible node would, take the first eligible node and set `pillar_run_relaxed = true`. A run limit of 0 disables the pillar rule.

## 3. Case coverage
Positive (6), hard negative (3: duplicate across channels, capacity deferral, zero capacity), edge (13: unfilled slots, missing prerequisite, relaxed run, empty inputs, zero cadence, prerequisite chains and same-week prerequisite, cross-channel prerequisite ignored, capacity starvation order).

## 4. Assertions and thresholds
| ID | Assertion |
|---|---|
| A1 | output equals `expected` exactly |
| A2 | no node appears twice; every slot's node came from its own channel's queue |
| A3 | per week, planned slots <= `org_videos_per_week_max` |
| A4 | pure and deterministic |
Pass threshold: **100 %** (mandatory).

## Recording fields (per case per run; 27 §6.4)
`run_id`, `prompt_id`, `prompt_sha256`, `rule_pack_versions`, `config_key`, `provider`, `model`, `case_id`, `passed`, `assertions` (id to pass/fail + detail), `judge_scores`, `judge_prompt_id`, `tokens_in`, `tokens_out`, `tokens_cached_in`, `cost_micros`, `currency`, `latency_ms`, `started_at`, `figure_kind` (`ESTIMATE` until reconciled with provider usage).
