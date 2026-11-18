# Deterministic golden dataset — Agent 04 non-LLM core (`agent_04.research_pack` and retrieval)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 04 Research & Knowledge |
| Depends on | blueprint `agents/agent_04_research_knowledge.md` §6, §8, §10, §19, §20; ADR-013; 08 §8; 07 §2; 13 §8 and §5.11 (FIN-R12); 04 §5.16 (release rule); 27 §6.1 (function-level datasets, CCR-024) |
| Why this dataset exists | Agent 04's decisions that matter most for safety and isolation (reliability tier, restricted-collection gate, tenant filtering, copy guard, coverage and failure mapping) are **deterministic**, so they get their own golden dataset in addition to the two LLM-step datasets. No model is called. |
| Answer-key cases (directive §1B.2) | none apply to this dataset: the four answer-key cases concern LLM output and are carried by the two LLM-step datasets `research_pack_plan` and `research_pack_notes` (their answer-key cases, numbered one to four) |
| MVP scope | **3A** (all cases) · Tier 0; tenancy cases are the Tier 1 cross-tenant suite already at Tier 0 |
| Files | `cases.jsonl` (69 cases; no judge), `input.schema.json` (shape of every case `input`) |

## 1. Case format
Function-level dataset (27 §6.1, CCR-024): the folder name ends in `_core`; each case has `function` (the pure function or method under test, class names of blueprint §9 and §10), `input` (its argument object `{component, fixture}`, validated against `input.schema.json`), `expected` (the exact deterministic result) and no `judge_min`. `category` carries the `eval_case_category` value. Case-ID prefixes are component prefixes `<COMP>-NN` (declared in §2). `fixture` keys are per component and are test data, not product defaults (tier scores, thresholds). Fixture shapes that name a whole pack or a whole run (`"pack": "valid pack fixture"`, `"run": …`) refer to the invented fixtures of the build ticket; none contains book text, a real source or tenant data.

## 2. Coverage
| Prefix | Component | Cases |
|---|---|---|
| RT | `ReliabilityScorer` (tier from kind, ownership, domain class; ownership UNKNOWN blocks; null ownership of an external reference; monotonic config via `TierScores.validate`) | 12 |
| RG | `RestrictedCollectionGate` (Q26, FIN-R12: method topics only, approval state/kind/org, per-topic release by `subject_sha256` and chunk set, source-level release; 04 §5.16) | 12 |
| TN | `LibraryRetriever`, `TenantGuard`, `PromptLoader`, log isolation via `ResearchPackStep` (08 §8 layers 1, 2, 4, 5; `video_kind` check) | 11 |
| CG | `CopyGuard`, `NoteValidator` (verbatim run, numbers, URL/quote, forward-looking, cross-language skip) | 10 |
| AS | `PackAssembler`, `PackValidator` (coverage, gaps, citations, unreachable source, snapshot check, blocked-topic gate result, cross-language WARN, failure when nothing is usable) | 12 |
| FL | `ResearchPackStep` flow and `ExternalReferenceFetcher`: idempotency keys (task and `fetch.reference`), budget stop, parse failure, auth failure, provider outage wait, fetch errors, private-address refusal, schema defect, plan check, checkpoint resume | 12 |

## 3. Assertions
Each case passes when the function's result equals `expected` on every listed key (extra keys in the result are allowed). Error codes are exactly the 07 §2 codes. Check IDs are the `a04.*` IDs of blueprint §8 and §20.3. Security-event expectations (`security_event: true`) require a log line with event name `security.cross_tenant_ref` and `org_id` of the caller (no content).

## 4. Thresholds
All 69 cases must pass (100 %); any failure blocks the PR (these are unit-level, free, run on every CI run). Tenancy cases TN-01…TN-11 and RG-07 are also part of the `security`/`tenancy` marker suites (08 §8.2).

## 5. Open points
- TN-01 requires the DB test role to run once with RLS active and once with only the explicit `org_id`/`channel_id` predicates, to prove the first line of defence alone is sufficient (rule 9).
- RG-02: whether a released method chunk may ever support a non-method video is an owner decision; the dataset encodes the directive text (FIN-R12 d: never mixed into a general-concept video).
- RG-09…RG-11 encode the reading of 04 §5.16 that the approved chunk list is the set of chunks carrying the approval's ID (04 does not say where the list is stored); the blueprint lists this as a contract need.
- RT-11/RT-12 encode the provisional rule of CCR-041 (`ownership: null` for external references); the value `THIRD_PARTY_PUBLIC` is an open owner question.
