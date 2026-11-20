"""``PgFactRowReader`` on real PostgreSQL: every read of agent_16 section 15.1a / 15.1b, absent
rows, tenant isolation and "reads write nothing" (the adapter runs as ``amw_app`` and a read-only
check compares the row-version stamps)."""

import uuid
from typing import Any

import pytest

from agent_16_compliance_qa.inputs.extractors import FactRowReader
from amw_core.enums import AudienceKind, CheckVerdict, ClaimStatus, LicenceState, VisualSourceTier
from amw_core.errors import ConfigInvalidError, InputInvalidError
from amw_core.ids import APPROVAL, ASSET, JOB, RENDER, ActorRef, new_uuid7
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.tenancy import PgTenancy
from amw_core.testing.memory import MemoryTransaction
from amw_orchestrator.db_adapters import PgFactRowReader
from amw_orchestrator.db_adapters._sql import CLAIM
from tests.db_adapters.seed import (
    Conn,
    Seeded,
    seed,
    seed_approval,
    seed_asset,
    seed_claim,
    seed_ledger,
    seed_licence,
    seed_qc,
    seed_render,
    seed_script,
    seed_task,
    sha,
)
from tests.pg_fixtures import Tenant

pytestmark = pytest.mark.integration
READ = PgFactRowReader()


def _ctx(t: Tenant) -> TenantContext:
    return TenantContext(t.org_id, ActorRef("agent_16"))


@pytest.fixture
def packs(admin: Conn) -> None:
    """Platform catalogue packs (idempotent: the database is shared by the session)."""
    for key, category, always in (
        ("rp.youtube_general", "youtube_general", True),
        ("rp.finance_sebi_in", "finance", False),
    ):
        admin.execute(
            "INSERT INTO rule_packs (id, org_id, key, version, scope, category, always_on,"
            " removable, rules_ref, rules_sha256, status, effective_from)"
            " VALUES (%s, NULL, %s, 1, 'PLATFORM', %s, %s, false, 'x', %s, 'ACTIVE', now())"
            " ON CONFLICT DO NOTHING",
            (new_uuid7(), key, category, always, sha(key)),
        )


def test_port_is_satisfied() -> None:
    reader: FactRowReader = PgFactRowReader()
    assert reader is not None


# -- channel and job --------------------------------------------------------------------------
def test_channel_row_is_returned_as_stored(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant
) -> None:
    kids = seed(admin, tenant_a, category="philosophy", audience="KIDS")
    undecided = seed(admin, tenant_a, category="Finance ")
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        row = READ.channel(tx, JOB.from_uuid(kids.job))
        assert row is not None
        assert (row.category, row.audience_kind, row.knowledge_collection_id) == (
            "philosophy",
            AudienceKind.KIDS,
            None,
        )
        raw = READ.channel(tx, JOB.from_uuid(undecided.job))
        assert raw is not None
        assert (raw.category, raw.audience_kind) == ("Finance ", None)  # verbatim, undecided
        assert READ.channel(tx, JOB.new()) is None


def _stages(admin: Conn, s: Seeded, **stage: str) -> None:
    for task_type, stage_id in stage.items():
        seed_task(admin, s.tenant, s.job, task_type=task_type.replace("__", "."), stage_id=stage_id)


def test_job_row_routing_comes_from_the_materialised_stages(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, packs: None
) -> None:
    s = seed(admin, tenant_a)
    _stages(
        admin,
        s,
        agent_05__script_draft="s05_script",
        agent_08__asset_sourcing="s08_assets",
        agent_11__thumbnail_variants="s11_thumbs",
    )
    # a cancelled task of a stage and an unrelated task type never count
    seed_task(
        admin,
        tenant_a,
        s.job,
        task_type="agent_11.thumbnail_variants",
        stage_id="old",
        state="CANCELLED",
    )
    seed_task(admin, tenant_a, s.job, task_type="agent_09.shot_plan", stage_id="s09_plan")
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        job = READ.job(tx, JOB.from_uuid(s.job))
    assert job is not None
    assert (job.language, job.production_type_key, job.live_format) == (
        "mr-IN", "CHANNEL_LONG_FORM", "STANDARD",
    )  # fmt: skip
    assert (
        job.routing_script_stage_id,
        job.routing_assets_stage_id,
        job.routing_thumbnails_stage_id,
    ) == ("s05_script", "s08_assets", "s11_thumbs")
    assert job.active_pack_keys == ("rp.youtube_general",)  # no profile: the always-on pack only


def test_thumbnails_disabled_is_none_and_missing_stages_fail_closed(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, packs: None
) -> None:
    s = seed(admin, tenant_a)
    t = JOB.from_uuid(s.job)
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        assert READ.job(tx, t) is None  # no script and no assets stage yet
    _stages(
        admin, s, agent_05__shorts_adaptation="s05_shorts", agent_08__asset_sourcing="s08_assets"
    )
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        job = READ.job(tx, t)
    assert job is not None
    assert (job.routing_script_stage_id, job.routing_thumbnails_stage_id) == ("s05_shorts", None)
    # two different stage IDs for one stage kind: ambiguous, so no row
    _stages(admin, s, agent_08__asset_sourcing="s08_other")
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        assert READ.job(tx, t) is None


def test_active_packs_include_the_profile_packs(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, packs: None
) -> None:
    s = seed(admin, tenant_a, category="finance")
    profile = new_uuid7()
    admin.execute(
        "INSERT INTO compliance_profiles (id, org_id, workspace_id, name, version, status)"
        " VALUES (%s, %s, %s, 'p', 1, 'ACTIVE')",
        (profile, tenant_a.org_uuid, tenant_a.workspace_uuid),
    )  # the trigger links rp.youtube_general
    admin.execute(
        "INSERT INTO compliance_profile_rule_packs (id, org_id, profile_id, rule_pack_id,"
        " is_mandatory) SELECT %s, %s, %s, id, false FROM rule_packs"
        " WHERE key = 'rp.finance_sebi_in'",
        (new_uuid7(), tenant_a.org_uuid, profile),
    )
    admin.execute(
        "UPDATE channels SET compliance_profile_id = %s WHERE id = %s", (profile, s.channel)
    )
    _stages(admin, s, agent_05__script_draft="s05_script", agent_08__asset_sourcing="s08_assets")
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        job = READ.job(tx, JOB.from_uuid(s.job))
    assert job is not None
    assert job.active_pack_keys == ("rp.finance_sebi_in", "rp.youtube_general")


# -- voice, assets ----------------------------------------------------------------------------
def test_voice_presenter_kind_is_not_known(tenancy: PgTenancy, tenant_a: Tenant) -> None:
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        assert READ.voice_presenter_kind(tx, JOB.new()) is None


def test_assets_join_licence_and_ledger(tenancy: PgTenancy, admin: Conn, tenant_a: Tenant) -> None:
    s = seed(admin, tenant_a)
    lic = seed_licence(admin, tenant_a, covers=True, permission="UNKNOWN")
    bare = seed_asset(admin, tenant_a, tier="C_CODE_MOTION")
    stock = seed_asset(admin, tenant_a, lic, person=True)
    seed_ledger(admin, tenant_a, stock, lic, s.job, s.task)
    missing = ASSET.from_uuid(new_uuid7())
    wanted = [ASSET.from_uuid(bare), ASSET.from_uuid(stock), missing]
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        got = READ.assets(tx, wanted, JOB.from_uuid(s.job))
        assert READ.assets(tx, [], JOB.from_uuid(s.job)) == {}
    assert set(got) == set(wanted[:2])  # the missing ID is simply absent
    plain, licensed = got[wanted[0]], got[wanted[1]]
    assert (plain.tier, plain.has_ledger_row, plain.licence_state) == (
        VisualSourceTier.C_CODE_MOTION, False, None,
    )  # fmt: skip
    assert (plain.covers_monetized_youtube, plain.third_party_permission) == (None, None)
    assert (licensed.tier, licensed.shows_person, licensed.is_realistic_synthetic) == (
        VisualSourceTier.B_LICENSED_STOCK, True, False,
    )  # fmt: skip
    assert (licensed.has_ledger_row, licensed.licence_state) == (True, LicenceState.ACTIVE)
    assert (licensed.covers_monetized_youtube, licensed.third_party_permission) == (True, "UNKNOWN")


def test_ledger_row_of_another_job_does_not_count(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant
) -> None:
    s = seed(admin, tenant_a)
    other = seed(admin, tenant_a)  # a second job of the same tenant
    lic = seed_licence(admin, tenant_a, covers=True, permission="UNKNOWN")
    reused = seed_asset(admin, tenant_a, lic)
    seed_ledger(admin, tenant_a, reused, lic, other.job, other.task)
    wire = ASSET.from_uuid(reused)
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        here = READ.assets(tx, [wire], JOB.from_uuid(s.job))[wire]
        there = READ.assets(tx, [wire], JOB.from_uuid(other.job))[wire]
    assert here.has_ledger_row is False  # ledgered for another job only: fail closed
    assert there.has_ledger_row is True


def test_assets_of_another_tenant_are_absent(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    asset = ASSET.from_uuid(seed_asset(admin, tenant_a))
    with tenancy.transaction(_ctx(tenant_b)) as tx:
        assert READ.assets(tx, [asset], JOB.new()) == {}


# -- approvals --------------------------------------------------------------------------------
def test_approval_lookups(tenancy: PgTenancy, admin: Conn, tenant_a: Tenant) -> None:
    s = seed(admin, tenant_a)
    release = seed_approval(admin, tenant_a, s.job, "KNOWLEDGE_RELEASE", new_uuid7(), sha("rel"))
    other_kind = seed_approval(admin, tenant_a, s.job, "SCRIPT", new_uuid7(), sha("x"))
    old = seed_approval(admin, tenant_a, s.job, "COPYRIGHT_DOUBT", new_uuid7(), sha("span"))
    new = seed_approval(admin, tenant_a, s.job, "COPYRIGHT_DOUBT", new_uuid7(), sha("span"))
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        subjects = READ.release_approval_subjects(
            tx, [APPROVAL.from_uuid(release), APPROVAL.from_uuid(other_kind), APPROVAL.new()]
        )
        assert subjects == {APPROVAL.from_uuid(release): sha("rel").hex()}
        assert READ.release_approval_subjects(tx, []) == {}
        found = READ.copyright_doubt_approvals(tx, [sha("span").hex(), sha("none").hex()])
        assert found == {sha("span").hex(): APPROVAL.from_uuid(new)}  # the newest of two
        assert APPROVAL.from_uuid(old) != found[sha("span").hex()]
        assert READ.copyright_doubt_approvals(tx, []) == {}
        with pytest.raises(InputInvalidError):
            READ.copyright_doubt_approvals(tx, ["not-hex"])
        with pytest.raises(InputInvalidError):
            READ.copyright_doubt_approvals(tx, ["ab" * 8])


def test_approval_lookups_do_not_cross_tenants(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    s = seed(admin, tenant_a)
    release = seed_approval(admin, tenant_a, s.job, "KNOWLEDGE_RELEASE", new_uuid7(), sha("rel"))
    seed_approval(admin, tenant_a, s.job, "COPYRIGHT_DOUBT", new_uuid7(), sha("span"))
    with tenancy.transaction(_ctx(tenant_b)) as tx:
        assert READ.release_approval_subjects(tx, [APPROVAL.from_uuid(release)]) == {}
        assert READ.copyright_doubt_approvals(tx, [sha("span").hex()]) == {}


# -- QC rows ----------------------------------------------------------------------------------
def test_qc_rows_take_the_latest_row_per_check(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant
) -> None:
    s = seed(admin, tenant_a)
    render, _ = seed_render(admin, tenant_a, s.job)
    empty, _ = seed_render(admin, tenant_a, s.job, "r2")
    seed_qc(admin, tenant_a, s.job, s.task, render, "qc.audio.loudness", "FAIL")
    seed_qc(admin, tenant_a, s.job, s.task, render, "qc.audio.loudness", "PASS")
    seed_qc(
        admin,
        tenant_a,
        s.job,
        s.task,
        render,
        "qc.watermark.visual",
        "SKIPPED",
        "JUDGED_BY_AGENT_16",
    )
    seed_qc(admin, tenant_a, s.job, s.task, render, "qc.other.skipped", "SKIPPED", "not applicable")
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        got = READ.qc_rows(tx, RENDER.from_uuid(render))
        assert got is not None
        assert {r.check_id: r.verdict for r in got} == {
            "qc.audio.loudness": CheckVerdict.PASS,
            "qc.watermark.visual": CheckVerdict.SKIPPED,
            "qc.other.skipped": CheckVerdict.SKIPPED,
        }
        assert READ.judged_qc_check_ids(tx, RENDER.from_uuid(render)) == ("qc.watermark.visual",)
        assert READ.qc_rows(tx, RENDER.from_uuid(empty)) == ()  # a render with no rows yet
        assert READ.qc_rows(tx, RENDER.new()) is None  # no such render
        assert READ.judged_qc_check_ids(tx, RENDER.new()) == ()


def test_thumbnail_qc_rows_are_the_jobs_a11_results(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant
) -> None:
    s = seed(admin, tenant_a)
    render, _ = seed_render(admin, tenant_a, s.job)
    seed_qc(admin, tenant_a, s.job, s.task, None, "a11.q.legibility", "WARN")
    seed_qc(admin, tenant_a, s.job, s.task, None, "a11.q.legibility", "PASS")
    seed_qc(admin, tenant_a, s.job, s.task, None, "a11.q.text_fit", "FAIL")
    seed_qc(admin, tenant_a, s.job, s.task, render, "qc.audio.loudness", "PASS")
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        got = READ.thumbnail_qc_rows(tx, JOB.from_uuid(s.job))
    assert {r.check_id: r.verdict for r in got} == {
        "a11.q.legibility": CheckVerdict.PASS,
        "a11.q.text_fit": CheckVerdict.FAIL,
    }


def test_qc_reads_do_not_cross_tenants(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    s = seed(admin, tenant_a)
    render, _ = seed_render(admin, tenant_a, s.job)
    seed_qc(
        admin,
        tenant_a,
        s.job,
        s.task,
        render,
        "qc.watermark.visual",
        "SKIPPED",
        "JUDGED_BY_AGENT_16",
    )
    seed_qc(admin, tenant_a, s.job, s.task, None, "a11.q.legibility", "PASS")
    with tenancy.transaction(_ctx(tenant_b)) as tx:
        assert READ.qc_rows(tx, RENDER.from_uuid(render)) is None
        assert READ.judged_qc_check_ids(tx, RENDER.from_uuid(render)) == ()
        assert READ.thumbnail_qc_rows(tx, JOB.from_uuid(s.job)) == ()
        assert READ.job(tx, JOB.from_uuid(s.job)) is None
        assert READ.channel(tx, JOB.from_uuid(s.job)) is None


# -- claims -----------------------------------------------------------------------------------
def test_claims_rows_and_their_sensitive_approval(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    s = seed(admin, tenant_a)
    script = seed_script(admin, tenant_a, s.job, s.channel, s.task)
    plain = seed_claim(admin, tenant_a, s.job, script, s.task, "VERIFIED")
    sensitive = seed_claim(admin, tenant_a, s.job, script, s.task, "NEEDS_SUBSTANTIATION")
    approval = seed_approval(admin, tenant_a, s.job, "SENSITIVE_CLAIM", sensitive, sha("claim"))
    wire = [CLAIM.from_uuid(plain), CLAIM.from_uuid(sensitive), CLAIM.from_uuid(new_uuid7())]
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        got = {c.claim_id: c for c in READ.claims(tx, wire)}
        assert READ.claims(tx, []) == ()
    assert set(got) == set(wire[:2])  # the unknown claim is absent (the extractor refuses it)
    assert (got[wire[0]].status, got[wire[0]].sensitive_approval) == (ClaimStatus.VERIFIED, None)
    assert got[wire[1]].sensitive_approval == (APPROVAL.from_uuid(approval), sha("claim").hex())
    assert got[wire[1]].claim_type == "FACTUAL"
    # no citations table and no chart column exist yet (CCR-301): the stricter reading
    assert (got[wire[0]].citation_count, got[wire[0]].chart_data_ref) == (0, None)
    with tenancy.transaction(_ctx(tenant_b)) as tx:
        assert READ.claims(tx, wire) == ()


# -- wiring errors ----------------------------------------------------------------------------
def test_bad_ids_and_foreign_transactions_fail_closed(tenancy: PgTenancy, tenant_a: Tenant) -> None:
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        for call in (
            lambda: READ.channel(tx, "chn_" + str(uuid.uuid4())),
            lambda: READ.job(tx, "garbage"),
            lambda: READ.assets(tx, ["job_" + "0" * 36], JOB.new()),
            lambda: READ.qc_rows(tx, "garbage"),
        ):
            with pytest.raises(InputInvalidError):
                call()
    memory = MemoryTransaction(_ctx(tenant_a))
    with pytest.raises(ConfigInvalidError):
        READ.channel(memory, JOB.new())
    with pytest.raises(ConfigInvalidError):
        READ.claims(memory, [CLAIM.from_uuid(new_uuid7())])


def test_reads_write_nothing(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, packs: None
) -> None:
    s = seed(admin, tenant_a)
    _stages(admin, s, agent_05__script_draft="s05_script", agent_08__asset_sourcing="s08_assets")
    render, _ = seed_render(admin, tenant_a, s.job)
    tables = ("jobs", "channels", "tasks", "renders", "qc_results", "approvals", "claims", "assets")

    def stamp() -> list[Any]:
        """Per table: row count and the sum of the row transaction stamps (changes on any write)."""
        return [
            admin.execute(
                f"SELECT count(*), coalesce(sum(xmin::text::bigint), 0) FROM {t}"  # noqa: S608
            ).fetchone()
            for t in tables
        ]

    before = stamp()
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        READ.channel(tx, JOB.from_uuid(s.job))
        READ.job(tx, JOB.from_uuid(s.job))
        READ.qc_rows(tx, RENDER.from_uuid(render))
        READ.thumbnail_qc_rows(tx, JOB.from_uuid(s.job))
        READ.claims(tx, [])
    assert stamp() == before
