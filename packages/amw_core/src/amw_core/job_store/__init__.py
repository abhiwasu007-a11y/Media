"""Job / task store (04 section 5.3): ``PgJobStore`` implements ``amw_core.interfaces.JobStore``."""

from amw_core.job_store.pg import PgJobStore

__all__ = ["PgJobStore"]
