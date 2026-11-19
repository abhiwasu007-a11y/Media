"""3A production-type records (24 section 7.1a ``CHANNEL_LONG_FORM`` v2, 7.2a ``SHORTS`` v2).

The records are transcribed from the 24 tables (the single source; nothing added) and validated
by ``amw.production_type`` 1.0.0 (``ProductionType``: unique IDs, known dependencies, DAG,
REVISE targets are ancestors). The remaining load rules of 24 section 2 that need other data
(task types exist, approval workflows exist, revision ceiling of 07 section 9) are checked by
``validate_record``. Ticket WS-03 seeds them as ``production_types`` rows.

Where 24 says "as v1" for a field that v1 states only in prose (templates, cost model), the
record carries the v1 list items as keys. Shorts duration and aspect bounds stay ``SKIPPED``
(3A_SLICE_SPEC R11 / R13): ``duration_targets_ms`` is open (``min``/``max`` null).
"""

import hashlib
import json
from functools import cache
from typing import Any

from amw_core.contracts import ProductionType, Stage, default_disabled, materialise
from amw_core.enums import ProductionTypeKey

_TASK_TYPES = frozenset(
    {
        "agent_04.research_pack",
        "agent_05.script_draft",
        "agent_05.shorts_adaptation",
        "agent_06.claim_extraction",
        "agent_06.claim_verification",
        "svc_s07.request_approval",
        "agent_07.voice_synthesis",
        "agent_07.audio_master",
        "agent_09.shot_plan",
        "agent_08.asset_sourcing",
        "agent_10.render",
        "agent_10.subtitles",
        "agent_10.technical_qc",
        "agent_11.thumbnail_variants",
        "agent_12.metadata",
        "svc_s02.uniqueness_check",
        "agent_16.compliance_gate",
        "agent_16.quality_score",
        "agent_16.publication_authorisation",
        "agent_13.file_delivery",
    }
)
"""The 24 section 3.2 task types the 3A graphs use."""

MAX_REVISION_LOOPS_CEILING = 10
"""07 section 9 hard ceiling (the record value 3 must not exceed it)."""


def _stage(
    stage_id: str,
    task_type: str,
    rc: str,
    caps: list[str],
    deps: list[str],
    *,
    required: bool = True,
    enabled: bool | None = None,
    revise: tuple[str, list[str]] | None = None,
    stop: bool = False,
    approval: tuple[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gate: dict[str, Any] | None = None
    if revise is not None:
        on_fail: dict[str, Any] = {"action": "REVISE", "target_stage_id": revise[0]}
        if revise[1]:
            on_fail["alt_target_stage_ids"] = revise[1]
        gate = {"blocking": True, "on_fail": on_fail}
    elif stop:
        gate = {"blocking": True, "on_fail": {"action": "STOP"}}
    doc: dict[str, Any] = {
        "stage_id": stage_id,
        "task_type": task_type,
        "required": required,
        "resource_class": rc,
        "capabilities": caps,
        "depends_on": deps,
        "gate": gate,
        "approval": (
            {"approval_kind": approval[0], "workflow_key": approval[1]} if approval else None
        ),
    }
    if enabled is not None:
        doc["enabled_by_default"] = enabled
    if params is not None:
        doc["params"] = params
    return doc


def _common(key: str, stages: list[dict[str, Any]], **over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema_version": "1.0.0",
        "key": key,
        "version": 2,
        "display_name": key.replace("_", " ").title(),
        "status": "IN_DEVELOPMENT",
        "first_tier": "TIER_0",
        "destinations": ["FILE_DELIVERY"],
        "requires_channel": True,
        "parent_input": "NONE",
        "duration_targets_ms": {"min": None, "max": None},
        "aspect_ratios": ["16:9"],
        "languages": "SINGLE",
        "stages": stages,
        "required_inputs": [
            {
                "key": "owner_topic",
                "description": "The owner's topic, recorded by the operator tool (D5)",
                "input_schema": "amw.owner_topic",
                "provided_by": "OWNER",
            },
            {
                "key": "compliance_profile",
                "description": "Channel compliance profile",
                "input_schema": None,
                "provided_by": "SYSTEM",
            },
            {
                "key": "brand_kit",
                "description": "Minimal brand kit",
                "input_schema": None,
                "provided_by": "OWNER",
            },
            {
                "key": "knowledge_sources",
                "description": "Knowledge library sources of the channel",
                "input_schema": None,
                "provided_by": "OWNER",
            },
        ],
        "approvals": [
            {"approval_kind": "FINAL_VIDEO", "workflow_key": "owner_one_tap", "mandatory": True},
            {"approval_kind": "SCRIPT", "workflow_key": "owner_one_tap", "mandatory": False},
            {
                "approval_kind": "SENSITIVE_CLAIM",
                "workflow_key": "owner_sensitive",
                "mandatory": False,
            },
            {
                "approval_kind": "COPYRIGHT_DOUBT",
                "workflow_key": "owner_sensitive",
                "mandatory": False,
            },
        ],
        "templates": ["channel_lower_thirds", "chart_templates", "end_screen", "brand_sting"],
        "qc_profile": "qc.long_form",
        "rule_packs": {
            "mandatory": ["rp.youtube_general"],
            "by_category": {
                "finance": ["rp.finance_sebi_in"],
                "health": ["rp.health"],
                "kids": ["rp.kids"],
                "political_news": ["rp.political_news"],
            },
        },
        "deliverables": [
            "yt_master_1080p",
            "srt_per_language",
            "thumbnail_set",
            "qc_report",
            "cost_per_stage_report",
            "delivery_manifest",
        ],
        "cost_model": [
            {"component": c, "unit": u}
            for c, u in (
                ("llm", "tokens"),
                ("tts", "characters"),
                ("stock", "items"),
                ("ai_broll", "seconds"),
                ("music", "items"),
                ("render", "cpu_seconds"),
                ("storage", "bytes"),
                ("human_review", "minutes"),
            )
        ],
        "default_price": None,
        "limits": {"max_revision_loops": 3},
    }
    doc.update(over)
    return doc


def _long_form_stages() -> list[dict[str, Any]]:
    S = _stage  # noqa: N806
    return [
        S("s04_research", "agent_04.research_pack", "AI_IO", ["llm", "web_fetch"], [], stop=True),
        S("s05_script", "agent_05.script_draft", "AI_IO", ["llm"], ["s04_research"]),
        S(
            "s06_claims",
            "agent_06.claim_extraction",
            "AI_IO",
            ["llm"],
            ["s05_script"],
            revise=("s05_script", []),
        ),
        S(
            "s06_verify",
            "agent_06.claim_verification",
            "AI_IO",
            ["llm"],
            ["s06_claims"],
            revise=("s05_script", ["s04_research"]),
        ),
        S(
            "a_script",
            "svc_s07.request_approval",
            "LIGHT",
            [],
            ["s06_verify"],
            required=False,
            enabled=False,
            approval=("SCRIPT", "owner_one_tap"),
        ),
        S(
            "s07_voice",
            "agent_07.voice_synthesis",
            "AI_IO",
            ["tts", "media_probe"],
            ["s06_verify", "a_script"],
        ),
        S(
            "s07_master",
            "agent_07.audio_master",
            "HEAVY_CPU",
            ["render_ffmpeg", "media_probe"],
            ["s07_voice"],
            revise=("s07_voice", []),
        ),
        S("s09_plan", "agent_09.shot_plan", "AI_IO", ["llm"], ["s06_verify", "s07_voice"]),
        S(
            "s08_assets",
            "agent_08.asset_sourcing",
            "AI_IO",
            ["llm", "stock_search", "media_probe"],
            ["s09_plan"],
            revise=("s09_plan", ["s05_script"]),
        ),
        S(
            "s06_chart",
            "agent_06.claim_verification",
            "AI_IO",
            ["llm"],
            ["s08_assets"],
            revise=("s05_script", ["s08_assets"]),
            params={"verify_mode": "CHART_FACTS"},
        ),
        S(
            "s10_render",
            "agent_10.render",
            "HEAVY_CPU",
            ["render_ffmpeg"],
            ["s07_master", "s08_assets", "s06_chart"],
        ),
        S("s10_subs", "agent_10.subtitles", "HEAVY_CPU", ["render_ffmpeg"], ["s10_render"]),
        S(
            "s10_qc",
            "agent_10.technical_qc",
            "HEAVY_CPU",
            ["render_ffmpeg", "media_probe"],
            ["s10_subs"],
            revise=("s10_render", ["s07_voice", "s08_assets", "s09_plan"]),
        ),
        S(
            "s11_thumbs",
            "agent_11.thumbnail_variants",
            "AI_IO",
            ["llm"],
            ["s09_plan", "s08_assets"],
            revise=("s05_script", []),
        ),
        S(
            "s12_meta",
            "agent_12.metadata",
            "AI_IO",
            ["llm"],
            ["s06_verify"],
            required=False,
            enabled=False,
        ),
        S(
            "s02u_unique",
            "svc_s02.uniqueness_check",
            "AI_IO",
            ["media_probe"],
            ["s10_qc"],
            revise=("s05_script", []),
        ),
        S(
            "s16_comp",
            "agent_16.compliance_gate",
            "AI_IO",
            ["llm"],
            ["s02u_unique", "s11_thumbs", "s12_meta"],
            revise=("s05_script", ["s08_assets", "s11_thumbs"]),
        ),
        S(
            "s16_score",
            "agent_16.quality_score",
            "AI_IO",
            ["llm"],
            ["s16_comp"],
            revise=("s09_plan", ["s05_script", "s07_voice", "s10_render", "s11_thumbs"]),
        ),
        S(
            "a_final",
            "svc_s07.request_approval",
            "LIGHT",
            [],
            ["s16_score"],
            approval=("FINAL_VIDEO", "owner_one_tap"),
        ),
        S("s16_auth", "agent_16.publication_authorisation", "LIGHT", [], ["a_final"], stop=True),
        S("s13_deliver", "agent_13.file_delivery", "LIGHT", ["file_delivery"], ["s16_auth"]),
    ]


def _shorts_stages() -> list[dict[str, Any]]:
    S = _stage  # noqa: N806
    return [
        S("s05_shorts", "agent_05.shorts_adaptation", "AI_IO", ["llm"], []),
        S(
            "s06_claims",
            "agent_06.claim_extraction",
            "AI_IO",
            ["llm"],
            ["s05_shorts"],
            revise=("s05_shorts", []),
        ),
        S(
            "s06_verify",
            "agent_06.claim_verification",
            "AI_IO",
            ["llm"],
            ["s06_claims"],
            revise=("s05_shorts", []),
        ),
        S("s07_voice", "agent_07.voice_synthesis", "AI_IO", ["tts", "media_probe"], ["s06_verify"]),
        S(
            "s07_master",
            "agent_07.audio_master",
            "HEAVY_CPU",
            ["render_ffmpeg", "media_probe"],
            ["s07_voice"],
            revise=("s07_voice", []),
        ),
        S("s09_plan", "agent_09.shot_plan", "AI_IO", ["llm"], ["s06_verify", "s07_voice"]),
        S(
            "s08_assets",
            "agent_08.asset_sourcing",
            "AI_IO",
            ["llm", "stock_search", "media_probe"],
            ["s09_plan"],
            revise=("s09_plan", ["s05_shorts"]),
        ),
        S(
            "s06_chart",
            "agent_06.claim_verification",
            "AI_IO",
            ["llm"],
            ["s08_assets"],
            revise=("s05_shorts", ["s08_assets"]),
            params={"verify_mode": "CHART_FACTS"},
        ),
        S(
            "s10_render",
            "agent_10.render",
            "HEAVY_CPU",
            ["render_ffmpeg"],
            ["s07_master", "s08_assets", "s06_chart"],
        ),
        S("s10_subs", "agent_10.subtitles", "HEAVY_CPU", ["render_ffmpeg"], ["s10_render"]),
        S(
            "s10_qc",
            "agent_10.technical_qc",
            "HEAVY_CPU",
            ["render_ffmpeg", "media_probe"],
            ["s10_subs"],
            revise=("s10_render", ["s07_voice", "s08_assets", "s09_plan"]),
        ),
        S(
            "s11_thumbs",
            "agent_11.thumbnail_variants",
            "AI_IO",
            ["llm"],
            ["s09_plan", "s08_assets"],
            required=False,
            enabled=False,
            revise=("s05_shorts", []),
        ),
        S(
            "s02u_unique",
            "svc_s02.uniqueness_check",
            "AI_IO",
            ["media_probe"],
            ["s10_qc"],
            revise=("s05_shorts", []),
        ),
        S(
            "s16_comp",
            "agent_16.compliance_gate",
            "AI_IO",
            ["llm"],
            ["s02u_unique", "s11_thumbs"],
            revise=("s05_shorts", ["s08_assets"]),
        ),
        S(
            "s16_score",
            "agent_16.quality_score",
            "AI_IO",
            ["llm"],
            ["s16_comp"],
            revise=("s09_plan", ["s05_shorts", "s07_voice", "s10_render"]),
        ),
        S(
            "a_final",
            "svc_s07.request_approval",
            "LIGHT",
            [],
            ["s16_score"],
            approval=("FINAL_VIDEO", "owner_one_tap"),
        ),
        S("s16_auth", "agent_16.publication_authorisation", "LIGHT", [], ["a_final"], stop=True),
        S("s13_deliver", "agent_13.file_delivery", "LIGHT", ["file_delivery"], ["s16_auth"]),
    ]


@cache
def record(key: ProductionTypeKey) -> ProductionType:
    if key is ProductionTypeKey.CHANNEL_LONG_FORM:
        doc = _common(key.value, _long_form_stages())
    elif key is ProductionTypeKey.SHORTS:
        doc = _common(
            key.value,
            _shorts_stages(),
            parent_input="PARENT_JOB",
            aspect_ratios=["9:16"],
            qc_profile="qc.shorts",
            deliverables=[
                "shorts_9x16",
                "srt_per_language",
                "qc_report",
                "cost_per_stage_report",
                "delivery_manifest",
            ],
        )
    else:
        raise KeyError(f"no 3A record for {key.value}")
    pt = ProductionType.model_validate(doc)
    validate_record(pt)
    return pt


def validate_record(pt: ProductionType) -> None:
    """The 24 section 2 load rules that need the task-type catalogue and config."""
    unknown = sorted({s.task_type for s in pt.stages} - _TASK_TYPES)
    if unknown:
        raise ValueError(f"unknown task types {unknown}")
    if pt.limits.max_revision_loops > MAX_REVISION_LOOPS_CEILING:
        raise ValueError("max_revision_loops above the 07 section 9 ceiling")
    workflows = {(a.approval_kind, a.workflow_key) for a in pt.approvals}
    for s in pt.stages:
        if (
            s.approval is not None
            and (s.approval.approval_kind, s.approval.workflow_key) not in workflows
        ):
            raise ValueError(f"stage {s.stage_id}: approval workflow not declared")


def job_graph(key: ProductionTypeKey, enabled: frozenset[str] = frozenset()) -> tuple[Stage, ...]:
    """The materialised graph of a job (24 section 3.3 rule 9): default-disabled optional
    stages minus the ones the job enables."""
    pt = record(key)
    return materialise(pt, default_disabled(pt) - enabled)


def topological_order(stages: tuple[Stage, ...]) -> tuple[str, ...]:
    """Deterministic order: Kahn's algorithm, ties broken by the record order."""
    order = [s.stage_id for s in stages]
    deps = {s.stage_id: set(s.depends_on) for s in stages}
    done: list[str] = []
    while len(done) < len(order):
        ready = [sid for sid in order if sid not in done and deps[sid] <= set(done)]
        if not ready:
            raise ValueError("cycle")
        done.append(ready[0])
    return tuple(done)


def record_sha256(pt: ProductionType) -> bytes:
    raw = json.dumps(pt.to_doc(), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).digest()
