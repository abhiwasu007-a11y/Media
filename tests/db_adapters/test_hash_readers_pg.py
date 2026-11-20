"""``PgScriptRegistry`` and ``PgRenderHashReader`` on real PostgreSQL (with tenant isolation)."""

import pytest

from agent_06_fact_checker.ports import ScriptRegistry
from agent_16_compliance_qa.assembler import RenderHashReader
from amw_core.errors import InputInvalidError
from amw_core.ids import RENDER, ActorRef
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.tenancy import PgTenancy
from amw_orchestrator.db_adapters import PgRenderHashReader, PgScriptRegistry
from amw_orchestrator.db_adapters._sql import SCRIPT
from tests.db_adapters.seed import Conn, seed, seed_render, seed_script, sha
from tests.pg_fixtures import Tenant

pytestmark = pytest.mark.integration


def _ctx(t: Tenant) -> TenantContext:
    return TenantContext(t.org_id, ActorRef("agent_06"))


def test_ports_are_satisfied() -> None:
    registry: ScriptRegistry = PgScriptRegistry()
    renders: RenderHashReader = PgRenderHashReader()
    assert registry is not None
    assert renders is not None


def test_script_hash_of_a_version(tenancy: PgTenancy, admin: Conn, tenant_a: Tenant) -> None:
    s = seed(admin, tenant_a)
    script = seed_script(admin, tenant_a, s.job, s.channel, s.task, version=2)
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        reg = PgScriptRegistry()
        found = reg.content_sha256(tx, script_id=SCRIPT.from_uuid(script), script_version=2)
        assert found == sha("script" + script.hex).hex()
        assert reg.content_sha256(tx, script_id=SCRIPT.from_uuid(script), script_version=1) is None
        assert reg.content_sha256(tx, script_id=SCRIPT.new(), script_version=2) is None
        with pytest.raises(InputInvalidError):
            reg.content_sha256(tx, script_id="not-an-id", script_version=2)


def test_script_of_another_tenant_is_invisible(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    s = seed(admin, tenant_a)
    script = seed_script(admin, tenant_a, s.job, s.channel, s.task)
    with tenancy.transaction(_ctx(tenant_b)) as tx:
        assert (
            PgScriptRegistry().content_sha256(
                tx, script_id=SCRIPT.from_uuid(script), script_version=1
            )
            is None
        )


def test_render_hash_and_isolation(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    s = seed(admin, tenant_a)
    render, digest = seed_render(admin, tenant_a, s.job)
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        reader = PgRenderHashReader()
        assert reader.render_content_sha256(tx, RENDER.from_uuid(render)) == digest.hex()
        assert reader.render_content_sha256(tx, RENDER.new()) is None
        with pytest.raises(InputInvalidError):
            reader.render_content_sha256(tx, "bad")
    with tenancy.transaction(_ctx(tenant_b)) as tx:
        assert PgRenderHashReader().render_content_sha256(tx, RENDER.from_uuid(render)) is None
