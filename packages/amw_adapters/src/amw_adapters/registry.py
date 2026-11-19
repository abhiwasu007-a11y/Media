"""Provider registry: fakes in a dry run, real adapters only after a passed real-run preflight.

Wiring code (workers, scripts) calls ``build_providers`` with the runtime config of
``amw_runtime.config.load_runtime_config`` and the report of ``amw_runtime.preflight.run_preflight``
(lane S4). The registry reads both through the small Protocols below, so ``amw_adapters`` does
not import ``amw_runtime`` (that package depends on agents, which depend on these adapters).

Rules (D1, D8): ``DRY_RUN`` -> fakes, no key read, no network. ``REAL_RUN`` -> refused with
``PERMANENT.CONFIG_INVALID`` unless a preflight report is given that is itself ``REAL_RUN`` and
checked the secrets; ``run_preflight`` only returns a report when every item passed (it raises
``PreflightRefused`` otherwise). Provider names and secret NAMES come from the runtime config;
only ``anthropic`` (LLM) and ``elevenlabs`` (TTS) have real adapters (ADR-007, ADR-008).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import httpx

from amw_adapters.llm.anthropic import AnthropicLlmAdapter
from amw_adapters.llm.fake import FakeLlmAdapter
from amw_adapters.llm.protocol import LlmAdapter
from amw_adapters.real.catalogue import ProviderCatalogue, load_catalogue
from amw_adapters.real.http import DEFAULT_BACKOFF
from amw_adapters.real.secrets import SecretRef
from amw_adapters.tts.elevenlabs import ElevenLabsTtsAdapter
from amw_adapters.tts.fake import FakeTtsAdapter
from amw_adapters.tts.protocol import TtsAdapter
from amw_core.config import RetryPolicySettings
from amw_core.errors import ConfigInvalidError

DRY_RUN = "DRY_RUN"
REAL_RUN = "REAL_RUN"


class ProviderSpecView(Protocol):
    """``amw_runtime.config.ProviderSpec``."""

    @property
    def name(self) -> str: ...

    @property
    def role(self) -> str: ...

    @property
    def required(self) -> bool: ...

    @property
    def secret_name(self) -> str | None: ...


class RuntimeConfigView(Protocol):
    """``amw_runtime.config.RuntimeConfig``."""

    @property
    def mode(self) -> StrEnum: ...

    @property
    def providers(self) -> Sequence[ProviderSpecView]: ...


class PreflightView(Protocol):
    """``amw_runtime.preflight.PreflightReport``."""

    @property
    def mode(self) -> StrEnum: ...

    @property
    def secrets_checked(self) -> bool: ...


@dataclass(frozen=True)
class ProviderSet:
    mode: str
    real: bool
    llm: LlmAdapter
    tts: TtsAdapter


def _spec(config: RuntimeConfigView, role: str, expected: str) -> ProviderSpecView:
    specs = [p for p in config.providers if p.role == role]
    if len(specs) != 1:
        raise ConfigInvalidError(
            "runtime config needs exactly one provider", details={"role": role}
        )
    spec = specs[0]
    if spec.name != expected or spec.secret_name is None:
        raise ConfigInvalidError(
            "no real adapter for the configured provider",
            details={"role": role, "provider": spec.name},
        )
    return spec


def build_providers(
    config: RuntimeConfigView,
    *,
    preflight: PreflightView | None,
    env: Mapping[str, str],
    catalogue: ProviderCatalogue | None = None,
    transports: Mapping[str, httpx.BaseTransport] | None = None,
    backoff: RetryPolicySettings = DEFAULT_BACKOFF,
) -> ProviderSet:
    """The adapters for this run. ``env`` is only read for secret NAMES at call time;
    ``transports`` (``{"anthropic": ..., "elevenlabs": ...}``) are for tests and recorded runs."""
    mode = config.mode.value
    if mode == DRY_RUN:
        return ProviderSet(mode=mode, real=False, llm=FakeLlmAdapter(), tts=FakeTtsAdapter())
    if mode != REAL_RUN:
        raise ConfigInvalidError("unknown run mode", details={"mode": mode})
    if preflight is None or preflight.mode.value != REAL_RUN or not preflight.secrets_checked:
        raise ConfigInvalidError(
            "real providers need a passed REAL_RUN preflight (amw_runtime.run_preflight)"
        )
    llm_spec = _spec(config, "LLM", "anthropic")
    tts_spec = _spec(config, "TTS", "elevenlabs")
    assert llm_spec.secret_name is not None  # noqa: S101 - checked in _spec
    assert tts_spec.secret_name is not None  # noqa: S101 - checked in _spec
    llm_secret = SecretRef(llm_spec.secret_name, env)
    tts_secret = SecretRef(tts_spec.secret_name, env)
    missing = [s.name for s in (llm_secret, tts_secret) if not s.present()]
    if missing:
        raise ConfigInvalidError("required secrets are missing", details={"names": missing})
    cat = catalogue or load_catalogue()
    chosen = transports or {}
    return ProviderSet(
        mode=mode,
        real=True,
        llm=AnthropicLlmAdapter(
            cat.anthropic, llm_secret, transport=chosen.get("anthropic"), backoff=backoff
        ),
        tts=ElevenLabsTtsAdapter(
            cat.elevenlabs, tts_secret, transport=chosen.get("elevenlabs"), backoff=backoff
        ),
    )
