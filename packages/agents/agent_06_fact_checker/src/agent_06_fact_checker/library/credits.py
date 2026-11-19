"""Credit lines and the further-reading check (D12; for the script gate and Agent 16).

Data model plus pure check, no channel text: a quoted public-domain work needs its credit line in
the video description (author, work, translator, year of the translation); a work used for ideas
only (not public domain, or unknown) needs a further-reading credit and must not be quoted.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from agent_06_fact_checker.library.copyright import (
    WorkCopyrightRecord,
    WorkKind,
    evaluate_public_domain,
    job_year,
)
from agent_06_fact_checker.library.quotes import normalise_quote_text
from amw_core.contracts.common import AmwModel


class WorkUse(StrEnum):
    QUOTED = "QUOTED"
    IDEAS_ONLY = "IDEAS_ONLY"


class CreditProblem(StrEnum):
    QUOTED_WORK_NOT_PUBLIC_DOMAIN = "QUOTED_WORK_NOT_PUBLIC_DOMAIN"
    CREDIT_MISSING = "CREDIT_MISSING"
    UNKNOWN_WORK = "UNKNOWN_WORK"


@dataclass(frozen=True, slots=True)
class UsedWork:
    work_id: str
    use: WorkUse


class CreditFinding(AmwModel):
    work_id: str
    problem: CreditProblem


def credit_line(record: WorkCopyrightRecord, use: WorkUse) -> str:
    """The credit text: public-domain translation line, or the further-reading line."""
    if record.work_kind is WorkKind.TRANSLATION and record.translator:
        year = f", {record.translation_year}" if record.translation_year else ""
        who = f"translated by {record.translator}{year}"
        base = f"{record.author}, {record.title}, {who}"
    else:
        base = f"{record.author}, {record.title}"
    return f"{base}. Public domain." if use is WorkUse.QUOTED else f"Further reading: {base}."


def check_credits(
    used: Sequence[UsedWork],
    records: dict[str, WorkCopyrightRecord],
    description: str,
    *,
    job_date: date,
) -> list[CreditFinding]:
    """Findings for the gate; an empty list means every used work is credited correctly.

    The credit must appear in ``description`` as an exact substring after whitespace and quote
    normalisation (same rule as quote matching)."""
    haystack = normalise_quote_text(description)
    findings: list[CreditFinding] = []
    for item in used:
        record = records.get(item.work_id)
        if record is None:
            findings.append(CreditFinding(work_id=item.work_id, problem=CreditProblem.UNKNOWN_WORK))
            continue
        use = item.use
        if (
            use is WorkUse.QUOTED
            and not evaluate_public_domain(record, year=job_year(job_date)).public_domain
        ):
            findings.append(
                CreditFinding(
                    work_id=item.work_id, problem=CreditProblem.QUOTED_WORK_NOT_PUBLIC_DOMAIN
                )
            )
            continue
        if normalise_quote_text(credit_line(record, use)) not in haystack:
            findings.append(
                CreditFinding(work_id=item.work_id, problem=CreditProblem.CREDIT_MISSING)
            )
    return findings
