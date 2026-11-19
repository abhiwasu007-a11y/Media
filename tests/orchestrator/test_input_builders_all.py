# ruff: noqa: PT018
"""PASS6-B1: every 3A input builder, against the agent's OWN input model and ``amw.task_input``.

The payload models come from ``agent_schemas`` (a test registry; the global allow-list is empty
until the payload-registration lane merges). The upstream outputs are hand-made (builder_world)."""

import ast
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from amw_core.contracts import TaskInput
from amw_core.errors import AmwError, InputInvalidError, MissingDependencyError
from amw_core.ids import ATTEMPT
from amw_orchestrator import input_builders
from amw_orchestrator.executor import BuildContext, ChannelCategory, JobDocuments, TaskExecutor
from amw_orchestrator.input_builders import BuilderTable
from amw_orchestrator.registry import job_graph
from tests.orchestrator.agent_schemas import agent_registry
from tests.orchestrator.builder_world import World, data_of, finance_job, job, with_data
from tests.orchestrator.test_executor import _Worker
from tests.orchestrator.world import LONG

pytestmark = pytest.mark.unit

# stage -> task type of every stage of the long-form graph that runs in 3A (a_script, s12_meta
# are disabled by default)
STAGES = [
    "s05_script", "s06_claims", "s06_verify", "s07_voice", "s07_master", "s09_plan", "s08_assets",
    "s06_chart", "s10_render", "s10_subs", "s10_qc", "s11_thumbs", "s02u_unique", "s16_comp",
    "s16_score", "a_final", "s16_auth", "s13_deliver",
]  # fmt: skip


class _Reg:
    def __init__(self, table: BuilderTable) -> None:
        self.t, self.w = table, _Worker()

    def worker_for(self, stage: object) -> _Worker:
        return self.w

    def builder_for(self, stage: object) -> BuilderTable:
        return self.t


def _prepare(ctx: BuildContext) -> TaskInput:
    ex = TaskExecutor(_Reg(BuilderTable()), schemas=agent_registry())
    prepared = ex.prepare(ctx, str(ATTEMPT.new()))  # validates payload through the registry
    return prepared.task_input


def _data(ctx: BuildContext) -> dict[str, Any]:
    data = _prepare(ctx).payload.data
    assert data is not None
    return data


@pytest.mark.parametrize("stage_id", STAGES)
def test_every_builder_validates_against_the_agents_own_model(stage_id: str) -> None:
    w = World()
    ti = _prepare(w.ctx(stage_id))
    assert ti.agent_id in {"agent_05", "agent_06", "agent_07", "agent_08", "agent_09", "agent_10",
                           "agent_11", "agent_16", "agent_13", "svc_s02", "svc_s07"}  # fmt: skip
    assert ti.payload.payload_schema.endswith(".input")


def test_every_running_task_type_has_a_builder() -> None:
    types = {s.task_type for s in job_graph(LONG)}
    missing = types - BuilderTable().task_types()
    assert missing == set() and "agent_12.metadata" not in BuilderTable().task_types()
    # Agent 12 is not built; its stage is disabled by default and is not in the running graph


def test_language_is_the_job_language_byte_for_byte() -> None:
    w = World()
    for stage in ("s05_script", "s06_claims", "s07_voice", "s10_render", "s10_subs"):
        data = _data(w.ctx(stage))
        assert data["language"] == w.job.language == "mr-IN"


def test_non_finance_has_no_finance_pack_and_finance_has_it() -> None:
    nf = World(job())
    assert _data(nf.ctx("s05_script"))["active_rule_packs"] == ["rp.youtube_general"]
    fw = World(finance_job())
    data = _data(fw.ctx("s05_script"))
    assert data["active_rule_packs"] == [
        "rp.youtube_general",
        "rp.finance_sebi_in",
    ]
    assert data["channel_category"] == "finance"
    # a non-finance job never gets the disclaimer template; a finance job does
    nf_refs = {r.purpose.value for r in _prepare(nf.ctx("s05_script")).context_refs}
    fw_refs = {r.purpose.value for r in _prepare(fw.ctx("s05_script")).context_refs}
    assert "TEMPLATE" not in nf_refs and "TEMPLATE" in fw_refs


def test_unknown_category_is_finance_and_needs_the_finance_pack_document() -> None:
    base = job(ChannelCategory.FINANCE)  # the fail-closed default; its documents lack the pack
    w = World(base)
    with pytest.raises(MissingDependencyError):
        _prepare(w.ctx("s05_script"))


def test_extraction_segments_and_citations_come_from_the_script_document() -> None:
    data = _data(World().ctx("s06_claims"))
    assert data is not None
    first, second = data["segments"]
    assert first["citation_refs"] == ["cit_0", "cit_1"] and "citation_refs" not in second
    assert first["visual_refs"] == [] and data["chart_data_refs"] == []
    assert [c["citation_ref"] for c in data["available_citations"]] == ["cit_1", "cit_0"]
    assert data["our_method_release_approved"] is False


def test_verification_reads_claim_ids_and_hashes_the_claims() -> None:
    w = World()
    data = _data(w.ctx("s06_verify"))
    assert data["verify_mode"] == "EVIDENCE"
    (claim,) = data["claims"]
    assert claim["claim_id"].startswith("clm_") and claim["extraction_verdict"] == "ALLOWED"
    from amw_orchestrator.input_builders.common import claims_sha256

    assert data["claims_sha256"] == claims_sha256(data["claims"])
    chart = _data(w.ctx("s06_chart"))
    assert chart["verify_mode"] == "CHART_FACTS" and chart["claims"] == []


def test_voice_refuses_when_the_verified_text_is_not_the_voiced_text() -> None:
    w = World()
    ver = w.up["s06_verify"]
    bad = with_data(ver, {**data_of(ver), "script_sha256": "b" * 64})
    w.up["s06_verify"] = bad
    with pytest.raises(InputInvalidError):
        BuilderTable().build(w.ctx("s07_voice"))


def test_master_takes_scene_pauses_only() -> None:
    data = _data(World().ctx("s07_master"))
    assert data["deliberate_pause_spans"] == [{"start_ms": 100, "end_ms": 900}]


def test_asset_plan_ref_is_the_plan_ref_unchanged() -> None:
    w = World()
    data = _data(w.ctx("s08_assets"))
    assert data["shot_plan_ref"] == data_of(w.up["s09_plan"])["plan_ref"]
    assert data["script_stage_id"] == "s05_script" and data["aspect_ratios"] == ["16:9"]


def test_agent_10_refs_one_per_schema_and_payload_documents_are_copied_verbatim() -> None:
    w = World()
    ti = _prepare(w.ctx("s10_qc"))
    schemas = [r.schema_ for r in ti.context_refs]
    assert len(schemas) == len(set(schemas)) == 8
    assert w.svc.copies >= 3  # audio master, render output, subtitles output (CCR-279)


def test_authorisation_binds_gate_and_score_tasks_and_the_approval() -> None:
    w = World()
    data = _data(w.ctx("s16_auth"))
    assert data is not None
    assert (
        data["gate_task_id"] == w.task_ids["s16_comp"]
        and data["score_task_id"] == w.task_ids["s16_score"]
    )
    assert data["requested_action"] == "DELIVERY" and data["intended_publish_date_utc"] is None


def test_authorisation_refuses_an_approval_that_is_not_approved() -> None:
    w = World()
    w.up["a_final"] = with_data(w.up["a_final"], {"state": "REJECTED", "approval_id": "x"})
    with pytest.raises(InputInvalidError):
        BuilderTable().build(w.ctx("s16_auth"))


def test_delivery_bundle_is_built_from_stored_outputs_and_runtime_facts() -> None:
    data = _data(World().ctx("s13_deliver"))
    assert data["banner"] == "PLUMBING TEST - NOT QUALITY"
    assert data["chosen_thumbnail_id"] == "v1" and data["gates"] == []
    assert data["compliance"]["authorised_for_delivery"] is True


def test_missing_documents_and_services_are_typed_refusals() -> None:
    w = World()
    bare = replace(w.job, documents=JobDocuments())
    for stage in ("s09_plan", "s07_voice", "s08_assets", "s05_script"):
        ctx = replace(w.ctx(stage), job=bare)
        with pytest.raises(MissingDependencyError):
            BuilderTable().build(ctx)
    with pytest.raises(MissingDependencyError):  # no services: cannot read the script document
        BuilderTable().build(replace(w.ctx("s06_claims"), services=None))
    with pytest.raises(MissingDependencyError):  # upstream missing
        BuilderTable().build(replace(w.ctx("s07_master"), upstream={}))


def test_revision_of_script_needs_prior_script_and_feedback() -> None:
    w = World()
    with pytest.raises(AmwError):
        BuilderTable().build(w.ctx("s05_script", iteration=1))  # no prior output
    ctx = w.ctx("s05_script", iteration=1, prior_output=w.up["s05_script"])
    with pytest.raises(InputInvalidError):  # no feedback item
        BuilderTable().build(replace(ctx, revision_source_stage_id="s16_comp"))
    from tests.orchestrator.builder_world import _result

    ctx = replace(
        ctx, revision_source_stage_id="s16_comp", revision_feedback=(_result("c.x", "FAIL"),)
    )
    data = _data(ctx)
    assert data["revision"]["feedback"][0]["source"] == "COMPLIANCE"
    assert data["revision"]["prior_script"]["uri"].endswith("script.json")


def test_agent_04_revision_stays_refused_until_the_gap_mapping_is_defined() -> None:
    w = World()
    stage = next(s for s in job_graph(LONG) if s.stage_id == "s04_research")
    with pytest.raises(InputInvalidError):
        BuilderTable().build(replace(w.ctx("s05_script", iteration=1), stage=stage))


def test_no_builder_imports_an_agent_package() -> None:
    root = Path(input_builders.__file__).parent
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            assert not any(n.startswith(("agent_", "amw_delivery")) for n in names), path.name
