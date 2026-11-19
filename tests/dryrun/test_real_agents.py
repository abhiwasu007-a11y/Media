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

The first failure of the real chain is ``a_final``: ``svc_s07.request_approval.*`` is not in the
payload registry (CCR-283, PROPOSED). The tests state that failure exactly and mark the chain's
``DELIVERED`` as a strict xfail linked to it; every other break found has a regression test or an
entry in the report."""

import io
import json
import zipfile
from pathlib import Path

import pytest

from amw_core.enums import OutputStatus, TaskState
from amw_core.ids import Prefix, new_id
from amw_core.interfaces import TenantContext
from amw_core.interfaces.storage import BlobUri
from tests.dryrun.harness import Result, run_hybrid, run_tail

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


def test_the_real_chain_gets_to_the_approval_stage_and_stops_there(chain: Result) -> None:
    """How far the real chain gets TODAY: 16 stages (every real agent) COMPLETED, then ``a_final``
    fails because the payload registry has no ``svc_s07.request_approval`` schema (CCR-283)."""
    r = chain.report
    assert r.status == "FAILED"
    assert r.detail == "a_final: PERMANENT.SCHEMA_INVALID: unknown payload schema"
    assert r.order == [*BEFORE_APPROVAL, "a_final"]
    for stage in BEFORE_APPROVAL:
        assert r.stages[stage].state is TaskState.COMPLETED, stage
    assert r.stages["a_final"].state is TaskState.FAILED
    for stage in ("s16_auth", "s13_deliver"):
        assert r.stages[stage].state is TaskState.PENDING


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


def test_the_tail_behind_the_approval_builds_and_delivers(chain: Result) -> None:
    """``s16_auth`` (builder and input model real, body a stand-in) and ``s13_deliver`` (real
    agent_13) over the real upstream outputs, run through the driver's own executor with an APPROVED
    ``a_final`` output made by the real ``ApprovalWorker`` (no ``svc_s07`` schema is registered)."""
    tail = run_tail(chain, str(new_id(Prefix.APPROVAL)))
    assert set(tail) == {"s16_auth", "s13_deliver"}, tail
    for stage, out in tail.items():
        assert not isinstance(out, Exception), (stage, repr(out))
        assert out.status is OutputStatus.SUCCEEDED, (stage, out.error)
    deliver = tail["s13_deliver"]
    assert deliver.payload is not None
    assert deliver.payload.payload_schema == "agent_13.file_delivery.output"
    assert [r.media_type for r in deliver.output_refs] == ["application/zip", "application/json"]
    # the bundle really holds what the real agents produced (a video, subtitles, thumbnails, reports)
    zip_ref = deliver.output_refs[0]
    ctx = TenantContext(chain.job.org_id, "agent_13", None)  # type: ignore[arg-type]
    raw = b"".join(chain.rig.storage.get(ctx, BlobUri(zip_ref.uri), zip_ref.sha256))
    names = zipfile.ZipFile(io.BytesIO(raw)).namelist()
    assert any(n.endswith(".mp4") for n in names), names
    assert any(n.endswith(".srt") for n in names), names
    assert any(n.endswith(".png") for n in names), names


@pytest.mark.xfail(
    strict=True,
    reason="CCR-283 (PROPOSED): svc_s07.request_approval.input/.output are not registered in the "
    "payload registry (36 names), so the driver fails a_final with PERMANENT.SCHEMA_INVALID "
    "'unknown payload schema'; no schema is invented here",
)
def test_the_real_chain_reaches_delivered(chain: Result) -> None:
    assert chain.report.status == "AWAITING_APPROVAL"  # what the driver should reach at a_final
    chain.rig.desk.decisions.add(chain.report.stages["a_final"].task_id)
    report = chain.rig.runner.run(chain.job, chain.rig.graph, chain.report)
    assert report.status == "DELIVERED", report.detail


@pytest.mark.xfail(
    strict=True,
    reason="CCR-289 (PROPOSED): agent_04 hardcodes library_languages=() in its plan input, so PL11 "
    "refuses queries in the language of an English library for a non-English video (mr-IN job, "
    "English queries): OUTPUT_SCHEMA_INVALID 'plan failed the deterministic checks after the repair'",
)
def test_agent_04_accepts_library_language_queries_for_a_marathi_video(
    pg_dsn: str, tmp_path: Path
) -> None:
    res = run_hybrid(
        pg_dsn, tmp_path, real={"agent_04.research_pack"}, language="mr-IN",
        options={"queries_language": "en"},
    )  # fmt: skip
    assert res.report.stages["s04_research"].state is TaskState.COMPLETED, res.report.detail


@pytest.mark.xfail(
    strict=True,
    reason="CCR-288 (PROPOSED): the value of channels.category is not defined: the builders send the "
    "normalised label (finance / non_finance, CCR-273) and agent_16 compares it for equality with "
    "channels.category as stored (the seeded philosophy channel stores 'philosophy'): "
    "INPUT_INVALID 'channel_category differs from channels.category'",
)
def test_agent_16_gate_accepts_the_channel_category_as_the_channel_row_stores_it(
    pg_dsn: str, tmp_path: Path
) -> None:
    res = run_hybrid(
        pg_dsn, tmp_path, real=set(ALL_REAL), options={"channel_category_label": "philosophy"}
    )
    assert res.report.stages["s16_comp"].state is TaskState.COMPLETED, res.report.detail


def test_no_book_text_and_no_finance_rule_pack_reach_any_real_agent(chain: Result) -> None:
    """D12 / D13: the job is a non-finance philosophy job; its inputs carry no finance pack."""
    for name, w in chain.registry.real.items():
        assert w.last_input is not None
        body = json.dumps(w.last_input.payload.data)
        assert "rp.finance_sebi_in" not in body, name
