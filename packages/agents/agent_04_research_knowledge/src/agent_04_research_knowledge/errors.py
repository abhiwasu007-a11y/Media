"""Typed exceptions of Agent 04, mapped 1:1 to the 07 section 2 codes (blueprint 18).

The classes are those of ``amw_core.errors`` (one class per code); this module only gives them the
names used in the blueprint and adds the two control-flow results that are *successes* (a topic
verdict inside a pack), which are therefore not ``AmwError`` subclasses.
"""

from dataclasses import dataclass

from amw_core.errors import (
    AuthInvalidError as AuthInvalid,
)
from amw_core.errors import (
    BudgetExhaustedError as BudgetExhausted,
)
from amw_core.errors import (
    CircuitOpenError as CircuitOpen,
)
from amw_core.errors import (
    ConfigInvalidError as ConfigInvalid,
)
from amw_core.errors import (
    CrossTenantRefError as CrossTenantRef,
)
from amw_core.errors import (
    DbTransientError as TransientDb,
)
from amw_core.errors import (
    DiskFullError as DiskFull,
)
from amw_core.errors import (
    IdempotencyConflictError as IdempotencyConflict,
)
from amw_core.errors import (
    InputInvalidError as InputInvalid,
)
from amw_core.errors import (
    InsufficientInputError as InsufficientInput,
)
from amw_core.errors import (
    InvalidJsonError as InvalidJson,
)
from amw_core.errors import (
    LoopCapExceededError as LoopCapExceeded,
)
from amw_core.errors import (
    MissingDependencyError as MissingDependency,
)
from amw_core.errors import (
    OutputSchemaInvalidError as OutputSchemaInvalid,
)
from amw_core.errors import (
    ProviderRefusalError as ProviderRefusal,
)
from amw_core.errors import (
    QualityRepeatedFailureError as QualityRepeatedFailure,
)
from amw_core.errors import (
    RateLimitedError as RateLimited,
)
from amw_core.errors import (
    StorageUnavailableError as StorageUnavailable,
)
from amw_core.errors import (
    TenantInactiveError as TenantInactive,
)
from amw_core.errors import (
    TenantMismatchError as TenantMismatch,
)


@dataclass(frozen=True, slots=True)
class TopicBlocked(Exception):  # noqa: N818 - a result, not an error (27 section 4.3)
    """Plan refusal ``RULE_WOULD_BE_BROKEN``: the task still SUCCEEDS with verdict BLOCKED."""

    rule_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TopicNeedsReview(Exception):  # noqa: N818 - a result, not an error (27 section 4.3)
    """Plan refusal ``UNSAFE_CONTENT``: the task SUCCEEDS with verdict NEEDS_HUMAN_REVIEW."""

    rule_ids: tuple[str, ...]


__all__ = [
    "AuthInvalid",
    "BudgetExhausted",
    "CircuitOpen",
    "ConfigInvalid",
    "CrossTenantRef",
    "DiskFull",
    "IdempotencyConflict",
    "InputInvalid",
    "InsufficientInput",
    "InvalidJson",
    "LoopCapExceeded",
    "MissingDependency",
    "OutputSchemaInvalid",
    "ProviderRefusal",
    "QualityRepeatedFailure",
    "RateLimited",
    "StorageUnavailable",
    "TenantInactive",
    "TenantMismatch",
    "TopicBlocked",
    "TopicNeedsReview",
    "TransientDb",
]
