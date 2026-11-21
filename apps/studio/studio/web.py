"""Basic dashboard: jobs, stage status, cost per stage, QC, gate, video, downloads; new job; voice upload.

Password-protected (HTTP Basic, AMW_DASHBOARD_USER / AMW_DASHBOARD_PASSWORD), same-origin check on every write,
failed-login lockout. One worker thread runs jobs one at a time; the queue is persisted in data/queue.json. Heavy
stages (voice, pictures, motion, render, QC) wait outside market hours when AMW_BLOCK_MARKET_HOURS=1 (shared VPS rule, D1).
"""

import contextlib
import html
import json
import math
import os
import queue
import re
import secrets
import shutil
import subprocess
import threading
import time
import traceback
import urllib.parse
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.concurrency import run_in_threadpool

from . import config, llm, pipeline
from .languages import LANGS

app = FastAPI(title="AMW Studio", docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(Exception)
async def _show_error(request: Request, exc: Exception):
    """Owner-only dashboard: show the error type and message (and log the trace) instead of a bare 500."""
    import logging  # noqa: PLC0415
    import traceback  # noqa: PLC0415

    logging.getLogger("studio").error("unhandled error on %s\n%s", request.url.path, traceback.format_exc())
    return PlainTextResponse(f"Dashboard error on {request.url.path}: {type(exc).__name__}: {str(exc)[:500]}", status_code=500)


security = HTTPBasic()
Q: "queue.Queue[tuple[str, str | None]]" = queue.Queue()
SERVE = {
    "final_1080p.mp4",
    "preview_360p.mp4",
    "export_720p.mp4",
    "export_480p.mp4",
    "thumbnail.png",
    "captions_mr.srt",
    "qc_report.json",
    "gate_report.json",
    "manifest.json",
    "script.json",
    "fact_check.json",
    "timings.json",
    "ledger.json",
    "visuals.mp4",
}
CAP_RE = re.compile(r"captions_[a-z]{2}\.srt")
JOB_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,120}")
IST = timezone(timedelta(hours=5, minutes=30))
# stages that use the shared CPU heavily: they wait outside market hours (the guard is checked before each one)
HEAVY_STAGES = {"07_voice", "08a_assets", "08b_motion", "08_visuals", "10_render", "10_qc"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".webm", ".mp4"}
# non-finance categories use the general rules (fact-check, no invented facts, no medical/legal/financial advice);
# finance needs the SEBI rule pack and stays blocked by the gate in this build
CATEGORY_LABELS = {
    "philosophy": "तत्त्वज्ञान (Philosophy)",
    "motivation": "प्रेरणा / स्वयं-विकास (Motivation, self-help)",
    "story": "कथा / बोधकथा (Stories, moral tales)",
    "history": "इतिहास (History)",
    "mythology": "पुराणकथा / अध्यात्म (Mythology, spirituality)",
    "science": "विज्ञान (Science)",
    "technology": "तंत्रज्ञान / AI (Technology)",
    "education": "शिक्षण / ज्ञान (Education, general knowledge)",
    "biography": "चरित्र (Biographies)",
    "business": "व्यवसाय / करिअर (Business, careers; no investment advice)",
    "health": "आरोग्य जागरूकता (Health awareness; no medical advice)",
    "kids": "मुलांसाठी (Kids; mark 'made for kids' on YouTube)",
    "finance": "शेअर बाजार शिक्षण (Finance education: SEBI rules + disclaimer)",
}
CATEGORIES = tuple(CATEGORY_LABELS)
VOICE_MODES = ("none", "parler")  # plus "ai:<speaker>" for the free Kaggle voice
FORMATS = ("long_16x9", "short_9x16")


def _max_upload() -> int:
    try:
        mb = float(os.environ.get("AMW_MAX_UPLOAD_MB", "300"))
    except ValueError:
        mb = 300.0
    return int((mb if math.isfinite(mb) and mb > 0 else 300.0) * 1024 * 1024)


MAX_UPLOAD = _max_upload()
MAX_ZIP_ENTRIES = 5000
LOOPBACK = {"127.0.0.1", "::1"}
FAILS: dict[str, list[float]] = {}
FAIL_LIMIT, FAIL_WINDOW_S, FAIL_MAX_KEYS = 10, 900, 10000
_qlock = threading.Lock()


def _queue_file() -> Path:
    return config.data_dir() / "queue.json"


def _queue_load() -> list[list]:
    try:
        d = json.loads(_queue_file().read_text())
        return [x for x in d if isinstance(x, list) and len(x) == 2] if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _queue_save(items: list[list]) -> None:
    f = _queue_file()
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(items))
    os.replace(tmp, f)


def enqueue(jid: str, frm: str | None) -> None:
    """Persist (job, from_stage) in data/queue.json, then hand it to the worker."""
    with _qlock:
        items = _queue_load()
        items.append([jid, frm])
        _queue_save(items)
    Q.put((jid, frm))


def _dequeue(jid: str, frm: str | None) -> None:
    with _qlock:
        items = _queue_load()
        if [jid, frm] in items:
            items.remove([jid, frm])
            _queue_save(items)


@app.middleware("http")
async def guard(request: Request, call_next):
    """Same-origin check on writes (CSRF), upload size cap, and hardening headers on every response."""
    if request.method not in ("GET", "HEAD"):
        site = request.headers.get("sec-fetch-site")
        if site:
            same = site in ("same-origin", "none")
        else:
            src = request.headers.get("origin") or request.headers.get("referer") or ""
            same = bool(src) and urllib.parse.urlsplit(src).netloc == request.headers.get("host", "\0")
        if not same:
            return PlainTextResponse("cross-site request refused", status_code=403)
        cl = request.headers.get("content-length")
        # chunked bodies (no Content-Length, possible behind the tunnel) are allowed: the upload handlers stream to
        # disk with a running byte count and stop at the same cap
        if cl is not None and (not cl.isdigit() or int(cl) > MAX_UPLOAD + 2 * 1024 * 1024):
            return PlainTextResponse("request too large", status_code=413)
    resp = await call_next(request)
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


def save_upload(up: UploadFile, dest: Path, limit: int = MAX_UPLOAD) -> int:
    """Stream an upload to ``dest`` in 1 MB chunks with a running byte count; 413 and no file when over ``limit``."""
    n = 0
    try:
        with dest.open("wb") as f:
            while chunk := up.file.read(1024 * 1024):
                n += len(chunk)
                if n > limit:
                    raise HTTPException(413, f"upload larger than {limit // (1024 * 1024)} MB")
                f.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return n


def audio_ext(up: UploadFile) -> str:
    ext = Path(up.filename or "").suffix.lower()
    if ext not in AUDIO_EXT:
        raise HTTPException(400, "unsupported audio type; use " + " ".join(sorted(AUDIO_EXT)))
    return ext


def auth(request: Request, c: HTTPBasicCredentials = Depends(security)) -> str:
    """HTTP Basic auth; an address with 10 wrong passwords in 15 minutes is refused until the window passes."""
    peer = request.client.host if request.client else "?"
    # cf-connecting-ip is only trusted when the TCP peer is not loopback (i.e. it came through the tunnel container)
    ip = (request.headers.get("cf-connecting-ip") or peer) if peer not in LOOPBACK else peer
    now_s = time.time()
    recent = [t for t in FAILS.pop(ip, []) if now_s - t < FAIL_WINDOW_S]
    FAILS[ip] = recent  # re-inserted last, so the dict stays ordered oldest-first
    while len(FAILS) > FAIL_MAX_KEYS:
        FAILS.pop(next(iter(FAILS)))
    if len(recent) >= FAIL_LIMIT:
        raise HTTPException(429, "too many failed logins, try again later")
    user, pw = os.environ.get("AMW_DASHBOARD_USER", "owner"), os.environ.get("AMW_DASHBOARD_PASSWORD", "")
    ok = bool(pw) and secrets.compare_digest(c.username, user) and secrets.compare_digest(c.password, pw)
    if not ok:
        recent.append(now_s)
        raise HTTPException(401, "unauthorised", headers={"WWW-Authenticate": "Basic"})
    return c.username


def market_hours() -> bool:
    """NSE regular session window, Mon–Fri 09:00–15:45 IST (exchange holidays not modelled: conservative)."""
    if os.environ.get("AMW_BLOCK_MARKET_HOURS", "1") != "1":
        return False
    n = datetime.now(IST)
    return n.weekday() < 5 and (9, 0) <= (n.hour, n.minute) <= (15, 45)


def wait_market(job: Path) -> None:
    """Block (checking every 60 s) while market hours are on; the job shows queue/waiting meanwhile."""
    waited = False
    while market_hours():
        waited = True
        pipeline.set_status(job, "queue", "waiting", "market hours: heavy stage waits (D1)")
        time.sleep(60)
    if waited:
        pipeline.set_status(job, "queue", "done", "resumed after market hours")


def _before_stage(job: Path):
    def before(stage: str) -> None:
        if stage in HEAVY_STAGES:
            wait_market(job)

    return before


def _ffmpeg_audio(src: Path, dst: Path, channels: int) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-nostdin", "-loglevel", "error", "-protocol_whitelist", "file,pipe", "-i", str(src)]
        + ["-ac", str(channels), "-ar", "48000", str(dst)],
        check=True,
        timeout=600,
    )


def _convert_uploads(job: Path) -> None:
    """Convert voice/music uploads (saved by the request) in the worker, outside market hours."""
    marker = job / "convert.json"
    if not marker.exists():
        return
    todo = pipeline.rj(marker)
    wait_market(job)
    try:
        for key, (name, ch) in {"voice": ("voice.wav", 1), "music": ("music.wav", 2)}.items():
            raw = todo.get(key)
            if raw and Path(raw).name == raw and (job / raw).exists() and Path(raw).suffix.lower() in AUDIO_EXT:
                _ffmpeg_audio(job / raw, job / name, ch)
    finally:
        marker.unlink(missing_ok=True)


def _mark_convert(job: Path, key: str, raw_name: str) -> None:
    marker = job / "convert.json"
    cur = pipeline.rj(marker) if marker.exists() else {}
    cur[key] = raw_name
    pipeline.wj(marker, cur)


def worker() -> None:
    while True:
        jid, frm = Q.get()
        try:
            job = config.jobs_dir() / jid
            try:
                _convert_uploads(job)
                pipeline.set_status(job, "queue", "done", "started")
                pipeline.run(job, frm, before_stage=_before_stage(job))
            except Exception as exc:  # keep the thread alive; show the reason on the job page
                msg = f"{type(exc).__name__}: {exc}"
                print(traceback.format_exc(), flush=True)
                with contextlib.suppress(Exception):
                    pipeline.set_status(job, "queue", "failed", msg)
            _dequeue(jid, frm)
        except Exception:  # never let the worker thread die
            print(traceback.format_exc(), flush=True)
        finally:
            Q.task_done()


@app.on_event("startup")
def _start() -> None:
    if not os.environ.get("AMW_DASHBOARD_PASSWORD"):
        raise RuntimeError("AMW_DASHBOARD_PASSWORD must be set")
    pending: list[tuple[str, str | None]] = []
    for jid, frm in _queue_load():  # queued before the restart
        if isinstance(jid, str) and JOB_ID_RE.fullmatch(jid) and (config.jobs_dir() / jid / "job.json").exists():
            pending.append((jid, frm if isinstance(frm, str) else None))
    queued = {j for j, _ in pending}
    for j in sorted(config.jobs_dir().iterdir()):  # jobs interrupted mid-stage (never-started jobs are NOT auto-queued)
        try:
            if j.name in queued or not (j / "job.json").exists() or not (j / "status.json").exists():
                continue
            if any(v.get("state") in ("running", "waiting") for v in pipeline.status(j)["stages"].values()):
                pending.append((j.name, None))
        except Exception:  # one broken job must not stop the app
            print(f"startup scan skipped {j.name}", flush=True)
    with _qlock:
        _queue_save([[a, b] for a, b in pending])
    for item in pending:
        Q.put(item)
    threading.Thread(target=worker, daemon=True).start()


# ------------------------------------------------------------------ html
CSS = """
:root{--bg:#10151f;--card:#1a2232;--ink:#f5efe6;--dim:#9aa3b5;--acc:#f2a541;--ok:#6ec48c;--bad:#e05252;--line:#2a344a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,'Mukta',sans-serif}
main{max-width:1100px;margin:auto;padding:16px}a{color:var(--acc)}h1{font-size:22px;margin:8px 0 16px}
h2{font-size:17px;margin:22px 0 8px;color:var(--acc)}table{width:100%;border-collapse:collapse;background:var(--card);border-radius:10px;overflow:hidden}
td,th{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{color:var(--dim);font-weight:600}
.ok{color:var(--ok)}.bad{color:var(--bad)}.dim{color:var(--dim)}.run{color:var(--acc)}
.card{background:var(--card);border-radius:10px;padding:14px;margin:10px 0}.row{display:flex;gap:14px;flex-wrap:wrap}
.row>*{flex:1 1 300px}video,img{width:100%;border-radius:8px;background:#000}
input,select,textarea,button{font:inherit;background:#0c111a;color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:8px;width:100%}
button{background:var(--acc);color:#1a1205;font-weight:700;cursor:pointer;width:auto;padding:8px 16px}
label{display:block;margin:8px 0 4px;color:var(--dim)}pre{white-space:pre-wrap;font-size:12px;color:var(--dim)}
.wrap{overflow-x:auto}
"""


def page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html lang=mr><head><meta charset=utf-8><meta name=viewport "
        f"content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title>"
        f"<style>{CSS}</style></head><body><main>{body}</main></body></html>"
    )


def e(x: object) -> str:
    return html.escape(str(x))


def state_cls(s: str) -> str:
    if s.startswith("in queue") or s == "working now":
        return "run"
    return {"done": "ok", "failed": "bad", "running": "run", "waiting": "run"}.get(s, "dim")


def job_summary(job: Path) -> dict:
    meta = pipeline.rj(job / "job.json")
    st = pipeline.status(job)["stages"]
    cur = next((s for s in pipeline.STAGES if st.get(s, {}).get("state") != "done"), None)
    qc = pipeline.rj_or_none(job / "qc_report.json")
    gate = pipeline.rj_or_none(job / "gate_report.json")
    state = st.get(cur, {}).get("state", "queued") if cur else "complete"
    try:
        cost = llm.job_spent(job)
    except (ValueError, OSError, KeyError):  # unreadable ledger: shown as unknown; paid calls stay refused (llm raises)
        cost = float("nan")
    return {"meta": meta, "stage": cur or "—", "state": state, "cost": cost, "qc": qc, "gate": gate}


@app.get("/", response_class=HTMLResponse)
def index(_: str = Depends(auth)) -> HTMLResponse:
    cfg = config.load()
    jobs = sorted((j for j in config.jobs_dir().iterdir() if (j / "job.json").exists()), key=lambda p: p.name, reverse=True)
    rows = ""
    with _qlock:
        order = [jid for jid, _ in _queue_load()]
    for j in jobs:
        s = job_summary(j)
        if j.name in order:
            pos = order.index(j.name)
            s["state"] = "working now" if pos == 0 else f"in queue #{pos}"
        qc = "—" if not s["qc"] else ("<span class=ok>PASS</span>" if s["qc"]["all_pass"] else "<span class=bad>FAIL</span>")
        gate = (
            "—"
            if not s["gate"]
            else ("<span class=ok>PASS</span>" if s["gate"]["auto_pass"] else "<span class=bad>BLOCKED</span>")
        )
        rows += (
            f"<tr><td><a href='/jobs/{e(j.name)}'>{e(s['meta'].get('title', j.name))}</a><div class=dim>{e(j.name)}</div></td>"
            f"<td>{e(s['meta'].get('category'))}</td><td>{e(s['stage'])} <span class={state_cls(s['state'])}>{e(s['state'])}</span></td>"
            f"<td>${s['cost']:.2f}</td><td>{qc}</td><td>{gate}</td></tr>"
        )
    try:
        spent = llm.pilot_spent()
    except (ValueError, OSError, KeyError):  # an unreadable ledger: shown as unknown (paid calls refuse on their own)
        spent = float("nan")
    body = (
        f"<h1>AMW Studio</h1><div class=row><div class=card>Pilot spend <b>${spent:.2f}</b> / ${cfg.pilot_cap_usd:.2f}"
        f"<div class=dim>Per-video cap ${cfg.per_video_cap_usd:.2f} · model {e(cfg.model)}</div></div>"
        f"<div class=card>Queue: {Q.qsize()} waiting · {'<span class=bad>market hours: render paused</span>' if market_hours() else '<span class=ok>render allowed</span>'}"
        f"<div><a href='/jobs/new'>+ New job</a> · <a href='/jobs/batch'>+ Many videos</a> · <a href='/settings'>Settings</a></div></div></div>"
        f"<form class=card method=post action=/jobs/import enctype=multipart/form-data><label>Import a job folder (.zip)</label>"
        f"<input type=file name=bundle accept='.zip' required><p><button>Import</button></p></form>"
        f"<div class=wrap><table><tr><th>Job</th><th>Category</th><th>Stage</th><th>Cost</th><th>QC</th><th>Gate</th></tr>"
        f"{rows or '<tr><td colspan=6 class=dim>No jobs yet</td></tr>'}</table></div>"
    )
    return page("AMW Studio", body)


@app.post("/jobs/import")
def import_job(bundle: UploadFile = File(...), _: str = Depends(auth)):
    """Import a zipped job folder (one top folder holding job.json). Paths and sizes are checked before extraction."""
    raw = config.data_dir() / f"import-{secrets.token_hex(4)}.zip"
    save_upload(bundle, raw)
    try:
        with zipfile.ZipFile(raw) as z:
            infos = [i for i in z.infolist() if not i.is_dir()]
            if len(z.infolist()) > MAX_ZIP_ENTRIES:
                raise HTTPException(400, f"zip has more than {MAX_ZIP_ENTRIES} entries")
            if sum(i.file_size for i in infos) > MAX_UPLOAD * 3:
                raise HTTPException(400, "zip content too large when unpacked")
            names = [i.filename for i in infos]
            tops = {n.split("/", 1)[0] for n in names}
            if len(tops) != 1 or not JOB_ID_RE.fullmatch(next(iter(tops))) or f"{next(iter(tops))}/job.json" not in names:
                raise HTTPException(400, "zip must hold one job folder with job.json")
            if any(".." in n.split("/") or n.startswith("/") or "\\" in n for n in names):
                raise HTTPException(400, "unsafe path in zip")
            jid = next(iter(tops))
            if (config.jobs_dir() / jid).exists():
                raise HTTPException(409, "a job with this id already exists")
            z.extractall(config.jobs_dir(), members=names)
    except zipfile.BadZipFile as exc:
        raise HTTPException(400, "not a zip file") from exc
    finally:
        raw.unlink(missing_ok=True)
    return RedirectResponse(f"/jobs/{jid}", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
def settings_page(msg: str = "", _: str = Depends(auth)) -> HTMLResponse:
    rows = ""
    for name, label, kind, default, opts in config.FIELDS:
        if kind == "secret":
            state = "<span class=ok>set</span>" if config.is_set(name) else "<span class=bad>not set</span>"
            field = f"<input type=password name='{name}' autocomplete=new-password placeholder='leave empty to keep'>"
            label_html = f"{e(label)} · {state}"
        elif kind == "select":
            cur = config.get(name, default)
            field = (
                f"<select name='{name}'>"
                + "".join(f"<option {'selected' if o == cur else ''}>{e(o)}</option>" for o in opts)
                + "</select>"
            )
            label_html = e(label)
        else:
            field = f"<input name='{name}' value='{e(config.get(name, default))}'>"
            label_html = e(label)
        rows += f"<label>{label_html}</label>{field}"
    tests = "".join(
        f"<form method=post action='/settings/test/{t}' style='display:inline'><button>Test {t}</button></form> "
        for t in ("anthropic", "cloudflare", "pixabay", "kaggle", "google_tts")
    )
    body = (
        f"<p><a href='/'>← dashboard</a></p><h1>Settings</h1>"
        f"{'<div class=card>' + e(msg) + '</div>' if msg else ''}"
        f"<form class=card method=post action=/settings>{rows}<p><button>Save</button></p>"
        f"<p class=dim>Keys are stored only on this server (data/settings.json, mode 0600) and are never shown again. "
        f"Every change is written to the audit log (names only, never values).</p></form>"
        f"<div class=card><b>Connection tests</b> (free calls only)<p>{tests}</p></div>"
    )
    return page("Settings", body)


@app.post("/settings")
async def settings_save(request: Request, user: str = Depends(auth)):
    form = await request.form()
    try:
        changed = config.update({k: str(v) for k, v in form.items()}, user)
        msg = f"saved: {', '.join(changed)}" if changed else "no change"
    except ValueError as exc:
        msg = f"not saved: {exc}"
    return RedirectResponse(f"/settings?msg={urllib.parse.quote(msg)}", status_code=303)


@app.post("/settings/test/{provider}")
def settings_test(provider: str, user: str = Depends(auth)):
    try:
        msg = f"{provider}: OK, {connection_test(provider)}"
    except Exception as exc:  # report, never the key
        msg = f"{provider}: FAILED, {type(exc).__name__}: {str(exc)[:160]}"
    config.audit(user, "settings.test", {"provider": provider, "ok": msg.startswith(f"{provider}: OK")})
    return RedirectResponse(f"/settings?msg={urllib.parse.quote(msg)}", status_code=303)


def connection_test(provider: str) -> str:
    """Free checks only: token count, account lookup, one search. No paid generation."""
    import json as _json  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    def get(url: str, headers: dict) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": "amw-studio/1", **headers})  # noqa: S310
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - fixed https endpoints
            return _json.loads(r.read())

    if provider == "anthropic":
        import anthropic  # noqa: PLC0415

        c = anthropic.Anthropic(api_key=config.get("AMW_SECRET_ANTHROPIC_API_KEY"), base_url="https://api.anthropic.com")
        n = c.messages.count_tokens(model=config.load().model, messages=[{"role": "user", "content": "नमस्कार"}])
        return f"token count works ({n.input_tokens} tokens), model {config.load().model}"
    if provider == "cloudflare":
        acc, tok = config.get("AMW_CF_ACCOUNT_ID"), config.get("AMW_SECRET_CF_AI_TOKEN")
        d = get("https://api.cloudflare.com/client/v4/user/tokens/verify", {"Authorization": f"Bearer {tok}"})
        if not d.get("success"):
            raise RuntimeError("token not valid")
        return f"token {d['result'].get('status')}; account id {'set' if acc else 'MISSING'}"
    if provider == "pixabay":
        q = urllib.parse.urlencode({"key": config.get("AMW_SECRET_PIXABAY_API_KEY"), "q": "clock", "per_page": 3})
        d = get(f"https://pixabay.com/api/videos/?{q}", {})
        return f"{d.get('totalHits', 0)} clips found for 'clock'"
    if provider == "google_tts":
        from .tts_google import month_used  # noqa: PLC0415

        q = urllib.parse.urlencode({"languageCode": "mr-IN", "key": config.get("AMW_SECRET_GOOGLE_TTS_KEY")})
        try:
            d = get(f"https://texttospeech.googleapis.com/v1/voices?{q}", {})
        except Exception as exc:  # the URL holds the key: report the status only
            raise RuntimeError(f"Google TTS check failed: HTTP {getattr(exc, 'code', '?')}") from None
        n = sum(1 for v in d.get("voices", []) if "Chirp3-HD" in v.get("name", ""))
        return f"{n} Marathi Chirp3-HD voices available; used this month {month_used()} characters"
    if provider == "kaggle":
        from . import motion_kaggle  # noqa: PLC0415

        d = motion_kaggle._call(
            config.get("AMW_KAGGLE_USERNAME"), config.get("AMW_SECRET_KAGGLE_KEY"), "ListKernels", {"mine": True, "pageSize": 1}
        )
        return f"authenticated ({len(d.get('kernels', []))} own notebook listed)"
    raise HTTPException(404)


@app.get("/jobs/new", response_class=HTMLResponse)
def new_form(_: str = Depends(auth)) -> HTMLResponse:
    body = """<h1>New job</h1><form class=card method=post action=/jobs enctype=multipart/form-data>
<label>Title</label><input name=title required>
<label>Category (विषय)</label><select name=category>{CATEGORY_OPTIONS}</select>
<label>Language</label><select name=language>{LANG_OPTIONS}</select>
<label>Video type</label><select name=format><option value=long_16x9>Long video 16:9 (YouTube)</option>
<option value=short_9x16>Short 9:16 (YouTube Shorts / Reels, under 60 s)</option></select>
<label>Length in minutes (long video only)</label><input name=minutes type=number step=0.5 value=8.5>
<label>Topic notes: what the video is about (type or paste here; any language)</label>
<textarea name=brief_text rows=10 placeholder="Topic, key ideas, story idea, outline, facts with sources..."></textarea>
<label>…or upload the notes as a file (.md / .txt)</label><input type=file name=brief accept=".md,.txt">
<label>Public-domain source text for quote check (.txt, optional)</label><input type=file name=source accept=".txt">
<label>Quote (exact text, optional)</label><input name=quote><label>Quote credit</label><input name=quote_credit>
<label>Voice</label><select name=voice_mode>{VOICE_OPTIONS}<option value=none>no voice yet (upload later)</option></select>
<label style='display:flex;gap:8px;align-items:center'><input type=checkbox name=has_fiction value=1 style='width:auto'>
Story contains fictional characters/events</label>
<p class=dim>Paid step: the script and fact-check use the Anthropic API within the per-video cap.</p>
<button>Create and run</button></form>"""
    from .languages import LANGS  # noqa: PLC0415

    opts = "".join(f"<option value={c}>{e(v[1])} ({e(v[0])})</option>" for c, v in LANGS.items())
    vopts = "<option value='ai:male'>AI voice – पुरुष (free)</option><option value='ai:female'>AI voice – स्त्री (free)</option>"
    return page(
        "New job",
        body.replace("{LANG_OPTIONS}", opts).replace("{VOICE_OPTIONS}", vopts).replace("{CATEGORY_OPTIONS}", cat_options()),
    )


BATCH_FORM = """<p><a href='/'>← dashboard</a></p><h1>Many videos at once</h1>
<form class=card method=post action=/jobs/batch>
<label>Videos: one block per video, separated by a line with only <b>---</b>. First line = title, next lines = topic notes.</label>
<textarea name=blocks rows=16 placeholder="मार्कस ऑरेलियस: जे हातात आहे ते करा
Idea: control what you can... story idea... outline...
---
एपिक्टेटस: काळजी कशाची करायची?
Idea: ... story ... outline ..."></textarea>
<label>Category (विषय)</label><select name=category>{CATEGORY_OPTIONS}</select>
<label>Language</label><select name=language>{LANG_OPTIONS}</select>
<label>Video type</label><select name=format><option value=long_16x9>Long video 16:9</option>
<option value=short_9x16>Short 9:16 (under 60 s)</option></select>
<label>Length in minutes (long video only)</label><input name=minutes type=number step=0.5 value=8.5>
<label>Voice</label><select name=voice_mode><option value='ai:male'>AI voice – पुरुष (free)</option>
<option value='ai:female'>AI voice – स्त्री (free)</option><option value=none>no voice yet</option></select>
<label><input type=checkbox name=has_fiction value=1 style='width:auto'> Stories contain fictional characters/events</label>
<p class=dim>Each video becomes its own job in the queue; they are made one after another. Paid part: the script
(about 1–2 USD per long video), within the per-video and pilot caps.</p>
<button>Queue all videos</button></form>"""


def cat_options() -> str:
    return "".join(f"<option value={c}>{e(lbl)}</option>" for c, lbl in CATEGORY_LABELS.items())


@app.get("/jobs/batch", response_class=HTMLResponse)
def batch_form(_: str = Depends(auth)) -> HTMLResponse:
    opts = "".join(f"<option value={c}>{e(v[1])} ({e(v[0])})</option>" for c, v in LANGS.items())
    return page("Many videos", BATCH_FORM.replace("{LANG_OPTIONS}", opts).replace("{CATEGORY_OPTIONS}", cat_options()))


@app.post("/jobs/batch")
def batch_create(
    blocks: str = Form(...),
    category: str = Form("philosophy"),
    language: str = Form("mr"),
    format: str = Form("long_16x9"),  # noqa: A002 - form field name
    minutes: float = Form(8.5),
    voice_mode: str = Form("ai:male"),
    has_fiction: str = Form(""),
    user: str = Depends(auth),
):
    """Create one queued job per block (title line + notes). Validation is the same as for a single job."""
    items = [b.strip() for b in re.split(r"(?m)^\s*---\s*$", blocks) if b.strip()]
    if not items:
        raise HTTPException(400, "write at least one video block")
    if len(items) > 50:
        raise HTTPException(400, "at most 50 videos per batch")
    made = []
    for b in items:
        title, _, notes = b.partition("\n")
        if len(notes.strip()) < 30:
            raise HTTPException(400, f"notes too short for: {title[:60]}")
    for b in items:
        title, _, notes = b.partition("\n")
        r = create(
            title=title,
            category=category,
            minutes=minutes,
            format=format,
            language=language,
            voice_mode=voice_mode,
            quote="",
            quote_credit="",
            has_fiction=has_fiction,
            brief_text=notes,
            brief=None,
            source=None,
            _=user,
        )
        made.append(r.headers["location"].rsplit("/", 1)[-1])
    config.audit(user, "jobs.batch", {"count": len(made)})
    return RedirectResponse("/", status_code=303)


@app.post("/jobs")
def create(
    title: str = Form(...),
    category: str = Form(...),
    minutes: float = Form(8.5),
    format: str = Form("long_16x9"),  # noqa: A002 - form field name
    language: str = Form("mr"),
    voice_mode: str = Form("none"),
    quote: str = Form(""),
    quote_credit: str = Form(""),
    has_fiction: str = Form(""),
    brief_text: str = Form(""),
    brief: UploadFile | None = File(None),
    source: UploadFile | None = File(None),
    _: str = Depends(auth),
):
    if category not in CATEGORIES:
        raise HTTPException(400, "unknown category")
    speaker = None
    if voice_mode.startswith("ai:"):
        speaker = voice_mode[3:]
        if speaker not in ("male", "female"):
            raise HTTPException(400, "unknown voice")
        voice_mode = "ai"
    elif voice_mode not in VOICE_MODES:
        raise HTTPException(400, "unknown voice mode")
    if format not in FORMATS:
        raise HTTPException(400, "unknown video type")
    if language not in LANGS:
        raise HTTPException(400, "unknown language")
    if not math.isfinite(minutes) or not 0.5 <= minutes <= 120:
        raise HTTPException(400, "minutes must be between 0.5 and 120")
    title = title.strip()[:200]
    if not title:
        raise HTTPException(400, "title required")
    has_file = bool(brief and brief.filename)
    if not has_file and len(brief_text.strip()) < 30:
        raise HTTPException(400, "write the topic notes (at least a few lines) or upload a notes file")
    if len(brief_text) > 200_000:
        raise HTTPException(413, "notes too long")
    jid = (
        datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        + "-"
        + (re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:24] or "job")
        + "-"
        + secrets.token_hex(2)
    )
    job = config.jobs_dir() / jid
    job.mkdir()
    try:
        if has_file:
            save_upload(brief, job / "brief.md")
        else:
            (job / "brief.md").write_text(brief_text.strip() + "\n", encoding="utf-8")
        if source and source.filename:
            save_upload(source, job / "source.txt")
        short = format == "short_9x16"
        if short:
            minutes = 0.9
        meta = {
            "id": jid,
            "title": title,
            "category": category,
            "format": format,
            "language": language,
            "minutes": minutes,
            "min_minutes": 0.6 if short else max(1, minutes - 1),
            "max_minutes": 1.0 if short else minutes + 1.2,
            "voice_mode": voice_mode,
            "speaker_gender": speaker,
            "quote": quote,
            "quote_credit": quote_credit,
            "has_fiction": bool(has_fiction),
            "created_utc": pipeline.now(),
        }
        pipeline.wj(job / "job.json", meta)
    except BaseException:
        shutil.rmtree(job, ignore_errors=True)
        raise
    enqueue(jid, None)
    return RedirectResponse(f"/jobs/{jid}", status_code=303)


def get_job(jid: str) -> Path:
    if not JOB_ID_RE.fullmatch(jid) or jid in (".", ".."):
        raise HTTPException(404)
    job = config.jobs_dir() / jid
    if not (job / "job.json").exists():
        raise HTTPException(404)
    return job


@app.get("/jobs/{jid}", response_class=HTMLResponse)
def job_page(jid: str, _: str = Depends(auth)) -> HTMLResponse:
    job = get_job(jid)
    s = job_summary(job)
    st = pipeline.status(job)["stages"]
    costs: dict[str, float] = {}
    try:
        ledger = llm.ledger_rows(job)
    except (ValueError, OSError):
        ledger = []
    for r in ledger:
        k = (
            "05_script"
            if r["stage"] in ("05_script", "05_script_continuation") or r["stage"].startswith("05_translate")
            else r["stage"]
        )
        costs[k] = costs.get(k, 0.0) + r["cost_usd"]
    rows = "".join(
        f"<tr><td>{e(k)}</td><td class={state_cls(st.get(k, {}).get('state', ''))}>{e(st.get(k, {}).get('state', 'pending'))}</td>"
        f"<td>${costs.get(k, 0.0):.4f}</td><td><pre>{e(st.get(k, {}).get('note', ''))[:600]}</pre></td></tr>"
        for k in pipeline.STAGES
    )
    media = ""
    if (job / "final_1080p.mp4").exists():
        play = "preview_360p.mp4" if (job / "preview_360p.mp4").exists() else "final_1080p.mp4"
        media += (
            f"<div><video controls preload=metadata src='/jobs/{e(jid)}/files/{play}' poster='/jobs/{e(jid)}/files/thumbnail.png'></video>"
            f"<div class=dim>वरचा प्लेयर हलकी (360p) फाइल चालवतो. YouTube साठी खालची 1080p फाइल डाउनलोड करा.</div>"
            + "<div class=card><b>डाउनलोड</b><ul style='margin:6px 0 0 18px;padding:0'>"
            + "".join(
                (
                    f"<li><a href='/jobs/{e(jid)}/files/{f}' download>{lbl}</a> · {(job / f).stat().st_size / 1e6:.0f} MB</li>"
                    if (job / f).exists()
                    else (
                        f"<li>{lbl} · <form method=post action='/jobs/{e(jid)}/export/{r}' style='display:inline'>"
                        f"<button style='padding:2px 10px'>बनवा</button></form> <span class=dim>(गरज असेल तरच)</span></li>"
                        if r
                        else f"<li>{lbl} · <span class=dim>प्लेयरच्या खालचे बटण वापरा</span></li>"
                    )
                )
                for f, lbl, r in (
                    ("final_1080p.mp4", "1080p – YouTube साठी (उत्तम)", ""),
                    ("export_720p.mp4", "720p – मध्यम", "720"),
                    ("export_480p.mp4", "480p – हलकी", "480"),
                    ("preview_360p.mp4", "360p – मोबाइलवर पाहण्यासाठी", ""),
                )
            )
            + "</ul></div></div>"
        )
    if (job / "thumbnail.png").exists():
        media += f"<div><img alt=thumbnail src='/jobs/{e(jid)}/files/thumbnail.png'></div>"
    names = {f for f in SERVE if (job / f).exists()} | {p.name for p in job.glob("captions_*.srt") if CAP_RE.fullmatch(p.name)}
    files = " · ".join(f"<a href='/jobs/{e(jid)}/files/{f}'>{f}</a>" for f in sorted(names))
    if (job / "script.json").exists():
        files += f" · <a href='/jobs/{e(jid)}/narration.txt'>narration.txt (वाचण्यासाठी स्क्रिप्ट)</a>"

    def checks(rep: dict | None, key: str) -> str:
        if not rep:
            return "<p class=dim>not yet</p>"
        return (
            "<table>"
            + "".join(
                f"<tr><td>{e(k)}</td><td class={'ok' if c['pass'] else 'bad'}>{'PASS' if c['pass'] else 'FAIL'}</td>"
                f"<td class=dim>{e(c['value'])}</td></tr>"
                for k, c in rep[key].items()
            )
            + "</table>"
        )

    titles = ""
    if (job / "script.json").exists():
        sc = pipeline.rj_or_none(job / "script.json") or {}
        titles = (
            "<ul>"
            + "".join(f"<li>{e(t)}</li>" for t in sc.get("title_options", []))
            + f"</ul><pre>{e(sc.get('description', ''))}</pre>"
        )
    opts = "".join(f"<option>{k}</option>" for k in pipeline.STAGES)
    voice_opts = "<option value=male>पुरुष (male)</option><option value=female>स्त्री (female)</option>"
    body = (
        f"<p><a href='/'>← all jobs</a></p><h1>{e(s['meta'].get('title'))}</h1>"  # noqa: S608 - HTML, not SQL
        f"<div class=dim>{e(jid)} · {e(s['meta'].get('category'))} · voice: {e(s['meta'].get('voice_mode'))} · cost ${s['cost']:.4f}</div>"
        f"<div class=row>{media}</div><div class=card>{files or '<span class=dim>no files yet</span>'}</div>"
        f"<h2>Stages</h2><div class=wrap><table><tr><th>Stage</th><th>State</th><th>Cost</th><th>Note</th></tr>{rows}</table></div>"
        f"<div class=row><div><h2>QC</h2>{checks(s['qc'], 'checks')}</div><div><h2>Gate (auto part)</h2>{checks(s['gate'], 'gates')}"
        f"<p class=dim>100-point score and approval: owner.</p></div></div>"
        f"<h2>Titles and description</h2><div class=card>{titles or '<span class=dim>after the script stage</span>'}</div>"
        f"<h2>Actions</h2><div class=row><form class=card method=post action='/jobs/{e(jid)}/voice' enctype=multipart/form-data>"
        f"<label>Upload owner voice recording (wav / mp3 / m4a): re-renders, no paid call</label>"
        f"<input type=file name=voice accept='audio/*' required><p><button>Upload and re-render</button></p></form>"
        f"<form class=card method=post action='/jobs/{e(jid)}/aivoice'><label>AI voice (free; provider chosen in Settings)</label><select name=speaker>{voice_opts}</select>"
        f"<p><button>Make AI voice and re-render</button></p></form>"
        f"<form class=card method=post action='/jobs/{e(jid)}/voicepack' enctype=multipart/form-data>"
        f"<label>Upload a voice pack (.zip from the free AI voice; exact timing per sentence)</label>"
        f"<input type=file name=pack accept='.zip' required><p><button>Upload voice pack and re-render</button></p></form>"
        f"<form class=card method=post action='/jobs/{e(jid)}/music' enctype=multipart/form-data>"
        f"<label>Background music (YouTube Audio Library track, own channels only, D10)</label>"
        f"<input type=file name=music accept='audio/*' required><label>Track title and artist</label><input name=title required>"
        f"<label>Licence</label><select name=licence><option value=standard>Audio Library standard (no attribution)</option>"
        f"<option value=cc-by>Creative Commons BY 4.0 (attribution added to the description)</option></select>"
        f"<p><button>Upload music and re-render</button></p></form>"
        f"<form class=card method=post action='/jobs/{e(jid)}/versions'><label>Make language versions (re-uses the pictures; "
        f"only a translation call is paid)</label>"
        + "".join(
            f"<label style='display:inline-block;margin-right:10px'><input type=checkbox name=langs value={c} "
            f"style='width:auto'> {e(v[1])}</label>"
            for c, v in LANGS.items()
            if c != s["meta"].get("language", "mr")
        )
        + "<p><button>Create versions</button></p></form>"
        f"<form class=card method=post action='/jobs/{e(jid)}/run'><label>Run / resume from stage</label>"
        f"<select name=from_stage><option value=''>resume (unfinished stages)</option>{opts}</select>"
        f"<p class=dim>Re-running 05/06 makes new paid calls.</p><p><button>Run</button></p></form></div>"
    )
    return page(str(s["meta"].get("title")), body)


@app.post("/jobs/{jid}/run")
def rerun(jid: str, from_stage: str = Form(""), _: str = Depends(auth)):
    get_job(jid)
    if from_stage and from_stage not in pipeline.STAGES:
        raise HTTPException(400, "unknown stage")
    enqueue(jid, from_stage or None)
    return RedirectResponse(f"/jobs/{jid}", status_code=303)


@app.post("/jobs/{jid}/music")
def music(
    jid: str, music: UploadFile = File(...), title: str = Form(...), licence: str = Form("standard"), _: str = Depends(auth)
):
    job = get_job(jid)
    if licence not in ("standard", "cc-by"):
        raise HTTPException(400, "unsupported licence (non-commercial tracks are rejected)")
    title = title.strip()[:200]
    raw = "music_upload" + audio_ext(music)
    save_upload(music, job / raw)
    _mark_convert(job, "music", raw)  # the worker converts it (outside market hours) before the render
    attribution = f'Music: "{title}" (YouTube Audio Library, CC BY 4.0)' if licence == "cc-by" else None
    pipeline.wj(
        job / "music.json", {"title": title, "source": "YouTube Audio Library", "licence": licence, "attribution": attribution}
    )
    enqueue(jid, "10_render")
    return RedirectResponse(f"/jobs/{jid}", status_code=303)


@app.post("/jobs/{jid}/versions")
async def versions(jid: str, request: Request, user: str = Depends(auth)):
    """One new job per language: copies the brief, research, picture plan and pictures; translates the script."""
    src = get_job(jid)
    if not (src / "script.json").exists():
        raise HTTPException(409, "the script is not ready yet")
    form = await request.form()
    langs = [str(x) for x in form.getlist("langs") if str(x) in LANGS]
    return await run_in_threadpool(_make_versions, jid, src, langs, user)


def _make_versions(jid: str, src: Path, langs: list[str], user: str):
    meta = pipeline.rj(src / "job.json")
    made = []
    for lang in langs:
        nid = f"{jid}-{lang}"
        dst = config.jobs_dir() / nid
        if dst.exists():
            continue
        dst.mkdir()
        for f in ("brief.md", "source.txt", "research.json", "asset_plan.json", "assets.json", "music.wav", "music.json"):
            if (src / f).exists():
                shutil.copy2(src / f, dst / f)
        if (src / "assets").exists():
            shutil.copytree(src / "assets", dst / "assets")
        shutil.copy2(src / "script.json", dst / "source_script.json")
        m = {
            **meta,
            "id": nid,
            "language": lang,
            "translate_from": jid,
            "voice_mode": "none",
            "created_utc": pipeline.now(),
            "source_language": meta.get("language", "mr"),
        }
        m["title"] = f"{meta.get('title')} [{LANGS[lang][0]}]"
        pipeline.wj(dst / "job.json", m)
        for st in ("04_research", "05b_asset_plan", "08a_assets", "08b_motion"):
            if (dst / "asset_plan.json").exists() or st == "04_research":
                pipeline.set_status(dst, st, "done", f"copied from {jid}")
        config.audit(user, "job.versions", {"from": jid, "to": nid})
        enqueue(nid, None)
        made.append(nid)
    return RedirectResponse("/" if made else f"/jobs/{jid}", status_code=303)


@app.post("/jobs/{jid}/aivoice")
def aivoice(jid: str, speaker: str = Form(...), user: str = Depends(auth)):
    job = get_job(jid)
    if speaker not in ("male", "female"):
        raise HTTPException(400, "unknown voice")
    (job / "voice.wav").unlink(missing_ok=True)
    meta = pipeline.rj(job / "job.json")
    meta["voice_mode"], meta["speaker_gender"] = "ai", speaker
    pipeline.wj(job / "job.json", meta)
    config.audit(user, "job.aivoice", {"job": jid, "speaker": speaker})
    enqueue(jid, "07_voice")
    return RedirectResponse(f"/jobs/{jid}", status_code=303)


@app.post("/jobs/{jid}/export/{res}")
def export(jid: str, res: str, _: str = Depends(auth)):
    job = get_job(jid)
    if res not in pipeline.EXPORTS or not (job / "final_1080p.mp4").exists():
        raise HTTPException(404)
    threading.Thread(target=lambda: pipeline.make_export(job, res), daemon=True).start()
    return RedirectResponse(f"/jobs/{jid}", status_code=303)


@app.post("/jobs/{jid}/preview")
def preview(jid: str, _: str = Depends(auth)):
    """Make the light 360p copy of an existing video in the background (a minute or two)."""
    job = get_job(jid)
    if not (job / "final_1080p.mp4").exists():
        raise HTTPException(409, "no video yet")
    threading.Thread(target=lambda: pipeline.make_preview(job), daemon=True).start()
    return RedirectResponse(f"/jobs/{jid}", status_code=303)


@app.post("/jobs/{jid}/voicepack")
def voicepack(jid: str, pack: UploadFile = File(...), user: str = Depends(auth)):
    """Install a voice pack (zip: voice.json + tts/*.wav, one file per sentence) made by the free local TTS. The
    sentences must match this job's script exactly, so the timing follows the real audio sentence by sentence."""
    job = get_job(jid)
    raw = job / "voicepack_upload.zip"
    save_upload(pack, raw)
    try:
        with zipfile.ZipFile(raw) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            if "voice.json" not in names or len(names) > 5000:
                raise HTTPException(400, "not a voice pack (voice.json missing)")
            if any(not (n == "voice.json" or re.fullmatch(r"tts/[A-Za-z0-9._-]+\.wav", n)) for n in names):
                raise HTTPException(400, "unexpected file in the voice pack")
            if sum(i.file_size for i in z.infolist()) > MAX_UPLOAD * 3:
                raise HTTPException(413, "voice pack too large")
            v = json.loads(z.read("voice.json"))
            script = pipeline.rj(job / "script.json")
            want = [(sc["id"], t) for sc in script["scenes"] for t in pipeline.sentences(sc["narration"])]
            got = [(it["scene"], it["text"]) for it in v.get("items", [])]
            if want != got:
                raise HTTPException(409, "this voice pack was made for a different script or language")
            if any(f"tts/{it['file']}" not in names for it in v["items"]):
                raise HTTPException(400, "voice pack is missing audio files")
            shutil.rmtree(job / "tts", ignore_errors=True)
            (job / "tts").mkdir()
            for n in names:
                if n.startswith("tts/"):
                    (job / n).write_bytes(z.read(n))
            v["mode"] = "parler"
            pipeline.wj(job / "voice.json", v)
    except zipfile.BadZipFile as exc:
        raise HTTPException(400, "not a zip file") from exc
    finally:
        raw.unlink(missing_ok=True)
    (job / "voice.wav").unlink(missing_ok=True)
    meta = pipeline.rj(job / "job.json")
    meta["voice_mode"], meta["speaker"] = "pack", v.get("speaker")
    pipeline.wj(job / "job.json", meta)
    config.audit(user, "job.voicepack", {"job": jid, "speaker": v.get("speaker")})
    enqueue(jid, "07_voice")
    return RedirectResponse(f"/jobs/{jid}", status_code=303)


@app.post("/jobs/{jid}/voice")
def voice(jid: str, voice: UploadFile = File(...), _: str = Depends(auth)):
    job = get_job(jid)
    raw = "voice_upload" + audio_ext(voice)
    save_upload(voice, job / raw)
    _mark_convert(job, "voice", raw)  # the worker converts it (outside market hours) before stage 07
    meta = pipeline.rj(job / "job.json")
    meta["voice_mode"] = "file"
    pipeline.wj(job / "job.json", meta)
    enqueue(jid, "07_voice")
    return RedirectResponse(f"/jobs/{jid}", status_code=303)


@app.get("/jobs/{jid}/narration.txt", response_class=PlainTextResponse)
def narration(jid: str, _: str = Depends(auth)) -> str:
    """Reading script for the owner's voice recording: one block per scene, read in order, short pause between."""
    sc = pipeline.rj(get_job(jid) / "script.json")
    head = "आवाज रेकॉर्ड करताना: शांत खोली, फोन तोंडापासून एक वीत अंतरावर, एकाच गतीने वाचा; प्रत्येक दृश्यानंतर एक सेकंद थांबा.\n\n"
    return head + "\n\n".join(f"[{s['id']}]\n{s['narration']}" for s in sc["scenes"]) + "\n"


@app.get("/jobs/{jid}/files/{name}")
def files(jid: str, name: str, _: str = Depends(auth)):
    job = get_job(jid)
    if not (name in SERVE or CAP_RE.fullmatch(name)) or not (job / name).exists():
        raise HTTPException(404)
    return FileResponse(job / name)


@app.get("/healthz")
def health() -> dict:
    return {"ok": True, "jobs": len(list(config.jobs_dir().iterdir()))}
