"""Internal ``ShotRequirement`` / ``OverlayRequirement`` and the anti-corruption mapper of the
Agent 09 shot plan (``ShotPlanReader``, blueprint 7.1 rule 6, 10.2). This is the only module that
knows Agent 09's field names (``views.agent_08_shots[]``, ``overlays[]``)."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from amw_core.enums import AspectRatio, ShotIntentKind, SubjectAnchor, VisualSourceTier
from amw_core.errors import InputInvalidError

from agent_08_visual_assets.cascade.tier_cascade import IntentKind


@dataclass(frozen=True, slots=True)
class ShotRequirement:
    shot_id: str
    scene_id: str
    start_ms: int
    end_ms: int
    aspect_ratio: AspectRatio
    tier_hint: VisualSourceTier
    intent_kind: ShotIntentKind
    intent_text: str
    on_screen_text: tuple[str, ...]
    chart_id: str | None
    allowed_tiers: tuple[VisualSourceTier, ...]
    fallback_template_key: str
    content_key: str
    allows_hold: bool
    vertical_anchor: SubjectAnchor | None
    realistic_event_depiction: bool
    change_events_ms: tuple[int, ...]

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def internal_intent(self) -> IntentKind:
        if self.intent_kind is ShotIntentKind.CHART:
            return IntentKind.CHART
        if self.intent_kind is ShotIntentKind.FOOTAGE:
            return IntentKind.FOOTAGE
        return IntentKind.GRAPHIC


@dataclass(frozen=True, slots=True)
class OverlayRequirement:
    overlay_id: str
    kind: str
    start_ms: int
    end_ms: int
    template_ref: str | None


class _ShotView(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    shot_id: str
    scene_id: str
    start_ms: int
    end_ms: int
    duration_ms: int
    aspect_ratio: AspectRatio
    tier_hint: VisualSourceTier
    intent_kind: ShotIntentKind
    intent_text: str
    on_screen_text: tuple[str, ...]
    chart_id: str | None
    allowed_tiers: tuple[VisualSourceTier, ...]
    fallback_template_key: str
    content_key: str
    allows_hold: bool
    change_events_ms: tuple[int, ...]
    vertical_anchor: SubjectAnchor | None
    realistic_event_depiction: bool


class _OverlayView(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    overlay_id: str
    kind: str
    start_ms: int
    end_ms: int
    template_ref: str | None = None


_TIER_INDEX = {t: i for i, t in enumerate(VisualSourceTier)}


class IntentClassifier:
    """D1: validates the plan's ``intent_kind`` against ``chart_id``, ``allowed_tiers`` and text;
    an inconsistent shot is ``PERMANENT.INPUT_INVALID`` (never silently repaired)."""

    @staticmethod
    def validate(shot: ShotRequirement) -> None:
        has_chart = shot.chart_id is not None
        if has_chart != (shot.intent_kind is ShotIntentKind.CHART):
            raise InputInvalidError("chart_id present exactly for CHART shots")
        if VisualSourceTier.C_CODE_MOTION not in shot.allowed_tiers:
            raise InputInvalidError("allowed_tiers must contain the tier C fallback")
        order = [_TIER_INDEX[t] for t in shot.allowed_tiers]
        if order != sorted(order) or len(set(order)) != len(order):
            raise InputInvalidError("allowed_tiers must be in hierarchy order")
        if shot.intent_kind is ShotIntentKind.TEXT_CARD and not shot.on_screen_text:
            raise InputInvalidError("a TEXT_CARD shot needs on-screen text")


class ShotPlanReader:
    @staticmethod
    def read(plan_json: bytes | Mapping[str, Any]) -> tuple[list[ShotRequirement], list[OverlayRequirement]]:
        doc = json.loads(plan_json) if isinstance(plan_json, bytes) else dict(plan_json)
        payload = doc.get("data", doc)
        try:
            views = [_ShotView.model_validate(v) for v in payload["views"]["agent_08_shots"]]
            overlays = [_OverlayView.model_validate(o) for o in payload.get("overlays", [])]
        except (KeyError, TypeError, ValidationError):
            raise InputInvalidError("shot plan is not a valid agent_09 plan") from None
        shots = [
            ShotRequirement(
                shot_id=v.shot_id,
                scene_id=v.scene_id,
                start_ms=v.start_ms,
                end_ms=v.end_ms,
                aspect_ratio=v.aspect_ratio,
                tier_hint=v.tier_hint,
                intent_kind=v.intent_kind,
                intent_text=v.intent_text,
                on_screen_text=v.on_screen_text,
                chart_id=v.chart_id,
                allowed_tiers=v.allowed_tiers,
                fallback_template_key=v.fallback_template_key,
                content_key=v.content_key,
                allows_hold=v.allows_hold,
                vertical_anchor=v.vertical_anchor,
                realistic_event_depiction=v.realistic_event_depiction,
                change_events_ms=v.change_events_ms,
            )
            for v in views
        ]
        ShotPlanReader._validate(shots)
        return shots, [
            OverlayRequirement(o.overlay_id, o.kind, o.start_ms, o.end_ms, o.template_ref)
            for o in overlays
        ]

    @staticmethod
    def _validate(shots: Sequence[ShotRequirement]) -> None:
        ids = [s.shot_id for s in shots]
        if len(set(ids)) != len(ids):
            raise InputInvalidError("duplicate shot ids in the plan")
        last_end: dict[AspectRatio, int] = {}
        for s in shots:
            if not 0 <= s.start_ms < s.end_ms:
                raise InputInvalidError("shot interval must satisfy 0 <= start < end")
            if s.start_ms < last_end.get(s.aspect_ratio, 0):
                raise InputInvalidError("shot intervals overlap or are not monotone")
            last_end[s.aspect_ratio] = s.end_ms
            IntentClassifier.validate(s)
