# Eval set — `agent_15.stop_scale` (deterministic, no prompt, no judge)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** (3C, Tier 0) |
| Owner | Agent 15 Growth & Revenue |
| Depends on | 17_BUSINESS_PLAN.md §10.1, §10.2; 09 §4 (B1–B8); agent_15 blueprint §6.5 |
| Directive sections covered | §1B.5 (stop/scale rules per channel), §3.1 row 15 |
| Files | `cases.jsonl` (24 cases); no `rubric.md` (no LLM step, 27 §6 applies only to LLM steps; the deterministic standard is 27 §6.2 item 1) |

## 1. Scope
Tests `StopScaleEvaluator.evaluate` (blueprint §6.5): scale conditions S1–S4, pause/stop triggers P1–P4 and the recommendation. It only recommends; every scale or stop action is an owner decision (17 §10.1, S7). Thresholds are carried inside each case (config namespace `business.*`, pending CCR; no value ships), so the set stays valid when the owner changes them. Case values are fixtures, not recommendations.

## 2. Case coverage
| Category | Cases | What they prove |
|---|---|---|
| ANSWER_KEY | AK-01 all conditions hold, AK-02 compliance incident stops immediately, AK-03 missed weeks reach M, AK-04 inauthentic-content signal | 17 §10 |
| POSITIVE / EDGE | POS-05 … EDGE-24 | boundaries (retention, ratio, QC 85), zero revenue, unmeasured revenue (INSUFFICIENT_DATA, never FAIL), fewer than N videos, only the newest N count, run of missed weeks, null week never counts as missed, P3 sets only the S4 pause flag, precedence P2 > P4 > P1 > scale, N = 1 |

## 3. Input and `expected`
Input: `config` (`n_consecutive`, `min_relative_retention_bp`, `max_cost_revenue_ratio_bp`, `m_weeks`, `review_budget_minutes_week`), `videos[]` newest first (`relative_retention_bp`, `revenue_minor`, `cost_minor`, `qc_score`, `compliance_all_passed`), `weeks[]` newest first (`missed`: true / false / null), `review_minutes_week`, `compliance_incident`, `budget_breached`, `inauthentic_signal`.
Expected: `S1`..`S4` (`PASS` / `FAIL` / `INSUFFICIENT_DATA`), `scale_eligible`, `pause_triggers`, `recommendation` (`STOP_IMMEDIATE`, `STOP_AND_REVIEW`, `PAUSE_RECOMMENDED`, `SCALE_ELIGIBLE`, `HOLD`, `INSUFFICIENT_DATA`), `paid_work_paused_by_s4`.

## 4. Assertions and thresholds
Exact equality. **Mandatory:** no case with `compliance_incident = true` may return anything but `STOP_IMMEDIATE` (AK-02, EDGE-22); `scale_eligible` is never true with any `INSUFFICIENT_DATA` or `FAIL`. **Threshold: 100 % of cases** (`evals.agent_15.stop_scale.min_pass_rate` = 1.0). Free in CI.

## 5. Open points
- The first-channel thresholds N, M, retention and ratio targets, and the weekly review budget (input A6) are owner inputs: REQUIRES REVIEW (Phase 1).
