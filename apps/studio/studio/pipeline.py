"""Sample production line: 04 research -> 05 script -> 06 fact-check -> 07 voice -> 09 timeline ->
08 visuals -> 11 thumbnail -> 10 render + QC -> 16 gate -> manifest.

A job is a folder under data/jobs/<id>/ holding job.json, brief.md (research pack, private), optional
source.txt (public-domain text used to verify the quote) and optional voice.wav (owner recording).
Every stage writes its output file and its status into status.json; a rerun skips finished stages.
"""

import hashlib
import json
import re
import subprocess
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf

from . import config, llm, visuals

SR = 48000
GAP_SENT, GAP_SCENE, LEAD, TAIL = 0.28, 0.55, 0.6, 1.5
STAGES = [
    "04_research",
    "05_script",
    "06_fact_check",
    "07_voice",
    "09_timeline",
    "08_visuals",
    "11_thumbnail",
    "10_render",
    "10_qc",
    "16_gate",
    "manifest",
]
VISUALS = sorted(visuals.DRAW)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rj(p: Path) -> dict:
    return json.loads(p.read_text())


def wj(p: Path, d: dict) -> None:
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1))


def status(job: Path) -> dict:
    f = job / "status.json"
    return rj(f) if f.exists() else {"stages": {}}


def set_status(job: Path, stage: str, state: str, note: str = "") -> None:
    st = status(job)
    st["stages"][stage] = {"state": state, "note": note[-2000:], "at": now()}
    wj(job / "status.json", st)


# ------------------------------------------------------------------ 04 research
def s04_research(job: Path, meta: dict) -> str:
    brief = (job / "brief.md").read_text()
    q = (meta.get("quote") or "").strip()
    out = {"brief_sha256": hashlib.sha256(brief.encode()).hexdigest(), "quote": None}
    if q:
        src = job / "source.txt"
        found = src.exists() and q in re.sub(r"\s+", " ", src.read_text())
        out["quote"] = {"text": q, "credit": meta.get("quote_credit", ""), "verified_exact": bool(found)}
    wj(job / "research.json", out)
    return "quote verified" if out["quote"] and out["quote"]["verified_exact"] else "no verified quote"


# ------------------------------------------------------------------ 05 script
SYSTEM_05 = """You are the scriptwriter of a Marathi YouTube channel. Channel category: {category}.
Write natural, warm, spoken Marathi (Devanagari) for a narrator voice, in short sentences a TTS voice reads well.
Use only the ideas in the research pack; attribute ideas to a named author only where the pack does, with its
chapter; keep historical dates vague unless the pack gives them; fictional stories are disclosed as fictional once;
no medical, legal or financial advice; no invented statistics; write numbers in narration as Marathi words.
{quote_rule}
Return ONLY a JSON object, no prose."""

USER_05 = """RESEARCH PACK:
<pack>
{brief}
</pack>

TASK: write the full {minutes}-minute script following the pack's outline. Target {words} Marathi words of
narration in total. Split into {scenes} scenes of 6–14 seconds. Each scene has 1–3 on-screen beats (short Marathi
text, max ~6 words each) so the picture changes every 3–5 seconds. Keep the JSON compact (no extra fields).

JSON shape:
{{"title_options": [3 Marathi titles <= 70 chars],
 "thumbnail_text": {{"line1": "<=3 words", "line2": "<=4 words"}},
 "description": "Marathi YouTube description with the source credit line",
 "tags": [8-12 tags],
 "scenes": [{{"id": "s01", "section": "hook|intro|story|lessons|action|ending", "narration": "...",
   "beats": ["..."], "visual": one of {visuals},
   "visual_params": {{"rows": [["दिला","..."]] for ledger_table | "word" for crossed_word | "items" for checklist |
   "hours" for screen_time_bar | "parts" for timeline_three_parts | "quote","meaning","credit" for quote_card}}}}],
 "claims": [{{"idea": "...", "chapter": "...", "scene_ids": ["s.."]}}]}}"""


def _complete_scenes(text: str) -> dict:
    """Recover the head fields and every complete scene from a JSON reply cut by max_tokens."""
    t = text[text.find("{") :]
    i = t.find('"scenes"')
    head = json.loads(t[:i].rstrip().rstrip(",") + "}")
    body, dec, scenes = t[i:], json.JSONDecoder(), []
    pos = body.find("[") + 1
    while True:
        pos = re.compile(r"\s*,?\s*").match(body, pos).end()
        try:
            obj, pos = dec.raw_decode(body, pos)
        except ValueError:
            break
        scenes.append(obj)
    head["scenes"] = scenes
    return head


def s05_script(job: Path, meta: dict) -> str:
    res = rj(job / "research.json")
    q = res.get("quote")
    quote_rule = (
        f'At most ONE quote, exactly this verified text: "{q["text"]}" ({q["credit"]}), shown on a quote_card '
        "with its Marathi meaning."
        if q and q["verified_exact"]
        else "Do not quote any author verbatim."
    )
    minutes = meta.get("minutes", 8.5)
    system = SYSTEM_05.format(category=meta.get("category", "finance"), quote_rule=quote_rule)
    user = USER_05.format(
        brief=(job / "brief.md").read_text(),
        minutes=minutes,
        words=int(minutes * 128),
        scenes=f"{int(minutes * 5)}–{int(minutes * 6.5)}",
        visuals=VISUALS,
    )
    r = llm.call(job, "05_script", system, user, max_tokens=64000, effort="medium")
    if r.stop_reason == "max_tokens":
        data = _complete_scenes(r.text)
        compact = [{"id": s["id"], "section": s["section"], "narration": s["narration"]} for s in data["scenes"]]
        cont = (
            f"RESEARCH PACK:\n<pack>{(job / 'brief.md').read_text()}</pack>\nScript so far (cut off):\n"
            f"{json.dumps(compact, ensure_ascii=False)}\nWrite ONLY the remaining scenes to the end of the outline "
            "(same scene shape), then the claims list for the whole script. Return ONLY JSON: "
            '{"scenes": [...], "claims": [...]}'
        )
        more = llm.parse_json(llm.call(job, "05_script_continuation", system, cont, 16000, "low").text)
        data["scenes"] += more["scenes"]
        data["claims"] = more.get("claims", [])
    else:
        data = llm.parse_json(r.text)
    for k, s in enumerate(data["scenes"], 1):
        s["id"] = f"s{k:02d}"
        if s.get("visual") not in visuals.DRAW:
            s["visual"] = "kinetic_text"
    wj(job / "script.json", data)
    words = sum(len(s["narration"].split()) for s in data["scenes"])
    return f"{len(data['scenes'])} scenes, {words} words"


# ------------------------------------------------------------------ 06 fact-check
def s06_fact_check(job: Path, meta: dict) -> str:
    d = rj(job / "script.json")
    res = rj(job / "research.json")
    q = res.get("quote")
    txt = json.dumps(d["scenes"], ensure_ascii=False)
    det = {
        "quote_verified_exact": bool(q and q["verified_exact"]),
        "quote_scenes": [s["id"] for s in d["scenes"] if q and q["text"][:20] in json.dumps(s, ensure_ascii=False)],
        "unverified_latin_quotes": [s["id"] for s in d["scenes"] if re.search(r"[\"“][A-Za-z][^\"”]{20,}[\"”]", s["narration"])],
        "digits_in_narration": [(s["id"], x) for s in d["scenes"] for x in re.findall(r"[0-9०-९]+", s["narration"])],
        "medical_terms": [s["id"] for s in d["scenes"] if re.search(r"डॉक्टर|उपचार|औषध|नैराश्य|डिप्रेशन|थेरपी", s["narration"])],
        "fiction_disclosure": [s["id"] for s in d["scenes"] if "काल्पनिक" in s["narration"]],
    }
    det["quote_count_ok"] = len(det["quote_scenes"]) <= 1 and (not det["quote_scenes"] or det["quote_verified_exact"])
    compact = [{"id": s["id"], "narration": s["narration"], "beats": s["beats"]} for s in d["scenes"]]
    user = (
        f"<pack>{(job / 'brief.md').read_text()}</pack>\n<script>{json.dumps(compact, ensure_ascii=False)}</script>\n"
        "Fact-check: every sentence that attributes an idea or fact to a named author, or states a historical fact, "
        "must match the pack. Flag invented statistics, medical/legal/financial advice, extra verbatim quotes, and any "
        'claim that a fictional story is real. Return ONLY JSON: {"items":[{"scene_id","claim","verdict":'
        '"SUPPORTED|UNSUPPORTED|NEEDS_EDIT","note"}],"overall":"PASS|FAIL","required_edits":[{"scene_id","old","new"}]}'
    )
    r = llm.parse_json(llm.call(job, "06_fact_check", "You are a strict fact-checker. Be concise.", user, 16000).text)
    wj(job / "fact_check.json", {"deterministic": det, "llm": r})
    del txt
    return f"{r.get('overall')} ({len(r.get('items', []))} items)"


# ------------------------------------------------------------------ 07 voice
def sentences(text: str) -> list[str]:
    out: list[str] = []
    for p in re.split(r"(?<=[.?!।…])\s+", text.strip()):
        p = p.strip()
        if p and out and len(p) < 12:
            out[-1] += " " + p
        elif p:
            out.append(p)
    return out


def s07_voice(job: Path, meta: dict) -> str:
    mode = meta.get("voice_mode", "none")
    if (job / "voice.wav").exists():
        mode = "file"
    info = {"mode": mode}
    if mode == "parler":
        from . import tts_parler  # optional extra (torch); see Dockerfile build arg WITH_TTS

        info.update(tts_parler.synthesize(job, rj(job / "script.json"), meta.get("speaker", "Sanjay")))
    elif mode == "file":
        info.update({"provider": "owner recording", "licence": "owner's own voice", "file": "voice.wav"})
    else:
        info.update({"provider": None, "note": "no voice yet: silent track, timings estimated"})
    wj(job / "voice.json", info)
    return mode


# ------------------------------------------------------------------ 09 timeline (+ narration + SRT)
def _trim(x: np.ndarray, sr: int) -> np.ndarray:
    thr = max(1e-3, 0.02 * float(np.max(np.abs(x)) or 1))
    idx = np.where(np.abs(x) > thr)[0]
    return x if len(idx) == 0 else x[max(0, idx[0] - int(0.03 * sr)) : idx[-1] + int(0.08 * sr)]


def _resample(x: np.ndarray, sr: int) -> np.ndarray:
    if sr == SR:
        return x
    n = int(round(len(x) * SR / sr))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def _ts(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _chunks(text: str, n: int = 42) -> list[str]:
    out, cur = [], ""
    for w in text.split():
        if cur and len(cur) + len(w) + 1 > n:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    return out + ([cur] if cur else [])


def s09_timeline(job: Path, meta: dict) -> str:
    script = rj(job / "script.json")
    voice = rj(job / "voice.json")
    wps = config.load().words_per_second
    # per sentence: (scene id, text, audio or None, duration)
    sents = []
    if voice["mode"] == "parler":
        files = {(it["scene"], it["n"]): it for it in voice["items"]}
        for s in script["scenes"]:
            for n, txt in enumerate(sentences(s["narration"])):
                x, sr = sf.read(job / "tts" / files[(s["id"], n)]["file"], dtype="float32")
                x = _resample(_trim(x if x.ndim == 1 else x.mean(axis=1), sr), sr)
                sents.append((s["id"], txt, x, len(x) / SR))
    else:
        for s in script["scenes"]:
            for txt in sentences(s["narration"]):
                sents.append((s["id"], txt, None, max(1.2, len(txt.split()) / wps)))
        if voice["mode"] == "file":  # scale the estimate to the real recording length
            x, sr = sf.read(job / "voice.wav", dtype="float32")
            real = len(x) / sr
            est = sum(d for *_, d in sents) + GAP_SENT * len(sents) + GAP_SCENE * len(script["scenes"]) + LEAD + TAIL
            k = max(0.2, (real - LEAD - TAIL) / (est - LEAD - TAIL))
            sents = [(a, b, None, d * k) for a, b, _, d in sents]
    pieces, t, scenes, subs, cur, start = [np.zeros(int(LEAD * SR), np.float32)], LEAD, [], [], None, 0.0
    for sid, txt, x, d in sents:
        if sid != cur:
            if cur is not None:
                t += GAP_SCENE
                pieces.append(np.zeros(int(GAP_SCENE * SR), np.float32))
                scenes.append({"id": cur, "start": round(start, 3), "dur": round(t - start, 3)})
            cur, start = sid, (0.0 if cur is None else t)
        cs = _chunks(txt)
        tot, ct = sum(len(c) for c in cs), t
        for c in cs:
            cd = d * len(c) / tot
            subs.append((ct, ct + cd, c))
            ct += cd
        pieces += [x if x is not None else np.zeros(int(d * SR), np.float32), np.zeros(int(GAP_SENT * SR), np.float32)]
        t += d + GAP_SENT
    t += GAP_SCENE + TAIL
    pieces.append(np.zeros(int((GAP_SCENE + TAIL) * SR), np.float32))
    scenes.append({"id": cur, "start": round(start, 3), "dur": round(t - start, 3)})
    if voice["mode"] == "parler":
        sf.write(job / "narration_48k.wav", np.concatenate(pieces), SR, subtype="PCM_24")
    basis = {
        "parler": "MEASURED from TTS audio",
        "file": "ESTIMATE scaled to the recording length",
        "none": f"ESTIMATE {wps} words/s (no voice)",
    }[voice["mode"]]
    wj(job / "timings.json", {"scenes": scenes, "total": round(t, 3), "basis": basis})
    srt = "\n".join(f"{i}\n{_ts(a)} --> {_ts(b)}\n{c}\n" for i, (a, b, c) in enumerate(subs, 1))
    (job / "captions_mr.srt").write_text(srt, encoding="utf-8")
    return f"{t / 60:.2f} min, {len(subs)} captions ({basis})"


# ------------------------------------------------------------------ 08 visuals / 11 thumbnail
def s08_visuals(job: Path, meta: dict) -> str:
    n = visuals.render_visuals(job, rj(job / "script.json"), rj(job / "timings.json"), job / "visuals.mp4")
    return f"{n} frames"


def s11_thumbnail(job: Path, meta: dict) -> str:
    visuals.thumbnail(rj(job / "script.json"), job / "thumbnail.png")
    return "1280x720"


# ------------------------------------------------------------------ 10 render + QC
def sh(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def audio_source(job: Path) -> Path | None:
    for f in ("narration_48k.wav", "voice.wav"):
        if (job / f).exists():
            return job / f
    return None


def s10_render(job: Path, meta: dict) -> str:
    out = job / "final_1080p.mp4"
    vid = [
        "-c:v",
        "libx264",
        "-profile:v",
        "high",
        "-preset",
        "slow",
        "-b:v",
        "8M",
        "-maxrate",
        "12M",
        "-bufsize",
        "16M",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "30",
        "-fps_mode",
        "cfr",
        "-g",
        "15",
        "-bf",
        "2",
    ]
    aud = ["-c:a", "aac", "-b:a", "384k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart"]
    src = audio_source(job)
    if src is None:
        sh(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(job / "visuals.mp4"),
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000:cl=stereo",
                "-map",
                "0:v",
                "-map",
                "1:a",
                *vid,
                *aud,
                "-shortest",
                str(out),
            ]
        )
        return "rendered with a SILENT audio track (voice pending)"
    m = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(src), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True,
        text=True,
    ).stderr
    j = json.loads(m[m.rindex("{") : m.rindex("}") + 1])
    af = (
        f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={j['input_i']}:measured_TP={j['input_tp']}:measured_LRA={j['input_lra']}:"
        f"measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true,aresample=48000"
    )
    sh(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(job / "visuals.mp4"),
            "-i",
            str(src),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-af",
            af,
            *vid,
            *aud,
            "-shortest",
            str(out),
        ]
    )
    return f"rendered with {src.name}"


def s10_qc(job: Path, meta: dict) -> str:
    f = job / "final_1080p.mp4"
    pr = json.loads(sh(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(f)]).stdout)
    v = next(s for s in pr["streams"] if s["codec_type"] == "video")
    a = next(s for s in pr["streams"] if s["codec_type"] == "audio")
    e = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(f), "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True,
        text=True,
    ).stderr
    summ = e[e.rindex("Summary:") :]
    li = re.search(r"I:\s+(-?[\d.]+|-inf) LUFS", summ)
    pk = re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", summ)
    lufs = float(li.group(1)) if li else float("-inf")
    tp = float(pk.group(1)) if pk else float("-inf")
    dur = float(pr["format"]["duration"])
    voiced = audio_source(job) is not None
    checks = {
        "video.h264_high": (v["codec_name"] == "h264" and v.get("profile") == "High", f"{v['codec_name']} {v.get('profile')}"),
        "video.1920x1080": ((v["width"], v["height"]) == (1920, 1080), f"{v['width']}x{v['height']}"),
        "video.cfr_30": (v["r_frame_rate"] == "30/1" and v["avg_frame_rate"] == "30/1", v["avg_frame_rate"]),
        "video.yuv420p": (v["pix_fmt"] == "yuv420p", v["pix_fmt"]),
        "video.encoder_8mbps_vbr": (True, f"-b:v 8M VBR target (D10); file {int(pr['format']['bit_rate']) / 1e6:.2f} Mbps"),
        "audio.aac_lc_48k": (
            a["codec_name"] == "aac" and a.get("profile") == "LC" and a["sample_rate"] == "48000",
            f"{a['codec_name']} {a.get('profile')} {a['sample_rate']}",
        ),
        "audio.voice_present": (voiced, "narration" if voiced else "MISSING: voice pending"),
        "audio.loudness_-14_lufs": (voiced and abs(lufs + 14) <= 1.0, f"{lufs} LUFS"),
        "audio.true_peak_-1_dbtp": (voiced and tp <= -1.0, f"{tp} dBTP"),
        "duration.min_max": (60 * meta.get("min_minutes", 8) <= dur <= 60 * meta.get("max_minutes", 9.6), f"{dur:.1f} s"),
    }
    rep = {
        "duration_s": round(dur, 2),
        "all_pass": all(p for p, _ in checks.values()),
        "checks": {k: {"pass": bool(p), "value": str(val)} for k, (p, val) in checks.items()},
    }
    wj(job / "qc_report.json", rep)
    failed = [k for k, c in rep["checks"].items() if not c["pass"]]
    return "PASS" if not failed else "FAIL: " + ", ".join(failed)


# ------------------------------------------------------------------ 16 gate + manifest
def s16_gate(job: Path, meta: dict) -> str:
    fc, qc = rj(job / "fact_check.json"), rj(job / "qc_report.json")
    det = fc["deterministic"]
    fin = meta.get("category", "finance") == "finance"
    gates = {
        "category": (True, "finance: SEBI rule pack applies" if fin else "non-finance: finance-only gates not applied (CCR-273)"),
        "finance_rule_pack": (not fin, "finance jobs are not supported by this studio build" if fin else "n/a"),
        "quote_policy": (det["quote_count_ok"] and not det["unverified_latin_quotes"], f"quote scenes {det['quote_scenes']}"),
        "fact_check": (fc["llm"].get("overall") == "PASS", fc["llm"].get("overall")),
        "fiction_disclosed": (
            bool(det["fiction_disclosure"]) or not meta.get("has_fiction", True),
            str(det["fiction_disclosure"]),
        ),
        "no_medical_terms": (not det["medical_terms"], str(det["medical_terms"])),
        "technical_qc": (qc["all_pass"], "see qc_report.json"),
        "budget": (llm.job_spent(job) <= config.load().per_video_cap_usd, f"{llm.job_spent(job):.4f} USD"),
    }
    rep = {
        "auto_pass": all(p for p, _ in gates.values()),
        "score_100": "OWNER (D5)",
        "publish": False,
        "gates": {k: {"pass": bool(p), "value": str(v)} for k, (p, v) in gates.items()},
    }
    wj(job / "gate_report.json", rep)
    failed = [k for k, g in rep["gates"].items() if not g["pass"]]
    return "auto PASS (owner review next)" if not failed else "BLOCKED: " + ", ".join(failed)


def manifest(job: Path, meta: dict) -> str:
    rows = llm.ledger_rows(job)
    by: dict[str, float] = {s: 0.0 for s in STAGES if s != "manifest"}
    for r in rows:
        k = "05_script" if r["stage"].startswith("05") else r["stage"]
        by[k] = round(by.get(k, 0.0) + r["cost_usd"], 6)
    voice = rj(job / "voice.json")
    script = rj(job / "script.json")
    files = [
        "final_1080p.mp4",
        "thumbnail.png",
        "captions_mr.srt",
        "qc_report.json",
        "gate_report.json",
        "script.json",
        "fact_check.json",
        "timings.json",
    ]
    m = {
        "job": meta,
        "created_utc": now(),
        "upload": False,
        "providers": {
            "llm": {"provider": "Anthropic", "model": config.load().model},
            "voice": voice,
            "fonts": "Mukta, SIL OFL 1.1",
            "music": None,
        },
        "cost_usd_by_stage": by,
        "cost_usd_total": round(sum(by.values()), 6),
        "cost_basis": "ESTIMATE = list price x usage (reconcile with the provider console)",
        "ledger": rows,
        "title_options": script.get("title_options"),
        "description": script.get("description"),
        "tags": script.get("tags"),
        "synthetic_media_disclosure_recommended": voice["mode"] == "parler",
        "files_sha256": {f: hashlib.sha256((job / f).read_bytes()).hexdigest() for f in files if (job / f).exists()},
    }
    wj(job / "manifest.json", m)
    return f"total {m['cost_usd_total']:.4f} USD"


FUNCS = {
    "04_research": s04_research,
    "05_script": s05_script,
    "06_fact_check": s06_fact_check,
    "07_voice": s07_voice,
    "09_timeline": s09_timeline,
    "08_visuals": s08_visuals,
    "11_thumbnail": s11_thumbnail,
    "10_render": s10_render,
    "10_qc": s10_qc,
    "16_gate": s16_gate,
    "manifest": manifest,
}
# stages that must rerun when the voice changes (script and fact-check are kept: no new paid call)
AFTER_VOICE = STAGES[STAGES.index("07_voice") :]


def run(job: Path, from_stage: str | None = None) -> bool:
    meta = rj(job / "job.json")
    st = status(job)
    todo = STAGES[STAGES.index(from_stage) :] if from_stage else STAGES
    for stage in STAGES:
        done = st["stages"].get(stage, {}).get("state") == "done"
        if stage not in todo and done:
            continue
        if done and not from_stage:
            continue
        set_status(job, stage, "running")
        try:
            note = FUNCS[stage](job, meta)
            set_status(job, stage, "done", note)
        except Exception as exc:  # recorded and the run stops: no silent skip, no retry loop
            set_status(job, stage, "failed", f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}")
            return False
    return True
