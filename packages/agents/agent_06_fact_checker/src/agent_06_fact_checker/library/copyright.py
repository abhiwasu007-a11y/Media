"""Per-work copyright record and the computed public-domain flag (PD-LEDGER, CCR-270 PROPOSED).

Owner rule (D12): a work is public domain only when its author, and for a translation also its
translator, died MORE THAN 60 years before the START of the current calendar year, that is
``year - death_year > 60`` for the year of the job date (CCR-270: ``death_year < year - 60``).
Any unknown or implausible field means ``False`` (fail closed). The flag is recomputed at every
use against an injected date and is never stored. Year granularity is the owner's rule, not a
legal fact (REQUIRES REVIEW (Phase 1): legal confirmation per distribution jurisdiction).
Instance data lives only in the private knowledge repository; this module carries the rule.
"""

from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import StringConstraints

from amw_core.contracts.common import AmwModel
from amw_core.interfaces.clock import Clock

PD_YEARS_AFTER_DEATH = 60
"""D12 / CCR-270: years that must have passed before the start of the current calendar year."""

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
_WorkId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,99}$")]
_RelPath = Annotated[str, StringConstraints(min_length=1, max_length=300)]


class WorkKind(StrEnum):
    ORIGINAL = "ORIGINAL"
    TRANSLATION = "TRANSLATION"


class PdReason(StrEnum):
    """Why the flag has its value; every code except ``PUBLIC_DOMAIN`` means ``False``."""

    PUBLIC_DOMAIN = "PUBLIC_DOMAIN"
    AUTHOR_DEATH_YEAR_UNKNOWN = "AUTHOR_DEATH_YEAR_UNKNOWN"
    AUTHOR_NOT_YET_PUBLIC_DOMAIN = "AUTHOR_NOT_YET_PUBLIC_DOMAIN"
    TRANSLATOR_UNKNOWN = "TRANSLATOR_UNKNOWN"
    TRANSLATOR_DEATH_YEAR_UNKNOWN = "TRANSLATOR_DEATH_YEAR_UNKNOWN"
    TRANSLATOR_NOT_YET_PUBLIC_DOMAIN = "TRANSLATOR_NOT_YET_PUBLIC_DOMAIN"
    DEATH_YEAR_IMPLAUSIBLE = "DEATH_YEAR_IMPLAUSIBLE"
    RECORD_INCONSISTENT = "RECORD_INCONSISTENT"


class WorkCopyrightRecord(AmwModel):
    """One work of the knowledge library (CCR-270 fields plus the location of its text)."""

    work_id: _WorkId
    title: _Text
    author: _Text
    author_death_year: int | None = None
    work_kind: WorkKind
    translator: _Text | None = None
    translator_death_year: int | None = None
    translation_year: int | None = None
    """Year of the translation, used only for the credit line."""
    text_path: _RelPath
    """Relative path of the text file inside the library checkout."""


class PublicDomainDecision(AmwModel):
    public_domain: bool
    reason: PdReason
    evaluated_year: int
    latest_death_year_allowed: int
    """``evaluated_year - 60 - 1``: a death year up to and including this passes."""


def job_year(job_date: date) -> int:
    return job_date.year


def clock_year(clock: Clock) -> int:
    """Calendar year of the injected clock (UTC)."""
    return clock.now().year


def _plausible(year: int | None, evaluated_year: int) -> bool:
    return year is not None and 1 <= year <= evaluated_year


def evaluate_public_domain(
    record: WorkCopyrightRecord,
    *,
    year: int,
    years_after_death: int = PD_YEARS_AFTER_DEATH,
) -> PublicDomainDecision:
    """The owner rule for ``year`` (the calendar year of the job date); fails closed."""
    limit = year - years_after_death - 1

    def decide(ok: bool, reason: PdReason) -> PublicDomainDecision:
        return PublicDomainDecision(
            public_domain=ok, reason=reason, evaluated_year=year, latest_death_year_allowed=limit
        )

    if record.author_death_year is None:
        return decide(False, PdReason.AUTHOR_DEATH_YEAR_UNKNOWN)
    if not _plausible(record.author_death_year, year):
        return decide(False, PdReason.DEATH_YEAR_IMPLAUSIBLE)
    if year - record.author_death_year <= years_after_death:
        return decide(False, PdReason.AUTHOR_NOT_YET_PUBLIC_DOMAIN)
    if record.work_kind is WorkKind.ORIGINAL:
        if record.translator is not None or record.translator_death_year is not None:
            return decide(False, PdReason.RECORD_INCONSISTENT)
        return decide(True, PdReason.PUBLIC_DOMAIN)
    if record.translator is None:
        return decide(False, PdReason.TRANSLATOR_UNKNOWN)
    if record.translator_death_year is None:
        return decide(False, PdReason.TRANSLATOR_DEATH_YEAR_UNKNOWN)
    if not _plausible(record.translator_death_year, year):
        return decide(False, PdReason.DEATH_YEAR_IMPLAUSIBLE)
    if year - record.translator_death_year <= years_after_death:
        return decide(False, PdReason.TRANSLATOR_NOT_YET_PUBLIC_DOMAIN)
    return decide(True, PdReason.PUBLIC_DOMAIN)


def is_public_domain(record: WorkCopyrightRecord, *, job_date: date) -> bool:
    """The flag for the year of ``job_date`` (the date comes from the job, never from a global)."""
    return evaluate_public_domain(record, year=job_year(job_date)).public_domain
