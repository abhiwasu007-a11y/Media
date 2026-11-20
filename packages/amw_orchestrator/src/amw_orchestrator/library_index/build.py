"""Index builder: library checkout at a pinned commit -> private index directory.

An operator tool for the development environment (never part of a run): it enumerates the pinned
commit's regular text files with a read-only ``git ls-tree``, reads each through the read-only
library reader (HEAD, size and blob checks), cuts the sections and writes offsets, locators and
hashes only. The result reports COUNTS, never text, names or locators."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agent_06_fact_checker.library.reader import (
    CheckoutLibraryReader,
    LibraryLimits,
    LibraryRef,
)
from amw_core.errors import MissingDependencyError
from amw_orchestrator.library_index.chunking import chunk_sections, git_blob_id
from amw_orchestrator.library_index.models import (
    CHUNKER_VERSION,
    FileShard,
    Manifest,
    ManifestFile,
)
from amw_orchestrator.library_index.store import check_private_dir, write_manifest, write_shard

_GIT_ENV: Final = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
    "LC_ALL": "C",
}
_REGULAR: Final = frozenset({"100644", "100755"})


@dataclass(frozen=True, slots=True)
class BuildReport:
    """Counts only (printed by the command line tool)."""

    files_seen: int
    files_indexed: int
    files_without_sections: int
    chunks: int
    ambiguous_locators: int


def list_text_files(root: Path, commit_sha: str, limits: LibraryLimits) -> list[str]:
    """Regular files of the pinned commit with an allowed suffix, sorted (read-only git call)."""
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, validated sha
            [*("git", "-C", str(root), "ls-tree", "-r", "-z", commit_sha)],
            capture_output=True,
            check=False,
            timeout=limits.git_timeout_seconds,
            env=_GIT_ENV,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise MissingDependencyError("library commit could not be listed") from exc
    if done.returncode != 0:
        raise MissingDependencyError("library commit could not be listed")
    out: list[str] = []
    for entry in done.stdout.split(b"\0"):
        meta, _, name = entry.partition(b"\t")
        fields = meta.split(b" ")
        if len(fields) != 3 or fields[1] != b"blob" or fields[0].decode() not in _REGULAR:
            continue
        path = name.decode("utf-8", "replace")
        if ".git" in path.split("/") or Path(path).suffix.lower() not in limits.allowed_suffixes:
            continue
        out.append(path)
    return sorted(out)


def build_index(
    *,
    library_root: Path,
    commit_sha: str,
    org_id: str,
    collection_id: str,
    index_dir: Path,
    limits: LibraryLimits,
) -> BuildReport:
    """Write the manifest and shards of one (org, collection, commit); counts only."""
    private = check_private_dir(index_dir, library_root)
    library = CheckoutLibraryReader(LibraryRef(library_root, commit_sha), limits)
    files: list[ManifestFile] = []
    seen = without = chunks = ambiguous = 0
    for path in list_text_files(library_root, commit_sha, limits):
        seen += 1
        raw = library.read_text(path)
        found = chunk_sections(raw)
        if not found.entries:
            without += 1
            ambiguous += found.ambiguous
            continue
        shard = FileShard(blob_id=git_blob_id(raw), chunker=CHUNKER_VERSION, entries=found.entries)
        digest = write_shard(private, org_id, collection_id, shard)
        files.append(ManifestFile(path=path, blob_id=shard.blob_id, shard_sha256=digest))
        chunks += len(found.entries)
        ambiguous += found.ambiguous
    write_manifest(
        private,
        Manifest(
            org_id=org_id,
            collection_id=collection_id,
            commit_sha=commit_sha,
            chunker=CHUNKER_VERSION,
            files=tuple(files),
        ),
    )
    return BuildReport(seen, len(files), without, chunks, ambiguous)
