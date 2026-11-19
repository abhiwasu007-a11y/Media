# 11 — Testing Strategy

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 01 (test harness, CI jobs, shared fixtures in `amw_core`); S6 Security & Audit (→ 16) for the security suite; each agent owns the tests of its blueprint section 21 |
| Depends on | 27_ENGINEERING_STANDARDS.md (§3 markers and coverage floors, §5 CI gates, §6 eval standard, §8 testing rules, §9 walking skeleton, §10 definition of done), 03_COMMUNICATION_STANDARD.md (§2–§7 schemas, §9 idempotency, §11 state machine), 04_DATABASE_ARCHITECTURE.md (§3.7 tenancy suite), 07_FAILURE_MANAGEMENT.md (§2 codes, §3 policies, §9 caps, §12 failure tests), 24_PRODUCTION_TYPES.md (§3.2 task types, QC profiles), GLOSSARY_AND_IDS.md (IDs, enums, FIN-R1…R13), 3A_SLICE_SPEC.md (§4 bundle, §5 budget, §10 golden samples, §14 tickets), 18_PRODUCTION_QUALITY_STANDARD.md (§7 QC, §9 rubric, §11 pilot), 13_COMPLIANCE_YOUTUBE_POLICY.md (§5.12, §5.13, §5.15), 09_COST_AND_BUDGET.md (§8.7 eval/smoke caps), 08_SECURITY.md (§8.2, §10), 05_RESOURCE_MANAGEMENT.md (RM-T1…T6), 06_NIGHT_SCHEDULING.md, ADR-001, ADR-007, ADR-008, ADR-009, ADR-012, KNOWLEDGE_LIBRARY_PLAN.md (§5), evals/README.md, RESEARCH_LOG.md (INF-04, INF-09, INF-10, PR-01…PR-03) |
| Directive sections covered | §3.5.3 (golden sets, thresholds, CI gate), §3.5.4 (no paid calls in tests; opt-in live smoke test), §3.5.6 (no ticket without a test), §3.5.7 (walking skeleton acceptance, as amended by D1); §1A.6 (QC self-test), §1A.10 (golden-sample pilot); §1C.1 (tenancy suite), §1C.13 (security gates); rules 5, 7, 8, 9 |
| Owner decisions applied | D1 (3A / 3B / 3C; paid calls only within owner-set limits; per-video and pilot budgets stop on breach; keys only via the environment secret mechanism; render never in market hours; no upload and no Google OAuth in 3A), D2 (fast track; no relaxation of any gate) |
| Scope marking | Each section carries **[3A / 3B / 3C · Tier n]**. Tier 0 is the owner's own tenant; Tier 1–3 items are listed as design hooks only (§15) and are built only when a paying client needs them (§1C.15). |
| "(CCR-NNN)" | A name this document needs that no contract defines, with its register number (CONTRACT_CHANGE_REQUESTS.md); none is invented here. |

---

## 1. Purpose and principles [3A · Tier 0]

This document says how every part of the factory is proven to work, without spending money in tests and without a gate that can be skipped. It does not change any standard of 27; it applies them and fixes what 27 leaves open (suite layout, when each suite runs, which evidence is attached).

1. **Nothing is "Tested" without evidence** (rule 7; 27 §10 item 8). `Tested` = the named acceptance tests are green in CI and the run record is attached.
2. **No paid call in an automatic test** (27 §8.1). The only paid runs are (a) the eval gate (§9) and (b) the opt-in live smoke tests (§6), both under owner-set caps (rule 8).
3. **Every gate is blocking** unless this document or 27 says otherwise. A flaky test is a defect to fix, never a reason to re-run until green or to skip it (no retries of tests; a quarantine list does not exist).
4. **Deterministic first** (27 §6.2, §7.3 item 7). Decisions that a blueprint marks deterministic are tested as pure functions. Only subjective quality uses an LLM judge, and the judge is itself regression-tested.
5. **Tenant isolation is tested at every layer** (rule 9): database, storage, cache, logs, API, prompts.
6. **Test data is synthetic.** No real personal data, no other tenant's data, no book or course text, no private method, no server details (the repository is public). Media fixtures are generated (`lavfi`), not stored (18 §7.11).
7. **No date or clock time in a chart-reading or content test input** (owner rule C.4; evals/README.md §2). Time-based behaviour (night window, market hours, quota day) is an operational setting and is tested with an injectable clock (§4.4).
8. **Evidence, not numbers alone** (owner rule A.12): media and user-visible changes carry before/after evidence (contact sheet, loudness chart, QC table, screenshot) in the PR (27 §10 item 9).

---

## 2. Test pyramid [3A · Tier 0]

| Layer | Marker (27 §3) | What it proves | Real components | Runs | Network | Cost | Gate |
|---|---|---|---|---|---|---|---|
| L1 Unit | `unit` | pure functions, validators, deterministic decisions, schema models, retry maths, budget maths | none | every push, every PR | blocked (socket guard) | none | blocking |
| L2 Contract | `contract` | every message and payload validates against the 03 schemas; compatibility between versions | JSON Schema validator | every push | blocked | none | blocking |
| L3 Component / adapter | `unit` + recorded fixtures | each adapter against redacted recorded responses; each agent step behind its Protocol with the fake adapters | fakes + fixtures | every push | blocked | none | blocking |
| L4 Integration | `integration` | agent package + `amw_core` + real PostgreSQL (RLS, `amw_app` role) + the queue (ADR-001) | PostgreSQL, queue | every PR | blocked except to the test database | none | blocking |
| L5 Tenancy | `tenancy` | 04 §3.7 items 1–8 | PostgreSQL | every push | blocked except to the test database | none | blocking |
| L6 Failure injection | `failure_injection` | 07 §12 scenarios, hard caps, DLQ, breakers, kill/resume | PostgreSQL, queue, worker processes | nightly and on changes to `amw_core.retries`/adapters (27 §5) | blocked | none | blocking |
| L7 Security | `security` | 08 §8.2, §10 | PostgreSQL, scanners | every push (static), every PR (dynamic) | blocked | none | blocking |
| L8 Eval (golden sets) | not a unit test (27 §8.3) | LLM steps meet thresholds | real LLM adapter | only on prompt/model/rule-pack change | allowed to the provider only | **paid, capped** | blocking when triggered |
| L9 End-to-end | `e2e` | the 3A graph produces the bundle; 3B golden samples | everything except paid providers (fakes) in CI; real providers only in the owner-authorised runs | per release candidate (§12, §13) | CI: blocked | CI: none; owner runs: **paid, capped** | blocking |
| L10 Performance | `performance` | throughput, memory, disk, render time on the target slice | real FFmpeg, PostgreSQL | per wave and on the VPS window (§11) | blocked | none | measured in 3B; gate values pending |
| L11 Live smoke | `live` | one real call per provider adapter still works | the real provider | manual / release only | allowed to one provider | **paid, capped** | not a CI gate; release checklist |

Shape: many L1–L3, fewer L4–L7, a small number of L8–L9, two L10 scenarios, one L11 per adapter. Coverage floors (27 §3) apply to L1–L5 combined: `amw_core` ≥ 90 % line+branch; `amw_core.state_machine` and `amw_core.tenancy` 100 % of the 03 §11.3 / §11.5 rows and every table of the 04 §3.7 suite; agents, services and adapters ≥ 80 %.

Required categories per agent (27 §8.5; blueprint section 21): unit, integration, contract, regression (eval), failure-injection, performance, security, E2E. A blueprint that omits one must say why (for example, an agent with no LLM step has no eval).

---

## 3. Repository layout and conventions [3A · Tier 0]

Layout (names follow SOURCE_LAYOUT.md; folders only, no code here):
- `tests/unit/`, `tests/contract/`, `tests/integration/`, `tests/tenancy/` (the 04 §3.7 name), `tests/failure_injection/`, `tests/security/`, `tests/performance/`, `tests/e2e/`, `tests/live/`.
- Per-package tests live next to the package when the package owns them; cross-cutting suites live under `tests/`.
- `tests/fixtures/` holds: recorded provider responses (§5), JSON examples per schema version (§7), tenant fixtures (orgs A and B, §8). `tests/fixtures/` contains no generated media; media is generated at test time (§5.4).
- `evals/<agent package>/<task>/` holds the golden sets (evals/README.md).

Conventions:
| Rule | Detail |
|---|---|
| Marker per test | Exactly one primary marker from 27 §3; CI fails on an unmarked test |
| Socket guard | Installed for the whole session by a pytest plugin; only `live` tests and the eval job lift it, and only for the named provider host (27 §8.1). A test that opens a socket outside the allowance fails with a clear message |
| Clock | Time is injected (the `Clock` Protocol in `amw_core.interfaces`, as built) so night-window, market-hours, lease, backoff and quota-day tests never sleep and never depend on the wall clock |
| IDs and randomness | Seeded; UUIDv7 generator injectable (GLOSSARY §2.1) so snapshots are stable |
| Database | One PostgreSQL schema per test session created by the real forward-only migrations; a test never uses a hand-made schema (so a missing RLS policy cannot hide). Each test runs in a transaction or a fresh tenant pair; no test depends on another's rows |
| Parallelism | Tests are order-independent and run in parallel; tests that need exclusive resources (cgroup, real FFmpeg timing) carry the marker `performance` and run serially |
| Naming | `test_<unit>_<behaviour>`; failure tests name the 07 §2 code they prove; state-machine tests name the 03 §11.3 transition ID (T01…T20) |
| Secrets in tests | None. A canary secret string is generated per run for the leak tests (§10) and never reused |
| Reports | JUnit-style result + coverage + the run records of §9; artefacts kept for the retention set in CI config (REQUIRES REVIEW (Phase 1): retention period) |

---

## 4. Unit and component tests [3A · Tier 0]

### 4.1 What every package must unit-test
| Area | Examples (non-exhaustive) | Source |
|---|---|---|
| Contracts models | Pydantic model equals the generated JSON Schema; reject unknown fields where the schema forbids them; version fields | 03 §2–§5; 27 §4.4 |
| Idempotency | key construction per scope, request-hash comparison, `COMPLETED` same-hash hit returns the stored result (T04) | 03 §9 |
| Retries | backoff + jitter formula, per-policy ceilings, `retry_after_ms` honoured, never-retried list | 07 §3 |
| Hard caps | each cap of 07 §9 reached exactly once and the result is the table's disposition | 07 §9 |
| Budget maths | reservation / consumption / release, committed amount formula, breach stops, ESTIMATE vs VERIFIED, integers only (no floats) | 09 §3; 27 §7.3 item 9 |
| Deterministic gates | `agent_16.*` deterministic checks, FIN-R rules that are pattern or data-lag based, uniqueness parts (b) and (c) | 13; 3A_SLICE_SPEC §2.4 |
| QC checks | each `qc.*` check as a function of ffprobe/ebur128/detector output, including threshold edges | 18 §7 |
| Prompt lint | §4.4 rules of 27 on every prompt file | 27 §4.4 |
| Config | invalid or missing config yields `PERMANENT.CONFIG_INVALID`, never a default literal | 27 §7.3 item 1 |

### 4.2 Adapter conformance suite [3A · Tier 0]
One reusable conformance suite per adapter Protocol (`llm`, `tts`, `stock_footage`, `music`, `image`, `video_gen`, `destination`; 3A_SLICE_SPEC §2.3). The same cases run against the fake and against every recorded-fixture replay, so a fake cannot drift from the contract:
1. Success path returns the typed result and a cost record with integer micros and `figure_kind = ESTIMATE` until reconciled (09 §5–§6).
2. Provider error classes map to the 07 §2 codes (429, 5xx, timeout, auth, content refusal, malformed body).
3. The call carries its idempotency key; a repeat with the same key and request hash performs no second effect (03 §9).
4. No secret, token or prompt text appears in the adapter's log lines (§10).
5. A call is refused before any I/O when the provider budget row is missing or `DISABLED` (3A_SLICE_SPEC §5; 09 §8).
6. Resource limits: response size and timeout limits enforced (08 §10 items 6–7).

### 4.3 Agent step tests [3A · Tier 0]
Each agent step is tested behind its Protocol with the fake adapters: input document → output document, with the 03 §5.3 success rule (a step never returns partial output as success). LLM steps additionally: invalid JSON and schema-invalid output produce `AGENT.INVALID_JSON` / `AGENT.OUTPUT_SCHEMA_INVALID`, one repair attempt with the validation error, then DLQ (27 §7.3 item 2; 07 §3.3 `agent_parse`); a refusal object (27 §4.3) maps to its disposition.

### 4.4 Time-dependent behaviour [3A · Tier 0]
With the injected clock: `RETRY_WAIT` times outside the window shift to the next opening; no admission after the stop time; graceful stop; the PT-day quota reset; market-hours render guard (06 §; ADR-012; RM-T3). Tests use the configured calendar record (`night.market_hours.calendar`), never a literal time in the test body.

---

## 5. Fakes and recorded fixtures (no paid calls) [3A · Tier 0]

### 5.1 Rules (27 §7.1, §8.1–§8.2)
1. Every adapter ships with a **fake** (deterministic, in-process, configurable to fail) and **recorded fixtures** (real responses captured once, redacted).
2. Fakes exist **only in tests** (27 §10 item 7). Production wiring (`workers/*`, `apps/*`) never imports a fake; a static check in CI fails any import of a fake from non-test code. A fake output is never presented as a working feature (rule 7).
3. A fixture stores: the provider's response, the provider response-schema version, the capture tool and config version, a redaction note. No keys, tokens, account IDs, personal data, server addresses.
4. A fixture refresh is a ticket and a paid event: it is a `live` run under §6 caps, counted against the pilot budget (09 §8.7).
5. Fixture drift is detected, not guessed: the nightly job validates each fixture against the current adapter response model; a provider change surfaces in the live smoke test (§6), never silently.

### 5.2 Fake behaviours required
| Adapter | Fake must support |
|---|---|
| `llm` | scripted responses per prompt id; valid JSON; invalid JSON; schema-invalid JSON; refusal object; truncated output; token counts and cost micros; latency injection |
| `tts` | deterministic audio of the right duration for the text; per-segment checkpoints; mispronunciation dictionary hit/miss; consent-flag handling for a human-narration file |
| `stock_footage`, `music`, `image`, `video_gen` | licence record with every field 18 §2.2 requires; a record with a missing field (to prove the QC licence-completeness check, 18 §7.9) |
| `destination` (file delivery only in 3A) | write-once bundle, SHA-256 verification, interrupted write |
| all | 429 with `retry_after`, 5xx, timeout, connection reset, auth rejection, content refusal, malformed body (the inputs of 07 §2) |

### 5.3 Recorded fixture set per provider class [3A]
Success, each error class above, and one oversized or malformed body. The LLM fixtures include prompt-cache fields so cost maths is tested (PR-02 figures are inputs to the unit-price table, 09 §7, not copied here).

### 5.4 Generated media (no stored media) [3A]
The QC self-test fixtures of 18 §7.11 are generated with `lavfi` at test time: a clean file passing every sourced check, and one defect file per detector (true peak above limit, black segment, frozen segment, silence gap, A/V offset, wrong container/codec/bitrate, subtitle desync, missing licence field). The self-test runs on the **pinned FFmpeg build** (INF-09 filters) and is part of the 3B entry conditions (18 §11). A different FFmpeg build re-runs it before use.

---

## 6. Opt-in live smoke tests with a hard budget cap [3A / 3B · Tier 0]

Basis: 27 §8.4; 09 §8.7; 08 §3.4, §10 rule 2; ADR-007, ADR-008.

| Item | Rule |
|---|---|
| Scope | **One** smoke test per live provider adapter (3A: `llm`, `tts`; `stock_footage` only if the owner buys a licence; `music`, `image` have no live adapter in 3A, 3A_SLICE_SPEC §2.3). Marker `live` |
| What it checks | The adapter still talks to the provider: smallest possible request, response parses into the adapter's model, cost record is produced, idempotent repeat performs no second billable effect where the provider allows it to be proven. It does not judge content quality (that is §9) |
| When it runs | Manually, or on release (27 §8.4). Never on push or PR. Never on a schedule that the owner has not authorised |
| Who may enable it | Only after the owner has set spending limits at the provider and the keys exist through the environment's secret mechanism (D1; rule 8; 08 §3.4). The `PROVIDER` budget row (3A_SLICE_SPEC §5; GLOSSARY §6.45, CCR-035) must be `ACTIVE`; otherwise the test refuses before I/O |
| Hard cap | `live_smoke.max_cost_micros` (config key named in 27 §8.4). **REQUIRES REVIEW (Phase 1): owner sets the smoke-test cap per provider.** No default above zero: with no value the test is skipped, not run |
| Enforcement | The cap is enforced by the cost ledger (reservation before the call), not by trusting the test: a call whose reservation would exceed the cap is refused and the test fails with `RESOURCE.BUDGET_EXHAUSTED` semantics. Spend counts against the pilot budget unless the owner states otherwise (09 §8.7) |
| Keys | CI never holds production keys; the smoke job uses a limit-capped key available only to a manually triggered, non-fork workflow (08 §10 rule 2). Keys are never printed; the log scan of §10 runs on the job output |
| Output | A run record (cost, latency, adapter, config version). A failure opens a ticket; it does not block unrelated merges but blocks a release |
| Fixtures | A passing smoke run may be used, under a ticket, to refresh the recorded fixtures of §5 |

---

## 7. Contract tests against the 03 schemas [3A · Tier 0]

Source of truth: `contracts/schemas/**` generated from the 03 definitions (`amw.common`, `amw.task_input`, `amw.envelope`, `amw.task_output`, `amw.error`, `amw.control`). Tests never redefine a schema.

| # | Test | Rule |
|---|---|---|
| C1 | Every example document in `tests/fixtures/` validates against its schema version | 03 §2 |
| C2 | Every Pydantic model equals its generated JSON Schema (no hand-edited schema) | 27 §4.4 |
| C3 | Compatibility: a MINOR/PATCH schema must accept every example of the previous version; a breaking change without a MAJOR bump fails | 03 §2.2–§2.3; 27 §5 "Contract compatibility" |
| C4 | Negative corpus per schema: missing required field, wrong ID prefix, wrong enum value, unknown field, bad version → rejected with `PERMANENT.SCHEMA_INVALID` / `PERMANENT.SCHEMA_VERSION_UNSUPPORTED` / `PERMANENT.INPUT_INVALID` as the 03 §7 order dictates | 03 §6–§7 |
| C5 | Receiver validation order of 03 §7.1 is exercised: schema, version, tenant (`org_id` agreement across envelope, input and refs), storage URI, idempotency, then budget (T03). Structured rejection (03 §7.2) is stored, not dropped | 03 §7 |
| C6 | Task Output success rule (03 §5.3): `SUCCEEDED` with a missing required output, a failed blob verification or an advisory field misused is rejected | 03 §5.3 |
| C7 | Per task type of 24 §3.2 used in 3A (`agent_04.research_pack`, `agent_05.script_draft`, `agent_05.shorts_adaptation`, `agent_06.claim_extraction`, `agent_06.claim_verification`, `agent_07.voice_synthesis`, `agent_07.audio_master`, `agent_08.asset_sourcing`, `agent_09.shot_plan`, `agent_10.render`, `agent_10.subtitles`, `agent_10.technical_qc`, `agent_11.thumbnail_variants`, `svc_s02.uniqueness_check`, `agent_16.compliance_gate`, `agent_16.quality_score`, `agent_16.publication_authorisation`, `svc_s07.request_approval`, `agent_13.file_delivery`): its input and output payload schemas exist, the producer's output validates as the consumer's input (producer/consumer pairs of the 3A graph, 3A_SLICE_SPEC §3). `agent_04.knowledge_ingest` joins this list when its CCR is applied | 24 §3.2; 3A_SLICE_SPEC §2.4 |
| C8 | Production-type registry: `CHANNEL_LONG_FORM` and `SHORTS` task graphs load, are DAGs, contain no task type outside 24 §3.2, and revision edges are bounded counters (07 §9 structural guarantees) | 24 §3; 24 §7.1a, §7.2a (CCR-003); 3A_SLICE_SPEC §14 (3A-03) |
| C9 | Storage references: only tenant-scoped URIs of 03 §8 validate; the delivery-area URI `jobs/<job>/deliveries/<pub>/` also validates (CCR-017) | 03 §8 |
| C10 | Enum parity: every enum in code equals GLOSSARY_AND_IDS.md (a generated check, CI fails on drift) | GLOSSARY |
| C11 | Prompt/schema parity: each prompt's Output JSON Schema equals the Pydantic model; each worked example validates | 27 §4.4 |
| C12 | Delivery bundle files (`qc_report`, `cost_per_stage_report`, `delivery_manifest`; 24 §4, CCR-043) validate against their schemas once defined | 3A_SLICE_SPEC §4 |

State-machine contract (the 27 §5 "State machine" gate, always on):
1. One test per transition row **T01…T20** of 03 §11.3 (guard true → allowed and audited with the named audit event; guard false → `PERMANENT.INVALID_TRANSITION`).
2. A generated "every other pair" test: every (from, to) pair not in the table is rejected and logs `state_machine.invalid_transition_rejected`.
3. The seeded `state_transition_rules` table equals the document table (CI fails on any difference).
4. Optimistic-locking: two concurrent transitions on the same `state_version` produce one winner and `TEMPORARY.LOCK_CONFLICT` for the other, re-evaluated at most `caps.lock_conflict_reevaluations` times (03 §11.4; 07 §9).
5. Job-level derived state (03 §11.5) tested for every job outcome used in 3A (including `DELIVERED`).
6. Approval waits: `CHECKPOINTED` + `wait_reason = AWAITING_APPROVAL` has no timeout by default and resumes only through `QUEUED` (T15; 03 §11.6).

---

## 8. Tenancy suite [3A · Tier 0 (blocking gate)]

Source: 04 §3.7 (the exact list), 08 §8.2, 27 §5 "Tenancy". This section adds only how it is run.

| 04 §3.7 item | Test (marker `tenancy`) | Notes |
|---|---|---|
| 1 | Fixtures: orgs A and B with rows in **every** TENANT and SHARED-CATALOGUE table | Generated from the 04 §4 table catalogue, so a new table is covered automatically |
| 2 | As `amw_app` with `app.org_id = A`: SELECT returns no B rows; INSERT with `org_id = B` fails `WITH CHECK`; UPDATE/DELETE of B rows affect 0 rows | Per table, parametrised |
| 3 | `app.org_id` unset → 0 rows on every tenant table | |
| 4 | A tenant-composite FK from an A row to a B parent fails | |
| 5 | Tenant A cannot UPDATE/DELETE an `org_id IS NULL` catalogue row (platform rule packs non-removable) | `rule_packs`, `circuit_breakers` |
| 6 | Catalogue check over `pg_class` (`relrowsecurity` and `relforcerowsecurity`) for every table except the GLOBAL allow-list of 04 §4 | A new table without RLS fails CI |
| 7 | Each 04 §3.6 function returns no content columns | e.g. the platform operations summary |
| 8 | Storage URI, cache key and log record of org B are rejected/absent in org A's context | see §10 for the extended list |

Additions required by 08 §8.2 and 27 §7.3 item 3 (tests in the same suite):
1. **API existence oracle:** a user of org A asking for org B's job, asset or audit entry by ID gets not-found (not forbidden); the attempt is logged as a permission/cross-tenant event. (3C for the API surface; the data-layer part runs in 3A.)
2. **Storage:** a task in org A given a URI of org B is rejected before any read (03 §8; `CrossTenantRef`).
3. **Cache:** a key not built by `amw_core.tenancy.cache_key()` is rejected; a poisoned entry of org B is not returned to A (GLOSSARY §2.4).
4. **Task chain:** `org_id` disagreement between envelope, input and refs → `TenantMismatch` before any work (03 §7.1; agent blueprints section 19).
5. **Retrieval:** per agent that reads knowledge or memory (Agent 04: T-01…T-06 in its blueprint) a chunk whose `org_id`/`channel_id` differs after load is rejected (`CrossTenantRef`); restricted collections (KNOWLEDGE_LIBRARY_PLAN.md §5: `pd_books`, `owner_strategies_notes`, `owner_books`) are tested for the release-approval gate (`RELEASE_MISSING`, `RELEASE_NOT_APPROVED`, `NOT_METHOD_TOPIC`) with synthetic collections only.
6. **Worker context:** every query path goes through `amw_core.tenancy` (`SET LOCAL app.org_id`); a static check bans raw cursors outside it (08 §10 "Static analysis").
7. **Grant drift:** the `amw_app` role's privileges equal the 04 §3 / 08 §4.1 expectation; any difference fails.
8. **Two-tenant queue test:** RM-T6 (05): claim order follows the fair-share ordering and one org cannot hold all slots of a class (logic in 3A with the synthetic test org; exercise in 3C).

3A runs the suite with two orgs: the platform owner's org and a synthetic test org (27 §9 "Tenancy"). Tier 1+ (client orgs, SSO, API keys, IP allow-list) adds suites in §15; none is built before a paying client needs it.

---

## 9. Golden-set eval gates in CI [3A · Tier 0]

Basis: 27 §5 "Eval gate", §6; evals/README.md; 09 §8.7; ADR-007.

### 9.1 What exists per LLM step
`evals/<agent package>/<task>/` with `README.md` (scope, categories, assertions, thresholds, judge configuration), `cases.jsonl` (≥ 20 cases: ANSWER_KEY, HARD_NEGATIVE, EDGE, REFUSAL, POSITIVE) and `rubric.md` (integer scores with anchors). Every directive answer-key case that applies to the step is included. Current example: `evals/agent_06_fact_checker/claim_extraction` (evals/README.md §5). 3A LLM steps that need a dataset: `agent_04.research_pack`, `agent_05.script_draft`, `agent_05.shorts_adaptation`, `agent_06.claim_extraction`, `agent_06.claim_verification`, `agent_09.shot_plan`, `agent_16.compliance_gate` (LLM part, if any), `agent_16.quality_score` (LLM-scored criteria), `agent_11.thumbnail_variants` (if an LLM step is used), `agent_07` pronunciation or text-prep steps if LLM-based. Whether a task has an LLM step is stated in its blueprint.

### 9.2 Three modes
| Mode | Trigger | Cost | Content |
|---|---|---|---|
| Offline, every CI run | always | none | schema-validate every case input against the step's input schema; re-run **deterministic assertions on the stored outputs** of the last accepted run; check that thresholds files and run-record schema are consistent |
| Online gate | a PR changes a prompt file, a `llm.<task_type>.*` config key, or an injected rule pack (27 §5) | **paid, capped** | each case once through the real adapter, then the step's deterministic post-checks, then assertions, then the judge |
| Calibration | after the 3B pilot, or when the judge prompt changes | paid, capped | judge regression on the fixed human-labelled calibration subset (27 §6.2 item 2) |

### 9.3 Pass/fail logic (27 §6.2–§6.3; evals/README.md §4)
1. A case passes only if every deterministic assertion passes and every judge criterion meets its minimum.
2. The dataset passes only if every threshold of its README is met. **Answer-key cases always require 100 %.**
3. Hard-negative and refusal categories have their own thresholds in the README, never averaged into positives.
4. Threshold values are configuration, recalibrated after the golden-sample pilot (27 §6.3; 18 §11 step 5). Until the pilot they are the draft values stated in each dataset README.

### 9.4 Budget and safety of the gate
1. Separate job with its own cap `evals.max_run_cost_micros` (27 §8.3). **REQUIRES REVIEW (Phase 1): owner sets the eval cap.** No value means the online gate does not run and the PR is blocked with a message (the gate fails closed, never passes silently).
2. The cap is enforced through the cost ledger reservation, as in §6. A breach stops the run, marks the gate failed, and writes the partial run record.
3. Eval spend counts against the pilot budget unless the owner states otherwise (09 §8.7).
4. Runs record `run_id`, `prompt_id`, `prompt_sha256`, `rule_pack_versions`, `config_key`, provider, model (resolved from config), case results, judge scores, tokens, `cost_micros`, `latency_ms`, `figure_kind = ESTIMATE` (27 §6.4). Cost and latency per case are mandatory.
5. A PR that changes only a prompt's wording still triggers the full dataset (no partial runs), so a "small" edit cannot slip through.
6. Model or provider changes (ADR-007 routing) trigger the gate for every task type that resolves to the changed key.
7. The judge is a different prompt from the generator and is versioned; a judge change triggers calibration.

### 9.5 Compliance evals (the highest-stakes set) [3A · Tier 0]
`agent_06` and `agent_16` datasets must contain, at 100 % required: the answer-key cases of 13 §5.12 (directive §1B.2), the Sathe-type cases of 13 §5.13 (hard negatives; FIN-R13), and one case per rule FIN-R1…FIN-R13 and YTG-R1…YTG-R8 that a gate evaluates. Each rule's deterministic checks are also unit tests (§4.1), so a rule regression is caught without any paid call. Evals required for the finance pack: 13 §5.15.

### 9.6 Prompt-injection and exfiltration cases [3A · Tier 0]
For every step that reads retrieved or external text: a case where the text instructs the agent to reveal another tenant's data, a secret, or to ignore its rules; expected outcome: refusal, no tool call, no content leakage (08 §8.2 item 6; 27 §4.3).

---

## 10. Security tests [3A · Tier 0]

Basis: 08 §8.2, §10; 27 §5 "Security". Marker `security` (and `tenancy` for the isolation items).

| # | Test | Gate |
|---|---|---|
| S1 | 04 §3.7 items 1–8 (§8) | blocking, always |
| S2 | Secret scan: pre-commit (staged diff) and CI (tree + PR range); scheduled full-history scan. Tool choices are recorded in RESEARCH_LOG.md before ticket 1 (08 §10 rule 1) — **REQUIRES REVIEW (Phase 1): choose scanners** | blocking |
| S3 | Dependency scan and container-image scan against the threshold (08 §10) — **REQUIRES REVIEW (Phase 1): threshold and exception expiry are an owner decision** | blocking |
| S4 | Lock-file integrity (install from lock only) and licence allow-list (08 §10) — **REQUIRES REVIEW (Phase 1): licence allow-list** | blocking |
| S5 | Static analysis rules: no raw cursors outside `amw_core.tenancy`; no `subprocess` with `shell=True` or unsanitised input; no `eval`/unsafe deserialisation; no logging of objects named `*token*` / `*secret*` | blocking |
| S6 | **Canary leak test:** a per-run canary secret and a canary org content string are injected through config, an adapter, a prompt and a knowledge chunk; the test then scans all log output, the audit log, error objects, the delivery bundle, run records and fixtures: none contains them (27 §7.3 item 6; 09 §12.3 item 5; 3A_SLICE_SPEC §4) | blocking |
| S7 | Role/permission matrix: one test per cell of 08 §5.2, denied cells included (3C for the UI/API roles; the data-layer roles in 3A) | blocking |
| S8 | Grant drift (08 §4.1) | blocking |
| S9 | Media input safety: oversized, over-long, mis-typed and malformed media is rejected before render; FFmpeg is invoked with bounded resources, without network, and never through a shell with a filename (08 §10 rule 6). Limits: **REQUIRES REVIEW (Phase 1)** in 08 | blocking |
| S10 | External fetch adapter: allow-list per task type, redirect and size limits, block on private/loopback addresses (SSRF) (08 §10 rule 7) | blocking |
| S11 | Audit chain: `audit_log` hash chain verifies; a tampered row or deleted row is detected (08 §9.3; 3A_SLICE_SPEC acceptance of walking skeleton "Records") | blocking |
| S12 | Publish guard: delivery without approval, without an editorial contribution, or for a render hash different from the approved one is refused by the database trigger (04 §5.21) and by `agent_16.publication_authorisation` | blocking |
| S13 | No upload and no OAuth in 3A: a test asserts that no `agent_13.upload_private`, `agent_13.publish`, `agent_13.verify_publication` task can be created in the 3A registry and that no Google OAuth client or token path is reachable (D1) | blocking in 3A |
| S14 | Container hardening checks against the built image (non-root, no privileged mode, no baked-in secrets) (08 §10 rule 5) | blocking for images CI builds |
| S15 | Forked PRs never receive secrets (workflow review, 08 §10 rule 2) | review item, checked on every CI-config change |

Security assurance beyond tests (external review, penetration test) is Tier 2–3 and out of this document (08 §13, §15 below).

---

## 11. Failure-injection tests [3A · Tier 0]

Basis: 07 §12 (the list is binding), 07 §2–§11, 27 §5 ("nightly + on `amw_core.retries`/adapter changes"). Marker `failure_injection`. The harness injects at the adapter, database, queue, process and clock boundaries; it never edits production code paths.

| # | Scenario | Expected result | Source |
|---|---|---|---|
| F1 | One test **per error code** of the 07 §2 catalogue: inject, assert the stated disposition (RETRY / SUSPEND / FAIL / DLQ), retry policy, breaker count and escalation level | each code proves its row | 07 §2, §12 |
| F2 | Retry maths and ceilings per policy (`temporary`, `rate_limited`, `db`, `resource`, `agent`, `agent_parse`, `infra`, `publish_resume`): attempts never exceed `max_attempts`; `retry_after_ms` honoured; jitter within bounds | | 07 §3 |
| F3 | Never-retried codes are never retried | | 07 §3.4 |
| F4 | Circuit breaker: closed → open → half-open → closed; open breaker keeps the task in `RETRY_WAIT` without consuming an attempt (T12) | | 07 §4 |
| F5 | DLQ: exhausted task reaches `DEAD_LETTER` (T14) with payload ref, reason, retry history; controlled replay needs `dlq.replay` and `REPLAY_APPROVED`; replay creates no duplicate effect (T17; `max_replays_per_item`) | | 07 §5 |
| F6 | **Kill during render:** kill the render worker mid-render; reaper detects the lost lease; the new attempt resumes from the checkpoint; exactly one output file; no corrupt file; file hash equals the checksum recorded | 27 §9 acceptance 2; 3A-10 | 07 §10, §12 |
| F7 | **Kill during multi-segment TTS or batch LLM:** resume skips completed effects (`completed_effects`); no second paid call for a completed segment (cost ledger row count unchanged) | | 07 §10, §11 |
| F8 | **Kill during delivery:** replay of `agent_13.file_delivery` from the DLQ creates no second bundle (idempotency scope `delivery.file`; one `publications` row per delivered file) | 27 §9 acceptance 3 | 07 §11; 3A_SLICE_SPEC §4 |
| F9 | Orchestrator restart between transactions resumes from the database; completed tasks are not re-run; a crashed worker affects only its claimed tasks | | 07 §10 |
| F10 | Stuck-job detection: lease expiry, no-heartbeat, max active time (`limits.max_job_active_ms`, excluding `CHECKPOINTED` time) → reaper escalation L2 then L3 | | 07 §6–§7, §9 |
| F11 | Every hard cap of 07 §9 reached once: `max_attempts_per_task`, `max_revision_loops` (job ends `BLOCKED_COMPLIANCE` / L3), `max_tasks_per_job`, `max_child_jobs_per_job`, `max_replays_per_item`, LLM call cap, cost cap, lock-conflict re-evaluations | each → the table's disposition, never an endless loop | 07 §9 |
| F12 | **Budget breach:** per-video budget and pilot budget; the breach suspends (`CHECKPOINTED` + `AWAITING_BUDGET`, `RESOURCE.BUDGET_EXHAUSTED`), no retry, no new paid call, completed work kept; resume only after the owner raises the limit | 27 §9 acceptance 4 | 3A_SLICE_SPEC §5; 09 §4 |
| F13 | Missing or `DISABLED` provider limit row: every paid call refused before I/O (start gate) | | 3A_SLICE_SPEC §5; 09 §8 |
| F14 | Night window: drain at a simulated stop of admission and graceful stop at window end; `DRAIN` tasks resume (T15) only when the window opens and admission allows; `RETRY_WAIT` times outside the window shift to the next opening | | 07 §8; RM-T3 |
| F15 | **Market-hours guard:** a claim of a render task inside market hours returns no rows on every placement; a render whose estimated remaining time passes the stop time is not admitted after the admission stop (D1; ADR-012; RM-T3; 27 §9 acceptance 6) | | 05; 06 |
| F16 | Resource: injected `RESOURCE.OOM` lowers the worker type's concurrency by one and restores it next window (RM-T4); disk below minimum blocks `HEAVY_CPU` claims but not `LIGHT` (RM-T5) | | 05 §6.4, §6.6 |
| F17 | Database transient failure and queue outage: retried under `db` / `infra` policies; no message silently dropped (no silently dropped jobs, rule 5) | | 07 §2 |
| F18 | Duplicate delivery of the same message: `message_receipts` dedupe; the second delivery has no effect | | 04 §5.5; 03 §9 |
| F19 | Storage write failure and half-written blob: write-once blobs are verified by hash before a task is `COMPLETED` (03 §5.3) | | 03 §8 |
| F20 | Cancel during run: worker stops at a safe point; no mid-write cancel (T20) | | 03 §11.3 |

Observability checks inside the same suite (07 §12): every failure log line carries `org_id`, `correlation_id`, `job_id`, `task_id`, `attempt_id`, `error_code`, `error_class`; metrics labelled `org_id`, `agent_id`, `error_code` are emitted.

---

## 12. End-to-end tests: the 3A bundle [3A · Tier 0]

Basis: 27 §9 (walking skeleton and its six acceptance tests), 3A_SLICE_SPEC §3, §4, §14 (3A-01, 3A-14, 3A-16), 18 §7.

### 12.1 Two modes
| Mode | Providers | Runs where | Cost | Purpose |
|---|---|---|---|---|
| **E2E-CI** | all fakes + generated media | CI (per release candidate and nightly) | none | full graph, state machine, tenancy, idempotency, budget, QC on generated media; proves the line holds together without spending |
| **E2E-LIVE** | real LLM and TTS adapters, real FFmpeg | development environment, or the VPS night window after the owner's approval | **paid, within owner-set limits** | the real walking skeleton and the 3A-16 acceptance with an owner-given topic |

E2E-LIVE starts only when all of these hold (D1; 27 §9 prerequisites): owner-set spending limits at each provider; keys through the environment secret mechanism; per-video and pilot budgets configured with the `PROVIDER` rows `ACTIVE`; on the VPS, measured headroom (audit A1) and the night window only; render never in market hours. A missing precondition makes the run refuse to start; it is not skipped silently.

### 12.2 The six acceptance tests of 27 §9, restated as E2E tests
| # | Acceptance test | CI mode | Live mode |
|---|---|---|---|
| E1 | The full path produces one delivery bundle for an owner-given topic | yes (fake topic text is synthetic) | yes |
| E2 | Kill the render worker mid-render: resumes from the checkpoint, one output file | yes (F6) | yes, once |
| E3 | Replaying the delivery task from the DLQ creates no second bundle | yes (F8) | optional |
| E4 | A budget breach stops further paid calls | yes (F12) | yes, with a deliberately low per-video cap on a short topic |
| E5 | Tenant B sees none of tenant A's rows, blobs or logs | yes (§8, §10 S6) | yes |
| E6 | No render starts during market hours when run on the VPS | yes (F15) | VPS only |
| E7 | Isolation: acceptance reads the cgroup files for slice placement and limits (RM-T1; INF-04 is PARTIAL, so this is a real test, not an assumption) | no | VPS only, owner-approved |

### 12.3 Bundle verification (the 3A deliverable) [3A]
The bundle of 3A_SLICE_SPEC §4 is checked by an automated verifier used by E1 and by 3A-14:
1. All seven items exist when applicable: 16:9 MP4, 9:16 MP4 (when a Shorts child job ran), 3 thumbnail variants, SRT (one language in the MVP), QC report with the 100-point score, cost-per-stage report, manifest.
2. Manifest lists every file with SHA-256 and size; recomputed hashes match; one `publications` row per delivered file with `destination_kind = FILE_DELIVERY` and the approved render SHA-256.
3. The bundle exists only after `agent_16.publication_authorisation` returned `ALLOWED` for the same render SHA-256 that the owner approved at `FINAL_VIDEO` (publish guard S12).
4. The QC report shows every check with measured value vs threshold and PASS/WARN/FAIL/SKIPPED; compliance `BLOCKED` stops delivery whatever the score (3A-12); score ≥ `quality.publish_min_score` (85) is a delivery condition (18 §9).
5. The cost report follows 09 §12: header, per-stage table, budget status per limit, ESTIMATE/VERIFIED labels, **unknown values printed as REQUIRES REVIEW, never as zero**.
6. The bundle contains no keys, account IDs, server addresses or prompt text (09 §12.3 item 5); the canary scan of S6 runs over it.
7. The export of the `audit_log` chain and the `cost_ledger` rows as JSON verifies (27 §9 "Records").
8. Technical specification of each media file measured, not trusted: container, H.264 profile, resolution, frame rate (CFR), video bitrate against the directive target (INF-10 notes YouTube's own floor is lower), audio −14 LUFS / −1 dBTP / 48 kHz / AAC-LC ≥ 384 kbps, `faststart` (18 §5–§7; INF-09 filters).
9. The 3A flow records `SKIPPED` for the cross-video uniqueness part (no prior videos), and the verifier asserts it is recorded, not omitted (3A_SLICE_SPEC §2.4).

### 12.4 Negative end-to-end scenarios [3A]
Each is a complete graph run that must end in the stated state (CI mode):
| Scenario | Expected |
|---|---|
| Script containing a FIN-R1/R2/R3/R13 violation | blocked at `agent_06`/`agent_16`; no render of that script; revision loop bounded by 3 (07 §9) |
| Missing licence field on one shot | `qc.licence.*` FAIL; delivery refused |
| Loudness out of range after master | `agent_07.audio_master` revise loop; if unresolved → FAIL, no bundle |
| Owner rejects `FINAL_VIDEO` | job ends without delivery; reason recorded; no bundle |
| Owner approves but no editorial contribution recorded | publish guard refuses (S12) |
| Provider outage for the whole run | breaker opens, tasks wait under policy, no budget burn, DLQ if exhausted |
| Narration file without consent flag | refused by `agent_07` consent check |

---

## 13. 3B golden samples [3B · Tier 0]

Basis: 18 §11 (binding procedure), 3A_SLICE_SPEC §10, D1. The pilot is both the acceptance test of the production line and the calibration of every threshold. It is run by the owner on the real line (E2E-LIVE); this section defines what testing contributes.

### 13.1 Entry (all must hold; 18 §11)
1. Provider limits set; keys only through the environment secret mechanism.
2. Per-video and pilot budgets configured; breach stops the pilot (F12). Amounts: **REQUIRES REVIEW (Phase 1): owner inputs.**
3. Narration choice made and pronunciation dictionary v1 exists.
4. The QC self-test (§5.4, 18 §7.11) passes on the pinned FFmpeg build.
5. Rendering only in the development environment or the VPS night window; never in market hours.
6. The 3A E2E-CI suite and the full suite of §14 are green on the commit that is used.

### 13.2 Test content of the pilot
| Step | Test activity | Evidence |
|---|---|---|
| 1–2 | Three owner-given topics of different structure (for example a concept, a chart-reading walk-through, a risk/psychology piece); the full 3A graph to the QC report with no manual repair of media between stages | all `qc_results`, `quality_scores`, cost per stage |
| 3 | Owner scores each dimension (18 §9.2 human scores) at `FINAL_VIDEO` and records ≥ 1 editorial contribution | `quality_scores` HUMAN rows; `editorial_contributions` |
| 4 | Machine-vs-human comparison per dimension; list gaps ≥ the gap value (provisional ≥ 20 % of the dimension maximum; **REQUIRES REVIEW (Phase 1)**: owner/calibration) | calibration table |
| 5 | Tuning changes (prompts, templates, pronunciation dictionary, detector parameters, tolerances, point splits) each carry a before/after QC value and trigger the **eval gate** (§9) for any prompt or config key changed | change list |
| 6–7 | Re-run affected stages as new iterations (cap 3 per job); then re-run topics 1 and 2 on the tuned configuration as a **regression table** | new rows, never edits |
| 8 | Freeze the calibrated configuration as the baseline version; each later job records its config version | config snapshot ref |

### 13.3 Exit criteria (each of the three videos; 18 §11, 3A_SLICE_SPEC §10)
Human total ≥ 85; no compliance `BLOCKED`; no blocking QC FAIL; every check that was WARN-until-calibrated is either calibrated or kept advisory by the owner's decision; cost within the per-video budget; render and human-review figures recorded as MEASURED. If the revision loops run out, the pilot stops and the cause is reported.

### 13.4 After calibration
The three golden-sample videos become **regression fixtures**: their frozen inputs, configs and QC results are the baseline of the E2E-LIVE regression run before any later release that changes a prompt, template or detector parameter. (Media files stay outside git; the manifest and QC table are the fixture; no private method or course content is stored in this public repository.)
The evidence package per video (contact sheet, loudness-over-time and tier-mix charts, check table, cost per stage) is a PROPOSAL in 18 §11 and is produced for the owner's judgement.

---

## 14. Performance tests [3A / 3B · Tier 0]

No target is invented here. Targets are **MEASURED in 3B** (agent_04 NFR-7 sets the same rule) and then become gate values by a recorded config change. Until then performance tests run in measurement mode (record, do not fail), except the resource-limit safety checks, which fail hard.

| # | Test | What it measures | Fails when (now) | Source |
|---|---|---|---|---|
| P1 | Slice and limits are real | cgroup files on the VPS show the slice and per-container limits (RM-T1) | placement or limits not as designed | 05 §5.3; INF-03, INF-04 (PARTIAL) |
| P2 | Headroom formula | evaluate 00b §2.2 from the audit output (RM-T2) | formula negative → sizing stops | 05 §8; 00b |
| P3 | Render under limits | render time per minute of output, peak memory, peak CPU on the pinned FFmpeg at the target preset, run inside the container limits | OOM or limit breach (an OOM is a finding, not a retry) | ADR-012; 18 §6 |
| P4 | Disk | free space before and after one full job; scratch cleanup after completion; bundle size | disk below the minimum admission threshold (RM-T5) | 05 §6.4 |
| P5 | Queue throughput and claim latency | claim rate with N workers on the real PostgreSQL; `SKIP LOCKED` contention; `LISTEN/NOTIFY` wake-up latency | measurement only until baselined; correctness failures fail | ADR-001; INF-05, INF-06 |
| P6 | Database | transition latency under RLS (`SET LOCAL` per transaction); audit-chain write cost; partitioned `message_log`/`state_transitions` growth | measurement only until baselined | 04 §3.2, §5.5–§5.6 |
| P7 | Retrieval (Agent 04) | full-text retrieval latency on a synthetic library of realistic size; statement timeout enforced; retrieval does not block other queue tasks (P-01 in its blueprint) | timeout not enforced, or queue blocked | agent_04 blueprint NFR-7; ADR-013 |
| P8 | Pipeline end-to-end | wall-clock and cost per stage for the 16:9 job and the 9:16 child job (E2E-LIVE, owner-authorised) | measurement only; feeds 09 §9 cost-per-video formula | 09 §9, §12 |
| P9 | LLM call latency and tokens per task type | from the eval run records (27 §6.4); Devanagari token measurement feeds the unit-price table | measurement only | 09 §11 |
| P10 | Noisy neighbour | under a worst-case render, the co-located apps' headroom is not eroded beyond the measured margin (VPS, night window, owner-approved) | breach of the agreed margin | 05 §7; INF-03 |
| P11 | Soak (3B/3C) | a night's worth of queued synthetic jobs without leaks (memory, file handles, connections) | monotonic growth beyond a measured band | 05 |

Performance tests never run inside the market-hours guard and never on the shared VPS outside the owner-approved window (D1; rule 2 of the directive: read-only VPS commands until the owner approves an exercise). Absolute numbers (seconds, megabytes) are **REQUIRES REVIEW (Phase 1): set from the 3B measurements** and recorded in RESEARCH_LOG.md as MEASURED.

---

## 15. Enterprise tiers and later scope [Tier 1–3 · design hooks only]

Nothing below is built before a paying client needs it (§1C.15). It is listed so the 3A suites are written to extend, not to be rewritten.

| Tier | Additional test areas (when built) | Prepared by |
|---|---|---|
| Tier 0 | Everything in §§2–14 | this document |
| Tier 1 (client orgs) | Per-client isolation with real second tenants, client guest roles (08 §5.4), client portal and billing metering correctness (integer money, reconciliation), per-tenant caps and fair sharing (05 §7), tenant secret encryption and OAuth token handling (08 §6), YouTube upload/publish/verify tests with a private test channel and quota accounting (3C, Agent 13) | the tenancy generator of §8 covers new tables automatically; adapter conformance suite of §4.2 |
| Tier 2 | Load tests with many tenants, data-retention and deletion tests, backup/restore drills, brand-safety pack per tenant (13 §7) | performance harness P5–P11 |
| Tier 3 | SSO / SCIM, API keys and webhooks, IP allow-list (08 §7.2–§7.4); external penetration test and assurance path (08 §13) | security suite §10 |

3C items that need new test suites when their scope opens (each blueprint section 21 lists them): orchestrator hardening and scheduler (F10, F14, F15 exercised on the real schedule), Agent 13 publishing (upload resume, reconciliation after an unknown outcome, quota; 07 §11), Agent 14 analytics, Agents 02/03 strategy, tenancy UI, client portal, billing. The YouTube-specific tests are written against the official API pages (YT-01, YT-02, YT-04) when the Agent 13 blueprint is written; their fixtures are recorded under §5.

---

## 16. Execution schedule: "full suite once per wave" [3A / 3B / 3C · Tier 0]

| Trigger | Suites | Gate |
|---|---|---|
| Pre-commit (local) | ruff format/check, mypy on changed packages, schema JSON check, prompt lint, secret scan, large-file guard (27 §3) | blocking locally |
| Every push / PR | L1 unit, L2 contract, L3 component, L4 integration, L5 tenancy, L7 security (static + dynamic), state-machine gate, migrations gate, commit convention (27 §5) | blocking on PRs to `main` |
| Prompt, `llm.*` config or rule-pack change | online eval gate for the affected tasks (§9) | blocking; capped |
| Nightly | L6 failure injection, fixture-drift check, dependency/base-image freshness scan (08 §10), E2E-CI | opens a ticket on failure; a red nightly blocks the next merge to `main` until triaged |
| Release candidate | the full suite below | blocking |
| Manual / release | L11 live smoke per provider (§6), E2E-LIVE when owner-authorised | release checklist |
| VPS night window (owner-approved) | P1, P2, P3, P4, P10, E7 | owner reviews evidence |

**Full suite once per wave.** At the end of each wave the integrator runs, on one commit: every layer L1–L7, L9 (E2E-CI), the offline eval pass and, where the wave changed LLM steps, the online eval gate; L10 in measurement mode; and publishes the result table (suite, count, pass/fail, coverage vs floor, evidence links) in `IMPLEMENTATION_PROGRESS.md` (Tested = green evidence). A wave is not closed on a red or skipped suite.

| Wave | Content | Full-suite additions |
|---|---|---|
| 3A | 3A-01…3A-16 (3A_SLICE_SPEC §14) | The six 27 §9 acceptance tests on the full graph (§12); bundle verifier (§12.3); QC self-test; eval gates for 3A LLM steps; first E2E-LIVE with an owner topic after owner approval; VPS items P1–P4, E7 after audit A1 |
| 3B | three golden samples | §13 procedure; calibration; regression table; frozen baseline config; thresholds recalibrated (§9.3); performance baselines recorded as MEASURED |
| 3C | orchestrator hardening, scheduler, Agent 13, 14, 02/03, UI, portal, billing | the suites of §15 for the pieces built; full tenancy exercise with a second real tenant when one exists |

Per-ticket rule (27 §10): a ticket's own acceptance tests, all §5 CI gates and the coverage floors; no ticket without a test.

---

## 17. Definition of "tested" for status reporting [3A · Tier 0]

| Status word (rule 7) | Evidence required by this document |
|---|---|
| Implemented | merged code; unit and contract tests green |
| Tested | the ticket's acceptance tests, tenancy, security and (for LLM steps) the eval gate green; run records and before/after evidence attached; the wave's full suite green for the affected area |
| Production Ready | owner approval after 3B pilot evidence (§13.3); calibrated thresholds frozen; no open blocking item |

Fakes never raise a feature above Implemented; only runs through the real component in E2E-LIVE (or the real database, queue and FFmpeg in CI) count toward Tested for that component.

---

## 18. Open items [REQUIRES REVIEW (Phase 1)]

| # | Needed | Owner |
|---|---|---|
| O1 | Eval cap `evals.max_run_cost_micros` (per run) | owner (rule 8; 27 §8.4; 09 §8.7) |
| O2 | Smoke-test cap `live_smoke.max_cost_micros` per provider | owner (rule 8) |
| O3 | Per-video and pilot budget amounts | owner (D1) |
| O4 | Choice and versions of the test, secret-scan, dependency-scan, container-scan and JSON-Schema tools, recorded in RESEARCH_LOG.md before ticket 1 | integrator (27 §3 "Tool choices pending") |
| O5 | Dependency vulnerability threshold, exception expiry, licence allow-list | owner (08 §10) |
| O6 | CPython minor version (affects the CI matrix) | integrator (27 §2) |
| O7 | Absolute performance targets (render seconds per output minute, memory, claim latency) | from 3B measurements |
| O8 | Machine-vs-human gap value for calibration | owner / calibration (18 §11) |
| O9 | Detector thresholds for `qc.shorts` and the vertical edit values | 18 §14 |
| O10 | CI artefact retention period | integrator |
| O11 | Draft dataset thresholds per step (set in each dataset README; recalibrated after the pilot) | agent owners |

---

## 19. Contract change requests this document depends on

None is filed here. Names this document uses that were requested elsewhere are all applied: `PILOT_TOTAL` and `PROVIDER` budget scopes (CCR-035), `qc_report` / `cost_per_stage_report` / `delivery_manifest` (CCR-043), the delivery storage area (CCR-017), `CHANNEL_LONG_FORM` v2 / `SHORTS` v2 (CCR-003) and `agent_04.knowledge_ingest` (CCR-014). The `Clock` Protocol exists as built (`amw_core.interfaces.clock`); SOURCE_LAYOUT.md lists it (CCR-162).
