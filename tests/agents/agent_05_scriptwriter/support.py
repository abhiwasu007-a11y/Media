"""Test support for Agent 05: fake LLM script, in-memory ports, fixture builders.

All text is invented. Scanner words (``lex_test_v1``) and thresholds are test values, not product
defaults (the product lexicons are REQUIRES REVIEW, blueprint 6.4).
"""

import json
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_05_scriptwriter.assemble.parts import DisclaimerTemplate
from agent_05_scriptwriter.checks.context import Scanners
from agent_05_scriptwriter.contracts import ScriptDraftInput
from agent_05_scriptwriter.lexicon import LanguageLexicon, LexiconPack, PatternRule
from agent_05_scriptwriter.pre.brief_mapper import ResearchPackView
from agent_05_scriptwriter.pre.tenant_guard import RefFact, TenantFacts
from agent_05_scriptwriter.protocols import (
    CheckpointState,
    HookHistoryEntry,
    LedgerRow,
    Ports,
    RulePack,
    SavedScript,
    StepContext,
)
from agent_05_scriptwriter.settings import Agent05Settings, LlmStepSettings, NearCopySettings
from agent_05_scriptwriter.steps.common import PromptSet, ResolvedInputs, load_prompts
from amw_adapters.common import FAKE_PRICE_REF, CallUsage, FakeProvider
from amw_adapters.llm import LlmRequest, LlmResponse, TokenCount
from amw_core import ids
from amw_core.enums import BillingMode
from amw_core.errors import (
    BudgetExhaustedError,
    DbTransientError,
    ProviderRefusalError,
    RateLimitedError,
)

ROOT = Path(__file__).resolve().parents[3]
PROMPTS = ROOT / "docs" / "v4" / "prompts"


def _rule(rule_id: str, *groups: tuple[str, ...]) -> PatternRule:
    return PatternRule(rule_id=rule_id, requires=tuple(groups))


EN = LanguageLexicon(
    fin_rules=(
        _rule("FIN-R1", (r"\b(buy|sell|hold)\b",), (r"\bNIFTY\b",)),
        _rule("FIN-R2", (r"\bNIFTY\b",), (r"\d[\d,]*\d",)),
        _rule("FIN-R3", (r"this week|tomorrow|looks weak",)),
        _rule("FIN-R6", (r"\d+\s*%",), (r"profit|return",)),
        _rule("FIN-R7", (r"testimonial",)),
        _rule("FIN-R8", (r"\bbroker\b",), (r"\b(link|account)\b",)),
    ),
    forward_rules=(_rule("FIN-R13", (r"\bNIFTY\b",), (r"\b(will|could go|next move)\b",)),),
    first_person=(r"\bmy (students|profit|results)\b", r"\bI am\b"),
    referral=(r"\buse code [A-Z0-9]+",),
    disclaimer_like=(r"not (financial )?advice",),
    brand_intro=(r"\b(welcome to|subscribe)\b",),
    promise_forbidden=(r"\b(guaranteed|secret)\b",),
)
MR = LanguageLexicon(fin_rules=(_rule("FIN-R6", (r"\d+\s*%",), ("नफा",)),))
LEX_TEST_V1 = LexiconPack(
    name="lex_test_v1", version="1", languages={"en-IN": EN, "mr-IN": MR, "hi-IN": MR}
)
SCANNERS = Scanners.from_lexicons(LEX_TEST_V1)


def scanners_for(_pack: LexiconPack) -> Scanners:
    return SCANNERS


def step_settings(key: str) -> LlmStepSettings:
    return LlmStepSettings(
        model="fake-model-test",
        temperature=0.0,
        max_output_tokens=4000,
        timeout_ms=30_000,
        cost_budget_micros=1_000_000,
        config_key_family=key,
    )


def make_settings(**over: Any) -> Agent05Settings:
    base: dict[str, Any] = {
        "plan": step_settings("llm.agent_05.script_draft.plan.*"),
        "section": step_settings("llm.agent_05.script_draft.section.*"),
        "cut": step_settings("llm.agent_05.shorts_adaptation.cut.*"),
        "near_copy": NearCopySettings(ngram_n=4, max_overlap_ratio=0.5, max_common_run_chars=60),
        "shorts_max_duration_ms": 60_000,
    }
    base.update(over)
    return Agent05Settings(**base)


_CIT = [f"kch_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d80{i:02d}" for i in range(1, 4)]


def make_pack(*, with_method: bool = False) -> ResearchPackView:
    evidence = [
        ("ev_001", "c01", _CIT[0], "Momentum tools compare recent rises with recent falls."),
        ("ev_002", "c02", _CIT[1], "Divergence means price and a tool move apart."),
        ("ev_003", "c02", _CIT[2], "It signals changing momentum only."),
    ]
    return ResearchPackView.model_validate(
        {
            "topic_verdict": {"verdict": "ALLOWED", "violated_rule_ids": []},
            "concepts": [
                {
                    "concept_id": "c01",
                    "label": "momentum tool",
                    "label_en": "momentum tool",
                    "coverage": "SOURCED",
                },
                {
                    "concept_id": "c02",
                    "label": "divergence",
                    "label_en": "divergence",
                    "coverage": "SOURCED",
                },
                {
                    "concept_id": "c03",
                    "label": "average",
                    "label_en": "average",
                    "coverage": "UNSOURCED",
                },
            ],
            "evidence": [
                {
                    "evidence_id": e,
                    "concept_id": c,
                    "citation_ref": r,
                    "note": n,
                    "usable_for_script": True,
                    "method_labelled": False,
                    "exclusion_reason": None,
                }
                for e, c, r, n in evidence
            ],
            "citations_available": [
                {"citation_ref": r, "kind": "KNOWLEDGE_CHUNK", "title": f"Note {i}"}
                for i, r in enumerate(_CIT)
            ],
            "method": {"used": with_method, "release_approval_ids": []},
            "terminology": [],
        }
    )


class _Ids:
    org = ids.ORG.new()
    channel = ids.CHANNEL.new()
    job = ids.JOB.new()
    project = ids.PROJECT.new()


def make_ctx(task_id: str | None = None, *, max_calls: int = 30) -> StepContext:
    return StepContext(
        org_id=_Ids.org,
        job_id=_Ids.job,
        task_id=task_id or ids.TASK.new(),
        attempt_id=ids.ATTEMPT.new(),
        channel_id=_Ids.channel,
        project_id=_Ids.project,
        correlation_id=ids.CORRELATION.new(),
        max_llm_calls=max_calls,
        max_cost_micros=10_000_000,
    )


def make_input(language: str = "en-IN", **over: Any) -> ScriptDraftInput:
    data: dict[str, Any] = {
        "topic": {
            "title": "Divergence on a past chart",
            "angle": None,
            "target_duration_ms": 480000,
        },
        "video_kind": "GENERAL",
        "language": language,
        "channel_category": "finance",
        "owner_sebi_registration": "UNREGISTERED",
        "active_rule_packs": ["rp.youtube_general", "rp.finance_sebi_in"],
        "course_chapter_pointer": None,
        "iteration": 0,
        "revision": None,
    }
    data.update(over)
    return ScriptDraftInput.model_validate(data)


def make_resolved(ctx: StepContext, **over: Any) -> ResolvedInputs:
    packs = {
        "rp.youtube_general": RulePack("rp.youtube_general", "v1", "PLATFORM RULES YT", "PLATFORM"),
        "rp.finance_sebi_in": RulePack(
            "rp.finance_sebi_in", "v1", "PLATFORM RULES FIN", "PLATFORM"
        ),
    }
    res = ResolvedInputs(
        tenant=TenantFacts(
            envelope_org=ctx.org_id,
            input_org=ctx.org_id,
            db_org=ctx.org_id,
            channel_org=ctx.org_id,
            tenant_status="ACTIVE",
            refs=[RefFact("PRIOR_OUTPUT", ctx.org_id, ctx.channel_id, True)],
            task_channel=ctx.channel_id,
        ),
        rule_packs=packs,
        profile_rule_packs=["rp.youtube_general", "rp.finance_sebi_in"],
        lexicons=LEX_TEST_V1,
        new_script_id=ids.new_id(ids.Prefix.SCRIPT),
        pack=make_pack(),
        brand_latin_allow_list=["NIFTY"],
        disclaimer_template=DisclaimerTemplate(
            "amw-blob://platform/tpl/d.json", "v-test", "TEST DISCLAIMER TEXT."
        ),
    )
    for k, v in over.items():
        setattr(res, k, v)
    return res


# ---------------------------------------------------------------------------- model outputs
ORDINALS = ["one", "two", "three", "four", "five", "six", "seven", "eight"]
PACE = ["NORMAL", "FAST", "SLOW"]
EMO = ["CURIOUS", "NEUTRAL", "SERIOUS"]


def plan_json(n: int, *, key: str = "divergence", selected: str = "h1") -> dict[str, Any]:
    shares = [1000 // n] * n
    shares[-1] += 1000 - sum(shares)
    start, mid = 0, 0
    for i, share in enumerate(shares):
        if start <= 500 < start + share:
            mid = i
        start += share

    def hook(hid: str, style: str, vr: int, cw: int, chart: bool) -> dict[str, Any]:
        def beat(name: str, text: str, example: str | None) -> dict[str, Any]:
            return {
                "beat": name,
                "sentences": [{"text": text, "pace": "NORMAL", "emotion": "CURIOUS"}],
                "concrete_example": example,
                "chart_request": (
                    {
                        "chart_id": "chart_9",
                        "chart_kind": "SCHEMATIC",
                        "instrument": None,
                        "timeframe": "1D",
                        "indicators": [],
                        "pattern_concept_id": "k2",
                        "outcome_shown": "NOT_APPLICABLE",
                        "must_be_historical": True,
                    }
                    if chart and name == "HOOK_PROOF"
                    else None
                ),
                "concept_refs": [],
            }

        return {
            "hook_id": hid,
            "hook_style": style,
            "beats": [
                beat(
                    "HOOK_PROOF",
                    f"A {key} showed up on an invented chart, option {hid}.",
                    "an invented chart",
                ),
                beat("HOOK_WHY", f"Why does a {key} matter to a learner, option {hid}?", None),
                beat("HOOK_COVERS", f"We cover how a {key} is read, option {hid}.", None),
            ],
            "rubric": {
                "viewer_relevance": vr,
                "curiosity_without_clickbait": cw,
                "rationale": "scored on the written rubric",
            },
        }

    sections = []
    for i in range(n):
        last = i == n - 1
        sections.append(
            {
                "section_id": f"sec{i + 1}",
                "section_kind": "RECAP" if last and n > 1 else "CONCEPT",
                "heading_local": f"Part {ORDINALS[i]}",
                "heading_en": f"Part {ORDINALS[i]}",
                "purpose": f"Teach part {ORDINALS[i]} of the idea.",
                "concept_ids": ["k2", "k1"] if i == 1 else ["k1"],
                "share_permille": shares[i],
                "needs_interrupt": i in (0, mid),
            }
        )
    plan_concepts = [
        {
            "concept_id": "k1",
            "taught_in_section_ids": ["sec1"],
            "own_words_angle": "plain words",
            "original_example_idea": "an invented example",
            "citation_refs": [_CIT[0]],
        }
    ]
    if n > 1:
        plan_concepts.append(
            {
                "concept_id": "k2",
                "taught_in_section_ids": ["sec2"],
                "own_words_angle": "plain words",
                "original_example_idea": "an invented example",
                "citation_refs": [_CIT[1], _CIT[2]],
            }
        )
        omitted = [{"concept_id": "k3", "reason": "NO_SOURCE"}]
    else:
        omitted = [
            {"concept_id": "k2", "reason": "DURATION_LIMIT"},
            {"concept_id": "k3", "reason": "NO_SOURCE"},
        ]
    return {
        "title_promise": {
            "working_title_local": f"What a {key} really tells you",
            "promise_statement": f"You will learn what a {key} is and what it is not.",
            "promise_key_terms": [key],
        },
        "hooks": [
            hook("h1", "CONCRETE_CASE", 2, 2, True),
            hook("h2", "QUESTION", 1, 2, False),
            hook("h3", "MYTH_BUST", 2, 1, False),
        ],
        "selected_hook_id": selected,
        "sections": sections,
        "concept_plan": plan_concepts,
        "omitted_concepts": omitted,
        "description_draft": f"A short lesson on the {key} using invented examples only.",
        "thumbnail_brief": {
            "subject_idea": f"a simple {key} sketch",
            "text_idea_local": f"{key}?",
            "must_not_promise": ["profit"],
        },
        "refusal": None,
    }


def section_json(step_input: dict[str, Any], *, copy_text: str | None = None) -> dict[str, Any]:
    plan = step_input["section_plan"]
    sid = plan["section_id"]
    n = int(sid[3:])
    concept = plan["concept_ids"][0]
    brief = next(b for b in step_input["concept_briefs"] if b["concept_id"] == concept)
    refs = [{"concept_id": concept, "citation_refs": brief["citation_refs"][:1]}]
    word = ORDINALS[n - 1]
    scenes = []
    for j in range(2):
        text = copy_text or (
            f"This is part {word} of the lesson. Scene {ORDINALS[j]} keeps the idea simple."
        )
        scenes.append(
            {
                "scene_local_id": f"sc{j + 1}",
                "beat": "RECAP" if plan["section_kind"] == "RECAP" else "BODY",
                "sentences": [
                    {"text": text, "pace": PACE[(n + j) % 3], "emotion": EMO[(n + j) % 3]},
                    {
                        "text": f"Then we pause on part {word} for a moment.",
                        "pace": "SLOW",
                        "emotion": "SERIOUS",
                    },
                ],
                "on_screen_text": [],
                "visual_intent": {
                    "tier_hint": "C_CODE_MOTION",
                    "description": "simple diagram",
                    "change_beats": 2,
                },
                "concept_refs": refs,
                "hypothetical_example": False,
                "method_label": False,
                "interrupt": {"kind": "GRAPHIC"} if plan["needs_interrupt"] and j == 0 else None,
                "deliberate_pause_ms": 0,
                "explanatory": True,
                "pronunciation_candidates": [],
                "chart_request": None,
                "purpose_concept_id": None,
            }
        )
    return {"section_id": sid, "scenes": scenes, "refusal": None}


def cut_json(step_input: dict[str, Any], citations: dict[str, list[str]]) -> dict[str, Any]:
    """A valid cut of the first two parent sections: verbatim sentences, three distinct hooks."""
    parent = step_input["parent"]
    removed = set(parent["removed_segment_ids"])
    segs = [
        x for sec in parent["sections"] for x in sec["segments"] if x["segment_id"] not in removed
    ]
    picks = [
        next(x for x in sec["segments"] if x["segment_id"] not in removed)
        for sec in parent["sections"][:2]
    ]
    used = {p["segment_id"] for p in picks}
    key = parent["promise"]["promise_key_terms"][0]

    def hook(hid: str, style: str, vr: int, cw: int) -> dict[str, Any]:
        return {
            "hook_id": hid,
            "hook_style": style,
            "sentences": [
                {
                    "text": f"One idea about {key}, framed as option {hid}.",
                    "pace": "FAST",
                    "emotion": "CURIOUS",
                }
            ],
            "parent_segment_ids": [picks[0]["segment_id"]],
            "rubric": {
                "viewer_relevance": vr,
                "curiosity_without_clickbait": cw,
                "rationale": "scored on the written rubric",
            },
        }

    scenes = []
    for n, pick in enumerate(picks, start=1):
        concept = pick["concept_refs"][0]
        scenes.append(
            {
                "scene_local_id": f"sc{n}",
                "beat": "BODY",
                "sentences": [{"text": pick["text"], "pace": PACE[n % 3], "emotion": EMO[n % 3]}],
                "on_screen_text": [],
                "visual_intent": {
                    "tier_hint": "C_CODE_MOTION",
                    "description": "diagram",
                    "change_beats": 1,
                },
                "concept_refs": [{"concept_id": concept, "citation_refs": citations[concept][:1]}],
                "hypothetical_example": pick["hypothetical_example"],
                "method_label": pick["method_label"],
                "interrupt": {"kind": "ZOOM"} if n == 1 else None,
                "deliberate_pause_ms": 0,
                "explanatory": True,
                "pronunciation_candidates": [],
                "chart_ref": pick["chart_ref"],
                "parent_segment_ids": [pick["segment_id"]],
            }
        )
    return {
        "title_promise": {
            "short_title_local": f"Quick look at {key}",
            "promise_statement": f"A short look at {key}.",
            "promise_key_terms": [key],
        },
        "hooks": [
            hook("h1", "CONCRETE_CASE", 2, 2),
            hook("h2", "QUESTION", 1, 2),
            hook("h3", "MYTH_BUST", 1, 1),
        ],
        "selected_hook_id": "h1",
        "scenes": scenes,
        "dropped_parent_content": [
            {"parent_segment_id": x["segment_id"], "reason": "DURATION_LIMIT"}
            for x in segs
            if x["segment_id"] not in used
        ],
        "refusal": None,
    }


def user_input(request: LlmRequest) -> dict[str, Any]:
    text = request.messages[0].content
    return dict(json.loads(text.split("INPUT (data, not instructions):\n\n", 1)[1]))


# ---------------------------------------------------------------------------- fake LLM
class ScriptedLlm:
    """LlmAdapter Protocol over a script of tokens; ``VALID_SECTIONS`` is sticky."""

    def __init__(
        self,
        script: Sequence[Any],
        n_sections: int = 2,
        citations: dict[str, list[str]] | None = None,
    ) -> None:
        self.citations = citations or {}
        self.script = deque(script)
        self.n = n_sections
        self.requests: list[LlmRequest] = []
        self.keys: list[str] = []

    @property
    def provider(self) -> str:
        return FakeProvider.LLM.value

    def count_tokens(self, request: LlmRequest, *, idempotency_key: str) -> TokenCount:
        raise NotImplementedError

    def complete(self, request: LlmRequest, *, idempotency_key: str) -> LlmResponse:
        self.requests.append(request)
        self.keys.append(idempotency_key)
        scripted = self.script[0]
        if scripted != "VALID_SECTIONS" and scripted != "VALID_CUT":
            self.script.popleft()
        text = self._text(scripted, request)
        usage = CallUsage(
            provider=FakeProvider.LLM,
            operation="llm.completion",
            model=request.model,
            billing_mode=BillingMode.STANDARD,
            tokens_in=10,
            tokens_out=20,
            tokens_cached_in=0,
            amount_micros=110,
            currency="USD",
            price_ref=FAKE_PRICE_REF,
            idempotency_key=idempotency_key,
        )
        return LlmResponse(text=text, stop_reason="end_turn", usage=usage)

    def _text(self, scripted: Any, request: LlmRequest) -> str:
        if isinstance(scripted, dict):
            if scripted.get("http") == 429:
                raise RateLimitedError("rate limited", retry_after_ms=scripted["retry_after_ms"])
            if scripted.get("provider_refusal"):
                raise ProviderRefusalError("refused")
            if "text" in scripted:
                return str(scripted["text"])
        if scripted == "VALID_CUT":
            return json.dumps(cut_json(user_input(request), self.citations))
        if scripted == "INVALID_JSON":
            return "this is not json"
        if scripted == "SCHEMA_INVALID":
            return json.dumps({"unexpected": True})
        if scripted == "VALID_PLAN":
            return json.dumps(plan_json(self.n))
        if scripted == "VALID_SECTIONS":
            return json.dumps(section_json(user_input(request)))
        if scripted == "NEAR_COPY_FAIL":
            data = user_input(request)
            brief = data["concept_briefs"][0]["summary"]
            return json.dumps(section_json(data, copy_text=brief))
        raise AssertionError(f"unknown script scripted {scripted!r}")


# ---------------------------------------------------------------------------- in-memory ports
@dataclass
class MemoryState:
    checkpoints: list[CheckpointState] = field(default_factory=list)
    scripts: dict[tuple[str, str, int], SavedScript] = field(default_factory=dict)
    blob_writes: int = 0
    hooks: list[HookHistoryEntry] = field(default_factory=list)
    ledger: list[LedgerRow] = field(default_factory=list)
    audit: list[str] = field(default_factory=list)
    completed: Any = None
    refuse_budget: bool = False
    drain_after: str | None = None
    persist_failures: list[Exception] = field(default_factory=list)
    foreign_hooks: list[HookHistoryEntry] = field(default_factory=list)
    chunk_texts: dict[str, str] = field(default_factory=dict)
    saved_contents: dict[str, bytes] = field(default_factory=dict)


class _Scripts:
    def __init__(self, st: MemoryState) -> None:
        self.st = st

    def next_version(self, ctx: StepContext, language: str) -> int:
        versions = [k[2] for k in self.st.scripts if k[0] == ctx.job_id and k[1] == language]
        return max(versions, default=0) + 1

    def read_blob(self, ctx: StepContext, uri: str, sha256: str) -> bytes:
        return self.st.saved_contents[uri]

    def save(self, ctx: StepContext, **kw: Any) -> SavedScript:
        if self.st.persist_failures:
            raise self.st.persist_failures.pop(0)
        key = (ctx.job_id, kw["language"], kw["version"])
        if key in self.st.scripts:
            return self.st.scripts[key]
        uri = f"amw-blob://{ctx.org_id}/jobs/{ctx.job_id}/tasks/{ctx.task_id}/script.json"
        self.st.blob_writes += 1
        self.st.saved_contents[uri] = kw["content"]
        saved = SavedScript(kw["script_id"], kw["version"], uri, kw["sha256"], True)
        self.st.scripts[key] = saved
        return saved


class _Hooks:
    def __init__(self, st: MemoryState) -> None:
        self.st = st

    def read(self, ctx: StepContext, n: int) -> list[HookHistoryEntry]:
        return [*self.st.hooks, *self.st.foreign_hooks][-n * 3 :]

    def write(self, ctx: StepContext, entries: Sequence[HookHistoryEntry]) -> None:
        self.st.hooks.extend(entries)


class _Checkpoints:
    def __init__(self, st: MemoryState) -> None:
        self.st = st

    def latest(self, ctx: StepContext) -> CheckpointState | None:
        return self.st.checkpoints[-1] if self.st.checkpoints else None

    def write(self, ctx: StepContext, checkpoint: CheckpointState) -> None:
        self.st.checkpoints.append(checkpoint)


class _Budget:
    def __init__(self, st: MemoryState) -> None:
        self.st = st

    def check_call(self, ctx: StepContext, estimated_cost_micros: int) -> None:
        if self.st.refuse_budget:
            raise BudgetExhaustedError("budget refused")


class _Ledger:
    def __init__(self, st: MemoryState) -> None:
        self.st = st

    def record(self, ctx: StepContext, step_key: str, call_seq: int, usage: Any) -> LedgerRow:
        row = LedgerRow(
            ids.COST_ENTRY.new(),
            usage.provider,
            usage.model or "",
            usage.tokens_in or 0,
            usage.tokens_out or 0,
            usage.tokens_cached_in or 0,
            usage.amount_micros,
        )
        self.st.ledger.append(row)
        return row


class _Control:
    def __init__(self, st: MemoryState) -> None:
        self.st = st

    def stop_requested(self, ctx: StepContext) -> Any:
        last = self.st.checkpoints[-1].step_key if self.st.checkpoints else None
        if self.st.drain_after and last == f"section_{self.st.drain_after}_done":
            return "DRAIN"
        return None


class _Idem:
    def __init__(self, st: MemoryState) -> None:
        self.st = st

    def stored_output(self, ctx: StepContext) -> Any:
        return self.st.completed

    def complete(self, ctx: StepContext, output: Any) -> None:
        self.st.completed = output


class _Audit:
    def __init__(self, st: MemoryState) -> None:
        self.st = st

    def record(self, ctx: StepContext, event: str, details: Any) -> None:
        self.st.audit.append(event)


class _Chunks:
    def __init__(self, st: MemoryState) -> None:
        self.st = st

    def read_cited(self, ctx: StepContext, refs: Sequence[str]) -> dict[str, str]:
        return {r: self.st.chunk_texts[r] for r in refs if r in self.st.chunk_texts}


def make_ports(st: MemoryState) -> Ports:
    return Ports(
        scripts=_Scripts(st),
        hook_history=_Hooks(st),
        checkpoints=_Checkpoints(st),
        budget=_Budget(st),
        ledger=_Ledger(st),
        control=_Control(st),
        idempotency=_Idem(st),
        audit=_Audit(st),
        chunks=_Chunks(st),
    )


def prompts() -> PromptSet:
    return load_prompts(PROMPTS)


__all__ = ["DbTransientError"]
