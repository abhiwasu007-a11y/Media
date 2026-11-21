"""CLI: python -m studio run <job_dir> [from_stage] | python -m studio serve"""

import os
import sys
from pathlib import Path

from . import pipeline


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "run":
        return 0 if pipeline.run(Path(sys.argv[2]).resolve(), sys.argv[3] if len(sys.argv) > 3 else None) else 1
    if len(sys.argv) >= 2 and sys.argv[1] == "serve":
        import uvicorn

        host = os.environ.get("AMW_BIND", "0.0.0.0")  # noqa: S104 - inside the container; compose publishes on loopback only
        # Always 8080 inside the container. AMW_PORT only picks the host port in compose.yaml.
        uvicorn.run("studio.web:app", host=host, port=int(os.environ.get("AMW_INTERNAL_PORT", "8080")))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
