"""``CheckpointManager`` (blueprint 16, ``CR-*``): resume without repeating a paid or ledger effect.

``completed_effects`` (idempotency-key natural names) is the source of truth for effects: a crash
after a ledger row but before the checkpoint must not write the row twice, and a stock licence
already registered must not be bought again.
"""

from collections.abc import Sequence
from dataclasses import dataclass

LEDGER_EFFECT_PREFIX = "db.output:ledger:"


def ledger_effect(shot_id: str) -> str:
    return f"{LEDGER_EFFECT_PREFIX}{shot_id}"


@dataclass(frozen=True, slots=True)
class ResumePlan:
    remaining: tuple[str, ...]
    ledger_rows_to_write: tuple[str, ...]
    external_effects_to_skip: tuple[str, ...]


class CheckpointManager:
    @staticmethod
    def resume(
        shots: Sequence[str],
        checkpoint_completed: Sequence[str],
        completed_effects: Sequence[str],
    ) -> ResumePlan:
        done = set(checkpoint_completed)
        remaining = tuple(s for s in shots if s not in done)
        effects = set(completed_effects)
        to_write = tuple(s for s in remaining if ledger_effect(s) not in effects)
        finished_ledgers = {ledger_effect(s) for s in done}
        skip = tuple(e for e in completed_effects if e not in finished_ledgers)
        return ResumePlan(remaining, to_write, skip)
