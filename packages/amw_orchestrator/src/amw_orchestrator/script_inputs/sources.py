"""Per-source use of a library work in a script: QUOTABLE or IDEAS_ONLY (D12, CCR-270 / CCR-291).

The owner's rule (``agent_06_fact_checker.library.copyright``): a work is public domain only when
its author, and for a translation also its translator, died MORE than 60 years before the START of
the job's calendar year. Only a public-domain work whose text the pinned checkout really holds is
``QUOTABLE``; every other work is ``IDEAS_ONLY`` (its ideas in the script's own words, credited as
further reading). The classification FAILS CLOSED:

* a citation the library index does not know, or a work with no copyright record: refused
  (``MissingDependencyError``): no source is used whose copyright status cannot be named;
* a record with an unknown, implausible or inconsistent field: ``IDEAS_ONLY`` (the reason code of
  ``evaluate_public_domain`` is kept);
* a public-domain work whose file is not in the pinned commit: ``IDEAS_ONLY``
  (``TEXT_NOT_IN_PINNED_COMMIT``): a quote could never be verified.

The text of a work that is not public domain is NEVER read. For a public-domain work the file is
read once through the read-only library reader only to prove it exists in the pinned commit; the
text is discarded, never logged or stored."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from agent_06_fact_checker.library.copyright import (
    WorkCopyrightRecord,
    evaluate_public_domain,
)
from agent_06_fact_checker.library.reader import KnowledgeLibraryReader
from agent_06_fact_checker.library.wiring import LibraryIndex
from amw_core.errors import MissingDependencyError


class SourceUse(StrEnum):
    QUOTABLE = "QUOTABLE"
    IDEAS_ONLY = "IDEAS_ONLY"


TEXT_NOT_IN_PINNED_COMMIT = "TEXT_NOT_IN_PINNED_COMMIT"
NOT_A_LIBRARY_WORK = "NOT_A_LIBRARY_WORK"


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    citation_ref: str
    use: SourceUse
    work_id: str | None
    """``None`` for a citation that is not a library work (an external reference)."""
    reason: str
    """``PUBLIC_DOMAIN`` or the ``PdReason`` / local code that made the source ideas-only."""
    evaluated_year: int | None = None


class LibrarySourceClassifier:
    """Marks the library works behind citation refs QUOTABLE or IDEAS_ONLY for one job date."""

    def __init__(
        self,
        index: LibraryIndex,
        records: Mapping[str, WorkCopyrightRecord],
    ) -> None:
        self._index, self._records = index, records

    def classify(
        self,
        citation_refs: Iterable[str],
        *,
        library: KnowledgeLibraryReader | None,
        job_date: date,
    ) -> dict[str, ResolvedSource]:
        out: dict[str, ResolvedSource] = {}
        for ref in dict.fromkeys(citation_refs):
            work = self._index.lookup(ref)
            if work is None:
                raise MissingDependencyError(
                    "a cited library source is not in the library index",
                    details={"class": "library_source"},
                )
            record = self._records.get(work.work_id)
            if record is None:
                raise MissingDependencyError(
                    "a cited library work has no copyright record",
                    details={"class": "work_record"},
                )
            decision = evaluate_public_domain(record, year=job_date.year)
            if not decision.public_domain:
                out[ref] = ResolvedSource(
                    ref, SourceUse.IDEAS_ONLY, work.work_id, decision.reason.value,
                    decision.evaluated_year,
                )  # fmt: skip
                continue
            out[ref] = self._quotable(ref, work.work_id, record, library, decision.evaluated_year)
        return out

    @staticmethod
    def _quotable(
        ref: str,
        work_id: str,
        record: WorkCopyrightRecord,
        library: KnowledgeLibraryReader | None,
        year: int,
    ) -> ResolvedSource:
        if library is None:
            raise MissingDependencyError(
                "a public-domain source needs the library of the job",
                details={"class": "library"},
            )
        try:
            library.read_text(record.text_path)  # proves the file is in the pinned commit
        except MissingDependencyError:
            return ResolvedSource(
                ref, SourceUse.IDEAS_ONLY, work_id, TEXT_NOT_IN_PINNED_COMMIT, year
            )
        return ResolvedSource(ref, SourceUse.QUOTABLE, work_id, "PUBLIC_DOMAIN", year)
