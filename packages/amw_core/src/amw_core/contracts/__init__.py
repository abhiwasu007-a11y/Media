"""Wave A contracts (03 sections 2-6): JSON Schemas 2020-12 + Pydantic v2 models + validators."""

from amw_core.contracts.common import (
    AmwModel,
    ContextRef,
    PayloadObject,
    ResourceBudget,
    storage_uri_owner,
)
from amw_core.contracts.control import ControlCommand
from amw_core.contracts.envelope import Envelope, PayloadRef
from amw_core.contracts.error import (
    ErrorDetails,
    ErrorObject,
    Violation,
    error_object_from_exception,
)
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import (
    NextAction,
    OutputRef,
    ResourceUsage,
    TaskOutput,
    ValidationResult,
)
from amw_core.contracts.validation import (
    schema_violations,
    validate_control,
    validate_envelope,
    validate_error,
    validate_task_input,
    validate_task_output,
)

__all__ = [
    "AmwModel",
    "ContextRef",
    "ControlCommand",
    "Envelope",
    "ErrorDetails",
    "ErrorObject",
    "NextAction",
    "OutputRef",
    "PayloadObject",
    "PayloadRef",
    "ResourceBudget",
    "ResourceUsage",
    "TaskInput",
    "TaskOutput",
    "ValidationResult",
    "Violation",
    "error_object_from_exception",
    "schema_violations",
    "storage_uri_owner",
    "validate_control",
    "validate_envelope",
    "validate_error",
    "validate_task_input",
    "validate_task_output",
]
