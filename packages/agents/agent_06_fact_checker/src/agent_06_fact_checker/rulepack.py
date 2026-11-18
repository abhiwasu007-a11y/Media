"""Rule-pack record and resolver port (13 2.1/2.2; blueprint 9.1 ``RulePackResolver``).

The FIN pre-filter lexicons are *data of the rule-pack record*: the future markers (D11, 13 5.4,
CCR-046, ``compliance.finance_sebi_in.markers.*``), the instrument names, the detector rules, the
suffix lists and the severity floor table (``FinLexicon``). Nothing in the step code carries a word
list. ``load_provisional_finance_lexicon`` reads the baseline data file shipped with the package
(``data/finance_sebi_in.provisional.json``): provisional, REQUIRES REVIEW (owner / counsel).
"""

import json
from collections.abc import Mapping
from importlib.resources import files
from typing import Protocol, runtime_checkable

from agent_06_fact_checker.models import RuleIdStr, RulePackKeyStr, Sha256Str
from amw_core.contracts.common import AmwModel
from amw_core.enums import RuleSeverity
from amw_core.errors import ConfigInvalidError

PROVISIONAL_FILE = "finance_sebi_in.provisional.json"


class DetectorRule(AmwModel):
    """One deterministic pattern: every group must match (a group is an OR of terms)."""

    rule_id: RuleIdStr
    severity: RuleSeverity
    lang: str
    groups: tuple[tuple[str, ...], ...]
    needs_instrument: bool = False
    needs_number: bool = False
    warn_if: tuple[str, ...] = ()
    """Any of these terms in the sentence lowers a code detection to WARNING (e.g. a backtest)."""
    quote_warn: bool = False
    """A match inside quotation marks (a third party's words) is a WARNING."""


class FinLexicon(AmwModel):
    status: str
    instruments: Mapping[str, tuple[str, ...]]
    suffixes: Mapping[str, tuple[str, ...]]
    severity_floor: Mapping[str, str | Mapping[str, str]]
    claim_type_floor: tuple[str, ...]
    detectors: tuple[DetectorRule, ...]


class RulePack(AmwModel):
    key: RulePackKeyStr
    version: int
    text: str
    """Rule text injected at ``{{rule_pack:<key>}}`` (read-only platform blob)."""
    rules_sha256: Sha256Str
    markers: Mapping[str, tuple[str, ...]] = {}
    """Future-tense / modal / expectation markers per language (``markers.<lang>``)."""
    lexicon: FinLexicon | None = None


@runtime_checkable
class RulePackResolver(Protocol):
    def resolve(self, key: str) -> RulePack:
        """The ACTIVE pack for ``key``; ``MissingDependencyError`` if it cannot be resolved.
        The pack file must hash to ``rules_sha256`` (13 2.1), otherwise it is refused."""
        ...


def load_provisional_finance_lexicon() -> tuple[Mapping[str, tuple[str, ...]], FinLexicon]:
    """The baseline markers and ``FinLexicon`` of the shipped provisional data file."""
    raw = json.loads(
        files("agent_06_fact_checker").joinpath("data", PROVISIONAL_FILE).read_text("utf-8")
    )
    markers = {k: tuple(v) for k, v in raw.pop("markers").items()}
    return markers, FinLexicon.model_validate(raw)


def required_languages(language: str) -> tuple[str, ...]:
    """Marker lists a script needs: English always (Latin terms occur in every script) plus the
    script's own language, plus Hinglish for a Latin-script Hindi / Marathi tag."""
    parts = language.lower().split("-")
    primary = parts[0]
    need = ["en"]
    if primary != "en":
        need.append(primary)
    if primary in ("hi", "mr") and "latn" in parts[1:]:
        need.append("hinglish")
    return tuple(need)


def ensure_lexicon(pack: RulePack, language: str) -> None:
    """Fail closed (``PERMANENT.CONFIG_INVALID``) when the finance pack's lexicon is empty or has
    no list for the script's language: a silent no-op pre-filter is not acceptable (13 3, 5.4)."""
    if pack.lexicon is None or not pack.lexicon.detectors:
        raise ConfigInvalidError("finance rule pack has no detector lexicon")
    missing = [lang for lang in required_languages(language) if not pack.markers.get(lang)]
    if missing:
        raise ConfigInvalidError(
            "finance rule pack has no future-marker list for the script language",
            details={"missing_languages": missing},
        )
    if not any(pack.lexicon.instruments.values()):
        raise ConfigInvalidError("finance rule pack has no instrument names")


__all__ = [
    "DetectorRule",
    "FinLexicon",
    "RulePack",
    "RulePackResolver",
    "ensure_lexicon",
    "load_provisional_finance_lexicon",
    "required_languages",
]
