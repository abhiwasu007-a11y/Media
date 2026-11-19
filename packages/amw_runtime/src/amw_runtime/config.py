"""Runtime configuration (interface 1). Reads ONLY names from the environment mapping it is
given; values of secrets are never read here (the preflight checks names for presence)."""

import re
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from amw_core.errors import ConfigInvalidError
from amw_runtime.data_files import DATA_DIR, read_json

ENV_MODE = "AMW_RUNTIME_MODE"
ENV_CONFIG_PATH = "AMW_RUNTIME_CONFIG_PATH"
ENV_PER_VIDEO_CAP = "AMW_RUNTIME_PER_VIDEO_CAP_MINOR"
ENV_TOTAL_CAP = "AMW_RUNTIME_TOTAL_CAP_MINOR"
DEFAULT_CONFIG_FILE = DATA_DIR / "runtime_config.json"
SECRET_NAME = re.compile(r"^AMW_SECRET_[A-Z0-9]+(_[A-Z0-9]+)*_API_KEY$")
_MICROS_EXPONENT = 6


class RunMode(StrEnum):
    DRY_RUN = "DRY_RUN"
    REAL_RUN = "REAL_RUN"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderSpec(_Model):
    name: str = Field(min_length=1)
    role: str
    required: bool
    secret_name: str | None
    source_id: str

    @model_validator(mode="after")
    def _secret_name(self) -> ProviderSpec:
        if self.required and self.secret_name is None:
            raise ValueError("a required provider needs a secret name")
        if self.secret_name is not None and not SECRET_NAME.match(self.secret_name):
            raise ValueError("secret name must look like AMW_SECRET_<PROVIDER>_API_KEY")
        return self


class OwnerDecisions(_Model):
    source: str
    topics: tuple[str, ...]
    topics_status: str
    music_in_first_sample: bool
    upload: bool


class RuntimeConfig(_Model):
    mode: RunMode
    currency: str
    currency_minor_exponent: dict[str, int]
    owner_per_video_cap_micros: int = Field(gt=0)
    owner_total_cap_micros: int = Field(gt=0)
    per_video_cap_micros: int = Field(gt=0)
    total_cap_micros: int = Field(gt=0)
    hard_stop_on_breach: bool
    price_data_lag_days: int = Field(ge=0)
    price_data_lag_unit: str
    providers: tuple[ProviderSpec, ...]
    environment_variable: str
    required_environment: str
    vps_markers: tuple[str, ...]
    chart_data_source_kind: str
    chart_data_location_variable: str
    chart_data_location: str | None
    disclaimer_template_id: str
    disclaimer_version: str
    calendar_segment: str
    owner_decisions: OwnerDecisions
    data_dir: Path

    @property
    def required_secret_names(self) -> tuple[str, ...]:
        return tuple(p.secret_name for p in self.providers if p.required and p.secret_name)


def _micros(minor: int, currency: str, exponents: Mapping[str, int]) -> int:
    exp = exponents.get(currency)
    if exp is None or not 0 <= exp <= _MICROS_EXPONENT:
        raise ConfigInvalidError(
            "no minor-unit exponent configured for the budget currency",
            details={"currency": currency},
        )
    factor: int = pow(10, _MICROS_EXPONENT - exp)
    return int(minor) * factor


def _env_int(env: Mapping[str, str], name: str) -> int | None:
    raw = env.get(name)
    if raw is None:
        return None
    if not raw.isascii() or not raw.isdigit() or int(raw) <= 0:
        raise ConfigInvalidError("must be a positive integer", details={"variable": name})
    return int(raw)


def _section(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key)
    if not isinstance(value, Mapping):
        raise ConfigInvalidError("runtime config section missing", details={"section": key})
    return value


def load_runtime_config(env: Mapping[str, str]) -> RuntimeConfig:
    """Build the config from the data file plus NAMES in ``env``; fail closed on anything missing
    or invalid (``ConfigInvalidError``). Env may only LOWER the owner-approved caps."""
    mode_raw = env.get(ENV_MODE)
    if mode_raw not in {m.value for m in RunMode}:
        raise ConfigInvalidError(
            "run mode must be DRY_RUN or REAL_RUN (no default)", details={"variable": ENV_MODE}
        )
    path = Path(env[ENV_CONFIG_PATH]) if env.get(ENV_CONFIG_PATH) else DEFAULT_CONFIG_FILE
    try:
        raw = read_json(path)
    except ValueError as exc:
        raise ConfigInvalidError(str(exc), details={"file": path.name}) from None
    budget = _section(raw, "budget")
    finance = _section(raw, "finance")
    lag = _section(raw, "price_data_lag")
    envsec = _section(raw, "environment")
    chart = _section(raw, "chart_data")
    disc = _section(raw, "disclaimer")
    cal = _section(raw, "calendar")
    try:
        exponents = {str(k): int(v) for k, v in dict(finance["currency_minor_exponent"]).items()}
        currency = str(budget["currency"])
        if budget["hard_stop_on_breach"] is not True:
            raise ConfigInvalidError("hard stop on breach must be true")
        owner_pv = _micros(int(budget["per_video_cap_minor"]), currency, exponents)
        owner_total = _micros(int(budget["total_pilot_cap_minor"]), currency, exponents)
        pv_env, total_env = _env_int(env, ENV_PER_VIDEO_CAP), _env_int(env, ENV_TOTAL_CAP)
        pv = owner_pv if pv_env is None else _micros(pv_env, currency, exponents)
        total = owner_total if total_env is None else _micros(total_env, currency, exponents)
        if pv > owner_pv or total > owner_total:
            raise ConfigInvalidError("an env value may only lower the owner-approved caps")
        location_var = str(chart["location_variable"])
        return RuntimeConfig(
            mode=RunMode(mode_raw),
            currency=currency,
            currency_minor_exponent=exponents,
            owner_per_video_cap_micros=owner_pv,
            owner_total_cap_micros=owner_total,
            per_video_cap_micros=pv,
            total_cap_micros=total,
            hard_stop_on_breach=True,
            price_data_lag_days=int(lag["days"]),
            price_data_lag_unit=str(lag["unit"]),
            providers=tuple(ProviderSpec(**p) for p in raw["providers"]),
            environment_variable=str(envsec["environment_variable"]),
            required_environment=str(envsec["required_value"]),
            vps_markers=tuple(str(m) for m in envsec["vps_markers"]),
            chart_data_source_kind=str(chart["source_kind"]),
            chart_data_location_variable=location_var,
            chart_data_location=env.get(location_var) or None,
            disclaimer_template_id=str(disc["template_id"]),
            disclaimer_version=str(disc["version"]),
            calendar_segment=str(cal["segment"]),
            owner_decisions=OwnerDecisions(
                source=raw["owner_decisions"]["source"],
                topics=tuple(raw["owner_decisions"]["topics"]),
                topics_status=raw["owner_decisions"]["topics_status"],
                music_in_first_sample=raw["owner_decisions"]["music_in_first_sample"],
                upload=raw["owner_decisions"]["upload"],
            ),
            data_dir=path.parent if env.get(ENV_CONFIG_PATH) else DATA_DIR,
        )
    except ConfigInvalidError:
        raise
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        # field names only: pydantic messages may echo input values
        where = type(exc).__name__ if not isinstance(exc, KeyError) else f"missing key {exc}"
        raise ConfigInvalidError(
            "runtime config invalid", details={"problem": where, "file": path.name}
        ) from None
