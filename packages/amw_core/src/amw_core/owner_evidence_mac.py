"""Verifier-provenance MAC of owner evidence (04 sections 3.6a and 5.16 ``evidence_mac`` /
``mac_key_version``; 08; CCR-100).

``evidence_mac`` = HMAC-SHA256 over the canonical evidence fields incl. ``org_id``, ``id`` and
``state`` (and, once confirmed, the confirmation fields), keyed by a versioned secret. In the
database the key lives in ``evidence_mac_keys`` (no grant to any role) and only the
``amw_verifier_fn`` definer functions stamp the MAC; in this package only the verifier side of
the store (``owner_evidence_fake.FakeEvidenceDatabase`` in tests; lane L1a's PostgreSQL functions
in production) holds a ``MacKeyring``. The key value reaches it only through the environment's
secret mechanism via ``amw_core.config`` (no module reads the environment itself; 27 section
7.3 rule 1). The keyring never exposes key bytes.
"""

import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final

from amw_core.errors import ConfigInvalidError

MIN_KEY_BYTES: Final = 32


def canonical_mac_material(fields: Mapping[str, Any]) -> bytes:
    """Canonical JSON (sorted keys, no whitespace); datetimes as ISO 8601."""

    def encode(value: Any) -> Any:
        return value.isoformat() if isinstance(value, datetime) else value

    material = {k: encode(v) for k, v in fields.items()}
    return json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


class MacKeyring:
    """Versioned HMAC keys; the newest version signs, every version verifies (rotation)."""

    __slots__ = ("__keys",)

    def __init__(self, keys: Mapping[int, bytes]) -> None:
        if not keys:
            raise ConfigInvalidError("evidence MAC keyring is empty")
        for version, key in keys.items():
            if version < 1 or len(key) < MIN_KEY_BYTES:
                raise ConfigInvalidError("evidence MAC key too short or bad version")
        self.__keys = dict(keys)

    @property
    def current_version(self) -> int:
        return max(self.__keys)

    def sign(self, version: int, fields: Mapping[str, Any]) -> bytes:
        key = self.__keys.get(version)
        if key is None:
            raise ConfigInvalidError("unknown evidence MAC key version")
        return hmac.new(key, canonical_mac_material(fields), hashlib.sha256).digest()

    def verify(self, version: int | None, fields: Mapping[str, Any], mac: bytes | None) -> bool:
        if version is None or mac is None or version not in self.__keys:
            return False
        return hmac.compare_digest(self.sign(version, fields), mac)

    def __repr__(self) -> str:
        return f"MacKeyring(versions={sorted(self.__keys)})"
