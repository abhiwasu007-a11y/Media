# mypy: disable-error-code="arg-type,attr-defined,unused-ignore,var-annotated,index,no-untyped-call,misc,union-attr"
# (throw-away dry-run fixtures feed fakes and dataset dicts into typed APIs)
"""``s06_claims`` / ``s06_verify`` / ``s06_chart`` -> Agent 06 (extraction and verification)."""

import json
import re
from typing import Any

from agent_06_fact_checker.extraction_step import ClaimExtractionStep
from agent_06_fact_checker.hashing import claims_sha256, sha256_hex
from agent_06_fact_checker.models import CitationKind
from agent_06_fact_checker.ports import SourceText
from agent_06_fact_checker.runtime import RunContext
from agent_06_fact_checker.verification_step import ClaimVerificationStep
from amw_adapters.llm import LlmRequest
from amw_core.contracts import TaskOutput
from amw_core.testing.memory import MemoryCheckpointStore
from amw_orchestrator.executor import StageCall
from amw_orchestrator.metering import MeteredLlm
from tests.agents.agent_06_fact_checker import support as s6
from tests.dryrun.base import World, task_input, upstream, upstream_data
from tests.dryrun.kit import AllowBudget, ListAudit, MemTenancy, MirrorLedger, ref_ending
from tests.dryrun.llm import ScriptedLlm

_INPUT = re.compile(r"<<<INPUT\n(.*)\nINPUT>>>", re.DOTALL)
SCRIPT_SCHEMA = "agent_05.script_draft.output"


def _view(request: LlmRequest) -> dict[str, Any]:
    match = _INPUT.search(request.messages[0].content)
    assert match is not None
    parsed: dict[str, Any] = json.loads(match.group(1))
    return parsed


def extraction_responder(request: LlmRequest) -> str:
    """One DEFINITION claim per cited segment (whole sentence), verdict ALLOWED."""
    view = _view(request)
    claims = []
    for seg in view["segments"]:
        cites = seg.get("citation_refs") or []
        if not cites:
            continue
        quote = seg["text"].split(",")[0]
        claims.append(
            {
                "local_id": f"c{len(claims) + 1}",
                "segment_id": seg["segment_id"],
                "char_start": 0,
                "char_end": len(quote),
                "quote": quote,
                "normalized_claim": quote[:300],
                "claim_type": "DEFINITION",
                "time_reference_kind": "TIMELESS",
                "instrument": None,
                "chart_data_ref": None,
                "requires_citation": True,
                "citation_refs": cites[:1],
                "rule_flags": [],
                "proposed_verdict": "ALLOWED",
                "rationale": "PLUMBING scripted extraction.",
            }
        )
    return json.dumps(
        {
            "claims": claims,
            "overall": {
                "proposed_verdict": "ALLOWED",
                "blocking_rule_ids": [],
                "needs_human_review_reasons": [],
            },
            "refusal": None,
        },
        ensure_ascii=False,
    )


def verification_responder(request: LlmRequest) -> str:
    """Every claim SUPPORTED by its first passage (whole window)."""
    view = _view(request)
    results = []
    passages = view.get("passages", [])
    for claim in view["claims"]:
        evidence = [
            {
                "evidence_id": p["evidence_id"],
                "relation": "SUPPORTS",
                "span_start": 0,
                "span_end": min(len(p["text"]), 400),
            }
            for p in passages
        ]
        results.append(
            {
                "local_id": claim["local_id"],
                "assessment": "SUPPORTED" if evidence else "UNVERIFIABLE",
                "evidence": evidence,
                "discrepancies": [],
                "certainty": "HIGH",
                "suggested_correction": None,
                "rationale": "PLUMBING scripted verification.",
            }
        )
    return json.dumps(
        {"results": results, "claim_conflicts": [], "passage_flags": [], "refusal": None},
        ensure_ascii=False,
    )


class _Scripts:
    def __init__(self) -> None:
        self.sha: dict[tuple[str, int], str] = {}

    def content_sha256(self, tx: Any, *, script_id: str, script_version: int) -> str | None:
        return self.sha.get((script_id, script_version))


class FactExecutor:
    """One executor for the three Agent 06 stages (state shared: the claims store)."""

    def __init__(self, world: World, chunk_text: dict[str, str]) -> None:
        self.w = world
        self.claims = s6.MemoryClaims()
        self.scripts = _Scripts()
        self.chunk_text = chunk_text

    def _script(self, call: StageCall) -> tuple[dict[str, Any], Any, dict[str, Any]]:
        script_stage = "s05_shorts" if "s05_shorts" in call.upstream else "s05_script"
        out = upstream(call, script_stage)
        data = upstream_data(call, script_stage)
        ref = ref_ending(out, ".json")
        doc = self.w.blobs.read_json(ref.uri, ref.sha256)
        self.scripts.sha[(data["script_id"], data["version"])] = ref.sha256
        return data, ref, doc

    def _refs(self, ref: Any) -> list[dict[str, Any]]:
        return [
            {
                "uri": ref.uri,
                "purpose": "PRIOR_OUTPUT",
                "sha256": ref.sha256,
                "schema": SCRIPT_SCHEMA,
            }
        ]

    def _citations(self, call: StageCall) -> list[dict[str, Any]]:
        pack = (
            upstream_data(call, "s04_research")
            if "s04_research" in call.upstream
            else upstream_data(call, "parent.s04_research")
        )
        return [
            {
                "citation_ref": c["citation_ref"],
                "kind": c["kind"],
                "title": c["title"],
                "content_sha256": c.get("content_sha256"),
            }
            for c in pack["citations_available"]
        ]

    def execute(self, call: StageCall) -> TaskOutput:
        if call.stage.task_type.endswith("claim_extraction"):
            return self._extract(call)
        return self._verify(call)

    def _common(self, llm: ScriptedLlm) -> dict[str, Any]:
        return {
            "llm": MeteredLlm(llm, self.w.meter, 2_000),
            "budget": AllowBudget(),
            "ledger": MirrorLedger(),
            "tenancy": MemTenancy(),
            "clock": self.w.clock,
            "blobs": self.w.blobs.storage,
            "checkpoints": MemoryCheckpointStore(),
            "audit": ListAudit(),
            "claims": self.claims,
            "scripts": self.scripts,
            "prompts": s6.DocPrompts(),
            "settings": s6.make_settings(),
        }

    def _extract(self, call: StageCall) -> TaskOutput:
        data, ref, doc = self._script(call)
        segments = []
        for seg in doc["segments"]:
            cites = sorted({c for cr in seg.get("concept_refs", []) for c in cr["citation_refs"]})
            item: dict[str, Any] = {
                "segment_id": seg["segment_id"],
                "text": seg["text"],
                "visual_refs": [seg["chart_ref"]] if seg.get("chart_ref") else [],
            }
            if cites:
                item["citation_refs"] = cites
            segments.append(item)
        payload = {
            "script_id": data["script_id"],
            "script_version": data["version"],
            "language": data["language"],
            "channel_category": "finance",
            "owner_sebi_registration": "UNREGISTERED",
            "active_rule_packs": ["rp.youtube_general", "rp.finance_sebi_in"],
            "segments": segments,
            "chart_data_refs": [
                {
                    "ref_id": c["chart_id"],
                    "instrument": c.get("instrument") or "SYNTHETIC",
                    "data_age_vs_lag": "OLDER_THAN_LAG",
                    "data_age_basis": "CONSTRAINT",
                }
                for c in doc.get("chart_requests", [])
            ],
            "available_citations": [
                {k: v for k, v in c.items() if k != "content_sha256"} for c in self._citations(call)
            ],
            "our_method_release_approved": False,
        }
        step = ClaimExtractionStep(
            **self._common(ScriptedLlm(extraction_responder)),
            rule_packs=s6.StaticPacks(),
            chart_ranges=s6.FixedRanges(),
        )
        ti = task_input(
            call, "agent_06", "agent_06.claim_extraction.input", payload, self._refs(ref), "1.1.0"
        )
        return step.run(ti, RunContext(call.attempt_id, call.stage.stage_id, call.iteration))  # type: ignore[arg-type]

    def _verify(self, call: StageCall) -> TaskOutput:
        data, ref, _doc = self._script(call)
        ext = upstream_data(call, "s06_claims")
        ids_ref = ref_ending(upstream(call, "s06_claims"), "claim_ids.json")
        claim_ids = self.w.blobs.read_json(ids_ref.uri, ids_ref.sha256)
        claims = [
            {
                "claim_id": claim_ids[c["local_id"]],
                "local_id": c["local_id"],
                "segment_id": c["segment_id"],
                "quote": c["quote"],
                "normalized_claim": c["normalized_claim"],
                "claim_type": c["claim_type"],
                "time_reference_kind": c["time_reference_kind"],
                "instrument": c["instrument"],
                "chart_data_ref": c["chart_data_ref"],
                "requires_citation": c["requires_citation"],
                "citation_refs": c["citation_refs"],
                "extraction_verdict": c["proposed_verdict"],
            }
            for c in ext["claims"]
        ]
        chart_mode = call.stage.stage_id == "s06_chart"
        chart_facts = self.w.extras.get("chart_facts", []) if chart_mode else []
        if chart_mode:
            claims = [c for c in claims if c["chart_data_ref"]]
        payload = {
            "script_id": data["script_id"],
            "script_version": data["version"],
            "script_sha256": ref.sha256,
            "verify_mode": "CHART_FACTS" if chart_mode else "EVIDENCE",
            "iteration": call.iteration,
            "language": data["language"],
            "channel_category": "finance",
            "active_rule_packs": ["rp.youtube_general", "rp.finance_sebi_in"],
            "our_method_release_approved": False,
            "extraction_overall_verdict": ext["overall"]["proposed_verdict"],
            "claims": claims,
            "available_citations": self._citations(call),
            "chart_facts": chart_facts,
            "claims_sha256": claims_sha256(claims),
        }
        knowledge = s6.MemoryKnowledge(
            [
                SourceText(
                    ref_id,
                    CitationKind.KNOWLEDGE_CHUNK,
                    text,
                    sha256_hex(text),
                    "B_PUBLISHED",
                    False,
                )
                for ref_id, text in self.chunk_text.items()
            ]
        )
        self.claims.register_extraction(
            [
                {
                    "claim_id": claim_ids[c["local_id"]],
                    "extraction_verdict": c["extraction_verdict"],
                }
                for c in claims
            ]
        )
        step = ClaimVerificationStep(
            **self._common(ScriptedLlm(verification_responder)), knowledge=knowledge
        )
        ti = task_input(
            call, "agent_06", "agent_06.claim_verification.input", payload, self._refs(ref)
        )
        return step.run(ti, RunContext(call.attempt_id, call.stage.stage_id, call.iteration))  # type: ignore[arg-type]
