# mypy: disable-error-code="arg-type,attr-defined,misc,has-type,no-untyped-def,no-any-return"
# mypy: disable-error-code="assignment,union-attr,index,call-arg"
# (test helpers feed dataset dicts and fakes into typed APIs; the package is strict clean)
"""Extract the JSON Schemas embedded in the blueprint (the contract lives in the document)."""

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

DOC = Path(__file__).resolve().parents[3] / "docs/v4/agents/agent_08_visual_assets.md"


@cache
def all_blocks() -> dict[str, Any]:
    found: dict[str, Any] = {}
    for m in re.finditer(r"```json\n(.*?)\n```", DOC.read_text(), re.S):
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(d, dict) and "$id" in d:
            found[d["$id"]] = d
    return found


def output_schema() -> dict[str, Any]:
    return all_blocks()["urn:amw:schema:agent_08.asset_sourcing.output:1.0.0"]


def facts_schema() -> dict[str, Any]:
    return all_blocks()["urn:amw:schema:agent_08.chart_facts:1.0.0"]
