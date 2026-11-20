"""Synthetic fake library for the index tests: a git checkout of invented filler text built in a
temporary directory. No private library text exists in the repository, its tests or its logs."""

import subprocess
from pathlib import Path

from amw_core.ids import ORG, new_uuid7

ORG_A = str(ORG.from_uuid(new_uuid7()))
ORG_B = str(ORG.from_uuid(new_uuid7()))
COLLECTION = "col_synthetic"

WORK_ONE = (
    "synthetic preface, not a section\n"
    "§ 1.1\nalpha beta gamma\ndelta epsilon\n"
    "§ 1.2\nzeta eta theta\n"
    "§ 2\ntail of the first synthetic work\n"
)
WORK_TWO = "§ A\nfirst body\n§ A\nrepeated locator\n§ B\nsecond body\n"
NO_SECTIONS = "plain synthetic file with no marker at all\n"
CRLF = "§ 9\r\nwindows line one\r\nwindows line two\r\n§ 10\r\nlast\r\n"


def git(root: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603 - fixed argv in a temporary directory
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def make_library(root: Path, files: dict[str, str] | None = None) -> str:
    """A git checkout with the given files committed; returns the full commit SHA."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    for name, body in (
        files
        or {
            "works/one.txt": WORK_ONE,
            "works/two.txt": WORK_TWO,
            "works/plain.txt": NO_SECTIONS,
            "works/crlf.txt": CRLF,
            "image.bin": "ignored: suffix not allowed",
        }
    ).items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body.encode("utf-8"))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "synthetic")
    return git(root, "rev-parse", "HEAD")


def tree_snapshot(root: Path) -> dict[str, bytes]:
    """Every file under ``root`` (including ``.git``) with its bytes, for before/after compares."""
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }
