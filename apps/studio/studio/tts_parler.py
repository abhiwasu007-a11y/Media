"""Free local TTS: AI4Bharat Indic Parler-TTS (Apache-2.0), CPU. Cost 0.

Optional extra (torch + parler-tts, see Dockerfile build arg WITH_TTS=1). The model is gated on Hugging Face:
the account must accept its terms once, and the read token is given as HF_TOKEN (environment secret).
Each sentence is cached by hash, so an interrupted run resumes.
"""

import hashlib
import os
from pathlib import Path

MODEL_ID = "ai4bharat/indic-parler-tts"


def synthesize(job: Path, script: dict, speaker: str) -> dict:
    import soundfile as sf
    import torch
    from parler_tts import ParlerTTSForConditionalGeneration
    from transformers import AutoTokenizer

    from .pipeline import sentences

    torch.set_num_threads(int(os.environ.get("AMW_TTS_THREADS", "2")))
    out = job / "tts"
    out.mkdir(exist_ok=True)
    desc_text = (
        f"{speaker} speaks in a calm, warm and expressive voice at a moderate pace, with very clear audio "
        "and no background noise, recorded close to the microphone."
    )
    model = ParlerTTSForConditionalGeneration.from_pretrained(MODEL_ID).eval()
    tok = AutoTokenizer.from_pretrained(MODEL_ID)
    dtok = AutoTokenizer.from_pretrained(model.config.text_encoder._name_or_path)
    desc = dtok(desc_text, return_tensors="pt")
    items = []
    for s in script["scenes"]:
        for n, sent in enumerate(sentences(s["narration"])):
            h = hashlib.sha256(f"{speaker}|{sent}".encode()).hexdigest()[:16]
            f = out / f"{s['id']}_{n:02d}_{h}.wav"
            if not f.exists():
                torch.manual_seed(7)
                p = tok(sent, return_tensors="pt")
                with torch.inference_mode():
                    audio = model.generate(
                        input_ids=desc.input_ids,
                        attention_mask=desc.attention_mask,
                        prompt_input_ids=p.input_ids,
                        prompt_attention_mask=p.attention_mask,
                        do_sample=True,
                    )
                sf.write(f, audio.cpu().numpy().squeeze(), model.config.sampling_rate)
            items.append({"scene": s["id"], "n": n, "text": sent, "file": f.name})
    return {
        "provider": "AI4Bharat Indic Parler-TTS (local CPU)",
        "model": MODEL_ID,
        "licence": "Apache-2.0",
        "speaker": speaker,
        "description": desc_text,
        "cost_usd": 0.0,
        "items": items,
    }
