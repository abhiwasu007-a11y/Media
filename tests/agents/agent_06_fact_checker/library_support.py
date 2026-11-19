"""Synthetic mini-library for the quote / copyright tests: invented sentences only.

No text of the real private knowledge library is used or copied; the checkout is a real git
repository built in a test tmp directory (local ``git init`` / ``commit``, no network)."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from agent_06_fact_checker.library.copyright import WorkCopyrightRecord, WorkKind
from agent_06_fact_checker.library.reader import (
    CheckoutLibraryReader,
    LibraryLimits,
    LibraryRef,
)

LIMITS = LibraryLimits(max_file_bytes=10_000, allowed_suffixes=frozenset({".txt", ".md"}))
JOB_DATE = datetime(2026, 11, 19, tzinfo=UTC).date()

ORIGINAL_TEXT = """Preface line before any section marker.
§ I.1
The river of days runs quicker than the idle hour admits.
It is not time we lack but the will to hold it.
§ I.2
A lamp unlit gives no account of the dark.
§ II.1
Short  life\u00a0is  a \u201cborrowed\u201d coat, said the clerk.
He wore it\u2019s patches with pride.
"""
TRANSLATION_TEXT = """§ 1
Every harbour was once an open shore.
§ 2
The ledger of hours is kept by the careless.
"""
NONPD_TEXT = "§ 1\nThis sentence must never be read by the verifier.\n"
DUPLICATE_TEXT = "§ A\nFirst body line here.\n§ A\nSecond body line here.\n"
NOMARKER_TEXT = "A plain text without any section marker line at all.\n"

FILES = {
    "phil/original.txt": ORIGINAL_TEXT,
    "phil/translation.txt": TRANSLATION_TEXT,
    "phil/modern.txt": NONPD_TEXT,
    "phil/dup.txt": DUPLICATE_TEXT,
    "phil/plain.txt": NOMARKER_TEXT,
    "phil/book.pdf": "not text",
}


def record(
    work_id: str,
    path: str,
    *,
    author: str = "Aelius Testor",
    author_death: int | None = 1500,
    kind: WorkKind = WorkKind.ORIGINAL,
    translator: str | None = None,
    translator_death: int | None = None,
    year: int | None = None,
) -> WorkCopyrightRecord:
    return WorkCopyrightRecord(
        work_id=work_id,
        title=f"On {work_id}",
        author=author,
        author_death_year=author_death,
        work_kind=kind,
        translator=translator,
        translator_death_year=translator_death,
        translation_year=year,
        text_path=path,
    )


def records() -> dict[str, WorkCopyrightRecord]:
    items = [
        record("orig", "phil/original.txt"),
        record(
            "trans",
            "phil/translation.txt",
            author="Quintus Fictus",
            author_death=100,
            kind=WorkKind.TRANSLATION,
            translator="Mary Invented",
            translator_death=1900,
            year=1890,
        ),
        record(
            "modern",
            "phil/modern.txt",
            author="Quintus Fictus",
            author_death=100,
            kind=WorkKind.TRANSLATION,
            translator="Living Translator",
            translator_death=1990,
            year=1985,
        ),
        record("unknown", "phil/modern.txt", author_death=None),
        record("dup", "phil/dup.txt"),
        record("plain", "phil/plain.txt"),
    ]
    return {r.work_id: r for r in items}


_GIT_ENV = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603 - fixed argv built from test paths
        ["git", "-C", str(repo), *args],  # noqa: S607
        capture_output=True,
        check=True,
        text=True,
        env=_GIT_ENV,
    )
    return done.stdout.strip()


def make_library(root: Path, files: dict[str, str] | None = None) -> Path:
    """A real, committed git repository holding the files (symlinks may be added after)."""
    repo = root / "lib"
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    for rel, text in (files if files is not None else FILES).items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", "synthetic library")
    return repo


def head_sha(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD")


def make_reader(root: Path) -> CheckoutLibraryReader:
    repo = make_library(root)
    return CheckoutLibraryReader(LibraryRef(repo, head_sha(repo)), LIMITS)


class FixedClock:
    def __init__(self, when: datetime) -> None:
        self._when = when

    def now(self) -> datetime:
        return self._when

    def monotonic_ms(self) -> int:
        return 0
