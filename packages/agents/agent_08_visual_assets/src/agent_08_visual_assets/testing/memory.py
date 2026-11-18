"""In-memory fakes of the repositories and of blob storage / audit log (tests and fixtures only).

Every row is partitioned by the transaction's ``org_id`` (a fake tenant boundary); nothing here is
for production use. ``amw_core.testing.memory`` has no blob storage or audit fake yet (core need).
"""

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from datetime import UTC, datetime
from itertools import count

from agent_08_visual_assets.persistence.records import (
    AssetRecord,
    FingerprintRow,
    LedgerEntry,
    LicenceRecord,
    NewAsset,
    NewLedgerEntry,
)
from amw_core.enums import ActorKind, AssetKind, AssetStatus, LicenceSourceType
from amw_core.errors import (
    CorruptedOutputError,
    CrossTenantRefError,
    InputInvalidError,
    MissingDependencyError,
    PermissionDeniedError,
)
from amw_core.ids import ASSET, AUDIT_ENTRY, Prefix, new_id
from amw_core.interfaces.audit_log import AuditEntry, ChainVerification, NewAuditEntry
from amw_core.interfaces.storage import BlobHead, BlobInfo, BlobUri, ReadableStream
from amw_core.interfaces.tenancy_context import TenantContext, TenantTransaction

_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)


def _org(tx: TenantTransaction) -> str:
    return str(tx.context.org_id)


class MemoryBlobStorage:
    """``BlobStorage`` fake: tenant check first, write-once, SHA-256 verified on read."""

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}
        self.puts: list[str] = []

    @staticmethod
    def _owner(uri: str) -> str:
        return uri.removeprefix("amw-blob://").split("/", 1)[0]

    def _check(self, context: TenantContext, uri: str, *, write: bool) -> None:
        owner = self._owner(uri)
        if owner == "platform":
            if write:
                raise PermissionDeniedError("platform area is read-only")
            return
        if owner != str(context.org_id):
            raise CrossTenantRefError("reference belongs to another tenant")

    def blob_uri(self, context: TenantContext, area: str, path: str) -> BlobUri:
        return BlobUri(f"amw-blob://{context.org_id}/{area}/{path}")

    def put(self, context: TenantContext, uri: BlobUri, stream: ReadableStream) -> BlobInfo:
        self._check(context, uri, write=True)
        if uri in self._blobs:
            raise InputInvalidError("blob path already exists (write-once)")
        data = stream.read()
        self._blobs[uri] = data
        self.puts.append(uri)
        return BlobInfo(uri, hashlib.sha256(data).hexdigest(), len(data))

    def get(self, context: TenantContext, uri: BlobUri, expected_sha256: str) -> Iterator[bytes]:
        self._check(context, uri, write=False)
        if uri not in self._blobs:
            raise MissingDependencyError("blob not found")
        data = self._blobs[uri]
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise CorruptedOutputError("blob hash mismatch")
        yield data

    def head(self, context: TenantContext, uri: BlobUri) -> BlobHead:
        self._check(context, uri, write=False)
        data = self._blobs.get(uri)
        if data is None:
            return BlobHead(False, None, None)
        return BlobHead(True, hashlib.sha256(data).hexdigest(), len(data))

    def list_prefix(self, context: TenantContext, org_id: object, area: str) -> Iterable[BlobInfo]:
        prefix = f"amw-blob://{context.org_id}/{area}/"
        return [
            BlobInfo(BlobUri(u), hashlib.sha256(d).hexdigest(), len(d))
            for u, d in self._blobs.items()
            if u.startswith(prefix)
        ]

    def tamper(self, uri: str, data: bytes) -> None:
        """Test helper: change a stored blob behind the store's back (S-06)."""
        self._blobs[uri] = data


class MemoryAssetRepository:
    def __init__(self) -> None:
        self._rows: dict[str, dict[str, AssetRecord]] = defaultdict(dict)
        self.uses: dict[tuple[str, str, str], int] = defaultdict(int)

    def insert(self, tx: TenantTransaction, asset: NewAsset) -> AssetRecord:
        org = _org(tx)
        existing = self.find_by_sha(tx, asset.content_sha256)
        if existing is not None:
            return existing
        record = AssetRecord(
            str(new_id(Prefix.ASSET)), org, AssetStatus.ACTIVE, datetime.now(UTC), asset
        )
        self._rows[org][record.asset_id] = record
        return record

    def get(self, tx: TenantTransaction, asset_id: str) -> AssetRecord | None:
        ASSET.validate(asset_id)
        return self._rows[_org(tx)].get(asset_id)

    def find_by_sha(self, tx: TenantTransaction, content_sha256: str) -> AssetRecord | None:
        for rec in self._rows[_org(tx)].values():
            if rec.asset.content_sha256 == content_sha256:
                return rec
        return None

    def list_assets(
        self,
        tx: TenantTransaction,
        *,
        kinds: Sequence[AssetKind],
        source_types: Sequence[LicenceSourceType] | None = None,
    ) -> Sequence[AssetRecord]:
        return [
            r
            for r in self._rows[_org(tx)].values()
            if r.asset.kind in kinds
            and (source_types is None or r.asset.source_type in source_types)
        ]

    def uses_in_window(self, tx: TenantTransaction, asset_id: str, channel_id: str) -> int:
        return self.uses[(_org(tx), asset_id, channel_id)]

    def set_status(self, org_id: str, asset_id: str, status: AssetStatus) -> None:
        rec = self._rows[org_id][asset_id]
        self._rows[org_id][asset_id] = AssetRecord(
            rec.asset_id, rec.org_id, status, rec.created_at, rec.asset
        )


class MemoryLicenceRepository:
    """Read side; ``add`` is a test helper standing in for the owner's licence registration."""

    def __init__(self) -> None:
        self._rows: dict[str, LicenceRecord] = {}

    def add(self, record: LicenceRecord) -> None:
        self._rows[record.licence_id] = record

    def get(self, tx: TenantTransaction, licence_id: str) -> LicenceRecord | None:
        rec = self._rows.get(licence_id)
        if rec is None or rec.org_id not in (None, _org(tx)):
            return None
        return rec

    def self_grant(
        self, tx: TenantTransaction, source_type: LicenceSourceType
    ) -> LicenceRecord | None:
        key = f"self_grant.{source_type.value}"
        for rec in self._rows.values():
            if rec.org_id == _org(tx) and rec.licence_key == key:
                return rec
        return None

    def active_for_source(
        self, tx: TenantTransaction, source_type: LicenceSourceType
    ) -> LicenceRecord | None:
        for rec in self._rows.values():
            if (
                rec.org_id in (None, _org(tx))
                and rec.source_type is source_type
                and not rec.licence_key.startswith("self_grant.")
            ):
                return rec
        return None


class MemoryLedgerRepository:
    def __init__(self) -> None:
        self._rows: dict[str, dict[tuple[object, ...], LedgerEntry]] = defaultdict(dict)
        self._seq = count(1)

    def write(self, tx: TenantTransaction, entry: NewLedgerEntry) -> LedgerEntry:
        org = _org(tx)
        key = (
            entry.task_id,
            entry.asset_id,
            entry.usage_kind,
            entry.shot_id,
            entry.used_from_ms,
        )
        stored = self._rows[org].get(key)
        if stored is not None:
            return stored
        row = LedgerEntry(str(new_id(Prefix.LICENCE_LEDGER_ENTRY)), org, entry)
        self._rows[org][key] = row
        return row

    def for_job(self, tx: TenantTransaction, job_id: str) -> Sequence[LedgerEntry]:
        return [r for r in self._rows[_org(tx)].values() if r.entry.job_id == job_id]


class MemoryFingerprintRepository:
    def __init__(self) -> None:
        self._rows: dict[str, list[FingerprintRow]] = defaultdict(list)

    def add(self, tx: TenantTransaction, rows: Sequence[FingerprintRow]) -> None:
        stored = self._rows[_org(tx)]
        for row in rows:
            if row not in stored:
                stored.append(row)

    def for_asset(self, tx: TenantTransaction, asset_id: str) -> Sequence[FingerprintRow]:
        return [r for r in self._rows[_org(tx)] if r.asset_id == asset_id]

    def perceptual_library(self, tx: TenantTransaction) -> Sequence[tuple[str, str]]:
        seen: dict[str, str] = {}
        for r in self._rows[_org(tx)]:
            if r.algo == "PERCEPTUAL_FRAME" and r.asset_id not in seen:
                seen[r.asset_id] = r.value_hex
        return list(seen.items())


class MemoryReleaseApprovals:
    def __init__(self) -> None:
        self._approved: set[tuple[str, str, str]] = set()

    def approve(self, org_id: str, asset_id: str, sha256: str) -> None:
        self._approved.add((org_id, asset_id, sha256))

    def is_released(self, tx: TenantTransaction, asset_id: str, subject_sha256: str) -> bool:
        return (_org(tx), asset_id, subject_sha256) in self._approved


class MemoryAuditLog:
    """Append-only list per tenant (no hash chain: the real chain is L1's)."""

    def __init__(self) -> None:
        self.entries: dict[str, list[NewAuditEntry]] = defaultdict(list)

    def append(self, tx: TenantTransaction, entry: NewAuditEntry) -> AuditEntry:
        org = _org(tx)
        self.entries[org].append(entry)
        seq = len(self.entries[org])
        digest = hashlib.sha256(f"{org}:{seq}".encode()).digest()
        return AuditEntry(
            id=AUDIT_ENTRY.new(),
            org_id=tx.context.org_id,
            seq=seq,
            entry=entry,
            prev_hash=digest,
            row_hash=digest,
        )

    def verify_chain(self, tx: TenantTransaction) -> ChainVerification:
        return ChainVerification(True, len(self.entries[_org(tx)]), None)

    def export(
        self, tx: TenantTransaction, since_seq: int = 0, target_id: str | None = None
    ) -> Iterator[AuditEntry]:
        raise NotImplementedError

    def actions(self, org_id: str) -> list[str]:
        return [e.action for e in self.entries[org_id]]


__all__ = [
    "ActorKind",
    "MemoryAssetRepository",
    "MemoryAuditLog",
    "MemoryBlobStorage",
    "MemoryFingerprintRepository",
    "MemoryLedgerRepository",
    "MemoryLicenceRepository",
    "MemoryReleaseApprovals",
]
