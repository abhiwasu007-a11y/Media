"""A provider key referenced by its secret NAME (docs/v4/runtime/SECRETS.md, 08 section 3.1).

The value is read, at the moment of the call, from the environment mapping the wiring code
passes (only workers and scripts touch ``os.environ``; amw_core.config rule) and placed only in
the outgoing request header. It is never stored on the adapter, logged, printed or put in an
error; ``repr`` shows the name only.
"""

import re
from collections.abc import Mapping

from amw_core.errors import ConfigInvalidError

SECRET_NAME = re.compile(r"^AMW_SECRET_[A-Z0-9]+(_[A-Z0-9]+)*_API_KEY$")


class SecretRef:
    __slots__ = ("_env", "name")

    def __init__(self, name: str, env: Mapping[str, str]) -> None:
        if not SECRET_NAME.match(name):
            raise ConfigInvalidError("secret name must look like AMW_SECRET_<PROVIDER>_API_KEY")
        self.name = name
        self._env = env

    def present(self) -> bool:
        return bool(self._env.get(self.name))

    def reveal(self) -> str:
        """The value, for the request header only. Missing -> ``CONFIG_INVALID`` naming the
        secret name (never a value, a length or a prefix)."""
        value = self._env.get(self.name)
        if not value:
            raise ConfigInvalidError("required secret is not set", details={"name": self.name})
        return value

    def __repr__(self) -> str:
        return f"SecretRef({self.name!r})"
