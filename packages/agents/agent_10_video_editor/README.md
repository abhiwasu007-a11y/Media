# agent-10-video-editor

Agent 10 (Video Editor), ticket 3A-10. Blueprint: `docs/v4/agents/agent_10_video_editor.md`.
Library code run by `workers/render_worker`; no HTTP server, no LLM, no network, no provider call.

| Task type | Stage class | Module |
|---|---|---|
| `agent_10.render` | `RenderStage` | `render.py` |
| `agent_10.subtitles` | `SubtitleStage` | `subtitle_stage.py` |
| `agent_10.technical_qc` | `QcStage` | `qc/stage.py` |

All three are `HEAVY_CPU` and share one guard (`guard.py`): never in market hours on any placement,
a self-drain timer armed with `act_by` at task start, a checkpoint before the next window opens, no
kill while a final blob is written (blobs are written atomically through `BlobStorage`; only a
running FFmpeg process is terminated and its scratch `.part` discarded). **No calendar configured
means the guard fails closed** (`PERMANENT.CONFIG_INVALID`); the calendar, night window and grace
come from configuration (`ops.market_windows`, `ops.night_window`, `drain.grace_ms`).

## Layout

| Module | Content |
|---|---|
| `frames.py`, `timeline.py` | frame quantiser, timeline `$T`, canonical hash, reveal steps, text binding, font coverage, upstream gate |
| `segments.py` | segment planner, content-addressed segment key, `ResumeVerifier`, checkpoint state |
| `ffmpeg.py` | `ArgvBuilder` (argument lists from closed templates), `FfmpegRunner` Protocol, `ProcessFfmpegRunner`, error mapping |
| `guard.py` | `HeavyWorkGuard`, `SelfDrainTimer`, `DrainSignal`, `HeavyTaskGuard` |
| `subtitles.py` | cue builder, SRT writer, strict parser, validator |
| `probe.py` | ffprobe / `ebur128` / `blackdetect` / `freezedetect` / `silencedetect` / scene parsers, MP4 atom order |
| `qc/checks.py` | one pure evaluator per check of section 20.1 |
| `qc/gate.py`, `qc/result.py` | `GateAggregator`, `QcPlan`, `RemedyMapper` (`remedy_stage_id`) |
| `qc/evidence.py` | frames, contact sheet, loudness series, report, and the single `agent_10.evidence_manifest` for Agent 16 |
| `qc/selftest.py` | QC self-test (R-02): `lavfi` fixtures with asserted verdicts |
| `contracts.py` | Pydantic payload models of section 7 and 8 (compared with the blueprint's JSON Schemas in `tests/.../test_contracts.py`) |
| `ports.py`, `deps.py` | narrow ports for `renders`, `qc_results`, assets and licence ledger; `StageDeps` |
| `testing.py` | in-memory fakes, including `FakeFfmpegRunner` (deterministic fake outputs behind the Protocol) |
| `readiness.py`, `observability.py`, `audit.py` | readiness probe, log/metric names with a structural no-leak guarantee, audit actions |

Tenant isolation: every DB access goes through `TenancyContext.transaction` (tenant transaction)
with explicit org scoping in the ports; `TenantScope` compares the org of the envelope, the Task
Input and every context ref before any file is staged; blob URIs are built by `amw_core` and
verified on every read (SHA-256); the segment cache is looked up only under the tenant's own
prefix; scratch is `<scratch_root>/<org uuid>/<task>/`. Tests: `test_security.py`.

## Pinned FFmpeg build (NFR-10, 18 section 7.0.2)

Recorded from the development environment on 2026-11-18 (a development build, not a
RESEARCH_LOG entry; the production pin is REQUIRES REVIEW):

| Item | Value |
|---|---|
| `ffmpeg -version` first line (the build ID recorded with every render and QC run) | `ffmpeg version 6.1.1-3ubuntu5 Copyright (c) 2000-2023 the FFmpeg developers` |
| compiler | `gcc 13 (Ubuntu 13.2.0-23ubuntu3)` |
| `ffprobe` | `6.1.1-3ubuntu5` |
| encoder | `libx264` (the build is `--enable-gpl`), native `aac` |
| filters used | `blackdetect`, `freezedetect`, `silencedetect`, `ebur128`, `select`, `showinfo`, `tile`, `drawtext`, `concat`, `overlay`, `scale`, `apad`, `tpad`, `fps`, `trim` |

Findings on this build (all recorded in tests):

* `ffmpeg -v error -i $S -f null -` (18 section 7.6) fails for a subtitle-only input ("does not
  contain any stream"); `ArgvBuilder.srt_check` adds `-c:s webvtt`, which accepts a good SRT and
  rejects garbage.
* x264 reports **Constrained Baseline** instead of **High** when `-preset ultrafast` is used (no
  CABAC, B-frames or 8x8dct); `qc.video.codec_profile` caught it. Keep `agent_10.render.x264_preset`
  at `faster` or slower. Integration tests use `faster`.
* The native AAC encoder's average rate on synthetic signals is about 240 kbps at a configured
  nominal 384 kbps (CCR-055): the nominal rate is gated, the measured average is reported.
* `sine` and `aevalsrc` mono sources lose 3 dB when up-mixed to stereo; the self-test's "hot"
  fixture therefore generates both channels explicitly.

## Tests

```
uv run pytest tests/agents/agent_10_video_editor -m "not integration"   # fast, fakes only
uv run pytest tests/agents/agent_10_video_editor -m integration         # real local FFmpeg, ~5 min
```

* `test_golden.py` runs the 120 deterministic cases of `docs/v4/evals/agent_10_video_editor/deterministic_core/` through the real pure functions (R-01); all 120 pass.
* `test_integration.py` (marker `integration`, skipped when ffmpeg or ffprobe is missing) generates synthetic `lavfi` audio and video at test time (never real material, never network): whole render and QC (IT-01, IT-03), revision reuse (IT-04), kill mid-segment with byte-identical resume (FI-01), self-drain timer stopping a running FFmpeg (FI-13), protocol whitelist (S-07), QC self-test fixtures (R-02).

## Decisions of this implementation (no contract invented)

* Overlay templates are composited full-frame (image template; geometry file is a PROPOSAL, REQUIRES REVIEW). Overlay **text drawing** waits for that decision: bound text is validated (SHA-256 binding, glyph coverage) and the render records the warning `OVERLAY_TEXT_NOT_DRAWN:<overlay_id>`.
* Motion other than `STATIC` and transitions other than `CUT` are carried in `$T` and rendered as hard cuts on a static frame; each is recorded as a warning (`MOTION_NOT_RENDERED`, `TRANSITION_RENDERED_AS_CUT`). The blueprint marks the look as REQUIRES REVIEW (owner look check in 3B).
* The end-screen segment (plan `content_end_ms < total_duration_ms`) is the template of the plan's `END_SCREEN` overlay shown full-frame for the reserved length.
* `agent_10.qc.single_pass` is refused (`CONFIG_INVALID`) until R-02 proves equality with the reference passes.
* `qc.audio.music_bed_offset` and `qc.audio.speech_spans` are `SKIPPED` without stems (3A); `qc.watermark.visual` is `SKIPPED` with `JUDGED_BY_AGENT_16` unless the deterministic corner-patch input is supplied.
* `qc.visual.chart_data_age` treats "older than the lag" as strictly more than `price_data_lag_days` days.
* Music bed: optional null input in 3A; non-null while `music_enabled` is false is `INPUT_INVALID`.

## Needs from other lanes

See the final report of lane L9b (core_needs, contract_needs).
