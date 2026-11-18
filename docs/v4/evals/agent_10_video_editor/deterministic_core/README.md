# Eval set — `agent_10.deterministic_core` (deterministic; no LLM)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 10 Video Editor |
| Depends on | agents/agent_10_video_editor.md (§6 decision engine, §10 functions F-01…F-46, §20 checks), 18_PRODUCTION_QUALITY_STANDARD.md §5–§7, 27_ENGINEERING_STANDARDS.md §6, §8 |
| Directive sections covered | §1A.4 (audio delivery), §1A.5 (video delivery), §1A.6 (automated QC), §1A.1 (tier share, licence per shot), §1A.2 (hook, cadence, chapters), §1 Heavy work and D1 (render guards) |
| Files | `cases.jsonl` (96 cases), `rubric.md` (statement: no judge) |
| Why this dataset exists | Agent 10 has **no LLM step**, so it has no prompt file and no judged dataset. This dataset holds the exact, recomputable decisions of its pure functions: frame quantisation, segment planning, cue building, SRT validation, tool-output parsing, check evaluators, the gate and the heavy-work guard. Media-level behaviour (real FFmpeg runs) is covered by the lavfi self-test (blueprint §21 R-02), not here. |

## 1. Scope
Each case names the `function` under test, an `input` fixture and the exact `expected` result. This is the dataset that the table-driven unit tests read (blueprint §21: U-11…U-26, U-34…U-43, U-61…U-70, U-84…U-95 and the check evaluator groups). Inputs contain no calendar dates, no tenant data and no copyrighted text; times are relative milliseconds, weekday plus time of day for the guard, and test values for every threshold that the blueprint marks `REQUIRES REVIEW (Phase 1)`.

## 2. Reference rules the expected values follow
| Rule | Statement |
|---|---|
| Frame quantisation | `frame(t_ms) = (t_ms * fps_num + 500 * fps_den) // (1000 * fps_den)` (round half up). Boundaries are quantised, durations are derived, so the tiling of the plan is preserved. |
| Frames to ms | `round_half_up(frames * 1000 * fps_den / fps_num)`. |
| Segment planning | segments close at the first shot end where the accumulated frames are `>= target_frames`; shots are never split; the last segment takes the remainder. |
| Cue building | tokens split on whitespace; greedy fill up to `max_chars_per_cue` Unicode code points; a longer token forms its own cue with warning `OVERLONG_TOKEN`; cue boundaries `start + round_half_up(duration * cumulative_code_points / total_code_points)`; a zero-length cue is `PERMANENT.INPUT_INVALID` (`CUE_TOO_SHORT`). |
| Parsers | seconds in tool text are converted to integer milliseconds by decimal text (round half up), never through floating-point arithmetic. A missing summary value is `MEASUREMENT_UNAVAILABLE`, never a default. |
| Verdict mapping | 18 §7.0.4: sourced threshold gives `PASS` / `FAIL` (blocking); unsourced threshold gives measured value, `threshold = null`, `WARN`, not blocking. |
| Guard order of reasons | `DRAIN`, then `MARKET_HOURS`, then `OUTSIDE_NIGHT_WINDOW`, then `NIGHT_WINDOW_END`. Estimated segment time is rounded up to whole minutes. Market windows apply to every placement; the night window applies to `VPS` only. |
| `remedy_stage` | advisory, one of `s07_voice`, `s08_assets`, `s09_plan`, `s10_render` (blueprint §6.5); present only on blocking or WARN-with-violation results. |

## 3. Case coverage
| Group | Cases | What they prove |
|---|---|---|
| Frame grid and timeline | DC-01…DC-13 | quantisation at integer and non-integer frame rates, exact halves, tiling preserved, zero-frame shot, missing asset, plan gap, canonical hash independent of key order and bound to asset bytes |
| Segments | DC-14…DC-20 | closure rule, long shot, `>=` boundary, short total, invalid target, content-addressed segment key (same inputs equal, other FFmpeg build different) |
| Subtitles | DC-21…DC-32 | time format, cue split and proportional timing, Devanagari code points, overlong token, too-short segment, validator errors reported together |
| Tool-output parsers | DC-33…DC-39 | ebur128 summary, missing true-peak block, no summary, blackdetect, silencedetect with an unclosed run, freezedetect complete and open |
| Check evaluators | DC-40…DC-85, DC-95, DC-96 | bitrate bands and bounds, true peak, loudness with and without tolerance, duration vs timeline, tier-E share at exactly 50 %, black frames (declared, undeclared, uncalibrated, last frame), silence (declared, undeclared, unset limit, end tail), licence completeness (interval, unknown monetisation, expiry, third-party, other render, no asset), music bed offset (band edges, no stem), cadence, chapters, brand sting, CFR, gate aggregation |
| Heavy-work guard | DC-86…DC-94 | market hours on the development placement, segment running into the window, weekday and weekend, VPS night window, grace edge, drain flag |
Categories: POSITIVE (normal path), HARD_NEGATIVE (a rule that must hold against a plausible request), EDGE (boundary arithmetic).

## 4. Assertions (all cases; deterministic)
| ID | Assertion |
|---|---|
| T1 | the function returns exactly the `expected` values (integer arithmetic; verdicts, offending IDs, error codes, violation lists) |
| T2 | tiling invariant on every frame list produced: contiguous, no overlap, sum of frames equals the total |
| T3 | error cases make zero FFmpeg, zero network and zero LLM calls |
| T4 | running a function twice on the same input returns identical output (determinism) |
| T5 | no output contains script text, subtitle text beyond the case's own `text` fixtures, keys or paths (IDs, numbers, enums only) |
| T6 | for a missing or unparseable measurement the verdict is never `PASS` |

## 5. Pass thresholds (config `evals.agent_10.deterministic_core.*`)
| Threshold | Value |
|---|---|
| Overall case pass rate | **100 %** (deterministic; a failing case is a defect, not noise) |
| Cases expecting an error code returning that code with zero tool calls | 100 % — mandatory |
| Cost and latency | no model call and no media process; recorded latency only (no threshold) |
CI fails the PR if any threshold is missed. Recording fields per case per run: `run_id`, `case_id`, `function`, `passed`, `assertions` (T1–T6), `config_version`, `started_at`, `figure_kind`.

## 6. Open points
- Thresholds set in cases (tolerances, limits, CFR tick tolerance, cue length, calendar, grace) are **test values**. **REQUIRES REVIEW (Phase 1): calibrate in the 3B pilot**; the cases set them explicitly, so they stay valid when the calibrated configuration changes the defaults.
- The market calendar of DC-86…DC-90 is a fixture, not the exchange calendar (**REQUIRES REVIEW (Phase 1): RESEARCH_LOG entry for the official sessions**, ADR-012 §3.3).
- Cue length is counted in code points; grapheme-cluster counting for Devanagari is **REQUIRES REVIEW (Phase 1)** (DC-26 changes with that decision).
- DC-63…DC-68, DC-95, DC-96 assume the matching rule of the pending CCR on 18 §7.9 (ledger rows written at sourcing with `render_id` null; Agent 08 item P3).
