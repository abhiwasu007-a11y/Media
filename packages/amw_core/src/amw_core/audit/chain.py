"""Hash chain of ``audit_log`` (04 section 5.13; 08 section 9.1).

``row_hash = SHA-256(prev_hash || canonical JSON of every column except row_hash)``; the genesis
``prev_hash`` is 32 zero bytes. The canonical JSON is built from the **stored** column values so a
verifier can recompute it from the table alone:

* keys sorted, no insignificant whitespace, UTF-8 (``ensure_ascii=False``);
* UUID columns as the canonical lowercase UUID string (the wire prefix is not stored);
* ``occurred_at`` as ``YYYY-MM-DDTHH:MM:SS.ffffffZ`` (UTC, microseconds, the timestamptz precision);
* ``prev_hash`` as lowercase hex; ``seq`` as an integer; ``details`` as JSON.

``details`` may hold only strings, integers, booleans, null, lists and objects (no floats: their
JSON spelling is not stable across jsonb; same rule as 03 section 9.1), no NUL characters, and no
secrets (08 section 3.1 rule 3).
"""

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from amw_core.enums import ActorKind
from amw_core.errors import InputInvalidError
from amw_core.ids import (
    AUDIT_ENTRY,
    CORRELATION,
    JOB,
    ORG,
    USER,
    Prefix,
    is_actor_ref,
    parse_id,
)
from amw_core.interfaces.audit_log import AuditEntry, ChainVerification, NewAuditEntry
from amw_core.observability.redaction import contains_secret

GENESIS_HASH = bytes(32)
MAX_DETAILS_BYTES = 64 * 1024


def format_ts(value: datetime) -> str:
    if value.tzinfo is None:
        raise InputInvalidError("audit timestamps must be timezone-aware (UTC)")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _check_json(value: Any, depth: int = 0) -> None:
    if depth > 32:
        raise InputInvalidError("audit details nested too deeply")
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, str):
        if "\x00" in value:
            raise InputInvalidError("audit details may not contain NUL characters")
        return
    if isinstance(value, Mapping):
        for k, v in value.items():
            if not isinstance(k, str):
                raise InputInvalidError("audit details keys must be strings")
            _check_json(k, depth + 1)
            _check_json(v, depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for v in value:
            _check_json(v, depth + 1)
        return
    raise InputInvalidError(f"audit details value of type {type(value).__name__} is not allowed")


def target_prefix(target_kind: str) -> Prefix:
    """``target_kind`` names the entity (``TASK``, ``JOB``, ``BUDGET`` ...: a GLOSSARY section 2.2
    entity name); ``target_id`` must carry that entity's prefix."""
    try:
        return Prefix[target_kind]
    except KeyError:
        raise InputInvalidError(f"unknown audit target_kind {target_kind!r}") from None


def validate_entry(entry: NewAuditEntry) -> None:
    if not is_actor_ref(entry.actor_ref):
        raise InputInvalidError("audit actor_ref is not a valid actor reference")
    ActorKind(entry.actor_kind)
    for name in ("authority", "action", "target_kind"):
        if not getattr(entry, name):
            raise InputInvalidError(f"audit {name} is required")
    if entry.target_id is not None:
        parse_id(entry.target_id, target_prefix(entry.target_kind))
    format_ts(entry.occurred_at)
    _check_json(entry.details)
    encoded = json.dumps(entry.details, sort_keys=True, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAX_DETAILS_BYTES:
        raise InputInvalidError("audit details too large")
    if contains_secret(dict(entry.details)):
        raise InputInvalidError("audit details look like they contain a secret (08 section 3.1)")


def _uuid(wire: str | None, prefix: Prefix) -> str | None:
    return None if wire is None else str(parse_id(wire, prefix))


def stored_columns(
    entry_id: str, org_id: str, seq: int, entry: NewAuditEntry, prev_hash: bytes
) -> dict[str, Any]:
    """The column values (DB-native form) that the hash covers."""
    return {
        "id": _uuid(entry_id, AUDIT_ENTRY.prefix),
        "org_id": _uuid(org_id, ORG.prefix),
        "seq": seq,
        "occurred_at": format_ts(entry.occurred_at),
        "actor_kind": str(entry.actor_kind),
        "actor_ref": entry.actor_ref,
        "on_behalf_of": _uuid(entry.on_behalf_of, USER.prefix),
        "authority": entry.authority,
        "action": entry.action,
        "target_kind": entry.target_kind,
        "target_id": (
            None
            if entry.target_id is None
            else _uuid(entry.target_id, target_prefix(entry.target_kind))
        ),
        "job_id": _uuid(entry.job_id, JOB.prefix),
        "correlation_id": _uuid(entry.correlation_id, CORRELATION.prefix),
        "details": json.loads(json.dumps(entry.details)),
        "prev_hash": prev_hash.hex(),
    }


def canonical_bytes(columns: Mapping[str, Any]) -> bytes:
    return json.dumps(columns, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def row_hash(prev_hash: bytes, columns: Mapping[str, Any]) -> bytes:
    if len(prev_hash) != 32:
        raise InputInvalidError("prev_hash must be 32 bytes")
    return hashlib.sha256(prev_hash + canonical_bytes(columns)).digest()


def hash_entry(entry: AuditEntry) -> bytes:
    columns = stored_columns(entry.id, entry.org_id, entry.seq, entry.entry, entry.prev_hash)
    return row_hash(entry.prev_hash, columns)


@dataclass(frozen=True, slots=True)
class ChainHead:
    last_seq: int
    last_hash: bytes


def verify_entries(entries: Iterable[AuditEntry], head: ChainHead | None) -> ChainVerification:
    """Recompute the chain from genesis: ``seq`` gap-free from 1, each ``prev_hash`` equals the
    previous ``row_hash``, each ``row_hash`` recomputes, and the head matches the last row
    (detects truncation of the tail)."""
    expected_prev = GENESIS_HASH
    expected_seq = 1
    checked = 0
    for entry in entries:
        if (
            entry.seq != expected_seq
            or entry.prev_hash != expected_prev
            or hash_entry(entry) != entry.row_hash
        ):
            return ChainVerification(ok=False, entries_checked=checked, first_bad_seq=expected_seq)
        expected_prev = entry.row_hash
        expected_seq += 1
        checked += 1
    last_seq = expected_seq - 1
    if head is None:
        head = ChainHead(0, GENESIS_HASH)
    if head.last_seq != last_seq or head.last_hash != expected_prev:
        bad = min(head.last_seq, last_seq) + 1
        return ChainVerification(ok=False, entries_checked=checked, first_bad_seq=bad)
    return ChainVerification(ok=True, entries_checked=checked, first_bad_seq=None)


def export_record(entry: AuditEntry) -> dict[str, Any]:
    """JSON export form (27 section 9 "Records"): wire IDs for readers plus the stored hashes."""
    e = entry.entry
    return {
        "id": entry.id,
        "org_id": entry.org_id,
        "seq": entry.seq,
        "occurred_at": format_ts(e.occurred_at),
        "actor_kind": str(e.actor_kind),
        "actor_ref": e.actor_ref,
        "on_behalf_of": e.on_behalf_of,
        "authority": e.authority,
        "action": e.action,
        "target_kind": e.target_kind,
        "target_id": e.target_id,
        "job_id": e.job_id,
        "correlation_id": e.correlation_id,
        "details": json.loads(json.dumps(e.details)),
        "prev_hash": entry.prev_hash.hex(),
        "row_hash": entry.row_hash.hex(),
    }


def export_json(entries: Iterable[AuditEntry]) -> str:
    """The tenant export as one JSON document (``{"audit_log": [...]}``) in ``seq`` order."""
    return json.dumps(
        {"audit_log": [export_record(e) for e in entries]}, ensure_ascii=False, sort_keys=True
    )


def wire_from_uuid(prefix: Prefix, value: uuid.UUID | str | None) -> str | None:
    if value is None:
        return None
    u = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    return f"{prefix.value}_{u}"
