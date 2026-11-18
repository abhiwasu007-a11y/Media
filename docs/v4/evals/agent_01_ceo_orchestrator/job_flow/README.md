# Deterministic golden dataset — Agent 01 job flow (state machine, graph, routing)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 01 CEO & Master Orchestrator |
| Depends on | blueprint `agents/agent_01_ceo_orchestrator.md` §6.1–§6.2, §6.5, §10, §19; 03 §5.3, §7.1, §9, §11; 07 §2, §7, §9; 24 §2, §3, §7.1; 3A_SLICE_SPEC §3 |
| Why this dataset exists | Agent 01 has **no LLM step** (blueprint §5). Its decisions are deterministic, so they are tested by this golden dataset instead of a prompt eval. No model is called; no judge; no cost. |
| MVP scope | **3A** (all cases) · Tier 0. Graph records use `CHANNEL_LONG_FORM` / `SHORTS` v2 (pending CCR-3A-1) |
| Files | `cases.jsonl` (44 cases; no `rubric.md` because there is no judge) |

## 1. Case format
evals/README §2 with `input = {component, fixture}`: `component` is the class under test (blueprint §9), `fixture` describes the state; `expected` is the exact deterministic result. `judge_min` is always `null`. Fixture values (counts, caps, hashes) are **test values**, not product defaults. No calendar dates appear.

## 2. Coverage
| Cases | Component | What they prove |
|---|---|---|
| JF-01…05 | `GraphValidator` | 24 §2 load checks: DAG, `on_fail` order, registered task types, `rp.youtube_general` with YouTube |
| JF-06…10 | `JobValidator` | J02 → J03 / J04 with the exact 07 codes; DRAFT channel valid for file delivery (3A) |
| JF-11…12 | `GraphMaterialiser` | optional stages; `limits.max_tasks_per_job` |
| JF-13…14 | `ReadySetEvaluator` | dependency readiness (fan-in) |
| JF-15…19 | `GateRouter` | REVISE to the registry target, cap → `BLOCKED_COMPLIANCE`, STOP, `NEEDS_HUMAN_REVIEW` insert |
| JF-20…23 | `ApprovalRouter` | approve, reject, changes requested (allowed targets, pending CCR), SHA change → withdraw |
| JF-24…26 | `SuccessRule` | 03 §5.3: incomplete output, blob mismatch, BLOCKED is a success |
| JF-27 | `AdviceFilter` | advice never creates tasks |
| JF-28…31 | `JobStateDeriver` | J06, J07, J08 and the no-change case |
| JF-32…34 | `ChildJobPolicy` | SHORTS child job, cap |
| JF-35 | `JobIntake` | `job.create` idempotency and conflict |
| JF-36…39 | `TaskValidator` | T04, T05, cross-tenant ref, tenant mismatch |
| JF-40 | `JobCanceller` | J12 cascade; running task cancels at a safe point |
| JF-41…42 | `StateMachine` | invalid transition, optimistic lock |
| JF-43 | `L2Escalator` | systemic threshold |
| JF-44 | `TaskDispatcher` | binder payload with a foreign-org URI |
Category counts: 10 POSITIVE, 16 HARD_NEGATIVE, 18 EDGE.

## 3. Assertions
A case passes when the component result equals `expected` on every listed key (extra keys allowed). Error codes are exactly 07 §2 codes; transition IDs exactly 03 §11. `security_event: true` requires a log line `security.cross_tenant_ref` with the caller's `org_id` and no content. Integration-level cases (JF-35, JF-38…JF-44) also run against real PostgreSQL with RLS in `tests/integration/orchestrator/`.

## 4. Thresholds
100 % of cases must pass; any failure blocks the PR. Runs on every CI run (free, offline; 27 §8.3). JF-38, JF-39, JF-44 are also in the `security` / `tenancy` marker suites (08 §8.2).

## 5. Open points
- JF-22 depends on the CCR for approval revision targets (blueprint §18.3 item 2); until it is applied the provisional target list of blueprint §6.2 is used.
- JF-07 / JF-09 use `PERMANENT.CONFIG_INVALID` for a missing budget / non-enabled production type; if the integrator prefers another existing 07 code, the expectation changes by CCR, not locally.
