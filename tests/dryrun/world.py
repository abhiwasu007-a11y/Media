# ruff: noqa: E501
# mypy: disable-error-code="arg-type,attr-defined,unused-ignore,var-annotated,index,no-untyped-call,misc,union-attr"
# (throw-away dry-run fixtures feed fakes and dataset dicts into typed APIs)
"""The PLUMBING dry-run world: one executor per 3A task type, the TEST approval desk and the
file-delivery stage (``s13_deliver`` -> lane S2's ``amw_delivery.bundle.build_bundle``).

PLUMBING TEST - NOT QUALITY. Fakes only (scripted LLM, tone TTS, code-made graphics), real
FFmpeg render / QC, real Pillow+Raqm thumbnails, real R14 verifier code on TEST events.
"""

import json
import shutil
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from amw_core.contracts import NextAction, OutputRef, ResourceUsage, Stage, TaskOutput
from amw_core.contracts.common import PayloadObject
from amw_core.cost.report import CostStageReport
from amw_core.enums import ComplianceVerdict, NextActionType, OutputRefKind, OutputStatus
from amw_core.interfaces import TenantContext
from amw_core.storage.local import LocalDiskStorage
from amw_delivery.bundle import build_bundle
from amw_delivery.models import (
    ArtefactRef,
    BundleInputs,
    BundleLimits,
    ComplianceInfo,
    DisclaimerInfo,
    GateRow,
    QcCheckRow,
    ScoreRow,
    ScoreSource,
    SubtitleFile,
    ThumbnailOption,
)
from amw_delivery.testing import PLUMBING_VERTICAL_SPEC
from amw_delivery.vertical import VerticalSpec, make_9x16
from amw_orchestrator.executor import StageCall, StageExecutor
from amw_orchestrator.metering import Meter
from tests.dryrun.base import World, upstream, upstream_data
from tests.dryrun.kit import PLUMBING, Blobs, WallClock
from tests.dryrun.runtime_iface import get_disclaimer
from tests.dryrun.stage_04 import ResearchExecutor
from tests.dryrun.stage_05 import ScriptExecutor
from tests.dryrun.stage_06 import FactExecutor
from tests.dryrun.stage_07 import MasterExecutor, VoiceExecutor
from tests.dryrun.stage_08 import AssetsExecutor
from tests.dryrun.stage_09 import PlanExecutor
from tests.dryrun.stage_10 import EditorExecutor
from tests.dryrun.stage_11 import ThumbsExecutor
from tests.dryrun.stage_16 import PLACEHOLDER_SCORES, ComplianceExecutor

GATE_STAGES = (
    "s04_research",
    "s06_claims",
    "s06_verify",
    "s07_master",
    "s08_assets",
    "s06_chart",
    "s10_qc",
    "s11_thumbs",
    "s02u_unique",
    "s16_comp",
    "s16_score",
    "s16_auth",
)


class _ChartSkip:
    """``s06_chart`` with no chart claim: Agent 06 still runs (mode CHART_FACTS)."""


class Registry:
    def __init__(
        self, world: World, *, ms_per_char: int, size: tuple[int, int], deliver: StageExecutor
    ) -> None:
        research = ResearchExecutor(world)
        fact = FactExecutor(world, research.chunk_text)
        self.compliance = ComplianceExecutor(world)
        self._by_type: dict[str, StageExecutor] = {
            "agent_04.research_pack": research,
            "agent_05.script_draft": ScriptExecutor(world, research.chunk_text),
            "agent_06.claim_extraction": fact,
            "agent_06.claim_verification": fact,
            "agent_07.voice_synthesis": VoiceExecutor(world, ms_per_char),
            "agent_07.audio_master": MasterExecutor(world),
            "agent_09.shot_plan": PlanExecutor(world),
            "agent_08.asset_sourcing": AssetsExecutor(world, *size),
            "agent_10.render": (editor := EditorExecutor(world)),
            "agent_10.subtitles": editor,
            "agent_10.technical_qc": editor,
            "agent_11.thumbnail_variants": ThumbsExecutor(world),
            "svc_s02.uniqueness_check": self.compliance,
            "agent_16.compliance_gate": self.compliance,
            "agent_16.quality_score": self.compliance,
            "agent_16.publication_authorisation": self.compliance,
            "agent_13.file_delivery": deliver,
        }
        self.overrides: dict[str, StageExecutor] = {}

    def executor_for(self, stage: Stage) -> StageExecutor:
        return self.overrides.get(stage.stage_id) or self._by_type[stage.task_type]


class TestOperatorDesk:
    """S7 TEST OPERATOR PATH (dry run only): the owner's FINAL_VIDEO decision, contribution and
    scores are TEST session events recorded by the operator through the R14 harness (real
    verifier and Agent 16 evidence code). ``owner_says`` controls what the TEST owner answers."""

    def __init__(self, compliance: ComplianceExecutor, owner_says: str = "APPROVE") -> None:
        self.c = compliance
        self.owner_says = owner_says
        self.opened: list[dict[str, object]] = []
        self.decided: dict[str, dict[str, Any]] = {}

    def open(self, call: StageCall) -> Mapping[str, object]:
        doc = {
            "approval_kind": "FINAL_VIDEO",
            "workflow_key": "owner_one_tap",
            "review_code": "R7K2",
            "state": "PENDING",
            "label": PLUMBING,
        }
        self.opened.append(doc)
        return doc

    def decision(self, call: StageCall) -> Mapping[str, object] | None:
        if not self.opened:
            return None
        if call.task_id not in self.decided:
            if self.owner_says != "APPROVE":
                self.decided[call.task_id] = {"state": "REJECTED", "label": PLUMBING}
            else:
                rec = self.c.record_final_approval(call)
                state = "APPROVED" if all(s == "CONFIRMED" for s in rec["states"]) else "PENDING"
                self.decided[call.task_id] = {"state": state, **rec}
        return self.decided[call.task_id]


class DeliveryExecutor:
    """``s13_deliver``: the S2 bundle builder over the stored artefacts (file destination)."""

    def __init__(
        self,
        world: World,
        out_dir: Path,
        cost_report: Callable[[str], CostStageReport],
        desk: Callable[[], TestOperatorDesk],
        vertical: VerticalSpec | None = None,
    ) -> None:
        self.w, self.out_dir, self.cost_report, self.desk = world, out_dir, cost_report, desk
        self.vertical = vertical or PLUMBING_VERTICAL_SPEC
        self.manifest: Any = None

    def _ref(self, uri: str, sha: str) -> ArtefactRef:
        head = self.w.blobs.storage.head(self.w.blobs.ctx, uri)  # type: ignore[arg-type]
        return ArtefactRef(uri=uri, sha256=sha, size_bytes=head.size_bytes or 0)

    def execute(self, call: StageCall) -> TaskOutput:
        render = upstream_data(call, "s10_render")
        r = render["render_ref"]
        video = self._ref(r["uri"], r["sha256"])
        subs = upstream(call, "s10_subs")
        srt = next(x for x in subs.output_refs if x.uri.endswith(".srt"))
        thumbs = [
            x for x in upstream(call, "s11_thumbs").output_refs if x.media_type == "image/png"
        ]
        vertical = None
        if call.job.owner_topic.shorts_wanted:
            src = self.w.blobs.local_path(r["uri"])
            work = self.w.scratch / "vertical"
            work.mkdir(parents=True, exist_ok=True)
            tmp = work / "cut_9x16.mp4"
            tmp.unlink(missing_ok=True)
            make_9x16(src, tmp, self.vertical, subtitles_srt=self.w.blobs.local_path(srt.uri))
            uri, sha = self.w.blobs.put_bytes(
                "jobs",
                f"{call.job.job_id}/deliveries/cut_9x16_{call.task_id}.mp4",
                tmp.read_bytes(),
            )
            vertical = self._ref(uri, sha)
        qc = upstream(call, "s10_qc")
        score = upstream_data(call, "s16_score")
        comp = upstream_data(call, "s16_comp")
        auth = upstream_data(call, "s16_auth")
        disc = get_disclaimer("v1")
        rows = [
            ScoreRow(
                dimension=d["dimension"],
                source=ScoreSource.MACHINE,
                max_points=Decimal(str(d["max_points"])),
                points=Decimal(str(d["points"])),
                evidence="PLUMBING scripted judge / deterministic checks",
            )
            for d in score["dimensions"]
        ]
        maxes = {d["dimension"]: Decimal(str(d["max_points"])) for d in score["dimensions"]}
        for dim, pts in PLACEHOLDER_SCORES:
            rows.append(
                ScoreRow(
                    dimension=dim.value,
                    source=ScoreSource.HUMAN,
                    max_points=maxes.get(dim.value, Decimal(pts)),
                    points=min(Decimal(pts), maxes.get(dim.value, Decimal(pts))),
                    evidence="PLUMBING TEST placeholder human score (R14 TEST event), NOT the owner's",
                )
            )
        gates = []
        for sid in GATE_STAGES:
            o = call.upstream.get(sid)
            if o is None:
                continue
            failed = [
                v.check_id
                for v in o.validation_results
                if v.gate and v.blocking and v.verdict.value == "FAIL"
            ]
            gates.append(GateRow(gate_id=sid, passed=not failed, remedy=", ".join(failed) or None))
        inputs = BundleInputs(
            org_id=call.job.org_id,
            job_id=call.job.job_id,
            production_type_key=call.job.production_type_key.value,
            production_type_version=str(call.job.production_type_version),
            config_version="dryrun-plumbing-1",
            metadata_present=False,
            banner=PLUMBING,
            disclaimer=DisclaimerInfo(
                text=disc.text, version=disc.version, status_label=disc.status
            ),
            disclosure_note=(
                f"Disclosure decision: {comp['disclosure']['decision']}. The owner applies the "
                "altered or synthetic content label by hand in YouTube Studio (13 section 3.3)."
            ),
            video_16x9=video,
            video_9x16=vertical,
            shorts_wanted=call.job.owner_topic.shorts_wanted,
            thumbnails=tuple(
                ThumbnailOption(
                    option_id=f"v{i + 1}", ref=self._ref(t.uri, t.sha256), media_type="image/png"
                )
                for i, t in enumerate(thumbs)
            ),
            chosen_thumbnail_id="v1",
            subtitles=(
                SubtitleFile(language=call.job.language, ref=self._ref(srt.uri, srt.sha256)),
            ),
            primary_language=call.job.language,
            qc_checks=tuple(
                QcCheckRow(
                    check_id=v.check_id,
                    verdict=v.verdict.value,
                    measured=None if v.measured is None else str(v.measured),
                    threshold=None if v.threshold is None else str(v.threshold),
                    unit=v.unit,
                )
                for v in qc.validation_results
            ),
            score_rows=tuple(rows),
            gates=tuple(gates),
            compliance=ComplianceInfo(
                verdict=ComplianceVerdict(comp["verdict"]),
                authorised_for_delivery=auth["verdict"] == "ALLOWED"
                and auth["authorised_action"] == "DELIVERY",
                authorisation_verdict_id=auth["authorisation_verdict_id"],
                render_sha256=r["sha256"],
            ),
            cost_report=self.cost_report(call.job.job_id),
            limits=BundleLimits(
                max_file_bytes=2_000_000_000,
                max_total_bytes=4_000_000_000,
                max_thumbnail_bytes=50_000_000,
            ),
        )
        self.out_dir.mkdir(parents=True, exist_ok=True)
        manifest = build_bundle(
            inputs, self.out_dir, storage=self.w.blobs.storage, context=self.w.blobs.ctx
        )
        self.manifest = manifest
        doc = manifest.model_dump(mode="json")
        return TaskOutput(
            status=OutputStatus.SUCCEEDED,
            payload=PayloadObject(
                payload_schema="agent_13.file_delivery.output",
                payload_schema_version="1.0.0",
                data=doc,
            ),
            output_refs=(),
            quality_score=None,
            confidence=None,
            validation_results=(),
            duration=0,
            resource_usage=ResourceUsage(
                cpu_ms=0,
                peak_rss_bytes=0,
                tokens_in=0,
                tokens_out=0,
                tokens_cached_in=0,
                llm_calls=0,
                provider_calls=0,
                cost_estimate_micros=0,
                currency="USD",
                cost_entry_ids=(),
            ),
            error=None,
            next_action=NextAction(
                type=NextActionType.CONTINUE,
                wait_reason=None,
                escalation_level=None,
                reason="bundle written",
            ),
            downstream_agent=None,
            timestamp=datetime.now(UTC),
        )


def build_world(out: Path, meter: Meter, org_id: str, *, scale: str) -> World:
    blobs = out / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)
    scratch = out / "scratch"
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True)
    return World(
        Blobs(LocalDiskStorage(blobs.resolve()), org_id),
        meter,
        WallClock(),
        scratch.resolve(),
        render_scale=scale,
    )


_ = (json, OutputRef, OutputRefKind, TenantContext)
