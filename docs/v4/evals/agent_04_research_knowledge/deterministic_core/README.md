# Deterministic golden dataset — Agent 04 non-LLM core (`agent_04.research_pack` and retrieval)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 04 Research & Knowledge |
| Depends on | blueprint `agents/agent_04_research_knowledge.md` §6, §10, §19, §20; ADR-013; 08 §8; 07 §2; 13 §8 and §5.11 (FIN-R12) |
| Why this dataset exists | Agent 04's decisions that matter most for safety and isolation (reliability tier, restricted-collection gate, tenant filtering, copy guard, coverage and failure mapping) are **deterministic**, so they get their own golden dataset in addition to the two LLM-step datasets. No model is called. |
| MVP scope | **3A** (all cases) · Tier 0; tenancy cases are the Tier 1 cross-tenant suite already at Tier 0 |
| Files | `cases.jsonl` (54 cases; no judge) |

## 1. Case format
Evals/README §2 with `input = {component, fixture}`: `component` is the unit under test (class names of blueprint §9), `fixture` describes the data; `expected` is the exact deterministic result. `judge_min` is always `null`. Fixture values such as tier scores are **test values**, not product defaults.

## 2. Coverage
| Prefix | Component | Cases |
|---|---|---|
| RT | `ReliabilityScorer` (tier from kind, ownership, domain class; ownership UNKNOWN blocks; monotonic config) | 10 |
| RG | `RestrictedCollectionGate` (Q26, FIN-R12: per-topic release, method topics only, approval state/kind/org) | 8 |
| TN | `LibraryRetriever`, `TenantGuard`, log and prompt-cache isolation (08 §8 layers 1, 2, 4, 5) | 10 |
| CG | `CopyGuard`, `NoteValidator` (verbatim run, numbers, URL/quote, forward-looking) | 10 |
| AS | `PackAssembler`, `PackValidator` (coverage, gaps, citations, failure when nothing is usable) | 8 |
| FL | `ResearchPackStep` flow: budget stop, parse failure, auth failure, fetch errors, plan check, checkpoint resume, idempotency | 8 |

## 3. Assertions
Each case passes when the component's result equals `expected` on every listed key (extra keys in the result are allowed). Error codes are exactly the 07 §2 codes. Security-event expectations (`security_event: true`) require a log line with event name `security.cross_tenant_ref` and `org_id` of the caller (no content).

## 4. Thresholds
All cases must pass (100 %); any failure blocks the PR (these are unit-level, free, run on every CI run). Tenancy cases TN-01…TN-10 and RG-07 are also part of the `security`/`tenancy` marker suites (08 §8.2).

## 5. Open points
- TN-01 requires the DB test role to run once with RLS active and once with only the explicit `org_id`/`channel_id` predicates, to prove the first line of defence alone is sufficient (rule 9).
- RG-02: whether a released method chunk may ever support a non-method video is an owner decision; the dataset encodes the directive text (FIN-R12 d: never mixed into a general-concept video).
