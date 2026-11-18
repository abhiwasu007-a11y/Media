"""VisualGuard and InjectionScanner (F-14, F-32; blueprint 6.5 G1-G7).

Lexical and flag tests only; the model never audits itself. A hit carries the guard ID and the
slot ID, never content (27 section 7.3.6).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from agent_09_video_director.contracts import (
    AspectRatio,
    Direction,
    DirectionInput,
    DirectionSlot,
    SlotRole,
)

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_DIGIT = re.compile(r"\d")
_URL = re.compile(r"(https?://|www\.|\b[\w-]+\.(?:com|in|org|net|io|co|app|me)\b|@\w+)", re.I)
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_MARKUP = re.compile(r"[<>{}]|\[\[|\]\]|```")
_MARKERS = ("<<<INPUT", "INPUT>>>")
_INSTRUCTION = re.compile(
    r"\b(ignore|disregard|forget|override)\b.{0,30}\b(rules?|instructions?|prompt|above|previous)\b"
    r"|\b(system prompt|developer message|reveal|jailbreak)\b"
    r"|\b(you must|you should now|new instructions?)\b",
    re.I | re.S,
)


@dataclass(frozen=True, slots=True)
class GuardHit:
    guard: str
    slot_id: str


def scan_injection(text: str) -> list[str]:
    """F-32: pattern IDs only (URL, markup, marker, control character, instruction phrase)."""
    ids: list[str] = []
    if _URL.search(text):
        ids.append("URL")
    if _MARKUP.search(text):
        ids.append("MARKUP")
    if any(m in text for m in _MARKERS):
        ids.append("MARKER")
    if _CONTROL.search(text):
        ids.append("CONTROL")
    if _INSTRUCTION.search(text):
        ids.append("INSTRUCTION")
    return ids


def _proper_noun_like(text: str) -> bool:
    """Lexical G1 second line: an all-caps word or a capitalised word inside a sentence."""
    at_start = True
    for word in re.findall(r"[A-Za-z][A-Za-z'-]*|[.!?]", text):
        if word in ".!?":
            at_start = True
            continue
        if len(word) >= 2 and word.isupper():
            return True
        if word[0].isupper() and not at_start:
            return True
        at_start = False
    return False


def _longest_shared_run(output: str, source: str) -> int:
    """Longest run of consecutive words of ``output`` that also appears in ``source``."""
    out = [w.lower() for w in _WORD.findall(output)]
    src = " ".join(w.lower() for w in _WORD.findall(source))
    best = 0
    for i in range(len(out)):
        n = best + 1
        while i + n <= len(out) and " ".join(out[i : i + n]) in src:
            best = n
            n += 1
    return best


def scan_direction(
    d: Direction, slot: DirectionSlot, ctx: DirectionInput, *, echo_run_limit: int = 5
) -> list[GuardHit]:
    """G1-G6 for one direction; G7 (realism) is recorded elsewhere and never blocks."""
    hits: list[GuardHit] = []

    def hit(guard: str) -> None:
        hits.append(GuardHit(guard, d.slot_id))

    finance = ctx.channel_category == "finance"
    if d.status == "NO_SAFE_VISUAL":
        if d.reason_code is None or d.intent_kind is not None or d.intent_text != "":
            hit("G5")
        return hits
    # G5 kind and anchor
    if d.reason_code is not None or d.intent_kind is None:
        hit("G5")
    portrait = ctx.aspect_ratio is AspectRatio.PORTRAIT
    if portrait != (d.subject_anchor is not None):
        hit("G5")
    if d.intent_kind == "TEXT_CARD" and (d.intent_text != "" or not d.text_ids):
        hit("G5")
    # G1 vocabulary
    text = d.intent_text
    banned = [b.lower() for b in ctx.banned_subjects]
    if (
        len(text) > ctx.limits.max_intent_chars
        or len(d.rationale) > ctx.limits.max_rationale_chars
        or _DEVANAGARI.search(text)
        or _DIGIT.search(text)
        or _URL.search(text)
        or _proper_noun_like(text)
        or any(b in text.lower() for b in banned)
    ):
        hit("G1")
    # G2 flags
    dep = d.depiction
    if (
        dep.real_person
        or dep.identifiable_person
        or dep.brand_or_logo
        or dep.ai_presenter
        or dep.market_data_screen
        or (finance and dep.market_direction_imagery)
    ):
        hit("G2")
    # G3 text provenance
    allowed_ids = {o.text_id for o in slot.text_options}
    if any(t not in allowed_ids for t in d.text_ids):
        hit("G3")
    # G4 capability
    caps = ctx.capabilities
    is_interrupt = slot.role is SlotRole.INTERRUPT_REQUIRED
    if (
        (d.needs_ai_video and not caps.ai_video_allowed)
        or (d.still_ok and not caps.still_allowed)
        or (d.interrupt_device is not None and not is_interrupt)
    ):
        hit("G4")
    # G6 injection: scanner hits or an echo of input text (more than five consecutive words)
    source = " ".join(
        [
            slot.narration_excerpt,
            slot.scene_visual_intent.description,
            *(o.text for o in slot.text_options),
        ]
    )
    echoed = max(
        _longest_shared_run(d.intent_text, source), _longest_shared_run(d.rationale, source)
    )
    if scan_injection(d.intent_text) or scan_injection(d.rationale) or echoed > echo_run_limit:
        hit("G6")
    return hits


def scan_batch(directions: Sequence[Direction], ctx: DirectionInput) -> dict[str, list[GuardHit]]:
    by_slot = {s.slot_id: s for s in ctx.slots}
    return {d.slot_id: h for d in directions if (h := scan_direction(d, by_slot[d.slot_id], ctx))}
