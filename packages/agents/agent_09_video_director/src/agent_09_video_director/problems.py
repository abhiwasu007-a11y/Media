"""Typed failures of agent_09 mapped to the 07 section 2 codes (blueprint 18)."""

from collections.abc import Sequence

from amw_core.contracts.error import violation
from amw_core.errors import InputInvalidError, LoopCapExceededError


def input_invalid(code: str, *, extra: Sequence[str] = (), path: str = "") -> InputInvalidError:
    """``PERMANENT.INPUT_INVALID`` with ``details.violations`` (no content, IDs only).

    Every item is ``{path, keyword, message}`` (03 section 6 rule 6, CCR-210): the payload-local
    reason code is the ``keyword``; ``path`` is a JSON Pointer or ``""``.
    """
    return InputInvalidError(
        f"input invalid: {code}",
        details={"violations": [violation(c, path if c == code else "") for c in (code, *extra)]},
    )


def loop_cap(what: str, limit: int) -> LoopCapExceededError:
    return LoopCapExceededError(f"{what} exceeds {limit}", details={"cap": what, "limit": limit})
