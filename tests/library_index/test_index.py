"""Library chunk index: builder, loader, reader integration, CLI (synthetic library only)."""

import hashlib
import json
from pathlib import Path

import pytest

from agent_06_fact_checker.library.reader import CheckoutLibraryReader, LibraryLimits, LibraryRef
from amw_core.errors import (
    ConfigInvalidError,
    CorruptedOutputError,
    CrossTenantRefError,
    InputInvalidError,
    MissingDependencyError,
)
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.testing.memory import MemoryTransaction
from amw_orchestrator.db_adapters import LibraryChunkReader
from amw_orchestrator.db_adapters.chunk_reader import section_text, slice_text
from amw_orchestrator.library_index import BuildReport, PrivateChunkIndex, build_index, chunk_id_for
from amw_orchestrator.library_index import cli as index_cli
from amw_orchestrator.library_index.chunking import chunk_sections, git_blob_id
from amw_orchestrator.library_index.models import MANIFEST_SCHEMA
from amw_orchestrator.library_index.store import manifest_path, shard_path
from tests.library_index.support import (
    COLLECTION,
    CRLF,
    ORG_A,
    ORG_B,
    WORK_ONE,
    WORK_TWO,
    git,
    make_library,
    tree_snapshot,
)

pytestmark = pytest.mark.unit
Lib = tuple[Path, str, Path]
LIMITS = LibraryLimits(max_file_bytes=100_000, allowed_suffixes=frozenset({".txt"}))


@pytest.fixture
def lib(tmp_path: Path) -> tuple[Path, str, Path]:
    root = tmp_path / "lib"
    return root, make_library(root), tmp_path / "private_index"


def _build(lib: Lib, org: str = ORG_A) -> BuildReport:
    root, sha, idx = lib
    return build_index(
        library_root=root, commit_sha=sha, org_id=org, collection_id=COLLECTION,
        index_dir=idx, limits=LIMITS,
    )  # fmt: skip


def _load(lib: Lib, org: str = ORG_A) -> PrivateChunkIndex:
    return PrivateChunkIndex.load(lib[2], org_id=org, collection_id=COLLECTION, commit_sha=lib[1])


def _tx(org: str) -> MemoryTransaction:
    return MemoryTransaction(TenantContext(org, "agent_16", None))  # type: ignore[arg-type]


def test_marker_regex_equals_the_reader_marker() -> None:
    from amw_orchestrator.db_adapters import chunk_reader
    from amw_orchestrator.library_index import chunking

    assert chunking._MARKER.pattern == chunk_reader._MARKER.pattern


def test_chunking_matches_section_text_for_every_unambiguous_section() -> None:
    for raw in (WORK_ONE, WORK_TWO, CRLF, "§ x\n\n§ y\nbody"):
        found = chunk_sections(raw)
        for entry in found.entries:
            text = slice_text(raw, entry.start, entry.end)
            assert text == section_text(raw, entry.locator)
            assert hashlib.sha256(text.encode()).hexdigest() == entry.text_sha256


def test_repeated_locator_is_not_indexed_and_counted() -> None:
    found = chunk_sections(WORK_TWO)
    assert [e.locator for e in found.entries] == ["B"]
    assert found.ambiguous == 1


def test_build_reports_counts_only_and_load_serves_chunks(lib: Lib) -> None:
    report = _build(lib)
    # one.txt (3 sections), two.txt (B only), crlf.txt (2); plain.txt has none; image.bin skipped
    assert (report.files_seen, report.files_indexed, report.files_without_sections) == (4, 3, 1)
    assert (report.chunks, report.ambiguous_locators) == (6, 1)
    index = _load(lib)
    assert len(index) == 6
    reader = LibraryChunkReader(CheckoutLibraryReader(LibraryRef(lib[0], lib[1]), LIMITS), index)
    cid = chunk_id_for(ORG_A, COLLECTION, "works/one.txt", "1.1")
    chunk = reader.read(_tx(ORG_A), cid)
    assert chunk.text == "alpha beta gamma\ndelta epsilon"
    assert (chunk.org_id, chunk.collection_id) == (ORG_A, COLLECTION)
    crlf = reader.read(_tx(ORG_A), chunk_id_for(ORG_A, COLLECTION, "works/crlf.txt", "9"))
    assert crlf.text == "windows line one\nwindows line two"


def test_index_holds_no_book_text(lib: Lib) -> None:
    _build(lib)
    blob = b"".join(p.read_bytes() for p in lib[2].rglob("*") if p.is_file()).decode()
    for word in ("alpha", "epsilon", "tail of", "windows", "second body", "preface"):
        assert word not in blob


def test_chunk_ids_are_deterministic_and_wire_valid(lib: Lib) -> None:
    from amw_core.ids import Prefix, prefix_of

    a = chunk_id_for(ORG_A, COLLECTION, "works/one.txt", "1.1")
    assert a == chunk_id_for(ORG_A, COLLECTION, "works/one.txt", "1.1")
    assert a != chunk_id_for(ORG_B, COLLECTION, "works/one.txt", "1.1")
    assert a != chunk_id_for(ORG_A, COLLECTION, "works/one.txt", "1.2")
    assert prefix_of(a) is Prefix.KNOWLEDGE_CHUNK
    _build(lib)
    first = sorted(_load(lib)._places)
    _build(lib)  # a rebuild keeps every id
    assert sorted(_load(lib)._places) == first


def test_unknown_chunk_is_none_and_reader_refuses(lib: Lib) -> None:
    _build(lib)
    index = _load(lib)
    reader = LibraryChunkReader(CheckoutLibraryReader(LibraryRef(lib[0], lib[1]), LIMITS), index)
    with pytest.raises(MissingDependencyError):
        reader.read(_tx(ORG_A), chunk_id_for(ORG_A, COLLECTION, "works/one.txt", "9.9"))


def test_other_tenant_cannot_read_a_chunk(lib: Lib) -> None:
    _build(lib)
    reader = LibraryChunkReader(
        CheckoutLibraryReader(LibraryRef(lib[0], lib[1]), LIMITS), _load(lib)
    )
    with pytest.raises(CrossTenantRefError):
        reader.read(_tx(ORG_B), chunk_id_for(ORG_A, COLLECTION, "works/one.txt", "1.1"))


def test_loader_refuses_other_tenant_collection_or_commit(lib: Lib) -> None:
    _build(lib)
    with pytest.raises(MissingDependencyError):  # no manifest for another tenant
        _load(lib, ORG_B)
    with pytest.raises(MissingDependencyError):
        PrivateChunkIndex.load(lib[2], org_id=ORG_A, collection_id="other", commit_sha=lib[1])
    with pytest.raises(MissingDependencyError):
        PrivateChunkIndex.load(lib[2], org_id=ORG_A, collection_id=COLLECTION, commit_sha="b" * 40)


def test_manifest_of_another_commit_in_the_pinned_place_is_refused(lib: Lib) -> None:
    _build(lib)
    other = "c" * 40
    src = manifest_path(lib[2], ORG_A, COLLECTION, lib[1])
    dst = manifest_path(lib[2], ORG_A, COLLECTION, other)
    dst.parent.mkdir(parents=True)
    dst.write_bytes(src.read_bytes())  # a copied manifest still names the old commit
    with pytest.raises(InputInvalidError):
        PrivateChunkIndex.load(lib[2], org_id=ORG_A, collection_id=COLLECTION, commit_sha=other)


def test_missing_damaged_and_swapped_shards_fail_closed(lib: Lib) -> None:
    _build(lib)
    manifest = json.loads(manifest_path(lib[2], ORG_A, COLLECTION, lib[1]).read_text())
    first = manifest["files"][0]["blob_id"]
    second = manifest["files"][1]["blob_id"]
    path = shard_path(lib[2], ORG_A, COLLECTION, first)
    good = path.read_bytes()
    path.write_bytes(good[:-3])  # truncated
    with pytest.raises(ConfigInvalidError):
        _load(lib)
    path.write_bytes(shard_path(lib[2], ORG_A, COLLECTION, second).read_bytes())  # swapped
    with pytest.raises(ConfigInvalidError):
        _load(lib)
    path.unlink()  # missing
    with pytest.raises(MissingDependencyError):
        _load(lib)


def test_damaged_manifest_and_wrong_chunker_fail_closed(lib: Lib) -> None:
    _build(lib)
    path = manifest_path(lib[2], ORG_A, COLLECTION, lib[1])
    doc = json.loads(path.read_text())
    path.write_text("{not json")
    with pytest.raises(ConfigInvalidError):
        _load(lib)
    doc["chunker"] = "other/9"
    assert doc["schema"] == MANIFEST_SCHEMA
    path.write_text(json.dumps(doc))
    with pytest.raises(InputInvalidError):
        _load(lib)


def test_tampered_chunk_hash_fails_at_use_time(lib: Lib) -> None:
    _build(lib)
    manifest = json.loads(manifest_path(lib[2], ORG_A, COLLECTION, lib[1]).read_text())
    entry = next(f for f in manifest["files"] if f["path"] == "works/one.txt")
    path = shard_path(lib[2], ORG_A, COLLECTION, entry["blob_id"])
    shard = json.loads(path.read_text())
    shard["entries"][0]["text_sha256"] = "0" * 64
    data = json.dumps(shard, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(data)
    entry["shard_sha256"] = hashlib.sha256(data).hexdigest()  # a consistent but wrong index
    manifest_path(lib[2], ORG_A, COLLECTION, lib[1]).write_text(json.dumps(manifest))
    index = _load(lib)  # structurally fine
    reader = LibraryChunkReader(CheckoutLibraryReader(LibraryRef(lib[0], lib[1]), LIMITS), index)
    with pytest.raises(CorruptedOutputError):
        reader.read(_tx(ORG_A), chunk_id_for(ORG_A, COLLECTION, "works/one.txt", "1.1"))
    with pytest.raises(CorruptedOutputError):
        index.verify_against_library(CheckoutLibraryReader(LibraryRef(lib[0], lib[1]), LIMITS))


def test_verify_counts_every_chunk_and_refuses_another_commit(lib: Lib) -> None:
    _build(lib)
    root, sha, _ = lib
    index = _load(lib)
    assert index.verify_against_library(CheckoutLibraryReader(LibraryRef(root, sha), LIMITS)) == 6
    (root / "works" / "new.txt").write_text("§ n\nnew\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "two")
    new_sha = git(root, "rev-parse", "HEAD")
    with pytest.raises(InputInvalidError):  # the library moved: the index is of the old commit
        index.verify_against_library(CheckoutLibraryReader(LibraryRef(root, new_sha), LIMITS))
    with pytest.raises(InputInvalidError):
        CheckoutLibraryReader(LibraryRef(root, sha), LIMITS)  # HEAD is no longer the pinned SHA


def test_index_of_an_old_commit_is_not_served_for_the_new_commit(lib: Lib) -> None:
    _build(lib)
    root, _, idx = lib
    (root / "works" / "one.txt").write_text("§ 1.1\nchanged synthetic body\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "changed")
    new_sha = git(root, "rev-parse", "HEAD")
    with pytest.raises(MissingDependencyError):  # no index was built for the new commit
        PrivateChunkIndex.load(idx, org_id=ORG_A, collection_id=COLLECTION, commit_sha=new_sha)


def test_blob_id_of_text_equals_git(lib: Lib) -> None:
    root, sha, _ = lib
    assert git_blob_id(WORK_ONE) == git(root, "rev-parse", f"{sha}:works/one.txt")
    assert git_blob_id(CRLF) == git(root, "rev-parse", f"{sha}:works/crlf.txt")


def test_builder_refuses_an_index_dir_inside_the_library_or_any_git_tree(
    lib: Lib,
    tmp_path: Path,
) -> None:
    root, sha, _ = lib

    def build(into: Path) -> None:
        build_index(
            library_root=root, commit_sha=sha, org_id=ORG_A, collection_id=COLLECTION,
            index_dir=into, limits=LIMITS,
        )  # fmt: skip

    with pytest.raises(ConfigInvalidError):
        build(root / "idx")
    other = tmp_path / "another_repo"
    make_library(other, {"a.txt": "§ 1\nx\n"})
    with pytest.raises(ConfigInvalidError):
        build(other / "idx")
    assert not (root / "idx").exists()
    assert not (other / "idx").exists()


def test_build_writes_nothing_inside_the_library_or_the_repository(lib: Lib) -> None:
    root, _, idx = lib
    repo = Path(__file__).resolve().parents[2]
    before_lib = tree_snapshot(root)
    before_status = git(repo, "status", "--porcelain")
    before_head = git(root, "status", "--porcelain")
    _build(lib)
    _load(lib).verify_against_library(CheckoutLibraryReader(LibraryRef(root, lib[1]), LIMITS))
    assert tree_snapshot(root) == before_lib  # not a byte changed, nothing added (also in .git)
    assert git(root, "status", "--porcelain") == before_head == ""
    assert git(repo, "status", "--porcelain") == before_status
    assert idx.is_dir()
    assert not idx.resolve().is_relative_to(root.resolve())
    assert not idx.resolve().is_relative_to(repo)


def test_unsafe_tenant_or_collection_ids_are_refused(lib: Lib) -> None:
    root, sha, idx = lib
    for org, col in (("../x", COLLECTION), (ORG_A, "a/b"), (ORG_A, "")):
        with pytest.raises(InputInvalidError):
            build_index(
                library_root=root, commit_sha=sha, org_id=org, collection_id=col,
                index_dir=idx, limits=LIMITS,
            )  # fmt: skip


def test_cli_prints_counts_only_and_verifies(
    lib: Lib,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, sha, idx = lib
    config = tmp_path / "cfg.json"
    config.write_text(
        json.dumps({"index_dir": str(idx), "max_file_bytes": 100000, "allowed_suffixes": [".txt"]})
    )
    common = [
        "--config", str(config), "--library", str(root), "--commit", sha,
        "--org-id", ORG_A, "--collection-id", COLLECTION,
    ]  # fmt: skip
    assert index_cli.main(["build", *common]) == 0
    out = capsys.readouterr().out
    assert json.loads(out) == {
        "ambiguous_locators": 1, "chunks": 6, "files_indexed": 3,
        "files_seen": 4, "files_without_sections": 1,
    }  # fmt: skip
    for secret in ("works/", "1.1", "alpha", sha):
        assert secret not in out
    assert index_cli.main(["verify", *common]) == 0
    assert json.loads(capsys.readouterr().out) == {"chunks_checked": 6}


def test_cli_refuses_with_a_code_and_no_detail(
    lib: Lib,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, sha, _ = lib
    config = tmp_path / "cfg.json"
    config.write_text(
        json.dumps(
            {"index_dir": str(root / "inside"), "max_file_bytes": 10, "allowed_suffixes": [".txt"]}
        )
    )
    args = ["--config", str(config), "--library", str(root), "--commit", sha,
            "--org-id", ORG_A, "--collection-id", COLLECTION]  # fmt: skip
    assert index_cli.main(["build", *args]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "refused" in captured.err
    assert str(root) not in captured.err
    config.write_text("{}")
    assert index_cli.main(["build", *args]) == 2
