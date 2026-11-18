"""Every enum value of GLOSSARY section 6 exists in amw_core.enums with the exact spelling."""

import pytest

from amw_core import enums
from tests.docs_tables import glossary_enums

GLOSSARY = glossary_enums()


def test_every_glossary_enum_has_a_class() -> None:
    assert set(GLOSSARY) == set(enums.GLOSSARY_ENUMS)


@pytest.mark.parametrize("name", sorted(GLOSSARY))
def test_values_match_glossary_exactly(name: str) -> None:
    code_values = [str(member.value) for member in enums.GLOSSARY_ENUMS[name]]
    assert code_values == GLOSSARY[name]


def test_priority_queue_integers() -> None:
    assert [p.queue_int for p in enums.Priority] == [0, 1, 2, 3, 4]


def test_feature_status_display_strings() -> None:
    assert [f.display for f in enums.FeatureStatus] == [
        "Planned",
        "In Development",
        "Implemented",
        "Tested",
        "Production Ready",
    ]


def test_quality_points_sum_to_100() -> None:
    assert sum(d.max_points for d in enums.QualityDimension) == 100


def test_small_helpers() -> None:
    assert not enums.ApprovalState.PENDING.is_final
    assert enums.ApprovalState.WITHDRAWN.is_final
    assert enums.AdSpotDurationS.S15.duration_target_ms == 15000
    assert enums.TransitionId.T03.entity_kind is enums.EntityKind.TASK
    assert enums.TransitionId.J12.entity_kind is enums.EntityKind.JOB


def test_pending_ccr_values_are_not_invented() -> None:
    # CCR-3A-4 / CCR-3A-5 are pending: the values must not exist until applied to GLOSSARY.
    assert "PILOT_TOTAL" not in {p.value for p in enums.BudgetPeriod}
    assert "PROVIDER" not in {s.value for s in enums.BudgetScopeKind}
