"""``agent_08.asset_sourcing.input`` 1.0.0 (blueprint 7.1), payload of the task input."""

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from agent_08_visual_assets.models.common import (
    ScriptIdStr,
    Sha256Hex,
    ShotIdStr,
    StageIdStr,
    StorageUri,
)
from amw_core.contracts.common import AmwModel
from amw_core.enums import LicenceDestination

Aspect = Literal["16:9", "9:16", "1:1", "4:5"]


class ShotPlanRef(AmwModel):
    uri: StorageUri
    sha256: Sha256Hex
    schema_: Literal["agent_09.shot_plan.output"] = Field(alias="schema")
    schema_version: Annotated[str, StringConstraints(pattern=r"^1\.[0-9]+\.[0-9]+$")]


class ScriptRef(AmwModel):
    uri: StorageUri
    sha256: Sha256Hex
    script_id: ScriptIdStr


class BlobRef(AmwModel):
    uri: StorageUri
    sha256: Sha256Hex


class SourcingInput(AmwModel):
    shot_plan_ref: ShotPlanRef
    script_ref: ScriptRef
    aspect_ratios: Annotated[tuple[Aspect, ...], Field(min_length=1, max_length=2)]
    destination: LicenceDestination
    script_stage_id: StageIdStr
    channel_category: Annotated[str, StringConstraints(max_length=32)]
    active_rule_packs: tuple[Annotated[str, StringConstraints(pattern=r"^rp\.[a-z_]+$")], ...]
    ai_video_allowed: bool
    stills_allowed: bool
    iteration: Annotated[int, Field(ge=0, le=10, strict=True)]
    previous_sourcing_ref: BlobRef | None
    changed_shot_ids: Annotated[tuple[ShotIdStr, ...], Field(max_length=500)]

    @model_validator(mode="after")
    def _rules(self) -> Self:
        if len(set(self.aspect_ratios)) != len(self.aspect_ratios):
            raise ValueError("aspect_ratios must be unique")
        if len(set(self.changed_shot_ids)) != len(self.changed_shot_ids):
            raise ValueError("changed_shot_ids must be unique")
        if self.iteration > 0 and self.previous_sourcing_ref is None:
            raise ValueError("iteration > 0 requires previous_sourcing_ref")
        return self
