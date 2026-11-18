"""Prompt loading and rendering (27 4; blueprint 5).

The prompt file is the source of truth. The loader verifies its SHA-256 against the registry
(mismatch is ``PERMANENT.CONFIG_INVALID``), resolves ``{{rule_pack:<key>}}`` from the rule-pack
records, and refuses any variable that the file's Inputs table does not declare. Variables are
*not* substituted into the system prompt: inputs travel as one JSON value in the user message
after the stable, cacheable prefix, and the prompt tells the model that data is content.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from agent_06_fact_checker.hashing import canonical_json, sha256_hex
from agent_06_fact_checker.rulepack import RulePack, RulePackResolver
from amw_core.errors import ConfigInvalidError

_PLACEHOLDER = re.compile(r"\{\{([^{}]+)\}\}")
_INPUT_ROW = re.compile(r"^\|\s*`\{\{([a-z_]+)\}\}`\s*\|", re.MULTILINE)
_START = "## Role"
_END_MARKERS = ("\n---\n\n## A. Input payload schema", "\n## Appendix")


@dataclass(frozen=True, slots=True)
class PromptDoc:
    prompt_id: str
    sha256: str
    system_template: str
    declared_variables: frozenset[str]


@dataclass(frozen=True, slots=True)
class RenderedPrompt:
    prompt_id: str
    sha256: str
    system: str
    rule_pack_versions: Mapping[str, int]


@runtime_checkable
class PromptSource(Protocol):
    def load(self, prompt_id: str) -> PromptDoc: ...


def parse_prompt_doc(prompt_id: str, raw: bytes) -> PromptDoc:
    """Cut the system part (Role .. Self-check) out of a prompt file and index its variables."""
    text = raw.decode("utf-8")
    start = text.find(_START)
    if start < 0:
        raise ConfigInvalidError("prompt file has no Role section", details={"prompt": prompt_id})
    end = len(text)
    for marker in _END_MARKERS:
        pos = text.find(marker, start)
        if pos >= 0:
            end = min(end, pos)
    declared = frozenset(_INPUT_ROW.findall(text))
    return PromptDoc(prompt_id, sha256_hex(raw), text[start:end].strip() + "\n", declared)


class FilePromptSource:
    """Reads ``<root>/<agent dir>/<name>.<ver>.md`` and checks the registered hash."""

    def __init__(self, root: Path, registry_sha256: Mapping[str, str]) -> None:
        self._root = root
        self._registry = dict(registry_sha256)

    def load(self, prompt_id: str) -> PromptDoc:
        agent, name = prompt_id.split("/", 1)
        path = self._root / "agent_06_fact_checker" / f"{name}.md"
        if agent != "agent_06" or not path.is_file():
            raise ConfigInvalidError("unknown prompt", details={"prompt": prompt_id})
        doc = parse_prompt_doc(prompt_id, path.read_bytes())
        if self._registry.get(prompt_id) != doc.sha256:
            raise ConfigInvalidError(
                "prompt hash does not match the registry", details={"prompt": prompt_id}
            )
        return doc


def render_system(
    doc: PromptDoc, resolver: RulePackResolver | None, pack_keys: tuple[str, ...]
) -> RenderedPrompt:
    """Resolve rule packs by reference; ``pack_keys`` are the input's ``active_rule_packs``."""
    packs: dict[str, RulePack] = {}

    def substitute(match: re.Match[str]) -> str:
        token = match.group(1).strip()
        if token.startswith("rule_pack:"):
            key = token.split(":", 1)[1]
            if resolver is None:
                raise ConfigInvalidError("prompt needs rule packs but no resolver is wired")
            if key not in pack_keys and key != "rp.youtube_general":
                return ""  # an inactive pack is not injected (D9: exactly the active packs)
            pack = resolver.resolve(key)
            packs[key] = pack
            return pack.text
        if token not in doc.declared_variables:
            raise ConfigInvalidError(
                "undeclared prompt variable", details={"prompt": doc.prompt_id, "variable": token}
            )
        return match.group(0)  # declared input: supplied in the user message JSON

    system = _PLACEHOLDER.sub(substitute, doc.system_template)
    return RenderedPrompt(
        doc.prompt_id, doc.sha256, system, {k: p.version for k, p in packs.items()}
    )


def user_message(variables: Mapping[str, object]) -> str:
    """Inputs as one JSON object between the markers; everything inside is data."""
    return "<<<INPUT\n" + canonical_json(dict(variables)) + "\nINPUT>>>"
