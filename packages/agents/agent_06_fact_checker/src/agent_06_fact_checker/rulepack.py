"""Rule-pack record and resolver port (13 2.1/2.2; blueprint 9.1 ``RulePackResolver``).

The FIN pre-filter lexicons (D11 future markers, 13 5.4, CCR-046) are *data of the rule-pack
record* (config ``compliance.finance_sebi_in.markers.*``, one list per language). Nothing here or
in the step code carries a lexicon; contents belong to 13 and S2 (REQUIRES REVIEW, lawyer).
"""

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from agent_06_fact_checker.models import RulePackKeyStr, Sha256Str
from amw_core.contracts.common import AmwModel


class RulePack(AmwModel):
    key: RulePackKeyStr
    version: int
    text: str
    """Rule text injected at ``{{rule_pack:<key>}}`` (read-only platform blob)."""
    rules_sha256: Sha256Str
    markers: Mapping[str, tuple[str, ...]] = {}
    """Future-tense / modal / expectation markers per language (``markers.<lang>``)."""


@runtime_checkable
class RulePackResolver(Protocol):
    def resolve(self, key: str) -> RulePack:
        """The ACTIVE pack for ``key``; ``MissingDependencyError`` if it cannot be resolved.
        The pack file must hash to ``rules_sha256`` (13 2.1), otherwise it is refused."""
        ...
