"""Runtime settings: dashboard Settings page first, then environment variables (.env). No secret values in code.

The dashboard store is data/settings.json (file mode 0600, inside the data volume, never in git). Secret values are
write-only from the dashboard: they are never sent back to a browser. Every change is appended to data/audit.log with
the time, the user and the names of the changed fields (never the values).
"""

import json
import math
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    model: str
    price_in: float  # USD per input token
    price_out: float  # USD per output token
    per_video_cap_usd: float
    pilot_cap_usd: float
    words_per_second: float  # timing estimate when there is no voice yet


def data_dir() -> Path:
    p = Path(os.environ.get("AMW_STUDIO_DATA", "./data")).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def jobs_dir() -> Path:
    p = data_dir() / "jobs"
    p.mkdir(parents=True, exist_ok=True)
    return p


# name, label, kind ("secret" | "text" | "number" | "select"), default, options
FIELDS: list[tuple[str, str, str, str, tuple[str, ...]]] = [
    ("AMW_SECRET_ANTHROPIC_API_KEY", "Anthropic API key (script, fact-check)", "secret", "", ()),
    (
        "AMW_LLM_MODEL",
        "Script model (owner decision D21: Opus)",
        "select",
        "claude-opus-5-5",
        ("claude-opus-5-5", "claude-sonnet-5-5"),
    ),
    ("AMW_IMAGE_PROVIDER", "AI picture source", "select", "cloudflare", ("cloudflare", "bfl", "off")),
    ("AMW_CF_ACCOUNT_ID", "Cloudflare account ID (free Workers AI)", "text", "", ()),
    ("AMW_SECRET_CF_AI_TOKEN", "Cloudflare API token with Workers AI permission", "secret", "", ()),
    ("AMW_SECRET_BFL_API_KEY", "Black Forest Labs key (paid, only if source = bfl)", "secret", "", ()),
    ("AMW_MAX_AI_IMAGES", "Max AI pictures per video", "number", "80", ()),
    (
        "AMW_VOICE_PROVIDER",
        "AI voice provider (owner D24: kaggle for now; Kaggle terms are non-commercial: switch to google before monetizing)",
        "select",
        "kaggle",
        ("kaggle", "google"),
    ),
    (
        "AMW_SECRET_HF_TOKEN",
        "Hugging Face read token (Kaggle AI voice; placed in your private Kaggle notebook)",
        "secret",
        "",
        (),
    ),
    ("AMW_SECRET_GOOGLE_TTS_KEY", "Google Cloud Text-to-Speech API key (AI voice, free monthly tier)", "secret", "", ()),
    (
        "AMW_GOOGLE_TTS_FREE_CHARS",
        "AI voice: stop before this many characters per month (free tier: 1,000,000)",
        "number",
        "1000000",
        (),
    ),
    ("AMW_SECRET_PIXABAY_API_KEY", "Pixabay API key (free stock video)", "secret", "", ()),
    ("AMW_MAX_STOCK_CLIPS", "Max stock clips per video", "number", "10", ()),
    (
        "AMW_MOTION_PROVIDER",
        "AI motion clips on Kaggle (Kaggle terms: non-commercial use only; keep OFF for monetized channels)",
        "select",
        "off",
        ("off", "kaggle"),
    ),
    ("AMW_KAGGLE_USERNAME", "Kaggle username", "text", "", ()),
    ("AMW_SECRET_KAGGLE_KEY", "Kaggle API key", "secret", "", ()),
    ("AMW_MAX_MOTION_CLIPS", "Max motion clips per video", "number", "8", ()),
    ("AMW_BUDGET_PER_VIDEO_USD", "Per-video cap, USD (D9)", "number", "5.0", ()),
    ("AMW_BUDGET_PILOT_USD", "Pilot cap, USD (D9)", "number", "50.0", ()),
]
BUDGET_FIELDS = {"AMW_BUDGET_PER_VIDEO_USD", "AMW_BUDGET_PILOT_USD"}
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0)}  # USD per MTok (claude-api skill table)
_lock = threading.Lock()


def _store() -> Path:
    return data_dir() / "settings.json"


def stored() -> dict:
    f = _store()
    return json.loads(f.read_text()) if f.exists() else {}


def get(name: str, default: str = "") -> str:
    """Dashboard value if set, else the environment, else the field default."""
    v = stored().get(name)
    if v not in (None, ""):
        return str(v)
    env = os.environ.get(name)
    if env not in (None, ""):
        return env
    return next((f[3] for f in FIELDS if f[0] == name), default) or default


def is_set(name: str) -> bool:
    return bool(stored().get(name) or os.environ.get(name))


def update(values: dict[str, str], user: str, clear: list[str] | None = None) -> list[str]:
    """Save changed fields (empty secret input = keep the old value). Returns the changed field names."""
    known = {f[0]: f for f in FIELDS}
    with _lock:
        cur = stored()
        changed = []
        for k, v in values.items():
            if k not in known:
                continue
            f = known[k]
            v = (v or "").strip()
            if f[2] == "secret" and not v:
                continue
            if f[2] == "number" and v:
                try:
                    num = float(v)
                except ValueError as exc:
                    raise ValueError(f"{k}: not a number") from exc
                if not math.isfinite(num) or num < 0:
                    raise ValueError(f"{k}: must be a finite number >= 0")
                if k in BUDGET_FIELDS and num <= 0:
                    raise ValueError(f"{k}: budget must be greater than 0")
            if f[2] == "select" and v not in f[4]:
                raise ValueError(f"{k}: unsupported value")
            if cur.get(k) != v:
                cur[k] = v
                changed.append(k)
        for k in clear or []:
            if k in cur:
                cur.pop(k)
                changed.append(k)
        f = _store()
        tmp = f.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # 0600 from the first byte
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(cur, indent=1))
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)  # in case the temp file already existed with looser bits
        os.replace(tmp, f)
        if changed:
            audit(user, "settings.update", {"fields": changed})
    return changed


def audit(user: str, action: str, details: dict) -> None:
    line = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "user": user, "action": action, **details}
    with (data_dir() / "audit.log").open("a") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")


def load() -> Settings:
    e = get
    return Settings(
        model=e("AMW_LLM_MODEL", "claude-opus-5-5"),
        price_in=PRICES.get(e("AMW_LLM_MODEL", "claude-opus-5-5"), (4.0, 20.0))[0] / 1e6,
        price_out=PRICES.get(e("AMW_LLM_MODEL", "claude-opus-5-5"), (4.0, 20.0))[1] / 1e6,
        per_video_cap_usd=float(e("AMW_BUDGET_PER_VIDEO_USD", "5.0")),
        pilot_cap_usd=float(e("AMW_BUDGET_PILOT_USD", "50.0")),
        words_per_second=float(os.environ.get("AMW_EST_WORDS_PER_SECOND", "2.45")),
    )
