# ADR-014 — Video encode targets: YouTube's bitrate is an encoder target (H.264 High VBR), quality is measured against a lossless intermediate

| Field | Value |
|---|---|
| Status | **Accepted** (owner decision D10, 2026-11-19). Software: **Built** in `packages/agents/agent_10_video_editor` (this PR) |
| Decider | Owner (Abhi), D10 (dry-run break 8) |
| Depends on | 18_PRODUCTION_QUALITY_STANDARD.md §6, §7.1, §7.11, §13; agents/agent_10_video_editor.md §8.1, §20.1, §24.2; evals/agent_10_video_editor/deterministic_core (DC-40…DC-44); CONTRACT_CHANGE_REQUESTS.md CCR-240 |
| Directive sections covered | §1A.5 (video delivery), §1A.6 (automated QC) |
| Research IDs | INF-10, INF-12, INF-13 (all from YouTube Help 1722171; INF-12 and INF-13 fetched 2026-11-19) |
| MVP scope | **3A**: encoder settings as data, encoder-settings check (blocking), SSIM against the lossless reference (report only). **3B**: the SSIM (or VMAF) pass threshold and whether it blocks. |
| Enterprise tier | Tier 0 onward; a tenant QC profile may only make the threshold stricter (18 §8) |

## 1. Context
- 18 §6 and §7.1 (`qc.video.bitrate`) gated the **measured** average bitrate of the final file: below 8 Mbps FAIL, 8–15 WARN, 15–25 PASS (directive §1A.5 target 15–25 Mbps; INF-10 floor 8 Mbps).
- Dry-run break 8: code-made still graphics encode at about **115 kbps** with x264 average-bitrate control against the 8 Mbps floor. A static picture needs very few bits; x264 cannot (and should not) spend 8 Mbps on it without padding. The dry run lowered the floor by configuration for that run only.
- YouTube (INF-12, fetched 2026-11-19): "Variable bitrate. No bitrate limit is required, though we offer recommended bit rates below for reference". SDR 1080p: **8 Mbps** at 24, 25, 30 fps; **12 Mbps** at 48, 50, 60 fps. These numbers equal the owner's statement in D10: no mismatch.
- YouTube (INF-13): H.264 High Profile, progressive, 2 consecutive B-frames, closed GOP of half the frame rate, CABAC, 4:2:0; MP4 with the moov atom at the front.
- The installed development FFmpeg (6.1.1) has the `ssim` and `psnr` filters and **no `libvmaf`** (only `vmafmotion`, which is not VMAF). Measured locally with `ffmpeg -filters`; not a research-log fact.
- Measured locally (FFmpeg 6.1.1, libx264 core 164): the x264 SEI (`x264 - core … options: … rc=abr … bitrate=8000 …`) stays in the stream with `-map_metadata -1` and `+bitexact`; with `-maxrate` equal to `-b:v` x264 reports `rc=cbr`; without VBV it reports `rc=abr` and no `filler` key; `-preset ultrafast` gives Constrained Baseline.

## 2. Options considered
| Option | What it means | Verdict |
|---|---|---|
| A. Floor on the measured bitrate (status quo) | FAIL when the measured average is below 8 Mbps | **Rejected.** YouTube states no bitrate limit is required (INF-12); static content fails for no quality reason (break 8) |
| B. CBR at the target | `-minrate = -maxrate = -b:v`, `nal-hrd=cbr` | **Rejected.** Not what YouTube asks ("Variable bitrate"); wastes bits on simple frames; needs filler to hold the rate |
| C. Filler padding | write filler NAL units until the measured rate reaches the floor | **Rejected (owner D10: no filler padding).** Bytes without picture information; bigger upload, no quality gain |
| D. Encoder target + settings check + quality metric (**chosen**) | encode H.264 High VBR (x264 ABR) at YouTube's target; verify the settings in the delivered stream; measure SSIM against a lossless intermediate | **Chosen (D10).** The target is a sourced fact; the check verifies what can be verified; the metric measures quality instead of bits |

## 3. Decision
1. **Target, not floor.** The delivery encode runs x264 average-bitrate rate control (`rc=abr`, variable bitrate) with `-b:v` equal to the target of `data/encode_targets.json`, keyed by the output size and the exact frame rate. Rows (from INF-12, adopted by D10): 1920×1080 at 24/25/30 fps → 8 000 000 bps; 1920×1080 at 48/50/60 fps → 12 000 000 bps. A configured `agent_10.render.video_bitrate_bps` that differs from a row is refused (`CONFIG_INVALID`, `ENCODE_TARGET_CONFLICT`).
2. **REQUIRES REVIEW (Phase 1): targets for other sizes.** 2560×1440, 3840×2160, the 9:16 1080×1920 preset and fractional frame rates (e.g. 30000/1001) have no row; such a render needs an operator value (`agent_10.render.video_bitrate_bps`, recorded with `target_source = OPERATOR_CONFIG`) or it does not start. INF-12 lists 1440p/2160p values; adopting them is an owner decision.
3. **Codec settings (INF-13):** profile High, `yuv420p`, progressive, CABAC on, `bframes=2`, closed GOP (`open-gop=0`), keyint = half the frame rate (15 at 30 fps; a fractional half such as 12.5 at 25 fps is REQUIRES REVIEW and needs `agent_10.render.gop_frames`), `scenecut=0`, IDR at every segment start (unchanged). `agent_10.render.x264_preset` must be `faster`, `fast`, `medium`, `slow`, `slower` or `veryslow` (never `ultrafast`: Constrained Baseline). `video_encoder` must be `libx264`.
4. **VBV cap: PROPOSAL, REQUIRES REVIEW (Phase 1).** By default there is no `-maxrate` / `-bufsize` (YouTube: no limit required). An operator may set `agent_10.render.video_maxrate_bps` and `agent_10.render.video_bufsize_bps` together; the maxrate must be above the target (otherwise x264 switches to CBR). No value is proposed here; it needs a measured reason (e.g. upload size) and an owner decision.
5. **No filler anywhere.** The argument templates never set `nal-hrd`, `filler` or `-minrate`; QC fails a stream whose SEI shows `filler=1` or `nal_hrd` other than `none`.
6. **`qc.video.encoder_settings` (new, blocking, replaces `qc.video.bitrate`).** On the final MP4: ffprobe `codec_name = h264`, `profile = High`, `pix_fmt = yuv420p`, `field_order = progressive`, `r_frame_rate` = project rate; x264 SEI present with `cabac=1`, `bframes=2`, `open_gop=0`, `interlaced=0`, `keyint` = the configured GOP, `rc=abr`, `bitrate` = target/1000, VBV values equal to the configuration (absent when unset), no filler. Any difference or no SEI = FAIL, remedy `s10_render`. The H.264 level is recorded only (no sourced value: REQUIRES REVIEW).
7. **`qc.video.quality_metric` (new, REPORT ONLY in 3A).** Each segment encode also writes the same filtered frames losslessly (FFV1, Matroska, scratch only); the render computes SSIM (`ffmpeg … -lavfi "[0:v][1:v]ssim"`) of the delivery segment against that reference, stores the `All` value per segment in the checkpoint, and reports the frame-weighted mean and the lowest segment in `encoder.quality_metric`. VMAF is not computed: the build has no `libvmaf`; the output says `vmaf_status = LIBVMAF_NOT_IN_BUILD` (or `LIBVMAF_IN_BUILD_NOT_USED` on a build that has it; wiring VMAF there is REQUIRES REVIEW). The QC check writes the value into the QC report as a non-blocking `WARN` with `threshold = null` and `details.report_only = true` (18 §7.0.4 convention for an unset threshold; `check_verdict` has no `INFO` value). The threshold key `qc.video.quality_min_ssim` is **unset in 3A**; 3B sets it, and whether it then blocks is also a 3B decision (until then a set threshold still gives only PASS / WARN, never blocking).
8. The measured video bitrate stays in the outputs (`probe.video_bitrate_bps`, QC `measurements.video_bitrate_bps`) as a reported number; it is not a gate.

## 4. Consequences
- Static and graphic content passes with whatever bitrate x264 needs; no padding, smaller uploads.
- Directive §1A.5 "15–25 Mbps at 1080p" is no longer the configured target (D10 sets YouTube's value as the target). **Open question Q-D10-1 (provisional default per owner rule A.9: YouTube's target applies; the 15–25 Mbps band is withdrawn):** the owner confirms that the 15–25 Mbps directive band is replaced, not kept as an upper band.
- CPU: every segment is encoded twice (x264 and FFV1) and decoded twice for SSIM. On real footage this adds encode time; FFV1 1080p scratch files are large but deleted per segment. Measure on pilot renders (3B) before the VPS night window is used.
- A segment adopted from storage without a checkpoint, or a replay without segment records, has no SSIM value: the check reports `NOT_MEASURED` (never PASS).
- Contract changes (CCR-240): 18 §6, §7.1, §7.11, §7.12, §12, §13, §14; blueprint 10 §8.1 (`encoder.rate_control`, `encoder.quality_metric`), §20.1 rows 14 and 14a, §21, §24.2, §17; eval cases DC-40…DC-44; the self-test fixture "12 Mbps" becomes the encoder-settings and SSIM fixtures. No GLOSSARY, 03, 04, 07 or 24 change, so no generated code is affected (R-SYNC not triggered).

## 5. Revisit triggers
1. 3B pilot: set `qc.video.quality_min_ssim` (or a VMAF threshold on a build with `libvmaf`) from measured pilot renders, and decide blocking.
2. A 1440p, 4K, 9:16 or fractional-rate render is wanted (rows for `encode_targets.json`).
3. YouTube changes Help 1722171 (re-verify INF-12 / INF-13 per the 30-day rule).
4. A different encoder (no x264 SEI) is proposed: the settings check needs another evidence source.

## 6. Cited RESEARCH_LOG IDs
INF-10, INF-12, INF-13.
