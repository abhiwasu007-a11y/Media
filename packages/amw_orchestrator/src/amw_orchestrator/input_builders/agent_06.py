"""``agent_06.claim_extraction`` (1.1.0) and ``agent_06.claim_verification`` inputs (agent_06
sections 7.1-7.2; CCR-053, CCR-004, CCR-201).

The extraction input carries the script text, so the builder reads the script document the
Agent 05 payload names (hash-verified) and derives ``segments`` as agent_05 section 8.3 says
(``visual_refs`` = the ``chart_ref``; ``citation_refs`` = the union of ``concept_refs[]``
citations, none invented). The verification input maps the extraction output; ``claim_id`` comes
from the ``claim_ids`` blob (CCR-201). ``script_sha256`` is the hash of the script document the
extraction input named.
"""

from typing import Any

from amw_core.enums import ContextRefPurpose
from amw_core.errors import InputInvalidError
from amw_orchestrator.executor import BuildContext, BuiltInput, DocRef
from amw_orchestrator.input_builders import common as c

EXTRACTION_SCHEMA = "agent_06.claim_extraction.input"
VERIFICATION_SCHEMA = "agent_06.claim_verification.input"
EXTRACTION_VERSION = "1.1.0"
PACK_SCHEMA = "agent_04.research_pack.output"


def _script(ctx: BuildContext) -> tuple[dict[str, Any], DocRef]:
    data = c.payload(ctx, c.script_stage_id(ctx.job))
    return data, c.ref_in(data, "script_document")


def _pack(ctx: BuildContext) -> tuple[DocRef, dict[str, Any]]:
    out = c.stage_output(ctx, "s04_research")
    return c.artifact(out, r"research_pack\.json"), c.payload_of(ctx, out)


def _citations(pack: dict[str, Any], *, with_hash: bool) -> list[dict[str, Any]]:
    keys = ("citation_ref", "kind", "title") + (("content_sha256",) if with_hash else ())
    return [
        {k: cit[k] for k in keys if cit.get(k) is not None} for cit in pack["citations_available"]
    ]


def _method_released(pack: dict[str, Any]) -> bool:
    """agent_04 section 8: from ``method.release_approval_ids``, never a free flag."""
    return bool(pack.get("method", {}).get("release_approval_ids"))


class ClaimExtractionBuilder:
    def build(self, ctx: BuildContext) -> BuiltInput:
        job = ctx.job
        script, doc_ref = _script(ctx)
        doc = c.read_doc(ctx, doc_ref)
        pack_ref, pack = _pack(ctx)
        segments = []
        for seg in doc["segments"]:
            cites = sorted(
                {x for cr in seg.get("concept_refs") or [] for x in cr.get("citation_refs", [])}
            )
            item: dict[str, Any] = {
                "segment_id": seg["segment_id"],
                "text": seg["text"],
                "visual_refs": [seg["chart_ref"]] if seg.get("chart_ref") else [],
            }
            if cites:
                item["citation_refs"] = cites
            segments.append(item)
        data = {
            "script_id": script["script_id"],
            "script_version": script["version"],
            "language": job.language,
            "channel_category": job.channel_category.value,
            "owner_sebi_registration": c.OWNER_SEBI_REGISTRATION,
            "active_rule_packs": c.active_rule_packs(job),
            "segments": segments,
            # CCR-004: a REAL_HISTORICAL chart request is a data-age requirement for Agent 08
            "chart_data_refs": [
                {
                    "ref_id": cr["chart_id"],
                    "instrument": cr.get("instrument") or "",
                    "data_age_vs_lag": "OLDER_THAN_LAG",
                    "data_age_basis": "CONSTRAINT",
                }
                for cr in doc.get("chart_requests", [])
                if cr.get("chart_kind") == "REAL_HISTORICAL"
            ],
            "available_citations": _citations(pack, with_hash=False),
            "our_method_release_approved": _method_released(pack),
        }
        refs = [
            c.context_ref(doc_ref, ContextRefPurpose.PRIOR_OUTPUT, c.SCRIPT_DOCUMENT_SCHEMA),
            c.context_ref(pack_ref, ContextRefPurpose.PRIOR_OUTPUT, PACK_SCHEMA),
            *c.rule_pack_refs(ctx),
        ]
        return BuiltInput(EXTRACTION_SCHEMA, EXTRACTION_VERSION, data, tuple(refs))


class ClaimVerificationBuilder:
    """``s06_verify`` (EVIDENCE) and ``s06_chart`` (CHART_FACTS, ``params.verify_mode``)."""

    def build(self, ctx: BuildContext) -> BuiltInput:
        job = ctx.job
        mode = str((ctx.stage.params or {}).get("verify_mode", "EVIDENCE"))
        if mode not in ("EVIDENCE", "CHART_FACTS"):
            raise InputInvalidError("unknown verify_mode", details={"verify_mode": mode[:32]})
        script, doc_ref = _script(ctx)
        ext_out = c.stage_output(ctx, "s06_claims")
        ext = c.payload_of(ctx, ext_out)
        ids = c.read_doc(ctx, c.artifact(ext_out, r"claim_ids\.json"))
        pack_ref, pack = _pack(ctx)
        claims = []
        for cl in ext["claims"]:
            local = cl["local_id"]
            if local not in ids:
                raise InputInvalidError(
                    "claim_ids blob has no ID for a claim", details={"local_id": str(local)[:16]}
                )
            claims.append(
                {
                    "claim_id": ids[local],
                    **{
                        k: cl[k]
                        for k in (
                            "local_id",
                            "segment_id",
                            "quote",
                            "normalized_claim",
                            "claim_type",
                            "time_reference_kind",
                            "instrument",
                            "chart_data_ref",
                            "requires_citation",
                            "citation_refs",
                        )
                    },
                    "extraction_verdict": cl["proposed_verdict"],
                }
            )
        refs = [
            c.context_ref(
                c.artifact(ext_out, r"claim_extraction_output\.json"),
                ContextRefPurpose.PRIOR_OUTPUT,
                "agent_06.claim_extraction.output",
            ),
            c.context_ref(pack_ref, ContextRefPurpose.PRIOR_OUTPUT, PACK_SCHEMA),
            c.context_ref(doc_ref, ContextRefPurpose.PRIOR_OUTPUT, c.SCRIPT_DOCUMENT_SCHEMA),
        ]
        chart_facts: list[dict[str, Any]] = []
        if mode == "CHART_FACTS":
            # 7.2: only claims of type HISTORICAL_MARKET with a chart_data_ref, hash over those
            claims = [
                x for x in claims if x["chart_data_ref"] and x["claim_type"] == "HISTORICAL_MARKET"
            ]
            sourcing = c.payload(ctx, "s08_assets")
            for ref in sourcing.get("chart_facts", []):
                fdoc = DocRef(ref["document_uri"], ref["document_sha256"])
                body = c.read_doc(ctx, fdoc)
                chart_facts.append(
                    {
                        "ref_id": body["chart_id"],
                        "instrument": body["instrument"],
                        "facts": [
                            {"fact_id": f["fact_id"], "statement": f["statement"]}
                            for f in body["facts"]
                        ],
                    }
                )
                refs.append(
                    c.context_ref(fdoc, ContextRefPurpose.PRIOR_OUTPUT, "agent_08.chart_facts")
                )
        data = {
            "script_id": script["script_id"],
            "script_version": script["version"],
            "script_sha256": doc_ref.sha256,
            "verify_mode": mode,
            "iteration": ctx.iteration,
            "language": job.language,
            "channel_category": job.channel_category.value,
            "active_rule_packs": c.active_rule_packs(job),
            "our_method_release_approved": _method_released(pack),
            "extraction_overall_verdict": ext["overall"]["proposed_verdict"],
            "claims": claims,
            "available_citations": _citations(pack, with_hash=True),
            "chart_facts": chart_facts,
            "claims_sha256": c.claims_sha256(claims),
        }
        if ctx.iteration > 0:
            prior = c.require_iteration_output(ctx)
            refs.append(
                c.context_ref(
                    c.artifact(prior, r"claim_verification_output\.json"),
                    ContextRefPurpose.PRIOR_OUTPUT,
                    "agent_06.claim_verification.output",
                )
            )
        return BuiltInput(VERIFICATION_SCHEMA, "1.0.0", data, tuple(refs))
