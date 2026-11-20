# ruff: noqa: E501
"""DRY_RUN plumbing: stand-in workers, the test approval desk and the plumbing build services.

PLUMBING TEST - NOT QUALITY. Everything here exists only so ``run_job`` can drive the real
``GraphRunner``, ``TaskExecutor``, input builders, ``ApprovalWorker`` and the real
``agent_13.file_delivery`` entry point end to end without any provider. The stand-in workers write
real blobs and return model-shaped outputs (only the fields the downstream builders read) with
INVENTED content; no model, no network, no key. The composition root builds these ONLY from a
DRY_RUN config (``composition.build_dry_run``); the real-run path never imports a desk or evidence
fixture from here (a test pins this).
"""

import io
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from amw_core.contracts import TaskInput, TaskOutput
from amw_core.contracts.payloads import PayloadSchemaRegistry, load_payload_schema_plugins
from amw_core.exec_context import ExecContext
from amw_core.ids import APPROVAL, OWNER_EVIDENCE, Prefix, new_id
from amw_core.interfaces import TenantContext
from amw_core.interfaces.storage import BlobUri
from amw_core.owner_evidence_approvals import APPROVAL_DECISION, ApprovalEvidenceStatus
from amw_core.owner_evidence_status import (
    OWNER_CHAT_OPERATOR,
    EvidenceSourceKind,
    EvidenceStatus,
)
from amw_core.storage.local import LocalDiskStorage
from amw_core.tenancy.storage_paths import blob_uri, task_artifact_uri
from amw_delivery.stage import DeliveryStage
from amw_orchestrator.executor import (
    ApprovalWorker,
    DocRef,
    JobDocuments,
    JobFacts,
    RulePackDoc,
)
from amw_orchestrator.input_builders import BuilderTable
from amw_orchestrator.outputs import now_z

BANNER = "PLUMBING TEST - NOT QUALITY"
"""The label every dry-run output carries (the delivery bundle banner and the run report)."""
PLUMBING_CATEGORY_RULE_PACK = "rp.youtube_general"


def ok_output(
    schema: str, data: dict[str, Any], *, results: list[dict[str, Any]] | None = None
) -> TaskOutput:
    return TaskOutput.model_validate(
        {
            "status": "SUCCEEDED",
            "payload": {"payload_schema": schema, "payload_schema_version": "1.0.0", "data": data},
            "output_refs": [],
            "quality_score": None,
            "confidence": None,
            "validation_results": results or [],
            "duration": 1,
            "resource_usage": {
                "cpu_ms": 0, "peak_rss_bytes": 0, "tokens_in": 0, "tokens_out": 0,
                "tokens_cached_in": 0, "llm_calls": 0, "provider_calls": 0,
                "cost_estimate_micros": 0, "currency": "USD", "cost_entry_ids": [],
            },
            "error": None,
            "next_action": {
                "type": "CONTINUE", "wait_reason": None, "escalation_level": None,
                "reason": "plumbing",
            },
            "downstream_agent": None,
            "timestamp": now_z(),
        }
    )  # fmt: skip


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


# ---------------------------------------------------------------------------------------------
# registry, schemas, job documents
# ---------------------------------------------------------------------------------------------
class _RealClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic_ms(self) -> int:
        return int(time.monotonic() * 1000)


class PlumbingRegistry:
    """Stand-ins for every stage but the S7 ``ApprovalWorker`` and the real agent_13 entry point."""

    def __init__(self, stand: StandIns, approval: ApprovalWorker, delivery: DeliveryStage) -> None:
        self.stand, self.approval, self.delivery = stand, approval, delivery
        self.table = BuilderTable()

    def worker_for(self, stage: Any) -> Any:
        if stage.task_type == "svc_s07.request_approval":
            return self.approval
        if stage.task_type == "agent_13.file_delivery":
            return self.delivery
        return self.stand

    def builder_for(self, stage: Any) -> BuilderTable:
        return self.table


def build_plumbing_registry(
    storage: LocalDiskStorage, approval: ApprovalWorker, scratch: Path | None
) -> PlumbingRegistry:
    return PlumbingRegistry(
        StandIns(storage), approval, DeliveryStage(storage, _RealClock(), scratch_root=scratch)
    )


def plumbing_schemas() -> PayloadSchemaRegistry:
    """The GLOBAL registry (every name the allow-list registers), nothing added. The outputs of
    the stand-in stages use a permissive model (they carry only what the downstream builders read);
    the delivery and approval outputs, which are the real ones, and every input keep the
    registered model."""
    from pydantic import BaseModel, ConfigDict

    class Open(BaseModel):
        model_config = ConfigDict(extra="allow")

    glob = PayloadSchemaRegistry()
    load_payload_schema_plugins(glob)
    reg = PayloadSchemaRegistry()
    real_outputs = {"agent_13.file_delivery.output", "svc_s07.request_approval.output"}
    for name in sorted(glob.names()):
        found = glob.resolve(name, "1.0.0")  # the registered version of this major
        stand_in = name.endswith(".output") and name not in real_outputs
        reg.register(name, found.version, Open if stand_in else found.model)
    return reg


_JOB_DOCS: Mapping[str, Mapping[str, Any]] = {
    "brand_kit": {
        "intro_ref": "sting_a", "intro_duration_ms": 1200, "outro_ref": None,
        "lower_third_template_ref": None,
    },
    "profile": {"placeholder": "compliance_profile"},
    "yt": {"placeholder": PLUMBING_CATEGORY_RULE_PACK},
    "template": {
        "segments": [{"section_role": "HOOK", "text": "Today we explore {topic} in simple steps."}],
        "shot_types": ["CHART"],
    },
    "dictionary": {"dictionary_key": "dry-run-dict", "version": 1, "entries": []},
}  # fmt: skip
"""Invented contents of the job-level documents of a plumbing run (not book text, not a brand)."""


def _put_doc(storage: LocalDiskStorage, org: str, name: str, doc: Mapping[str, Any]) -> DocRef:
    uri = blob_uri(org, "assets", f"{new_id(Prefix.ASSET)}/{name}")  # type: ignore[arg-type]
    info = storage.put(
        TenantContext(org, "agent_01", None),  # type: ignore[arg-type]
        BlobUri(uri),
        io.BytesIO(json.dumps(doc, sort_keys=True).encode()),
    )
    return DocRef(str(info.uri), info.sha256)


def seed_job_documents(storage: LocalDiskStorage, job: JobFacts) -> JobDocuments:
    """The plumbing job documents, stored write-once in the tenant's ``assets`` area."""
    org = job.org_id
    return JobDocuments(
        brand_kit=_put_doc(storage, org, "brand_kit.json", _JOB_DOCS["brand_kit"]),
        compliance_profile=_put_doc(storage, org, "profile.json", _JOB_DOCS["profile"]),
        rule_packs={
            PLUMBING_CATEGORY_RULE_PACK: RulePackDoc(
                new_id(Prefix.RULE_PACK),
                1,
                _put_doc(storage, org, "yt.json", _JOB_DOCS["yt"]),
            )
        },
        voice_id=new_id(Prefix.VOICE),
        voice_dictionary=_put_doc(
            storage, org, "dictionary.json", {**_JOB_DOCS["dictionary"], "language": job.language}
        ),
        uniqueness_template=_put_doc(storage, org, "template.json", _JOB_DOCS["template"]),
    )


# ---------------------------------------------------------------------------------------------
# build services (cost report, delivery facts)
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DeliveryLimits:
    max_file_bytes: int
    max_total_bytes: int
    max_thumbnail_bytes: int


class PlumbingServices:
    """``BuildServices`` of a plumbing run: an empty cost report and the delivery policy values with
    the plumbing banner. The limits are configuration (``run_entry.json``), not literals."""

    def __init__(self, limits: DeliveryLimits) -> None:
        self._limits = limits

    def read_json(self, uri: str, sha256: str) -> Mapping[str, Any]:
        raise NotImplementedError("document reads are served by the runner's own TaskIo")

    def payload_document(self, job: JobFacts, output: TaskOutput) -> DocRef:
        raise NotImplementedError("payload documents are served by the runner's own TaskIo")

    def cost_report(self, job: JobFacts) -> Mapping[str, Any]:
        return {
            "job_id": job.job_id, "production_type_key": job.production_type_key.value,
            "production_type_version": str(job.production_type_version), "topic_ref": None,
            "query_scope": "JOB", "figure_kind_summary": "ESTIMATE", "price_refs": {},
            "generated_at": now_z(), "run_mode": "TEST", "currency": job.currency, "rows": [],
            "total_micros": 0, "total_minor": 0, "terms_micros": {}, "allocated": [],
            "human_review_minutes": 0, "budgets": [], "header_budget": {},
        }  # fmt: skip

    def delivery_facts(self, job: JobFacts) -> Mapping[str, Any]:
        return {
            "config_version": "plumbing",
            "banner": BANNER,
            "disclaimer": {"text": BANNER, "version": "plumbing", "status_label": "TEST"},
            "disclosure_note": BANNER,
            "limits": {
                "max_file_bytes": self._limits.max_file_bytes,
                "max_total_bytes": self._limits.max_total_bytes,
                "max_thumbnail_bytes": self._limits.max_thumbnail_bytes,
            },
        }


# ---------------------------------------------------------------------------------------------
# the dry-run approval desk and its TEST_FIXTURE evidence (DRY_RUN only)
# ---------------------------------------------------------------------------------------------
class DryRunEvidence:
    """In-memory evidence of the dry-run desk. Every row is ``TEST_FIXTURE``: the approval binding
    accepts it in a dry run and refuses it in a real run. Serves both reader shapes (``get`` by
    evidence ID, ``approved`` by approval ID and subject hash)."""

    def __init__(self) -> None:
        self.rows: dict[str, ApprovalEvidenceStatus] = {}
        self._by_approval: dict[str, str] = {}

    def record(
        self, org_id: str, subject_kind: str, subject_id: str, *, approval_id: str, sha256: str,
        decision: str,
    ) -> str:  # fmt: skip
        evidence_id = str(OWNER_EVIDENCE.new())
        self.rows[evidence_id] = ApprovalEvidenceStatus(
            evidence_id=evidence_id, evidence_state="CONFIRMED", recorded_from=OWNER_CHAT_OPERATOR,
            org_id=org_id, kind=APPROVAL_DECISION, subject_kind=subject_kind,
            subject_id=subject_id, subject=None, source_kind=EvidenceSourceKind.TEST_FIXTURE,
            mac_valid=True, approval_id=approval_id, step_no=1, decision=decision,
            subject_sha256=sha256, review_code="TEST", parsed_target_stage_id=None,
        )  # fmt: skip
        self._by_approval[approval_id] = evidence_id
        return evidence_id

    def of_approval(self, approval_id: str) -> str | None:
        return self._by_approval.get(approval_id)

    def get(self, evidence_id: str) -> EvidenceStatus | None:
        return self.rows.get(evidence_id)

    def approved(self, approval_id: str, subject_sha256: str) -> ApprovalEvidenceStatus | None:
        row = self.rows.get(self._by_approval.get(approval_id, ""))
        if row is None or row.subject_sha256 != subject_sha256 or row.decision != "APPROVED":
            return None
        return row


@dataclass
class DryRunDesk:
    """S7 stand-in for a DRY_RUN: the owner's decision exists only after ``decide(task_id)`` (the
    boundary stays: the desk never infers one). The decision is a TEST decision, not an owner
    confirmation, and its evidence is ``TEST_FIXTURE``."""

    state: str = "APPROVED"
    evidence: DryRunEvidence = field(default_factory=DryRunEvidence)
    decisions: set[str] = field(default_factory=set)
    _approval_of_task: dict[str, str] = field(default_factory=dict)

    def _payload(self, task_input: TaskInput, ctx: ExecContext, state: str) -> Mapping[str, object]:
        data = task_input.payload.data or {}
        subject = data.get("subject") or {}
        sha256 = str(subject.get("sha256", "0" * 64))
        task = str(ctx.task_id)
        approval_id = self._approval_of_task.setdefault(task, str(APPROVAL.new()))
        decided = state in {"APPROVED", "REJECTED", "CHANGES_REQUESTED"}
        evidence_ids: list[str] = []
        known = self.evidence.of_approval(approval_id)
        if decided and known is not None:
            evidence_ids = [known]  # one decision, one evidence row, however often it is read
        elif decided:
            evidence_ids = [
                self.evidence.record(
                    str(task_input.org_id), str(subject.get("kind", "")),
                    str(subject.get("id", "")), approval_id=approval_id, sha256=sha256,
                    decision=state,
                )
            ]  # fmt: skip
        return {
            "approval_id": approval_id,
            "approval_kind": str(data.get("approval_kind", "FINAL_VIDEO")),
            "state": state,
            "subject_sha256": sha256,
            "evidence_ids": evidence_ids,
            "parsed_target_stage_id": "s05_script" if state == "CHANGES_REQUESTED" else None,
        }

    def open(self, task_input: TaskInput, ctx: ExecContext) -> Mapping[str, object]:
        return self._payload(task_input, ctx, "PENDING")

    def decision(self, task_input: TaskInput, ctx: ExecContext) -> Mapping[str, object] | None:
        if str(ctx.task_id) not in self.decisions:
            return None
        return self._payload(task_input, ctx, self.state)

    def decided(self, job_id: str, task_id: str) -> bool:
        return task_id in self.decisions

    def decide(self, task_id: str) -> None:
        """The dry-run owner decision (a TEST decision, never an owner confirmation)."""
        self.decisions.add(task_id)
