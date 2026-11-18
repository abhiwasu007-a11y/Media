"""NearCopyChecker (C4, F-13; YTG-R9, 13 section 8): n-gram overlap and longest common substring
of a script sentence against its cited chunks, in the **private worker only**. Only IDs and
measures leave this module; chunk text is never persisted, logged or returned (NF-07).

Thresholds (``compliance.paraphrase.ngram_n``, ``.max_overlap_ratio``, ``.lcs_max_chars``) are
REQUIRES REVIEW (Phase 1): while unset, every sentence with any overlap is a judge candidate and
the measure is reported only; a configured threshold that is exceeded is a code flag
(``NEEDS_HUMAN_REVIEW``) that no judge answer can clear.
"""

import re
from collections.abc import Sequence
from difflib import SequenceMatcher
from typing import Protocol

from agent_16_compliance_qa.base import Model
from amw_core.errors import CrossTenantRefError
from amw_core.interfaces.tenancy_context import TenantTransaction

_WORD = re.compile(r"\w+", re.UNICODE)


class ChunkText(Model):
    chunk_id: str
    org_id: str
    collection_id: str
    text: str


class PrivateChunkReader(Protocol):
    """Reads chunk text from the org's channel-isolated collection (ADR-013, private worker)."""

    def read(self, tx: TenantTransaction, chunk_id: str) -> ChunkText: ...


class NearCopyResult(Model):
    sentence_ref: str
    chunk_id: str
    overlap_ratio: float | None
    """``None`` while ``compliance.paraphrase.ngram_n`` is unset (measure not computed)."""
    lcs_chars: int
    candidate: bool
    exceeds_threshold: bool


def _ngrams(text: str, n: int) -> set[tuple[str, ...]]:
    words = [w.casefold() for w in _WORD.findall(text)]
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def measure(sentence: str, chunk: str, n: int) -> tuple[float, int]:
    grams = _ngrams(sentence, n)
    ratio = len(grams & _ngrams(chunk, n)) / len(grams) if grams else 0.0
    a, b = sentence.casefold(), chunk.casefold()
    m = SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b))
    return round(ratio, 4), m.size


def check_near_copy(
    tx: TenantTransaction,
    sentences: Sequence[tuple[str, str, Sequence[str]]],
    reader: PrivateChunkReader,
    collection_id: str,
    n: int | None,
    max_overlap: float | None,
    lcs_max: int | None,
) -> list[NearCopyResult]:
    """``sentences``: (sentence_ref, text, cited chunk IDs). A chunk of another org or another
    channel's collection is refused (S-05)."""
    org = tx.context.org_id
    out: list[NearCopyResult] = []
    for ref, text, chunk_ids in sentences:
        for cid in chunk_ids:
            chunk = reader.read(tx, cid)
            if chunk.org_id != org or chunk.collection_id != collection_id:
                raise CrossTenantRefError("cited chunk is outside the channel's collection")
            ratio: float | None
            if n is None:  # not configured: every cited sentence goes to the judge
                ratio, lcs = None, measure(text, chunk.text, 1)[1]
            else:
                ratio, lcs = measure(text, chunk.text, n)
            exceeds = (max_overlap is not None and ratio is not None and ratio > max_overlap) or (
                lcs_max is not None and lcs > lcs_max
            )
            out.append(
                NearCopyResult(
                    sentence_ref=ref,
                    chunk_id=cid,
                    overlap_ratio=ratio,
                    lcs_chars=lcs,
                    candidate=ratio is None or ratio > 0 or exceeds,
                    exceeds_threshold=exceeds,
                )
            )
    return out
