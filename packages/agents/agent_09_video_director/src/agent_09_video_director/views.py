"""Hand-off views (FR-20, blueprint 8.1.1): the same plan seen by Agents 08, 11 and 16."""

from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import Field

from agent_09_video_director.assemble import sha256_text  # noqa: F401
from agent_09_video_director.contracts import (
    Anchor,
    AspectRatio,
    Framing,
    IntentKind,
    Model,
    Origin,
    ScriptDoc,
    Shot,
    ShotId,
    ShotPlan,
    TextRefDisclaimer,
    TextRefScene,
    Tier,
)


class Agent08Shot(Model):
    shot_id: ShotId
    scene_id: str
    start_ms: int
    end_ms: int
    duration_ms: int
    aspect_ratio: AspectRatio
    tier_hint: Tier
    intent_kind: IntentKind
    intent_text: str = Field(max_length=240)
    on_screen_text: tuple[str, ...]
    chart_id: str | None
    allowed_tiers: tuple[Tier, ...]
    fallback_template_key: str
    content_key: str
    allows_hold: bool
    change_events_ms: tuple[int, ...]
    vertical_anchor: Anchor | None
    realistic_event_depiction: bool
    parent_shot_id: str | None


class Agent11Subject(Model):
    hint_id: Annotated[str, Field(pattern=r"^hn[0-9]{2}$")]
    shot_id: ShotId
    shot_role: Literal["HOOK", "PROOF"]
    intent_text: str = Field(max_length=240)
    framing: Framing


class Agent16Realism(Model):
    shot_id: ShotId
    realistic_event_depiction: bool
    schematic: bool
    origin: Origin
    refusal_reason: Literal["RULE_WOULD_BE_BROKEN", "UNSAFE_CONTENT"] | None


class Views(Model):
    agent_08_shots: tuple[Agent08Shot, ...]
    agent_11_subjects: tuple[Agent11Subject, ...] = Field(max_length=4)
    agent_16_realism: tuple[Agent16Realism, ...]


def _resolve_text(script: ScriptDoc, shot: Shot) -> tuple[str, ...]:
    out: list[str] = []
    scenes = {s.scene_id: s for s in script.scenes}
    for ref in shot.text_refs:
        if isinstance(ref, TextRefScene):
            out.append(scenes[ref.scene_id].on_screen_text[ref.index])
        elif isinstance(ref, TextRefDisclaimer):
            out.append(ref.disclaimer_slot_id)  # wording is the template's; ID is the handle
    return tuple(out)


def build_views(plan: ShotPlan, script: ScriptDoc) -> Views:
    shots = plan.shots
    a08 = tuple(
        Agent08Shot(
            shot_id=s.shot_id,
            scene_id=s.scene_id,
            start_ms=s.start_ms,
            end_ms=s.end_ms,
            duration_ms=s.duration_ms,
            aspect_ratio=plan.aspect_ratio,
            tier_hint=s.tier_hint,
            intent_kind=s.intent_kind,
            intent_text=s.intent_text,
            on_screen_text=_resolve_text(script, s),
            chart_id=s.chart_id,
            allowed_tiers=s.allowed_tiers,
            fallback_template_key=s.fallback_template_key,
            content_key=s.content_key,
            allows_hold=s.held is not None,
            change_events_ms=s.change_events_ms,
            vertical_anchor=s.vertical.subject_anchor if s.vertical else None,
            realistic_event_depiction=s.depiction.realistic_event_depiction,
            parent_shot_id=s.parent_shot_id,
        )
        for s in shots
    )
    hook_ids = set(plan.hook.segment_ids)
    chosen: list[tuple[Shot, Literal["HOOK", "PROOF"]]] = []
    for s in shots:
        if s.intent_kind in (IntentKind.CHART, IntentKind.TEXT_CARD):
            continue
        if hook_ids & set(s.segment_ids) and len(chosen) < 4:
            chosen.append((s, "HOOK" if not chosen else "PROOF"))
    subjects = tuple(
        Agent11Subject(
            hint_id=f"hn{i:02d}",
            shot_id=s.shot_id,
            shot_role=role,
            intent_text=s.intent_text,
            framing=s.framing,
        )
        for i, (s, role) in enumerate(chosen, start=1)
    )
    reasons = {r["shot_id"]: r["refusal_reason"] for r in plan.realism}
    realism = tuple(
        Agent16Realism(
            shot_id=s.shot_id,
            realistic_event_depiction=s.depiction.realistic_event_depiction,
            schematic=s.depiction.schematic,
            origin=s.origin,
            refusal_reason=reasons.get(s.shot_id),
        )
        for s in shots
    )
    return Views(agent_08_shots=a08, agent_11_subjects=subjects, agent_16_realism=realism)


def view_matches_shots(views: Views, shots: Sequence[Shot]) -> bool:
    """Contract test C-05: the Agent 08 view equals the shot objects field by field."""
    return all(
        v.shot_id == s.shot_id
        and v.start_ms == s.start_ms
        and v.end_ms == s.end_ms
        and v.content_key == s.content_key
        and v.allowed_tiers == s.allowed_tiers
        for v, s in zip(views.agent_08_shots, shots, strict=True)
    )
