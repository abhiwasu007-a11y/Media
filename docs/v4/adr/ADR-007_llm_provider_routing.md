# ADR-007 — LLM provider adapter and model routing

| Field | Value |
|---|---|
| Status | **Proposed** (documentation). Software: **Planned**. |
| Date | 2026-11-18 |
| Directive | §3.2a (provider-independent adapters; Claude Code is for development, production AI calls use separately billed APIs), §3.3 AI providers, §0 rule 5 (no hard-coded keys/models/providers), rule 8 (no spend without the owner) |
| Owner decisions | D1 (spend controls, secrets), D2 |
| Contracts used | 03 (`resource_budget`, `resource_usage`), 04 §5.14 (`cost_ledger`, `budgets`, `budget_reservations`), 07 §2 / §4 (error codes, circuit breakers), 27 §4 / §7.3 / §8 (config keys, structured output, no paid calls in tests), SOURCE_LAYOUT (`amw_adapters/llm/`) |
| Research | PR-01, PR-02, PR-03 |
| MVP scope | **3A** (adapter, config routing, cost capture, budget stop) · **3B** (tier tuning against owner-scored golden samples, Devanagari token measurement) · **3C** (second provider, Batch for scheduled overnight work, per-tenant credentials) |
| Enterprise tier | Tier 0 for everything in 3A/3B. Tier 1+: per-tenant cost attribution already present (`org_id` on every ledger row); client-owned provider credentials as a `credential_scope` (07 §4.1). |

## 1. Context
- Every LLM step (Agents 04, 05, 06, 11, 16 in 3A; 02, 03, 12, 17 and S3/S13 later) calls a model. The directive forbids hard-coded models or providers (rule 5) and asks for "provider-independent adapters (Anthropic, OpenAI, others if justified) with model selection by config, token budgets, timeouts, rate limits, fallback and per-call cost tracking" (§3.3).
- Price spread is large. Official list prices (PR-01, VERIFIED 2026-11-18), USD per million tokens in / out: `claude-fable-5-2` 8 / 40; `claude-opus-5-5` 4 / 20; `claude-sonnet-5-5` 2 / 10; `claude-haiku-5-5` "from" 0.10 / 0.50, tiered by prompt length (exact tiers not extracted).
- Cost levers (PR-02, VERIFIED): Batch "50 percent discount on both input and output tokens"; cache write 1.25× (5-minute TTL) or 2× (1-hour TTL); cache read 0.1× generally, 0.05× on Opus 5.5 / Sonnet 5.5, 0.025× on Fable 5.2; the multipliers stack with Batch.
- Billing: "A paid Claude subscription enhances your chat experience, and the Claude API is billed separately" (PR-03, VERIFIED). Production calls need a separately billed API account (owner input A7).
- Devanagari text tokenizes heavier than English (§3.3); the factor for Marathi is **not measured** and no research entry gives it.
- D1: paid calls start only after the owner has set spending limits at each provider; the cost ledger enforces a per-video and a total pilot budget and stops on breach; keys only through the environment's secret mechanism.
- OpenAI facts are not recorded: `openai.com` was a blocked host in research wave 2 (RESEARCH_LOG, "Blocked vendor hosts").

## 2. Decision
1. **One adapter Protocol, many providers.** `amw_adapters/llm/` exposes a single `LlmAdapter` Protocol (complete, batch submit/poll, count tokens where the provider supports it). Agents import the Protocol only; workers wire the concrete adapter (SOURCE_LAYOUT rules 2–3). Every adapter ships with a fake and redacted recorded fixtures; tests never make paid calls (27 §8.1). One opt-in `live` smoke test per adapter, budget-capped (27 §8.4).
2. **First provider: Anthropic API** (only provider with VERIFIED prices in the log, PR-01/02). A second provider is added only when an ADR amendment shows a need (fallback availability, a measured quality gap, or price), with its facts recorded in the research log first.
3. **Model per task type, by configuration.** Routing reads `llm.<task_type>.model_tier`, `.temperature`, `.max_output_tokens`, `.timeout_ms`, `.cost_budget_micros`, `.cache_system_prompt`, `.batch_eligible` (27 §4.2). A separate config map resolves tier → provider + model ID (`llm.tiers.<tier>.provider`, `llm.tiers.<tier>.model`; pending CCR, same as below). Model IDs never appear in code or prompt files. Tier values `SMALL`, `MID`, `TOP` **(pending CCR: `llm_model_tier` value set)**.
4. **Cheapest tier that passes the gate.** Starting assignment (§3.3, PR-01 decision column), each to be confirmed by the task's eval gate (27 §5–6), never by opinion:

   | Starting tier | Model class (PR-01) | Typical 3A task types (24 §3.2) |
   |---|---|---|
   | `SMALL` | Haiku class | classification, SEO/metadata checks, QA checks, judge pre-screens inside `agent_16.compliance_gate` where only deterministic rules are not enough |
   | `MID` | Sonnet class | `agent_04.research_pack`, `agent_05.script_draft`, `agent_06.claim_extraction`, `agent_06.claim_verification`, `agent_11.thumbnail_variants` (text), `agent_16.quality_score` (LLM-judge part) |
   | `TOP` | Opus / Fable class | only a task whose golden set fails at `MID` and passes at `TOP` (measured) |

   Procedure (3B): run the task's golden dataset at the next cheaper tier; if all thresholds in 27 §6.3 pass, move down; a change of `model_tier` is a config change that triggers the eval gate (27 §5). LLM scores are never the only gate (§3.3 Quality); the human score wins on conflict (§1A.7).
5. **Prompt caching.** System prompts, the rule-pack text and channel context are placed in a stable prefix and cached when `.cache_system_prompt = true`. TTL class (5-minute vs 1-hour) is config; the 1-hour write costs 2× (PR-02), so it is used only where the measured reuse inside one hour pays for it.
6. **Batch.** Tasks with `.batch_eligible = true` and no interactive deadline go through the Batch API (PR-02: 50 % discount). In 3A runs are owner-triggered and short, so Batch is **off by default**; it is enabled per task type in 3C for scheduled night-window work. A batch result arriving after the task `deadline` fails with `PERMANENT.DEADLINE_EXCEEDED` (07 §2).
7. **Per-call cost capture.** Every call writes one `cost_ledger` row (04 §5.14): `provider`, `model` (resolved ID), `operation = llm.completion`, `billing_mode`, `tokens_in`, `tokens_out`, `tokens_cached_in`, `amount_micros`, `figure_kind = ESTIMATE` with `price_ref` (pricing config version), `idempotency_key` (scope `llm.call`). A later `VERIFIED` row from the provider usage export points to its estimate via `estimate_entry_id`; estimates are never overwritten. Cache-write tokens and the batch+cache combination need fields the ledger does not have **(pending CCR: `cost_ledger` cache-write and stacking fields)**. Task Output `resource_usage` carries the ledger IDs (03).
8. **Budget enforcement before the call.** The adapter wrapper asks S4 for a reservation against `resource_budget.max_cost_micros` (03 T03) and the per-video / pilot budget rows (D1); on refusal the task gets `RESOURCE.BUDGET_EXHAUSTED` → `CHECKPOINTED` / `AWAITING_BUDGET` (07 §2), no automatic budget increase (rule 8). The estimate uses `max_output_tokens` as the worst case. Provider-side spending limits set by the owner are the second line (D1).
9. **Devanagari token cost is measured, not assumed.** For every LLM call the ledger records tokens; the script/prompt character counts and language needed to compute tokens per character are **(pending CCR: `cost_ledger` character and language fields)**. 3B reports tokens and cost per stage per video for Marathi vs an English control prompt of the same content (§3.3), labelled MEASURED.
10. **Failure handling** uses existing codes only: 429 → `TEMPORARY.RATE_LIMITED` honouring `retry_after_ms`; 5xx → `TEMPORARY.UPSTREAM_5XX`; timeout → `TEMPORARY.TIMEOUT`; 401/403 → `PERMANENT.AUTH_INVALID`; safety refusal → `PERMANENT.PROVIDER_REFUSAL`; parse/schema failure → `AGENT.INVALID_JSON` / `AGENT.OUTPUT_SCHEMA_INVALID`, retried once with the error appended (27 §7.3). One breaker per `(provider, operation_class, credential_scope)` (07 §4). Fallback to another tier/provider happens only inside the attempt and only when configured (`llm.<task_type>.fallback_tier`, `llm.tiers.<tier>.*` **(pending CCR: config keys added to 27 §4.2)**); a fallback result must still pass the same eval-calibrated checks.
11. **Secrets.** API keys come only from the environment's secret mechanism through `amw_core.config` (D1, 27 §7.3); never in git, logs, fixtures or shared environment variables.

## 3. Options considered (with evidence)
| Option | Evidence | Verdict |
|---|---|---|
| A. Single hard-wired provider SDK in each agent | Violates rule 5 and §3.3 ("provider-independent adapters") | Rejected |
| B. One top model for every stage | PR-01: Opus 5.5 costs 2× Sonnet 5.5 and Fable 5.2 4× per token; no measured quality need | Rejected (cost without evidence) |
| C. **Adapter Protocol + config routing by tier + eval gate decides the tier** | §3.3 cost levers; PR-01 decision column; 27 §4.2 keys already exist | **Chosen** |
| D. Third-party multi-provider gateway / router service | Adds a hosted dependency and its own pricing; no research entry; §3.2a "simplest option … nothing is added just because it was suggested" | Rejected for now; revisit only with evidence |
| E. Use the owner's Claude subscription for production | PR-03: the API is billed separately; rule 5 | Rejected |
| F. Batch for everything | PR-02: 50 % off, but results are asynchronous; 3A runs are owner-triggered | Partial: per task type, 3C default |

## 4. Consequences
- Positive: model choice is a reviewed config change with an eval run, not a code change; per-call cost is visible per stage, per video and per tenant (`org_id`); provider swap needs a new adapter + fixtures only.
- Negative: every task type needs a golden dataset before its tier can be lowered (27 §6); until then it runs at its starting tier.
- 3A cannot make a paid call until A7 (API account, keys in the secret mechanism) and the owner's provider-side limits are in place (D1).
- REQUIRES REVIEW (Phase 1): exact Haiku 5.5 prompt-length price tiers (PR-01 not extracted); re-verify all prices if older than 30 days at the cost decision (RESEARCH_LOG, plan Q18).
- REQUIRES REVIEW (Phase 1): per-video and pilot budget values (owner, rule 8); eval and smoke-test caps `evals.max_run_cost_micros`, `live_smoke.max_cost_micros` (27 §8.4).
- REQUIRES REVIEW (Phase 1): Marathi tokens-per-character factor — MEASURED in 3B, no estimate is used for decisions before then.

## 5. Revisit trigger
- A task's golden set fails at its tier, or passes at a cheaper one.
- Provider price or model list changes (re-verification of PR-01/PR-02).
- Measured Devanagari token cost makes cost per finished video exceed the owner's per-video budget.
- Breaker for the provider is `OPEN` longer than `open_ms_max` repeatedly (07 §4.2) → second-provider evaluation.
- First client (Tier 1) needs its own provider account or data-processing terms.

## 6. Research IDs cited
PR-01, PR-02, PR-03.
