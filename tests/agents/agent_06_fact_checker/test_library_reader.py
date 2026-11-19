"""KNOWLEDGE-LIB: the read-only reader; commit pin, path safety, and proof it never writes."""

import builtins
import hashlib
import inspect
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from agent_06_fact_checker.library import reader as reader_module
from agent_06_fact_checker.library.reader import (
    CheckoutLibraryReader,
    KnowledgeLibraryReader,
    LibraryLimits,
    LibraryRef,
    head_commit,
)
from amw_core.errors import InputInvalidError, MissingDependencyError
from tests.agents.agent_06_fact_checker.library_support import (
    FILES,
    LIMITS,
    git,
    head_sha,
    make_library,
    make_reader,
)

pytestmark = pytest.mark.unit


def test_reads_text_at_the_pinned_commit(tmp_path: Path) -> None:
    reader = make_reader(tmp_path)
    assert isinstance(reader, KnowledgeLibraryReader)
    assert reader.read_text("phil/plain.txt") == FILES["phil/plain.txt"]
    assert reader.commit_sha == head_sha(tmp_path / "lib")


def test_abbreviated_sha_is_refused(tmp_path: Path) -> None:
    repo = make_library(tmp_path)
    for short in (head_sha(repo)[:7], head_sha(repo)[:39]):
        with pytest.raises(InputInvalidError):
            LibraryRef(repo, short)


@pytest.mark.parametrize("sha", ["", "abc", "A" * 40, "g" * 40, "0" * 41, "0" * 39])
def test_malformed_sha_is_refused(tmp_path: Path, sha: str) -> None:
    with pytest.raises(InputInvalidError):
        LibraryRef(make_library(tmp_path), sha)


def test_head_mismatch_fails_closed(tmp_path: Path) -> None:
    repo = make_library(tmp_path)
    with pytest.raises(InputInvalidError):
        CheckoutLibraryReader(LibraryRef(repo, "f" * 40), LIMITS)


def test_head_moving_after_construction_is_caught(tmp_path: Path) -> None:
    repo = make_library(tmp_path)
    reader = CheckoutLibraryReader(LibraryRef(repo, head_sha(repo)), LIMITS)
    (repo / ".git" / "refs" / "heads" / "main").write_text("e" * 40 + "\n", encoding="utf-8")
    with pytest.raises(InputInvalidError):
        reader.read_text("phil/plain.txt")


def test_missing_checkout_and_non_git_directory(tmp_path: Path) -> None:
    with pytest.raises(MissingDependencyError):
        CheckoutLibraryReader(LibraryRef(tmp_path / "nope", "a" * 40), LIMITS)
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(MissingDependencyError):
        CheckoutLibraryReader(LibraryRef(plain, "a" * 40), LIMITS)


def test_detached_head_and_packed_refs(tmp_path: Path) -> None:
    repo = make_library(tmp_path)
    sha = head_sha(repo)
    git_dir = repo / ".git"
    (git_dir / "HEAD").write_text(sha + "\n", encoding="utf-8")
    assert head_commit(repo) == sha
    (git_dir / "HEAD").write_text("ref: refs/heads/packed\n", encoding="utf-8")
    (git_dir / "packed-refs").write_text(
        f"# pack-refs\n{'1' * 40} refs/heads/other\n{sha} refs/heads/packed\n", encoding="utf-8"
    )
    assert head_commit(repo) == sha
    (git_dir / "HEAD").write_text("ref: refs/heads/absent\n", encoding="utf-8")
    with pytest.raises(MissingDependencyError):
        head_commit(repo)
    (git_dir / "HEAD").write_text("garbage\n", encoding="utf-8")
    with pytest.raises(MissingDependencyError):
        head_commit(repo)


def test_linked_worktree_layout(tmp_path: Path) -> None:
    main = make_library(tmp_path / "main")
    link = tmp_path / "linked"
    link.mkdir()
    wt_git = main / ".git" / "worktrees" / "linked"
    wt_git.mkdir(parents=True)
    (wt_git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (wt_git / "commondir").write_text("../..\n", encoding="utf-8")
    (link / ".git").write_text(f"gitdir: {wt_git}\n", encoding="utf-8")
    (link / "t.txt").write_text("x", encoding="utf-8")
    assert head_commit(link) == head_sha(main)
    (link / ".git").write_text("nonsense\n", encoding="utf-8")
    with pytest.raises(MissingDependencyError):
        head_commit(link)


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/etc/passwd",
        "../outside.txt",
        "phil/../../outside.txt",
        "phil//plain.txt",
        ".git/HEAD",
        "phil\\plain.txt",
        "phil/plain.txt\x00.pdf",
        "phil/book.pdf",
        "phil",
    ],
)
def test_unsafe_paths_are_refused(tmp_path: Path, path: str) -> None:
    reader = make_reader(tmp_path)
    with pytest.raises((InputInvalidError, MissingDependencyError)):
        reader.read_text(path)


def test_symlink_leaving_the_checkout_is_refused(tmp_path: Path) -> None:
    repo = make_library(tmp_path)
    outside = tmp_path / "secret.txt"
    outside.write_text("outside", encoding="utf-8")
    (repo / "phil" / "link.txt").symlink_to(outside)
    (repo / "phil" / "gitlink.txt").symlink_to(repo / ".git" / "HEAD")
    reader = CheckoutLibraryReader(LibraryRef(repo, head_sha(repo)), LIMITS)
    for name in ("phil/link.txt", "phil/gitlink.txt"):
        with pytest.raises(InputInvalidError):
            reader.read_text(name)


def test_missing_file_oversize_and_bad_encoding(tmp_path: Path) -> None:
    repo = make_library(tmp_path)
    (repo / "phil" / "big.txt").write_text("x" * 50, encoding="utf-8")
    (repo / "phil" / "bin.txt").write_bytes(b"\xff\xfe\x00bad")
    small = LibraryLimits(max_file_bytes=40, allowed_suffixes=frozenset({".txt"}))
    reader = CheckoutLibraryReader(LibraryRef(repo, head_sha(repo)), small)
    with pytest.raises(MissingDependencyError):
        reader.read_text("phil/none.txt")
    with pytest.raises(InputInvalidError):
        reader.read_text("phil/big.txt")
    with pytest.raises(InputInvalidError):
        reader.read_text("phil/bin.txt")


def test_limits_need_values() -> None:
    with pytest.raises(InputInvalidError):
        LibraryLimits(max_file_bytes=0, allowed_suffixes=frozenset({".txt"}))
    with pytest.raises(InputInvalidError):
        LibraryLimits(max_file_bytes=10, allowed_suffixes=frozenset())


def _snapshot(root: Path) -> dict[str, tuple[str, int, int]]:
    rows: dict[str, tuple[str, int, int]] = {}
    for path in sorted(root.rglob("*")):
        rel = str(path.relative_to(root))
        if path.is_dir():
            rows[rel] = ("dir", 0, path.stat().st_mtime_ns)
        else:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            stat = path.stat()
            rows[rel] = (digest, stat.st_size, stat.st_mtime_ns)
    return rows


def test_nothing_in_the_library_is_written_or_copied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every byte, size, mtime and entry of the library is unchanged after reads, no file is
    opened in a mode other than ``rb``, and no new file appears next to it."""
    repo = make_library(tmp_path)
    reader = CheckoutLibraryReader(LibraryRef(repo, head_sha(repo)), LIMITS)
    before = _snapshot(repo)
    outside_before = sorted(p.name for p in tmp_path.iterdir())
    modes: list[str] = []
    real_open = builtins.open

    def spy(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if str(file).startswith(str(repo.resolve())):
            modes.append(mode)
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    for name in ("phil/original.txt", "phil/translation.txt", "phil/plain.txt"):
        reader.read_text(name)
    for bad in ("../x.txt", ".git/HEAD", "phil/book.pdf"):
        with pytest.raises(InputInvalidError):
            reader.read_text(bad)
    monkeypatch.undo()
    assert modes == ["rb", "rb", "rb"]
    assert _snapshot(repo) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == outside_before


def test_read_only_checkout_still_reads(tmp_path: Path) -> None:
    repo = make_library(tmp_path)
    reader = CheckoutLibraryReader(LibraryRef(repo, head_sha(repo)), LIMITS)
    for root, dirs, files in os.walk(repo):
        for name in files:
            (Path(root) / name).chmod(0o444)
        for name in dirs:
            (Path(root) / name).chmod(0o555)
    try:
        assert reader.read_text("phil/plain.txt")
    finally:
        for root, dirs, _ in os.walk(repo):
            for name in dirs:
                (Path(root) / name).chmod(0o755)


def test_reader_surface_has_no_write_or_copy_methods() -> None:
    public = {n for n, _ in inspect.getmembers(CheckoutLibraryReader) if not n.startswith("_")}
    assert public == {"commit_sha", "read_text"}
    source = inspect.getsource(reader_module)
    for forbidden in (
        "shutil",
        "write_text",
        "write_bytes",
        "os.remove",
        "unlink",
        "rename",
        "mkdir",
    ):
        assert forbidden not in source
    assert source.count('open(target, "rb")') == 1
    # the only process the reader starts is the read-only ``git ls-tree``
    assert source.count("subprocess.run(") == 1
    assert source.count('"ls-tree"') == 1
    for verb in ('"add"', '"commit"', '"checkout"', '"reset"', '"clean"', '"update-index"'):
        assert verb not in source


def _reader(repo: Path) -> CheckoutLibraryReader:
    return CheckoutLibraryReader(LibraryRef(repo, head_sha(repo)), LIMITS)


def test_modified_tracked_file_is_refused(tmp_path: Path) -> None:
    """HEAD still matches but the bytes differ from the commit: no fake quote may verify."""
    repo = make_library(tmp_path)
    reader = _reader(repo)
    assert reader.read_text("phil/original.txt")
    (repo / "phil" / "original.txt").write_text(
        FILES["phil/original.txt"] + "A line added by an edit.\n", encoding="utf-8"
    )
    assert head_commit(repo) == reader.commit_sha
    with pytest.raises(InputInvalidError, match="differs from the pinned commit"):
        reader.read_text("phil/original.txt")
    assert reader.read_text("phil/translation.txt") == FILES["phil/translation.txt"]


def test_one_byte_change_and_restored_file(tmp_path: Path) -> None:
    repo = make_library(tmp_path)
    reader = _reader(repo)
    path = repo / "phil" / "plain.txt"
    path.write_bytes(path.read_bytes().replace(b"plain", b"plaim", 1))
    with pytest.raises(InputInvalidError):
        reader.read_text("phil/plain.txt")
    path.write_text(FILES["phil/plain.txt"], encoding="utf-8")
    assert reader.read_text("phil/plain.txt") == FILES["phil/plain.txt"]


def test_staged_change_is_refused(tmp_path: Path) -> None:
    repo = make_library(tmp_path)
    reader = _reader(repo)
    (repo / "phil" / "original.txt").write_text("§ I.1\nA staged edit.\n", encoding="utf-8")
    git(repo, "add", "phil/original.txt")
    assert git(repo, "status", "--porcelain").startswith("M ")
    with pytest.raises(InputInvalidError, match="differs from the pinned commit"):
        reader.read_text("phil/original.txt")


def test_untracked_file_is_refused(tmp_path: Path) -> None:
    repo = make_library(tmp_path)
    reader = _reader(repo)
    (repo / "phil" / "extra.txt").write_text("§ 1\nNot in any commit.\n", encoding="utf-8")
    with pytest.raises(InputInvalidError, match="not part of the pinned commit"):
        reader.read_text("phil/extra.txt")


def test_file_replaced_by_another_tracked_files_content_is_refused(tmp_path: Path) -> None:
    repo = make_library(tmp_path)
    reader = _reader(repo)
    (repo / "phil" / "original.txt").write_text(FILES["phil/translation.txt"], encoding="utf-8")
    with pytest.raises(InputInvalidError):
        reader.read_text("phil/original.txt")


def test_symlink_swap_of_a_tracked_file_is_refused(tmp_path: Path) -> None:
    repo = make_library(tmp_path)
    reader = _reader(repo)
    target = repo / "phil" / "original.txt"
    target.unlink()
    target.symlink_to(repo / "phil" / "translation.txt")  # stays inside the checkout
    with pytest.raises(InputInvalidError, match="symbolic link"):
        reader.read_text("phil/original.txt")


def test_symlink_committed_in_the_pinned_commit_is_refused(tmp_path: Path) -> None:
    repo = make_library(tmp_path)
    (repo / "phil" / "alias.txt").symlink_to("translation.txt")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "add a symlink")
    with pytest.raises(InputInvalidError):
        _reader(repo).read_text("phil/alias.txt")


def test_symlinked_directory_component_with_other_content_is_refused(tmp_path: Path) -> None:
    repo = make_library(tmp_path)
    reader = _reader(repo)
    other = repo / "other"
    other.mkdir()
    (other / "plain.txt").write_text("§ 1\nA different text.\n", encoding="utf-8")
    (repo / "phil").rename(repo / "phil_real")
    (repo / "phil").symlink_to(repo / "other")
    with pytest.raises(InputInvalidError):
        reader.read_text("phil/plain.txt")


def test_deleted_file_is_refused(tmp_path: Path) -> None:
    repo = make_library(tmp_path)
    reader = _reader(repo)
    (repo / "phil" / "plain.txt").unlink()
    with pytest.raises(MissingDependencyError):
        reader.read_text("phil/plain.txt")


def test_git_missing_or_failing_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_library(tmp_path)
    reader = _reader(repo)

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(MissingDependencyError):
        reader.read_text("phil/plain.txt")


def test_commit_without_the_object_fails_closed(tmp_path: Path) -> None:
    repo = make_library(tmp_path)
    fake = "e" * 40
    (repo / ".git" / "refs" / "heads" / "main").write_text(fake + "\n", encoding="utf-8")
    reader = CheckoutLibraryReader(LibraryRef(repo, fake), LIMITS)
    with pytest.raises(MissingDependencyError):
        reader.read_text("phil/plain.txt")


def test_reading_leaves_the_git_index_alone(tmp_path: Path) -> None:
    repo = make_library(tmp_path)
    before = (repo / ".git" / "index").stat().st_mtime_ns
    _reader(repo).read_text("phil/plain.txt")
    assert (repo / ".git" / "index").stat().st_mtime_ns == before
