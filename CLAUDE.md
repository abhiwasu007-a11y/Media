# CLAUDE.md — AMW AI Media Factory (keep ≤150 lines: rules, commands, pointers only)

## Read first
1. `docs/v4/CONTEXT_BRIEF.md`: the digest of the binding directive. Read specific § of `docs/v4/MASTER_DIRECTIVE.md` only when needed.
2. `docs/v4/IMPLEMENTATION_PROGRESS.md`: status, owner decisions (D1+), open questions. Resume from it; never redo finished work.
3. `docs/REPO_MAP.md`: where everything lives. Use it instead of scanning.

## Hard rules
- Current phase: **documentation only**. No code, migrations, configs, deployment or VPS changes until the owner approves the V4.0 baseline in writing.
- This repo is **public**: no secrets, book content, private method, private trading data or server details (container names, ports, IPs).
- Never touch the trading app or BagMitra. VPS: read-only commands only, run by the owner.
- Every external fact cites a `RESEARCH_LOG.md` ID (official URL + date). Never invent numbers. Mark unknowns `REQUIRES REVIEW (Phase 1): <need>`.
- Contracts live only in the Wave A docs (see REPO_MAP). Need a change? File it in `docs/v4/CONTRACT_CHANGE_REQUESTS.md`; never create a variant.
- No paid API calls except owner-approved runs within owner-set budgets. Keys only via the environment's secret mechanism.
- Reports to the owner: Marathi, ≤15 lines per phase. Docs, specs, prompts and code: English.

## Token discipline
- Targeted reads: grep first, then line ranges. Do not re-read files you just wrote.
- Private repos: use the file indexes in `~/.amw_private/`; never list or glob the trade-data tree.
- Sub-agents: at most 4 in parallel, tight brief (task, exact files, output path), return ≤200 words. Models: Opus for foundation/architecture/contracts/final review; Sonnet for blueprints, code, tests; Haiku for inventories, formatting, link checks, progress updates.
- Tests (from the build phase on): affected tests only with `pytest -q`; full suite once per wave; fakes and fixtures only.
- Record token usage per wave in `IMPLEMENTATION_PROGRESS.md`.

## Git
- Work on `claude/…` branches; one docs-only PR per phase or wave; the owner merges.
- Conventional commits (`docs(v4): …`).
