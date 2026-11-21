# AMW Studio (sample-first build)

A lean production line plus a basic dashboard, built for owner decision D15 (2026-11-21): "only the coding that is
needed, a package ready to deploy, then improve stage by stage". It runs one job at a time:

`04 research -> 05 script (Anthropic) -> 06 fact-check (Anthropic + exact quote check) -> 07 voice -> 09 timeline ->
08 code-made visuals -> 11 thumbnail -> 10 render + QC -> 16 gate (auto part) -> manifest`

Output per job (`data/jobs/<id>/`): `final_1080p.mp4` (H.264 High, 8 Mbps VBR target, 30 fps CFR, AAC-LC 384k 48 kHz,
-14 LUFS / -1 dBTP when a voice is present), `thumbnail.png`, `captions_mr.srt`, `qc_report.json`, `gate_report.json`,
`manifest.json` (provider, licence, cost per stage). No upload to YouTube, no OAuth (D1).

This is a separate, minimal app. It does not replace the `packages/` 3A platform; it reuses only the Mukta fonts.

## Deploy (Docker)

Needs Docker with the compose plugin. All commands run in this folder on the server.

1. `cp .env.example .env`, then fill in `.env` on the server only (never commit it):
   - `AMW_SECRET_ANTHROPIC_API_KEY`: the Anthropic API key. Also set a spend limit in the Anthropic Console.
   - `AMW_DASHBOARD_PASSWORD`: a long password. The app refuses to start without one.
2. `docker compose up -d --build`
3. Open the dashboard:
   - phone: the `tunnel` service (Cloudflare quick tunnel) prints an HTTPS link:
     `docker compose logs tunnel | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1`.
     No server port is opened. The link changes when the tunnel restarts. Quick tunnels are Cloudflare's test
     service (no uptime guarantee); a named tunnel on your own domain is the next step.
   - computer: `ssh -L 8080:127.0.0.1:8080 <server>`, then `http://localhost:8080`.
   The password is the only lock: use a long one. 10 wrong passwords from one address in 15 minutes lock it out
   for the rest of the window.
4. Health: `curl http://127.0.0.1:8080/healthz`.

Resource caps are in `compose.yaml` (`AMW_CPUS`, default 1 CPU; `AMW_MEM`, default 2 GB; low CPU shares).
Rendering waits outside NSE market hours (Mon–Fri 09:00–15:45 IST) while `AMW_BLOCK_MARKET_HOURS=1`.
Exchange holidays are not modelled, so the guard errs on the side of waiting.

## Use

- **New job**: title, category, length, the research pack (`.md`), optionally a public-domain source text and the
  exact quote to verify. The script and fact-check stages make paid calls, refused before the request when the
  worst case would pass the per-video cap (default USD 5) or the pilot cap (default USD 50).
- **Voice**: three ways.
  1. Upload an owner recording on the job page. The job re-renders from stage 07 with no paid call.
  2. Free local TTS (AI4Bharat Indic Parler-TTS, Apache-2.0): build with `WITH_TTS=1` in `.env`, set `HF_TOKEN`
     (Hugging Face read token of an account that accepted the model's terms) and pick voice "Indic Parler-TTS".
     On CPU this is slow; a GPU-less 2-vCPU server can take hours for an 8-minute script.
  3. None: the video renders with a silent track and QC marks the voice checks FAIL (voice pending).
- **Re-run from a stage**: on the job page. Re-running 05/06 makes new paid calls.

## Import sample #1

The sample #1 job folder is delivered privately (it contains the private study text, so it is not in git). Copy the
folder into `data/jobs/` on the server; it appears on the dashboard. To add the voice later, upload the recording on
its page or re-run it from `07_voice` with TTS enabled.

## Known gaps (next stages)

- Category `finance` is blocked by the gate: the SEBI rule pack is not wired into this build.
- The 100-point score and approval are the owner's; the gate here is the automated part only.
- Timings without a voice are an estimate; with an uploaded recording they are scaled to its length, not
  aligned word by word.
- One worker, one job at a time. A job interrupted by a restart is resumed at startup; queued-but-not-started jobs
  are resumed too.
- Costs are estimates from list prices; reconcile them with the Anthropic Console.
