"""ReportSectionBuilder (F-23; blueprint section 10, U-67): the data of the ``qc_report`` preset
(24 section 4, CCR-043) built from the three task payloads (gate 8.2, score 8.4, authorisation
8.5).

Rules: every check row of every payload is present (rules, frame checks, disclosure, criteria,
judged checks, guards); a value that is missing or not yet known prints as
``REQUIRES REVIEW`` and is never turned into zero; a payload that does not exist yet (the task
has not run) yields one ``REQUIRES REVIEW`` row for its section, never an empty pass. The FIN-R9
``earliest_compliant_publish_date`` is shown together with the evaluation date so a date in the
past reads as "already compliant" (review minor 5). Numbers first, prose last (OWNER_RULES D.2:
the preset renders them).
"""

from collections.abc import Mapping, Sequence
from typing import Any, Final, Literal

from agent_16_compliance_qa.base import Model

UNKNOWN: Final = "REQUIRES REVIEW"
Section = Literal["compliance", "quality", "authorisation"]


class ReportRow(Model):
    section: Section
    check_id: str
    verdict: str
    value: str
    detail: str


class ReportSection(Model):
    rows: tuple[ReportRow, ...]
    compliance_verdict: str
    quality_total: str
    authorisation_verdict: str
    earliest_compliant_publish_date: str
    publish_date_note: str


def _v(value: Any) -> str:
    """A value as text; ``None`` / missing is ``REQUIRES REVIEW`` (never ``0``)."""
    if value is None or value == "":
        return UNKNOWN
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _row(section: Section, check_id: Any, verdict: Any, value: Any, detail: Any) -> ReportRow:
    return ReportRow(
        section=section,
        check_id=_v(check_id),
        verdict=_v(verdict),
        value=_v(value),
        detail=_v(detail)[:500],
    )


def _list(payload: Mapping[str, Any], key: str) -> Sequence[Mapping[str, Any]]:
    items = payload.get(key)
    return items if isinstance(items, list) else []


class ReportSectionBuilder:
    def build(
        self,
        gate: Mapping[str, Any] | None,
        score: Mapping[str, Any] | None,
        auth: Mapping[str, Any] | None,
    ) -> ReportSection:
        rows: list[ReportRow] = []
        if gate is None:
            rows.append(_row("compliance", "s16_comp", None, None, "gate has not run"))
        else:
            for r in _list(gate, "rules"):
                rows.append(
                    _row(
                        "compliance",
                        r.get("rule_id"),
                        r.get("compliance_verdict") or r.get("check_verdict"),
                        r.get("check_verdict"),
                        r.get("precondition") or r.get("rationale"),
                    )
                )
            for f in _list(gate, "frame_checks"):
                rows.append(
                    _row(
                        "compliance",
                        f.get("check_id"),
                        f.get("verdict"),
                        f.get("finding"),
                        f.get("rationale"),
                    )
                )
            disc = gate.get("disclosure")
            disc = disc if isinstance(disc, Mapping) else {}
            rows.append(
                _row(
                    "compliance",
                    "disclosure",
                    disc.get("decision"),
                    disc.get("report_text_key"),
                    disc.get("rationale"),
                )
            )
        if score is None:
            rows.append(_row("quality", "s16_score", None, None, "score has not run"))
        else:
            for d in _list(score, "dimensions"):
                for c in _list(d, "criteria"):
                    earned = c.get("earned") if c.get("status") != "SKIPPED" else None
                    rows.append(
                        _row(
                            "quality",
                            c.get("criterion_id"),
                            c.get("status"),
                            f"{_v(earned)} / {_v(c.get('max'))}",
                            c.get("precondition") or d.get("dimension"),
                        )
                    )
            for j in _list(score, "judged_checks"):
                rows.append(
                    _row("quality", j.get("check_id"), j.get("verdict"), None, j.get("rationale"))
                )
        if auth is None:
            rows.append(_row("authorisation", "s16_auth", None, None, "authorisation has not run"))
        else:
            for g in _list(auth, "guards"):
                rows.append(
                    _row(
                        "authorisation",
                        g.get("guard_id"),
                        g.get("result"),
                        g.get("result"),
                        g.get("detail"),
                    )
                )
        earliest = (auth or {}).get("earliest_compliant_publish_date") or (gate or {}).get(
            "earliest_compliant_publish_date"
        )
        evaluated = (auth or {}).get("evaluation_date")
        note = UNKNOWN
        if earliest and evaluated:
            note = (
                "already compliant (the date is on or before the evaluation date)"
                if str(earliest) <= str(evaluated)
                else f"wait until {earliest}"
            )
        elif earliest is None and gate is not None:
            note = "no dated price data (FIN-R9 not applicable)"
        return ReportSection(
            rows=tuple(rows),
            compliance_verdict=_v((gate or {}).get("verdict")),
            quality_total=_v((score or {}).get("machine_total")),
            authorisation_verdict=_v((auth or {}).get("verdict")),
            earliest_compliant_publish_date=_v(earliest),
            publish_date_note=note,
        )
