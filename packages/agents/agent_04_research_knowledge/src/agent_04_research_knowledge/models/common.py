"""Shared constrained types and the refusal object (27 section 4.3)."""

from typing import Annotated

from pydantic import StringConstraints

from amw_core.contracts.common import AmwModel
from amw_core.enums import RefusalReason

LanguageTag = Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")]
CollectionKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{2,48}$")]
ConceptId = Annotated[str, StringConstraints(pattern=r"^c[0-9]{2}$")]
GapId = Annotated[str, StringConstraints(pattern=r"^g[0-9]{1,3}$")]
RuleId = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2,8}-R[0-9]{1,3}$")]
RulePackKeyStr = Annotated[str, StringConstraints(pattern=r"^rp\.[a-z0-9_]+$")]
ChannelCategory = Annotated[str, StringConstraints(pattern=r"^[a-z_]{3,32}$")]


class Refusal(AmwModel):
    """``refusal`` object of both prompt output schemas."""

    reason: RefusalReason
    message: Annotated[str, StringConstraints(max_length=1000)]
    missing_inputs: tuple[str, ...]
    violated_rule_ids: tuple[RuleId, ...]


__all__ = [
    "ChannelCategory",
    "CollectionKey",
    "ConceptId",
    "GapId",
    "LanguageTag",
    "Refusal",
    "RuleId",
    "RulePackKeyStr",
]
