"""Shared fixtures of the script-input resolver tests: a synthetic library (invented filler), a
local-disk tenant storage, a research pack, and fakes of the injected ports. No network."""

import io
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from agent_05_scriptwriter.assemble.parts import DisclaimerTemplate
from agent_05_scriptwriter.contracts import ScriptDraftInput
from agent_05_scriptwriter.pre.brief_mapper import ApprovalView
from agent_05_scriptwriter.protocols import RulePack, StepContext
from agent_06_fact_checker.library.copyright import WorkCopyrightRecord, WorkKind
from agent_06_fact_checker.library.reader import CheckoutLibraryReader, LibraryLimits, LibraryRef
from agent_06_fact_checker.library.wiring import StaticLibraryIndex, WorkRef
from amw_core import ids
from amw_core.contracts.task_input import TaskInput
from amw_core.interfaces.storage import BlobUri
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.storage.local import LocalDiskStorage
from amw_core.tenancy.storage_paths import blob_uri
from amw_orchestrator.script_inputs import (
    ChannelFacts,
    LibrarySourceClassifier,
    ScriptInputResolver,
)
from tests.agents.agent_05_scriptwriter import support as sp
from tests.agents.agent_05_scriptwriter.test_entry_point import task_input
from tests.library_index.support import make_library

LIMITS = LibraryLimits(max_file_bytes=100_000, allowed_suffixes=frozenset({".txt"}))
JOB_DATE = date(2026, 11, 20)
CIT = [f"kch_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d80{i:02d}" for i in range(1, 4)]
LIBRARY_TEXT = {
    "works/pd.txt": "§ 1\nsynthetic filler one\n",
    "works/modern.txt": "§ 1\nsynthetic filler two\n",
}


def record(work_id: str, path: str, **over: Any) -> WorkCopyrightRecord:
    data: dict[str, Any] = {
        "work_id": work_id,
        "title": f"Title of {work_id}",
        "author": "Author Synthetic",
        "author_death_year": -300,
        "work_kind": WorkKind.ORIGINAL,
        "text_path": path,
    }
    data.update(over)
    return WorkCopyrightRecord.model_validate(data)


class SpyLibrary:
    """A pinned read-only library that remembers which paths were read (never the text)."""

    def __init__(self, inner: CheckoutLibraryReader) -> None:
        self._inner, self.reads = inner, []  # type: ignore[var-annotated]

    @property
    def commit_sha(self) -> str:
        return self._inner.commit_sha

    def read_text(self, relative_path: str) -> str:
        self.reads.append(relative_path)
        return self._inner.read_text(relative_path)


class Channels:
    def __init__(self, ctx: StepContext, category: str | None = "youtube_general") -> None:
        self.ctx, self.category, self.status = ctx, category, "ACTIVE"
        self.gone = False

    def facts(self, ctx: StepContext) -> ChannelFacts | None:
        if self.gone:
            return None
        return ChannelFacts(ctx.org_id, ctx.org_id, self.status, self.category)


@dataclass
class Documents:
    ctx: StepContext
    disclaimer: DisclaimerTemplate | None = None
    calls: list[str] = field(default_factory=list)

    def profile_rule_packs(self, ctx: StepContext, task_input: TaskInput) -> list[str]:
        return ["rp.youtube_general"]

    def rule_packs(self, ctx: StepContext, task_input: TaskInput, keys: Any) -> dict[str, RulePack]:
        return {k: RulePack(k, "v1", "PLATFORM RULES", "PLATFORM") for k in keys}

    def lexicons(self, ctx: StepContext, task_input: TaskInput) -> Any:
        return sp.LEX_TEST_V1

    def latin_allow_list(self, ctx: StepContext, task_input: TaskInput) -> list[str] | None:
        return []

    def disclaimer_template(
        self, ctx: StepContext, task_input: TaskInput
    ) -> DisclaimerTemplate | None:
        self.calls.append("disclaimer")
        return self.disclaimer

    def approvals(self, ctx: StepContext, task_input: TaskInput, ids_: Any) -> list[ApprovalView]:
        return []


class FixedDate:
    def __init__(self, day: date = JOB_DATE) -> None:
        self.day = day

    def job_date(self, task_input: TaskInput) -> date:
        return self.day


class World:
    def __init__(self, tmp_path: Path, **kw: Any) -> None:
        self.ctx = sp.make_ctx()
        self.storage = LocalDiskStorage(tmp_path / "store")
        self.root = tmp_path / "lib"
        self.sha = make_library(self.root, LIBRARY_TEXT)
        self.library = SpyLibrary(CheckoutLibraryReader(LibraryRef(self.root, self.sha), LIMITS))
        self.records = {
            "w_pd": record("w_pd", "works/pd.txt"),
            "w_modern": record(
                "w_modern",
                "works/modern.txt",
                work_kind=WorkKind.TRANSLATION,
                translator="Translator Synthetic",
                translator_death_year=2000,
            ),
        }
        self.index = StaticLibraryIndex(
            {
                CIT[0]: WorkRef("w_pd", "1", ("Author Synthetic",)),
                CIT[1]: WorkRef("w_modern", "1", ("Author Synthetic",)),
                CIT[2]: WorkRef("w_pd", "1", ("Author Synthetic",)),
            }
        )
        self.channels = Channels(self.ctx)
        self.documents = Documents(self.ctx)
        self.dates = FixedDate()
        self.library_for: Any = lambda _t: self.library
        self.non_finance: object = frozenset({"youtube_general"})
        self.pack_doc = sp.make_pack().model_dump_json().encode()
        self.__dict__.update(kw)

    def resolver(self) -> ScriptInputResolver:
        return ScriptInputResolver(
            storage=self.storage,
            channels=self.channels,
            documents=self.documents,
            classifier=LibrarySourceClassifier(self.index, self.records),
            library_for=lambda t: self.library_for(t),
            job_dates=self.dates,
            non_finance_categories=self.non_finance,
        )

    def put(self, body: bytes, name: str = "pack.json", org: str | None = None) -> dict[str, Any]:
        org = org or self.ctx.org_id
        uri = blob_uri(org, "assets", name)  # type: ignore[arg-type]
        tenant = TenantContext(org, "agent_04", None)  # type: ignore[arg-type]
        head = self.storage.head(tenant, BlobUri(uri))
        if head.exists:  # write-once storage: the same document is stored once
            return {"uri": uri, "sha256": head.sha256}
        info = self.storage.put(tenant, BlobUri(uri), io.BytesIO(body))
        return {"uri": str(info.uri), "sha256": info.sha256}

    def task(self, refs: list[dict[str, Any]] | None = None, **data: Any) -> TaskInput:
        if refs is None:
            ref = self.put(self.pack_doc)
            refs = [
                {
                    **ref, "purpose": "PRIOR_OUTPUT", "schema": "agent_04.research_pack.output",
                    "schema_version": "1.0.0",
                }
            ]  # fmt: skip
        fields: dict[str, Any] = {
            "channel_category": "youtube_general",
            "active_rule_packs": ["rp.youtube_general"],
            **data,
        }
        payload = sp.make_input(**fields).model_dump(mode="json")
        return task_input(payload, context_refs=refs, org_id=self.ctx.org_id,
                          job_id=self.ctx.job_id, channel_id=self.ctx.channel_id,
                          project_id=self.ctx.project_id)  # fmt: skip

    def data(self, ti: TaskInput) -> Any:
        return ScriptDraftInput.model_validate(ti.payload.data)


NEW_ID = ids.new_id
