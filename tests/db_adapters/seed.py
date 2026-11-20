"""Rows for the DB adapter tests, written as the superuser (setup only; the code under test never
runs with these rights). Synthetic values only: no library text, no real keys."""

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

import psycopg

from amw_core.ids import new_uuid7
from amw_core.interfaces.tenancy_context import TenantContext
from tests.pg_fixtures import Tenant

Conn = psycopg.Connection[tuple[Any, ...]]


def sha(label: str) -> bytes:
    return hashlib.sha256(label.encode()).digest()


@dataclass(frozen=True, slots=True)
class Seeded:
    tenant: Tenant
    channel: uuid.UUID
    job: uuid.UUID
    task: uuid.UUID

    @property
    def context(self) -> TenantContext:
        from amw_core.ids import ActorRef

        return TenantContext(self.tenant.org_id, ActorRef("agent_16"))


def seed_channel(
    conn: Conn, t: Tenant, *, category: str = "philosophy", audience: str | None = None
) -> uuid.UUID:
    channel = new_uuid7()
    conn.execute(
        "INSERT INTO channels (id, org_id, workspace_id, platform, title, language, category,"
        " status, audience_kind) VALUES (%s, %s, %s, 'YOUTUBE', 'TEST channel', 'mr-IN', %s,"
        " 'DRAFT', %s)",
        (channel, t.org_uuid, t.workspace_uuid, category, audience),
    )
    return channel


def seed_production_type(conn: Conn) -> None:
    record = json.dumps({"key": "CHANNEL_LONG_FORM", "version": 2})
    conn.execute(
        "INSERT INTO production_types (id, key, version, status, tier, record, record_sha256)"
        " VALUES (%s, 'CHANNEL_LONG_FORM', 2, 'IN_DEVELOPMENT', 'TIER_0', %s, %s)"
        " ON CONFLICT (key, version) DO NOTHING",
        (new_uuid7(), record, sha("pt")),
    )


def seed_job(
    conn: Conn,
    t: Tenant,
    channel: uuid.UUID | None,
    *,
    monetized: bool = True,
    language: str = "mr-IN",
) -> uuid.UUID:
    seed_production_type(conn)
    job = new_uuid7()
    conn.execute(
        "INSERT INTO jobs (id, org_id, workspace_id, channel_id, production_type_key,"
        " production_type_version, language, priority, correlation_id, idempotency_key,"
        " requested_by, currency, monetized_destination)"
        " VALUES (%s, %s, %s, %s, 'CHANNEL_LONG_FORM', 2, %s, 2, %s, %s, 'sys_operator', 'INR',"
        " %s)",
        (
            job, t.org_uuid, t.workspace_uuid, channel, language, new_uuid7(),
            "idk_" + uuid.uuid4().hex * 2, monetized,
        ),
    )  # fmt: skip
    return job


def seed_task(
    conn: Conn,
    t: Tenant,
    job: uuid.UUID,
    *,
    task_type: str = "agent_05.script_draft",
    stage_id: str | None = None,
    state: str | None = None,
) -> uuid.UUID:
    task = new_uuid7()
    conn.execute(
        "INSERT INTO tasks (id, org_id, job_id, task_type, agent_id, priority, resource_class,"
        " required_capabilities, idempotency_key, payload_schema, payload_schema_version,"
        " resource_budget, max_attempts, stage_id)"
        " VALUES (%s, %s, %s, %s, %s, 2, 'AI_IO', '{llm}', %s, 'x.input', '1.0.0',"
        " '{}', 5, %s)",
        (
            task,
            t.org_uuid,
            job,
            task_type,
            task_type.split(".")[0],
            "idk_" + uuid.uuid4().hex * 2,
            stage_id,
        ),
    )
    if state is not None:
        conn.execute("UPDATE tasks SET state = %s WHERE id = %s", (state, task))
    return task


def seed(conn: Conn, t: Tenant, **channel_kw: Any) -> Seeded:
    channel = seed_channel(conn, t, **channel_kw)
    job = seed_job(conn, t, channel)
    return Seeded(t, channel, job, seed_task(conn, t, job))


def seed_render(
    conn: Conn, t: Tenant, job: uuid.UUID, label: str = "r1"
) -> tuple[uuid.UUID, bytes]:
    render, digest = new_uuid7(), sha("render-" + label)
    conn.execute(
        "INSERT INTO renders (id, org_id, job_id, kind, preset_key, version, timeline_sha256,"
        " width_px, height_px, fps_num, fps_den, video_codec, audio_codec, duration_ms,"
        " size_bytes, storage_ref, content_sha256, status)"
        " VALUES (%s, %s, %s, 'MASTER', 'p', 1, %s, 1920, 1080, 30, 1, 'h264', 'aac', 1000, 1,"
        " 'amw-blob://x', %s, 'COMPLETE')",
        (render, t.org_uuid, job, sha("tl" + label), digest),
    )
    return render, digest


def seed_qc(
    conn: Conn,
    t: Tenant,
    job: uuid.UUID,
    task: uuid.UUID,
    render: uuid.UUID | None,
    check_id: str,
    verdict: str = "PASS",
    message: str = "ok",
) -> None:
    conn.execute(
        "INSERT INTO qc_results (id, org_id, job_id, task_id, render_id, check_id, kind, verdict,"
        " blocking, message) VALUES (%s, %s, %s, %s, %s, %s, 'DETERMINISTIC', %s, false, %s)",
        (new_uuid7(), t.org_uuid, job, task, render, check_id, verdict, message),
    )


def seed_licence(
    conn: Conn,
    t: Tenant,
    *,
    state: str = "ACTIVE",
    covers: bool | None = True,
    permission: str = "PERMITTED",
) -> uuid.UUID:
    lic = new_uuid7()
    conn.execute(
        "INSERT INTO licences (id, org_id, licence_key, vendor, source_type, licence_name,"
        " covers_monetized_youtube, third_party_permission, starts_at, state, terms_ref,"
        " terms_sha256) VALUES (%s, %s, %s, 'v', 'PAID_STOCK', 'n', %s, %s, now(), %s, 'x', %s)",
        (lic, t.org_uuid, "k" + lic.hex[-8:], covers, permission, state, sha("terms")),
    )
    return lic


def seed_asset(
    conn: Conn,
    t: Tenant,
    licence: uuid.UUID | None = None,
    *,
    person: bool = False,
    tier: str = "B_LICENSED_STOCK",
) -> uuid.UUID:
    asset = new_uuid7()
    conn.execute(
        "INSERT INTO assets (id, org_id, kind, visual_source_tier, storage_ref, content_sha256,"
        " size_bytes, media_type, source_type, licence_id, is_realistic_synthetic,"
        " depicts_real_person, status) VALUES (%s, %s, 'IMAGE', %s, 'amw-blob://x', %s, 1,"
        " 'image/png', %s, %s, false, %s, 'ACTIVE')",
        (
            asset, t.org_uuid, tier, sha("asset" + asset.hex),
            "PAID_STOCK" if licence else "CODE_GENERATED", licence, person,
        ),
    )  # fmt: skip
    return asset


def seed_ledger(
    conn: Conn, t: Tenant, asset: uuid.UUID, licence: uuid.UUID, job: uuid.UUID, task: uuid.UUID
) -> None:
    conn.execute(
        "INSERT INTO licence_ledger (id, org_id, asset_id, licence_id, job_id, task_id, usage_kind,"
        " recorded_by) VALUES (%s, %s, %s, %s, %s, %s, 'IMAGE', 'agent_08')",
        (new_uuid7(), t.org_uuid, asset, licence, job, task),
    )


def seed_approval(
    conn: Conn,
    t: Tenant,
    job: uuid.UUID,
    kind: str,
    subject_id: uuid.UUID,
    digest: bytes,
    subject_kind: str = "claim",
) -> uuid.UUID:
    approval = new_uuid7()
    conn.execute(
        "INSERT INTO approvals (id, org_id, job_id, kind, subject_kind, subject_id,"
        " subject_sha256, state, workflow_key, current_step, managed_service, requested_by,"
        " review_code) VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING', 'owner_one_tap', 1, false,"
        " 'svc_s07', %s)",
        (
            approval,
            t.org_uuid,
            job,
            kind,
            subject_kind,
            subject_id,
            digest,
            "RC" + approval.hex[-8:],
        ),
    )
    return approval


def seed_claim(
    conn: Conn,
    t: Tenant,
    job: uuid.UUID,
    script: uuid.UUID,
    task: uuid.UUID,
    status: str = "VERIFIED",
) -> uuid.UUID:
    claim = new_uuid7()
    conn.execute(
        "INSERT INTO claims (id, org_id, script_id, job_id, segment_id, char_start, char_end,"
        " quote, normalized_claim, claim_type, time_reference_kind, status, rule_flags,"
        " proposed_verdict, requires_citation, extracted_by_task_id)"
        " VALUES (%s, %s, %s, %s, %s, 0, 5, 'q', 'c', 'FACTUAL', 'TIMELESS', %s, '[]',"
        " 'ALLOWED', false, %s)",
        (claim, t.org_uuid, script, job, "s" + claim.hex[-6:], status, task),
    )
    return claim


def seed_script(
    conn: Conn, t: Tenant, job: uuid.UUID, channel: uuid.UUID, task: uuid.UUID, version: int = 1
) -> uuid.UUID:
    script = new_uuid7()
    conn.execute(
        "INSERT INTO scripts (id, org_id, job_id, channel_id, language, version, iteration, status,"
        " body_ref, content_sha256, segment_count, word_count, created_by_task_id)"
        " VALUES (%s, %s, %s, %s, 'mr-IN', %s, 1, 'DRAFT', 'amw-blob://x', %s, 1, 1, %s)",
        (script, t.org_uuid, job, channel, version, sha("script" + script.hex), task),
    )
    return script
