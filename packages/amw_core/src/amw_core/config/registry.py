"""Config key registry (18 section 13, CCR-019 / CCR-020).

Shared namespaces belong to ``amw_core``; each agent owns ``agent_NN.*`` and the namespaces its
blueprint section 24 declares. A key declared twice is refused, whoever declares it.
"""

import re
from collections.abc import Iterable, Mapping
from types import MappingProxyType

from amw_core.errors import ConfigInvalidError

SHARED_NAMESPACES: frozenset[str] = frozenset(
    {
        "contracts",
        "limits",
        "retry",
        "breaker",
        "quality",
        "qc",
        "compliance",
        "memory",
        "assets",
        "llm",
    }
)
"""18 section 13: the shared namespaces (owned by ``amw_core``)."""

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_<>-]+)+$")
_AGENT_NS_RE = re.compile(r"^agent_(0[1-9]|1[0-7])$")
CORE_OWNER = "amw_core"


class ConfigKeyRegistry:
    """Registry of declared config keys and their owners (``amw_core`` or an executor ID)."""

    def __init__(self) -> None:
        self._keys: dict[str, str] = {}
        self._extra_namespaces: dict[str, str] = {}

    def allow_namespace(self, namespace: str, owner: str) -> None:
        """A blueprint-declared extra namespace (18 section 13: "any other namespace its
        blueprint section 24 declares"); a namespace has exactly one owner."""
        if namespace in SHARED_NAMESPACES or _AGENT_NS_RE.fullmatch(namespace):
            raise ConfigInvalidError(f"namespace {namespace!r} is reserved")
        current = self._extra_namespaces.get(namespace)
        if current is not None and current != owner:
            raise ConfigInvalidError(f"namespace {namespace!r} already owned by {current}")
        self._extra_namespaces[namespace] = owner

    def _may_declare(self, namespace: str, owner: str) -> bool:
        if namespace in SHARED_NAMESPACES:
            return owner == CORE_OWNER or namespace == "llm"
        if _AGENT_NS_RE.fullmatch(namespace):
            return owner == namespace
        return self._extra_namespaces.get(namespace) == owner or owner == CORE_OWNER

    def declare(self, key: str, owner: str) -> None:
        if not _KEY_RE.fullmatch(key):
            raise ConfigInvalidError(f"malformed config key {key!r}")
        namespace = key.split(".", 1)[0]
        if not self._may_declare(namespace, owner):
            raise ConfigInvalidError(f"{owner} may not declare {key!r} (namespace {namespace})")
        if key in self._keys:
            raise ConfigInvalidError(f"config key {key!r} declared twice")
        self._keys[key] = owner

    def declare_all(self, keys: Iterable[str], owner: str) -> None:
        for key in keys:
            self.declare(key, owner)

    @property
    def keys(self) -> Mapping[str, str]:
        return MappingProxyType(self._keys)
