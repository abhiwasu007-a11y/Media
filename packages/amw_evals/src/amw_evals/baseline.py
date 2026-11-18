"""Known-defect baseline and the lint report (report-only for old defects, blocking for new)."""

import json
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from amw_evals.findings import Finding


def load_baseline(path: Path | None) -> set[str]:
    if path is None or not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k) for k in data.get("findings", [])}


def write_baseline(path: Path, findings: list[Finding]) -> None:
    payload = {
        "description": (
            "Known defects in existing draft prompts/evals under docs/v4 (lane owners fix them). "
            "Findings listed here are report-only; any finding not listed is blocking."
        ),
        "findings": sorted({f.key for f in findings}),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def changed_files(ref: str, cwd: Path | None = None) -> set[str]:
    out = subprocess.run(  # noqa: S603
        ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{ref}...HEAD"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
        cwd=cwd,
    ).stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


def _unit(path: str) -> str:
    """The unit a finding belongs to: the dataset folder for cases.jsonl, else the file itself."""
    return path.rsplit("/", 1)[0] + "/" if path.endswith("/cases.jsonl") else path


def is_changed(finding: Finding, changed: set[str]) -> bool:
    unit = _unit(finding.path)
    if unit.endswith("/"):
        return any(c.startswith(unit) for c in changed)
    return unit in changed


@dataclass
class Classified:
    blocking: list[Finding]
    known: list[Finding]
    fixed_baseline_keys: list[str]


def classify(
    findings: list[Finding], baseline: set[str], changed: set[str] | None = None
) -> Classified:
    changed = changed or set()
    blocking: list[Finding] = []
    known: list[Finding] = []
    for f in findings:
        if f.key not in baseline or is_changed(f, changed):
            blocking.append(f)
        else:
            known.append(f)
    current = {f.key for f in findings}
    return Classified(blocking, known, sorted(baseline - current))


def _agent_of(path: str) -> str:
    parts = path.split("/")
    for i, p in enumerate(parts):
        if p in ("prompts", "evals") and i + 1 < len(parts):
            return parts[i + 1]
    return "(other)"


def counts_per_agent(findings: list[Finding]) -> dict[str, tuple[int, int]]:
    """agent -> (files with defects, findings)."""
    files: dict[str, set[str]] = {}
    n: Counter[str] = Counter()
    for f in findings:
        a = _agent_of(f.path)
        files.setdefault(a, set()).add(f.path)
        n[a] += 1
    return {a: (len(files[a]), n[a]) for a in sorted(files)}


def render_report(
    findings: list[Finding], cls: Classified, scanned_prompts: int, scanned_datasets: int
) -> str:
    lines = [
        "# Prompt and eval lint report",
        "",
        f"Scanned {scanned_prompts} prompt file(s) and {scanned_datasets} eval dataset(s).",
        f"Findings: {len(findings)} total; {len(cls.known)} known (baseline, report-only); "
        f"**{len(cls.blocking)} blocking** (new or in a changed file).",
        "",
    ]
    per_agent = counts_per_agent(findings)
    if per_agent:
        lines += [
            "## Files with defects per agent",
            "",
            "| Agent | Files | Findings |",
            "|---|---|---|",
        ]
        lines += [f"| {a} | {nf} | {n} |" for a, (nf, n) in per_agent.items()]
        lines.append("")
    for title, items in (("Blocking", cls.blocking), ("Known (baseline)", cls.known)):
        lines += [f"## {title}", ""]
        if not items:
            lines += ["None.", ""]
            continue
        lines += ["| File | Code | Message |", "|---|---|---|"]
        lines += [f"| `{f.path}` | {f.code} | {f.message.replace('|', '/')} |" for f in items]
        lines.append("")
    if cls.fixed_baseline_keys:
        lines += ["## Baseline entries no longer found (remove them with --update-baseline)", ""]
        lines += [f"- `{k}`" for k in cls.fixed_baseline_keys]
        lines.append("")
    return "\n".join(lines)
