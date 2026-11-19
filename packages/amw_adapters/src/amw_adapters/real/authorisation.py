"""Proof that a REAL_RUN preflight passed for one provider (D10, D11, D13).

A ``ProviderAuthorisation`` cannot be built by calling the class: the constructor needs a private
mint key that only ``mint_provider_authorisation`` holds, and the only caller of that function
in the source tree is ``amw_runtime.preflight.run_preflight`` (a test scans for it). It is minted
only when the REAL_RUN preflight passed with an evidence-backed ``PROVIDER_LIMIT`` confirmation
for this provider, and it carries the per-video cap the preflight verified (owner ceiling, USD 5).
Every real adapter and call guard requires one, so a real provider call is unreachable without a
passing preflight. The token holds no secret; it is not copyable or picklable.
"""

from typing import Final, NoReturn, final

from amw_core.errors import ConfigInvalidError

_MINT: Final = object()


@final
class ProviderAuthorisation:
    __slots__ = ("currency", "per_video_cap_micros", "provider")

    provider: str
    per_video_cap_micros: int
    currency: str

    def __init__(
        self, provider: str, per_video_cap_micros: int, currency: str, *, _mint: object = None
    ) -> None:
        if _mint is not _MINT:
            raise ConfigInvalidError(
                "a provider authorisation can only come from a passed REAL_RUN preflight"
            )
        if (
            not provider
            or isinstance(per_video_cap_micros, bool)
            or per_video_cap_micros <= 0
            or len(currency) != 3
        ):
            raise ConfigInvalidError(
                "provider authorisation needs a provider, a cap and a currency"
            )
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "per_video_cap_micros", per_video_cap_micros)
        object.__setattr__(self, "currency", currency)

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError("a provider authorisation is immutable")

    def __delattr__(self, name: str) -> NoReturn:
        raise AttributeError("a provider authorisation is immutable")

    def __reduce__(self) -> NoReturn:
        raise TypeError("a provider authorisation cannot be copied or pickled")

    def __repr__(self) -> str:
        return f"ProviderAuthorisation({self.provider!r}, cap={self.per_video_cap_micros})"


def mint_provider_authorisation(
    provider: str, *, per_video_cap_micros: int, currency: str
) -> ProviderAuthorisation:
    """Only ``amw_runtime.preflight`` calls this, after every preflight item passed."""
    return ProviderAuthorisation(provider, per_video_cap_micros, currency, _mint=_MINT)
