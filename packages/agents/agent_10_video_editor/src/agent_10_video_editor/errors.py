"""Agent 10 error helpers: typed ``amw_core`` errors with violation lists (blueprint 10 section 18).

No new error code exists: every violation is carried in ``details["violations"]`` of an
``amw_core.errors`` exception (``INPUT_INVALID``, ``MISSING_DEPENDENCY``, ``CONFIG_INVALID`` ...).
``MeasurementUnavailable`` is the internal signal of a missing or unparseable tool measurement
(18 section 7.0.3); it is never ``PASS`` and maps to ``AGENT.CRASH`` or ``RESOURCE.RENDER_CRASH``.
"""

from collections.abc import Sequence

from amw_core.errors import (
    AgentCrashError,
    AmwError,
    ConfigInvalidError,
    InputInvalidError,
    MissingDependencyError,
    RenderCrashError,
)


class MeasurementUnavailable(Exception):  # noqa: N818 - blueprint name (F-18)
    """A tool output is missing a required value or cannot be parsed."""

    def __init__(self, missing: Sequence[str], message: str = "measurement unavailable") -> None:
        super().__init__(message)
        self.missing: tuple[str, ...] = tuple(missing)


def input_invalid(*violations: str) -> InputInvalidError:
    return InputInvalidError("input invalid", details={"violations": list(violations)})


def missing_dependency(*violations: str) -> MissingDependencyError:
    return MissingDependencyError("missing dependency", details={"violations": list(violations)})


def config_invalid(*violations: str) -> ConfigInvalidError:
    return ConfigInvalidError("configuration invalid", details={"violations": list(violations)})


def violations_of(error: AmwError) -> list[str]:
    raw = error.details.get("violations", [])
    return [str(item) for item in raw]


def map_measurement_error(error: MeasurementUnavailable, *, process_died: bool) -> AmwError:
    """18 section 7.0.3 / blueprint section 18: never ``PASS``; died process is a render crash."""
    details = {"missing": list(error.missing)}
    if process_died:
        return RenderCrashError("measurement process died", details=details)
    return AgentCrashError("measurement unavailable", details=details)
