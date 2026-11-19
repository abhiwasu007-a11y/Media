"""Approval review codes (04 section 5.16 ``approvals.review_code``; CCR-090).

Format: ``approvals.review_code.length`` characters (default 4, owner-confirmable, Q-O11) from
``23456789ABCDEFGHJKMNPQRSTUVWXYZ`` (no ``0``, ``1``, ``I``, ``L``, ``O``), at least one letter
and one digit; unique per org (``UNIQUE (org_id, review_code)``), regenerated on collision;
matched case-insensitively. The owner types it in his decision message (03 section 11.6 rule 7).
"""

import secrets
from collections.abc import Callable
from typing import Final

from amw_core.errors import InputInvalidError

ALPHABET: Final = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
DIGITS: Final = frozenset("23456789")
MIN_LENGTH: Final = 4
MAX_LENGTH: Final = 8
"""Bounds the database enforces for an own code (0052); the configured length is 4 (Q-O11)."""
DEFAULT_LENGTH: Final = 4
MAX_ATTEMPTS: Final = 64


def is_valid_review_code(code: str, length: int = DEFAULT_LENGTH) -> bool:
    """True for a well-formed code in any letter case (matching is case-insensitive)."""
    upper = code.upper()
    return (
        len(upper) == length
        and all(c in ALPHABET for c in upper)
        and any(c in DIGITS for c in upper)
        and any(c not in DIGITS for c in upper)
    )


def canonical_review_code(code: str, length: int = DEFAULT_LENGTH) -> str:
    """The stored (upper-case) form; ``InputInvalidError`` for a malformed code."""
    if not is_valid_review_code(code, length):
        raise InputInvalidError("malformed review code (CCR-090)")
    return code.upper()


def generate_review_code(
    taken: Callable[[str], bool],
    *,
    length: int = DEFAULT_LENGTH,
    choice: Callable[[str], str] = secrets.choice,
) -> str:
    """A fresh code not yet used in the org (``taken(code)`` checks ``UNIQUE (org_id,
    review_code)``); regenerated on collision, ``InputInvalidError`` after ``MAX_ATTEMPTS``."""
    if length < 2:
        raise InputInvalidError("a review code needs at least one letter and one digit")
    for _ in range(MAX_ATTEMPTS):
        code = "".join(choice(ALPHABET) for _ in range(length))
        if is_valid_review_code(code, length) and not taken(code):
            return code
    raise InputInvalidError("could not generate a free review code")
