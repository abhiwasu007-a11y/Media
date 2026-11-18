"""``agent_04.knowledge_ingest.input`` / ``.output`` 1.0.0 (blueprint 7.1)."""

from typing import Annotated

from pydantic import Field, StringConstraints

from agent_04_research_knowledge.models.enums import IngestSourceStatus
from amw_core.contracts.common import AmwModel
from amw_core.ids import UUID7_BODY

INGEST_INPUT_SCHEMA = "agent_04.knowledge_ingest.input"
INGEST_OUTPUT_SCHEMA = "agent_04.knowledge_ingest.output"

SourceIdStr = Annotated[str, StringConstraints(pattern=rf"^ksr_{UUID7_BODY}$")]
NonNeg = Annotated[int, Field(ge=0, strict=True)]


class IngestInput(AmwModel):
    source_id: SourceIdStr
    ingest_version: Annotated[int, Field(ge=1, strict=True)]
    force_reextract: bool


class IngestOutput(AmwModel):
    source_id: SourceIdStr
    ingest_version: Annotated[int, Field(ge=1, strict=True)]
    source_status: IngestSourceStatus
    chunks_written: NonNeg
    pages_total: NonNeg
    pages_needs_ocr: NonNeg
    qa_sample_size: NonNeg
    unresolved_headings: NonNeg
