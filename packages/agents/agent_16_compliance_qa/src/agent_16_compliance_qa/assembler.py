"""GateInputAssembler (F-03; blueprint sections 7.2 and 7.7): Task Input -> ``GateInputs``.

What it does itself (fail closed, in this order):

1. the payload validates against ``agent_16.compliance_gate.input`` 1.0.0
   (``PERMANENT.SCHEMA_INVALID``);
2. every ``*_ref`` URI belongs to the envelope org (``PERMANENT.CROSS_TENANT_REF``; the stage
   writes a ``security.cross_tenant_ref`` audit event);
3. ``subject.render_sha256`` equals ``renders.content_sha256`` read under RLS
   (``PERMANENT.INPUT_INVALID``; missing render ``PERMANENT.MISSING_DEPENDENCY``);
4. every blob is read through ``BlobStorage.get`` with its stated SHA-256 (a mismatch is
   ``AGENT.CORRUPTED_OUTPUT``, raised by the storage before the last chunk);
5. the FIN-R12 release state of every method segment and the V12 state of every quotation are
   **derived** by ``ApprovalStepVerifier`` (F-26, G2 + G4 over the steps); whatever state an
   upstream blob carries is overwritten (``NONE`` when no approval is named).

What it delegates: turning the upstream output blobs (Agent 05 script, Agent 06 claims and
verification, Agent 07 voice, Agent 08 manifest, Agent 09 shot plan, Agent 10 render QC and
evidence manifest, Agent 11 thumbnails, S2 uniqueness) into gate facts is ``GateFactExtractor``.
Its implementation depends on the Agent 10 output schemas, which are not built in this slice
(core_need / lane dependency); tests use a fixture extractor. No caller can supply an approval
state, a hash verdict or a tenant decision through it.
"""

from collections.abc import Mapping
from datetime import date
from typing import Literal, Protocol

from pydantic import Field, ValidationError

from agent_16_compliance_qa.authorisation.stage import ApprovalStepVerifier
from agent_16_compliance_qa.base import Model
from agent_16_compliance_qa.gate import GateInputs, Routing
from amw_core.contracts.common import storage_uri_owner
from amw_core.contracts.task_input import TaskInput
from amw_core.enums import ApprovalKind
from amw_core.errors import (
    CrossTenantRefError,
    InputInvalidError,
    MissingDependencyError,
    SchemaInvalidError,
)
from amw_core.interfaces.storage import BlobStorage, BlobUri
from amw_core.interfaces.tenancy_context import TenantTransaction

INPUT_SCHEMA = "agent_16.compliance_gate.input"
_SHA = r"^[0-9a-f]{64}$"


class BlobRefIn(Model):
    uri: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA)


class GateSubject(Model):
    render_id: str = Field(pattern=r"^rnd_")
    render_sha256: str = Field(pattern=_SHA)
    script_id: str = Field(pattern=r"^scr_")
    script_sha256: str = Field(pattern=_SHA)


class GateRefs(Model):
    script_ref: BlobRefIn
    claims_ref: BlobRefIn
    verification_ref: BlobRefIn
    asset_manifest_ref: BlobRefIn
    shot_plan_ref: BlobRefIn
    render_qc_ref: BlobRefIn
    voice_ref: BlobRefIn
    thumbnails_ref: BlobRefIn
    uniqueness_ref: BlobRefIn
    research_pack_ref: BlobRefIn
    frames_ref: BlobRefIn
    metadata_ref: BlobRefIn | None = None


ProductionType = Literal[
    "CHANNEL_LONG_FORM",
    "SHORTS",
    "AD_SPOT",
    "EXPLAINER_CORPORATE_TRAINING",
    "ECOMMERCE_PRODUCT",
    "DUBBING_LOCALISATION",
]


class ComplianceGateInput(Model):
    """``agent_16.compliance_gate.input`` 1.0.0 (section 7.2)."""

    subject: GateSubject
    iteration: int = Field(ge=0)
    channel_category: str = Field(min_length=1)
    production_type_key: ProductionType
    destination_kinds: tuple[Literal["YOUTUBE", "FILE_DELIVERY"], ...] = Field(min_length=1)
    evaluate_as_destination: Literal["YOUTUBE"]
    owner_sebi_registration: Literal["UNREGISTERED"]
    language: str = Field(min_length=2)
    routing: Routing
    inputs: GateRefs


class ExtractedGate(Model):
    """What ``GateFactExtractor`` returns: the gate facts plus the approval IDs whose state the
    assembler derives (the extractor never decides an approval state)."""

    inputs: GateInputs
    method_release_approvals: Mapping[str, str | None] = Field(default_factory=dict)
    """segment_ref -> ``KNOWLEDGE_RELEASE`` approval id named by the research pack (or None)."""
    quotation_approvals: Mapping[str, str | None] = Field(default_factory=dict)
    """span sha256 -> ``COPYRIGHT_DOUBT`` approval id (or None)."""


class GateFactExtractor(Protocol):
    def extract(
        self, request: ComplianceGateInput, blobs: Mapping[str, bytes], evaluation_date: date
    ) -> ExtractedGate:
        """Parse the verified upstream blobs (keyed by ``*_ref`` name) into gate facts."""
        ...


class RenderHashReader(Protocol):
    def render_content_sha256(self, tx: TenantTransaction, render_id: str) -> str | None:
        """``renders.content_sha256`` under RLS (explicit ``org_id`` filter); None = not found."""
        ...


class GateInputAssembler:
    def __init__(
        self,
        storage: BlobStorage,
        renders: RenderHashReader,
        approvals: ApprovalStepVerifier,
        extractor: GateFactExtractor,
    ) -> None:
        self._storage, self._renders = storage, renders
        self._approvals, self._extractor = approvals, extractor

    @staticmethod
    def parse(ti: TaskInput) -> ComplianceGateInput:
        if ti.payload.payload_schema != INPUT_SCHEMA or ti.payload.data is None:
            raise SchemaInvalidError("payload is not agent_16.compliance_gate.input")
        try:
            req = ComplianceGateInput.model_validate(ti.payload.data)
        except ValidationError as exc:
            raise SchemaInvalidError(
                "agent_16.compliance_gate.input invalid",
                details={"violations": [".".join(map(str, e["loc"])) for e in exc.errors()]},
            ) from exc
        for name, ref in req.inputs:
            if ref is not None and storage_uri_owner(ref.uri) != ti.org_id:
                raise CrossTenantRefError(
                    "reference belongs to another tenant", details={"ref": name}
                )
        return req

    def assemble(
        self, ti: TaskInput, tx: TenantTransaction, evaluation_date: date
    ) -> tuple[ComplianceGateInput, GateInputs]:
        req = self.parse(ti)
        stored = self._renders.render_content_sha256(tx, req.subject.render_id)
        if stored is None:
            raise MissingDependencyError("render not found in this tenant")
        if stored != req.subject.render_sha256:
            raise InputInvalidError("subject.render_sha256 is not renders.content_sha256")
        blobs: dict[str, bytes] = {}
        for name, ref in req.inputs:
            if ref is not None:
                chunks = self._storage.get(tx.context, BlobUri(ref.uri), ref.sha256)
                blobs[name] = b"".join(chunks)
        extracted = self._extractor.extract(req, blobs, evaluation_date)
        inputs = extracted.inputs
        segments = tuple(
            seg.model_copy(
                update={
                    "release_state": self._approvals.derive(
                        tx,
                        extracted.method_release_approvals.get(seg.segment_ref),
                        ApprovalKind.KNOWLEDGE_RELEASE,
                    )
                }
            )
            for seg in inputs.method_segments
        )
        quotations = tuple(
            (span, self._approvals.derive(tx, aid, ApprovalKind.COPYRIGHT_DOUBT))
            for span, aid in sorted(extracted.quotation_approvals.items())
        )
        fixed = inputs.model_copy(
            update={
                "method_segments": segments,
                "quotation_approvals": quotations,
                "routing": req.routing,
                "language": req.language,
                "channel_category": req.channel_category,
                "production_type_key": req.production_type_key,
                "evaluation_date": evaluation_date,
            }
        )
        return req, fixed
