"""``PgJobDestinationReader`` and the brand-kit refusal on real PostgreSQL (CCR-028, CCR-299)."""

import pytest

from agent_08_visual_assets.stage import BrandKitReader, JobDestinationReader
from amw_core.errors import ConfigInvalidError, InputInvalidError, MissingDependencyError
from amw_core.ids import JOB, ActorRef
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.tenancy import PgTenancy
from amw_core.testing.memory import MemoryTransaction
from amw_orchestrator.db_adapters import PgJobDestinationReader, UnavailableBrandKitReader
from tests.db_adapters.seed import Conn, seed_channel, seed_job
from tests.pg_fixtures import Tenant

pytestmark = pytest.mark.integration


def _ctx(t: Tenant) -> TenantContext:
    return TenantContext(t.org_id, ActorRef("agent_08"))


def test_ports_are_satisfied() -> None:
    """Checked by mypy (structural typing): the adapters are accepted where the port is typed."""
    destinations: JobDestinationReader = PgJobDestinationReader()
    brand_kits: BrandKitReader = UnavailableBrandKitReader()
    assert destinations is not None
    assert brand_kits is not None


@pytest.mark.parametrize("flag", [True, False])
def test_reads_the_stored_flag(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, flag: bool
) -> None:
    job = seed_job(admin, tenant_a, seed_channel(admin, tenant_a), monetized=flag)
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        assert PgJobDestinationReader().monetized_destination(tx, JOB.from_uuid(job)) is flag


def test_missing_job_is_a_typed_refusal(tenancy: PgTenancy, tenant_a: Tenant) -> None:
    with tenancy.transaction(_ctx(tenant_a)) as tx, pytest.raises(MissingDependencyError):
        PgJobDestinationReader().monetized_destination(tx, JOB.new())


def test_another_tenants_job_is_invisible(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    job = seed_job(admin, tenant_a, seed_channel(admin, tenant_a))
    with tenancy.transaction(_ctx(tenant_b)) as tx, pytest.raises(MissingDependencyError):
        PgJobDestinationReader().monetized_destination(tx, JOB.from_uuid(job))


def test_malformed_job_id_and_foreign_transaction(tenancy: PgTenancy, tenant_a: Tenant) -> None:
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        with pytest.raises(InputInvalidError):
            PgJobDestinationReader().monetized_destination(tx, "job_not-a-uuid")
        with pytest.raises(InputInvalidError):
            PgJobDestinationReader().monetized_destination(tx, "chn_" + "0" * 36)
    memory_tx = MemoryTransaction(_ctx(tenant_a))
    with pytest.raises(ConfigInvalidError):
        PgJobDestinationReader().monetized_destination(memory_tx, JOB.new())


def test_the_read_writes_nothing(tenancy: PgTenancy, admin: Conn, tenant_a: Tenant) -> None:
    job = seed_job(admin, tenant_a, seed_channel(admin, tenant_a))
    before = admin.execute(
        "SELECT xmin::text, updated_at FROM jobs WHERE id = %s", (job,)
    ).fetchone()
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        PgJobDestinationReader().monetized_destination(tx, JOB.from_uuid(job))
    after = admin.execute(
        "SELECT xmin::text, updated_at FROM jobs WHERE id = %s", (job,)
    ).fetchone()
    assert before == after


def test_brand_kit_refuses_closed(tenancy: PgTenancy, tenant_a: Tenant) -> None:
    with tenancy.transaction(_ctx(tenant_a)) as tx, pytest.raises(MissingDependencyError) as info:
        UnavailableBrandKitReader().brand_kit(tx, f"amw-blob://{tenant_a.org_id}/x.json", None)
    assert info.value.details == {"class": "brand_kit"}
