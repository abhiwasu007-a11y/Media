"""``NearCopyGuard`` (blueprint 10.3; YTG-R9, IN-08).

Compares each sentence with the cited chunk texts and the brief summaries inside the private
worker. The texts live in ``WORKING`` memory only; results carry sentence indexes and numbers.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from agent_05_scriptwriter.settings import NearCopySettings
from agent_05_scriptwriter.text import words


@dataclass(frozen=True, slots=True)
class NearCopyResult:
    violation: bool
    overlap_ratio: float
    common_run_chars: int


def _ngrams(tokens: Sequence[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _longest_run(a: Sequence[str], b: Sequence[str]) -> int:
    """Longest common contiguous run of tokens, in tokens."""
    best = 0
    previous = [0] * (len(b) + 1)
    for tok_a in a:
        current = [0] * (len(b) + 1)
        for j, tok_b in enumerate(b, start=1):
            if tok_a == tok_b:
                current[j] = previous[j - 1] + 1
                best = max(best, current[j])
        previous = current
    return best


def check_sentence(
    sentence: str, cited_texts: Sequence[str], thresholds: NearCopySettings
) -> NearCopyResult:
    tokens = words(sentence)
    n = thresholds.ngram_n
    grams = _ngrams(tokens, n)
    matched: set[tuple[str, ...]] = set()
    best_run_tokens = 0
    best_run_chars = 0
    for cited in cited_texts:
        cited_tokens = words(cited)
        matched |= grams & _ngrams(cited_tokens, n)
        run = _longest_run(tokens, cited_tokens)
        if run > best_run_tokens:
            best_run_tokens = run
        if run:
            # characters of the longest run (words and single spaces between them)
            best_run_chars = max(best_run_chars, _run_chars(tokens, cited_tokens, run))
    ratio = len(matched) / len(grams) if grams else 0.0
    violation = (
        ratio > thresholds.max_overlap_ratio or best_run_chars > thresholds.max_common_run_chars
    )
    return NearCopyResult(violation, ratio, best_run_chars)


def _run_chars(a: Sequence[str], b: Sequence[str], run: int) -> int:
    index = {tuple(b[i : i + run]) for i in range(len(b) - run + 1)}
    for i in range(len(a) - run + 1):
        window = tuple(a[i : i + run])
        if window in index:
            return sum(len(w) for w in window) + run - 1
    return 0


def check_sentences(
    sentences: Sequence[str], cited_texts: Sequence[str], thresholds: NearCopySettings
) -> list[int]:
    """Indexes of violating sentences."""
    return [
        i
        for i, sentence in enumerate(sentences)
        if check_sentence(sentence, cited_texts, thresholds).violation
    ]
