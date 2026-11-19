"""Cost-per-stage report data (09 section 12)."""

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from amw_core.cost import (
    AllocatedLine,
    JobHeader,
    MemoryCostLedger,
    TaskInfo,
    build_cost_stage_report,
)
from amw_core.cost.report import review, term_of, to_minor
from amw_core.enums import (
    BudgetPeriod,
    BudgetScopeKind,
    BudgetState,
    CostFigureKind,
    CostOperation,
    CostUnitKind,
)
from amw_core.errors import ConfigInvalidError, InputInvalidError
from amw_core.ids import ATTEMPT, JOB, ORG, TASK
from amw_core.interfaces.budget_guard import BudgetStatus
from amw_core.interfaces.cost_ledger import NewCostEntry
from tests.core_services.support import T0, budget, tx_for

pytestmark = pytest.mark.unit
EXP = {"INR": 2}
ORG_A = ORG.new()
JOB_A = JOB.new()
SCRIPT_1, SCRIPT_2, VOICE, ORPHAN = TASK.new(), TASK.new(), TASK.new(), TASK.new()
BAD_ATTEMPT = ATTEMPT.new()
HEADER = JobHeader(JOB_A, "CHANNEL_LONG_FORM", 2, "topic-ref", "development")
TASKS = {
    SCRIPT_1: TaskInfo("agent_05.script_draft", "s05_script", 0, output_discarded=True),
    SCRIPT_2: TaskInfo("agent_05.script_draft", "s05_script", 1),
    VOICE: TaskInfo(
        "agent_07.voice_synthesis", "s07_voice", 0, discarded_attempts=frozenset({BAD_ATTEMPT})
    ),
}


def _row(task: str, micros: int, **kw: object) -> NewCostEntry:
    base = NewCostEntry(
        provider="llm_provider",
        operation=CostOperation.LLM_COMPLETION,
        amount_micros=micros,
        currency="INR",
        figure_kind=CostFigureKind.ESTIMATE,
        occurred_at=T0,
        job_id=JOB_A,
        task_id=task,  # type: ignore[arg-type]
        model="model-mid",
        tokens_in=100,
        tokens_out=50,
        tokens_cached_in=10,
        price_ref="pricing.v1",
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def _ledger() -> MemoryCostLedger:
    led = MemoryCostLedger()
    tx = tx_for(ORG_A)
    led.record(tx, _row(SCRIPT_1, 300_000))
    led.record(tx, _row(SCRIPT_2, 200_000))
    tts = {
        "provider": "tts_provider",
        "operation": CostOperation.TTS_SYNTHESIZE,
        "model": "tts-v",
        "tokens_in": None,
        "tokens_out": None,
        "tokens_cached_in": None,
        "units": Decimal("4500"),
        "unit_kind": CostUnitKind.CHARACTERS,
    }
    led.record(tx, _row(VOICE, 400_000, attempt_id=BAD_ATTEMPT, **tts))
    led.record(tx, _row(VOICE, 100_005, **tts))
    led.record(
        tx,
        _row(
            ORPHAN,
            0,
            provider="render",
            operation=CostOperation.RENDER_FFMPEG,
            price_ref=None,
            model=None,
            units=Decimal(1),
            unit_kind=CostUnitKind.RENDER_MS,
        ),
    )
    return led


def _statuses() -> list[BudgetStatus]:
    video = budget(ORG_A, BudgetPeriod.PER_VIDEO, 200)
    pilot = budget(ORG_A, BudgetPeriod.PILOT_TOTAL, 5000, state=BudgetState.SUSPENDED_EXCEEDED)
    prov = budget(
        ORG_A,
        BudgetPeriod.PILOT_TOTAL,
        9000,
        scope_kind=BudgetScopeKind.PROVIDER,
        scope_key="llm_provider",
    )
    return [
        BudgetStatus(video, 1_000_005, 999_995, True),
        BudgetStatus(pilot, 50_000_000, 0, True),
        BudgetStatus(prov, 1_000, 89_999_000, False),
    ]


def _report(**kw: object):  # type: ignore[no-untyped-def]
    led = _ledger()
    return build_cost_stage_report(
        HEADER,
        led.for_job(tx_for(ORG_A), JOB_A),
        TASKS,
        _statuses(),
        T0,
        EXP,
        price_ref_sources={"pricing.v1": "PR-01"},
        **kw,  # type: ignore[arg-type]
    )


def test_rows_group_by_stage_and_add_up_to_the_ledger_sum() -> None:
    rep = _report()
    assert rep.total_micros == 1_000_005
    assert rep.total_minor == 100
    assert rep.query_scope == f"cost_ledger WHERE job_id = {JOB_A}"
    by_stage = {r.stage: r for r in rep.rows}
    script = by_stage["s05_script"]
    assert (script.calls, script.tokens_in, script.tokens_out, script.tokens_cached_in) == (
        2,
        200,
        100,
        20,
    )
    assert script.cost_micros == 500_000
    assert script.revision_loops == 1
    assert script.wasted_cost_micros == 300_000
    assert script.share_of_total == "50.0%"
    voice = by_stage["s07_voice"]
    assert voice.units == {"characters": "9000"}
    assert voice.wasted_cost_micros == 400_000
    assert voice.figure_kind == "ESTIMATE"
    assert voice.revision_loops == 0
    unlinked = [r for r in rep.rows if r.stage.startswith("REQUIRES REVIEW")]
    assert len(unlinked) == 1
    assert unlinked[0].share_of_total == "0.0%"
    assert sum(r.cost_micros for r in rep.rows) == rep.total_micros
    assert rep.terms_micros["LLM"] == 500_000
    assert rep.terms_micros["TTS"] == 500_005
    assert rep.terms_micros["infra"] == 0
    assert rep.price_refs == {"pricing.v1": "PR-01"}


def test_header_budget_lines_and_unknowns_print_requires_review() -> None:
    rep = _report()
    assert rep.figure_kind_summary == "ESTIMATE"
    assert rep.header_budget["per_video_limit_minor"] == 200
    assert rep.header_budget["pilot_committed_micros"] == 50_000_000
    statuses = [b.status for b in rep.budgets]
    assert statuses == ["soft_limit_exceeded", "breached", "within_limit"]
    assert "green" in rep.budgets[2].status_text
    assert "red" in rep.budgets[1].status_text
    assert str(rep.human_review_minutes).startswith("REQUIRES REVIEW (Phase 1):")
    text = rep.to_text()
    assert "s05_script" in text
    assert "REQUIRES REVIEW" in text
    doc = json.loads(rep.to_json())
    assert doc["total_micros"] == 1_000_005


def test_allocated_lines_are_separate_and_unknowns_never_zero() -> None:
    rep = _report(
        allocated=[
            AllocatedLine("footage", "stock subscription share", None, "videos per month"),
            AllocatedLine("infra", "VPS share", 0),
        ],
        human_review_minutes=12,
    )
    assert rep.allocated[0].amount_micros == review("videos per month")
    assert rep.allocated[1].amount_micros == 0
    assert rep.allocated[0].allocated
    assert rep.human_review_minutes == 12
    assert rep.total_micros == 1_000_005  # allocated lines are not mixed into per-call totals


def test_price_ref_without_research_id_and_missing_budgets() -> None:
    led = _ledger()
    rep = build_cost_stage_report(HEADER, led.for_job(tx_for(ORG_A), JOB_A), TASKS, [], T0, {})
    assert rep.price_refs["pricing.v1"].startswith("REQUIRES REVIEW")
    assert str(rep.total_minor).startswith("REQUIRES REVIEW")
    assert str(rep.header_budget["pilot_limit_minor"]).startswith("REQUIRES REVIEW")


def test_verified_rows_and_mixed_labels() -> None:
    led = MemoryCostLedger()
    tx = tx_for(ORG_A)
    est = led.record(tx, _row(SCRIPT_2, 100))
    led.record(
        tx,
        _row(
            SCRIPT_2,
            120,
            figure_kind=CostFigureKind.VERIFIED,
            price_ref=None,
            estimate_entry_id=est.id,
            verification_ref="inv",
        ),
    )
    led.record(tx, _row(SCRIPT_1, 50))
    rep = build_cost_stage_report(HEADER, led.for_job(tx, JOB_A), TASKS, [], T0, EXP)
    assert rep.figure_kind_summary == "partly verified (1 of 2 rows)"
    assert rep.rows[0].figure_kind == "mixed"
    assert rep.total_micros == 170


def test_empty_job_report() -> None:
    rep = build_cost_stage_report(HEADER, [], TASKS, [], T0, EXP)
    assert rep.total_micros == 0
    assert rep.rows == []
    assert rep.currency.startswith("REQUIRES REVIEW")


def test_rows_of_another_job_are_refused() -> None:
    led = MemoryCostLedger()
    tx = tx_for(ORG_A)
    led.record(tx, _row(SCRIPT_1, 1, job_id=JOB.new()))
    with pytest.raises(InputInvalidError):
        build_cost_stage_report(HEADER, led.all_rows(tx), TASKS, [], T0, EXP)


@pytest.mark.security
def test_report_with_a_secret_like_value_is_refused() -> None:
    led = MemoryCostLedger()
    tx = tx_for(ORG_A)
    led.record(tx, _row(SCRIPT_1, 1, model="sk-ant-" + "q" * 30))
    with pytest.raises(InputInvalidError, match="secret"):
        build_cost_stage_report(HEADER, led.all_rows(tx), TASKS, [], T0, EXP)


def test_mixed_currencies_fail_closed() -> None:
    led = MemoryCostLedger()
    tx = tx_for(ORG_A)
    led.record(tx, _row(SCRIPT_1, 1))
    led.record(tx, _row(SCRIPT_2, 1, currency="USD"))
    with pytest.raises(ConfigInvalidError):
        build_cost_stage_report(HEADER, led.all_rows(tx), TASKS, [], T0, EXP)


@pytest.mark.parametrize(
    ("op", "term"),
    [
        ("llm.batch", "LLM"),
        ("tts.synthesize", "TTS"),
        ("stock.license", "footage"),
        ("music.license", "music"),
        ("video.generate", "ai_broll"),
        ("render.ffmpeg", "infra"),
        ("storage.bytes", "infra"),
        ("image.generate", "other"),
    ],
)
def test_terms(op: str, term: str) -> None:
    assert term_of(op) == term


def test_to_minor_rounds_half_up() -> None:
    assert to_minor(5_000, "INR", EXP) == 1  # 0.5 paise -> 1
    assert to_minor(4_999, "INR", EXP) == 0
    assert str(to_minor(1, "JPY", EXP)).startswith("REQUIRES REVIEW")


@pytest.mark.parametrize("exponent", [7, -1, 100, True])
def test_to_minor_refuses_an_exponent_outside_zero_to_six(exponent: int) -> None:
    """A wrong exponent must not print a figure 10x too large (7) or 0 (-1): it is marked for
    review like a missing entry."""
    out = to_minor(1_234_567, "INR", {"INR": exponent})
    assert isinstance(out, str)
    assert "outside 0..6" in out


def test_to_minor_valid_exponents() -> None:
    assert to_minor(1_234_567, "JPY", {"JPY": 0}) == 1
    assert to_minor(1_234_567, "KWD", {"KWD": 3}) == 1235
    assert to_minor(1_234_567, "XXX", {"XXX": 6}) == 1_234_567
