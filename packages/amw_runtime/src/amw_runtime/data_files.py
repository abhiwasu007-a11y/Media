"""Locate and read the packaged data files (owner decisions and calendars are data, not code)."""

import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent / "data"


def read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"unreadable data file {path.name}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"data file {path.name} is not a JSON object")
    return raw
