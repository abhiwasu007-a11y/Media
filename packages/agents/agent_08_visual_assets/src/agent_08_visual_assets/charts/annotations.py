"""``AnnotationValidator``: nothing forward-looking on a chart (FIN-R13, FIN-R1, FIN-R2).

Allowed kinds only: ``MARK_BAR``, ``HLINE_THROUGH_BARS`` (starts and ends inside the window, never
extended right), ``SHADE_RANGE`` and ``LABEL`` (text from the script's on-screen text allowlist or
the versioned template label set). Anything else, anything right of the last bar and any free text
is rejected (blueprint 6.4(5), AN-01 to AN-07). Bar numbers are dataset bar indexes.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class AnnotationKind(StrEnum):
    MARK_BAR = "MARK_BAR"
    HLINE_THROUGH_BARS = "HLINE_THROUGH_BARS"
    SHADE_RANGE = "SHADE_RANGE"
    LABEL = "LABEL"


class Annotation(BaseModel):
    """One annotation of an owner chart case. ``kind`` stays a string so that an unknown kind
    reaches the validator and is rejected there (``KIND_NOT_ALLOWED``) instead of at parsing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    bar: int | None = None
    from_bar: int | None = None
    to_bar: int | None = None
    text: str | None = None
    price: str | None = None
    extend_right: bool = False


class Rejection(StrEnum):
    BEYOND_LAST_BAR = "BEYOND_LAST_BAR"
    TEXT_NOT_ALLOWED = "TEXT_NOT_ALLOWED"
    KIND_NOT_ALLOWED = "KIND_NOT_ALLOWED"
    MALFORMED = "MALFORMED"


@dataclass(frozen=True, slots=True)
class AnnotationVerdict:
    ok: bool
    reason: Rejection | None = None


_OK = AnnotationVerdict(True)


def _bad(reason: Rejection) -> AnnotationVerdict:
    return AnnotationVerdict(False, reason)


class AnnotationValidator:
    @staticmethod
    def validate(
        *,
        annotations: Sequence[Annotation],
        last_bar_index: int,
        on_screen_text_allowlist: Collection[str],
        template_labels: Collection[str],
        first_bar_index: int = 0,
    ) -> AnnotationVerdict:
        allowed_text = set(on_screen_text_allowlist) | set(template_labels)
        kinds = {k.value for k in AnnotationKind}
        for a in annotations:
            if a.kind not in kinds:
                return _bad(Rejection.KIND_NOT_ALLOWED)
            verdict = AnnotationValidator._one(a, first_bar_index, last_bar_index, allowed_text)
            if not verdict.ok:
                return verdict
        return _OK

    @staticmethod
    def _one(
        a: Annotation, first: int, last: int, allowed_text: Collection[str]
    ) -> AnnotationVerdict:
        kind = AnnotationKind(a.kind)
        if kind is AnnotationKind.HLINE_THROUGH_BARS and a.extend_right:
            return _bad(Rejection.BEYOND_LAST_BAR)
        if kind in (AnnotationKind.MARK_BAR, AnnotationKind.LABEL):
            bars = [a.bar]
        elif kind is AnnotationKind.HLINE_THROUGH_BARS:
            bars = [a.from_bar if a.from_bar is not None else first, a.to_bar]
        else:
            bars = [a.from_bar, a.to_bar]
        resolved = [b for b in bars if b is not None]
        if len(resolved) != len(bars):
            return _bad(Rejection.MALFORMED)
        for b in resolved:
            if b > last:
                return _bad(Rejection.BEYOND_LAST_BAR)
            if b < first:
                return _bad(Rejection.MALFORMED)
        if kind is AnnotationKind.LABEL and (a.text is None or a.text not in allowed_text):
            return _bad(Rejection.TEXT_NOT_ALLOWED)
        if kind is not AnnotationKind.LABEL and a.text is not None:
            return _bad(Rejection.TEXT_NOT_ALLOWED)
        return _OK
