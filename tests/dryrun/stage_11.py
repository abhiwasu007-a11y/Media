"""``s11_thumbs`` -> ``agent_11.thumbnail_variants`` (real Pillow + Raqm composition).

Agent 11 reads the script promise, brand kit and shot plan through its own repository port
(no reader of the upstream documents): the dry run fills the agent's in-memory repository
from the stored Agent 05 document (integration finding, WS-02). The scripted model is the
agent's own deterministic planner answering in the model's JSON format (PLUMBING).
"""

import hashlib
from typing import Any

from agent_11_thumbnail_design.composer import PillowComposer
from agent_11_thumbnail_design.models import Brief, Promise
from agent_11_thumbnail_design.ports import BrandKitView, FontRef, RegisteredAsset, ScriptView
from agent_11_thumbnail_design.prompting import PromptBundle
from agent_11_thumbnail_design.stage import Lexicons, RulePacks, StageDeps, ThumbnailStage
from agent_11_thumbnail_design.templates import load_templates
from amw_core.contracts import TaskOutput
from amw_core.testing.memory import MemoryCheckpointStore, MemoryIdempotencyStore
from amw_orchestrator.executor import StageCall
from amw_orchestrator.metering import MeteredLlm
from tests.agents.agent_11_thumbnail_design import fakes as f11
from tests.agents.agent_11_thumbnail_design.env import FIN_MARKERS, PROMPT_PATH, PlannerLlm
from tests.agents.agent_11_thumbnail_design.support import INJECTION_MARKERS
from tests.dryrun.base import World, task_input, upstream, upstream_data
from tests.dryrun.kit import ref_ending
from tests.dryrun.stage_08 import BRAND_FONT


class ThumbsExecutor:
    def __init__(self, world: World) -> None:
        self.w = world
        self._font: tuple[str, str] | None = None

    def execute(self, call: StageCall) -> TaskOutput:
        org = call.job.org_id
        sref = ref_ending(upstream(call, "s05_script"), ".json")
        doc = self.w.blobs.read_json(sref.uri, sref.sha256)
        verify = upstream_data(call, "s06_verify")
        if self._font is None:
            self._font = self.w.blobs.put_bytes("assets", "fonts/brand_freesans.ttf", BRAND_FONT.read_bytes())
        font_uri, font_sha = self._font
        promise = doc["promise"]
        brief = doc["thumbnail_brief"]
        script = ScriptView(
            doc["script_id"],
            sref.sha256,
            verify["script_sha256"],
            verify["overall"]["verification_verdict"],
            0,
            Promise(
                promise_statement=promise["promise_statement"],
                promise_key_terms=tuple(promise["promise_key_terms"]),
                working_title_local=promise["working_title_local"],
            ),
            Brief(
                subject_idea=brief["subject_idea"],
                text_idea_local=brief["text_idea_local"],
                must_not_promise=tuple(brief["must_not_promise"]),
            ),
        )
        font = FontRef("ast_brandfont", font_uri, font_sha, ("Latin", "Devanagari"))
        repo = f11.FakeRepo(script, "finance", BrandKitView({}, (font,), ()), font)
        for t in load_templates():
            repo.registered[("TEMPLATE", t.template_key)] = RegisteredAsset(
                f"ast_{t.template_key}", "TEMPLATE", t.template_key, "ACTIVE", True, "CODE_GENERATED"
            )
        repo.registered[("TEMPLATE", "glyphset")] = RegisteredAsset(
            "ast_glyphset", "TEMPLATE", "glyphset", "ACTIVE", True, "CODE_GENERATED"
        )
        repo.registered[("FONT", "ast_brandfont")] = RegisteredAsset(
            "ast_brandfont", "FONT", "ast_brandfont", "ACTIVE", True, "FONT"
        )
        prompt_text = PROMPT_PATH.read_text(encoding="utf-8")
        deps = StageDeps(
            settings=f11.settings(),
            tenancy=f11.FakeTenancy(),
            repo=repo,
            storage=self.w.blobs.storage,
            llm=MeteredLlm(PlannerLlm(finance=True), self.w.meter, 2_000),
            budget=f11.FakeBudget(grant=True),
            costs=f11.FakeCosts(),
            audit=f11.FakeAudit(),
            idem=MemoryIdempotencyStore(),
            checkpoints=MemoryCheckpointStore(),
            composer=PillowComposer(),
            clock=self.w.clock,
            prompt=PromptBundle(
                "agent_11/thumbnail_concepts.v1",
                prompt_text,
                hashlib.sha256(prompt_text.encode()).hexdigest(),
            ),
            lexicons=Lexicons(
                FIN_MARKERS, tuple(INJECTION_MARKERS), ("ignore all rules",), frozenset({"the"})
            ),
            packs=RulePacks(
                {"rp.youtube_general": "PLUMBING YT", "rp.finance_sebi_in": "PLUMBING FIN"},
                "PLUMBING TENANT PACK",
            ),
            templates=load_templates(),
        )
        plan_ref = upstream_data(call, "s09_plan")["plan_ref"]
        vref = ref_ending(upstream(call, "s06_verify"), "claim_verification_output.json")
        kit_uri, kit_sha = self.w.blobs.put_json("assets", "brand_kit/plumbing.json", {"kit": "PLUMBING"})
        payload: dict[str, Any] = {
            "production_type_key": "CHANNEL_LONG_FORM",
            "language": call.job.language,
            "variant_count": 3,
            "aspect_ratio": "16:9",
            "iteration": call.iteration,
            "script_ref": {"uri": sref.uri, "sha256": sref.sha256},
            "verification_ref": {"uri": vref.uri, "sha256": vref.sha256},
            "shot_plan_ref": {"uri": plan_ref["uri"], "sha256": plan_ref["sha256"]},
            "brand_kit_ref": {"uri": kit_uri, "sha256": kit_sha},
            "previous_set_ref": None,
            "revision_feedback": [],
        }
        ti = task_input(call, "agent_11", "agent_11.thumbnail_variants.input", payload)
        _ = org
        return ThumbnailStage(deps).run(ti, call.attempt_id)
