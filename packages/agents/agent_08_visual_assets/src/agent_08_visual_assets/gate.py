"""``GateRouter``: the single gate result of Agent 08 and its remedy stage (blueprint 18, GR-*)."""

from collections.abc import Sequence
from dataclasses import dataclass

from amw_core.enums import ShotUnresolvedReason
from amw_core.errors import MissingDependencyError

GATE_CHECK_ID = "a08.cov.all_shots_resolved"
PLAN_STAGE_ID = "s09_plan"

OWNER_MATERIAL_REASONS = frozenset(
    {
        ShotUnresolvedReason.NO_DATASET,
        ShotUnresolvedReason.NO_CHART_CASE,
        ShotUnresolvedReason.METHOD_NOT_RELEASED,
    }
)


@dataclass(frozen=True, slots=True)
class Unresolved:
    shot_id: str
    reason: ShotUnresolvedReason


@dataclass(frozen=True, slots=True)
class GateResult:
    check_id: str
    verdict: str
    blocking: bool
    gate: bool
    remedy_stage_id: str | None


@dataclass(frozen=True, slots=True)
class GateOutcome:
    task_status: str
    gate_verdict: str | None
    error_code: str | None
    gate_result: GateResult | None
    next_action_type: str | None


class GateRouter:
    """Pure. Owner-material reasons fail the task; the others fail the gate.

    The remedy is the earliest stage that fixes every cause (24 section 3.3 rule 1): the script
    stage when a chart must change (``DATA_WITHIN_LAG``), else the plan stage.
    """

    @staticmethod
    def route(unresolved: Sequence[Unresolved], script_stage_id: str) -> GateOutcome:
        if not unresolved:
            return GateOutcome(
                "SUCCEEDED",
                "PASSED",
                None,
                GateResult(GATE_CHECK_ID, "PASS", True, True, None),
                "CONTINUE",
            )
        if any(u.reason in OWNER_MATERIAL_REASONS for u in unresolved):
            return GateOutcome("FAILED", None, MissingDependencyError.code, None, None)
        needs_script = any(u.reason is ShotUnresolvedReason.DATA_WITHIN_LAG for u in unresolved)
        remedy = script_stage_id if needs_script else PLAN_STAGE_ID
        return GateOutcome(
            "SUCCEEDED",
            "FAILED",
            None,
            GateResult(GATE_CHECK_ID, "FAIL", True, True, remedy),
            "CONTINUE",
        )
