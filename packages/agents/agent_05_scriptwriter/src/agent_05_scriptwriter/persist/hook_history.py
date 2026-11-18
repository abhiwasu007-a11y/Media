"""``HookHistoryMemory`` (blueprint 14, 19.1): channel-scoped hook openings, read twice-filtered."""

from agent_05_scriptwriter.protocols import HookHistoryEntry, HookHistoryStore, StepContext


class HookHistoryMemory:
    """Reads only this channel's entries: the store is asked for the channel and the result is
    filtered again here, so a store that over-returns can never leak another channel's openings."""

    def __init__(self, store: HookHistoryStore) -> None:
        self._store = store

    def read(self, ctx: StepContext, n: int) -> list[str]:
        rows = [e for e in self._store.read(ctx, n) if e.channel_id == ctx.channel_id]
        return [e.text for e in rows][:n]

    def write(self, ctx: StepContext, entries: list[HookHistoryEntry]) -> None:
        own = [e for e in entries if e.channel_id == ctx.channel_id]
        self._store.write(ctx, own)
