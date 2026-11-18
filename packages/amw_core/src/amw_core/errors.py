"""Error code catalogue and typed exceptions (docs/v4/07_FAILURE_MANAGEMENT.md section 2).

``CATALOGUE`` is the 07 section 2 table, one ``ErrorSpec`` per ``<CLASS>.<CODE>``. Every code has
exactly one exception class (27 section 7.3 rule 4: typed exceptions that map 1:1 to the codes);
``tests/test_errors.py`` parses the 07 table and fails on a missing or extra code.

``retryable`` here is the catalogue default; the retry policy engine (``amw_core.retries``, lane L1)
decides per attempt (03 section 6 rule 2). The Error object model lives in
``amw_core.contracts.error``; ``amw_core.contracts.error.error_object_from_exception`` builds it.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar

from amw_core.enums import EscalationLevel, FailureClass, WaitReason


class Disposition(StrEnum):
    """07 section 2 disposition (``SUSPEND:<reason>`` = SUSPEND + ``ErrorSpec.wait_reason``)."""

    RETRY = "RETRY"
    SUSPEND = "SUSPEND"
    FAIL = "FAIL"
    NO_ATTEMPT = "NO-ATTEMPT"


class RetryPolicyName(StrEnum):
    """07 section 3.3 policy names (config ``retry.<policy>.*``)."""

    TEMPORARY = "temporary"
    RATE_LIMITED = "rate_limited"
    DB = "db"
    RESOURCE = "resource"
    AGENT = "agent"
    AGENT_PARSE = "agent_parse"
    INFRA = "infra"
    PUBLISH_RESUME = "publish_resume"


@dataclass(frozen=True, slots=True)
class ErrorSpec:
    """One row of the 07 section 2 catalogue."""

    code: str
    meaning: str
    disposition: Disposition
    retry_policy: RetryPolicyName | None
    breaker_counts: bool
    escalation: EscalationLevel
    wait_reason: WaitReason | None = None

    @property
    def error_class(self) -> FailureClass:
        return FailureClass(self.code.split(".", 1)[0])

    @property
    def retryable(self) -> bool:
        """Catalogue default: RETRY codes, plus NO-ATTEMPT codes that come back (see STEP0 gaps)."""
        return self.disposition is Disposition.RETRY or self.code in _NO_ATTEMPT_RETRYABLE


_NO_ATTEMPT_RETRYABLE = frozenset({"TEMPORARY.LOCK_CONFLICT", "INFRASTRUCTURE.CIRCUIT_OPEN"})

# 07 section 2, one row per code: code | disposition[:wait_reason] | retry policy | breaker counts
# | first escalation level ("L1 -> L2" is L1; the detail stays in 07) | meaning (shortened).
_TABLE = """
TEMPORARY.NETWORK | RETRY | temporary | yes | L1 | connection reset/refused, DNS failure
TEMPORARY.TIMEOUT | RETRY | temporary | yes | L1 | provider or internal call timed out
TEMPORARY.RATE_LIMITED | RETRY | rate_limited | yes | L1 | HTTP 429 or provider rate limit
TEMPORARY.UPSTREAM_5XX | RETRY | temporary | yes | L1 | HTTP 5xx from a provider
TEMPORARY.DB_TRANSIENT | RETRY | db | no | L1 | serialization failure, deadlock, blip
TEMPORARY.LOCK_CONFLICT | NO-ATTEMPT | - | no | L1 | optimistic-lock mismatch on a transition
PERMANENT.SCHEMA_INVALID | FAIL | - | no | L2 | contract or payload failed its schema
PERMANENT.SCHEMA_VERSION_UNSUPPORTED | FAIL | - | no | L2 | version outside the supported set
PERMANENT.INPUT_INVALID | FAIL | - | no | L2 | semantically invalid input
PERMANENT.CONFIG_INVALID | FAIL | - | no | L3 | missing/invalid configuration
PERMANENT.UNSUPPORTED_TASK | FAIL | - | no | L2 | task type not registered for the executor
PERMANENT.MISSING_DEPENDENCY | FAIL | - | no | L2 | referenced row/blob absent
PERMANENT.AUTH_INVALID | FAIL | - | no | L3 | provider credential rejected
PERMANENT.PERMISSION_DENIED | FAIL | - | no | L3 | actor lacks the permission (RBAC)
PERMANENT.TENANT_INACTIVE | FAIL | - | no | L3 | org suspended/offboarding
PERMANENT.TENANT_MISMATCH | FAIL | - | no | L3 | org IDs disagree across messages
PERMANENT.CROSS_TENANT_REF | FAIL | - | no | L3 | a URI/ref of another tenant
PERMANENT.IDEMPOTENCY_CONFLICT | FAIL | - | no | L3 | same key, different request hash
PERMANENT.INVALID_TRANSITION | FAIL | - | no | L2 | state transition not allowed
PERMANENT.DEADLINE_EXCEEDED | FAIL | - | no | L2 | deadline passed or wait timed out
PERMANENT.PROVIDER_REFUSAL | FAIL | - | no | L2 | provider refused the content
PERMANENT.INSUFFICIENT_INPUT | FAIL | - | no | L2 | LLM step refused: INSUFFICIENT_INPUT
RESOURCE.OOM | RETRY | resource | no | L1 | process killed for memory
RESOURCE.CPU_SATURATION | RETRY | resource | no | L1 | task aborted under CPU pressure
RESOURCE.DISK_FULL | SUSPEND:OPERATOR_PAUSE | - | no | L3 | write failed: no space
RESOURCE.RENDER_CRASH | RETRY | resource | no | L1 | FFmpeg exited abnormally
RESOURCE.BUDGET_EXHAUSTED | SUSPEND:AWAITING_BUDGET | - | no | L3 | S4 refused the spend
AGENT.CRASH | RETRY | agent | no | L1 | unhandled exception in stage code
AGENT.HANG | RETRY | agent | no | L1 | heartbeat stale / wall budget exceeded
AGENT.INVALID_JSON | RETRY | agent_parse | no | L2 | LLM output not parseable
AGENT.OUTPUT_SCHEMA_INVALID | RETRY | agent_parse | no | L2 | parsed output fails its schema
AGENT.CORRUPTED_OUTPUT | RETRY | agent | no | L2 | output blob hash/size mismatch
AGENT.INCOMPLETE_OUTPUT | RETRY | agent_parse | no | L2 | success claimed, 03 5.3 rule failed
AGENT.QUALITY_REPEATED_FAILURE | FAIL | - | no | L3 | own checks failed on every attempt
AGENT.LOOP_CAP_EXCEEDED | FAIL | - | no | L3 | a hard cap of 07 section 9 reached
INFRASTRUCTURE.HOST_RESTART | RETRY | infra | no | L1 | host or container restarted
INFRASTRUCTURE.DB_UNAVAILABLE | RETRY | infra | no | L1 | database unreachable
INFRASTRUCTURE.QUEUE_UNAVAILABLE | RETRY | infra | no | L1 | queue functions unavailable
INFRASTRUCTURE.STORAGE_UNAVAILABLE | RETRY | infra | no | L1 | storage backend unreachable
INFRASTRUCTURE.NETWORK_OUTAGE | RETRY | infra | yes | L1 | all outbound calls failing
INFRASTRUCTURE.CIRCUIT_OPEN | NO-ATTEMPT | - | no | L1 | breaker for the provider is OPEN
INFRASTRUCTURE.WORKER_LOST | RETRY | infra | no | L1 | lease expired, heartbeat stale
PUBLISHING.UPLOAD_INTERRUPTED | RETRY | publish_resume | no | L1 | resumable upload broke
PUBLISHING.UPLOAD_REJECTED | FAIL | - | no | L3 | destination rejected file/metadata
PUBLISHING.QUOTA_EXHAUSTED | SUSPEND:AWAITING_QUOTA | - | no | L1 | quota bucket used up (PT day)
PUBLISHING.OAUTH_REVOKED | FAIL | - | no | L3 | token revoked by the channel owner
PUBLISHING.OAUTH_REFRESH_FAILED | RETRY | temporary | yes | L3 | refresh failed (not revocation)
PUBLISHING.PROCESSING_FAILED | FAIL | - | no | L3 | destination processing failed
PUBLISHING.VERIFICATION_MISMATCH | FAIL | - | no | L3 | post-publish read-back differs
PUBLISHING.DUPLICATE_DETECTED | FAIL | - | no | L3 | already uploaded and inconsistent
PUBLISHING.NOT_AUTHORISED | FAIL | - | no | L3 | publish guard failed
PUBLISHING.DESTINATION_UNAVAILABLE | RETRY | temporary | yes | L1 | destination 5xx/outage
"""


def _parse_row(line: str) -> ErrorSpec:
    code, disposition, policy, breaker, escalation, meaning = (c.strip() for c in line.split("|"))
    kind, _, wait = disposition.partition(":")
    return ErrorSpec(
        code=code,
        meaning=meaning,
        disposition=Disposition(kind),
        retry_policy=None if policy == "-" else RetryPolicyName(policy),
        breaker_counts=breaker == "yes",
        escalation=EscalationLevel(escalation),
        wait_reason=WaitReason(wait) if wait else None,
    )


CATALOGUE: Mapping[str, ErrorSpec] = MappingProxyType(
    {spec.code: spec for spec in map(_parse_row, _TABLE.strip().splitlines())}
)


class AmwError(Exception):
    """Base of every typed factory error. Subclasses fix ``code``; ``spec`` is its catalogue row."""

    code: ClassVar[str] = ""
    registry: ClassVar[dict[str, type[AmwError]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.code:
            if cls.code not in CATALOGUE:
                raise TypeError(f"{cls.__name__}: code {cls.code!r} is not in 07 section 2")
            if cls.code in AmwError.registry:
                raise TypeError(f"duplicate exception class for {cls.code}")
            AmwError.registry[cls.code] = cls

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
        retry_after_ms: int | None = None,
        provider: str | None = None,
        upstream_status: int | None = None,
        upstream_code: str | None = None,
    ) -> None:
        if not type(self).code:
            raise TypeError("instantiate a concrete error class (one per 07 code)")
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = dict(details or {})
        self.retry_after_ms = retry_after_ms
        self.provider = provider
        self.upstream_status = upstream_status
        self.upstream_code = upstream_code

    @property
    def spec(self) -> ErrorSpec:
        return CATALOGUE[type(self).code]

    @property
    def error_class(self) -> FailureClass:
        return self.spec.error_class

    @property
    def retryable(self) -> bool:
        return self.spec.retryable

    @classmethod
    def for_code(cls, code: str) -> type[AmwError]:
        """Exception class of a catalogue code; ``KeyError`` for an unknown code."""
        return AmwError.registry[code]


class TemporaryError(AmwError):
    pass


class PermanentError(AmwError):
    pass


class ResourceError(AmwError):
    pass


class AgentError(AmwError):
    pass


class InfrastructureError(AmwError):
    pass


class PublishingError(AmwError):
    pass


# --- TEMPORARY ---
class NetworkError(TemporaryError):
    code = "TEMPORARY.NETWORK"


class CallTimeoutError(TemporaryError):
    code = "TEMPORARY.TIMEOUT"


class RateLimitedError(TemporaryError):
    code = "TEMPORARY.RATE_LIMITED"


class Upstream5xxError(TemporaryError):
    code = "TEMPORARY.UPSTREAM_5XX"


class DbTransientError(TemporaryError):
    code = "TEMPORARY.DB_TRANSIENT"


class LockConflictError(TemporaryError):
    code = "TEMPORARY.LOCK_CONFLICT"


# --- PERMANENT ---
class SchemaInvalidError(PermanentError):
    code = "PERMANENT.SCHEMA_INVALID"


class SchemaVersionUnsupportedError(PermanentError):
    code = "PERMANENT.SCHEMA_VERSION_UNSUPPORTED"


class InputInvalidError(PermanentError):
    code = "PERMANENT.INPUT_INVALID"


class ConfigInvalidError(PermanentError):
    code = "PERMANENT.CONFIG_INVALID"


class UnsupportedTaskError(PermanentError):
    code = "PERMANENT.UNSUPPORTED_TASK"


class MissingDependencyError(PermanentError):
    code = "PERMANENT.MISSING_DEPENDENCY"


class AuthInvalidError(PermanentError):
    code = "PERMANENT.AUTH_INVALID"


class PermissionDeniedError(PermanentError):
    code = "PERMANENT.PERMISSION_DENIED"


class TenantInactiveError(PermanentError):
    code = "PERMANENT.TENANT_INACTIVE"


class TenantMismatchError(PermanentError):
    code = "PERMANENT.TENANT_MISMATCH"


class CrossTenantRefError(PermanentError):
    code = "PERMANENT.CROSS_TENANT_REF"


class IdempotencyConflictError(PermanentError):
    code = "PERMANENT.IDEMPOTENCY_CONFLICT"


class InvalidTransitionError(PermanentError):
    code = "PERMANENT.INVALID_TRANSITION"


class DeadlineExceededError(PermanentError):
    code = "PERMANENT.DEADLINE_EXCEEDED"


class ProviderRefusalError(PermanentError):
    code = "PERMANENT.PROVIDER_REFUSAL"


class InsufficientInputError(PermanentError):
    code = "PERMANENT.INSUFFICIENT_INPUT"


# --- RESOURCE ---
class OomError(ResourceError):
    code = "RESOURCE.OOM"


class CpuSaturationError(ResourceError):
    code = "RESOURCE.CPU_SATURATION"


class DiskFullError(ResourceError):
    code = "RESOURCE.DISK_FULL"


class RenderCrashError(ResourceError):
    code = "RESOURCE.RENDER_CRASH"


class BudgetExhaustedError(ResourceError):
    code = "RESOURCE.BUDGET_EXHAUSTED"


# --- AGENT ---
class AgentCrashError(AgentError):
    code = "AGENT.CRASH"


class AgentHangError(AgentError):
    code = "AGENT.HANG"


class InvalidJsonError(AgentError):
    code = "AGENT.INVALID_JSON"


class OutputSchemaInvalidError(AgentError):
    code = "AGENT.OUTPUT_SCHEMA_INVALID"


class CorruptedOutputError(AgentError):
    code = "AGENT.CORRUPTED_OUTPUT"


class IncompleteOutputError(AgentError):
    code = "AGENT.INCOMPLETE_OUTPUT"


class QualityRepeatedFailureError(AgentError):
    code = "AGENT.QUALITY_REPEATED_FAILURE"


class LoopCapExceededError(AgentError):
    code = "AGENT.LOOP_CAP_EXCEEDED"


# --- INFRASTRUCTURE ---
class HostRestartError(InfrastructureError):
    code = "INFRASTRUCTURE.HOST_RESTART"


class DbUnavailableError(InfrastructureError):
    code = "INFRASTRUCTURE.DB_UNAVAILABLE"


class QueueUnavailableError(InfrastructureError):
    code = "INFRASTRUCTURE.QUEUE_UNAVAILABLE"


class StorageUnavailableError(InfrastructureError):
    code = "INFRASTRUCTURE.STORAGE_UNAVAILABLE"


class NetworkOutageError(InfrastructureError):
    code = "INFRASTRUCTURE.NETWORK_OUTAGE"


class CircuitOpenError(InfrastructureError):
    code = "INFRASTRUCTURE.CIRCUIT_OPEN"


class WorkerLostError(InfrastructureError):
    code = "INFRASTRUCTURE.WORKER_LOST"


# --- PUBLISHING ---
class UploadInterruptedError(PublishingError):
    code = "PUBLISHING.UPLOAD_INTERRUPTED"


class UploadRejectedError(PublishingError):
    code = "PUBLISHING.UPLOAD_REJECTED"


class QuotaExhaustedError(PublishingError):
    code = "PUBLISHING.QUOTA_EXHAUSTED"


class OauthRevokedError(PublishingError):
    code = "PUBLISHING.OAUTH_REVOKED"


class OauthRefreshFailedError(PublishingError):
    code = "PUBLISHING.OAUTH_REFRESH_FAILED"


class ProcessingFailedError(PublishingError):
    code = "PUBLISHING.PROCESSING_FAILED"


class VerificationMismatchError(PublishingError):
    code = "PUBLISHING.VERIFICATION_MISMATCH"


class DuplicateDetectedError(PublishingError):
    code = "PUBLISHING.DUPLICATE_DETECTED"


class NotAuthorisedError(PublishingError):
    code = "PUBLISHING.NOT_AUTHORISED"


class DestinationUnavailableError(PublishingError):
    code = "PUBLISHING.DESTINATION_UNAVAILABLE"


CLASS_BASES: Mapping[FailureClass, type[AmwError]] = MappingProxyType(
    {
        FailureClass.TEMPORARY: TemporaryError,
        FailureClass.PERMANENT: PermanentError,
        FailureClass.RESOURCE: ResourceError,
        FailureClass.AGENT: AgentError,
        FailureClass.INFRASTRUCTURE: InfrastructureError,
        FailureClass.PUBLISHING: PublishingError,
    }
)
