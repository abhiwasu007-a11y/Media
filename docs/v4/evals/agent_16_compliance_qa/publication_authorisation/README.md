# Deterministic golden set — `agent_16.publication_authorisation`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 16 Compliance & QA |
| Depends on | [blueprint](../../../agents/agent_16_compliance_qa.md) §6.5 (guards G1–G14), §6.6 (human-wins total), §23.3 (R14 owner-chat evidence); 04 §5.16, §5.17, §5.21; 18 §9.1 |
| Files | `cases.jsonl` (28 cases), `rubric.md` |
| LLM step | **none** — this task is deterministic (27 §9: "deterministic checks only"); no prompt file exists |

## 1. Case format
`input.fixture` describes the DB rows the guard functions read (approval, steps, contributions, owner-evidence records (pending CCR), gate state, disclosure decision, render, per-dimension machine and HUMAN points, licence state, FIN-R9 age in days relative to evaluation, hash and tenant flags). The test harness materialises the fixture as rows in a test org and runs `AuthorisationGuards.evaluate`. No calendar dates: ages are relative day counts.

## 2. `expected`
`verdict` (`ALLOWED` / `BLOCKED`, always `is_final = true`), `failed_guards` (exact set), `authorised_action` (`DELIVERY` in 3A when ALLOWED, else null), `human_wins_total` (machine rows replaced by HUMAN rows per dimension; checked by the generator).

## 3. Coverage
Positive paths (PA-01, 03, 18, 20, 23, 25, 28), §1A.7 compliance-rejects-regardless (PA-04), approval binding (PA-05…07), contribution (PA-08, 09), human-only steps (PA-10), **R14 negatives** — unconfirmed (PA-11), subagent message (PA-12), document (PA-13), tool result (PA-14), no review code (PA-15), paraphrased quote (PA-16) — NHR and disclosure (PA-17…20), blocking QC (PA-21), licences (PA-22, 23), FIN-R9 boundary (PA-24, 25), subject changed (PA-26), cross-tenant (PA-27), threshold boundary (PA-28).

## 4. Threshold
**100 %** of cases (deterministic; any failure blocks the PR).
