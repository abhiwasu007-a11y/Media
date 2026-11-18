"""LLM adapter: Protocol + deterministic fake."""

from amw_adapters.llm.fake import FakeLlmAdapter
from amw_adapters.llm.protocol import LlmAdapter, LlmMessage, LlmRequest, LlmResponse, TokenCount

__all__ = ["FakeLlmAdapter", "LlmAdapter", "LlmMessage", "LlmRequest", "LlmResponse", "TokenCount"]
