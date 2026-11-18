"""Runs ``claim_verification`` eval cases through the real step.

The dataset has no recorded model output, only expectations (``expected``): the recorded response
is *derived* from them (``synthesize``), so the deterministic pre- and post-checks run end to end
while the model's "assessment" is, by construction, what the case expects. Discrepancy values are
verbatim placeholders (a numeral or first token), not judged text; the judge criteria J1-J4 are not
evaluated here (no judge model is run). Evidence spans cover the whole window (capped)."""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from agent_06_fact_checker.hashing import sha256_hex
from agent_06_fact_checker.models import CitationKind
from agent_06_fact_checker.ports import SourceText
from amw_adapters.common import CallUsage
from amw_adapters.llm.protocol import LlmRequest, LlmResponse
from amw_core.contracts.task_output import TaskOutput
from amw_core.enums import CostOperation
from tests.agents.agent_06_fact_checker.support import (
    MemoryKnowledge,
    World,
    make_settings,
    run_context,
    task_input,
    verification_step,
)

_INPUT = re.compile(r"<<<INPUT\n(.*)\nINPUT>>>", re.DOTALL)
_NUM = re.compile(r"\d+(?:[.,:]\d+)*")


class RespondingLlm:
    """A fake model that answers from the case expectation, reading the real rendered request."""

    provider = "fake_llm"

    def __init__(self, case: dict[str, Any]) -> None:
        self.case = case
        self.requests: list[LlmRequest] = []

    @property
    def calls(self) -> int:
        return len(self.requests)

    def complete(self, request: LlmRequest, *, idempotency_key: str) -> LlmResponse:
        self.requests.append(request)
        match = _INPUT.search(request.messages[0].content)
        assert match, "user message carries one INPUT block"
        text = json.dumps(synthesize(self.case, json.loads(match.group(1))), ensure_ascii=False)
        usage = CallUsage(
            provider="fake_llm",
            operation=CostOperation.LLM_COMPLETION,
            model=request.model,
            tokens_in=10,
            tokens_out=10,
            amount_micros=1,
            currency="USD",
            idempotency_key=idempotency_key,
        )
        return LlmResponse(usage=usage, text=text, stop_reason="end_turn")

    def count_tokens(self, request: LlmRequest, *, idempotency_key: str) -> Any:
        raise NotImplementedError


def _fixture_to_batch_ids(case: dict[str, Any], view: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """Fixture evidence id (p01, f01) -> (batch evidence id, text), matched by text."""
    out: dict[str, tuple[str, str]] = {}
    passages = {p["text"]: p["evidence_id"] for p in view["passages"]}
    for fix in case["fixture"]["passages"]:
        if fix["text"] in passages:
            out[fix["evidence_id"]] = (passages[fix["text"]], fix["text"])
    facts = {f["statement"]: f["evidence_id"] for f in view["chart_facts"]}
    n = 0
    for chart in case["input"]["chart_facts"]:
        for fact in chart["facts"]:
            n += 1
            if fact["statement"] in facts:
                out[f"f{n:02d}"] = (facts[fact["statement"]], fact["statement"])
    return out


def _pair(claim: dict[str, Any], evidence: str) -> tuple[str, str]:
    a, b = _NUM.search(claim["quote"]), _NUM.search(evidence)
    if a and b:
        return a.group(0), b.group(0)
    return claim["quote"].split()[0], evidence.split()[0]


def synthesize(case: dict[str, Any], view: dict[str, Any]) -> dict[str, Any]:
    exp = case["expected"]
    refusal = exp.get("refusal_reason")
    if refusal is not None:
        return {
            "results": [],
            "claim_conflicts": [],
            "passage_flags": [],
            "refusal": {
                "reason": refusal,
                "message": "recorded refusal",
                "missing_inputs": [],
                "violated_rule_ids": [],
            },
        }
    ids = _fixture_to_batch_ids(case, view)
    claims = {c["local_id"]: c for c in case["input"]["claims"]}
    max_span = case["fixture"]["step_config"]["max_span_chars"]
    sent = {c["local_id"] for c in view["claims"]}
    results = []
    for lid, spec in exp["claims"].items():
        if "assessment_any" not in spec or lid not in sent:
            continue
        evidence: list[dict[str, Any]] = []
        relations = spec.get("relation_any", [])
        for k, fid in enumerate(spec.get("evidence_any", [])):
            batch_id, text = ids[fid]
            rel = relations[min(k, len(relations) - 1)] if relations else "SUPPORTS"
            if len(relations) == 1:
                rel = relations[0]
            evidence.append(
                {
                    "evidence_id": batch_id,
                    "relation": rel,
                    "span_start": 0,
                    "span_end": min(len(text), max_span),
                }
            )
        discrepancies = []
        kinds = spec.get("discrepancy_kinds_any", [])
        if kinds and evidence:
            ev_text = ids[spec["evidence_any"][0]][1]
            cv, evv = _pair(claims[lid], ev_text)
            discrepancies.append({"kind": kinds[0], "claim_value": cv, "evidence_value": evv})
        correction = None
        if spec.get("correction") == "present":
            first = ids[spec["evidence_any"][0]][1] if spec.get("evidence_any") else "the source"
            correction = ("The source states: " + first)[:280]
        results.append(
            {
                "local_id": lid,
                "assessment": spec["assessment_any"][0],
                "evidence": evidence,
                "discrepancies": discrepancies,
                "certainty": "HIGH",
                "suggested_correction": correction,
                "rationale": "Recorded fixture derived from the case expectation.",
            }
        )
    conflicts = [
        {"claim_a": a, "claim_b": b, "kind": "NUMBER", "explanation": "Fixture conflict."}
        for a, b in exp.get("claim_conflicts", [])
    ]
    flags = [
        {"evidence_id": ids[f][0], "flag": "INJECTION_SUSPECTED"}
        for f in exp.get("flagged_passages", [])
        if f in ids
    ]
    return {
        "results": results,
        "claim_conflicts": conflicts,
        "passage_flags": flags,
        "refusal": None,
    }


def knowledge_for(case: dict[str, Any]) -> MemoryKnowledge:
    sources = [
        SourceText(
            p["citation_ref"],
            CitationKind(p["source_kind"]),
            p["text"],
            sha256_hex(p["text"]),
            p["reliability_tier"],
            p["restricted"],
        )
        for p in case["fixture"]["passages"]
    ]
    return MemoryKnowledge(sources)


@dataclass
class CaseRun:
    case: dict[str, Any]
    output: TaskOutput
    llm: RespondingLlm
    world: World
    batch_texts: list[str] = field(default_factory=list)


def run_case(case: dict[str, Any], *, script_sha: str | None = None) -> CaseRun:
    cfg = case["fixture"]["step_config"]
    settings = make_settings(
        min_tier_for_verified=cfg["min_tier_for_verified"],
        tier_order=cfg["tier_order"],
        max_span_chars=cfg["max_span_chars"],
        rounding_match=cfg["rounding_match"],
    )
    llm = RespondingLlm(case)
    world = World(llm=llm)  # type: ignore[arg-type]
    pairs = [tuple(p) for p in case["fixture"].get("conflict_candidates") or []]
    step = verification_step(
        world,
        knowledge_for(case),
        settings=settings,
        script_sha=script_sha or case["input"]["script_sha256"],
        conflict_finder=lambda claims, s: [(a, b) for a, b in pairs],
    )
    stage = "s06_chart" if case["input"]["verify_mode"] == "CHART_FACTS" else "s06_verify"
    task = task_input("agent_06.claim_verification.input", case["input"])
    out = step.run(task, run_context(stage, case["input"]["iteration"]))
    return CaseRun(case, out, llm, world)
