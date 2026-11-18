"""``ConflictCandidateFinder`` (V8; blueprint 6.7, 10.3). Deliberately recall-oriented: the model
decides, a candidate pair is not reported unless the model reports it."""

import re
from collections.abc import Sequence

from agent_06_fact_checker.config import FactCheckSettings
from agent_06_fact_checker.models import VerificationClaim
from agent_06_fact_checker.numbers import numerals

_TOKEN = re.compile(r"[\wऀ-ॿ]+")


def _content_tokens(text: str, stop: frozenset[str]) -> set[str]:
    out = set()
    for tok in _TOKEN.findall(text.casefold()):
        if tok in stop or tok.isdigit():
            continue
        out.add(tok)
    return out


def find_pairs(
    claims: Sequence[VerificationClaim], settings: FactCheckSettings
) -> list[tuple[str, str]]:
    """Unordered candidate pairs as ``(local_id, local_id)`` in input order, capped."""
    stop = frozenset(w.casefold() for ws in settings.conflict_stop_words.values() for w in ws)
    opposites = [
        (a.casefold(), b.casefold()) for ps in settings.conflict_opposites.values() for a, b in ps
    ]
    negations = frozenset(w.casefold() for ws in settings.conflict_negations.values() for w in ws)
    views = [
        (
            c,
            _content_tokens(c.normalized_claim, stop),
            {n.text for n in numerals(c.normalized_claim)},
            set(_TOKEN.findall(c.normalized_claim.casefold())),
        )
        for c in claims
    ]
    pairs: list[tuple[str, str]] = []
    for i, (ca, ta, na, wa) in enumerate(views):
        for cb, tb, nb, wb in views[i + 1 :]:
            if len(ta & tb) < settings.conflict_min_shared_tokens:
                continue
            number_diff = bool(na) and bool(nb) and na != nb
            direction = any((a in wa and b in wb) or (b in wa and a in wb) for a, b in opposites)
            negation = bool(wa & negations) != bool(wb & negations)
            if number_diff or direction or negation:
                pairs.append((ca.local_id, cb.local_id))
                if len(pairs) >= settings.conflict_max_pairs:
                    return pairs
    return pairs
