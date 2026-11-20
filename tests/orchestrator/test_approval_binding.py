# ruff: noqa: PT018
"""An approval authorises only the subject it was given for (CCR-296 PROVISIONAL, SAFETY): hash,
kind, id, org, approval state and CONFIRMED evidence are checked against the CURRENT render
(and script) by the builder of ``agent_16.publication_authorisation``."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from amw_core.errors import InputInvalidError
from amw_core.ids import APPROVAL, OWNER_EVIDENCE, Prefix, new_id
from amw_core.owner_evidence_approvals import (
    APPROVAL_DECISION,
    ApprovalEvidencePort,
    PgApprovalEvidencePort,
)
from amw_core.owner_evidence_status import EvidenceSourceKind, EvidenceStatus
from amw_core.storage.local import LocalDiskStorage
from amw_delivery.stage import DeliveryStage
from amw_orchestrator.approval_binding import ExpectedSubject, require_bound_approval
from amw_orchestrator.executor import ApprovalWorker, BuildContext, JobFacts
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


def _swap_evidence(w: World, org: str | None, kind: str, subject_id: str, **kw: Any) -> None:
    """The final approval now names evidence of the same approval but of another subject/org."""
    data = _final(w)
    ev = w.evidence.record(
        org or w.job.org_id, kind, subject_id,
        approval_id=data["approval_id"], subject_sha256=data["subject_sha256"], **kw,
    )  # fmt: skip
    _set_final(w, evidence_ids=[ev])


def test_evidence_of_another_subject_kind_is_refused() -> None:
    w = World()
    _swap_evidence(w, None, "script", w.render_id)
    _refused(w, "another subject")


def test_evidence_of_another_job_s_render_is_refused() -> None:
    w = World()
    _swap_evidence(w, None, "render", new_id(Prefix.RENDER))
    _refused(w, "another subject")


def test_evidence_of_another_org_is_refused() -> None:
    w = World()
    _swap_evidence(w, new_id(Prefix.ORGANISATION), "render", w.render_id)
    _refused(w, "another org")


def test_evidence_of_another_approval_with_the_same_subject_is_refused() -> None:
    """The earlier open gap: same subject kind and ID, but the evidence decided ANOTHER approval."""
    w = World()
    (ev,) = _final(w)["evidence_ids"]
    w.evidence.change(ev, approval_id=str(APPROVAL.new()))
    _refused(w, "another approval")


def test_rejecting_evidence_is_refused_even_under_an_approved_output() -> None:
    for decision in ("REJECTED", "CHANGES_REQUESTED"):
        w = World()
        (ev,) = _final(w)["evidence_ids"]
        w.evidence.change(ev, decision=decision)
        _refused(w, "not APPROVED")


def test_evidence_of_a_stale_subject_hash_is_refused() -> None:
    w = World()
    (ev,) = _final(w)["evidence_ids"]
    w.evidence.change(ev, subject_sha256=OTHER_SHA)
    _refused(w, "another subject hash")


def test_a_base_evidence_status_or_wrong_kind_is_refused() -> None:
    w = World()
    (ev,) = _final(w)["evidence_ids"]
    row = w.evidence.rows[ev]
    base = EvidenceStatus(
        evidence_id=row.evidence_id, evidence_state="CONFIRMED", recorded_from=row.recorded_from,
        org_id=row.org_id, kind=APPROVAL_DECISION, subject_kind=row.subject_kind,
        subject_id=row.subject_id, subject=None, source_kind=row.source_kind, mac_valid=True,
    )  # fmt: skip
    w.evidence.rows[ev] = base  # type: ignore[assignment]  # a port that answers the base type
    _refused(w, "not an approval-decision status")
    for kind in (None, "PROVIDER_LIMIT", "FIN_R10_NOT_SEBI_REGISTERED", "SOMETHING_NEW"):
        w2 = World()
        (ev2,) = _final(w2)["evidence_ids"]
        w2.evidence.change(ev2, kind=kind)
        _refused(w2, "not an approval decision")


def test_the_port_is_asked_for_this_approval_and_the_current_hash() -> None:
    w = World()
    BuilderTable().build(w.ctx("s16_auth"))
    final = _final(w)
    assert w.evidence.asked[-1] == (final["approval_id"], final["subject_sha256"])


def test_evidence_the_approval_does_not_name_is_refused() -> None:
    w = World()
    (ev,) = _final(w)["evidence_ids"]
    _set_final(w, evidence_ids=[str(OWNER_EVIDENCE.new())])
    assert ev not in _final(w)["evidence_ids"]
    _refused(w, "not one the approval names")


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
    _set_final(w2, approval_id=str(APPROVAL.new()))  # an approval the port does not know
    _refused(w2, "no approved evidence")


def test_without_an_evidence_reader_nothing_is_authorised() -> None:
    w = World()
    ctx = replace(w.ctx("s16_auth"), evidence=None)
    with pytest.raises(InputInvalidError) as exc:
        BuilderTable().build(ctx)
    assert "no evidence port" in str(exc.value.details)


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
    w.evidence.change(ev, source_kind="OTHER")  # neither REAL nor TEST_FIXTURE
    with pytest.raises(InputInvalidError):
        BuilderTable().build(replace(w.ctx("s16_auth"), real_run=True))


def test_the_default_context_is_a_real_run_with_no_port() -> None:
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
    apr = str(APPROVAL.new())
    ev = w.evidence.record(w.job.org_id, "script", sid, approval_id=apr, subject_sha256=sha)
    w.add("a_script", "svc_s07.request_approval.output",
          approval_output(sha, kind="SCRIPT", approval_id=apr, evidence_ids=[ev]))  # fmt: skip


def test_a_script_approval_of_the_current_script_is_accepted() -> None:
    w = World()
    _with_script_approval(w)
    assert BuilderTable().build(w.ctx("s16_auth")).data["approval_id"]


_PAID = ("s07_voice", "s09_plan")


def _script_data(w: World) -> dict[str, Any]:
    out = w.up["a_script"].payload
    assert out is not None and out.data is not None
    return dict(out.data)


@pytest.mark.parametrize("stage", _PAID)
def test_the_paid_stage_builders_accept_the_current_script_approval(stage: str) -> None:
    w = World()
    _with_script_approval(w)
    built = BuilderTable().build(w.ctx(stage))
    assert built.data is not None


def _script_approval_world(**ev: Any) -> World:
    w = World()
    _with_script_approval(w)
    (e,) = _script_data(w)["evidence_ids"]
    if ev:
        w.evidence.change(e, **ev)
    return w


@pytest.mark.parametrize("stage", _PAID)
@pytest.mark.parametrize(
    ("change", "text"),
    [
        ({"evidence_state": "VERIFIED"}, "not CONFIRMED"),
        ({"source_kind": EvidenceSourceKind.TEST_FIXTURE}, "TEST_FIXTURE"),
        ({"subject_kind": "render"}, "another subject"),
        ({"subject_id": "scr_other"}, "another subject"),
        ({"mac_valid": False}, "MAC"),
        ({"kind": "PROVIDER_LIMIT"}, "not an approval decision"),
        ({"approval_id": "apr_other"}, "another approval"),
        ({"decision": "REJECTED"}, "not APPROVED"),
        ({"subject_sha256": "e" * 64}, "another subject hash"),
    ],
)
def test_a_bad_script_approval_is_refused_by_the_paid_stage_builder_in_a_real_run(
    stage: str, change: dict[str, Any], text: str
) -> None:
    w = _script_approval_world(**{"source_kind": EvidenceSourceKind.REAL, **change})
    with pytest.raises(InputInvalidError) as exc:
        BuilderTable().build(w.ctx(stage, real_run=True))
    assert text in str(exc.value.details), exc.value.details


@pytest.mark.parametrize("stage", _PAID)
def test_a_stale_hash_or_other_kind_script_approval_is_refused_before_paid_stages(
    stage: str,
) -> None:
    w = World()
    _with_script_approval(w, script_sha=OTHER_SHA)
    with pytest.raises(InputInvalidError) as exc:
        BuilderTable().build(w.ctx(stage))
    assert "subject hash differs" in str(exc.value.details)
    w2 = World()
    _with_script_approval(w2)
    data = _script_data(w2)
    w2.up["a_script"] = with_data(w2.up["a_script"], {**data, "approval_kind": "FINAL_VIDEO"})
    with pytest.raises(InputInvalidError) as exc2:
        BuilderTable().build(w2.ctx(stage))
    assert "approval kind differs" in str(exc2.value.details)


@pytest.mark.parametrize("stage", _PAID)
def test_a_script_approval_that_is_not_approved_or_has_no_port_is_refused(stage: str) -> None:
    w = World()
    _with_script_approval(w)
    data = _script_data(w)
    w.up["a_script"] = with_data(w.up["a_script"], {**data, "state": "PENDING"})
    with pytest.raises(InputInvalidError):
        BuilderTable().build(w.ctx(stage))
    w2 = World()
    _with_script_approval(w2)
    with pytest.raises(InputInvalidError) as exc:
        BuilderTable().build(replace(w2.ctx(stage), evidence=None))
    assert "no evidence port" in str(exc.value.details)


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


def test_the_fake_port_unknown_approval_is_none() -> None:
    assert FakeEvidenceStatuses().approved(str(APPROVAL.new()), "a" * 64) is None


def test_the_fake_and_the_postgresql_adapter_both_are_the_port() -> None:
    assert isinstance(FakeEvidenceStatuses(), ApprovalEvidencePort)
    assert issubclass(PgApprovalEvidencePort, ApprovalEvidencePort)


# -- the whole chain through the driver ---------------------------------------------------------
def _run_to_decision(
    pg_dsn: str, tmp: Path, *, real_run: bool, script_approval: bool = False, evidence: Any = ...
) -> tuple[Any, Any]:
    """The run report and the stand-ins (``seen``: the stages that really started)."""
    from amw_core.ids import Prefix
    from amw_orchestrator.executor import JobDocuments, RulePackDoc
    from tests.orchestrator.test_dryrun_builders import Registry, RuntimeFacts, StandIns, _Clock

    stand: list[Any] = []

    def factory(approval: ApprovalWorker, storage: LocalDiskStorage) -> Registry:
        stand.append(StandIns(storage))
        return Registry(stand[0], approval, DeliveryStage(storage, _Clock(), scratch_root=tmp))

    rig = build_rig(
        pg_dsn, tmp / "blobs", registry_factory=factory, real_run=real_run,
        schemas=agent_registry(real_outputs=False), build_services=RuntimeFacts(), desk=TestDesk(),
        evidence=evidence,
    )  # fmt: skip
    base = rig.intake("youtube_general")
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
    graph = job_graph(LONG, frozenset({"a_script"}) if script_approval else frozenset())
    report = rig.runner.run(job, graph, rig.runner.start(job, graph))
    for stage in ("a_script", "a_final") if script_approval else ("a_final",):
        assert report.status == "AWAITING_APPROVAL", report.detail
        (task,) = [r.task_id for r in report.stages.values() if r.stage_id == stage]
        rig.desk.decisions.add(task)
        report = rig.runner.run(job, graph, report)
        if report.status != "AWAITING_APPROVAL" and stage == "a_script":
            break
    return report, stand[0]


def test_the_chain_with_test_desk_evidence_is_delivered_in_a_dry_run(
    pg_dsn: str, tmp_path: Path
) -> None:
    report, _ = _run_to_decision(pg_dsn, tmp_path, real_run=False)
    assert report.status == "DELIVERED"


def test_a_real_run_without_the_port_refuses_the_whole_chain(pg_dsn: str, tmp_path: Path) -> None:
    """Fail closed: no ``ApprovalEvidencePort`` injected into the runner, a real run authorises
    nothing (a dry run neither: the port is the only reader of approval evidence)."""
    report, _ = _run_to_decision(pg_dsn, tmp_path, real_run=True, evidence=None)
    assert report.status != "DELIVERED"
    auth = report.stages["s16_auth"]
    assert auth.output is not None and auth.output.error is not None
    assert "no evidence port" in str(auth.output.error.details)
    assert "s13_deliver" not in report.order


def test_the_same_chain_is_refused_at_the_authorisation_in_a_real_run(
    pg_dsn: str, tmp_path: Path
) -> None:
    report, _ = _run_to_decision(pg_dsn, tmp_path, real_run=True)
    assert report.status != "DELIVERED"
    auth = report.stages["s16_auth"]
    assert auth.output is not None and auth.output.error is not None
    assert "TEST_FIXTURE" in str(auth.output.error.details)
    assert "s13_deliver" not in report.order


def test_a_dry_run_with_the_script_approval_still_passes_with_the_test_desk(
    pg_dsn: str, tmp_path: Path
) -> None:
    report, stand = _run_to_decision(pg_dsn, tmp_path, real_run=False, script_approval=True)
    assert report.status == "DELIVERED", report.detail
    assert "s07_voice" in stand.seen


def test_a_real_run_refuses_the_script_approval_before_any_paid_stage(
    pg_dsn: str, tmp_path: Path
) -> None:
    """The test desk evidence is TEST_FIXTURE: refused at the builder of the paid TTS stage,
    which therefore never starts (nor the shot plan, the render or the authorisation)."""
    report, stand = _run_to_decision(pg_dsn, tmp_path, real_run=True, script_approval=True)
    assert report.status != "DELIVERED"
    voice = report.stages["s07_voice"]
    assert voice.output is not None and voice.output.error is not None
    assert "TEST_FIXTURE" in str(voice.output.error.details)
    assert not {"s07_voice", "s09_plan", "s10_render", "s16_auth"} & set(stand.seen)


def test_the_graph_runner_default_is_a_real_run() -> None:
    """No production caller of ``GraphRunner`` exists yet; when one is written it must take
    ``real_run`` from the ``RunMode`` config (``mode is REAL_RUN``), never from job or caller
    input. Until then the constructor default is fail closed: a real run."""
    import inspect

    from amw_orchestrator.driver import GraphRunner

    assert inspect.signature(GraphRunner.__init__).parameters["real_run"].default is True
    field = BuildContext.__dataclass_fields__["real_run"]
    assert field.default is True and "real_run" not in JobFacts.__dataclass_fields__
