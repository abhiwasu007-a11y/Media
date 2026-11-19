"""ADR-005 local-disk backend: write-once, atomic publish, SHA-256 verification, tenant check
(04 section 3.7.8), list_prefix; kill during put leaves no file (07 section 8.4)."""

import errno
import hashlib
import io
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from amw_core.config import load_settings
from amw_core.errors import (
    ConfigInvalidError,
    CorruptedOutputError,
    CrossTenantRefError,
    DiskFullError,
    InputInvalidError,
    MissingDependencyError,
    StorageUnavailableError,
)
from amw_core.ids import JOB, ORG, ActorRef, new_uuid7
from amw_core.interfaces.storage import BlobStorage, BlobUri
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.storage import LocalDiskStorage, parse_uri, storage_from_settings
from amw_core.storage.local import TEMP_PREFIX

pytestmark = pytest.mark.unit
A = TenantContext(ORG.new(), ActorRef("agent_10"))
B = TenantContext(ORG.new(), ActorRef("agent_10"))
J = str(JOB.new())
DATA = b"x" * 5000 + b"tail"
SHA = hashlib.sha256(DATA).hexdigest()


@pytest.fixture
def store(tmp_path: Path) -> LocalDiskStorage:
    return LocalDiskStorage(tmp_path / "root", chunk_bytes=1024)


def _uri(ctx: TenantContext, path: str = f"jobs/{J}/renders/master.mp4") -> BlobUri:
    return BlobUri(f"amw-blob://{ctx.org_id}/{path}")


def test_is_a_blob_storage(store: LocalDiskStorage) -> None:
    assert isinstance(store, BlobStorage)


def test_put_get_head_roundtrip_and_physical_mapping(
    store: LocalDiskStorage, tmp_path: Path
) -> None:
    uri = store.blob_uri(A, "jobs", f"{J}/renders/master.mp4")
    info = store.put(A, uri, io.BytesIO(DATA))
    assert (info.sha256, info.size_bytes, info.uri) == (SHA, len(DATA), uri)
    assert b"".join(store.get(A, uri, SHA)) == DATA
    head = store.head(A, uri)
    assert (head.exists, head.sha256, head.size_bytes) == (True, SHA, len(DATA))
    physical = tmp_path / "root" / str(ORG.to_uuid(A.org_id)) / f"jobs/{J}/renders/master.mp4"
    assert (physical.is_file() and not os.access(physical, os.W_OK)) or os.geteuid() == 0
    assert oct(physical.stat().st_mode & 0o777) == "0o444"
    assert store.head(A, _uri(A, f"jobs/{J}/renders/none.bin")).exists is False


def test_write_once_refuses_even_identical_content(store: LocalDiskStorage) -> None:
    uri = _uri(A)
    store.put(A, uri, io.BytesIO(DATA))
    with pytest.raises(InputInvalidError, match="write-once"):
        store.put(A, uri, io.BytesIO(DATA))


@pytest.mark.security
@pytest.mark.tenancy
def test_cross_tenant_uri_is_rejected_on_every_operation(store: LocalDiskStorage) -> None:
    uri = _uri(A)
    store.put(A, uri, io.BytesIO(DATA))
    with pytest.raises(CrossTenantRefError):
        store.put(B, uri, io.BytesIO(b"evil"))
    with pytest.raises(CrossTenantRefError):
        list(store.get(B, uri, SHA))
    with pytest.raises(CrossTenantRefError):
        store.head(B, uri)
    with pytest.raises(CrossTenantRefError):
        store.list_prefix(B, A.org_id, "jobs")
    assert list(store.list_prefix(B, B.org_id, "jobs")) == []


@pytest.mark.security
def test_platform_blobs_are_read_only_for_tenants(store: LocalDiskStorage, tmp_path: Path) -> None:
    platform = BlobUri("amw-blob://platform/templates/title_card.svg")
    with pytest.raises(CrossTenantRefError):
        store.put(A, platform, io.BytesIO(b"x"))
    target = tmp_path / "root" / "platform" / "templates"
    target.mkdir(parents=True)
    (target / "title_card.svg").write_bytes(b"<svg/>")
    digest = hashlib.sha256(b"<svg/>").hexdigest()
    assert b"".join(store.get(A, platform, digest)) == b"<svg/>"
    assert store.head(B, platform).exists


@pytest.mark.security
@pytest.mark.parametrize(
    "uri",
    [
        "s3://bucket/x",
        "amw-blob://org_x/jobs/a",
        "amw-blob://{org}/jobs",
        "amw-blob://{org}/unknown_area/a",
        "amw-blob://{org}/jobs/../../etc/passwd",
        "amw-blob://{org}/jobs/a//b",
        "amw-blob://{org}/jobs/.hidden",
        "amw-blob://{org}/jobs/a b",
    ],
)
def test_malformed_or_unsafe_uris(store: LocalDiskStorage, uri: str) -> None:
    with pytest.raises(InputInvalidError):
        store.put(A, BlobUri(uri.format(org=A.org_id)), io.BytesIO(b"x"))


def test_get_verifies_sha_before_the_last_chunk(store: LocalDiskStorage, tmp_path: Path) -> None:
    uri = _uri(A)
    store.put(A, uri, io.BytesIO(DATA))
    received: list[bytes] = []
    chunks = store.get(A, uri, "0" * 64)
    with pytest.raises(CorruptedOutputError):
        received.extend(chunks)
    assert b"".join(received) != DATA
    assert len(b"".join(received)) < len(DATA)
    # tamper with the stored bytes: detected by the reader
    physical = tmp_path / "root" / str(ORG.to_uuid(A.org_id)) / f"jobs/{J}/renders/master.mp4"
    physical.chmod(0o644)
    physical.write_bytes(DATA[:-1] + b"!")
    with pytest.raises(CorruptedOutputError):
        b"".join(store.get(A, uri, SHA))
    with pytest.raises(MissingDependencyError):
        store.get(A, _uri(A, f"jobs/{J}/renders/missing.bin"), SHA)


def test_small_and_empty_blobs(store: LocalDiskStorage) -> None:
    empty = _uri(A, f"jobs/{J}/renders/empty.json")
    info = store.put(A, empty, io.BytesIO(b""))
    assert b"".join(store.get(A, empty, info.sha256)) == b""
    small = _uri(A, f"jobs/{J}/renders/small.json")
    info = store.put(A, small, io.BytesIO(b"{}"))
    assert b"".join(store.get(A, small, info.sha256.upper())) == b"{}"


def test_list_prefix_skips_temp_files(store: LocalDiskStorage, tmp_path: Path) -> None:
    store.put(A, _uri(A, f"jobs/{J}/renders/a.json"), io.BytesIO(b"a"))
    store.put(A, _uri(A, f"jobs/{J}/renders/deep/b.json"), io.BytesIO(b"bb"))
    store.put(A, _uri(A, "assets/ast_1/c.png"), io.BytesIO(b"c"))
    orphan = (
        tmp_path / "root" / str(ORG.to_uuid(A.org_id)) / "jobs" / J / "renders" / f"{TEMP_PREFIX}x"
    )
    orphan.write_bytes(b"partial")
    listed = {(i.uri, i.size_bytes) for i in store.list_prefix(A, A.org_id, "jobs")}
    assert listed == {
        (_uri(A, f"jobs/{J}/renders/a.json"), 1),
        (_uri(A, f"jobs/{J}/renders/deep/b.json"), 2),
    }
    with pytest.raises(InputInvalidError):
        store.list_prefix(A, A.org_id, "nope")
    assert store.remove_orphan_temp_files(older_than_s=0, now_s=time.time() + 1) == 1
    assert not orphan.exists()


class _Exploding(io.RawIOBase):
    def __init__(self) -> None:
        self.calls = 0

    def read(self, size: int = -1, /) -> bytes:
        self.calls += 1
        if self.calls > 2:
            raise OSError(errno.EIO, "source broke")
        return b"y" * 100


@pytest.mark.failure_injection
def test_failed_stream_leaves_no_final_and_no_temp_file(
    store: LocalDiskStorage, tmp_path: Path
) -> None:
    uri = _uri(A, f"jobs/{J}/renders/broken.bin")
    with pytest.raises(StorageUnavailableError):
        store.put(A, uri, _Exploding())
    assert not store.head(A, uri).exists
    assert not list((tmp_path / "root").rglob(f"{TEMP_PREFIX}*"))


@pytest.mark.failure_injection
def test_disk_full_maps_to_resource_disk_full(
    store: LocalDiskStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_space(*_a: object, **_k: object) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "fsync", no_space)
    uri = _uri(A, f"jobs/{J}/renders/full.bin")
    with pytest.raises(DiskFullError):
        store.put(A, uri, io.BytesIO(b"z"))
    monkeypatch.undo()
    assert not store.head(A, uri).exists


@pytest.mark.failure_injection
def test_unreadable_root_is_storage_unavailable(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    store = LocalDiskStorage(blocker / "root")
    with pytest.raises(StorageUnavailableError):
        store.put(A, _uri(A), io.BytesIO(b"x"))


_KILL_SCRIPT = textwrap.dedent(
    """
    import sys, time
    from pathlib import Path
    from amw_core.ids import ActorRef, OrgId
    from amw_core.interfaces.storage import BlobUri
    from amw_core.interfaces.tenancy_context import TenantContext
    from amw_core.storage import LocalDiskStorage

    class Slow:
        def __init__(self):
            self.n = 0
        def read(self, size=-1):
            self.n += 1
            if self.n == 2:
                print("writing", flush=True)
            time.sleep(0.05)
            return b"k" * 512

    root, org, uri = sys.argv[1], sys.argv[2], sys.argv[3]
    ctx = TenantContext(OrgId(org), ActorRef("agent_10"))
    LocalDiskStorage(Path(root), chunk_bytes=512).put(ctx, BlobUri(uri), Slow())
    """
)


@pytest.mark.failure_injection
def test_kill_during_put_leaves_no_file_at_the_final_path(tmp_path: Path) -> None:
    """07 section 8.4: a hard kill mid-write never leaves a corrupt file at a final path."""
    root = tmp_path / "root"
    uri = _uri(A, f"jobs/{J}/renders/killed.mp4")
    script = tmp_path / "writer.py"
    script.write_text(_KILL_SCRIPT, encoding="utf-8")
    proc = subprocess.Popen(  # noqa: S603 - fixed interpreter and test-owned script
        [sys.executable, str(script), str(root), A.org_id, uri],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "writing"
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=10)
    store = LocalDiskStorage(root)
    assert not store.head(A, uri).exists
    temps = list(root.rglob(f"{TEMP_PREFIX}*"))
    assert len(temps) == 1  # the orphan temp file is never an output ...
    assert store.list_prefix(A, A.org_id, "jobs") == []
    assert store.remove_orphan_temp_files(0, time.time() + 1) == 1  # ... and is cleaned up
    info = store.put(A, uri, io.BytesIO(DATA))  # the resumed attempt writes the final file once
    assert info.sha256 == SHA


def test_settings_factory(tmp_path: Path) -> None:
    with pytest.raises(ConfigInvalidError):
        storage_from_settings(load_settings(environ={}))
    with pytest.raises(ConfigInvalidError):
        storage_from_settings(load_settings(environ={"AMW_STORAGE__BACKEND": "s3"}))
    cfg = load_settings(environ={"AMW_STORAGE__ROOT": str(tmp_path)})
    assert isinstance(storage_from_settings(cfg), LocalDiskStorage)
    with pytest.raises(InputInvalidError):
        LocalDiskStorage(Path("relative"))


def test_parse_uri() -> None:
    org = ORG.from_uuid(new_uuid7())
    parsed = parse_uri(f"amw-blob://{org}/jobs/{J}/renders/x.json")
    assert (parsed.owner, parsed.area, parsed.path, parsed.is_platform) == (
        org,
        "jobs",
        f"{J}/renders/x.json",
        False,
    )
    assert parse_uri("amw-blob://platform/templates/a").is_platform
