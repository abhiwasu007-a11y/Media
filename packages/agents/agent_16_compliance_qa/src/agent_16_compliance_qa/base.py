"""Shared model base and the verdict order used by every Agent 16 component."""

from collections.abc import Iterable
from typing import Final

from pydantic import BaseModel, ConfigDict

from amw_core.enums import CheckVerdict, ComplianceVerdict


class Model(BaseModel):
    """Frozen, strict-shape Pydantic base (unknown fields are an error, 27 section 7.3.2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


_RANK: Final = {
    ComplianceVerdict.ALLOWED: 0,
    ComplianceVerdict.NEEDS_HUMAN_REVIEW: 1,
    ComplianceVerdict.BLOCKED: 2,
}
_CHECK_RANK: Final = {
    CheckVerdict.SKIPPED: 0,
    CheckVerdict.PASS: 1,
    CheckVerdict.WARN: 2,
    CheckVerdict.FAIL: 3,
}


def worst(verdicts: Iterable[ComplianceVerdict | None]) -> ComplianceVerdict:
    """``BLOCKED`` > ``NEEDS_HUMAN_REVIEW`` > ``ALLOWED`` (13 section 2.3); empty = ``ALLOWED``."""
    found = [v for v in verdicts if v is not None]
    return max(found, key=_RANK.__getitem__) if found else ComplianceVerdict.ALLOWED


def worse_or_equal(a: ComplianceVerdict, b: ComplianceVerdict) -> bool:
    """True when ``a`` is at least as strict as ``b`` (monotonicity, P-01)."""
    return _RANK[a] >= _RANK[b]


def worst_check(verdicts: Iterable[CheckVerdict]) -> CheckVerdict:
    found = list(verdicts)
    return max(found, key=_CHECK_RANK.__getitem__) if found else CheckVerdict.SKIPPED
