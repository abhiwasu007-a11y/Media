"""``AiPromptComposer`` (D14): the deterministic text prompt of an AI generation request.

A free-text, model-written prompt would be a second injection path and an uncontrolled cost, so v1
composes the prompt from validated fields and a fixed negative-constraint tail, and rejects what
may never be generated: a presenter or real person on a finance channel (FIN-R11), a market-data
visual on a finance channel, anything the query plan already flagged as needing a real person.
The lexicons are rule content owned by 13 and are injected (never literals here).
"""

import hashlib
from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum

from amw_core.errors import InputInvalidError
from amw_core.text_normalise import normalise_for_matching, tokenize

CONSTRAINTS = (
    "Constraints: no people's faces, no readable text, no logos, no real persons, "
    "no real events, no watermark."
)
FINANCE = "finance"


class PromptRejection(StrEnum):
    PROHIBITED_DEPICTION = "PROHIBITED_DEPICTION"
    PRESENTER_OR_REAL_PERSON = "PRESENTER_OR_REAL_PERSON"
    MARKET_DATA_VISUAL = "MARKET_DATA_VISUAL"


@dataclass(frozen=True, slots=True)
class Lexicon:
    lexicon_id: str
    presenter_terms: Collection[str]
    market_data_terms: Collection[str]


@dataclass(frozen=True, slots=True)
class ComposedPrompt:
    prompt: str | None
    prompt_sha256: str | None
    rejection: PromptRejection | None = None


def _words(text: str) -> list[str]:
    """Whole-word tokens of the shared core normaliser (CCR-105); the same function folds the
    lexicon entries, so zero-width, look-alike and case variants of a term still match."""
    return [t.text for t in tokenize(normalise_for_matching(text))]


def _has_term(text: str, terms: Collection[str]) -> bool:
    words = _words(text)
    for term in terms:
        needle = _words(term)
        n = len(needle)
        if n and any(words[i : i + n] == needle for i in range(len(words) - n + 1)):
            return True
    return False


class AiPromptComposer:
    @staticmethod
    def compose(
        *,
        description: str,
        channel_category: str,
        style: str,
        max_chars: int,
        needs_real_person: bool,
        lexicon: Lexicon,
    ) -> ComposedPrompt:
        if not description.strip() or len(description) > max_chars:
            raise InputInvalidError("shot description is empty or above the length limit")
        if needs_real_person:
            return ComposedPrompt(None, None, PromptRejection.PROHIBITED_DEPICTION)
        if channel_category == FINANCE:
            if _has_term(description, lexicon.presenter_terms):
                return ComposedPrompt(None, None, PromptRejection.PRESENTER_OR_REAL_PERSON)
            if _has_term(description, lexicon.market_data_terms):
                return ComposedPrompt(None, None, PromptRejection.MARKET_DATA_VISUAL)
        prompt = f"{description.strip().rstrip('.')}. Style: {style}. {CONSTRAINTS}"
        return ComposedPrompt(prompt, hashlib.sha256(prompt.encode("utf-8")).hexdigest())
