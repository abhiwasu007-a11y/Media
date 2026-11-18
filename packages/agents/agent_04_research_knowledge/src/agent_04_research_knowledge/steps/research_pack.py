"""ResearchPackStep: sequences S0 to S7 of ``agent_04.research_pack`` (blueprint 4, 10.1, 16).

Every failure is returned as a ``TaskOutput`` with an ``amw.error`` (never raised to the worker).
A replay of the same (job, stage, task type, iteration) returns the stored output; a crash after
a step resumes from the latest checkpoint without repeating a paid call.
"""

import hashlib
import json
import resource
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from io import BytesIO
from typing import Any

from pydantic import BaseModel, ValidationError

from agent_04_research_knowledge.errors import (
    ConfigInvalid,
    QualityRepeatedFailure,
    TopicBlocked,
    TopicNeedsReview,
)
from agent_04_research_knowledge.guards.copy_guard import CopyResult
from agent_04_research_knowledge.guards.restricted import TopicFlags
from agent_04_research_knowledge.guards.tenant import TenantCheck, TenantDirectory, TenantGuard
from agent_04_research_knowledge.library.models import CollectionView, SourceView, TenantScope
from agent_04_research_knowledge.library.protocol import KnowledgeLibrary
from agent_04_research_knowledge.llm import StructuredLlmCaller
from agent_04_research_knowledge.memory import PackMemory
from agent_04_research_knowledge.models.common import Refusal
from agent_04_research_knowledge.models.enums import (
    CopyGuardStatus,
    ExclusionReason,
    FetchStatus,
    ReliabilityTier,
)
from agent_04_research_knowledge.models.notes import NoteCandidate
from agent_04_research_knowledge.models.pack_input import (
    PAYLOAD_SCHEMA,
    PAYLOAD_SCHEMA_VERSION,
    ResearchPackInput,
)
from agent_04_research_knowledge.models.pack_output import (
    PACK_OUTPUT_SCHEMA,
    PACK_OUTPUT_SCHEMA_VERSION,
    PackTopic,
    ResearchPack,
)
from agent_04_research_knowledge.models.plan import (
    PlanCollection,
    PlanGap,
    PlannedConcept,
    ResearchPlan,
    ResearchPlanInput,
)
from agent_04_research_knowledge.observability import CoreAuditSink, EventLogger, LogContext
from agent_04_research_knowledge.prompts import NOTES_PROMPT_ID, PLAN_PROMPT_ID, PromptLoader
from agent_04_research_knowledge.runtime import CallCounter, RunInfo
from agent_04_research_knowledge.scoring.reliability import ReliabilityScorer, SourceMeta
from agent_04_research_knowledge.settings import ResearchSettings
from agent_04_research_knowledge.steps.assemble import (
    Assembly,
    AssemblyInput,
    CitationMeta,
    ConceptEvidence,
    PackAssembler,
    SourceRecord,
    blocked_pack,
)
from agent_04_research_knowledge.steps.external import (
    ExternalReferenceFetcher,
    FetchedSource,
    SnapshotWriter,
)
from agent_04_research_knowledge.steps.notes import (
    DroppedNote,
    EvidenceNoter,
    NoteLimits,
    NotesResult,
    PassageSource,
    ValidatedNote,
)
from agent_04_research_knowledge.steps.plan import ConceptPlanner
from agent_04_research_knowledge.steps.retrieve import (
    LibraryRetriever,
    RetrievalLimits,
    RetrievalResult,
    allowed_collections,
    rank_candidates,
)
from agent_04_research_knowledge.steps.validate_pack import (
    CitationResolver,
    PackValidator,
    notes_refused_result,
)
from amw_adapters.llm.protocol import LlmAdapter
from amw_adapters.web_fetch.protocol import WebFetchAdapter
from amw_core.contracts.common import PayloadObject
from amw_core.contracts.error import ErrorObject, error_object_from_exception
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import (
    NextAction,
    OutputRef,
    ResourceUsage,
    TaskOutput,
    ValidationResult,
)
from amw_core.enums import (
    CheckVerdict,
    ComplianceVerdict,
    IdempotencyStatus,
    KnowledgeSourceKind,
    NextActionType,
    OutputRefKind,
    OutputStatus,
    OwnerReferenceKind,
    VideoKind,
)
from amw_core.errors import (
    AmwError,
    BudgetExhaustedError,
    CrossTenantRefError,
    LockConflictError,
    SchemaInvalidError,
    SchemaVersionUnsupportedError,
    UnsupportedTaskError,
)
from amw_core.ids import (
    AttemptId,
    ExecutorId,
    IdempotencyKey,
    JobId,
    TaskId,
    make_idempotency_key,
)
from amw_core.interfaces import (
    AuditLog,
    BlobStorage,
    BlobUri,
    BudgetGuard,
    CheckpointStore,
    Clock,
    CostLedger,
    IdempotencyStore,
    NewCheckpoint,
    TenancyContext,
    TenantContext,
)
from amw_core.interfaces.idempotency_store import BeginAction

TASK_TYPE = "agent_04.research_pack"
STAGE_ID = "s04_research"
AGENT = ExecutorId("agent_04")
S0, S1, S5, S7 = "S0_validated", "S1_planned", "S5_assembled", "S7_persisted"
ARTIFACT = "artifacts/research_pack.json"
LOCK_MS = 600_000
REPAIRED_CODES = frozenset({"AGENT.INVALID_JSON", "AGENT.OUTPUT_SCHEMA_INVALID"})
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


@dataclass
class StepDeps:
    llm: LlmAdapter
    web: WebFetchAdapter
    library: KnowledgeLibrary
    directory: TenantDirectory
    tenancy: TenancyContext
    storage: BlobStorage
    checkpoints: CheckpointStore
    idempotency: IdempotencyStore
    budget: BudgetGuard
    ledger: CostLedger
    audit: AuditLog
    clock: Clock
    settings: ResearchSettings
    prompts: PromptLoader
    memory: PackMemory
    resolver_factory: ResolverFactory


class ResolverFactory:
    """Builds the ``CitationResolver`` for one tenant scope (library plus snapshot reads)."""

    def __init__(self, library: KnowledgeLibrary, storage: BlobStorage) -> None:
        self._library, self._storage = library, storage

    def build(self, scope: TenantScope, context: TenantContext) -> CitationResolver:
        return _Resolver(self._library, self._storage, scope, context)


class _Resolver:
    def __init__(
        self,
        library: KnowledgeLibrary,
        storage: BlobStorage,
        scope: TenantScope,
        ctx: TenantContext,
    ) -> None:
        self._library, self._storage, self._scope, self._ctx = library, storage, scope, ctx

    def chunk_sha256(self, chunk_id: str) -> str | None:
        rows = self._library.load_chunks(self._scope, [chunk_id])
        return rows[0].body_sha256 if rows else None

    def snapshot_content_sha256(self, snapshot_ref: str) -> str | None:
        uri = BlobUri(snapshot_ref)
        head = self._storage.head(self._ctx, uri)
        if not head.exists or head.sha256 is None:
            return None
        raw = b"".join(self._storage.get(self._ctx, uri, head.sha256))
        value = json.loads(raw).get("content_sha256")
        return value if isinstance(value, str) else None


class StoredNote(BaseModel):
    note: NoteCandidate
    passage: dict[str, Any]
    usable: bool
    exclusion_reason: ExclusionReason | None
    copy_guard: CopyGuardStatus
    copy_result: dict[str, Any] | None


class StoredBatch(BaseModel):
    notes: list[StoredNote]
    dropped: list[tuple[str, str, str]]
    excluded_forward_looking: int
    injection: list[str]
    refusal: Refusal | None


class StepState(BaseModel):
    """Checkpoint ``state_ref`` blob: IDs, hashes and validated notes, never passage text."""

    plan: ResearchPlan | None = None
    batches: dict[str, StoredBatch] = {}


def canonical(doc: object) -> bytes:
    return json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def task_key(org_id: str, job_id: str, iteration: int) -> IdempotencyKey:
    """Task idempotency key: ``task.agent_04.research_pack`` over (job, stage, type, iteration)."""
    return make_idempotency_key(
        org_id, f"task.{AGENT}.research_pack", [job_id, STAGE_ID, TASK_TYPE, iteration]
    )


def _tokens(text: str) -> set[str]:
    return {t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split() if t}


class ResearchPackStep:
    def __init__(self, deps: StepDeps) -> None:
        self._d = deps
        s = deps.settings
        self._caller = StructuredLlmCaller(
            deps.llm, deps.tenancy, deps.budget, deps.ledger, deps.clock
        )
        self._planner = ConceptPlanner(self._caller, deps.prompts, s.llm.plan)
        self._limits = NoteLimits.from_settings(s.notes, s.copy_guard)
        self._noter = EvidenceNoter(self._caller, deps.prompts, s.llm.notes, s.notes, self._limits)
        self._retriever = LibraryRetriever(deps.library)
        self._fetcher = ExternalReferenceFetcher(deps.web, deps.clock, s.external)
        self._snapshots = SnapshotWriter(deps.storage)
        self._scorer = ReliabilityScorer()
        self._assembler = PackAssembler()
        self._guard = TenantGuard(deps.directory, deps.library)

    # ------------------------------------------------------------------ entry point
    def run(
        self,
        task_input: TaskInput,
        attempt_id: AttemptId,
        attempt_no: int = 1,
        envelope_org_id: str | None = None,
    ) -> TaskOutput:
        started = self._d.clock.monotonic_ms()
        cpu0 = time.process_time()
        log = EventLogger(
            LogContext(
                task_input.org_id,
                task_input.correlation_id,
                task_input.job_id,
                task_input.task_id,
                attempt_id,
            )
        )
        usage = RunInfoHolder()
        try:
            data, check = self._validate(task_input, envelope_org_id)
        except AmwError as exc:
            if isinstance(exc, CrossTenantRefError):
                log.error("security.cross_tenant_ref")
            return self._error_output(
                task_input,
                exc,
                0 if exc.code in S0_ERRORS else attempt_no,
                started,
                cpu0,
                usage.run,
            )
        context = TenantContext(task_input.org_id, AGENT, task_input.correlation_id)  # type: ignore[arg-type]
        run = RunInfo(
            context=context,
            scope=check.scope,
            job_id=JobId(task_input.job_id),
            task_id=TaskId(task_input.task_id),
            attempt_id=attempt_id,
            currency=task_input.resource_budget.currency,
            log=log,
            audit=CoreAuditSink(
                self._d.audit, self._d.tenancy, self._d.clock, context, JobId(task_input.job_id)
            ),
            counter=CallCounter(
                task_input.resource_budget.max_llm_calls
                or self._d.settings.llm.default_max_llm_calls
            ),
        )
        usage.run = run
        log.info("research_pack.started", iteration=data.iteration)
        key = task_key(task_input.org_id, task_input.job_id, data.iteration)
        try:
            stored = self._begin(run, key, task_input)
            if stored is not None:
                return stored
            output = self._execute(task_input, data, check, run, attempt_no, started, cpu0, key)
            log.info("research_pack.completed", status=output.status.value)
            return output
        except (TopicBlocked, TopicNeedsReview) as verdict:
            return self._verdict_output(task_input, data, check, run, verdict, started, cpu0, key)
        except AmwError as exc:
            with self._d.tenancy.transaction(context) as tx:
                if self._d.idempotency.get(tx, key) is not None:
                    rec = self._d.idempotency.get(tx, key)
                    if rec is not None and rec.status is IdempotencyStatus.IN_PROGRESS:
                        self._d.idempotency.fail(tx, key, self._d.clock.now())
            log.error("research_pack.failed", code=exc.code)
            return self._error_output(task_input, exc, attempt_no, started, cpu0, run)

    # ------------------------------------------------------------------ S0
    def _validate(
        self, task: TaskInput, envelope_org_id: str | None
    ) -> tuple[ResearchPackInput, TenantCheck]:
        if task.agent_id != AGENT:
            raise UnsupportedTaskError("task is not addressed to agent_04")
        payload = task.payload
        if payload.payload_schema != PAYLOAD_SCHEMA:
            raise UnsupportedTaskError("unknown payload schema")
        if payload.payload_schema_version.split(".")[0] != PAYLOAD_SCHEMA_VERSION.split(".")[0]:
            raise SchemaVersionUnsupportedError("payload schema version not supported")
        raw: object = payload.data
        if raw is None:
            if payload.data_ref is None or payload.data_sha256 is None:
                raise SchemaInvalidError("payload carries neither data nor a data reference")
            context = TenantContext(task.org_id, AGENT, task.correlation_id)  # type: ignore[arg-type]
            chunks = self._d.storage.get(context, BlobUri(payload.data_ref), payload.data_sha256)
            raw = json.loads(b"".join(chunks))
        try:
            data = ResearchPackInput.model_validate(raw)
        except ValidationError as exc:
            violations = [
                {
                    "path": "/" + "/".join(str(p) for p in e["loc"]),
                    "keyword": e["type"],
                    "message": e["msg"][:200],
                }
                for e in exc.errors()[:50]
            ]
            raise SchemaInvalidError(
                "input fails the schema", details={"violations": violations}
            ) from None
        return data, self._guard.check(task, data, envelope_org_id)

    def _begin(self, run: RunInfo, key: IdempotencyKey, task: TaskInput) -> TaskOutput | None:
        """03 section 9.1 rule 3 for the task key: a COMPLETED same-hash key returns the output."""
        request_hash = hashlib.sha256(canonical(task.to_doc()["payload"])).hexdigest()
        with self._d.tenancy.transaction(run.context) as tx:
            decision = self._d.idempotency.begin(
                tx,
                key,
                f"task.{AGENT}.research_pack",
                request_hash,
                run.task_id,
                self._d.clock.now(),
                LOCK_MS,
            )
        if decision.action is BeginAction.RETURN_STORED and decision.record.result_ref:
            uri = BlobUri(decision.record.result_ref)
            head = self._d.storage.head(run.context, uri)
            if head.exists and head.sha256:
                raw = b"".join(self._d.storage.get(run.context, uri, head.sha256))
                return TaskOutput.model_validate_json(raw)
        if decision.action is BeginAction.IN_FLIGHT:
            raise LockConflictError("another attempt holds this task")
        return None

    # ------------------------------------------------------------------ S1 to S7
    def _execute(
        self,
        task: TaskInput,
        data: ResearchPackInput,
        check: TenantCheck,
        run: RunInfo,
        attempt_no: int,
        started: int,
        cpu0: float,
        key: IdempotencyKey,
    ) -> TaskOutput:
        state = self._resume(run)
        topic = TopicFlags(data.topic.video_kind, data.topic.title)
        self._checkpoint(run, S0, state, 0.05)
        if state.plan is None:
            plan = self._planner.plan(run, self._plan_input(data, check.collections))
            state.plan = plan
            self._checkpoint(run, S1, state, 0.2)
        plan = state.plan
        scope_keys = data.library_scope.collection_keys
        limits = RetrievalLimits(
            self._d.settings.retrieval.top_k_per_concept,
            self._d.settings.retrieval.max_chunks_per_source_per_concept,
            self._d.settings.retrieval.candidate_pool_per_query,
        )
        source_refs = frozenset(
            r.knowledge_source_id
            for r in data.owner_references
            if r.kind is OwnerReferenceKind.KNOWLEDGE_SOURCE and r.knowledge_source_id
        )
        # S2 retrieve (deterministic, read-only)
        results: dict[str, RetrievalResult] = {}
        for concept in plan.concepts:
            allowed = allowed_collections(
                check.collections, scope_keys, concept, data.topic.video_kind
            )
            res = self._retriever.retrieve(run, concept, allowed, topic, limits)
            if source_refs:
                extra = self._retriever.retrieve(run, concept, allowed, topic, limits, source_refs)
                merged = {c.chunk_id: c for c in (*res.candidates, *extra.candidates)}
                res.candidates = rank_candidates(list(merged.values()), limits)
                for k, v in extra.restricted_blocked.items():
                    res.restricted_blocked[k] = max(res.restricted_blocked.get(k, 0), v)
            results[concept.concept_id] = res
        # S3 external references
        fetched: dict[str, FetchedSource] = {}
        for pos, ref in enumerate(data.owner_references, start=1):
            if ref.kind is OwnerReferenceKind.EXTERNAL_URL and ref.url:
                fetched[f"r{pos}"] = self._fetcher.fetch(
                    run, f"r{pos}", ref.url, data.topic.language
                )
        source_cache: dict[str, SourceView] = {}
        sources: dict[str, SourceRecord] = {}
        citations: dict[str, CitationMeta] = {}
        approvals: dict[str, str | None] = {}
        for ext in fetched.values():
            self._register_external(ext, sources, check)
        # S4 notes per concept and batch
        evidence: list[ConceptEvidence] = []
        refused: list[ValidationResult] = []
        for concept in plan.concepts:
            ce = ConceptEvidence(concept)
            res = results[concept.concept_id]
            ce.restricted_blocked = bool(res.restricted_blocked)
            passages = self._passages(
                run, concept, res, fetched, topic, source_cache, sources, citations, approvals
            )
            per_call = self._d.settings.notes.max_passages_per_call
            for b, start in enumerate(range(0, len(passages), per_call), start=1):
                step_key = f"S4_notes_{concept.concept_id}_{b}"
                batch = passages[start : start + per_call]
                renamed = [replace(p, passage_id=f"p{i}") for i, p in enumerate(batch, start=1)]
                if step_key in state.batches:
                    notes = self._restore(state.batches[step_key], renamed)
                else:
                    notes = self._noter.note(
                        run,
                        concept,
                        renamed,
                        step_key,
                        data.channel_category,
                        tuple(data.active_rule_packs),
                    )
                    state.batches[step_key] = self._store(notes)
                    self._checkpoint(run, step_key, state, 0.5)
                ce.notes.extend(notes.notes)
                ce.dropped.extend(notes.dropped)
                ce.excluded_forward_looking += notes.excluded_forward_looking
                if notes.refusal is not None:
                    ce.notes_refused = True
                    refused.append(notes_refused_result(concept.concept_id, notes.refusal))
            evidence.append(ce)
        restricted_pending: dict[str, list[str]] = {}
        for cid, res in results.items():
            for ckey in res.restricted_blocked:
                restricted_pending.setdefault(ckey, []).append(cid)
        # S5 assemble (two passes: a snapshot only for a reference that backs a usable note)
        assembly = self._assemble_with_snapshots(
            task,
            data,
            run,
            evidence,
            sources,
            citations,
            approvals,
            restricted_pending,
            fetched,
            plan,
            check,
        )
        self._assembler.require_usable(assembly)
        pack = assembly.pack
        copy_results = self._copy_results(pack, evidence)
        results_v = PackValidator(self._d.resolver_factory.build(run.scope, run.context)).validate(
            pack,
            task.org_id,
            scope=run.scope,
            library=self._d.library,
            copy_results=copy_results,
            has_revision=data.revision is not None,
            unclosed_gap_ids=assembly.unclosed_gap_ids,
            cross_language_items=assembly.cross_language_items,
            refused=refused,
        )
        failed = [r.check_id for r in results_v if r.blocking and r.verdict is CheckVerdict.FAIL]
        if failed:
            raise QualityRepeatedFailure("blocking pack checks failed", details={"checks": failed})
        self._checkpoint(run, S5, state, 0.9)
        return self._persist(
            task, data, check, run, pack, results_v, fetched, started, cpu0, key, state
        )

    # ------------------------------------------------------------------ helpers
    def _plan_input(
        self, data: ResearchPackInput, collections: Sequence[CollectionView]
    ) -> ResearchPlanInput:
        s = self._d.settings
        scope_keys = data.library_scope.collection_keys
        method = data.topic.video_kind is VideoKind.METHOD_TOPIC
        views = [
            c
            for c in collections
            if (scope_keys is None or c.collection_key in scope_keys)
            and (method or not c.restricted)
        ]
        gaps = data.revision.gaps if data.revision else ()
        return ResearchPlanInput(
            topic_title=data.topic.title,
            topic_brief=data.topic.brief,
            topic_angle=data.topic.angle,
            video_language=data.topic.language,
            channel_category=data.channel_category,
            active_rule_packs=data.active_rule_packs,
            video_kind=data.topic.video_kind,
            collections=tuple(
                PlanCollection(
                    collection_key=c.collection_key, kind=KnowledgeSourceKind.BOOK, languages=()
                )
                for c in views
            ),
            library_languages=(),
            glossary_terms=(),
            revision_gaps=tuple(
                PlanGap(gap_id=g.gap_id, gap_text=g.gap_text, reason=g.reason) for g in gaps
            ),
            max_concepts=s.plan.max_concepts,
            max_queries_per_concept=s.plan.max_queries_per_concept,
        )

    def _passages(
        self,
        run: RunInfo,
        concept: PlannedConcept,
        res: RetrievalResult,
        fetched: dict[str, FetchedSource],
        topic: TopicFlags,
        cache: dict[str, SourceView],
        sources: dict[str, SourceRecord],
        citations: dict[str, CitationMeta],
        approvals: dict[str, str | None],
    ) -> list[PassageSource]:
        out: list[PassageSource] = []
        cfg = self._d.settings
        loaded = self._retriever.load_passages(run, res.candidates, topic)
        by_id = {c.chunk_id: c for c in res.candidates}
        for p in loaded:
            cand = by_id[p.chunk_id]
            src = cache.get(cand.source_id) or self._d.library.get_source(run.scope, cand.source_id)
            if src is None:
                continue
            cache[cand.source_id] = src
            rel = self._scorer.score(
                SourceMeta(src.kind, src.ownership, None, True), None, cfg.tier_scores()
            )
            if rel.excluded or rel.tier is None:
                continue
            sources[src.source_id] = SourceRecord(
                src.source_id,
                src.kind,
                src.title,
                src.author,
                src.edition,
                src.ownership,
                rel.tier,
                rel.score,
                cand.collection_key,
                None,
                None,
                FetchStatus.OK,
                src.content_sha256,
                None,
                src.credit_in_description,
            )
            citations[cand.chunk_id] = CitationMeta(_chunk_kind(), src.title, cand.body_sha256)
            approvals[cand.chunk_id] = cand.release_approval_id
            out.append(
                PassageSource(
                    "",
                    p.text,
                    p.language,
                    rel.tier,
                    cand.chunk_id,
                    src.source_id,
                    cand.method_labelled,
                    rel.owner_authored,
                    cand.chapter,
                    cand.page_from,
                    cand.page_to,
                )
            )
        terms = _tokens(" ".join(q.text for q in concept.queries))
        scored: list[tuple[int, str, PassageSource]] = []
        for ext in fetched.values():
            if ext.status is not FetchStatus.OK or ext.ext_ref not in sources:
                continue
            record = sources[ext.ext_ref]
            for i, ep in enumerate(ext.passages):
                score = len(terms & _tokens(ep.text))
                if score > 0:
                    scored.append(
                        (
                            score,
                            f"{ext.ext_ref}{i:04d}",
                            PassageSource(
                                "",
                                ep.text,
                                ep.language,
                                record.tier,
                                ext.ext_ref,
                                ext.ext_ref,
                                False,
                                False,
                                None,
                                None,
                                None,
                            ),
                        )
                    )
        scored.sort(key=lambda t: (-t[0], t[1]))
        room = max(0, cfg.retrieval.top_k_per_concept - len(out))
        out.extend(p for _, _, p in scored[:room])
        return out

    def _register_external(
        self, ext: FetchedSource, sources: dict[str, SourceRecord], check: TenantCheck
    ) -> None:
        domain = self._d.settings.domain_registry().class_of_url(ext.url)
        rel = self._scorer.score(
            SourceMeta(KnowledgeSourceKind.WEB_REFERENCE, None, domain, False),
            None,
            self._d.settings.tier_scores(),
        )
        if rel.tier is None:  # pragma: no cover - an external reference has no ownership to exclude
            raise ConfigInvalid("external reference could not be scored")
        sources[ext.ext_ref] = SourceRecord(
            ext.ext_ref,
            KnowledgeSourceKind.WEB_REFERENCE,
            ext.url[:300],
            None,
            None,
            None,
            rel.tier,
            rel.score,
            None,
            ext.url,
            ext.accessed_at,
            ext.status,
            ext.content_sha256,
            None,
        )
        del check

    def _assemble_with_snapshots(
        self,
        task: TaskInput,
        data: ResearchPackInput,
        run: RunInfo,
        evidence: list[ConceptEvidence],
        sources: dict[str, SourceRecord],
        citations: dict[str, CitationMeta],
        approvals: dict[str, str | None],
        pending: dict[str, list[str]],
        fetched: dict[str, FetchedSource],
        plan: ResearchPlan,
        check: TenantCheck,
    ) -> Assembly:
        del check
        by_ext = {f.ext_ref: f for f in fetched.values()}
        for ref, ext in by_ext.items():
            if ext.status is FetchStatus.OK and ref in sources:
                citations[ref] = CitationMeta(
                    _ext_kind(), sources[ref].title, ext.content_sha256 or ""
                )

        def build(snapshots: dict[str, str]) -> Assembly:
            srcs = {k: (replace(v, snapshot_ref=snapshots.get(k))) for k, v in sources.items()}
            return self._assembler.assemble(
                AssemblyInput(
                    topic=PackTopic(
                        title=data.topic.title,
                        language=data.topic.language,
                        video_kind=data.topic.video_kind,
                    ),
                    iteration=data.iteration,
                    concepts=evidence,
                    sources=srcs,
                    citations=citations,
                    restricted_pending=pending,
                    input_gap_ids=frozenset(
                        g.gap_id for g in (data.revision.gaps if data.revision else ())
                    ),
                    approvals_by_citation=approvals,
                    min_tier_for_factual=self._d.settings.min_tier_for_factual,
                    rule_pack_versions={},
                    plan_prompt_id=PLAN_PROMPT_ID,
                    notes_prompt_id=NOTES_PROMPT_ID,
                    llm_calls=run.counter.used,
                )
            )

        used_ext = {
            n.passage.citation_ref
            for ce in evidence
            for n in ce.notes
            if n.passage.citation_ref in by_ext
        }
        first = build({r: self._snapshot_uri(run, r) for r in used_ext})
        usable_ext = {
            e.citation_ref
            for e in first.pack.evidence
            if e.usable_for_script and e.citation_ref in by_ext
        }
        for ref in sorted(usable_ext):
            self._snapshots.write(run, by_ext[ref])
        return build({r: self._snapshot_uri(run, r) for r in usable_ext})

    def _snapshot_uri(self, run: RunInfo, ext_ref: str) -> str:
        return str(
            self._d.storage.blob_uri(run.context, "evidence", f"{run.job_id}/{ext_ref}.json")
        )

    @staticmethod
    def _copy_results(pack: ResearchPack, evidence: list[ConceptEvidence]) -> dict[str, CopyResult]:
        flat: list[ValidatedNote] = [n for ce in evidence for n in ce.notes]
        return {
            item.evidence_id: note.copy
            for item, note in zip(pack.evidence, flat, strict=True)
            if note.copy is not None
        }

    # ---- checkpoints
    def _resume(self, run: RunInfo) -> StepState:
        with self._d.tenancy.transaction(run.context) as tx:
            latest = self._d.checkpoints.latest(tx, run.task_id)
        if latest is None:
            return StepState()
        uri = BlobUri(latest.checkpoint.state_ref)
        raw = b"".join(self._d.storage.get(run.context, uri, latest.checkpoint.state_sha256))
        return StepState.model_validate_json(raw)

    def _checkpoint(self, run: RunInfo, step_key: str, state: StepState, progress: float) -> None:
        body = state.model_dump_json().encode()
        sha = hashlib.sha256(body).hexdigest()
        uri = self._d.storage.blob_uri(
            run.context,
            "jobs",
            f"{run.job_id}/checkpoints/{run.task_id}/{run.attempt_id}/{step_key}.json",
        )
        self._d.storage.put(run.context, uri, BytesIO(body))
        from decimal import Decimal

        with self._d.tenancy.transaction(run.context) as tx:
            self._d.checkpoints.write(
                tx,
                NewCheckpoint(
                    run.task_id,
                    run.attempt_id,
                    step_key,
                    str(uri),
                    sha,
                    tuple(IdempotencyKey(e) for e in run.effects),
                    Decimal(str(progress)),
                ),
                self._d.clock.now(),
            )
        run.log.info("research_pack.step_done", step_key=step_key)

    @staticmethod
    def _store(notes: NotesResult) -> StoredBatch:
        stored = [
            StoredNote(
                note=n.note,
                passage={k: v for k, v in asdict(n.passage).items() if k != "text"},
                usable=n.usable,
                exclusion_reason=n.exclusion_reason,
                copy_guard=n.copy_guard,
                copy_result=None
                if n.copy is None
                else {
                    "longest_shared_run": n.copy.longest_shared_run,
                    "overlap_ratio": n.copy.overlap_ratio,
                    "passed": n.copy.passed,
                    "skipped_reason": n.copy.skipped_reason,
                },
            )
            for n in notes.notes
        ]
        return StoredBatch(
            notes=stored,
            dropped=[(d.note_ref, d.passage_id, d.problem.value) for d in notes.dropped],
            excluded_forward_looking=notes.excluded_forward_looking,
            injection=notes.injection_passages,
            refusal=notes.refusal,
        )

    @staticmethod
    def _restore(batch: StoredBatch, passages: list[PassageSource]) -> NotesResult:
        from agent_04_research_knowledge.models.enums import NoteProblem

        result = NotesResult("restored")
        for n in batch.notes:
            passage = PassageSource(
                **{**n.passage, "text": "", "tier": ReliabilityTier(n.passage["tier"])}
            )
            copy = None if n.copy_result is None else CopyResult(**n.copy_result)
            result.notes.append(
                ValidatedNote(
                    n.note.note_ref,
                    passage,
                    n.note,
                    n.usable,
                    n.exclusion_reason,
                    n.copy_guard,
                    copy,
                )
            )
        result.dropped = [DroppedNote(a, b, NoteProblem(c)) for a, b, c in batch.dropped]
        result.excluded_forward_looking = batch.excluded_forward_looking
        result.injection_passages = batch.injection
        result.refusal = batch.refusal
        del passages
        return result

    # ---- outputs
    def _persist(
        self,
        task: TaskInput,
        data: ResearchPackInput,
        check: TenantCheck,
        run: RunInfo,
        pack: ResearchPack,
        results: list[ValidationResult],
        fetched: dict[str, FetchedSource],
        started: int,
        cpu0: float,
        key: IdempotencyKey,
        state: StepState,
    ) -> TaskOutput:
        refs: list[OutputRef] = []
        doc = pack.to_doc()
        body = canonical(doc)
        sha = hashlib.sha256(body).hexdigest()
        uri = self._d.storage.blob_uri(
            run.context,
            "jobs",
            f"{run.job_id}/tasks/{run.task_id}/attempts/{run.attempt_id}/{ARTIFACT}",
        )
        if not self._d.storage.head(run.context, uri).exists:
            self._d.storage.put(run.context, uri, BytesIO(body))
        refs.append(_ref(uri, sha, len(body)))
        for src in pack.sources:
            if src.snapshot_ref:
                head = self._d.storage.head(run.context, BlobUri(src.snapshot_ref))
                if head.sha256 is not None and head.size_bytes is not None:
                    refs.append(_ref(BlobUri(src.snapshot_ref), head.sha256, head.size_bytes))
        now = self._d.clock.now()
        self._d.memory.write(
            org_id=task.org_id,
            channel_id=run.scope.channel_id,
            workspace_id=check.workspace_id,
            project_id=task.project_id or "",
            job_id=task.job_id,
            iteration=pack.iteration,
            task_id=task.task_id,
            pack_uri=str(uri),
            pack_sha256=sha,
            now=now,
        )
        run.audit.record(
            "research.pack_created",
            "task",
            task.task_id,
            {"concepts": len(pack.concepts), "evidence": len(pack.evidence), "sha256": sha},
        )
        self._checkpoint(run, S7, state, 1.0)
        payload = self._payload(pack, doc, body, uri, sha)
        reason = (
            "gate FAILED: a04.topic_allowed"
            if pack.topic_verdict.verdict is ComplianceVerdict.BLOCKED
            else "research pack ready for the script step"
        )
        output = TaskOutput(
            status=OutputStatus.SUCCEEDED,
            payload=payload,
            output_refs=tuple(refs),
            quality_score=None,
            confidence=None,
            validation_results=tuple(results),
            duration=self._d.clock.monotonic_ms() - started,
            resource_usage=self._usage(run, cpu0),
            error=None,
            next_action=NextAction(
                type=NextActionType.CONTINUE, wait_reason=None, escalation_level=None, reason=reason
            ),
            downstream_agent=ExecutorId("agent_05"),
            timestamp=now,
        )
        out_uri = self._store_output(run, output)
        with self._d.tenancy.transaction(run.context) as tx:
            self._d.idempotency.complete(tx, key, str(out_uri), now)
        return output

    def _store_output(self, run: RunInfo, output: TaskOutput) -> BlobUri:
        uri = self._d.storage.blob_uri(
            run.context,
            "jobs",
            f"{run.job_id}/tasks/{run.task_id}/attempts/{run.attempt_id}/output.json",
        )
        if not self._d.storage.head(run.context, uri).exists:
            self._d.storage.put(run.context, uri, BytesIO(output.model_dump_json().encode()))
        return uri

    def _payload(
        self, pack: ResearchPack, doc: dict[str, Any], body: bytes, uri: BlobUri, sha: str
    ) -> PayloadObject:
        if len(body) <= self._d.settings.inline_payload_max_bytes:
            return PayloadObject(
                payload_schema=PACK_OUTPUT_SCHEMA,
                payload_schema_version=PACK_OUTPUT_SCHEMA_VERSION,
                data=doc,
            )
        return PayloadObject(
            payload_schema=PACK_OUTPUT_SCHEMA,
            payload_schema_version=PACK_OUTPUT_SCHEMA_VERSION,
            data_ref=str(uri),
            data_sha256=sha,
        )

    def _verdict_output(
        self,
        task: TaskInput,
        data: ResearchPackInput,
        check: TenantCheck,
        run: RunInfo,
        verdict: TopicBlocked | TopicNeedsReview,
        started: int,
        cpu0: float,
        key: IdempotencyKey,
    ) -> TaskOutput:
        blocked = isinstance(verdict, TopicBlocked)
        pack = blocked_pack(
            PackTopic(
                title=data.topic.title,
                language=data.topic.language,
                video_kind=data.topic.video_kind,
            ),
            data.iteration,
            ComplianceVerdict.BLOCKED if blocked else ComplianceVerdict.NEEDS_HUMAN_REVIEW,
            verdict.rule_ids,
            {},
            PLAN_PROMPT_ID,
            NOTES_PROMPT_ID,
            run.counter.used,
        )
        results = PackValidator(self._d.resolver_factory.build(run.scope, run.context)).validate(
            pack,
            task.org_id,
            scope=run.scope,
            library=self._d.library,
            copy_results={},
            has_revision=data.revision is not None,
            unclosed_gap_ids=(),
            cross_language_items=0,
            refused=[],
        )
        return self._persist(
            task, data, check, run, pack, results, {}, started, cpu0, key, StepState()
        )

    def _usage(self, run: RunInfo | None, cpu0: float) -> ResourceUsage:
        u = run.usage if run else None
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        return ResourceUsage(
            cpu_ms=int((time.process_time() - cpu0) * 1000),
            peak_rss_bytes=int(rss),
            tokens_in=u.tokens_in if u else 0,
            tokens_out=u.tokens_out if u else 0,
            tokens_cached_in=u.tokens_cached_in if u else 0,
            llm_calls=u.llm_calls if u else 0,
            provider_calls=u.provider_calls if u else 0,
            cost_estimate_micros=u.cost_micros if u else 0,
            currency=run.currency if run else "USD",
            cost_entry_ids=tuple(u.cost_entry_ids) if u else (),
        )

    def _error_output(
        self,
        task: TaskInput,
        exc: AmwError,
        attempt_no: int,
        started: int,
        cpu0: float,
        run: RunInfo | None,
    ) -> TaskOutput:
        now = self._d.clock.now()
        error: ErrorObject = error_object_from_exception(
            exc,
            actor=str(AGENT),
            attempt_no=attempt_no,
            occurred_at=now,
            correlation_id=task.correlation_id,
        )
        if exc.code in S0_ERRORS and attempt_no == 0:
            status = OutputStatus.REJECTED
        elif isinstance(exc, BudgetExhaustedError):
            status = OutputStatus.SUSPENDED
        else:
            status = OutputStatus.FAILED
        spec = exc.spec
        if status is OutputStatus.SUSPENDED:
            action = NextAction(
                type=NextActionType.WAIT,
                wait_reason=spec.wait_reason,
                escalation_level=None,
                reason=exc.code,
            )
        else:
            kind = NextActionType.RETRY if exc.retryable else NextActionType.STOP
            reason = exc.code
            if exc.code in REPAIRED_CODES:  # the one allowed repair is spent (07 agent_parse)
                kind, reason = NextActionType.STOP, f"{exc.code}: repair exhausted, dead letter"
            action = NextAction(type=kind, wait_reason=None, escalation_level=None, reason=reason)
        return TaskOutput(
            status=status,
            payload=None,
            output_refs=(),
            quality_score=None,
            confidence=None,
            validation_results=(),
            duration=self._d.clock.monotonic_ms() - started,
            resource_usage=self._usage(run, cpu0),
            error=error,
            next_action=action,
            downstream_agent=None,
            timestamp=now,
        )


class RunInfoHolder:
    run: RunInfo | None = None


def _ref(uri: BlobUri, sha: str, size: int) -> OutputRef:
    return OutputRef(
        uri=uri, kind=OutputRefKind.DATA, sha256=sha, size_bytes=size, media_type="application/json"
    )


def _chunk_kind() -> Any:
    from amw_core.enums import EvidenceSourceKind

    return EvidenceSourceKind.KNOWLEDGE_CHUNK


def _ext_kind() -> Any:
    from amw_core.enums import EvidenceSourceKind

    return EvidenceSourceKind.EXTERNAL_REFERENCE
