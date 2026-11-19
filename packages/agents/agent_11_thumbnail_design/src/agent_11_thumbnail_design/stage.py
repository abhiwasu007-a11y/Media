"""ThumbnailStage (P1..P9; blueprint 4.1): the task ``agent_11.thumbnail_variants``.

Failures are raised as typed 07 errors (the worker maps them to the Task Output); a result decided
by the compliance verdict (``BLOCKED``, ``NEEDS_HUMAN_REVIEW``) is a ``SUCCEEDED`` output.
Tenant isolation: every row is read and written inside a tenant transaction through the
repository port, every URI is compared with the task's org before use, caches carry the org.
"""

import hashlib
import io
import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from agent_11_thumbnail_design.checks import (
    CheckContext,
    LicenceFact,
    PictureFact,
    VariantFacts,
    run_checks,
    variant_failures,
)
from agent_11_thumbnail_design.composer import ImageComposer, RenderResult, RenderSpec
from agent_11_thumbnail_design.config import Agent11Settings
from agent_11_thumbnail_design.errors import (
    ComposeFailedError,
    FontIntegrityError,
    GlyphMissingError,
    TextDoesNotFitError,
)
from agent_11_thumbnail_design.fallback import FallbackPlanner, PlannerPolicy
from agent_11_thumbnail_design.guards import GuardContext, check_concepts, rationale_ok
from agent_11_thumbnail_design.models import (
    AccentRole,
    Concept,
    GuardHit,
    Limits,
    Manifest,
    PictureOption,
    PictureOptionView,
    PreviousChoice,
    RetryEntry,
    StepIn,
    StepOut,
    SubjectHint,
    TextOption,
)
from agent_11_thumbnail_design.payload import (
    Omitted,
    OutputPayload,
    PayloadFile,
    PayloadPicture,
    PayloadVariant,
    PlannerInfo,
    ThumbnailInput,
)
from agent_11_thumbnail_design.pinning import (
    FALLBACK_FONT_KEY,
    font_manifest,
    pinned_font_bytes,
    render_environment,
    verify_font,
)
from agent_11_thumbnail_design.ports import (
    BrandKitView,
    FontRef,
    LedgerRow,
    NewImageAsset,
    NewLedgerRow,
    OwnerAsset,
    RegisteredAsset,
    ThumbnailRepository,
)
from agent_11_thumbnail_design.prompting import PromptBundle, parse_output, render_request
from agent_11_thumbnail_design.revision import build_previous, canonical_json, set_sha256
from agent_11_thumbnail_design.scanner import InjectionScanner
from agent_11_thumbnail_design.subject_options import (
    GlyphFacts,
    PictureBuildConfig,
    PictureOptions,
    build_picture_options,
)
from agent_11_thumbnail_design.templates import (
    GlyphSpec,
    TemplateSpec,
    glyph_catalogue,
    offer_templates,
    palette,
    reserved_corner_rect,
    template_set_sha256,
)
from agent_11_thumbnail_design.text_options import (
    TextBuildConfig,
    TextOptions,
    build_text_options,
    finance_text_hit,
)
from agent_11_thumbnail_design.textutil import contains_sequence, fold, folded_words
from amw_adapters.llm.protocol import LlmAdapter
from amw_core.config import RulePackSettings, effective_non_finance_categories
from amw_core.contracts.common import PayloadObject, storage_uri_owner
from amw_core.contracts.error import error_object_from_exception, violation
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import (
    NextAction,
    OutputRef,
    ResourceUsage,
    TaskOutput,
    ValidationResult,
)
from amw_core.enums import (
    ActorKind,
    BillingMode,
    ComplianceVerdict,
    ContextRefPurpose,
    CostFigureKind,
    CostOperation,
    NextActionType,
    OutputRefKind,
    OutputStatus,
)
from amw_core.errors import (
    AgentCrashError,
    AmwError,
    BudgetExhaustedError,
    CircuitOpenError,
    ConfigInvalidError,
    CrossTenantRefError,
    IncompleteOutputError,
    InputInvalidError,
    InsufficientInputError,
    InvalidJsonError,
    LockConflictError,
    MissingDependencyError,
    OutputSchemaInvalidError,
    ProviderRefusalError,
    QualityRepeatedFailureError,
    SchemaInvalidError,
    TenantMismatchError,
)
from amw_core.exec_context import ExecContext
from amw_core.ids import (
    ActorRef,
    AttemptId,
    ChannelId,
    CorrelationId,
    ExecutorId,
    JobId,
    TaskId,
    make_idempotency_key,
)
from amw_core.interfaces.audit_log import AuditLog, NewAuditEntry
from amw_core.interfaces.budget_guard import BudgetGuard, CallCheck
from amw_core.interfaces.checkpoint_store import CheckpointStore, NewCheckpoint
from amw_core.interfaces.clock import Clock
from amw_core.interfaces.cost_ledger import CostLedger, NewCostEntry
from amw_core.interfaces.idempotency_store import BeginAction, IdempotencyStore
from amw_core.interfaces.storage import BlobStorage, BlobUri
from amw_core.interfaces.tenancy_context import TenancyContext, TenantContext, TenantTransaction
from amw_core.tenancy.storage_paths import checkpoint_uri, task_artifact_uri

AGENT_ID = "agent_11"
INPUT_SCHEMA = "agent_11.thumbnail_variants.input"
OUTPUT_SCHEMA = "agent_11.thumbnail_variants.output"
_SCRIPT_OF = {"mr-IN": "Devanagari", "hi-IN": "Devanagari", "en-IN": "Latin"}
_ACCENT_ROLES: tuple[AccentRole, ...] = ("PRIMARY", "SECONDARY", "TERTIARY")
_DIRECT = {"HOOK", "PROOF"}


@dataclass(frozen=True, slots=True)
class Lexicons:
    """Rule-pack / package-data lists (13 owns the finance markers); never literals in code."""

    finance_markers: tuple[str, ...]
    injection_markers: tuple[str, ...]
    instruction_phrases: tuple[str, ...]
    neutral_words: frozenset[str]
    non_finance_categories: frozenset[str] = frozenset()
    """Explicitly known non-finance channel categories (exact match, injected from the rule
    pack). Fail closed (owner D13, CCR-273): any other value (None, empty, unknown, wrong type,
    other case) is treated as finance; the default (empty) makes every channel finance."""

    @classmethod
    def from_rule_pack_config(
        cls,
        rule_packs: RulePackSettings,
        *,
        finance_markers: tuple[str, ...],
        injection_markers: tuple[str, ...],
        instruction_phrases: tuple[str, ...],
        neutral_words: frozenset[str],
    ) -> Lexicons:
        """The production builder (PASS6-N): the non-finance categories come from the rule-pack
        config (``rule_packs.non_finance_categories``, amw_core), never from a literal here."""
        return cls(
            finance_markers,
            injection_markers,
            instruction_phrases,
            neutral_words,
            effective_non_finance_categories(rule_packs.non_finance_categories),
        )

    def is_finance(self, category: object) -> bool:
        # re-checked: a directly built Lexicons cannot make finance or an ad category non-finance
        allowed = effective_non_finance_categories(self.non_finance_categories)
        return not (isinstance(category, str) and category in allowed)


@dataclass(frozen=True, slots=True)
class RulePacks:
    platform: dict[str, str]
    tenant_text: str | None = None


@dataclass(frozen=True, slots=True)
class StageDeps:
    settings: Agent11Settings
    tenancy: TenancyContext
    repo: ThumbnailRepository
    storage: BlobStorage
    llm: LlmAdapter
    budget: BudgetGuard
    costs: CostLedger
    audit: AuditLog
    idem: IdempotencyStore
    checkpoints: CheckpointStore
    composer: ImageComposer
    clock: Clock
    prompt: PromptBundle
    lexicons: Lexicons
    packs: RulePacks
    templates: tuple[TemplateSpec, ...]


@dataclass(slots=True)
class _Calls:
    records: list[dict[str, Any]] = field(default_factory=list)
    cost_entry_ids: list[str] = field(default_factory=list)
    cost_micros: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    reasks: int = 0
    fallback_code: str | None = None

    @property
    def paid(self) -> int:
        """Calls this run really made (a replay from the idempotency store costs nothing)."""
        return sum(1 for r in self.records if not r.get("replayed"))


@dataclass(frozen=True, slots=True)
class _Pick:
    concept: Concept
    planned_by: str


S0_ERRORS = frozenset(
    {
        "PERMANENT.SCHEMA_INVALID",
        "PERMANENT.SCHEMA_VERSION_UNSUPPORTED",
        "PERMANENT.INPUT_INVALID",
        "PERMANENT.TENANT_MISMATCH",
        "PERMANENT.CROSS_TENANT_REF",
        "PERMANENT.TENANT_INACTIVE",
        "PERMANENT.MISSING_DEPENDENCY",
        "PERMANENT.UNSUPPORTED_TASK",
    }
)
"""Failures of the 03 section 7.1 receiver checks: the task is rejected before any work."""


def check_ctx(task_input: TaskInput, ctx: ExecContext) -> None:
    """The context and the Task Input must name the same org, job and task (19.1 layer 1).
    Anything else is ``TENANT_MISMATCH`` before any step runs."""
    if (
        str(ctx.org_id) != task_input.org_id
        or str(ctx.job_id) != task_input.job_id
        or str(ctx.task_id) != task_input.task_id
    ):
        raise TenantMismatchError("execution context does not match the Task Input")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ThumbnailStage:
    def __init__(self, deps: StageDeps) -> None:
        self.d = deps

    # ------------------------------------------------------------------ entry point
    def run(self, task_input: TaskInput, ctx: ExecContext) -> TaskOutput:
        """``TaskWorker`` entry point (03 section 1 rule 5, CCR-203); every failure is returned
        as a Task Output carrying the cost really incurred so far, never raised."""
        d = self.d
        started = d.clock.monotonic_ms()
        run: _Run | None = None
        pre_run = True
        try:
            check_ctx(task_input, ctx)
            tc = ctx.tenant
            try:
                inp = self._parse_input(task_input)
            except CrossTenantRefError as exc:
                # Blueprint 18 / 19.1 layer 1: a foreign reference is a security event.
                _append_audit(d, tc, task_input, "security.cross_tenant_ref", dict(exc.details))
                raise
            run = _Run(self, task_input, inp, tc, ctx.attempt_id)
            pre_run = False
            run.audit("thumbnail_set.started", {"iteration": inp.iteration})
            try:
                out = run.execute()
            except Exception as exc:
                run.audit(
                    "thumbnail_set.failed", {"code": getattr(exc, "code", type(exc).__name__)}
                )
                raise
            run.audit(
                "thumbnail_set.blocked"
                if out.payload_verdict != "ALLOWED"
                else "thumbnail_set.completed",
                {"produced": out.produced, "verdict": out.payload_verdict},
            )
            return out.task_output(d.clock.monotonic_ms() - started, d.clock.now(), d.settings)
        except AmwError as exc:
            return self._error_output(task_input, ctx, exc, started, run, pre_run)
        except Exception as exc:  # a bug must still end as a typed Task Output (07 AGENT.CRASH)
            crash = AgentCrashError(f"unexpected {type(exc).__name__} in agent_11")
            return self._error_output(task_input, ctx, crash, started, run, pre_run)

    def _error_output(
        self,
        ti: TaskInput,
        ctx: ExecContext,
        exc: AmwError,
        started: int,
        run: _Run | None,
        pre_run: bool,
    ) -> TaskOutput:
        """``amw.task_output`` of a failure. A receiver-check failure before any work is
        ``REJECTED`` with attempt 0; ``BudgetExhausted`` is ``SUSPENDED``; the rest ``FAILED``.
        The usage is the real cost of the calls made so far (never a silent 0)."""
        d, now = self.d, self.d.clock.now()
        rejected = pre_run and exc.code in S0_ERRORS
        error = error_object_from_exception(
            exc,
            actor=AGENT_ID,
            attempt_no=0 if rejected else ctx.attempt_no,
            occurred_at=now,
            correlation_id=ti.correlation_id,
        )
        if rejected:
            status = OutputStatus.REJECTED
        elif isinstance(exc, BudgetExhaustedError):
            status = OutputStatus.SUSPENDED
        else:
            status = OutputStatus.FAILED
        if status is OutputStatus.SUSPENDED:
            action = NextAction(
                type=NextActionType.WAIT,
                wait_reason=exc.spec.wait_reason,
                escalation_level=None,
                reason=exc.code,
            )
        else:
            kind = NextActionType.RETRY if exc.retryable else NextActionType.STOP
            action = NextAction(type=kind, wait_reason=None, escalation_level=None, reason=exc.code)
        calls = run.calls if run is not None else _Calls()
        return TaskOutput(
            status=status,
            payload=None,
            output_refs=(),
            quality_score=None,
            confidence=None,
            validation_results=(),
            duration=max(0, d.clock.monotonic_ms() - started),
            resource_usage=_usage(calls, ti.resource_budget.currency),
            error=error,
            next_action=action,
            downstream_agent=None,
            timestamp=now,
        )

    def _parse_input(self, ti: TaskInput) -> ThumbnailInput:
        if ti.agent_id != AGENT_ID or ti.payload.payload_schema != INPUT_SCHEMA:
            raise InputInvalidError("wrong agent or payload schema for agent_11")
        try:
            inp = ThumbnailInput.model_validate(ti.payload.data)
        except ValidationError as exc:
            raise SchemaInvalidError(
                "agent_11 input payload invalid",
                details={
                    "violations": [
                        violation(
                            "FIELD_INVALID",
                            "".join(f"/{part}" for part in e["loc"]),
                            str(e["type"]),
                        )
                        for e in exc.errors()
                    ]
                },
            ) from exc
        if inp.variant_count > self.d.settings.max_variants:
            raise InputInvalidError(
                "variant_count out of range",
                details={"violations": [violation("VARIANT_COUNT", "/variant_count")]},
            )
        refs = [inp.script_ref, inp.verification_ref, inp.shot_plan_ref, inp.brand_kit_ref]
        if inp.previous_set_ref:
            refs.append(inp.previous_set_ref)
        for ref in refs:
            if storage_uri_owner(ref.uri) not in (ti.org_id, "platform"):
                raise CrossTenantRefError(
                    "reference belongs to another tenant", details={"ref_kind": "PAYLOAD_REF"}
                )
        for cref in ti.context_refs:
            owner = storage_uri_owner(cref.uri)
            allowed = (
                (ti.org_id,) if cref.purpose is ContextRefPurpose.ASSET else (ti.org_id, "platform")
            )
            if owner not in allowed:
                raise CrossTenantRefError(
                    "context reference belongs to another tenant",
                    details={"ref_kind": "CONTEXT_REF", "purpose": str(cref.purpose)},
                )
        return inp


def _usage(calls: _Calls, currency: str) -> ResourceUsage:
    """The resource usage of the calls made so far (a failure reports it too, never 0)."""
    return ResourceUsage(
        cpu_ms=0,
        peak_rss_bytes=0,
        tokens_in=calls.tokens_in,
        tokens_out=calls.tokens_out,
        tokens_cached_in=calls.tokens_cached,
        llm_calls=calls.paid,
        provider_calls=calls.paid,
        cost_estimate_micros=calls.cost_micros,
        currency=currency,
        cost_entry_ids=tuple(calls.cost_entry_ids),
    )


@dataclass(slots=True)
class _Result:
    verdict: str
    payload: OutputPayload
    refs: list[OutputRef]
    checks: list[ValidationResult]
    calls: _Calls
    currency: str
    produced: int

    @property
    def payload_verdict(self) -> str:
        return self.verdict

    def task_output(self, duration_ms: int, now: datetime, s: Agent11Settings) -> TaskOutput:
        usage = _usage(self.calls, self.currency)
        return TaskOutput(
            status=OutputStatus.SUCCEEDED,
            payload=PayloadObject(
                payload_schema=OUTPUT_SCHEMA,
                payload_schema_version="1.0.0",
                data=json.loads(self.payload.model_dump_json()),
            ),
            output_refs=tuple(self.refs),
            quality_score=None,
            confidence=None,
            validation_results=tuple(self.checks),
            duration=max(0, duration_ms),
            resource_usage=usage,
            error=None,
            next_action=NextAction(
                type=NextActionType.CONTINUE,
                wait_reason=None,
                escalation_level=None,
                reason="set composed",
            ),
            downstream_agent="agent_16",
            timestamp=now,
        )


def _append_audit(
    d: StageDeps, tc: TenantContext, ti: TaskInput, action: str, details: dict[str, Any]
) -> None:
    with d.tenancy.transaction(tc) as t:
        d.audit.append(
            t,
            NewAuditEntry(
                actor_kind=ActorKind.AGENT,
                actor_ref=ActorRef(AGENT_ID),
                authority=AGENT_ID,
                action=action,
                target_kind="job",
                target_id=ti.job_id,
                occurred_at=d.clock.now(),
                job_id=JobId(ti.job_id),
                correlation_id=CorrelationId(ti.correlation_id),
                details=details,
            ),
        )


class _Run:
    """State of one task execution (one tenant, one job)."""

    def __init__(
        self,
        stage: ThumbnailStage,
        ti: TaskInput,
        inp: ThumbnailInput,
        tc: TenantContext,
        attempt: AttemptId,
    ) -> None:
        self.d = stage.d
        self.s = stage.d.settings
        self.ti, self.inp, self.tc, self.attempt = ti, inp, tc, attempt
        self.calls = _Calls()
        self.banned_words: tuple[str, ...] = ()
        self.font_source = "tenant_asset"
        self.fallback_font_bytes: bytes | None = None
        self.fallback_font_source: str | None = None
        self.fallback_weight: int | None = None
        self.fallback_asset_id: str | None = None
        self.scanner = InjectionScanner(
            stage.d.lexicons.injection_markers, stage.d.lexicons.instruction_phrases
        )

    # ------------------------------------------------------------------ helpers
    @contextmanager
    def tx(self) -> Iterator[TenantTransaction]:
        with self.d.tenancy.transaction(self.tc) as t:
            yield t

    def audit(self, action: str, details: dict[str, Any]) -> None:
        _append_audit(self.d, self.tc, self.ti, action, details)

    def _read_blob(self, uri: str, sha: str) -> bytes:
        return b"".join(self.d.storage.get(self.tc, BlobUri(uri), sha))

    def _put(self, uri: str, data: bytes) -> tuple[str, str, int]:
        """Write-once blob at a core-built URI; an identical existing blob is reused."""
        blob = BlobUri(uri)
        head = self.d.storage.head(self.tc, blob)
        sha = _sha(data)
        if head.exists:
            if head.sha256 != sha:
                raise InputInvalidError("a different blob already exists at this path")
            return uri, sha, len(data)
        info = self.d.storage.put(self.tc, blob, io.BytesIO(data))
        return str(info.uri), info.sha256, info.size_bytes

    def _artifact(self, name: str, data: bytes) -> tuple[str, str, int]:
        """A write-once task file of this attempt (``.../attempts/<att>/artifacts/<name>``)."""
        ti = self.ti
        uri = task_artifact_uri(
            self.tc.org_id, JobId(ti.job_id), TaskId(ti.task_id), self.attempt, name
        )
        return self._put(uri, data)

    def _checkpoint(self, step_key: str, state: dict[str, Any]) -> None:
        raw = canonical_json(state)
        ti = self.ti
        uri, sha, _ = self._put(
            checkpoint_uri(
                self.tc.org_id,
                JobId(ti.job_id),
                TaskId(ti.task_id),
                f"{step_key}-{_sha(raw)[:16]}.json",
            ),
            raw,
        )
        with self.tx() as t:
            self.d.checkpoints.write(
                t,
                NewCheckpoint(
                    task_id=TaskId(self.ti.task_id),
                    attempt_id=self.attempt,
                    step_key=step_key,
                    state_ref=uri,
                    state_sha256=sha,
                    completed_effects=(),
                    progress_ratio=Decimal("0"),
                ),
                self.d.clock.now(),
            )

    # ------------------------------------------------------------------ P1, P2
    def execute(self) -> _Result:
        s, inp, ti = self.s, self.inp, self.ti
        with self.tx() as t:
            script = self.d.repo.script_view(t, inp.script_ref.uri, inp.script_ref.sha256)
            self._script_gate(script)
            if script.promise is None or script.brief is None:
                raise InsufficientInputError("title_promise or thumbnail_brief is missing")
            promise, brief = script.promise, script.brief
            category = self.d.repo.channel_category(t, ti.channel_id or "")
            kit = self.d.repo.brand_kit(t, inp.brand_kit_ref.uri, inp.brand_kit_ref.sha256)
            font = self._pick_font(t, kit)
            asset_uris = [r.uri for r in ti.context_refs if r.purpose is ContextRefPurpose.ASSET]
            owner_assets = self.d.repo.owner_assets(t, asset_uris)
            absent = sorted(set(asset_uris) - {a.uri for a in owner_assets})
            if absent:
                raise MissingDependencyError(
                    "an owner asset context reference does not resolve to an asset row",
                    details={"missing": absent},
                )
            hints = self.d.repo.subject_hints(t, inp.shot_plan_ref.uri, inp.shot_plan_ref.sha256)
            prev_manifest = None
            if inp.previous_set_ref:
                prev_manifest = self.d.repo.previous_manifest(
                    t, inp.previous_set_ref.uri, inp.previous_set_ref.sha256
                )
                if prev_manifest is None:
                    raise MissingDependencyError("previous thumbnail set manifest is unreadable")
        finance = self.d.lexicons.is_finance(category)
        self._preflight(finance)  # a11.pre.config: fail closed before any model call
        font_bytes = self._read_blob(font.uri, font.sha256)
        try:
            # the registered asset's recorded hash must match the bytes (fail closed)
            self.font_source = verify_font(font_bytes, font.sha256)
        except FontIntegrityError as exc:
            raise MissingDependencyError(
                "the font bytes do not match the recorded hash of the font asset",
                details={"check_id": "a11.pre.config", "missing": ["font_hash_match"]},
            ) from exc
        if self.s.fonts_policy == "MANIFEST_ONLY" and self.font_source == "tenant_asset":
            raise MissingDependencyError(
                "the font policy of this channel allows only repo-manifest fonts",
                details={"check_id": "a11.pre.config", "missing": ["font_manifest_only"]},
            )
        self._pick_fallback(font_bytes)
        colours = {**palette(), **(kit.colours if kit else {})}
        banned_words = kit.banned_words if kit else ()
        self.banned_words = tuple(banned_words)
        covered_text = " ".join(
            [promise.working_title_local, brief.text_idea_local, *promise.promise_key_terms]
        )
        if self.d.composer.missing_glyphs(
            self.ti.org_id,
            font_bytes,
            covered_text,
            font.sha256,
            self.fallback_font_bytes,
            hashlib.sha256(self.fallback_font_bytes).hexdigest()
            if self.fallback_font_bytes
            else None,
        ):
            raise MissingDependencyError("no font with glyph coverage for the language")

        # Promise material scan: instruction-like content means a human must look (8.4).
        promise_material = " ".join(
            [promise.promise_statement, promise.working_title_local, *promise.promise_key_terms]
        )
        if self.scanner.scan(promise_material).flagged:
            return self._empty_result(
                promise, ComplianceVerdict.NEEDS_HUMAN_REVIEW, "INSTRUCTION_IN_INPUT", (), finance
            )

        text_opts = build_text_options(
            working_title_local=promise.working_title_local,
            promise_key_terms=promise.promise_key_terms,
            brief_text=brief.text_idea_local,
            banned_words=banned_words,
            must_not_promise=brief.must_not_promise,
            finance=finance,
            cfg=TextBuildConfig(s.text_max_words, s.text_max_chars, s.text_max_options),
            lexicon=self.d.lexicons.finance_markers,
            scanner=self.scanner,
        )
        glyphs = [g.facts() for g in glyph_catalogue() if not _banned(g.label, banned_words)]
        pic_opts = build_picture_options(
            assets=[a.facts for a in owner_assets if not _banned(a.facts.label, banned_words)],
            glyphs=glyphs,
            finance=finance,
            cfg=PictureBuildConfig(
                s.asset_min_width_px, s.asset_min_height_px, s.faces_allowed, s.chart_still_allowed
            ),
        )
        templates = offer_templates(self.d.templates, finance=finance)
        self._checkpoint(
            "CK1_OPTIONS",
            {
                "texts": [o.text_id for o in text_opts.options],
                "pictures": [o.option_id for o in pic_opts.options],
                "template_set": template_set_sha256(),
                "script": script.content_sha256,
            },
        )
        stats = {
            "text_built": len(text_opts.options),
            "text_excluded": _count([e.reason for e in text_opts.excluded]),
            "picture_built": len(pic_opts.options),
            "picture_excluded": _count([e.reason for e in pic_opts.excluded]),
            "templates_offered": len(templates),
        }
        call = finance and any(
            finance_text_hit(text, self.d.lexicons.finance_markers)
            for text in (promise.working_title_local, promise.promise_statement)
        )
        if call or not text_opts.options:
            reason = "PROMISE_IS_A_CALL" if call else "NO_ELIGIBLE_TEXT"
            return self._empty_result(
                promise,
                ComplianceVerdict.BLOCKED,
                reason,
                ("FIN-R1",) if call else (),
                finance,
                stats,
            )
        step = self._step_in(
            category, promise, brief, hints, pic_opts, text_opts, templates, prev_manifest
        )
        picks, _omitted, refusal = self._choose(step, finance)
        if refusal is not None:
            return self._refusal_result(promise, refusal, finance, stats)
        ok_picks = [p for p in picks if p.concept.status == "OK"]
        omitted_ids = [
            (p.concept.concept_id, p.concept.reason_code or "NO_DISTINCT_OPTION")
            for p in picks
            if p.concept.status != "OK"
        ]
        if not ok_picks:
            return self._empty_result(
                promise,
                ComplianceVerdict.BLOCKED,
                omitted_ids[0][1] if omitted_ids else "NO_DISTINCT_OPTION",
                (),
                finance,
                stats,
            )
        self._checkpoint(
            "CK2_CONCEPTS",
            {
                "concepts": [p.concept.model_dump(mode="json") for p in picks],
                "calls": len(self.calls.records),
            },
        )
        return self._compose_and_persist(
            promise,
            brief,
            picks,
            [(c, str(r)) for c, r in omitted_ids],
            step,
            pic_opts,
            owner_assets,
            font,
            font_bytes,
            colours,
            finance,
            stats,
            hints_count=len(hints),
        )

    def _preflight(self, finance: bool) -> None:
        """a11.pre.config (blueprint 6.4, 18): a missing or empty list or rule pack is
        ``CONFIG_INVALID`` / ``MISSING_DEPENDENCY``. It is never replaced by a weaker screen."""
        d = self.d
        bad: list[str] = []

        def blank(items: Sequence[str]) -> bool:
            return not any(i.strip() for i in items)

        if blank(d.lexicons.injection_markers):
            bad.append("injection_markers")
        if blank(d.lexicons.instruction_phrases):
            bad.append("instruction_phrases")
        if finance and blank(d.lexicons.finance_markers):
            bad.append("compliance.finance_sebi_in.markers")
        if not d.prompt.text.strip() or _sha(d.prompt.text.encode("utf-8")) != d.prompt.sha256:
            bad.append("prompt_sha256_mismatch")
        needed = ["rp.youtube_general", *(["rp.finance_sebi_in"] if finance else [])]
        bad.extend(f"rule_pack:{t}" for t in needed if not d.packs.platform.get(t, "").strip())
        if bad:
            raise ConfigInvalidError(
                "required list, rule pack or prompt is absent, empty or altered",
                details={
                    "check_id": "a11.pre.config",
                    "violations": [violation(key, "/config") for key in sorted(bad)],
                },
            )
        if not d.composer.raqm_available():
            raise MissingDependencyError(
                "the Raqm layout engine (libraqm with system libfribidi) is not available",
                details={"check_id": "a11.pre.config", "missing": ["raqm"]},
            )

    def _script_gate(self, script: Any) -> None:
        if script.verified_sha256 is None or not (
            script.content_sha256 == self.inp.script_ref.sha256 == script.verified_sha256
        ):
            raise InputInvalidError(
                "script hash differs from the verified hash",
                details={"violations": [violation("SCRIPT_HASH_MISMATCH", "/script_ref/sha256")]},
            )
        if script.verdict != ComplianceVerdict.ALLOWED.value or script.open_blocked_claims:
            raise InputInvalidError(
                "script verdict is not ALLOWED",
                details={"violations": [violation("VERDICT_NOT_ALLOWED", "/script_ref")]},
            )
        if script.promise is None or script.brief is None:
            raise InsufficientInputError("title_promise or thumbnail_brief is missing")

    def _pick_font(self, t: TenantTransaction, kit: BrandKitView | None) -> FontRef:
        want = _SCRIPT_OF[self.inp.language]
        if kit:
            for f in kit.fonts:
                if want in f.scripts:
                    return f
        default = self.d.repo.default_font(t)
        if default is None or want not in default.scripts:
            raise MissingDependencyError("no font with coverage for the language")
        return default

    def _step_in(
        self,
        category: str,
        promise: Any,
        brief: Any,
        hints: Sequence[SubjectHint],
        pics: PictureOptions,
        texts: TextOptions,
        templates: Sequence[Any],
        prev_manifest: dict[str, Any] | None,
    ) -> StepIn:
        previous = None
        if prev_manifest is not None:
            previous = tuple(
                build_previous(
                    prev_manifest["variants"],
                    [o.model_dump() for o in texts.options],
                    [o.model_dump() for o in pics.options],
                    [t.template_key for t in templates],
                    [f.model_dump() for f in self.inp.revision_feedback],
                )
            )
        return StepIn(
            call_seq=1,
            language=self.inp.language,
            channel_category=category,
            variant_count=self.inp.variant_count,
            promise=promise,
            brief=brief,
            subject_hints=tuple(hints[:4]),
            subject_options=tuple(
                PictureOptionView(
                    option_id=o.option_id,
                    kind=o.kind,
                    label=o.label,
                    has_face=o.has_face,
                    direction_neutral=o.direction_neutral,
                )
                for o in pics.options
            ),
            text_options=texts.options,
            templates=tuple(templates),
            banned_subjects=(),
            limits=Limits(max_rationale_chars=self.s.llm_max_rationale_chars),
            retry_context=None,
            previous_concepts=previous,
            revision_feedback=self.inp.revision_feedback,
        )

    # ------------------------------------------------------------------ P3..P5
    def _guard_ctx(self, step: StepIn, finance: bool) -> GuardContext:
        return GuardContext(
            step_in=step,
            finance=finance,
            faces_allowed=self.s.faces_allowed,
            scanner=self.scanner,
            neutral_lexicon=frozenset(fold(w) for w in self.d.lexicons.neutral_words),
            fin_lexicon=self.d.lexicons.finance_markers,
        )

    def _planner(self, finance: bool) -> FallbackPlanner:
        return FallbackPlanner(
            PlannerPolicy(
                finance=finance,
                faces_allowed=self.s.faces_allowed and not finance,
                fin_lexicon=self.d.lexicons.finance_markers,
            )
        )

    def _choose(self, step: StepIn, finance: bool) -> tuple[list[_Pick], list[str], Any]:
        planner = self._planner(finance)
        gctx = self._guard_ctx(step, finance)
        keep_prev = [
            Concept(
                concept_id=p.concept_id,
                status="OK",
                reason_code=None,
                template_key=p.template_key,
                subject_option_id=p.subject_option_id,
                text_ids=p.text_ids,
                angle=p.angle,
                hypothesis_kind=p.hypothesis_kind,
                emphasis_style=p.emphasis_style,
                accent_role=p.accent_role,
                rationale="Repeated from the previous set.",
            )
            for p in (step.previous_concepts or ())
            if p.keep
        ]
        need_ids = [
            f"c{i + 1}"
            for i in range(step.variant_count)
            if f"c{i + 1}" not in {k.concept_id for k in keep_prev}
        ]
        if not self.s.llm_enabled:
            concepts = planner.plan(step, keep_prev, need_ids)
            return (
                [_Pick(c, "FALLBACK" if c.concept_id in need_ids else "LLM") for c in concepts],
                [],
                None,
            )
        self._reserve_budget()
        first: StepOut | None = None
        try:
            first = self._call_parse(step)
        except (
            CircuitOpenError,
            ProviderRefusalError,
            InvalidJsonError,
            OutputSchemaInvalidError,
        ) as exc:
            if not self.s.llm_fallback_on_unavailable:
                raise
            self.calls.fallback_code = exc.code
        if first is None:
            concepts = planner.plan(step, keep_prev, need_ids)
            return [_Pick(c, "FALLBACK") for c in concepts], [], None
        if first.refusal is not None:
            return [], [], first.refusal
        accepted: dict[str, Concept] = {}
        hits = check_concepts(first.concepts, gctx)
        bad = {h.concept_id: h for h in hits}
        for c in first.concepts:
            if c.concept_id not in bad:
                accepted[c.concept_id] = c
        if bad and self.s.llm_max_reasks >= 1 and len(self.calls.records) < 2:
            self.calls.reasks += 1
            retry = tuple(
                RetryEntry(
                    concept_id=c.concept_id,
                    guard_id=bad[c.concept_id].guard if c.concept_id in bad else None,
                    previous=PreviousChoice(
                        template_key=c.template_key or "",
                        subject_option_id=c.subject_option_id or "o00",
                        text_ids=c.text_ids,
                    ),
                )
                for c in first.concepts
            )
            second_step = step.model_copy(update={"call_seq": 2, "retry_context": retry})
            try:
                second = self._call_parse(second_step, seq=2)
            except (
                InvalidJsonError,
                OutputSchemaInvalidError,
                CircuitOpenError,
                ProviderRefusalError,
            ) as exc:
                if not self.s.llm_fallback_on_unavailable:
                    raise
                self.calls.fallback_code = exc.code
                second = None
            if second is not None and second.refusal is None:
                second_hits = {h.concept_id for h in check_concepts(second.concepts, gctx)}
                for c in second.concepts:
                    if c.concept_id in bad and c.concept_id not in second_hits:
                        accepted[c.concept_id] = c
        remaining = [f"c{i + 1}" for i in range(step.variant_count) if f"c{i + 1}" not in accepted]
        picks: dict[str, _Pick] = {cid: _Pick(c, "LLM") for cid, c in accepted.items()}
        if remaining:
            planned = planner.plan(step, [*keep_prev, *accepted.values()], remaining)
            for c in planned:
                if c.concept_id in remaining:
                    picks[c.concept_id] = _Pick(c, "FALLBACK")
        ordered = [picks[f"c{i + 1}"] for i in range(step.variant_count)]
        if check_concepts([p.concept for p in ordered], gctx):  # backstop: the whole set again
            ordered = [_Pick(c, "FALLBACK") for c in planner.plan(step)]
        return ordered, [], None

    def _reserve_budget(self) -> None:
        with self.tx() as t:
            outcome = self.d.budget.reserve(
                t,
                TaskId(self.ti.task_id),
                self.ti.resource_budget.max_cost_micros,
                self.ti.resource_budget.currency,
            )
        if not outcome.granted:
            raise BudgetExhaustedError("no budget reservation for the concept call")

    def _call_parse(self, step: StepIn, seq: int = 1) -> StepOut:
        """One call plus, on a parse failure, one retry with the validation error (07 3.3)."""
        parse_error: str | None = None
        for attempt in range(2):
            call_seq = seq + attempt
            if len(self.calls.records) >= 2:
                break
            text = self._one_call(
                step.model_copy(update={"call_seq": call_seq}), call_seq, parse_error
            )
            try:
                return parse_output(text)
            except (InvalidJsonError, OutputSchemaInvalidError) as exc:
                parse_error = str(exc.details or exc.message)
                if attempt == 1:
                    raise
        raise OutputSchemaInvalidError("model output unusable after the retry")

    def _one_call(self, step: StepIn, call_seq: int, parse_error: str | None) -> str:
        s, d = self.s, self.d
        request = render_request(
            step,
            d.prompt,
            model=s.model_id,
            max_output_tokens=s.max_output_tokens,
            temperature=s.temperature,
            timeout_ms=s.timeout_ms,
            cache_system_prompt=s.cache_system_prompt,
            platform_packs=d.packs.platform,
            tenant_pack_text=d.packs.tenant_text,
            parse_error=parse_error,
        )
        key = make_idempotency_key(
            self.ti.org_id, "llm.call", [self.ti.task_id, "concepts", call_seq]
        )
        req_sha = _sha(request.model_dump_json().encode("utf-8"))
        reconciled = False
        with self.tx() as t:
            est = (len(request.system) + sum(len(m.content) for m in request.messages)) // 4
            d.budget.check_call(
                t,
                CallCheck(
                    task_id=TaskId(self.ti.task_id),
                    job_id=JobId(self.ti.job_id),
                    provider=d.llm.provider,
                    estimated_cost_micros=est * s.price_in_micros_per_token
                    + s.max_output_tokens * s.price_out_micros_per_token,
                    currency=s.currency,
                    tokens_in=est,
                    tokens_out=s.max_output_tokens,
                ),
            )
            decision = d.idem.begin(
                t,
                key,
                "llm.call",
                req_sha,
                TaskId(self.ti.task_id),
                d.clock.now(),
                s.timeout_ms + 5000,
            )
            if decision.action is BeginAction.RETURN_STORED and decision.record.result_ref:
                uri = decision.record.result_ref
                head = d.storage.head(self.tc, BlobUri(uri))
                self.calls.records.append({"call_seq": call_seq, "replayed": True})
                return self._read_blob(uri, head.sha256 or "").decode("utf-8")
            if decision.action is BeginAction.IN_FLIGHT:
                raise LockConflictError("another attempt holds this LLM call; retry later")
            if decision.action is BeginAction.RECONCILE:
                # 07 section 11: a completion has no external effect to look up (nothing is
                # written by the provider), so the reconciliation is to mark the stale key FAILED
                # (its cost, if any, is unknown and stays unrecorded) and run the call again.
                d.idem.fail(t, key, d.clock.now())
                reconciled = True
                decision = d.idem.begin(
                    t,
                    key,
                    "llm.call",
                    req_sha,
                    TaskId(self.ti.task_id),
                    d.clock.now(),
                    s.timeout_ms + 5000,
                )
            if decision.action is not BeginAction.PROCEED:
                raise LockConflictError("the LLM call could not be reconciled; retry later")
            try:
                response = d.llm.complete(request, idempotency_key=key)
            except Exception:
                d.idem.fail(t, key, d.clock.now())
                raise
            u = response.usage
            entry = d.costs.record(
                t,
                NewCostEntry(
                    provider=u.provider,
                    operation=CostOperation.LLM_COMPLETION,
                    amount_micros=u.amount_micros,
                    currency=u.currency,
                    figure_kind=CostFigureKind.ESTIMATE,
                    occurred_at=d.clock.now(),
                    job_id=JobId(self.ti.job_id),
                    task_id=TaskId(self.ti.task_id),
                    attempt_id=self.attempt,
                    channel_id=ChannelId(self.ti.channel_id) if self.ti.channel_id else None,
                    agent_id=ExecutorId(AGENT_ID),
                    model=request.model,
                    billing_mode=BillingMode.STANDARD,
                    tokens_in=u.tokens_in,
                    tokens_out=u.tokens_out,
                    tokens_cached_in=u.tokens_cached_in,
                    tokens_cache_write_in=u.tokens_cache_write_in,
                    chars_in=u.chars_in,
                    language=step.language,
                    price_ref=u.price_ref,
                    idempotency_key=key,
                ),
            )
            d.budget.after_call(t, entry)
            raw = response.text.encode("utf-8")
            uri, _sha_hex, _ = self._artifact(f"llm/concepts-{call_seq}-{_sha(raw)[:16]}.json", raw)
            d.idem.complete(t, key, uri, d.clock.now())
        self.calls.cost_entry_ids.append(str(entry.id))
        self.calls.cost_micros += u.amount_micros
        self.calls.tokens_in += u.tokens_in or 0
        self.calls.tokens_out += u.tokens_out or 0
        self.calls.tokens_cached += u.tokens_cached_in or 0
        self.calls.records.append(
            {
                "step_key": "concepts",
                "call_seq": call_seq,
                "provider": u.provider,
                "model": request.model,
                "tokens_in": u.tokens_in or 0,
                "tokens_out": u.tokens_out or 0,
                "tokens_cached_in": u.tokens_cached_in or 0,
                "cost_entry_id": str(entry.id),
                "reconciled_stale_key": reconciled,
            }
        )
        return response.text

    # ------------------------------------------------------------------ P6..P9
    def _build_spec(
        self,
        org: str,
        tpl: TemplateSpec,
        concept: Concept,
        texts: Sequence[TextOption],
        pic: PictureOption,
        owner: OwnerAsset | None,
        glyph: GlyphSpec | None,
        promise_terms: tuple[str, ...],
        colours: dict[str, str],
        font: FontRef,
        font_bytes: bytes,
        accent: str,
        cap: int | None,
        image: bytes | None,
    ) -> RenderSpec:
        return RenderSpec(
            org_id=org,
            canvas_w=self.s.canvas_width_px,
            canvas_h=self.s.canvas_height_px,
            template=tpl,
            colours=colours,
            lines=tuple(t.text for t in texts),
            emphasis=concept.emphasis_style or "PLAIN",
            accent_role=accent,
            key_terms=promise_terms,
            picture_kind=pic.kind,
            glyph=glyph,
            image_bytes=image,
            image_sha256=owner.content_sha256 if owner else None,
            font_bytes=font_bytes,
            font_sha256=font.sha256,
            min_font_px=self.s.text_min_font_px,
            max_font_px=self.s.text_max_font_px,
            font_step_px=self.s.text_font_step_px,
            font_cap_px=cap,
            fallback_font_bytes=self.fallback_font_bytes,
            fallback_font_sha256=(
                hashlib.sha256(self.fallback_font_bytes).hexdigest()
                if self.fallback_font_bytes
                else None
            ),
            fallback_weight=self.fallback_weight,
        )

    def _pick_fallback(self, font_bytes: bytes) -> None:
        """Per-glyph fallback (owner decision WS-06): only when the primary is a repo-manifest
        brand font (purpose ``brand_primary``), and only the pinned fallback font. A tenant's own
        font gets no fallback: its coverage and licence stay as the tenant registered them."""
        self.fallback_font_bytes = None
        self.fallback_font_source = None
        self.fallback_weight = None
        pinned = font_manifest().get(hashlib.sha256(font_bytes).hexdigest())
        if pinned is None or pinned.purpose != "brand_primary":
            return
        fallback = pinned_font_bytes(FALLBACK_FONT_KEY)
        if fallback != font_bytes:
            self.fallback_font_bytes = fallback
            self.fallback_font_source = f"repo_manifest:{FALLBACK_FONT_KEY}"
            self.fallback_weight = pinned.weight

    def _compose_and_persist(
        self,
        promise: Any,
        brief: Any,
        picks: list[_Pick],
        omitted_pre: list[tuple[str, str]],
        step: StepIn,
        pics: PictureOptions,
        owner_assets: list[OwnerAsset],
        font: FontRef,
        font_bytes: bytes,
        colours: dict[str, str],
        finance: bool,
        stats: dict[str, Any],
        hints_count: int,
    ) -> _Result:
        s = self.s
        org = self.ti.org_id
        tpl_by_key = {t.template_key: t for t in self.d.templates}
        glyph_by_key = {g.key: g for g in glyph_catalogue()}
        owner_by_sha = {a.facts.sha: a for a in owner_assets}
        pic_by_id = {o.option_id: o for o in pics.options}
        txt_by_id = {o.text_id: o for o in step.text_options}
        w, h = s.canvas_width_px, s.canvas_height_px
        m = s.layout_safe_margin_permille
        safe = (w * m // 1000, h * m // 1000, w - w * m // 1000, h - h * m // 1000)
        corner = reserved_corner_rect(s.layout_reserved_corner, w, h)
        omitted = [(c, r) for c, r in omitted_pre]
        built: list[tuple[_Pick, VariantFacts, RenderResult, RenderSpec]] = []
        for pick in picks:
            c = pick.concept
            if c.status != "OK" or c.template_key is None or c.subject_option_id is None:
                continue
            tpl = tpl_by_key[c.template_key]
            pic = pic_by_id[c.subject_option_id]
            texts = [txt_by_id[i] for i in c.text_ids]
            owner = owner_by_sha.get(pic.key) if pic.kind == "OWNER_IMAGE" else None
            glyph = glyph_by_key.get(pic.key) if pic.kind == "CODE_GLYPH" else None
            image = None
            if owner is not None:
                image = self._read_blob(owner.uri, owner.content_sha256)
            fact = _picture_fact(owner)
            accent = c.accent_role or "PRIMARY"
            cap: int | None = None
            result: tuple[RenderResult, RenderSpec, VariantFacts] | None = None
            for attempt in range(2):
                spec = self._build_spec(
                    org,
                    tpl,
                    c,
                    texts,
                    pic,
                    owner,
                    glyph,
                    tuple(promise.promise_key_terms),
                    colours,
                    font,
                    font_bytes,
                    accent,
                    cap,
                    image,
                )
                try:
                    rr = self.d.composer.render(spec)
                except GlyphMissingError:
                    break
                except TextDoesNotFitError:
                    rr = None
                except ComposeFailedError as exc:
                    raise AgentCrashError("composition failed") from exc
                if rr is not None:
                    facts = VariantFacts(
                        variant_id="v" + c.concept_id[1:],
                        concept=c,
                        template_key=tpl.template_key,
                        template_direction_neutral=tpl.direction_neutral,
                        picture=pic,
                        picture_fact=fact,
                        texts=tuple(texts),
                        render=rr,
                        file_size_bytes=len(rr.png),
                        text_local=" ".join(rr.lines),
                        rationale_ok=rationale_ok(c.rationale, self._guard_ctx(step, finance)),
                    )
                    if not variant_failures(facts, s, safe, corner):
                        result = (rr, spec, facts)
                        break
                    base = rr.font_px
                else:
                    base = cap or s.text_max_font_px
                if attempt == 0:  # the one code repair: font step down, then another accent role
                    cap = max(s.text_min_font_px, base - s.text_font_step_px)
                    accent = _ACCENT_ROLES[(_ACCENT_ROLES.index(accent) + 1) % 3]
            if result is None:
                omitted.append((c.concept_id, "CHECK_FAILED"))
                continue
            rr, spec, facts = result
            near = [
                b
                for b in built
                if bin(int(b[2].phash, 16) ^ int(rr.phash, 16)).count("1")
                < s.distinct_min_hash_distance_bits
            ]
            if near:
                omitted.append((c.concept_id, "CHECK_FAILED"))
                continue
            built.append((pick, facts, rr, spec))
        if not built or built[0][0].concept.concept_id != "c1":
            raise QualityRepeatedFailureError(
                "no variant (or no control) passed the blocking checks",
                details={"omitted": omitted},
            )
        return self._persist_and_finish(
            promise,
            built,
            omitted,
            step,
            pics,
            owner_by_sha,
            glyph_by_key,
            font,
            tpl_by_key,
            finance,
            stats,
            safe,
            corner,
        )

    def _persist_and_finish(
        self,
        promise: Any,
        built: list[Any],
        omitted: list[tuple[str, str]],
        step: StepIn,
        pics: PictureOptions,
        owner_by_sha: dict[str, OwnerAsset],
        glyph_by_key: dict[str, GlyphSpec],
        font: FontRef,
        tpl_by_key: dict[str, TemplateSpec],
        finance: bool,
        stats: dict[str, Any],
        safe: tuple[int, int, int, int],
        corner: tuple[int, int, int, int],
    ) -> _Result:
        s = self.s
        job, task = self.ti.job_id, self.ti.task_id
        files: list[tuple[str, str, int, str]] = []  # (asset_id, uri, size, sha)
        with self.tx() as t:
            lic_id = self.d.repo.licence_id_code_generated(t)
            wanted = {("FONT", font.asset_id)} | {("TEMPLATE", b[1].template_key) for b in built}
            if any(b[2].fallback_used for b in built):
                # The fallback font drew pixels: it is a used FONT like any other (asset, licence
                # row, ledger row, LicenceFact). The registry row key is the manifest font key.
                wanted.add(("FONT", FALLBACK_FONT_KEY))
            if any(b[1].picture.kind == "CODE_GLYPH" for b in built):
                wanted.add(("TEMPLATE", "glyphset"))
            registered = self.d.repo.registered_assets(t, sorted(wanted))
            missing = sorted(k for k in wanted if k not in registered)
            if missing:
                raise MissingDependencyError(
                    "template, glyph-set or font asset is not registered for the tenant",
                    details={"missing": [list(k) for k in missing]},
                )
            # Whole-set blocking checks run BEFORE any blob, asset row or ledger row is written
            # (03 9.2, blueprint 6.7): a licence or set failure leaves nothing behind.
            planned: list[tuple[str, str]] = []
            for _pick, facts, _rr, _spec in built:
                planned += [
                    (registered[("TEMPLATE", facts.template_key)].asset_id, "TEMPLATE"),
                    (registered[("FONT", font.asset_id)].asset_id, "FONT"),
                ]
                if _rr.fallback_used:
                    planned.append((registered[("FONT", FALLBACK_FONT_KEY)].asset_id, "FONT"))
                if facts.picture.kind == "OWNER_IMAGE":
                    planned.append((owner_by_sha[facts.picture.key].asset_id, "IMAGE"))
                elif facts.picture.kind == "CODE_GLYPH":
                    planned.append((registered[("TEMPLATE", "glyphset")].asset_id, "TEMPLATE"))
            if ("FONT", FALLBACK_FONT_KEY) in wanted:
                self.fallback_asset_id = registered[("FONT", FALLBACK_FONT_KEY)].asset_id
            expected = [LedgerRow(a, k, job, False) for a, k in planned]
            checks = self._set_checks(
                promise,
                built,
                step,
                finance,
                safe,
                corner,
                self._licence_facts(built, owner_by_sha, registered, expected, job, font),
            )
            failed = [r.check_id for r in checks if r.blocking and r.verdict.value == "FAIL"]
            if failed:
                raise QualityRepeatedFailureError(
                    "blocking checks failed", details={"check_ids": failed}
                )
            for _pick, facts, rr, _spec in built:
                name = f"thumbnails/{facts.variant_id}-{_sha(rr.png)[:16]}.png"
                uri, sha, size = self._artifact(name, rr.png)
                tier = "A_OWNER_REAL" if facts.picture.kind == "OWNER_IMAGE" else "C_CODE_MOTION"
                asset_id = self.d.repo.insert_image_asset(
                    t,
                    NewImageAsset(
                        sha,
                        uri,
                        size,
                        rr.width,
                        rr.height,
                        tier,
                        {"licence_id": lic_id, "composition_sha256": rr.composition_sha256},
                    ),
                )
                files.append((asset_id, uri, size, sha))
                used = [("TEMPLATE", facts.template_key), ("FONT", font.asset_id)]
                if rr.fallback_used:
                    used.append(("FONT", FALLBACK_FONT_KEY))
                for kind, key in used:
                    self.d.repo.insert_ledger_row(
                        t, NewLedgerRow(registered[(kind, key)].asset_id, kind, job, task)
                    )
                if facts.picture.kind == "OWNER_IMAGE":
                    self.d.repo.insert_ledger_row(
                        t,
                        NewLedgerRow(owner_by_sha[facts.picture.key].asset_id, "IMAGE", job, task),
                    )
                elif facts.picture.kind == "CODE_GLYPH":
                    self.d.repo.insert_ledger_row(
                        t,
                        NewLedgerRow(
                            registered[("TEMPLATE", "glyphset")].asset_id, "TEMPLATE", job, task
                        ),
                    )
            ledger = self.d.repo.ledger_rows(t, job)
            written = {(r.asset_id, r.usage_kind) for r in ledger if r.job_id == job}
            if not set(planned) <= written:  # rolls the whole transaction back
                raise IncompleteOutputError("a licence ledger row was not written")
        for i in range(len(built)):
            self._checkpoint(f"CK3_VARIANT_{i + 1}", {"sha256": files[i][3], "check": "persisted"})
        manifest_variants = []
        payload_variants: list[PayloadVariant] = []
        for (pick, facts, rr, spec), (asset_id, uri, size, sha) in zip(built, files, strict=True):
            c = pick.concept
            owner = (
                owner_by_sha.get(facts.picture.key) if facts.picture.kind == "OWNER_IMAGE" else None
            )
            pic_asset = owner.asset_id if owner else None
            manifest_variants.append(
                {
                    "variant_id": facts.variant_id,
                    "concept_id": c.concept_id,
                    "is_control": c.concept_id == "c1",
                    "hypothesis_kind": c.hypothesis_kind,
                    "angle": c.angle,
                    "emphasis_style": c.emphasis_style,
                    "accent_role": spec.accent_role,
                    "template_key": facts.template_key,
                    "picture": {
                        "kind": facts.picture.kind,
                        "key": facts.picture.key,
                        "asset_id": pic_asset,
                    },
                    "texts": [{"text_id": t.text_id, "text": t.text} for t in facts.texts],
                    "text_local": facts.text_local,
                    "file": {"asset_id": asset_id, "uri": uri, "sha256": sha},
                }
            )
            covered = tuple(
                k
                for k in promise.promise_key_terms
                if contains_sequence(folded_words(facts.text_local), folded_words(k))
            )
            payload_variants.append(
                PayloadVariant(
                    variant_id=facts.variant_id,
                    concept_id=c.concept_id,
                    is_control=c.concept_id == "c1",
                    hypothesis_kind=c.hypothesis_kind or "CONTROL",
                    angle=c.angle or "TERM_CLARITY",
                    planned_by=pick.planned_by,
                    template_key=facts.template_key,
                    template_version=tpl_by_key[facts.template_key].version,
                    picture=PayloadPicture(
                        option_id=facts.picture.option_id,
                        kind=facts.picture.kind,
                        asset_id=pic_asset,
                        has_face=facts.picture.has_face,
                        direction_neutral=facts.picture.direction_neutral,
                    ),
                    text_ids=c.text_ids,
                    text_lines_local=rr.lines,
                    text_local=facts.text_local,
                    text_language=self.inp.language,
                    emphasis_style=c.emphasis_style or "PLAIN",
                    accent_role=spec.accent_role,
                    promise_terms_covered=covered,
                    rationale=c.rationale,
                    file=PayloadFile(
                        asset_id=asset_id,
                        uri=uri,
                        sha256=sha,
                        size_bytes=size,
                        media_type="image/png",
                        width_px=rr.width,
                        height_px=rr.height,
                    ),
                    composition_sha256=rr.composition_sha256,
                )
            )
        base = {
            "iteration": self.inp.iteration,
            "language": self.inp.language,
            "aspect_ratio": "16:9",
            "canvas": {
                "width_px": s.canvas_width_px,
                "height_px": s.canvas_height_px,
                "format": s.output_format,
            },
            "variants": manifest_variants,
        }
        # The URI is a location, which changes with the attempt (03 section 8 rule 5, CCR-208);
        # the file hash stays in the hashed manifest, so a replay keeps the same set hash.
        set_hash = set_sha256(
            {
                **base,
                "variants": [
                    {**v, "file": {k: x for k, x in v["file"].items() if k != "uri"}}
                    for v in manifest_variants
                ],
            }
        )
        manifest = Manifest.model_validate({**base, "set_sha256": set_hash})
        manifest_bytes = canonical_json(manifest.model_dump(mode="json"))
        fallback_ids = tuple(
            p.concept.concept_id for p in (b[0] for b in built) if p.planned_by == "FALLBACK"
        )
        payload = OutputPayload(
            verdict="ALLOWED",
            iteration=self.inp.iteration,
            language=self.inp.language,
            aspect_ratio="16:9",
            canvas=manifest.canvas,
            variant_count_requested=self.inp.variant_count,
            variant_count_produced=len(built),
            variants=tuple(payload_variants),
            violated_rule_ids=(),
            omitted=tuple(Omitted(concept_id=c, reason_code=r) for c, r in omitted),
            promise={
                "promise_sha256": _sha(canonical_json(promise.model_dump(mode="json"))),
                "promise_key_terms": list(promise.promise_key_terms),
            },
            option_stats=stats,
            chart_stills_used=(),
            planner=PlannerInfo(
                llm_enabled=s.llm_enabled,
                llm_calls=self.calls.paid,
                reasks=self.calls.reasks,
                fallback_concepts=fallback_ids,
            ),
            set_sha256=set_hash,
            refusal=None,
            provenance=self._provenance(font),
        )
        m_uri, m_sha, m_size = self._artifact(
            f"thumbnails/manifest-{set_hash[:16]}.json", manifest_bytes
        )
        refs = [
            OutputRef(
                uri=f.uri,
                kind=OutputRefKind.IMAGE,
                sha256=f.sha256,
                size_bytes=f.size_bytes,
                media_type="image/png",
                entity_ref=f.uri,
            )
            for f in payload_variants_files(payload_variants)
        ]
        refs.append(
            OutputRef(
                uri=m_uri,
                kind=OutputRefKind.DATA,
                sha256=m_sha,
                size_bytes=m_size,
                media_type="application/json",
            )
        )
        return _Result(
            "ALLOWED",
            payload,
            refs,
            checks,
            self.calls,
            self.ti.resource_budget.currency,
            len(built),
        )

    def _set_checks(
        self,
        promise: Any,
        built: list[Any],
        step: StepIn,
        finance: bool,
        safe: tuple[int, int, int, int],
        corner: tuple[int, int, int, int],
        facts_all: tuple[LicenceFact, ...],
    ) -> list[Any]:
        s = self.s
        return run_checks(
            CheckContext(
                settings=s,
                verdict=ComplianceVerdict.ALLOWED,
                finance=finance,
                requested=self.inp.variant_count,
                variants=tuple(b[1] for b in built),
                promise_key_terms=tuple(promise.promise_key_terms),
                must_not_promise=tuple(step.brief.must_not_promise),
                banned_words=self.banned_words,
                fin_lexicon=self.d.lexicons.finance_markers,
                faces_allowed=s.faces_allowed,
                licence_facts=facts_all,
                schema_ok=True,
                llm_calls=self.calls.paid,
                cost_micros=self.calls.cost_micros,
                reserved_micros=self.ti.resource_budget.max_cost_micros,
                max_cost_micros=self.ti.resource_budget.max_cost_micros,
                cost_entry_ids=tuple(self.calls.cost_entry_ids),
                llm_fallback_code=self.calls.fallback_code,
                safe_rect=safe,
                reserved_corner_rect=corner,
            )
        )

    def _licence_facts(
        self,
        built: list[Any],
        owner_by_sha: dict[str, OwnerAsset],
        registered: dict[tuple[str, str], RegisteredAsset],
        ledger: Sequence[Any],
        job: str,
        font: FontRef,
    ) -> tuple[LicenceFact, ...]:
        rows = {(r.asset_id, r.usage_kind): r for r in ledger if r.job_id == job}
        out: dict[tuple[str, str], LicenceFact] = {}

        def reg(kind: str, key: str) -> None:
            a = registered[(kind, key)]
            row = rows.get((a.asset_id, kind))
            out[(a.asset_id, kind)] = LicenceFact(
                a.asset_id,
                kind,
                row is not None,
                bool(row and row.has_interval),
                a.licence_state,
                a.covers_monetized,
                None,
                a.source_type,
                a.expired,
            )

        reg("FONT", font.asset_id)
        for b in built:
            f: VariantFacts = b[1]
            if b[2].fallback_used:
                reg("FONT", FALLBACK_FONT_KEY)
            reg("TEMPLATE", f.template_key)
            if f.picture.kind == "CODE_GLYPH":
                reg("TEMPLATE", "glyphset")
            elif f.picture.kind == "OWNER_IMAGE":
                o = owner_by_sha[f.picture.key]
                row = rows.get((o.asset_id, "IMAGE"))
                out[(o.asset_id, "IMAGE")] = LicenceFact(
                    o.asset_id,
                    "IMAGE",
                    row is not None,
                    bool(row and row.has_interval),
                    o.facts.licence_state,
                    o.facts.covers_monetized,
                    o.facts.third_party_permission,
                    o.facts.source_type,
                    o.facts.expired,
                )
        return tuple(out.values())

    def _provenance(self, font: FontRef) -> dict[str, Any]:
        return {
            "prompt_id": self.d.prompt.prompt_id,
            "prompt_sha256": self.d.prompt.sha256,
            "rule_pack_versions": {},
            "config_key_families": ["agent_11.", "llm.agent_11.thumbnail_variants.concepts."],
            "composer_version": "pillow-raqm",
            "template_set_sha256": template_set_sha256(),
            "font_asset_ids": [
                font.asset_id,
                *([self.fallback_asset_id] if self.fallback_asset_id else []),
            ],
            "font_source": self.font_source,
            "font_fallback_source": self.fallback_font_source,
            "font_fallback_used": self.fallback_asset_id is not None,
            "render_environment": render_environment(),
            "calls": self.calls.records,
        }

    # ------------------------------------------------------------------ empty results
    def _empty_result(
        self,
        promise: Any,
        verdict: ComplianceVerdict,
        reason: str,
        rules: tuple[str, ...],
        finance: bool,
        stats: dict[str, Any] | None = None,
    ) -> _Result:
        s = self.s
        omitted = tuple(
            Omitted(concept_id=f"c{i + 1}", reason_code=reason)
            for i in range(self.inp.variant_count)
        )
        payload = OutputPayload(
            verdict=verdict.value,
            iteration=self.inp.iteration,
            language=self.inp.language,
            aspect_ratio="16:9",
            canvas={
                "width_px": s.canvas_width_px,
                "height_px": s.canvas_height_px,
                "format": s.output_format,
            },
            variant_count_requested=self.inp.variant_count,
            variant_count_produced=0,
            variants=(),
            violated_rule_ids=rules,
            omitted=omitted,
            promise={
                "promise_sha256": _sha(canonical_json(promise.model_dump(mode="json"))),
                "promise_key_terms": list(promise.promise_key_terms),
            },
            option_stats=stats or {},
            chart_stills_used=(),
            planner=PlannerInfo(
                llm_enabled=s.llm_enabled,
                llm_calls=self.calls.paid,
                reasks=0,
                fallback_concepts=(),
            ),
            set_sha256=None,
            refusal=None,
            provenance={
                "prompt_id": self.d.prompt.prompt_id,
                "prompt_sha256": self.d.prompt.sha256,
                "template_set_sha256": template_set_sha256(),
                "calls": self.calls.records,
            },
        )
        checks = run_checks(self._empty_ctx(verdict, finance))
        return _Result(
            verdict.value, payload, [], checks, self.calls, self.ti.resource_budget.currency, 0
        )

    def _empty_ctx(self, verdict: ComplianceVerdict, finance: bool) -> CheckContext:
        return CheckContext(
            settings=self.s,
            verdict=verdict,
            finance=finance,
            requested=self.inp.variant_count,
            variants=(),
            promise_key_terms=(),
            must_not_promise=(),
            banned_words=self.banned_words,
            fin_lexicon=self.d.lexicons.finance_markers,
            faces_allowed=self.s.faces_allowed,
            licence_facts=(),
            schema_ok=True,
            llm_calls=self.calls.paid,
            cost_micros=self.calls.cost_micros,
            reserved_micros=self.ti.resource_budget.max_cost_micros,
            max_cost_micros=self.ti.resource_budget.max_cost_micros,
            cost_entry_ids=tuple(self.calls.cost_entry_ids),
            llm_fallback_code=self.calls.fallback_code,
        )

    def _refusal_result(
        self, promise: Any, refusal: Any, finance: bool, stats: dict[str, Any]
    ) -> _Result:
        """Refusal mapping of blueprint 8.4."""
        r = refusal.reason
        if r == "INSUFFICIENT_INPUT":
            raise InsufficientInputError("the concept step reports insufficient input")
        if r in ("OUT_OF_SCOPE", "CONFLICTING_INSTRUCTIONS"):
            raise InputInvalidError("the concept step refused the input")
        verdict = (
            ComplianceVerdict.NEEDS_HUMAN_REVIEW
            if r == "UNSAFE_CONTENT"
            else ComplianceVerdict.BLOCKED
        )
        out = self._empty_result(
            promise,
            verdict,
            "PROMISE_IS_A_CALL" if verdict is ComplianceVerdict.BLOCKED else "INSTRUCTION_IN_INPUT",
            tuple(refusal.violated_rule_ids),
            finance,
            stats,
        )
        return out


def payload_variants_files(variants: Sequence[PayloadVariant]) -> list[PayloadFile]:
    return [v.file for v in variants]


def _banned(label: str, banned: Sequence[str]) -> bool:
    folded = fold(label)
    return any(fold(b) in folded for b in banned if b.strip())


def _count(reasons: Sequence[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in reasons:
        out[r] = out.get(r, 0) + 1
    return out


def _picture_fact(owner: OwnerAsset | None) -> PictureFact:
    if owner is None:
        return PictureFact(None, False, False, None, False, False, False)
    f = owner.facts
    return PictureFact(
        owner.asset_kind,
        f.depicts_real_person,
        f.release_ref,
        f.data_age_vs_lag,
        f.label_free,
        f.direction_balanced,
        owner.data_end_date_present,
    )


_unused = (GuardHit, GlyphFacts, BrandKitView, _DIRECT)
