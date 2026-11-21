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

from . import assets, config, languages, llm, visuals

SR = 48000
GAP_SENT, GAP_SCENE, LEAD, TAIL = 0.28, 0.55, 0.6, 1.5
STAGES = [
    "04_research",
    "05_script",
    "06_fact_check",
    "05b_asset_plan",
    "08a_assets",
    "08b_motion",
    "07_voice",
    "09_timeline",
    "08_visuals",
    "11_thumbnail",
    "10_render",
    "10_qc",
    "16_gate",
    "manifest",
]
VISUALS = sorted(k for k in visuals.DRAW if k != "disclaimer")  # the disclaimer card is added by code


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rj(p: Path) -> dict:
    return json.loads(p.read_text())


def wj(p: Path, d: dict) -> None:
    """Atomic JSON write: readers never see a half-written file, a crash never corrupts it."""
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    tmp.replace(p)


def status(job: Path) -> dict:
    f = job / "status.json"
    try:
        return rj(f) if f.exists() else {"stages": {}}
    except ValueError:  # unreadable (e.g. written by an older, non-atomic version): start a fresh record
        return {"stages": {}}


def rj_or_none(p: Path) -> dict | None:
    """Read a JSON report for display; None when missing or unreadable (the dashboard must never break on one file)."""
    try:
        return rj(p) if p.exists() else None
    except (ValueError, OSError):
        return None


def set_status(job: Path, stage: str, state: str, note: str = "") -> None:
    st = status(job)
    st["stages"][stage] = {"state": state, "note": note[-2000:], "at": now()}
    wj(job / "status.json", st)


# ------------------------------------------------------------------ 04 research
def s04_research(job: Path, meta: dict) -> str:
    note = ""
    if meta.get("brief_auto") and not (job / "brief_topic.md").exists():
        # topic only: the AI researches the web and writes the research pack (sources listed with each fact)
        topic = (job / "brief.md").read_text()
        r = llm.research(job, f"{topic}\nVideo length: {meta.get('minutes', 8.5)} minutes; category: {meta.get('category')}.")
        (job / "brief_topic.md").write_text(topic)
        (job / "brief.md").write_text(r.text.strip() + "\n")
        note = "web research done; "
    brief = (job / "brief.md").read_text()
    q = (meta.get("quote") or "").strip()
    out = {"brief_sha256": hashlib.sha256(brief.encode()).hexdigest(), "quote": None}
    if q:
        src = job / "source.txt"
        found = src.exists() and q in re.sub(r"\s+", " ", src.read_text())
        out["quote"] = {"text": q, "credit": meta.get("quote_credit", ""), "verified_exact": bool(found)}
    wj(job / "research.json", out)
    return note + ("quote verified" if out["quote"] and out["quote"]["verified_exact"] else "no verified quote")


# ------------------------------------------------------------------ 05 script
SYSTEM_05 = """You are the scriptwriter of a {language} YouTube channel. Channel category: {category}.
Write natural, warm, spoken {language} in its usual script for a narrator voice, in short sentences a TTS voice reads well.
Use only the ideas in the research pack; attribute ideas to a named author only where the pack does, with its
chapter; keep historical dates vague unless the pack gives them; fictional stories are disclosed as fictional once;
no medical, legal or financial advice; no invented statistics; write numbers in narration as {language} words.
{quote_rule}
Return ONLY a JSON object, no prose."""

USER_05 = """RESEARCH PACK:
<pack>
{brief}
</pack>

TASK: write the full {minutes}-minute script following the pack's outline. Target {words} {language} words of
narration in total. Split into {scenes} scenes of 6–14 seconds. Each scene has 1–3 on-screen beats (short {language}
text, max ~6 words each) so the picture changes every 3–5 seconds. Keep the JSON compact (no extra fields).

JSON shape:
{{"title_options": [3 {language} titles <= 70 chars],
 "thumbnail_text": {{"line1": "<=3 words", "line2": "<=4 words"}},
 "description": "{language} YouTube description with the source credit line",
 "tags": [8-12 tags],
 "scenes": [{{"id": "s01", "section": "hook|intro|story|lessons|action|ending", "narration": "...",
   "beats": ["..."], "visual": one of {visuals},
   "visual_params": {{"rows": [["दिला","..."]] for ledger_table | "word" for crossed_word | "items" for checklist |
   "hours" for screen_time_bar | "parts" for timeline_three_parts | "quote","meaning","credit" for quote_card}}}}],
 "claims": [{{"idea": "...", "chapter": "...", "scene_ids": ["s.."]}}]}}"""


def _complete_scenes(text: str) -> dict:
    """Recover the head fields and every complete scene from a JSON reply cut by max_tokens."""
    if "{" not in text or '"scenes"' not in text:
        raise ValueError("the cut-off reply holds no scenes; raise max_tokens or shorten the brief")
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
    if meta.get("translate_from"):
        return s05_translate(job, meta)
    lang_name = languages.info(meta.get("language", "mr"))[0]
    res = rj(job / "research.json")
    q = res.get("quote")
    quote_rule = (
        f'At most ONE quote, exactly this verified text: "{q["text"]}" ({q["credit"]}), shown on a quote_card '
        f"with its {lang_name} meaning."
        if q and q["verified_exact"]
        else "Do not quote any author verbatim."
    )
    minutes = meta.get("minutes", 8.5)
    system = SYSTEM_05.format(category=meta.get("category", "finance"), quote_rule=quote_rule, language=lang_name)
    if meta.get("category") == "finance":
        system += "\n" + FINANCE_RULES
    user = USER_05.format(
        brief=(job / "brief.md").read_text(),
        language=lang_name,
        minutes=minutes,
        words=int(minutes * 128),
        scenes=f"{int(minutes * 5)}–{int(minutes * 6.5)}",
        visuals=VISUALS,
    )
    if meta.get("format") == "short_9x16":
        user += (
            "\n\nFORMAT: YouTube Short, vertical 9:16, 45–58 seconds in total (about 110–135 words in the video language), 8–12 scenes "
            "of 3–6 seconds. The first scene is a 2-second hook question or shock line; one idea only; end with a one-line "
            "takeaway and an invitation to watch the full video. Beats max 4 words (small screen)."
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
    if meta.get("category") == "finance":
        add_finance_disclaimer(data, meta.get("language", "mr"))
    wj(job / "script.json", data)
    words = sum(len(s["narration"].split()) for s in data["scenes"])
    return f"{len(data['scenes'])} scenes, {words} words"


TRANSLATE_BATCH = 12  # scenes per call: keeps each reply far below the output limit


def src_lang(job: Path) -> str:
    try:
        return rj(job / "job.json").get("source_language", "mr")
    except (OSError, ValueError):
        return "mr"


def s05_translate(job: Path, meta: dict) -> str:
    """Language version of an existing job: translate the script in batches, keep scene ids, visuals and pictures."""
    src = rj(job / "source_script.json")
    target = languages.info(meta["language"])[0]
    keep_quote = (meta.get("quote") or "").strip()
    system = (
        f"You translate a YouTube narration script into natural, spoken {target} (its usual script), for a narrator voice. "
        "Keep meaning, tone and scene ids exactly; adapt idioms naturally; write numbers as words; beats stay short "
        "(max ~6 words). Translate narration, beats and any visible text in visual_params (table rows, words, items, "
        "meaning), but never translate an English quote marked as a quote: keep it verbatim and translate only its "
        "meaning field. Return ONLY JSON with the same shape as the input."
    )
    head_in = {k: src.get(k) for k in ("title_options", "thumbnail_text", "description", "tags")}
    head = llm.parse_json(
        llm.call(job, "05_translate_head", system, f"JSON:\n{json.dumps(head_in, ensure_ascii=False)}", 8000, "low").text
    )
    scenes: list[dict] = []
    for b in range(0, len(src["scenes"]), TRANSLATE_BATCH):
        part = src["scenes"][b : b + TRANSLATE_BATCH]
        user = f"Verbatim quote to keep: {keep_quote or 'none'}\n\nJSON:\n{json.dumps({'scenes': part}, ensure_ascii=False)}"
        out = llm.parse_json(llm.call(job, f"05_translate_{b // TRANSLATE_BATCH:02d}", system, user, 24000, "low").text)
        got = out.get("scenes", [])
        if [x.get("id") for x in got] != [x["id"] for x in part]:
            raise RuntimeError(f"translation changed the scene list in batch {b // TRANSLATE_BATCH}; refusing")
        for a, src_s in zip(got, part, strict=True):
            a["visual"] = src_s["visual"]
            a.setdefault("section", src_s.get("section"))
        scenes += got
    data = {**{k: head.get(k, src.get(k)) for k in head_in}, "scenes": scenes, "claims": src.get("claims", [])}
    if meta.get("category") == "finance":  # the approved template of the target language, never a free translation
        if disclaimer(meta["language"]):
            data["description"] = (data.get("description") or "").replace(disclaimer(src_lang(job)) or "\0", "").strip()
        add_finance_disclaimer(data, meta["language"])
    wj(job / "script.json", data)
    return f"translated {len(scenes)} scenes to {target}"


# ------------------------------------------------------------------ finance (SEBI rule pack, 13 section 5)
FINANCE_RULES = """FINANCE RULES (SEBI, India; education only; any breach blocks the video):
- No buy, sell or hold call on any instrument (FIN-R1). No entry, exit, stop-loss, target, strike or trigger level for a
  current instrument (FIN-R2). No view on what a current market will do tomorrow/this week/in future (FIN-R3).
- No performance, profit or return claims, no "guaranteed" or "assured" returns, no profit testimonials (FIN-R6, R7).
- No broker referral, affiliate or paid promotion of any regulated entity (FIN-R8); no paid tips group (FIN-R5).
- No forward-looking statement about the future direction of a NAMED security, even in a historical example (FIN-R13).
  Prefer generic examples ("a stock", "an index"); dated price examples only if older than 30 days (FIN-R9).
- Explain concepts, risks and how things work; always mention risk where returns are discussed."""
FIN_FLAGS = re.compile(
    r"खरेदी करा|विकत घ्या|विका\b|टार्गेट|स्टॉप.?लॉस|नफा (मिळेल|नक्की)|गॅरंटी|हमखास|खरीदें|बेचें|मुनाफा पक्का|"
    r"\b(buy now|sell now|target price|stop.?loss at|guaranteed returns?|assured returns?|sure.?shot|multibagger)\b",
    re.IGNORECASE,
)


def disclaimer(lang: str) -> str | None:
    d = json.loads((Path(__file__).parent / "data" / "disclaimers.json").read_text(encoding="utf-8"))
    return d.get(lang)


def add_finance_disclaimer(data: dict, lang: str) -> None:
    """FIN-R10: an on-screen disclaimer card first (5-6 s) and the text at the end of the description."""
    text = disclaimer(lang) or disclaimer("en")
    first = text.split(". ")[0].split("। ")[0].rstrip(".।") + ("।" if lang in ("hi",) else ".")
    data["scenes"] = [s for s in data["scenes"] if s.get("id") != "s00"]
    data["scenes"].insert(
        0,
        {
            "id": "s00",
            "section": "intro",
            "narration": first,
            "beats": [],
            "visual": "disclaimer",
            "visual_params": {"text": text},
        },
    )
    desc = data.get("description") or ""
    if text not in desc:
        data["description"] = (desc.rstrip() + "\n\n" + text).strip()


# ------------------------------------------------------------------ 06 fact-check
# medical / mental-health advice markers (mr, hi, en); other languages rely on the LLM fact-check item
MEDICAL = re.compile(
    r"डॉक्टर|उपचार|औषध|नैराश्य|डिप्रेशन|थेरपी|दवा|इलाज|\b(doctor|medicine|medication|therapy|diagnos\w*|cure|depression)\b",
    re.IGNORECASE,
)


def s06_fact_check(job: Path, meta: dict) -> str:
    d = rj(job / "script.json")
    res = rj(job / "research.json")
    q = res.get("quote")
    txt = json.dumps(d["scenes"], ensure_ascii=False)
    det = {
        "quote_verified_exact": bool(q and q["verified_exact"]),
        "quote_scenes": [s["id"] for s in d["scenes"] if q and q["text"][:20] in json.dumps(s, ensure_ascii=False)],
        "unverified_latin_quotes": [
            s["id"]
            for s in d["scenes"]
            for m in re.findall(r"[\"“]([A-Za-z][^\"”]{20,})[\"”]", s["narration"])
            if not (q and q["verified_exact"] and m.strip().rstrip(".") in q["text"])
        ],
        "digits_in_narration": [(s["id"], x) for s in d["scenes"] for x in re.findall(r"[0-9०-९]+", s["narration"])],
        "medical_terms": [s["id"] for s in d["scenes"] if MEDICAL.search(s["narration"])],
        "finance_flags": [
            s["id"]
            for s in d["scenes"]
            if s.get("id") != "s00" and FIN_FLAGS.search(s["narration"] + " " + " ".join(s.get("beats", [])))
        ],
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
    if meta.get("brief_auto"):
        user += (
            "\nThe pack is only a topic line: judge each factual claim against widely documented, mainstream knowledge "
            "(traditional versions for mythology); mark SUPPORTED when well established, UNSUPPORTED when doubtful or "
            "invented. Creative retelling of a traditional story is fine."
        )
    if meta.get("category") == "finance":
        user += "\nAlso judge every scene against these rules; any breach makes overall FAIL:\n" + FINANCE_RULES
    r = llm.parse_json(llm.call(job, "06_fact_check", "You are a strict fact-checker. Be concise.", user, 16000).text)
    wj(job / "fact_check.json", {"deterministic": det, "llm": r})
    del txt
    return f"{r.get('overall')} ({len(r.get('items', []))} items)"


# ------------------------------------------------------------------ 07 voice
def sentences(text: str) -> list[str]:
    out: list[str] = []
    for p in re.split(r"(?<=[.?!।…؟۔])\s+|(?<=[。！？])", text.strip()):
        p = p.strip()
        if p and out and len(p) < 12:
            out[-1] += " " + p
        elif p:
            out.append(p)
    return out


def s07_voice(job: Path, meta: dict) -> str:
    mode = meta.get("voice_mode", "none")
    if mode == "ai":  # AI narration, provider chosen in Settings (D24: kaggle for now, google later)
        gender = meta.get("speaker_gender") or "male"
        lang = meta.get("language", "mr")
        if config.get("AMW_VOICE_PROVIDER", "kaggle") == "google":
            from . import tts_google  # noqa: PLC0415

            info = tts_google.synthesize(job, rj(job / "script.json"), lang, gender, sentences)
        else:
            from . import tts_kaggle  # noqa: PLC0415

            speaker = tts_kaggle.speaker_for(lang, gender)
            user, key = config.get("AMW_KAGGLE_USERNAME"), config.get("AMW_SECRET_KAGGLE_KEY")
            hf = config.get("AMW_SECRET_HF_TOKEN")
            if not (user and key and hf):
                raise RuntimeError("Kaggle AI voice needs the Kaggle username, Kaggle key and Hugging Face token in Settings")
            info = tts_kaggle.synthesize(job, rj(job / "script.json"), speaker, sentences, user, key, hf)
        wj(job / "voice.json", info)
        return f"AI voice: {info['speaker']} ({len(info['items'])} sentences)"
    if mode == "pack":  # per-sentence TTS files installed from a voice pack (exact timing per sentence)
        v = rj(job / "voice.json") if (job / "voice.json").exists() else {}
        missing = [it["file"] for it in v.get("items", []) if not (job / "tts" / it["file"]).exists()]
        if v.get("mode") != "parler" or not v.get("items") or missing:
            raise RuntimeError(f"voice pack incomplete ({len(missing)} files missing); upload it again")
        return f"voice pack: {v.get('speaker')} ({len(v['items'])} sentences)"
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


def _chunks(text: str, n: int = 42, cjk: bool = False) -> list[str]:
    if cjk or (" " not in text.strip() and len(text) > 18):  # ja/zh: no word spaces, cut by characters
        return [text[i : i + 18] for i in range(0, len(text), 18)]
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
    lang = meta.get("language", "mr")
    wps = languages.info(lang)[3]
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
                sents.append((s["id"], txt, None, max(1.2, languages.units(lang, txt) / wps)))
        if voice["mode"] == "file":  # scale the estimate to the real recording length
            x, sr = sf.read(job / "voice.wav", dtype="float32")
            real = len(x) / sr
            gaps = GAP_SENT * len(sents) + GAP_SCENE * len(script["scenes"])
            spoken = sum(d for *_, d in sents)
            k = max(0.2, (real - LEAD - TAIL - gaps) / max(spoken, 0.1))  # timeline total then equals the recording
            sents = [(a, b, None, d * k) for a, b, _, d in sents]
    pieces, t, scenes, subs, cur, start = [np.zeros(int(LEAD * SR), np.float32)], LEAD, [], [], None, 0.0
    for sid, txt, x, d in sents:
        if sid != cur:
            if cur is not None:
                t += GAP_SCENE
                pieces.append(np.zeros(int(GAP_SCENE * SR), np.float32))
                scenes.append({"id": cur, "start": round(start, 3), "dur": round(t - start, 3)})
            cur, start = sid, (0.0 if cur is None else t)
        cs = _chunks(txt, cjk=lang in languages.CHAR_BASED)
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
    else:
        (job / "narration_48k.wav").unlink(missing_ok=True)
    basis = {
        "parler": "MEASURED from TTS audio",
        "file": "ESTIMATE scaled to the recording length",
        "none": f"ESTIMATE {wps} words/s (no voice)",
    }[voice["mode"]]
    wj(job / "timings.json", {"scenes": scenes, "total": round(t, 3), "basis": basis})
    srt = "\n".join(f"{i}\n{_ts(a)} --> {_ts(b)}\n{c}\n" for i, (a, b, c) in enumerate(subs, 1))
    for old in job.glob("captions_*.srt"):
        old.unlink()
    (job / f"captions_{lang}.srt").write_text(srt, encoding="utf-8")
    return f"{t / 60:.2f} min, {len(subs)} captions ({basis})"


# ------------------------------------------------------------------ 08 visuals / 11 thumbnail
def s08_visuals(job: Path, meta: dict) -> str:
    visuals.set_output(meta.get("format") == "short_9x16")
    visuals.set_language(meta.get("language", "mr"))
    n = visuals.render_visuals(job, rj(job / "script.json"), rj(job / "timings.json"), job / "visuals.mp4")
    return f"{n} frames"


def s11_thumbnail(job: Path, meta: dict) -> str:
    visuals.set_language(meta.get("language", "mr"))
    af = job / "assets.json"
    tf = (rj(af).get("_thumbnail") or {}).get("file") if af.exists() else None
    hero = job / tf if tf else job / "assets" / "missing.jpg"
    visuals.thumbnail(rj(job / "script.json"), job / "thumbnail.png", hero if hero.exists() else None)
    return "1280x720" + (" with AI hero picture" if hero.exists() else "")


# ------------------------------------------------------------------ 10 render + QC
def sh(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def audio_source(job: Path) -> Path | None:
    """The narration chosen by stage 07 (voice.json mode), never a leftover file from an earlier mode."""
    vf = job / "voice.json"
    mode = rj(vf).get("mode") if vf.exists() else None
    f = {"parler": job / "narration_48k.wav", "file": job / "voice.wav"}.get(mode or "")
    return f if f and f.exists() else None


def s10_render(job: Path, meta: dict) -> str:
    final = job / "final_1080p.mp4"
    out = job / "final_1080p.rendering.mp4"  # swapped in only when complete: the dashboard never serves a half file
    vid = ["-c:v", "copy"]  # the visuals stage already encoded at the delivery settings: no second video encode
    aud = ["-c:a", "aac", "-b:a", "384k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart"]
    voiced = audio_source(job) is not None
    mix = build_mix(job)
    if voiced:
        m = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-i",
                str(mix),
                "-af",
                "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
        ).stderr
        j = json.loads(m[m.rindex("{") : m.rindex("}") + 1])
        af = (
            f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={j['input_i']}:measured_TP={j['input_tp']}:measured_LRA={j['input_lra']}:"
            f"measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true,aresample=48000"
        )
    else:  # music/SFX only: fixed level, no loudness target (voice pending)
        af = "volume=0.8,alimiter=limit=0.8,aresample=48000"
    sh(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(job / "visuals.mp4"),
            "-i",
            str(mix),
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
    out.replace(final)
    make_preview(job)
    parts = ["voice" if voiced else "NO voice (pending)"]
    parts += ["music"] if music_file(job) else []
    parts += ["SFX"]
    return "rendered with " + " + ".join(parts)


def make_preview(job: Path) -> Path:
    """Light copy for watching on a phone over a slow connection (360p, about 0.4 Mbps); the full file stays for YouTube."""
    final, prev = job / "final_1080p.mp4", job / "preview_360p.mp4"
    tmp = job / "preview_360p.rendering.mp4"
    sh(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(final),
            "-vf",
            "scale=-2:360",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "30",
            "-maxrate",
            "450k",
            "-bufsize",
            "900k",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-movflags",
            "+faststart",
            str(tmp),
        ]
    )
    tmp.replace(prev)
    return prev


EXPORTS = {"720": ("1280", "23", "2500k"), "480": ("854", "26", "1200k")}


def make_export(job: Path, res: str) -> Path:
    """Smaller download copy (720p / 480p) of the final video, made on request."""
    w, crf, mx = EXPORTS[res]
    out, tmp = job / f"export_{res}p.mp4", job / f"export_{res}p.rendering.mp4"
    sh(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(job / "final_1080p.mp4"),
            "-vf",
            f"scale=-2:{res}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            crf,
            "-maxrate",
            mx,
            "-bufsize",
            mx,
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(tmp),
        ]
    )
    tmp.replace(out)
    return out


def music_file(job: Path) -> Path | None:
    f = job / "music.wav"
    return f if f.exists() else None


def build_sfx(job: Path, total: float) -> Path:
    """Code-made sound effects (no licence needed): a soft whoosh at scene changes, ticks on running-clock scenes."""
    rng = np.random.default_rng(7)
    out = np.zeros(int((total + 1) * SR), np.float32)
    tim = rj(job / "timings.json")
    by = {s["id"]: s for s in rj(job / "script.json")["scenes"]}
    n = int(0.45 * SR)
    noise = rng.standard_normal(n).astype(np.float32)
    k = np.ones(40, np.float32) / 40  # crude low-pass
    whoosh = np.convolve(noise, k, mode="same") * np.sin(np.linspace(0, np.pi, n)) ** 2 * 0.05
    tn = int(0.03 * SR)
    tt = np.arange(tn) / SR
    tick = (np.sin(2 * np.pi * 2400 * tt) * np.exp(-tt * 180) * 0.12).astype(np.float32)
    for row in tim["scenes"][1:]:
        a = max(0, int((row["start"] - 0.2) * SR))
        out[a : a + n] += whoosh[: len(out) - a]
    for row in tim["scenes"]:
        if by[row["id"]]["visual"] == "clock_running":
            t = row["start"] + 0.3
            while t < row["start"] + row["dur"] - 0.3:
                a = int(t * SR)
                out[a : a + tn] += tick[: len(out) - a]
                t += 1.0
    f = job / "sfx.wav"
    sf.write(f, out, SR, subtype="PCM_16")
    return f


def build_mix(job: Path) -> Path:
    """Narration (or silence) + SFX + music ducked under the voice -> mix.wav (48 kHz stereo)."""
    total = rj(job / "timings.json")["total"]
    narr = audio_source(job)
    if narr is None:
        narr = job / "silence.wav"
        sf.write(narr, np.zeros(int(total * SR), np.float32), SR, subtype="PCM_16")
    sfx = build_sfx(job, total)
    mus = music_file(job)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(narr), "-i", str(sfx)]
    if mus:
        cmd += ["-stream_loop", "-1", "-i", str(mus)]
        fc = (
            "[0:a]aformat=channel_layouts=stereo,asplit=2[v][sc];[2:a]aformat=channel_layouts=stereo,volume=0.30[m];"
            "[m][sc]sidechaincompress=threshold=0.015:ratio=10:attack=15:release=450[md];"
            "[1:a]aformat=channel_layouts=stereo[x];[v][x][md]amix=inputs=3:normalize=0:duration=first[out]"
        )
    else:
        fc = "[0:a]aformat=channel_layouts=stereo[v];[1:a]aformat=channel_layouts=stereo[x];[v][x]amix=inputs=2:normalize=0:duration=first[out]"
    out = job / "mix.wav"
    sh([*cmd, "-filter_complex", fc, "-map", "[out]", "-ar", "48000", str(out)])
    return out


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
    target = 60 * float(meta.get("minutes", 8.5))
    if meta.get("format") == "short_9x16":
        lo, hi = 20.0, 60.0  # a Short must stay under one minute
    else:  # a real voice reads at its own pace: allow 25 % around the target length
        lo = min(60 * meta.get("min_minutes", 8), 0.75 * target)
        hi = max(60 * meta.get("max_minutes", 9.6), 1.25 * target)
    checks = {
        "video.h264_high": (v["codec_name"] == "h264" and v.get("profile") == "High", f"{v['codec_name']} {v.get('profile')}"),
        "video.resolution": (
            (v["width"], v["height"]) == ((1080, 1920) if meta.get("format") == "short_9x16" else (1920, 1080)),
            f"{v['width']}x{v['height']}",
        ),
        "video.cfr_30": (v["r_frame_rate"] == "30/1" and v["avg_frame_rate"] == "30/1", v["avg_frame_rate"]),
        "video.yuv420p": (v["pix_fmt"] == "yuv420p", v["pix_fmt"]),
        "video.encoder_bitrate": (
            True,
            f"quality '{config.get('AMW_VIDEO_QUALITY', 'high')}' (high = 8 Mbps, D10); file {int(pr['format']['bit_rate']) / 1e6:.2f} Mbps",
        ),
        "audio.aac_lc_48k": (
            a["codec_name"] == "aac" and a.get("profile") == "LC" and a["sample_rate"] == "48000",
            f"{a['codec_name']} {a.get('profile')} {a['sample_rate']}",
        ),
        "audio.voice_present": (voiced, "narration" if voiced else "MISSING: voice pending"),
        "audio.loudness_-14_lufs": (voiced and abs(lufs + 14) <= 1.0, f"{lufs} LUFS"),
        "audio.true_peak_-1_dbtp": (voiced and tp <= -1.0, f"{tp} dBTP"),
        "font.for_language": (languages.font_ok(meta.get("language", "mr")), meta.get("language", "mr")),
        "duration.min_max": (lo <= dur <= hi, f"{dur:.1f} s (allowed {lo:.0f}-{hi:.0f} s)"),
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
        "finance_rule_pack": (
            (not fin) or (not det.get("finance_flags") and fc["llm"].get("overall") == "PASS"),
            f"SEBI rule pack: flagged scenes {det.get('finance_flags', [])}" if fin else "n/a",
        ),
        "finance_voice": (
            True,  # advisory (D28): the owner chose his own voice for monetized finance videos
            (
                "AI voice used: record your own voice before monetizing (D28, FIN-R11)"
                if meta.get("voice_mode") in ("ai", "pack")
                else "owner voice"
            )
            if fin
            else "n/a",
        ),
        "finance_disclaimer": (
            (not fin) or _has_disclaimer(job),
            "FIN-R10 card at the start + description" if fin else "n/a",
        ),
        "quote_policy": (det["quote_count_ok"] and not det["unverified_latin_quotes"], f"quote scenes {det['quote_scenes']}"),
        "fact_check": (fc["llm"].get("overall") == "PASS", fc["llm"].get("overall")),
        "fiction_disclosed": (
            bool(det["fiction_disclosure"]) or not meta.get("has_fiction", False),
            str(det["fiction_disclosure"]),
        ),
        "no_medical_terms": (not det["medical_terms"], str(det["medical_terms"])),
        "technical_qc": (qc["all_pass"], "see qc_report.json"),
        "budget": (llm.job_spent(job) <= config.load().per_video_cap_usd, f"{llm.job_spent(job):.4f} USD"),
        "asset_licences": (
            all(a.get("licence") for a in (rj(job / "assets.json").values() if (job / "assets.json").exists() else [])),
            "every picture/clip has a licence record",
        ),
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


def _has_disclaimer(job: Path) -> bool:
    sc = rj_or_none(job / "script.json") or {}
    first = (sc.get("scenes") or [{}])[0]
    text = (first.get("visual_params") or {}).get("text", "")
    return first.get("visual") == "disclaimer" and bool(text) and text in (sc.get("description") or "")


def manifest(job: Path, meta: dict) -> str:
    rows = llm.ledger_rows(job)
    by: dict[str, float] = {s: 0.0 for s in STAGES if s != "manifest"}
    for r in rows:
        k = (
            "05_script"
            if r["stage"] in ("05_script", "05_script_continuation") or r["stage"].startswith("05_translate")
            else r["stage"]
        )
        by[k] = round(by.get(k, 0.0) + r["cost_usd"], 6)
    voice = rj(job / "voice.json")
    script = rj(job / "script.json")
    files = [
        "final_1080p.mp4",
        "thumbnail.png",
        f"captions_{meta.get('language', 'mr')}.srt",
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
        "assets": rj(job / "assets.json") if (job / "assets.json").exists() else {},
        "music": rj(job / "music.json") if (job / "music.json").exists() else None,
        "synthetic_media_disclosure_recommended": voice["mode"] == "parler" or (job / "assets.json").exists(),
        "files_sha256": {f: hashlib.sha256((job / f).read_bytes()).hexdigest() for f in files if (job / f).exists()},
    }
    wj(job / "manifest.json", m)
    return f"total {m['cost_usd_total']:.4f} USD"


FUNCS = {
    "04_research": s04_research,
    "05_script": s05_script,
    "06_fact_check": s06_fact_check,
    "05b_asset_plan": assets.s05b_asset_plan,
    "08a_assets": assets.s08a_assets,
    "08b_motion": assets.s08b_motion,
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


HEAVY = {"07_voice", "08a_assets", "08b_motion", "08_visuals", "10_render", "10_qc"}


def run(job: Path, from_stage: str | None = None, before_stage=None) -> bool:
    """Run the stages in order. A stage that is not done runs; once any stage runs, every later stage runs too, so
    nothing downstream is left from an older input. ``before_stage(stage)`` lets the caller wait (market hours)."""
    try:
        meta = rj(job / "job.json")
        st = status(job)
    except Exception as exc:  # unreadable job: report, never kill the caller
        set_status(job, "queue", "failed", f"job unreadable: {type(exc).__name__}: {exc}")
        return False
    if from_stage is not None and from_stage not in STAGES:
        set_status(job, "queue", "failed", f"unknown stage {from_stage!r}")
        return False
    dirty = False
    for stage in STAGES:
        done = st["stages"].get(stage, {}).get("state") == "done"
        forced = from_stage is not None and STAGES.index(stage) >= STAGES.index(from_stage)
        if done and not forced and not dirty:
            continue
        if before_stage is not None:
            before_stage(stage)
        set_status(job, stage, "running")
        try:
            note = FUNCS[stage](job, meta)
            set_status(job, stage, "done", note)
            dirty = True
        except Exception as exc:  # recorded and the run stops: no silent skip, no retry loop
            set_status(job, stage, "failed", f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}")
            for later in STAGES[STAGES.index(stage) + 1 :]:  # downstream results are now stale
                if st["stages"].get(later, {}).get("state") == "done":
                    set_status(job, later, "stale", f"needs re-run after {stage} failed")
            return False
    return True
