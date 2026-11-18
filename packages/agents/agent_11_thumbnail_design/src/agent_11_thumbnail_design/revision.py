"""RevisionPlanner (F-23) and ManifestBuilder (F-22) - pure, blueprint 6.7 and 8.5."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from agent_11_thumbnail_design.models import PreviousConcept


def build_previous(
    prev_variants: Sequence[Mapping[str, Any]],
    texts: Sequence[Mapping[str, Any]],
    pictures: Sequence[Mapping[str, Any]],
    templates: Sequence[str],
    feedback: Sequence[Mapping[str, Any]],
) -> list[PreviousConcept]:
    """Re-map the previous choices to the current option IDs by content (text byte-equal,
    picture by key, template by key); a vanished choice is null and the variant is not kept."""
    named = {str(f["variant_id"]) for f in feedback}
    control_named = "v1" in named
    by_text = {str(t["text"]): str(t["text_id"]) for t in texts}
    by_pic = {(str(p["kind"]), str(p["key"])): str(p["option_id"]) for p in pictures}
    out: list[PreviousConcept] = []
    for v in prev_variants:
        pic = v["picture"]
        pid = by_pic.get((str(pic["kind"]), str(pic["key"])))
        tids = tuple(by_text[str(t["text"])] for t in v["texts"] if str(t["text"]) in by_text)
        tpl = str(v["template_key"]) if str(v["template_key"]) in templates else None
        vanished = pid is None or tpl is None or len(tids) != len(v["texts"])
        keep = not (control_named or str(v["variant_id"]) in named or vanished)
        out.append(
            PreviousConcept(
                concept_id=str(v["concept_id"]),
                template_key=tpl,
                subject_option_id=pid,
                text_ids=tids,
                angle=v["angle"],
                hypothesis_kind=v["hypothesis_kind"],
                emphasis_style=v["emphasis_style"],
                accent_role=v["accent_role"],
                keep=keep,
            )
        )
    return out


def canonical_json(doc: Mapping[str, Any]) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def set_sha256(manifest_without_hash: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(manifest_without_hash)).hexdigest()
