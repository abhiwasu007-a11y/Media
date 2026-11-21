# HANDOVER — AMW Studio (sample-first build), state at 2026-11-21

Read this first in a new session, then `IMPLEMENTATION_PROGRESS.md` (decisions D13–D22 and audit A1). Public repo:
no secrets, no server details, no book text here.

## 1. What exists

- **App:** `apps/studio/` — lean production line + password-protected dashboard, Docker deploy. Separate from the
  `packages/` 3A platform (it only reuses the Mukta fonts). README in that folder is the operator guide.
- **Pipeline stages:** 04 research → 05 script (Anthropic Opus 5.5, D21) → 06 fact-check → 05b picture plan →
  08a pictures/clips → 08b motion (optional) → 07 voice → 09 timeline/SRT → 08 visuals → 11 thumbnail → 10 render
  → 10 QC → 16 gate (auto part) → manifest. A re-run stage re-runs everything after it.
- **Free sources (D17):** AI pictures = Cloudflare Workers AI FLUX.1 [schnell] free allocation (CF-01); B-roll =
  Pixabay (STK-02); SFX code-made; parallax depth = Depth-Anything-V2-Small (Apache-2.0); fonts Mukta/Noto (OFL).
  Paid BFL is opt-in only. Kaggle Wan2.1 motion stage exists but is OFF and never live-tested.
- **Video types:** long 16:9 and Shorts 9:16. **Languages:** 22 (D22); "Make language versions" reuses pictures.
- **Voice:** owner recording upload, or **voice pack** (zip of per-sentence free TTS audio + voice.json; exact
  timing). Free TTS = AI4Bharat Indic Parler-TTS, run OFF the server (too heavy for the shared VPS: 2 GB cap).
- **Settings page:** keys and options on the dashboard (data/settings.json 0600, write-only secrets, audit log,
  free connection tests). `CF_TUNNEL_TOKEN` (permanent link) is the only value that must go in `.env`.
- **Security/ops (audit A1):** same-origin POST check, upload/zip caps, persistent queue, per-stage market-hours
  guard, reserved LLM cost before each call, reply cache, container hardening. 7 tests: `cd apps/studio && pytest -q tests`.

## 2. Deployed state (owner's VPS, owner runs every command)

- Permanent dashboard link on the owner's SECOND domain via a Cloudflare named tunnel (token in the server `.env`).
  The main domain (trading app) is untouched. Deploy = the one-line clone + `apps/studio/deploy.sh` (prints commit).
- Server limits agreed (D23): `AMW_CPUS=2.0` (low CPU shares, trading app first), `AMW_MEM=3g`; deploy sets them.
- Settings saved by the owner: Cloudflare account ID + Workers AI token, Pixabay key, Kaggle username/key, HF token.
  Voice provider = kaggle (D24) until monetization, then google (needs a Google Cloud TTS key; free 1M chars/month).
- Sample #1 (Seneca, Marathi): pictures + Sanjay voice pack rendered (~10 min, 540 MB at 8 Mbps); a Kaggle voice run
  failed on a slug bug (fixed in code, not yet re-run on the server). Sunita voice pack sent to the owner.
- Last code on the branch not yet deployed at handover time: Kaggle slug fix, quality setting + previews + downloads,
  batch form, categories + finance (D25–D28). Owner reported a downloaded 1080p file that Windows could not play
  (likely an incomplete 540 MB download over a slow link); asked to compare sizes / try the 360p file / VLC.

- Render speed-up (owner: 2 h too long): picture frames use cached OpenCV grade/shade/vignette/grain, parallax warp
  field built at half size, x264 preset veryfast. Bench on 2 CPUs: 84 -> 44 ms/frame (about half the render time).

## 3. Work in progress outside the repo (session scratch, lost if the session ends)

- Hindi/English job zips (translated, fact-check PASS) were sent; not yet imported. Voice packs sent: mr Sanjay,
  mr Sunita. Other local TTS runs were stopped (the dashboard's Kaggle voice replaces them).

## 4. Spend so far (ESTIMATE, list price × usage)

Sample #1 Marathi about 2.44 USD (includes a 0.98 USD held worst case: reconcile in the Anthropic Console);
Hindi translation 0.38; English 0.29. Caps: 5 USD per video, 50 USD pilot (D9).

## 5. Next steps (in order)

1. Owner deploys; re-run the Kaggle voice once to confirm the slug fix; owner reviews sample #1 (score verbatim, D5).
2. Owner imports the hi/en jobs, runs "resume", chooses an AI voice (or uploads packs).
3. First new-topic videos through "+ New job" / "+ Many videos" (categories incl. finance with disclaimer).
4. Before monetizing: switch voice provider to google (Kaggle terms, KG-01); finance videos with the owner's voice;
   lawyer review of the disclaimer; Kaggle motion stays off.
5. Enterprise backlog (D21): users/roles, encrypted secrets, DB-backed queue, backups, deploy from a merged tag.

## 6. Working with the owner

Marathi replies, short. Mobile only, no CLI except pasting one block into the VPS terminal. **One step at a time**
("झाले" before the next step); long lists confuse. Give direct links. Never ask for keys in chat (Settings page or the
secure credential form only). Never touch the trading app, BagMitra, or the main domain's DNS.
