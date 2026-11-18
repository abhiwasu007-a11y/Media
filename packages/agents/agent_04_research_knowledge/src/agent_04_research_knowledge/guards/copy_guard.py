"""CopyGuard (blueprint 10.6; YTG-R9, 13 section 8, IN-08): similarity of a note to source text.

A note fails when ANY of four independent measures reaches its configured threshold:

* longest verbatim run of words (``max_verbatim_words``);
* containment of the note's word n-grams in the passage (``max_containment_ratio``, size
  ``ngram_n``);
* windowed longest-common-subsequence ratio (``max_lcs_ratio``): tolerates inserted filler words,
  changed words and local re-wording;
* fuzzy run (``max_fuzzy_words`` matched words in one aligned segment with at most
  ``fuzzy_edits`` substitutions, insertions or deletions): "one word changed in every eight".

Every threshold is configuration (``CopyGuardSettings``, REQUIRES REVIEW owner/counsel); this
module has none. Texts are compared through ``normalise_for_matching`` only; the decision to skip
a pair as cross-language rests on the scripts of the actual texts (``scripts_differ``), never on
language tags. Same-script pairs (Marathi and Hindi, English and transliterated Hindi) are always
checked. Pure; results hold numbers only.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from agent_04_research_knowledge.guards.text_match import normalise_for_matching, scripts_differ

CROSS_LANGUAGE = "CROSS_LANGUAGE"
MIN_SHARED_WORDS = 3


@dataclass(frozen=True, slots=True)
class CopyThresholds:
    """Mirror of ``CopyGuardSettings`` (no defaults by design)."""

    max_verbatim_words: int
    ngram_n: int
    max_containment_ratio: float
    max_lcs_ratio: float
    fuzzy_edits: int
    max_fuzzy_words: int


@dataclass(frozen=True, slots=True)
class CopyResult:
    longest_shared_run: int
    overlap_ratio: float
    """Containment of the note's word n-grams in the passage (0..1)."""
    passed: bool
    skipped_reason: str | None
    lcs_ratio: float = 0.0
    fuzzy_run: int = 0


def _shingles(words: Sequence[str], n: int) -> set[tuple[str, ...]]:
    if n <= 0 or len(words) < n:
        return set()
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def longest_shared_run(note_words: Sequence[str], passage_words: Sequence[str]) -> int:
    """Longest run of consecutive words present in both (dynamic programming)."""
    if not note_words or not passage_words:
        return 0
    best = 0
    previous = [0] * (len(passage_words) + 1)
    for nw in note_words:
        current = [0] * (len(passage_words) + 1)
        for j, pw in enumerate(passage_words, start=1):
            if nw == pw:
                current[j] = previous[j - 1] + 1
                best = max(best, current[j])
        previous = current
    return best


def lcs_length(a: Sequence[str], b: Sequence[str]) -> int:
    previous = [0] * (len(b) + 1)
    for x in a:
        current = [0]
        for j, y in enumerate(b, start=1):
            current.append(previous[j - 1] + 1 if x == y else max(previous[j], current[j - 1]))
        previous = current
    return previous[-1]


def windowed_lcs_ratio(note: Sequence[str], passage: Sequence[str]) -> float:
    """Best LCS(note, window) / len(note) over windows of twice the note length."""
    if not note or not passage:
        return 0.0
    win = 2 * len(note) + 2
    stride = max(1, len(note) // 2)
    anchors = set(note)
    best = 0
    for start in range(0, max(1, len(passage) - win + stride), stride):
        window = passage[start : start + win]
        if not anchors.intersection(window):
            continue
        best = max(best, lcs_length(note, window))
    return best / len(note)


def fuzzy_run(note: Sequence[str], passage: Sequence[str], max_edits: int) -> int:
    """Most matched words in one aligned segment with at most ``max_edits`` edits.

    An edit is a substitution, a word inserted in the note or a word missing from the note.
    """
    if not note or not passage:
        return 0
    m = len(passage)
    best = 0
    # f[e][j]: matched words of the best segment ending at (current note word, passage j), e edits
    prev = [[0] * (m + 1) for _ in range(max_edits + 1)]
    for nw in note:
        cur = [[0] * (m + 1) for _ in range(max_edits + 1)]
        for e in range(max_edits + 1):
            for j in range(1, m + 1):
                v = prev[e][j - 1] + 1 if nw == passage[j - 1] else 0
                if e:
                    v = max(v, prev[e - 1][j - 1], prev[e - 1][j], cur[e - 1][j - 1])
                cur[e][j] = v
                best = max(best, v)
        prev = cur
    return best


def coverage_positions(note_words: Sequence[str], passage_words: Sequence[str], n: int) -> set[int]:
    """Positions of ``passage_words`` that lie inside an n-gram also present in the note."""
    shared = _shingles(note_words, n) & _shingles(passage_words, n)
    covered: set[int] = set()
    for i in range(len(passage_words) - n + 1):
        if tuple(passage_words[i : i + n]) in shared:
            covered.update(range(i, i + n))
    return covered


class CopyGuard:
    def check(self, note: str, passage: str, thresholds: CopyThresholds) -> CopyResult:
        """Compare one note with one passage. Skipped only when the scripts truly differ."""
        if scripts_differ(note, passage):
            return CopyResult(0, 0.0, True, CROSS_LANGUAGE)
        nw, pw = normalise_for_matching(note), normalise_for_matching(passage)
        run = longest_shared_run(nw, pw)
        note_shingles = _shingles(nw, thresholds.ngram_n)
        containment = (
            len(note_shingles & _shingles(pw, thresholds.ngram_n)) / len(note_shingles)
            if note_shingles
            else 0.0
        )
        lcs, fuzzy = 0.0, 0
        if len(set(nw) & set(pw)) >= MIN_SHARED_WORDS:
            lcs = windowed_lcs_ratio(nw, pw)
            fuzzy = fuzzy_run(nw, pw, thresholds.fuzzy_edits)
        passed = (
            run < thresholds.max_verbatim_words
            and containment < thresholds.max_containment_ratio
            and lcs < thresholds.max_lcs_ratio
            and fuzzy < thresholds.max_fuzzy_words
        )
        return CopyResult(run, containment, passed, None, lcs, fuzzy)

    def check_pool(
        self, note: str, passages: Sequence[str], thresholds: CopyThresholds
    ) -> CopyResult:
        """The note against every passage of the job's retrieval set: the worst result wins
        (a failing pair beats a passing one; among equals the larger similarity is reported)."""
        worst: CopyResult | None = None
        for text in passages:
            res = self.check(note, text, thresholds)
            if worst is None or _severity(res) > _severity(worst):
                worst = res
        return worst or CopyResult(0, 0.0, True, None)


def _severity(r: CopyResult) -> tuple[int, int, float, float, int]:
    return (
        0 if r.skipped_reason else 1,
        0 if r.passed else 1,
        r.overlap_ratio,
        r.lcs_ratio,
        r.longest_shared_run,
    )
