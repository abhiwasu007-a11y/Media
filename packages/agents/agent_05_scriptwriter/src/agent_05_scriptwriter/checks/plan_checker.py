"""``PlanChecker`` (blueprint 10.2): the ``a05.plan.*`` checks and the option qualification."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from agent_05_scriptwriter.checks.context import Scanners
from agent_05_scriptwriter.checks.language import check_language
from agent_05_scriptwriter.checks.results import (
    CheckResult,
    failed,
    passed,
)
from agent_05_scriptwriter.checks.scanners import promise_outcome_terms
from agent_05_scriptwriter.contracts import (
    ConceptBrief,
    GlossaryTerm,
    PlanHook,
    PlanOutput,
    PlanStepInput,
)
from agent_05_scriptwriter.hooks import HookScore, Selection, select_hook
from agent_05_scriptwriter.settings import Agent05Settings
from agent_05_scriptwriter.text import normalise

BEATS = ("HOOK_PROOF", "HOOK_WHY", "HOOK_COVERS")
RULE_BY_CHECK = {"a05.plan.fin_prefilter": "FIN"}


@dataclass(frozen=True, slots=True)
class PlanReport:
    results: list[CheckResult]
    option_failures: dict[str, list[str]]
    selection: Selection | None
    qualified_ids: list[str] = field(default_factory=list)


def hook_text(hook: PlanHook) -> str:
    parts: list[str] = []
    for beat in hook.beats:
        parts.extend(s.text for s in beat.sentences)
    return " ".join(parts)


def hook_chars(hook: PlanHook) -> int:
    return sum(len(s.text) for beat in hook.beats for s in beat.sentences)


def proof_text(hook: PlanHook) -> str:
    return " ".join(s.text for s in hook.beats[0].sentences)


def glossary_terms(briefs: Iterable[ConceptBrief]) -> list[GlossaryTerm]:
    return [
        GlossaryTerm(concept_id=b.concept_id, term_local=b.term_local, term_en=b.term_en)
        for b in briefs
    ]


def contains_term(text: str, term: str) -> bool:
    return normalise(term) in normalise(text)


def repeats_history(
    sentences: Iterable[str], history: Iterable[str], similarity: float | None
) -> bool:
    past = [normalise(h) for h in history]
    for sentence in sentences:
        norm = normalise(sentence)
        for old in past:
            if norm == old:
                return True
            if similarity is not None and SequenceMatcher(None, norm, old).ratio() >= similarity:
                return True
    return False


def midpoint_flags(sections: list[tuple[int, bool]]) -> tuple[bool, bool]:
    """(first-half section flagged, midpoint section flagged) from ``(share, needs_interrupt)``."""
    start = 0
    first_half = False
    midpoint = False
    for share, needs in sections:
        end = start + share
        if start < 500 and needs:
            first_half = True
        if start <= 500 < end and needs:
            midpoint = True
        start = end
    return first_half, midpoint


class PlanChecker:
    def __init__(self, settings: Agent05Settings, scanners: Scanners) -> None:
        self._settings = settings
        self._scan = scanners

    def check(self, plan: PlanOutput, inp: PlanStepInput) -> PlanReport:
        results: list[CheckResult] = [passed("a05.plan.schema", "plan output valid")]
        if plan.refusal is not None:
            return PlanReport(results, {}, None)
        option_failures = self._option_failures(plan, inp)
        results.append(self._hooks(plan, inp, option_failures))
        scores = [
            HookScore(
                h.hook_id,
                h.rubric.viewer_relevance,
                h.rubric.curiosity_without_clickbait,
                not option_failures[h.hook_id],
            )
            for h in plan.hooks
        ]
        selection = select_hook(scores, plan.selected_hook_id, inp.min_hook_options)
        if selection.status == "REPAIR":
            results.append(
                failed(
                    "a05.plan.selection",
                    "fewer qualified hook options than the minimum",
                    details={"disqualified": {k: v for k, v in option_failures.items() if v}},
                )
            )
        else:
            results.append(passed("a05.plan.selection", "selection recomputed"))
        results.append(self._concepts(plan, inp))
        results.append(self._promise(plan, inp))
        results.extend(self._text_scans(plan, inp))
        results.append(self._method_gate(plan, inp))
        results.append(self._sections(plan, inp))
        return PlanReport(
            results,
            option_failures,
            selection,
            [s.hook_id for s in scores if s.qualified],
        )

    # ---- option level ----
    def _option_failures(self, plan: PlanOutput, inp: PlanStepInput) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        terms = glossary_terms(inp.concept_briefs)
        key_terms = plan.title_promise.promise_key_terms if plan.title_promise else []
        s = self._settings
        for hook in plan.hooks:
            bad: set[str] = set()
            beats = [b.beat for b in hook.beats]
            if tuple(beats) != BEATS or hook.beats[0].concrete_example is None:
                bad.add("a05.plan.hooks")
            budget = inp.speech_budget
            chars = hook_chars(hook)
            if budget is not None and not (budget.hook_chars_min <= chars <= budget.hook_chars_max):
                bad.add("a05.plan.hooks")
            sentences = [x.text for b in hook.beats for x in b.sentences]
            if repeats_history(sentences, inp.hook_history, s.hook_history_similarity):
                bad.add("a05.plan.hooks")
            if any(
                self._scan.forbidden.brand_intro(x, lang)
                for x in (b_s.text for b_s in hook.beats[0].sentences)
                for lang in self._scan.languages(inp.language)
                if lang in self._scan.lexicons.languages
            ):
                bad.add("a05.plan.hooks")
            if not all(contains_term(proof_text(hook), t) for t in key_terms):
                bad.add("a05.plan.promise")
            text = hook_text(hook) + " " + " ".join(b.concrete_example or "" for b in hook.beats)
            if check_language(text, inp.language, inp.latin_allow_list, [], terms):
                bad.add("a05.plan.lang")
            if self._scan.fin_ids(text, inp.language):
                bad.add("a05.plan.fin_prefilter")
            if self._scan.tokens(text, inp.language):
                bad.add("a05.plan.forbidden_tokens")
            out[hook.hook_id] = sorted(bad)
        return out

    def _hooks(
        self, plan: PlanOutput, inp: PlanStepInput, option_failures: dict[str, list[str]]
    ) -> CheckResult:
        count_ok = inp.min_hook_options <= len(plan.hooks) <= inp.max_hook_options
        styles = [h.hook_style for h in plan.hooks]
        distinct = len(set(styles)) == len(styles)
        ids_unique = len({h.hook_id for h in plan.hooks}) == len(plan.hooks)
        structural = [k for k, v in option_failures.items() if "a05.plan.hooks" in v]
        if count_ok and distinct and ids_unique and not structural:
            return passed("a05.plan.hooks", f"{len(plan.hooks)} hook options")
        return failed(
            "a05.plan.hooks",
            "hook count, style distinctness, beats, budget, history or brand intro failed",
            details={
                "count_ok": count_ok,
                "distinct_styles": distinct,
                "unique_ids": ids_unique,
                "options": structural,
            },
        )

    # ---- plan level ----
    def _concepts(self, plan: PlanOutput, inp: PlanStepInput) -> CheckResult:
        briefs = {b.concept_id: b for b in inp.concept_briefs}
        planned = [c.concept_id for c in plan.concept_plan]
        omitted = {o.concept_id: o.reason for o in plan.omitted_concepts}
        problems: list[str] = []
        if len(set(planned)) != len(planned) or set(planned) & set(omitted):
            problems.append("concept in both lists or twice")
        if set(planned) | set(omitted) != set(briefs):
            problems.append("an input concept is in neither list")
        for cid, reason in omitted.items():
            brief = briefs.get(cid)
            if brief is not None and (reason == "NO_SOURCE") != (not brief.citation_refs):
                problems.append(f"NO_SOURCE mismatch for {cid}")
        section_ids = {s.section_id: s for s in plan.sections}
        for entry in plan.concept_plan:
            brief = briefs.get(entry.concept_id)
            if brief is None or not set(entry.citation_refs) <= set(brief.citation_refs):
                problems.append(f"citations of {entry.concept_id} not a subset of its brief")
            for sid in entry.taught_in_section_ids:
                sec = section_ids.get(sid)
                if sec is None or entry.concept_id not in sec.concept_ids:
                    problems.append(f"{entry.concept_id} not taught in {sid}")
        if problems:
            return failed("a05.plan.concepts", "; ".join(sorted(set(problems))))
        return passed("a05.plan.concepts", "concept lists consistent")

    def _promise(self, plan: PlanOutput, inp: PlanStepInput) -> CheckResult:
        promise = plan.title_promise
        assert promise is not None  # noqa: S101 - a non-refusal plan always has one
        problems: list[str] = []
        for term in promise.promise_key_terms:
            if not contains_term(promise.working_title_local, term):
                problems.append("key term missing in working title")
            if plan.description_draft is None or not contains_term(plan.description_draft, term):
                problems.append("key term missing in description")
        brief = plan.thumbnail_brief
        if brief is None or not brief.must_not_promise:
            problems.append("thumbnail brief incomplete")
        elif not any(
            contains_term(brief.text_idea_local + " " + brief.subject_idea, t)
            for t in promise.promise_key_terms
        ):
            problems.append("thumbnail brief repeats no key term")
        promise_texts = [
            promise.working_title_local,
            promise.promise_statement,
            plan.description_draft or "",
            brief.text_idea_local if brief else "",
        ]
        if any(
            promise_outcome_terms(self._scan.lexicons, t, lang)
            for t in promise_texts
            for lang in self._scan.languages(inp.language)
            if lang in self._scan.lexicons.languages
        ):
            problems.append("promise text contains an outcome or urgency word")
        if problems:
            return failed("a05.plan.promise", "; ".join(sorted(set(problems))))
        return passed("a05.plan.promise", "promise repeated")

    def _text_fields(self, plan: PlanOutput) -> list[tuple[str, str]]:
        """(text, kind) pairs: ``local`` fields are language-checked, ``en`` fields only scanned."""
        fields: list[tuple[str, str]] = []
        if plan.title_promise:
            fields += [
                (plan.title_promise.working_title_local, "local"),
                (plan.title_promise.promise_statement, "local"),
            ]
        for hook in plan.hooks:
            fields.append((hook_text(hook), "local"))
            fields += [(b.concrete_example, "local") for b in hook.beats if b.concrete_example]
        for sec in plan.sections:
            fields += [(sec.heading_local, "local"), (sec.heading_en, "en"), (sec.purpose, "en")]
        for entry in plan.concept_plan:
            fields += [(entry.own_words_angle, "en"), (entry.original_example_idea, "en")]
        if plan.description_draft:
            fields.append((plan.description_draft, "local"))
        if plan.thumbnail_brief:
            tb = plan.thumbnail_brief
            fields += [(tb.subject_idea, "en"), (tb.text_idea_local, "local")]
            fields += [(m, "en") for m in tb.must_not_promise]
        return fields

    def _text_scans(self, plan: PlanOutput, inp: PlanStepInput) -> list[CheckResult]:
        terms = glossary_terms(inp.concept_briefs)
        fin: set[str] = set()
        tokens: set[str] = set()
        language_problems = 0
        for text, kind in self._text_fields(plan):
            fin.update(self._scan.fin_ids(text, inp.language))
            tokens.update(self._scan.tokens(text, inp.language))
            if kind == "local" and check_language(
                text, inp.language, inp.latin_allow_list, [], terms
            ):
                language_problems += 1
        out: list[CheckResult] = []
        out.append(
            failed("a05.plan.lang", f"{language_problems} text(s) failed the language check")
            if language_problems
            else passed("a05.plan.lang", "language ok")
        )
        out.append(
            failed("a05.plan.fin_prefilter", "FIN pre-filter hit", rule_ids=tuple(sorted(fin)))
            if fin
            else passed("a05.plan.fin_prefilter", "no FIN pre-filter hit")
        )
        out.append(
            failed(
                "a05.plan.forbidden_tokens",
                "forbidden token found: " + ",".join(sorted(tokens)),
            )
            if tokens
            else passed("a05.plan.forbidden_tokens", "no forbidden token")
        )
        return out

    def _method_gate(self, plan: PlanOutput, inp: PlanStepInput) -> CheckResult:
        briefs = {b.concept_id: b for b in inp.concept_briefs}
        kinds = {s.section_id: s.section_kind for s in plan.sections}
        omitted = {o.concept_id: o.reason for o in plan.omitted_concepts}
        problems: list[str] = []
        for entry in plan.concept_plan:
            brief = briefs.get(entry.concept_id)
            if brief is None or not brief.method_content:
                continue
            if inp.video_kind != "METHOD_TOPIC" or brief.release_status != "RELEASED":
                problems.append(f"{entry.concept_id} method concept planned without release")
            if any(
                kinds.get(sid) != "CASE_STUDY_HISTORICAL" for sid in entry.taught_in_section_ids
            ):
                problems.append(f"{entry.concept_id} method concept outside a case study")
        for cid, brief in briefs.items():
            if not brief.method_content or cid not in omitted:
                continue
            if omitted[cid] == "NO_SOURCE":
                continue
            expected = (
                "METHOD_NOT_RELEASED" if brief.release_status != "RELEASED" else "METHOD_MIXING"
            )
            if inp.video_kind == "GENERAL" and brief.release_status == "RELEASED":
                expected = "METHOD_MIXING"
            if omitted[cid] not in (expected, "DURATION_LIMIT", "OUT_OF_SCOPE"):
                problems.append(f"{cid} omitted with a wrong method reason")
        if problems:
            return failed(
                "a05.plan.method_gate", "; ".join(sorted(set(problems))), rule_ids=("FIN-R12",)
            )
        return passed("a05.plan.method_gate", "method gate ok")

    def _sections(self, plan: PlanOutput, inp: PlanStepInput) -> CheckResult:
        sections = plan.sections
        problems: list[str] = []
        if len(sections) > inp.max_sections:
            problems.append("too many sections")
        if sum(s.share_permille for s in sections) != 1000:
            problems.append("share_permille does not sum to 1000")
        ids = [s.section_id for s in sections]
        if len(set(ids)) != len(ids):
            problems.append("duplicate section ids")
        pointers = [i for i, s in enumerate(sections) if s.section_kind == "COURSE_POINTER"]
        teaching = [s for s in sections if s.section_kind != "COURSE_POINTER"]
        if not teaching or teaching[-1].section_kind != "RECAP":
            problems.append("RECAP is not the last teaching section")
        if inp.course_chapter_pointer is None and pointers:
            problems.append("COURSE_POINTER without a pointer")
        if inp.course_chapter_pointer is not None and (
            len(pointers) != 1 or pointers[0] != len(sections) - 1
        ):
            problems.append("exactly one COURSE_POINTER must follow the recap")
        known = {b.concept_id for b in inp.concept_briefs}
        if any(c not in known for s in sections for c in s.concept_ids):
            problems.append("section lists an unknown concept")
        first_half, midpoint = midpoint_flags(
            [(s.share_permille, s.needs_interrupt) for s in sections]
        )
        if not (first_half and midpoint):
            problems.append("needs_interrupt missing in the first half or at the 50 % point")
        if problems:
            return failed("a05.plan.sections", "; ".join(sorted(set(problems))))
        return passed("a05.plan.sections", f"{len(sections)} sections")


__all__ = ["PlanChecker", "PlanReport"]
