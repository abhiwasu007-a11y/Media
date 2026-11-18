"""Canonical JSON and SHA-256 helpers (blueprint 7.2: ``claims_sha256``; 03 9.1)."""

import hashlib
import json
from collections.abc import Sequence
from typing import Any


def canonical_json(value: Any) -> str:
    """UTF-8 text, keys sorted, separators ``,`` and ``:``, no ASCII escaping."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(data: str | bytes) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


def claims_sha256(claims: Sequence[Any]) -> str:
    """SHA-256 of the canonical JSON of the claims list (as wire documents)."""
    return sha256_hex(canonical_json(list(claims)))
