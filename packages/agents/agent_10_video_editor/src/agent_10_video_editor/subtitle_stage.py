"""``agent_10.subtitles``: SRT per language from script text and narration timeline (s4.2)."""

import re
from dataclasses import dataclass

from pydantic import ValidationError

from agent_10_video_editor.audit import record as audit_record
from agent_10_video_editor.canonical import sha256_hex
from agent_10_video_editor.checkpointing import CheckpointIO
from agent_10_video_editor.contracts import SrtEntry, SubtitlesInput, SubtitlesOutput
from agent_10_video_editor.deps import StageDeps
from agent_10_video_editor.entry import run_task
from agent_10_video_editor.errors import input_invalid, missing_dependency
from agent_10_video_editor.guard import DrainSignal, HeavyTaskGuard
from agent_10_video_editor.inputs import NarrationTimeline, ScriptStrings
from agent_10_video_editor.observability import LogContext, emit
from agent_10_video_editor.ports import SubtitleAsset
from agent_10_video_editor.qc.result import CheckResult, passed
from agent_10_video_editor.scope import TenantScope, one_ref_per_schema
from agent_10_video_editor.subtitles import Cue, SrtParser, SubtitleStageCore
from agent_10_video_editor.taskio import (
    ACTOR,
    build_output,
    continue_action,
    drain_action,
    output_ref,
    parse_blob,
    to_validation_result,
    usage,
    validate_budget,
)
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import TaskOutput
from amw_core.enums import CheckVerdict, OutputRefKind, OutputStatus
from amw_core.errors import IncompleteOutputError, SchemaInvalidError
from amw_core.exec_context import ExecContext
from amw_core.ids import ASSET, ActorRef
from amw_core.interfaces.tenancy_context import TenantContext

SUBTITLE_SCHEMAS = (
    "agent_10.render.output",
    "agent_07.voice_synthesis.output",
    "agent_05.script_document",
)
_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub(" ", text).strip()


@dataclass(frozen=True, slots=True)
class SubtitleResult:
    output: TaskOutput


class SubtitleStage:
    """Typed implementation of task type ``agent_10.subtitles`` (``s10_subs``)."""

    def __init__(self, deps: StageDeps) -> None:
        self._d = deps

    def run(self, task_input: TaskInput, ctx: ExecContext) -> TaskOutput:
        """``TaskWorker`` entry point (03 section 1 rule 5, CCR-203); every failure is returned."""
        return run_task(
            task_input,
            ctx,
            self._d.clock,
            lambda: self.execute(task_input, str(ctx.attempt_id), str(ctx.org_id)),
        )

    def execute(
        self, task_input: TaskInput, attempt_id: str, envelope_org: str | None = None
    ) -> TaskOutput:
        d = self._d
        started = d.clock.monotonic_ms()
        log = LogContext(
            task_input.org_id,
            task_input.job_id,
            task_input.task_id,
            attempt_id,
            task_input.correlation_id,
        )
        ctx = TenantContext(org_id=task_input.org_id, actor=ActorRef(ACTOR))  # type: ignore[arg-type]
        scope = TenantScope(ctx, d.storage)
        if envelope_org is not None:
            TenantScope.assert_consistent(envelope_org, task_input)
        else:
            TenantScope.assert_refs_owned(task_input)
        validate_budget(task_input)
        if task_input.payload.data is None:
            raise input_invalid("PAYLOAD_NOT_INLINE")
        try:
            payload = SubtitlesInput.model_validate(task_input.payload.data)
        except ValidationError as exc:
            raise SchemaInvalidError("subtitles input failed its schema") from exc
        refs = one_ref_per_schema(task_input, SUBTITLE_SCHEMAS)
        script = parse_blob(
            ScriptStrings,
            scope.read_bytes(*refs["agent_05.script_document"]),
            "agent_05.script_document",
        )
        if refs["agent_05.script_document"][1] != payload.verified_script_sha256:
            raise input_invalid("SCRIPT_HASH_MISMATCH")
        timeline = parse_blob(
            NarrationTimeline,
            scope.read_bytes(*refs["agent_07.voice_synthesis.output"]),
            "agent_07.voice_synthesis.output",
        )
        SubtitleStageCore.check_timeline_source(timeline.source)
        if timeline.language not in (None, payload.language):
            raise input_invalid("LANGUAGE_MISMATCH")
        with d.tenancy.transaction(ctx) as tx:
            row = d.renders.get(tx, payload.render_id)
        if row is None:
            raise missing_dependency(f"RENDER_NOT_FOUND:{payload.render_id}")

        signal = DrainSignal()
        guard = HeavyTaskGuard(d.cfg.guard, d.admission, signal, d.timers)
        guard.arm()
        try:
            verdict = guard.check(60_000)
            if not verdict.allowed:
                return build_output(
                    status=OutputStatus.SUSPENDED,
                    schema="agent_10.subtitles.output",
                    data=None,
                    refs=[],
                    results=[],
                    duration_ms=d.clock.monotonic_ms() - started,
                    resource_usage=usage(0, task_input.resource_budget.currency),
                    next_action=drain_action(f"CHECKPOINTED / DRAIN ({verdict.reason})"),
                    now=d.clock.now(),
                )
        finally:
            guard.disarm()

        built = SubtitleStageCore.build(
            timeline, script.segments, d.cfg.sub.max_chars_per_cue, row.duration_ms
        )
        emit("subs.cues", log, cues=len(built.cues), errors=len(built.errors))
        results = self._checks(built.srt, built.errors, timeline, script, built.cues)
        failing = [r for r in results if r.verdict is CheckVerdict.FAIL]
        if failing:
            raise IncompleteOutputError(
                "subtitle checks failed",
                details={"checks": [r.check_id for r in failing], "errors": list(built.errors)},
            )
        emit("subs.validated", log, cues=len(built.cues))
        sha = sha256_hex(built.srt)
        info = scope.put_bytes(
            scope.artifact_uri(
                task_input.job_id,
                task_input.task_id,
                attempt_id,
                f"subtitles/{payload.language}-{sha[:16]}.srt",
            ),
            built.srt,
        )
        with d.tenancy.transaction(ctx) as tx:
            asset = d.assets.find_subtitle(tx, sha) or d.assets.insert_subtitle(
                tx,
                SubtitleAsset(str(ASSET.new()), info.uri, sha, info.size_bytes, payload.language),
            )
        with d.tenancy.transaction(ctx) as tx:
            audit_record(
                d.audit, tx, d.clock, action="subtitles.completed", target_kind="asset",
                target_id=asset.asset_id, job_id=task_input.job_id,
                correlation_id=task_input.correlation_id,
                details={"srt_sha256": sha, "cues": len(built.cues)},
            )  # fmt: skip
        CheckpointIO(
            scope=scope,
            tenancy=d.tenancy,
            store=d.checkpoints,
            clock=d.clock,
            context=ctx,
            job_id=task_input.job_id,
            task_id=task_input.task_id,
            attempt_id=attempt_id,
        ).write("subs.registered", _SubsState(srt_sha256=sha, asset_id=asset.asset_id))
        output = SubtitlesOutput(
            srt=(
                SrtEntry(
                    language=payload.language,
                    uri=asset.uri,
                    sha256=sha,
                    size_bytes=info.size_bytes,
                    cue_count=len(built.cues),
                    asset_id=asset.asset_id,
                    last_cue_end_ms=built.cues[-1].end_ms,
                ),
            ),
            warnings=tuple(w for w in built.warnings),
            timeline_source=timeline.source,
            sync_basis="NARRATION_TIMELINE",
        )
        return build_output(
            status=OutputStatus.SUCCEEDED,
            schema="agent_10.subtitles.output",
            data=output.model_dump(mode="json"),
            refs=[
                output_ref(
                    asset.uri, OutputRefKind.SUBTITLE, sha, info.size_bytes, "application/x-subrip"
                )
            ],
            results=[to_validation_result(r) for r in results],
            duration_ms=d.clock.monotonic_ms() - started,
            resource_usage=usage(0, task_input.resource_budget.currency),
            next_action=continue_action("subtitles complete"),
            now=d.clock.now(),
        )

    @staticmethod
    def _checks(
        srt: bytes,
        errors: tuple[str, ...],
        timeline: NarrationTimeline,
        script: ScriptStrings,
        cues: tuple[Cue, ...],
    ) -> list[CheckResult]:
        parsed = SrtParser.parse(srt)
        fmt_ok = not errors and len(parsed) == len(cues)
        by_segment: dict[str, list[str]] = {}
        for cue in cues:
            by_segment.setdefault(cue.segment_id or "", []).append(cue.text)
        coverage_ok = bool(cues) and all(
            seg.segment_id in by_segment or not script.segments.get(seg.segment_id, "").strip()
            for seg in timeline.segments
        )
        text_ok = all(
            _norm(" ".join(by_segment.get(seg.segment_id, [])))
            == _norm(script.segments.get(seg.segment_id, ""))
            for seg in timeline.segments
        )
        return [
            _proc("a10.sub.format", fmt_ok),
            _proc("a10.sub.coverage", coverage_ok),
            _proc("a10.sub.text_from_script", text_ok),
        ]


def _proc(check_id: str, ok: bool) -> CheckResult:
    if ok:
        return passed(check_id, gate=False)
    return CheckResult(check_id, CheckVerdict.FAIL, True, gate=False)


from pydantic import BaseModel, ConfigDict  # noqa: E402


class _SubsState(BaseModel):
    model_config = ConfigDict(frozen=True)

    srt_sha256: str
    asset_id: str
