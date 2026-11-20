"""Hash-pinned prompt files for the production workers (27 section 4: the files are the single
source; a released version is immutable).

``data/prompt_registry.json`` pins the SHA-256 of every released prompt file by prompt ID
(``<agent_id>/<task>.v<N>``). A file that is missing, or whose bytes differ from the pin, is
``CONFIG_INVALID`` before any model call: changing a prompt is a new version file plus a new pin
(and the eval gate), never an edit in place. The directory is run-entry configuration
(``prompts_dir``), resolved against the repository root when relative. Nothing here reads the
network or a secret."""

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from amw_core.errors import ConfigInvalidError

REGISTRY_FILE: Final = Path(__file__).parent / "data" / "prompt_registry.json"
_ID: Final = re.compile(r"^(agent_[0-9]{2})/([a-z][a-z0-9_]*\.v[0-9]+)$")
_SHA: Final = re.compile(r"^[0-9a-f]{64}$")


def load_prompt_registry(path: Path | None = None) -> Mapping[str, str]:
    """``{prompt_id: sha256 of the file bytes}`` of the packaged pin file."""
    file = path or REGISTRY_FILE
    try:
        doc = json.loads(file.read_text(encoding="utf-8"))
        pins = doc["prompts"]
        if not isinstance(pins, dict) or not pins:
            raise ValueError("no pins")
        for key, value in pins.items():
            if not _ID.match(key) or not isinstance(value, str) or not _SHA.match(value):
                raise ValueError("bad pin")
    except OSError, ValueError, KeyError, TypeError:
        raise ConfigInvalidError(
            "the prompt registry is missing or invalid", details={"file": file.name}
        ) from None
    return dict(pins)


def repo_root() -> Path | None:
    """The checkout that holds ``docs/v4/prompts`` (None when this is not a checkout)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "docs" / "v4" / "prompts").is_dir():
            return parent
    return None


def resolve_prompts_dir(configured: str) -> Path | None:
    """``prompts_dir`` of the run entry settings: absolute as given, relative to the repo root;
    ``None`` when it does not exist (the port is then unwired, never guessed)."""
    path = Path(configured)
    if not path.is_absolute():
        root = repo_root()
        if root is None:
            return None
        path = root / path
    return path if path.is_dir() else None


class PinnedPrompts:
    """Reads prompt files of ``root`` and verifies each against its pin."""

    def __init__(self, root: Path, registry: Mapping[str, str]) -> None:
        self.root = root
        self.registry = dict(registry)

    def path(self, prompt_id: str) -> Path:
        match = _ID.match(prompt_id)
        if match is None or prompt_id not in self.registry:
            raise ConfigInvalidError("unknown prompt", details={"prompt": prompt_id[:64]})
        directories = sorted(self.root.glob(f"{match.group(1)}_*"))
        if len(directories) != 1:
            raise ConfigInvalidError("prompt directory missing", details={"prompt": prompt_id})
        return directories[0] / f"{match.group(2)}.md"

    def raw(self, prompt_id: str) -> bytes:
        path = self.path(prompt_id)
        try:
            data = path.read_bytes()
        except OSError:
            raise ConfigInvalidError("prompt file missing", details={"prompt": prompt_id}) from None
        if hashlib.sha256(data).hexdigest() != self.registry[prompt_id]:
            raise ConfigInvalidError(
                "prompt file does not match its pinned hash", details={"prompt": prompt_id}
            )
        return data

    def text(self, prompt_id: str) -> str:
        return self.raw(prompt_id).decode("utf-8")

    def sha256(self, prompt_id: str) -> str:
        return self.registry[prompt_id]

    def verify_all(self) -> None:
        """Every pinned file exists and matches (a deployment check, no model call)."""
        for prompt_id in sorted(self.registry):
            self.raw(prompt_id)


def compute_registry(root: Path) -> dict[str, str]:
    """The pins of every released prompt file under ``root`` (used to (re)generate the data file
    and by the drift test)."""
    pins: dict[str, str] = {}
    for file in sorted(root.glob("agent_[0-9][0-9]_*/*.md")):
        agent = "_".join(file.parent.name.split("_")[:2])
        pins[f"{agent}/{file.name.removesuffix('.md')}"] = hashlib.sha256(
            file.read_bytes()
        ).hexdigest()
    return pins


class PromptTextStore:
    """``PromptStore.get`` of agent_09 over the pinned files."""

    def __init__(self, prompts: PinnedPrompts) -> None:
        self._prompts = prompts

    def get(self, prompt_id: str) -> str:
        return self._prompts.text(prompt_id)
