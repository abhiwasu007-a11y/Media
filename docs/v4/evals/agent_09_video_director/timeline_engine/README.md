# Eval set — `agent_09.timeline_engine` (deterministic; no LLM)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 09 Video Director |
| Depends on | agents/agent_09_video_director.md (§6 decision engine, §10 functions F-04…F-24, §20 checks), 18_PRODUCTION_QUALITY_STANDARD.md §3, 27_ENGINEERING_STANDARDS.md §6, §8 |
| Directive sections covered | §1A.2 (hook window, cadence 3–5 s, interrupts, J/L cuts, chapters, end screen, sting after the hook), §1A.1 and §1A.11 (tier plan), §1A.8 (9:16 plan) |
| Files | `cases.jsonl` (33 cases), `rubric.md` (statement: no judge) |

## 1. Scope
The pure functions of the shot-plan engine run on fixture inputs without any model, clock or network. Each case names the `function` under test, an `input` fixture and the exact `expected` result. This is the dataset the table-driven unit tests U-19…U-26, U-30…U-33, U-49…U-58, U-64…U-67 and U-73…U-75 read (agent blueprint §21). It replaces a prompt-style dataset for the deterministic part of the agent; the LLM step has its own dataset (`../shot_direction/`).

## 2. Baseline configuration (`"config": "base"`)
`cadence.min_gap_ms` 3000, `cadence.max_gap_ms` 5000, `cadence.safety_margin_ms` 0, `snap.tolerance_ms` 0, `snap.min_slot_ms` 2000, `qc.hook.window_ms` 30000, `qc.visual.tier_e_max_share` 0.50, `tier.d_enabled` false, `tier.e_plan_fraction` unset, `jl.offset_ms` and `jl.every_nth` unset, `held.max_ms` unset. A case's `config_overrides` change single keys. The fixture values are test values: where the blueprint says `PROPOSAL` or `REQUIRES REVIEW` (J/L offset 400, `every_nth`, windows, held limit, end-screen length, transition limit) the case sets the value explicitly, so the dataset stays valid when the calibrated config changes the defaults.

## 3. Case coverage
| Group | Cases | What they prove |
|---|---|---|
| Slot grid | TE-01…TE-10, TE-32 | count formula (n_min, n_tgt, n_cap), hard limit beats floor, short scene, hook pacing, snapping accepted and rejected, tiling over several scenes, held exemption |
| Hook and sting | TE-11…TE-14 | hook end inside and outside the window, sting exactly at hook end, no sting without a template |
| Interrupts | TE-15, TE-16 | forced slot nearest the window centre, script-planned interrupt satisfies the window |
| J/L cuts | TE-17…TE-22 | alternation J then L, offset sign, chart rule, disclaimer rule, hook-end rule, gap-limit rule |
| End screen, chapters | TE-23, TE-24 | reserved segment (set and unset), chapters from measured starts |
| Tiers | TE-25, TE-26 | time-ordered E allowance and share arithmetic, D disabled |
| Gates | TE-27, TE-28 | script hash mismatch, incomplete narration timeline: error code, zero model calls |
| Rebase, vertical, charts, transitions | TE-29, TE-30, TE-31, TE-33 | shot IDs kept and limit failure, 9:16 anchor presence, chart reveal steps, no fade to black |
Categories: POSITIVE (normal path), HARD_NEGATIVE (a rule that must hold against a plausible request), EDGE (boundary arithmetic). Cases with `variants` list several inputs and expected results in the same order.

## 4. Assertions (all cases; deterministic)
| ID | Assertion |
|---|---|
| T1 | the function returns exactly the `expected` values (slot counts, boundaries, durations, cut times, roles, allowed tiers, overlays, chapters, error codes and violation lists); integer arithmetic with `round_half_up` as in blueprint §6.2 |
| T2 | tiling invariant on every slot list produced: contiguous, no overlap, `Σ duration = span` |
| T3 | no slot duration exceeds `g_max` unless a recorded `held` exemption applies |
| T4 | error cases make zero LLM calls and zero network calls |
| T5 | running a function twice on the same input returns identical output (determinism) |
| T6 | no case output contains narration text or on-screen text (only IDs, numbers, enums) |

## 5. Pass thresholds (config `evals.agent_09.timeline_engine.*`)
| Threshold | Value |
|---|---|
| Overall case pass rate | **100 %** (every case is deterministic; a failing case is a defect, not noise) |
| Cases expecting an error code returning that code with zero model calls | 100 % — mandatory |
| Cost and latency | no model call; recorded latency only (no threshold) |
CI fails the PR if any threshold is missed. Recording fields per case per run: `run_id`, `case_id`, `function`, `passed`, `assertions` (T1–T6), `config_version`, `started_at`, `figure_kind`.

## 6. Open points
- The alternation rule when a J-cut is replaced by an L-cut (TE-19): the alternation pointer advances once per applied boundary and is not changed by the replacement. If the 3B pilot prefers another rule, TE-19 and TE-17/18 change in the same PR.
- Snap and floor values (`snap.min_slot_ms` 2000) are test values; **REQUIRES REVIEW (Phase 1): calibrate in 3B**.
