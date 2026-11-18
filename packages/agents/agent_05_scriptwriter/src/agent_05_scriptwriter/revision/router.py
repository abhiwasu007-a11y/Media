"""``FeedbackRouter`` (blueprint 6.6, 10.7): which steps a revision re-runs."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from agent_05_scriptwriter.contracts import FeedbackItem
from agent_05_scriptwriter.errors import InputInvalid

HOOK = "hook"


@dataclass(frozen=True, slots=True)
class RevisionPlan:
    sections_to_rewrite: list[str] = field(default_factory=list)
    rerun_plan: bool = False
    rerun_cut: bool = False
    items_per_section: dict[str, int] = field(default_factory=dict)
    feedback_per_section: dict[str, list[FeedbackItem]] = field(default_factory=dict)


def route_feedback(
    prior: Mapping[str, Sequence[str]], items: Sequence[FeedbackItem], *, shorts: bool = False
) -> RevisionPlan:
    """``prior`` maps ``hook`` and each section id (or ``cut``) to its segment IDs, in order.

    A ``segment_ref`` that is not a segment of the prior script (or previous cut) is
    ``InputInvalid``. Long form: items on sections only re-run those sections; an item without a
    ``segment_ref`` or on a hook segment re-runs the plan step. Shorts: any item re-runs the cut.
    """
    owner: dict[str, str] = {seg: sec for sec, segs in prior.items() for seg in segs}
    for item in items:
        if item.segment_ref is not None and item.segment_ref not in owner:
            raise InputInvalid("segment_ref is not a segment of the prior script")
    if shorts:
        return RevisionPlan(rerun_cut=True)
    if any(i.segment_ref is None or owner[i.segment_ref] == HOOK for i in items):
        return RevisionPlan(rerun_plan=True)
    per_section: dict[str, list[FeedbackItem]] = {}
    for item in items:
        assert item.segment_ref is not None  # noqa: S101 - narrowed by the check above
        per_section.setdefault(owner[item.segment_ref], []).append(item)
    order = [s for s in prior if s in per_section]
    return RevisionPlan(
        sections_to_rewrite=order,
        items_per_section={s: len(per_section[s]) for s in order},
        feedback_per_section={s: per_section[s] for s in order},
    )
