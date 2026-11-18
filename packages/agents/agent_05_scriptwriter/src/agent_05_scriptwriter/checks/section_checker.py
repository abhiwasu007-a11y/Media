"""``SectionChecker`` (blueprint 10.3): the ``a05.sec.*`` checks of one section's scenes."""

import re
from collections.abc import Mapping, Sequence

from agent_05_scriptwriter.checks.cadence import check_cadence
from agent_05_scriptwriter.checks.context import Scanners
from agent_05_scriptwriter.checks.language import check_language
from agent_05_scriptwriter.checks.near_copy import check_sentences
from agent_05_scriptwriter.checks.plan_checker import glossary_terms
from agent_05_scriptwriter.checks.results import (
    CheckResult,
    failed,
    passed,
    warned,
)
from agent_05_scriptwriter.contracts import ConceptBrief, Scene, SectionOutput, SectionStepInput
from agent_05_scriptwriter.settings import Agent05Settings
from agent_05_scriptwriter.text import speech_chars

_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9'\-]*")
_NUMBER = re.compile(r"\d[\d,.]*")


def scene_text(scene: Scene) -> str:
    return " ".join(s.text for s in scene.sentences)


def pronunciation_tokens(text: str, language: str) -> list[str]:
    """Tokens the voice stage needs a dictionary entry for (blueprint 10.3 ``a05.sec.lang``).

    In ``mr-IN`` / ``hi-IN`` every Latin word (including bracketed English terms), acronym and
    number; in ``en-IN`` only acronyms and numbers (plain English words need no entry).
    """
    latin = _LATIN.findall(text)
    if language != "en-IN":
        return latin + _NUMBER.findall(text)
    return [t for t in latin if len(t) > 1 and t.isupper()] + _NUMBER.findall(text)


class SectionChecker:
    def __init__(self, settings: Agent05Settings, scanners: Scanners) -> None:
        self._settings = settings
        self._scan = scanners

    def check(
        self,
        out: SectionOutput,
        inp: SectionStepInput,
        *,
        cited_texts: Mapping[str, str] | None = None,
        used_chart_ids: Sequence[str] = (),
    ) -> list[CheckResult]:
        plan = inp.section_plan
        briefs = {b.concept_id: b for b in inp.concept_briefs}
        results = [self._pre(inp, briefs)]
        results.append(passed("a05.sec.schema", "section output valid"))
        if out.refusal is not None:
            return results
        results.append(self._concepts(out, inp, briefs))
        results.append(self._lang(out, inp, briefs))
        results.extend(self._scans(out, inp))
        results.append(self._charts(out, inp, briefs, used_chart_ids))
        results.append(self._cadence(out, inp))
        results.append(self._tags(out))
        results.append(self._method_label(out, inp, briefs))
        results.append(self._budget(out, inp))
        results.append(self._near_copy(out, briefs, cited_texts or {}))
        _ = plan
        return results

    # ---- individual checks ----
    def _pre(self, inp: SectionStepInput, briefs: Mapping[str, ConceptBrief]) -> CheckResult:
        if not set(inp.section_plan.concept_ids) <= set(briefs):
            return failed("a05.sec.pre", "section plan lists a concept without a brief")
        return passed("a05.sec.pre", "inputs consistent")

    def _concepts(
        self, out: SectionOutput, inp: SectionStepInput, briefs: Mapping[str, ConceptBrief]
    ) -> CheckResult:
        plan = inp.section_plan
        allowed = set(plan.concept_ids)
        problems: list[str] = []
        for scene in out.scenes:
            for ref in scene.concept_refs:
                brief = briefs.get(ref.concept_id)
                if ref.concept_id not in allowed or brief is None:
                    problems.append("concept outside the section plan")
                elif not ref.citation_refs or not set(ref.citation_refs) <= set(
                    brief.citation_refs
                ):
                    problems.append("citation not in the concept's brief")
            if allowed and scene.explanatory and scene.beat == "BODY" and not scene.concept_refs:
                problems.append("explanatory scene without concept refs")
            if scene.purpose_concept_id is not None and scene.purpose_concept_id not in allowed:
                problems.append("purpose concept outside the section plan")
        if plan.section_kind == "CASE_STUDY_HISTORICAL":
            if any(s.purpose_concept_id is None for s in out.scenes):
                problems.append("case-study scene without purpose_concept_id")
            last = out.scenes[-1]
            if last.purpose_concept_id is None or last.purpose_concept_id not in {
                r.concept_id for r in last.concept_refs
            }:
                problems.append("last case-study scene does not cite the lesson concept")
        if problems:
            return failed("a05.sec.concepts", "; ".join(sorted(set(problems))))
        return passed("a05.sec.concepts", "concepts and citations ok")

    def _lang(
        self, out: SectionOutput, inp: SectionStepInput, briefs: Mapping[str, ConceptBrief]
    ) -> CheckResult:
        terms = glossary_terms(briefs.values())
        introduced = list(inp.running_summary.terms_introduced)
        allow = {t.casefold() for entry in inp.latin_allow_list for t in _LATIN.findall(entry)}
        allow |= {entry.casefold() for entry in inp.latin_allow_list}
        problems = 0
        for scene in out.scenes:
            text = scene_text(scene)
            if check_language(text, inp.language, inp.latin_allow_list, introduced, terms):
                problems += 1
            candidates = {
                w.casefold() for c in scene.pronunciation_candidates for w in c.split()
            } | {c.casefold() for c in scene.pronunciation_candidates}
            for token in pronunciation_tokens(text, inp.language):
                if token.casefold() not in candidates and token.casefold() not in allow:
                    problems += 1
                    break
            for term in terms:
                if term.term_local in text and term.concept_id not in introduced:
                    introduced.append(term.concept_id)
        if problems:
            return failed("a05.sec.lang", f"{problems} scene(s) failed the language check")
        return passed("a05.sec.lang", "language ok")

    def _scan_texts(self, out: SectionOutput) -> list[tuple[str, str]]:
        texts: list[tuple[str, str]] = []
        for scene in out.scenes:
            narration = scene_text(scene)
            texts.append((narration, "narration"))
            texts += [(t, "screen") for t in scene.on_screen_text]
            texts.append((scene.visual_intent.description, "visual"))
        return texts

    def _scans(self, out: SectionOutput, inp: SectionStepInput) -> list[CheckResult]:
        fin: set[str] = set()
        tokens: set[str] = set()
        for text, _kind in self._scan_texts(out):
            fin.update(self._scan.fin_ids(text, inp.language))
            tokens.update(self._scan.tokens(text, inp.language))
        for scene in out.scenes:
            fin.update(
                self._scan.forward_ids(
                    scene_text(scene), inp.language, inp.section_plan.section_kind
                )
            )
        return [
            failed("a05.sec.fin_prefilter", "FIN pre-filter hit", rule_ids=tuple(sorted(fin)))
            if fin
            else passed("a05.sec.fin_prefilter", "no FIN pre-filter hit"),
            failed("a05.sec.forbidden_tokens", "forbidden token: " + ",".join(sorted(tokens)))
            if tokens
            else passed("a05.sec.forbidden_tokens", "no forbidden token"),
        ]

    def _charts(
        self,
        out: SectionOutput,
        inp: SectionStepInput,
        briefs: Mapping[str, ConceptBrief],
        used: Sequence[str],
    ) -> CheckResult:
        pool = set(inp.chart_ids_available)
        seen: set[str] = set(used)
        problems: list[str] = []
        instruments: list[str] = []
        charts = [s.chart_request for s in out.scenes if s.chart_request is not None]
        for chart in charts:
            if chart.chart_id not in pool or chart.chart_id in seen:
                problems.append("chart id outside the pool or used twice")
            seen.add(chart.chart_id)
            if chart.chart_kind == "REAL_HISTORICAL":
                if not chart.instrument:
                    problems.append("real chart without an instrument")
                else:
                    instruments.append(chart.instrument)
            elif chart.instrument is not None:
                problems.append("schematic chart names an instrument")
            if chart.pattern_concept_id not in briefs:
                problems.append("chart pattern concept unknown")
        if inp.section_plan.section_kind == "CASE_STUDY_HISTORICAL" and not charts:
            problems.append("case-study section without a chart request")
        for text, _kind in self._scan_texts(out):
            low = text.casefold()
            if any(i.casefold() in low for i in instruments) and re.search(r"\d", text):
                problems.append("date, price or level next to a real instrument")
        if problems:
            return failed("a05.sec.chart_requests", "; ".join(sorted(set(problems))))
        return passed("a05.sec.chart_requests", "chart requests ok")

    def _cadence(self, out: SectionOutput, inp: SectionStepInput) -> CheckResult:
        rate = inp.scene_budget.speech_rate_cps
        gap = inp.scene_budget.max_change_gap_ms
        bad = 0
        for scene in out.scenes:
            result = check_cadence(
                explanatory=scene.explanatory,
                chars=speech_chars(scene_text(scene)),
                sentences=len(scene.sentences),
                pause_ms=scene.deliberate_pause_ms,
                rate_cps=rate,
                max_gap_ms=gap,
                change_beats=scene.visual_intent.change_beats,
                hold_reason=None if scene.explanatory else scene.visual_intent.description,
                needs_interrupt=False,
                scene_interrupts=[],
            )
            if result.verdict == "FAIL":
                bad += 1
        interrupt = inp.section_plan.needs_interrupt and not any(
            s.interrupt is not None for s in out.scenes
        )
        if bad or interrupt:
            blocking = rate is not None or interrupt
            msg = f"{bad} scene(s) below the change-beat minimum" + (
                "; no interrupt in a section that needs one" if interrupt else ""
            )
            return (
                failed("a05.sec.cadence", msg, blocking=blocking)
                if blocking
                else warned("a05.sec.cadence", msg)
            )
        return passed("a05.sec.cadence", "cadence ok")

    def _tags(self, out: SectionOutput) -> CheckResult:
        sentences = [s for scene in out.scenes for s in scene.sentences]
        if len(sentences) > 1 and len({(s.pace, s.emotion) for s in sentences}) == 1:
            return warned("a05.sec.tags", "one pace and emotion throughout the section")
        return passed("a05.sec.tags", "tags present")

    def _method_label(
        self, out: SectionOutput, inp: SectionStepInput, briefs: Mapping[str, ConceptBrief]
    ) -> CheckResult:
        problems: list[str] = []
        for scene in out.scenes:
            uses_method = any(
                briefs[r.concept_id].method_content
                for r in scene.concept_refs
                if r.concept_id in briefs
            )
            allowed = (
                inp.video_kind == "METHOD_TOPIC"
                and inp.section_plan.section_kind == "CASE_STUDY_HISTORICAL"
                and scene.chart_request is not None
                and all(
                    briefs[r.concept_id].release_status == "RELEASED"
                    for r in scene.concept_refs
                    if r.concept_id in briefs and briefs[r.concept_id].method_content
                )
            )
            if uses_method and not allowed:
                problems.append("method concept in a scene that may not use it")
            if uses_method != scene.method_label:
                problems.append("method_label does not match the concepts used")
        if problems:
            return failed(
                "a05.sec.method_label", "; ".join(sorted(set(problems))), rule_ids=("FIN-R12",)
            )
        return passed("a05.sec.method_label", "method labels ok")

    def _budget(self, out: SectionOutput, inp: SectionStepInput) -> CheckResult:
        budget = inp.scene_budget
        if len(out.scenes) > budget.max_scenes:
            return failed("a05.sec.budget_chars", "more scenes than the budget allows")
        chars = sum(speech_chars(scene_text(s)) for s in out.scenes)
        if (
            budget.chars_min is not None
            and budget.chars_max is not None
            and not budget.chars_min <= chars <= budget.chars_max
        ):
            return warned("a05.sec.budget_chars", "narration outside the size budget", chars)
        return passed("a05.sec.budget_chars", "size within budget")

    def _near_copy(
        self,
        out: SectionOutput,
        briefs: Mapping[str, ConceptBrief],
        cited_texts: Mapping[str, str],
    ) -> CheckResult:
        violations = 0
        for scene in out.scenes:
            refs = {c for r in scene.concept_refs for c in r.citation_refs}
            texts = [cited_texts[c] for c in sorted(refs) if c in cited_texts]
            texts += [
                briefs[r.concept_id].summary for r in scene.concept_refs if r.concept_id in briefs
            ]
            violations += len(
                check_sentences([s.text for s in scene.sentences], texts, self._settings.near_copy)
            )
        if violations:
            return failed("a05.sec.near_copy", f"{violations} sentence(s) too close to a source")
        return passed("a05.sec.near_copy", "no near copy")
