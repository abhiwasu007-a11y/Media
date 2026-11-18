"""In-memory web fetch fake: enforces HTTPS, the host allow-list, the private-address block and
the size cap, then returns fixture or synthetic content (no network)."""

import hashlib
import ipaddress
from typing import Any
from urllib.parse import urlsplit

from amw_adapters.common import (
    CallUsage,
    FailurePlan,
    FakeEngine,
    FakeProvider,
    FixtureStore,
    fake_provider,
)
from amw_adapters.web_fetch.protocol import OPERATION_FETCH, WebFetchRequest, WebFetchResult
from amw_core.enums import CostUnitKind
from amw_core.errors import InputInvalidError


def _is_private(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".internal"):
        return True
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return not address.is_global


class FakeWebFetchAdapter:
    def __init__(
        self,
        *,
        allowed_hosts: frozenset[str] = frozenset({"example.org"}),
        provider: str = FakeProvider.WEB,
        currency: str = "USD",
        failures: FailurePlan | None = None,
        fixtures: FixtureStore | None = None,
    ) -> None:
        self._provider = fake_provider(provider)
        self._allowed = allowed_hosts
        self._currency = currency
        self.engine = FakeEngine("web_fetch", failures=failures, fixtures=fixtures)

    @property
    def provider(self) -> str:
        return self._provider

    def _check(self, request: WebFetchRequest) -> None:
        host = (urlsplit(request.url).hostname or "").lower()
        if _is_private(host):
            raise InputInvalidError("private or local address refused")
        if host not in self._allowed:
            raise InputInvalidError("host is not on the fetch allow-list")

    def fetch(self, request: WebFetchRequest, *, idempotency_key: str) -> WebFetchResult:
        self._check(request)

        def build(digest: str, fixture: dict[str, Any] | None) -> WebFetchResult:
            fx = fixture or {}
            content = str(fx.get("text", f"fake page {digest[:16]}")).encode("utf-8")
            if len(content) > request.max_bytes:
                raise InputInvalidError("response larger than max_bytes")
            usage = CallUsage(
                provider=self._provider,
                operation=OPERATION_FETCH,
                units=len(content),
                unit_kind=CostUnitKind.BYTES,
                amount_micros=0,
                currency=self._currency,
                idempotency_key=idempotency_key,
            )
            return WebFetchResult(
                final_url=request.url,
                status_code=int(fx.get("status_code", 200)),
                media_type=str(fx.get("media_type", "text/html")),
                content=content,
                content_sha256=hashlib.sha256(content).hexdigest(),
                usage=usage,
            )

        return self.engine.run(OPERATION_FETCH, idempotency_key, request, build, WebFetchResult)
