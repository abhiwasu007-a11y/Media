"""CAT-01 / D13 / CCR-273 (PROPOSED): the job category is read from ``channels.category`` inside
the tenant transaction and fails closed; no caller argument can set it or widen the set.

Needs ``AMW_TEST_DATABASE_URL`` (the suite skips without it)."""

from pathlib import Path

import pytest

from amw_core.config import RulePackSettings
from amw_core.ids import CHANNEL, ActorRef
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.tenancy.channel_category import read_channel_category
from amw_orchestrator.executor import ChannelCategory
from tests.orchestrator.world import Rig, build_rig, set_channel_category

pytestmark = pytest.mark.integration


def _read(rig: Rig, channel_id: str, *, org_id: str | None = None) -> str | None:
    ctx = TenantContext(org_id or rig.seed.org_id, ActorRef("sys_operator"))  # type: ignore[arg-type]
    with rig.tenancy.transaction(ctx) as tx:
        return read_channel_category(tx, channel_id)


@pytest.mark.parametrize(
    ("stored", "finance"),
    [
        ("youtube_general", False),
        ("health", False),
        ("kids", False),
        ("political_news", False),
        ("non-finance", False),
        ("finance", True),
        ("advertising", True),
        ("ad_sector", True),
        ("brand_safety", True),
        ("philosophy", True),  # unknown value: fail closed (CCR-288 open)
        ("YouTube_General", True),
        ("", True),
    ],
)
def test_category_comes_from_the_channel_row(
    pg_dsn: str, tmp_path: Path, stored: str, finance: bool
) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    job = rig.intake(stored)
    assert job.finance_rules_apply is finance
    assert job.channel_category is (
        ChannelCategory.FINANCE if finance else ChannelCategory.NON_FINANCE
    )


def test_a_caller_cannot_label_the_job_the_row_decides(pg_dsn: str, tmp_path: Path) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    topic = rig.intake("finance").owner_topic
    from amw_core.ids import CORRELATION
    from amw_orchestrator.services import intake
    from tests.orchestrator.world import LONG

    common = {
        "org_id": rig.seed.org_id, "workspace_id": rig.seed.workspace_id,
        "project_id": rig.seed.project_id, "channel_id": rig.seed.channel_id, "topic": topic,
        "production_type": LONG, "version": 2, "correlation_id": str(CORRELATION.new()),
    }  # fmt: skip
    for attack in (
        {"channel_category": "non-finance"},
        {"channel_category": "youtube_general"},
        {"non_finance_categories": {"finance"}},
        {"non_finance_categories": "finance"},
    ):
        with pytest.raises(TypeError):
            intake(rig.tenancy, rig.jobs, **common, **attack)  # type: ignore[arg-type]
    assert intake(rig.tenancy, rig.jobs, **common).finance_rules_apply  # type: ignore[arg-type]


def test_rule_pack_settings_narrow_what_the_row_may_say(pg_dsn: str, tmp_path: Path) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    from amw_core.ids import CORRELATION
    from amw_orchestrator.services import intake
    from tests.orchestrator.world import LONG

    topic = rig.intake("kids").owner_topic
    narrowed = RulePackSettings(non_finance_categories=frozenset({"kids"}))
    for stored, expected_finance in (("kids", False), ("youtube_general", True)):
        rig.set_channel_category(stored)
        job = intake(
            rig.tenancy, rig.jobs, org_id=rig.seed.org_id, workspace_id=rig.seed.workspace_id,
            project_id=rig.seed.project_id, channel_id=rig.seed.channel_id, topic=topic,
            production_type=LONG, version=2, correlation_id=str(CORRELATION.new()),
            rule_packs=narrowed,
        )  # fmt: skip
        assert job.finance_rules_apply is expected_finance


def test_unreadable_channel_is_none_and_does_not_abort_the_transaction(
    pg_dsn: str, tmp_path: Path
) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    rig.set_channel_category("kids")
    other = str(CHANNEL.new())  # no such row
    assert _read(rig, rig.seed.channel_id) == "kids"
    assert _read(rig, other) is None
    assert _read(rig, "chn_not-a-uuid") is None
    assert _read(rig, "") is None
    assert _read(rig, "org_" + rig.seed.channel_id.split("_", 1)[1]) is None  # wrong prefix
    ctx = TenantContext(rig.seed.org_id, ActorRef("sys_operator"))  # type: ignore[arg-type]
    with rig.tenancy.transaction(ctx) as tx:  # a failed read leaves the transaction usable
        assert read_channel_category(tx, "chn_bad") is None
        assert read_channel_category(tx, rig.seed.channel_id) == "kids"


def test_another_tenants_channel_reads_as_unknown(pg_dsn: str, tmp_path: Path) -> None:
    a = build_rig(pg_dsn, tmp_path / "a")
    b = build_rig(pg_dsn, tmp_path / "b")
    set_channel_category(pg_dsn, b.seed.channel_id, "kids")
    assert _read(b, b.seed.channel_id) == "kids"
    assert _read(a, b.seed.channel_id) is None  # org filter + RLS: no cross-tenant read


def test_a_non_postgres_transaction_reads_as_unknown() -> None:
    class _Tx:
        context = TenantContext("org_x", ActorRef("sys_operator"))  # type: ignore[arg-type]

    assert read_channel_category(_Tx(), "chn_x") is None
