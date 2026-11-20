# ruff: noqa: E501
"""Hand-made upstream outputs for the input-builder tests (only the fields a builder reads, in the
shape the producers' output models define). PLUMBING TEST - NOT QUALITY."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from amw_core.contracts import OwnerTopic, ResourceBudget, TaskOutput
from amw_core.ids import (
    APPROVAL,
    ATTEMPT,
    CHANNEL,
    CORRELATION,
    JOB,
    ORG,
    PROJECT,
    TASK,
    WORKSPACE,
    Prefix,
    new_id,
)
from amw_core.tenancy.storage_paths import task_artifact_uri
from amw_orchestrator.executor import (
    BuildContext,
    ChannelCategory,
    DocRef,
    JobDocuments,
    JobFacts,
    RulePackDoc,
)
from amw_orchestrator.registry import job_graph
from tests.orchestrator.evidence_fake import FakeEvidenceStatuses
from tests.orchestrator.world import LONG, approval_output, ok_output

H = "a" * 64


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class Services:
    """In-memory ``BuildServices``: documents by (uri, sha), the cost report and delivery facts."""

    def __init__(self) -> None:
        self.docs: dict[tuple[str, str], Mapping[str, Any]] = {}
        self.copies = 0

    def put(self, uri: str, doc: Mapping[str, Any]) -> DocRef:
        ref = DocRef(uri, sha(json.dumps(doc, sort_keys=True)))
        self.docs[(ref.uri, ref.sha256)] = doc
        return ref

    def read_json(self, uri: str, sha256: str) -> Mapping[str, Any]:
        return self.docs[(uri, sha256)]

    def payload_document(self, job: JobFacts, output: TaskOutput) -> DocRef:
        self.copies += 1
        assert output.payload is not None
        assert output.payload.data is not None
        return self.put(
            output.output_refs[0].uri.rsplit("/", 1)[0] + "/payload.json", output.payload.data
        )

    def cost_report(self, job: JobFacts) -> Mapping[str, Any]:
        return {
            "job_id": job.job_id, "production_type_key": "CHANNEL_LONG_FORM",
            "production_type_version": "2", "topic_ref": None, "query_scope": "JOB",
            "figure_kind_summary": "ESTIMATE", "price_refs": {}, "generated_at": "2030-01-01T00:00:00Z",
            "run_mode": "TEST", "currency": "USD", "rows": [], "total_micros": 0, "total_minor": 0,
            "terms_micros": {}, "allocated": [], "human_review_minutes": 0, "budgets": [],
            "header_budget": {},
        }  # fmt: skip

    def delivery_facts(self, job: JobFacts) -> Mapping[str, Any]:
        return {
            "config_version": "cfg-test",
            "banner": "PLUMBING TEST - NOT QUALITY",
            "disclaimer": {"text": "test text", "version": "v-test", "status_label": "TEST"},
            "disclosure_note": "plain words",
            "limits": {
                "max_file_bytes": 10**9,
                "max_total_bytes": 10**9,
                "max_thumbnail_bytes": 10**7,
            },
        }


def topic(language: str = "mr-IN") -> OwnerTopic:
    return OwnerTopic.model_validate(
        {
            "schema_version": "1.0.0", "title": "Seneca on time", "brief": None, "angle": None,
            "language": language, "video_kind": "GENERAL", "course_chapter_pointer": None,
            "owner_references": [], "target_duration_ms": 60_000, "shorts_wanted": False,
        }
    )  # fmt: skip


def doc_ref(org: str, name: str = "d.json") -> DocRef:
    return DocRef(f"amw-blob://{org}/assets/{name}", sha(name))


def job(category: ChannelCategory = ChannelCategory.NON_FINANCE) -> JobFacts:
    org = str(ORG.new())
    packs = {
        "rp.youtube_general": RulePackDoc(
            new_id(Prefix.RULE_PACK), 1, doc_ref(org, "youtube_pack.json")
        ),
    }
    return JobFacts(
        org_id=org, workspace_id=str(WORKSPACE.new()), project_id=str(PROJECT.new()),
        channel_id=str(CHANNEL.new()), job_id=str(JOB.new()), parent_job_id=None,
        correlation_id=str(CORRELATION.new()), production_type_key=LONG, production_type_version=2,
        language="mr-IN", owner_topic=topic(), currency="USD", channel_category=category,
        documents=JobDocuments(
            brand_kit=doc_ref(org, "brand_kit.json"),
            compliance_profile=doc_ref(org, "profile.json"),
            rule_packs=packs,
            voice_id=new_id(Prefix.VOICE),
            voice_dictionary=doc_ref(org, "dictionary.json"),
            uniqueness_template=doc_ref(org, "template.json"),
        ),
    )  # fmt: skip


def finance_job() -> JobFacts:
    base = job(ChannelCategory.FINANCE)
    docs = base.documents
    packs = dict(docs.rule_packs)
    packs["rp.finance_sebi_in"] = RulePackDoc(
        new_id(Prefix.RULE_PACK), 1, doc_ref(base.org_id, "finance_pack.json")
    )
    return replace(
        base,
        documents=replace(
            docs, rule_packs=packs, disclaimer_template=doc_ref(base.org_id, "disclaimer.json")
        ),
    )


class World:
    """One finished long-form run up to ``a_final`` as ``BuildContext.upstream`` mappings."""

    def __init__(self, jb: JobFacts | None = None) -> None:
        self.job = jb or job()
        self.svc = Services()
        self.evidence = FakeEvidenceStatuses()
        self.up: dict[str, TaskOutput] = {}
        self.task_ids: dict[str, str] = {}
        self._build()

    # -- helpers ------------------------------------------------------------------------------
    def uri(self, stage: str, name: str) -> str:
        tid = self.task_ids.setdefault(stage, str(TASK.new()))
        att = self.task_ids.setdefault(stage + "#a", str(ATTEMPT.new()))
        from amw_core.ids import AttemptId, JobId, OrgId, TaskId

        return task_artifact_uri(
            OrgId(self.job.org_id), JobId(self.job.job_id), TaskId(tid), AttemptId(att), name
        )

    def add(
        self,
        stage: str,
        schema: str,
        data: dict[str, Any],
        files: Mapping[str, DocRef] | None = None,
    ) -> dict[str, DocRef]:
        refs = {}
        for name, ref in (files or {}).items():
            refs[name] = ref
        out = ok_output(schema, data)
        raw = out.model_dump(mode="json", by_alias=True)
        raw["output_refs"] = [
            {
                "uri": r.uri, "kind": "DATA", "sha256": r.sha256, "size_bytes": 10,
                "media_type": "application/json",
            }
            for r in refs.values()
        ]  # fmt: skip
        self.up[stage] = TaskOutput.model_validate(raw)
        self.task_ids.setdefault(stage, str(TASK.new()))
        return refs

    def file(self, stage: str, name: str, doc: Mapping[str, Any] | None = None) -> DocRef:
        uri = self.uri(stage, name)
        return self.svc.put(uri, doc or {"name": name})

    # -- the run ------------------------------------------------------------------------------
    def _build(self) -> None:
        j = self.job
        script_doc = self.file(
            "s05_script", "script.json",
            {
                "segments": [
                    {"segment_id": "s1", "text": "Time is the one thing we cannot buy back.",
                     "chart_ref": None,
                     "concept_refs": [{"concept_id": "k1", "citation_refs": ["cit_1", "cit_0"]}]},
                    {"segment_id": "s2", "text": "So spend it on purpose.", "chart_ref": None,
                     "concept_refs": []},
                ],
                "chart_requests": [],
            },
        )  # fmt: skip
        sid = new_id(Prefix.SCRIPT)
        self.add(
            "s05_script", "agent_05.script_draft.output",
            {"script_id": sid, "version": 1, "script_document": {"uri": script_doc.uri, "sha256": script_doc.sha256}},
            {"script.json": script_doc},
        )  # fmt: skip
        pack = self.file("s04_research", "research_pack.json")
        self.add(
            "s04_research", "agent_04.research_pack.output",
            {
                "citations_available": [
                    {"citation_ref": "cit_1", "kind": "KNOWLEDGE_CHUNK", "title": "T1", "content_sha256": H},
                    {"citation_ref": "cit_0", "kind": "KNOWLEDGE_CHUNK", "title": "T0", "content_sha256": H},
                ],
                "method": {"used": False, "release_approval_ids": [], "restricted_pending": []},
            },
            {"research_pack.json": pack},
        )  # fmt: skip
        claim = {
            "local_id": "c1", "segment_id": "s1", "char_start": 0, "char_end": 4, "quote": "Time",
            "normalized_claim": "Time is finite", "claim_type": "DEFINITION",
            "time_reference_kind": "TIMELESS", "instrument": None, "chart_data_ref": None,
            "requires_citation": True, "citation_refs": ["cit_1"], "rule_flags": [],
            "proposed_verdict": "ALLOWED", "rationale": "x",
        }  # fmt: skip
        ext = self.file("s06_claims", "claim_extraction_output.json")
        ids = self.file("s06_claims", "claim_ids.json", {"c1": new_id(Prefix.CLAIM)})
        self.add(
            "s06_claims", "agent_06.claim_extraction.output",
            {"claims": [claim], "overall": {"proposed_verdict": "ALLOWED", "blocking_rule_ids": [],
                                              "needs_human_review_reasons": []}, "refusal": None},
            {"claim_extraction_output.json": ext, "claim_ids.json": ids},
        )  # fmt: skip
        ver = self.file("s06_verify", "claim_verification_output.json")
        ver_data = {"script_sha256": script_doc.sha256, "overall": {"proposed_verdict": "ALLOWED"}}
        self.add("s06_verify", "agent_06.claim_verification.output", ver_data,
                 {"claim_verification_output.json": ver})  # fmt: skip
        tl = self.file("s07_voice", "timeline.json")
        stem = self.file("s07_voice", "narration.wav")
        self.add(
            "s07_voice", "agent_07.voice_synthesis.output",
            {
                "narration": {"stem_uri": stem.uri, "sha256": stem.sha256},
                "timeline": {"timeline_uri": tl.uri, "timeline_sha256": tl.sha256,
                             "pauses": [{"after_segment_id": "s1", "start_ms": 100, "end_ms": 900,
                                         "kind": "SCENE_PAUSE"},
                                        {"after_segment_id": "s1", "start_ms": 1, "end_ms": 2, "kind": "GAP"}]},
            },
            {"narration.wav": stem, "timeline.json": tl},
        )  # fmt: skip
        rep = self.file("s07_master", "report.json")
        self.add(
            "s07_master",
            "agent_07.audio_master.output",
            {"gate_verdict": "PASSED"},
            {"report.json": rep},
        )
        plan = self.file("s09_plan", "shot_plan.json")
        self.add(
            "s09_plan", "agent_09.shot_plan.output",
            {"plan_ref": {"uri": plan.uri, "sha256": plan.sha256, "schema": "agent_09.shot_plan.output",
                          "schema_version": "1.0.0"}},
            {"shot_plan.json": plan},
        )  # fmt: skip
        man = self.file("s08_assets", "sourcing_manifest.json")
        self.add("s08_assets", "agent_08.asset_sourcing.output", {"chart_facts": []},
                 {"sourcing_manifest.json": man})  # fmt: skip
        self.add("s06_chart", "agent_06.claim_verification.output", ver_data)
        rnd = self.file("s10_render", "render.mp4")
        rtl = self.file("s10_render", "timeline_x.json")
        self.add(
            "s10_render", "agent_10.render.output",
            {
                "render_id": new_id(Prefix.RENDER),
                "render_ref": {"uri": rnd.uri, "sha256": rnd.sha256, "size_bytes": 1234},
                "timeline_ref": {"uri": rtl.uri, "sha256": rtl.sha256},
            },
            {"render.mp4": rnd},
        )  # fmt: skip
        srt = self.file("s10_subs", "subs-mr-IN.srt")
        self.add(
            "s10_subs", "agent_10.subtitles.output",
            {"srt": [{"language": "mr-IN", "uri": srt.uri, "sha256": srt.sha256, "size_bytes": 55}]},
            {"subs-mr-IN.srt": srt},
        )  # fmt: skip
        qrep, qman = (
            self.file("s10_qc", "qc_report.json"),
            self.file("s10_qc", "evidence_manifest.json"),
        )
        self.add(
            "s10_qc", "agent_10.technical_qc.output",
            {"evidence": {
                "report_ref": {"uri": qrep.uri, "sha256": qrep.sha256},
                "manifest_ref": {"uri": qman.uri, "sha256": qman.sha256}}},
            {"qc_report.json": qrep},
        )  # fmt: skip
        self.up["s10_qc"] = self.up["s10_qc"].model_copy(
            update={"validation_results": (_result("a10.q.duration"),)}
        )
        thumb = self.file("s11_thumbs", "thumbnails/v1.png")
        tman = self.file("s11_thumbs", "thumbnails/manifest-abc123.json")
        self.add(
            "s11_thumbs", "agent_11.thumbnail_variants.output",
            {"variants": [{"variant_id": "v1", "is_control": True,
                           "file": {"uri": thumb.uri, "sha256": thumb.sha256, "size_bytes": 99,
                                    "media_type": "image/png"}}]},
            {"thumbnails/manifest-abc123.json": tman},
        )  # fmt: skip
        uq = self.file("s02u_unique", "uniqueness-0.json")
        self.add("s02u_unique", "svc_s02.uniqueness_check.output", {"verdict": "ALLOWED"},
                 {"uniqueness-0.json": uq})  # fmt: skip
        gate = self.file("s16_comp", "compliance_gate-0.json")
        self.add("s16_comp", "agent_16.compliance_gate.output", {"verdict": "ALLOWED"},
                 {"compliance_gate-0.json": gate})  # fmt: skip
        self.add(
            "s16_score", "agent_16.quality_score.output",
            {"dimensions": [{"dimension": "ACCURACY", "max_points": 20, "points": 18,
                             "scorer_kind": "DETERMINISTIC", "criteria": []}]},
        )  # fmt: skip
        self.render_id = str(self.up["s10_render"].payload.data["render_id"])  # type: ignore[union-attr, index]
        final_apr = str(APPROVAL.new())
        self.add("a_final", "svc_s07.request_approval.output",
                 approval_output(rnd.sha256, approval_id=final_apr, evidence_ids=[
                     self.evidence.record(self.job.org_id, "render", self.render_id,
                                          approval_id=final_apr, subject_sha256=rnd.sha256)]))  # fmt: skip
        self.add(
            "s16_auth", "agent_16.publication_authorisation.output",
            {"verdict": "ALLOWED", "authorised_action": "DELIVERY", "authorisation_verdict_id": "vrd_x",
             "subject": {"render_sha256": rnd.sha256}},
        )  # fmt: skip
        _ = j

    def ctx(self, stage_id: str, iteration: int = 0, **kw: Any) -> BuildContext:
        stage = next(s for s in job_graph(LONG) if s.stage_id == stage_id)
        upstream = {k: v for k, v in self.up.items() if k != stage_id}
        return BuildContext(
            job=self.job, stage=stage, task_id=str(TASK.new()), iteration=iteration, attempt_no=1,
            idempotency_key="idk_" + "a" * 64,
            resource_budget=ResourceBudget(max_cost_micros=0, currency="USD", max_wall_ms=1000, max_llm_calls=0),
            upstream=upstream, upstream_task_ids=self.task_ids, services=self.svc,
            evidence=self.evidence, **{"real_run": False, **kw},
        )  # fmt: skip


def _result(check_id: str, verdict: str = "PASS") -> Any:
    from amw_core.contracts import ValidationResult

    return ValidationResult.model_validate(
        {"check_id": check_id, "kind": "DETERMINISTIC", "verdict": verdict, "blocking": False,
         "message": "ok", "measured": 1, "threshold": 2, "unit": "ms"}
    )  # fmt: skip


def with_data(out: TaskOutput, data: dict[str, Any]) -> TaskOutput:
    """``out`` with another payload ``data`` (same schema)."""
    assert out.payload is not None
    return out.model_copy(update={"payload": out.payload.model_copy(update={"data": data})})


def data_of(out: TaskOutput) -> dict[str, Any]:
    assert out.payload is not None
    assert out.payload.data is not None
    return out.payload.data
