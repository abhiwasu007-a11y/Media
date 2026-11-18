"""``ChartSpec`` and ``ChartSpecHasher`` (blueprint 6.4, 10.3).

The spec hash is SHA-256 over the canonical JSON of the spec (sorted keys, no whitespace); it is
the idempotency and reuse key of a rendered chart (CH-01 to CH-05).
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from agent_08_visual_assets.charts.annotations import Annotation


class ChartSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    window: tuple[int, int]
    instrument: str
    timeframe: str
    indicators: tuple[str, ...]
    template_id: str
    template_version: Annotated[int, Field(ge=1)]
    annotations: tuple[Annotation, ...]
    aspect_ratio: str
    palette_ref: str
    reveal_steps: Annotated[int, Field(ge=1)] = 1
    palette_sha256: str | None = None


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class ChartSpecHasher:
    @staticmethod
    def hash(spec: BaseModel | Mapping[str, Any]) -> str:
        data = spec.model_dump(mode="json", exclude_none=False) if isinstance(spec, BaseModel) else spec
        return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()
