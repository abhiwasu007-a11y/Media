# Proposed Source Layout (document only, nothing created yet)

| Field | Value |
|---|---|
| Status | PROPOSAL (documentation). Software status: **Planned**. |
| Basis | Directive §3.3 (one shared library), §3.5.5 (one package per agent, typed `Protocol` interfaces), §3.3 Migration (workers with declared capabilities), §3.2a (FastAPI, PostgreSQL queue, FFmpeg). |
| Final decision | Confirmed or changed by `27_ENGINEERING_STANDARDS.md` and the ADRs. This layout is the starting point, not a decision. |

## 1. Tree

```text
amw-media-factory/
├── pyproject.toml              # workspace root: pinned Python, ruff, mypy --strict, pytest config
├── packages/
│   ├── amw_core/               # SHARED LIBRARY (every stage depends on it, it depends on nothing internal)
│   │   ├── contracts/          #   versioned JSON Schemas + Pydantic models (input, output, envelope)
│   │   ├── state_machine/      #   job/task states, transition table, audited transitions
│   │   ├── retries/            #   failure taxonomy, retry policies, circuit breakers, DLQ helpers
│   │   ├── tenancy/            #   org context, RLS session setup, tenant-scoped storage paths & cache keys
│   │   ├── audit/              #   append-only, tamper-evident audit writer (human + agent actions)
│   │   ├── cost/               #   per-call cost capture, budget checks (used by S4)
│   │   ├── config/             #   pydantic-settings; models/providers/limits only from config
│   │   ├── queue/              #   Postgres-backed queue wrapper (library chosen in ADR-001)
│   │   ├── storage/            #   S3-compatible interface; local-disk backend first
│   │   └── observability/      #   JSON logging, metrics, correlation IDs
│   ├── amw_adapters/           # PROVIDER ADAPTERS behind Protocols, each with a fake + recorded fixtures
│   │   ├── llm/  tts/  image/  video_gen/  stock_footage/  music/
│   │   └── destinations/youtube/ (OAuth, resumable upload, analytics)
│   ├── amw_orchestrator/       # Agent 01: workflow engine, admission control, night scheduler, shutdown
│   ├── agents/                 # ONE PACKAGE PER STAGE (02–17), each exposing a typed Protocol
│   │   ├── agent_02_market_intelligence/
│   │   ├── agent_03_content_strategy/
│   │   ├── …                   #   04–16 in pipeline order
│   │   └── agent_17_brief_creative_strategy/
│   └── services/               # SHARED SERVICES S1–S13 (modules, not LLM agents unless an ADR says so)
│       ├── s01_audience_intelligence/ … s13_community_comments/
├── workers/                    # PROCESS ENTRY POINTS; each registers its declared capabilities
│   ├── ai_worker/              #   LLM / TTS / image calls (light CPU, external APIs)
│   ├── render_worker/          #   FFmpeg; can run on another machine with no code change
│   ├── publish_worker/         #   uploads, publish verification
│   └── scheduler/              #   night window, 06:30 drain, 07:00 stop; quota-aware (Pacific reset)
├── apps/
│   ├── api/                    # FastAPI: dashboard backend, client portal API, later integration API
│   └── dashboard/              # S8 Command Center UI (stack chosen in ADR-004)
├── prompts/<agent>/<task>.v<N>.md   # versioned prompt files (§3.5.1)
├── evals/<agent>/<task>/            # golden datasets + judge rubrics (§3.5.3)
├── migrations/                 # DB migrations (tool chosen in 04_DATABASE_ARCHITECTURE)
├── deploy/
│   ├── compose/                # own Compose project under /opt/amw-media-factory, explicit project name
│   ├── systemd/                # factory slice (CPUWeight/IOWeight/MemoryHigh/MemoryMax/TasksMax)
│   └── env.example             # names only, never values
├── tests/
│   ├── unit/  contract/  integration/  e2e/  failure_injection/  security/  performance/
│   └── tenancy/                # proves cross-tenant reads return nothing
└── docs/                       # this documentation set
```

## 2. Dependency rules
1. `amw_core` imports no other internal package.
2. Agents and services import `amw_core` and adapter **Protocols** only, never concrete adapters (dependency injection) and never each other. Hand-offs go through contracts and the orchestrator (§2: control flow in code).
3. Only `workers/*` and `apps/*` wire concrete adapters and start processes.
4. Every call that has an external side effect goes through an adapter that takes an idempotency key (§3.3 Recovery).
5. No package reads environment variables directly; all configuration goes through `amw_core.config`.

## 3. Note on the current documentation-phase location
During this phase, `prompts/` and `evals/` skeletons live in `docs/v4/prompts/` and `docs/v4/evals/` (execution plan Q3). They move to the repo root in the first build ticket.
