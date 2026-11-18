"""``amw.production_type`` 1.0.0 (24 section 2.1, CCR-057): one registry record.

The model mirrors the schema and adds the load-time rules 24 section 2 lists that need no other
registry: unique stage IDs, known dependencies, the stage graph is a DAG, every gate's REVISE
target and alternative targets are ancestors of the gate (CCR-002), and ``rp.youtube_general`` is
mandatory whenever ``YOUTUBE`` is a destination. The remaining load rules (task types exist in
24 section 3.2, mandatory approvals have workflows, revision ceiling of 07 section 9) need the
task-type catalogue and config; the registry loader (lane L1) checks them.
"""

from collections.abc import Mapping
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import Field, StrictBool, StringConstraints, model_validator

from amw_core.contracts.common import AmwModel, Currency, SchemaName
from amw_core.enums import (
    ApprovalKind,
    ApprovalWorkflowKey,
    AspectRatio,
    Capability,
    DestinationKind,
    FeatureStatus,
    InputProvider,
    LanguageMode,
    ParentInput,
    ProductionTypeKey,
    ResourceClass,
    RulePackKey,
    Tier,
)

StageId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{2,32}$")]
RulePackKeyStr = Annotated[str, StringConstraints(pattern=r"^rp\.[a-z0-9_]+$")]
TaskType = Annotated[
    str,
    StringConstraints(pattern=r"^(agent_(0[1-9]|1[0-7])|svc_s(0[1-9]|1[0-3]))\.[a-z0-9_]+$"),
]
NonNeg = Annotated[int, Field(ge=0, strict=True)]


def _unique[T](items: tuple[T, ...], what: str) -> tuple[T, ...]:
    if len(set(items)) != len(items):
        raise ValueError(f"{what} must be unique")
    return items


class ReviseOnFail(AmwModel):
    omit_if_none: ClassVar[frozenset[str]] = frozenset({"alt_target_stage_ids"})

    action: Literal["REVISE"]
    target_stage_id: StageId
    alt_target_stage_ids: tuple[StageId, ...] | None = None

    @model_validator(mode="after")
    def _unique_alts(self) -> Self:
        if self.alt_target_stage_ids is not None:
            _unique(self.alt_target_stage_ids, "alt_target_stage_ids")
        return self


class StopOnFail(AmwModel):
    action: Literal["STOP"]


class Gate(AmwModel):
    blocking: Literal[True]
    on_fail: Annotated[ReviseOnFail | StopOnFail, Field(discriminator="action")]


class StageApproval(AmwModel):
    approval_kind: ApprovalKind
    workflow_key: ApprovalWorkflowKey


class Stage(AmwModel):
    omit_if_none: ClassVar[frozenset[str]] = frozenset({"enabled_by_default", "params"})

    stage_id: StageId
    task_type: TaskType
    required: StrictBool
    enabled_by_default: StrictBool | None = None
    resource_class: ResourceClass
    capabilities: tuple[Capability, ...]
    depends_on: tuple[StageId, ...]
    gate: Gate | None
    approval: StageApproval | None
    params: Annotated[dict[str, Any], Field(max_length=16)] | None = None

    @model_validator(mode="after")
    def _unique_lists(self) -> Self:
        _unique(self.capabilities, "capabilities")
        _unique(self.depends_on, "depends_on")
        return self


class DurationRange(AmwModel):
    min: NonNeg | None
    max: NonNeg | None


class RequiredInput(AmwModel):
    key: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{2,48}$")]
    description: Annotated[str, StringConstraints(max_length=500)]
    input_schema: SchemaName | None
    provided_by: InputProvider


class ApprovalRequirement(AmwModel):
    approval_kind: ApprovalKind
    workflow_key: ApprovalWorkflowKey
    mandatory: StrictBool


class RulePacks(AmwModel):
    mandatory: tuple[RulePackKeyStr, ...]
    by_category: Mapping[
        Annotated[str, StringConstraints(pattern=r"^[a-z_]{2,32}$")], tuple[RulePackKeyStr, ...]
    ]

    @model_validator(mode="after")
    def _unique_mandatory(self) -> Self:
        _unique(self.mandatory, "rule_packs.mandatory")
        return self


class CostComponent(AmwModel):
    omit_if_none: ClassVar[frozenset[str]] = frozenset({"note"})

    component: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{2,48}$")]
    unit: Annotated[str, StringConstraints(max_length=32)]
    note: Annotated[str, StringConstraints(max_length=300)] | None = None


class DefaultPrice(AmwModel):
    amount_minor: NonNeg | None
    currency: Currency
    label: Literal["PROPOSAL"]


class Limits(AmwModel):
    max_revision_loops: Annotated[int, Field(ge=0, le=10, strict=True)]


class ProductionType(AmwModel):
    key: ProductionTypeKey
    version: Annotated[int, Field(ge=1, strict=True)]
    display_name: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    status: FeatureStatus
    first_tier: Tier
    destinations: Annotated[tuple[DestinationKind, ...], Field(min_length=1)]
    requires_channel: StrictBool
    parent_input: ParentInput
    duration_targets_ms: (
        DurationRange
        | Annotated[tuple[Annotated[int, Field(ge=1, strict=True)], ...], Field(min_length=1)]
    )
    aspect_ratios: Annotated[tuple[AspectRatio, ...], Field(min_length=1)]
    languages: LanguageMode
    stages: Annotated[tuple[Stage, ...], Field(min_length=1, max_length=64)]
    required_inputs: tuple[RequiredInput, ...]
    approvals: tuple[ApprovalRequirement, ...]
    templates: tuple[Annotated[str, StringConstraints(pattern=r"^[a-z0-9_.]{2,64}$")], ...]
    qc_profile: Annotated[str, StringConstraints(pattern=r"^qc\.[a-z_]{2,32}$")]
    rule_packs: RulePacks
    deliverables: Annotated[
        tuple[Annotated[str, StringConstraints(pattern=r"^[a-z0-9_<>]{2,64}$")], ...],
        Field(min_length=1),
    ]
    cost_model: tuple[CostComponent, ...]
    default_price: DefaultPrice | None
    limits: Limits

    @model_validator(mode="after")
    def _record_rules(self) -> Self:
        _unique(self.destinations, "destinations")
        _unique(self.aspect_ratios, "aspect_ratios")
        if isinstance(self.duration_targets_ms, tuple):
            _unique(self.duration_targets_ms, "duration_targets_ms")
        if (
            DestinationKind.YOUTUBE in self.destinations
            and RulePackKey.YOUTUBE_GENERAL.value not in self.rule_packs.mandatory
        ):
            raise ValueError("rp.youtube_general is mandatory with a YOUTUBE destination")
        ancestors = stage_ancestors(self.stages)
        for stage in self.stages:
            if stage.gate is not None and isinstance(stage.gate.on_fail, ReviseOnFail):
                on_fail = stage.gate.on_fail
                for target in (on_fail.target_stage_id, *(on_fail.alt_target_stage_ids or ())):
                    if target not in ancestors[stage.stage_id]:
                        raise ValueError(
                            f"gate {stage.stage_id}: target {target} is not an ancestor"
                        )
        return self

    def stage(self, stage_id: str) -> Stage:
        return next(s for s in self.stages if s.stage_id == stage_id)


def stage_ancestors(stages: tuple[Stage, ...]) -> dict[str, frozenset[str]]:
    """Transitive dependencies per stage; ``ValueError`` for duplicates, unknown IDs or a cycle."""
    by_id = {s.stage_id: s for s in stages}
    if len(by_id) != len(stages):
        raise ValueError("stage_id values must be unique")
    for stage in stages:
        unknown = set(stage.depends_on) - by_id.keys()
        if unknown:
            raise ValueError(f"stage {stage.stage_id} depends on unknown {sorted(unknown)}")
    done: dict[str, frozenset[str]] = {}
    visiting: set[str] = set()

    def visit(stage_id: str) -> frozenset[str]:
        if stage_id in done:
            return done[stage_id]
        if stage_id in visiting:
            raise ValueError(f"stage graph has a cycle through {stage_id}")
        visiting.add(stage_id)
        found: set[str] = set()
        for dep in by_id[stage_id].depends_on:
            found |= {dep} | visit(dep)
        visiting.discard(stage_id)
        done[stage_id] = frozenset(found)
        return done[stage_id]

    for stage in stages:
        visit(stage.stage_id)
    return done
