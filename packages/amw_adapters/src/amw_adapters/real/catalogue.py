"""Provider catalogue: model IDs, prices and limits as config data tied to RESEARCH_LOG ids.

The packaged file ``amw_adapters/data/providers.json`` is the default; a deployment may pass its
own file. Every price is integer micros (CCR-106/107/133: integer money). Nothing here is a code
default: a model, price or limit that is not in the file does not exist for the adapters
(``PERMANENT.CONFIG_INVALID``).
"""

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from amw_core.errors import ConfigInvalidError

DEFAULT_CATALOGUE = Path(__file__).resolve().parent.parent / "data" / "providers.json"
PosInt = Annotated[int, Field(gt=0, strict=True)]
NonNegInt = Annotated[int, Field(ge=0, strict=True)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class InCallRetry(_Model):
    """Retries inside one adapter call (only where no request was processed, PR-09/PR-12)."""

    max_in_call_retries: Annotated[int, Field(ge=0, le=5, strict=True)]
    max_in_call_wait_ms: NonNegInt
    retry_429_without_retry_after: bool


class TokenPrice(_Model):
    """Micros per million tokens for one prompt-length band (``None`` = no upper bound)."""

    max_prompt_tokens: PosInt | None
    input: NonNegInt
    cache_write_5m: NonNegInt
    cache_write_1h: NonNegInt
    cache_read: NonNegInt
    output: NonNegInt


class AnthropicModel(_Model):
    source: str = Field(min_length=1)
    max_output_tokens: PosInt
    prices: tuple[TokenPrice, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _bands(self) -> AnthropicModel:
        bounds = [p.max_prompt_tokens for p in self.prices]
        if bounds[-1] is not None or any(b is None for b in bounds[:-1]):
            raise ValueError("only the last price band is unbounded")
        finite = [b for b in bounds if b is not None]
        if finite != sorted(set(finite)):
            raise ValueError("price bands must be strictly increasing")
        return self

    def band(self, prompt_tokens: int) -> TokenPrice:
        for price in self.prices:
            if price.max_prompt_tokens is None or prompt_tokens <= price.max_prompt_tokens:
                return price
        raise AssertionError("unreachable: the last band is unbounded")  # pragma: no cover


class AnthropicCatalogue(_Model):
    provider: Literal["anthropic"]
    base_url: str = Field(pattern=r"^https://[a-z0-9.-]+$")
    api_version: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    price_ref: str = Field(min_length=1)
    billed_refusal_categories: frozenset[str]
    cache_ttl: Literal["5m", "1h"]
    connect_timeout_ms: PosInt
    retry: InCallRetry
    models: dict[str, AnthropicModel] = Field(min_length=1)

    def model(self, model_id: str) -> AnthropicModel:
        found = self.models.get(model_id)
        if found is None:
            raise ConfigInvalidError(
                "model is not in the verified provider catalogue",
                details={"provider": self.provider, "model": model_id},
            )
        return found


class ElevenLabsModel(_Model):
    source: str = Field(min_length=1)
    enabled: bool
    languages: tuple[str, ...] = Field(min_length=1)
    max_chars_per_request: PosInt | None
    price_micros_per_1k_chars: NonNegInt
    speed_control: bool
    ipa_inline: bool

    @model_validator(mode="after")
    def _enabled_needs_limit(self) -> ElevenLabsModel:
        if self.enabled and self.max_chars_per_request is None:
            raise ValueError("an enabled model needs a documented character limit")
        return self


class ElevenLabsCatalogue(_Model):
    provider: Literal["elevenlabs"]
    base_url: str = Field(pattern=r"^https://[a-z0-9.-]+$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    price_ref: str = Field(min_length=1)
    character_count_rule: Literal["UNICODE_CODE_POINTS"]
    connect_timeout_ms: PosInt
    synthesize_timeout_ms: PosInt
    list_timeout_ms: PosInt
    list_voices_page_size: Annotated[int, Field(ge=1, le=100, strict=True)]
    list_voices_max_pages: Annotated[int, Field(ge=1, le=100, strict=True)]
    retry: InCallRetry
    wav_sample_rates_hz: frozenset[int] = Field(min_length=1)
    forbidden_models: dict[str, str]
    emotion_audio_tags: dict[str, str]
    voice_settings: dict[str, float | bool] | None
    models: dict[str, ElevenLabsModel] = Field(min_length=1)

    @model_validator(mode="after")
    def _forbidden_never_listed(self) -> ElevenLabsCatalogue:
        overlap = set(self.forbidden_models) & set(self.models)
        if overlap:
            raise ValueError("a forbidden model is also listed as allowed")
        if not any(m.enabled for m in self.models.values()):
            raise ValueError("no enabled model")
        for tag in self.emotion_audio_tags.values():
            if not (tag.startswith("[") and tag.endswith("]") and 2 < len(tag) <= 64):
                raise ValueError("an emotion audio tag must look like [tag]")
        return self

    @property
    def enabled_models(self) -> dict[str, ElevenLabsModel]:
        return {k: v for k, v in self.models.items() if v.enabled}

    def model(self, model_id: str) -> ElevenLabsModel:
        if model_id in self.forbidden_models:
            raise ConfigInvalidError(
                "TTS model is forbidden for this factory (no Marathi support)",
                details={"provider": self.provider, "model": model_id},
            )
        found = self.models.get(model_id)
        if found is None or not found.enabled:
            raise ConfigInvalidError(
                "TTS model is not on the verified, enabled allow-list",
                details={"provider": self.provider, "model": model_id},
            )
        return found


class ProviderCatalogue(_Model):
    anthropic: AnthropicCatalogue
    elevenlabs: ElevenLabsCatalogue


def load_catalogue(path: Path | None = None) -> ProviderCatalogue:
    """Read and validate the catalogue; any problem is ``PERMANENT.CONFIG_INVALID`` (field names
    only, never values)."""
    source = path or DEFAULT_CATALOGUE
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
        return ProviderCatalogue.model_validate(raw)
    except OSError:
        raise ConfigInvalidError(
            "provider catalogue not readable", details={"file": source.name}
        ) from None
    except json.JSONDecodeError:
        raise ConfigInvalidError(
            "provider catalogue is not JSON", details={"file": source.name}
        ) from None
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
        raise ConfigInvalidError(
            "provider catalogue invalid", details={"file": source.name, "fields": fields}
        ) from None
