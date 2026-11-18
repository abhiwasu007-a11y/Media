"""The direction loop (P7): per batch render, call, parse, guard, re-ask once, fall back."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial

from pydantic import Field

from agent_09_video_director.config import Agent09Config
from agent_09_video_director.contracts import (
    Direction,
    DirectionInput,
    DirectionOutput,
    DirectionSlot,
    Model,
    Origin,
    Refusal,
    TailItem,
)
from agent_09_video_director.direction.batcher import Batch
from agent_09_video_director.direction.client import DirectionClient
from agent_09_video_director.direction.guard import scan_batch
from agent_09_video_director.direction.parser import parse_direction_output
from agent_09_video_director.direction.prompt import RenderedPrompt, render_prompt
from agent_09_video_director.direction.repair import default_interrupt_device, fallback_direction
from agent_09_video_director.problems import input_invalid
from amw_core.errors import (
    AmwError,
    InsufficientInputError,
    InvalidJsonError,
    OutputSchemaInvalidError,
)


class Accepted(Model):
    direction: Direction
    origin: Origin
    refusal_reason: str | None = None


class ResumeState(Model):
    """Checkpoint state after each accepted batch (FR-19): a kill never repeats a call."""

    input_sha256: str = ""
    batches: dict[str, tuple[Accepted, ...]] = Field(default_factory=dict)
    refusal: Refusal | None = None


@dataclass(slots=True)
class DirectionResult:
    accepted: dict[str, Accepted]
    refusal: Refusal | None
    guard_hits: dict[str, int] = field(default_factory=dict)
    state: ResumeState = field(default_factory=ResumeState)


def _tail(accepted: Sequence[Accepted]) -> tuple[TailItem, ...]:
    items = [
        TailItem(
            slot_id=a.direction.slot_id,
            intent_kind=a.direction.intent_kind,
            framing=a.direction.framing,
        )
        for a in accepted[-2:]
        if a.direction.intent_kind is not None
    ]
    return tuple(items)


def _call_and_parse(
    client: DirectionClient,
    prompt: RenderedPrompt,
    batch_id: str,
    seq: int,
    slot_ids: Sequence[str],
) -> tuple[DirectionOutput, int]:
    """One call, and on a parse failure one retry with the validation error (07 section 3.3)."""
    raw = ""
    try:
        raw = client.complete(prompt, batch_id, seq)
        return parse_direction_output(raw, slot_ids), seq
    except (InvalidJsonError, OutputSchemaInvalidError) as first:
        paths = first.details.get("violations") or [first.code]
        hint = (
            "Your previous output was rejected: "
            + "; ".join(map(str, paths[:20]))
            + ". Return only valid JSON."
        )
        raw = client.complete(prompt, batch_id, seq + 1, extra_user=hint)
        return parse_direction_output(raw, slot_ids), seq + 1


def run_direction(
    *,
    batches: Sequence[Batch],
    base: Callable[[Batch, Sequence[TailItem]], DirectionInput],
    prompt_text: str,
    packs: Mapping[str, str],
    client: DirectionClient,
    cfg: Agent09Config,
    aspect_fallback: Callable[[DirectionSlot], Direction] | None = None,
    resume: ResumeState | None = None,
    checkpoint: Callable[[ResumeState], None] | None = None,
    input_sha256: str = "",
) -> DirectionResult:
    if resume is not None and resume.input_sha256 != input_sha256:
        resume = None  # stale checkpoint: inputs or config changed, discard (blueprint 16 rule 1)
    state = resume or ResumeState(input_sha256=input_sha256)
    accepted: dict[str, Accepted] = {}
    refusal: Refusal | None = state.refusal
    hits_total: dict[str, int] = {}
    previous: list[Accepted] = []
    for batch in batches:
        done = state.batches.get(batch.batch_id)
        if done is not None:  # resumed: no second call
            for a in done:
                accepted[a.direction.slot_id] = a
            previous = list(done)
            continue
        step = base(batch, _tail(previous))
        slot_by_id = {s.slot_id: s for s in batch.slots}
        aspect = step.aspect_ratio
        make_fb = aspect_fallback or partial(fallback_direction, aspect=aspect)
        prompt = render_prompt(prompt_text, step, packs)
        out, seq = _call_and_parse(
            client, prompt, batch.batch_id, 1, [s.slot_id for s in batch.slots]
        )
        results: dict[str, Accepted] = {}
        if out.refusal is not None:
            r = out.refusal.reason
            if r == "INSUFFICIENT_INPUT":
                raise InsufficientInputError("model refused: insufficient input")
            if r in ("OUT_OF_SCOPE", "CONFLICTING_INSTRUCTIONS"):
                raise input_invalid(r)
            refusal = out.refusal
            for s in batch.slots:
                results[s.slot_id] = Accepted(
                    direction=make_fb(s), origin=Origin.FALLBACK, refusal_reason=r
                )
        else:
            pending = {d.slot_id: d for d in out.directions}
            origin_of: dict[str, Origin] = dict.fromkeys(pending, Origin.MODEL)
            for attempt in range(cfg.llm_max_repairs_per_batch + 1):
                hits = scan_batch(list(pending.values()), step)
                for h in hits.values():
                    for x in h:
                        hits_total[x.guard] = hits_total.get(x.guard, 0) + 1
                bad = [
                    sid for sid in pending if sid in hits or pending[sid].status == "NO_SAFE_VISUAL"
                ]
                for sid, d in pending.items():
                    if sid not in bad:
                        results[sid] = Accepted(
                            direction=default_interrupt_device(d, slot_by_id[sid]),
                            origin=origin_of[sid],
                        )
                hard = [sid for sid in bad if sid in hits]
                if not hard or attempt == cfg.llm_max_repairs_per_batch:
                    pending = {}
                    for sid in bad:
                        results[sid] = Accepted(
                            direction=make_fb(slot_by_id[sid]), origin=Origin.FALLBACK
                        )
                    break
                # one re-ask of the failing slots with guard IDs only (no content)
                for sid in bad:
                    if sid not in hits:  # NO_SAFE_VISUAL is final: fallback, no re-ask
                        results[sid] = Accepted(
                            direction=make_fb(slot_by_id[sid]), origin=Origin.FALLBACK
                        )
                sub = step.model_copy(update={"slots": tuple(slot_by_id[s] for s in hard)})
                notes = "; ".join(
                    f"{sid}:{','.join(sorted({x.guard for x in hits[sid]}))}" for sid in hard
                )
                seq += 1
                sub_prompt = render_prompt(prompt_text, sub, packs)
                raw = client.complete(
                    sub_prompt,
                    batch.batch_id,
                    seq,
                    extra_user=f"Guard rejections (IDs only): {notes}. Re-direct these slots.",
                )
                try:
                    redo = parse_direction_output(raw, hard)
                except AmwError:
                    pending = {}
                    for sid in hard:
                        results[sid] = Accepted(
                            direction=make_fb(slot_by_id[sid]), origin=Origin.FALLBACK
                        )
                    break
                pending = {d.slot_id: d for d in redo.directions}
                origin_of = dict.fromkeys(pending, Origin.REPAIRED)
        ordered = tuple(results[s.slot_id] for s in batch.slots)
        for a in ordered:
            accepted[a.direction.slot_id] = a
        previous = list(ordered)
        state = state.model_copy(
            update={"batches": {**state.batches, batch.batch_id: ordered}, "refusal": refusal}
        )
        if checkpoint is not None:
            checkpoint(state)
    return DirectionResult(accepted, refusal, hits_total, state)
