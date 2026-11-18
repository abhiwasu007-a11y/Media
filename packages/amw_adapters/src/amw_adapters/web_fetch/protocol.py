"""Web fetch adapter Protocol (SOURCE_LAYOUT ``web_fetch/``, CCR-015; capability ``web_fetch``).

Allow-listed HTTPS GET of an owner reference (Agent 04) with size, time and redirect caps and a
private-address block. Idempotency scope ``fetch.reference`` (task, ref_id, URL SHA-256); the
snapshot is written write-once to ``evidence/<job>/<ext_ref>.json`` by the caller (03 section 8,
CCR-016). Usage operation ``web.fetch``; no money cost. Refusals: a host not on the allow-list,
a non-HTTPS URL or a private address -> ``InputInvalidError``; too large -> ``InputInvalidError``;
upstream 5xx / timeout -> the 07 TEMPORARY codes.
"""

from typing import Annotated, Protocol, runtime_checkable

from pydantic import Field, StringConstraints

from amw_adapters.common import AdapterModel, AdapterResult

OPERATION_FETCH = "web.fetch"


class WebFetchRequest(AdapterModel):
    url: Annotated[str, StringConstraints(pattern=r"^https://", max_length=2048)]
    max_bytes: Annotated[int, Field(ge=1)] = 5_000_000
    timeout_ms: Annotated[int, Field(ge=1)] = 20_000
    max_redirects: Annotated[int, Field(ge=0, le=10)] = 3


class WebFetchResult(AdapterResult):
    final_url: str
    status_code: int
    media_type: str
    content: bytes
    content_sha256: str


@runtime_checkable
class WebFetchAdapter(Protocol):
    @property
    def provider(self) -> str: ...

    def fetch(self, request: WebFetchRequest, *, idempotency_key: str) -> WebFetchResult: ...
