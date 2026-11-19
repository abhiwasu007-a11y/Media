"""``s05_script`` -> ``agent_05.script_draft`` (and ``s05_shorts`` -> shorts adaptation).

The scripted LLM writes placeholder Marathi sentences (Devanagari, with ``(PLUMBING)`` and the
English term in brackets) built from the step input, so the deterministic checks of Agent 05
(language, near-copy, hook rubric, budgets) run on real input.
"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from agent_05_scriptwriter import ScriptDraftRequest, ScriptDraftStep
from agent_05_scriptwriter.assemble.parts import DisclaimerTemplate
from agent_05_scriptwriter.contracts import ScriptDraftInput, ShortsAdaptationInput
from agent_05_scriptwriter.pre.brief_mapper import ResearchPackView
from agent_05_scriptwriter.pre.tenant_guard import RefFact, TenantFacts
from agent_05_scriptwriter.protocols import RulePack, SavedScript, StepContext
from agent_05_scriptwriter.steps.common import ResolvedInputs
from agent_05_scriptwriter.task_output import build_task_output
from amw_adapters.llm import LlmRequest
from amw_core import ids
from amw_core.contracts import TaskOutput
from amw_orchestrator.executor import StageCall
from amw_orchestrator.metering import MeteredLlm
from tests.agents.agent_05_scriptwriter import support as sp
from tests.dryrun.base import World, upstream
from tests.dryrun.kit import PLUMBING, ref_ending
from tests.dryrun.llm import ScriptedLlm
from tests.dryrun.runtime_iface import get_disclaimer

PACE = ["NORMAL", "SLOW", "NORMAL"]
EMO = ["NEUTRAL", "CURIOUS", "SERIOUS"]
WORDS = ["पहिला", "दुसरा", "तिसरा", "चौथा", "पाचवा", "सहावा"]
KEY = "डायव्हर्जन्स"
ALLOW_LATIN = ["PLUMBING", "TEST", "RSI", "NOT", "QUALITY"]


def _s(text: str, i: int = 0) -> dict[str, Any]:
    return {"text": text, "pace": PACE[i % 3], "emotion": EMO[i % 3]}


def plan_json(data: dict[str, Any]) -> dict[str, Any]:
    briefs = data["concept_briefs"]
    n = max(2, min(3, len(briefs)))
    shares = [1000 // n] * n
    shares[-1] += 1000 - sum(shares)
    concept_ids = [b["concept_id"] for b in briefs]
    start, mid = 0, 0
    for i, share in enumerate(shares):
        if start <= 500 < start + share:
            mid = i
        start += share

    def hook(hid: str, style: str, vr: int, cw: int) -> dict[str, Any]:
        opt = WORDS[int(hid[1:]) - 1]
        beats = [
            ("HOOK_PROOF", f"हा (PLUMBING) नमुना आहे: एका जुन्या आलेखावर {KEY} दिसला, पर्याय {opt}."),
            ("HOOK_WHY", f"शिकणाऱ्यासाठी हे का महत्त्वाचे आहे, पर्याय {opt}?"),
            ("HOOK_COVERS", f"या भागात आपण आलेख कसा वाचायचा ते पाहू, पर्याय {opt}."),
        ]
        return {
            "hook_id": hid,
            "hook_style": style,
            "beats": [
                {
                    "beat": name,
                    "sentences": [_s(text)],
                    "concrete_example": "एक जुना आलेख" if name == "HOOK_PROOF" else None,
                    "chart_request": None,
                    "concept_refs": [],
                }
                for name, text in beats
            ],
            "rubric": {
                "viewer_relevance": vr,
                "curiosity_without_clickbait": cw,
                "rationale": "PLUMBING placeholder rubric",
            },
        }

    sections = [
        {
            "section_id": f"sec{i + 1}",
            "section_kind": "RECAP" if i == n - 1 else "CONCEPT",
            "heading_local": f"भाग {WORDS[i]}: {KEY}",
            "heading_en": f"Part {i + 1}",
            "purpose": f"PLUMBING placeholder part {i + 1}.",
            "concept_ids": [concept_ids[min(i, len(concept_ids) - 1)]],
            "share_permille": shares[i],
            "needs_interrupt": i in (0, mid),
        }
        for i in range(n)
    ]
    concept_plan = [
        {
            "concept_id": b["concept_id"],
            "taught_in_section_ids": [f"sec{min(j, n - 1) + 1}"],
            "own_words_angle": "PLUMBING placeholder",
            "original_example_idea": "PLUMBING invented example",
            "citation_refs": b["citation_refs"][:2],
        }
        for j, b in enumerate(briefs)
        if b["citation_refs"]
    ]
    return {
        "title_promise": {
            "working_title_local": f"{KEY} म्हणजे काय (PLUMBING TEST)",
            "promise_statement": f"या भागात {KEY} म्हणजे काय ते समजेल.",
            "promise_key_terms": [KEY],
        },
        "hooks": [hook("h1", "CONCRETE_CASE", 2, 2), hook("h2", "QUESTION", 1, 2),
                  hook("h3", "MYTH_BUST", 2, 1)],
        "selected_hook_id": "h1",
        "sections": sections,
        "concept_plan": concept_plan,
        "omitted_concepts": [],
        "description_draft": f"{KEY} (PLUMBING TEST - NOT QUALITY) हे केवळ नमुना वर्णन आहे.",
        "thumbnail_brief": {
            "subject_idea": "PLUMBING simple chart sketch",
            "text_idea_local": f"{KEY}?",
            "must_not_promise": ["profit"],
        },
        "refusal": None,
    }


def section_json(data: dict[str, Any]) -> dict[str, Any]:
    plan = data["section_plan"]
    sid = plan["section_id"]
    n = int(sid[3:])
    concept = plan["concept_ids"][0]
    brief = next(b for b in data["concept_briefs"] if b["concept_id"] == concept)
    refs = [{"concept_id": concept, "citation_refs": brief["citation_refs"][:1]}]
    word = WORDS[(n - 1) % len(WORDS)]
    scenes = []
    for j in range(2):
        scenes.append(
            {
                "scene_local_id": f"sc{j + 1}",
                "beat": "RECAP" if plan["section_kind"] == "RECAP" else "BODY",
                "sentences": [
                    _s(f"हा {word} भाग आहे (PLUMBING TEST), दृश्य {WORDS[j]} कल्पना सोपी ठेवते.", n + j),
                    _s(f"आता आपण {word} भागावर थोडा वेळ थांबतो.", n + j + 1),
                ],
                "on_screen_text": [],
                "visual_intent": {
                    "tier_hint": "C_CODE_MOTION",
                    "description": "PLUMBING simple diagram",
                    "change_beats": 2,
                },
                "concept_refs": refs if brief["citation_refs"] else [],
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


def responder(request: LlmRequest) -> str:
    data = sp.user_input(request)
    if "section_plan" in data:
        return json.dumps(section_json(data), ensure_ascii=False)
    if "parent" in data:
        return json.dumps(sp.cut_json(data, _CITATIONS), ensure_ascii=False)
    return json.dumps(plan_json(data), ensure_ascii=False)


_CITATIONS: dict[str, list[str]] = {}


class _Scripts:
    """ScriptStore over the shared blob store (write-once, hash-checked reads)."""

    def __init__(self, world: World) -> None:
        self.w = world
        self.versions: dict[tuple[str, str], int] = {}

    def next_version(self, ctx: StepContext, language: str) -> int:
        return self.versions.get((ctx.job_id, language), 0) + 1

    def read_blob(self, ctx: StepContext, uri: str, sha256: str) -> bytes:
        return self.w.blobs.read(uri, sha256)

    def save(self, ctx: StepContext, **kw: Any) -> SavedScript:
        path = f"{ctx.job_id}/tasks/{ctx.task_id}/script_v{kw['version']}.json"
        uri, sha = self.w.blobs.put_bytes("jobs", path, kw["content"])
        self.versions[(ctx.job_id, kw["language"])] = kw["version"]
        return SavedScript(kw["script_id"], kw["version"], uri, sha, True)


def rule_packs() -> dict[str, RulePack]:
    return {
        "rp.youtube_general": RulePack("rp.youtube_general", "v1", "PLUMBING YT", "PLATFORM"),
        "rp.finance_sebi_in": RulePack("rp.finance_sebi_in", "v1", "PLUMBING FIN", "PLATFORM"),
    }


def tenant_facts(ctx: StepContext) -> TenantFacts:
    return TenantFacts(
        envelope_org=ctx.org_id,
        input_org=ctx.org_id,
        db_org=ctx.org_id,
        channel_org=ctx.org_id,
        tenant_status="ACTIVE",
        refs=[RefFact("PRIOR_OUTPUT", ctx.org_id, ctx.channel_id, True)],
        task_channel=ctx.channel_id,
    )


def disclaimer() -> DisclaimerTemplate:
    d = get_disclaimer("v0")
    return DisclaimerTemplate("amw-blob://platform/tpl/disclaimer.json", d.version, d.text)


class ScriptExecutor:
    def __init__(self, world: World, chunk_text: dict[str, str]) -> None:
        self.w = world
        self.state = sp.MemoryState(chunk_texts=chunk_text)
        self.scripts = _Scripts(world)

    def ctx(self, call: StageCall) -> StepContext:
        job = call.job
        return StepContext(
            org_id=job.org_id,
            job_id=job.job_id,
            task_id=call.task_id,
            attempt_id=call.attempt_id,
            channel_id=job.channel_id,
            project_id=job.project_id,
            correlation_id=job.correlation_id,
            max_llm_calls=call.resource_budget.max_llm_calls or 30,
            max_cost_micros=call.resource_budget.max_cost_micros,
        )

    def step(self) -> ScriptDraftStep:
        ports = sp.make_ports(self.state)
        ports.scripts = self.scripts
        llm = MeteredLlm(ScriptedLlm(responder), self.w.meter, 2_000)
        return ScriptDraftStep(llm, ports, sp.make_settings(), sp.prompts(), sp.scanners_for)

    def execute(self, call: StageCall) -> TaskOutput:
        self.state.completed = None  # each task id is a new task (idempotency per task)
        self.state.checkpoints = []
        ctx = self.ctx(call)
        pack_out = upstream(call, "s04_research")
        assert pack_out.payload is not None
        pack = ResearchPackView.model_validate(pack_out.payload.data)
        prior = self._prior(call)
        topic = call.job.owner_topic
        data: dict[str, Any] = {
            "topic": {
                "title": topic.title,
                "angle": topic.angle,
                "target_duration_ms": topic.target_duration_ms,
            },
            "video_kind": topic.video_kind.value,
            "language": topic.language,
            "channel_category": "finance",
            "owner_sebi_registration": "UNREGISTERED",
            "active_rule_packs": ["rp.youtube_general", "rp.finance_sebi_in"],
            "course_chapter_pointer": None,
            "iteration": call.iteration,
            "revision": revision_block(call, prior) if call.iteration else None,
        }
        resolved = ResolvedInputs(
            tenant=tenant_facts(ctx),
            rule_packs=rule_packs(),
            profile_rule_packs=["rp.youtube_general", "rp.finance_sebi_in"],
            lexicons=sp.LEX_TEST_V1,
            new_script_id=ids.new_id(ids.Prefix.SCRIPT),
            pack=pack,
            brand_latin_allow_list=ALLOW_LATIN,
            disclaimer_template=disclaimer(),
        )
        if prior is not None:
            resolved.prior_script, resolved.prior_script_sha256 = prior
        req = ScriptDraftRequest(ctx, ScriptDraftInput.model_validate(data), resolved)
        outcome = self.step().run(req)
        return build_task_output(
            outcome, ctx, now=datetime.now(UTC), duration_ms=1, attempt_no=call.attempt_no
        )

    def _prior(self, call: StageCall) -> Any:
        if call.prior_output is None:
            return None
        from agent_05_scriptwriter.contracts import ScriptDocument

        ref = ref_ending(call.prior_output, ".json")
        raw = self.w.blobs.read(ref.uri, ref.sha256)
        return ScriptDocument.model_validate_json(raw), ref.sha256


def revision_block(call: StageCall, prior: Any) -> dict[str, Any]:
    """24 section 3.3 rule 7: feedback items from the failing gate results (<= 60)."""
    items: list[dict[str, Any]] = []
    for r in call.revision_feedback[:60]:
        items.append(
            {
                "source": _source(call.revision_source_stage_id),
                "segment_ref": None,
                "rule_ids": [r.rule_id] if r.rule_id else [],
                "instruction": r.message[:500],
                "suggested_citation_refs": [],
            }
        )
    return {
        "prior_script_ref": ref_ending(call.prior_output, ".json").uri  # type: ignore[arg-type]
        if call.prior_output is not None
        else None,
        "feedback": items,
    }


def _source(stage_id: str | None) -> str:
    return {
        "s06_claims": "CLAIM_EXTRACTION",
        "s06_verify": "CLAIM_VERIFICATION",
        "s06_chart": "CLAIM_VERIFICATION",
        "s02u_unique": "UNIQUENESS",
        "s16_comp": "COMPLIANCE",
        "s16_score": "QUALITY_SCORE",
    }.get(stage_id or "", "APPROVER")


def _unused(_: Sequence[Any] | ShortsAdaptationInput) -> None:
    return None
