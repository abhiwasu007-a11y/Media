"""Text preparation: sanitiser, pronunciation dictionary, unknown-term scanner (F-06...F-09).

Everything here is a pure function (27 section 7.3 rule 7). The request-construction order is the
one of blueprint 6.3: take the text as stored, NFC and control-character removal, dictionary
substitution, markup escaping, reject empty. There is no user regular expression: matching is by
literal comparison, so there is no ReDoS surface (7.4).
"""

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from agent_07_voice_production.contracts import (
    DictEntry,
    DictionaryDocument,
    DictionaryHit,
    MatchType,
    ReplacementMode,
    ScriptScene,
    ScriptSegment,
    UnknownTerm,
    UnknownTermSource,
)
from amw_core.errors import CorruptedOutputError, InputInvalidError

ZWNJ = "‌"
ZWJ = "‍"
MARKUP_CHARS = ("<", ">", "&")
_ESCAPES = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}
_LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z0-9'_-]*")
_DIGIT_RUN = re.compile(r"[0-9०-९]+")


def is_word_char(ch: str) -> bool:
    """Letters, marks, digits and ZWJ/ZWNJ (6.3 step 3). Devanagari vowel signs are marks (Mc/Mn),
    so a plain alphanumeric class would split Marathi words."""
    return unicodedata.category(ch)[0] in "LMN" or ch in (ZWJ, ZWNJ)


# --- sanitiser (F-09) --------------------------------------------------------------------


def sanitise(text: str) -> str:
    """NFC, control characters removed, whitespace collapsed (6.3 step 2).

    Tab and line breaks count as whitespace; other control (Cc) and format (Cf) characters are
    removed except ZWJ/ZWNJ, which Devanagari conjuncts need.
    """
    out: list[str] = []
    for ch in unicodedata.normalize("NFC", text):
        cat = unicodedata.category(ch)
        if ch.isspace():
            out.append(" ")
        elif cat == "Cc" or (cat == "Cf" and ch not in (ZWJ, ZWNJ)):
            continue
        else:
            out.append(ch)
    return " ".join("".join(out).split())


def escape_markup(text: str, extra_delimiters: Iterable[str] = ()) -> str:
    """Markup-significant characters are escaped so script text is never provider markup (6.3 step 4)."""
    escaped = "".join(_ESCAPES.get(ch, ch) for ch in text)
    for delimiter in extra_delimiters:
        escaped = escaped.replace(delimiter, "".join(f"&#{ord(c)};" for c in delimiter))
    return escaped


def markup_characters(text: str) -> tuple[str, ...]:
    return tuple(ch for ch in MARKUP_CHARS if ch in text)


# --- dictionary (F-06, F-07) -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Match:
    start: int
    end: int
    entry: DictEntry


@dataclass(frozen=True, slots=True)
class AppliedText:
    text: str
    hits: tuple[DictionaryHit, ...]
    skipped_phoneme_entries: int = 0
    expected_matches: int = 0
    """Matches found in the input: the denominator of ``qc.voice.dictionary_applied``."""


class PronunciationDictionary:
    """A verified, immutable dictionary version (load rules of F-06)."""

    def __init__(self, document: DictionaryDocument, sha256: str) -> None:
        self.document = document
        self.sha256 = sha256
        self._entries = tuple(
            sorted(document.entries, key=lambda e: (-len(e.match.value), e.entry_id))
        )
        self._validate()

    @classmethod
    def from_bytes(
        cls, data: bytes, expected_sha256: str | None, language: str
    ) -> "PronunciationDictionary":
        """Parse and verify a dictionary blob. ``expected_sha256`` None means "use the hash stored
        with the row"; the caller always passes the row hash then (the loader never skips it)."""
        digest = hashlib.sha256(data).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise CorruptedOutputError("pronunciation dictionary hash mismatch")
        try:
            document = DictionaryDocument.model_validate(json.loads(data))
        except (ValueError, TypeError) as exc:
            raise InputInvalidError(
                "pronunciation dictionary does not match its schema",
                details={"violations": [{"path": "", "keyword": "schema", "message": str(exc)[:300]}]},
            ) from exc
        if document.language.split("-")[0] != language.split("-")[0]:
            raise InputInvalidError("pronunciation dictionary language differs from the script")
        return cls(document, digest)

    @property
    def entries(self) -> tuple[DictEntry, ...]:
        return self._entries

    def _validate(self) -> None:
        ids = [e.entry_id for e in self._entries]
        if len(set(ids)) != len(ids):
            raise InputInvalidError("duplicate dictionary entry_id")
        seen: dict[tuple[str, str, bool], tuple[str, str]] = {}
        for e in self._entries:
            key = (e.match.type, e.match.value, e.match.case_sensitive)
            val = (e.replacement.mode, e.replacement.text)
            if key in seen and seen[key] != val:
                raise InputInvalidError(
                    "duplicate dictionary match with different replacements",
                    details={"entry_id": e.entry_id},
                )
            seen[key] = val
        for e in self._entries:
            if self._find(e.replacement.text, self._entries):
                raise InputInvalidError(
                    "a replacement matches a dictionary entry (chained rewrite)",
                    details={"entry_id": e.entry_id},
                )

    @staticmethod
    def _find(text: str, entries: Sequence[DictEntry]) -> list[_Match]:
        """Left to right; at one position the longest entry wins (ties: lowest entry_id);
        matches never overlap."""
        found: list[_Match] = []
        pos = 0
        length = len(text)
        folded = text.lower()
        while pos < length:
            chosen: _Match | None = None
            for entry in entries:  # already ordered by length desc, entry_id
                value = entry.match.value
                n = len(value)
                if entry.match.case_sensitive:
                    if not text.startswith(value, pos):
                        continue
                elif folded[pos : pos + n] != value.lower() or len(value.lower()) != n:
                    continue
                end = pos + n
                if entry.match.type is MatchType.WORD and (
                    (pos > 0 and is_word_char(text[pos - 1]))
                    or (end < length and is_word_char(text[end]))
                ):
                    continue
                chosen = _Match(pos, end, entry)
                break
            if chosen is None:
                pos += 1
            else:
                found.append(chosen)
                pos = chosen.end
        return found

    def apply(self, text: str, *, phoneme_support: bool) -> AppliedText:
        """F-07. ``PHONEME`` entries are skipped when the adapter lacks phoneme support."""
        usable = tuple(
            e
            for e in self._entries
            if phoneme_support or e.replacement.mode is not ReplacementMode.PHONEME
        )
        skipped = sum(1 for e in self._entries if e not in usable)
        matches = self._find(text, usable)
        out: list[str] = []
        cursor = 0
        counts: dict[str, int] = {}
        order: list[str] = []
        for m in matches:
            out.append(text[cursor : m.start])
            out.append(m.entry.replacement.text)
            cursor = m.end
            if m.entry.entry_id not in counts:
                order.append(m.entry.entry_id)
            counts[m.entry.entry_id] = counts.get(m.entry.entry_id, 0) + 1
        out.append(text[cursor:])
        by_id = {e.entry_id: e for e in self._entries}
        hits = tuple(
            DictionaryHit(
                entry_id=i, segment_id="s0", count=counts[i], mode=by_id[i].replacement.mode
            )
            for i in order
        )
        return AppliedText("".join(out), hits, skipped, len(matches))


# --- unknown terms (F-08) ----------------------------------------------------------------


def term_hash(org_wire_id: str, term: str) -> str:
    """SHA-256 over the org wire id, a 0x00 byte and the normalised term (14): identical terms of
    two tenants never share a hash."""
    normalised = unicodedata.normalize("NFC", term).casefold().strip()
    return hashlib.sha256(org_wire_id.encode() + b"\x00" + normalised.encode()).hexdigest()


@dataclass(slots=True)
class _Unknown:
    term: str
    source: UnknownTermSource
    segments: list[str] = field(default_factory=list)


def scan_unknown_terms(
    *,
    org_wire_id: str,
    segments: Sequence[ScriptSegment],
    scenes: Sequence[ScriptScene],
    original_texts: Mapping[str, str],
    substituted_texts: Mapping[str, str],
    allow_list: frozenset[str] = frozenset(),
) -> tuple[UnknownTerm, ...]:
    """Candidates the dictionary did not cover, Latin and numeral tokens no entry matched, and
    markup characters found before escaping. Reported by hash and segment IDs only; never added
    to the dictionary (the owner decides after listening, 5.2)."""
    found: dict[tuple[str, UnknownTermSource], _Unknown] = {}

    def note(term: str, source: UnknownTermSource, segment_id: str) -> None:
        folded = unicodedata.normalize("NFC", term).casefold().strip()
        if not folded or folded in allow_list:
            return
        item = found.setdefault((folded, source), _Unknown(term, source))
        if segment_id not in item.segments:
            item.segments.append(segment_id)

    scene_of = {s.segment_id: s.scene_id for s in segments}
    candidates: dict[str, tuple[str, ...]] = {s.scene_id: s.pronunciation_candidates for s in scenes}
    for seg in segments:
        sid = seg.segment_id
        spoken = substituted_texts[sid]
        covered_spans: list[tuple[int, int]] = []
        for candidate in candidates.get(scene_of[sid], ()):
            if candidate and candidate in original_texts[sid] and candidate in spoken:
                note(candidate, UnknownTermSource.SCRIPT_CANDIDATE, sid)
                start = spoken.find(candidate)
                covered_spans.append((start, start + len(candidate)))
        for m in _LATIN_RUN.finditer(spoken):
            if any(a <= m.start() < b for a, b in covered_spans):
                continue
            note(m.group(0), UnknownTermSource.SCRIPT_CANDIDATE, sid)
        for m in _DIGIT_RUN.finditer(spoken):
            note(m.group(0), UnknownTermSource.NUMERAL, sid)
        for ch in markup_characters(original_texts[sid]):
            note(ch, UnknownTermSource.MARKUP_CHARACTER, sid)
    result = [
        UnknownTerm(
            term_sha256=term_hash(org_wire_id, u.term), segment_ids=tuple(u.segments), source=u.source
        )
        for u in found.values()
    ]
    return tuple(sorted(result, key=lambda t: (t.source, t.term_sha256)))


# --- request construction (6.3) ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PreparedSegment:
    segment_id: str
    sanitised: str
    spoken_text: str
    """Final text sent to the provider (substituted and escaped)."""
    spoken_text_sha256: str
    characters: int
    hits: tuple[DictionaryHit, ...]
    expected_matches: int
    skipped_phoneme_entries: int


def prepare_segment(
    segment: ScriptSegment,
    dictionary: PronunciationDictionary,
    *,
    phoneme_support: bool,
    max_chars_per_request: int | None,
    extra_delimiters: Iterable[str] = (),
) -> PreparedSegment:
    sanitised = sanitise(segment.text)
    applied = dictionary.apply(sanitised, phoneme_support=phoneme_support)
    spoken = escape_markup(applied.text, extra_delimiters)
    if not spoken:
        raise InputInvalidError(
            "a sentence is empty after sanitising", details={"segment_id": segment.segment_id}
        )
    if max_chars_per_request is not None and len(spoken) > max_chars_per_request:
        raise InputInvalidError(
            "a sentence is longer than the provider limit (Agent 07 never splits a sentence)",
            details={"segment_id": segment.segment_id, "limit": max_chars_per_request},
        )
    hits = tuple(
        DictionaryHit(entry_id=h.entry_id, segment_id=segment.segment_id, count=h.count, mode=h.mode)
        for h in applied.hits
    )
    return PreparedSegment(
        segment_id=segment.segment_id,
        sanitised=sanitised,
        spoken_text=spoken,
        spoken_text_sha256=hashlib.sha256(spoken.encode("utf-8")).hexdigest(),
        characters=len(spoken),
        hits=hits,
        expected_matches=applied.expected_matches,
        skipped_phoneme_entries=applied.skipped_phoneme_entries,
    )


def hits_by_entry(prepared: Iterable[PreparedSegment]) -> Mapping[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for p in prepared:
        for h in p.hits:
            totals[h.entry_id] += h.count
    return dict(totals)
