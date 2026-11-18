"""``BatchPlanner`` (V-S3; blueprint 10.4): claims per call, evidence ids, digest, pairs. Pure.

Claims of one candidate pair share a batch; ids ``p01...`` (windows) and ``f01...`` (chart facts)
are assigned by code per batch and mapped back to ``citation_ref`` / ``<chart_id>#<fact_id>`` after
the call. The model gets no database id, no storage path and no reliability tier."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from agent_06_fact_checker.config import FactCheckSettings
from agent_06_fact_checker.evidence import Candidate, ClaimEvidence
from agent_06_fact_checker.models import ClaimMode, EvidenceSourceKind
from agent_06_fact_checker.numbers import numerals
from agent_06_fact_checker.planner import ClaimPlan
from agent_06_fact_checker.windows import tokens


@dataclass(slots=True)
class Batch:
    index: int
    plans: list[ClaimPlan] = field(default_factory=list)
    evidence: dict[str, Candidate] = field(default_factory=dict)
    """Batch evidence id -> candidate."""
    claim_ids: dict[str, list[str]] = field(default_factory=dict)
    """``local_id`` -> evidence ids that are candidates of that claim."""
    pairs: list[tuple[str, str]] = field(default_factory=list)

    @property
    def local_ids(self) -> list[str]:
        return [p.claim.local_id for p in self.plans]


def _components(ids: Sequence[str], pairs: Sequence[tuple[str, str]]) -> list[list[str]]:
    parent = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        if a in parent and b in parent:
            parent[find(a)] = find(b)
    groups: dict[str, list[str]] = {}
    for i in ids:
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def build_batches(
    sendable: Sequence[tuple[ClaimPlan, ClaimEvidence]],
    pairs: Sequence[tuple[str, str]],
    settings: FactCheckSettings,
) -> list[Batch]:
    by_id = {p.claim.local_id: (p, e) for p, e in sendable}
    order = [p.claim.local_id for p, _ in sendable]
    groups = _components(order, pairs)
    groups.sort(key=lambda g: order.index(g[0]))
    packed: list[list[str]] = []
    for group in groups:
        group.sort(key=order.index)
        if packed and len(packed[-1]) + len(group) <= settings.max_claims_per_call:
            packed[-1].extend(group)
        else:
            packed.append(list(group))
    batches: list[Batch] = []
    for index, ids in enumerate(packed):
        batch = Batch(index)
        seen: dict[tuple[str, int], str] = {}
        p_n = f_n = 0
        for local_id in ids:
            plan, ev = by_id[local_id]
            batch.plans.append(plan)
            mine: list[str] = []
            for cand in ev.candidates:
                key = (cand.source_ref, cand.offset)
                if key not in seen:
                    if cand.kind is EvidenceSourceKind.CHART_FACT:
                        f_n += 1
                        seen[key] = f"f{f_n:02d}"
                    else:
                        p_n += 1
                        seen[key] = f"p{p_n:02d}"
                    batch.evidence[seen[key]] = cand
                mine.append(seen[key])
            batch.claim_ids[local_id] = mine
        batch.pairs = [(a, b) for a, b in pairs if a in ids or b in ids]
        batches.append(batch)
    return batches


def claim_view(plan: ClaimPlan, batch: Batch) -> dict[str, object]:
    claim = plan.claim
    cited = {
        eid
        for eid in batch.claim_ids[claim.local_id]
        if batch.evidence[eid].source_ref in claim.citation_refs
        or (
            plan.mode is ClaimMode.CHART_FACTS
            and batch.evidence[eid].source_ref.startswith(f"{claim.chart_data_ref}#")
        )
    }
    nums = [n.text for n in numerals(claim.quote + " " + claim.normalized_claim)]
    return {
        "local_id": claim.local_id,
        "quote": claim.quote,
        "normalized_claim": claim.normalized_claim,
        "claim_type": claim.claim_type.value,
        "time_reference_kind": claim.time_reference_kind.value,
        "instrument": claim.instrument,
        "verify_mode": plan.mode.value,
        "script_cited_evidence_ids": sorted(cited),
        "candidate_evidence_ids": batch.claim_ids[claim.local_id],
        "numbers_in_claim": nums,
    }


def digest(
    batch: Batch, others: Sequence[ClaimPlan], settings: FactCheckSettings
) -> list[dict[str, str]]:
    """Other verifiable claims, closest (shared tokens) first, capped (``max_digest_claims``)."""
    mine = set()
    for p in batch.plans:
        mine |= tokens(p.claim.normalized_claim)
    in_batch = set(batch.local_ids)
    pool = [p for p in others if p.claim.local_id not in in_batch]
    pool.sort(key=lambda p: (-len(tokens(p.claim.normalized_claim) & mine), p.claim.local_id))
    return [
        {"local_id": p.claim.local_id, "normalized_claim": p.claim.normalized_claim}
        for p in pool[: settings.max_digest_claims]
    ]


def batch_variables(
    batch: Batch,
    others: Sequence[ClaimPlan],
    settings: FactCheckSettings,
    *,
    language: str,
    channel_category: str,
) -> dict[str, object]:
    passages = [
        {"evidence_id": eid, "source_kind": c.kind.value, "text": c.text}
        for eid, c in batch.evidence.items()
        if c.kind is not EvidenceSourceKind.CHART_FACT
    ]
    facts = [
        {
            "evidence_id": eid,
            "ref_id": c.source_ref.split("#", 1)[0],
            "statement": c.text,
        }
        for eid, c in batch.evidence.items()
        if c.kind is EvidenceSourceKind.CHART_FACT
    ]
    return {
        "language": language,
        "channel_category": channel_category,
        "claims": [claim_view(p, batch) for p in batch.plans],
        "passages": passages,
        "chart_facts": facts,
        "claim_digest": digest(batch, others, settings),
        "conflict_candidates": [{"claim_a": a, "claim_b": b} for a, b in batch.pairs],
    }


def evidence_by_claim(batch: Batch) -> Mapping[str, Mapping[str, Candidate]]:
    return {lid: {eid: batch.evidence[eid] for eid in ids} for lid, ids in batch.claim_ids.items()}
