"""Typed settings (pydantic-settings). See the package docstring for the rules."""

import json
import os
import tomllib
from collections.abc import Iterable, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Final

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictInt,
    StringConstraints,
    ValidationError,
    model_validator,
)
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from amw_core.enums import LlmModelTier, RetryPolicy
from amw_core.errors import ConfigInvalidError

ENV_PREFIX = "AMW_"
ENV_NESTED_DELIMITER = "__"


MAX_MINOR_EXPONENT: Final = 6
"""Largest ISO 4217 minor-unit exponent the money arithmetic can represent: money is integer
micros (10^-6 of the major unit, GLOSSARY section 3), so an exponent above 6 has no exact micros
conversion. Every consumer of ``finance.currency_minor_exponent`` refuses a value outside
``0..MAX_MINOR_EXPONENT`` (``limit_micros``, ``cost.report.to_minor``)."""

CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
"""ISO 4217 alphabetic code: three upper-case ASCII letters (as the CHECK of migration 0050)."""
MinorExponent = Annotated[StrictInt, Field(ge=0, le=MAX_MINOR_EXPONENT)]
"""A real integer (not a bool, string or float) between 0 and ``MAX_MINOR_EXPONENT``."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RetryPolicySettings(_Model):
    """``retry.<policy>.*`` (07 section 3.3, design defaults ESTIMATE)."""

    base_ms: int = Field(ge=0)
    multiplier: int = Field(ge=1)
    cap_ms: int = Field(ge=0)
    jitter: Decimal = Field(ge=0, le=1)
    max_attempts: int = Field(ge=1, le=10)
    retry_after_max_ms: int | None = Field(default=None, ge=0)


def _policy(
    base: int, mult: int, cap: int, attempts: int, retry_after_max: int | None = None
) -> RetryPolicySettings:
    return RetryPolicySettings(
        base_ms=base,
        multiplier=mult,
        cap_ms=cap,
        jitter=Decimal("0.5") if base else Decimal(0),
        max_attempts=attempts,
        retry_after_max_ms=retry_after_max,
    )


def _default_retry() -> dict[RetryPolicy, RetryPolicySettings]:
    return {
        RetryPolicy.TEMPORARY: _policy(2_000, 2, 300_000, 5),
        RetryPolicy.RATE_LIMITED: _policy(10_000, 2, 900_000, 6, 3_600_000),
        RetryPolicy.DB: _policy(200, 2, 10_000, 5),
        RetryPolicy.RESOURCE: _policy(60_000, 2, 1_800_000, 3),
        RetryPolicy.AGENT: _policy(5_000, 2, 120_000, 3),
        RetryPolicy.AGENT_PARSE: _policy(0, 1, 0, 2),
        RetryPolicy.INFRA: _policy(30_000, 2, 900_000, 8),
        RetryPolicy.PUBLISH_RESUME: _policy(15_000, 2, 600_000, 5),
    }


class BreakerSettings(_Model):
    """``breaker.<provider>.<operation_class>.*`` (07 section 4.2, design defaults ESTIMATE)."""

    window_ms: int = Field(default=60_000, gt=0)
    min_calls: int = Field(default=5, ge=1)
    failure_ratio: Decimal = Field(default=Decimal("0.5"), gt=0, le=1)
    consecutive_failures: int = Field(default=5, ge=1)
    open_ms: int = Field(default=30_000, gt=0)
    open_ms_max: int = Field(default=900_000, gt=0)
    half_open_max_probes: int = Field(default=1, ge=1)
    half_open_successes_to_close: int = Field(default=2, ge=1)
    half_open_probe_timeout_ms: int | None = Field(default=None, gt=0)
    """How long an admitted HALF_OPEN probe may stay unreported before its slot is reclaimed (a
    crashed worker must not wedge the breaker). No value in 07: REQUIRES REVIEW (owner / Phase 1),
    no default; unset, ``PgBreakerFunctions.admit`` refuses with ``CONFIG_INVALID``."""

    @model_validator(mode="after")
    def _open_bounds(self) -> BreakerSettings:
        if self.open_ms > self.open_ms_max:
            raise ValueError("open_ms must not exceed open_ms_max")
        return self


class LimitsSettings(_Model):
    """``limits.*`` hard caps (07 section 9)."""

    max_attempts_per_task: int = Field(default=10, ge=1, le=10)
    max_revision_loops: int = Field(default=3, ge=0)
    max_tasks_per_job: int = Field(default=200, ge=1)
    max_child_jobs_per_job: int = Field(default=10, ge=0)
    max_replays_per_item: int = Field(default=3, ge=0)
    max_job_active_ms: int = Field(default=86_400_000, gt=0)


class CapsSettings(_Model):
    lock_conflict_reevaluations: int = Field(default=5, ge=1)


class ReaperSettings(_Model):
    """07 section 6 thresholds (``reaper.*``, ``lease_ms``, ``heartbeat_ms``)."""

    interval_ms: int = Field(default=15_000, gt=0)
    lease_ms: int = Field(default=60_000, gt=0)
    heartbeat_ms: int = Field(default=15_000, gt=0)
    stale_heartbeat_factor: int = Field(default=3, ge=1)
    validating_max_ms: int = Field(default=300_000, gt=0)
    failed_without_dlq_ms: int = Field(default=60_000, gt=0)
    retry_wait_overdue_ms: int = Field(default=300_000, gt=0)
    job_max_idle_ms: int | None = Field(default=None, gt=0)
    """``job.max_idle_ms``: no value in 07; unset means the check is off."""


class WaitSettings(_Model):
    """``wait.<reason>.timeout_ms`` (03 T16); ``AWAITING_APPROVAL`` has no timeout by default."""

    awaiting_external_timeout_ms: int | None = Field(default=None, gt=0)
    approval_reminder_ms: int | None = Field(default=None, gt=0)
    approval_escalate_ms: int | None = Field(default=None, gt=0)
    quota_max_wait_days: int | None = Field(default=None, gt=0)


class DlqSettings(_Model):
    """``dlq.*`` (07 section 5). No value in 07: both stay unset until configured."""

    bulk_replay_max: int | None = Field(default=None, ge=1)
    replay_cost_review_micros: int | None = Field(default=None, ge=0)


class FinanceSettings(_Model):
    """``finance.*`` (09). Every value is REQUIRES REVIEW (owner / Finance) and has no default."""

    variance_alert_ratio: Decimal | None = Field(default=None, gt=0)
    devanagari_token_factor: Decimal | None = Field(default=None, gt=0)
    currency_minor_exponent: dict[CurrencyCode, MinorExponent] = Field(default_factory=dict)
    """ISO 4217 minor-unit exponent per budget currency. **No code default** (empty map): a budget
    whose currency has no entry cannot be converted to micros and is refused
    ``PERMANENT.CONFIG_INVALID`` (fail closed, CCR-133). The values (INR 2, USD 2: RV-07) are
    deployment config data; REQUIRES REVIEW (owner decision, Q-O12): which currencies are used."""
    fx_pairs: list[str] = Field(default_factory=list)
    """Currency pairs ``"<row currency>/<budget currency>"`` for which a ledger row's recorded
    ``fx_rate`` may be applied (e.g. ``"USD/INR"``). Empty: no conversion (fail closed)."""


class EvalSettings(_Model):
    """27 section 8.3 / 8.4 caps: owner sets them (REQUIRES REVIEW); no default."""

    max_run_cost_micros: int | None = Field(default=None, ge=0)
    live_smoke_max_cost_micros: int | None = Field(default=None, ge=0)


class LlmTierSettings(_Model):
    """``llm.tiers.<tier>.provider`` / ``.model`` (ADR-007). No default model or provider."""

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)


class LlmTaskSettings(_Model):
    """``llm.<task_type>.*`` (27 section 4.2)."""

    model_tier: LlmModelTier
    temperature: Decimal | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, gt=0)
    timeout_ms: int | None = Field(default=None, gt=0)
    cost_budget_micros: int | None = Field(default=None, ge=0)
    cache_system_prompt: bool = False
    batch_eligible: bool = False
    fallback_tier: LlmModelTier | None = None


class LlmSettings(_Model):
    tiers: dict[LlmModelTier, LlmTierSettings] = Field(default_factory=dict)
    tasks: dict[str, LlmTaskSettings] = Field(default_factory=dict)

    def for_task(self, task_type: str) -> LlmTaskSettings:
        try:
            return self.tasks[task_type]
        except KeyError:
            raise ConfigInvalidError(f"no llm config for task type {task_type!r}") from None

    def resolve(self, tier: LlmModelTier) -> LlmTierSettings:
        try:
            return self.tiers[tier]
        except KeyError:
            raise ConfigInvalidError(f"no provider/model configured for tier {tier}") from None


class StorageSettings(_Model):
    """ADR-005 section 3.1: backend and root come only from configuration (no default path)."""

    backend: str = "local"
    root: Path | None = None
    chunk_bytes: int = Field(default=1024 * 1024, gt=0)


class DatabaseSettings(_Model):
    """The database URL carries a credential: it is a secret and has no default."""

    url: SecretStr | None = None
    lock_timeout_ms: int = Field(default=5_000, gt=0)


class WindowSettings(_Model):
    """Operational windows (GLOSSARY section 4; ADR-012). The market-hours calendar source is
    REQUIRES REVIEW (R9): no default calendar is shipped."""

    timezone: str | None = None
    night_start: str | None = None
    night_drain_at: str | None = None
    night_stop_at: str | None = None
    drain_grace_ms: int | None = Field(default=None, ge=0)


class AmwSettings(BaseSettings):
    """Root settings. Environment: ``AMW_<SECTION>__<FIELD>`` (``AMW_LIMITS__MAX_TASKS_PER_JOB``).

    ``secrets`` maps a secret *name* (e.g. ``llm_api_key``) to its value; values come only from the
    environment (``AMW_SECRETS__<NAME>``) or a mounted secret directory, never from a config file.
    """

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_nested_delimiter=ENV_NESTED_DELIMITER,
        extra="forbid",
        frozen=True,
        case_sensitive=False,
    )

    environment: str = "development"
    retry: dict[RetryPolicy, RetryPolicySettings] = Field(default_factory=_default_retry)
    breaker_default: BreakerSettings = Field(default_factory=BreakerSettings)
    breaker: dict[str, BreakerSettings] = Field(default_factory=dict)
    """Overrides keyed ``<provider>.<operation_class>``."""
    limits: LimitsSettings = Field(default_factory=LimitsSettings)
    caps: CapsSettings = Field(default_factory=CapsSettings)
    reaper: ReaperSettings = Field(default_factory=ReaperSettings)
    wait: WaitSettings = Field(default_factory=WaitSettings)
    dlq: DlqSettings = Field(default_factory=DlqSettings)
    finance: FinanceSettings = Field(default_factory=FinanceSettings)
    evals: EvalSettings = Field(default_factory=EvalSettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    windows: WindowSettings = Field(default_factory=WindowSettings)
    secrets: dict[str, SecretStr] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _complete_retry_table(self) -> AmwSettings:
        missing = set(RetryPolicy) - set(self.retry)
        if missing:
            merged = _default_retry() | dict(self.retry)
            object.__setattr__(self, "retry", merged)
        return self

    def retry_policy(self, policy: RetryPolicy) -> RetryPolicySettings:
        return self.retry[policy]

    def breaker_for(self, provider: str, operation_class: str) -> BreakerSettings:
        return self.breaker.get(f"{provider}.{operation_class}", self.breaker_default)

    def secret(self, name: str) -> str:
        """The secret value for ``name``; ``ConfigInvalidError`` (no value printed) if absent."""
        value = self.secrets.get(name)
        if value is None or not value.get_secret_value():
            raise ConfigInvalidError(f"required secret {name!r} is not set")
        return value.get_secret_value()

    def secret_values(self) -> tuple[str, ...]:
        """Every configured secret value (for the log redaction filter)."""
        values = [v.get_secret_value() for v in self.secrets.values()]
        if self.database.url is not None:
            values.append(self.database.url.get_secret_value())
        return tuple(v for v in values if v)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Only explicit values: ``load_settings`` parses the environment and the mounted secret
        # directory itself, so there is exactly one reading path (no .env file, no hidden source).
        return (init_settings,)


def _read_config_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".toml":
        data: Any = tomllib.loads(text)
    elif path.suffix == ".json":
        data = json.loads(text)
    else:
        raise ConfigInvalidError(f"unsupported config file type {path.suffix!r}")
    if not isinstance(data, dict):
        raise ConfigInvalidError("config file must hold an object")
    if "secrets" in data or "url" in data.get("database", {}):
        raise ConfigInvalidError("secrets are never read from a config file (08 section 3.1)")
    return data


def load_settings(
    config_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
    secrets_dir: Path | None = None,
) -> AmwSettings:
    """Load settings: non-secret values from ``config_file`` (TOML/JSON), then ``AMW_*``
    environment values (they win), then mounted secret files (one file per secret name in
    ``secrets_dir``). ``environ`` defaults to the process environment (tests pass their own).

    Any validation failure is ``PERMANENT.CONFIG_INVALID``; the message names fields, never values.
    """
    file_values = _read_config_file(config_file) if config_file is not None else {}
    env = os.environ if environ is None else environ
    merged = _deep_merge(file_values, _environ_to_tree(env))
    if secrets_dir is not None:
        merged = _deep_merge(merged, {"secrets": _read_secret_dir(secrets_dir)})
    try:
        return AmwSettings(**merged)
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in err["loc"]) for err in exc.errors()})
        raise ConfigInvalidError("invalid configuration", details={"fields": fields}) from None


def _read_secret_dir(directory: Path) -> dict[str, str]:
    if not directory.is_dir():
        raise ConfigInvalidError("secret directory is not readable")
    out: dict[str, str] = {}
    for entry in sorted(directory.iterdir()):
        if entry.is_file() and not entry.name.startswith("."):
            out[entry.name.lower()] = entry.read_text(encoding="utf-8").strip()
    return out


def _environ_to_tree(environ: Mapping[str, str]) -> dict[str, Any]:
    tree: dict[str, Any] = {}
    for raw_key, value in environ.items():
        key = raw_key.upper()
        if not key.startswith(ENV_PREFIX):
            continue
        parts = [p.lower() for p in key[len(ENV_PREFIX) :].split(ENV_NESTED_DELIMITER)]
        if parts[0] not in AmwSettings.model_fields:
            continue  # another component's AMW_* variable (e.g. AMW_TEST_DATABASE_URL)
        node = tree
        for part in parts[:-1]:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                raise ConfigInvalidError("conflicting environment keys", details={"key": raw_key})
            node = child
        node[parts[-1]] = _maybe_json(value)
    return tree


def _maybe_json(value: str) -> Any:
    stripped = value.strip()
    if stripped[:1] in "{[":
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return value
    return value


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        current = out.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            out[key] = _deep_merge(current, value)
        else:
            out[key] = value
    return out


def require_secrets(settings: AmwSettings, names: Iterable[str]) -> None:
    """08 section 3.1 rule 7: a service lists the secrets it needs; a missing one fails startup
    with ``PERMANENT.CONFIG_INVALID``. Only the names are reported, never a value or its length."""
    missing = sorted(n for n in names if not settings.secrets.get(n))
    if missing:
        raise ConfigInvalidError("required secrets are missing", details={"names": missing})
