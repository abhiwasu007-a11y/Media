# agent_09_video_director (ticket 3A-08)

Task `agent_09.shot_plan`, stage `s09_plan`. Blueprint: `docs/v4/agents/agent_09_video_director.md`.
Status: **implemented and tested offline (fakes only); not yet wired to the worker, DB or a real provider.**

## What exists
- Pure engine (`timeline/`, `assemble.py`, `checks.py`): slot grid, charts, interrupts, J/L, transitions, tiers, overlays, end screen, chapters, vertical plan, audio plan, rebase (FR-16, called by the step when the timeline hash changed; `REBASE_LIMIT` reachable), 24 `a09.q.*` checks plus `a09.q.vertical.safe_zone` and the `a09.q.visual_guard.refusal` WARN.
- `ShotPlanStep` (gates incl. claim/status, fail-closed budget and rule packs, direction loop, revision reuse), `ShotPlanTask` (plan blob write-once, Task Output, `plan_ref`, views), hash-bound checkpoints through the core `CheckpointStore`.

## What the tests prove, and what they do not
- `timeline_engine` (39 cases): every `expected` function output is compared exactly; every `a09.q.*` verdict named in `expected` is produced by the real check on a plan built from the case input; gate cases (TE-12/27/28/34) also run through the step with zero model calls. Through the `amw_evals` runner: **not run** (the runner has no function-level assertions; core/evals need). Run by pytest (`test_timeline_engine_cases.py`).
- `shot_direction` (30 cases): **plumbing only.** The "recorded" answer is built from each case's own `expected`, so A3/A4/A7-A12 hold by construction (AK-01..04, POS-05..09, HN-10..15, EDGE-16..23/29/30, REF-24..28). Real: input/output schema validation, the production guard on compliant output, the amw_evals runner plumbing (30/30). Not proven: that a model produces such answers (judged run J1-J4, online eval gate), G6 on the injection cases, REF-27 `either`.

## Open (not covered, with reason)
- S-02 / RLS and DB-backed IT: no DB access in this package; needs L1 stores.
- P-01..P-03 performance: bounds not set yet (REQUIRES REVIEW in the blueprint).
- Judge prompt, online eval gate, E-02 pilot: owner-authorised paid run.
- Not measured: `cpu_ms`, `peak_rss_bytes` of `resource_usage` (worker fills them).
- core needs: `amw_core.config`, `amw_core.observability`, root coverage `source`, a shared in-memory `BlobStorage` fake.
