"""Shared step types and pre-checks (blueprint 10.1, 16, 18)."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_05_scriptwriter.assemble.parts import DisclaimerTemplate
from agent_05_scriptwriter.checks.results import CheckResult, passed, warned
from agent_05_scriptwriter.contracts import (
    Provenance,
    ProvenanceCall,
    ScriptDocument,
    ScriptDraftResult,
    ShortsAdaptationResult,
)
from agent_05_scriptwriter.errors import ConfigInvalid, InputInvalid, MissingDependency
from agent_05_scriptwriter.lexicon import LexiconPack
from agent_05_scriptwriter.llm.prompt_renderer import LoadedPrompt, load_prompt
from agent_05_scriptwriter.llm.structured_caller import CallRecord
from agent_05_scriptwriter.observability import log_security_event
from agent_05_scriptwriter.pre.brief_mapper import ApprovalView, ResearchPackView
from agent_05_scriptwriter.pre.speech_budget import hook_budget
from agent_05_scriptwriter.pre.tenant_guard import TenantFacts, check_tenant
from agent_05_scriptwriter.protocols import RulePack, SavedScript, StepContext
from agent_05_scriptwriter.settings import Agent05Settings
from amw_core.errors import AmwError


@dataclass(frozen=True, slots=True)
class PromptSet:
    plan: LoadedPrompt
    section: LoadedPrompt
    cut: LoadedPrompt | None = None


def load_prompts(root: Path) -> PromptSet:
    """Load the three prompt files of ``prompts/agent_05_scriptwriter`` (SHA-256 recorded)."""
    base = root / "agent_05_scriptwriter"
    return PromptSet(
        plan=load_prompt(base / "script_draft.v1.md"),
        section=load_prompt(base / "script_draft_section.v1.md"),
        cut=load_prompt(base / "shorts_adaptation.v1.md"),
    )


@dataclass(slots=True)
class ResolvedInputs:
    """Everything the worker loaded and hash-verified from the task's context refs (7.3)."""

    tenant: TenantFacts
    rule_packs: dict[str, RulePack]
    profile_rule_packs: list[str]
    lexicons: LexiconPack
    new_script_id: str
    pack: ResearchPackView | None = None
    approvals: list[ApprovalView] = field(default_factory=list)
    brand_latin_allow_list: list[str] | None = None
    disclaimer_template: DisclaimerTemplate | None = None
    prior_script: ScriptDocument | None = None
    prior_script_sha256: str | None = None
    parent_script: ScriptDocument | None = None
    parent_script_sha256: str | None = None
    parent_claims_cleared: bool = False
    previous_cut: ScriptDocument | None = None


@dataclass(slots=True)
class StepOutcome:
    status: str  # SUCCEEDED | FAILED | SUSPENDED
    result: ScriptDraftResult | ShortsAdaptationResult | None
    validation_results: list[CheckResult]
    error: AmwError | None = None
    saved: SavedScript | None = None
    records: list[CallRecord] = field(default_factory=list)
    wait_reason: str | None = None
    checkpoint_step: str | None = None
    stored_output_returned: bool = False
    document_bytes: bytes | None = None
    refusal_rule_ids: list[str] = field(default_factory=list)


def pre_checks(
    ctx: StepContext,
    settings: Agent05Settings,
    inputs: ResolvedInputs,
    *,
    language: str,
    active_rule_packs: Sequence[str],
    channel_category: str,
    pointer_needed_pack: str = "rp.finance_sebi_in",
) -> list[CheckResult]:
    """D-PRE-1..5; raises typed errors before any paid call."""
    check_tenant(inputs.tenant, lambda event, _f: log_security_event(event, ctx.org_id))
    results = [passed("a05.pre.tenant", "tenant, channel and references belong to the task")]
    if language not in settings.languages_enabled:
        raise InputInvalid("language is not enabled", details={"language": language})
    results.append(passed("a05.pre.language", "language enabled"))
    if set(active_rule_packs) != set(inputs.profile_rule_packs):
        raise InputInvalid("active_rule_packs differ from the compliance profile")
    for key in active_rule_packs:
        if key not in inputs.rule_packs:
            raise ConfigInvalid("rule pack not loadable", details={"key": key})
    if "rp.youtube_general" not in active_rule_packs:
        raise InputInvalid("rp.youtube_general is required")
    results.append(passed("a05.pre.rules", "rule packs present"))
    if ctx.max_llm_calls < 2:
        from agent_05_scriptwriter.errors import LoopCapExceeded

        raise LoopCapExceeded("max_llm_calls too small for a plan and one section")
    results.append(passed("a05.pre.budget", "reservation and call cap present"))
    rate = settings.rate_for(language)
    budget = hook_budget(rate, settings.hook_window_ms, settings.hook_min_fill_ratio)
    results.append(
        passed("a05.pre.speech_budget", "speech budget computed")
        if budget.budget is not None
        else warned("a05.pre.speech_budget", "speech rate unset: budgets are null")
    )
    return results


def require_pack(inputs: ResolvedInputs) -> ResearchPackView:
    if inputs.pack is None:
        raise MissingDependency("research pack is missing")
    return inputs.pack


def provenance_calls(records: Sequence[CallRecord]) -> list[ProvenanceCall]:
    return [
        ProvenanceCall(
            step_key=r.step_key,
            provider=r.provider,
            model=r.model,
            tokens_in=r.tokens_in,
            tokens_out=r.tokens_out,
            tokens_cached_in=r.tokens_cached_in,
            cost_entry_id=r.cost_entry_id,
        )
        for r in records
    ]


def records_from_state(state: dict[str, Any]) -> list[CallRecord]:
    return [CallRecord(**r) for r in state.get("calls", [])]


def make_provenance(
    prompts: PromptSet, versions: dict[str, str], families: list[str], records: Sequence[CallRecord]
) -> Provenance:
    return Provenance(
        plan_prompt_id=prompts.plan.prompt_id,
        section_prompt_id=prompts.section.prompt_id,
        prompt_sha256={
            prompts.plan.prompt_id: prompts.plan.sha256,
            prompts.section.prompt_id: prompts.section.sha256,
        },
        rule_pack_versions=versions,
        config_key_families=families,
        calls=provenance_calls(records),
    )
