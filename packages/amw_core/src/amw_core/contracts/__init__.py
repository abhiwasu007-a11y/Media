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
from amw_core.contracts.owner_topic import CourseChapterPointer, OwnerReference, OwnerTopic
from amw_core.contracts.production_type import (
    Gate,
    ProductionType,
    Stage,
    default_disabled,
    materialise,
    stage_ancestors,
)
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import (
    NextAction,
    OutputRef,
    ResourceUsage,
    TaskOutput,
    ValidationResult,
    gate_failures,
    has_gate_results,
    integrity_failures,
    meets_success_rule_2b,
)
from amw_core.contracts.validation import (
    schema_violations,
    validate_control,
    validate_envelope,
    validate_error,
    validate_owner_topic,
    validate_production_type,
    validate_task_input,
    validate_task_output,
)

__all__ = [
    "AmwModel",
    "ContextRef",
    "ControlCommand",
    "CourseChapterPointer",
    "Envelope",
    "ErrorDetails",
    "ErrorObject",
    "Gate",
    "NextAction",
    "OutputRef",
    "OwnerReference",
    "OwnerTopic",
    "PayloadObject",
    "PayloadRef",
    "ProductionType",
    "ResourceBudget",
    "ResourceUsage",
    "Stage",
    "TaskInput",
    "TaskOutput",
    "ValidationResult",
    "Violation",
    "default_disabled",
    "error_object_from_exception",
    "gate_failures",
    "has_gate_results",
    "integrity_failures",
    "materialise",
    "meets_success_rule_2b",
    "schema_violations",
    "stage_ancestors",
    "storage_uri_owner",
    "validate_control",
    "validate_envelope",
    "validate_error",
    "validate_owner_topic",
    "validate_production_type",
    "validate_task_input",
    "validate_task_output",
]
