"""FallbackPlanner (F-12; blueprint 6.6). Same logic as prompt rules 4-5, by arithmetic."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from agent_11_thumbnail_design.models import (
    Concept,
    HypothesisKind,
    PictureOptionView,
    StepIn,
    TemplateOffer,
    TextOption,
)
from agent_11_thumbnail_design.text_options import finance_text_hit
from agent_11_thumbnail_design.textutil import fold, folded_words

_SOURCE_RANK = {"BRIEF_TEXT": 0, "TITLE_SPAN": 1, "KEY_TERM": 2}
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)

RATIONALES: dict[HypothesisKind, str] = {
    "CONTROL": "The brief's own phrase and the best fitting picture repeat the promise.",
    "TEXT_ANGLE": "Only the words change, so the test shows which wording works.",
    "SUBJECT_CHOICE": "Only the picture option changes, so the test shows which picture works.",
    "LAYOUT_STYLE": "Only the layout changes, because no other single change is possible.",
}


@dataclass(frozen=True, slots=True)
class PlannerPolicy:
    finance: bool
    faces_allowed: bool
    fin_lexicon: Sequence[str] = ()


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(fold(text)))


def _texts_ok(texts: Sequence[TextOption], step: StepIn) -> bool:
    if not 1 <= len(texts) <= 2 or not any(t.key_term_ids for t in texts):
        return False
    must = [fold(m) for m in step.brief.must_not_promise if m.strip()]
    if any(m in fold(t.text) for t in texts for m in must):
        return False
    return not (len(texts) == 2 and set(folded_words(texts[0].text)) & set(folded_words(texts[1].text)))


def _viable(
    tpl: TemplateOffer, pic: PictureOptionView, texts: Sequence[TextOption], step: StepIn, pol: PlannerPolicy
) -> bool:
    if pic.kind not in tpl.supports_subject_kinds or tpl.text_lines_max < len(texts):
        return False
    if pol.finance and (
        not tpl.direction_neutral
        or not pic.direction_neutral
        or pic.has_face
        or any(finance_text_hit(t.text, pol.fin_lexicon) for t in texts)
    ):
        return False
    return _texts_ok(texts, step)


def _ordered_texts(step: StepIn) -> list[TextOption]:
    return sorted(step.text_options, key=lambda t: (_SOURCE_RANK[t.source], t.text_id))


def _ranked_pictures(step: StepIn) -> list[PictureOptionView]:
    idea = " ".join([step.brief.subject_idea, *[h.intent_text for h in step.subject_hints]])
    want = _tokens(idea)
    return sorted(
        step.subject_options, key=lambda o: (-len(_tokens(o.label) & want), o.option_id)
    )


def _concept(
    cid: str,
    tpl: TemplateOffer,
    pic: PictureOptionView,
    texts: Sequence[TextOption],
    kind: HypothesisKind,
    accent: str = "PRIMARY",
) -> Concept:
    return Concept(
        concept_id=cid,
        status="OK",
        reason_code=None,
        template_key=tpl.template_key,
        subject_option_id=pic.option_id,
        text_ids=tuple(t.text_id for t in texts),
        angle="TERM_CLARITY",
        hypothesis_kind=kind,
        emphasis_style="TERM_HIGHLIGHT" if any(t.key_term_ids for t in texts) else "PLAIN",
        accent_role=accent,  # type: ignore[arg-type]
        rationale=RATIONALES[kind],
    )


def _no_distinct(cid: str) -> Concept:
    return Concept(
        concept_id=cid,
        status="NO_SAFE_CONCEPT",
        reason_code="NO_DISTINCT_OPTION",
        template_key=None,
        subject_option_id=None,
        text_ids=(),
        hypothesis_kind=None,
        emphasis_style=None,
        rationale="No further honest change to the control exists.",
    )


def _no_text(cid: str, reason: str) -> Concept:
    return Concept(
        concept_id=cid,
        status="NO_SAFE_CONCEPT",
        reason_code=reason,  # type: ignore[arg-type]
        template_key=None,
        subject_option_id=None,
        text_ids=(),
        hypothesis_kind=None,
        emphasis_style=None,
        rationale="No eligible text option exists for this promise.",
    )


class FallbackPlanner:
    def __init__(self, policy: PlannerPolicy) -> None:
        self._pol = policy

    def plan(self, step: StepIn, keep: Sequence[Concept] = (), need: Sequence[str] | None = None) -> list[Concept]:
        """Concepts c1..cN: ``keep`` entries are repeated, ``need`` ids (default all) are planned."""
        kept = {c.concept_id: c for c in keep}
        wanted = set(need) if need is not None else {f"c{i + 1}" for i in range(step.variant_count)}
        prev = {p.concept_id: p for p in step.previous_concepts or ()}
        out: list[Concept] = []
        for i in range(step.variant_count):
            cid = f"c{i + 1}"
            if cid in kept and cid not in wanted:
                out.append(kept[cid])
                continue
            out.append(self._one(step, i, out, prev.get(cid)))
        return out

    def _one(self, step: StepIn, idx: int, made: Sequence[Concept], prev: object) -> Concept:
        cid = f"c{idx + 1}"
        texts = _ordered_texts(step)
        pics = _ranked_pictures(step)
        tpls = sorted(step.templates, key=lambda t: not t.is_default)
        avoid = None
        if prev is not None:
            avoid = (getattr(prev, "template_key", None), getattr(prev, "subject_option_id", None), tuple(getattr(prev, "text_ids", ())))
        if idx == 0:
            return self._control(step, cid, texts, pics, tpls, avoid)
        control = made[0]
        if control.status != "OK":
            return _no_distinct(cid)
        return self._variant(step, cid, idx, control, made, avoid)

    def _control(self, step, cid, texts, pics, tpls, avoid) -> Concept:  # type: ignore[no-untyped-def]
        if not texts:
            return _no_text(cid, "NO_ELIGIBLE_TEXT")
        default = next((t for t in tpls if t.is_default), tpls[0] if tpls else None)
        for t in texts:
            for p in pics:
                for tpl in ([default] if default else []) + [x for x in tpls if x is not default]:
                    if _viable(tpl, p, [t], step, self._pol) and (tpl.template_key, p.option_id, (t.text_id,)) != avoid:
                        return _concept(cid, tpl, p, [t], "CONTROL")
        return _no_text(cid, "NO_ELIGIBLE_TEXT")

    def _variant(self, step, cid, idx, control, made, avoid) -> Concept:  # type: ignore[no-untyped-def]
        tpl0 = next(t for t in step.templates if t.template_key == control.template_key)
        pic0 = next(o for o in step.subject_options if o.option_id == control.subject_option_id)
        texts0 = [t for t in step.text_options if t.text_id in control.text_ids]
        used = {c.choices() for c in made if c.status == "OK"}

        def free(tpl: TemplateOffer, pic: PictureOptionView, txt: Sequence[TextOption]) -> bool:
            key = (tpl.template_key, pic.option_id, tuple(t.text_id for t in txt))
            return key not in used and key != avoid and _viable(tpl, pic, txt, step, self._pol)

        def by_text() -> Concept | None:
            for t in sorted(step.text_options, key=lambda o: o.text_id):
                if t.text_id not in control.text_ids and free(tpl0, pic0, [t]):
                    return _concept(cid, tpl0, pic0, [t], "TEXT_ANGLE")
            return None

        def by_picture() -> Concept | None:
            for p in sorted(step.subject_options, key=lambda o: o.option_id):
                if p.option_id != pic0.option_id and free(tpl0, p, texts0):
                    return _concept(cid, tpl0, p, texts0, "SUBJECT_CHOICE")
            return None

        def by_layout() -> Concept | None:
            for tpl in step.templates:
                if tpl.template_key != tpl0.template_key and free(tpl, pic0, texts0):
                    return _concept(cid, tpl, pic0, texts0, "LAYOUT_STYLE", "SECONDARY")
            return None

        order = (by_text, by_picture) if idx == 1 else (by_picture, by_text)
        for fn in (order[0], by_layout):
            got = fn()
            if got:
                return got
        return _no_distinct(cid)
