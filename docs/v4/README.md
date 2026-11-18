# docs/v4 — V4.0 documentation index

This index lists every V4.0 document with its **documentation** status. Software status is tracked separately in `IMPLEMENTATION_PROGRESS.md` (directive rule 6). It is currently **Planned** for everything.

The directive (§4) requires 35 files directly under `docs/v4/`, the `prompts/`, `evals/` and `adr/` folders, and 17 agent blueprints in `agents/`. All of them are listed below. `00_EXECUTION_PLAN.md` and `SOURCE_LAYOUT.md` are additional planning documents.

Documentation status values: **Not started** · **Draft** · **Partial (blocked)** · **Complete** · **Audited**.

## 0. Governance
| File | Status |
|---|---|
| [MASTER_DIRECTIVE.md](MASTER_DIRECTIVE.md) | Complete (binding, unchanged) |
| [00_EXECUTION_PLAN.md](00_EXECUTION_PLAN.md) | Complete (owner-approved 2026-11-18, all defaults accepted) |
| [IMPLEMENTATION_PROGRESS.md](IMPLEMENTATION_PROGRESS.md) | Draft (live ledger) |
| [CHANGE_REQUESTS.md](CHANGE_REQUESTS.md) | Complete (empty register) |
| [SOURCE_LAYOUT.md](SOURCE_LAYOUT.md) | Draft (proposal) |

## 1. Discovery & audit
| File | Status |
|---|---|
| [00_REPO_AND_SERVER_AUDIT.md](00_REPO_AND_SERVER_AUDIT.md) | Partial (blocked: VPS output) |
| [RESEARCH_LOG.md](RESEARCH_LOG.md) | Draft (waves 1 and 2 complete) |
| [KNOWLEDGE_LIBRARY_PLAN.md](KNOWLEDGE_LIBRARY_PLAN.md) | Draft (generic; book location pending) |
| [00b_TECHNICAL_FEASIBILITY.md](00b_TECHNICAL_FEASIBILITY.md) | Partial (server verdict needs VPS output) |

## 2. Business architecture
| File | Status |
|---|---|
| 19_NICHE_BENCHMARKS.md | Integrated draft (lane B2-1, not independently reviewed; UNLOGGED facts and unfiled CCRs open) |
| 17_BUSINESS_PLAN.md | Integrated draft (lane B2-1, not independently reviewed; UNLOGGED facts and unfiled CCRs open) |
| 26_GROWTH_OPPORTUNITIES.md | Integrated draft (lane B2-1, not independently reviewed; UNLOGGED facts and unfiled CCRs open) |
| 21_PRICING_AND_PACKAGING.md | Integrated draft (lane B2-1, not independently reviewed; UNLOGGED facts and unfiled CCRs open) |

## 3. System architecture
| File | Status |
|---|---|
| adr/ (ADR-001 … ADR-012) | Not started |
| 01_MASTER_ARCHITECTURE.md | Draft (integrated; open contract requests in audit/b2_unfiled_ccr_requests_shared.md) |
| 02_AGENT_REGISTRY.md | Draft (integrated; open contract requests in audit/b2_unfiled_ccr_requests_shared.md) |
| 03_COMMUNICATION_STANDARD.md | Not started |
| 24_PRODUCTION_TYPES.md | Not started |
| 20_MULTI_TENANCY_AND_ENTERPRISE.md | Draft (integrated; open contract requests in audit/b2_unfiled_ccr_requests_shared.md) |
| 04_DATABASE_ARCHITECTURE.md | Not started |
| 05_RESOURCE_MANAGEMENT.md | Draft (integrated; open contract requests in audit/b2_unfiled_ccr_requests_shared.md) |
| 06_NIGHT_SCHEDULING.md | Draft (integrated; open contract requests in audit/b2_unfiled_ccr_requests_shared.md) |
| 07_FAILURE_MANAGEMENT.md | Not started |
| 08_SECURITY.md | Not started |
| 22_DATA_PROTECTION.md | Draft (integrated; open contract requests in audit/b2_unfiled_ccr_requests_shared.md) |
| 09_COST_AND_BUDGET.md | Not started |
| 18_PRODUCTION_QUALITY_STANDARD.md | Not started |
| 13_COMPLIANCE_YOUTUBE_POLICY.md | Not started |
| 25_ADVERTISING_COMPLIANCE.md | Draft (integrated; open contract requests in audit/b2_unfiled_ccr_requests_shared.md) |
| 14_SHARED_SERVICES.md | Draft (integrated; open contract requests in audit/b2_unfiled_ccr_requests_shared.md) |
| 15_LEARNING_LOOP.md | Draft (integrated; open contract requests in audit/b2_unfiled_ccr_requests_shared.md) |
| 16_COMMAND_CENTER.md | Draft (integrated; open contract requests in audit/b2_unfiled_ccr_requests_shared.md) |
| 10_DEPLOYMENT_AND_MIGRATION.md | Draft (integrated; open contract requests in audit/b2_unfiled_ccr_requests_shared.md) |
| 12_DISASTER_RECOVERY.md | Draft (integrated; open contract requests in audit/b2_unfiled_ccr_requests_shared.md) |
| 27_ENGINEERING_STANDARDS.md | Not started |
| 11_TESTING_STRATEGY.md | Draft (integrated; open contract requests in audit/b2_unfiled_ccr_requests_shared.md) |
| prompts/ + evals/ skeletons | Not started |
| 23_ENTERPRISE_READINESS_CHECKLIST.md | Not started |

## 4. Agent blueprints (`agents/`, 26 sections each)
| Files | Status |
|---|---|
| agent_01_ceo_orchestrator.md … agent_17_brief_creative_strategy.md | Not started (0 / 17) |

## 5. Close-out
| File | Status |
|---|---|
| BLUEPRINT_COMPATIBILITY_AUDIT.md | Not started |
| BUILD_BACKLOG.md | Not started |
| BLUEPRINT_COMPLETION_REPORT.md | Not started |

## Supporting
| File | Purpose |
|---|---|
| [audit/vps_readonly_audit.sh](audit/vps_readonly_audit.sh) | Read-only VPS audit script (owner runs it; output stays private) |
