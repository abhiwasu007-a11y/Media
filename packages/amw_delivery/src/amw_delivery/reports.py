"""QC report (json + md) and cost-per-stage files (json + csv) of the delivery bundle.

Pure functions: inputs in, text out. The 100-point score keeps machine rows apart from human
rows; machine rows count at most 79 points (R1), the rest needs HUMAN rows. Compliance is shown as
its own clearly marked verdict, and the banner, disclaimer text, version and status label come from
the caller and are printed verbatim.
"""

import csv
import io
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from amw_core.errors import InputInvalidError
from amw_delivery.models import (
    MAX_MACHINE_POINTS,
    TOTAL_POINTS,
    BundleInputs,
    ScoreRow,
    ScoreSource,
)


@dataclass(frozen=True, slots=True)
class DimensionScore:
    dimension: str
    max_points: Decimal
    machine: Decimal | None
    human: Decimal | None
    used: Decimal
    evidence: str


@dataclass(frozen=True, slots=True)
class ScoreSummary:
    dimensions: tuple[DimensionScore, ...]
    machine_total: Decimal
    used_total: Decimal


def summarise_score(rows: tuple[ScoreRow, ...]) -> ScoreSummary:
    """Per dimension: machine, human and used points (human replaces machine when present)."""
    by_dim: dict[str, dict[ScoreSource, ScoreRow]] = {}
    for row in rows:
        slot = by_dim.setdefault(row.dimension, {})
        if row.source in slot:
            raise InputInvalidError(
                "two score rows with the same dimension and source",
                details={"dimension": row.dimension, "source": str(row.source)},
            )
        slot[row.source] = row
    out: list[DimensionScore] = []
    for dim in sorted(by_dim):
        slot = by_dim[dim]
        m, h = slot.get(ScoreSource.MACHINE), slot.get(ScoreSource.HUMAN)
        ref = h or m
        assert ref is not None  # noqa: S101 (slot is never empty)
        used = h.points if h else (m.points if m else Decimal(0))
        evidence = " | ".join(r.evidence for r in (m, h) if r is not None and r.evidence)
        out.append(
            DimensionScore(
                dimension=dim,
                max_points=max(r.max_points for r in slot.values()),
                machine=m.points if m else None,
                human=h.points if h else None,
                used=used,
                evidence=evidence,
            )
        )
    machine_total = sum((d.machine or Decimal(0) for d in out), Decimal(0))
    used_total = sum((d.used for d in out), Decimal(0))
    if machine_total > MAX_MACHINE_POINTS:
        raise InputInvalidError(
            "machine rows exceed the machine maximum of the 100-point score",
            details={"machine_total": str(machine_total), "maximum": MAX_MACHINE_POINTS},
        )
    if used_total > TOTAL_POINTS:
        raise InputInvalidError("used points exceed 100", details={"used_total": str(used_total)})
    return ScoreSummary(tuple(out), machine_total, used_total)


def _num(value: Decimal | None) -> str:
    return "-" if value is None else format(value.normalize(), "f")


def qc_report_dict(inputs: BundleInputs) -> dict[str, Any]:
    score = summarise_score(inputs.score_rows)
    gates_failed = [g.gate_id for g in inputs.gates if not g.passed]
    return {
        "banner": inputs.banner,
        "job_id": inputs.job_id,
        "render_sha256": inputs.video_16x9.sha256,
        "compliance": {
            "verdict": str(inputs.compliance.verdict),
            "authorised_for_delivery": inputs.compliance.authorised_for_delivery,
            "authorisation_verdict_id": inputs.compliance.authorisation_verdict_id,
            "render_sha256": inputs.compliance.render_sha256,
        },
        "disclaimer": {
            "text": inputs.disclaimer.text,
            "version": inputs.disclaimer.version,
            "status_label": inputs.disclaimer.status_label,
        },
        "disclosure_note": inputs.disclosure_note,
        "score": {
            "machine_total": _num(score.machine_total),
            "machine_maximum": MAX_MACHINE_POINTS,
            "used_total": _num(score.used_total),
            "out_of": TOTAL_POINTS,
            "dimensions": [
                {
                    "dimension": d.dimension,
                    "max_points": _num(d.max_points),
                    "machine_points": _num(d.machine),
                    "human_points": _num(d.human),
                    "used_points": _num(d.used),
                    "evidence": d.evidence,
                }
                for d in score.dimensions
            ],
        },
        "gates": [
            {
                "gate_id": g.gate_id,
                "result": "PASS" if g.passed else "FAIL",
                "blocking": g.blocking,
                "remedy": g.remedy,
            }
            for g in inputs.gates
        ],
        "gates_failed": gates_failed,
        "checks": [c.model_dump(mode="json") for c in inputs.qc_checks],
    }


def qc_report_json(inputs: BundleInputs) -> str:
    return json.dumps(qc_report_dict(inputs), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def qc_report_md(inputs: BundleInputs) -> str:
    d = qc_report_dict(inputs)
    c = d["compliance"]
    lines = [
        f"# {inputs.banner}",
        "",
        f"QC report - job {inputs.job_id}",
        "",
        "## Compliance verdict",
        "",
        f"**COMPLIANCE VERDICT: {c['verdict']}** "
        f"(authorised for delivery: {'YES' if c['authorised_for_delivery'] else 'NO'}; "
        f"authorisation verdict {c['authorisation_verdict_id']})",
        "",
        f"Disclaimer (FIN-R10), version {inputs.disclaimer.version}, "
        f"status: **{inputs.disclaimer.status_label}**",
        "",
        f"> {inputs.disclaimer.text}",
        "",
        f"Disclosure: {inputs.disclosure_note}",
        "",
        "## 100-point score",
        "",
        f"Machine rows count at most {MAX_MACHINE_POINTS} of {TOTAL_POINTS}; the rest needs "
        "HUMAN rows. A dimension with a human row uses the human points.",
        "",
        "| Dimension | Max | Machine | Human | Used | Evidence |",
        "|---|---|---|---|---|---|",
    ]
    for r in d["score"]["dimensions"]:
        lines.append(
            f"| {_cell(r['dimension'])} | {r['max_points']} | {r['machine_points']} | "
            f"{r['human_points']} | {r['used_points']} | {_cell(r['evidence'])} |"
        )
    lines += [
        "",
        f"Machine total: {d['score']['machine_total']} (maximum {MAX_MACHINE_POINTS}). "
        f"Used total: {d['score']['used_total']} of {TOTAL_POINTS}.",
        "",
        "## Gates",
        "",
        "| Gate | Result | Blocking | Remedy |",
        "|---|---|---|---|",
    ]
    for g in d["gates"]:
        lines.append(
            f"| {_cell(g['gate_id'])} | {g['result']} | {'yes' if g['blocking'] else 'no'} | "
            f"{_cell(g['remedy'] or '-')} |"
        )
    lines += [
        "",
        "## Checks",
        "",
        "| Check | Verdict | Measured | Threshold | Unit |",
        "|---|---|---|---|---|",
    ]
    for k in d["checks"]:
        lines.append(
            f"| {_cell(k['check_id'])} | {k['verdict']} | {_cell(k['measured'] or '-')} | "
            f"{_cell(k['threshold'] or '-')} | {_cell(k['unit'] or '-')} |"
        )
    lines.append("")
    return "\n".join(lines)


def cost_json(inputs: BundleInputs) -> str:
    report = inputs.cost_report
    body = {
        "banner": inputs.banner,
        "report": json.loads(report.to_json()),
        "totals": {
            "total_micros": report.total_micros,
            "total_minor": report.total_minor,
            "currency": report.currency,
            "figure_kind_summary": report.figure_kind_summary,
        },
        "caps": dict(report.header_budget),
    }
    return json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def cost_csv(inputs: BundleInputs) -> str:
    report = inputs.cost_report
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["# " + inputs.banner])
    w.writerow(
        [
            "stage", "task_type", "provider", "model", "calls", "tokens_in", "tokens_out",
            "units_or_characters", "amount_micros", "currency", "figure_kind", "share",
        ]
    )  # fmt: skip
    for r in report.rows:
        w.writerow(
            [
                r.stage, r.task_type, r.provider, r.model or "", r.calls, r.tokens_in,
                r.tokens_out, ";".join(f"{k}={v}" for k, v in r.units.items()), r.cost_micros,
                r.currency, r.figure_kind, r.share_of_total,
            ]
        )  # fmt: skip
    w.writerow(
        ["TOTAL", "", "", "", sum(r.calls for r in report.rows), "", "", "",
         report.total_micros, report.currency, report.figure_kind_summary, ""]
    )  # fmt: skip
    for key, value in report.header_budget.items():
        w.writerow([f"CAP:{key}", "", "", "", "", "", "", "", value, report.currency, "", ""])
    return buf.getvalue()
