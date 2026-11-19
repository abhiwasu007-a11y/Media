"""``ClaimExtractionStep`` (blueprint 10.1): validate, D0, model call per batch, post-checks,
persist, assemble the Task Output. One checkpoint after every paid call."""

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from agent_06_fact_checker.config import FactCheckSettings
from agent_06_fact_checker.detect import Detector, Finding, chart_findings
from agent_06_fact_checker.extraction import (
    FINANCE_CATEGORY,
    FINANCE_PACK,
    ExtractionReport,
    SegmentBatch,
    apply_chart_flags,
    apply_floor,
    attach_findings,
    batch_segments,
    drop_fin_flags,
    raising_refusal,
    recompute,
    refusal_effect,
    refusal_only_output,
    structural_problems,
)
from agent_06_fact_checker.models import (
    DataAge,
    ExtractionInput,
    ExtractionOutput,
    RefusalReason,
    Verdict,
)
from agent_06_fact_checker.outputs import (
    check,
    check_ctx,
    error_output,
    next_action_for,
    success_output,
    write_blob,
)
from agent_06_fact_checker.ports import ChartRanges, ClaimStore, ScriptRegistry
from agent_06_fact_checker.price_age import resolve_chart_ages
from agent_06_fact_checker.prompts import PromptSource, RenderedPrompt, render_system
from agent_06_fact_checker.rulepack import RulePack, RulePackResolver, ensure_lexicon
from agent_06_fact_checker.runtime import (
    AGENT_ID,
    PaidCallRunner,
    StepCheckpoints,
    UsageTotals,
    task_key,
)
from amw_adapters.llm.protocol import LlmAdapter
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import TaskOutput, ValidationResult
from amw_core.enums import ActorKind, ContextRefPurpose
from amw_core.errors import (
    AgentError,
    BudgetExhaustedError,
    InputInvalidError,
    InsufficientInputError,
    MissingDependencyError,
    OutputSchemaInvalidError,
    PermanentError,
    SchemaInvalidError,
    SchemaVersionUnsupportedError,
)
from amw_core.exec_context import ExecContext
from amw_core.ids import ActorRef, ChannelId
from amw_core.interfaces import (
    AuditLog,
    BlobStorage,
    BlobUri,
    BudgetGuard,
    CheckpointStore,
    Clock,
    CostLedger,
    NewAuditEntry,
    TenancyContext,
)

log = logging.getLogger(__name__)
INPUT_SCHEMA = "agent_06.claim_extraction.input"
OUTPUT_SCHEMA = "agent_06.claim_extraction.output"
PROMPT_ID = "agent_06/claim_extraction.v1"
STAGE_CLAIMS = "s06_claims"
SCRIPT_REF_SCHEMA_PREFIX = "agent_05."


@dataclass(slots=True)
class _State:
    validated: bool = False
    usage: UsageTotals = field(default_factory=UsageTotals)


class ClaimExtractionStep:
    def __init__(
        self,
        *,
        llm: LlmAdapter,
        budget: BudgetGuard,
        ledger: CostLedger,
        tenancy: TenancyContext,
        clock: Clock,
        blobs: BlobStorage,
        checkpoints: CheckpointStore,
        audit: AuditLog,
        claims: ClaimStore,
        scripts: ScriptRegistry,
        rule_packs: RulePackResolver,
        prompts: PromptSource,
        settings: FactCheckSettings,
        chart_ranges: ChartRanges,
    ) -> None:
        self._llm = llm
        self._tenancy = tenancy
        self._clock = clock
        self._blobs = blobs
        self._checkpoints = checkpoints
        self._audit = audit
        self._claims = claims
        self._scripts = scripts
        self._packs = rule_packs
        self._prompts = prompts
        self._settings = settings
        self._ranges = chart_ranges
        self._runner = PaidCallRunner(
            llm=llm,
            budget=budget,
            ledger=ledger,
            tenancy=tenancy,
            clock=clock,
            settings=settings.extraction_llm,
            max_repairs=settings.max_repairs,
        )

    # ------------------------------------------------------------------ entry point
    def run(self, task_input: TaskInput, ctx: ExecContext) -> TaskOutput:
        started = self._clock.monotonic_ms()
        state = _State()
        try:
            return self._run(task_input, ctx, state, started)
        except (PermanentError, AgentError, BudgetExhaustedError) as exc:
            return error_output(
                exc,
                task=task_input,
                clock=self._clock,
                started_ms=started,
                usage=state.usage,
                attempt_no=task_input.retry_count,
                validated=state.validated,
            )

    # ------------------------------------------------------------------ E0
    def _validate(
        self, task: TaskInput, ctx: ExecContext
    ) -> tuple[ExtractionInput, dict[str, RulePack]]:
        if task.agent_id != AGENT_ID:
            raise InputInvalidError("task is not addressed to agent_06")
        payload = task.payload
        if payload.payload_schema != INPUT_SCHEMA:
            raise SchemaInvalidError("unexpected payload schema")
        if not payload.payload_schema_version.startswith("1."):
            raise SchemaVersionUnsupportedError("payload schema major is not supported")
        doc = self._payload_doc(task, ctx)
        try:
            inp = ExtractionInput.model_validate(doc)
        except ValidationError as exc:
            raise SchemaInvalidError(
                "extraction input does not match the schema",
                details={"violations": _violations(exc)},
            ) from None
        if inp.owner_sebi_registration != "UNREGISTERED":
            raise InputInvalidError("owner_sebi_registration is not supported in v1")
        ids = [s.segment_id for s in inp.segments]
        if len(set(ids)) != len(ids):
            raise InputInvalidError("duplicate segment_id")
        if FINANCE_PACK in inp.active_rule_packs and task.channel_id is None:
            raise InputInvalidError("channel_id is required for a finance script")
        if inp.channel_category == FINANCE_CATEGORY and FINANCE_PACK not in inp.active_rule_packs:
            raise InputInvalidError("a finance script needs the finance rule pack to be active")
        packs = {key: self._packs.resolve(key) for key in inp.active_rule_packs}  # D9
        finance = packs.get(FINANCE_PACK)
        if finance is not None:
            ensure_lexicon(finance, inp.language)  # fail closed before any paid call
        self._check_script_hash(task, ctx, inp)
        return inp, packs

    def _payload_doc(self, task: TaskInput, ctx: ExecContext) -> Mapping[str, Any]:
        payload = task.payload
        if payload.data is not None:
            return payload.data
        if payload.data_ref is None or payload.data_sha256 is None:  # PayloadObject rules out
            raise SchemaInvalidError("payload has neither inline data nor a stored reference")
        raw = b"".join(self._blobs.get(ctx.tenant, BlobUri(payload.data_ref), payload.data_sha256))
        loaded = json.loads(raw.decode("utf-8"))
        if not isinstance(loaded, dict):
            raise SchemaInvalidError("payload blob is not a JSON object")
        return loaded

    def _check_script_hash(self, task: TaskInput, ctx: ExecContext, inp: ExtractionInput) -> None:
        """E0: the script blob's SHA-256 equals ``scripts.content_sha256`` (blueprint 7.1)."""
        tenant = ctx.tenant
        with self._tenancy.transaction(tenant) as tx:
            self._tenancy.require_same_tenant(tx, task.org_id)
            expected = self._scripts.content_sha256(
                tx, script_id=inp.script_id, script_version=inp.script_version
            )
        if expected is None:
            raise MissingDependencyError("script is not known to this tenant")
        refs = [
            r
            for r in task.context_refs
            if r.purpose is ContextRefPurpose.PRIOR_OUTPUT
            and r.schema_ is not None
            and r.schema_.startswith(SCRIPT_REF_SCHEMA_PREFIX)
        ]
        if not refs:
            raise MissingDependencyError("the script blob is not among the context refs")
        if any(r.sha256 != expected for r in refs):
            raise InputInvalidError("script blob hash differs from scripts.content_sha256")

    # ------------------------------------------------------------------ the run
    def _run(self, task: TaskInput, ctx: ExecContext, state: _State, started: int) -> TaskOutput:
        check_ctx(task, ctx)
        inp, packs = self._validate(task, ctx)
        state.validated = True
        settings = self._settings
        tenant = ctx.tenant
        saved = StepCheckpoints(
            store=self._checkpoints,
            blobs=self._blobs,
            tenancy=self._tenancy,
            clock=self._clock,
            task=task,
            ctx=ctx,
        )
        done = saved.load()
        finance = packs.get(FINANCE_PACK)

        # E1 / D0
        if "E1_aged" not in done:
            today = self._clock.now().date()
            ends = {r.ref_id: self._ranges.range_end(r.ref_id) for r in inp.chart_data_refs}
            aged = resolve_chart_ages(
                inp.chart_data_refs,
                ends,
                today,
                settings.price_data_lag_days,
                settings.price_data_lag_unit,
            )
            saved.save(
                "E1_aged",
                {
                    "evaluated_at": self._clock.now().isoformat(),
                    "ages": {
                        r.ref_id: (r.data_age_vs_lag.value if r.data_age_vs_lag else None)
                        for r in aged
                    },
                },
            )
        ages: dict[str, DataAge | None] = {
            ref: (DataAge(v) if v is not None else None)
            for ref, v in done["E1_aged"]["ages"].items()
        }
        refs = {r.ref_id: r for r in inp.chart_data_refs}
        aged_refs = tuple(
            r.model_copy(update={"data_age_vs_lag": ages[r.ref_id]}) for r in inp.chart_data_refs
        )

        # E2 / E3
        doc = self._prompts.load(PROMPT_ID)
        prompt = render_system(doc, self._packs, inp.active_rule_packs)
        batches = batch_segments(inp.segments, settings.extract_max_chars_per_call)
        segments = {s.segment_id: s for s in inp.segments}
        order = {s.segment_id: i for i, s in enumerate(inp.segments)}
        chart_ids = frozenset(refs)
        citation_ids = frozenset(c.citation_ref for c in inp.available_citations)
        outputs: list[ExtractionOutput] = []
        for batch in batches:
            key = f"E3_batch_{batch.index}"
            if key in done:
                outputs.append(ExtractionOutput.model_validate(done[key]))
                continue
            out = self._extract_batch(
                task, ctx, state, inp, aged_refs, prompt, batch, segments, chart_ids, citation_ids
            )
            saved.save(key, out.to_doc(), (batch.index + 1) / len(batches))
            outputs.append(out)
        report = ExtractionReport(batches=len(batches))

        # refusals (B-1): they never replace what the other batches or the code found
        refusals = [o.refusal for o in outputs if o.refusal is not None]
        merged = sorted(
            (c for o in outputs for c in o.claims),
            key=lambda c: (order[c.segment_id], c.char_start),
        )
        failing = raising_refusal(refusals)
        if failing is not None and not merged:
            if failing.reason is RefusalReason.INSUFFICIENT_INPUT:
                raise InsufficientInputError(
                    "the model refused: insufficient input", details={"refusal": failing.to_doc()}
                )
            raise InputInvalidError(
                "the model refused the input", details={"refusal": failing.to_doc()}
            )
        if len(merged) > 500:
            raise OutputSchemaInvalidError("more than 500 claims")
        renumbered = [c.model_copy(update={"local_id": f"c{i}"}) for i, c in enumerate(merged, 1)]
        dropped = 0
        loose: list[Finding] = []
        restricted: frozenset[str] = frozenset()
        if finance is not None and finance.lexicon is not None:
            lex = finance.lexicon
            restricted = frozenset(lex.claim_type_floor)
            flagged = apply_chart_flags(apply_floor(renumbered, lex), ages)
            extra = {r.instrument for r in inp.chart_data_refs} | {
                c.instrument for c in flagged if c.instrument
            }
            detector = Detector(lex, finance.markers, settings.referral_patterns, extra)
            findings = [f for seg in inp.segments for f in detector.scan(seg)]
            linked = {c.chart_data_ref for c in flagged if c.chart_data_ref}
            findings += chart_findings(aged_refs, inp.segments, linked)
            flagged, loose = attach_findings(flagged, findings)
        else:
            flagged, dropped = drop_fin_flags(renumbered)
        effect = refusal_effect(refusals)
        claims_final, overall, changed = recompute(flagged, loose, effect, restricted)
        report = ExtractionReport(
            batches=len(batches),
            dropped_fin_flags=dropped,
            verdicts_changed=changed,
            loose_findings=loose,
            refused_batches=len(refusals),
        )
        if claims_final:
            if refusals:  # claims and a refusal object cannot coexist (output schema)
                overall = overall.model_copy(
                    update={
                        "needs_human_review_reasons": tuple(
                            sorted({*overall.needs_human_review_reasons, *effect.reasons})
                        )
                    }
                )
            final = ExtractionOutput(claims=tuple(claims_final), overall=overall, refusal=None)
        else:
            final = refusal_only_output(overall, effect)
        with self._tenancy.transaction(tenant) as tx:
            ids = dict(
                self._claims.insert_claims(
                    tx, script_id=inp.script_id, task_id=task_key(task), claims=claims_final
                )
            )
        return self._assemble(
            task, ctx, state, started, inp, final, ids, ages, finance is not None, report
        )

    # ------------------------------------------------------------------ one batch
    def _extract_batch(
        self,
        task: TaskInput,
        ctx: ExecContext,
        state: _State,
        inp: ExtractionInput,
        aged_refs: tuple[Any, ...],
        prompt: RenderedPrompt,
        batch: SegmentBatch,
        segments: Mapping[str, Any],
        chart_ids: frozenset[str],
        citation_ids: frozenset[str],
    ) -> ExtractionOutput:
        batch_segments_by_id = {s.segment_id: s for s in batch.segments}
        variables: dict[str, object] = {
            "language": inp.language,
            "channel_category": inp.channel_category,
            "owner_sebi_registration": inp.owner_sebi_registration,
            "active_rule_packs": list(inp.active_rule_packs),
            "segments": [s.to_doc() for s in batch.segments],
            "chart_data_refs": [r.to_doc() for r in aged_refs],
            "available_citations": [
                {"citation_ref": c.citation_ref, "kind": c.kind.value, "title": c.title}
                for c in inp.available_citations
            ],
            "our_method_release_approved": inp.our_method_release_approved,
        }

        def check_output(out: ExtractionOutput) -> list[str]:
            return structural_problems(out.claims, batch_segments_by_id, chart_ids, citation_ids)

        return self._runner.complete_json(
            task=task,
            ctx=ctx,
            usage=state.usage,
            step_key=f"E3_batch_{batch.index}",
            prompt=prompt,
            variables=variables,
            model=ExtractionOutput,
            language=inp.language,
            check=check_output,
        )

    # ------------------------------------------------------------------ E6
    def _assemble(
        self,
        task: TaskInput,
        ctx: ExecContext,
        state: _State,
        started: int,
        inp: ExtractionInput,
        final: ExtractionOutput,
        ids: Mapping[str, str],
        ages: Mapping[str, DataAge | None],
        finance: bool,
        report: ExtractionReport,
    ) -> TaskOutput:
        tenant = ctx.tenant
        doc = final.to_doc()
        refs = [write_blob(self._blobs, tenant, task, ctx, "claim_extraction_output.json", doc)]
        refs.append(write_blob(self._blobs, tenant, task, ctx, "claim_ids.json", dict(ids)))
        with self._tenancy.transaction(tenant) as tx:
            self._audit.append(
                tx,
                NewAuditEntry(
                    actor_kind=ActorKind.AGENT,
                    actor_ref=ActorRef(AGENT_ID),
                    authority="agent_06.claim_extraction",
                    action="claims.extracted",
                    target_kind="script",
                    target_id=inp.script_id,
                    occurred_at=self._clock.now(),
                    correlation_id=None,
                    details={
                        "task_id": task.task_id,
                        "claims": len(final.claims),
                        "verdict": final.overall.proposed_verdict.value,
                        "batches": report.batches,
                        "channel_id": task.channel_id or ChannelId(""),
                    },
                ),
            )
        results = self._results(inp, final, ids, ages, finance, report, doc)
        failed_gate = [r.check_id for r in results if r.gate and r.verdict.value == "FAIL"]
        log.info(  # ids, counts and codes only (NFR-6): never quotes or script text
            "claims.completed",
            extra={
                "task_id": task.task_id,
                "script_id": inp.script_id,
                "claims": len(final.claims),
                "verdict": final.overall.proposed_verdict.value,
                "batches": report.batches,
            },
        )
        return success_output(
            clock=self._clock,
            started_ms=started,
            schema=OUTPUT_SCHEMA,
            doc=doc,
            refs=refs,
            results=results,
            usage=state.usage,
            next_action=next_action_for(final.overall.proposed_verdict, failed_gate),
        )

    def _results(
        self,
        inp: ExtractionInput,
        final: ExtractionOutput,
        ids: Mapping[str, str],
        ages: Mapping[str, DataAge | None],
        finance: bool,
        report: ExtractionReport,
        doc: Mapping[str, Any],
    ) -> list[ValidationResult]:
        claims = final.claims
        segs = {s.segment_id: s for s in inp.segments}
        offsets_ok = all(
            c.segment_id in segs and segs[c.segment_id].text[c.char_start : c.char_end] == c.quote
            for c in claims
        )
        loose = report.loose_findings
        loose_rules = sorted({f.rule_id for f in loose})
        r9_missing = [
            c.local_id
            for c in claims
            if c.chart_data_ref is not None
            and ages.get(c.chart_data_ref) in (DataAge.WITHIN_LAG, DataAge.UNKNOWN)
            and not any(f.rule_id == "FIN-R9" for f in c.rule_flags)
        ]
        citation_ok = all(
            set(c.citation_refs) <= {a.citation_ref for a in inp.available_citations}
            for c in claims
        )
        uncited = [c.local_id for c in claims if c.requires_citation and not c.citation_refs]
        blocked = final.overall.proposed_verdict is Verdict.BLOCKED
        return [
            check(
                "claims.schema",
                True,
                "extraction payload validated by its model when parsed (D1; a failure raises)",
            ),
            check(
                "claims.tenant_scope",
                True,
                "org, script hash and rule packs were checked at E0 (a failure rejects the task)",
            ),
            check("claims.offsets", offsets_ok, "quote equals segment text at the offsets (D2)"),
            check(
                "claims.chart_lag",
                not r9_missing,
                "FIN-R9 flag on every chart WITHIN_LAG or UNKNOWN (D3)",
                rule_id="FIN-R9",
                skipped=not finance,
            ),
            check(
                "claims.code_findings",
                not loose,
                "code detections without an extracted claim: " + (",".join(loose_rules) or "none"),
                skipped=not finance,
                blocking=False,
                warn_instead=True,
                measured=len(loose),
            ),
            check(
                "claims.future_marker_filter",
                True,
                "D11 sentence scan ran with the rule-pack marker lists (an empty list fails at E0)",
                rule_id="FIN-R13",
                skipped=not finance,
            ),
            check(
                "claims.refusals",
                report.refused_batches == 0,
                f"{report.refused_batches} batch(es) refused by the model",
                blocking=False,
                warn_instead=True,
                measured=report.refused_batches,
            ),
            check("claims.citation_refs_exist", citation_ok, "citation_refs exist (D5)"),
            check(
                "claims.citation_required",
                not uncited,
                f"{len(uncited)} claim(s) need a citation and have none (D6)",
                blocking=False,
                warn_instead=True,
                measured=len(uncited),
            ),
            check(
                "claims.verdict_recomputed",
                True,
                f"verdicts recomputed by code (D7); {report.verdicts_changed} changed",
                measured=report.verdicts_changed,
            ),
            check(
                "claims.persisted",
                set(ids) == {c.local_id for c in claims},
                "claims rows exist for every claim",
                measured=len(ids),
                threshold=len(claims),
            ),
            check(
                "claims.gate.rule_flags",
                not blocked,
                "gate: no BLOCKING rule flag" if not blocked else "gate FAILED: BLOCKING rule flag",
                gate=True,
            ),
        ]


def _violations(exc: ValidationError) -> list[dict[str, str]]:
    return [
        {
            "path": "/" + "/".join(str(p) for p in e["loc"]),
            "keyword": "model",
            "message": str(e["type"]),
        }
        for e in exc.errors()[:200]
    ]


__all__ = ["ClaimExtractionStep"]
