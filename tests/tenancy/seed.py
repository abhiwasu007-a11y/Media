"""One row per TENANT / SHARED-CATALOGUE table for a tenant (04 section 3.7 item 1).

``seed_tenant`` inserts, as the superuser with triggers off (``session_replication_role =
replica``, so guard triggers such as the publish guard do not need a full approval flow), a
consistent row in every table the 3A migrations create. Other lanes add their tables with a module
``tests/tenancy/seed_<name>.py`` that defines ``seed(conn, tenant, world) -> None`` and records each
table it filled in ``world.tables``; ``seed_tenant`` runs every such module. A tenant table without
a seeded row fails the suite.
"""

import hashlib
import importlib
import pkgutil
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from amw_core.ids import new_uuid7
from tests.pg_fixtures import Tenant, ensure_production_type

Conn = psycopg.Connection[tuple[Any, ...]]
SHA = hashlib.sha256(b"seed").digest()


@dataclass
class World:
    tenant: Tenant
    ids: dict[str, uuid.UUID] = field(default_factory=dict)
    tables: set[str] = field(default_factory=set)

    def __getitem__(self, name: str) -> uuid.UUID:
        return self.ids[name]


def ins(
    conn: Conn,
    world: World,
    table: str,
    ref: str | None = None,
    *,
    with_id: bool = True,
    **cols: Any,
) -> None:
    """Insert one row; ``id`` (unless ``with_id=False``) and ``org_id`` are filled if not given."""
    cols.setdefault("org_id", world.tenant.org_uuid)
    if with_id:
        cols.setdefault("id", new_uuid7())
    values = [Jsonb(v) if isinstance(v, dict) else v for v in cols.values()]
    conn.execute(
        sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, cols)),
            sql.SQL(", ").join(sql.Placeholder() * len(cols)),
        ),
        values,
    )
    world.tables.add(table)
    if ref is not None:
        world.ids[ref] = cols["id"]


def ensure_platform_catalogue(conn: Conn) -> None:
    """Platform rows (``org_id IS NULL``) of the SHARED-CATALOGUE tables, once per database."""
    present = conn.execute("SELECT count(*) FROM rule_packs WHERE org_id IS NULL").fetchone()
    if present != (0,):
        return
    gcp = new_uuid7()
    with conn.transaction():
        conn.execute(
            "INSERT INTO rule_packs (id, org_id, key, version, scope, category, always_on,"
            " removable, rules_ref, rules_sha256, status, effective_from) VALUES"
            " (%s, NULL, 'rp.youtube_general', 1, 'PLATFORM', 'youtube_general', true, false,"
            " 'amw-blob://platform/rule_packs/ytg.md', %s, 'ACTIVE', now())",
            (new_uuid7(), SHA),
        )
        conn.execute(
            "INSERT INTO licences (id, org_id, licence_key, vendor, source_type, licence_name,"
            " third_party_permission, starts_at, state, terms_ref, terms_sha256) VALUES"
            " (%s, NULL, 'platform-stock', 'v', 'PAID_STOCK', 'std', 'PERMITTED', now(),"
            " 'ACTIVE', 'amw-blob://platform/licences/t.pdf', %s)",
            (new_uuid7(), SHA),
        )
        conn.execute(
            "INSERT INTO gcp_projects (id, org_id, ownership, project_label,"
            " oauth_verification_status, api_audit_status, quota_limits) VALUES"
            " (%s, NULL, 'PLATFORM', 'platform', 'NOT_STARTED', 'NOT_STARTED', '{}')",
            (gcp,),
        )
        conn.execute(
            "INSERT INTO circuit_breakers (id, org_id, provider, operation_class, credential_scope,"
            " state, window_started_at) VALUES (%s, NULL, 'seed', 'llm.completion', 'platform',"
            " 'CLOSED', now())",
            (new_uuid7(),),
        )
        conn.execute(
            "INSERT INTO quota_usage (org_id, gcp_project_id, pt_date, bucket, units_used,"
            " units_reserved, units_limit) VALUES (NULL, %s, current_date, 'DEFAULT', 0, 0, 1)",
            (gcp,),
        )


def _core(conn: Conn, w: World) -> None:
    t = w.tenant
    now = datetime.now(UTC)
    org = t.org_uuid
    w.tables.update({"organisations", "workspaces"})
    w.ids["workspace"] = t.workspace_uuid
    user = new_uuid7()
    conn.execute(
        "INSERT INTO users (id, email, display_name, status) VALUES (%s, %s, 'Owner', 'ACTIVE')",
        (user, f"{user.hex}@example.invalid"),
    )
    w.ids["user"] = user
    ins(conn, w, "memberships", user_id=user, role="REVIEWER_APPROVER", status="ACTIVE")
    ins(
        conn,
        w,
        "invitations",
        email=f"i{user.hex}@example.invalid",
        role="VIEWER",
        token_hash=hashlib.sha256(user.bytes).digest(),
        state="PENDING",
        invited_by=user,
        expires_at=now + timedelta(days=1),
    )
    ins(
        conn,
        w,
        "org_controls",
        key="emergency_stop",
        value={"on": False},
        updated_by="sys_operator",
    )
    ins(
        conn,
        w,
        "org_production_types",
        production_type_key="CHANNEL_LONG_FORM",
        enabled_version=1,
        enabled=True,
    )
    ins(
        conn,
        w,
        "rule_packs",
        "pack",
        key="rp.tenant_brand_safety",
        version=1,
        scope="TENANT",
        category="brand_safety",
        always_on=False,
        removable=True,
        rules_ref=f"amw-blob://org_{org}/rule_packs/b.md",
        rules_sha256=SHA,
        status="ACTIVE",
        effective_from=now,
    )
    ins(
        conn,
        w,
        "compliance_profiles",
        "profile",
        workspace_id=t.workspace_uuid,
        name="p",
        version=1,
        status="ACTIVE",
    )
    ins(
        conn,
        w,
        "compliance_profile_rule_packs",
        profile_id=w["profile"],
        rule_pack_id=w["pack"],
        is_mandatory=False,
    )
    ins(
        conn,
        w,
        "gcp_projects",
        "gcp",
        ownership="CLIENT_OWNED",
        project_label="client",
        oauth_verification_status="NOT_STARTED",
        api_audit_status="NOT_STARTED",
        quota_limits={},
    )
    ins(
        conn,
        w,
        "channels",
        "channel",
        workspace_id=t.workspace_uuid,
        platform="YOUTUBE",
        title="c",
        language="en",
        category="finance",
        status="DRAFT",
        compliance_profile_id=w["profile"],
        gcp_project_id=w["gcp"],
    )
    ins(
        conn,
        w,
        "projects",
        "project",
        workspace_id=t.workspace_uuid,
        channel_id=w["channel"],
        name="p",
        kind="SERIES",
        status="ACTIVE",
    )
    job = new_uuid7()
    ins(
        conn,
        w,
        "jobs",
        "job",
        id=job,
        workspace_id=t.workspace_uuid,
        project_id=w["project"],
        channel_id=w["channel"],
        production_type_key="CHANNEL_LONG_FORM",
        production_type_version=1,
        language="en",
        priority=2,
        correlation_id=new_uuid7(),
        idempotency_key="idk_" + job.hex.ljust(64, "0"),
        requested_by="agent_01",
        currency="INR",
    )
    tasks = []
    for n in range(2):
        task = new_uuid7()
        tasks.append(task)
        ins(
            conn,
            w,
            "tasks",
            f"task{n}",
            id=task,
            job_id=job,
            task_type="agent_05.script_draft",
            agent_id="agent_05",
            priority=2,
            resource_class="AI_IO",
            required_capabilities=["llm"],
            idempotency_key="idk_" + task.hex.ljust(64, "0"),
            payload_schema="agent_05.script_draft.input",
            payload_schema_version="1.0.0",
            resource_budget={"max_cost_micros": 1, "currency": "INR", "max_wall_ms": 1},
            max_attempts=3,
        )
    w.ids["task"] = tasks[0]
    ins(conn, w, "task_dependencies", with_id=False, task_id=tasks[1], depends_on_task_id=tasks[0])
    worker = new_uuid7()
    conn.execute(
        "INSERT INTO workers (id, logical_name, capabilities, resource_classes, max_concurrency,"
        " status, software_version) VALUES (%s, %s, '{llm}', '{AI_IO}', 1, 'IDLE', 't')",
        (worker, f"seed-{worker.hex[-10:]}"),
    )
    w.ids["worker"] = worker
    ins(
        conn,
        w,
        "task_attempts",
        "attempt",
        task_id=tasks[0],
        attempt_no=1,
        worker_id=worker,
        started_at=now,
    )
    ins(
        conn,
        w,
        "checkpoints",
        "checkpoint",
        task_id=tasks[0],
        attempt_id=w["attempt"],
        seq=1,
        step_key="s",
        state_ref=f"amw-blob://org_{org}/c",
        state_sha256=SHA,
        completed_effects=[],
        is_latest=True,
    )
    ins(
        conn,
        w,
        "task_queue",
        task_id=tasks[0],
        job_id=job,
        queue_name="ai",
        status="DONE",
        priority=2,
        resource_class="AI_IO",
        required_capabilities=["llm"],
        scheduled_at=now,
        fair_share_key=f"org_{org}",
        envelope={"seed": True},
    )
    ins(
        conn,
        w,
        "idempotency_keys",
        with_id=False,
        key="idk_" + tasks[0].hex.ljust(64, "1"),
        scope="db.output",
        request_sha256=SHA,
        status="COMPLETED",
        task_id=tasks[0],
    )
    ins(
        conn,
        w,
        "state_transitions",
        entity_kind="TASK",
        entity_id=tasks[0],
        transition_id="T01",
        to_state="PENDING",
        actor_kind="AGENT",
        actor_ref="agent_01",
        authority="state_machine.T01",
        state_version_after=1,
        correlation_id=new_uuid7(),
        occurred_at=now,
        audit_seq=1,
    )
    w.tables.add("state_transitions_default")
    ins(
        conn,
        w,
        "message_log",
        sender="agent_01",
        receiver="agent_05",
        job_id=job,
        task_id=tasks[0],
        payload_schema="amw.task_input",
        payload_uri=f"amw-blob://org_{org}/m",
        payload_sha256=SHA,
        priority=2,
        sent_at=now,
        correlation_id=new_uuid7(),
        schema_version="1.0.0",
    )
    w.tables.add("message_log_default")
    ins(
        conn,
        w,
        "message_receipts",
        with_id=False,
        message_id=new_uuid7(),
        receiver="agent_05",
        processed_at=now,
    )
    ins(
        conn,
        w,
        "approvals",
        "approval",
        job_id=job,
        kind="FINAL_VIDEO",
        subject_kind="render",
        subject_id=job,
        subject_sha256=SHA,
        state="APPROVED",
        workflow_key="owner_one_tap",
        current_step=1,
        managed_service=False,
        requested_by="svc_s07",
        review_code=job.hex[-6:],
    )
    ins(
        conn,
        w,
        "dead_letter",
        task_id=tasks[1],
        job_id=job,
        failure_class="AGENT",
        error_code="AGENT.CRASH",
        reason="r",
        error={"code": "AGENT.CRASH"},
        payload_ref=f"amw-blob://org_{org}/p",
        payload_sha256=SHA,
        retry_history=Jsonb([]),
        escalation_level="L2",
        replay_approval_id=w["approval"],
    )
    ins(
        conn,
        w,
        "circuit_breakers",
        provider="seed",
        operation_class="youtube.upload",
        credential_scope=f"gcp_{w['gcp']}",
        state="CLOSED",
        window_started_at=now,
    )
    ins(
        conn,
        w,
        "memory_items",
        scope="CHANNEL",
        workspace_id=t.workspace_uuid,
        channel_id=w["channel"],
        key="k",
        value={"v": 1},
        provenance_ref="x",
        created_by="agent_04",
    )
    ins(
        conn,
        w,
        "scripts",
        "script",
        job_id=job,
        channel_id=w["channel"],
        language="en",
        version=1,
        iteration=0,
        status="DRAFT",
        body_ref=f"amw-blob://org_{org}/s",
        content_sha256=SHA,
        segment_count=1,
        word_count=1,
        created_by_task_id=tasks[0],
    )
    ins(
        conn,
        w,
        "licences",
        "licence",
        licence_key="own",
        vendor="v",
        source_type="PAID_STOCK",
        licence_name="n",
        covers_monetized_youtube=True,
        third_party_permission="PERMITTED",
        starts_at=now,
        state="ACTIVE",
        terms_ref=f"amw-blob://org_{org}/t",
        terms_sha256=SHA,
    )
    ins(
        conn,
        w,
        "assets",
        "asset",
        workspace_id=t.workspace_uuid,
        kind="IMAGE",
        visual_source_tier="B_LICENSED_STOCK",
        storage_ref=f"amw-blob://org_{org}/a",
        content_sha256=SHA,
        size_bytes=1,
        media_type="image/png",
        source_type="PAID_STOCK",
        licence_id=w["licence"],
        is_realistic_synthetic=False,
        depicts_real_person=False,
        status="ACTIVE",
    )
    ins(
        conn,
        w,
        "voices",
        display_name="v",
        kind="PROVIDER_STOCK",
        provider="p",
        languages=["en"],
        licence_id=w["licence"],
        presenter_kind="NEUTRAL_NARRATION",
        status="ACTIVE",
    )
    ins(
        conn,
        w,
        "renders",
        "render",
        job_id=job,
        script_id=w["script"],
        kind="MASTER",
        preset_key="yt_master_1080p",
        version=1,
        timeline_sha256=SHA,
        width_px=1920,
        height_px=1080,
        fps_num=30,
        fps_den=1,
        video_codec="h264",
        audio_codec="aac",
        duration_ms=1,
        size_bytes=1,
        storage_ref=f"amw-blob://org_{org}/r",
        content_sha256=SHA,
        status="COMPLETE",
        worker_id=worker,
    )
    ins(
        conn,
        w,
        "licence_ledger",
        asset_id=w["asset"],
        licence_id=w["licence"],
        job_id=job,
        render_id=w["render"],
        task_id=tasks[0],
        usage_kind="IMAGE",
        recorded_by="agent_08",
    )
    ins(
        conn,
        w,
        "owner_instruction_evidence",
        "evidence",
        job_id=job,
        approval_id=w["approval"],
        step_no=1,
        record_kind="CONTRIBUTION",
        subject_kind="render",
        subject_id=job,
        source_kind="OWNER_CHAT_MESSAGE",
        session_id="s",
        event_uuid=str(uuid.uuid4()),
        quote="add an example",
        message_at=now,
        state="PENDING_VERIFICATION",
        recorded_by="sys_operator",
        on_behalf_of=user,
        evidence_sha256=SHA,
    )
    ins(
        conn,
        w,
        "approval_steps",
        approval_id=w["approval"],
        step_no=1,
        required_role="REVIEWER_APPROVER",
        state="PENDING",
    )
    ins(
        conn,
        w,
        "editorial_contributions",
        job_id=job,
        approval_id=w["approval"],
        contributor_user_id=user,
        approval_channel="OWNER_CHAT_OPERATOR",
        recorded_by="sys_operator",
        evidence_id=w["evidence"],
        type="EXAMPLE",
        description="add an example",
    )
    ins(
        conn,
        w,
        "quality_scores",
        job_id=job,
        subject_kind="render",
        subject_id=w["render"],
        subject_sha256=SHA,
        rubric_version="r1",
        dimension="COMPLIANCE",
        max_points=5,
        points=5,
        scorer_kind="LLM_JUDGE",
        scorer_ref="agent_16",
    )
    ins(
        conn,
        w,
        "qc_results",
        job_id=job,
        task_id=tasks[0],
        render_id=w["render"],
        check_id="qc.audio.integrated_lufs",
        kind="DETERMINISTIC",
        verdict="PASS",
        blocking=True,
        message="ok",
    )
    ins(
        conn,
        w,
        "compliance_verdicts",
        "verdict",
        job_id=job,
        subject_kind="render",
        subject_id=w["render"],
        subject_sha256=SHA,
        verdict="ALLOWED",
        rationale="ok",
        decided_by="agent_16",
        is_final=True,
    )
    ins(
        conn,
        w,
        "publications",
        job_id=job,
        render_id=w["render"],
        render_sha256=SHA,
        destination_kind="FILE_DELIVERY",
        state="DELIVERED",
        approval_id=w["approval"],
        authorisation_verdict_id=w["verdict"],
        idempotency_key="idk_" + job.hex.ljust(64, "2"),
    )
    ins(
        conn,
        w,
        "notifications",
        user_id=user,
        channel="IN_APP",
        template_key="t",
        subject_kind="approval",
        subject_id=w["approval"],
        status="QUEUED",
        idempotency_key=f"n-{job.hex}",
    )
    ins(
        conn,
        w,
        "tenant_data_keys",
        "dek",
        wrapped_key=b"\1" * 32,
        kek_ref="env:KEK",
        algorithm="aead",
        status="ACTIVE",
    )
    ins(
        conn,
        w,
        "oauth_tokens",
        channel_id=w["channel"],
        gcp_project_id=w["gcp"],
        scopes=["youtube.upload"],
        granted_by_user_id=user,
        refresh_token_ct=b"\2",
        refresh_token_nonce=b"\3",
        data_key_id=w["dek"],
        status="ACTIVE",
    )
    ins(
        conn,
        w,
        "quota_usage",
        with_id=False,
        gcp_project_id=w["gcp"],
        pt_date=now.date(),
        bucket="DEFAULT",
        units_used=0,
        units_reserved=0,
        units_limit=1,
    )


def seed_tenant(conn: Conn, tenant: Tenant) -> World:
    ensure_production_type(conn)
    ensure_platform_catalogue(conn)
    world = World(tenant)
    with conn.transaction():
        conn.execute("SET LOCAL session_replication_role = replica")
        _core(conn, world)
        for mod in pkgutil.iter_modules([str(Path(__file__).parent)]):
            if mod.name.startswith("seed_"):
                importlib.import_module(f"tests.tenancy.{mod.name}").seed(conn, tenant, world)
    return world
