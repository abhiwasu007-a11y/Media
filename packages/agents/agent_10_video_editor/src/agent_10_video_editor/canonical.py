"""Canonical JSON and SHA-256 helpers (blueprint 10 section 10 F-08; 03 section 9.1 form).

Sorted keys, no insignificant whitespace, integers and strings only: a float anywhere in a
hashed structure is a contract violation (``InputInvalidError``), never silently rounded.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from amw_core.errors import InputInvalidError


def _reject_floats(value: Any, path: str = "$") -> None:
    if isinstance(value, float):
        raise InputInvalidError("float in a canonical structure", details={"violations": [path]})
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_floats(item, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for index, item in enumerate(value):
            _reject_floats(item, f"{path}[{index}]")


def canonical_json(value: Any) -> bytes:
    """Canonical UTF-8 JSON bytes of ``value`` (no floats)."""
    _reject_floats(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_hex(canonical_json(value))
