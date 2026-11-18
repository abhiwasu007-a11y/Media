"""DirectionParser (F-13): strict parse into the Pydantic model; never best-effort."""

import json
from collections.abc import Sequence

from pydantic import ValidationError

from agent_09_video_director.contracts import DirectionOutput
from amw_core.errors import InvalidJsonError, OutputSchemaInvalidError


def parse_direction_output(raw: str, expected_slot_ids: Sequence[str]) -> DirectionOutput:
    """``AGENT.INVALID_JSON`` / ``AGENT.OUTPUT_SCHEMA_INVALID``; coverage: every input slot once,
    same order (an empty list only with a refusal)."""
    try:
        doc = json.loads(raw)
    except ValueError as exc:
        raise InvalidJsonError("model output is not JSON") from exc
    if not isinstance(doc, dict):
        raise InvalidJsonError("model output is not a JSON object")
    try:
        out = DirectionOutput.model_validate(doc)
    except ValidationError as exc:
        paths = ["/" + "/".join(str(p) for p in e["loc"]) + ": " + e["type"] for e in exc.errors()]
        raise OutputSchemaInvalidError(
            "model output violates the schema", details={"violations": paths[:50]}
        ) from exc
    ids = [d.slot_id for d in out.directions]
    if out.refusal is not None:
        if ids:
            raise OutputSchemaInvalidError(
                "refusal with directions", details={"violations": ["REFUSAL_WITH_DIRECTIONS"]}
            )
    elif ids != list(expected_slot_ids):
        raise OutputSchemaInvalidError(
            "slot coverage or order mismatch", details={"violations": ["SLOT_COVERAGE"]}
        )
    return out
