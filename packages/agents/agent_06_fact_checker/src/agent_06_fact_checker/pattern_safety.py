"""Load-time safety check of configured regular expressions (catastrophic backtracking).

The guard patterns are trusted configuration, but a pattern that backtracks exponentially would
stall the task on a 2000-character claim (measured: ``(a+)+$`` took 30 s on 29 characters). The
stdlib ``re`` has no timeout, so a pattern is validated BEFORE use and rejected when it

* is longer than ``max_length`` characters,
* uses a back-reference or a conditional,
* repeats more than ``max_repeat`` times (a finite upper bound above the limit), or
* has a repeat (upper bound above 1) whose body holds another such repeat or an alternation
  (nested quantifier: ``(a+)+``, ``(a*)*``, ``(a|a)*``).

The check reads the parse tree of the interpreter (``re._parser``, a private module: any change
that makes it unavailable is a configuration error, never a silent pass)."""

import importlib
import re
from collections.abc import Iterable
from typing import Any

from amw_core.errors import ConfigInvalidError

_REPEATS = frozenset({"MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"})
_REFS = frozenset({"GROUPREF", "GROUPREF_EXISTS"})


def _parse(pattern: str) -> Any:
    try:
        parser = importlib.import_module("re._parser")
        constants = importlib.import_module("re._constants")
    except ImportError as exc:
        raise ConfigInvalidError("the regular expression parser is not available") from exc
    return parser.parse(pattern), int(constants.MAXREPEAT)


def _children(op: str, arg: Any) -> Iterable[Any]:
    """Sub-patterns of one parse node."""
    if op == "SUBPATTERN":
        return (arg[3],)
    if op == "BRANCH":
        return tuple(arg[1])
    if op in _REPEATS:
        return (arg[2],)
    if op in ("ASSERT", "ASSERT_NOT"):
        return (arg[1],)
    if op == "ATOMIC_GROUP":
        return (arg,)
    return ()


def _nodes(sub: Any) -> Iterable[tuple[str, Any]]:
    for op, arg in sub.data:
        yield str(op), arg
        for child in _children(str(op), arg):
            yield from _nodes(child)


def _repeats_or_branches(sub: Any, unbounded: int) -> bool:
    for op, arg in _nodes(sub):
        if op == "BRANCH" and len(arg[1]) > 1:
            return True
        if op in _REPEATS and int(arg[1]) > 1:
            return True
    return False


def validate_pattern(pattern: str, *, max_length: int, max_repeat: int) -> None:
    """Raise ``ConfigInvalidError`` for an invalid or unsafe pattern."""
    if len(pattern) > max_length:
        raise ConfigInvalidError(
            "pattern is longer than the configured limit",
            details={"pattern": pattern[:40], "max_length": max_length},
        )
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ConfigInvalidError(
            "invalid regular expression", details={"pattern": pattern, "error": str(exc)}
        ) from exc
    tree, unbounded = _parse(pattern)
    for op, arg in _nodes(tree):
        if op in _REFS or op == "CONDITIONAL":
            raise ConfigInvalidError(
                "back-references and conditionals are not allowed", details={"pattern": pattern}
            )
        if op in _REPEATS:
            high = int(arg[1])
            if high != unbounded and high > max_repeat:
                raise ConfigInvalidError(
                    "repeat bound above the configured limit",
                    details={"pattern": pattern, "max_repeat": max_repeat},
                )
            if high > 1 and _repeats_or_branches(arg[2], unbounded):
                raise ConfigInvalidError(
                    "nested quantifier (catastrophic backtracking) is not allowed",
                    details={"pattern": pattern},
                )
