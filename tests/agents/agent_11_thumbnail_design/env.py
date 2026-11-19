"""Builds a complete stage environment around the fakes."""

import hashlib
import io
import json
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from agent_11_thumbnail_design.composer import PillowComposer
from agent_11_thumbnail_design.fallback import FallbackPlanner, PlannerPolicy
from agent_11_thumbnail_design.models import Brief, Promise, StepIn, SubjectHint
from agent_11_thumbnail_design.payload import Ref
from agent_11_thumbnail_design.ports import (
    BrandKitView,
    FontRef,
    OwnerAsset,
    RegisteredAsset,
    ScriptView,
)
from agent_11_thumbnail_design.prompting import PromptBundle
from agent_11_thumbnail_design.stage import Lexicons, RulePacks, StageDeps, ThumbnailStage
from agent_11_thumbnail_design.templates import glyph_catalogue, load_templates
from amw_core.contracts.task_input import TaskInput
from amw_core.ids import Prefix, new_id
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.testing.memory import MemoryCheckpointStore, MemoryIdempotencyStore
from tests.agents.agent_11_thumbnail_design.baseline import plan_with_keep
from tests.agents.agent_11_thumbnail_design.fakes import (
    FakeAudit,
    FakeBudget,
    FakeClock,
    FakeCosts,
    FakeRepo,
    FakeStorage,
    FakeTenancy,
    ScriptedLlm,
    asset_facts,
    promise_en,
    settings,
)
from tests.agents.agent_11_thumbnail_design.fontgen import build_font
from tests.agents.agent_11_thumbnail_design.support import FIN_LEXICON, INJECTION_MARKERS, ROOT

PROMPT_PATH = ROOT / "docs/v4/prompts/agent_11_thumbnail_design/thumbnail_concepts.v1.md"
FIN_MARKERS = ("buy", "sell", "hold", "target", "profit", "return", "guaranteed")


class PlannerLlm:
    """A stand-in model: answers with the deterministic planner's concepts (recorded-response)."""

    provider = "fake"

    def __init__(self, inner: ScriptedLlm | None = None, *, finance: bool = False) -> None:
        self.finance = finance
        self.requests: list[Any] = []
        self.calls = 0

    def complete(self, request: Any, *, idempotency_key: str) -> Any:
        from amw_adapters.common import CallUsage
        from amw_adapters.llm.protocol import LlmResponse
        from amw_core.enums import BillingMode, CostOperation

        self.requests.append(request)
        self.calls += 1
        body = request.messages[0].content
        doc = json.loads(body.split("<<<INPUT\n", 1)[1].split("\nINPUT>>>", 1)[0])
        step = StepIn.model_validate(doc)
        planner = FallbackPlanner(
            PlannerPolicy(finance=self.finance, faces_allowed=False, fin_lexicon=FIN_MARKERS)
        )
        concepts = [json.loads(c.model_dump_json()) for c in plan_with_keep(step, planner)]
        text = json.dumps({"call_seq": step.call_seq, "concepts": concepts, "refusal": None})
        usage = CallUsage(
            provider="fake",
            operation=CostOperation.LLM_COMPLETION,
            model=request.model,
            billing_mode=BillingMode.STANDARD,
            tokens_in=100,
            tokens_out=50,
            tokens_cached_in=0,
            tokens_cache_write_in=0,
            chars_in=10,
            language=request.language,
            amount_micros=350,
            currency="USD",
            price_ref="fake-price",
            idempotency_key=idempotency_key,
        )
        return LlmResponse(text=text, stop_reason="end_turn", usage=usage)

    def count_tokens(self, request: Any, *, idempotency_key: str) -> Any:
        raise NotImplementedError


def png_bytes(
    color: tuple[int, int, int] = (200, 40, 40), size: tuple[int, int] = (1920, 1080)
) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "PNG")
    return out.getvalue()


@dataclass
class Env:
    stage: ThumbnailStage
    ti: TaskInput
    repo: FakeRepo
    storage: FakeStorage
    llm: Any
    budget: FakeBudget
    costs: FakeCosts
    audit: FakeAudit
    idem: MemoryIdempotencyStore
    tenancy: FakeTenancy
    org: str
    font_bytes: bytes
    deps: StageDeps = field(init=False)

    def __post_init__(self) -> None:
        self.deps = self.stage.d


def make_env(
    *,
    finance: bool = False,
    llm: Any = None,
    language: str = "en-IN",
    variant_count: int = 3,
    promise: tuple[Promise, Brief] | None = None,
    owner_assets: int = 0,
    llm_enabled: bool = True,
    grant: bool = True,
    iteration: int = 0,
    previous: dict[str, Any] | None = None,
    feedback: list[dict[str, Any]] | None = None,
    fallback_flag: bool = False,
    kit: bool = True,
    font: bytes | None = None,
    **cfg: Any,
) -> Env:
    org = str(new_id(Prefix.ORGANISATION))
    storage = FakeStorage()
    tc = TenantContext(org_id=org, actor="agent_11")  # type: ignore[arg-type]
    font_bytes = font if font is not None else build_font()
    font_sha = hashlib.sha256(font_bytes).hexdigest()
    font_uri = str(storage.blob_uri(tc, "fonts", "test.ttf"))
    storage.blobs[font_uri] = font_bytes
    p, b = promise or promise_en()
    script = ScriptView("scr_1", "a" * 64, "a" * 64, "ALLOWED", 0, p, b)
    font_ref = FontRef("ast_font", font_uri, font_sha, ("Latin", "Devanagari"))
    kit_view = BrandKitView({}, (font_ref,), ()) if kit else None
    assets: list[OwnerAsset] = []
    ctx_refs: list[dict[str, Any]] = []
    for i in range(owner_assets):
        data = png_bytes((30 + i * 40, 90, 160))
        sha = hashlib.sha256(data).hexdigest()
        uri = str(storage.blob_uri(tc, "assets", f"img{i}.png"))
        storage.blobs[uri] = data
        assets.append(OwnerAsset(f"ast_img{i}", asset_facts(sha), uri, sha, "IMAGE"))
        ctx_refs.append({"uri": uri, "purpose": "ASSET"})
    repo = FakeRepo(
        script,
        "finance" if finance else "education",
        kit_view,
        font_ref,
        assets=assets,
        previous=previous,
    )
    for t in load_templates():
        repo.registered[("TEMPLATE", t.template_key)] = RegisteredAsset(
            f"ast_{t.template_key}", "TEMPLATE", t.template_key, "ACTIVE", True, "CODE_GENERATED"
        )
    repo.registered[("TEMPLATE", "glyphset")] = RegisteredAsset(
        "ast_glyphset", "TEMPLATE", "glyphset", "ACTIVE", True, "CODE_GENERATED"
    )
    repo.registered[("FONT", "ast_font")] = RegisteredAsset(
        "ast_font", "FONT", "ast_font", "ACTIVE", True, "FONT"
    )
    budget, costs, audit = FakeBudget(grant=grant), FakeCosts(), FakeAudit()
    idem, tenancy = MemoryIdempotencyStore(), FakeTenancy()
    llm_obj = llm or PlannerLlm(finance=finance)
    prompt_text = PROMPT_PATH.read_text(encoding="utf-8")
    deps = StageDeps(
        settings=settings(
            **{
                "agent_11__llm__enabled": llm_enabled,
                "agent_11__llm__fallback_on_unavailable": fallback_flag,
                **cfg,
            }
        ),
        tenancy=tenancy,
        repo=repo,
        storage=storage,
        llm=llm_obj,
        budget=budget,
        costs=costs,
        audit=audit,
        idem=idem,
        checkpoints=MemoryCheckpointStore(),
        composer=PillowComposer(),
        clock=FakeClock(),
        prompt=PromptBundle(
            "agent_11/thumbnail_concepts.v1",
            prompt_text,
            hashlib.sha256(prompt_text.encode()).hexdigest(),
        ),
        lexicons=Lexicons(
            FIN_MARKERS, tuple(INJECTION_MARKERS), ("ignore all rules",), frozenset({"the"})
        ),
        packs=RulePacks(
            {"rp.youtube_general": "PLATFORM-PACK", "rp.finance_sebi_in": "FIN-PACK"},
            "TENANT-CANARY-PACK",
        ),
        templates=load_templates(),
    )

    def ref(n: str) -> dict[str, str]:
        return {"uri": f"amw-blob://{org}/docs/{n}.json", "sha256": "b" * 64}

    payload = {
        "production_type_key": "CHANNEL_LONG_FORM",
        "language": language,
        "variant_count": variant_count,
        "aspect_ratio": "16:9",
        "iteration": iteration,
        "script_ref": {**ref("script"), "sha256": "a" * 64},
        "verification_ref": ref("verif"),
        "shot_plan_ref": ref("shots"),
        "brand_kit_ref": ref("kit"),
        "previous_set_ref": ref("prev") if previous else None,
        "revision_feedback": feedback or [],
    }
    ti = TaskInput.model_validate(
        {
            "org_id": org,
            "job_id": str(new_id(Prefix.JOB)),
            "task_id": str(new_id(Prefix.TASK)),
            "project_id": str(new_id(Prefix.PROJECT)),
            "channel_id": str(new_id(Prefix.CHANNEL)),
            "agent_id": "agent_11",
            "source_agent": "agent_01",
            "priority": "NORMAL",
            "deadline": None,
            "context_refs": ctx_refs,
            "resource_budget": {
                "max_cost_micros": 100000,
                "currency": "USD",
                "max_wall_ms": 600000,
                "max_llm_calls": 2,
            },
            "payload": {
                "payload_schema": "agent_11.thumbnail_variants.input",
                "payload_schema_version": "1.0.0",
                "data": payload,
            },
            "correlation_id": str(new_id(Prefix.CORRELATION)),
            "idempotency_key": "idk_" + "c" * 64,
            "retry_count": 0,
            "schema_version": "1.0.0",
        }
    )
    return Env(
        ThumbnailStage(deps),
        ti,
        repo,
        storage,
        llm_obj,
        budget,
        costs,
        audit,
        idem,
        tenancy,
        org,
        font_bytes,
    )


_ = (glyph_catalogue, Ref, SubjectHint, FIN_LEXICON)
