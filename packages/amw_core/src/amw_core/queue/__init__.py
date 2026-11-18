"""Task queue (ADR-001 option A): ``PgTaskQueue`` implements ``amw_core.interfaces.TaskQueue``."""

from amw_core.queue.pg import NOTIFY_CHANNEL, PgTaskQueue

__all__ = ["NOTIFY_CHANNEL", "PgTaskQueue"]
