# Eval set — `agent_15.unit_economics` (deterministic, no prompt, no judge)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** (3C, Tier 0 (3A produces only the cost side, see cost_stage_report)) |
| Owner | Agent 15 Growth & Revenue |
| Depends on | 17_BUSINESS_PLAN.md §8.1–§8.3, §9.2, §9.3; agent_15 blueprint §6.4 |
| Directive sections covered | §1B.5 (financial model, unit economics, break-even, payback), rule 4 (labels PROJECTION vs ACTUAL) |
| Files | `cases.jsonl` (25 cases); no `rubric.md` (no LLM step, 27 §6 applies only to LLM steps; the deterministic standard is 27 §6.2 item 1) |

## 1. Scope
Tests `UnitEconomics.video`, `.channel_month` and `.payback` (blueprint §6.4) exactly as 17 §8.2, §9.2, §9.3 define them, in integer minor units and basis points. No input value is a forecast of this project: all numbers are fixtures. Labels follow 17 §8.3.

## 2. Case coverage
| Category | Cases | What they prove |
|---|---|---|
| ANSWER_KEY | AK-01 no YPP and no funnel: break-even `UNDEFINED`, never a number; AK-02 funnel-only revenue; AK-03 above break-even | 17 §9.2 |
| POSITIVE / EDGE (video) | POS-04, EDGE-05 … EDGE-16 | ad revenue with withholding, zero views, round-up of fixed share, invalid inputs, label propagation, ATP term outside break-even (open item O-6), negative profit, integer floors |
| Month | MON-17 … MON-19 | revenue, cost, profit, ROI in basis points (floor toward minus infinity), zero cost gives null, MRR from recurring items only |
| Payback | PAY-20 … PAY-25 | only ACTUAL months, `NO_PAYBACK_YET`, `INSUFFICIENT_DATA`, round up to one decimal month, invalid k |

## 3. Input and `expected`
See blueprint §6.4 for every formula. Input `kind` is `VIDEO`, `CHANNEL_MONTH` or `PAYBACK`. Expected values are exact integers, `null`, or the strings `UNDEFINED`, `ABOVE_BEV`, `BELOW_BEV`, `OK`, `NO_PAYBACK_YET`, `INSUFFICIENT_DATA`; `error` is null or `PERMANENT.INPUT_INVALID`.

## 4. Assertions and thresholds
Exact equality; floats are forbidden (a test fails if any intermediate is a float); permuting `videos` or `months` order within their stated order rules changes nothing else. **Threshold: 100 % of cases** (`evals.agent_15.unit_economics.min_pass_rate` = 1.0). Free in CI.

## 5. Open points
- O-6: 17 §9.2 leaves the ATP margin out of the break-even contribution while 17 §8.2 includes it in revenue. Implemented as written (EDGE-13); a change is a CCR to 17.
