"""``CutChecker`` (blueprint 10.4): the ``a05.sh.*`` checks of a Shorts cut."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from agent_05_scriptwriter.checks.context import Scanners
from agent_05_scriptwriter.checks.language import check_language
from agent_05_scriptwriter.checks.plan_checker import contains_term, repeats_history
from agent_05_scriptwriter.checks.results import (
    CheckResult,
    failed,
    passed,
    skipped,
)
from agent_05_scriptwriter.contracts import CutHook, CutOutput, CutStepInput, GlossaryTerm
from agent_05_scriptwriter.hooks import HookScore, Selection, select_hook
from agent_05_scriptwriter.settings import Agent05Settings
from agent_05_scriptwriter.text import normalise, speech_chars

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9'\-]*|\d[\d,.]*")


@dataclass(frozen=True, slots=True)
class CutReport:
    results: list[CheckResult]
    option_failures: dict[str, list[str]]
    selection: Selection | None
    estimated_ms: int | None = None
    qualified_ids: list[str] = field(default_factory=list)


def hook_sentences(hook: CutHook) -> list[str]:
    return [s.text for s in hook.sentences]


def parent_segments(inp: CutStepInput) -> dict[str, str]:
    return {seg.segment_id: seg.text for sec in inp.parent.sections for seg in sec.segments}


def _tokens(text: str) -> set[str]:
    return {t.casefold().rstrip(".,") for t in _TOKEN.findall(text)}


class CutChecker:
    def __init__(self, settings: Agent05Settings, scanners: Scanners) -> None:
        self._settings = settings
        self._scan = scanners

    def check(
        self,
        out: CutOutput,
        inp: CutStepInput,
        *,
        parent_citations: Mapping[str, set[str]] | None = None,
        shorts_limit_ms: int | None = None,
    ) -> CutReport:
        results: list[CheckResult] = [passed("a05.sh.schema", "cut output valid")]
        if out.refusal is not None:
            return CutReport(results, {}, None)
        segments = parent_segments(inp)
        removed = set(inp.parent.removed_segment_ids)
        usable = {k: v for k, v in segments.items() if k not in removed}
        terms = [GlossaryTerm(**t.model_dump()) for t in inp.glossary_terms]
        option_failures = self._option_failures(out, inp, usable, terms)
        results.append(self._provenance(out, inp, segments, usable, parent_citations))
        results.append(self._hooks(out, inp, option_failures))
        scores = [
            HookScore(
                h.hook_id,
                h.rubric.viewer_relevance,
                h.rubric.curiosity_without_clickbait,
                not option_failures[h.hook_id],
            )
            for h in out.hooks
        ]
        selection = select_hook(scores, out.selected_hook_id, inp.min_hook_options)
        duration, estimate = self._duration(out, inp, shorts_limit_ms)
        results.append(duration)
        results.append(self._lang(out, inp, terms))
        results.extend(self._scans(out, inp))
        results.append(self._flags(out, inp, usable, removed))
        if inp.revision_feedback is not None:
            results.append(self._revision(out, inp))
        return CutReport(
            results,
            option_failures,
            selection,
            estimate,
            [s.hook_id for s in scores if s.qualified],
        )

    def _option_failures(
        self,
        out: CutOutput,
        inp: CutStepInput,
        usable: Mapping[str, str],
        terms: Sequence[GlossaryTerm],
    ) -> dict[str, list[str]]:
        key_terms = out.title_promise.promise_key_terms if out.title_promise else []
        parent_terms = inp.parent.promise.promise_key_terms
        languages = [
            lang
            for lang in self._scan.languages(inp.language)
            if lang in self._scan.lexicons.languages
        ]
        result: dict[str, list[str]] = {}
        for hook in out.hooks:
            bad: set[str] = set()
            text = " ".join(hook_sentences(hook))
            budget = inp.speech_budget
            if budget is not None and len(text) > budget.hook_chars_max:
                bad.add("a05.sh.hooks")
            if repeats_history(
                hook_sentences(hook), inp.hook_history, self._settings.hook_history_similarity
            ):
                bad.add("a05.sh.hooks")
            if any(self._scan.forbidden.brand_intro(text, lang) for lang in languages):
                bad.add("a05.sh.hooks")
            if not set(hook.parent_segment_ids) <= set(usable):
                bad.add("a05.sh.provenance")
            if not all(contains_term(text, t) for t in key_terms):
                bad.add("a05.sh.hooks")
            if not all(any(normalise(k) == normalise(p) for p in parent_terms) for k in key_terms):
                bad.add("a05.sh.hooks")
            if check_language(text, inp.language, inp.latin_allow_list, [], terms):
                bad.add("a05.sh.lang")
            if self._scan.fin_ids(text, inp.language):
                bad.add("a05.sh.fin_prefilter")
            if self._scan.tokens(text, inp.language):
                bad.add("a05.sh.forbidden_tokens")
            result[hook.hook_id] = sorted(bad)
        return result

    def _provenance(
        self,
        out: CutOutput,
        inp: CutStepInput,
        segments: Mapping[str, str],
        usable: Mapping[str, str],
        parent_citations: Mapping[str, set[str]] | None,
    ) -> CheckResult:
        problems: list[str] = []
        parent_charts = {
            seg.chart_ref
            for sec in inp.parent.sections
            for seg in sec.segments
            if seg.chart_ref is not None
        }
        parent_concepts = {
            c for sec in inp.parent.sections for seg in sec.segments for c in seg.concept_refs
        }
        parent_tokens = _tokens(" ".join(segments.values()))
        parent_tokens |= {t for g in inp.glossary_terms for t in _tokens(g.term_en)}
        parent_tokens |= {a.casefold() for a in inp.latin_allow_list}
        for scene in out.scenes:
            if scene.beat != "FULL_VIDEO_POINTER":
                if not scene.parent_segment_ids or not set(scene.parent_segment_ids) <= set(usable):
                    problems.append("scene not drawn from usable parent segments")
                scene_tokens = _tokens(" ".join(s.text for s in scene.sentences))
                if not scene_tokens <= parent_tokens:
                    problems.append("scene adds a number or term the parent lacks")
            if scene.chart_ref is not None and scene.chart_ref not in parent_charts:
                problems.append("chart not in the parent")
            for ref in scene.concept_refs:
                if ref.concept_id not in parent_concepts:
                    problems.append("concept not in the parent")
                elif parent_citations is not None and not set(
                    ref.citation_refs
                ) <= parent_citations.get(ref.concept_id, set()):
                    problems.append("citation not in the parent's concept references")
        if problems:
            return failed("a05.sh.provenance", "; ".join(sorted(set(problems))))
        return passed("a05.sh.provenance", "every scene traces to the parent")

    def _hooks(
        self, out: CutOutput, inp: CutStepInput, option_failures: Mapping[str, list[str]]
    ) -> CheckResult:
        count_ok = inp.min_hook_options <= len(out.hooks) <= inp.max_hook_options
        distinct = len({h.hook_style for h in out.hooks}) == len(out.hooks)
        structural = [k for k, v in option_failures.items() if "a05.sh.hooks" in v]
        qualified = sum(1 for v in option_failures.values() if not v)
        if count_ok and distinct and qualified >= inp.min_hook_options:
            return passed("a05.sh.hooks", f"{len(out.hooks)} hook options, {qualified} qualified")
        return failed(
            "a05.sh.hooks",
            "hook count, style distinctness, budget, history or qualification failed",
            details={"options": structural, "qualified": qualified},
        )

    def _duration(
        self, out: CutOutput, inp: CutStepInput, shorts_limit_ms: int | None
    ) -> tuple[CheckResult, int | None]:
        rate = self._settings.rate_for(inp.language)
        if rate is None:
            return skipped("a05.sh.duration", "no speech rate measured yet"), None
        selected = next((h for h in out.hooks if h.hook_id == out.selected_hook_id), None)
        chars = sum(speech_chars(s.text) for s in (selected.sentences if selected else []))
        pause = 0
        for scene in out.scenes:
            chars += sum(speech_chars(s.text) for s in scene.sentences)
            pause += scene.deliberate_pause_ms
        estimate = round(chars / rate * 1000) + pause
        limit = min(x for x in (inp.short_target_duration_ms, shorts_limit_ms) if x is not None)
        if estimate > limit:
            return failed("a05.sh.duration", "estimated duration exceeds the limit"), estimate
        return passed("a05.sh.duration", "duration within limits"), estimate

    def _lang(
        self, out: CutOutput, inp: CutStepInput, terms: Sequence[GlossaryTerm]
    ) -> CheckResult:
        selected = next((h for h in out.hooks if h.hook_id == out.selected_hook_id), None)
        texts = [" ".join(hook_sentences(selected))] if selected else []
        texts += [" ".join(s.text for s in sc.sentences) for sc in out.scenes]
        introduced: list[str] = []
        bad = 0
        for text in texts:
            if check_language(text, inp.language, inp.latin_allow_list, introduced, terms):
                bad += 1
            introduced += [t.concept_id for t in terms if t.term_local in text]
        if bad:
            return failed("a05.sh.lang", f"{bad} text(s) failed the language check")
        return passed("a05.sh.lang", "language ok")

    def _scans(self, out: CutOutput, inp: CutStepInput) -> list[CheckResult]:
        texts = [" ".join(hook_sentences(h)) for h in out.hooks]
        for scene in out.scenes:
            texts.append(" ".join(s.text for s in scene.sentences))
            texts += scene.on_screen_text
            texts.append(scene.visual_intent.description)
        fin: set[str] = set()
        tokens: set[str] = set()
        for text in texts:
            fin.update(self._scan.fin_ids(text, inp.language))
            tokens.update(self._scan.tokens(text, inp.language))
        return [
            failed("a05.sh.fin_prefilter", "FIN pre-filter hit", rule_ids=tuple(sorted(fin)))
            if fin
            else passed("a05.sh.fin_prefilter", "no FIN pre-filter hit"),
            failed("a05.sh.forbidden_tokens", "forbidden token: " + ",".join(sorted(tokens)))
            if tokens
            else passed("a05.sh.forbidden_tokens", "no forbidden token"),
        ]

    def _flags(
        self,
        out: CutOutput,
        inp: CutStepInput,
        usable: Mapping[str, str],
        removed: set[str],
    ) -> CheckResult:
        flags = {
            seg.segment_id: (seg.method_label, seg.hypothetical_example)
            for sec in inp.parent.sections
            for seg in sec.segments
        }
        problems: list[str] = []
        used: set[str] = set()
        for hook in out.hooks:
            if hook.hook_id == out.selected_hook_id:
                used |= set(hook.parent_segment_ids)
        for scene in out.scenes:
            used |= set(scene.parent_segment_ids)
            method = any(flags.get(p, (False, False))[0] for p in scene.parent_segment_ids)
            hypo = any(flags.get(p, (False, False))[1] for p in scene.parent_segment_ids)
            if method and not scene.method_label:
                problems.append("method_label not carried over")
            if hypo and not scene.hypothetical_example:
                problems.append("hypothetical_example not carried over")
        dropped = {d.parent_segment_id for d in out.dropped_parent_content}
        if used & removed:
            problems.append("a removed segment was used")
        if dropped & used:
            problems.append("a segment is both used and dropped")
        if set(usable) - used - dropped:
            problems.append("a parent segment is neither used nor dropped")
        if problems:
            return failed("a05.sh.flags", "; ".join(sorted(set(problems))))
        return passed("a05.sh.flags", "flags carried over and every parent segment accounted for")

    def _revision(self, out: CutOutput, inp: CutStepInput) -> CheckResult:
        previous = inp.previous_cut
        feedback = inp.revision_feedback or []
        if previous is None:
            return failed("a05.sh.revision", "revision without a previous cut")
        texts = {s.segment_id: s.text for s in previous.hook.sentences}
        for scene in previous.scenes:
            texts.update({s.segment_id: s.text for s in scene.sentences})
        new_sentences = {normalise(s.text) for sc in out.scenes for s in sc.sentences} | {
            normalise(s) for h in out.hooks for s in hook_sentences(h)
        }
        for item in feedback:
            if item.segment_ref is None:
                continue
            if item.segment_ref not in texts:
                return failed("a05.sh.revision", "segment_ref is not in the previous cut")
            if normalise(texts[item.segment_ref]) in new_sentences:
                return failed("a05.sh.revision", "a flagged sentence recurs verbatim")
        return passed("a05.sh.revision", "feedback addressed")
