"""QualityChecks (F-17; blueprint 20): the ``a11.q.*`` results, measured against thresholds."""

from collections.abc import Sequence
from dataclasses import dataclass, field

from agent_11_thumbnail_design.composer import RenderResult
from agent_11_thumbnail_design.config import Agent11Settings
from agent_11_thumbnail_design.measure import distinctness
from agent_11_thumbnail_design.models import Concept, PictureOption, TextOption
from agent_11_thumbnail_design.text_options import finance_text_hit
from agent_11_thumbnail_design.textutil import contains_sequence, fold, folded_words, words
from amw_core.contracts.task_output import ValidationResult
from amw_core.enums import CheckKind, CheckVerdict, ComplianceVerdict

_ALLOWED_SOURCES = frozenset({"OWNER_MADE", "CODE_GENERATED", "CLIENT_SUPPLIED"})

ALL_CHECK_IDS = (
    "a11.q.schema",
    "a11.q.count",
    "a11.q.promise_terms",
    "a11.q.text_provenance",
    "a11.q.must_not_promise",
    "a11.q.finance_text",
    "a11.q.finance_imagery",
    "a11.q.chart_still",
    "a11.q.no_person",
    "a11.q.no_ai_still",
    "a11.q.licence_rows",
    "a11.q.size",
    "a11.q.dimensions",
    "a11.q.legibility",
    "a11.q.text_fit",
    "a11.q.preview_legibility",
    "a11.q.word_count",
    "a11.q.distinct",
    "a11.q.single_variable",
    "a11.q.language_glyphs",
    "a11.q.cost",
    "a11.q.rationale_clean",
    "a11.q.llm_fallback",
)


@dataclass(frozen=True, slots=True)
class LicenceFact:
    """One asset used by the thumbnail (picture, glyph set, template or font) and its ledger row."""

    asset_id: str
    usage_kind: str
    has_ledger_row: bool
    ledger_has_interval: bool
    licence_state: str
    covers_monetized: bool
    third_party_permission: str | None
    source_type: str
    expired: bool


@dataclass(frozen=True, slots=True)
class PictureFact:
    asset_kind: str | None  # IMAGE / CHART for an owner asset, None for glyph / none
    depicts_real_person: bool
    release_ref: bool
    data_age_vs_lag: str | None
    label_free: bool
    direction_balanced: bool
    data_end_date_present: bool
    is_synthetic_presenter: bool = False


@dataclass(frozen=True, slots=True)
class VariantFacts:
    variant_id: str
    concept: Concept
    template_key: str
    template_direction_neutral: bool
    picture: PictureOption
    picture_fact: PictureFact
    texts: tuple[TextOption, ...]
    render: RenderResult
    file_size_bytes: int
    text_local: str
    rationale_ok: bool
    rationale_fixed: bool = False


@dataclass(frozen=True, slots=True)
class CheckContext:
    settings: Agent11Settings
    verdict: ComplianceVerdict
    finance: bool
    requested: int
    variants: tuple[VariantFacts, ...]
    promise_key_terms: tuple[str, ...]
    must_not_promise: tuple[str, ...]
    banned_words: tuple[str, ...]
    fin_lexicon: Sequence[str]
    faces_allowed: bool
    licence_facts: tuple[LicenceFact, ...]
    schema_ok: bool
    llm_calls: int
    cost_micros: int
    reserved_micros: int
    max_cost_micros: int
    cost_entry_ids: tuple[str, ...]
    image_provider_calls: int = 0
    llm_fallback_code: str | None = None
    safe_rect: tuple[int, int, int, int] = (0, 0, 0, 0)
    reserved_corner_rect: tuple[int, int, int, int] = (0, 0, 0, 0)
    skipped_ids: frozenset[str] = field(default_factory=frozenset)


def _r(
    check: str,
    verdict: CheckVerdict,
    blocking: bool,
    message: str,
    *,
    rule: str | None = None,
    measured: bool | int | float | str | None = None,
    threshold: bool | int | float | str | None = None,
    unit: str | None = None,
) -> ValidationResult:
    return ValidationResult(
        check_id=check,
        kind=CheckKind.DETERMINISTIC,
        verdict=verdict,
        blocking=blocking and verdict not in (CheckVerdict.WARN, CheckVerdict.SKIPPED),
        rule_id=rule,
        measured=measured,
        threshold=threshold,
        unit=unit,
        message=message,
        gate=False,
    )


def _ok(check: str, passed: bool, message: str, **kw: object) -> ValidationResult:
    return _r(check, CheckVerdict.PASS if passed else CheckVerdict.FAIL, True, message, **kw)  # type: ignore[arg-type]


def _skip(check: str, why: str) -> ValidationResult:
    return _r(check, CheckVerdict.SKIPPED, False, why)


def _inside(inner: tuple[int, int, int, int], outer: tuple[int, int, int, int]) -> bool:
    return (
        inner[0] >= outer[0]
        and inner[1] >= outer[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def _overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _legible(v: VariantFacts, s: Agent11Settings) -> bool:
    return all(r.contrast >= s.legibility_min_contrast_ratio for r in v.render.runs)


def _fits(
    v: VariantFacts,
    s: Agent11Settings,
    safe: tuple[int, int, int, int],
    corner: tuple[int, int, int, int],
) -> bool:
    return v.render.font_px >= s.text_min_font_px and all(
        _inside(r.bbox, safe) and not _overlap(r.bbox, corner) for r in v.render.runs
    )


def variant_failures(
    v: VariantFacts,
    s: Agent11Settings,
    safe: tuple[int, int, int, int],
    corner: tuple[int, int, int, int],
) -> list[str]:
    """The per-file blocking checks that the code repair can act on (FR-10)."""
    out = []
    if not _legible(v, s):
        out.append("a11.q.legibility")
    if not _fits(v, s, safe, corner):
        out.append("a11.q.text_fit")
    if v.file_size_bytes > s.output_max_bytes:
        out.append("a11.q.size")
    if len(words(v.text_local)) > s.text_max_words or len(v.text_local) > s.text_max_chars:
        out.append("a11.q.word_count")
    if v.render.missing_glyphs:
        out.append("a11.q.language_glyphs")
    return out


def run_checks(c: CheckContext) -> list[ValidationResult]:
    """All 23 results in the order of blueprint 20. Empty-set rule: checks 2..20 are SKIPPED."""
    s = c.settings
    empty = c.verdict is not ComplianceVerdict.ALLOWED or not c.variants
    out: list[ValidationResult] = [
        _ok("a11.q.schema", c.schema_ok, "output validates against its schema")
    ]

    def per_variant(check: str, pred: object, msg: str, **kw: object) -> ValidationResult:
        if empty:
            return _skip(check, "no variant to measure (empty set)")
        bad = [v.variant_id for v in c.variants if not pred(v)]  # type: ignore[operator]
        return _ok(check, not bad, msg if not bad else f"{msg}: failed for {','.join(bad)}", **kw)

    def _count() -> ValidationResult:
        if empty:
            return _skip("a11.q.count", "no variant to measure (empty set)")
        n, cap = len(c.variants), min(c.requested, s.max_variants)
        ctrl = c.variants[0].concept.hypothesis_kind == "CONTROL"
        return _ok(
            "a11.q.count",
            1 <= n <= cap and ctrl,
            "variant count and control first",
            measured=n,
            threshold=cap,
        )

    out.append(_count())
    out.append(
        per_variant(
            "a11.q.promise_terms",
            lambda v: any(
                contains_sequence(folded_words(v.text_local), folded_words(k))
                for k in c.promise_key_terms
            ),
            "every variant repeats a promise key term",
        )
    )
    out.append(
        per_variant(
            "a11.q.text_provenance",
            lambda v: " ".join(v.render.lines) == " ".join(t.text for t in v.texts),
            "displayed text equals the chosen option text",
        )
    )
    bad_words = [fold(x) for x in (*c.must_not_promise, *c.banned_words) if x.strip()]
    out.append(
        per_variant(
            "a11.q.must_not_promise",
            lambda v: not any(b in fold(v.text_local) for b in bad_words),
            "no must-not-promise item or banned word is displayed",
        )
    )
    if empty or not c.finance:
        out.append(_skip("a11.q.finance_text", "not a finance channel or empty set"))
        out.append(_skip("a11.q.finance_imagery", "not a finance channel or empty set"))
    else:
        out.append(
            per_variant(
                "a11.q.finance_text",
                lambda v: not finance_text_hit(v.text_local, c.fin_lexicon),
                "no number, symbol or finance marker in the text",
                rule="FIN-R1",
            )
        )
        out.append(
            per_variant(
                "a11.q.finance_imagery",
                lambda v: v.template_direction_neutral and v.picture.direction_neutral,
                "template and picture are direction neutral",
                rule="FIN-R13",
            )
        )
    charts = [v for v in c.variants if v.picture_fact.asset_kind == "CHART"]
    if empty or not charts:
        out.append(_skip("a11.q.chart_still", "no chart still used"))
    else:
        out.append(
            per_variant(
                "a11.q.chart_still",
                lambda v: (
                    v.picture_fact.asset_kind != "CHART"
                    or (
                        v.picture_fact.data_age_vs_lag == "OLDER_THAN_LAG"
                        and v.picture_fact.label_free
                        and v.picture_fact.direction_balanced
                        and v.picture_fact.data_end_date_present
                    )
                ),
                "chart still older than the lag, label free, balanced",
                rule="FIN-R9",
            )
        )
    out.append(
        per_variant(
            "a11.q.no_person",
            lambda v: (
                not v.picture_fact.is_synthetic_presenter
                and (
                    not v.picture_fact.depicts_real_person
                    or (c.faces_allowed and v.picture_fact.release_ref and not c.finance)
                )
            ),
            "no unreleased or synthetic person",
            rule="FIN-R11",
        )
    )
    ai_free = c.image_provider_calls == 0 and all(
        f.source_type in _ALLOWED_SOURCES
        for f in c.licence_facts
        if f.usage_kind in ("IMAGE", "TEMPLATE")
    )
    out.append(
        _skip("a11.q.no_ai_still", "empty set")
        if empty
        else _ok(
            "a11.q.no_ai_still",
            ai_free,
            "only owner, client or code-made pictures; no image-provider call",
            measured=c.image_provider_calls,
            threshold=0,
        )
    )
    bad_lic = [
        f.asset_id
        for f in c.licence_facts
        if not (
            f.has_ledger_row
            and not f.ledger_has_interval
            and f.licence_state == "ACTIVE"
            and f.covers_monetized
            and not f.expired
            and not (
                f.source_type == "CLIENT_SUPPLIED"
                and f.third_party_permission in (None, "UNKNOWN", "NOT_PERMITTED")
            )
        )
    ]
    out.append(
        _skip("a11.q.licence_rows", "empty set")
        if empty
        else _ok(
            "a11.q.licence_rows",
            not bad_lic,
            "every asset used has an active ledger row without interval",
            rule="YTG-R6",
            measured=len(bad_lic),
            threshold=0,
        )
    )
    out.append(
        per_variant(
            "a11.q.size",
            lambda v: v.file_size_bytes <= s.output_max_bytes,
            "file within the size maximum",
            threshold=s.output_max_bytes,
            unit="bytes",
        )
    )
    out.append(
        per_variant(
            "a11.q.dimensions",
            lambda v: (
                (v.render.width, v.render.height) == (s.canvas_width_px, s.canvas_height_px)
                and v.render.width * 9 == v.render.height * 16
            ),
            "canvas size and 16:9 aspect",
        )
    )
    out.append(
        per_variant(
            "a11.q.legibility",
            lambda v: _legible(v, s),
            "contrast of every text run",
            threshold=s.legibility_min_contrast_ratio,
        )
    )
    out.append(
        per_variant(
            "a11.q.text_fit",
            lambda v: _fits(v, s, c.safe_rect, c.reserved_corner_rect),
            "text inside the safe rectangle, outside the reserved corner",
        )
    )
    if s.legibility_min_text_height_px_at_preview is None or s.legibility_preview_width_px is None:
        out.append(
            _r(
                "a11.q.preview_legibility",
                CheckVerdict.WARN if not empty else CheckVerdict.SKIPPED,
                False,
                "preview threshold not set (REQUIRES REVIEW)",
            )
        )
    else:
        need, prev_w = s.legibility_min_text_height_px_at_preview, s.legibility_preview_width_px
        out.append(
            per_variant(
                "a11.q.preview_legibility",
                lambda v: v.render.font_px * prev_w / s.canvas_width_px >= need,
                "text height at preview size",
                threshold=need,
            )
        )
    out.append(
        per_variant(
            "a11.q.word_count",
            lambda v: (
                len(words(v.text_local)) <= s.text_max_words
                and len(v.text_local) <= s.text_max_chars
            ),
            "displayed words and characters within limits",
        )
    )
    if empty:
        out.append(_skip("a11.q.distinct", "empty set"))
        out.append(_skip("a11.q.single_variable", "empty set"))
    else:
        d = distinctness([v.render.phash for v in c.variants], s.distinct_min_hash_distance_bits)
        diff_ok = all(
            (a.template_key, a.picture.option_id, a.concept.text_ids)
            != (b.template_key, b.picture.option_id, b.concept.text_ids)
            for i, a in enumerate(c.variants)
            for b in c.variants[i + 1 :]
        )
        out.append(
            _ok(
                "a11.q.distinct",
                d.verdict == "PASS" and diff_ok,
                "pairwise hash distance and one differing choice",
                measured=min((b for _, b in d.pairs), default=64),
                threshold=s.distinct_min_hash_distance_bits,
                unit="bits",
            )
        )
        ctrl = c.variants[0]
        single = True
        for v in c.variants[1:]:
            changed = [
                name
                for name, same in (
                    ("LAYOUT_STYLE", v.template_key == ctrl.template_key),
                    ("SUBJECT_CHOICE", v.picture.option_id == ctrl.picture.option_id),
                    ("TEXT_ANGLE", v.concept.text_ids == ctrl.concept.text_ids),
                )
                if not same
            ]
            single = single and changed == [v.concept.hypothesis_kind]
        out.append(
            _ok("a11.q.single_variable", single, "each later variant changes exactly one choice")
        )
    out.append(
        per_variant(
            "a11.q.language_glyphs",
            lambda v: not v.render.missing_glyphs,
            "every character has a glyph",
        )
    )
    cost_ok = (
        c.llm_calls <= 2
        and c.cost_micros <= c.reserved_micros
        and c.cost_micros <= c.max_cost_micros
        and len(c.cost_entry_ids) == c.llm_calls
    )
    out.append(
        _ok(
            "a11.q.cost",
            cost_ok,
            "LLM calls and cost within the reservation",
            measured=c.llm_calls,
            threshold=2,
        )
    )
    out.append(
        _ok(
            "a11.q.rationale_clean",
            all(v.rationale_ok for v in c.variants),
            "rationales are short, free of digits and URLs",
        )
    )
    if not s.llm_enabled:
        out.append(_skip("a11.q.llm_fallback", "deterministic mode"))
    elif c.llm_fallback_code:
        out.append(
            _r(
                "a11.q.llm_fallback",
                CheckVerdict.WARN,
                False,
                f"fallback planner used after {c.llm_fallback_code}",
            )
        )
    else:
        out.append(_r("a11.q.llm_fallback", CheckVerdict.PASS, False, "no fallback needed"))
    return out


__all__ = [
    "ALL_CHECK_IDS",
    "CheckContext",
    "LicenceFact",
    "PictureFact",
    "VariantFacts",
    "run_checks",
    "variant_failures",
]
