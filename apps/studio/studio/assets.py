"""Stage 05b (asset plan, one cheap LLM call) and stage 08a (fetch assets).

Visual sources per D16: AI story illustrations from Black Forest Labs FLUX.2 [pro] (research log IMG-03) and free
stock video from Pixabay (STK-02). Keys come only from the environment (AMW_SECRET_BFL_API_KEY,
AMW_SECRET_PIXABAY_API_KEY). A missing key, a moderated prompt or any fetch error leaves that scene on the code-made
visual: the run never stops for an optional asset, and every asset is listed with its licence in assets.json.
"""

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import config, llm

BFL_URL = "https://api.bfl.ai/v1/flux-2-pro"
PIXABAY_URL = "https://pixabay.com/api/videos/"
IMG_W, IMG_H = 1920, 1088  # cropped to 1080 at render time
# FLUX.2 [pro]: USD 0.03 for the first megapixel + 0.015 per extra megapixel (IMG-03). Worst case rounds the extra
# megapixels up, so the guard never under-counts.
BFL_WORST_USD = 0.03 + 0.015 * 2
UA = {"User-Agent": "amw-studio/1"}

DEFAULT_STYLE = (
    "stylized 3D animated feature-film look, expressive characters with large eyes and clear emotions, soft global "
    "illumination, vibrant saturated colours, cinematic depth of field, rich detailed Indian setting, warm rim light, "
    "no text, no letters, no logos, no watermark"
)

SYSTEM_PLAN = """You plan the pictures for a Marathi explainer video. Return ONLY JSON.
For each scene choose: "ai_image" for story moments with characters or specific places (a consistent illustrated
world), "stock_video" for generic real-world B-roll (city traffic, phone screens, clocks, nature, crowds), or "none"
where the code-made diagram/kinetic text is best (tables, timelines, checklists, quote cards, questions).
Image prompts: English, concrete, one shot, describe composition and camera (wide/medium/close), reuse the exact
character descriptions from the character sheet every time a character appears, never include text in the image,
no real people, no brands. Stock queries: 2-4 English words."""

USER_PLAN = """Scenes:
{scenes}

Limits: at most {max_ai} "ai_image" scenes and at most {max_stock} "stock_video" scenes.
Also write "thumbnail_prompt": one close-up of the main character with a strong, readable emotion (surprise or
realisation) and the story's key object, character on the RIGHT half, empty darker space on the LEFT for big text.
JSON shape: {{"characters": {{"name": "fixed visual description"}}, "thumbnail_prompt": "...",
 "scenes": [{{"id": "s01", "kind": "ai_image|stock_video|none", "prompt": "...", "query": "..."}}]}}"""


def s05b_asset_plan(job: Path, meta: dict) -> str:
    script = json.loads((job / "script.json").read_text())
    compact = [
        {"id": s["id"], "section": s["section"], "visual": s["visual"], "beats": s["beats"], "narration": s["narration"][:220]}
        for s in script["scenes"]
    ]
    max_ai = int(os.environ.get("AMW_MAX_AI_IMAGES", "28"))
    max_stock = int(os.environ.get("AMW_MAX_STOCK_CLIPS", "10"))
    user = USER_PLAN.format(scenes=json.dumps(compact, ensure_ascii=False), max_ai=max_ai, max_stock=max_stock)
    plan = llm.parse_json(llm.call(job, "05b_asset_plan", SYSTEM_PLAN, user, max_tokens=16000, effort="low").text)
    n_ai = n_st = 0
    for p in plan["scenes"]:  # enforce the limits in code, not only in the prompt
        if p.get("kind") == "ai_image":
            n_ai += 1
            if n_ai > max_ai:
                p["kind"] = "none"
        elif p.get("kind") == "stock_video":
            n_st += 1
            if n_st > max_stock:
                p["kind"] = "none"
    plan["style"] = meta.get("visual_style") or DEFAULT_STYLE
    (job / "asset_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1))
    kinds = [p["kind"] for p in plan["scenes"]]
    return f"ai_image {kinds.count('ai_image')}, stock_video {kinds.count('stock_video')}, none {kinds.count('none')}"


# ------------------------------------------------------------------ providers
def _get_json(url: str, headers: dict | None = None, data: bytes | None = None, timeout: int = 60) -> dict:
    if not url.startswith("https://"):
        raise ValueError("only https URLs are fetched")
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})}, method="POST" if data else "GET")  # noqa: S310
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed https endpoints
        return json.loads(r.read())


def _download(url: str, out: Path) -> None:
    if not url.startswith("https://"):
        raise ValueError("only https URLs are fetched")
    req = urllib.request.Request(url, headers=UA)  # noqa: S310
    with urllib.request.urlopen(req, timeout=120) as r, out.open("wb") as f:  # noqa: S310 - provider result URL
        while chunk := r.read(1 << 16):
            f.write(chunk)


def bfl_image(job: Path, key: str, prompt: str, out: Path, seed: int) -> dict:
    if llm.job_spent(job) + BFL_WORST_USD > config.load().per_video_cap_usd:
        raise llm.BudgetRefused("per-video cap reached before an AI image")
    if llm.pilot_spent() + BFL_WORST_USD > config.load().pilot_cap_usd:
        raise llm.BudgetRefused("pilot cap reached before an AI image")
    body = json.dumps({"prompt": prompt, "width": IMG_W, "height": IMG_H, "seed": seed, "output_format": "jpeg"}).encode()
    sub = _get_json(BFL_URL, {"x-key": key, "Content-Type": "application/json", "accept": "application/json"}, body)
    llm.append_row(
        job,
        {
            "stage": "08a_assets",
            "provider": "bfl",
            "model": "flux-2-pro",
            "request_id": sub.get("id"),
            "cost_usd": BFL_WORST_USD,
            "basis": "ESTIMATE worst case per image (IMG-03)",
        },
    )
    deadline = time.time() + 180
    while time.time() < deadline:
        time.sleep(2)
        r = _get_json(sub["polling_url"], {"x-key": key, "accept": "application/json"})
        st = r.get("status")
        if st == "Ready":
            _download(r["result"]["sample"], out)  # signed URL valid 10 minutes: download at once
            return {
                "provider": "Black Forest Labs FLUX.2 [pro]",
                "request_id": sub.get("id"),
                "seed": seed,
                "licence": "BFL API terms: no ownership claimed in Output (IMG-03); AI-generated, disclose as such",
            }
        if st not in ("Pending", "Reasoning", "Generating"):
            raise RuntimeError(f"BFL status {st}")
    raise TimeoutError("BFL image not ready in 180 s")


def pixabay_video(key: str, query: str, out: Path, used: set[int]) -> dict:
    q = urllib.parse.urlencode({"key": key, "q": query, "safesearch": "true", "per_page": 20, "video_type": "film"})
    hits = _get_json(f"{PIXABAY_URL}?{q}").get("hits", [])
    for h in hits:
        if h["id"] in used:
            continue
        v = h["videos"].get("large") or {}
        if not v.get("url") or v.get("width", 0) < 1920:
            v = h["videos"].get("medium") or {}
        if not v.get("url") or v.get("width", 0) < 1280:
            continue
        _download(v["url"], out)
        used.add(h["id"])
        return {
            "provider": "Pixabay",
            "pixabay_id": h["id"],
            "page": h.get("pageURL"),
            "user": h.get("user"),
            "size": f"{v.get('width')}x{v.get('height')}",
            "licence": "Pixabay Content License (STK-02)",
        }
    raise LookupError(f"no usable Pixabay video for '{query}'")


def s08a_assets(job: Path, meta: dict) -> str:
    plan = json.loads((job / "asset_plan.json").read_text())
    adir = job / "assets"
    adir.mkdir(exist_ok=True)
    bfl, pix = os.environ.get("AMW_SECRET_BFL_API_KEY"), os.environ.get("AMW_SECRET_PIXABAY_API_KEY")
    chars = plan.get("characters", {})
    sheet = "; ".join(f"{k}: {v}" for k, v in chars.items())
    out, used, notes = {}, set(), []
    old = json.loads((job / "assets.json").read_text()) if (job / "assets.json").exists() else {}
    for i, p in enumerate(plan["scenes"]):
        sid, kind = p["id"], p.get("kind", "none")
        try:
            if kind == "ai_image":
                f = adir / f"{sid}.jpg"
                if sid in old and f.exists():  # keep paid images on a re-run
                    out[sid] = old[sid]
                    continue
                if not bfl:
                    raise LookupError("AMW_SECRET_BFL_API_KEY not set")
                prompt = f"{p['prompt']}. Characters: {sheet}. Style: {plan['style']}"
                info = bfl_image(job, bfl, prompt, f, seed=1000 + i)
                out[sid] = {"kind": "image", "file": f"assets/{f.name}", "prompt": p["prompt"], **info}
            elif kind == "stock_video":
                f = adir / f"{sid}.mp4"
                if sid in old and f.exists():
                    out[sid] = old[sid]
                    continue
                if not pix:
                    raise LookupError("AMW_SECRET_PIXABAY_API_KEY not set")
                info = pixabay_video(pix, p.get("query") or "city life", f, used)
                out[sid] = {"kind": "video", "file": f"assets/{f.name}", "query": p.get("query"), **info}
        except llm.BudgetRefused as exc:
            notes.append(f"{sid}: {exc}")
            break
        except Exception as exc:  # optional asset: fall back to the code-made visual, record why
            notes.append(f"{sid}: {type(exc).__name__}: {str(exc)[:120]}")
    tp, tf = plan.get("thumbnail_prompt"), adir / "thumb.jpg"
    if tp and bfl and not tf.exists():
        try:
            info = bfl_image(job, bfl, f"{tp}. Characters: {sheet}. Style: {plan['style']}", tf, seed=999)
            out["_thumbnail"] = {"kind": "thumbnail", "file": "assets/thumb.jpg", "prompt": tp, **info}
        except Exception as exc:
            notes.append(f"thumbnail: {type(exc).__name__}: {str(exc)[:120]}")
    elif tf.exists() and "_thumbnail" in old:
        out["_thumbnail"] = old["_thumbnail"]
    (job / "assets.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    kinds = [a["kind"] for a in out.values()]
    msg = f"images {kinds.count('image')}, videos {kinds.count('video')}"
    return msg + (f"; fallbacks: {len(notes)} ({'; '.join(notes[:3])})" if notes else "")
