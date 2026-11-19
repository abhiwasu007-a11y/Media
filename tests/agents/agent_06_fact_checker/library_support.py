"""Synthetic mini-library for the quote / copyright tests: invented sentences only.

No text of the real private knowledge library is used or copied; the fake checkout is built in a
test tmp directory and carries a hand-written git HEAD so no git process or network is needed."""

# ruff: noqa: RUF001

from datetime import UTC, datetime
from pathlib import Path

from agent_06_fact_checker.library.copyright import WorkCopyrightRecord, WorkKind
from agent_06_fact_checker.library.reader import (
    CheckoutLibraryReader,
    LibraryLimits,
    LibraryRef,
)

SHA = "0123456789abcdef0123456789abcdef01234567"
LIMITS = LibraryLimits(max_file_bytes=10_000, allowed_suffixes=frozenset({".txt", ".md"}))
JOB_DATE = datetime(2026, 11, 19, tzinfo=UTC).date()

ORIGINAL_TEXT = """Preface line before any section marker.
§ I.1
The river of days runs quicker than the idle hour admits.
It is not time we lack but the will to hold it.
§ I.2
A lamp unlit gives no account of the dark.
§ II.1
Short  life is  a “borrowed” coat, said the clerk.
He wore it’s patches with pride.
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


def make_library(root: Path, files: dict[str, str] | None = None, sha: str = SHA) -> Path:
    repo = root / "lib"
    git = repo / ".git"
    (git / "refs" / "heads").mkdir(parents=True, exist_ok=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "refs" / "heads" / "main").write_text(sha + "\n", encoding="utf-8")
    for rel, text in (files if files is not None else FILES).items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return repo


def make_reader(root: Path) -> CheckoutLibraryReader:
    return CheckoutLibraryReader(LibraryRef(make_library(root), SHA), LIMITS)


class FixedClock:
    def __init__(self, when: datetime) -> None:
        self._when = when

    def now(self) -> datetime:
        return self._when

    def monotonic_ms(self) -> int:
        return 0
