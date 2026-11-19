"""Cost-per-stage report data for the delivery bundle (09 section 12; 3A slice spec section 4,
file 6 ``cost_per_stage_report``). S4 defines the content; ``agent_13.file_delivery`` owns the
file name and manifest entry.

Rules kept here: totals equal the sum of the ledger rows used (scope ``job_id``, 12.3.1);
allocated items are separate lines (12.3.2); an unknown value prints as
``REQUIRES REVIEW (Phase 1): <need>``, never as zero (12.3.3); JSON and a text view (12.3.4); the
report holds no keys, account IDs, server addresses or prompt text (12.3.5, checked on build).
Money stays integer micros; minor units use round-half-up only here (GLOSSARY section 3).
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from amw_core.config.settings import MAX_MINOR_EXPONENT
from amw_core.cost.ledger import effective_rows, figure_kind_label, totals
from amw_core.enums import BudgetPeriod, BudgetScopeKind, BudgetState, CostFigureKind
from amw_core.errors import ConfigInvalidError, InputInvalidError
from amw_core.ids import AttemptId, JobId, TaskId
from amw_core.interfaces.budget_guard import BudgetStatus
from amw_core.interfaces.cost_ledger import CostEntry
from amw_core.observability.redaction import contains_secret

REQUIRES_REVIEW = "REQUIRES REVIEW (Phase 1)"

TERM_OF_OPERATION_PREFIX: tuple[tuple[str, str], ...] = (
    ("llm.", "LLM"),
    ("tts.", "TTS"),
    ("stock.", "footage"),
    ("music.", "music"),
    ("video.generate", "ai_broll"),
    ("render.", "infra"),
    ("storage.", "infra"),
)
"""09 section 9 terms; any other operation is reported under ``other``."""
TERMS: tuple[str, ...] = ("LLM", "TTS", "footage", "music", "ai_broll", "infra", "other")


def review(need: str) -> str:
    return f"{REQUIRES_REVIEW}: {need}"


def term_of(operation: str) -> str:
    for prefix, term in TERM_OF_OPERATION_PREFIX:
        if operation.startswith(prefix):
            return term
    return "other"


@dataclass(frozen=True, slots=True)
class TaskInfo:
    task_type: str
    stage_id: str | None
    iteration: int = 0
    output_discarded: bool = False
    """The task's output was discarded by a gate (its whole cost is wasted)."""
    discarded_attempts: frozenset[AttemptId] = field(default_factory=frozenset)
    """Attempts whose output a gate discarded."""


@dataclass(frozen=True, slots=True)
class AllocatedLine:
    """An allocated (not per-call) item, e.g. a subscription share or the infra share."""

    term: str
    label: str
    amount_micros: int | None
    """``None`` = unknown -> printed as REQUIRES REVIEW with ``need``."""
    need: str = ""


@dataclass(frozen=True, slots=True)
class JobHeader:
    job_id: JobId
    production_type_key: str
    production_type_version: int | str
    topic_ref: str | None
    run_mode: str
    """``development`` or ``vps_night_window``."""


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class StageRow(_Out):
    stage: str
    task_type: str
    provider: str
    model: str | None
    calls: int
    tokens_in: int
    tokens_out: int
    tokens_cached_in: int
    units: dict[str, str]
    cost_micros: int
    cost_minor: int | str
    currency: str
    figure_kind: str
    share_of_total: str
    revision_loops: int
    wasted_cost_micros: int


class BudgetLine(_Out):
    scope_kind: str
    scope_key: str | None
    period: str
    limit_minor: int
    committed_micros: int
    remaining_micros: int
    currency: str
    state: str
    status: str
    """``within_limit`` (green) / ``soft_limit_exceeded`` (amber) / ``breached`` (red)."""
    status_text: str


class AllocatedOut(_Out):
    term: str
    label: str
    allocated: bool = True
    amount_micros: int | str


class CostStageReport(_Out):
    job_id: str
    production_type_key: str
    production_type_version: str
    topic_ref: str | None
    query_scope: str
    figure_kind_summary: str
    price_refs: dict[str, str]
    generated_at: str
    run_mode: str
    currency: str
    rows: list[StageRow]
    total_micros: int
    total_minor: int | str
    terms_micros: dict[str, int]
    allocated: list[AllocatedOut]
    human_review_minutes: int | str
    budgets: list[BudgetLine]
    header_budget: dict[str, int | str]

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)

    def to_text(self) -> str:
        """A plain human-readable view (numbers first)."""
        lines = [
            f"Cost per stage - job {self.job_id} ({self.production_type_key} "
            f"v{self.production_type_version}) - {self.figure_kind_summary}",
            f"Total: {self.total_micros} micros {self.currency} (minor: {self.total_minor})",
            "stage | task_type | provider/model | calls | tok in/out/cached | cost micros | "
            "kind | share | loops | wasted",
        ]
        for r in self.rows:
            lines.append(
                f"{r.stage} | {r.task_type} | {r.provider}/{r.model or '-'} | {r.calls} | "
                f"{r.tokens_in}/{r.tokens_out}/{r.tokens_cached_in} | {r.cost_micros} | "
                f"{r.figure_kind} | {r.share_of_total} | {r.revision_loops} | "
                f"{r.wasted_cost_micros}"
            )
        lines.append("Terms: " + ", ".join(f"{k} {v}" for k, v in self.terms_micros.items()))
        for a in self.allocated:
            lines.append(f"allocated {a.term} ({a.label}): {a.amount_micros}")
        lines.append(f"Human review minutes (not money): {self.human_review_minutes}")
        for b in self.budgets:
            lines.append(
                f"Budget {b.scope_kind}/{b.period}: {b.status_text} "
                f"(committed {b.committed_micros} of limit {b.limit_minor} minor {b.currency})"
            )
        lines.append(f"Query scope: {self.query_scope}; generated {self.generated_at}")
        return "\n".join(lines)


def to_minor(micros: int, currency: str, exponents: Mapping[str, int]) -> int | str:
    exp = exponents.get(currency)
    if exp is None:
        return review(f"minor-unit exponent of {currency} in finance.currency_minor_exponent")
    if isinstance(exp, bool) or not isinstance(exp, int) or not 0 <= exp <= MAX_MINOR_EXPONENT:
        return review(
            f"minor-unit exponent of {currency} outside 0..{MAX_MINOR_EXPONENT} in "
            "finance.currency_minor_exponent"
        )
    value = Decimal(micros) / (Decimal(10) ** (6 - exp))
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _share(part: int, total: int) -> str:
    if total == 0:
        return "n/a (no paid cost)"
    permille = (Decimal(part) * 1000 / Decimal(total)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return f"{permille / 10:.1f}%"


def _kind(rows: Sequence[CostEntry]) -> str:
    kinds = {r.entry.figure_kind for r in rows}
    if kinds == {CostFigureKind.VERIFIED}:
        return "VERIFIED"
    if kinds == {CostFigureKind.ESTIMATE}:
        return "ESTIMATE"
    return "mixed"


def _budget_line(status: BudgetStatus) -> BudgetLine:
    b = status.budget
    if b.state is BudgetState.SUSPENDED_EXCEEDED or status.remaining_micros <= 0:
        state, text = "breached", "breached (red): no new paid call"
    elif status.soft_limit_reached:
        state, text = "soft_limit_exceeded", "soft limit exceeded (amber): warning only"
    else:
        state, text = "within_limit", "within limit (green)"
    return BudgetLine(
        scope_kind=str(b.scope_kind),
        scope_key=b.scope_key,
        period=str(b.period),
        limit_minor=b.limit_minor,
        committed_micros=status.committed_micros,
        remaining_micros=status.remaining_micros,
        currency=b.currency,
        state=str(b.state),
        status=state,
        status_text=text,
    )


def _header_budget(statuses: Sequence[BudgetStatus]) -> dict[str, int | str]:
    out: dict[str, int | str] = {}

    def pick(period: BudgetPeriod) -> BudgetStatus | None:
        return next(
            (
                s
                for s in statuses
                if s.budget.period is period and s.budget.scope_kind is not BudgetScopeKind.PROVIDER
            ),
            None,
        )

    video = pick(BudgetPeriod.PER_VIDEO)
    pilot = pick(BudgetPeriod.PILOT_TOTAL)
    out["per_video_limit_minor"] = video.budget.limit_minor if video else review("per-video limit")
    out["pilot_limit_minor"] = pilot.budget.limit_minor if pilot else review("pilot limit")
    out["pilot_committed_micros"] = pilot.committed_micros if pilot else review("pilot limit")
    out["pilot_remaining_micros"] = pilot.remaining_micros if pilot else review("pilot limit")
    return out


def build_cost_stage_report(
    header: JobHeader,
    rows: Sequence[CostEntry],
    tasks: Mapping[TaskId, TaskInfo],
    budgets: Sequence[BudgetStatus],
    generated_at: datetime,
    currency_minor_exponent: Mapping[str, int],
    price_ref_sources: Mapping[str, str] | None = None,
    allocated: Sequence[AllocatedLine] = (),
    human_review_minutes: int | None = None,
) -> CostStageReport:
    """Build the report from the job's ledger rows (09 section 12)."""
    foreign = [r for r in rows if r.entry.job_id != header.job_id]
    if foreign:
        raise InputInvalidError("report rows must all belong to the job (query scope job_id)")
    sums = totals(rows)
    currency = sums.currency
    used = effective_rows(rows)
    groups: dict[tuple[str, str, str, str | None], list[CostEntry]] = {}
    for row in used:
        info = tasks.get(row.entry.task_id) if row.entry.task_id else None
        task_type = info.task_type if info else review("ledger row not linked to a task")
        stage = (info.stage_id or info.task_type) if info else task_type
        groups.setdefault((stage, task_type, row.entry.provider, row.entry.model), []).append(row)
    total = sums.effective_micros
    out_rows: list[StageRow] = []
    for (stage, task_type, provider, model), members in sorted(
        groups.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2], kv[0][3] or "")
    ):
        cost = sum(m.entry.amount_micros for m in members)
        units: dict[str, Decimal] = {}
        for m in members:
            if m.entry.unit_kind is not None and m.entry.units is not None:
                key = str(m.entry.unit_kind)
                units[key] = units.get(key, Decimal(0)) + m.entry.units
        iterations = {
            tasks[m.entry.task_id].iteration
            for m in members
            if m.entry.task_id is not None and m.entry.task_id in tasks
        }
        wasted = 0
        for m in members:
            info = tasks.get(m.entry.task_id) if m.entry.task_id else None
            if info and (info.output_discarded or m.entry.attempt_id in info.discarded_attempts):
                wasted += m.entry.amount_micros
        out_rows.append(
            StageRow(
                stage=stage,
                task_type=task_type,
                provider=provider,
                model=model,
                calls=len(members),
                tokens_in=sum(m.entry.tokens_in or 0 for m in members),
                tokens_out=sum(m.entry.tokens_out or 0 for m in members),
                tokens_cached_in=sum(m.entry.tokens_cached_in or 0 for m in members),
                units={k: format(v, "f") for k, v in sorted(units.items())},
                cost_micros=cost,
                cost_minor=to_minor(cost, currency, currency_minor_exponent),
                currency=currency,
                figure_kind=_kind(members),
                share_of_total=_share(cost, total),
                revision_loops=max(len(iterations) - 1, 0),
                wasted_cost_micros=wasted,
            )
        )
    terms = dict.fromkeys(TERMS, 0)
    for row in used:
        terms[term_of(str(row.entry.operation))] += row.entry.amount_micros
    sources = price_ref_sources or {}
    price_refs = {
        ref: sources.get(ref, review("research ID of this price_ref"))
        for ref in sorted({r.entry.price_ref for r in used if r.entry.price_ref})
    }
    report = CostStageReport(
        job_id=header.job_id,
        production_type_key=header.production_type_key,
        production_type_version=str(header.production_type_version),
        topic_ref=header.topic_ref,
        query_scope=f"cost_ledger WHERE job_id = {header.job_id}",
        figure_kind_summary=figure_kind_label(sums),
        price_refs=price_refs,
        generated_at=generated_at.isoformat(),
        run_mode=header.run_mode,
        currency=currency or review("no paid call recorded; currency unknown"),
        rows=out_rows,
        total_micros=total,
        total_minor=to_minor(total, currency, currency_minor_exponent) if currency else 0,
        terms_micros=terms,
        allocated=[
            AllocatedOut(
                term=a.term,
                label=a.label,
                amount_micros=a.amount_micros if a.amount_micros is not None else review(a.need),
            )
            for a in allocated
        ],
        human_review_minutes=(
            human_review_minutes
            if human_review_minutes is not None
            else review("human review minutes are not measured yet")
        ),
        budgets=[_budget_line(s) for s in budgets],
        header_budget=_header_budget(budgets),
    )
    if sum(r.cost_micros for r in out_rows) != total:
        raise ConfigInvalidError("report rows do not add up to the ledger total")
    payload: Any = report.model_dump(mode="json")
    if contains_secret(payload):
        raise InputInvalidError("cost report would contain a secret-like value (09 section 12.3.5)")
    return report
