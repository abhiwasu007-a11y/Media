"""``amw.control`` 1.0.0 (03 section 4.3): cooperative drain / cancel / pause / resume."""

from typing import Annotated

from pydantic import StringConstraints

from amw_core.contracts.common import AmwModel, SchemaVersionV1, UtcTimestamp
from amw_core.enums import ControlCommandKind


class ControlCommand(AmwModel):
    command: ControlCommandKind
    reason: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    act_by: UtcTimestamp
    schema_version: SchemaVersionV1
