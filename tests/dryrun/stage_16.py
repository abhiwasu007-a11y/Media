# ruff: noqa: E501, RUF059
# mypy: disable-error-code="arg-type,attr-defined,unused-ignore,var-annotated"
# mypy: disable-error-code="index,no-untyped-call,misc,union-attr"
# (throw-away dry-run fixtures feed fakes and dataset dicts into typed APIs)
"""``s02u_unique`` / ``s16_comp`` / ``s16_score`` / ``a_final`` / ``s16_auth`` -> Agent 16 (+S7).

Integration findings handled here (see the dry-run report):
* ``GateFactExtractor`` and ``UniquenessExtractor`` are Protocols with no implementation in the
  package: the dry run ships MINIMAL extractors that read the real upstream documents
  (script segments, extraction claims, asset manifest, QC rows); facts the documents do not
  carry are stated as constants below and listed in the report.
* ``agent_16.quality_score`` has no stage entry point (only ``QualityScorer``): wrapped here.
* Approvals (R14): the owner's decisions are TEST session events in the agents' own R14
  harness (fake evidence database with its three login roles, real ``EvidenceVerifierService``
  and Agent 16 ``OwnerEvidenceVerifier`` incl. MAC checks). Every quote says PLUMBING TEST; no
  production rule is relaxed. Human scores are PLACEHOLDER numbers, not the owner's scores.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

from agent_16_compliance_qa.assembler import ExtractedGate, GateInputAssembler
from agent_16_compliance_qa.authorisation.stage import (
    ApprovalRow,
    AuthorisationInput,
    ContributionRow,
    GateSummary,
    HumanScoreRow,
    PublicationAuthorisationStage,
    RenderRow,
    ScoreSummary,
    StepRow,
)
from agent_16_compliance_qa.checks import rules as R  # noqa: N812
from agent_16_compliance_qa.gate import GateInputs, ItemClaim, Routing, SourceItem
from agent_16_compliance_qa.judge.models import PolicyInput, QualityOutput
from agent_16_compliance_qa.output import Usage, auth_payload, auth_results, build_task_output
from agent_16_compliance_qa.quality import GroupRequest, QualityScorer, score_payload
from agent_16_compliance_qa.scoring.aggregate import (
    ClaimFact,
    DeterministicInputs,
    GateFacts,
    QcRow,
    ScriptFacts,
    ThumbnailFacts,
)
from agent_16_compliance_qa.scoring.rubric import group_criteria
from agent_16_compliance_qa.stages import (
    ComplianceGateStage,
    GateStageDeps,
    UniquenessCheckStage,
    UniquenessFacts,
    UniquenessStageDeps,
)
from agent_16_compliance_qa.uniqueness import Segment
from agent_16_compliance_qa.verdicts import VerdictWriter
from amw_core import ids
from amw_core.contracts import OutputRef, TaskOutput
from amw_core.enums import (
    ApprovalChannel,
    ApprovalKind,
    ApprovalState,
    ApprovalStepState,
    ClaimStatus,
    ComplianceVerdict,
    DisclosureDecision,
    EditorialContributionType,
    EvidenceRecordKind,
    OutputRefKind,
    PresenterKind,
    QualityDimension,
    RenderStatus,
)
from amw_orchestrator.executor import StageCall
from amw_orchestrator.metering import MeteredLlm
from tests.agents.agent_16_compliance_qa.r14_support import CODE, R14, REQUESTED
from tests.agents.agent_16_compliance_qa.support import PROMPTS, Breaker, Budget, config
from tests.agents.agent_16_compliance_qa.test_gate import frames_clean, packs, policy_reply
from tests.agents.agent_16_compliance_qa.test_stages import Approvals, Store, Tenancy
from tests.dryrun.base import World, task_input, upstream, upstream_data
from tests.dryrun.kit import PLUMBING, ListAudit, MirrorLedger, ref_ending
from tests.dryrun.llm import ScriptedLlm

OP = "sys_operator"
CH = ApprovalChannel.OWNER_CHAT_OPERATOR
CONTRIBUTION = "PLUMBING TEST placeholder example card added to section one"
PLACEHOLDER_SCORES = (
    (QualityDimension.RESEARCH_ACCURACY, 18),
    (QualityDimension.STORYTELLING, 13),
    (QualityDimension.AUDIENCE_VALUE, 13),
    (QualityDimension.VISUAL_QUALITY, 13),
    (QualityDimension.AUDIO_QUALITY, 9),
    (QualityDimension.EDITING_QUALITY, 8),
    (QualityDimension.THUMBNAIL_METADATA, 8),
)
"""PLUMBING TEST PLACEHOLDER human scores (the R14 harness fixture values), NOT the owner's:
without human rows G9 (>= 85) refuses delivery, which the budget/negative tests also show."""


def _policy(request: Any) -> str:
    payload = request.messages[0].content.split("<<<INPUT\n", 1)[1].split("\nINPUT>>>")[0]
    doc = json.loads(payload)
    if "checks_requested" in doc:
        return frames_clean(doc).model_dump_json()
    return policy_reply(PolicyInput.model_validate(doc)).model_dump_json()


def _quality_judge(payload: Any) -> QualityOutput:
    """PLUMBING scripted judge: half points per judged criterion (NOT a quality judgement)."""
    group = payload["group_id"]
    return QualityOutput.model_validate(
        {
            "group_id": group,
            "scores": [
                {
                    "criterion_id": c.criterion_id,
                    "points": c.max_points // 2,
                    "max_points": c.max_points,
                    "evidence_refs": ["s01"],
                    "why_not_higher": "PLUMBING scripted judge",
                }
                for c in group_criteria(group)
            ],
            "check_results": [],
            "injection_suspected": [],
            "refusal": None,
        }
    )


def _script(w: World, call: StageCall) -> tuple[dict[str, Any], Any]:
    stage = "s05_shorts" if "s05_shorts" in call.upstream else "s05_script"
    ref = ref_ending(upstream(call, stage), ".json")
    return w.blobs.read_json(ref.uri, ref.sha256), ref


class _UniqExtractor:
    """Minimal real extractor: section roles and texts of the script, shot intents of the plan."""

    def __init__(self, script: dict[str, Any], shots: Sequence[str]) -> None:
        self.script, self.shots = script, tuple(shots)

    def extract(self, blobs: Mapping[str, bytes]) -> UniquenessFacts:
        segs = tuple(
            Segment(section_role=s["kind"], text=s["text"]) for s in self.script["segments"]
        )
        return UniquenessFacts(
            script=segs, template=(), shots=self.shots, template_shots=(), complete=True
        )


class _NoPriors:
    def prior_scripts(self, tx: Any, channel_id: str, limit: int) -> Sequence[tuple[Segment, ...]]:
        return []


class _GateExtractor:
    """Minimal real extractor of the gate facts from the stored upstream documents."""

    def __init__(self, facts: GateInputs) -> None:
        self.facts = facts

    def extract(
        self, request: Any, blobs: Mapping[str, bytes], evaluation_date: date
    ) -> ExtractedGate:
        return ExtractedGate(
            inputs=self.facts.model_copy(update={"evaluation_date": evaluation_date}),
            method_release_approvals={},
            quotation_approvals={},
        )


class ComplianceExecutor:
    def __init__(self, world: World) -> None:
        self.w = world
        self.store = Store()
        self.h: R14 | None = None
        self.approval_ids: dict[str, str] = {}

    # -- helpers ---------------------------------------------------------------------------------
    def _refs(self, call: StageCall) -> dict[str, dict[str, str]]:
        doc, sref = _script(self.w, call)
        out: dict[str, dict[str, str]] = {"script_ref": {"uri": sref.uri, "sha256": sref.sha256}}

        def first(stage: str, suffix: str = "") -> dict[str, str] | None:
            o = call.upstream.get(stage)
            if o is None or not o.output_refs:
                return None
            r = next((x for x in o.output_refs if x.uri.endswith(suffix)), o.output_refs[0])
            return {"uri": r.uri, "sha256": r.sha256}

        plan = upstream_data(call, "s09_plan")["plan_ref"]
        out["shot_plan_ref"] = {"uri": plan["uri"], "sha256": plan["sha256"]}
        for name, stage, suffix in (
            ("claims_ref", "s06_claims", "claim_extraction_output.json"),
            ("verification_ref", "s06_verify", "claim_verification_output.json"),
            ("asset_manifest_ref", "s08_assets", "sourcing.json"),
            ("render_qc_ref", "s10_qc", ""),
            ("voice_ref", "s07_voice", "timeline.json"),
            ("thumbnails_ref", "s11_thumbs", ".json"),
            ("uniqueness_ref", "s02u_unique", ""),
            ("research_pack_ref", "s04_research", "research_pack.json"),
            ("frames_ref", "s10_qc", ".png"),
        ):
            ref = first(stage, suffix) or first(f"parent.{stage}", suffix)
            if ref is not None:
                out[name] = ref
        return out

    def _render(self, call: StageCall) -> tuple[str, str]:
        r = upstream_data(call, "s10_render")
        return r["render_id"], r["render_ref"]["sha256"]

    # -- stages ----------------------------------------------------------------------------------
    def execute(self, call: StageCall) -> TaskOutput:
        tt = call.stage.task_type
        if tt == "svc_s02.uniqueness_check":
            return self._uniqueness(call)
        if tt == "agent_16.compliance_gate":
            return self._gate(call)
        if tt == "agent_16.quality_score":
            return self._score(call)
        if tt == "agent_16.publication_authorisation":
            return self._auth(call)
        raise KeyError(tt)

    def _uniqueness(self, call: StageCall) -> TaskOutput:
        doc, sref = _script(self.w, call)
        plan_view = upstream_data(call, "s09_plan")["views"]["agent_08_shots"]
        refs = self._refs(call)
        tpl_uri, tpl_sha = self.w.blobs.put_json(
            "assets", "templates/script_template_none.json", {"template": None, "note": PLUMBING}
        )
        payload = {
            "subject": {"script_id": doc["script_id"], "script_sha256": sref.sha256},
            "iteration": call.iteration,
            "channel_id": call.job.channel_id,
            "production_type_key": call.job.production_type_key.value,
            "routing": {
                "script_stage_id": "s05_shorts" if "s05_shorts" in call.upstream else "s05_script"
            },
            "inputs": {
                "script_ref": refs["script_ref"],
                "shot_plan_ref": refs["shot_plan_ref"],
                "thumbnails_ref": refs.get("thumbnails_ref", refs["shot_plan_ref"]),
                "template_ref": {"uri": tpl_uri, "sha256": tpl_sha},
            },
            "prior_window": {"max_prior_jobs": 5},
        }
        deps = UniquenessStageDeps(
            config=config(),
            tenancy=Tenancy(),
            storage=self.w.blobs.storage,
            audit=ListAudit(),
            clock=self.w.clock,
            store=self.store,
            source=_NoPriors(),
            extractor=_UniqExtractor(doc, [s["intent_kind"] for s in plan_view]),
        )
        ti = task_input(call, "svc_s02", "svc_s02.uniqueness_check.input", payload)
        return UniquenessCheckStage(deps).run(ti, call.attempt_id)

    def _gate_facts(self, call: StageCall) -> GateInputs:
        doc, _ = _script(self.w, call)
        claims = upstream_data(call, "s06_claims")["claims"]
        by_seg: dict[str, list[dict[str, Any]]] = {}
        for c in claims:
            by_seg.setdefault(c["segment_id"], []).append(c)
        items = [
            SourceItem(
                ref=s["segment_id"],
                surface="SCRIPT_SEGMENT",
                text=s["text"],
                claims=tuple(
                    ItemClaim(
                        claim_type=c["claim_type"],
                        time_reference_kind=c["time_reference_kind"],
                        rule_flags=(),
                    )
                    for c in by_seg.get(s["segment_id"], [])
                ),
            )
            for s in doc["segments"]
        ]
        manifest_ref = ref_ending(upstream(call, "s08_assets"), "sourcing.json")
        manifest = self.w.blobs.read_json(manifest_ref.uri, manifest_ref.sha256)
        licensed = [
            R.LicensedAsset(
                asset_ref=s["asset_id"],
                source_kind=s["source_type"],
                has_ledger_row=bool(s["ledger_entry_ids"]),
                licence_state="ACTIVE",
                covers_monetized_youtube=True,
                third_party_permission="NOT_APPLICABLE",
            )
            for s in manifest["shots"]
            if s.get("asset_id")
        ]
        disclosure = [
            R.DisclosureAsset(
                asset_ref=s["asset_id"],
                tier=s["tier"],
                is_realistic_synthetic=s["disclosure"]["is_realistic_synthetic"],
                realistic_person=s["disclosure"]["depicts_real_person"],
            )
            for s in manifest["shots"]
            if s.get("asset_id")
        ]
        uniq = upstream_data(call, "s02u_unique")["verdict"]
        return GateInputs.model_validate(
            {
                "channel_category": "finance",
                "language": call.job.language,
                "sensitive_channel": True,
                "routing": Routing(
                    script_stage_id="s05_script",
                    assets_stage_id="s08_assets",
                    thumbnails_stage_id="s11_thumbs" if "s11_thumbs" in call.upstream else None,
                ),
                "items": items,
                "charts": [],
                "text_prices": [],
                "disclaimer_spoken": any(s["kind"] == "DISCLAIMER" for s in doc["segments"]),
                "disclaimer_onscreen": True,  # Agent 09 plans DISCLAIMER_CARD overlays (checked in QC)
                "disclaimer_template_version": doc["disclaimer_slots"][0]["template_version"]
                if doc.get("disclaimer_slots")
                else None,
                "metadata_present": False,
                "description_hash_matches": None,
                "method_segments": [],
                "method_label_overlay": False,
                "production_type_key": call.job.production_type_key.value,
                "live_format": "STANDARD",
                "metadata_terms": None,
                "presenter_kind": PresenterKind.NEUTRAL_NARRATION,
                "voice_known": True,
                "render_person_assets": [],
                "thumbnail_person_assets": [],
                "licensed_assets": licensed,
                "audience_kind": "GENERAL",
                "disclosure_assets": disclosure,
                "realism_shots": [],
                "voice_kind": "NEUTRAL_TTS",
                "frame_ids": self._frame_ids(call),
                "frames_payload": {
                    "checks_requested": ["qc.watermark.visual", "qc.visual.no_synthetic_presenter"]
                },
                "uniqueness_verdict": ComplianceVerdict(uniq),
                "evaluation_date": datetime.now(UTC).date(),
            }
        )

    def _frame_ids(self, call: StageCall) -> tuple[str, ...]:
        """Sample frame IDs of Agent 10's QC evidence pack (the frames the frames judge sees)."""
        qc = upstream_data(call, "s10_qc")
        ref = qc["evidence"]["manifest_ref"]
        manifest = self.w.blobs.read_json(ref["uri"], ref["sha256"])
        return tuple(f["frame_id"] for f in manifest["frames"])

    def _gate(self, call: StageCall) -> TaskOutput:
        doc, sref = _script(self.w, call)
        render_id, render_sha = self._render(call)
        h = self._harness(call, render_id)
        approvals = Approvals()
        approvals.render_sha[render_id] = render_sha
        from agent_16_compliance_qa.assembler import ApprovalStepVerifier

        cfg = config()
        audit = ListAudit()
        prompts = {
            k: (PROMPTS / f"{n}.v1.md").read_text(encoding="utf-8")
            for k, n in (
                ("policy", "compliance_gate"),
                ("paraphrase", "compliance_gate_paraphrase"),
                ("frames", "compliance_gate_frames"),
            )
        }

        class _Packs:
            loaded = packs()

            def load(self, tx: Any, channel_category: str) -> Any:
                return self.loaded

        deps = GateStageDeps(
            config=cfg,
            tenancy=Tenancy(),
            storage=self.w.blobs.storage,
            audit=audit,
            budget=Budget(),
            costs=MirrorLedger(),
            breaker=Breaker(),
            clock=self.w.clock,
            llm=MeteredLlm(ScriptedLlm(_policy), self.w.meter, 2_000),
            assembler=GateInputAssembler(
                self.w.blobs.storage,
                approvals,
                ApprovalStepVerifier(approvals, h.a16, cfg.accepted_channels),
                _GateExtractor(self._gate_facts(call)),
            ),
            evidence=h.a16,
            packs=_Packs(),
            writer=VerdictWriter(self.store, self.w.blobs.storage, audit),
            prompts=prompts,
            pack_texts={},
            prompt_ids=("agent_16/compliance_gate.v1",),
        )
        refs = self._refs(call)
        payload = {
            "subject": {
                "render_id": render_id,
                "render_sha256": render_sha,
                "script_id": doc["script_id"],
                "script_sha256": sref.sha256,
            },
            "iteration": call.iteration,
            "channel_category": "finance",
            "production_type_key": call.job.production_type_key.value,
            "destination_kinds": ["FILE_DELIVERY"],
            "evaluate_as_destination": "YOUTUBE",
            "owner_sebi_registration": "UNREGISTERED",
            "language": call.job.language,
            "routing": {
                "script_stage_id": "s05_script",
                "assets_stage_id": "s08_assets",
                "thumbnails_stage_id": "s11_thumbs" if "s11_thumbs" in call.upstream else None,
            },
            "inputs": refs | {"metadata_ref": None},
        }
        ti = task_input(call, "agent_16", "agent_16.compliance_gate.input", payload)
        return ComplianceGateStage(deps).run(ti, call.attempt_id)

    def _score(self, call: StageCall) -> TaskOutput:
        doc, _ = _script(self.w, call)
        qc_out = upstream(call, "s10_qc")
        verify = upstream_data(call, "s06_verify")
        gate = upstream_data(call, "s16_comp")
        thumbs = upstream(call, "s11_thumbs") if "s11_thumbs" in call.upstream else None
        n_thumbs = (
            sum(1 for r in thumbs.output_refs if r.media_type == "image/png") if thumbs else 0
        )
        det = DeterministicInputs(
            qc=tuple(
                QcRow(check_id=r.check_id, verdict=r.verdict) for r in qc_out.validation_results
            ),
            claims=tuple(
                ClaimFact(
                    claim_id=c["claim_id"],
                    claim_type="DEFINITION",
                    status=ClaimStatus(c["status"]),
                    has_citation_or_chart=bool(c.get("evidence")),
                )
                for c in verify["claims"]
            ),
            script=ScriptFacts(
                hook_options=len(doc.get("hook_options", [])),
                promise_fields_present=bool(doc.get("promise")),
                sections_with_takeaway=None,
                sections_with_example=None,
                section_count=len(doc.get("sections", [])),
                viewer_problem_addressed=None,
            ),
            thumbnails=ThumbnailFacts(
                variants=n_thumbs,
                required_variants=3,
                spec_ok=n_thumbs > 0,
                legible=None,
                title_length_ok=None,
            ),
            gate=GateFacts(
                overall=ComplianceVerdict(gate["verdict"]),
                licence_pass=True,
                disclosure_decision=gate.get("disclosure", {}).get("decision", "NOT_REQUIRED")
                if isinstance(gate.get("disclosure"), dict)
                else "NOT_REQUIRED",
                disclaimer_pass=True,
                finance=True,
            ),
        )
        meter = MeteredLlm(ScriptedLlm(lambda r: "{}"), self.w.meter, 2_000)

        def judge(payload: Any) -> QualityOutput:
            # one metered call per judged group (fake price), answer scripted
            from amw_adapters.llm import LlmMessage, LlmRequest

            meter.complete(
                LlmRequest(
                    model="fake-judge",
                    system="PLUMBING",
                    messages=(LlmMessage(role="user", content=json.dumps(payload)),),
                    max_output_tokens=10,
                ),
                idempotency_key=ids.make_idempotency_key(
                    call.job.org_id, "llm.call", [call.task_id, "judge", str(payload["group_id"])]
                ),
            )
            return _quality_judge(payload)

        routing = {
            "script_stage_id": "s05_script",
            "plan_stage_id": "s09_plan",
            "voice_stage_id": "s07_voice",
            "render_stage_id": "s10_render",
            "thumbnails_stage_id": "s11_thumbs",
        }
        groups = {
            g: GroupRequest(payload={"group_id": g}, known_refs=frozenset({"s01"}))
            for g in ("G1", "G2", "G3")
        }
        res = QualityScorer(config(), judge).score(det, groups, routing)
        data = score_payload(res, [], {"prompt": "agent_16/quality_score.v1", "note": PLUMBING})
        uri, sha = self.w.blobs.put_json(
            "jobs", f"{call.job.job_id}/tasks/{call.task_id}/quality_score.json", data
        )
        out = build_task_output(
            payload_schema="agent_16.quality_score.output",
            data=data,
            results=list(res.results),
            blob=None,
            usage=Usage(),
            now=datetime.now(UTC),
            currency="USD",
            quality_score=float(res.machine_total),
            verdict=ComplianceVerdict.ALLOWED,
            downstream=None,
        )
        body = self.w.blobs.read(uri, sha)
        return out.model_copy(
            update={
                "output_refs": (
                    OutputRef(
                        uri=uri,
                        kind=OutputRefKind.REPORT,
                        sha256=sha,
                        size_bytes=len(body),
                        media_type="application/json",
                    ),
                )
            }
        )

    # -- R14 TEST operator path ---------------------------------------------------------------------
    def _harness(self, call: StageCall, render_id: str) -> R14:
        if self.h is None or str(self.h.render) != render_id or str(self.h.org) != call.job.org_id:
            self.h = R14(org=call.job.org_id, render=render_id, job=call.job.job_id)  # type: ignore[arg-type]
        return self.h

    def record_final_approval(self, call: StageCall) -> dict[str, Any]:
        """TEST operator: records the PLUMBING owner messages through the R14 harness."""
        render_id, render_sha = self._render(call)
        h = self._harness(call, render_id)
        step = h.record(f"approve {CODE}")
        contrib = h.record(f"{CODE} {CONTRIBUTION}", EvidenceRecordKind.CONTRIBUTION)
        msg = CODE + " " + " ".join(f"{d.value.lower()} {p}" for d, p in PLACEHOLDER_SCORES)
        score = h.record(msg, EvidenceRecordKind.HUMAN_SCORE, claimed_scores=PLACEHOLDER_SCORES)
        self.approval = {
            "approval_id": str(h.approval),
            "review_code": CODE,
            "render_id": render_id,
            "render_sha256": render_sha,
            "step_evidence": str(step.id),
            "contribution_evidence": str(contrib.id),
            "score_evidence": str(score.id),
            "states": [step.state.value, contrib.state.value, score.state.value],
            "channel": CH.value,
            "recorded_by": OP,
            "label": f"{PLUMBING}: TEST operator path, TEST session events",
        }
        return self.approval

    def _auth(self, call: StageCall) -> TaskOutput:
        render_id, render_sha = self._render(call)
        h = self._harness(call, render_id)
        doc, sref = _script(self.w, call)
        app = self.approval
        thumbs = upstream(call, "s11_thumbs")
        t_sha = tuple(r.sha256 for r in thumbs.output_refs if r.media_type == "image/png")
        gate = upstream_data(call, "s16_comp")
        score = upstream_data(call, "s16_score")
        org = h.org
        repo = _AuthRepo()
        repo.approvals[h.approval] = ApprovalRow(
            h.approval,
            org,
            ApprovalKind.FINAL_VIDEO,
            ApprovalState.APPROVED,
            "render",
            h.render,
            render_sha,
            CODE,
            REQUESTED,
        )
        repo.steps_[h.approval] = [
            StepRow(
                h.approval,
                org,
                1,
                ApprovalStepState.APPROVED,
                h.owner,
                True,
                True,
                OP,
                CH,
                app["step_evidence"],
                f"step:{h.approval}:1",
            )
        ]
        repo.contribs = [
            ContributionRow(
                h.approval,
                org,
                EditorialContributionType.EXAMPLE,
                CONTRIBUTION,
                h.owner,
                OP,
                CH,
                app["contribution_evidence"],
                f"c:{app['contribution_evidence']}",
            )
        ]
        repo.scores = [
            HumanScoreRow(
                org,
                d,
                float(p),
                render_sha,
                h.owner,
                OP,
                CH,
                app["score_evidence"],
                f"s:{app['score_evidence']}",
            )
            for d, p in PLACEHOLDER_SCORES
        ]
        pack_rows = (
            tuple((p.rule_pack_id, p.version) for p in packs().rows)
            if hasattr(packs(), "rows")
            else ((ids.new_id(ids.Prefix.RULE_PACK), 1),)
        )
        repo.gate_ = GateSummary(
            org,
            ComplianceVerdict(gate["verdict"]),
            render_sha,
            sref.sha256,
            t_sha,
            pack_rows,
            (),
            0,
            DisclosureDecision.NOT_REQUIRED,
            ids.new_id(ids.Prefix.COMPLIANCE_VERDICT),
            (),
            None,
        )
        repo.score_ = ScoreSummary(
            org,
            render_sha,
            {QualityDimension(d["dimension"]): float(d["points"]) for d in score["dimensions"]},
        )
        repo.render_ = RenderRow(
            render_id, org, RenderStatus.QC_PASSED, render_sha, sref.sha256, t_sha, 0, True, 0
        )
        req = AuthorisationInput(
            subject={
                "render_id": render_id,
                "render_sha256": render_sha,
                "script_id": doc["script_id"],
                "script_sha256": sref.sha256,
                "thumbnail_set_sha256": t_sha,
            },
            iteration=call.iteration,
            approval_id=h.approval,
            gate_task_id=_task_of(call, "s16_comp"),
            score_task_id=_task_of(call, "s16_score"),
            requested_action="DELIVERY",
            intended_publish_date_utc=None,
            pack_versions=[{"rule_pack_id": p, "version": v} for p, v in pack_rows],
        )
        stage = PublicationAuthorisationStage(config(), repo, h.a16, _Writer(), ListAudit())
        res = stage.run(h.tx("agent_16"), req, datetime.now(UTC), call.idempotency_key)
        d = res.decision
        payload = auth_payload(
            d,
            req.subject.model_dump(mode="json"),
            datetime.now(UTC).date(),
            res.earliest_compliant_publish_date,
            res.authorisation_verdict_id,
            res.disclosure_verdict_id,
            res.evidence_ids,
            f"amw-blob://{org}/evidence/{call.job.job_id}/auth.json",
        )
        return build_task_output(
            payload_schema="agent_16.publication_authorisation.output",
            data=payload,
            results=auth_results(d),
            blob=None,
            usage=Usage(),
            now=datetime.now(UTC),
            currency="USD",
            quality_score=d.human_wins_total,
            verdict=d.verdict,
            downstream="agent_13",
        )


def _task_of(call: StageCall, stage_id: str) -> str:
    return call.upstream_task_ids[stage_id]


class _AuthRepo:
    def __init__(self) -> None:
        self.approvals: dict[str, ApprovalRow] = {}
        self.steps_: dict[str, list[StepRow]] = {}
        self.contribs: list[ContributionRow] = []
        self.scores: list[HumanScoreRow] = []
        self.verdicts: list[Any] = []
        self.gate_: GateSummary | None = None
        self.score_: ScoreSummary | None = None
        self.render_: RenderRow | None = None

    def approval(self, tx: Any, approval_id: str) -> ApprovalRow | None:
        return self.approvals.get(approval_id)

    def steps(self, tx: Any, approval_id: str) -> Sequence[StepRow]:
        return self.steps_.get(approval_id, [])

    def contributions(self, tx: Any, approval_id: str) -> Sequence[ContributionRow]:
        return [c for c in self.contribs if c.approval_id == approval_id]

    def human_scores(self, tx: Any, render_id: str) -> Sequence[HumanScoreRow]:
        return self.scores

    def human_verdicts(self, tx: Any, gate_task_id: str) -> Sequence[Any]:
        return self.verdicts

    def gate(self, tx: Any, gate_task_id: str) -> GateSummary | None:
        return self.gate_

    def score(self, tx: Any, score_task_id: str) -> ScoreSummary | None:
        return self.score_

    def render(self, tx: Any, render_id: str) -> RenderRow | None:
        return self.render_

    def destination(self, tx: Any) -> str:
        return "FILE_DELIVERY"


class _Writer:
    def __init__(self) -> None:
        self.rows: dict[str, str] = {}

    def write_final(self, tx: Any, subject: Any, decision: Any, idempotency_key: str) -> str:
        return self.rows.setdefault(idempotency_key, ids.new_id(ids.Prefix.COMPLIANCE_VERDICT))


_ = hashlib
