"""Load an owner-evidence MAC key version (CCR-100; 04 section 3.6a).

Run by the migrator at setup with key material read from the environment's secret mechanism by
the caller (``amw_core.config``); the key is passed straight to ``amw_evidence_mac_key_add`` and
never logged or returned. Rotation = a new, higher version (older versions are retired).
"""

import psycopg

from amw_core.errors import InputInvalidError

MIN_KEY_BYTES = 32


def install_evidence_mac_key(conninfo: str, version: int, key: bytes) -> None:
    if version < 1:
        raise InputInvalidError("key version starts at 1")
    if len(key) < MIN_KEY_BYTES:
        raise InputInvalidError("evidence MAC key must be at least 32 bytes")
    with psycopg.connect(conninfo) as conn:
        conn.execute("SELECT amw_evidence_mac_key_add(%s, %s)", (version, key))
