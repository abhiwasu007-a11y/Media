"""Fail on an unregistered pytest marker or a missing required one.

Required markers: docs/v4/27_ENGINEERING_STANDARDS.md section 3.
"""

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = {
    "unit",
    "contract",
    "integration",
    "e2e",
    "failure_injection",
    "security",
    "performance",
    "tenancy",
    "live",
    "state_machine",
}
BUILTIN = {
    "parametrize",
    "skip",
    "skipif",
    "xfail",
    "usefixtures",
    "filterwarnings",
    "asyncio",
    "anyio",
}
USED = re.compile(r"pytest\.mark\.([A-Za-z_][A-Za-z0-9_]*)")


def registered(pyproject: Path) -> set[str]:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    lines = data["tool"]["pytest"]["ini_options"]["markers"]
    return {line.split(":", 1)[0].split("(", 1)[0].strip() for line in lines}


def used_markers(root: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*.py")):
        if ".venv" in path.parts or "node_modules" in path.parts:
            continue
        for name in USED.findall(path.read_text(encoding="utf-8")):
            found.setdefault(name, []).append(str(path.relative_to(root)))
    return found


def check(root: Path) -> list[str]:
    reg = registered(root / "pyproject.toml")
    problems = [f"required marker not registered: {m}" for m in sorted(REQUIRED - reg)]
    for name, files in used_markers(root).items():
        if name not in reg and name not in BUILTIN:
            problems.append(f"marker used but not registered: {name} ({files[0]})")
    return problems


def main() -> int:
    problems = check(ROOT)
    for p in problems:
        print(p, file=sys.stderr)
    if problems:
        return 1
    print("markers registered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
