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

- Deployed from branch `ccr-b1e90a39-0g1b1l` with the one-line deploy (clone + `apps/studio/deploy.sh`), which
  prints the commit and a temporary trycloudflare link. Last deploy included the voice-pack upload (commit b5a63a1
  or later). Not yet deployed: commits after it (render to temp file, cost-column fix) — next deploy picks them up.
- Settings done by the owner: Cloudflare account ID + Workers AI token, Pixabay key (tests reported done).
- Sample #1 (Seneca, Marathi) on the server: pictures generated (21 AI scenes / 51 shots, 8 stock clips), rendered
  without voice; the owner then uploaded the Marathi voice pack (Sanjay) — result not yet reported.
- Permanent link: the owner's main domain carries the trading app — **never move its nameservers**. A second
  domain was added to Cloudflare (DNS records empty) and its nameservers were being switched at Hostinger; the
  tunnel is now live (Zero Trust tunnel `amw-studio`, route `studio.<second domain>` → `http://studio:8080`, token in
  the server `.env` as `CF_TUNNEL_TOKEN`); `/healthz` answers 200 and the dashboard asks for the password. The
  quick trycloudflare tunnel is off.

## 3. Work in progress outside the repo (session scratch, lost if the session ends)

- Hindi and English job folders (translated, fact-check PASS; cost hi 0.38 / en 0.29 USD) were sent to the owner
  as zips to import; not yet imported.
- Free TTS runs in the session: done = Marathi Sanjay (pack sent). Queued/running = Marathi Sunita, English Thoma,
  English Mary, Hindi Rohit, Hindi Divya (~30–90 min each, two at a time). Packs are zipped automatically and must
  be sent to the owner. If the session is gone, regenerate with `tts_parler`-equivalent code (speaker names from the
  model card: mr Sanjay/Sunita, hi Rohit/Divya, en Thoma/Mary) — sentence split must equal `pipeline.sentences`.

## 4. Spend so far (ESTIMATE, list price × usage)

Sample #1 Marathi 2.44 USD (includes a 0.98 USD held worst case from a lost first call — reconcile in the Anthropic
Console); Hindi translation 0.38; English 0.29. Caps: 5 USD per video, 50 USD pilot (D9).

## 5. Next steps (in order)

1. Owner reports the Marathi video with the Sanjay voice; collect score/feedback verbatim (D5) — no score recorded yet.
2. Send the remaining voice packs as they finish; owner imports the hi/en job zips, runs "resume", uploads packs.
3. Finish the permanent link on the second domain (tunnel token → `.env`, redeploy).
4. Open owner items: music track (D10), Kaggle terms first-hand before enabling motion, foreign-language TTS
   (Parler covers Indian languages + English only), visual check of non-Devanagari fonts and RTL.
5. Enterprise backlog (D21): users/roles, encrypted secrets, CI for apps/studio, DB-backed queue, backups; deploy a
   merged tag instead of the work branch.

## 6. Working with the owner

Marathi replies, short. Mobile only, no CLI except pasting one block into the VPS terminal. **One step at a time**
("झाले" before the next step); long lists confuse. Give direct links. Never ask for keys in chat (Settings page or the
secure credential form only). Never touch the trading app, BagMitra, or the main domain's DNS.
