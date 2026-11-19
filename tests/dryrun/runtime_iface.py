# mypy: disable-error-code="arg-type,attr-defined,unused-ignore,var-annotated"
# mypy: disable-error-code="index,no-untyped-call,misc,union-attr"
# (throw-away dry-run fixtures feed fakes and dataset dicts into typed APIs)
"""Re-export of the S4 bridge for the dry-run world."""

from amw_orchestrator.runtime_iface import get_disclaimer, market_calendar

__all__ = ["get_disclaimer", "market_calendar"]
