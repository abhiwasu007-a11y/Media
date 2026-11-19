# ruff: noqa: PT018
"""The real ``GraphRunner`` through the real driver on the real PostgreSQL tables, fake workers:
a 3A skeleton run for a NON-finance job (philosophy sample, D13) from J01 to DELIVERED.

PLUMBING TEST - NOT QUALITY. Needs ``AMW_TEST_DATABASE_URL`` (the suite skips without it)."""

from pathlib import Path

import pytest

from amw_core.errors import ConfigInvalidError, InputInvalidError
from amw_orchestrator.registry import job_graph
from amw_orchestrator.services import intake
from tests.orchestrator.world import LONG, PAID, build_rig, db_rows

pytestmark = pytest.mark.integration

EXPECTED = [
    "s04_research",
    "s05_script",
    "s06_claims",
    "s06_verify",
    "s07_voice",
    "s07_master",
    "s09_plan",
    "s08_assets",
    "s06_chart",
    "s10_render",
    "s10_subs",
    "s10_qc",
    "s11_thumbs",
    "s02u_unique",
    "s16_comp",
    "s16_score",
    "a_final",  # parks (T09)
    "a_final",  # resumes (T15) after the decision
    "s16_auth",
    "s13_deliver",
]


def test_non_finance_skeleton_runs_end_to_end(pg_dsn: str, tmp_path: Path) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    job = rig.intake("non-finance")
    assert not job.finance_rules_apply
    graph = rig.graph
    report = rig.runner.start(job, graph)
    report = rig.runner.run(job, graph, report)
    assert report.status == "AWAITING_APPROVAL"
    (task,) = [r.task_id for r in report.stages.values() if r.stage_id == "a_final"]
    rig.desk.decisions.add(task)
    report = rig.runner.run(job, graph, report)
    assert report.status == "DELIVERED", report.detail
    assert report.order == EXPECTED
    assert rig.world.seen_finance and not any(rig.world.seen_finance)
    rows = db_rows(
        pg_dsn,
        "SELECT stage_id, iteration, state, input_ref IS NOT NULL, output_ref IS NOT NULL"
        " FROM tasks WHERE job_id = (SELECT id FROM jobs ORDER BY created_at DESC LIMIT 1)"
        " ORDER BY stage_id",
    )
    assert len(rows) == 19 and all(r[0] for r in rows)  # every task carries its stage_id
    assert {r[2] for r in rows} == {"COMPLETED"} and all(r[3] and r[4] for r in rows)
    assert rig.meter.refused == [] and rig.meter.calls  # only fake providers, every call metered
    assert rig.world.calls.count(("s05_script", 0, 1)) == 1


def test_default_category_is_finance_and_unknown_fails_closed(pg_dsn: str, tmp_path: Path) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    assert rig.intake("").finance_rules_apply  # empty (channels.category is NOT NULL, 04)
    assert rig.intake("philosophy", title="Seneca two").finance_rules_apply  # unknown label


def test_intake_refuses_a_job_without_project(pg_dsn: str, tmp_path: Path) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    topic = rig.intake().owner_topic
    with pytest.raises(InputInvalidError) as exc:
        intake(
            rig.tenancy,
            rig.jobs,
            org_id=rig.seed.org_id,
            workspace_id=rig.seed.workspace_id,
            project_id=None,
            channel_id=rig.seed.channel_id,
            topic=topic,
            production_type=LONG,
            version=2,
            correlation_id="cor_x",
        )
    assert exc.value.details["violations"][0].keyword == "PROJECT_MISSING"


def test_unconfigured_paid_stage_refuses_the_job_at_j02(pg_dsn: str, tmp_path: Path) -> None:
    paid = {k: v for k, v in PAID.items() if k != "agent_09.shot_plan"}
    rig = build_rig(pg_dsn, tmp_path, paid=paid)
    job = rig.intake()
    with pytest.raises(ConfigInvalidError) as exc:
        rig.runner.start(job, job_graph(LONG))
    assert exc.value.details["violations"][0].path == "/llm/agent_09.shot_plan/cost_budget_micros"
    state = db_rows(
        pg_dsn, "SELECT state FROM jobs WHERE id::text IS NOT NULL ORDER BY created_at DESC LIMIT 1"
    )
    assert state[0][0] == "FAILED"
    assert not db_rows(
        pg_dsn,
        "SELECT 1 FROM tasks WHERE job_id = (SELECT id FROM jobs ORDER BY created_at DESC LIMIT 1)",
    )


def test_missing_per_video_budget_refuses_the_job(pg_dsn: str, tmp_path: Path) -> None:
    rig = build_rig(pg_dsn, tmp_path, per_video_budget=False)
    job = rig.intake()
    with pytest.raises(ConfigInvalidError) as exc:
        rig.runner.start(job, job_graph(LONG))
    assert exc.value.details["violations"][0].keyword == "PER_VIDEO_BUDGET_MISSING"


def test_intake_keeps_the_channel_row_value_beside_the_resolved_category(
    pg_dsn: str, tmp_path: Path
) -> None:
    """CCR-288 PROVISIONAL: ``JobFacts.channel_category_row`` is the value as given (what the gate
    compares with the row); the resolved category is fail closed and never taken from it."""
    rig = build_rig(pg_dsn, tmp_path / "blobs")
    named = rig.intake("philosophy", title="Row value kept")
    assert named.channel_category_row == "philosophy"
    assert named.finance_rules_apply is True  # unknown free text = finance (CCR-273 item 4)
    explicit = rig.intake("non-finance", title="Explicit label")
    assert explicit.channel_category_row == "non-finance"
    assert explicit.finance_rules_apply is False
    unset = rig.intake(None, title="No category")
    assert unset.channel_category_row is None and unset.finance_rules_apply is True
    blank = rig.intake("  ", title="Blank category")
    assert blank.channel_category_row is None and blank.finance_rules_apply is True
