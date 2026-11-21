"""Basic dashboard: jobs, stage status, cost per stage, QC, gate, video, downloads; new job; voice upload.

Password-protected (HTTP Basic, AMW_DASHBOARD_USER / AMW_DASHBOARD_PASSWORD). One worker thread runs jobs one
at a time. Rendering waits outside market hours when AMW_BLOCK_MARKET_HOURS=1 (shared VPS rule, D1).
"""

import html
import os
import queue
import re
import secrets
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from . import config, llm, pipeline

app = FastAPI(title="AMW Studio", docs_url=None, redoc_url=None, openapi_url=None)
security = HTTPBasic()
Q: "queue.Queue[tuple[str, str | None]]" = queue.Queue()
SERVE = {
    "final_1080p.mp4",
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
IST = timezone(timedelta(hours=5, minutes=30))
RENDER_STAGES = {"08_visuals", "10_render"}


def auth(c: HTTPBasicCredentials = Depends(security)) -> str:
    user, pw = os.environ.get("AMW_DASHBOARD_USER", "owner"), os.environ.get("AMW_DASHBOARD_PASSWORD", "")
    ok = bool(pw) and secrets.compare_digest(c.username, user) and secrets.compare_digest(c.password, pw)
    if not ok:
        raise HTTPException(401, "unauthorised", headers={"WWW-Authenticate": "Basic"})
    return c.username


def market_hours() -> bool:
    """NSE regular session window, Mon–Fri 09:00–15:45 IST (exchange holidays not modelled: conservative)."""
    if os.environ.get("AMW_BLOCK_MARKET_HOURS", "1") != "1":
        return False
    n = datetime.now(IST)
    return n.weekday() < 5 and (9, 0) <= (n.hour, n.minute) <= (15, 45)


def worker() -> None:
    while True:
        jid, frm = Q.get()
        job = config.jobs_dir() / jid
        try:
            while market_hours():
                pipeline.set_status(job, "queue", "waiting", "market hours: render waits (D1)")
                time.sleep(60)
            pipeline.set_status(job, "queue", "done", "started")
            pipeline.run(job, frm)
        finally:
            Q.task_done()


@app.on_event("startup")
def _start() -> None:
    if not os.environ.get("AMW_DASHBOARD_PASSWORD"):
        raise RuntimeError("AMW_DASHBOARD_PASSWORD must be set")
    for j in sorted(config.jobs_dir().iterdir()):  # resume jobs interrupted by a restart
        st = pipeline.status(j)["stages"] if (j / "job.json").exists() else None
        if st is not None and (not st or any(v.get("state") in ("running", "waiting") for v in st.values())):
            Q.put((j.name, None))
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
    return {"done": "ok", "failed": "bad", "running": "run", "waiting": "run"}.get(s, "dim")


def job_summary(job: Path) -> dict:
    meta = pipeline.rj(job / "job.json")
    st = pipeline.status(job)["stages"]
    cur = next((s for s in pipeline.STAGES if st.get(s, {}).get("state") != "done"), None)
    qc = pipeline.rj(job / "qc_report.json") if (job / "qc_report.json").exists() else None
    gate = pipeline.rj(job / "gate_report.json") if (job / "gate_report.json").exists() else None
    state = st.get(cur, {}).get("state", "queued") if cur else "complete"
    return {"meta": meta, "stage": cur or "—", "state": state, "cost": llm.job_spent(job), "qc": qc, "gate": gate}


@app.get("/", response_class=HTMLResponse)
def index(_: str = Depends(auth)) -> HTMLResponse:
    cfg = config.load()
    jobs = sorted((j for j in config.jobs_dir().iterdir() if (j / "job.json").exists()), key=lambda p: p.name, reverse=True)
    rows = ""
    for j in jobs:
        s = job_summary(j)
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
    spent = llm.pilot_spent()
    body = (
        f"<h1>AMW Studio</h1><div class=row><div class=card>Pilot spend <b>${spent:.2f}</b> / ${cfg.pilot_cap_usd:.2f}"
        f"<div class=dim>Per-video cap ${cfg.per_video_cap_usd:.2f} · model {e(cfg.model)}</div></div>"
        f"<div class=card>Queue: {Q.qsize()} waiting · {'<span class=bad>market hours: render paused</span>' if market_hours() else '<span class=ok>render allowed</span>'}"
        f"<div><a href='/jobs/new'>+ New job</a></div></div></div>"
        f"<div class=wrap><table><tr><th>Job</th><th>Category</th><th>Stage</th><th>Cost</th><th>QC</th><th>Gate</th></tr>"
        f"{rows or '<tr><td colspan=6 class=dim>No jobs yet</td></tr>'}</table></div>"
    )
    return page("AMW Studio", body)


@app.get("/jobs/new", response_class=HTMLResponse)
def new_form(_: str = Depends(auth)) -> HTMLResponse:
    body = """<h1>New job</h1><form class=card method=post action=/jobs enctype=multipart/form-data>
<label>Title</label><input name=title required>
<label>Category</label><select name=category><option value=philosophy>philosophy (non-finance)</option>
<option value=finance>finance (blocked in this build)</option></select>
<label>Length (minutes)</label><input name=minutes type=number step=0.5 value=8.5>
<label>Research pack / brief (.md, private)</label><input type=file name=brief accept=".md,.txt" required>
<label>Public-domain source text for quote check (.txt, optional)</label><input type=file name=source accept=".txt">
<label>Quote (exact text, optional)</label><input name=quote><label>Quote credit</label><input name=quote_credit>
<label>Voice</label><select name=voice_mode><option value=none>none yet (silent, upload later)</option>
<option value=parler>Indic Parler-TTS (free, needs HF_TOKEN + WITH_TTS build)</option></select>
<p class=dim>Paid step: the script and fact-check use the Anthropic API within the per-video cap.</p>
<button>Create and run</button></form>"""
    return page("New job", body)


@app.post("/jobs")
async def create(
    title: str = Form(...),
    category: str = Form(...),
    minutes: float = Form(8.5),
    voice_mode: str = Form("none"),
    quote: str = Form(""),
    quote_credit: str = Form(""),
    brief: UploadFile = File(...),
    source: UploadFile | None = File(None),
    _: str = Depends(auth),
):
    jid = (
        datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        + "-"
        + (re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:24] or "job")
    )
    job = config.jobs_dir() / jid
    job.mkdir()
    (job / "brief.md").write_bytes(await brief.read())
    if source and source.filename:
        (job / "source.txt").write_bytes(await source.read())
    meta = {
        "id": jid,
        "title": title,
        "category": category,
        "minutes": minutes,
        "min_minutes": max(1, minutes - 1),
        "max_minutes": minutes + 1.2,
        "voice_mode": voice_mode,
        "quote": quote,
        "quote_credit": quote_credit,
        "created_utc": pipeline.now(),
    }
    pipeline.wj(job / "job.json", meta)
    Q.put((jid, None))
    return RedirectResponse(f"/jobs/{jid}", status_code=303)


def get_job(jid: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", jid):
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
    for r in llm.ledger_rows(job):
        k = "05_script" if r["stage"].startswith("05") else r["stage"]
        costs[k] = costs.get(k, 0.0) + r["cost_usd"]
    rows = "".join(
        f"<tr><td>{e(k)}</td><td class={state_cls(st.get(k, {}).get('state', ''))}>{e(st.get(k, {}).get('state', 'pending'))}</td>"
        f"<td>${costs.get(k, 0.0):.4f}</td><td><pre>{e(st.get(k, {}).get('note', ''))[:600]}</pre></td></tr>"
        for k in pipeline.STAGES
    )
    media = ""
    if (job / "final_1080p.mp4").exists():
        media += f"<div><video controls preload=metadata src='/jobs/{e(jid)}/files/final_1080p.mp4' poster='/jobs/{e(jid)}/files/thumbnail.png'></video></div>"
    if (job / "thumbnail.png").exists():
        media += f"<div><img alt=thumbnail src='/jobs/{e(jid)}/files/thumbnail.png'></div>"
    files = " · ".join(f"<a href='/jobs/{e(jid)}/files/{f}'>{f}</a>" for f in sorted(SERVE) if (job / f).exists())

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
        sc = pipeline.rj(job / "script.json")
        titles = (
            "<ul>"
            + "".join(f"<li>{e(t)}</li>" for t in sc.get("title_options", []))
            + f"</ul><pre>{e(sc.get('description', ''))}</pre>"
        )
    opts = "".join(f"<option>{k}</option>" for k in pipeline.STAGES)
    body = (
        f"<p><a href='/'>← all jobs</a></p><h1>{e(s['meta'].get('title'))}</h1>"
        f"<div class=dim>{e(jid)} · {e(s['meta'].get('category'))} · voice: {e(s['meta'].get('voice_mode'))} · cost ${s['cost']:.4f}</div>"
        f"<div class=row>{media}</div><div class=card>{files or '<span class=dim>no files yet</span>'}</div>"
        f"<h2>Stages</h2><div class=wrap><table><tr><th>Stage</th><th>State</th><th>Cost</th><th>Note</th></tr>{rows}</table></div>"
        f"<div class=row><div><h2>QC</h2>{checks(s['qc'], 'checks')}</div><div><h2>Gate (auto part)</h2>{checks(s['gate'], 'gates')}"
        f"<p class=dim>100-point score and approval: owner.</p></div></div>"
        f"<h2>Titles and description</h2><div class=card>{titles or '<span class=dim>after the script stage</span>'}</div>"
        f"<h2>Actions</h2><div class=row><form class=card method=post action='/jobs/{e(jid)}/voice' enctype=multipart/form-data>"
        f"<label>Upload owner voice recording (wav / mp3 / m4a): re-renders, no paid call</label>"
        f"<input type=file name=voice accept='audio/*' required><p><button>Upload and re-render</button></p></form>"
        f"<form class=card method=post action='/jobs/{e(jid)}/run'><label>Run / resume from stage</label>"
        f"<select name=from_stage><option value=''>resume (unfinished stages)</option>{opts}</select>"
        f"<p class=dim>Re-running 05/06 makes new paid calls.</p><p><button>Run</button></p></form></div>"
    )
    return page(str(s["meta"].get("title")), body)


@app.post("/jobs/{jid}/run")
def rerun(jid: str, from_stage: str = Form(""), _: str = Depends(auth)):
    get_job(jid)
    Q.put((jid, from_stage or None))
    return RedirectResponse(f"/jobs/{jid}", status_code=303)


@app.post("/jobs/{jid}/voice")
async def voice(jid: str, voice: UploadFile = File(...), _: str = Depends(auth)):
    job = get_job(jid)
    raw = job / ("voice_upload" + Path(voice.filename or "a.wav").suffix.lower()[:5])
    with raw.open("wb") as f:
        shutil.copyfileobj(voice.file, f)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ac", "1", "-ar", "48000", str(job / "voice.wav")], check=True
    )
    meta = pipeline.rj(job / "job.json")
    meta["voice_mode"] = "file"
    pipeline.wj(job / "job.json", meta)
    Q.put((jid, "07_voice"))
    return RedirectResponse(f"/jobs/{jid}", status_code=303)


@app.get("/jobs/{jid}/files/{name}")
def files(jid: str, name: str, _: str = Depends(auth)):
    job = get_job(jid)
    if name not in SERVE or not (job / name).exists():
        raise HTTPException(404)
    return FileResponse(job / name)


@app.get("/healthz")
def health() -> dict:
    return {"ok": True, "jobs": len(list(config.jobs_dir().iterdir()))}
