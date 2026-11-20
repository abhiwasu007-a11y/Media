"""Worker rows for the runner: one registered ``workers`` row per resource class, read from the
database (the worker pool of 3C registers them; the run entry point never invents one)."""

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Any

from amw_core.enums import Capability, ResourceClass
from amw_core.errors import MissingDependencyError
from amw_core.ids import WORKER, WorkerId

ConnectionFactory = Callable[[], AbstractContextManager[Any]]

_QUERY = (
    "SELECT id, resource_classes, capabilities FROM workers"
    " WHERE status = ANY(%s) AND %s = ANY(resource_classes) AND starts_with(logical_name, %s)"
    " ORDER BY logical_name LIMIT 1"
)


def read_workers(
    connections: ConnectionFactory,
    classes: Sequence[ResourceClass],
    statuses: Sequence[str],
    name_prefix: str = "",
) -> tuple[Mapping[ResourceClass, WorkerId], tuple[Capability, ...]]:
    """The worker per resource class and the union of their capabilities; a class without a live
    row is ``MISSING_DEPENDENCY`` naming the classes (fail closed)."""
    found: dict[ResourceClass, WorkerId] = {}
    capabilities: set[Capability] = set()
    with connections() as conn:
        for rc in classes:
            row = conn.execute(_QUERY, (list(statuses), rc.value, name_prefix)).fetchone()
            if row is None:
                continue
            found[rc] = WORKER.from_uuid(row[0])
            capabilities.update(Capability(c) for c in row[2])
    missing = sorted(rc.value for rc in classes if rc not in found)
    if missing:
        raise MissingDependencyError(
            "no registered worker row for a resource class",
            details={"resource_classes": missing},
        )
    return found, tuple(sorted(capabilities, key=lambda c: c.value))
