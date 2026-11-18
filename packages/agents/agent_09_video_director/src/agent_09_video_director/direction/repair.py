"""DirectionRepair and FallbackBuilder (F-15): re-ask once, then a code-made fallback."""

from agent_09_video_director.contracts import (
    Anchor,
    AspectRatio,
    Depiction,
    Device,
    Direction,
    DirectionSlot,
    Framing,
    Motion,
    SlotRole,
    TransitionKind,
)

_SAFE = Depiction(
    real_person=False,
    identifiable_person=False,
    market_direction_imagery=False,
    market_data_screen=False,
    brand_or_logo=False,
    ai_presenter=False,
    realistic_event_depiction=False,
    schematic=False,
)


def fallback_direction(slot: DirectionSlot, aspect: AspectRatio) -> Direction:
    """A direction that is always renderable: a ``TEXT_CARD`` from an existing script text option,
    else an abstract code-made motion template (``DIAGRAM`` with no description, tier C).
    Never invented words. An interrupt slot gets ``ZOOM`` / ``PUNCH_IN`` (6.4.3)."""
    interrupt = slot.role is SlotRole.INTERRUPT_REQUIRED
    text_ids = (slot.text_options[0].text_id,) if slot.text_options else ()
    kind = "TEXT_CARD" if text_ids else "DIAGRAM"
    return Direction(
        slot_id=slot.slot_id,
        status="OK",
        reason_code=None,
        intent_kind=kind,
        intent_text="",
        framing=Framing.NONE,
        motion=Motion.PUNCH_IN if interrupt else Motion.STATIC,
        still_ok=False,
        needs_ai_video=False,
        interrupt_device=Device.ZOOM if interrupt else None,
        transition_hint=TransitionKind.CUT,
        text_ids=text_ids,
        subject_anchor=Anchor.CENTER if aspect is AspectRatio.PORTRAIT else None,
        depiction=_SAFE.model_copy(update={"schematic": True}),
        rationale="Code-made fallback.",
    )


def default_interrupt_device(d: Direction, slot: DirectionSlot) -> Direction:
    """6.4.3: a missing or not-allowed device on an interrupt slot becomes ZOOM / PUNCH_IN."""
    if slot.role is not SlotRole.INTERRUPT_REQUIRED:
        return d
    if d.interrupt_device is not None and d.interrupt_device in slot.allowed_devices:
        return d
    return d.model_copy(update={"interrupt_device": Device.ZOOM, "motion": Motion.PUNCH_IN})
