"""PostgreSQL adapters for ports the agents declared as Protocols (lane DB-ADAPTERS).

Every adapter runs inside the caller's tenant transaction (``amw_app``; explicit ``org_id``
predicate plus RLS) or opens one through ``TenancyContext``, fails closed with the 07 typed errors,
and writes only the tables of its owning agent. Ports with no table or document contract behind
them are not built here: see CCR-300 and CCR-301 in ``docs/v4/CONTRACT_CHANGE_REQUESTS.md``.
"""

from amw_orchestrator.db_adapters.brand_kit import UnavailableBrandKitReader
from amw_orchestrator.db_adapters.chunk_reader import (
    ChunkIndex,
    ChunkLocation,
    LibraryChunkReader,
)
from amw_orchestrator.db_adapters.fact_rows import PgFactRowReader
from amw_orchestrator.db_adapters.hash_readers import PgRenderHashReader, PgScriptRegistry
from amw_orchestrator.db_adapters.job_destination import PgJobDestinationReader
from amw_orchestrator.db_adapters.score_store import PgScoreStore
from amw_orchestrator.db_adapters.script_rows import PgScriptRowPort

__all__ = [
    "ChunkIndex",
    "ChunkLocation",
    "LibraryChunkReader",
    "PgFactRowReader",
    "PgJobDestinationReader",
    "PgRenderHashReader",
    "PgScoreStore",
    "PgScriptRegistry",
    "PgScriptRowPort",
    "UnavailableBrandKitReader",
]
