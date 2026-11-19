"""Proof that a REAL_RUN preflight passed for one provider, one org and (optionally) one job
(D10, D11, D13).

A ``ProviderAuthorisation`` is a SEALED capability. The seal is an HMAC over every field; the key
is generated at import time inside ``amw_runtime.preflight``, is never exported and is held only
in the closures of that module. This module holds no key: it holds a verifier function that
``amw_runtime.preflight`` installs at import (``install_verifier`` refuses a second call and a
caller outside that module; this stops an accidental or in-tree re-install, it is NOT a boundary
against code that assigns the module attribute ``_verifier`` directly).
Every real adapter call is checked again with ``verify_authorisation``: seal, expiry, provider,
currency, org and job binding, and the caps are CLAMPED to the packaged owner ceilings (USD 5 per
video, USD 50 pilot) whatever the token says.

What this prevents in plain Python: constructing a token by hand (no key, so no valid seal),
changing a field of a real token (seal breaks; the class is immutable and not copyable or
picklable), importing a mint function (there is none here), a token of another org, job or
provider, an expired token, a cap above the ceiling. What it cannot prevent: a caller that can
run arbitrary code in the process can read the closure cells of ``amw_runtime.preflight`` or patch
memory and forge anything. The seal is a guard against mistakes and in-tree shortcuts, not a
sandbox. The token holds no secret and no provider key.
"""

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final, NoReturn, final

from amw_core.errors import ConfigInvalidError

_INSTALLER_MODULE: Final = "amw_runtime.preflight"
SEAL_BYTES: Final = 32


@final
class ProviderAuthorisation:
    __slots__ = (
        "currency",
        "expires_at",
        "issued_at",
        "job_id",
        "nonce",
        "org_id",
        "per_video_cap_micros",
        "provider",
        "seal",
        "total_cap_micros",
    )

    provider: str
    org_id: str
    job_id: str | None
    per_video_cap_micros: int
    total_cap_micros: int
    currency: str
    issued_at: int
    expires_at: int
    nonce: str
    seal: bytes

    def __init__(
        self,
        *,
        provider: str,
        org_id: str,
        job_id: str | None,
        per_video_cap_micros: int,
        total_cap_micros: int,
        currency: str,
        issued_at: int,
        expires_at: int,
        nonce: str,
        seal: bytes,
    ) -> None:
        ints = (per_video_cap_micros, total_cap_micros, issued_at, expires_at)
        if (
            not provider
            or not org_id
            or not nonce
            or len(currency) != 3
            or any(isinstance(v, bool) or not isinstance(v, int) for v in ints)
            or per_video_cap_micros <= 0
            or total_cap_micros < per_video_cap_micros
            or expires_at <= issued_at
            or not isinstance(seal, bytes)
        ):
            raise ConfigInvalidError(
                "provider authorisation needs provider, org, caps, currency, validity and a seal"
            )
        values = {
            "provider": provider,
            "org_id": org_id,
            "job_id": job_id,
            "per_video_cap_micros": per_video_cap_micros,
            "total_cap_micros": total_cap_micros,
            "currency": currency,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "nonce": nonce,
            "seal": seal,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)

    def __init_subclass__(cls, **kwargs: object) -> NoReturn:
        raise TypeError("ProviderAuthorisation cannot be subclassed")

    def canonical(self) -> bytes:
        """The bytes the seal covers (every field but the seal itself)."""
        parts = (
            "amw.provider_authorisation.v1",
            self.provider,
            self.org_id,
            "" if self.job_id is None else self.job_id,
            str(self.per_video_cap_micros),
            str(self.total_cap_micros),
            self.currency,
            str(self.issued_at),
            str(self.expires_at),
            self.nonce,
        )
        return "\x1f".join(parts).encode("utf-8")

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError("a provider authorisation is immutable")

    def __delattr__(self, name: str) -> NoReturn:
        raise AttributeError("a provider authorisation is immutable")

    def __reduce__(self) -> NoReturn:
        raise TypeError("a provider authorisation cannot be copied or pickled")

    def __repr__(self) -> str:
        return f"ProviderAuthorisation({self.provider!r}, org={self.org_id!r})"


@dataclass(frozen=True, slots=True)
class VerifiedGrant:
    """What a verified token allows right now. The caps are already clamped to the owner
    ceilings; read the cap from here, never from the token."""

    provider: str
    org_id: str
    job_id: str | None
    per_video_cap_micros: int
    total_cap_micros: int
    currency: str
    expires_at: int


Verifier = Callable[[ProviderAuthorisation, datetime], VerifiedGrant]

_verifier: Verifier | None = None


def install_verifier(verifier: Verifier) -> None:
    """Called at import by ``amw_runtime.preflight`` (the holder of the seal key). A later call, or
    a call from another module, is refused: a guard against mistakes, not a security boundary
    (code in the process can assign ``_verifier``; see the module docstring)."""
    global _verifier
    caller = sys._getframe(1).f_globals.get("__name__")
    if caller != _INSTALLER_MODULE or _verifier is not None:
        raise ConfigInvalidError(
            "the authorisation verifier can only be installed once by preflight"
        )
    _verifier = verifier


def verify_authorisation(
    auth: object, now: datetime, *, provider: str, currency: str
) -> VerifiedGrant:
    """Full check of a token at the moment of a provider call; ``CONFIG_INVALID`` otherwise
    (fail closed: no verifier installed means no token can be valid)."""
    if type(auth) is not ProviderAuthorisation:
        raise ConfigInvalidError("a real adapter needs a preflight authorisation")
    if _verifier is None:
        raise ConfigInvalidError("no preflight has installed the authorisation verifier")
    grant = _verifier(auth, now)
    if grant.provider != provider or grant.currency != currency:
        raise ConfigInvalidError(
            "the preflight authorisation is for another provider or currency",
            details={"provider": provider},
        )
    return grant
