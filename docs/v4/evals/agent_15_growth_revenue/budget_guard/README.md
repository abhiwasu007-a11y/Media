# Eval set — `agent_15.budget_guard` (deterministic, no prompt, no judge)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** (3A, Tier 0) |
| Owner | Agent 15 Growth & Revenue |
| Depends on | 09_COST_AND_BUDGET.md §2–§4, §8; 03 §11.3 (T03, T05); 07 §2 `RESOURCE.BUDGET_EXHAUSTED`; agent_15 blueprint §6.2 |
| Directive sections covered | D1 (spend controls), rule 8, §2 S4 |
| Files | `cases.jsonl` (36 cases); no `rubric.md` (no LLM step, 27 §6 applies only to LLM steps; the deterministic standard is 27 §6.2 item 1) |

## 1. Scope
Tests the pure budget functions `admit` (E1), `check_call` (E2) and `evaluate_post_call` (E3) of the blueprint §6.2. Each case carries its budgets, ledger rows and held reservations, so no database is needed. The consumed amount is the single definition of 09 §3.3 (VERIFIED replaces its ESTIMATE through `estimate_entry_id`; held reservations added). Amounts are integer micros (27 §7.3 rule 9). Limits in cases are fixtures, not recommendations; no real limit is stated anywhere (rule 8).

## 2. Case coverage
| Category | Cases | What they prove |
|---|---|---|
| ANSWER_KEY | AK-01 per-video budget fully used, AK-02 limit 0 means no paid call, AK-03 provider limit row missing, AK-04 ample budgets | D1: stop on breach, owner-set limits only, provider gate (09 §8) |
| POSITIVE / EDGE (ADMIT) | POS-05 … EDGE-23 | exact fit, one micro short, held reservations, VERIFIED replacement and leak, suspended state with and without `non_critical_suspend`, missing/DISABLED budgets, provider cap, several providers, non-paid tasks (B4), soft limit warning (B7), all-or-nothing, reason precedence |
| CALL (E2) | CALL-24 … CALL-28 | task hold cap, provider gate at call time, a running task inside its own hold continues after a breach (B2) |
| POST_CALL (E3) | POST-29 … POST-36 | state change at consumed >= limit, soft-limit notice, holds do not suspend at E3, per-budget independence, no re-change of suspended or disabled budgets, VERIFIED lowering consumption |

## 3. Input and `expected`
Input: `op` (`ADMIT` / `CALL` / `POST_CALL`); for ADMIT `paid`, `requested_micros`, `required_providers`, `required_periods`; for CALL `provider`, `call_micros`, `task_hold_remaining_micros`; `budgets[]` each with `budget_id`, `scope_kind`, `scope_key`, `period`, `state`, `limit_micros`, `soft_limit_ratio_bp`, `non_critical_suspend`, `held_micros`, `ledger[]` (`entry_id`, `figure_kind`, `amount_micros`, `estimate_entry_id`).
Expected: ADMIT `{decision (ADMIT/SUSPEND), reason (NOT_PAID, OK, PROVIDER_GATE_MISSING, NO_ACTIVE_BUDGET, BUDGET_SUSPENDED, INSUFFICIENT_REMAINING), budget_ids, warnings, error_code, transition (T03 or T05)}`; CALL `{decision (CALL_OK/CALL_REFUSED), reason, error_code}`; POST_CALL `{state_changes, soft_limit_notices}`.

## 4. Assertions and thresholds
Every expected field equals the function output exactly (integer arithmetic, ordered ID lists). **Threshold: 100 % of cases** (config `evals.agent_15.budget_guard.min_pass_rate`, fixed at 1.0). Also run as a property test: permuting the order of `budgets` or `ledger` rows never changes the result. No paid call; free in CI.

## 5. Open points
- O-2 (blueprint §25.3): 09 §3.2 says "consumed + held >= limit"; E3 here uses ledger-consumed >= limit (POST-30, POST-32), holds are enforced at E1 only. Cases change by CCR if 09's owner decides otherwise.
