# ruff: noqa: E501, PT018
"""PASS6-B1 dry-run acceptance (builders). PLUMBING TEST - NOT QUALITY.

What runs for real: the GraphRunner and its driver on the PostgreSQL tables, the TaskExecutor, the
real ``BuilderTable`` (every task type of the 3A long-form graph), every Task Input validated
through the agents' OWN input models (the GLOBAL registry of PR #98 where the name is registered;
the TEST registry ``agent_schemas`` only for the unregistered names: agent_16 gate/score/
authorisation outputs, svc_s02.*, svc_s07.request_approval.*), the hash-verified document reads of the builders
through the real ``TaskIo``/``LocalDiskStorage``, the S7 ``ApprovalWorker`` and the REAL
``agent_13.file_delivery`` entry point (``DeliveryStage``), which builds the zip and the manifest
from what the builders passed it.

What does NOT run for real: the agent entry points 04-11 and 16. They are stand-in workers that
write real blobs and return model-shaped outputs (only the fields the downstream builders read), so
this test proves the builders, the document hand-offs and the driver, not the agents' behaviour.
A non-finance job (D13 philosophy sample shape) goes from J01 to DELIVERED."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from amw_core.ids import Prefix, new_id
from amw_core.storage.local import LocalDiskStorage
from amw_delivery.stage import DeliveryStage
from amw_orchestrator.executor import ApprovalWorker, JobFacts
from amw_orchestrator.input_builders import BuilderTable
from amw_orchestrator.plumbing import StandIns
from amw_orchestrator.registry import job_graph
from tests.orchestrator.agent_schemas import agent_registry
from tests.orchestrator.builder_world import Services, doc_ref
from tests.orchestrator.world import LONG, TestDesk, build_rig

pytestmark = pytest.mark.integration


class _Clock:
    def now(self) -> Any:
        from datetime import UTC, datetime

        return datetime(2030, 1, 1, tzinfo=UTC)

    def monotonic_ms(self) -> int:
        return 0


class Registry:
    def __init__(self, stand: StandIns, approval: ApprovalWorker, delivery: DeliveryStage) -> None:
        self.stand, self.approval, self.delivery = stand, approval, delivery
        self.table = BuilderTable()
        self.real_delivery_runs = 0

    def worker_for(self, stage: Any) -> Any:
        if stage.task_type == "svc_s07.request_approval":
            return self.approval
        if stage.task_type == "agent_13.file_delivery":
            return self.delivery
        return self.stand

    def builder_for(self, stage: Any) -> BuilderTable:
        return self.table


class RuntimeFacts:
    """The runtime lane's ``BuildServices`` part: cost report and delivery policy values."""

    def __init__(self) -> None:
        self._svc = Services()

    def cost_report(self, job: JobFacts) -> Mapping[str, Any]:
        return self._svc.cost_report(job)

    def delivery_facts(self, job: JobFacts) -> Mapping[str, Any]:
        return self._svc.delivery_facts(job)


def test_non_finance_job_runs_to_delivered_through_the_real_builders(
    pg_dsn: str, tmp_path: Path
) -> None:
    holder: dict[str, Registry] = {}

    def factory(approval: ApprovalWorker, storage: LocalDiskStorage) -> Registry:
        reg = Registry(
            StandIns(storage), approval, DeliveryStage(storage, _Clock(), scratch_root=tmp_path)
        )
        holder["r"] = reg
        return reg

    rig = build_rig(
        pg_dsn, tmp_path / "blobs", registry_factory=factory,
        schemas=agent_registry(real_outputs=False), build_services=RuntimeFacts(), desk=TestDesk(),
    )  # fmt: skip
    base = rig.intake("youtube_general")
    org = base.org_id
    from dataclasses import replace

    from amw_orchestrator.executor import JobDocuments, RulePackDoc

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
    j = replace(base, documents=docs)
    assert not j.finance_rules_apply
    graph = job_graph(LONG)
    report = rig.runner.start(j, graph)
    report = rig.runner.run(j, graph, report)
    assert report.status == "AWAITING_APPROVAL", report.detail
    (task,) = [r.task_id for r in report.stages.values() if r.stage_id == "a_final"]
    rig.desk.decisions.add(task)
    report = rig.runner.run(j, graph, report)
    assert report.status == "DELIVERED", report.detail
    stand = holder["r"].stand
    # every builder-made payload of every stage validated through the agent's own input model
    assert set(stand.seen) >= {"s04_research", "s05_script", "s06_claims", "s06_verify", "s07_voice", "s07_master", "s09_plan", "s08_assets", "s06_chart", "s10_render", "s10_subs", "s10_qc", "s11_thumbs", "s02u_unique", "s16_comp", "s16_score", "s16_auth"}  # fmt: skip
    # no finance rule pack anywhere
    for payload in stand.seen.values():
        assert "rp.finance_sebi_in" not in json.dumps(payload)
    # the real agent_13 entry point built the bundle
    deliver = report.stages["s13_deliver"].output
    assert deliver is not None and deliver.payload is not None
    assert deliver.payload.payload_schema == "agent_13.file_delivery.output"
    assert [r.media_type for r in deliver.output_refs] == ["application/zip", "application/json"]
