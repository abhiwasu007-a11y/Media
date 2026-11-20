"""Private library chunk index (CCR-307): builder, loader and operator command.

The index feeds ``LibraryChunkReader`` (``db_adapters``). It holds offsets, hashes and locators only
and lives in a private directory outside git; chunk text is always re-read from the pinned checkout.
"""

from amw_orchestrator.library_index.build import BuildReport, build_index
from amw_orchestrator.library_index.loader import PrivateChunkIndex
from amw_orchestrator.library_index.models import chunk_id_for

__all__ = ["BuildReport", "PrivateChunkIndex", "build_index", "chunk_id_for"]
