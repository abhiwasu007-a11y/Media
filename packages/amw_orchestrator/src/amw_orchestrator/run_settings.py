"""Seeded operational defaults of the run entry point (owner decision D16: no hard-coded
operational values). The file ``data/run_entry.json`` carries the seeds; amw_core settings win
where they carry the same knob (the per-stage cost budget ``llm.tasks.<type>.cost_budget_micros``,
``limits.max_attempts_per_task``). A bad or missing file is ``CONFIG_INVALID`` (fail closed)."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from amw_core.config import AmwSettings
from amw_core.errors import ConfigInvalidError
from amw_orchestrator.plumbing import DeliveryLimits

DEFAULT_FILE: Final = Path(__file__).parent / "data" / "run_entry.json"
_ROLE = r"^[a-z][a-z0-9_]*$"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DeliveryLimitsSeed(_Model):
    max_file_bytes: int = Field(gt=0)
    max_total_bytes: int = Field(gt=0)
    max_thumbnail_bytes: int = Field(gt=0)


class TtsSettings(_Model):
    provider: str | None = None
    """``tts.provider``: the owner's voice route. NO default: unset refuses a real run."""


class RunEntrySettings(_Model):
    schema_id: str = Field(alias="schema")
    note: str
    database_role: str = Field(pattern=_ROLE)
    stage_max_wall_ms: int = Field(gt=0)
    stage_max_llm_calls: int = Field(gt=0)
    claim_lease_ms: int = Field(gt=0)
    score_lock_ms: int = Field(gt=0)
    """Window of the ``ScoreStore`` effect lock (CCR-304). Its own key: it is not the task lease."""
    worker_name_prefix: str
    """Only workers whose ``logical_name`` starts with it are used (empty: any worker)."""
    worker_statuses: tuple[str, ...] = Field(min_length=1)
    stage_cost_budget_micros: dict[str, int]
    dry_run_delivery_limits: DeliveryLimitsSeed
    tts: TtsSettings = TtsSettings()

    def delivery_limits(self) -> DeliveryLimits:
        d = self.dry_run_delivery_limits
        return DeliveryLimits(d.max_file_bytes, d.max_total_bytes, d.max_thumbnail_bytes)

    def paid_budgets(self, settings: AmwSettings) -> Mapping[str, int]:
        """Per task type: the amw_core setting when it is a positive number, else the seed."""
        merged = dict(self.stage_cost_budget_micros)
        for task_type, task in settings.llm.tasks.items():
            if task.cost_budget_micros is not None and task.cost_budget_micros > 0:
                merged[task_type] = task.cost_budget_micros
        return merged


def load_run_entry_settings(path: Path | None = None) -> RunEntrySettings:
    file = path or DEFAULT_FILE
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
        return RunEntrySettings.model_validate(raw)
    except OSError, ValueError, ValidationError:
        raise ConfigInvalidError(
            "run entry settings are missing or invalid", details={"file": file.name}
        ) from None
