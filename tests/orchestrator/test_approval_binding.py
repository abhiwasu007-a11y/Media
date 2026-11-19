# ruff: noqa: PT018
"""An approval authorises only the subject it was given for (CCR-296 PROVISIONAL, SAFETY): hash,
kind, id, org, approval state and CONFIRMED evidence are checked against the CURRENT render
(and script) by the builder of ``agent_16.publication_authorisation``."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from amw_core.errors import InputInvalidError
from amw_core.ids import OWNER_EVIDENCE, Prefix, new_id
from amw_core.owner_evidence_status import EvidenceSourceKind
from amw_core.storage.local import LocalDiskStorage
from amw_delivery.stage import DeliveryStage
from amw_orchestrator.approval_binding import ExpectedSubject, require_bound_approval
from amw_orchestrator.executor import ApprovalWorker, BuildContext
from amw_orchestrator.input_builders import BuilderTable
from amw_orchestrator.registry import job_graph
from tests.orchestrator.agent_schemas import agent_registry
from tests.orchestrator.builder_world import World, doc_ref, with_data
from tests.orchestrator.evidence_fake import FakeEvidenceStatuses
from tests.orchestrator.world import LONG, TestDesk, approval_output, build_rig

pytestmark = pytest.mark.unit

OTHER_SHA = "f" * 64


def _final(w: World) -> dict[str, Any]:
    out = w.up["a_final"].payload
    assert out is not None and out.data is not None
    return dict(out.data)


def _set_final(w: World, **changes: Any) -> None:
    w.up["a_final"] = with_data(w.up["a_final"], {**_final(w), **changes})


def _refused(w: World, text: str) -> None:
    with pytest.raises(InputInvalidError) as exc:
        BuilderTable().build(w.ctx("s16_auth"))
    assert text in str(exc.value.details), exc.value.details


def test_the_matching_approval_authorises() -> None:
    built = BuilderTable().build(World().ctx("s16_auth"))
    assert built.data["approval_id"].startswith("apr_")


def test_a_stale_render_hash_is_refused() -> None:
    w = World()
    _set_final(w, subject_sha256=OTHER_SHA)  # the approval is of an earlier render
    _refused(w, "subject hash differs")


def test_a_new_render_after_the_approval_is_refused() -> None:
    w = World()
    render = w.up["s10_render"]
    assert render.payload is not None and render.payload.data is not None
    data = dict(render.payload.data)
    data["render_ref"] = {**data["render_ref"], "sha256": OTHER_SHA}
    w.up["s10_render"] = with_data(render, data)
    _refused(w, "subject hash differs")


def test_evidence_of_another_subject_kind_is_refused() -> None:
    w = World()
    ev = w.evidence.record(w.job.org_id, "script", w.render_id)
    _set_final(w, evidence_ids=[ev])
    _refused(w, "another subject")


def test_evidence_of_another_job_s_render_is_refused() -> None:
    w = World()
    ev = w.evidence.record(w.job.org_id, "render", new_id(Prefix.RENDER))
    _set_final(w, evidence_ids=[ev])
    _refused(w, "another subject")


def test_evidence_of_another_org_is_refused() -> None:
    w = World()
    other = new_id(Prefix.ORGANISATION)
    ev = w.evidence.record(other, "render", w.render_id)
    _set_final(w, evidence_ids=[ev])
    _refused(w, "another org")


@pytest.mark.parametrize("state", ["PENDING", "REJECTED", "EXPIRED", "WITHDRAWN"])
def test_an_approval_that_is_not_approved_is_refused(state: str) -> None:
    w = World()
    _set_final(w, state=state)
    _refused(w, "not APPROVED")


def test_a_superseded_approval_and_its_unconfirmed_evidence_are_refused() -> None:
    w = World()
    _set_final(w, state="WITHDRAWN")  # replaced by a newer decision
    _refused(w, "not APPROVED")
    w2 = World()
    (ev,) = _final(w2)["evidence_ids"]
    w2.evidence.change(ev, evidence_state="VERIFIED")  # not (or no longer) CONFIRMED
    _refused(w2, "not CONFIRMED")


def test_missing_evidence_is_refused() -> None:
    w = World()
    _set_final(w, evidence_ids=[])
    _refused(w, "not a valid approval")  # the model demands the evidence
    w2 = World()
    _set_final(w2, evidence_ids=[str(OWNER_EVIDENCE.new())])  # an ID the store does not know
    _refused(w2, "not found")


def test_one_bad_evidence_row_refuses_even_beside_a_good_one() -> None:
    w = World()
    bad = w.evidence.record(w.job.org_id, "script", w.render_id)
    _set_final(w, evidence_ids=[*_final(w)["evidence_ids"], bad])
    _refused(w, "another subject")


def test_without_an_evidence_reader_nothing_is_authorised() -> None:
    w = World()
    ctx = replace(w.ctx("s16_auth"), evidence=None)
    with pytest.raises(InputInvalidError) as exc:
        BuilderTable().build(ctx)
    assert "no evidence reader" in str(exc.value.details)


def test_a_mac_invalid_or_not_owner_chat_row_is_refused() -> None:
    w = World()
    (ev,) = _final(w)["evidence_ids"]
    w.evidence.change(ev, mac_valid=False)
    _refused(w, "MAC")
    w2 = World()
    (ev2,) = _final(w2)["evidence_ids"]
    w2.evidence.change(ev2, recorded_from="SYSTEM")
    _refused(w2, "not CONFIRMED from the owner chat")


def test_a_wrong_approval_kind_is_refused() -> None:
    w = World()
    _set_final(w, approval_kind="SCRIPT")
    _refused(w, "approval kind differs")


def test_a_malformed_approval_is_refused() -> None:
    w = World()
    _set_final(w, approval_id="x")
    _refused(w, "not a valid approval")


def test_test_fixture_evidence_is_refused_in_a_real_run_and_real_evidence_is_accepted() -> None:
    w = World()
    ctx: BuildContext = replace(w.ctx("s16_auth"), real_run=True)
    with pytest.raises(InputInvalidError) as exc:
        BuilderTable().build(ctx)
    assert "TEST_FIXTURE" in str(exc.value.details)
    (ev,) = _final(w)["evidence_ids"]
    w.evidence.change(ev, source_kind=EvidenceSourceKind.REAL)
    assert BuilderTable().build(replace(w.ctx("s16_auth"), real_run=True)).data["approval_id"]


def test_the_default_context_is_a_real_run_with_no_reader() -> None:
    ctx = World().ctx("s16_auth")
    default = BuildContext(**{k: getattr(ctx, k) for k in (
        "job", "stage", "task_id", "iteration", "attempt_no", "idempotency_key",
        "resource_budget", "upstream", "upstream_task_ids", "services",
    )})  # fmt: skip
    assert default.real_run is True and default.evidence is None
    with pytest.raises(InputInvalidError):
        BuilderTable().build(default)


def _with_script_approval(w: World, *, script_sha: str | None = None) -> None:
    script = w.up["s05_script"].payload
    assert script is not None and script.data is not None
    sid = str(script.data["script_id"])
    sha = script_sha or str(script.data["script_document"]["sha256"])
    ev = w.evidence.record(w.job.org_id, "script", sid)
    w.add("a_script", "svc_s07.request_approval.output",
          approval_output(sha, kind="SCRIPT", evidence_ids=[ev]))  # fmt: skip


def test_a_script_approval_of_the_current_script_is_accepted() -> None:
    w = World()
    _with_script_approval(w)
    assert BuilderTable().build(w.ctx("s16_auth")).data["approval_id"]


def test_a_script_approval_of_an_older_script_is_refused() -> None:
    w = World()
    _with_script_approval(w, script_sha=OTHER_SHA)
    _refused(w, "subject hash differs")


def test_the_pure_check_returns_the_validated_approval() -> None:
    w = World()
    render = w.up["s10_render"].payload
    assert render is not None and render.data is not None
    got = require_bound_approval(
        _final(w),
        stage_id="a_final",
        approval_kind="FINAL_VIDEO",
        subject=ExpectedSubject("render", w.render_id, str(render.data["render_ref"]["sha256"])),
        org_id=w.job.org_id,
        evidence=w.evidence,
        real_run=False,
    )
    assert got.state == "APPROVED"


def test_the_fake_reader_unknown_id_is_none() -> None:
    assert FakeEvidenceStatuses().get(str(OWNER_EVIDENCE.new())) is None


# -- the whole chain through the driver ---------------------------------------------------------
def _run_to_decision(pg_dsn: str, tmp: Path, *, real_run: bool) -> Any:
    from amw_core.ids import Prefix
    from amw_orchestrator.executor import JobDocuments, RulePackDoc
    from tests.orchestrator.test_dryrun_builders import Registry, RuntimeFacts, StandIns, _Clock

    def factory(approval: ApprovalWorker, storage: LocalDiskStorage) -> Registry:
        return Registry(
            StandIns(storage), approval, DeliveryStage(storage, _Clock(), scratch_root=tmp)
        )

    rig = build_rig(
        pg_dsn, tmp / "blobs", registry_factory=factory, real_run=real_run,
        schemas=agent_registry(real_outputs=False), build_services=RuntimeFacts(), desk=TestDesk(),
    )  # fmt: skip
    base = rig.intake("non-finance")
    org = base.org_id
    docs = JobDocuments(
        brand_kit=doc_ref(org, "brand_kit.json"),
        compliance_profile=doc_ref(org, "profile.json"),
        rule_packs={
            "rp.youtube_general": RulePackDoc(new_id(Prefix.RULE_PACK), 1, doc_ref(org, "yt.json"))
        },
        voice_id=new_id(Prefix.VOICE),
        voice_dictionary=doc_ref(org, "dictionary.json"),
        uniqueness_template=doc_ref(org, "template.json"),
    )
    job = replace(base, documents=docs)
    graph = job_graph(LONG)
    report = rig.runner.run(job, graph, rig.runner.start(job, graph))
    assert report.status == "AWAITING_APPROVAL", report.detail
    (task,) = [r.task_id for r in report.stages.values() if r.stage_id == "a_final"]
    rig.desk.decisions.add(task)
    return rig.runner.run(job, graph, report)


def test_the_chain_with_test_desk_evidence_is_delivered_in_a_dry_run(
    pg_dsn: str, tmp_path: Path
) -> None:
    assert _run_to_decision(pg_dsn, tmp_path, real_run=False).status == "DELIVERED"


def test_the_same_chain_is_refused_at_the_authorisation_in_a_real_run(
    pg_dsn: str, tmp_path: Path
) -> None:
    report = _run_to_decision(pg_dsn, tmp_path, real_run=True)
    assert report.status != "DELIVERED"
    auth = report.stages["s16_auth"]
    assert auth.output is not None and auth.output.error is not None
    assert "TEST_FIXTURE" in str(auth.output.error.details)
    assert "s13_deliver" not in report.order
