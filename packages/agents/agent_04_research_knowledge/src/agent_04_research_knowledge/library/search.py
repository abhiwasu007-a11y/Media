"""FtsQueryBuilder: language to text-search configuration and query text (blueprint 6.6, 9)."""

import re
from dataclasses import dataclass

from agent_04_research_knowledge.errors import ConfigInvalid

_CONFIG_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_CONTROL = re.compile(r"[\x00-\x1f]")
MAX_QUERY_CHARS = 120


@dataclass(frozen=True, slots=True)
class FtsQuery:
    config: str
    text: str


class FtsQueryBuilder:
    """Resolves the text-search configuration of a query language.

    The per-language mapping is configuration (REQUIRES REVIEW, blueprint 6.6: Devanagari uses
    ``simple`` until verified). A configured name must be a plain identifier so it can be passed
    to ``to_tsquery`` only as an identifier-checked value.
    """

    def __init__(self, configs: dict[str, str], default_config: str) -> None:
        for name in (*configs.values(), default_config):
            if not _CONFIG_NAME.fullmatch(name):
                raise ConfigInvalid("unknown text-search configuration name")
        self._configs = {k.lower(): v for k, v in configs.items()}
        self._default = default_config

    def build(self, language: str, text: str) -> FtsQuery:
        cleaned = _CONTROL.sub(" ", text).strip()[:MAX_QUERY_CHARS]
        primary = language.split("-", 1)[0].lower()
        return FtsQuery(self._configs.get(primary, self._default), cleaned)
