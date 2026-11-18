"""StockFootage adapter: Protocol + deterministic fake."""

from amw_adapters.stock_footage.fake import FakeStockFootageAdapter
from amw_adapters.stock_footage.protocol import StockFootageAdapter

__all__ = ["FakeStockFootageAdapter", "StockFootageAdapter"]
