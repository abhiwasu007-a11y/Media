"""``ClaimVerificationStep`` (V-S0..V-S7; blueprint 10.1, 10.3-10.5): ``s06_verify`` with
``verify_mode`` EVIDENCE and ``s06_chart`` with ``verify_mode`` CHART_FACTS.

Evidence only, never the model's knowledge. The model compares; code selects the evidence,
guards every assessment and derives status, verdict, gate result and revision requests."""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from pydantic import ValidationError

from agent_06_fact_checker.batches import Batch, batch_variables, build_batches
from agent_06_fact_checker.config import FactCheckSettings
from agent_06_fact_checker.conflicts import find_pairs
from agent_06_fact_checker.evidence import ClaimEvidence, EvidenceResolver
from agent_06_fact_checker.hashing import claims_sha256
from agent_06_fact_checker.models import (
    BatchConflict,
    ClaimMode,
    EvidenceScope,
    Provenance,
    RefusalReason,
    VerificationBatchOutput,
    VerificationClaim,
    VerificationInput,
    VerificationOutput,
    VerifiedClaim,
    VerifyMode,
    most_severe,
)
from agent_06_fact_checker.numbers import missing_numerals, numerals
from agent_06_fact_checker.outputs import (
    check,
    check_ctx,
    error_output,
    next_action_for,
    success_output,
    write_blob,
)
from agent_06_fact_checker.planner import ClaimPlan, plan_claims, reject_blocked_input
from agent_06_fact_checker.ports import CitationRow, ClaimStore, KnowledgeReader, ScriptRegistry
from agent_06_fact_checker.prompts import PromptSource, render_system
from agent_06_fact_checker.reconcile import (
    Outcome,
    reconcile_claim,
    refused_outcome,
    static_outcome,
)
from agent_06_fact_checker.runtime import (
    AGENT_ID,
    PaidCallRunner,
    StepCheckpoints,
    UsageTotals,
    task_key,
)
from agent_06_fact_checker.verdicts import (
    StageResult,
    accuracy,
    apply_conflicts,
    finalize,
    verification_verdict,
)
from amw_adapters.llm.protocol import LlmAdapter
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import TaskOutput, ValidationResult
from amw_core.enums import ActorKind, ClaimStatus
from amw_core.errors import (
    AgentError,
    BudgetExhaustedError,
    CrossTenantRefError,
    InputInvalidError,
    InsufficientInputError,
    MissingDependencyError,
    PermanentError,
    SchemaInvalidError,
    SchemaVersionUnsupportedError,
)
from amw_core.exec_context import ExecContext
from amw_core.ids import ActorRef, ChannelId
from amw_core.interfaces import (
    AuditLog,
    BlobStorage,
    BudgetGuard,
    CheckpointStore,
    Clock,
    CostLedger,
    NewAuditEntry,
    TenancyContext,
    TenantTransaction,
)

log = logging.getLogger(__name__)
INPUT_SCHEMA = "agent_06.claim_verification.input"
OUTPUT_SCHEMA = "agent_06.claim_verification.output"
PROMPT_ID = "agent_06/claim_verification.v1"
ConflictFinder = Callable[[Sequence[VerificationClaim], FactCheckSettings], list[tuple[str, str]]]


@dataclass(slots=True)
class _State:
    validated: bool = False
    usage: UsageTotals = field(default_factory=UsageTotals)


class ClaimVerificationStep:
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
        knowledge: KnowledgeReader,
        prompts: PromptSource,
        settings: FactCheckSettings,
        conflict_finder: ConflictFinder = find_pairs,
    ) -> None:
        self._finder = conflict_finder
        self._tenancy = tenancy
        self._clock = clock
        self._blobs = blobs
        self._checkpoints = checkpoints
        self._audit = audit
        self._claims = claims
        self._scripts = scripts
        self._knowledge = knowledge
        self._prompts = prompts
        self._settings = settings
        self._runner = PaidCallRunner(
            llm=llm,
            budget=budget,
            ledger=ledger,
            tenancy=tenancy,
            clock=clock,
            settings=settings.verification_llm,
            max_repairs=settings.max_repairs,
        )

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

    # ------------------------------------------------------------------ V-S0
    def _parse(self, task: TaskInput) -> tuple[VerificationInput, Mapping[str, Any]]:
        if task.agent_id != AGENT_ID:
            raise InputInvalidError("task is not addressed to agent_06")
        payload = task.payload
        if payload.payload_schema != INPUT_SCHEMA:
            raise SchemaInvalidError("unexpected payload schema")
        if not payload.payload_schema_version.startswith("1."):
            raise SchemaVersionUnsupportedError("payload schema major is not supported")
        doc = payload.data
        if doc is None:
            raise SchemaInvalidError("verification input must be inline (claims are bounded)")
        try:
            return VerificationInput.model_validate(doc), doc
        except ValidationError as exc:
            raise SchemaInvalidError(
                "verification input does not match the schema",
                details={
                    "violations": [
                        {
                            "path": "/" + "/".join(str(p) for p in e["loc"]),
                            "keyword": "model",
                            "message": str(e["type"]),
                        }
                        for e in exc.errors()[:200]
                    ]
                },
            ) from None

    def _validate(
        self,
        task: TaskInput,
        ctx: ExecContext,
        inp: VerificationInput,
        doc: Mapping[str, Any],
        resolver: EvidenceResolver,
    ) -> int:
        """V0-V2 (blueprint 7.2): order of the semantic checks is part of the contract.
        Returns the number of knowledge reads (audit count)."""
        if task.channel_id is None:
            raise InputInvalidError("channel_id is required (the library is channel scoped)")
        channel = ChannelId(task.channel_id)
        tenant = ctx.tenant
        if inp.channel_category == "finance" and "rp.finance_sebi_in" not in inp.active_rule_packs:
            raise InputInvalidError("a finance script needs the finance rule pack to be active")
        # (3) hashes
        if claims_sha256(doc["claims"]) != inp.claims_sha256:
            raise InputInvalidError("claims_sha256 does not match the claims")
        with self._tenancy.transaction(tenant) as tx:
            self._tenancy.require_same_tenant(tx, task.org_id)  # (1)
            expected = self._scripts.content_sha256(
                tx, script_id=inp.script_id, script_version=inp.script_version
            )
            if expected is None:
                raise MissingDependencyError("script is not known to this tenant")
            if expected != inp.script_sha256:
                raise InputInvalidError("script_sha256 differs from scripts.content_sha256")
            ids = [c.claim_id for c in inp.claims]
            owned = self._claims.owned_claim_ids(tx, script_id=inp.script_id, claim_ids=ids)
            if set(ids) - owned:  # (2) generic message: no existence oracle
                raise CrossTenantRefError("a reference does not belong to this tenant")
            self._cross_check_extraction(tx, inp)
            reads = resolver.preflight(tx, channel, inp.available_citations)
        # (4) blocked input, (5) shape, (6) iteration
        reject_blocked_input(inp.claims, inp.extraction_overall_verdict.value, inp.verify_mode)
        locals_ = [c.local_id for c in inp.claims]
        if len(set(locals_)) != len(locals_):
            raise InputInvalidError("duplicate local_id")
        if inp.iteration != ctx.iteration:
            raise InputInvalidError("iteration differs from the task's revision counter")
        return reads

    def _cross_check_extraction(self, tx: TenantTransaction, inp: VerificationInput) -> None:
        """The extraction verdicts in the input are not trusted: they must equal the stored
        (code-recomputed) ``claims`` rows, and the overall verdict may not be below any of them."""
        stored = self._claims.extraction_verdicts(
            tx, script_id=inp.script_id, claim_ids=[c.claim_id for c in inp.claims]
        )
        for c in inp.claims:
            if stored.get(c.claim_id) is not c.extraction_verdict:
                raise InputInvalidError("extraction_verdict differs from the stored claim")
        floor = most_severe(*stored.values())
        if most_severe(inp.extraction_overall_verdict, floor) is not inp.extraction_overall_verdict:
            raise InputInvalidError("extraction_overall_verdict is below a stored claim verdict")

    # ------------------------------------------------------------------ the run
    def _run(self, task: TaskInput, ctx: ExecContext, state: _State, started: int) -> TaskOutput:
        check_ctx(task, ctx)
        s = self._settings
        tenant = ctx.tenant
        inp, raw = self._parse(task)
        resolver = EvidenceResolver(
            self._knowledge, s, release_approved=inp.our_method_release_approved
        )
        reads = self._validate(task, ctx, inp, raw, resolver)
        state.validated = True
        channel = ChannelId(task.channel_id or "")
        doc = self._prompts.load(PROMPT_ID)
        prompt = render_system(doc, None, inp.active_rule_packs)
        facts = {f.ref_id: f for f in inp.chart_facts}

        plans = plan_claims(inp.claims, inp.verify_mode, s, facts)
        with self._tenancy.transaction(tenant) as tx:
            evidence = resolver.resolve(tx, channel, plans, inp.available_citations, facts)
        verifiable = [p for p in plans if p.mode in (ClaimMode.EVIDENCE, ClaimMode.CHART_FACTS)]
        pairs = self._finder([p.claim for p in verifiable], s)
        in_pair = {i for pair in pairs for i in pair}
        sendable = [
            (p, evidence[p.claim.local_id])
            for p in verifiable
            if evidence[p.claim.local_id].candidates or p.claim.local_id in in_pair
        ]
        sent_ids = {p.claim.local_id for p, _ in sendable}
        outcomes: dict[str, Outcome] = {}
        for p in plans:
            if p.claim.local_id not in sent_ids:
                outcomes[p.claim.local_id] = static_outcome(p, evidence.get(p.claim.local_id))

        batches = build_batches(sendable, pairs, s)
        saved = StepCheckpoints(
            store=self._checkpoints,
            blobs=self._blobs,
            tenancy=self._tenancy,
            clock=self._clock,
            task=task,
            ctx=ctx,
        )
        done = saved.load()
        model_conflicts: list[BatchConflict] = []
        leaks = 0
        paid_calls = 0  # calls over every attempt: a replay yields the same provenance
        for batch in batches:
            key = f"V4_batch_{batch.index}"
            if key in done:
                out = VerificationBatchOutput.model_validate(done[key]["out"])
                paid_calls += int(done[key]["calls"])
            else:
                before = state.usage.llm_calls
                out = self._verify_batch(task, ctx, state, inp, prompt, batch, verifiable, pairs)
                made = state.usage.llm_calls - before
                paid_calls += made
                saved.save(
                    key,
                    {"out": out.to_doc(), "calls": made},
                    (batch.index + 1) / max(len(batches), 1),
                )
            flags = {f.evidence_id for f in out.passage_flags}
            self._reconcile(batch, out, evidence, outcomes, flags)
            leaks += sum(1 for lid in batch.local_ids if set(outcomes[lid].used_ids) & flags)
            model_conflicts.extend(out.claim_conflicts)

        ordered = [outcomes[c.local_id] for c in inp.claims]
        kept = apply_conflicts(ordered, model_conflicts)
        ext = {c.local_id: c.extraction_verdict for c in inp.claims}
        result = finalize(
            ordered,
            kept,
            ext,
            inp.extraction_overall_verdict,
            {c.local_id: c.claim_id for c in inp.claims},
            s,
            include_extraction_overall=inp.verify_mode is VerifyMode.EVIDENCE,
        )
        restricted_used = any(o.restricted_used for o in ordered)
        output = VerificationOutput(
            script_id=inp.script_id,
            script_version=inp.script_version,
            script_sha256=inp.script_sha256,
            verify_mode=inp.verify_mode,
            iteration=inp.iteration,
            gate_verdict=result.gate,
            claims=result.claims,
            claim_conflicts=result.conflicts,
            revision_requests=result.revisions,
            overall=result.overall,
            accuracy_summary=result.accuracy,
            provenance=Provenance(
                prompt_id=PROMPT_ID,
                prompt_sha256=doc.sha256,
                llm_calls=paid_calls,
                batches=len(batches),
                config_version=s.config_version,
                evidence_scope=EvidenceScope(channel_scoped=True, restricted_used=restricted_used),
            ),
        )
        if result.claims:
            self._persist(task, ctx, inp, result, reads)
        return self._assemble(task, ctx, state, started, inp, output, ordered, evidence, leaks)

    # ------------------------------------------------------------------ V-S4
    def _verify_batch(
        self,
        task: TaskInput,
        ctx: ExecContext,
        state: _State,
        inp: VerificationInput,
        prompt: Any,
        batch: Batch,
        verifiable: Sequence[ClaimPlan],
        pairs: Sequence[tuple[str, str]],
    ) -> VerificationBatchOutput:
        variables = batch_variables(
            batch,
            verifiable,
            self._settings,
            language=inp.language,
            channel_category=inp.channel_category,
        )
        sent = set(batch.local_ids)
        digest = cast("list[dict[str, str]]", variables["claim_digest"])
        digest_ids = {d["local_id"] for d in digest}
        known = sent | digest_ids | {i for pair in batch.pairs for i in pair}

        def check_output(out: VerificationBatchOutput) -> list[str]:
            problems: list[str] = []
            if out.refusal is None:
                got = [r.local_id for r in out.results]
                if sorted(got) != sorted(sent):  # P2: exactly one result per claim sent
                    problems.append("results must hold exactly one entry per claim sent")
            for pair in out.claim_conflicts:  # P9
                if pair.claim_a == pair.claim_b or not {pair.claim_a, pair.claim_b} <= known:
                    problems.append("claim_conflicts must name two different known claims")
            return problems

        return self._runner.complete_json(
            task=task,
            ctx=ctx,
            usage=state.usage,
            step_key=f"V4_batch_{batch.index}",
            prompt=prompt,
            variables=variables,
            model=VerificationBatchOutput,
            language=inp.language,
            check=check_output,
        )

    def _reconcile(
        self,
        batch: Batch,
        out: VerificationBatchOutput,
        evidence: Mapping[str, ClaimEvidence],
        outcomes: dict[str, Outcome],
        flagged: set[str],
    ) -> None:
        plans = {p.claim.local_id: p for p in batch.plans}
        if out.refusal is not None:
            reason = out.refusal.reason
            if reason is RefusalReason.INSUFFICIENT_INPUT:
                raise InsufficientInputError(
                    "the model refused: insufficient input",
                    details={"refusal": out.refusal.to_doc()},
                )
            if reason is not RefusalReason.UNSAFE_CONTENT:
                raise InputInvalidError(
                    "the model refused the input", details={"refusal": out.refusal.to_doc()}
                )
            for lid, plan in plans.items():
                outcomes[lid] = refused_outcome(plan)
            return
        by_id = {r.local_id: r for r in out.results}
        for lid, plan in plans.items():
            cands = {
                eid: batch.evidence[eid] for eid in batch.claim_ids[lid] if eid in batch.evidence
            }
            outcomes[lid] = reconcile_claim(
                plan, evidence[lid], cands, by_id[lid], flagged, self._settings
            )

    # ------------------------------------------------------------------ V-S6
    def _persist(
        self,
        task: TaskInput,
        ctx: ExecContext,
        inp: VerificationInput,
        result: StageResult,
        reads: int,
    ) -> None:
        tenant = ctx.tenant
        rows: list[CitationRow] = []
        kinds = {c.citation_ref: c.kind for c in inp.available_citations}
        for claim in result.claims:
            for ev in claim.evidence:
                if ev.source_ref in kinds:
                    rows.append(
                        CitationRow(
                            claim.claim_id, ev.source_ref, kinds[ev.source_ref], ev.relation
                        )
                    )
        with self._tenancy.transaction(tenant) as tx:
            self._claims.update_status(tx, task_id=task_key(task), results=result.claims)
            self._claims.insert_citations(tx, rows)
            self._audit.append(
                tx,
                NewAuditEntry(
                    actor_kind=ActorKind.AGENT,
                    actor_ref=ActorRef(AGENT_ID),
                    authority="agent_06.claim_verification",
                    action="claims.verified",
                    target_kind="script",
                    target_id=inp.script_id,
                    occurred_at=self._clock.now(),
                    details={
                        "task_id": task.task_id,
                        "verify_mode": inp.verify_mode.value,
                        "claims": len(result.claims),
                        "knowledge_reads": reads,
                        "verdict": result.overall.proposed_verdict.value,
                        "gate": result.gate.value,
                    },
                ),
            )

    # ------------------------------------------------------------------ V-S7
    def _assemble(
        self,
        task: TaskInput,
        ctx: ExecContext,
        state: _State,
        started: int,
        inp: VerificationInput,
        output: VerificationOutput,
        outcomes: Sequence[Outcome],
        evidence: Mapping[str, ClaimEvidence],
        leaks: int,
    ) -> TaskOutput:
        tenant = ctx.tenant
        doc = output.to_doc()
        ref = write_blob(self._blobs, tenant, task, ctx, "claim_verification_output.json", doc)
        results = self._results(inp, output, outcomes, evidence, leaks)
        failed = [r.check_id for r in results if r.gate and r.verdict.value == "FAIL"]
        log.info(  # ids, counts and codes only (NFR-6): never claim text or evidence
            "fact.completed",
            extra={
                "task_id": task.task_id,
                "verify_mode": inp.verify_mode.value,
                "claims": len(output.claims),
                "verdict": output.overall.proposed_verdict.value,
                "llm_calls": state.usage.llm_calls,
            },
        )
        return success_output(
            clock=self._clock,
            started_ms=started,
            schema=OUTPUT_SCHEMA,
            doc=doc,
            refs=[ref],
            results=results,
            usage=state.usage,
            next_action=next_action_for(output.overall.proposed_verdict, failed),
        )

    def _results(
        self,
        inp: VerificationInput,
        output: VerificationOutput,
        outcomes: Sequence[Outcome],
        evidence: Mapping[str, ClaimEvidence],
        leaks: int,
    ) -> list[ValidationResult]:
        s = self._settings
        by_local = {o.claim.local_id: o for o in outcomes}
        complete = {c.local_id for c in output.claims} == {c.local_id for c in inp.claims}
        resolvable = all(
            any(
                cand.source_ref == ev.source_ref and cand.source_sha256 == ev.content_sha256
                for cand in evidence[c.local_id].candidates
            )
            for c in output.claims
            for ev in c.evidence
            if c.local_id in evidence
        )
        bad_verified = _verified_violations(output.claims, by_local, s)
        numbers_ok = not any(v == "number" for v in bad_verified.values())
        evidence_ok = not any(v != "number" for v in bad_verified.values())
        restricted_ok = inp.our_method_release_approved or not any(
            o.restricted_used for o in outcomes
        )
        spans_ok = all(
            any(
                cand.source_ref == ev.source_ref and ev.char_end <= cand.source_len
                for cand in evidence[c.local_id].candidates
            )
            for c in output.claims
            for ev in c.evidence
            if c.local_id in evidence
        )
        recount = accuracy(outcomes)
        unresolved = [
            c.local_id
            for c in output.claims
            if c.status is not ClaimStatus.VERIFIED and c.mode is not ClaimMode.SKIPPED
        ]
        contradicted = output.gate_verdict.value == "FAILED"
        recomputed = all(
            c.verification_verdict == verification_verdict(c.status, s.verdict_map)
            for c in output.claims
        )
        pair_ok = all(
            len(set(p.claim_ids)) == 2 and len(set(p.local_ids)) == 2
            for p in output.claim_conflicts
        )
        return [
            check(
                "fact.schema", True, "payload validated by its model when parsed (a failure raises)"
            ),
            check(
                "fact.script_hash",
                output.script_sha256 == inp.script_sha256,
                "script_sha256 echoes the input (equal to scripts.content_sha256, checked at V0)",
            ),
            check(
                "fact.tenant_scope", True, "claims and refs belong to the task's org and channel"
            ),
            check("fact.claims_complete", complete, "one entry per input claim, no extra"),
            check(
                "fact.evidence_resolvable",
                resolvable,
                "every evidence item has a resolvable source",
            ),
            check(
                "fact.span_valid", spans_ok, "every evidence span lies inside its source text (P4)"
            ),
            check(
                "fact.number_guard",
                numbers_ok,
                "no VERIFIED claim has a numeral absent from evidence",
            ),
            check(
                "fact.verified_requires_evidence", evidence_ok, "VERIFIED claims rest on evidence"
            ),
            check(
                "fact.injected_excluded",
                leaks == 0,
                "no evidence item from a flagged passage",
            ),
            check(
                "fact.restricted_gate",
                restricted_ok,
                "no restricted source used without a release",
                rule_id="FIN-R12",
            ),
            check("fact.conflict_refs_valid", pair_ok, "every conflict names two input claims"),
            check("fact.verdict_recomputed", recomputed, "verdicts equal the code derivation"),
            check(
                "fact.accuracy_counters",
                recount == output.accuracy_summary,
                "counters equal a recount",
                blocking=False,
                warn_instead=True,
            ),
            check(
                "fact.unresolved_claims",
                not unresolved,
                f"{len(unresolved)} claim(s) are not VERIFIED",
                blocking=False,
                warn_instead=True,
                measured=len(unresolved),
            ),
            check(
                "fact.gate.no_contradicted_claim",
                not contradicted,
                "gate FAILED: a claim is CONTRADICTED"
                if contradicted
                else "gate: no claim is CONTRADICTED",
                gate=True,
            ),
        ]


def _verified_violations(
    claims: Sequence[VerifiedClaim], by_local: Mapping[str, Outcome], s: FactCheckSettings
) -> dict[str, str]:
    """Self-check of blueprint 8.4: re-derive the preconditions of every ``VERIFIED`` claim."""
    bad: dict[str, str] = {}
    for c in claims:
        if c.status is not ClaimStatus.VERIFIED:
            continue
        o = by_local[c.local_id]
        wanted = numerals(o.claim.quote + " " + o.claim.normalized_claim)
        if missing_numerals(wanted, o.support_texts, s.rounding_match):
            bad[c.local_id] = "number"
        elif not any(e.relation.value == "SUPPORTS" for e in c.evidence):
            bad[c.local_id] = "evidence"
        elif c.mode is ClaimMode.EVIDENCE and not (
            c.script_cited
            and o.support_tiers
            and min(s.tier_rank(t) for t in o.support_tiers) <= s.tier_rank(s.min_tier_for_verified)
        ):
            bad[c.local_id] = "tier_or_citation"
        elif c.mode is ClaimMode.CHART_FACTS and not c.script_cited:
            bad[c.local_id] = "chart"
    return bad


__all__ = ["ClaimVerificationStep"]
