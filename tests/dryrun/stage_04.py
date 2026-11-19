"""``s04_research`` -> ``agent_04.research_pack`` over a synthetic, invented knowledge library."""

import hashlib
import json
from typing import Any

from agent_04_research_knowledge.guards.tenant import ChannelRecord
from agent_04_research_knowledge.library.memory import InMemoryKnowledgeLibrary
from agent_04_research_knowledge.library.models import ChunkRow, CollectionView, SourceView
from agent_04_research_knowledge.memory import InMemoryMemoryItems, PackMemory
from agent_04_research_knowledge.prompts import PromptLoader, RulePackText, StaticRulePacks
from agent_04_research_knowledge.steps.research_pack import (
    ResearchPackStep,
    ResolverFactory,
    StepDeps,
)
from amw_adapters.llm import LlmRequest
from amw_adapters.web_fetch.fake import FakeWebFetchAdapter
from amw_core.contracts import TaskOutput
from amw_core.enums import (
    KnowledgeSourceKind,
    KnowledgeSourceStatus,
    RulePackScope,
    SourceOwnership,
)
from amw_core.ids import AttemptId, Prefix, new_id
from amw_core.testing.memory import MemoryCheckpointStore, MemoryIdempotencyStore
from amw_orchestrator.executor import StageCall
from amw_orchestrator.metering import MeteredLlm
from tests.agents.agent_04_research_knowledge.conftest import make_settings, user_payload
from tests.agents.agent_04_research_knowledge.fakes import FakeDirectory
from tests.dryrun.base import World, task_input
from tests.dryrun.kit import PROMPTS, AllowBudget, ListAudit, MemTenancy, MirrorLedger
from tests.dryrun.llm import ScriptedLlm

# Invented placeholder notes (no book text): the PLUMBING library of the dry-run channel.
CHUNKS = (
    "PLUMBING TEST momentum oscillator RSI compares the size of recent rises with recent falls "
    "on a scale from zero to one hundred.",
    "PLUMBING TEST divergence means price makes a new high or low while the RSI momentum "
    "reading does not confirm it.",
)
CONCEPTS = (
    ("c01", "RSI momentum oscillator", "RSI", ["DEFINITION"]),
    ("c02", "RSI divergence", "divergence", ["MECHANISM"]),
)
NOTE = {
    "c01": "PLUMBING placeholder: the RSI reading compares average gains with average losses.",
    "c02": "PLUMBING placeholder: divergence is price and the RSI reading moving apart.",
}


def responder(request: LlmRequest) -> str:
    payload = user_payload(request)
    if "topic_title" in payload:
        language = payload["video_language"].split("-")[0]
        concepts = [
            {
                "concept_id": cid,
                "label": label,
                "label_en": label,
                "kind": "CORE_CONCEPT",
                "rationale": "PLUMBING placeholder",
                "evidence_needs": needs,
                "time_reference": "TIMELESS",
                "queries": [{"text": query, "language": language, "purpose": "PRIMARY"}],
                "wants_method_material": False,
                "closes_gap_ids": [],
                "target_collection_keys": [],
            }
            for cid, label, query, needs in CONCEPTS
        ]
        return json.dumps({"concepts": concepts, "out_of_scope_notes": [], "refusal": None})
    concept = payload["concept"]
    notes, assess = [], []
    for i, passage in enumerate(payload["passages"], start=1):
        relevant = concept["label_en"].split()[-1].lower() in passage["text"].lower()
        assess.append(
            {
                "passage_id": passage["passage_id"],
                "relevance": "RELEVANT" if relevant else "IRRELEVANT",
                "reason": "PLUMBING keyword match",
            }
        )
        if relevant:
            notes.append(
                {
                    "note_ref": f"n{i}",
                    "passage_id": passage["passage_id"],
                    "statement_kind": concept["evidence_needs"][0],
                    "note": NOTE[concept["concept_id"]],
                    "time_reference_kind": "TIMELESS",
                    "instruments": [],
                    "numbers_in_note": [],
                    "clarity": "CLEAR",
                    "forward_looking": False,
                }
            )
    return json.dumps(
        {"assessments": assess, "notes": notes, "excluded_statements": [], "refusal": None}
    )


class ResearchExecutor:
    def __init__(self, world: World) -> None:
        self.w = world
        self.library = InMemoryKnowledgeLibrary()
        self.chunk_text: dict[str, str] = {}
        self._seeded = False

    def _seed(self, org: str, channel: str) -> None:
        if self._seeded:
            return
        cid = new_id(Prefix.KNOWLEDGE_COLLECTION)
        self.library.add_collection(
            org, channel, CollectionView(cid, "general_trading", "general_trading", False)
        )
        sid = new_id(Prefix.KNOWLEDGE_SOURCE)
        self.library.add_source(
            SourceView(
                source_id=sid,
                org_id=org,
                channel_id=channel,
                collection_id=cid,
                kind=KnowledgeSourceKind.BOOK,
                title="PLUMBING invented primer",
                author="PLUMBING",
                edition="0",
                language="en",
                ownership=SourceOwnership.OWNED_COPY,
                status=KnowledgeSourceStatus.INDEXED,
                ingest_version=1,
                content_sha256="ab" * 32,
                size_bytes=10,
            )
        )
        for no, body in enumerate(CHUNKS, start=1):
            chunk = new_id(Prefix.KNOWLEDGE_CHUNK)
            self.library.add_chunk(
                ChunkRow(
                    chunk,
                    org,
                    channel,
                    sid,
                    cid,
                    1,
                    no,
                    "PLUMBING",
                    None,
                    1,
                    1,
                    "en",
                    body,
                    hashlib.sha256(body.encode()).hexdigest(),
                )
            )
            self.chunk_text[chunk] = body
        self._seeded = True

    def execute(self, call: StageCall) -> TaskOutput:
        job = call.job
        self._seed(job.org_id, job.channel_id)
        directory = FakeDirectory()
        directory.channels[(job.org_id, job.channel_id)] = ChannelRecord(
            job.org_id, job.channel_id, True
        )
        if job.project_id is not None:
            directory.workspaces[(job.org_id, job.project_id)] = job.workspace_id
        packs = StaticRulePacks(
            {
                "rp.youtube_general": RulePackText(
                    "rp.youtube_general", RulePackScope.PLATFORM, "1", "PLUMBING rules YTG"
                ),
                "rp.finance_sebi_in": RulePackText(
                    "rp.finance_sebi_in", RulePackScope.PLATFORM, "1", "PLUMBING rules FIN"
                ),
            }
        )
        deps = StepDeps(
            llm=MeteredLlm(ScriptedLlm(responder), self.w.meter, 2_000),
            web=FakeWebFetchAdapter(allowed_hosts=frozenset()),
            library=self.library,
            directory=directory,
            tenancy=MemTenancy(),
            storage=self.w.blobs.storage,
            checkpoints=MemoryCheckpointStore(),
            idempotency=MemoryIdempotencyStore(),
            budget=AllowBudget(),
            ledger=MirrorLedger(),
            audit=ListAudit(),
            clock=self.w.clock,
            settings=make_settings(),
            prompts=PromptLoader(PROMPTS, packs),
            memory=PackMemory(InMemoryMemoryItems(), 86_400_000),
            resolver_factory=ResolverFactory(self.library, self.w.blobs.storage),
        )
        topic = job.owner_topic
        revision: Any = None
        if call.iteration > 0:
            revision = {"iteration": call.iteration, "gaps": []}
        data = {
            "topic": {
                "title": topic.title,
                "brief": topic.brief,
                "angle": topic.angle,
                "language": topic.language,
                "video_kind": topic.video_kind.value,
                "course_chapter_pointer": None,
            },
            "channel_category": "finance",
            "active_rule_packs": ["rp.youtube_general", "rp.finance_sebi_in"],
            "library_scope": {"collection_keys": None},
            "owner_references": [],
            "revision": revision,
        }
        ti = task_input(call, "agent_04", "agent_04.research_pack.input", data)
        return ResearchPackStep(deps).run(ti, AttemptId(call.attempt_id), call.attempt_no)
