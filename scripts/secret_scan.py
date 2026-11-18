"""Blocking CI gate: fail if a tracked file looks like it contains a secret.

Deliberately simple and dependency-free. It is a second line of defence: real keys must only ever
come through the environment's secret mechanism and never appear in git, logs or shared variables.
"""

import re
import subprocess
import sys
from pathlib import Path

PATTERNS: dict[str, re.Pattern[str]] = {
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    "anthropic key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "generic sk- key": re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
    "github token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "google api key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "aws access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "assigned secret": re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password)\b\s*[:=]\s*[\"'][A-Za-z0-9/+_=-]{24,}[\"']"
    ),
}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".woff", ".woff2", ".ico"}
SELF = Path(__file__).name


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],  # noqa: S607
        check=True,
        capture_output=True,
        text=False,
    ).stdout
    return [Path(p.decode()) for p in out.split(b"\0") if p]


def scan(path: Path) -> list[str]:
    if path.suffix.lower() in SKIP_SUFFIXES or path.name == SELF or not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    hits: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for label, pattern in PATTERNS.items():
            if pattern.search(line):
                hits.append(f"{path}:{lineno}: {label}")
    return hits


def main() -> int:
    findings = [hit for p in tracked_files() for hit in scan(p)]
    for hit in findings:
        print(hit, file=sys.stderr)
    if findings:
        print(f"secret scan FAILED: {len(findings)} finding(s)", file=sys.stderr)
        return 1
    print("secret scan passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
