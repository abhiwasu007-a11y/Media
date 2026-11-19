# ruff: noqa: E501, PT018
"""PASS6-B1 dry-run acceptance (builders). PLUMBING TEST - NOT QUALITY.

What runs for real: the GraphRunner and its driver on the PostgreSQL tables, the TaskExecutor, the
real ``BuilderTable`` (every task type of the 3A long-form graph), every Task Input validated
through the agents' OWN input models (a TEST registry, ``agent_schemas``: the global allow-list
stays empty and this lane does not edit it), the hash-verified document reads of the builders
through the real ``TaskIo``/``LocalDiskStorage``, the S7 ``ApprovalWorker`` and the REAL
``agent_13.file_delivery`` entry point (``DeliveryStage``), which builds the zip and the manifest
from what the builders passed it.

What does NOT run for real: the agent entry points 04-11 and 16. They are stand-in workers that
write real blobs and return model-shaped outputs (only the fields the downstream builders read), so
this test proves the builders, the document hand-offs and the driver, not the agents' behaviour.
A non-finance job (D13 philosophy sample shape) goes from J01 to DELIVERED."""

import io
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from amw_core.contracts import TaskInput, TaskOutput
from amw_core.exec_context import ExecContext
from amw_core.ids import Prefix, new_id
from amw_core.interfaces.storage import BlobUri
from amw_core.storage.local import LocalDiskStorage
from amw_core.tenancy.storage_paths import task_artifact_uri
from amw_delivery.stage import DeliveryStage
from amw_orchestrator.executor import ApprovalWorker, JobFacts
from amw_orchestrator.input_builders import BuilderTable
from amw_orchestrator.registry import job_graph
from tests.orchestrator.agent_schemas import agent_registry
from tests.orchestrator.builder_world import Services, doc_ref
from tests.orchestrator.world import LONG, TestDesk, build_rig, ok_output

pytestmark = pytest.mark.integration


class _Clock:
    def now(self) -> Any:
        from datetime import UTC, datetime

        return datetime(2030, 1, 1, tzinfo=UTC)

    def monotonic_ms(self) -> int:
        return 0


class StandIns:
    """One ``TaskWorker`` for the stages whose real entry point needs an agent-sized fake world."""

    def __init__(self, storage: LocalDiskStorage) -> None:
        self.s = storage
        self.seen: dict[str, dict[str, Any]] = {}  # stage -> the payload the builder produced
        self.state: dict[str, Any] = {}

    # -- plumbing ---------------------------------------------------------------------------
    def put(
        self, ctx: ExecContext, name: str, body: bytes, media: str = "application/json"
    ) -> dict[str, Any]:
        uri = task_artifact_uri(ctx.org_id, ctx.job_id, ctx.task_id, ctx.attempt_id, name)
        info = self.s.put(ctx.tenant, BlobUri(uri), io.BytesIO(body))
        kind = (
            "IMAGE"
            if media.startswith("image/")
            else "VIDEO"
            if media.startswith("video/")
            else "DATA"
        )
        return {
            "uri": uri,
            "kind": kind,
            "sha256": info.sha256,
            "size_bytes": info.size_bytes,
            "media_type": media,
        }

    def doc(self, ctx: ExecContext, name: str, doc: Mapping[str, Any]) -> dict[str, Any]:
        return self.put(ctx, name, json.dumps(doc, sort_keys=True).encode())

    def out(
        self,
        schema: str,
        data: dict[str, Any],
        refs: list[dict[str, Any]],
        results: list[dict[str, Any]] | None = None,
    ) -> TaskOutput:
        base = ok_output(schema, data, results=results).model_dump(mode="json", by_alias=True)
        base["output_refs"] = refs
        return TaskOutput.model_validate(base)

    def run(self, task_input: TaskInput, ctx: ExecContext) -> TaskOutput:
        stage = str(ctx.stage_id)
        self.seen[stage] = dict(task_input.payload.data or {})
        out: TaskOutput = getattr(self, f"_{stage}")(task_input, ctx)
        return out

    # -- stages -----------------------------------------------------------------------------
    def _s04_research(self, ti: TaskInput, ctx: ExecContext) -> TaskOutput:
        pack = self.doc(ctx, "research_pack.json", {"pack": 1})
        data = {
            "citations_available": [
                {
                    "citation_ref": "cit_1",
                    "kind": "KNOWLEDGE_CHUNK",
                    "title": "T1",
                    "content_sha256": "a" * 64,
                }
            ],
            "method": {"used": False, "release_approval_ids": [], "restricted_pending": []},
        }
        return self.out("agent_04.research_pack.output", data, [pack])

    def _s05_script(self, ti: TaskInput, ctx: ExecContext) -> TaskOutput:
        doc = {
            "segments": [
                {"segment_id": "s1", "text": "Time is finite.", "chart_ref": None,
                 "concept_refs": [{"concept_id": "k1", "citation_refs": ["cit_1"]}]},
            ],
            "chart_requests": [],
        }  # fmt: skip
        ref = self.doc(ctx, "script.json", doc)
        data = {"script_id": new_id(Prefix.SCRIPT), "version": 1,
                "script_document": {"uri": ref["uri"], "sha256": ref["sha256"]}}  # fmt: skip
        return self.out("agent_05.script_draft.output", data, [ref])

    def _s06_claims(self, ti: TaskInput, ctx: ExecContext) -> TaskOutput:
        claim = {
            "local_id": "c1", "segment_id": "s1", "char_start": 0, "char_end": 4, "quote": "Time",
            "normalized_claim": "Time is finite", "claim_type": "DEFINITION",
            "time_reference_kind": "TIMELESS", "instrument": None, "chart_data_ref": None,
            "requires_citation": True, "citation_refs": ["cit_1"], "rule_flags": [],
            "proposed_verdict": "ALLOWED", "rationale": "x",
        }  # fmt: skip
        refs = [
            self.doc(ctx, "claim_extraction_output.json", {"claims": [claim]}),
            self.doc(ctx, "claim_ids.json", {"c1": new_id(Prefix.CLAIM)}),
        ]
        data = {"claims": [claim], "overall": {"proposed_verdict": "ALLOWED", "blocking_rule_ids": [], "needs_human_review_reasons": []}, "refusal": None}  # fmt: skip
        return self.out("agent_06.claim_extraction.output", data, refs)

    def _verify(self, ctx: ExecContext, ti: TaskInput) -> TaskOutput:
        ref = self.doc(ctx, "claim_verification_output.json", {"v": 1})
        data = {
            "script_sha256": (ti.payload.data or {})["script_sha256"],
            "overall": {"proposed_verdict": "ALLOWED"},
        }
        return self.out("agent_06.claim_verification.output", data, [ref])

    def _s06_verify(self, ti: TaskInput, ctx: ExecContext) -> TaskOutput:
        return self._verify(ctx, ti)

    def _s06_chart(self, ti: TaskInput, ctx: ExecContext) -> TaskOutput:
        return self._verify(ctx, ti)

    def _s07_voice(self, ti: TaskInput, ctx: ExecContext) -> TaskOutput:
        stem = self.put(ctx, "narration.wav", b"RIFF-stem", "audio/wav")
        tl = self.doc(ctx, "timeline.json", {"segments": []})
        data = {
            "narration": {"stem_uri": stem["uri"], "sha256": stem["sha256"]},
            "timeline": {"timeline_uri": tl["uri"], "timeline_sha256": tl["sha256"], "pauses": []},
        }  # fmt: skip
        return self.out("agent_07.voice_synthesis.output", data, [stem, tl])

    def _s07_master(self, ti: TaskInput, ctx: ExecContext) -> TaskOutput:
        rep = self.doc(ctx, "report.json", {"gate": []})
        return self.out("agent_07.audio_master.output", {"gate_verdict": "PASSED"}, [rep])

    def _s09_plan(self, ti: TaskInput, ctx: ExecContext) -> TaskOutput:
        plan = self.doc(ctx, "shot_plan.json", {"plan": 1})
        ref = {"uri": plan["uri"], "sha256": plan["sha256"], "schema": "agent_09.shot_plan.output", "schema_version": "1.0.0"}  # fmt: skip
        return self.out("agent_09.shot_plan.output", {"plan_ref": ref}, [plan])

    def _s08_assets(self, ti: TaskInput, ctx: ExecContext) -> TaskOutput:
        man = self.doc(ctx, "sourcing_manifest.json", {"shots": []})
        return self.out("agent_08.asset_sourcing.output", {"chart_facts": []}, [man])

    def _s10_render(self, ti: TaskInput, ctx: ExecContext) -> TaskOutput:
        mp4 = self.put(ctx, "render.mp4", b"\x00\x00mp4-bytes", "video/mp4")
        tl = self.doc(ctx, "timeline_render.json", {"t": 1})
        data = {
            "render_id": new_id(Prefix.RENDER),
            "render_ref": {"uri": mp4["uri"], "sha256": mp4["sha256"], "size_bytes": mp4["size_bytes"]},
            "timeline_ref": {"uri": tl["uri"], "sha256": tl["sha256"]},
        }  # fmt: skip
        return self.out("agent_10.render.output", data, [mp4, tl])

    def _s10_subs(self, ti: TaskInput, ctx: ExecContext) -> TaskOutput:
        srt = self.put(
            ctx, "subs-mr-IN.srt", b"1\n00:00:00,000 --> 00:00:01,000\nx\n", "application/x-subrip"
        )
        data = {"srt": [{"language": "mr-IN", "uri": srt["uri"], "sha256": srt["sha256"], "size_bytes": srt["size_bytes"]}]}  # fmt: skip
        return self.out("agent_10.subtitles.output", data, [srt])

    def _s10_qc(self, ti: TaskInput, ctx: ExecContext) -> TaskOutput:
        rep = self.doc(ctx, "qc_report.json", {"r": 1})
        man = self.doc(ctx, "evidence_manifest.json", {"frames": []})
        data = {"evidence": {"report_ref": {"uri": rep["uri"], "sha256": rep["sha256"]}, "manifest_ref": {"uri": man["uri"], "sha256": man["sha256"]}}}  # fmt: skip
        res = [{"check_id": "a10.q.duration", "kind": "DETERMINISTIC", "verdict": "PASS", "blocking": False, "message": "ok", "measured": 1, "threshold": 2, "unit": "s"}]  # fmt: skip
        return self.out("agent_10.technical_qc.output", data, [rep, man], res)

    def _s11_thumbs(self, ti: TaskInput, ctx: ExecContext) -> TaskOutput:
        png = self.put(ctx, "thumbnails/v1.png", b"\x89PNG-thumb", "image/png")
        man = self.doc(ctx, "thumbnails/manifest-abc123.json", {"m": 1})
        variant = {"variant_id": "v1", "is_control": True, "file": {"uri": png["uri"], "sha256": png["sha256"], "size_bytes": png["size_bytes"], "media_type": "image/png"}}  # fmt: skip
        return self.out("agent_11.thumbnail_variants.output", {"variants": [variant]}, [png, man])

    def _s02u_unique(self, ti: TaskInput, ctx: ExecContext) -> TaskOutput:
        return self.out(
            "svc_s02.uniqueness_check.output",
            {"verdict": "ALLOWED"},
            [self.doc(ctx, "uniqueness-0.json", {"u": 1})],
        )

    def _s16_comp(self, ti: TaskInput, ctx: ExecContext) -> TaskOutput:
        gate = [
            {
                "check_id": "a16.gate.rules", "kind": "DETERMINISTIC", "verdict": "PASS",
                "blocking": True, "message": "ok", "gate": True,
            }
        ]  # fmt: skip
        ref = self.doc(ctx, "compliance_gate-0.json", {"g": 1})
        return self.out("agent_16.compliance_gate.output", {"verdict": "ALLOWED"}, [ref], gate)

    def _s16_score(self, ti: TaskInput, ctx: ExecContext) -> TaskOutput:
        dims = [{"dimension": "ACCURACY", "max_points": 20, "points": 18, "scorer_kind": "DETERMINISTIC", "criteria": []}]  # fmt: skip
        return self.out(
            "agent_16.quality_score.output",
            {"dimensions": dims},
            [self.doc(ctx, "quality_score-0.json", {"s": 1})],
        )

    def _s16_auth(self, ti: TaskInput, ctx: ExecContext) -> TaskOutput:
        subject = (ti.payload.data or {})["subject"]
        data = {"verdict": "ALLOWED", "authorised_action": "DELIVERY", "authorisation_verdict_id": "vrd_test", "subject": subject}  # fmt: skip
        return self.out(
            "agent_16.publication_authorisation.output",
            data,
            [self.doc(ctx, "publication_authorisation-0.json", {"a": 1})],
        )


class ApprovingDesk(TestDesk):
    """A TEST decision that carries the approval ID (the S7 desk of the real system returns it)."""

    def decision(self, task_input: TaskInput, ctx: ExecContext) -> Mapping[str, object] | None:
        if str(ctx.task_id) not in self.decisions:
            return None
        return {"state": "APPROVED", "approval_id": new_id(Prefix.APPROVAL)}


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
        schemas=agent_registry(real_outputs=False), build_services=RuntimeFacts(), desk=ApprovingDesk(),
    )  # fmt: skip
    base = rig.intake("non-finance")
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
