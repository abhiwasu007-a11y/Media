# ruff: noqa: E501
"""Driver harness of the second dry run: the REAL ``GraphRunner`` / ``TaskExecutor`` / builders on the
PostgreSQL tables, with the stages named in ``real`` served by the REAL agent entry points (own fakes)
and every other stage by the first dry run's stand-ins. PLUMBING TEST - NOT QUALITY."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from amw_core.contracts.payloads import PayloadSchemaRegistry, load_payload_schema_plugins
from amw_core.ids import Prefix, new_id
from amw_core.storage.local import LocalDiskStorage
from amw_delivery.stage import DeliveryStage
from amw_orchestrator.driver import RunReport
from amw_orchestrator.executor import ApprovalWorker, DocRef, JobDocuments, JobFacts, RulePackDoc
from amw_orchestrator.input_builders import BuilderTable
from amw_orchestrator.plumbing import StandIns
from amw_orchestrator.registry import job_graph
from tests.dryrun.real_world import FACTORIES, LazyWorker
from tests.orchestrator.agent_schemas import INPUTS, OUTPUTS, Open
from tests.orchestrator.test_dryrun_builders import (
    RuntimeFacts,
    _Clock,
)
from tests.orchestrator.world import LONG, Rig, TestDesk, build_rig


class HybridRegistry:
    def __init__(
        self,
        stand: StandIns,
        approval: ApprovalWorker,
        delivery: DeliveryStage,
        real: dict[str, LazyWorker],
    ) -> None:
        self.stand, self.approval, self.delivery, self.real = stand, approval, delivery, real
        self.table = BuilderTable()

    def worker_for(self, stage: Any) -> Any:
        if stage.task_type == "svc_s07.request_approval":
            return self.approval
        if stage.task_type == "agent_13.file_delivery":
            return self.delivery
        return self.real.get(stage.task_type, self.stand)

    def builder_for(self, stage: Any) -> BuilderTable:
        return self.table


def hybrid_schemas(real: set[str]) -> PayloadSchemaRegistry:
    """The GLOBAL registry (38 names: CCR-283 adds ``svc_s07.request_approval.*``), nothing added. Outputs of the stages served by
    stand-ins use the permissive model (they carry only what the downstream builders read); the
    outputs of the REAL stages (agent_13 and the ``ApprovalWorker`` included) use the registered model."""
    glob = PayloadSchemaRegistry()
    load_payload_schema_plugins(glob)
    reg = PayloadSchemaRegistry()
    for name in sorted(glob.names()):
        known = INPUTS.get(name) or OUTPUTS.get(name)
        found = glob.resolve(name, known[0] if known else "1.0.0")
        task_type = name.rsplit(".", 1)[0]
        stand_in = task_type not in real and task_type not in (
            "agent_13.file_delivery",
            "svc_s07.request_approval",
        )  # the delivery stage and the ApprovalWorker are the real ones
        reg.register(
            name, found.version, Open if name.endswith(".output") and stand_in else found.model
        )
    return reg


@dataclass
class Result:
    rig: Rig
    report: RunReport
    job: JobFacts
    registry: HybridRegistry
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        r = self.report
        lines = [f"status={r.status} detail={r.detail!r}", f"order={r.order}"]
        for sid, run in r.stages.items():
            err = run.output.error if run.output is not None else None
            lines.append(
                f"  {sid}: {run.state.value} {err.code + ': ' + err.message if err else ''}"
            )
        return "\n".join(lines)


def intake_job(rig: Rig, language: str, title: str = "Seneca on the shortness of time") -> JobFacts:
    """Same intake as ``Rig.intake`` (non-finance philosophy sample shape, D13) with a chosen job
    language. The canned model responses of the real agents are English, so the dry run uses en-IN;
    the Marathi language path is NOT exercised (listed in the report)."""
    from amw_core.contracts import OwnerTopic
    from amw_core.ids import CORRELATION
    from amw_orchestrator.services import intake

    topic = OwnerTopic.model_validate(
        {
            "schema_version": "1.0.0", "title": title, "brief": None, "angle": None,
            "language": language, "video_kind": "GENERAL", "course_chapter_pointer": None,
            "owner_references": [], "target_duration_ms": 60_000, "shorts_wanted": False,
        }
    )  # fmt: skip
    rig.set_channel_category("youtube_general")  # intake reads channels.category (CCR-273, D13)
    return intake(
        rig.tenancy, rig.jobs, org_id=rig.seed.org_id, workspace_id=rig.seed.workspace_id,
        project_id=rig.seed.project_id, channel_id=rig.seed.channel_id, topic=topic,
        production_type=LONG, version=2, correlation_id=str(CORRELATION.new()),
    )  # fmt: skip


JOB_DOCS: dict[str, dict[str, Any]] = {
    "brand_kit": {
        "intro_ref": "sting_a",
        "intro_duration_ms": 1200,
        "outro_ref": None,
        "lower_third_template_ref": None,
    },
    "profile": {"placeholder": "compliance_profile"},
    "yt": {"placeholder": "rp.youtube_general"},
    "template": {
        "segments": [{"section_role": "HOOK", "text": "Today we explore {topic} in simple steps."}],
        "shot_types": ["CHART"],
    },
    "dictionary": {"dictionary_key": "dry-run-dict", "version": 1, "entries": []},
}
"""Contents of the job-level documents. Only the pronunciation dictionary has a shape (agent_07's own
model); the others have none registered anywhere, so a real consumer that parses one reports it."""


def put_doc(storage: LocalDiskStorage, org: str, name: str, doc: Mapping[str, Any]) -> DocRef:
    """Store a job-level document in the tenant's ``assets`` area (write-once) and return its ref."""
    import io
    import json

    from amw_core.interfaces import TenantContext
    from amw_core.interfaces.storage import BlobUri
    from amw_core.tenancy.storage_paths import blob_uri

    uri = blob_uri(org, "assets", f"{new_id(Prefix.ASSET)}/{name}")  # type: ignore[arg-type]
    body = json.dumps(doc, sort_keys=True).encode()
    info = storage.put(TenantContext(org, "agent_01", None), BlobUri(uri), io.BytesIO(body))  # type: ignore[arg-type]
    return DocRef(str(info.uri), info.sha256)


def run_hybrid(
    dsn: str,
    tmp: Path,
    *,
    real: set[str],
    approve: bool = True,
    max_attempts: int = 2,  # the resume of the suspended approval task is its second attempt
    language: str = "en-IN",
    options: Mapping[str, Any] | None = None,
) -> Result:
    holder: dict[str, HybridRegistry] = {}
    shared: dict[str, Any] = {**(options or {}), "language": language}
    """Per-run options the in-memory adapters read (a canned query language, a channel label)."""

    def factory(approval: ApprovalWorker, storage: LocalDiskStorage) -> HybridRegistry:
        lazy = {
            tt: LazyWorker(tt, FACTORIES[tt], storage, tmp / "scratch", shared)
            for tt in sorted(real)
        }
        reg = HybridRegistry(
            StandIns(storage), approval, DeliveryStage(storage, _Clock(), scratch_root=tmp), lazy
        )
        holder["r"] = reg
        return reg

    rig = build_rig(
        dsn, tmp / "blobs", registry_factory=factory,
        schemas=hybrid_schemas(real),
        build_services=RuntimeFacts(), desk=TestDesk(), max_attempts=max_attempts,
    )  # fmt: skip
    base = intake_job(rig, language)
    if "channel_category_label" in shared:  # the value the channel row stores (CCR-288)
        base = replace(base, channel_category_row=str(shared["channel_category_label"]))
    org = base.org_id
    storage = rig.storage
    docs = JobDocuments(
        brand_kit=put_doc(storage, org, "brand_kit.json", JOB_DOCS["brand_kit"]),
        compliance_profile=put_doc(storage, org, "profile.json", JOB_DOCS["profile"]),
        rule_packs={
            "rp.youtube_general": RulePackDoc(
                new_id(Prefix.RULE_PACK), 1, put_doc(storage, org, "yt.json", JOB_DOCS["yt"])
            )
        },
        voice_id=new_id(Prefix.VOICE),
        voice_dictionary=put_doc(
            storage, org, "dictionary.json", {**JOB_DOCS["dictionary"], "language": language}
        ),
        uniqueness_template=put_doc(storage, org, "template.json", JOB_DOCS["template"]),
    )
    job = replace(base, documents=docs)
    graph = job_graph(LONG)
    report = rig.runner.start(job, graph)
    report = rig.runner.run(job, graph, report)
    if approve and report.status == "AWAITING_APPROVAL":
        (task,) = [r.task_id for r in report.stages.values() if r.stage_id == "a_final"]
        rig.desk.decisions.add(task)
        report = rig.runner.run(job, graph, report)
    return Result(rig, report, job, holder["r"])


__all__ = ["Mapping", "Result", "run_hybrid"]
