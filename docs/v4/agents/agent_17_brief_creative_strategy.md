# Agent 17 — Brief & Creative Strategy (blueprint)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** (rule 6, rule 7) |
| Owner | Agent 17 Brief & Creative Strategy; integration owner: Agent 01 (orchestrator) |
| Package | `agent_17_brief_creative_strategy` (27 §7.2); prompts `prompts/agent_17_brief_creative_strategy/`; evals `evals/agent_17_brief_creative_strategy/` |
| Directive sections covered | §3.1 row 17 (client/campaign brief intake and clarification questions, audience and objective, creative concepts and variants, ad scripts and storyboards per format, claim list to 06/16, usage-rights and talent/likeness checklist, client concept approval before production), §1D (advertising line: 1D.1 workflow, 1D.2 rules, 1D.3 blocking checks, 1D.4 ad quality and 3-5 variants), §3.3 (contracts, failures, quality, observability, AI providers, memory), §3.5 (prompt, eval, code standards), §4 (26 sections) |
| Owner decisions applied | D1 (3A production line first; **Agent 17 is not part of 3A or 3B**; spend limits at each provider; keys only through the environment's secret mechanism; render never in market hours; no upload, no Google OAuth in 3A), D2 (blueprints of non-3A agents are written in parallel and approved before their own build begins) |
| Binding contracts | GLOSSARY_AND_IDS.md (§6.15 `approval_kind`, §6.37 rule-pack keys, §6.39-6.40 claims, §6.43 `disclosure_decision`, §6.47 `tier`, §6.49-6.51), 03_COMMUNICATION_STANDARD.md, 04_DATABASE_ARCHITECTURE.md (§5.3, §5.10, §5.11, §5.12, §5.15, §5.16), 07_FAILURE_MANAGEMENT.md, 24_PRODUCTION_TYPES.md (§3.2 task types `agent_17.brief_intake`, `agent_17.concept_variants`, `agent_17.ad_script_storyboard`; §7.3-7.5), 27_ENGINEERING_STANDARDS.md |
| Shared docs referenced by name/§ only | 25_ADVERTISING_COMPLIANCE.md (§2 workflow, §3 substantiation, §4.3 rules `ADV-R1..R16`, §5 sector packs, §6 disclosure decision, §7 releases and likeness, §8 virtual presenters, §10 usage-rights), 13_COMPLIANCE_YOUTUBE_POLICY.md, 18_PRODUCTION_QUALITY_STANDARD.md, 09_COST_AND_BUDGET.md, 08_SECURITY.md §8, 22_DATA_PROTECTION.md, 20_MULTI_TENANCY_AND_ENTERPRISE.md, 3A_SLICE_SPEC.md, ADR-001, ADR-005, ADR-007, KNOWLEDGE_LIBRARY_PLAN.md (not used by this agent; client material is the client's own and is not an owner-library collection) |
| Facts cited | RESEARCH_LOG IN-04 (ASCI synthetic-content labelling; **not in force on 2026-11-18**), IN-05 (ASCI influencer rules), IN-06 (IT Rules on synthetically generated information, in force 20 Feb 2026), IN-07 (DPDP Rules), YT-06 / YT-07 / YT-09 (synthetic-media field, disclosure policy, AI personas), PR-01 / PR-02 / PR-03 (models, batch and caching, API separate from subscription), INF-11 (RLS). The ASCI Code Chapter I text is cited as read in 25 §1.3 (it has **no RESEARCH_LOG row yet: REQUIRES REVIEW (Phase 1): add a log row**) |
| Marking | Every section ends its first line with **MVP** (3A / 3B / 3C, tier 0-3 per GLOSSARY §6.47). Agent 17 is **3C, Tier 1+** (built when the first ad client is signed, 02 §registry, 24 header, plan Q17). Nothing here is part of 3A or 3B |
| Conventions | `(pending CCR)` = a contract item that does not exist in Wave A/B-1 and is listed in the structured return for the integrator. `REQUIRES REVIEW (Phase 1): <need>` = an unknown value; none is invented. All client names, brands, people and documents used in examples are fictional. No private method, book text or server detail appears in this document. |

---

## 1 Identity and mission
**MVP: 3C · Tier 1 (first managed-service ad client); portal-driven intake is Tier 2.**

### 1.1 Mission
Agent 17 is the creative front of the advertising line (directive §1D.1). It turns a client's brief into (a) a clarified, structured brief with the open questions the client must answer, (b) a small set of creative concepts with 3 to 5 test variants the client can choose from, and (c) for the approved variant, an ad script and a shot-by-shot storyboard per ordered format, together with the hand-off facts the compliance chain needs: the **claim list** (every factual, comparative, statistical or performance statement and the client document that is supposed to support it), the **label proposal** (which AI-content elements the ad contains), and the **usage-rights and talent/likeness checklist** (who or what needs a release, consent or permission). It writes creative text; it never decides truth, compliance or approval.

### 1.2 Where it sits
| Production type (24 §7) | Stages that use Agent 17 | Notes |
|---|---|---|
| `AD_SPOT` (24 §7.3) | `agent_17.brief_intake` → (approval `BRIEF`, pending CCR, see §23) → `agent_17.concept_variants` → approval `CONCEPT` (`client_two_step`) → `agent_17.ad_script_storyboard` → `agent_06.claim_extraction` | the reference flow (25 §2) |
| `ECOMMERCE_PRODUCT` (24 §7.5) | `agent_17.brief_intake`, `agent_17.ad_script_storyboard` | no concept stage unless ordered; the script step builds an implicit variant from the brief (prompt `ad_script_storyboard.v1` rule 3, input row `approved_variant`) |
| `EXPLAINER_CORPORATE_TRAINING` (24 §7.4) | `agent_17.brief_intake` only | the clarified brief is confirmed by approval `BRIEF`; scripting is Agent 05; ad-specific outputs are skipped (§8) |
| `CHANNEL_LONG_FORM`, `SHORTS`, `DUBBING_LOCALISATION` | none | owner channels use Agent 03 (17 replaces 03 for client types only, §3.1) |

All three task types run as `AI_IO` tasks on queue `ai`, capability `llm` (24 §3.1). Control flow is in the orchestrator's state machine (03 §11); Agent 17 never calls another agent and never creates tasks.

### 1.3 Authority boundaries
| Agent 17 **decides** | Agent 17 **does not decide** (owner of the decision) |
|---|---|
| how to restate the brief faithfully (no added facts) | whether the brief is approved (client, approval `BRIEF`) |
| which questions to ask the client and which are blocking | whether the product or sector may be served (owner decision on the alcohol/tobacco-surrogate sector, 25 §5.1; Agent 16 for the pack) |
| which statements in the brief are claims and which client document is tied to them by the client's own words | whether a claim is true or supported (client carries truth, 25 §1.2; Agent 06 proposes, **Agent 16 final**, Q5) |
| the creative concepts, variants, hooks, scripts and storyboards (inside the limits of §6.6) | which concept is produced (the client, approval `CONCEPT`); the script and storyboard (client, approvals `SCRIPT` / `STORYBOARD`) |
| which AI-content elements the storyboard contains (declaration) | whether an AI label is required (Agent 16, ADV-R7; Agent 17 only **proposes**, ADV-R16 compares) |
| which people, voices, brands and elements need a release or permission (the checklist) | whether a release is valid or covers the use (human check, 25 §7.2 step 3); legal drafting (lawyer, ⚖) |
| its own retries inside its caps | job routing, revision loops, approvals, budgets (orchestrator, S7, S4) |

It never writes to `approvals`, `editorial_contributions`, `compliance_verdicts` or `claims`; never raises a budget; never calls the YouTube API (zero quota units); never uploads; never fetches web pages or client links; has no tool-use for the model (the LLM returns JSON that code validates, 27 §4); and never names or imitates a real person in anything it writes.

### 1.4 Success criteria (measurable; thresholds are config and set at the first client pilot; the eval thresholds are in §26)
| ID | Criterion | Measure |
|---|---|---|
| SC-1 | Fidelity of the structured brief | 100 % of recorded quotes are exact substrings of the client's text (eval A2) |
| SC-2 | No invented claim | 0 statements in any script or concept outside the register of documented claims (eval `ad_script_storyboard` A5, `concept_variants` A3) |
| SC-3 | No unapproved person or brand | 0 shots flagged as a real person or a third-party brand without an approved reference (A7, A8) |
| SC-4 | Variants are real alternatives | all variants of a concept have distinct angles and hook overlap within `ad.variants.max_hook_overlap` (A6) |
| SC-5 | Clarification converges | share of briefs that reach `READY` within `ad.brief.max_clarification_rounds` rounds (MEASURED at the first pilot; target set then) |
| SC-6 | Plan arithmetic is exact | shot durations sum to the ordered duration in 100 % of delivered storyboards (A4) |
| SC-7 | Hand-off completeness | every delivered script has a claim list, a label proposal and a rights checklist; 0 downstream `PERMANENT.MISSING_DEPENDENCY` caused by Agent 17 |
| SC-8 | Cost discipline | cost per ordered ad stays inside the per-video budget of D1; per-task cost recorded (ESTIMATE until measured, §17) |
| SC-9 | Downstream pass rate | share of scripts that pass `agent_06.claim_extraction` and `agent_16.compliance_gate` without a revision loop caused by Agent 17 content (MEASURED; no target until the pilot) |

---

## 2 Functional requirements
**MVP: 3C · Tier 1. Each row names its tier: the brief, concept and script functions are Tier 1; client self-service answers in a portal are Tier 2.**

### 2.1 What, why, when
| ID | Function | Why | When / trigger | Inputs | Outputs | Dependants | Tier |
|---|---|---|---|---|---|---|---|
| FR-01 | Validate the task input and tenant context (S0) | rule 9; 03 §7 | every task start | Task Input, context refs | accepted input or structured rejection | orchestrator | 1 |
| FR-02 | Compute `required_inputs_status` (brand kit, client media, release documents) from the tenant's own rows | the model must not ask what the system already knows; 24 §7.3 `required_inputs` | `brief_intake` | `brand_kits`, `assets`, client documents | status map | prompt input, FR-05 | 1 |
| FR-03 | Extract the structured brief (objective, audience, product, offer, CTA, tone, mandatories, formats, languages) | §1D.1 step 1 | `brief_intake` | brief text, answers, document titles | `brief` | FR-05, 07 concept, 15 | 1 |
| FR-04 | List stated claims, named people, named third-party brands, requested AI-content classes and risk notes | claim substantiation (25 §3), rights (25 §7), label decision inputs (25 §6.2) | `brief_intake` | as FR-03 | the five lists | claim register, checklist, Agent 16 | 1 |
| FR-05 | Decide clarification questions: model asks about content ambiguity; **code** asks for missing standard inputs (brand kit, release documents, a document per claim, formats) | a clarified brief is a required input; ask once, completely | `brief_intake` | FR-02..04 | `questions[]` with `generated_by` | client (via S7 / managed service) | 1 |
| FR-06 | Compute `brief_readiness` (`READY` / `NEEDS_CLARIFICATION` / `NEEDS_HUMAN_REVIEW`, pending CCR) deterministically | the readiness gates the next stage | `brief_intake` | FR-02..05 | `readiness`, `readiness_reasons` | orchestrator routing (approval `BRIEF`) | 1 |
| FR-07 | Map the category to sector keys (code) and record `category.status` | Agent 16 loads sector packs from the brief category (25 §5.3); unknown category stops the job at validation | `brief_intake` | `category_candidates` | `category` | Agent 16, orchestrator J02 | 1 |
| FR-08 | Build the **claim register** from the approved brief: every stated claim with `register_status` `DOC_ATTACHED` / `NO_DOC` and its conditions | only documented claims may be used in creative work (ADV-R1) | `concept_variants` P3, `ad_script_storyboard` P3 | brief output, document refs | `claim_register` | concept and script steps | 1 |
| FR-09 | Build `forbidden_names` (people without a release, competitor brands) and `approved_people` / `approved_brands` | ADV-R5, ADV-R6; generation prompts must never name a real person (25 §7.2 step 4) | P4 of the two creative steps | brief output, `assets.release_ref`, `voice_consents`, client documents | lists | prompt inputs, post-checks | 1 |
| FR-10 | Propose 1-2 concepts and exactly 3-5 variants | §1D.1, §1D.4 | `concept_variants` | brief, register, constraints | concept deck | approval `CONCEPT`, script step | 1 |
| FR-11 | Write script and storyboard per ordered format; the script is written once per (language, duration) and locked for the other ratios | §1D.1, §1D.4; consistent wording across ratios | `ad_script_storyboard` | approved variant, register, media inventory | script + storyboard per format | Agents 06, 07, 09, 08, 10, 16 | 1 |
| FR-12 | Emit the **claim list** for Agents 06 and 16 | "claim list sent to 06/16 for substantiation" (§3.1) | `ad_script_storyboard` | FR-11 | `claim_list` | 06 (extraction, verification), 16 | 1 |
| FR-13 | Build the **label proposal** from the element declarations by the table of 25 §6.2 (code) | label decision input; ADV-R7, ADV-R16 | `ad_script_storyboard` | shot declarations, destinations, approved people roles | `label_proposal` | Agent 16, Agent 13 (via Agent 16's decision) | 1 |
| FR-14 | Build the **usage-rights and talent/likeness checklist** (code) | ADV-R5 inventory; `USAGE_RIGHTS` record input (25 §10.2) | `ad_script_storyboard` | FR-04, FR-11 | `rights_checklist` | Agent 16, S7 (`USAGE_RIGHTS`), Agent 08 | 1 |
| FR-15 | Handle revisions: a revision task carries `revision_feedback`; IDs of unchanged variants stay stable | 03 §3 (revision routing), `limits.max_revision_loops` | revision iteration | feedback | new iteration output | orchestrator | 1 |
| FR-16 | Persist documents (write-once blobs, SHA-256), the `scripts` row, `memory_items` pointers, cost and audit | 03 §8; 04 | end of each task | validated output | `output_refs` | all downstream | 1 |
| FR-17 | Remember concept history and client preferences per workspace, from human decisions only | avoid repeating concepts for one client | after `CONCEPT` decisions | approval decisions | `memory_items` | next campaign | 2 |

### 2.2 Out of scope (explicit)
Truth or sufficiency of any claim; recommending a price, a media plan or a budget; choosing a sector pack; selecting or generating media; voice choice (Agent 07); shot-level planning and timeline (Agent 09, which refines the storyboard); thumbnails and metadata (11, 12 are not used by ad types); rendering; client communication (S7 notifications); contract terms; reading client web links; document-to-text extraction (contract request).

---

## 3 Non-functional requirements
**MVP: 3C · Tier 1.**
| ID | Requirement | Value / rule |
|---|---|---|
| NFR-1 | Determinism of structure | the same input and the same recorded model output give the same computed fields (readiness, register, label proposal, checklist); the computed layer has no randomness and no clock dependence |
| NFR-2 | Idempotency | every external side effect carries an idempotency key (03 §9): LLM call key per (task, step, ratio, attempt-independent content hash); `scripts` insert keyed by (task, format); blob writes are write-once |
| NFR-3 | Resource class | `AI_IO`, queue `ai`, capability `llm`; no CPU-heavy work; peak memory under 256 MB (ESTIMATE); runs inside the shared `ai_worker` (10 §7) |
| NFR-4 | Latency | dominated by provider latency; **not measured**; REQUIRES REVIEW (Phase 1): measure p50/p95 in the first eval run; a client waits on `brief_intake` and `concept_variants` (interactive), so these are not batch by default (§11) |
| NFR-5 | Bounded work | hard caps: LLM calls per task `resource_budget.max_llm_calls` (brief 2, concept 2, script `2 x ratios`), clarification rounds `ad.brief.max_clarification_rounds`, revision loops `limits.max_revision_loops` (07 §9); beyond them `AGENT.LOOP_CAP_EXCEEDED` or human review |
| NFR-6 | Tenant isolation | absolute; §19 |
| NFR-7 | Confidentiality | briefs, claims, client documents and concepts are client confidential data; never in logs or metrics; never used to train or tune shared prompts (§14, §19) |
| NFR-8 | Provider independence | provider and model by config only; fake and recorded adapters for every test (27 §8) |
| NFR-9 | Cost | within the per-video and pilot budgets (D1, 09); the agent reserves before each call and stops on breach (07 `RESOURCE.BUDGET_EXHAUSTED`) |
| NFR-10 | Language | the brief may be in any language of the client; the ad language is an order parameter (English, Hindi, Marathi first); JSON field values are English except ad text and quotes (§6.3) |
| NFR-11 | Honest scope | creative output is a proposal; every output carries `proposal_only = true` semantics (it is never a verdict) |
| NFR-12 | Accessibility of questions | clarification questions are one sentence, answerable in one reply, so that a client can answer on a phone |

---

## 4 Internal architecture
**MVP: 3C · Tier 1.**

```mermaid
flowchart TD
  IN[Task Input from orchestrator] --> S0[S0 validate: schema, tenant guard, deadline]
  S0 --> LD[Load inputs: brief, register, brand kit, assets, approvals; verify SHA-256]
  LD --> PRE[Deterministic pre-steps P1..P7: required_inputs_status, register, forbidden names, budgets]
  PRE --> RSV[Cost reservation S4]
  RSV --> LLM[LlmStepRunner: render prompt, call adapter, parse]
  LLM --> POST[Deterministic post-checks D1..D12]
  POST -->|fail once| REP[Repair round: error appended, one retry]
  REP --> POST
  POST -->|pass| CMP[Computed layer: readiness, category, questions from code, claim list, label proposal, rights checklist]
  CMP --> PER[Persist: blobs, scripts row, memory pointers, audit, cost]
  PER --> OUT[Task Output + output_refs]
  POST -->|fail twice| QF[AGENT.QUALITY_REPEATED_FAILURE]
  LLM -->|refusal| RF[Refusal mapping 27 4.3]
```

```mermaid
sequenceDiagram
  participant C as Client (portal or managed service)
  participant O as Orchestrator
  participant A as Agent 17
  participant S7 as S7 approvals
  participant D as Agent 06 / 16
  C->>O: brief (text, documents)
  O->>A: brief_intake (round 1)
  A-->>O: readiness, questions, register inputs
  O->>S7: approval BRIEF (pending CCR)
  S7-->>C: questions and brief summary
  C-->>S7: answers (CHANGES_REQUESTED) or confirm (APPROVED)
  S7-->>O: decision
  O->>A: brief_intake (round n) or concept_variants
  A-->>O: 1-2 concepts, 3-5 variants
  O->>S7: approval CONCEPT (client_two_step)
  S7-->>O: approved variants
  O->>A: ad_script_storyboard (per language and duration)
  A-->>O: script, storyboard, claim list, label proposal, rights checklist
  O->>D: claim_extraction, claim_verification, compliance_gate (read Agent 17 hand-off)
```

Components are defined in §9; the state of a task in §16.

---

## 5 Full system prompt
**MVP: 3C · Tier 1. The real prompt text lives in the prompt files (27 §4); this section summarises and links them.**

There are three LLM steps, one prompt file each, all written to `prompts/_TEMPLATE.v1.md` (header table, Role, Objective, Inputs, Rules with rule packs by reference, Output JSON Schema with the `refusal` property, worked examples including a refusal path, Refusal and escalation, Self-check). Model, temperature, token caps, timeout, cost budget, caching and batch eligibility are configuration (`llm.agent_17.<task>.*`), never in the file.

| Prompt ID | File | Task type | Role in one line | Rule packs (by reference) |
|---|---|---|---|---|
| `agent_17/brief_intake.v1` | [`prompts/agent_17_brief_creative_strategy/brief_intake.v1.md`](../prompts/agent_17_brief_creative_strategy/brief_intake.v1.md) | `agent_17.brief_intake` | faithful structured brief, claims, people, brands, AI-content requests, questions, risk notes | `rp.advertising_asci_in`; sector packs when known |
| `agent_17/concept_variants.v1` | [`prompts/agent_17_brief_creative_strategy/concept_variants.v1.md`](../prompts/agent_17_brief_creative_strategy/concept_variants.v1.md) | `agent_17.concept_variants` | 1-2 concepts and exactly 3-5 distinct variants, claims only from the documented register | `rp.advertising_asci_in`; sector packs; `rp.youtube_general` if YouTube |
| `agent_17/ad_script_storyboard.v1` | [`prompts/agent_17_brief_creative_strategy/ad_script_storyboard.v1.md`](../prompts/agent_17_brief_creative_strategy/ad_script_storyboard.v1.md) | `agent_17.ad_script_storyboard` | script and storyboard for one format; per-shot declarations of people, presenter kind and AI elements | same as concept step |

Design points that hold for all three prompts:
1. **The model proposes; code decides.** Readiness, category mapping, code-generated questions, claim register, claim list, label proposal and rights checklist are computed by code from the model's declarations (§6). The prompts forbid the model to state a verdict, a label or a legal conclusion.
2. **No fact without a source.** Product facts come only from the client's brief and documents; creative steps use only register claims with a document attached. A statement outside the register is a defect, repaired once, then `AGENT.QUALITY_REPEATED_FAILURE`.
3. **No real person, no imitation.** Prompts forbid naming, describing or imitating a real, identifiable person or a competitor; people appear only as generic descriptors or as `person_ref` of an approved person (25 §7.2 step 4: generation prompts later built from shot descriptions must never name a real person).
4. **Untrusted text.** Brief text, answers, document titles, feedback and names are data. Injection cases are in every eval set.
5. **Shared prefix has no tenant data.** The system prompt, rules and schema form the cacheable prefix (PR-02); tenant content is in the user part only (08 §8 layer 4).
6. **Rule packs by reference.** `{{rule_pack:rp.advertising_asci_in}}` is resolved at runtime from `rule_packs`; the version is recorded per call. Sector packs are stubs until researched (25 §5): the prompts forbid inventing sector rules.
7. **Language.** Rule and output text in English; quotes and ad text in the client's language (§6.3).
8. **Judge prompts** (`agent_17/<task>_judge.v1`) are separate files written at build time with the eval runner (planned paths in §26); the judge never decides a verdict.

Prompt changes are `v<N+1>` and trigger the eval gate (27 §5). A released prompt is immutable.

---

## 6 Decision engine
**MVP: 3C · Tier 1.** Principle (directive §2): code decides everything that can be decided by a rule; the model is used only where language understanding or creativity is needed, and its output is always validated and then **re-derived** by code where a verdict, a count or a reference is involved.

### 6.1 Deterministic versus LLM
| Decision | Kind | Why |
|---|---|---|
| tenant and context agreement, deadline, schema | deterministic (S0) | rule 9, 03 §7 |
| `required_inputs_status` (brand kit, client media, release documents) | deterministic (P4) | facts in the tenant's own rows; the model must not guess them |
| extracting objective, audience, claims, people, brands, AI-content requests from free text | **LLM** (`brief_intake`) | natural language, any client language |
| quote fidelity | deterministic (D2: exact substring) | prevents invention |
| tie of a claim to a client document | LLM proposes only when the client's own words or the document title say so; code verifies the doc ID and kind (D3) | the platform never judges proof (25 §3.1) |
| missing-input questions (brand kit, releases, a document per claim, formats) | deterministic (D5) fixed templates in the ad language | completeness must not depend on the model |
| ambiguity questions and `blocking` flag | **LLM** | needs reading comprehension; bounded by D4 (no question on a `PRESENT` input, cap) |
| category to sector keys and pack loading | deterministic mapping table (keys fixed by GLOSSARY §6.37) | Agent 16 maps deterministically too (25 §5.3) |
| `brief_readiness` | deterministic (§6.2) | gates the next stage |
| claim register (`DOC_ATTACHED` / `NO_DOC`) | deterministic from the brief output | only documented claims are used in creative work (ADV-R1) |
| concepts, variants, hooks, scripts, storyboards | **LLM** | creative |
| counts, uniqueness of angles and hook overlap, banned words, forbidden names, claim refs, word and shot budgets, duration sum, lock identity | deterministic post-checks (D) | hard limits |
| which AI-content elements a shot has | LLM declares, **code audits**: contradictions (a person described as generated but flagged real, an AI persona without `SYNTHETIC_PRESENTER`) fail D7/D8 | honest declarations feed the label decision |
| label proposal | deterministic table (§6.4) | 25 §6.2; IN-04; the final decision is Agent 16's |
| rights checklist | deterministic (§6.5) | ADV-R5 inventory |
| approval, truth, compliance, publication | **none: not Agent 17** | §1.3 |

### 6.2 `brief_readiness` (code, evaluated in this order)
1. `NEEDS_HUMAN_REVIEW` if any `risk_notes` entry has severity `BLOCKING` (the brief as written asks for something no document can cure: ADV-R2, R3, R4, R5, R6 cases); or `category` contains a sector the platform has not been told to serve (config `ad.sectors.served`; `alcohol_tobacco_surrogate` is held for the owner's decision, 25 §5.1); or the model returned `UNSAFE_CONTENT`; or the round number reached `ad.brief.max_clarification_rounds` with blocking questions still open. Routing: approval of kind `SENSITIVE_CLAIM` (24 §3.3.2) for the operator; the client is not told to proceed.
2. else `NEEDS_CLARIFICATION` if any question is blocking (model or code), or a required input is `ABSENT` (brand kit; release documents when a real person is named; a document for any stated claim), or formats are unknown, or the category is unknown.
3. else `READY`.
The model never states readiness. `readiness_reasons[]` lists the codes (for the S7 card): `BLOCKING_RISK`, `SECTOR_HELD`, `ROUND_CAP`, `OPEN_BLOCKING_QUESTION`, `MISSING_BRAND_KIT`, `MISSING_RELEASE`, `CLAIM_WITHOUT_DOCUMENT`, `FORMATS_UNKNOWN`, `CATEGORY_UNKNOWN` (pending CCR: payload-local value set).

### 6.3 Language handling
The brief and answers may be in any language; `quote` fields stay in the original language. All other JSON text is English, except ad text (hooks, script segments, on-screen text, disclaimers), which is in `language`. Marathi and Hindi creative quality is unproven (09 §10.1 states the Marathi quality as unmeasured): the first eval run records it; no claim of quality is made here. Devanagari token cost is measured per 09 §11 (REQUIRES REVIEW (Phase 1)).

### 6.4 Label proposal (code; 25 §6.2 table, IN-04 2A-2E and 3A-3E)
Input: per-shot `synthetic_elements`, `presenter_kind`, `depicts_real_person`, approved people roles, destinations. The proposal is **not** a decision; Agent 16 decides (ADV-R7) and compares (ADV-R16).
| Condition | `asci_ai_label` (`disclosure_decision`, GLOSSARY §6.43) | Basis |
|---|---|---|
| any shot with `SYNTHETIC_PRESENTER`, or `presenter_kind = AI_PERSONA` | `REQUIRED`; also sets `presenter_identification_needed = true` | IN-04 2A; IN-05 (virtual influencers disclose); 25 §8 |
| any `REPLICATED_LIKENESS_OR_VOICE` | `REQUIRED` (and a release item in the checklist) | IN-04 2B |
| any `FABRICATED_SETTING_OR_EVENT` | `REQUIRED` | IN-04 2C |
| any `NONEXISTENT_PRODUCT_OR_PLACE_DEMO` | `REQUIRED` | IN-04 2D |
| any `SYNTHETIC_SOUND_RELEVANT_TO_PRODUCT` | `REQUIRED` | IN-04 2E |
| none of the above, all declarations present | `NOT_REQUIRED` (routine editing, ambient backgrounds, music, subtitles are not element classes: IN-04 3A-3E) | IN-04 3 |
| a declaration is missing, contradictory, or an AI visual (`D_AI_VIDEO`, `E_AI_STILL`) shows a person, a place or a product result without any declared element | `NEEDS_HUMAN_REVIEW` (never `NOT_REQUIRED`, 25 §6.2 combination rule) | 25 §6.2 |
Further fields: `elements[]` (shot number, element), `timing_hint` (from the first shot with a `REQUIRED` element to the end of the last, plus the start of the spot; a design default, IN-04 states no duration: 25 §6.4), `text_key` (reference to the localised label text catalogue; wording **REQUIRES REVIEW (Phase 1): translator and lawyer sign-off**, 25 §6.4), `youtube_declaration_hint` (`disclosure_decision`, only when `YOUTUBE` is a destination: realistic altered or synthetic content per YT-06/YT-07, IN-06; Agent 13 copies Agent 16's decision, not this hint), and `paid_endorsement_label` (needed when an approved person has role `ENDORSER`; minimum on-screen seconds from IN-05: spot length at most 15 s gives 3 s, 15 s to 2 min gives one third of the video; for 6, 15, 30, 60 s this is 3, 3, 10, 20 s, 25 §6.4; **BFSI endorsers: SEBI registration number stated** is flagged for Agent 16, ADV-R10).

### 6.5 Rights checklist (code; 25 §7)
One item per subject. Kinds (payload-local, pending CCR): `PERSON_RELEASE` (every real person: named in the brief, flagged `depicts_real_person`, or a lookalike request), `VOICE_CONSENT` (replicated voice; maps to `voices.kind = CONSENTED_CLONE` and `voice_consents.state = VERIFIED`, 04 §5.12), `BRAND_PERMISSION` (each third-party brand shown or named), `TESTIMONIAL_DOCUMENT` (each `TESTIMONIAL` claim: a real, consenting person, 25 §7.3), `CLIENT_MEDIA_LICENCE` (the client's own footage and photos: the client's grant to the platform, 25 §10.2), `THIRD_PARTY_ELEMENT` (stock, music, fonts: left `OPEN` for Agent 08's licence-ledger rows), `SPECIAL_PERSON_REVIEW` (a minor, a deceased person or a person in a sensitive profession: default `NEEDS_HUMAN_REVIEW`, lawyer position **REQUIRES REVIEW (Phase 1)**, 25 §7.2). Each item has `item_id`, `subject`, `required_evidence`, `status` (`OPEN` / `EVIDENCE_ATTACHED`, set only when a matching `assets.release_ref`, a `VERIFIED` voice consent or a client document ID exists in the tenant), `evidence_ref`, `scope_check_by = HUMAN` (25 §7.2 step 3: whether the release covers the advertiser, medium, term and AI replication is a human check; Agent 17 never marks a scope fit). The checklist also seeds the `USAGE_RIGHTS` record (25 §10.2); Agent 17 does not write it.

### 6.6 Hard limits for creative output (enforced by D-checks, §10)
1. Product facts only from the claim register entries with a document attached; wording not stronger, conditions visible with the claim (ADV-R1, ADV-R3, ADV-R12).
2. No named or described real person, celebrity, creator, lookalike or competitor; people only as generic descriptors or `approved_people` refs (ADV-R5, ADV-R6).
3. No invented testimonial, quote, rating, before/after result or customer (ADV-R2, ADV-R3). Fictional characters are allowed only when the ad claims no real use or result (25 §7.3).
4. Product shown accurately; client's own media first; AI visuals of the product must not change shape, colour, size or function (§1D.4, 25 §9; hierarchy of §1A.1).
5. AI-content elements declared honestly per shot.
6. 3-5 variants per concept order (§1D.4); the number is fixed by the order, not chosen by the model.

### 6.7 Computations (config values; no number here is a measured fact)
| Quantity | Formula | Note |
|---|---|---|
| spoken-word budget | `budget = seconds x wpm[lang] / 60`; `min_words = floor(fill_min x budget)`, `max_words = floor(fill_max x budget)` | `ad.script.words_per_minute.<lang>`, `fill_min`, `fill_max`: **REQUIRES REVIEW (Phase 1): measured with Agent 07 in 3B**; no value is invented |
| shot range | `min_shots = max(1, floor(seconds / 5))`, `max_shots = ceil(seconds / 3)` (6 s: 1-2; 15 s: 3-5; 30 s: 6-10; 60 s: 12-20) | from directive §1A.2 "a visual change every 3-5 s", applied to ads as a design default; ad pacing REQUIRES REVIEW (Phase 1): 18 |
| hook overlap | token-set Jaccard of two normalised `hook_line` values | max `ad.variants.max_hook_overlap` (design default 0.5; calibrated at the pilot) |
| hook length | `max_hook_words` derived from the shortest ordered format | design default from config; passed to the prompt as a constraint |

### 6.8 Repair and caps
Output that fails JSON parse or schema: one retry with the error appended (`agent_parse`, 07 §3). Output that parses but fails a D-check: **one** repair round with the failing check IDs appended; if it fails again, `AGENT.QUALITY_REPEATED_FAILURE` (07 §2), nothing is persisted as final, and the previous iteration remains valid. The code never edits model text silently. Refusals are mapped by 27 §4.3 (§18).

---

## 7 Input schema
**MVP: 3C · Tier 1.** Envelope: `amw.task_input` 1.0.0 (03 §3). `agent_id = agent_17`, `source_agent = agent_01`, `project_id` always present, `channel_id` null for file-delivery ads or the client's channel when `YOUTUBE` is a destination. `payload` = `{payload_schema, payload_schema_version, data | data_ref + data_sha256}`; inline limit 262,144 bytes (design value, 03 §3.3). All `context_refs[].uri` and `data_ref` belong to `org_id` (03 §8).

### 7.1 `agent_17.brief_intake.input` 1.0.0
| Field | Type | Null | Rule |
|---|---|---|---|
| `production_type_key` | enum GLOSSARY §6.48 | no | `AD_SPOT`, `ECOMMERCE_PRODUCT` or `EXPLAINER_CORPORATE_TRAINING`; else `PERMANENT.UNSUPPORTED_TASK` |
| `round_no` | int 1..`ad.brief.max_clarification_rounds` | no | 1 for the first intake |
| `brief_language` | BCP 47 | no | |
| `brief_text` | string | no | client's brief (typed by the client or entered by the operator in the managed service); size cap config |
| `client_documents[]` | `{doc_id, kind, title, storage_uri, sha256}` | no (may be empty) | `kind` in `BRIEF`, `SUBSTANTIATION`, `RELEASE`, `BRAND_GUIDE`, `PRODUCT_MEDIA`, `OTHER` (payload-local, pending CCR); documents are the client's data in the client's tenant |
| `client_answers[]` | `{question_id, answer_text}` | no | from the previous round (from the `BRIEF` approval decision) |
| `prior_output_ref` | `amw-blob://` URI | yes | previous round output, with SHA-256 in `context_refs` (`PRIOR_OUTPUT`) |
| `requested_formats[]` | `{ratio, seconds}` | yes | ratios GLOSSARY §6.50, seconds §6.49 |
| `destinations[]` | `FILE_DELIVERY` / `YOUTUBE` | no | GLOSSARY §6.26 |
Required `context_refs`: `BRAND_KIT` (if one exists), `COMPLIANCE_PROFILE`, `RULE_PACK` (`rp.advertising_asci_in`), `CLIENT_INPUT` for each document.

### 7.2 `agent_17.concept_variants.input` 1.0.0
| Field | Type | Null | Rule |
|---|---|---|---|
| `production_type_key` | enum | no | ad types only |
| `brief_ref` + `brief_sha256` | storage URI + hash | no | the confirmed brief (`agent_17.brief_intake.output`); the `BRIEF` approval (when required by the workflow) must be `APPROVED` for that hash |
| `language` | BCP 47 | no | ad language |
| `concept_count` | int 1..2 | no | config `ad.concept.max_concepts` (design default 2) |
| `variant_count` | int 3..5 | no | §1D.4; set by the order |
| `formats[]` | `{ratio, seconds}` | no | at least one |
| `revision_feedback[]` | `{source, instruction}` | yes | untrusted text |
| `iteration` | int >= 0 | no | revision counter |

### 7.3 `agent_17.ad_script_storyboard.input` 1.0.0
| Field | Type | Null | Rule |
|---|---|---|---|
| `production_type_key` | enum | no | `AD_SPOT` or `ECOMMERCE_PRODUCT` |
| `concept_ref` + `approved_variant_ids[]` | URI + IDs | `approved_variant_ids` empty only for `ECOMMERCE_PRODUCT` without a concept stage | bound to the `CONCEPT` approval's `subject_sha256` |
| `brief_ref` + `brief_sha256` | storage URI + hash | no | |
| `language` | BCP 47 | no | ad language |
| `duration_seconds` | enum 6, 15, 30, 60 | no | GLOSSARY §6.49 |
| `ratios[]` | non-empty subset of `16:9`, `9:16`, `1:1`, `4:5` | no | one task = one (language, duration); the first ratio writes the script, the others use it locked (§6.7, prompt rule 1) |
| `destinations[]` | `FILE_DELIVERY` / `YOUTUBE` | no | feeds the label proposal hint |
| `revision_feedback[]`, `iteration` | as above | yes / no | |
`resource_budget.max_llm_calls = 2 x len(ratios)`. Required `context_refs`: `PRIOR_OUTPUT` (brief, concept deck), `BRAND_KIT`, `COMPLIANCE_PROFILE`, `RULE_PACK`, `APPROVAL` (`CONCEPT` decision), `ASSET` for client media.

### 7.4 Validation order (all three)
S0: schema and version; org agreement (envelope, input, every ref); deadline; production type supported; approval prerequisites (hash match); document existence and SHA-256; size caps; then business checks. Failures are structured rejections (03 §7): `PERMANENT.SCHEMA_INVALID`, `PERMANENT.TENANT_MISMATCH`, `PERMANENT.CROSS_TENANT_REF`, `PERMANENT.MISSING_DEPENDENCY` (approval not `APPROVED` or hash differs), `PERMANENT.INPUT_INVALID`.

---

## 8 Output schema
**MVP: 3C · Tier 1.** Envelope: `amw.task_output` 1.0.0 (03 §5): `status`, `payload`, `output_refs`, `quality_score` (null: Agent 17 does not score), `confidence` (null), `validation_results` (deterministic checks first, check IDs `a17.<task>.<check>`), `duration`, `resource_usage`, `error`, `next_action` (advisory), `downstream_agent`, `timestamp`. The LLM part of each payload is the `llm_output` schema of the prompt file (the JSON Schemas live in the prompt files, 27 §4.2 item 6); the payload wraps it with the code-computed layer.

### 8.1 `agent_17.brief_intake.output` 1.0.0
| Field | Meaning |
|---|---|
| `round_no`, `brief_sha256`, `rule_pack_versions` | provenance |
| `readiness` (`brief_readiness`, pending CCR), `readiness_reasons[]` | §6.2 |
| `brief` | the model's `brief_summary` (null on refusal) |
| `category` | `{sector_keys[], status: KNOWN / UNKNOWN / HELD_FOR_OWNER}`, from the mapping table |
| `claim_register[]` | `{claim_id (cr1..), quote, claim_type_hint, register_status DOC_ATTACHED / NO_DOC, doc_ids[], conditions}`; local IDs, not `claims` rows |
| `people[]`, `third_party_brands[]`, `synthetic_requests[]` | as extracted |
| `questions[]` | `{question_id, topic, question, blocking, reason, generated_by MODEL / CODE}` |
| `risk_notes[]` | `{rule_id, severity, quote, note}` (advisory; verdicts are Agent 16's) |
| `required_inputs_status` | as computed |
| `refusal` | the model's refusal object or null (27 §4.3) |
`output_refs`: `DATA` `brief.json` (write-once, SHA-256). `next_action`: `AWAIT_APPROVAL` (readiness `READY` or `NEEDS_CLARIFICATION`, approval `BRIEF`) or `NEEDS_REVIEW` (`NEEDS_HUMAN_REVIEW`). Non-ad types: `claim_register`, `synthetic_requests`, `category` are present but `rp.advertising_asci_in` flags are omitted.

### 8.2 `agent_17.concept_variants.output` 1.0.0
`concepts[]`, `variants[]` (as in the prompt schema), `claim_register_ref` + SHA-256 (the register the step used), `forbidden_names_checked` (count, not the names), `checks[]` (D-check results), `refusal`, and `advisory_verdict` (`BLOCKED` only when the refusal is `RULE_WOULD_BE_BROKEN`; mapping 27 §4.3). `output_refs`: `DATA` `concepts.json`. This blob is the **subject** of approval `CONCEPT` (hash-bound, 03 §11.6).

### 8.3 `agent_17.ad_script_storyboard.output` 1.0.0
| Field | Meaning |
|---|---|
| `language`, `duration_seconds`, `approved_variant_id` | provenance |
| `script` | `{segments[], spoken_word_count, bounds {min,max}}`; identical for all ratios of the task |
| `storyboards[]` | one per ratio: `{ratio, shots[], total_ms}`; shot fields as in the prompt schema |
| `claim_list[]` | `{claim_ref, quote, segment_id, claim_type_hint, requires_substantiation = true, substantiation_doc_ids[], conditions, disclaimer_segment_id}` (**hand-off to 06 and 16**, FR-12) |
| `disclaimers[]` | from the model plus the register conditions (code adds any the model missed and marks `added_by = CODE`, then fails D10 if the display shot is missing) |
| `label_proposal` | §6.4; payload shape aligned with the pending decision-record schema of 25 §6.5 (pending CCR) |
| `rights_checklist[]` | §6.5 |
| `scripts_row_ref` | `amw-entity://<org>/scripts/scr_<uuid7>` (the persisted `scripts` row, `status = DRAFT`) |
| `checks[]`, `refusal`, `advisory_verdict` | as above |
`output_refs`: `SCRIPT` `script.json`, `DATA` `storyboard_<ratio>.json` per ratio, `DATA` `claim_list.json`, `DATA` `label_proposal.json`, `DATA` `rights_checklist.json`. The bundle hash is the subject of approvals `SCRIPT` and `STORYBOARD`.

---

## 9 Python package and class architecture
**MVP: 3C · Tier 1. Rules: 27 §7 (one package per agent; imports only `amw_core` and adapter Protocols; constructor injection; no globals; mypy strict).**

```text
agent_17_brief_creative_strategy/
  __init__.py            # exports Agent17Stage (Protocol StageExecutor)
  stage.py               # Agent17Stage: task-type dispatch, step order, checkpoints
  config.py              # AdSettings (pydantic-settings via amw_core.config): ad.*, llm.agent_17.*
  models/                # Pydantic: brief_in.py, brief_out.py, concept_in.py, concept_out.py, script_in.py, script_out.py, common.py
  guards/tenant.py       # TenantGuard
  guards/prerequisites.py# ApprovalPrerequisiteChecker (BRIEF / CONCEPT hash binding)
  intake/inputs.py       # RequiredInputsProbe (brand kit, assets, release documents)
  intake/questions.py    # CodeQuestionFactory (templates per language), QuestionMerger
  intake/readiness.py    # ReadinessEvaluator
  intake/category.py     # SectorMapper
  register/builder.py    # ClaimRegisterBuilder
  register/people.py     # PeopleResolver (forbidden_names, approved_people, approved_brands)
  creative/budgets.py    # WordBudget, ShotRange, HookLimits
  creative/variant_checks.py # VariantValidator (counts, angles, overlap, names, banned words, fictional rules)
  creative/script_checks.py  # ScriptValidator (words, shots, durations, lock, claim scan, disclaimers, declarations)
  handoff/claim_list.py  # ClaimListBuilder
  handoff/label.py       # LabelProposalBuilder
  handoff/rights.py      # RightsChecklistBuilder
  llm/steps.py           # LlmStepRunner (render prompt, call, parse, repair once)
  store.py               # DocStore (write-once blobs), ScriptStore (scripts row), PointerStore (memory_items)
  persist.py             # OutputAssembler, audit and cost hooks
  errors.py              # Agent17Error -> amw_core error codes
```
### 9.1 Protocols and collaborators (constructor injection)
| Protocol | Implemented by | Purpose |
|---|---|---|
| `LlmAdapter` (amw_core) | provider adapters, fake, recorded | one call: system + user text in, text out, usage |
| `BrandKitRepo`, `AssetRepo`, `ApprovalReader` | SQL repos | read-only, tenant context, explicit columns |
| `VoiceConsentReader` | SQL repo | `voices`, `voice_consents` state only (no personal data columns) |
| `RulePackLoader` (amw_core) | core | rule-pack text and version |
| `CostGuard`, `AuditWriter`, `Clock`, `Tracer`, `IdGenerator` (amw_core) | core | reservation and ledger, audit events, time, tracing, UUIDv7 |
| `BlobStore` (amw_core) | core | write-once blobs, SHA-256 verified on read |
### 9.2 Class responsibilities
| Class | Responsibility | Pure? |
|---|---|---|
| `Agent17Stage` | validate, dispatch by task type, drive steps, emit Task Output; the only class sequencing side effects | no |
| `TenantGuard` | assert org agreement of every ID, URI, row and document handled (§19) | yes |
| `ApprovalPrerequisiteChecker` | approval state and `subject_sha256` match the referenced blob | no (reads) |
| `RequiredInputsProbe` | compute `required_inputs_status` | no (reads) |
| `CodeQuestionFactory` / `QuestionMerger` | questions for missing inputs, merged and deduplicated with the model's, capped | yes |
| `ReadinessEvaluator` | §6.2 | yes |
| `SectorMapper` | `category_candidates` to `sector_keys` and status; held sectors from config | yes |
| `ClaimRegisterBuilder` | register from the brief output and documents | yes |
| `PeopleResolver` | forbidden and approved lists from rows and brief | no (reads) |
| `WordBudget` / `ShotRange` / `HookLimits` | §6.7 | yes |
| `VariantValidator` | D1-D9 of `concept_variants` | yes |
| `ScriptValidator` | D1-D11 of `ad_script_storyboard` including the deterministic claim scan | yes |
| `ClaimListBuilder` / `LabelProposalBuilder` / `RightsChecklistBuilder` | §6.4, §6.5, FR-12 | yes |
| `LlmStepRunner` | one repair round (27 §3.5.2); never retries beyond | no |
| `DocStore` / `ScriptStore` / `PointerStore` | persistence, idempotent | no |
| `OutputAssembler` | Task Output, `validation_results`, `output_refs` | yes |

---

## 10 Function-level specification
**MVP: 3C · Tier 1. Every function logs with `org_id`, `channel_id`, `job_id`, `task_id`, `correlation_id`; none logs brief text, claims, names, documents, prompts or model output (08 §8 layer 5).**

| # | Function | Signature (types abbreviated) | Side effects | Exceptions (to 07 code) | Validation | Tests |
|---|---|---|---|---|---|---|
| 1 | `Agent17Stage.execute` | `(inp: TaskInput) -> TaskOutput` | all below, in order; checkpoints C1-C4; audit | any `Agent17Error` mapped to `amw.error` | S0 | contract, E2E |
| 2 | `TenantGuard.assert_scope` | `(ctx: TenantCtx, refs: Iterable[EntityRef]) -> None` | none | `PERMANENT.TENANT_MISMATCH`, `PERMANENT.CROSS_TENANT_REF` | org of envelope, input, every URI, row, document | security, property |
| 3 | `ApprovalPrerequisiteChecker.assert_approved` | `(ctx, kind, subject_uri, sha256) -> ApprovalRef` | read | `PERMANENT.MISSING_DEPENDENCY` | state `APPROVED`, hash equals | unit, integration |
| 4 | `RequiredInputsProbe.status` | `(ctx, docs: list[Doc]) -> RequiredInputs` | read | `TEMPORARY.DB_TRANSIENT` | brand kit `is_current`; assets of the workspace; RELEASE documents | unit |
| 5 | `LlmStepRunner.run` | `(step: StepDef, vars: dict, budget: Budget) -> RawOutput` | cost reservation, adapter call, raw blob, ledger row | `AGENT.INVALID_JSON`, `AGENT.OUTPUT_SCHEMA_INVALID`, `RESOURCE.BUDGET_EXHAUSTED`, `TEMPORARY.*`, `PERMANENT.PROVIDER_REFUSAL`, `PERMANENT.AUTH_INVALID` | undeclared variables rejected; size caps | unit (fake), golden |
| 6 | `BriefValidator.check` | `(raw: BriefLlm, inp: BriefIn) -> list[CheckResult]` | none | none | D1 schema; D2 quote substring; D3 doc IDs; D4 questions | unit, golden |
| 7 | `CodeQuestionFactory.make` | `(status: RequiredInputs, register: list[RegItem], formats, category) -> list[Question]` | none | none | fixed templates; language of the client | unit |
| 8 | `QuestionMerger.merge` | `(model: list, code: list, max_q: int, answered: list) -> list[Question]` | none | none | cap; no duplicate topic+subject; answered questions dropped | unit, property |
| 9 | `SectorMapper.map` | `(cands: list[Cand], served: set[str]) -> Category` | none | none | keys within GLOSSARY §6.37; `none` handling; two sectors allowed | unit |
| 10 | `ReadinessEvaluator.evaluate` | `(out: BriefComputed, round_no, cap) -> (Readiness, list[Reason])` | none | none | §6.2 order | unit table (all branches) |
| 11 | `ClaimRegisterBuilder.build` | `(brief_out, docs) -> list[RegItem]` | none | none | stable IDs `cr<n>` by order of the brief; `DOC_ATTACHED` only if doc ID exists and kind is `SUBSTANTIATION` | unit |
| 12 | `PeopleResolver.resolve` | `(ctx, brief_out) -> People` | read | `TEMPORARY.DB_TRANSIENT` | approved only with `assets.release_ref` or `VERIFIED` voice consent, not expired or withdrawn | unit, integration |
| 13 | `WordBudget.bounds` / `ShotRange.bounds` / `HookLimits.max_words` | `(seconds, lang, cfg) -> (int, int)` | none | `PERMANENT.CONFIG_INVALID` when `wpm[lang]` is missing | §6.7 | unit, property |
| 14 | `VariantValidator.check` | `(raw: ConceptLlm, inp: ConceptIn) -> list[CheckResult]` | none | none | D1-D9 (`concept_variants` prompt header) | unit, golden |
| 15 | `ScriptValidator.check` | `(raw: ScriptLlm, inp: ScriptIn, lock) -> list[CheckResult]` | none | none | D1-D11 (`ad_script_storyboard` header); claim scan: numbers, `%`, comparatives, superlatives in every segment must lie inside a `claims_in_script` quote | unit, golden |
| 16 | `ScriptValidator.lock_identity` | `(segments, lock) -> bool` | none | none | byte equality of IDs, kinds, text, refs | unit |
| 17 | `ClaimListBuilder.build` | `(script, register) -> list[ClaimListItem]` | none | none | each `claim_ref` resolves; adds disclaimer segment IDs | unit |
| 18 | `LabelProposalBuilder.build` | `(storyboards, people, destinations, duration) -> LabelProposal` | none | none | §6.4 table, all rows tested | unit table |
| 19 | `RightsChecklistBuilder.build` | `(people, brands, shots, register, status) -> list[RightsItem]` | none | none | §6.5; evidence status only from tenant rows | unit table |
| 20 | `DocStore.write` | `(ctx, kind, doc, idem: IdemKey) -> OutputRef` | write-once blob, SHA-256 | `INFRASTRUCTURE.STORAGE_UNAVAILABLE` | schema; idempotent by key | unit, failure-injection |
| 21 | `ScriptStore.insert` | `(ctx, script, fmt_key, idem) -> ScriptId` | insert `scripts` (`status = DRAFT`, `prompt_id = agent_17/ad_script_storyboard.v1`, `created_by_task_id`) | `TEMPORARY.DB_TRANSIENT` | `UNIQUE (org_id, job_id, language, version)`: version allocated in sequence per (job, language) | integration |
| 22 | `PointerStore.upsert` | `(ctx, key, ref, scope=PROJECT, expires_at) -> MemId` | `memory_items` insert, supersede previous | `TEMPORARY.DB_TRANSIENT` | `expires_at` required for PROJECT (04 CHECK); provenance = output ref | unit |
| 23 | `OutputAssembler.assemble` | `(parts) -> TaskOutput` | none | `AGENT.INCOMPLETE_OUTPUT` | 03 §5.3 success rule | contract |
| 24 | `Agent17Stage.map_refusal` | `(refusal, ctx) -> TaskOutput` | none | per 27 §4.3 | mapping table of §18 | unit |

Logging: events `a17.task.start`, `a17.step.llm_call` (tokens, cost, latency only), `a17.check.fail` (check ID only), `a17.refusal` (reason code only), `a17.task.done`; fields in §22.

---

## 11 AI provider use
**MVP: 3C · Tier 1.** Provider, model and limits come from configuration (`llm.agent_17.<task>.*`, ADR-007); production AI calls use API access, which is billed separately from any Claude subscription (PR-03, rule 5); keys only through the environment's secret mechanism, held by the adapter (08 §3), never by Agent 17 code.
| Task / step | Starting tier hypothesis (config; confirmed or changed only through the eval gate, 09 §10.1) | Why | Cache | Batch |
|---|---|---|---|---|
| `brief_intake` | small to mid | structured extraction and classification; PR-01 names a small tier for classification-type work | prefix cached (system + rules + schema; no tenant data) | no: a client is waiting |
| `concept_variants` | mid | creative writing; PR-01: mid tier for most writing | cached prefix | no by default; `batch_eligible` configurable for non-urgent orders |
| `ad_script_storyboard` | mid; top tier only if the eval fails in a language | wording discipline; Marathi/Hindi quality unmeasured | cached prefix | configurable; one call per ratio |
Prices are not repeated here; see 09 §7 and PR-01/PR-02 (batch: 50 % discount; cache read multiplier 0.05x on the mid tier named in PR-02). A tier change is a config change that passes the eval gate; S4 never switches tier at runtime to hide a breach (09 §10.1).
**Provider refusal** (`PERMANENT.PROVIDER_REFUSAL`): fail with escalation L2; if a compliance question, L3. A configured fallback provider may be tried once inside the attempt (07 §2) only if it has passed the same eval gate.
**Determinism controls:** temperature, max tokens, timeout in config; the raw model output blob is stored (write-once) before any post-check so a retry never repays for the same call (checkpoint C2, §16).
**No tool-use, no web search, no browsing**: the model sees only the variables of its prompt.
**Fakes:** `FakeLlmAdapter` (scripted JSON by prompt ID and case) and `RecordedLlmAdapter` (fixtures) serve all tests (27 §8); no paid call in CI.

---

## 12 External APIs
**MVP: 3C · Tier 1.**
| API | Use by Agent 17 | Auth / scopes | Quotas | Errors and fallback |
|---|---|---|---|---|
| LLM provider (through `LlmAdapter`) | the three steps | provider key in the adapter's secret; no scopes in this document | provider rate limits and the owner-set spending limits (D1); per-task `resource_budget` | 429 to `TEMPORARY.RATE_LIMITED` (honour `retry_after_ms`); 5xx to `TEMPORARY.UPSTREAM_5XX`; timeout to `TEMPORARY.TIMEOUT`; 401/403 to `PERMANENT.AUTH_INVALID`; content refusal to `PERMANENT.PROVIDER_REFUSAL`; connection errors to `TEMPORARY.NETWORK`; breaker open to `INFRASTRUCTURE.CIRCUIT_OPEN`; fallback provider only by config and only if eval-passed. Exact provider error codes: adapter documentation per ADR-007; model IDs and prices PR-01, PR-02 |
| YouTube Data API | **none** (0 quota units) | no Google OAuth in 3A (D1); none needed here | none | not applicable |
| Web, client URLs, social platforms | **none**; links in a brief are recorded as text, never fetched | | | a client who wants a link used supplies the content as a document |
| Document-to-text extraction (PDF, office files) | not done by Agent 17; the brief and answers arrive as text; documents are referenced by ID and title | | | a platform function with no owner yet: contract request |
| Platform ad-spec pages (safe zones, durations) | not read at runtime; thresholds belong to `qc.ad_spot` (25 §9: REQUIRES REVIEW (25)) | | | |
Verification: no external API fact is asserted here beyond RESEARCH_LOG PR-01..PR-03.

---

