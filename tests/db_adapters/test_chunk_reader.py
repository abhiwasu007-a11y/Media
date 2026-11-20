"""``LibraryChunkReader`` over a synthetic git checkout (no PostgreSQL, no network). The text in
this file is invented filler; no private library text exists in the repository or its tests."""

import subprocess
from pathlib import Path

import pytest

from agent_06_fact_checker.library.reader import CheckoutLibraryReader, LibraryLimits, LibraryRef
from agent_16_compliance_qa.nearcopy import PrivateChunkReader
from amw_core.errors import (
    CrossTenantRefError,
    InputInvalidError,
    MissingDependencyError,
)
from amw_core.ids import ORG, ActorRef, new_uuid7
from amw_core.interfaces.tenancy_context import TenantContext, TenantTransaction
from amw_core.testing.memory import MemoryTransaction
from amw_orchestrator.db_adapters import ChunkLocation, LibraryChunkReader

pytestmark = pytest.mark.unit
BODY = (
    "preface line\n§ 1.1\nalpha beta gamma\ndelta\n§ 1.2\nepsilon zeta\n§ 1.2\nrepeated\n§ 2\ntail"
)
ORG_A = ORG.from_uuid(new_uuid7())
ORG_B = ORG.from_uuid(new_uuid7())


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603 - fixed argv in a temp directory
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


@pytest.fixture
def library(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "lib"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "work.txt").write_text(BODY, encoding="utf-8")
    _git(root, "add", "work.txt")
    _git(root, "commit", "-q", "-m", "synthetic")
    return root, _git(root, "rev-parse", "HEAD")


class Index:
    def __init__(self, **locations: ChunkLocation) -> None:
        self.locations = locations

    def locate(self, tx: TenantTransaction, chunk_id: str) -> ChunkLocation | None:
        return self.locations.get(chunk_id)


def _tx(org: str) -> MemoryTransaction:
    return MemoryTransaction(TenantContext(org, ActorRef("agent_16")))  # type: ignore[arg-type]


def _reader(library: tuple[Path, str], **locations: ChunkLocation) -> LibraryChunkReader:
    root, sha = library
    lib = CheckoutLibraryReader(
        LibraryRef(root, sha),
        LibraryLimits(max_file_bytes=10_000, allowed_suffixes=frozenset({".txt"})),
    )
    return LibraryChunkReader(lib, Index(**locations))


def loc(org: str = ORG_A, path: str = "work.txt", locator: str | None = None) -> ChunkLocation:
    return ChunkLocation(org, "kcl_x", path, locator)


def test_port_is_satisfied(library: tuple[Path, str]) -> None:
    reader: PrivateChunkReader = _reader(library)
    assert reader is not None


def test_reads_a_section_and_a_whole_file(library: tuple[Path, str]) -> None:
    r = _reader(library, sec=loc(locator="1.1"), whole=loc(), last=loc(locator="2"))
    got = r.read(_tx(ORG_A), "sec")
    assert (got.chunk_id, got.org_id, got.collection_id) == ("sec", ORG_A, "kcl_x")
    assert got.text == "alpha beta gamma\ndelta"
    assert r.read(_tx(ORG_A), "whole").text == BODY
    assert r.read(_tx(ORG_A), "last").text == "tail"


def test_unresolvable_chunks_fail_closed(library: tuple[Path, str]) -> None:
    r = _reader(
        library, repeated=loc(locator="1.2"), absent=loc(locator="9"), nofile=loc(path="no.txt"),
        bad_path=loc(path="../x.txt"), bad_suffix=loc(path="work.md"),
    )  # fmt: skip
    tx = _tx(ORG_A)
    with pytest.raises(MissingDependencyError):
        r.read(tx, "unknown")  # the index has no location
    with pytest.raises(MissingDependencyError):
        r.read(tx, "repeated")  # a repeated locator never resolves
    with pytest.raises(MissingDependencyError):
        r.read(tx, "absent")
    with pytest.raises(MissingDependencyError):
        r.read(tx, "nofile")
    with pytest.raises(InputInvalidError):
        r.read(tx, "bad_path")
    with pytest.raises(InputInvalidError):
        r.read(tx, "bad_suffix")
    with pytest.raises(InputInvalidError):
        r.read(tx, "")


def test_another_tenants_chunk_is_refused(library: tuple[Path, str]) -> None:
    r = _reader(library, theirs=loc(org=ORG_B))
    with pytest.raises(CrossTenantRefError):
        r.read(_tx(ORG_A), "theirs")
    assert r.read(_tx(ORG_B), "theirs").org_id == ORG_B


def test_a_checkout_that_moved_or_changed_never_reads(library: tuple[Path, str]) -> None:
    root, sha = library
    r = _reader(library, sec=loc(locator="1.1"))
    assert r.read(_tx(ORG_A), "sec").text
    (root / "work.txt").write_text(BODY + "\nedited", encoding="utf-8")  # differs from the commit
    with pytest.raises(InputInvalidError):
        r.read(_tx(ORG_A), "sec")
    _git(root, "checkout", "-q", "--", "work.txt")
    (root / "work.txt").write_text("other\n", encoding="utf-8")
    _git(root, "add", "work.txt")
    _git(root, "commit", "-q", "-m", "second")  # HEAD is no longer the commit the job names
    with pytest.raises(InputInvalidError):
        r.read(_tx(ORG_A), "sec")
    with pytest.raises(InputInvalidError):
        LibraryRef(root, "abc")  # a short SHA is refused up front
    assert sha != _git(root, "rev-parse", "HEAD")
