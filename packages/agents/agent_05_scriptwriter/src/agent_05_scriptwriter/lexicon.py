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
from amw_core.text_normalise import normalise_for_matching


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


_META = set("\\[](){}|*+?.^$")


def _norm_run(run: str) -> str:
    """Normalise a literal run; the whitespace at its edges is kept (the normaliser trims it)."""
    lead = run[: len(run) - len(run.lstrip())]
    trail = run[len(run.rstrip()) :]
    core = run.strip()
    return lead + (normalise_for_matching(core).text if core else "") + (trail if core else "")


def normalise_pattern(pattern: str) -> str:
    """Normalise the literal runs of a regex with the shared function (escapes and operators are
    kept), so lexicon entries and scanned text meet in the same form."""
    out: list[str] = []
    run: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" or ch in _META:
            if run:
                out.append(_norm_run("".join(run)))
                run = []
            out.append(pattern[i : i + 2] if ch == "\\" else ch)
            i += 2 if ch == "\\" else 1
        else:
            run.append(ch)
            i += 1
    if run:
        out.append(_norm_run("".join(run)))
    return "".join(out)


@lru_cache(maxsize=2048)
def compiled(pattern: str) -> re.Pattern[str]:
    return re.compile(normalise_pattern(pattern), re.IGNORECASE | re.UNICODE)


def any_match(patterns: Sequence[str], text: str) -> bool:
    """Match on the normalised copy (zero-width characters and look-alike letters do not hide)."""
    normalised = normalise_for_matching(text).text
    return any(compiled(p).search(normalised) for p in patterns)
