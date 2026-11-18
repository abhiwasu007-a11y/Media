# 27 — Engineering, Prompt and Evaluation Standards

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 01 (shared library `amw_core`, CI); S6 Security & Audit (→ 16) for the security gates |
| Depends on | SOURCE_LAYOUT.md, GLOSSARY_AND_IDS.md, 03_COMMUNICATION_STANDARD.md, 04_DATABASE_ARCHITECTURE.md (§3.7 tenancy tests), 07_FAILURE_MANAGEMENT.md (§3 `agent_parse`, §12 failure tests), 24_PRODUCTION_TYPES.md (§7.1), prompts/README.md, evals/README.md, RESEARCH_LOG.md (INF-04, INF-05, INF-06) |
| Directive sections covered | §3.5.1–§3.5.7 (prompt template, structured output, golden datasets, no paid calls, code standards, backlog, walking skeleton); §3.3 (shared library, observability, AI providers config); rules 5, 7, 8 |
| Tier | All **MVP (Tier 0)**: these standards apply from the first ticket. |

---

## 1. Scope
Binding for every line of production code, prompt, eval set, migration and CI job of AMW AI Media Factory. A ticket that does not meet §10 is not done.

## 2. Language and runtime
| Item | Standard | Status |
|---|---|---|
| Language | Python for backend, agents, workers (§3.2a) | decided |
| Version pin | One exact CPython minor version for the whole workspace: `requires-python` in `pyproject.toml` pins `==3.X.*`; the same minor in the container base image and in CI | rule decided |
| Which minor | Selection rule: the newest CPython minor in **bugfix** support at build start that every pinned dependency supports; floor **3.11** (PgQueuer requires ≥ 3.11, INF-06; Procrastinate ≥ 3.10, INF-05). **REQUIRES REVIEW (Phase 1): read the official CPython release-status page and record the chosen minor and its end-of-support date in RESEARCH_LOG.md (python.org hosts were blocked in this session).** | value pending |
| Why pin | Reproducible builds; identical behaviour across the shared VPS, a future render worker and CI (§3.3 Migration) | — |
| Upgrade | One minor at a time, by ticket, with the full CI suite and the eval sets green | — |
| Dashboard | TypeScript only if ADR-004 chooses Next.js; then `strict: true`, ESLint, typed API client generated from the FastAPI schema | depends on ADR-004 |

## 3. Toolchain and dependencies
| Concern | Standard |
|---|---|
| Lint + format | `ruff check` and `ruff format` (one tool, one config in `pyproject.toml`); CI fails on any finding |
| Types | `mypy --strict` on every package; no `Any` in public signatures; `# type: ignore` only with an error code and a reason comment |
| Tests | `pytest`; markers `unit`, `contract`, `integration`, `e2e`, `failure_injection`, `security`, `performance`, `tenancy`, `live` (opt-in, §8.4) |
| Coverage floors (line + branch) | `amw_core` ≥ 90 %; `amw_core.state_machine` and `amw_core.tenancy`: every transition row of 03 §11.3/§11.5 and every invalid sample pair tested (100 % of rows), every table in the 04 §3.7 suite; agents, services, adapters ≥ 80 %; CI fails below the floor |
| Pre-commit | ruff, ruff-format, mypy (changed packages), JSON Schema check of `contracts/schemas/**`, prompt lint (§4.4), secret scan, large-file guard, end-of-file/whitespace fixers |
| Commits | Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, `ci:`; scope = package, e.g. `feat(agent_06): …`); a CI check rejects non-conforming PR titles |
| Dependency pinning | One lock file for the workspace; exact versions; hashes where the tool supports them; upgrades by ticket with changelog review |
| Tool choices pending | Package/lock manager, migration runner (04 §8), UUIDv7 generator (GLOSSARY §2.1), JSON Schema validator, secret/dependency/container scanners (08): **REQUIRES REVIEW (Phase 1): record each choice with version and licence in RESEARCH_LOG.md before ticket 1** |

## 4. Prompt standard (§3.5.1)
### 4.1 File and naming
`prompts/<agent package>/<task>.v<N>.md` (in this phase `docs/v4/prompts/…`, plan Q3). Package names: §7.2. Prompt ID `<agent_id>/<task>.v<N>`. A released version is immutable; any change is `v<N+1>` and triggers the eval gate (§5).

### 4.2 Mandatory sections, in this order (template: `prompts/_TEMPLATE.v1.md`)
1. Header table (metadata: prompt ID, task type, status, input/output payload schema names and versions, rule packs injected, eval path, config keys)
2. `## Role`
3. `## Objective`
4. `## Inputs` — every runtime variable `{{name}}` with type and source; the step's input JSON Schema 2020-12 (`<task_type>.<step>.input`, GLOSSARY §2.4) is defined in the blueprint §7 and eval inputs are validated against it (CCR-018)
5. `## Rules` — numbered; compliance rule packs injected **by reference** `{{rule_pack:<key>}}` (resolved at runtime from `rule_packs`, version recorded per call); never pasted
6. `## Output JSON Schema` — JSON Schema 2020-12, identical to the step's Pydantic output model (§4.4 check)
7. `## Worked examples` — 2–3, each a full input and the exact valid output
8. `## Refusal and escalation` — when and how to return the refusal object (§4.3)
9. `## Self-check` — list the model must verify before answering

Model, temperature, max output tokens, timeout, cost budget, prompt-caching and batch eligibility are configuration, never in the file or in code: keys `llm.<task_type>.model_tier`, `.temperature`, `.max_output_tokens`, `.timeout_ms`, `.cost_budget_micros`, `.cache_system_prompt`, `.batch_eligible`, and `.fallback_tier` (optional). A task type with more than one LLM step uses one family per step, `llm.<task_type>.<step>.*` (same suffixes; CCR-019); a change to either form triggers the eval gate (§5). Tiers are `llm_model_tier` values (`SMALL` · `MID` · `TOP`, GLOSSARY §6.52), resolved by `llm.tiers.<tier>.provider` / `llm.tiers.<tier>.model` (ADR-007). Config namespaces: 18 §13. **Prompt caching and tenancy (CCR-025):** the cached stable prefix holds only the prompt file's system text and **PLATFORM**-scope rule packs; **TENANT**-scope packs (e.g. `rp.tenant_brand_safety`) and every other tenant value are rendered after the cache breakpoint, so a cached prefix never contains tenant data (§3.3 AI providers: cheapest tier that passes the gate; caching; Batch API for non-urgent overnight work — prices **REQUIRES REVIEW (Phase 1): 09 / research wave 2**).

### 4.3 Refusal object (every LLM output schema includes it)
```json
"refusal": {
  "oneOf": [
    { "type": "null" },
    { "type": "object", "additionalProperties": false,
      "required": ["reason", "message", "missing_inputs", "violated_rule_ids"],
      "properties": {
        "reason": { "enum": ["INSUFFICIENT_INPUT", "RULE_WOULD_BE_BROKEN", "OUT_OF_SCOPE", "CONFLICTING_INSTRUCTIONS", "UNSAFE_CONTENT"] },
        "message": { "type": "string", "maxLength": 1000 },
        "missing_inputs": { "type": "array", "items": { "type": "string" } },
        "violated_rule_ids": { "type": "array", "items": { "type": "string", "pattern": "^[A-Z]{2,8}-R[0-9]{1,3}$" } } } }
  ]
}
```
Mapping by the step code (deterministic): `INSUFFICIENT_INPUT` → Task Output `FAILED` with `PERMANENT.INSUFFICIENT_INPUT` (07 §2; orchestrator re-plans upstream); `RULE_WOULD_BE_BROKEN` → `SUCCEEDED` with compliance verdict `BLOCKED` in the payload (03 §5.3.3); `OUT_OF_SCOPE`, `CONFLICTING_INSTRUCTIONS` → `FAILED` `PERMANENT.INPUT_INVALID` (L2); `UNSAFE_CONTENT` → `SUCCEEDED` with verdict `NEEDS_HUMAN_REVIEW` (L3 via S7).
**Declared item-level mapping (CCR-023).** A step that is not a compliance gate (its payload carries no compliance verdict), or a per-item step inside a deterministic cascade (e.g. one shot's candidate ranking), may instead map a refusal to a deterministic per-item fallback, provided that (1) the blueprint §18 declares the mapping per refusal reason and the task-level failure condition (when too many items degrade, the task still fails with the codes above); (2) each degraded item emits a validation result with verdict `WARN`, `blocking: false`, and the refusal's `violated_rule_ids` in `rule_id` / `message`; (3) `RULE_WOULD_BE_BROKEN` and `UNSAFE_CONTENT` items are surfaced to Agent 16 through those results; (4) a refusal never becomes a `PASS`. A refusal inside a verification step that must return one entry per input item returns that entry with its "not decided" status and reason `MODEL_REFUSED` (GLOSSARY §6.52) rather than dropping it.

### 4.4 Prompt lint (pre-commit + CI)
Sections present and ordered; every `{{variable}}` declared in Inputs and supplied by the step; the Output JSON Schema parses as 2020-12 and equals the schema generated from the Pydantic model; every worked example validates against it; no model names, provider names, API keys or prices in the file; no calendar dates or clock times in rules (owner rule C.4; operational time rules come from config); rule packs referenced, not pasted.

## 5. CI gates (all blocking on PRs to `main`)
| Gate | Runs | Fails when |
|---|---|---|
| Lint/format | always | any ruff finding |
| Types | always | any mypy error |
| Unit + contract tests | always | any failure; coverage below §3 floors |
| Contract compatibility | contracts changed | a MINOR/PATCH schema rejects any example of the previous version; a breaking change without MAJOR bump (03 §2) |
| State machine | always | a transition row of 03 §11 without a test; DB `state_transition_rules` seed differs from the doc table |
| Tenancy | always | any 04 §3.7 check fails; a table without ENABLE + FORCE RLS outside the GLOBAL allow-list |
| Migrations | migrations changed | migration not forward-only/transactional; table added without its policy |
| Failure injection | nightly + on `amw_core.retries`/adapter changes | any 07 §12 scenario fails |
| Prompt lint | prompts changed | §4.4 |
| Eval gate | a PR changes a prompt file, a model/config key `llm.<task_type>.*`, or a rule pack | the task's golden dataset falls below its pass thresholds (§6.3). Runs as a separate, budget-capped job (§8.3) |
| Security | always | secret found; dependency/container vulnerability above the threshold set in 08 |
| Commit convention | always | PR title not Conventional Commits |

## 6. Evaluation standard (§3.5.3)
### 6.1 Golden dataset
`evals/<agent package>/<task>/` (this phase `docs/v4/evals/…`), format defined in `evals/README.md` (CCR-024 extensions below): ≥ 20 cases per LLM step, including hard negatives, edge cases and **every** answer-key case of the directive that applies to the step (e.g. §1B.2 for `agent_06.claim_extraction`). Cases contain no real personal data and no other tenant's data.
Dataset format extensions (CCR-024; `evals/README.md` §2 is aligned by the eval-harness lane L9):
- **LLM-step datasets:** `input` validates against the step input schema (`<task_type>.<step>.input`) or the task input schema; an optional top-level `fixture` object carries test doubles (search results, passages) and is declared in the dataset README.
- **Deterministic executor datasets** (no LLM step, e.g. Agent 07 synthesis/master): `input = {"payload": <task_type>.input, "fixtures": {…}}`; CI validates `input.payload`.
- **Function-level deterministic datasets** (engines such as a timeline or chart-fact engine): folder `<package>/<engine>_core/`, field `function` names the pure function, `input` is its argument object, `judge_min` is omitted.
- **Case-ID prefixes:** the category prefixes (`AK-`, `HN-`, `EDGE-`/`MIX-`, `REF-`, `POS-`) or, in deterministic and component datasets, a component prefix `<COMP>-NN` (2–5 capitals, declared in the README); `category` always carries the `eval_case_category` value.
- Each dataset README states which directive answer-key cases apply, or "none apply" with the reason.

### 6.2 Assertions
1. Deterministic first: schema validity, required fields, exact-substring/offset checks, banned phrases, rule-pack violations expected/forbidden, lengths, verdict equality.
2. LLM judge second, for subjective quality only, with a written rubric (`rubric.md`) and integer scores; the judge prompt is itself versioned and regression-tested against a fixed calibration subset with human labels.
3. A case passes only if every deterministic assertion passes and the judge score meets the case's minimum.

### 6.3 Thresholds
Stated per dataset in its `README.md`/`thresholds` block; answer-key cases always require 100 %. Thresholds are configuration and recalibrated after the golden-sample pilot.

### 6.4 Run record (one JSON line per case per run, stored as an eval artefact)
`run_id` (`run_…`), `prompt_id`, `prompt_sha256`, `rule_pack_versions`, `config_key`, `provider`, `model` (resolved from config), `case_id`, `passed`, `assertions` (id → pass/fail + detail), `judge_scores`, `judge_prompt_id`, `tokens_in`, `tokens_out`, `tokens_cached_in`, `cost_micros`, `currency`, `latency_ms`, `started_at`, `figure_kind` (`ESTIMATE` until reconciled with provider usage). Cost and latency per case are mandatory (§3.5.3).

## 7. Code standards (§3.5.5)
### 7.1 Structure (SOURCE_LAYOUT.md)
- `amw_core` = the one shared library: contracts, state machine, retries, tenancy, audit, cost, config, queue, storage, observability, ids. It imports no other internal package.
- One package per agent and per shared service; each exposes a typed `Protocol` (its stage interface) and Pydantic models for its payload schemas; it imports only `amw_core` and adapter Protocols, never another agent (§2 of the directive: hand-offs only through contracts and the orchestrator).
- Adapters (LLM, TTS, image, video generation, stock, music, destinations) implement Protocols and ship with a fake and recorded fixtures.
- Only `workers/*` and `apps/*` wire concrete adapters (dependency injection via constructor parameters; no service locator, no globals).

Adapter request/response models (e.g. `LlmRequest`, `TtsRequest`, stock/music search and licence, image, video, delivery) are **adapter-owned** typed models in `amw_adapters/<family>/`, not Wave A contracts; they change with their adapter's tests and fakes, never with a CCR (CCR-057). What crosses an agent boundary is always a 03 contract or a payload schema.

### 7.2 Package names (also the `prompts/` and `evals/` folder names)
Agents: `agent_01_ceo_orchestrator` (code package `amw_orchestrator`), `agent_02_market_intelligence`, `agent_03_content_strategy`, `agent_04_research_knowledge`, `agent_05_scriptwriter`, `agent_06_fact_checker`, `agent_07_voice_production`, `agent_08_visual_assets`, `agent_09_video_director`, `agent_10_video_editor`, `agent_11_thumbnail_design`, `agent_12_seo_metadata`, `agent_13_publishing_delivery`, `agent_14_analytics`, `agent_15_growth_revenue`, `agent_16_compliance_qa`, `agent_17_brief_creative_strategy`.
Services: `s01_audience_intelligence`, `s02_uniqueness_auditor`, `s03_localisation_dubbing`, `s04_financial_controller`, `s05_infrastructure_intelligence`, `s06_security_audit`, `s07_human_approval`, `s08_command_center`, `s09_tenant_identity_access`, `s10_billing_metering`, `s11_client_portal`, `s12_integration_api`, `s13_community_comments`.

### 7.3 Rules
1. **Configuration** only through `amw_core.config` (pydantic-settings); no package reads environment variables directly; models, providers, limits, thresholds and windows are config, never literals (rule 5).
2. **Structured output** (§3.5.2): every LLM response is parsed into its Pydantic model; parse or schema failure = failed step (`AGENT.INVALID_JSON` / `AGENT.OUTPUT_SCHEMA_INVALID`), retried once with the validation error, then DLQ (07 §3.3 `agent_parse`). No "best effort" parsing, no regex extraction from free text.
3. **Tenancy**: every DB access goes through `amw_core.tenancy` (transaction with `SET LOCAL app.org_id`, 04 §3.2); every storage path through `amw_core.storage` (03 §8); every cache key built by `amw_core.tenancy.cache_key()` (GLOSSARY §2.4). Queries also filter `org_id` explicitly (§1C.1: RLS is the second line).
4. **Errors**: raise typed exceptions that map 1:1 to the 07 §2 codes; never swallow exceptions; never return partial outputs as success (03 §5.3).
5. **Side effects** only through adapters that take an idempotency key (03 §9).
6. **Logging**: structured JSON via `amw_core.observability`; fields `org_id`, `correlation_id`, `job_id`, `task_id`, `attempt_id`, `actor`; no secrets, tokens, knowledge-chunk text or personal data in logs.
7. **Determinism**: decisions marked deterministic in a blueprint are pure functions with unit tests; LLM judgements are isolated behind the step's Protocol.
8. **Time**: `timestamptz`/aware `datetime` in UTC only; zones only at display or for the operational rules of GLOSSARY §4.
9. **Money**: integers (`_minor`, `_micros`), never floats.

## 8. Testing rules (§3.5.4)
1. **No paid calls in tests.** The test runner blocks outbound network (socket guard) except for `live`-marked tests; adapters are exercised through fakes and recorded fixtures.
2. Recorded fixtures are redacted (no keys, tokens, personal data) and stored with the provider response schema version; a fixture refresh is a ticket.
3. The eval gate (§5) is not a unit test: it is a separate CI job with its own per-run budget cap (config `evals.max_run_cost_micros`), triggered only by prompt/model/rule-pack changes; deterministic assertions can be re-run offline on stored outputs at no cost.
4. **One opt-in live smoke test** per provider adapter, marker `live`, run manually or on release, with a hard budget cap (config `live_smoke.max_cost_micros`). Budget values and enabling any paid run need the owner's authorisation (rule 8): **REQUIRES REVIEW (Phase 1): owner sets the eval and smoke-test budget caps.**
5. Test categories required per agent blueprint section 21: unit, integration, contract, regression (eval), failure-injection, performance, security, E2E.

## 9. Walking skeleton (§3.5.7, amended by owner decision D1) — build ticket 1
**Definition (D1, 2026-11-18):** the thinnest end-to-end path through real components of the **3A production line**, before any agent is deepened:
owner-given topic → script → TTS → simple render → QC → approval → **downloadable delivery bundle** → audit/cost record.
**No YouTube upload and no Google OAuth in 3A.** The directive's original final step (private upload to a test channel) moves to the first Agent 13 ticket in 3C.

| Element | Real component used | Minimum behaviour |
|---|---|---|
| Tenancy | PostgreSQL with RLS, `amw_app` role, two orgs (platform owner + a synthetic test org) | cross-tenant suite (04 §3.7) green |
| Contracts + state machine | `amw_core.contracts`, `amw_core.state_machine`, trigger rules | every transition audited; invalid transition rejected |
| Queue | Postgres-backed queue per ADR-001 | claim with SKIP LOCKED, lease, reaper |
| Topic | entered directly by the owner (D1: Agents 02/03 come later) | stored as the job's topic input |
| Script | `agent_05.script_draft` minimal, one real LLM call through the adapter | Pydantic-validated output |
| TTS | `agent_07.voice_synthesis`, one real TTS call | audio stored write-once |
| Render | `agent_10.render` on the render worker: narration over a code-rendered title/chart card | `yt_master_1080p` container spec |
| QC | `agent_10.technical_qc`: ffprobe + `ebur128` (INF-09) | verdicts in `qc_results` |
| Approval | `svc_s07.request_approval` (one tap) + one editorial contribution + `agent_16.publication_authorisation` (deterministic checks only), here authorising **delivery** | guard exercised before the bundle is released |
| Delivery | `agent_13.file_delivery` (file destination only) | bundle: MP4, SRT, QC report, cost-per-stage report, downloadable |
| Records | `audit_log` chain verifies; `cost_ledger` rows for each paid call | export of both as JSON |
| Budget | cost ledger enforces a **per-video budget and a total pilot budget**; a breach stops new paid calls and suspends the job (`AWAITING_BUDGET`) | breach test passes |
| Isolation | factory containers under their slice/limits when run on the VPS | acceptance test reads the cgroup files (INF-04) |

Acceptance tests:
1. The full path produces one delivery bundle for an owner-given topic.
2. Kill the render worker mid-render: it resumes from the checkpoint and produces one output file.
3. Replaying the delivery task from the DLQ creates no second bundle (idempotency key `delivery.file`).
4. A budget breach stops further paid calls.
5. Tenant B sees none of tenant A's rows, blobs or logs.
6. No render starts during market hours when run on the VPS (D1).

Prerequisites: owner-set spending limits at each provider and keys through the environment's secret mechanism (A7, rule 8, D1). If run on the VPS: measured headroom (A1) and night window only.

## 10. Definition of done (per ticket)
A ticket is done only when **all** hold:
1. Acceptance tests named in the ticket exist and pass; no ticket without a test (§3.5.6).
2. All CI gates of §5 green; coverage floors met.
3. Migrations (if any) add RLS in the same file; tenancy suite green.
4. LLM steps: prompt file per §4, eval set per §6 at or above threshold, run record attached.
5. Observability: logs/metrics carry `org_id` and correlation fields; cost recorded for paid calls.
6. Errors map to 07 codes; side effects idempotent; no infinite loop possible (07 §9 caps).
7. No mock data, placeholder integration or simulated result presented as working (rule 7); fakes exist only in tests.
8. Feature status moved only with evidence (rule 7): `Implemented` = merged code; `Tested` = acceptance tests green; `Production Ready` = owner approval after pilot evidence.
9. Before/after evidence (screenshot, chart, media sample or log excerpt) attached to the PR for any user-visible or media change (owner rule A.12).
10. Self-review of the full diff before pushing (owner rule A.10); PR via a `claude/<name>` branch, Conventional Commits title; `IMPLEMENTATION_PROGRESS.md` updated (task ID, status, checks, open dependencies).
11. Documentation updated where behaviour differs from the blueprint, via `CONTRACT_CHANGE_REQUESTS.md` for contracts and `CHANGE_REQUESTS.md` after the baseline freeze (rule 11).
