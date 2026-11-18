"""ConceptGuards G1..G8 (F-11; blueprint 6.5). The model has no authority: code decides."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from agent_11_thumbnail_design.models import Concept, GuardHit, GuardId, StepIn
from agent_11_thumbnail_design.scanner import InjectionScanner
from agent_11_thumbnail_design.text_options import finance_text_hit
from agent_11_thumbnail_design.textutil import fold, folded_words

_URL = re.compile(r"https?://|www\.|\b[\w-]+\.(?:com|org|net|in|io|co)\b|@", re.IGNORECASE)
_MAX_COPIED_RUN = 5
_EVIDENCE_REASONS = {
    "NO_ELIGIBLE_TEXT": "no_eligible_text",
    "PROMISE_IS_A_CALL": "promise_is_call",
    "BANNED_SUBJECT": "banned_removed_all",
    "NO_DISTINCT_OPTION": "no_distinct_option",
    "INSTRUCTION_IN_INPUT": "instruction_flagged",
    "TOO_VAGUE": "too_vague",
}


@dataclass(frozen=True, slots=True)
class GuardContext:
    step_in: StepIn
    finance: bool
    faces_allowed: bool
    scanner: InjectionScanner
    neutral_lexicon: frozenset[str]
    fin_lexicon: Sequence[str] = ()
    evidence: Mapping[str, bool] = field(default_factory=dict)


def _wset(text: str) -> set[str]:
    return set(folded_words(text))


def _g1(c: Concept, idx: int, ctx: GuardContext) -> bool:
    s = ctx.step_in
    if c.concept_id != f"c{idx + 1}":
        return False
    if c.status != "OK":
        return True
    return (
        any(t.template_key == c.template_key for t in s.templates)
        and any(o.option_id == c.subject_option_id for o in s.subject_options)
        and all(any(t.text_id == tid for t in s.text_options) for tid in c.text_ids)
    )


def _g2(c: Concept, ctx: GuardContext) -> bool:
    s = ctx.step_in
    ids = c.text_ids
    if not 1 <= len(ids) <= 2 or len(set(ids)) != len(ids):
        return False
    opts = [next(t for t in s.text_options if t.text_id == tid) for tid in ids]
    must = [fold(m) for m in s.brief.must_not_promise if m.strip()]
    if any(m in fold(o.text) for o in opts for m in must):
        return False
    if len(opts) == 2 and _wset(opts[0].text) & _wset(opts[1].text):
        return False
    return any(o.key_term_ids for o in opts)


def _g3(c: Concept, ctx: GuardContext) -> bool:
    s = ctx.step_in
    tpl = next(t for t in s.templates if t.template_key == c.template_key)
    pic = next(o for o in s.subject_options if o.option_id == c.subject_option_id)
    return (
        pic.kind in tpl.supports_subject_kinds
        and tpl.text_lines_max >= len(c.text_ids)
        and (c.emphasis_style != "TWO_TONE" or len(c.text_ids) == 2)
    )


def _g4(c: Concept, ctx: GuardContext) -> bool:
    if not ctx.finance:
        return True
    s = ctx.step_in
    tpl = next(t for t in s.templates if t.template_key == c.template_key)
    pic = next(o for o in s.subject_options if o.option_id == c.subject_option_id)
    texts = [next(t for t in s.text_options if t.text_id == tid) for tid in c.text_ids]
    return (
        tpl.direction_neutral
        and pic.direction_neutral
        and not any(finance_text_hit(t.text, ctx.fin_lexicon) for t in texts)
    )


def _g5(c: Concept, ctx: GuardContext) -> bool:
    pic = next(o for o in ctx.step_in.subject_options if o.option_id == c.subject_option_id)
    return not pic.has_face or (ctx.faces_allowed and not ctx.finance)


def _g6(c: Concept, ctx: GuardContext) -> bool:
    s = ctx.step_in
    r = c.rationale
    if len(r) > s.limits.max_rationale_chars or not r.isascii():
        return False
    if any(ch.isdigit() for ch in r) or _URL.search(r):
        return False
    if ctx.scanner.scan(r).flagged:
        return False
    folded = fold(r)
    if any(fold(b) in folded for b in s.banned_subjects if b.strip()):
        return False
    rw = folded_words(r)
    for o in s.text_options:
        ow = folded_words(o.text)
        for i in range(len(ow) - _MAX_COPIED_RUN):
            run = ow[i : i + _MAX_COPIED_RUN + 1]
            if any(rw[j : j + len(run)] == run for j in range(len(rw) - len(run) + 1)):
                return False
    tokens = r.split()
    for pos, tok in enumerate(tokens):
        if pos == 0 or tokens[pos - 1][-1:] in ".!?":
            continue
        bare = tok.strip(".,;:!?\"'()")
        if bare[:1].isupper() and bare.casefold() not in ctx.neutral_lexicon:
            return False
    return True


def _differs(c: Concept, ref: Concept) -> list[str]:
    out = []
    if c.template_key != ref.template_key:
        out.append("LAYOUT_STYLE")
    if c.subject_option_id != ref.subject_option_id:
        out.append("SUBJECT_CHOICE")
    if c.text_ids != ref.text_ids:
        out.append("TEXT_ANGLE")
    return out


def _g7(c: Concept, idx: int, concepts: Sequence[Concept], ctx: GuardContext) -> bool:
    s = ctx.step_in
    if idx == 0:
        ok = c.hypothesis_kind == "CONTROL"
    else:
        control = concepts[0]
        diff = _differs(c, control) if control.status == "OK" else []
        ok = len(diff) == 1 and c.hypothesis_kind == diff[0]
    if not ok:
        return False
    ok_others = [o for o in concepts[:idx] if o.status == "OK"]
    if any(o.choices() == c.choices() for o in ok_others):
        return False
    if s.previous_concepts:
        prev = next((p for p in s.previous_concepts if p.concept_id == c.concept_id), None)
        if prev is not None:
            named = {f.variant_id for f in s.revision_feedback}
            vid = "v" + c.concept_id[1:]
            same = (
                prev.template_key == c.template_key
                and prev.subject_option_id == c.subject_option_id
                and prev.text_ids == c.text_ids
            )
            if prev.keep and not (
                same
                and prev.angle == (c.angle or prev.angle)
                and prev.hypothesis_kind == (c.hypothesis_kind or prev.hypothesis_kind)
            ):
                return False
            if (not prev.keep or vid in named) and same:
                return False
    return True


def _g8(c: Concept, ctx: GuardContext) -> bool:
    if (
        c.reason_code is None
        or c.template_key is not None
        or c.subject_option_id is not None
        or c.text_ids
    ):
        return False
    s = ctx.step_in
    ev = dict(ctx.evidence)
    ev.setdefault("no_eligible_text", not s.text_options)
    ev.setdefault("too_vague", not any(t.key_term_ids for t in s.text_options))
    return bool(ev.get(_EVIDENCE_REASONS[c.reason_code], False))


def check_concepts(concepts: Sequence[Concept], ctx: GuardContext) -> list[GuardHit]:
    """First failing guard per concept, in the order G1..G8 (count mismatch hits the missing id)."""
    hits: list[GuardHit] = []
    for idx, c in enumerate(concepts):
        guard = _first_failure(c, idx, concepts, ctx)
        if guard:
            hits.append(GuardHit(concept_id=c.concept_id, guard=guard))
    for idx in range(len(concepts), ctx.step_in.variant_count):
        hits.append(GuardHit(concept_id=f"c{idx + 1}", guard="G1"))
    if len(concepts) > ctx.step_in.variant_count:
        hits.extend(GuardHit(concept_id=c.concept_id, guard="G1") for c in concepts[ctx.step_in.variant_count :])
    return hits


def _first_failure(c: Concept, idx: int, concepts: Sequence[Concept], ctx: GuardContext) -> GuardId | None:
    if not _g1(c, idx, ctx):
        return "G1"
    if c.status != "OK":
        return None if _g8(c, ctx) else "G8"
    checks: list[tuple[GuardId, bool]] = [
        ("G2", _g2(c, ctx)),
        ("G3", _g3(c, ctx)),
        ("G4", _g4(c, ctx)),
        ("G5", _g5(c, ctx)),
        ("G6", _g6(c, ctx)),
        ("G7", _g7(c, idx, concepts, ctx)),
    ]
    return next((g for g, ok in checks if not ok), None)
