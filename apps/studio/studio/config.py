"""Runtime settings from environment variables (see .env.example). No secrets here."""

import os
from dataclasses import dataclass
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


def load() -> Settings:
    e = os.environ.get
    return Settings(
        model=e("AMW_LLM_MODEL", "claude-opus-5-5"),
        # Opus 5.5 list price USD 4 / 20 per million tokens; change together with AMW_LLM_MODEL.
        price_in=float(e("AMW_LLM_PRICE_IN_PER_MTOK", "4.0")) / 1e6,
        price_out=float(e("AMW_LLM_PRICE_OUT_PER_MTOK", "20.0")) / 1e6,
        per_video_cap_usd=float(e("AMW_BUDGET_PER_VIDEO_USD", "5.0")),
        pilot_cap_usd=float(e("AMW_BUDGET_PILOT_USD", "50.0")),
        words_per_second=float(e("AMW_EST_WORDS_PER_SECOND", "2.45")),
    )
