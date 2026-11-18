"""Shared adapter types and the deterministic fake engine.

Every adapter call takes an ``idempotency_key`` (``idk_...``, 03 section 9; SOURCE_LAYOUT rule 4)
and returns ``CallUsage``: the data a cost-ledger row needs (04 section 5.14, 09 section 5), always
``figure_kind = ESTIMATE`` at call time. Fakes never touch the network (27 section 8): results come
from a recorded JSON fixture when one matches, else they are derived deterministically from the
request. Synthetic fake prices are test configuration, never real provider prices.
"""

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from amw_core.enums import BillingMode, CostFigureKind, CostUnitKind
from amw_core.errors import AmwError, ConfigInvalidError, IdempotencyConflictError
from amw_core.ids import IDEMPOTENCY_KEY_PATTERN, idempotency_key_of

NonNeg = Annotated[int, Field(ge=0, strict=True)]
ProviderName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{2,32}$")]
Operation = Annotated[str, StringConstraints(pattern=r"^[a-z_]+\.[a-z_]+$")]
FAKE_PRICE_REF = "fake-pricing-v0"


class FakeProvider(StrEnum):
    """The only provider names a fake accepts (real names come from config, never fakes)."""

    LLM = "fake_llm"
    TTS = "fake_tts"
    STOCK = "fake_stock"
    MUSIC = "fake_music"
    IMAGE = "fake_image"
    VIDEO = "fake_video"
    DELIVERY = "fake_delivery"


def fake_provider(value: str) -> FakeProvider:
    """``ConfigInvalidError`` for any name that is not a ``FakeProvider``."""
    try:
        return FakeProvider(value)
    except ValueError:
        raise ConfigInvalidError(f"unknown fake provider {value!r}") from None


class AdapterModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CallUsage(AdapterModel):
    """Usage and cost of one provider call, mapped 1:1 onto ``cost_ledger`` columns."""

    provider: ProviderName
    operation: Operation
    model: str | None = None
    billing_mode: BillingMode | None = None
    tokens_in: NonNeg | None = None
    tokens_out: NonNeg | None = None
    tokens_cached_in: NonNeg | None = None
    units: NonNeg | None = None
    unit_kind: CostUnitKind | None = None
    amount_micros: NonNeg
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
    figure_kind: CostFigureKind = CostFigureKind.ESTIMATE
    price_ref: str | None = None
    idempotency_key: Annotated[str, StringConstraints(pattern=IDEMPOTENCY_KEY_PATTERN)]
    external_request_id: str | None = None

    @model_validator(mode="after")
    def _units_pair(self) -> Self:
        if (self.units is None) != (self.unit_kind is None):
            raise ValueError("units and unit_kind are set together")
        return self

    @property
    def characters(self) -> int | None:
        return self.units if self.unit_kind is CostUnitKind.CHARACTERS else None


class AdapterResult(AdapterModel):
    usage: CallUsage


def request_sha256(request: BaseModel) -> str:
    """Canonical hash of a request (the ``request_sha256`` of ``idempotency_keys``, 03 9.1)."""
    canonical = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fake_bytes(seed: str, size: int) -> bytes:
    """Deterministic pseudo-content of ``size`` bytes."""
    out = bytearray()
    counter = 0
    while len(out) < size:
        out += hashlib.sha256(f"{seed}:{counter}".encode()).digest()
        counter += 1
    return bytes(out[:size])


class FixtureStore:
    """Recorded fixtures: ``<root>/<adapter>/*.json`` files of the form
    ``{"operation": "...", "match": {<subset of request fields>}, "response": {...}}``.

    A fixture applies when its operation equals the call's and every ``match`` field equals the
    request's value. Files are redacted recordings: no keys, tokens or account identifiers.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def find(
        self, adapter: str, operation: str, request: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        folder = self._root / adapter
        if not folder.is_dir():
            return None
        for path in sorted(folder.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            if doc.get("operation") != operation:
                continue
            match: Mapping[str, Any] = doc.get("match", {})
            if all(request.get(k) == v for k, v in match.items()):
                response: dict[str, Any] = doc["response"]
                return response
        return None


@dataclass(frozen=True, slots=True)
class RecordedCall:
    operation: str
    idempotency_key: str
    request_sha256: str
    outcome: str
    """``ok`` (billable new call), ``replayed`` (idempotent hit) or the raised error code."""


@dataclass
class FailurePlan:
    """Configurable failures: ``sequence[i]`` is raised on the i-th new call (``None`` = succeed);
    ``by_key`` raises for one idempotency key, once. A failed call is not stored, so a retry with
    the same key runs again (as a real retry would)."""

    sequence: Sequence[AmwError | None] = ()
    by_key: Mapping[str, AmwError] = field(default_factory=dict)
    _index: int = 0
    _used_keys: set[str] = field(default_factory=set)

    def next_failure(self, idempotency_key: str) -> AmwError | None:
        if idempotency_key in self.by_key and idempotency_key not in self._used_keys:
            self._used_keys.add(idempotency_key)
            return self.by_key[idempotency_key]
        if self._index < len(self.sequence):
            failure = self.sequence[self._index]
            self._index += 1
            return failure
        return None


class FakeEngine:
    """Idempotency, failure injection, fixtures and call recording shared by every fake."""

    def __init__(
        self,
        adapter: str,
        *,
        failures: FailurePlan | None = None,
        fixtures: FixtureStore | None = None,
    ) -> None:
        self.adapter = adapter
        self.failures = failures or FailurePlan()
        self.fixtures = fixtures
        self.calls: list[RecordedCall] = []
        self._done: dict[tuple[str, str], tuple[str, AdapterResult]] = {}

    def run[R: AdapterResult](
        self,
        operation: str,
        idempotency_key: str,
        request: BaseModel,
        build: Callable[[str, dict[str, Any] | None], R],
        result_type: type[R],
    ) -> R:
        """Validate the key, replay or refuse a repeat, inject failures, then ``build`` the result
        from ``(request_sha256, matching fixture response or None)``."""
        idempotency_key_of(idempotency_key)
        digest = request_sha256(request)
        stored = self._done.get((operation, idempotency_key))
        if stored is not None:
            stored_digest, stored_result = stored
            if stored_digest != digest:
                self.calls.append(
                    RecordedCall(operation, idempotency_key, digest, IdempotencyConflictError.code)
                )
                raise IdempotencyConflictError("same idempotency key, different request")
            self.calls.append(RecordedCall(operation, idempotency_key, digest, "replayed"))
            if not isinstance(stored_result, result_type):  # pragma: no cover - defensive
                raise TypeError("stored result type changed")
            return stored_result
        failure = self.failures.next_failure(idempotency_key)
        if failure is not None:
            self.calls.append(RecordedCall(operation, idempotency_key, digest, failure.code))
            raise failure
        fixture = None
        if self.fixtures is not None:
            fixture = self.fixtures.find(self.adapter, operation, request.model_dump(mode="json"))
        result = build(digest, fixture)
        self._done[(operation, idempotency_key)] = (digest, result)
        self.calls.append(RecordedCall(operation, idempotency_key, digest, "ok"))
        return result

    @property
    def billable_calls(self) -> int:
        return sum(1 for c in self.calls if c.outcome == "ok")
