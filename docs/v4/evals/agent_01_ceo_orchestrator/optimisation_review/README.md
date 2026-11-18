# Deterministic golden dataset — Agent 01 workflow optimisation proposals

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 01 CEO & Master Orchestrator |
| Depends on | blueprint `agents/agent_01_ceo_orchestrator.md` §6.6, §8.3, §10.6; directive §3.1 row 01, §3.3 learning loop and cost levers; RESEARCH_LOG PR-02; ADR-007, ADR-012; task type `agent_01.optimisation_review` (pending CCR) |
| Why this dataset exists | Proposals are rule-based detectors over MEASURED metrics with no LLM (blueprint §5). The dataset proves that proposals need enough data, use only measured evidence, stay inside one tenant, and never target compliance gates, approvals, budgets or window guards. |
| MVP scope | **3C** · Tier 0; OP-23 (platform aggregate) Tier 1 |
| Files | `cases.jsonl` (24 cases; no judge) |

## 1. Case format
evals/README §2 with `input = {component: "ProposalEngine", fixture: {scope, config, open_proposals, metrics}}`. `config` values are **test thresholds**, not product defaults. `expected.proposals` is the exact ordered list (by `rule_id`); `expected.skipped` lists rules that matched but were suppressed.

## 2. Coverage
| Cases | Rule / guard |
|---|---|
| OP-01…03 | P1 bottleneck; G1 minimum samples; G3 MEASURED only |
| OP-04…05 | P2 retry hotspot |
| OP-06…08 | P3 revision loops; G2 compliance gate excluded |
| OP-09…11 | P4 cheaper model tier (proposal only; eval gate required) |
| OP-12…13 | P5 prompt caching (PR-02) |
| OP-14…15 | P6 batch eligibility (AI_IO only) |
| OP-16…17 | P7 render capacity (recommend only, rule 8) |
| OP-18 | P8 queue wait |
| OP-19 | G5 duplicate open proposal |
| OP-20…21 | G2: never a budget increase, never skip an approval |
| OP-22…23 | G4 tenant isolation; platform aggregate needs `platform.ops_summary` |
| OP-24 | several rules in one window |
Category counts: 8 POSITIVE, 12 HARD_NEGATIVE, 4 EDGE.

## 3. Assertions
Exact equality on `proposals` (rule, target, action, experiment kind) and `skipped`; `must_not_target` lists targets that must not appear in any proposal; `applied_changes` must be 0 in every case (nothing is applied automatically); `security_event` / `error_code` as given.

## 4. Thresholds
100 % pass; any failure blocks the PR. Runs offline on every CI run.

## 5. Open points
- The task type `agent_01.optimisation_review` and its system production type are pending CCR (blueprint §18.3 item 1); threshold config keys pending CCR (item 5).
