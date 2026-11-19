"""Provider wiring: fakes in a dry run, real adapters only behind a passed REAL_RUN preflight.

``build_providers`` takes the REAL ``PreflightReport`` (type-checked, not duck-typed) and builds a
real adapter for a provider only when the report carries that provider's ``ProviderAuthorisation``
(minted by ``run_preflight`` after its evidence-backed ``PROVIDER_LIMIT:<provider>`` item passed,
D10 / D11). The adapter in turn needs a ``CallGuard`` bound to that same token, so it cannot be
constructed or called any other way. ``guard_for`` makes the guard of one authorisation (the
production factory is ``BudgetCallGuard``; the live smoke script uses ``CapOnlyCallGuard``).

DRY_RUN -> fakes, no key read, no network. Only ``anthropic`` (LLM) and ``elevenlabs`` (TTS) have
real adapters (ADR-007, ADR-008). Secret NAMES come from the runtime config; the value is read
at call time by the adapter.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx

from amw_adapters.llm.anthropic import AnthropicLlmAdapter
from amw_adapters.llm.fake import FakeLlmAdapter
from amw_adapters.llm.protocol import LlmAdapter
from amw_adapters.real.authorisation import ProviderAuthorisation
from amw_adapters.real.catalogue import ProviderCatalogue, load_catalogue
from amw_adapters.real.guard import CallGuard
from amw_adapters.real.http import DEFAULT_BACKOFF
from amw_adapters.real.secrets import SecretRef
from amw_adapters.tts.elevenlabs import ElevenLabsTtsAdapter
from amw_adapters.tts.fake import FakeTtsAdapter
from amw_adapters.tts.protocol import TtsAdapter
from amw_core.config import RetryPolicySettings
from amw_core.errors import ConfigInvalidError
from amw_runtime.config import ProviderSpec, RunMode, RuntimeConfig
from amw_runtime.preflight import PreflightReport

GuardFactory = Callable[[ProviderAuthorisation], CallGuard]


@dataclass(frozen=True)
class ProviderSet:
    mode: RunMode
    real: bool
    llm: LlmAdapter
    tts: TtsAdapter


def _spec(config: RuntimeConfig, role: str, expected: str) -> ProviderSpec:
    specs = [p for p in config.providers if p.role == role]
    if len(specs) != 1:
        raise ConfigInvalidError(
            "runtime config needs exactly one provider", details={"role": role}
        )
    spec = specs[0]
    if spec.name != expected or spec.secret_name is None or not spec.required:
        raise ConfigInvalidError(
            "no real adapter for the configured provider",
            details={"role": role, "provider": spec.name},
        )
    return spec


def _authorisation(report: PreflightReport, provider: str) -> ProviderAuthorisation:
    found = [a for a in report.provider_authorisations if a.provider == provider]
    if len(found) != 1 or f"PROVIDER_LIMIT:{provider}" not in report.checks_passed:
        raise ConfigInvalidError(
            "no passed preflight with a provider spending limit for this provider",
            details={"provider": provider},
        )
    return found[0]


def build_providers(
    config: RuntimeConfig,
    *,
    preflight: PreflightReport | None,
    env: Mapping[str, str],
    guard_for: GuardFactory | None = None,
    catalogue: ProviderCatalogue | None = None,
    transports: Mapping[str, httpx.BaseTransport] | None = None,
    backoff: RetryPolicySettings = DEFAULT_BACKOFF,
) -> ProviderSet:
    """The adapters for this run. ``env`` is only read for secret NAMES (and by the adapter at
    call time); ``transports`` (``{"anthropic": ..., "elevenlabs": ...}``) are for tests."""
    if config.mode is RunMode.DRY_RUN:
        return ProviderSet(mode=config.mode, real=False, llm=FakeLlmAdapter(), tts=FakeTtsAdapter())
    if config.mode is not RunMode.REAL_RUN:  # pragma: no cover - closed enum
        raise ConfigInvalidError("unknown run mode")
    if (
        not isinstance(preflight, PreflightReport)
        or preflight.mode is not RunMode.REAL_RUN
        or not preflight.secrets_checked
        or preflight.test_confirmation_used
    ):
        raise ConfigInvalidError(
            "real providers need a passed REAL_RUN preflight (amw_runtime.run_preflight)"
        )
    if guard_for is None:
        raise ConfigInvalidError("real providers need a call guard (per-video hard stop)")
    llm_spec = _spec(config, "LLM", "anthropic")
    tts_spec = _spec(config, "TTS", "elevenlabs")
    llm_auth = _authorisation(preflight, llm_spec.name)
    tts_auth = _authorisation(preflight, tts_spec.name)
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
        mode=config.mode,
        real=True,
        llm=AnthropicLlmAdapter(
            cat.anthropic,
            llm_secret,
            guard=guard_for(llm_auth),
            transport=chosen.get("anthropic"),
            backoff=backoff,
        ),
        tts=ElevenLabsTtsAdapter(
            cat.elevenlabs,
            tts_secret,
            guard=guard_for(tts_auth),
            transport=chosen.get("elevenlabs"),
            backoff=backoff,
        ),
    )
