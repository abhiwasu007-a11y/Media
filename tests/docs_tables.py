"""Parsers for the binding design documents (tests compare code against these, not the reverse)."""

import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs" / "v4"
_TICK = re.compile(r"`([^`]+)`")


def doc_text(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def section(text: str, heading_re: str, level: int) -> str:
    """Body of the first ``level`` heading matching ``heading_re``, up to the next one."""
    marks = "#" * level
    lines = text.splitlines()
    out: list[str] = []
    inside = False
    for line in lines:
        if re.match(rf"^{marks} ", line):
            if inside:
                break
            inside = re.match(rf"^{marks} {heading_re}", line) is not None
            continue
        if inside:
            out.append(line)
    if not inside and not out:
        raise AssertionError(f"heading not found: {heading_re}")
    return "\n".join(out)


def table_rows(body: str) -> list[list[str]]:
    """Cells of every markdown table data row (header and separator rows skipped)."""
    rows: list[list[str]] = []
    header_seen = False
    for line in body.splitlines():
        if not line.startswith("|"):
            header_seen = False
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            header_seen = True
            continue
        if header_seen:
            rows.append(cells)
    return rows


def ticks(text: str) -> list[str]:
    """Backticked tokens in order, de-duplicated."""
    seen: dict[str, None] = {}
    for token in _TICK.findall(text):
        seen.setdefault(token, None)
    return list(seen)


def list_values(text: str) -> list[str]:
    """Values of a ``·``-separated list: the leading backticked token of each segment, so prose
    and cross-references after a value (``(`UNKNOWN` is ...)``, ``A `cost_ledger` row``) are
    ignored."""
    values: list[str] = []
    for segment in text.split("·"):
        match = re.match(r"\s*`([^`]+)`", segment)
        if match and match[1] not in values:
            values.append(match[1])
    return values


def _expand_ranges(text: str) -> list[str]:
    values: list[str] = []
    for letter, lo, hi in re.findall(r"`([A-Z])(\d+)`\s*[\u2013-]\s*`[A-Z](\d+)`", text):
        width = len(lo)
        values += [f"{letter}{n:0{width}d}" for n in range(int(lo), int(hi) + 1)]
    return values


def glossary_enums() -> dict[str, list[str]]:
    """Every enum of GLOSSARY section 6 as ``{name: values}`` (exact spellings)."""
    s6 = section(doc_text("GLOSSARY_AND_IDS.md"), r"6\. ", 2)
    result: dict[str, list[str]] = {}
    for block in re.split(r"(?m)^### ", s6)[1:]:
        heading, _, body = block.partition("\n")
        number = heading.split(" ", 1)[0]
        names = ticks(heading.split("(", 1)[0])
        first_list = next((ln for ln in body.splitlines() if "`" in ln and "·" in ln), "")
        rows = table_rows(body)
        if number in {"6.44", "6.45", "6.52"}:
            for row in rows:
                row_names = ticks(row[0].split("(", 1)[0])
                cell = row[1]
                if cell.startswith("uses "):
                    groups = [result[ticks(cell)[0]]]
                elif cell.startswith("same as "):
                    groups = [list_values(cell.split(":", 1)[1])]
                elif "\u2013" in cell:  # en dash range
                    groups = [_expand_ranges(cell)]
                elif " / " in cell and len(row_names) > 1:
                    groups = [list_values(part) for part in cell.split(" / ")]
                else:
                    groups = [list_values(cell)]
                if len(groups) == 1:
                    groups = groups * len(row_names)
                for name, values in zip(row_names, groups, strict=True):
                    result[name] = values
        elif number == "6.2":
            result["job_state"] = [v for v in result["task_state"] if v != "RETRY_WAIT"]
        elif number == "6.36":
            decision, kind = first_list.split("Kind:")
            result["experiment_decision"] = list_values(decision.split(":", 1)[1])
            result["experiment_kind"] = list_values(kind)
        elif number == "6.37":
            scope, severity = first_list.split("Severity:")
            result["rule_pack_scope"] = list_values(scope.split(":", 1)[1])
            result["rule_severity"] = list_values(severity)
            keys: list[str] = []
            for row in rows:
                key = ticks(row[0])[0]
                if "<sector>" in key:
                    sectors = ticks(row[2].split("sectors:", 1)[1])
                    keys += [key.replace("<sector>", s) for s in sectors]
                else:
                    keys.append(key)
            result["rule_pack_key"] = keys
        elif number == "6.38":
            result["fin_rule_id"] = [ticks(r[0])[0] for r in rows]
        elif number == "6.38a":
            result["ytg_rule_id"] = [ticks(r[0])[0] for r in rows]
        elif number == "6.49":
            result["ad_spot_duration_s"] = [t for t in ticks(body) if t.isdigit()]
        elif rows:
            result[names[0]] = [ticks(r[0])[0] for r in rows]
        else:
            line = next(ln for ln in body.splitlines() if "`" in ln)
            result[names[0]] = list_values(line.split(" — ", 1)[0])
    return result


def glossary_prefixes() -> dict[str, str]:
    """GLOSSARY section 2.2: ``{prefix: entity}``."""
    body = section(doc_text("GLOSSARY_AND_IDS.md"), r"2\.2 ", 3)
    return {ticks(r[0])[0]: r[1] for r in table_rows(body)}


def error_catalogue() -> dict[str, list[str]]:
    """07 section 2: ``{code: [meaning, disposition, policy, breaker, escalation]}``."""
    body = section(doc_text("07_FAILURE_MANAGEMENT.md"), r"2\. ", 2)
    return {ticks(r[0])[0]: r[1:] for r in table_rows(body)}


def doc_json_schemas() -> list[str]:
    """Raw JSON blocks of 03 and 24 that declare an ``urn:amw:schema`` ``$id``."""
    blocks: list[str] = []
    for name in ("03_COMMUNICATION_STANDARD.md", "24_PRODUCTION_TYPES.md"):
        blocks += re.findall(r"```json\n(.*?)```", doc_text(name), re.S)
    return [b for b in blocks if '"$id": "urn:amw:schema:' in b]


def _stage_route(cell: str) -> dict[str, object] | None:
    """Gate of a 24 section 7 stage-table cell, or ``None``."""
    if "on_fail STOP" in cell:
        return {"blocking": True, "on_fail": {"action": "STOP"}}
    match = re.search(r"on_fail REVISE → (\w+)(?:; alt ([\w, ]+?))?\s*(?:[.(;]|$)", cell)
    if match is None:
        return None
    on_fail: dict[str, object] = {"action": "REVISE", "target_stage_id": match[1]}
    if match[2]:
        on_fail["alt_target_stage_ids"] = [a.strip() for a in match[2].split(",") if a.strip()]
    return {"blocking": True, "on_fail": on_fail}


def stage_table(heading_re: str) -> list[dict[str, object]]:
    """Stages of one 24 section 7 record table as ``amw.production_type`` stage objects."""
    body = section(doc_text("24_PRODUCTION_TYPES.md"), heading_re, 3)
    stages: list[dict[str, object]] = []
    for row in table_rows(body):
        if len(row) != 7 or not re.fullmatch(r"[a-z0-9_]{2,32}", row[0]):
            continue
        stage_id, task_cell, req, klass, caps, deps, route = row
        gate = _stage_route(route)
        if route.startswith("blocking") and gate is None:
            raise AssertionError(f"unparsed gate route for {stage_id}: {route}")
        approval = re.match(r"`([A-Z_]+)` / `([a-z_]+)`", route)
        stage: dict[str, object] = {}
        if not req.startswith("yes") and "disabled" in req:
            stage["enabled_by_default"] = False
        stages.append(
            stage
            | {
                "stage_id": stage_id,
                "task_type": ticks(task_cell)[0],
                "required": req.startswith("yes"),
                "resource_class": klass,
                "capabilities": ticks(caps),
                "depends_on": re.findall(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b", deps.split("(")[0]),
                "gate": gate,
                "approval": {"approval_kind": approval[1], "workflow_key": approval[2]}
                if approval
                else None,
            }
        )
    return stages


def idempotency_scopes() -> list[str]:
    """03 section 9.2: every scope name (``task.<task_type>`` kept as written)."""
    body = section(doc_text("03_COMMUNICATION_STANDARD.md"), r"9\.2 ", 3)
    return [ticks(r[0])[0] for r in table_rows(body)]


def system_actor_names() -> list[str]:
    """GLOSSARY section 2.3: the names allowed after ``sys_``."""
    body = section(doc_text("GLOSSARY_AND_IDS.md"), r"2\.3 ", 3)
    row = next(r for r in table_rows(body) if r[0] == "`SYSTEM`")
    return ticks(row[1].split("∈", 1)[1])


def r14_tables() -> tuple[list[str], dict[str, list[str]]]:
    """03 11.6 rule 7: authenticity test IDs and ``{verification kind: record kinds}``."""
    body = section(doc_text("03_COMMUNICATION_STANDARD.md"), r"11\.6 ", 3)
    rows = [
        [c.strip() for c in line.strip().strip("|").split("|")]
        for line in body.splitlines()
        if line.strip().startswith("|")
    ]
    test_ids: list[str] = []
    kinds: dict[str, list[str]] = {}
    for row in rows:
        if re.fullmatch(r"A\d", row[0]):
            test_ids += [t for t in re.findall(r"\bA\d\b", " ".join(row)) if t not in test_ids]
        elif len(row) >= 2 and re.fullmatch(r"`[A-Z]+`", row[0]):
            kinds[ticks(row[0])[0]] = ticks(row[1].split("(")[0])
    return test_ids, kinds
