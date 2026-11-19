# ruff: noqa: E501, PT018
"""Second dry run: the REAL agent entry points behind the REAL driver. PLUMBING TEST - NOT QUALITY.

What runs for real: ``amw_orchestrator`` (``GraphRunner``, ``TaskExecutor``, every input builder,
``TaskIo``, ``ApprovalWorker``) on PostgreSQL tables, the real payload registry (the 36 names of the
global allow-list: nothing is registered by this test), ONE shared ``LocalDiskStorage``, and the real
entry points of agents 04, 05, 06 (both task types), 07 (both), 08, 09, 10 (render, subtitles, QC),
11, 16 (compliance gate, quality score), the S2 uniqueness check and agent_13 (file delivery). Each
agent runs over its OWN fakes (fake LLM answering with the agent's canned response shape, fake TTS,
descriptor-driven FFmpeg stubs, in-memory ports); the content is INVENTED (a tiny script about the
shortness of time, NOT book text, D12). No network, no paid call, no key.

What is NOT real: the BODY of ``agent_16.publication_authorisation`` (its approval, evidence and
human-score rows are the S7 service, which does not exist yet; its builder and input model are real),
the production implementations of the ports listed in ``docs/v4/DRYRUN2_REAL_AGENTS.md``.

The real chain now reaches ``DELIVERED`` (CCR-283: ``svc_s07.request_approval.*`` registered, PROVISIONAL).
What is still open is listed as strict xfails with their CCR reference (the Marathi run); every
other break found has a regression test or an entry in the report."""

import io
import json
import zipfile
from pathlib import Path

import pytest

from amw_core.enums import OutputStatus, TaskState
from amw_core.interfaces import TenantContext
from amw_core.interfaces.storage import BlobUri
from tests.dryrun.harness import Result, run_hybrid

pytestmark = pytest.mark.integration

ALL_REAL = frozenset(
    {
        "agent_04.research_pack",
        "agent_05.script_draft",
        "agent_06.claim_extraction",
        "agent_06.claim_verification",
        "agent_07.voice_synthesis",
        "agent_07.audio_master",
        "agent_09.shot_plan",
        "agent_08.asset_sourcing",
        "agent_10.render",
        "agent_10.subtitles",
        "agent_10.technical_qc",
        "agent_11.thumbnail_variants",
        "agent_16.compliance_gate",
        "agent_16.quality_score",
        "svc_s02.uniqueness_check",
    }
)
BEFORE_APPROVAL = (
    "s04_research", "s05_script", "s06_claims", "s06_verify", "s07_voice", "s07_master",
    "s09_plan", "s08_assets", "s06_chart", "s10_render", "s10_subs", "s10_qc", "s11_thumbs",
    "s02u_unique", "s16_comp", "s16_score",
)  # fmt: skip


@pytest.fixture(scope="module")
def chain(pg_dsn: str, tmp_path_factory: pytest.TempPathFactory) -> Result:
    return run_hybrid(pg_dsn, tmp_path_factory.mktemp("realchain"), real=set(ALL_REAL))


def test_the_real_chain_runs_every_stage_to_delivered(chain: Result) -> None:
    """Every one of the 19 stages COMPLETED through the driver (``a_final`` suspended, then
    resumed with the owner decision the desk reports), ``DELIVERED`` at the end."""
    r = chain.report
    assert r.status == "DELIVERED", r.detail
    assert r.order[: len(BEFORE_APPROVAL)] == list(BEFORE_APPROVAL)
    assert r.order[-2:] == ["s16_auth", "s13_deliver"]
    assert r.order.count("a_final") == 2  # suspended, then resumed with the owner decision
    for stage in (*BEFORE_APPROVAL, "a_final", "s16_auth", "s13_deliver"):
        assert r.stages[stage].state is TaskState.COMPLETED, stage
    # the approval output is the CCR-283 shape, validated by the registered model
    out = r.stages["a_final"].output
    assert out is not None and out.payload is not None
    assert out.payload.payload_schema == "svc_s07.request_approval.output"
    assert out.payload.data is not None and out.payload.data["state"] == "APPROVED"


def test_the_chain_waits_at_the_approval_until_the_owner_decides(
    pg_dsn: str, tmp_path: Path
) -> None:
    res = run_hybrid(pg_dsn, tmp_path, real=set(ALL_REAL), approve=False)
    r = res.report
    assert r.status == "AWAITING_APPROVAL", r.detail
    assert r.order == [*BEFORE_APPROVAL, "a_final"]
    assert r.stages["a_final"].state is not TaskState.COMPLETED
    for stage in ("s16_auth", "s13_deliver"):
        assert r.stages[stage].state is TaskState.PENDING
    assert len(res.rig.desk.opened) == 1  # the approval was requested once and nothing decided it


def test_every_real_entry_point_ran_and_returned_a_succeeded_output(chain: Result) -> None:
    ran = dict(chain.registry.real)
    assert set(ran) == set(ALL_REAL)
    for name, w in ran.items():
        assert w.calls >= 1, name
        assert w.last_output is not None and w.last_output.status is OutputStatus.SUCCEEDED, name
    assert (
        ran["agent_06.claim_verification"].calls == 2
    )  # s06_verify and s06_chart (no chart facts)
    # the real outputs validated against the REAL models of the global registry (not permissive ones)
    out = chain.report.stages["s05_script"].output
    assert out is not None and out.payload is not None
    assert out.payload.payload_schema == "agent_05.script_draft.output"


def test_tenant_ids_of_the_job_are_the_ones_every_real_agent_saw(chain: Result) -> None:
    for name, w in chain.registry.real.items():
        assert w.last_input is not None, name
        assert w.last_input.org_id == chain.job.org_id, name
        assert w.last_input.job_id == chain.job.job_id, name


def test_the_delivered_bundle_holds_what_the_real_agents_produced(chain: Result) -> None:
    """``s16_auth`` (builder and input model real, body a stand-in) and ``s13_deliver`` (real
    agent_13) ran through the driver: the bundle holds a video, subtitles, thumbnails, reports."""
    deliver = chain.report.stages["s13_deliver"].output
    assert deliver is not None and deliver.status is OutputStatus.SUCCEEDED
    assert deliver.payload is not None
    assert deliver.payload.payload_schema == "agent_13.file_delivery.output"
    assert [r.media_type for r in deliver.output_refs] == ["application/zip", "application/json"]
    zip_ref = deliver.output_refs[0]
    ctx = TenantContext(chain.job.org_id, "agent_13", None)  # type: ignore[arg-type]
    raw = b"".join(chain.rig.storage.get(ctx, BlobUri(zip_ref.uri), zip_ref.sha256))
    names = zipfile.ZipFile(io.BytesIO(raw)).namelist()
    assert any(n.endswith(".mp4") for n in names), names
    assert any(n.endswith(".srt") for n in names), names
    assert any(n.endswith(".png") for n in names), names


def test_agent_04_accepts_library_language_queries_for_a_marathi_video(
    pg_dsn: str, tmp_path: Path
) -> None:
    """CCR-289 (PROVISIONAL, implemented): ``library_languages`` = the languages of the channel's
    searchable sources, so an ``mr-IN`` video may query the ``en`` library (PL11)."""
    res = run_hybrid(
        pg_dsn, tmp_path, real={"agent_04.research_pack"}, language="mr-IN",
        options={"queries_language": "en"},
    )  # fmt: skip
    assert res.report.stages["s04_research"].state is TaskState.COMPLETED, res.report.detail
    worker = res.registry.real["agent_04.research_pack"]
    assert worker.last_output is not None and worker.last_output.status is OutputStatus.SUCCEEDED


def test_agent_16_gate_accepts_the_channel_category_as_the_channel_row_stores_it(
    pg_dsn: str, tmp_path: Path
) -> None:
    """CCR-288 (PROVISIONAL, implemented): the builder sends the row value (``philosophy``) the
    gate compares, so the gate runs (no ``INPUT_INVALID channel_category differs``). What the
    category MEANS stays fail closed: ``philosophy`` is not an explicit non-finance label, so the
    pack source of the dry run loads the finance pack and the verdict is BLOCKED (a finance
    channel never looks non-finance). Finance-ness comes from the rule-pack resolution of PR 102,
    which this change does not depend on."""
    res = run_hybrid(
        pg_dsn, tmp_path, real=set(ALL_REAL), options={"channel_category_label": "philosophy"}
    )
    gate = res.registry.real["agent_16.compliance_gate"]
    assert gate.calls >= 1 and gate.last_input is not None
    assert gate.last_input.payload.data["channel_category"] == "philosophy"  # type: ignore[index]
    out = gate.last_output
    assert out is not None and out.status is OutputStatus.SUCCEEDED, out and out.error
    assert out.payload is not None and out.payload.data is not None
    assert out.payload.data["verdict"] == "BLOCKED"  # finance pack loaded: fail closed
    assert {p["key"] for p in out.payload.data["packs"]} >= {"rp.finance_sebi_in"}


def test_the_default_job_sends_the_channel_row_value_and_the_gate_is_not_blocked(
    chain: Result,
) -> None:
    gate = chain.registry.real["agent_16.compliance_gate"]
    assert gate.last_input is not None
    assert gate.last_input.payload.data["channel_category"] == "non-finance"  # type: ignore[index]
    assert gate.last_output is not None and gate.last_output.payload is not None
    assert gate.last_output.payload.data is not None
    # NEEDS_HUMAN_REVIEW here is YTG-R5 (third-party permission unknown), not a finance rule
    assert gate.last_output.payload.data["verdict"] in {"ALLOWED", "NEEDS_HUMAN_REVIEW"}
    assert {p["key"] for p in gate.last_output.payload.data["packs"]} == {"rp.youtube_general"}


@pytest.mark.xfail(
    strict=True,
    reason="CCR-289 (remainder, PROPOSED; report break O6): the canned model responses of the real "
    "agents' fakes are English, so the Marathi (mr-IN) run of the whole real chain stops at "
    "s05_script (AGENT.QUALITY_REPEATED_FAILURE, a05.plan.lang: the language check refuses English "
    "text for an mr-IN job). agent_04 (CCR-289) passes; the Devanagari content of agents 05 to 16 "
    "has no fixtures",
)
def test_the_whole_real_chain_runs_for_a_marathi_job(pg_dsn: str, tmp_path: Path) -> None:
    res = run_hybrid(
        pg_dsn, tmp_path, real=set(ALL_REAL), language="mr-IN", options={"queries_language": "en"}
    )
    assert res.report.status == "DELIVERED", res.report.detail


def test_the_marathi_run_stops_where_the_report_says_it_stops(pg_dsn: str, tmp_path: Path) -> None:
    """The first break of the Marathi run, stated exactly (the xfail above says it must change)."""
    res = run_hybrid(
        pg_dsn, tmp_path, real=set(ALL_REAL), language="mr-IN", options={"queries_language": "en"}
    )
    assert res.report.status == "FAILED"
    assert res.report.order == ["s04_research", "s05_script"]
    assert res.report.stages["s04_research"].state is TaskState.COMPLETED
    failed = res.report.stages["s05_script"]
    assert failed.state is TaskState.FAILED and failed.output is not None
    assert failed.output.error is not None
    assert failed.output.error.code == "AGENT.QUALITY_REPEATED_FAILURE"
    assert "a05.plan.lang" in str(failed.output.error.details)


def test_no_book_text_and_no_finance_rule_pack_reach_any_real_agent(chain: Result) -> None:
    """D12 / D13: the job is a non-finance philosophy job; its inputs carry no finance pack."""
    for name, w in chain.registry.real.items():
        assert w.last_input is not None
        body = json.dumps(w.last_input.payload.data)
        assert "rp.finance_sebi_in" not in body, name
