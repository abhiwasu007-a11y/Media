"""AI narration on Kaggle's free GPU (Kaggle terms: personal, non-commercial use only, KG-01; owner D24 keeps it
for now and switches to Google before monetizing): AI4Bharat Indic Parler-TTS (Apache-2.0), one file per sentence.

The dashboard VPS is too small for this model (several GB of RAM), so stage 07 sends the sentences to a private Kaggle
GPU notebook and downloads the audio. Re-uses the Kaggle REST helpers of ``motion_kaggle`` (push, poll, download).

The model is gated on Hugging Face, so the notebook needs the owner's read-only HF token: it is placed inside the
private notebook source (Kaggle's secret store has no public API). Use a read-only token; rotate it if the notebook is
ever shared.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from . import motion_kaggle as mk

MODEL_ID = "ai4bharat/indic-parler-tts"
# recommended speakers from the model card (README "Recommended Speakers"), with gender for the dashboard list
VOICES: dict[str, tuple[str, str, str]] = {
    "Sanjay": ("mr", "male", "मराठी"),
    "Sunita": ("mr", "female", "मराठी"),
    "Rohit": ("hi", "male", "हिन्दी"),
    "Divya": ("hi", "female", "हिन्दी"),
    "Thoma": ("en", "male", "English"),
    "Mary": ("en", "female", "English"),
}
DONE = "tts_done.json"


def speaker_for(lang: str, gender: str) -> str:
    """Recommended Parler speaker for the video language and gender (model card)."""
    for name, (code, g, _) in VOICES.items():
        if code == lang and g == gender:
            return name
    raise RuntimeError(f"no Kaggle (Parler) voice for language {lang}; choose the google provider in Settings")


def description(speaker: str) -> str:
    return (
        f"{speaker} speaks in a calm, warm and expressive voice at a moderate pace, with very clear audio "
        "and no background noise, recorded close to the microphone."
    )


def items_for(script: dict, speaker: str, sentences) -> list[dict]:
    out = []
    for s in script["scenes"]:
        for n, t in enumerate(sentences(s["narration"])):
            h = hashlib.sha256(f"{speaker}|{t}".encode()).hexdigest()[:16]
            out.append({"scene": s["id"], "n": n, "text": t, "file": f"{s['id']}_{n:02d}_{h}.wav"})
    return out


_KERNEL = """\
import json, os, subprocess, sys, traceback
OUT = "/kaggle/working"
ITEMS = json.loads(__ITEMS__)
DESC = __DESC__
os.environ["HF_TOKEN"] = __TOKEN__
res = {"done": [], "errors": {}}
def save():
    json.dump(res, open(os.path.join(OUT, "__DONE__"), "w"))
try:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "git+https://github.com/huggingface/parler-tts.git",
                    "soundfile"], check=True)
    import torch, soundfile as sf
    from parler_tts import ParlerTTSForConditionalGeneration
    from transformers import AutoTokenizer
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = ParlerTTSForConditionalGeneration.from_pretrained("__MODEL__").to(dev).eval()
    tok = AutoTokenizer.from_pretrained("__MODEL__")
    dtok = AutoTokenizer.from_pretrained(model.config.text_encoder._name_or_path)
    d = dtok(DESC, return_tensors="pt").to(dev)
except Exception:
    res["errors"]["setup"] = traceback.format_exc()[-1500:]
    save()
    raise SystemExit(0)
for it in ITEMS:
    try:
        torch.manual_seed(7)
        p = tok(it["text"], return_tensors="pt").to(dev)
        with torch.inference_mode():
            a = model.generate(input_ids=d.input_ids, attention_mask=d.attention_mask, prompt_input_ids=p.input_ids,
                               prompt_attention_mask=p.attention_mask, do_sample=True)
        sf.write(os.path.join(OUT, it["file"]), a.cpu().float().numpy().squeeze(), model.config.sampling_rate)
        res["done"].append(it["file"])
    except Exception as exc:
        res["errors"][it["file"]] = (type(exc).__name__ + ": " + str(exc))[:300]
    if len(res["done"]) % 20 == 0:
        save()
save()
"""


def kernel_source(items: list[dict], speaker: str, hf_token: str) -> str:
    return (
        _KERNEL.replace("__ITEMS__", repr(json.dumps([{"text": i["text"], "file": i["file"]} for i in items])))
        .replace("__DESC__", repr(description(speaker)))
        .replace("__TOKEN__", repr(hf_token))
        .replace("__MODEL__", MODEL_ID)
        .replace("__DONE__", DONE)
    )


def synthesize(
    job: Path, script: dict, speaker: str, sentences, username: str, key: str, hf_token: str, timeout_s: int = 3 * 3600, log=print
) -> dict:
    """Generate the missing sentence files into job/tts on Kaggle; return the voice.json payload (mode parler)."""
    items = items_for(script, speaker, sentences)
    tts = job / "tts"
    tts.mkdir(exist_ok=True)
    todo = [i for i in items if not (tts / i["file"]).exists()]
    if todo:
        slug = f"amw-tts-{job.name[-20:].lower().replace('_', '-')}-{int(time.time())}"[:50]
        # the title must slugify to the slug (official client rule), so the slug itself is the title
        resp = mk.push_kernel(username, key, slug, slug, kernel_source(todo, speaker, hf_token), timeout_s)
        slug = mk.resolved_slug(resp, slug)
        status, msg = mk.wait_for_kernel(username, key, slug, timeout_s, log)
        (tts / DONE).unlink(missing_ok=True)
        try:
            mk.download_outputs(username, key, slug, tts)
        except RuntimeError as exc:
            msg = msg or str(exc)
        missing = [i["file"] for i in items if not (tts / i["file"]).exists()]
        if missing:
            done = {}
            try:
                done = json.loads((tts / DONE).read_text())
            except (OSError, ValueError):
                pass
            raise RuntimeError(
                f"Kaggle TTS {status}: {len(missing)} of {len(items)} sentences missing; "
                f"{msg or ''} {str(done.get('errors', {}))[:300]}"
            )
    return {
        "mode": "parler",
        "provider": "AI4Bharat Indic Parler-TTS on a Kaggle GPU notebook (free)",
        "model": MODEL_ID,
        "licence": "Apache-2.0",
        "speaker": speaker,
        "description": description(speaker),
        "cost_usd": 0.0,
        "items": items,
    }
