"""AI narration with Google Cloud Text-to-Speech, Chirp 3: HD voices (research log GTTS-01).

Free usage: the first 1,000,000 characters per month for Chirp 3: HD voices (pricing page, read 2026-11-21); billing
must be enabled on the Google Cloud project. This module keeps a monthly character count in data/tts_usage.json and
refuses BEFORE a request that would pass the free limit (AMW_GOOGLE_TTS_FREE_CHARS), so the owner is never charged
unless that setting is raised on purpose. One WAV per sentence, so the timeline follows the real audio.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import config

URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
# video language -> Google locale (voice list page, read 2026-11-21: Chirp3-HD voices exist for each of these)
LOCALES = {
    "mr": "mr-IN",
    "hi": "hi-IN",
    "en": "en-IN",
    "gu": "gu-IN",
    "bn": "bn-IN",
    "pa": "pa-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "kn": "kn-IN",
    "ml": "ml-IN",
    "ur": "ur-IN",
    "es": "es-ES",
    "fr": "fr-FR",
    "de": "de-DE",
    "pt": "pt-BR",
    "it": "it-IT",
    "id": "id-ID",
    "ru": "ru-RU",
    "ar": "ar-XA",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "zh": "cmn-CN",
}
SPEAKERS = {"male": "Charon", "female": "Kore"}  # both listed for every locale above
_lock = threading.Lock()


class FreeLimitReached(RuntimeError):
    pass


def voice_name(lang: str, gender: str) -> str:
    return f"{LOCALES[lang]}-Chirp3-HD-{SPEAKERS[gender]}"


def _usage_file() -> Path:
    return config.data_dir() / "tts_usage.json"


def month_used() -> int:
    f = _usage_file()
    d = json.loads(f.read_text()) if f.exists() else {}
    return int(d.get(datetime.now(timezone.utc).strftime("%Y-%m"), 0))


def _add_usage(n: int) -> None:
    with _lock:
        f = _usage_file()
        d = json.loads(f.read_text()) if f.exists() else {}
        m = datetime.now(timezone.utc).strftime("%Y-%m")
        d[m] = int(d.get(m, 0)) + n
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1))
        tmp.replace(f)


def _synth(key: str, text: str, lang: str, name: str) -> bytes:
    body = {
        "input": {"text": text},
        "voice": {"languageCode": LOCALES[lang], "name": name},
        "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 48000},
    }
    req = urllib.request.Request(  # noqa: S310 - fixed https endpoint
        f"{URL}?key={urllib.parse.quote(key)}",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
            d = json.loads(r.read())
    except urllib.error.HTTPError as exc:  # never include the URL (it holds the key)
        raise RuntimeError(f"Google TTS HTTP {exc.code}: {exc.read(300).decode('utf-8', 'replace')}") from None
    return base64.b64decode(d["audioContent"])


def synthesize(job: Path, script: dict, lang: str, gender: str, sentences) -> dict:
    key = config.get("AMW_SECRET_GOOGLE_TTS_KEY")
    if not key:
        raise RuntimeError("Google TTS key not set in Settings")
    if lang not in LOCALES:
        raise RuntimeError(f"no Google voice for language {lang}")
    name = voice_name(lang, gender)
    limit = int(float(config.get("AMW_GOOGLE_TTS_FREE_CHARS", "1000000")))
    tts = job / "tts"
    tts.mkdir(exist_ok=True)
    items = []
    for s in script["scenes"]:
        for n, t in enumerate(sentences(s["narration"])):
            h = hashlib.sha256(f"{name}|{t}".encode()).hexdigest()[:16]
            items.append({"scene": s["id"], "n": n, "text": t, "file": f"{s['id']}_{n:02d}_{h}.wav"})
    todo = [i for i in items if not (tts / i["file"]).exists()]
    need = sum(len(i["text"]) for i in todo)
    if month_used() + need > limit:
        raise FreeLimitReached(f"free monthly limit: used {month_used()} + needed {need} > {limit} characters; no request sent")
    for it in todo:
        audio = _synth(key, it["text"], lang, name)
        (tts / it["file"]).write_bytes(audio)
        _add_usage(len(it["text"]))
    return {
        "mode": "parler",  # per-sentence files: the timeline treats them like any per-sentence TTS
        "provider": "Google Cloud Text-to-Speech, Chirp 3: HD (free monthly tier)",
        "model": name,
        "licence": "Google Cloud terms (GTTS-01)",
        "speaker": name,
        "cost_usd": 0.0,
        "characters": sum(len(i["text"]) for i in items),
        "items": items,
    }
