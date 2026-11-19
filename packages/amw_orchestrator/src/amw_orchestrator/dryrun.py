"""``python -m amw_orchestrator.dryrun --topic ... --out <dir>``: the PLUMBING dry run.

PLUMBING TEST - NOT QUALITY. The world of fakes (scripted LLM, tone TTS, code-made graphics)
lives with the throw-away fixtures in ``tests/dryrun`` (it reuses the agents' own test fakes),
so this entry point must run from the repository root. Nothing here is used in production.
"""

import importlib
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    root = Path.cwd()
    if not (root / "tests" / "dryrun" / "cli.py").is_file():
        print("run from the repository root (tests/dryrun is the dry-run world)", file=sys.stderr)
        return 2
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    cli = importlib.import_module("tests.dryrun.cli")
    code: int = cli.main(argv)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
