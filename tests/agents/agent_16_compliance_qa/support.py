"""Shared test helpers for Agent 16: config, lexicon, dataset loading, scripted LLM, IDs."""

import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from agent_16_compliance_qa.config import Agent16Config
from amw_adapters.common import CallUsage
from amw_adapters.llm.protocol import LlmRequest, LlmResponse
from amw_core import ids

REPO = Path(__file__).resolve().parents[3]
EVALS = REPO / "docs/v4/evals/agent_16_compliance_qa"
PROMPTS = REPO / "docs/v4/prompts/agent_16_compliance_qa"
BLUEPRINT = REPO / "docs/v4/agents/agent_16_compliance_qa.md"

EN_LEXICON: dict[str, Any] = {
    "version": "lex.en.test.1",
    "future_markers": [
        "will",
        "should",
        "likely to",
        "target",
        "next move",
        "again",
        "repeat",
        "same setup now",
    ],
    "imperative_verbs": [
        "buy",
        "sell",
        "hold",
        "enter",
        "exit",
        "add",
        "accumulate",
        "avoid",
        "go long",
        "short",
    ],
    "level_words": ["target", "stop", "strike", "level"],
    "promotion_words": ["link", "code", "broker", "sponsor", "sponsored", "open an account"],
    "group_words": ["group", "membership", "tips", "daily calls"],
    "identity_markers": ["i am", "your host"],
    "child_markers": ["nursery", "cartoon", "kids", "children", "little friends"],
    "person_markers": ["i", "my", "you", "your", "we", "our", "students"],
    "live_format_terms": ["live trading", "live session", "live"],
}

BASE_CONFIG: dict[str, Any] = {
    "quality.publish_min_score": 85,
    "quality.machine_scaling": "NONE",
    "quality.score_gate_mode": "REPORT_ONLY",
    "editorial.min_description_chars": 20,
    "approvals.accepted_channels": ["OWNER_CHAT_OPERATOR"],
    "approvals.review_code.length": 4,
    "compliance.finance_sebi_in.price_data_lag_days": 30,
    "compliance.watermark_visual.calibrated": False,
    "compliance.gate.max_items_per_judge_call": 8,
    "compliance.gate.max_llm_calls": 16,
    "uniqueness.cross_video.skip_below_prior_count": 3,
    "agent_16.llm.fallback_on_unavailable": False,
    "compliance.prefilter.lexicon.en": EN_LEXICON,
    "compliance.prefilter.lexicon.mr": EN_LEXICON | {"version": "lex.mr.test.1"},
    "compliance.prefilter.lexicon.hi": EN_LEXICON | {"version": "lex.hi.test.1"},
}
for _step in (
    "compliance_gate.policy",
    "compliance_gate.paraphrase",
    "compliance_gate.frames",
    "quality_score.judge",
):
    for _k, _v in {
        "model": "test-model-from-config",
        "max_output_tokens": 2000,
        "temperature": 0,
        "timeout_ms": 30000,
        "cache_system_prompt": True,
        "max_calls": 8,
        "worst_case_call_micros": 100,
        "max_cost_micros": 100000,
        "accepts_images": _step.endswith("frames") or _step.endswith("judge"),
    }.items():
        BASE_CONFIG[f"llm.agent_16.{_step}.{_k}"] = _v


def config(**overrides: Any) -> Agent16Config:
    return Agent16Config.from_mapping(BASE_CONFIG | overrides)


def cases(dataset: str) -> list[dict[str, Any]]:
    path = EVALS / dataset / "cases.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def case_ids(rows: list[dict[str, Any]]) -> list[str]:
    return [str(r["case_id"]) for r in rows]


class ScriptedLlm:
    """``LlmAdapter`` that returns queued texts (no network, no cost beyond fake micros)."""

    provider = "fake_llm"

    def __init__(self, texts: Iterator[str] | list[str], micros: int = 10) -> None:
        self._texts = iter(texts)
        self.requests: list[LlmRequest] = []
        self.keys: list[str] = []
        self._micros = micros

    def complete(self, request: LlmRequest, *, idempotency_key: str) -> LlmResponse:
        self.requests.append(request)
        self.keys.append(idempotency_key)
        text = next(self._texts)
        usage = CallUsage(
            provider="fake_llm",
            operation="llm.completion",
            model=request.model,
            tokens_in=10,
            tokens_out=5,
            amount_micros=self._micros,
            currency="USD",
            idempotency_key=idempotency_key,
        )
        return LlmResponse(text=text, stop_reason="end_turn", usage=usage)

    def count_tokens(self, request: LlmRequest, *, idempotency_key: str) -> Any:
        raise NotImplementedError


class Recorder:
    def __init__(self) -> None:
        self.rows: list[str] = []

    def record(self, response: LlmResponse, idempotency_key: str) -> str:
        self.rows.append(idempotency_key)
        return ids.COST_ENTRY.new()


def blueprint_schema(heading: str) -> dict[str, Any]:
    """The JSON Schema block under a section heading of the blueprint (contract tests C-01)."""
    text = BLUEPRINT.read_text(encoding="utf-8")
    start = text.index(heading)
    block = text.index("```json", start) + len("```json")
    return dict(json.loads(text[block : text.index("```", block)]))


def validate_against_blueprint(payload: Any, heading: str) -> None:
    """JSON Schema check of a payload against the blueprint section, with ``amw.common`` from
    the amw_core registry (no network)."""
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    from amw_core.contracts.registry import get_schema, schema_id

    common = get_schema("amw.common", "1.0.0")
    registry: Registry[Any] = Registry().with_resource(
        schema_id("amw.common", "1.0.0"), Resource.from_contents(dict(common))
    )
    Draft202012Validator(blueprint_schema(heading), registry=registry).validate(payload)


def evidence_mapping(**over: Any) -> Mapping[str, Any]:
    base = {
        "state": "CONFIRMED",
        "source_kind": "OWNER_CHAT_MESSAGE",
        "same_org": True,
        "on_behalf_of_matches": True,
        "subject_matches": True,
        "review_code_matches": True,
        "parsed_decision_matches": True,
        "message_after_request": True,
        "confirmation_after_message": True,
        "verifier_all_passed": True,
        "failed_tests": [],
        "refused_reason": None,
        "hash_recomputes": True,
        "mac_valid": True,
        "replay_free": True,
        "backs_only_this_record": True,
    }
    return base | over
