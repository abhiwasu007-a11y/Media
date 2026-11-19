# ruff: noqa: E501
# mypy: disable-error-code="arg-type,attr-defined,assignment,index,misc,var-annotated"
# (glue between the agents' own test doubles, which type the same ports differently; no logic here)
"""The REAL-agent dry-run world (plumbing only: PLUMBING TEST - NOT QUALITY; no paid call).

Each real agent entry point (04, 05, 06, 07, 08, 09, 10, 11, 16, 13) is built from the agent's OWN
test fakes (fake LLM returning the agent's canned model response, fake TTS, in-memory ports), over
ONE shared ``LocalDiskStorage`` (the real write-once backend) and tenant IDs taken from the Task
Input the real ``amw_orchestrator`` driver hands over. Workers are built lazily on their first Task
Input, so the world carries the tenant, channel and project of the job under run.

Nothing here invents a contract: where a port has no production implementation yet, the in-memory
adapter lives in this file and reads ONLY what the Task Input and its context refs carry.
"""

import dataclasses
import hashlib
import io
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from amw_core.contracts import TaskInput, TaskOutput
from amw_core.exec_context import ExecContext
from amw_core.interfaces import TaskWorker
from amw_core.interfaces.storage import BlobUri
from amw_core.storage.local import LocalDiskStorage


@dataclass(frozen=True)
class Tenant:
    org: str
    channel: str
    project: str
    job: str
    shared: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)
    """State the real agents of ONE job share through their ports (the library of agent_04, the
    script rows of agent_05, the claim rows of agent_06): in production these are PostgreSQL tables."""


WorkerFactory = Callable[[Tenant, LocalDiskStorage, Path], TaskWorker]


class LazyWorker:
    """Builds the real worker on its first Task Input (tenant from the input, not from a guess)."""

    def __init__(
        self,
        name: str,
        factory: WorkerFactory,
        storage: LocalDiskStorage,
        scratch: Path,
        shared: dict[str, Any],
    ) -> None:
        self.name, self._factory, self._storage, self._scratch = name, factory, storage, scratch
        self._shared = shared
        self._worker: TaskWorker | None = None
        self.calls = 0
        self.last_input: TaskInput | None = None
        self.last_output: TaskOutput | None = None

    def run(self, task_input: TaskInput, ctx: ExecContext) -> TaskOutput:
        if self._worker is None:
            tenant = Tenant(
                task_input.org_id,
                str(task_input.channel_id),
                str(task_input.project_id),
                task_input.job_id,
                self._shared,
            )
            self._shared["first_input"] = task_input
            self._worker = self._factory(tenant, self._storage, self._scratch)
        self.calls += 1
        self.last_input = task_input
        out = self._worker.run(task_input, ctx)
        if os.environ.get("DRYRUN_TRACE"):
            for r in out.output_refs:
                print("REF", self.name, r.kind.value, r.uri.split("/jobs/", 1)[-1][-90:])
        self.last_output = out
        return out


SYN_1 = "Time is a finite resource that a person spends every day. Many people postpone living until a later time."
SYN_2 = "Busy people often confuse activity with living. A short list of chosen priorities protects attention and time."
"""INVENTED synthetic chunk bodies (NOT book text, D12)."""


def responder_04(request: Any, queries_language: str | None = None) -> str:
    """The agent's own canned-response shape (plan JSON / notes JSON) over the synthetic content."""
    import json

    from tests.agents.agent_04_research_knowledge.conftest import user_payload

    payload = user_payload(request)
    if "topic_title" in payload:
        concept = {
            "concept_id": "c01", "label": "finite time", "label_en": "finite time",
            "kind": "CORE_CONCEPT", "rationale": "needed", "evidence_needs": ["DEFINITION"],
            "time_reference": "TIMELESS",
            "queries": [{"text": "time", "language": queries_language or payload["video_language"].split("-")[0], "purpose": "PRIMARY"}],
            "wants_method_material": False, "closes_gap_ids": [], "target_collection_keys": [],
        }  # fmt: skip
        return json.dumps({"concepts": [concept], "out_of_scope_notes": [], "refusal": None})
    notes, assess = [], []
    for i, p in enumerate(payload["passages"], start=1):
        relevant = "time" in p["text"].lower()
        assess.append(
            {
                "passage_id": p["passage_id"],
                "relevance": "RELEVANT" if relevant else "IRRELEVANT",
                "reason": "checked",
            }
        )
        if relevant:
            notes.append({
                "note_ref": f"n{i}", "passage_id": p["passage_id"],
                "statement_kind": payload["concept"]["evidence_needs"][0],
                "note": "A day is a limited amount of time that each person has to choose how to use.",
                "time_reference_kind": "TIMELESS", "instruments": [], "numbers_in_note": [],
                "clarity": "CLEAR", "forward_looking": False,
            })  # fmt: skip
    return json.dumps(
        {"assessments": assess, "notes": notes, "excluded_statements": [], "refusal": None}
    )


def build_agent_04(t: Tenant, storage: LocalDiskStorage, scratch: Path) -> TaskWorker:
    """Agent 04 over its own fakes (scripted LLM = the agent's canned plan/notes responder, in-memory
    library holding two INVENTED chunks, fake web adapter), real storage."""
    import dataclasses

    from agent_04_research_knowledge.guards.tenant import ChannelRecord
    from agent_04_research_knowledge.steps.research_pack import ResearchPackStep, ResolverFactory
    from tests.agents.agent_04_research_knowledge.conftest import build_world

    w = build_world()
    w.directory.channels[(t.org, t.channel)] = ChannelRecord(t.org, t.channel, True)
    w.directory.workspaces[(t.org, t.project)] = "wsp_x"
    # re-home the seeded library on this tenant
    from agent_04_research_knowledge.library.memory import InMemoryKnowledgeLibrary

    lib = InMemoryKnowledgeLibrary()
    w.library = lib
    w.org, w.channel = t.org, t.channel
    from agent_04_research_knowledge.library.models import CollectionView
    from amw_core.ids import Prefix, new_id

    w.collections, w.sources, w.chunks = {}, {}, []
    for key, restricted in (("general_trading", False), ("owner_method", True)):
        cid = new_id(Prefix.KNOWLEDGE_COLLECTION)
        lib.add_collection(t.org, t.channel, CollectionView(cid, key, key, restricted))
        w.collections[key] = cid
    w.add_source("general_trading")
    w.add_chunk(SYN_1)
    w.add_chunk(SYN_2)
    t.shared["lib04"] = lib
    t.shared["collection04"] = w.collections["general_trading"]
    w.llm.responder = lambda req: responder_04(req, t.shared.get("queries_language"))
    deps = dataclasses.replace(
        w.deps, library=lib, storage=storage, resolver_factory=ResolverFactory(lib, storage)
    )
    return ResearchPackStep(deps)


def read_ref(storage: LocalDiskStorage, org: str, uri: str, sha256: str) -> Any:
    """Hash-verified JSON read of a context ref (what an ``InputResolver`` does for a document)."""
    import json

    from amw_core.interfaces import TenantContext
    from amw_core.interfaces.storage import BlobUri

    ctx = TenantContext(org, "agent_05", None)
    return json.loads(b"".join(storage.get(ctx, BlobUri(uri), sha256)))


class Resolver05:
    """In-memory ``InputResolver`` of agent_05 (the production one is not written yet): the research
    pack and the prior/parent script are READ from storage through the context refs (hash-verified,
    parsed by agent_05's own view models); rule packs, profile and brand kit have no registered
    document schema, so their content is a fixed test table keyed by the ref purpose."""

    def __init__(self, storage: LocalDiskStorage) -> None:
        self.storage = storage

    def resolve(self, ctx: Any, task_input: TaskInput, data: Any) -> Any:
        from agent_05_scriptwriter.pre.brief_mapper import ResearchPackView
        from agent_05_scriptwriter.pre.tenant_guard import RefFact, TenantFacts
        from agent_05_scriptwriter.protocols import RulePack
        from amw_core import ids
        from amw_core.tenancy.storage_paths import uri_owner
        from tests.agents.agent_05_scriptwriter import support as sp

        refs = []
        pack = None
        for r in task_input.context_refs:
            refs.append(RefFact(r.purpose.value, uri_owner(r.uri), None, True))
            if r.purpose.value == "PRIOR_OUTPUT" and (r.schema_ or "").startswith("agent_04."):
                pack = ResearchPackView.model_validate(
                    read_ref(self.storage, ctx.org_id, r.uri, r.sha256)
                )
        packs = {
            "rp.youtube_general": RulePack(
                "rp.youtube_general", "v1", "PLATFORM RULES YT", "PLATFORM"
            ),
        }
        return sp.ResolvedInputs(
            tenant=TenantFacts(
                ctx.org_id, ctx.org_id, ctx.org_id, ctx.org_id, "ACTIVE", refs, ctx.channel_id
            ),
            rule_packs=packs,
            profile_rule_packs=["rp.youtube_general"],
            lexicons=sp.LEX_TEST_V1,
            new_script_id=ids.new_id(ids.Prefix.SCRIPT),
            pack=pack,
            brand_latin_allow_list=[],
            disclaimer_template=None,
        )


def _llm05_cls() -> Any:
    from tests.agents.agent_05_scriptwriter import support as sp

    class Llm05(sp.ScriptedLlm):
        """agent_05's own canned model responses; each call is answered by step (plan vs section)
        from the request's own input, and every request is recorded for the report."""

        def _text(self, scripted: Any, request: Any) -> str:
            import json

            body = sp.user_input(request)
            if "section_plan" in body:
                return json.dumps(sp.section_json(body))
            plan = sp.plan_json(self.n, key=body["concept_briefs"][0]["term_local"])
            brief_refs = {b["concept_id"]: b["citation_refs"] for b in body["concept_briefs"]}
            known = set(brief_refs)
            plan["concept_plan"] = [c for c in plan["concept_plan"] if c["concept_id"] in known]
            for c in plan["concept_plan"]:
                c["citation_refs"] = brief_refs[c["concept_id"]][:1]
            plan["omitted_concepts"] = [
                o for o in plan["omitted_concepts"] if o["concept_id"] in known
            ]
            for sec in plan["sections"]:
                sec["concept_ids"] = [k for k in sec["concept_ids"] if k in known]
            for h in plan["hooks"]:
                for b in h["beats"]:
                    b["chart_request"] = None
            return json.dumps(plan)

    return Llm05


def build_agent_05(t: Tenant, storage: LocalDiskStorage, scratch: Path) -> TaskWorker:
    from agent_05_scriptwriter import ScriptDraftStage, ScriptDraftStep, ScriptRepository
    from tests.agents.agent_05_scriptwriter import support as sp
    from tests.agents.agent_05_scriptwriter.test_entry_point import Clock, Rows

    st = sp.MemoryState()
    ports = sp.make_ports(st)
    rows = Rows()
    t.shared["rows05"] = rows
    ports.scripts = ScriptRepository(storage, rows)
    llm = _llm05_cls()(["VALID_PLAN", "VALID_SECTIONS"], 2)
    step = ScriptDraftStep(llm, ports, sp.make_settings(), sp.prompts(), sp.scanners_for)
    return ScriptDraftStage(step, Resolver05(storage), storage, Clock())


class Scripts06:
    """``ScriptRegistry`` over the script rows agent_05 wrote (shared in-memory ``Rows``)."""

    def __init__(self, rows: Any) -> None:
        self.rows = rows

    def content_sha256(self, tx: Any, *, script_id: str, script_version: int) -> str | None:
        for saved in self.rows.rows.values():
            if saved.script_id == script_id and saved.version == script_version:
                return str(saved.sha256)
        return None


class Knowledge06:
    """``KnowledgeReader`` over agent_04's in-memory library (chunk text read by code)."""

    def __init__(self, lib: Any, org: str, channel: str) -> None:
        self.lib, self.scope = lib, (org, channel)

    def get_source(self, tx: Any, channel_id: str, citation_ref: str) -> Any:
        from agent_04_research_knowledge.library.models import TenantScope
        from agent_06_fact_checker.models import CitationKind
        from agent_06_fact_checker.ports import SourceText

        rows = self.lib.load_chunks(TenantScope(*self.scope), [citation_ref])
        if not rows:
            return None
        r = rows[0]
        return SourceText(
            citation_ref, CitationKind.KNOWLEDGE_CHUNK, r.body, r.body_sha256, "B_PUBLISHED", False
        )

    def search(self, tx: Any, channel_id: str, query: str, top_k: int) -> list[Any]:
        return []


def _llm06_cls() -> Any:
    import json
    import re

    from agent_06_fact_checker.hashing import sha256_hex  # noqa: F401
    from tests.agents.agent_06_fact_checker.support import RecordedLlm

    inp = re.compile(r"<<<INPUT\n(.*)\nINPUT>>>", re.DOTALL)

    class Llm06(RecordedLlm):
        """agent_06's own recorded-response shape, answered from the rendered request."""

        def __init__(self) -> None:
            super().__init__([])
            self.bodies: list[dict[str, Any]] = []

        def complete(self, request: Any, *, idempotency_key: str) -> Any:
            match = inp.search(request.messages[0].content)
            assert match, "one INPUT block"
            body = json.loads(match.group(1))
            self.bodies.append(body)
            self.texts = [self.respond(body)]
            return super().complete(request, idempotency_key=idempotency_key)

        @staticmethod
        def respond(body: dict[str, Any]) -> str:
            raise NotImplementedError

    return Llm06


def build_agent_06_extraction(t: Tenant, storage: LocalDiskStorage, scratch: Path) -> TaskWorker:
    import json

    from agent_06_fact_checker.extraction_step import ClaimExtractionStep
    from tests.agents.agent_06_fact_checker import support as sp

    class Extract(_llm06_cls()):
        @staticmethod
        def respond(body: dict[str, Any]) -> str:
            claims = []
            for seg in body["segments"]:
                if not seg.get("citation_refs") or claims:
                    continue
                text = seg["text"]
                claims.append({
                    "local_id": "c1", "segment_id": seg["segment_id"], "char_start": 0,
                    "char_end": len(text), "quote": text, "normalized_claim": text.rstrip("."),
                    "claim_type": "DEFINITION", "time_reference_kind": "TIMELESS",
                    "instrument": None, "chart_data_ref": None, "requires_citation": True,
                    "citation_refs": list(seg["citation_refs"]), "rule_flags": [],
                    "proposed_verdict": "ALLOWED", "rationale": "an invented plain statement",
                })  # fmt: skip
            overall = {
                "proposed_verdict": "ALLOWED",
                "blocking_rule_ids": [],
                "needs_human_review_reasons": [],
            }
            return json.dumps({"claims": claims, "overall": overall, "refusal": None})

    world = shared06(t, storage, Extract())
    return ClaimExtractionStep(
        llm=world.llm, budget=world.budget, ledger=world.ledger, tenancy=world.tenancy,
        clock=world.clock, blobs=storage, checkpoints=world.checkpoints, audit=world.audit,
        claims=world.claims, scripts=Scripts06(t.shared["rows05"]), chart_ranges=sp.FixedRanges(),
        rule_packs=sp.StaticPacks(), prompts=sp.DocPrompts(), settings=sp.make_settings(),
    )  # fmt: skip


def build_agent_06_verification(t: Tenant, storage: LocalDiskStorage, scratch: Path) -> TaskWorker:
    import json

    from agent_06_fact_checker.verification_step import ClaimVerificationStep
    from tests.agents.agent_06_fact_checker import support as sp

    class Verify(_llm06_cls()):
        @staticmethod
        def respond(body: dict[str, Any]) -> str:
            by_id = {p["evidence_id"]: p["text"] for p in body["passages"]}
            results = []
            for c in body["claims"]:
                ev = c["script_cited_evidence_ids"] or c["candidate_evidence_ids"]
                evidence = [
                    {
                        "evidence_id": e,
                        "relation": "SUPPORTS",
                        "span_start": 0,
                        "span_end": min(len(by_id[e]), 100),
                    }
                    for e in ev[:1]
                ]
                results.append({
                    "local_id": c["local_id"], "assessment": "SUPPORTED", "evidence": evidence,
                    "discrepancies": [], "certainty": "HIGH", "suggested_correction": None,
                    "rationale": "the cited passage states the same idea",
                })  # fmt: skip
            return json.dumps(
                {"results": results, "claim_conflicts": [], "passage_flags": [], "refusal": None}
            )

    world = shared06(t, storage, Verify())
    return ClaimVerificationStep(
        llm=world.llm, budget=world.budget, ledger=world.ledger, tenancy=world.tenancy,
        clock=world.clock, blobs=storage, checkpoints=world.checkpoints, audit=world.audit,
        claims=world.claims, scripts=Scripts06(t.shared["rows05"]),
        knowledge=Knowledge06(t.shared["lib04"], t.org, t.channel),
        prompts=sp.DocPrompts(), settings=sp.make_settings(),
    )  # fmt: skip


def shared06(t: Tenant, storage: LocalDiskStorage, llm: Any) -> Any:
    """ONE agent_06 world per job: both steps share the claim rows (the ``claims`` table)."""
    from tests.agents.agent_06_fact_checker import support as sp

    class Claims06(sp.MemoryClaims):
        def __init__(self) -> None:
            super().__init__()
            self.extracted: dict[str, Any] = {}

        """The ``claims`` table keeps the stored extraction verdict of each inserted claim (the
        agent's test double only learns it from ``register_extraction``)."""

        def insert_claims(self, tx: Any, *, script_id: str, task_id: Any, claims: Any) -> Any:
            ids = super().insert_claims(tx, script_id=script_id, task_id=task_id, claims=claims)
            for c in claims:
                self.verdicts[ids[c.local_id]] = c.proposed_verdict
                self.extracted[ids[c.local_id]] = c
            return ids

    if "w06" not in t.shared:
        w = sp.World(llm=llm, claims=Claims06())
        w.blobs = storage
        t.shared["w06"] = w
    w06: Any = t.shared["w06"]
    w06.llm = llm
    return w06


def build_agent_07_voice(t: Tenant, storage: LocalDiskStorage, scratch: Path) -> TaskWorker:
    """Agent 07 voice synthesis: fake TTS (a tone), the agent's own in-memory facts / registry /
    ledger doubles, real storage. The voice, licence and dictionary asset are facts of the job."""
    from typing import cast

    from agent_07_voice_production.ports import AssetFacts, LicenceFacts, VoiceBundle
    from agent_07_voice_production.voice_stage import VoiceDeps, VoiceSynthesisStage
    from amw_core.enums import (
        AssetStatus,
        LicenceSourceType,
        LicenceState,
        PresenterKind,
        ThirdPartyPermission,
        VoiceKind,
    )
    from amw_core.ids import Prefix, new_id
    from amw_core.interfaces.voices import VoiceRecord
    from amw_core.testing.memory import MemoryCheckpointStore, MemoryIdempotencyStore
    from tests.agents.agent_07_voice_production import support as sp

    data = t.shared["first_input"].payload.data
    voice_id, dict_uri, dict_sha = (
        data["voice_id"],
        data["dictionary_ref"],
        data["dictionary_sha256"],
    )
    language = data["language"]
    licence = LicenceFacts(
        new_id(Prefix.LICENCE), t.org, LicenceState.ACTIVE, LicenceSourceType.TTS_PROVIDER, True,
        ThirdPartyPermission.PERMITTED,
    )  # fmt: skip
    voice = VoiceRecord(
        voice_id, t.org, "test voice", VoiceKind.PROVIDER_STOCK, "fake_tts", "fake-neutral-1",
        (language,), None, None, licence.licence_id, PresenterKind.NEUTRAL_NARRATION, AssetStatus.ACTIVE,
    )  # fmt: skip
    assets = {
        dict_uri: AssetFacts(new_id(Prefix.ASSET), t.org, "DOCUMENT", True, (t.channel,), dict_sha)
    }
    facts = sp.FakeFacts(
        script_hash=None, approval_facts=None, bundle=VoiceBundle(voice, licence, None, False),
        brand_kit_voice=voice_id, monetized=True, platform_owner=True, assets=assets,
    )  # fmt: skip
    t.shared["facts07"] = facts
    caps = sp.capabilities(languages=(language,))
    tts = sp.ToneTts(ms_per_char=50)
    cfg = sp.config(
        gap_ms=300, trim_keep_ms=0, price_micros_per_1k_chars=80000, sample_max_segments=2
    )
    deps = VoiceDeps(
        config=cfg, tts=sp.ViewOf(tts, caps), storage=storage, tenancy=sp.MemoryTenancy(),
        idempotency=MemoryIdempotencyStore(), ledger=cast(Any, sp.MemoryLedger()),
        budget=cast(Any, sp.FakeBudget(provider_row=True, reservation_micros=50_000_000)),
        breaker=sp.FakeBreaker(open_=False), checkpoints=MemoryCheckpointStore(), facts=facts,
        registry=sp.FakeRegistry(), tools=sp.PcmTools(), clock=sp.FakeClock(),
        control=sp.FakeControl(), scratch_root=scratch, sleep=lambda _s: None,
    )  # fmt: skip
    return _FactsRefresh07(VoiceSynthesisStage(deps), facts, t.shared["rows05"])


def build_agent_07_master(t: Tenant, storage: LocalDiskStorage, scratch: Path) -> TaskWorker:
    """Agent 07 audio master over the agent's own descriptor-driven FFmpeg stub (no ffmpeg run)."""
    import json

    from agent_07_voice_production.master_stage import AudioMasterStage, MasterDeps
    from amw_core.testing.memory import MemoryCheckpointStore
    from tests.agents.agent_07_voice_production import support as sp
    from tests.agents.agent_07_voice_production.master_world import StubFfmpeg

    case = json.loads(
        (Path(__file__).resolve().parents[2] / "docs/v4/evals/agent_07_voice_production/audio_master/cases.jsonl")
        .read_text().splitlines()[0]
    )  # fmt: skip
    fx = case["input"]["fixtures"]
    cm, cfgx = fx["codec_model"], fx["config"]
    d = t.shared["first_input"].payload.data
    timeline = read_ref(storage, t.org, d["timeline_ref"], d["timeline_sha256"])
    stem = {
        **fx["stem"],
        "duration_ms": timeline["total_duration_ms"],
    }  # the stub measures a descriptor
    ffmpeg = StubFfmpeg(stem, list(cm["post_codec_true_peak_overshoot_db"]), cm["bitrate_bps"], [])
    keys = ("target_lufs", "true_peak_max_dbtp", "tolerance_lu", "max_passes", "limiter_ceiling_dbtp",
            "codec_headroom_step_db", "max_limiter_reduction_db", "max_silence_ms", "music_enabled",
            "min_bitrate_bps", "denoise_mode")  # fmt: skip
    deps = MasterDeps(
        config=sp.config(**{k: cfgx[k] for k in keys}), storage=storage, tenancy=sp.MemoryTenancy(),
        checkpoints=MemoryCheckpointStore(), facts=t.shared["facts07"], tools=ffmpeg, backend=ffmpeg,
        clock=sp.FakeClock(), control=sp.FakeControl(), scratch_root=scratch,
    )  # fmt: skip
    return AudioMasterStage(deps)


class Ports09:
    """``PlanInputPorts`` (CCR-267 provisional port; no production implementation yet): the brand kit
    is read from the document the builder referenced (hash-verified), gate facts and rule pack text
    are fixed test values."""

    def __init__(self, storage: LocalDiskStorage) -> None:
        self.storage = storage

    def brand_kit(self, tenant: Any, ref: Any) -> Any:
        return read_ref(self.storage, str(tenant.org_id), ref.uri, ref.sha256)

    def gate_facts(self, tenant: Any, **_: Any) -> Any:
        from agent_09_video_director.protocol import GateFacts

        return GateFacts(approval_approved=False, claim_blocked=False, script_status="APPROVED")

    def rule_pack(self, tenant: Any, key: str) -> Any:
        from agent_09_video_director.protocol import RulePackText

        return RulePackText(text=f"{key} RULES", version="1")


def build_agent_09(t: Tenant, storage: LocalDiskStorage, scratch: Path) -> TaskWorker:
    from agent_09_video_director.protocol import ShotPlanTask
    from tests.agents.agent_09_video_director.support import make_step
    from tests.agents.agent_09_video_director.test_entry_point import Clock

    step = make_step()[0]
    return ShotPlanTask(step, storage, Ports09(storage), Clock(), worst_case_call_micros=1000)


def tiny_png(n: int) -> bytes:
    """A valid 1x1 PNG whose pixel depends on ``n`` (distinct bytes, so distinct SHA-256)."""
    import struct
    import zlib

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    raw = b"\x00" + bytes([n * 20 % 256, 80, 160])
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def build_agent_08(t: Tenant, storage: LocalDiskStorage, scratch: Path) -> TaskWorker:
    """Agent 08 over its own in-memory repositories (one World re-keyed on this tenant: standing
    licences, the platform template assets), real storage; the brand kit and job destination ports
    have no production implementation yet (in-memory readers below)."""
    from agent_08_visual_assets.stage import AssetSourcingStage, BrandKit
    from amw_core.enums import LicenceSourceType
    from amw_core.interfaces.tenancy_context import TenantContext
    from amw_core.testing.memory import MemoryTransaction
    from tests.agents.agent_08_visual_assets.fixtures import (
        PALETTE,
        FakeTenancy,
        FixedClock,
        World,
        lic,
        settings,
    )

    w = World.__new__(World)
    w.org = t.org
    w.ctx = TenantContext(t.org, "agent_08", None)
    from tests.agents.agent_08_visual_assets.fixtures import (
        MemoryAssetRepository,
        MemoryAuditLog,
        MemoryFingerprintRepository,
        MemoryLedgerRepository,
        MemoryLicenceRepository,
        MemoryReleaseApprovals,
    )

    w.blobs, w.assets = storage, MemoryAssetRepository()
    w.licences, w.ledger = MemoryLicenceRepository(), MemoryLedgerRepository()
    w.fps, w.approvals, w.audit = (
        MemoryFingerprintRepository(),
        MemoryReleaseApprovals(),
        MemoryAuditLog(),
    )
    w.tx = MemoryTransaction(w.ctx)
    for st in (
        LicenceSourceType.CODE_GENERATED,
        LicenceSourceType.OWNER_MADE,
        LicenceSourceType.FONT,
    ):
        w.licences.add(lic(t.org, st))
    from agent_08_visual_assets.persistence.records import NewAsset
    from amw_core.enums import AssetKind

    for i, tid in enumerate(
        ("caption_card", "chapter_card", "disclaimer_card", "end_screen", "lower_third", "sting_a")
    ):
        body = tiny_png(i)
        sha = hashlib.sha256(body).hexdigest()
        uri = f"amw-blob://{t.org}/assets/templates/{sha}.png"
        storage.put(w.ctx, BlobUri(uri), io.BytesIO(body))
        w.assets.insert(
            w.tx,
            NewAsset(
                kind=AssetKind.TEMPLATE, source_type=LicenceSourceType.CODE_GENERATED,
                content_sha256=sha, uri=uri, size_bytes=len(body), title=tid,
                attributes={"template_id": tid, "template_version": 1},
            ),
        )  # fmt: skip
    font = w.add_font()

    class Brands:
        def brand_kit(self, tx: Any, uri: str, sha256: str | None) -> Any:
            doc = read_ref(storage, t.org, uri, sha256 or "")  # hash-verified read of the ref
            assert doc is not None
            return BrandKit(PALETTE, (font,))

    class Jobs:
        def monetized_destination(self, tx: Any, job_id: str) -> bool | None:
            return True

    t.shared["w08"] = w
    return AssetSourcingStage(
        tenancy=FakeTenancy(), assets=w.assets, licences=w.licences, ledger=w.ledger,
        fingerprints=w.fps, approvals=w.approvals, blobs=storage, clock=FixedClock(),
        settings=settings(), brand_kits=Brands(), job_destinations=Jobs(),
    )  # fmt: skip


class Licences10:
    """``LicenceReader`` (read-only snapshot of the licence ledger, licences and assets, CCR-030)
    over the rows agent_08 wrote (the shared tables in production)."""

    def __init__(self, w08: Any, org: str) -> None:
        self.w08, self.org = w08, org

    def snapshot(self, tx: Any, job_id: str, render_id: str, asset_ids: Any) -> Any:
        from agent_10_video_editor.ports import LicenceSnapshot

        t8 = self.w08.tx
        ledger, licences, assets = [], {}, {}
        for row in self.w08.ledger.for_job(t8, job_id):
            e = row.entry
            ledger.append({
                "asset_id": e.asset_id, "licence_id": e.licence_id, "render_id": None,
                "used_from_ms": e.used_from_ms, "used_to_ms": e.used_to_ms,
                "usage_kind": e.usage_kind.value,
            })  # fmt: skip
            lic = self.w08.licences.get(t8, e.licence_id)
            if lic is not None:
                licences[e.licence_id] = {
                    "state": lic.state.value, "covers_monetized_youtube": lic.covers_monetized_youtube,
                    "expires_in_days": None,
                    "third_party_permission": lic.third_party_permission.value if lic.third_party_permission else None,
                    "org": lic.org_id or self.org,
                }  # fmt: skip
            assets[e.asset_id] = {"status": "ACTIVE", "ai_item": False}
        return LicenceSnapshot(ledger=ledger, licences=licences, assets=assets)


def deps10(t: Tenant, storage: LocalDiskStorage, scratch: Path) -> Any:
    """ONE agent_10 deps object per job (render, subtitles and QC share the render rows, the asset
    catalog and the fake FFmpeg runner): the agent's own in-memory doubles, real storage; the asset
    catalog reads the ``assets`` rows agent_08 inserted (the shared table in production)."""
    from agent_10_video_editor.config import Placement
    from agent_10_video_editor.deps import StageDeps
    from agent_10_video_editor.guard import LocalTime
    from agent_10_video_editor.inputs import AssetRecord
    from agent_10_video_editor.testing import (
        FakeAdmissionProbe,
        FakeClock,
        FakeFfmpegRunner,
        ManualTimerFactory,
        MemoryAssetCatalog,
        MemoryAuditLog,
        MemoryCostLedger,
        MemoryLicenceReader,
        MemoryQcResultRepository,
        MemoryRenderRepository,
        MemoryTenancy,
        make_config,
    )  # fmt: skip
    from amw_core.testing.memory import MemoryCheckpointStore, MemoryIdempotencyStore

    if "deps10" in t.shared:
        return t.shared["deps10"]
    w08 = t.shared["w08"]

    class Catalog10(MemoryAssetCatalog):
        def lookup(self, tx: Any, asset_ids: Any) -> Any:
            out = {}
            for a in asset_ids:
                rec = w08.assets.get(tx, a)
                if rec is not None:
                    out[a] = AssetRecord(
                        asset_id=a,
                        uri=rec.asset.uri,
                        sha256=rec.asset.content_sha256,
                        attributes=dict(rec.asset.attributes or {}),
                    )
            return out

    deps = StageDeps(
        cfg=make_config(), storage=storage, tenancy=MemoryTenancy(),
        checkpoints=MemoryCheckpointStore(), cost_ledger=MemoryCostLedger(),
        idempotency=MemoryIdempotencyStore(), audit=MemoryAuditLog(), runner=FakeFfmpegRunner(),
        admission=FakeAdmissionProbe(LocalTime.parse("SAT", "22:00"), Placement.DEV),
        timers=ManualTimerFactory(), clock=FakeClock(), scratch_root=scratch / "r10",
        renders=MemoryRenderRepository(), assets=Catalog10(), qc_results=MemoryQcResultRepository(),
        licences=MemoryLicenceReader(),
    )  # fmt: skip
    deps = dataclasses.replace(deps, licences=Licences10(w08, t.org))
    t.shared["deps10"] = deps
    return deps


def build_agent_10_render(t: Tenant, storage: LocalDiskStorage, scratch: Path) -> TaskWorker:
    from agent_10_video_editor.render import RenderStage

    return RenderStage(deps10(t, storage, scratch))


def build_agent_10_subtitles(t: Tenant, storage: LocalDiskStorage, scratch: Path) -> TaskWorker:
    from agent_10_video_editor.subtitle_stage import SubtitleStage

    return SubtitleStage(deps10(t, storage, scratch))


def build_agent_10_qc(t: Tenant, storage: LocalDiskStorage, scratch: Path) -> TaskWorker:
    from agent_10_video_editor.qc.stage import QcStage
    from tests.agents.agent_10_video_editor.test_qc_stage import _SelfTests

    return QcStage(deps10(t, storage, scratch), _SelfTests())


def build_agent_11(t: Tenant, storage: LocalDiskStorage, scratch: Path) -> TaskWorker:
    """Agent 11 over its own in-memory repository (``ThumbnailRepository``: no production
    implementation yet), the deterministic planner as the recorded model response and the real
    Pillow composer; the script view (promise, brief) is read from the REAL script document."""
    from agent_11_thumbnail_design.models import Brief, Promise
    from agent_11_thumbnail_design.ports import BrandKitView, FontRef, ScriptView
    from agent_11_thumbnail_design.stage import ThumbnailStage
    from tests.agents.agent_11_thumbnail_design.env import make_env
    from tests.agents.agent_11_thumbnail_design.fakes import FakeRepo
    from tests.agents.agent_11_thumbnail_design.fontgen import build_font

    env = make_env()
    font = build_font()
    font_sha = hashlib.sha256(font).hexdigest()
    font_uri = f"amw-blob://{t.org}/assets/{new_id_asset()}/test.ttf"
    storage.put(
        TenantContextOf(t.org), BlobUri(font_uri), io.BytesIO(font)
    )  # the brand font lives in the tenant's assets area
    font_ref = FontRef("ast_font", font_uri, font_sha, ("Latin", "Devanagari"))
    old = env.deps.repo

    class Repo11(FakeRepo):
        def script_view(self, tx: Any, uri: str, sha256: str) -> Any:
            doc = read_ref(storage, t.org, uri, sha256)
            return ScriptView(
                str(doc["script_id"]), sha256, sha256, "ALLOWED", 0,
                Promise.model_validate(doc["promise"]), Brief.model_validate(doc["thumbnail_brief"]),
            )  # fmt: skip

    repo = Repo11(
        old.script, "youtube_general", BrandKitView({}, (font_ref,), ()), font_ref,
    )  # fmt: skip
    repo.registered.update(old.registered)
    repo.registered[("FONT", "ast_font")] = old.registered[("FONT", "ast_font")]
    deps = dataclasses.replace(env.deps, repo=repo, storage=storage)
    return ThumbnailStage(deps)


def new_id_asset() -> str:
    from amw_core.ids import Prefix, new_id

    return str(new_id(Prefix.ASSET))


def TenantContextOf(org: str) -> Any:  # noqa: N802
    from amw_core.interfaces import TenantContext

    return TenantContext(org, "agent_11", None)


class Rows16:
    """``FactRowReader`` (lane L1 has not written the SQL one): the rows agent_16 reads from the
    shared tables, taken from what the real agents before it wrote (QC rows of agent_10, assets and
    licence ledger of agent_08, claim rows of agent_06, the voice of agent_07). The channel row is
    the seeded channel (category as stored, free text)."""

    def __init__(self, t: Tenant, category: str) -> None:
        self.t, self.category = t, category

    def channel(self, tx: Any, job_id: str) -> Any:
        from agent_16_compliance_qa.inputs.extractors import ChannelRow
        from amw_core.enums import AudienceKind

        return ChannelRow(self.category, AudienceKind.GENERAL, self.t.shared["collection04"])

    def job(self, tx: Any, job_id: str) -> Any:
        from agent_16_compliance_qa.inputs.extractors import JobRow

        return JobRow(
            language="en-IN", production_type_key="CHANNEL_LONG_FORM", live_format=None,
            active_pack_keys=tuple(self.t.shared.get("packs16", ("rp.youtube_general",))),
            routing_script_stage_id="s05_script", routing_assets_stage_id="s08_assets",
            routing_thumbnails_stage_id="s11_thumbs",
        )  # fmt: skip

    def assets(self, tx: Any, asset_ids: Any) -> Any:
        from agent_16_compliance_qa.inputs.extractors import AssetFactRow

        w08 = self.t.shared["w08"]
        out = {}
        ledger = {r.entry.asset_id: r for r in w08.ledger.for_job(w08.tx, self.t.job)}
        for a in asset_ids:
            rec = w08.assets.get(w08.tx, a)
            if rec is None:
                continue
            row = ledger.get(a)
            lic = w08.licences.get(w08.tx, row.entry.licence_id) if row else None
            out[a] = AssetFactRow(
                asset_id=a, tier=None, shows_person=False, is_realistic_synthetic=False,
                has_ledger_row=row is not None,
                licence_state=lic.state if lic else None,
                covers_monetized_youtube=lic.covers_monetized_youtube if lic else None,
                third_party_permission=None,
            )  # fmt: skip
        return out

    def voice_presenter_kind(self, tx: Any, job_id: str) -> Any:
        from amw_core.enums import PresenterKind

        return PresenterKind.NEUTRAL_NARRATION

    def judged_qc_check_ids(self, tx: Any, render_id: str) -> tuple[str, ...]:
        return ()

    def release_approval_subjects(self, tx: Any, approval_ids: Any) -> Any:
        return {}

    def copyright_doubt_approvals(self, tx: Any, span_hashes: Any) -> Any:
        return {}

    def qc_rows(self, tx: Any, render_id: str) -> Any:
        from agent_16_compliance_qa.scoring.aggregate import QcRow

        deps10 = self.t.shared["deps10"]
        rows = deps10.qc_results.for_render(tx, render_id)
        return tuple(QcRow(check_id=r.check_id, verdict=r.verdict) for r in rows)

    def thumbnail_qc_rows(self, tx: Any, job_id: str) -> tuple[Any, ...]:
        return ()

    def claims(self, tx: Any, claim_ids: Any) -> tuple[Any, ...]:
        from agent_16_compliance_qa.inputs.extractors import ClaimRow

        store = self.t.shared["w06"].claims
        out = []
        for cid in claim_ids:
            ext = store.extracted.get(cid)
            ver = store.status.get(cid)
            if ext is None or ver is None:
                continue
            out.append(
                ClaimRow(
                    cid,
                    ext.claim_type.value,
                    ver.status,
                    len(ext.citation_refs),
                    ext.chart_data_ref,
                    None,
                )
            )
        return tuple(out)


class Chunks16:
    """``PrivateChunkReader`` over agent_04's in-memory library (the channel-isolated collection)."""

    def __init__(self, t: Tenant) -> None:
        self.t = t

    def read(self, tx: Any, chunk_id: str) -> Any:
        from agent_04_research_knowledge.library.models import TenantScope
        from agent_16_compliance_qa.nearcopy import ChunkText

        (row,) = self.t.shared["lib04"].load_chunks(
            TenantScope(self.t.org, self.t.channel), [chunk_id]
        )
        return ChunkText(
            chunk_id=chunk_id, org_id=self.t.org, collection_id=row.collection_id, text=row.body
        )


def _llm16_cls() -> Any:
    """The agent's own policy stand-in extended by the paraphrase judge (every pair OWN_WORDS)."""
    import json

    from tests.agents.agent_16_compliance_qa.test_stages import PolicyLlm

    class Llm16(PolicyLlm):
        def complete(self, request: Any, *, idempotency_key: str) -> Any:
            payload = request.messages[0].content.split("<<<INPUT\n", 1)[1].split("\nINPUT>>>")[0]
            doc = json.loads(payload)
            if "pairs" in doc:
                results = [
                    {
                        "pair_id": p["pair_id"], "decision": "OWN_WORDS", "same_structure": False,
                        "same_examples": False, "same_sequence": False,
                        "surface_change_only": False, "is_quotation": False,
                        "closest_passage_id": None, "rationale": "own words",
                    }
                    for p in doc["pairs"]
                ]  # fmt: skip
                reply = json.dumps({"results": results, "injection_suspected": [], "refusal": None})
                self._texts = iter([reply])
                from tests.agents.agent_16_compliance_qa.support import ScriptedLlm

                return ScriptedLlm.complete(self, request, idempotency_key=idempotency_key)
            return super().complete(request, idempotency_key=idempotency_key)

    return Llm16


class Packs16:
    """``PackSource`` (no production implementation): the rule packs of the channel category. The
    finance pack is loaded only for FINANCE; ``resolve_channel_category`` fails closed (CCR-273)."""

    def load(self, tx: Any, channel_category: str) -> Any:
        from amw_orchestrator.executor import ChannelCategory, resolve_channel_category
        from tests.agents.agent_16_compliance_qa.test_gate import packs

        return packs(finance=resolve_channel_category(channel_category) is ChannelCategory.FINANCE)


def build_agent_16_score(t: Tenant, storage: LocalDiskStorage, scratch: Path) -> TaskWorker:
    """Agent 16 quality score: the REAL document extractor over the real documents; the judge's
    group request builder has no production implementation (the agent's fixed test builder is used)
    and the model replies are the agent's recorded group replies."""
    from agent_16_compliance_qa.inputs.extractors import DocumentScoreFactExtractor
    from agent_16_compliance_qa.scoring.stage import QualityScoreStage, ScoreStageDeps
    from tests.agents.agent_16_compliance_qa import support as sp16
    from tests.agents.agent_16_compliance_qa.test_entry_points import (
        QUALITY_PROMPT,
        Groups,
        ScoreStore,
        _Verifier,
        judge_text,
    )  # fmt: skip
    from tests.agents.agent_16_compliance_qa.test_stages import NOW, Tenancy
    from tests.fake_audit import RecordingAuditLog

    rows = t.shared.get("rows16") or Rows16(
        t, t.shared.get("channel_category_label", "youtube_general")
    )

    class Renders:
        def render_content_sha256(self, tx: Any, render_id: str) -> str | None:
            row = t.shared["deps10"].renders.get(tx, render_id)
            return None if row is None else str(row.content_sha256)

    cfg = sp16.config(**{"quality.judge.default_audience_level": "beginner"})
    deps = ScoreStageDeps(
        config=cfg, tenancy=Tenancy(), storage=storage, audit=RecordingAuditLog(),
        budget=sp16.Budget(), costs=sp16.Ledger(), breaker=sp16.Breaker(),
        clock=sp16.FixedClock(NOW),
        llm=sp16.ScriptedLlm([judge_text(g) for g in ("G1", "G2", "G3")]),
        renders=Renders(), rows=rows, extractor=DocumentScoreFactExtractor(rows, _Verifier()),
        groups=Groups(), store=ScoreStore(), prompt=QUALITY_PROMPT.read_text(encoding="utf-8"),
        prompt_ids=("agent_16/quality_score.v1",),
    )  # fmt: skip
    return QualityScoreStage(deps)


def build_agent_16_gate(t: Tenant, storage: LocalDiskStorage, scratch: Path) -> TaskWorker:
    """Agent 16 compliance gate: the REAL document extractor over the real documents, an in-memory
    ``FactRowReader`` (above), the agent's own policy LLM stand-in (every rule NO_VIOLATION)."""
    from agent_16_compliance_qa.assembler import GateInputAssembler
    from agent_16_compliance_qa.authorisation.stage import ApprovalStepVerifier
    from agent_16_compliance_qa.inputs.extractors import DocumentGateFactExtractor
    from agent_16_compliance_qa.stages import ComplianceGateStage, GateStageDeps
    from agent_16_compliance_qa.verdicts import VerdictWriter
    from tests.agents.agent_16_compliance_qa import support as sp16
    from tests.agents.agent_16_compliance_qa.r14_support import R14
    from tests.agents.agent_16_compliance_qa.test_stages import (
        NOW,
        PROMPTS,
        Approvals,
        Store,
        Tenancy,
    )  # fmt: skip
    from tests.fake_audit import RecordingAuditLog

    cfg = sp16.config()
    h = R14()
    approvals = Approvals()

    class Renders(Approvals):
        def render_content_sha256(self, tx: Any, render_id: str) -> str | None:
            row = t.shared["deps10"].renders.get(tx, render_id)
            return None if row is None else str(row.content_sha256)

    approvals = Renders()
    rows = Rows16(t, t.shared.get("channel_category_label", "youtube_general"))
    t.shared["rows16"] = rows
    audit = RecordingAuditLog()
    extractor = DocumentGateFactExtractor(rows, cfg, None, Chunks16(t))
    assembler = GateInputAssembler(
        storage, approvals, ApprovalStepVerifier(approvals, h.a16, cfg.accepted_channels), extractor
    )
    prompts = {
        k: (PROMPTS / f"{n}.v1.md").read_text(encoding="utf-8")
        for k, n in (
            ("policy", "compliance_gate"),
            ("paraphrase", "compliance_gate_paraphrase"),
            ("frames", "compliance_gate_frames"),
        )
    }
    deps = GateStageDeps(
        config=cfg, tenancy=Tenancy(), storage=storage, audit=audit, budget=sp16.Budget(),
        costs=sp16.Ledger(), breaker=sp16.Breaker(), clock=sp16.FixedClock(NOW), llm=_llm16_cls()(),
        assembler=assembler, evidence=h.a16, packs=Packs16(), writer=VerdictWriter(Store(), storage, audit),
        prompts=prompts, pack_texts={}, prompt_ids=("agent_16/compliance_gate.v1",),
    )  # fmt: skip
    return ComplianceGateStage(deps)


def build_svc_s02(t: Tenant, storage: LocalDiskStorage, scratch: Path) -> TaskWorker:
    """svc_s02 uniqueness check (hosted in agent_16): the REAL document extractor over the real script,
    plan, thumbnail manifest and the job's uniqueness template; no prior scripts of the channel."""
    from agent_16_compliance_qa.inputs.extractors import DocumentUniquenessExtractor
    from agent_16_compliance_qa.stages import UniquenessCheckStage, UniquenessStageDeps
    from tests.agents.agent_16_compliance_qa import support as sp16
    from tests.agents.agent_16_compliance_qa.test_stages import NOW, Priors, Store, Tenancy
    from tests.fake_audit import RecordingAuditLog

    deps = UniquenessStageDeps(
        config=sp16.config(), tenancy=Tenancy(), storage=storage, audit=RecordingAuditLog(),
        clock=sp16.FixedClock(NOW), store=Store(), source=Priors(),
        extractor=DocumentUniquenessExtractor(),
    )  # fmt: skip
    return UniquenessCheckStage(deps)


class _FactsRefresh07:
    """The ``scripts`` row facts of agent_07 are a read of the row agent_05 saved: refresh them from
    the shared rows before each run."""

    def __init__(self, stage: Any, facts: Any, rows: Any) -> None:
        self.stage, self.facts, self.rows = stage, facts, rows

    def run(self, task_input: TaskInput, ctx: ExecContext) -> TaskOutput:
        sid = task_input.payload.data["script_id"]
        for saved in self.rows.rows.values():
            if saved.script_id == sid:
                self.facts.script_hash = saved.sha256
        out: TaskOutput = self.stage.run(task_input, ctx)
        return out


FACTORIES: dict[str, WorkerFactory] = {
    "agent_04.research_pack": build_agent_04,
    "agent_05.script_draft": build_agent_05,
    "agent_06.claim_extraction": build_agent_06_extraction,
    "agent_06.claim_verification": build_agent_06_verification,
    "agent_07.voice_synthesis": build_agent_07_voice,
    "agent_07.audio_master": build_agent_07_master,
    "agent_09.shot_plan": build_agent_09,
    "agent_08.asset_sourcing": build_agent_08,
    "agent_10.render": build_agent_10_render,
    "agent_10.subtitles": build_agent_10_subtitles,
    "agent_10.technical_qc": build_agent_10_qc,
    "agent_11.thumbnail_variants": build_agent_11,
    "agent_16.compliance_gate": build_agent_16_gate,
    "svc_s02.uniqueness_check": build_svc_s02,
    "agent_16.quality_score": build_agent_16_score,
}
