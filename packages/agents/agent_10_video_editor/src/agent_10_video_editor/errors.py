"""Agent 10 error helpers: typed ``amw_core`` errors with violation lists (blueprint 10 section 18).

No new error code exists: every violation is carried in ``details["violations"]`` of an
``amw_core.errors`` exception (``INPUT_INVALID``, ``MISSING_DEPENDENCY``, ``CONFIG_INVALID`` ...).
``MeasurementUnavailable`` is the internal signal of a missing or unparseable tool measurement
(18 section 7.0.3); it is never ``PASS`` and maps to ``AGENT.CRASH`` or ``RESOURCE.RENDER_CRASH``.
"""

from collections.abc import Sequence

from amw_core.contracts import Violation, violation
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


def _item(text: str | Violation) -> Violation:
    """One violation item through the core builder (03 section 6 rule 6, CCR-210):
    the reason code (before the first ``:``) is the ``keyword``; the whole text is the message."""
    if isinstance(text, Violation):
        return text
    return violation(text.split(":", 1)[0], "", text)


def _items(violations: Sequence[str | Violation]) -> list[Violation]:
    return [_item(v) for v in violations]


def input_invalid(*violations: str | Violation) -> InputInvalidError:
    return InputInvalidError("input invalid", details={"violations": _items(violations)})


def missing_dependency(*violations: str | Violation) -> MissingDependencyError:
    return MissingDependencyError("missing dependency", details={"violations": _items(violations)})


def config_invalid(*violations: str | Violation) -> ConfigInvalidError:
    return ConfigInvalidError("configuration invalid", details={"violations": _items(violations)})


def violations_of(error: AmwError) -> list[str]:
    """The message of every violation item (the ``CODE:detail`` text this agent builds)."""
    out: list[str] = []
    for item in error.details.get("violations", []):
        if isinstance(item, Violation):
            out.append(item.message)
        elif isinstance(item, dict):
            out.append(str(item.get("message", item.get("keyword", ""))))
        else:
            out.append(str(item))
    return out


def map_measurement_error(error: MeasurementUnavailable, *, process_died: bool) -> AmwError:
    """18 section 7.0.3 / blueprint section 18: never ``PASS``; died process is a render crash."""
    details = {"missing": list(error.missing)}
    if process_died:
        return RenderCrashError("measurement process died", details=details)
    return AgentCrashError("measurement unavailable", details=details)
