"""``ScriptInputResolver``: the production ``InputResolver`` of agent_05 script drafting.

What it does itself (blueprint 7.3): checks the Task Input (channel, language, first draft only),
reads the research pack through its hash-verified context ref, builds the tenant facts (every
context ref must belong to the task's org; its stored SHA-256 must equal the reference), decides
finance or non-finance from the channel's own category (unknown = finance), and marks every
library source the pack cites QUOTABLE or IDEAS_ONLY with the per-work copyright rule
(``LibrarySourceClassifier``; the library is read only through the read-only reader, pinned by
repo path + commit SHA; no text is copied, logged or stored).

What it takes from injected ports because no registered document schema exists (CCR-290, CCR-306):
the rule-pack texts, the compliance profile, the lexicons, the Latin allow-list and the disclaimer
template (``ScriptDocumentSource``) and the database facts of the channel (``ChannelFactsReader``).
A missing port is a typed ``MissingDependencyError``: nothing is invented.

NOT resolved here (refused, fail closed): revisions (``iteration > 0`` or a revision block) and
Shorts adaptation: they need the prior output's omitted concepts, the parent's claim status and the
previous cut, which no document provides yet."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from pydantic import ValidationError

from agent_05_scriptwriter.assemble.parts import DisclaimerTemplate
from agent_05_scriptwriter.contracts import ScriptDraftInput, ShortsAdaptationInput
from agent_05_scriptwriter.errors import (
    CrossTenantRef,
    InputInvalid,
    MissingDependency,
)
from agent_05_scriptwriter.lexicon import LexiconPack
from agent_05_scriptwriter.pre.brief_mapper import ApprovalView, ResearchPackView
from agent_05_scriptwriter.pre.tenant_guard import RefFact, TenantFacts
from agent_05_scriptwriter.protocols import RulePack, StepContext
from agent_05_scriptwriter.steps.common import ResolvedInputs
from agent_06_fact_checker.library.reader import KnowledgeLibraryReader
from amw_core.config import effective_non_finance_categories
from amw_core.contracts.task_input import TaskInput
from amw_core.enums import ContextRefPurpose
from amw_core.ids import ActorRef, CorrelationId, OrgId, Prefix, new_id
from amw_core.interfaces.storage import BlobStorage, BlobUri
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.tenancy.storage_paths import uri_owner
from amw_orchestrator.input_limits import InputLimits, read_bounded
from amw_orchestrator.script_inputs.sources import (
    NOT_A_LIBRARY_WORK,
    LibrarySourceClassifier,
    ResolvedSource,
    SourceUse,
)

PACK_SCHEMA = "agent_04.research_pack.output"


@dataclass(slots=True)
class ScriptResolvedInputs(ResolvedInputs):
    """``ResolvedInputs`` plus what this resolver established beyond them."""

    sources: dict[str, ResolvedSource] = field(default_factory=dict)
    """Per cited citation ref: QUOTABLE / IDEAS_ONLY."""
    finance_rules_apply: bool = True


@dataclass(frozen=True, slots=True)
class ChannelFacts:
    """Database facts of the task's tenant and channel (04 organisations / channels)."""

    db_org_id: str
    channel_org_id: str | None
    tenant_status: str
    category: str | None


class ChannelFactsReader(Protocol):
    def facts(self, ctx: StepContext) -> ChannelFacts | None: ...


class ScriptDocumentSource(Protocol):
    """Documents without a registered schema (CCR-290): the composition root supplies them."""

    def profile_rule_packs(self, ctx: StepContext, task_input: TaskInput) -> list[str]: ...

    def rule_packs(
        self, ctx: StepContext, task_input: TaskInput, keys: Sequence[str]
    ) -> dict[str, RulePack]: ...

    def lexicons(self, ctx: StepContext, task_input: TaskInput) -> LexiconPack: ...

    def latin_allow_list(self, ctx: StepContext, task_input: TaskInput) -> list[str] | None: ...

    def disclaimer_template(
        self, ctx: StepContext, task_input: TaskInput
    ) -> DisclaimerTemplate | None: ...

    def approvals(
        self, ctx: StepContext, task_input: TaskInput, approval_ids: Sequence[str]
    ) -> list[ApprovalView]: ...


class JobDateSource(Protocol):
    """The date the job started: the public-domain test counts years back from its calendar year
    (CCR-270). Never a global clock read inside the rule."""

    def job_date(self, task_input: TaskInput) -> date: ...


LibraryFor = Callable[[TaskInput], KnowledgeLibraryReader | None]
"""The read-only library of the job (path + commit SHA from the job request), or ``None``."""


class ScriptInputResolver:
    def __init__(
        self,
        *,
        storage: BlobStorage,
        channels: ChannelFactsReader,
        documents: ScriptDocumentSource,
        classifier: LibrarySourceClassifier,
        library_for: LibraryFor,
        job_dates: JobDateSource,
        limits: InputLimits,
        non_finance_categories: object,
        new_script_id: Callable[[], str] = lambda: str(new_id(Prefix.SCRIPT)),
    ) -> None:
        self._storage, self._channels, self._documents = storage, channels, documents
        self._classifier, self._library_for, self._job_dates = classifier, library_for, job_dates
        self._non_finance = effective_non_finance_categories(non_finance_categories)
        self._limits = limits
        self._new_script_id = new_script_id

    # -- the InputResolver port ----------------------------------------------------------------
    def resolve(
        self,
        ctx: StepContext,
        task_input: TaskInput,
        data: ScriptDraftInput | ShortsAdaptationInput,
    ) -> ResolvedInputs:
        if not isinstance(data, ScriptDraftInput):
            raise MissingDependency(
                "shorts adaptation inputs cannot be resolved yet",
                details={"class": "script_revision_inputs"},
            )
        if data.iteration > 0 or data.revision is not None:
            raise MissingDependency(
                "revision inputs (prior omitted concepts) cannot be resolved yet",
                details={"class": "script_revision_inputs"},
            )
        if ctx.channel_id != task_input.channel_id:
            raise InputInvalid("the step context and the Task Input name different channels")
        facts = self._channels.facts(ctx)
        if facts is None:
            raise MissingDependency("channel not found", details={"class": "channel"})
        finance = self._finance_applies(data.channel_category, facts)
        pack = self._pack(ctx, task_input)
        tenant = TenantFacts(
            envelope_org=task_input.org_id,
            input_org=ctx.org_id,
            db_org=facts.db_org_id,
            channel_org=facts.channel_org_id,
            tenant_status=facts.tenant_status,
            refs=self._ref_facts(ctx, task_input),
            task_channel=ctx.channel_id,
        )
        keys = list(data.active_rule_packs)
        sources = self._sources(task_input, pack)
        return ScriptResolvedInputs(
            tenant=tenant,
            rule_packs=self._documents.rule_packs(ctx, task_input, keys),
            profile_rule_packs=self._documents.profile_rule_packs(ctx, task_input),
            lexicons=self._documents.lexicons(ctx, task_input),
            new_script_id=self._new_script_id(),
            pack=pack,
            approvals=self._documents.approvals(
                ctx, task_input, list(pack.method.release_approval_ids)
            ),
            brand_latin_allow_list=self._documents.latin_allow_list(ctx, task_input),
            disclaimer_template=(self._require_disclaimer(ctx, task_input) if finance else None),
            sources=sources,
            finance_rules_apply=finance,
        )

    # -- pieces --------------------------------------------------------------------------------
    def _finance_applies(self, category: str, facts: ChannelFacts) -> bool:
        """The channel's own category decides (CCR-295); the input must agree with it. Unknown,
        unset or ``finance`` means finance rules apply (D13, fail closed)."""
        own = facts.category or ""
        if own and category != own:
            raise InputInvalid("the input channel category differs from the channel's category")
        return not (own and category in self._non_finance)

    def _require_disclaimer(self, ctx: StepContext, task_input: TaskInput) -> DisclaimerTemplate:
        template = self._documents.disclaimer_template(ctx, task_input)
        if template is None:
            raise MissingDependency(
                "finance rules apply and the disclaimer template is missing",
                details={"class": "disclaimer_template"},
            )
        return template

    @staticmethod
    def _tenant(ctx: StepContext) -> TenantContext:
        return TenantContext(
            OrgId(ctx.org_id), ActorRef(ctx.actor), CorrelationId(ctx.correlation_id)
        )

    def _read(self, ctx: StepContext, uri: str, sha256: str) -> bytes:
        """The research pack, bounded while it is read (a larger blob is not a pack)."""
        return read_bounded(
            self._storage.get(self._tenant(ctx), BlobUri(uri), sha256),
            self._limits.max_research_pack_bytes,
            lambda: InputInvalid("a context document is too large"),
        )

    def _pack(self, ctx: StepContext, task_input: TaskInput) -> ResearchPackView:
        refs = [
            r
            for r in task_input.context_refs
            if r.purpose is ContextRefPurpose.PRIOR_OUTPUT and r.schema_ == PACK_SCHEMA
        ]
        if len(refs) != 1:
            raise MissingDependency(
                "the task needs exactly one research pack reference",
                details={"class": "research_pack"},
            )
        if uri_owner(refs[0].uri) != ctx.org_id:
            raise CrossTenantRef("the research pack belongs to another tenant")
        if not refs[0].sha256:
            raise InputInvalid("the research pack reference has no SHA-256")
        try:
            return ResearchPackView.model_validate_json(
                self._read(ctx, refs[0].uri, refs[0].sha256)
            )
        except ValidationError:
            raise InputInvalid("the research pack does not match its view") from None

    def _ref_facts(self, ctx: StepContext, task_input: TaskInput) -> list[RefFact]:
        tenant = self._tenant(ctx)
        facts: list[RefFact] = []
        for ref in task_input.context_refs:
            owner = uri_owner(ref.uri)
            if owner != ctx.org_id and owner != "platform":
                facts.append(RefFact(ref.purpose.value, owner, None, False))
                continue
            head = self._storage.head(tenant, BlobUri(ref.uri))
            facts.append(
                RefFact(
                    ref.purpose.value,
                    ctx.org_id if owner == "platform" else owner,
                    None,
                    head.exists and head.sha256 == ref.sha256,
                )
            )
        return facts

    def _sources(self, task_input: TaskInput, pack: ResearchPackView) -> dict[str, ResolvedSource]:
        """Every KNOWLEDGE_CHUNK citation a usable evidence line cites; an external reference is
        ideas-only by construction (CCR-291: a quote needs a library record)."""
        kinds = {c.citation_ref: c.kind for c in pack.citations_available}
        cited = list(dict.fromkeys(e.citation_ref for e in pack.evidence if e.usable_for_script))
        library_refs = [c for c in cited if kinds.get(c, "KNOWLEDGE_CHUNK") == "KNOWLEDGE_CHUNK"]
        out: dict[str, ResolvedSource] = {
            c: ResolvedSource(c, SourceUse.IDEAS_ONLY, None, NOT_A_LIBRARY_WORK)
            for c in cited
            if c not in library_refs
        }
        if library_refs:
            library = self._library_for(task_input)
            out.update(
                self._classifier.classify(
                    library_refs, library=library, job_date=self._job_dates.job_date(task_input)
                )
            )
        return out
