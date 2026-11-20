"""Two small readers of stored content hashes on PostgreSQL (04 section 5.7 ``scripts`` and 5.15
``renders``): ``ScriptRegistry`` of agent_06 and ``RenderHashReader`` of agent_16. One SELECT each,
explicit ``org_id`` predicate plus RLS, writes nothing. A row that is not in the tenant (absent or
another tenant's) is ``None`` (the port's own contract: "else None")."""

from amw_core.ids import RENDER
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_orchestrator.db_adapters._sql import SCRIPT, org_of, rows, uuid_of


def _hex(raw: object) -> str | None:
    if raw is None:
        return None
    return bytes(raw).hex() if isinstance(raw, bytes | bytearray | memoryview) else str(raw)


class PgScriptRegistry:
    """``agent_06_fact_checker.ports.ScriptRegistry``: ``scripts.content_sha256`` of one version."""

    def content_sha256(
        self, tx: TenantTransaction, *, script_id: str, script_version: int
    ) -> str | None:
        found = rows(
            tx,
            "SELECT content_sha256 FROM scripts WHERE org_id = %s AND id = %s AND version = %s",
            (org_of(tx), uuid_of(SCRIPT, script_id), script_version),
        )
        return _hex(found[0][0]) if found else None


class PgRenderHashReader:
    """``agent_16_compliance_qa.assembler.RenderHashReader``: ``renders.content_sha256``."""

    def render_content_sha256(self, tx: TenantTransaction, render_id: str) -> str | None:
        found = rows(
            tx,
            "SELECT content_sha256 FROM renders WHERE org_id = %s AND id = %s",
            (org_of(tx), uuid_of(RENDER, render_id)),
        )
        return _hex(found[0][0]) if found else None
