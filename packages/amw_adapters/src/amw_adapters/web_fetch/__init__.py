"""Web fetch adapter: Protocol + deterministic fake (CCR-015)."""

from amw_adapters.web_fetch.fake import FakeWebFetchAdapter
from amw_adapters.web_fetch.protocol import WebFetchAdapter, WebFetchRequest, WebFetchResult

__all__ = ["FakeWebFetchAdapter", "WebFetchAdapter", "WebFetchRequest", "WebFetchResult"]
