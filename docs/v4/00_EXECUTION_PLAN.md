# 00 — Execution Plan for the V4.0 Documentation & Design Phase

| Field | Value |
|---|---|
| Status | DRAFT — awaiting owner approval |
| Governing document | `docs/v4/MASTER_DIRECTIVE.md` (SHA-256 `aeb2794bb175781f7870280990db60d7c6771fb9dc9c3e30e4d268914e37032e`, committed unchanged) |
| Scope | Directive §5 phases 1–3 only: discovery & audit, business architecture, system architecture. No code, schema, config or VPS change. |
| Date | 2026-11-18 |

All effort and token figures below are **ESTIMATE** (rule 4). None is measured.

---

## 1. Understanding of the goal (10 lines)

1. Build the V4.0 **design baseline** for AMW AI Media Factory. It is a multi-tenant AI video production platform covering research → script → fact-check → voice → visuals → edit → thumbnail → SEO → publish → analytics → revenue.
2. It serves two tenant types on one codebase: the platform owner's own channels (the live proof) and paying business clients (channels, ads, dubbing, corporate video).
3. The output must look and sound like a professionally made human channel. Still-image slideshows are excluded, because they are both low quality and the demonetization pattern.
4. Compliance gates are blocking: YPP inauthentic content, AI disclosure, copyright/licences, SEBI (finance), ASCI (ads) and DPDP (data). A recorded human editorial contribution and approval are required before anything is published.
5. The first channel is Marathi-first stock-market trading **education**, drawn from the owner's private book library and historical data. It funnels to the owner's course and ATP and never gives advice.
6. Architecture: 17 pipeline stages under a code-controlled orchestrator (a state machine, not LLM-to-LLM), plus 13 shared services. PostgreSQL holds the data and the job queue, with org_id and RLS everywhere.
7. Runtime: a shared 2 vCPU / 8 GB VPS with the trading app and BagMitra, which must never be disturbed. The factory runs only 00:00–07:00 IST in its own cgroup slice. External APIs do the heavy AI work, and rendering can be moved to another machine.
8. Enterprise features are designed from day one but built in tiers (0→3), each only when a paying client needs it. Cost stays low.
9. Every external fact is verified against its official source on the day it is written and logged with URL and date. Nothing is fabricated, and every figure is labelled ESTIMATE / MEASURED / PROJECTION.
10. This phase ends when all §4 documents exist and pass the §5 audits and the §7 definition of done. Work then STOPS for written approval of the baseline before any code.

---

## 2. Phases and ordered document list (§4, sequenced per §5)

Each phase ends with a docs-only PR, an update to `IMPLEMENTATION_PROGRESS.md` and a Marathi summary (≤15 lines). A phase starts only after the previous phase's PR has been reviewed.

### Phase 0 — Kick-off (this session)
| # | Document | Depends on |
|---|---|---|
| 0.1 | `MASTER_DIRECTIVE.md` (unchanged copy) | — |
| 0.2 | `00_EXECUTION_PLAN.md` (this file) | 0.1 |

### Phase 1 — Repository skeleton & discovery audit
| # | Document / artefact | Depends on |
|---|---|---|
| 1.1 | `.gitignore` (Python, `.env`, media outputs, knowledge index), README update, `docs/v4/` skeleton, proposed source layout *as a document* (§5.1) | Plan approval |
| 1.2 | `IMPLEMENTATION_PROGRESS.md` (task ledger, resume point) | 1.1 |
| 1.3 | `CHANGE_REQUESTS.md` (empty register, freeze rule) | 1.1 |
| 1.4 | `00_REPO_AND_SERVER_AUDIT.md`: repo state, measured VPS RAM/CPU/disk/ports/containers/DBs, peak usage of the trading app and BagMitra, inventory of the private repos (file list and formats only) | VPS read-only output (A1), private repo access (A2) |
| 1.5 | `RESEARCH_LOG.md`, first wave: every §1 constraint (YouTube quotas, `videos.insert`, Test & Compare, YPP policy, synthetic-media disclosure, SEBI lag circular, quota reset time, server plan specs) | Research network access (A3) |
| 1.6 | `00b_TECHNICAL_FEASIBILITY.md`: infrastructure requirements, headroom verdict (shared vs dedicated VPS), detailed cost estimates | 1.4, 1.5, research wave 2 (provider prices) |

### Phase 2 — Business architecture (comes before the agent blueprints, because channel choice drives Agents 02/03/05/08/15)
| # | Document | Depends on |
|---|---|---|
| 2.1 | `RESEARCH_LOG.md`, second wave: §1A (delivery specs, stock/music licences incl. third-party/agency rights), §1B (RPM evidence, YPP thresholds), §1C (tenancy, OAuth verification, YouTube API audit, SSO/SCIM, DPDP Rules), §1D (ASCI, IT Rules), §1E (multi-language audio), vendor prices (LLM, TTS, AI video, image, footage, music) | 1.5 |
| 2.2 | `19_NICHE_BENCHMARKS.md`: top 3–5 channels per target niche/language, with structure, pacing, length, visual mix, thumbnails and measurable targets | 2.1 |
| 2.3 | `17_BUSINESS_PLAN.md`: niche scoring (published weights and evidence), feasibility report, first-channel rules, Trading Knowledge Library plan, unit economics, scenarios, stop/scale rules, tier gates, legal/accounting checklist | 2.1, 2.2, 1.4 (library inventory), owner inputs (A6) |
| 2.4 | `26_GROWTH_OPPORTUNITIES.md` | 2.3 |
| 2.5 | `21_PRICING_AND_PACKAGING.md` (all prices = PROPOSAL) | 2.3, 1.6 cost model |

### Phase 3 — Shared system architecture & ADRs
Listed in dependency order:
| # | Document | Depends on |
|---|---|---|
| 3.1 | `adr/` (one file per decision): ADR-001 queue (Postgres vs Redis/Celery), ADR-002 tenancy model + RLS, ADR-003 auth library / identity service, ADR-004 dashboard stack, ADR-005 storage interface, ADR-006 monitoring stack, ADR-007 LLM provider adapter & model routing, ADR-008 TTS provider, ADR-009 stock footage/music libraries, ADR-010 payment gateway, ADR-011 n8n (expected outcome: not needed), ADR-012 render-worker placement | 1.6, 2.1 |
| 3.2 | `01_MASTER_ARCHITECTURE.md` (Mermaid) | 3.1 |
| 3.3 | `02_AGENT_REGISTRY.md` (binding §3.1 table, deterministic vs LLM per stage) | 3.2 |
| 3.4 | `03_COMMUNICATION_STANDARD.md` (contracts, envelope, state machine and full transition table, failure taxonomy) | 3.2 |
| 3.5 | `24_PRODUCTION_TYPES.md` | 3.3 |
| 3.6 | `20_MULTI_TENANCY_AND_ENTERPRISE.md` | ADR-002/003, 2.3 tier gates |
| 3.7 | `04_DATABASE_ARCHITECTURE.md` (tables, columns, types, keys, indexes, constraints, org_id + RLS on every tenant table) | 3.4, 3.5, 3.6 |
| 3.8 | `05_RESOURCE_MANAGEMENT.md` (slices, cgroup limits, admission, fair sharing) | 1.4, ADR-001/012 |
| 3.9 | `06_NIGHT_SCHEDULING.md` (00:00–07:00 IST window, 06:30 drain, Pacific-time quota reset) | 3.8 |
| 3.10 | `07_FAILURE_MANAGEMENT.md` (retries, circuit breakers, DLQ, idempotency, escalation) | 3.4 |
| 3.11 | `08_SECURITY.md` | 3.6, 3.7 |
| 3.12 | `22_DATA_PROTECTION.md` (items marked for the owner's lawyer) | 3.11 |
| 3.13 | `09_COST_AND_BUDGET.md` (S4, model routing, caching, batch, Devanagari token cost) | 1.6, 2.1 |
| 3.14 | `18_PRODUCTION_QUALITY_STANDARD.md` (§1A as measurable specs, rubric, exact ffmpeg QC commands) | 2.1, 2.2 |
| 3.15 | `13_COMPLIANCE_YOUTUBE_POLICY.md` (incl. SEBI rule pack and answer-key cases) | 2.1, 2.3 |
| 3.16 | `25_ADVERTISING_COMPLIANCE.md` | 2.1 |
| 3.17 | `14_SHARED_SERVICES.md` (S1–S13) | 3.3–3.16 |
| 3.18 | `15_LEARNING_LOOP.md` | 3.7, 3.17 |
| 3.19 | `16_COMMAND_CENTER.md` | 3.6, 3.17 |
| 3.20 | `10_DEPLOYMENT_AND_MIGRATION.md` | 3.8, ADR-005/012 |
| 3.21 | `12_DISASTER_RECOVERY.md` (RTO/RPO per plan) | 3.7, 3.20 |
| 3.22 | `27_ENGINEERING_STANDARDS.md` (§3.5) | 3.4 |
| 3.23 | `11_TESTING_STRATEGY.md` | 3.22 |
| 3.24 | `prompts/` and `evals/` skeletons: template plus one complete example step (proposed: Agent 06 claim extraction, which carries the SEBI answer-key cases) | 3.22, 3.15 |
| 3.25 | `23_ENTERPRISE_READINESS_CHECKLIST.md` | 3.6, 3.11, 3.12 |

### Phase 4 — 17 agent blueprints (`docs/v4/agents/`, 26 sections each; order 01 → 16, then 17)
| # | File | Main extra dependency |
|---|---|---|
| 4.1 | `agent_01_ceo_orchestrator.md` | 3.4, 3.8, 3.9, 3.10 |
| 4.2 | `agent_02_market_intelligence.md` | 2.3 |
| 4.3 | `agent_03_content_strategy.md` | 2.3, 2.2 |
| 4.4 | `agent_04_research_knowledge.md` | library inventory (1.4) |
| 4.5 | `agent_05_scriptwriter.md` | 3.14, 3.15 |
| 4.6 | `agent_06_fact_checker.md` | 3.15, 3.24 |
| 4.7 | `agent_07_voice_production.md` | ADR-008, 3.14 |
| 4.8 | `agent_08_visual_assets.md` | ADR-009, 3.14 |
| 4.9 | `agent_09_video_director.md` | 3.14 |
| 4.10 | `agent_10_video_editor.md` | 3.14, ADR-012 |
| 4.11 | `agent_11_thumbnail_design.md` | Test & Compare research |
| 4.12 | `agent_12_seo_metadata.md` | 2.2 |
| 4.13 | `agent_13_publishing_delivery.md` | YouTube API research, 3.6 |
| 4.14 | `agent_14_analytics.md` | YouTube Analytics API research |
| 4.15 | `agent_15_growth_revenue.md` | 2.3, 3.13 |
| 4.16 | `agent_16_compliance_qa.md` | 3.15, 3.16 |
| 4.17 | `agent_17_brief_creative_strategy.md` | 3.16, 3.5 |

### Phase 5 — Audits, backlog, close-out
| # | Document | Depends on |
|---|---|---|
| 5.1 | `BLUEPRINT_COMPATIBILITY_AUDIT.md` (§5.5) | all of Phase 4 |
| 5.2 | Quality checklist, 17 × 26 sections (§5.6), kept inside 5.4 | 5.1 |
| 5.3 | `BUILD_BACKLOG.md` (epics → session-sized tickets with tests, tier and owner; walking skeleton first) | 5.1 |
| 5.4 | `BLUEPRINT_COMPLETION_REPORT.md` (counts, gaps, risks, open decisions, build order, MVP cost per video ESTIMATE) | 5.1–5.3 |

Then STOP for written approval of the V4.0 baseline (§7).

---

## 3. Effort estimate and cost control (all ESTIMATE)

"Session" means one focused Claude Code session that ends with a PR. The token figures are rough totals, input plus output, including research and re-reading.

| Phase | Sessions | Tokens (approx.) | Main cost driver |
|---|---|---|---|
| 0 Kick-off | 1 | 0.1 M | — |
| 1 Skeleton & audit | 2–3 | 0.5–0.8 M | research wave 1, VPS output analysis |
| 2 Business architecture | 3–5 | 1.0–1.8 M | web research (prices, RPM, benchmarks, policies) |
| 3 Shared architecture & ADRs | 6–9 | 1.5–2.5 M | DB design, compliance, quality standard |
| 4 17 agent blueprints | 9–14 (1–2 agents per session) | 3.0–5.0 M | 26 sections × 17, including full system prompts |
| 5 Audits & close-out | 2–3 | 0.8–1.2 M | cross-reading every blueprint |
| **Total** | **23–35** | **≈7–11 M** | |

This work runs on Claude Code. Per rule 5, that is a different thing from paid Anthropic API usage; no API spend is needed in this phase.

Where I will cut cost:
1. **Reference, don't repeat.** Agent blueprints cite shared standards by section (`03 §4.2`) and write out only the agent-specific parts, as §4 already requires. I expect this to roughly halve Phase 4 output.
2. **One research pass per topic.** Each fact is verified once, logged with URL and date, and later documents cite the `RESEARCH_LOG` entry ID instead of re-researching. A fact is re-verified only if it is more than 30 days old when cited for a decision, and again just before build.
3. **Cheaper parallel workers for research.** Source-checking fans out to subagents on a smaller or cheaper model that return only the finding, URL and date. Synthesis and design stay on the main model.
4. **Resume from `IMPLEMENTATION_PROGRESS.md`** after any context reset, never redoing finished work. Each session reads only the sections of the directive it needs, located via a section index.
5. **Small PRs, one phase or 1–4 documents each**, so review findings don't force rewrites across many files.
6. **Agent blueprints in tier order.** MVP content is written in full; Tier 2/3 parts are specified only to the depth needed to keep the data model and contracts forward-compatible.
7. **Ask instead of drafting alternatives.** Owner decisions come up early, so I don't write documents for options that will be discarded.

---

## 4. Access, credentials and files needed from the owner

| ID | What | Why | Needed by | How (least privilege) |
|---|---|---|---|---|
| A1 | **VPS read-only data**: output of `free -h`, `nproc`, `df -h`, `docker version`, `docker ps -a`, `docker stats --no-stream`, `docker compose ls`, `ss -tlnp`, `systemctl list-units --type=service`, `systemd-cgls`/cgroup version, `uptime`, `lsb_release -a`, plus peak-hour usage (sampled during trading hours and at night) | `00_REPO_AND_SERVER_AUDIT`, headroom verdict, port selection | Phase 1 (next session) | **Recommended:** I give you a read-only script, you run it on the VPS and paste or commit its output; no credentials enter this cloud session. Alternative: a dedicated read-only SSH user with no sudo, which also needs a network allowlist change. |
| A2 | **Read access to `trade-data` and `atp-private`** (exact `owner/repo` names) | Library inventory (Phase 1) and Agent 04 / business plan (Phase 2). Read-only; nothing copied into this repo. | Phase 1 (inventory), Phase 2 (content plan) | Read-only attach to the session. I only list files, formats and sizes at this stage; no ingestion and no book text in git. |
| A3 | **Network access for research** to official sources (e.g. developers.google.com, support.google.com, sebi.gov.in, ascionline.in, meity.gov.in, vendor pricing pages) | Rule 3: every fact verified against its official source. **This environment currently blocks these hosts** (tested today: all failed). | Phase 1 | Approve an allowlist update for this environment (exact hosts, proposed when needed), or confirm that the built-in web search/fetch tools are acceptable as the verification route. |
| A4 | **Google Cloud Console evidence** of the YouTube Data API quota for the project you will use (Quotas page screenshot or export: default units, "Video Uploads" bucket, verification status) | The directive asks for confirmation in the Console, not only the docs | Phase 1–2 (before `00b` and Agent 13) | Screenshot. No login sharing. |
| A5 | **Google/YouTube accounts**: which Google account or Brand Account will own channel 1; whether a separate test channel exists | Ownership design, walking-skeleton test target | Phase 2 (decision); OAuth itself only at build | Decision only. No credentials in this phase. |
| A6 | **Owner business inputs**: course outline + chapter list; existing Marathi glossary (if any); ATP and BagMitra one-paragraph descriptions + URLs; your SEBI registration status (none / RA / IA); GST status; weekly time you can give to review; monthly build/run budget ceiling; whether you will narrate yourself or use neutral TTS; any benchmark channels you already admire | Business plan, compliance rule pack, unit economics, voice design | Phase 2 | Files or plain answers. |
| A7 | **API keys** (Anthropic API, other LLMs, TTS, stock footage, music, image/AI-video) | **Not needed in this phase.** Needed only at build (walking skeleton) after baseline approval. | Build phase | Via the environment's secret store, never in chat or git; you authorise every paid plan (rule 8). |

---

## 5. Ambiguities and conflicts found in the directive

Each question comes with my recommended default. I will apply these defaults unless you say otherwise.

| # | Where | Question | Recommended default |
|---|---|---|---|
| Q1 | §5.1 | The directive says the repo is EMPTY (no commits), but it already has one commit (`README.md`: "AMW AI Media Factory"). | Treat the repo as effectively empty: keep the commit, expand the README in Phase 1, and record this in the audit. |
| Q2 | §5.1 vs this session | §5.1 says the first commit includes `.gitignore`, the `docs/v4/` skeleton and the source layout; this session's instruction forbids anything beyond two files. | This session's instruction wins. `.gitignore`, the skeleton and the layout document move to Phase 1. |
| Q3 | §4 vs §3.5 vs §7 | `prompts/` and `evals/` are listed under `docs/v4/`, §3.5 uses root paths `prompts/<agent>/…`, and §7 says nothing outside `docs/` may change. | Create them as `docs/v4/prompts/` and `docs/v4/evals/` in this phase; move them to the repo root in the first build ticket. |
| Q4 | §3.2 | S6 Security & Audit, S7 Human Approval and S8 Command Center have no owning agent, while §2 requires a named owner for every service. | S6 → 16, S7 → 01, S8 → 01. |
| Q5 | §1 vs §1B.2 | SEBI blocking is assigned to "Agent 06 and 16" in §1 but to "03/05/06/16" in §1B.2. | All four enforce (03 topic planning, 05 writing, 06 claim check); Agent 16 is the sole final authority for publication authorisation. |
| Q6 | §1, rule 2 vs §1C.14 | The VPS may be too small (rule: recommend a dedicated VPS), yet the owner "does not want a bigger VPS". | Size Tier 0 for the shared VPS. If measured headroom fails, the feasibility report recommends the cheapest separate render-only worker; I recommend, you decide, nothing is purchased. |
| Q7 | §1 production window | After 07:00 the "scheduler/monitor may stay up only if its measured footprint is safe", but nothing can be measured before build. | Design it as stoppable by configuration with an ESTIMATE footprint. Default: OFF in daytime until the pilot measures it. |
| Q8 | §1 | The SEBI 30-day price-data lag is labelled a "research finding" and may have changed. | Verify the circular in force and record it in the research log. The lag is configuration, and the design uses the stricter value if sources conflict. |
| Q9 | §4 (agent section 5) | Each blueprint needs a "full system prompt", which overlaps with the versioned prompt files of §3.5. | The blueprint holds prompt v1 text written to the template; the same text becomes `prompts/<agent>/<task>.v1.md` at build, so there is one source. |
| Q10 | §3.5.3 | ≥20 golden cases are required per LLM step, but this phase only requires "one complete example step". | Write one full eval set (Agent 06 claim extraction, ≥20 cases including the four answer-key cases). Other steps list case categories only; full sets become backlog tickets. |
| Q11 | §1A.3, §1B.2 | Voice for the finance channel: the owner's narration, a consented clone or neutral TTS. | Design all three behind the TTS adapter; the default for the pilot is the owner's own recorded narration or neutral TTS (no persona). You decide after hearing samples. |
| Q12 | §1B.2 | Marathi-first vs bilingual/Hinglish for channel 1 is to be scored, but the owner already chose Marathi. | Score both in the niche report. Your decision stands unless the evidence shows a serious risk, which I will flag rather than override. |
| Q13 | Language | The language of the documents isn't specified; only the summaries are Marathi. | Documents in English (technical precision, tooling), owner summaries in Marathi, and the glossary/content rules bilingual. |
| Q14 | §6 | "Small PRs": how small, and who merges? | One PR per phase or per 1–4 documents; you review and merge; I never merge. |
| Q15 | §3.2a | Dashboard: Next.js "or a lighter server-rendered option". | Decide in ADR-004 by RAM footprint on the shared VPS; my expectation is that a server-rendered FastAPI + HTMX-type UI wins for Tier 0, with Next.js later if the client portal needs it. |
| Q16 | §1C.1 vs MVP | Tier 0 has one tenant, yet RLS, audit and RBAC are required now. | Full multi-tenant schema, RLS and audit are designed now. Tier 0 build implements them, but with only the roles and flows one tenant needs. |
| Q17 | §1E vs §1B.6 | Growth lines (ads, dubbing, agencies) are scored now, but the expansion path says prove channel 1 first. | Score and document them now as ranked options; none affects the MVP scope. Agent 17 and ad types are blueprinted but are build-tier "first ad client signed". |
| Q18 | Rule 3 | "Re-verify on the day it is written" across a phase lasting several weeks. | Verify when first written; re-verify if more than 30 days old when used for a decision, and do a full sweep before the build starts. |
| Q19 | §1B.2a | Reading the private repos during the docs phase: inventory only, or a sample ingestion? | Inventory only (titles, formats, sizes, data date ranges). No text extraction until build. |
| Q20 | §3.1 | "If the repo already has a registry… list conflicts". | None exists, so the §3.1 registry is adopted unchanged. |

---

## 6. Top 10 risks

| # | Risk | Impact | Mitigation in design |
|---|---|---|---|
| R1 | **Channel-level YPP demonetization** for inauthentic or template content | Revenue path for every channel | Blocking uniqueness/originality gate (S2), recorded human editorial contribution, a visual hierarchy favouring real material, no AI persona for finance |
| R2 | **SEBI violation** (content drifts from education into advice, or a regulated-entity association) | Legal and reputational harm to the owner | Rule pack with the answer-key cases in evals, multi-stage blocking, price-data lag as config, no broker affiliate income, human approval |
| R3 | **Harm to the trading app or BagMitra** from resource contention on the shared VPS | Core existing business | Measured headroom, systemd slice with low weights and hard caps, night window, external render worker option, read-only audit only |
| R4 | **Copyright** from the book library or unlicensed footage/music | Strikes, claims, channel loss | Concepts in original words, no reproduction of book content, licence ledger per shot (blocking QC), agency-grade licences for client work |
| R5 | **YouTube API limits and audit** (upload quota, OAuth verification, compliance audit) block scaling or the first client | Publishing capacity, Tier 1 date | Verify quotas first, a quota-aware scheduler on Pacific reset, start verification and audit early in Tier 1, a client-owned GCP project option |
| R6 | **Documentation scope overrun**: about 60 files and 442 agent sections could consume many sessions and drift out of sync | Delay, inconsistency | Reference-not-repeat, the progress ledger, small PRs, a compatibility audit, reporting documentation status separately from software status (rule 6) |
| R7 | **Quality bar vs cost**: professional look, Marathi TTS quality and real footage may cost more per video than revenue supports | Unit economics | Golden-sample pilot before scaling, measured cost per video, model routing/caching/batch, code-generated charts as cheap high-value visuals, stop/scale rules |
| R8 | **Stale external facts** (prices, policies, model names) by build time | Wrong design decisions | Dated research log, 30-day re-verification rule, everything in config |
| R9 | **Revenue target not reached**: Marathi niche RPM and YPP timing are uncertain, and owner review time is a bottleneck | Business viability | Funnel-first revenue (course/ATP), conservative/moderate/aggressive projections labelled, review designed as one-tap, early stop/scale checkpoints |
| R10 | **Tenant-isolation or token security failure** once clients join, or over-engineering enterprise features before demand | Contractual and legal exposure, or wasted build cost | org_id + RLS + explicit filters + cross-tenant tests, per-tenant encrypted tokens, append-only audit; features strictly by tier gate |

---

## 7. What happens next

1. You review this plan and answer or accept the defaults in §5, and arrange A1–A3.
2. On written approval I start Phase 1 (skeleton, progress ledger, server/repo audit, research wave 1) in a new docs-only PR.
3. Nothing outside `docs/` changes and the VPS is not touched (only you run the read-only script).
