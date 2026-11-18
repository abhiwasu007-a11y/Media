"""Typed exceptions of Agent 05, one per 07 section 2 code (blueprint section 18).

The classes are the ``amw_core.errors`` classes (one class per catalogue code); this module only
gives them the names of blueprint section 9 and adds the two internal signals that are not errors.
Messages carry codes, IDs and counts only, never narration or brief text (27 section 7.3.6).
"""

from amw_core.errors import (
    BudgetExhaustedError as BudgetExhausted,
)
from amw_core.errors import (
    ConfigInvalidError as ConfigInvalid,
)
from amw_core.errors import (
    CrossTenantRefError as CrossTenantRef,
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
    TenantInactiveError as TenantInactive,
)
from amw_core.errors import (
    TenantMismatchError as TenantMismatch,
)

__all__ = [
    "BudgetExhausted",
    "ConfigInvalid",
    "CrossTenantRef",
    "InputInvalid",
    "InsufficientInput",
    "InvalidJson",
    "LoopCapExceeded",
    "MissingDependency",
    "OutputSchemaInvalid",
    "ProviderRefusal",
    "QualityRepeatedFailure",
    "TenantInactive",
    "TenantMismatch",
]
