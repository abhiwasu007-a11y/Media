"""Read-only reader of the private knowledge-library checkout (KNOWLEDGE-LIB, D12).

A job input carries only the library path and a commit SHA, never text. The reader refuses to
read unless the checkout's HEAD equals that SHA (fail closed), opens files only in binary read
mode, accepts only relative paths of allowed text suffixes inside the checkout (never ``.git``,
never a symlink that leaves it), and offers no write, copy or listing method. The text it returns
is held by the caller in memory only; it must never reach a log, fixture, blob or PR.

Not verified: that the working tree is clean (HEAD identifies the commit, not the file bytes).
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from amw_core.errors import InputInvalidError, MissingDependencyError

_SHA = re.compile(r"^[0-9a-f]{7,40}$")
_FULL = re.compile(r"^[0-9a-f]{40}$")
_REF_PREFIX = "ref: "


@dataclass(frozen=True, slots=True)
class LibraryRef:
    """What a job carries: where the library checkout is and which commit it must be at."""

    repo_path: Path
    commit_sha: str

    def __post_init__(self) -> None:
        if not _SHA.fullmatch(self.commit_sha):
            raise InputInvalidError("library commit_sha must be 7-40 lowercase hex characters")


@dataclass(frozen=True, slots=True)
class LibraryLimits:
    """Reader limits are configuration; there is no default."""

    max_file_bytes: int
    allowed_suffixes: frozenset[str]

    def __post_init__(self) -> None:
        if self.max_file_bytes < 1 or not self.allowed_suffixes:
            raise InputInvalidError("library limits need a positive size and a suffix list")


@runtime_checkable
class KnowledgeLibraryReader(Protocol):
    """Read-only view of a library at one verified commit: no write, copy or list method."""

    @property
    def commit_sha(self) -> str: ...

    def read_text(self, relative_path: str) -> str:
        """Text of one file; ``InputInvalidError`` for a bad path or an HEAD mismatch."""
        ...


def _git_dir(root: Path) -> Path:
    dot = root / ".git"
    if dot.is_dir():
        return dot
    if dot.is_file():
        first = dot.read_text(encoding="utf-8").strip()
        if first.startswith("gitdir: "):
            target = Path(first[len("gitdir: ") :])
            return target if target.is_absolute() else (root / target).resolve()
    raise MissingDependencyError("library path is not a git checkout")


def _common_dir(git_dir: Path) -> Path:
    marker = git_dir / "commondir"
    if marker.is_file():
        rel = marker.read_text(encoding="utf-8").strip()
        return (git_dir / rel).resolve()
    return git_dir


def _packed_ref(common: Path, ref: str) -> str | None:
    packed = common / "packed-refs"
    if not packed.is_file():
        return None
    for line in packed.read_text(encoding="utf-8").splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[1] == ref and _FULL.fullmatch(parts[0]):
            return parts[0]
    return None


def head_commit(repo_path: Path) -> str:
    """HEAD commit of a checkout, read from the git files (no git process, no index access)."""
    git_dir = _git_dir(repo_path)
    head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    if not head.startswith(_REF_PREFIX):
        if _FULL.fullmatch(head):
            return head
        raise MissingDependencyError("library HEAD is not readable")
    ref = head[len(_REF_PREFIX) :]
    common = _common_dir(git_dir)
    for base in (git_dir, common):
        loose = base / ref
        if loose.is_file():
            value = loose.read_text(encoding="utf-8").strip()
            if _FULL.fullmatch(value):
                return value
    found = _packed_ref(common, ref)
    if found is None:
        raise MissingDependencyError("library HEAD does not resolve to a commit")
    return found


class CheckoutLibraryReader:
    """``KnowledgeLibraryReader`` over a local checkout, bound to one expected commit."""

    def __init__(self, ref: LibraryRef, limits: LibraryLimits) -> None:
        if not ref.repo_path.is_dir():
            raise MissingDependencyError("library path does not exist")
        self._root = ref.repo_path.resolve()
        self._ref = ref
        self._limits = limits
        self._check_head()

    @property
    def commit_sha(self) -> str:
        return self._ref.commit_sha

    def _check_head(self) -> None:
        if not head_commit(self._root).startswith(self._ref.commit_sha):
            raise InputInvalidError("library checkout is not at the commit the job names")

    def _resolve(self, relative_path: str) -> Path:
        rel = Path(relative_path)
        if (
            not relative_path
            or rel.is_absolute()
            or "\\" in relative_path
            or "\x00" in relative_path
            or any(part in ("..", ".git", "") for part in relative_path.split("/"))
            or rel.suffix.lower() not in self._limits.allowed_suffixes
        ):
            raise InputInvalidError("library path must be a relative path of an allowed text file")
        target = (self._root / rel).resolve()
        if not target.is_relative_to(self._root) or ".git" in target.relative_to(self._root).parts:
            raise InputInvalidError("library path leaves the checkout")
        if not target.is_file():
            raise MissingDependencyError("library file does not exist")
        return target

    def read_text(self, relative_path: str) -> str:
        self._check_head()  # HEAD may have moved since construction
        target = self._resolve(relative_path)
        with open(target, "rb") as handle:
            data = handle.read(self._limits.max_file_bytes + 1)
        if len(data) > self._limits.max_file_bytes:
            raise InputInvalidError("library file exceeds the size limit")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InputInvalidError("library file is not UTF-8 text") from exc
