"""Copy every JSON Schema block of 03 and 24 into the contracts registry folder (single copy).

Run ``uv run python -m scripts.extract_schemas`` after a contract change; the contract tests fail
if a document block and its shipped file differ.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("docs/v4/03_COMMUNICATION_STANDARD.md", "docs/v4/24_PRODUCTION_TYPES.md")
OUT = ROOT / "packages/amw_core/src/amw_core/contracts/schemas"
ID_RE = re.compile(r"urn:amw:schema:([a-z_.]+):(\d+\.\d+\.\d+)")


def main() -> int:
    for source in SOURCES:
        text = (ROOT / source).read_text(encoding="utf-8")
        for block in re.findall(r"```json\n(.*?)```", text, re.S):
            doc = json.loads(block)
            match = ID_RE.fullmatch(str(doc.get("$id", "")))
            if match is None:
                continue
            path = OUT / match[1] / f"{match[2]}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            sys.stdout.write(f"{source} -> {path.relative_to(ROOT)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
