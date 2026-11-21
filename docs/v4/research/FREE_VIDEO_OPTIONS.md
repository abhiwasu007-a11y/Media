# Free and low-cost options for cinematic / animated video (D19 research, 2026-11-21)

Owner request (D19): high-quality cinematic, animated and cartoon videos at the lowest cost; find every free option.
Method: three research passes of official pages (pricing, model cards, licence files). Many pages were read through
fetch summaries; anything not confirmed is marked UNVERIFIED. **No provider below is cleared for commercial use until
its terms are read first-hand** (rule 3). Prices are the vendors' own figures as quoted; per-minute costs are computed.

## 1. Paid AI video APIs (cheapest found)

| Option | Quoted price | Per minute of video (computed) | Notes |
|---|---|---|---|
| Replicate, Wan 2.2 fast, 720p | $0.10 per video (replicate.com/blog/wan-22); 5 s clip length inferred | ≈ $1.20 | Commercial terms UNVERIFIED |
| Alibaba Model Studio, wan2.6-i2v-flash, 720p silent | $0.025/s (alibabacloud.com/help/en/model-studio/model-pricing) | $1.50 | Image-to-video; one-time 50 s free on some wan2.1 models |
| MiniMax Hailuo-2.3-Fast 768P | $0.19 per 6 s (platform.minimax.io pricing) | ≈ $1.90 | |
| fal PixVerse v6, 720p | $0.045/s (fal.ai model page) | $2.70 | |
| Google Veo 3.1 Fast, 720p | $0.10/s (third-party restatement, UNVERIFIED) | $6.00 | Official page not read |
| Cloudflare Workers AI video models | price not published (dashboard only) | UNVERIFIED | 10,000 free neurons/day apply to Workers AI generally (CF-01) |

## 2. Open video models on free GPU

| Model | Licence (as quoted on the model card) | Hardware | Image-to-video |
|---|---|---|---|
| Wan2.1 T2V-1.3B | Apache 2.0 | 8.19 GB VRAM; ≈ 4 min per 5 s 480p on an RTX 4090 (card) | T2V only (14B I2V exists, UNVERIFIED) |
| Wan2.2 TI2V-5B | Apache 2.0 | ≥ 24 GB for 720p; "under 9 minutes" per 5 s 720p on a 4090 | Yes |
| LTX-2 / 2.3 | LTX-2 community licence (revenue threshold per third parties, UNVERIFIED) | 22B, distilled variant exists | Yes |
| HunyuanVideo 1.5 | Tencent community licence (territory exclusions per third parties, UNVERIFIED) | 14 GB with offload | Yes |
| Mochi 1 | Apache 2.0 | ≈ 22 GB | No |

Free compute: Kaggle (≈ 30 GPU h/week on T4/P100, community-reported, terms on commercial use of outputs UNVERIFIED,
CLI `kaggle kernels push` UNVERIFIED); Colab free (no API, UI-only use required by its FAQ: not automatable); Hugging
Face ZeroGPU (5 min/day on a free account: too small).
ESTIMATE: Wan2.1-1.3B on a Kaggle T4 ≈ 12–16 min per 5 s 480p clip → ≈ 80 usable clips/week after overhead.

## 3. Cartoon animation (free, scriptable)

- Safe: Rhubarb Lip Sync (MIT, CLI, mouth-cue JSON from the voice), Motion Canvas (MIT), Manim (MIT), Godot (MIT, own
  output), Blender (scripted with `bpy`; licence page not read), RIFE ncnn (MIT, CPU) for frame interpolation,
  Real-ESRGAN (BSD-3) for upscaling; CC0 assets: Kenney, Open Peeps, Humaaans.
- Remotion: free only for individuals and companies up to 3 people.
- Avoid: Wav2Lip ("any form of commercial use is strictly prohibited"); anything that ships InsightFace weights
  ("non-commercial research use only"), which includes LivePortrait's and Hallo's default pipelines.

## 4. Recommended path (lowest cost first)

1. **Now, free:** current studio pipeline: Workers AI FLUX.1 [schnell] stills + 2.5D depth parallax + Pixabay real
   footage + code-made motion + cinematic grade + music/SFX. Only paid part: the script (Anthropic).
2. **Free hero motion:** Wan2.1-1.3B (Apache 2.0) on Kaggle for 8–12 short moving shots per video, upscaled. Needs a
   Kaggle account/token and a first-hand read of Kaggle's terms; built as an optional stage.
3. **Low cost if needed:** a few paid hero clips (≈ $0.10 per 5 s clip quoted for Replicate Wan 2.2 fast), only after
   the provider's commercial terms are read and the owner approves a cap.
4. **Cartoon characters that talk:** layered character art + Rhubarb mouth cues, rendered by code (later stage).
5. **Cost cut on the script:** a cheaper Claude model for drafting is an owner choice (the sample's script cost most).
