"""``FinPrefilter``, ``ForbiddenTokenScanner``, ``ForwardLookingScanner`` (blueprint 6.4).

Recall-oriented engines: a hit is a check result, never a verdict, and the checks can only add
blocking (Agent 06 and Agent 16 keep the final authority).
"""

import re

from agent_05_scriptwriter.lexicon import LexiconPack, PatternRule, any_match, compiled
from agent_05_scriptwriter.text import normalise_for_matching, split_sentences

URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")
HASHTAG = re.compile(r"(?<![\w#])#[^\W\d_][\w]*", re.UNICODE)

TOKEN_ORDER = ("URL", "EMAIL", "HASHTAG", "REFERRAL_CODE", "FIRST_PERSON", "DISCLAIMER_LIKE")


def _rule_fires(rule: PatternRule, sentence: str) -> bool:
    return all(any_match(group, sentence) for group in rule.requires)


def _fired(rules: tuple[PatternRule, ...], text: str) -> list[str]:
    text = normalise_for_matching(text).text
    sentences = split_sentences(text) or [text]
    hits = {rule.rule_id for rule in rules for sentence in sentences if _rule_fires(rule, sentence)}
    return sorted(hits)


class FinPrefilter:
    """FIN-R1/R2/R3/R6/R7/R8 patterns of the language lexicon."""

    def __init__(self, lexicons: LexiconPack) -> None:
        self._lexicons = lexicons

    def scan(self, text: str, language: str) -> list[str]:
        return _fired(self._lexicons.for_language(language).fin_rules, text)


class ForbiddenTokenScanner:
    """URL, e-mail, hashtag, referral code, first-person claim, disclaimer-like text."""

    def __init__(self, lexicons: LexiconPack) -> None:
        self._lexicons = lexicons

    def scan(self, text: str, language: str) -> list[str]:
        lex = self._lexicons.for_language(language)
        text = normalise_for_matching(text).text
        found: set[str] = set()
        if URL.search(text):
            found.add("URL")
        if EMAIL.search(text):
            found.add("EMAIL")
        if HASHTAG.search(text):
            found.add("HASHTAG")
        if any_match(lex.referral, text):
            found.add("REFERRAL_CODE")
        if any_match(lex.first_person, text):
            found.add("FIRST_PERSON")
        if any_match(lex.disclaimer_like, text):
            found.add("DISCLAIMER_LIKE")
        return [t for t in TOKEN_ORDER if t in found]

    def brand_intro(self, text: str, language: str) -> bool:
        """A channel name, greeting or brand element (used before the proof beat ends)."""
        return any_match(self._lexicons.for_language(language).brand_intro, text)


class ForwardLookingScanner:
    """FIN-R13 (IN-03): a forward statement about a named security in a historical case scene."""

    def __init__(self, lexicons: LexiconPack) -> None:
        self._lexicons = lexicons

    def scan(self, text: str, language: str, scene_kind: str) -> list[str]:
        # Review M3: scanned on every script surface, whatever the section kind.
        _ = scene_kind
        return _fired(self._lexicons.for_language(language).forward_rules, text)


def promise_outcome_terms(lexicons: LexiconPack, text: str, language: str) -> bool:
    """True when a promise text contains a guaranteed-outcome / urgency word of the lexicon."""
    patterns = lexicons.for_language(language).promise_forbidden
    normalised = normalise_for_matching(text).text
    return any(compiled(p).search(normalised) for p in patterns)
