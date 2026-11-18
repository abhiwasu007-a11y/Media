"""Runs the 69 cases of evals/agent_04_research_knowledge/deterministic_core against the code.

Each case calls the function it names (blueprint 9, 10); a case passes when its result equals
``expected`` on every listed key. Fixtures are abstract (``same_org: true``): the builders below
turn them into real objects. Nothing is skipped; the choices a fixture leaves open are noted where
they are made (the dataset README lists the open points).
"""
# ruff: noqa: E501, N806, C408

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from agent_04_research_knowledge.errors import (
    ConfigInvalid,
    CrossTenantRef,
    InputInvalid,
    InsufficientInput,
)
from agent_04_research_knowledge.guards.copy_guard import CopyGuard
from agent_04_research_knowledge.guards.restricted import (
    ApprovalView,
    ChunkMeta,
    RestrictedCollectionGate,
    TopicFlags,
    release_subject_sha256,
)
from agent_04_research_knowledge.guards.tenant import TenantGuard
from agent_04_research_knowledge.library.memory import InMemoryKnowledgeLibrary
from agent_04_research_knowledge.library.models import (
    ChunkRow,
    CollectionView,
    SourceView,
    TenantScope,
)
from agent_04_research_knowledge.models.enums import (
    CopyGuardStatus,
    DomainClass,
    FetchStatus,
    ReliabilityTier,
)
from agent_04_research_knowledge.models.pack_input import ResearchPackInput
from agent_04_research_knowledge.models.plan import ResearchPlan
from agent_04_research_knowledge.scoring.reliability import (
    ReliabilityScorer,
    SourceMeta,
    TierScores,
)
from agent_04_research_knowledge.steps.assemble import PackAssembler
from agent_04_research_knowledge.steps.external import fetch_key
from agent_04_research_knowledge.steps.notes import NoteLimits, NoteValidator
from agent_04_research_knowledge.steps.plan import PlanValidator
from agent_04_research_knowledge.steps.research_pack import task_key
from agent_04_research_knowledge.steps.retrieve import (
    LibraryRetriever,
    RetrievalLimits,
    allowed_collections,
)
from agent_04_research_knowledge.steps.validate_pack import PackValidator
from amw_adapters.common import FailurePlan
from amw_adapters.web_fetch.fake import FakeWebFetchAdapter
from amw_core.enums import (
    ApprovalKind,
    ApprovalState,
    CheckVerdict,
    KnowledgeSourceKind,
    KnowledgeSourceStatus,
    NextActionType,
    SourceOwnership,
    VideoKind,
)
from amw_core.errors import AuthInvalidError, RateLimitedError, Upstream5xxError
from amw_core.ids import ATTEMPT, CHANNEL, ORG, Prefix, make_idempotency_key, new_id
from tests.agents.agent_04_research_knowledge.conftest import (
    BODY_1,
    build_world,
    make_run,
    user_payload,
)
from tests.agents.agent_04_research_knowledge.test_steps import (
    assemble,
    concept_doc,
    concept_ev,
    fetcher,
    plan_input,
    source,
    vnote,
    web_with,
)

DATASET = (
    Path(__file__).resolve().parents[3]
    / "docs/v4/evals/agent_04_research_knowledge/deterministic_core"
)
CASES = [
    json.loads(line) for line in (DATASET / "cases.jsonl").read_text(encoding="utf-8").splitlines()
]
SCORES = TierScores(0.9, 0.7, 0.5, 0.2)
#: Values the fixtures leave open (dataset README: "test values, not product defaults").
NOTE_LIMITS = NoteLimits(max_note_chars=300, max_verbatim_words=8, max_overlap_ratio=0.9, ngram_n=3)
ORG_A = "org_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e9f"
ORG_B = "org_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e90"


def err_code(exc: Exception) -> str:
    return str(getattr(exc, "code", type(exc).__name__))


# ---- RT -----------------------------------------------------------------------------------------
def rt(fx: dict[str, Any]) -> dict[str, Any]:
    if "config_tier_scores" in fx:
        try:
            TierScores.from_mapping(fx["config_tier_scores"])
        except ConfigInvalid as exc:
            return {"error": exc.code}
        return {"valid": True}
    library = fx.get("library_row", True)
    domain = DomainClass(fx["domain_class"]) if fx.get("domain_class") else None
    own = SourceOwnership(fx["ownership"]) if fx.get("ownership") else None
    meta = SourceMeta(KnowledgeSourceKind(fx["kind"]), own, domain, library)
    rel = ReliabilityScorer().score(meta, None, SCORES)
    if rel.excluded:
        return {"excluded": True, "reason": rel.reason}
    assert rel.tier is not None
    return {
        "tier": rel.tier.value,
        "owner_authored": rel.owner_authored,
        "ownership_in_pack": rel.ownership_in_pack,
        "excluded": False,
    }


# ---- RG -----------------------------------------------------------------------------------------
def rg(fx: dict[str, Any]) -> dict[str, Any]:
    ap = fx["chunk_release_approval"]
    topic = TopicFlags(VideoKind(fx["video_kind"]), "Topic title")
    meta = dict(
        chunk_id="kch_1",
        org_id=ORG_A,
        collection_id="kcl_1",
        collection_key="owner_method",
        collection_restricted=fx["collection_restricted"],
        source_id="ksr_1",
    )
    released = frozenset(
        {"kch_1"} if (ap or {}).get("chunk_in_listed_set", True) else {"kch_other"}
    )
    view: ApprovalView | None = None
    if ap is not None:
        sub = ap.get("subject_kind")
        view = ApprovalView(
            "apr_1",
            ORG_A if ap["same_org"] else ORG_B,
            ApprovalKind(ap["kind"]),
            ApprovalState(ap["state"]),
            sub,
            None,
            None,
        )
        if sub == "knowledge_release":
            meta["chunk_release_approval_id"] = "apr_1"
            title = "Topic title" if ap["subject_sha256_matches"] else "Another title"
            view = replace(
                view,
                subject_id="kcl_1" if ap["subject_is_chunk_collection"] else "kcl_x",
                subject_sha256=release_subject_sha256(title, "owner_method", released),
            )
        else:
            meta["source_release_approval_id"] = "apr_1"  # source-level release (the 3A default)
            if sub == "knowledge_source":
                view = replace(
                    view, subject_id="ksr_1" if ap["subject_is_chunk_source"] else "ksr_x"
                )

    class L:
        def approval(self, approval_id: str) -> ApprovalView | None:
            return view

        def released_chunk_ids(self, approval_id: str, collection_id: str) -> frozenset[str]:
            return released

    try:
        res = RestrictedCollectionGate().evaluate(ChunkMeta(**meta), topic, L())
    except CrossTenantRef as exc:
        return {"error": exc.code, "security_event": True}
    out: dict[str, Any] = {
        "allowed": res.allowed,
        "method_labelled": res.method_labelled,
        "restricted_pending": res.restricted_pending,
    }
    if res.reason:
        out["reason"] = res.reason.value
    return out


# ---- TN -----------------------------------------------------------------------------------------
def tn_retrieve(fx: dict[str, Any]) -> dict[str, Any]:
    orgs: dict[str, str] = {}
    chans: dict[str, str] = {}

    def org(name: str) -> str:
        return orgs.setdefault(name, str(ORG.new()))

    def chan(name: str) -> str:
        return chans.setdefault(name, str(CHANNEL.new()))

    lib = InMemoryKnowledgeLibrary()
    rows: Any = fx["rows"]
    if isinstance(rows, str):  # "6 matching chunks from source S1, 2 from S2"
        rows = [{"org": "A", "channel": "A1", "text": "stop loss order", "source": "S1"}] * 6 + [
            {"org": "A", "channel": "A1", "text": "stop loss order", "source": "S2"}
        ] * 2
    cols: dict[tuple[str, str], str] = {}
    srcs: dict[tuple[str, str, str], str] = {}
    for i, r in enumerate(rows):
        o, c = org(r["org"]), chan(r["channel"])
        if (o, c) not in cols:
            cols[(o, c)] = new_id(Prefix.KNOWLEDGE_COLLECTION)
            lib.add_collection(o, c, CollectionView(cols[(o, c)], "general_trading", "t", False))
        skey = (o, c, r.get("source", f"src{i if 'source_status' in r else 0}"))
        if skey not in srcs:
            srcs[skey] = new_id(Prefix.KNOWLEDGE_SOURCE)
            lib.add_source(
                SourceView(
                    srcs[skey],
                    o,
                    c,
                    cols[(o, c)],
                    KnowledgeSourceKind.BOOK,
                    "T",
                    None,
                    None,
                    "en",
                    SourceOwnership.OWNED_COPY,
                    KnowledgeSourceStatus(r.get("source_status", "INDEXED")),
                    1,
                    "ab" * 32,
                    1,
                )
            )
        body = r["text"] + f" variant{i}"
        lib.add_chunk(
            ChunkRow(
                new_id(Prefix.KNOWLEDGE_CHUNK),
                o,
                c,
                srcs[skey],
                cols[(o, c)],
                1,
                i + 1,
                None,
                None,
                1,
                1,
                "en",
                body,
                hashlib.sha256(body.encode()).hexdigest(),
            )
        )
    qo = fx.get("query_org", "A")
    scope = TenantScope(
        org(qo) if qo else "org_none", chan(fx.get("query_channel", "A1")) if qo else "chn_none"
    )
    world = build_world()
    run = make_run(world)
    run.scope = scope
    run.context = replace(run.context, org_id=scope.org_id)
    concept = world_concept()
    own_cols = lib.collections_for_channel(scope)
    allowed = allowed_collections(own_cols, None, concept, VideoKind.GENERAL)
    limits = RetrievalLimits(fx.get("top_k", 10), fx.get("max_per_source", 10), 50)
    res = LibraryRetriever(lib).retrieve(
        run, concept, allowed, TopicFlags(VideoKind.GENERAL, "t"), limits
    )
    inverse_o = {v: k for k, v in orgs.items()}
    inverse_c = {v: k for k, v in chans.items()}
    inverse_s = {v: k[2] for k, v in srcs.items()}
    by_source: dict[str, int] = {}
    for cand in res.candidates:
        by_source[inverse_s[cand.source_id]] = by_source.get(inverse_s[cand.source_id], 0) + 1
    raw = [lib._chunks[c.chunk_id] for c in res.candidates]
    return {
        "returned": [{"org": inverse_o[r.org_id], "channel": inverse_c[r.channel_id]} for r in raw],
        "returned_count": len(raw),
        "returned_by_source": by_source,
    }


def world_concept() -> Any:
    from agent_04_research_knowledge.models.plan import PlannedConcept

    return PlannedConcept.model_validate(
        concept_doc(queries=[{"text": "stop loss order", "language": "en", "purpose": "PRIMARY"}])
    )


def tn_tenant(fx: dict[str, Any]) -> dict[str, Any]:
    w = build_world()
    try:
        if "envelope_org" in fx:
            task = w.task_input()
            TenantGuard(w.directory, w.library).check(
                task, ResearchPackInput.model_validate(w.data()), envelope_org_id=ORG_B
            )
        elif "task_org" in fx:
            ref = {
                "uri": f"amw-blob://{ORG_B if fx['context_ref_uri_org'] == 'B' else 'platform'}/rules/x.json",
                "purpose": "RULE_PACK",
            }
            task = w.task_input(context_refs=[ref])
            TenantGuard(w.directory, w.library).check(
                task, ResearchPackInput.model_validate(w.data())
            )
        else:
            w.library._collections = {
                k: v for k, v in w.library._collections.items() if not v.restricted
            }
            data = w.data(topic={**w.data()["topic"], "video_kind": fx["video_kind"]})
            TenantGuard(w.directory, w.library).check(
                w.task_input(data), ResearchPackInput.model_validate(data)
            )
    except Exception as exc:
        return {"error": err_code(exc), "security_event": isinstance(exc, CrossTenantRef)}
    return {"allowed": True}


def tn_logs(caplog: pytest.LogCaptureFixture) -> dict[str, Any]:
    import logging

    w = build_world()
    with caplog.at_level(logging.DEBUG):
        w.step().run(w.task_input(), ATTEMPT.new())
    text = " ".join(r.getMessage() for r in caplog.records)
    lines = [json.loads(r.getMessage()) for r in caplog.records if r.name == "amw.agent_04"]
    return {
        "chunk_text_in_logs": BODY_1 in text or "advance order" in text,
        "org_id_on_every_line": bool(lines) and all(line.get("org_id") for line in lines),
    }


def tn_prompt() -> dict[str, Any]:
    from agent_04_research_knowledge.prompts import PLAN_PROMPT_ID, PromptLoader
    from tests.agents.agent_04_research_knowledge.conftest import PROMPTS
    from tests.agents.agent_04_research_knowledge.test_contracts_prompts import packs

    a, b = build_world(), build_world()
    loader = PromptLoader(PROMPTS, packs())
    prompt = loader.load(PLAN_PROMPT_ID)
    pa = loader.render(prompt, ("rp.youtube_general", "rp.finance_sebi_in")).system
    pb = loader.render(prompt, ("rp.youtube_general", "rp.finance_sebi_in")).system
    tenant_text = any(t in pa for t in (a.org, b.org, a.channel, b.channel))
    return {"shared_prefix_identical": pa == pb, "tenant_text_in_prefix": tenant_text}


# ---- CG -----------------------------------------------------------------------------------------
def cg(fx: dict[str, Any], case_id: str) -> dict[str, Any]:
    if case_id in ("CG-09", "CG-10"):
        verdict = NoteValidator().validate(
            __import__(
                "tests.agents.agent_04_research_knowledge.test_guards", fromlist=["note"]
            ).note(
                "A cap helps keep one trade small.",
                time_reference_kind=fx["note_time_reference"],
                forward_looking=fx.get("forward_looking", False),
            ),
            "Risk caps keep each trade small over time.",
            "en",
            NOTE_LIMITS,
        )
        return {
            "usable_for_script": verdict.usable,
            "exclusion_reason": verdict.exclusion_reason.value
            if verdict.exclusion_reason
            else None,
        }
    if case_id in ("CG-05", "CG-06", "CG-07", "CG-08"):
        from tests.agents.agent_04_research_knowledge.test_guards import note

        v = NoteValidator().validate(note(fx["note"]), fx["passage"], "en", NOTE_LIMITS)
        return {"pass": v.passed, **({"problem": v.problem.value} if v.problem else {})}
    res = CopyGuard().check(
        fx["note"],
        fx["passage"],
        3,
        0.9,
        max_verbatim_words=fx["max_verbatim_words"],
        note_language=fx.get("note_language", "en"),
        passage_language=fx.get("passage_language", "en"),
    )
    out: dict[str, Any] = {"pass": res.passed}
    if not res.passed:
        out["problem"] = "COPY_OVERLAP"
    if res.skipped_reason:
        out["copy_guard"] = CopyGuardStatus.SKIPPED_CROSS_LANGUAGE.value
    return out


# ---- AS -----------------------------------------------------------------------------------------
class Resolver:
    def __init__(self, chunks: dict[str, str], snaps: dict[str, str]) -> None:
        self.chunks, self.snaps = chunks, snaps

    def chunk_sha256(self, chunk_id: str) -> str | None:
        return self.chunks.get(chunk_id)

    def snapshot_content_sha256(self, snapshot_ref: str) -> str | None:
        return self.snaps.get(snapshot_ref)


def validate_pack(pack: Any, resolver: Resolver) -> list[Any]:
    w = build_world()
    from agent_04_research_knowledge.guards.copy_guard import CopyResult

    passed = {e.evidence_id: CopyResult(0, 0.0, True, None) for e in pack.evidence}
    return PackValidator(resolver).validate(
        pack,
        w.org,
        scope=TenantScope(w.org, w.channel),
        library=InMemoryKnowledgeLibrary(),
        copy_results=passed,
        has_revision=False,
        unclosed_gap_ids=(),
        cross_language_items=0,
        refused=[],
    )


def as_case(fx: dict[str, Any], case_id: str, w_tmp: Path) -> dict[str, Any]:
    B, D = ReliabilityTier.B_PUBLISHED, ReliabilityTier.D_UNVERIFIED
    if case_id == "AS-01":
        r = assemble([concept_ev(["DEFINITION"], [vnote("a", "DEFINITION", B)])])
        return {"coverage": r.pack.concepts[0].coverage.value}
    if case_id == "AS-02":
        r = assemble(
            [concept_ev(["STATISTIC"], [vnote("a", "STATISTIC", D)])], {"ksr_1": source(tier=D)}
        )
        return {"coverage": r.pack.concepts[0].coverage.value, "gap": r.pack.gaps[0].reason.value}
    if case_id in ("AS-03", "AS-04"):
        good = [concept_ev(["DEFINITION"], [vnote("a", "DEFINITION", B)])] if fx["sourced"] else []
        rest = [
            concept_ev(["DEFINITION"], [], f"c{i + 1:02d}")
            for i in range(fx["sourced"], fx["concepts"])
        ]
        r = assemble(good + rest)
        try:
            PackAssembler.require_usable(r)
        except InsufficientInput as exc:
            return {"task_status": "FAILED", "error": exc.code}
        second = r.pack.concepts[1]
        results = validate_pack(r.pack, Resolver({"kch_a": "cd" * 32}, {}))
        cov = next(x for x in results if x.check_id == "a04.coverage")
        return {
            "coverage_second": second.coverage.value,
            "gap": r.pack.gaps[0].reason.value,
            "task_status": "SUCCEEDED",
            "validation": {"research.coverage": cov.verdict.value},
        }
    if case_id == "AS-05":
        r = assemble(
            [concept_ev(["DEFINITION"], [], restricted_blocked=True)],
            restricted_pending={"owner_method": ["c01"]},
        )
        return {
            "coverage": r.pack.concepts[0].coverage.value,
            "gap": r.pack.gaps[0].reason.value,
            "restricted_pending_nonempty": bool(r.pack.method.restricted_pending),
        }
    if case_id == "AS-06":
        ext_note = vnote("b", "DEFINITION", B, cite="ext_" + "a" * 24)
        r = assemble(
            [
                concept_ev(
                    ["DEFINITION"], [vnote("a", "DEFINITION", B, cite="kch_" + "0" * 36), ext_note]
                )
            ],
            {"ksr_1": source(), "ksr_2": source("ksr_2")},
        )
        refs = [c.citation_ref for c in r.pack.citations_available]
        assert max(len(x) for x in refs) <= 64
        return {
            "citation_ref_max_len": 64,
            "citation_ref_unique": len(set(refs)) == len(refs),
            "chunk_ref_prefix": next(x for x in refs if x.startswith("kch_"))[:4],
            "external_ref_prefix": next(x for x in refs if x.startswith("ext_"))[:4],
        }
    if case_id in ("AS-07", "AS-08", "AS-10"):
        sha = "cd" * 32
        if case_id == "AS-10":
            ext = "ext_" + "a" * 24
            e_src = source(
                ext,
                D,
                kind=KnowledgeSourceKind.WEB_REFERENCE,
                ownership=None,
                content_sha256=sha,
                snapshot_ref="amw-blob://" + ORG_A + "/evidence/j/x.json",
                external_url="https://example.org/a",
            )
            vn = vnote("a", "DEFINITION", D, cite=ext)
            vn = replace(vn, passage=replace(vn.passage, source_ref=ext))
            r = assemble([concept_ev(["DEFINITION"], [vn])], {ext: e_src}, min_tier_for_factual=D)
            resolver = Resolver({}, {})
        else:
            r = assemble([concept_ev(["DEFINITION"], [vnote("a", "DEFINITION", B)])])
            resolver = Resolver({"kch_a": sha} if case_id == "AS-07" else {}, {})
        results = validate_pack(r.pack, resolver)
        failing = [
            x.check_id
            for x in results
            if x.blocking and x.verdict is CheckVerdict.FAIL and x.check_id != "a04.tenant_scope"
        ]
        return {
            "blocking_checks_pass": not failing,
            **({"failed_check": failing[0]} if failing else {}),
        }
    if case_id == "AS-09":
        ext = "ext_" + "b" * 24
        gone = source(
            ext,
            D,
            kind=KnowledgeSourceKind.WEB_REFERENCE,
            ownership=None,
            fetch_status=FetchStatus.UNREACHABLE,
            content_sha256=None,
            external_url="https://example.org/x",
        )
        r = assemble([concept_ev(["DEFINITION"], [])], {ext: gone})
        row = r.pack.sources[0]
        return {
            "coverage": r.pack.concepts[0].coverage.value,
            "gap": r.pack.gaps[0].reason.value,
            "source_row": {
                "fetch_status": row.fetch_status.value,
                "content_sha256": row.content_sha256,
                "snapshot_ref": row.snapshot_ref,
            },
            "in_citations_available": bool(r.pack.citations_available),
        }
    if case_id == "AS-11":
        refusal = {
            "concepts": [],
            "out_of_scope_notes": [],
            "refusal": {
                "reason": "RULE_WOULD_BE_BROKEN",
                "message": "m",
                "missing_inputs": [],
                "violated_rule_ids": fx["violated_rule_ids"],
            },
        }
        w = build_world(lambda _r: json.dumps(refusal))
        out = w.step().run(w.task_input(), ATTEMPT.new())
        gate = next(x for x in out.validation_results if x.gate)
        return {
            "task_status": out.status.value,
            "concepts": list((out.payload.data or {}).get("concepts", [None]))
            if out.payload
            else None,
            "gate_result": {
                "check_id": gate.check_id,
                "gate": gate.gate,
                "blocking": gate.blocking,
                "verdict": gate.verdict.value,
                "rule_id": gate.rule_id,
            },
            "next_action_type": out.next_action.type.value,
        }
    if case_id == "AS-12":
        from tests.agents.agent_04_research_knowledge.test_guards import note

        verdict = NoteValidator().validate(
            note("A stop-loss closes the trade automatically at a preset level."),
            "स्टॉप-लॉस म्हणजे किंमत ठरावीक पातळीवर आली की व्यवहार बंद करणारी ऑर्डर.",
            "mr",
            NOTE_LIMITS,
        )
        vn = vnote("a", "DEFINITION", B, guard=verdict.copy_guard_status)
        vn = replace(vn, copy_guard=verdict.copy_guard_status)
        r = assemble([concept_ev(["DEFINITION"], [vn])])
        res = PackValidator(Resolver({"kch_a": "cd" * 32}, {})).validate(
            r.pack,
            ORG_A,
            scope=TenantScope(ORG_A, "chn_x"),
            library=InMemoryKnowledgeLibrary(),
            copy_results={},
            has_revision=False,
            unclosed_gap_ids=(),
            cross_language_items=r.cross_language_items,
            refused=[],
        )
        cl = next(x for x in res if x.check_id == "a04.copy_guard_cross_language")
        return {
            "evidence_copy_guard": r.pack.evidence[0].copy_guard.value,
            "validation": {cl.check_id: cl.verdict.value},
            "blocking": cl.blocking,
        }
    raise AssertionError(case_id)


# ---- FL -----------------------------------------------------------------------------------------
def fl(fx: dict[str, Any], case_id: str, tmp: Path) -> dict[str, Any]:
    w = build_world()

    def run(ww: Any = None, **k: Any) -> Any:
        target = ww or w
        return target.step().run(target.task_input(**k), ATTEMPT.new())

    if case_id == "FL-01":
        a = task_key(w.org, w.job, fx["iteration_a"])
        same = task_key(w.org, w.job, fx["iteration_a"])
        b = task_key(w.org, w.job, fx["iteration_b"])
        manual = make_idempotency_key(
            w.org,
            "task.agent_04.research_pack",
            [w.job, fx["stage_id"], "agent_04.research_pack", fx["iteration_a"]],
        )
        return {
            "keys_equal_for_same_iteration": a == same == manual,
            "keys_differ_across_iterations": a != b,
            "key_parts": ["job_id", "stage_id", "task_type", "iteration"],
        }
    if case_id == "FL-02":
        w.budget.exhausted_after = 0
        out = run()
        return {
            "task_status": out.status.value,
            "wait_reason": out.next_action.wait_reason.value
            if out.next_action.wait_reason
            else None,
            "error": out.error.code if out.error else None,
            "llm_calls": len(w.llm.requests),
        }
    if case_id == "FL-03":
        ww = build_world(lambda _r: "not json")
        out = run(ww)
        return {
            "retries": len(ww.llm.requests) - 1,
            "error": out.error.code if out.error else None,
            "next": "DEAD_LETTER" if "dead letter" in out.next_action.reason else "RETRY",
        }
    if case_id in ("FL-04", "FL-10"):
        exc = (
            AuthInvalidError("401")
            if case_id == "FL-04"
            else Upstream5xxError("503", upstream_status=503)
        )
        w.llm.engine.failures = FailurePlan(sequence=[exc])
        out = run()
        keep = bool(w.checkpoints._rows)
        return {
            "error": out.error.code if out.error else None,
            "task_state": "RETRY_WAIT"
            if out.next_action.type is NextActionType.RETRY
            else "FAILED",
            "checkpoint_kept": keep,
        }
    if case_id == "FL-05":
        got = fetcher(w, web_with(tmp, fx["http_status"])).fetch(
            make_run(w), "r1", "https://example.org/a", "en"
        )
        return {
            "fetch_status": got.status.value,
            "content_sha256": got.content_sha256,
            "snapshot_ref": None,
            "task_failed": False,
            "gap_if_sole_source": "NO_SOURCE_FOUND",
        }
    if case_id == "FL-06":
        web = FakeWebFetchAdapter(
            allowed_hosts=frozenset({"example.org"}),
            failures=FailurePlan(
                sequence=[RateLimitedError("slow", retry_after_ms=fx["retry_after_ms"])]
            ),
        )
        try:
            fetcher(w, web).fetch(make_run(w), "r1", "https://example.org/a", "en")
        except RateLimitedError as exc:
            return {"error": exc.code, "retry_after_ms": exc.retry_after_ms}
        return {}
    if case_id == "FL-07":
        plan = ResearchPlan.model_validate(
            {
                "concepts": [concept_doc(wants_method_material=True)],
                "out_of_scope_notes": [],
                "refusal": None,
            }
        )
        found = PlanValidator().validate(plan, plan_input())
        return {
            "pass": not found,
            "check": found[0].check,
            "action": "re-ask once, then AGENT.OUTPUT_SCHEMA_INVALID",
        }
    if case_id == "FL-08":
        w.budget.exhausted_after = 1
        run()
        w.budget.exhausted_after = None
        run()
        plan_calls = sum(1 for r in w.llm.requests if "topic_title" in user_payload(r))
        return {"resume_from": "S2", "plan_llm_calls_total": plan_calls}
    if case_id == "FL-09":
        same_url = fetch_key(w.org, fx["task_id"], fx["ref_id"], "https://example.org/a")
        return {
            "keys_equal_for_same_url": same_url
            == fetch_key(w.org, fx["task_id"], fx["ref_id"], "https://example.org/a"),
            "keys_differ_for_other_url": same_url
            != fetch_key(w.org, fx["task_id"], fx["ref_id"], "https://example.org/b"),
            "key_parts": ["task_id", "ref_id", "url_sha256"],
        }
    if case_id == "FL-11":
        bad = w.data(
            owner_references=[
                {"kind": "EXTERNAL_URL", "url": None, "knowledge_source_id": None, "note": None}
            ]
        )
        out = w.step().run(w.task_input(bad), ATTEMPT.new())
        return {"error": out.error.code if out.error else None, "llm_calls": len(w.llm.requests)}
    if case_id == "FL-12":
        try:
            fetcher(w).fetch(make_run(w), "r1", "https://10.0.0.5/a", "en")
        except InputInvalid as exc:
            return {"error": exc.code, "snapshot_written": bool(w.storage.blobs)}
        return {}
    raise AssertionError(case_id)


# ---- driver -------------------------------------------------------------------------------------
def run_case(case: dict[str, Any], tmp: Path, caplog: pytest.LogCaptureFixture) -> dict[str, Any]:
    cid, fx = case["case_id"], case["input"]["fixture"]
    prefix = cid[:2]
    if prefix == "RT":
        return rt(fx)
    if prefix == "RG":
        return rg(fx)
    if prefix == "TN":
        if cid in ("TN-01", "TN-02", "TN-03", "TN-04", "TN-05"):
            return tn_retrieve(fx)
        if cid == "TN-09":
            return tn_logs(caplog)
        if cid == "TN-10":
            return tn_prompt()
        return tn_tenant(fx)
    if prefix == "CG":
        return cg(fx, cid)
    if prefix == "AS":
        return as_case(fx, cid, tmp)
    return fl(fx, cid, tmp)


def compare(expected: dict[str, Any], got: dict[str, Any]) -> None:
    for key, want in expected.items():
        assert key in got, f"result lacks {key}: {got}"
        if isinstance(want, dict) and isinstance(got[key], dict):
            compare(want, got[key])
        else:
            assert got[key] == want, f"{key}: expected {want!r}, got {got[key]!r}"


@pytest.mark.unit
@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_deterministic_core_case(
    case: dict[str, Any], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    compare(case["expected"], run_case(case, tmp_path, caplog))


def test_dataset_is_the_documented_69() -> None:
    assert len(CASES) == 69
    counts = {
        p: sum(1 for c in CASES if c["case_id"].startswith(p))
        for p in ("RT", "RG", "TN", "CG", "AS", "FL")
    }
    assert counts == {"RT": 12, "RG": 12, "TN": 11, "CG": 10, "AS": 12, "FL": 12}
