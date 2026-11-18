"""Versioned scanner lexicons (blueprint 6.4).

The lexicon *content* is owned with the rule-pack text in 13 section 5 and is **REQUIRES REVIEW
(Phase 1)**; this package ships the engine and the data model only, never invented word lists.
The worker loads a ``LexiconPack`` from the rule-pack store (``RulePackStore``); tests use a small
fixed ``lex_test_v1`` that exists only in the test tree.
"""

import re
from collections.abc import Sequence
from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field

from agent_05_scriptwriter.errors import ConfigInvalid


class PatternRule(BaseModel):
    """A rule fires when, in one sentence, every group has at least one matching alternative."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str = Field(pattern=r"^[A-Z]{2,8}-R[0-9]{1,3}$")
    requires: tuple[tuple[str, ...], ...] = Field(min_length=1)


class LanguageLexicon(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fin_rules: tuple[PatternRule, ...] = ()
    forward_rules: tuple[PatternRule, ...] = ()
    first_person: tuple[str, ...] = ()
    referral: tuple[str, ...] = ()
    disclaimer_like: tuple[str, ...] = ()
    brand_intro: tuple[str, ...] = ()
    promise_forbidden: tuple[str, ...] = ()


class LexiconPack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    languages: dict[str, LanguageLexicon]

    def for_language(self, language: str) -> LanguageLexicon:
        try:
            return self.languages[language]
        except KeyError:
            raise ConfigInvalid(f"lexicon {self.name} has no entry for {language}") from None


@lru_cache(maxsize=2048)
def compiled(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE | re.UNICODE)


def any_match(patterns: Sequence[str], text: str) -> bool:
    return any(compiled(p).search(text) for p in patterns)
