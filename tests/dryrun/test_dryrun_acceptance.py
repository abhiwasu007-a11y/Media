# ruff: noqa: PT018, PT022
# mypy: disable-error-code="arg-type,attr-defined,unused-ignore,var-annotated,index,no-untyped-call,misc,union-attr"
# (throw-away dry-run fixtures feed fakes and dataset dicts into typed APIs)
"""3A-16 acceptance (CI-sized): the whole 3A graph on fakes through the real PostgreSQL job /
task / queue / budget / ledger / audit tables, real FFmpeg render and QC, S2's bundle.

PLUMBING TEST - NOT QUALITY. Needs ``AMW_TEST_DATABASE_URL`` (superuser of a scratch cluster)
and ffmpeg; skipped otherwise. Render size is ``tiny`` (640x360): a config difference only.
Market hours: the runner gets a TEST CALENDAR FIXTURE and Agent 10 a FIXED admission clock
(Saturday 22:00) so CI does not depend on the hour; the guards themselves run unchanged.
"""

import json
import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from agent_10_video_editor.config import Placement
from agent_10_video_editor.guard import LocalTime
from amw_core.contracts import TaskOutput, ValidationResult
from amw_core.enums import CheckKind, CheckVerdict
from amw_orchestrator.executor import StageCall
from tests.dryrun.cli import DryRunResult, _FixedCalendar, run_dryrun
from tests.dryrun.kit import PLUMBING

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not os.environ.get("AMW_TEST_DATABASE_URL"), reason="needs AMW_TEST_DATABASE_URL"
    ),
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg"),
]
TOPIC = "RSI divergence explained on historical charts"
EXPECTED_ORDER = [
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
    "a_final",
    "a_final",
    "s16_auth",
    "s13_deliver",
]
"""``a_final`` runs twice: park (T09 AWAITING_APPROVAL), then resume (T15) after the decision."""


class FixedNight:
    """TEST admission fixture for Agent 10's guard: Saturday 22:00 local, DEV placement."""

    def now_local(self) -> LocalTime:
        return LocalTime.parse("SAT", "22:00")

    def drain_flag(self) -> bool:
        return False

    def placement(self) -> Placement:
        return Placement.DEV


def _run(tmp: Path, **kw: Any) -> DryRunResult:
    return run_dryrun(
        topic_title=TOPIC,
        out=tmp,
        admin_dsn=os.environ["AMW_TEST_DATABASE_URL"],
        scale="tiny",
        calendar=_FixedCalendar(True),
        admission=FixedNight(),
        **kw,
    )


@pytest.fixture(scope="module")
def happy(tmp_path_factory: pytest.TempPathFactory) -> Iterator[DryRunResult]:
    yield _run(tmp_path_factory.mktemp("happy"))


def test_full_graph_delivers_with_every_gate_and_no_paid_call(happy: DryRunResult) -> None:
    assert happy.status == "DELIVERED", happy.detail
    assert happy.order == EXPECTED_ORDER  # deterministic graph order
    assert happy.paid_calls == 0 and happy.refused_providers == []
    assert happy.cost_rows > 0
    db = happy.extras["db"]
    assert db["job_state"] == "COMPLETED/DELIVERED"
    assert db["tasks_completed"] == db["tasks"] == 19
    assert db["audit_rows"] == db["state_transitions"] > 0
    assert db["cost_ledger_rows"] == happy.cost_rows


def test_bundle_files_labels_and_cost_rows(happy: DryRunResult) -> None:
    assert happy.bundle_dir is not None
    b = Path(happy.bundle_dir)
    for name in (
        "video_16x9.mp4",
        "video_9x16.mp4",
        "subtitles.srt",
        "qc_report.json",
        "qc_report.md",
        "cost_per_stage.csv",
        "cost_per_stage.json",
        "README.txt",
        "manifest.json",
    ):
        assert (b / name).is_file(), name
    assert list((b / "thumbnails").glob("*.png"))
    assert (b / "qc_report.md").read_text(encoding="utf-8").startswith(f"# {PLUMBING}")
    assert (b / "README.txt").read_text(encoding="utf-8").startswith(PLUMBING)
    report = json.loads((b / "qc_report.json").read_text(encoding="utf-8"))
    assert PLUMBING in json.dumps(report)
    cost = json.loads((b / "cost_per_stage.json").read_text(encoding="utf-8"))
    stages = {r["stage"] for r in cost["rows"]}
    assert {"s04_research", "s05_script", "s07_voice"} <= stages
    assert happy.zip_path is not None and Path(happy.zip_path).is_file()


class _FailOnce:
    """Wraps the real master executor: the first call reports a failed loudness gate naming
    ``s07_voice`` (a fixture fault), later calls are the real Agent 07 output."""

    def __init__(self, inner: Any, always: bool = False) -> None:
        self.inner, self.always, self.calls = inner, always, 0

    def execute(self, call: StageCall) -> TaskOutput:
        self.calls += 1
        out: TaskOutput = self.inner.execute(call)
        if self.calls == 1 or self.always:
            bad = ValidationResult(
                check_id="qc.audio.integrated_lufs",
                kind=CheckKind.DETERMINISTIC,
                verdict=CheckVerdict.FAIL,
                blocking=True,
                message="PLUMBING injected gate fault",
                gate=True,
                remedy_stage_id="s07_voice",
            )
            out = out.model_copy(update={"validation_results": (*out.validation_results, bad)})
        return out


def test_failing_gate_loops_through_its_remedy_stage(tmp_path: Path) -> None:
    from tests.dryrun import world as w

    original = w.Registry.__init__

    def patched(self: Any, *a: Any, **k: Any) -> None:
        original(self, *a, **k)
        self.overrides["s07_master"] = _FailOnce(self._by_type["agent_07.audio_master"])

    w.Registry.__init__ = patched  # type: ignore[method-assign]
    try:
        res = _run(tmp_path, shorts=False)
    finally:
        w.Registry.__init__ = original  # type: ignore[method-assign]
    assert res.status == "DELIVERED", res.detail
    assert res.revisions and res.revisions[0]["target"] == "s07_voice"
    assert "s07_voice#1" in res.order and "s07_master#1" in res.order


def test_revision_cap_ends_blocked_compliance(tmp_path: Path) -> None:
    from tests.dryrun import world as w

    original = w.Registry.__init__

    def patched(self: Any, *a: Any, **k: Any) -> None:
        original(self, *a, **k)
        self.overrides["s07_master"] = _FailOnce(
            self._by_type["agent_07.audio_master"], always=True
        )

    w.Registry.__init__ = patched  # type: ignore[method-assign]
    try:
        res = _run(tmp_path, shorts=False)
    finally:
        w.Registry.__init__ = original  # type: ignore[method-assign]
    assert res.status == "BLOCKED_COMPLIANCE"
    assert len(res.revisions) == 3  # max_revision_loops of the record
    assert res.extras["db"]["job_state"] == "COMPLETED/BLOCKED_COMPLIANCE"
    assert "s10_render" not in res.order and res.bundle_dir is None


def test_budget_breach_stops_hard_before_render(tmp_path: Path) -> None:
    """Owner caps USD 5 / video and USD 50 pilot (S4 config); fake price USD 1 per call and a
    USD 5 reservation per paid task: research spends USD 3, the next reservation would pass
    the per-video cap, so E1 refuses it (T05 AWAITING_BUDGET) and nothing else runs."""
    stage_micros = dict.fromkeys(
        (
            "agent_04.research_pack",
            "agent_05.script_draft",
            "agent_06.claim_extraction",
            "agent_06.claim_verification",
            "agent_07.voice_synthesis",
        ),
        5_000_000,
    )
    res = _run(tmp_path, shorts=False, fake_micros_per_call=1_000_000, stage_micros=stage_micros)
    assert res.status == "AWAITING_BUDGET", res.detail
    assert res.order == ["s04_research"]
    assert res.paid_calls == 0 and res.bundle_dir is None
    assert res.extras["db"]["job_state"].startswith("CHECKPOINTED")
