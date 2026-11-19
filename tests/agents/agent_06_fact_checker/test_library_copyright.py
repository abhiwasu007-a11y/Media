"""PD-LEDGER: the 60-year rule, computed, fail closed, clock injected (CCR-270 PROPOSED)."""

from datetime import UTC, date, datetime
from typing import Any

import pytest

from agent_06_fact_checker.library.copyright import (
    PdReason,
    WorkKind,
    clock_year,
    evaluate_public_domain,
    is_public_domain,
)
from tests.agents.agent_06_fact_checker.library_support import FixedClock, record

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("death", "year", "expected"),
    [
        (1965, 2026, True),  # 61 years: more than 60
        (1966, 2026, False),  # exactly 60: not more than 60
        (1966, 2027, True),
        (1965, 2025, False),  # same work, previous calendar year
        (1959, 2026, True),  # a translator who died in 1959
        (1971, 2026, False),  # died 1971: not yet PD (55 years)
        (2000, 2026, False),
    ],
)
def test_sixty_year_boundary(death: int, year: int, expected: bool) -> None:
    rec = record("w", "a.txt", author_death=death)
    decision = evaluate_public_domain(rec, year=year)
    assert decision.public_domain is expected
    assert decision.latest_death_year_allowed == year - 61
    assert (decision.reason is PdReason.PUBLIC_DOMAIN) is expected


def test_flag_follows_the_year_of_the_job_date() -> None:
    rec = record("w", "a.txt", author_death=1965)
    assert is_public_domain(rec, job_date=date(2025, 12, 31)) is False
    assert is_public_domain(rec, job_date=date(2026, 1, 1)) is True


def test_clock_is_injected() -> None:
    assert clock_year(FixedClock(datetime(2031, 6, 1, tzinfo=UTC))) == 2031


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"author_death": None}, PdReason.AUTHOR_DEATH_YEAR_UNKNOWN),
        ({"author_death": 1990}, PdReason.AUTHOR_NOT_YET_PUBLIC_DOMAIN),
        ({"author_death": 2999}, PdReason.DEATH_YEAR_IMPLAUSIBLE),
        ({"author_death": 0}, PdReason.DEATH_YEAR_IMPLAUSIBLE),
        ({"translator": "T"}, PdReason.RECORD_INCONSISTENT),
        ({"translator_death": 1900}, PdReason.RECORD_INCONSISTENT),
    ],
)
def test_original_fails_closed(kwargs: dict[str, Any], reason: PdReason) -> None:
    rec = record("w", "a.txt", **kwargs)
    decision = evaluate_public_domain(rec, year=2026)
    assert (decision.public_domain, decision.reason) == (False, reason)


@pytest.mark.parametrize(
    ("translator", "tdeath", "reason"),
    [
        (None, None, PdReason.TRANSLATOR_UNKNOWN),
        ("Tr", None, PdReason.TRANSLATOR_DEATH_YEAR_UNKNOWN),
        ("Tr", 1971, PdReason.TRANSLATOR_NOT_YET_PUBLIC_DOMAIN),
        ("Tr", 1966, PdReason.TRANSLATOR_NOT_YET_PUBLIC_DOMAIN),
        ("Tr", 3000, PdReason.DEATH_YEAR_IMPLAUSIBLE),
        ("Tr", 1959, PdReason.PUBLIC_DOMAIN),
    ],
)
def test_translation_needs_a_public_domain_translator(
    translator: str | None, tdeath: int | None, reason: PdReason
) -> None:
    rec = record(
        "w",
        "a.txt",
        author_death=100,
        kind=WorkKind.TRANSLATION,
        translator=translator,
        translator_death=tdeath,
    )
    decision = evaluate_public_domain(rec, year=2026)
    assert decision.reason is reason
    assert decision.public_domain is (reason is PdReason.PUBLIC_DOMAIN)


def test_old_translator_does_not_rescue_a_recent_author() -> None:
    rec = record(
        "w",
        "a.txt",
        author_death=1990,
        kind=WorkKind.TRANSLATION,
        translator="Tr",
        translator_death=1800,
    )
    assert evaluate_public_domain(rec, year=2026).reason is PdReason.AUTHOR_NOT_YET_PUBLIC_DOMAIN


def test_flag_is_computed_never_stored() -> None:
    rec = record("w", "a.txt")
    assert "public_domain" not in type(rec).model_fields
    assert "public_domain" not in rec.model_dump()


def test_record_rejects_unknown_fields_and_bad_ids() -> None:
    from pydantic import ValidationError

    from agent_06_fact_checker.library.copyright import WorkCopyrightRecord

    with pytest.raises(ValidationError):
        WorkCopyrightRecord.model_validate(
            {
                "work_id": "Bad Id",
                "title": "t",
                "author": "a",
                "work_kind": "ORIGINAL",
                "text_path": "x",
            }
        )
    with pytest.raises(ValidationError):
        WorkCopyrightRecord.model_validate(
            {
                "work_id": "ok",
                "title": "t",
                "author": "a",
                "work_kind": "ORIGINAL",
                "text_path": "x",
                "public_domain": True,
            }
        )
