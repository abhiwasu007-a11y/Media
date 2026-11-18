"""Typed failures of agent_09 mapped to the 07 section 2 codes (blueprint 18)."""

from collections.abc import Sequence

from amw_core.errors import InputInvalidError, LoopCapExceededError


def input_invalid(code: str, *, extra: Sequence[str] = ()) -> InputInvalidError:
    """``PERMANENT.INPUT_INVALID`` with ``details.violations`` (no content, IDs only)."""
    return InputInvalidError(f"input invalid: {code}", details={"violations": [code, *extra]})


def loop_cap(what: str, limit: int) -> LoopCapExceededError:
    return LoopCapExceededError(f"{what} exceeds {limit}", details={"cap": what, "limit": limit})
