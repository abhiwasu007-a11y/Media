"""Shared constrained types of the Agent 08 payload models (patterns of blueprint 7 and 8)."""

from typing import Annotated

from pydantic import Field, StringConstraints

from amw_core.contracts.common import Currency, NonNegInt, Sha256Hex, StorageUri
from amw_core.ids import UUID7_BODY


def wire(prefix: str) -> str:
    return rf"^{prefix}_{UUID7_BODY}$"


ShotIdStr = Annotated[str, StringConstraints(pattern=r"^sh[0-9]{2,4}$")]
OverlayIdStr = Annotated[str, StringConstraints(pattern=r"^ov[0-9]{2,4}$")]
ChartIdStr = Annotated[str, StringConstraints(pattern=r"^chart_[0-9a-z_]{1,32}$")]
AssetIdStr = Annotated[str, StringConstraints(pattern=wire("ast"))]
LicenceIdStr = Annotated[str, StringConstraints(pattern=wire("lic"))]
LedgerIdStr = Annotated[str, StringConstraints(pattern=wire("lcu"))]
ScriptIdStr = Annotated[str, StringConstraints(pattern=wire("scr"))]
IsoDateStr = Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]
PerceptualHex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")]
StageIdStr = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{2,32}$")]
PosInt = Annotated[int, Field(ge=1, strict=True)]
Permille = Annotated[int, Field(ge=0, le=1000, strict=True)]

__all__ = [
    "AssetIdStr",
    "ChartIdStr",
    "Currency",
    "IsoDateStr",
    "LedgerIdStr",
    "LicenceIdStr",
    "NonNegInt",
    "OverlayIdStr",
    "Permille",
    "PerceptualHex",
    "PosInt",
    "ScriptIdStr",
    "Sha256Hex",
    "ShotIdStr",
    "StageIdStr",
    "StorageUri",
    "wire",
]
