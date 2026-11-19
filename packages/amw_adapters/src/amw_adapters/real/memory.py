"""In-process idempotency memory of a real adapter (same contract as ``FakeEngine``).

Neither provider dedupes a paid call by key (PR-09, PR-12), so the adapter itself guarantees
that one process never pays twice for the same key: same key + same request returns the stored
result (no HTTP call); same key + different request is ``PERMANENT.IDEMPOTENCY_CONFLICT``; a
failed call is not stored, so a retry under the same key runs again. Durable, cross-process
idempotency stays with the caller's ``idempotency_keys`` store (03 section 9).
"""

from collections import OrderedDict
from dataclasses import dataclass

from pydantic import BaseModel

from amw_adapters.common import AdapterResult, request_sha256
from amw_core.errors import IdempotencyConflictError
from amw_core.ids import idempotency_key_of


@dataclass(frozen=True, slots=True)
class CallRecord:
    operation: str
    idempotency_key: str
    outcome: str
    """``ok`` (a new provider call that returned), ``replayed`` or the raised 07 code."""


class CallMemory:
    def __init__(self, max_entries: int = 10_000) -> None:
        self._max = max_entries
        self._done: OrderedDict[tuple[str, str], tuple[str, AdapterResult]] = OrderedDict()
        self.calls: list[CallRecord] = []

    def lookup[R: AdapterResult](
        self, operation: str, idempotency_key: str, request: BaseModel, result_type: type[R]
    ) -> tuple[str, R | None]:
        """Validate the key; ``(request digest, stored result or None)``."""
        idempotency_key_of(idempotency_key)
        digest = request_sha256(request)
        stored = self._done.get((operation, idempotency_key))
        if stored is None:
            return digest, None
        stored_digest, result = stored
        if stored_digest != digest:
            self.calls.append(CallRecord(operation, idempotency_key, IdempotencyConflictError.code))
            raise IdempotencyConflictError("same idempotency key, different request")
        if not isinstance(result, result_type):  # pragma: no cover - defensive
            raise TypeError("stored result type changed")
        self.calls.append(CallRecord(operation, idempotency_key, "replayed"))
        return digest, result

    def store(
        self, operation: str, idempotency_key: str, digest: str, result: AdapterResult
    ) -> None:
        self._done[(operation, idempotency_key)] = (digest, result)
        self._done.move_to_end((operation, idempotency_key))
        while len(self._done) > self._max:
            self._done.popitem(last=False)
        self.calls.append(CallRecord(operation, idempotency_key, "ok"))

    def failed(self, operation: str, idempotency_key: str, code: str) -> None:
        self.calls.append(CallRecord(operation, idempotency_key, code))

    @property
    def billable_calls(self) -> int:
        return sum(1 for c in self.calls if c.outcome == "ok")
