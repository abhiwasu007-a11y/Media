"""PromptRenderer (F-12): prompt file + rule packs + one data block between markers."""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from agent_09_video_director.contracts import DirectionInput
from amw_core.errors import ConfigInvalidError

PROMPT_ID = "agent_09/shot_direction.v1"
_PACK = re.compile(r"\{\{rule_pack:(rp\.[a-z0-9_]+)\}\}")
_BEGIN, _END = "<<<INPUT", "INPUT>>>"
TENANT_PACK = "rp.tenant_brand_safety"


class PromptStore(Protocol):
    def get(self, prompt_id: str) -> str: ...


class FilePromptStore:
    """Reads the released prompt file (tests and the eval gate); the worker injects its own."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def get(self, prompt_id: str) -> str:
        if prompt_id != PROMPT_ID:
            raise ConfigInvalidError(f"unknown prompt {prompt_id}")
        return self._path.read_text(encoding="utf-8")


@dataclass(frozen=True, slots=True)
class RenderedPrompt:
    system: str
    user: str
    prompt_sha256: str


def _escape(text: str) -> str:
    return text.replace(_BEGIN, "<<< INPUT").replace(_END, "INPUT >>>")


def render_prompt(
    prompt_text: str, batch: DirectionInput, packs: Mapping[str, str]
) -> RenderedPrompt:
    """System = Role..Self-check with platform rule packs (cacheable prefix, no tenant data);
    user = tenant-scope pack text (after the cache breakpoint) + the data block."""
    start = prompt_text.find("## Role")
    end = prompt_text.find("## A. Input payload schema")
    if start < 0 or end < 0:
        raise ConfigInvalidError("prompt file has no Role / schema sections")
    body = prompt_text[start:end]

    required = {"rp.youtube_general"}
    if batch.channel_category == "finance":
        required.add("rp.finance_sebi_in")
    missing = sorted(n for n in required if n in _PACK.findall(body) and not packs.get(n))
    if missing:  # fail closed: a missing compliance pack never renders as empty text
        raise ConfigInvalidError("required rule pack missing", details={"missing": missing})

    def pack(m: re.Match[str]) -> str:
        name = m.group(1)
        return "" if name == TENANT_PACK else packs.get(name, "")

    body = _PACK.sub(pack, body)
    body = body.replace("{{limits.max_intent_chars}}", str(batch.limits.max_intent_chars))
    body = body.replace("{{limits.max_rationale_chars}}", str(batch.limits.max_rationale_chars))
    data = json.loads(batch.model_dump_json())
    payload = _escape(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1))
    tenant = packs.get(TENANT_PACK, "")
    user = (f"Tenant rules (data):\n{_escape(tenant)}\n\n" if tenant else "") + (
        f"{_BEGIN}\n{payload}\n{_END}"
    )
    return RenderedPrompt(
        system=body.strip(),
        user=user,
        prompt_sha256=hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
    )
