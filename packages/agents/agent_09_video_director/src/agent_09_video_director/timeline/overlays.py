"""OverlayPlanner, EndScreenPlanner, ChapterBuilder (F-19, F-20, F-21; FR-10, FR-12)."""

import itertools
from collections.abc import Sequence
from dataclasses import dataclass

from agent_09_video_director.config import Agent09Config
from agent_09_video_director.contracts import (
    AspectRatio,
    BrandKit,
    Chapter,
    DeliberatePause,
    IntentKind,
    Overlay,
    OverlayKind,
    ScriptDoc,
    Section,
    Shot,
    TextRef,
    TextRefDisclaimer,
)
from agent_09_video_director.problems import input_invalid
from agent_09_video_director.timeline.timemap import TimeMap

CAPTION_CARD_ID = "caption_card"
CHAPTER_CARD_ID = "chapter_card"
DISCLAIMER_CARD_ID = "disclaimer_card"
END_SCREEN_ID = "end_screen"
"""Platform package template IDs (agent_09 8.2, CCR-204): registered per tenant by the shared
template registry; Agent 08 alone resolves an ID to an asset."""


@dataclass(frozen=True, slots=True)
class EndScreen:
    start_ms: int
    end_ms: int


def plan_brand_sting(
    hook_end_ms: int, brand: BrandKit, cfg: Agent09Config
) -> tuple[int, int] | None:
    """6.4.7: only with an intro template, starting exactly at the hook end, never earlier."""
    if brand.intro_ref is None or brand.intro_duration_ms is None:
        return None
    length = brand.intro_duration_ms
    if cfg.sting_max_ms is not None:
        length = min(length, cfg.sting_max_ms)
    return (hook_end_ms, hook_end_ms + length)


def plan_end_screen(
    content_end_ms: int, cfg: Agent09Config
) -> tuple[EndScreen | None, tuple[DeliberatePause, ...]]:
    """Reserved segment after the narration; length unset -> none (check WARN)."""
    if cfg.end_screen_length_ms is None:
        return None, ()
    end = content_end_ms + cfg.end_screen_length_ms
    return (
        EndScreen(content_end_ms, end),
        (DeliberatePause(start_ms=content_end_ms, end_ms=end, reason="END_SCREEN"),),
    )


def section_start_ms(script: ScriptDoc, tm: TimeMap) -> dict[str, int]:
    """Start of every section's chapter (18 ``edit.chapters``, CCR-202).

    The first chapter starts at 0 and covers the lead-in (every scene before the first scene of
    ``sections[0]``: the hook and an ``AFTER_HOOK`` disclaimer); every later section starts at
    the measured start of its first segment.
    """
    first_seg = {sc.scene_id: sc.segment_ids[0] for sc in script.scenes if sc.segment_ids}
    return {
        sec.section_id: 0 if i == 0 else tm.start(first_seg[sec.scene_ids[0]])
        for i, sec in enumerate(script.sections)
        if sec.scene_ids
    }


def build_chapters(
    sections: Sequence[Section], section_start_ms: dict[str, int], aspect: AspectRatio
) -> tuple[Chapter, ...]:
    """Chapters from measured section starts (script estimates are ignored)."""
    if aspect is AspectRatio.PORTRAIT or not sections:
        return ()
    chapters = tuple(
        Chapter(
            section_id=s.section_id,
            start_ms=section_start_ms[s.section_id],
            title_local=s.heading_local,
        )
        for s in sections
    )
    starts = [c.start_ms for c in chapters]
    if starts[0] != 0 or any(b <= a for a, b in itertools.pairwise(starts)):
        raise input_invalid("CHAPTER_ORDER")
    return chapters


def plan_overlays(
    shots: Sequence[Shot],
    *,
    hook_end_ms: int,
    content_end_ms: int,
    brand: BrandKit,
    chapters: Sequence[Chapter],
    aspect: AspectRatio,
    cfg: Agent09Config,
) -> tuple[Overlay, ...]:
    """Track V2: sting at the hook end, lower-thirds / caption cards (script text only),
    disclaimer cards, optional chapter cards, end screen last. No free text anywhere."""
    vertical = aspect is AspectRatio.PORTRAIT
    items: list[tuple[int, int, OverlayKind, str, tuple[TextRef, ...]]] = []
    sting = plan_brand_sting(hook_end_ms, brand, cfg)
    if sting is not None and brand.intro_ref is not None:
        items.append((sting[0], sting[1], OverlayKind.BRAND_STING, brand.intro_ref, ()))
    for shot in shots:
        disclaimers = tuple(t for t in shot.text_refs if isinstance(t, TextRefDisclaimer))
        if disclaimers:
            items.append(
                (
                    shot.start_ms,
                    shot.end_ms,
                    OverlayKind.DISCLAIMER_CARD,
                    DISCLAIMER_CARD_ID,
                    disclaimers,
                )
            )
            continue
        if shot.text_refs and shot.intent_kind is not IntentKind.TEXT_CARD:
            lower_third = brand.lower_third_template_ref
            if vertical or lower_third is None:
                kind, template = OverlayKind.CAPTION_CARD, CAPTION_CARD_ID
            else:
                kind, template = OverlayKind.LOWER_THIRD, lower_third
            items.append((shot.start_ms, shot.end_ms, kind, template, shot.text_refs))
    if cfg.chapter_cards_enabled:
        by_start = {s.start_ms: s for s in shots}
        for ch in chapters:
            first = by_start.get(ch.start_ms)
            if first is not None:
                items.append(
                    (first.start_ms, first.end_ms, OverlayKind.CHAPTER_CARD, CHAPTER_CARD_ID, ())
                )
    end_screen, _ = plan_end_screen(content_end_ms, cfg)
    if end_screen is not None:
        items.append(
            (
                end_screen.start_ms,
                end_screen.end_ms,
                OverlayKind.END_SCREEN,
                brand.outro_ref or END_SCREEN_ID,
                (),
            )
        )
    order = {k: i for i, k in enumerate(OverlayKind)}
    items.sort(key=lambda it: (it[0], order[it[2]], it[1]))
    return tuple(
        Overlay(
            overlay_id=f"ov{i:02d}",
            kind=kind,
            start_ms=start,
            end_ms=end,
            template_ref=tpl,
            text_refs=refs,
            vertical_variant=vertical,
        )
        for i, (start, end, kind, tpl, refs) in enumerate(items, start=1)
    )
