"""Read the machine-checkable thresholds from a dataset README (the 'Pass thresholds' table)."""

import re
from dataclasses import dataclass
from pathlib import Path

PCT100 = re.compile(r"\*\*\s*100\s*%\s*\*\*|\b100\s*%")
GE = re.compile(r"≥\s*([0-9]*\.?[0-9]+)")


@dataclass(frozen=True)
class Thresholds:
    overall_pass_rate: float | None = None
    answer_key_pass_rate: float | None = None
    source: str = ""


def parse_thresholds(readme: Path) -> Thresholds:
    """Recognises 'Overall case pass rate' / 'Pass rate' and 'Answer-key cases passing' rows.

    Other threshold rows (judge means, per-step safety counts) are step-specific and are not
    evaluated here; the runner reports them as not machine-evaluated.
    """
    if not readme.is_file():
        return Thresholds()
    overall: float | None = None
    answer_key: float | None = None
    for line in readme.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        label, value = cells[0].lower(), "|".join(cells[1:])
        if "answer-key cases passing" in label:
            answer_key = 1.0 if PCT100.search(value) else answer_key
        elif label.startswith(("overall case pass rate", "pass rate")):
            if PCT100.search(value):
                overall = 1.0
            else:
                m = GE.search(value)
                if m:
                    overall = float(m.group(1))
    return Thresholds(overall, answer_key, readme.as_posix())
