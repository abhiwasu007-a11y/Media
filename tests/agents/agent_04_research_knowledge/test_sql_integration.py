"""``library/sql.py`` against a real PostgreSQL 16 (own scratch database, RLS forced).

Skipped when ``AMW_TEST_DATABASE_URL`` is unset. The URL only locates the server and the admin
role: this test creates its own database ``agent04_scratch_<random>`` and a non-superuser role
without BYPASSRLS, runs everything there and drops both. It never touches ``amw_l1a`` or
``amw_l1b``. The scratch tables follow 04 section 5.10 and 5.16 (own copy of the columns Agent 04
reads and writes; L1a owns the real migrations).
"""
# ruff: noqa: E501, PT018

import hashlib
import json
import os
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest

from agent_04_research_knowledge.errors import IdempotencyConflict, InputInvalid
from agent_04_research_knowledge.guards.restricted import (
    ChunkMeta,
    RestrictedCollectionGate,
    TopicFlags,
    release_subject_sha256,
)
from agent_04_research_knowledge.library.models import ChunkRow, SearchRequest, TenantScope
from agent_04_research_knowledge.library.search import FtsQueryBuilder
from agent_04_research_knowledge.library.sql import SqlKnowledgeLibrary
from agent_04_research_knowledge.steps.retrieve import _LibraryApprovals
from amw_core.enums import KnowledgeSourceStatus, VideoKind
from amw_core.ids import Prefix, format_id

URL = os.environ.get("AMW_TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not URL, reason="AMW_TEST_DATABASE_URL is not set (needs a local PostgreSQL 16)"
    ),
]
psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row  # noqa: E402

APP_ROLE = "agent04_scratch_app"
DDL = """
CREATE TABLE knowledge_collections (id uuid PRIMARY KEY, org_id uuid NOT NULL, channel_id uuid NOT NULL,
  collection_key text NOT NULL, title text NOT NULL, restricted boolean NOT NULL DEFAULT false,
  UNIQUE (org_id, id), UNIQUE (org_id, channel_id, collection_key));
CREATE TABLE approvals (id uuid PRIMARY KEY, org_id uuid NOT NULL, kind text NOT NULL, state text NOT NULL,
  subject_kind text NOT NULL, subject_id uuid NOT NULL, subject_sha256 bytea, subject_ref text, UNIQUE (org_id, id));
CREATE TABLE knowledge_sources (id uuid PRIMARY KEY, org_id uuid NOT NULL, channel_id uuid NOT NULL,
  collection_id uuid NOT NULL, kind text NOT NULL, title text NOT NULL, author text, edition text,
  language text NOT NULL, ownership text NOT NULL, storage_ref text NOT NULL DEFAULT 'x',
  content_sha256 bytea NOT NULL, size_bytes bigint NOT NULL, status text NOT NULL, ingest_version int NOT NULL,
  reliability_score numeric(4,3), release_approval_id uuid, credit_in_description boolean NOT NULL DEFAULT true,
  UNIQUE (org_id, id), UNIQUE (org_id, channel_id, content_sha256),
  FOREIGN KEY (org_id, collection_id) REFERENCES knowledge_collections (org_id, id));
CREATE TABLE knowledge_chunks (id uuid PRIMARY KEY, org_id uuid NOT NULL, channel_id uuid NOT NULL,
  source_id uuid NOT NULL, collection_id uuid NOT NULL, ingest_version int NOT NULL, chunk_no int NOT NULL,
  extraction_method text NOT NULL DEFAULT 'TEXT_LAYER', ocr_confidence numeric(4,3), release_approval_id uuid,
  chapter text, section text, page_from int, page_to int, language text NOT NULL, body text NOT NULL,
  body_sha256 bytea NOT NULL, search_tsv tsvector, token_count int,
  UNIQUE (org_id, source_id, ingest_version, chunk_no),
  FOREIGN KEY (org_id, source_id) REFERENCES knowledge_sources (org_id, id));
CREATE INDEX ON knowledge_chunks USING gin (search_tsv);
"""
TABLES = ("knowledge_collections", "approvals", "knowledge_sources", "knowledge_chunks")


def _dsn(db: str, user: str | None = None, password: str | None = None) -> str:
    assert URL
    p = urlsplit(URL)
    netloc = p.netloc
    if user:
        netloc = f"{user}:{password}@{p.hostname}" + (f":{p.port}" if p.port else "")
    return urlunsplit((p.scheme, netloc, "/" + db, "", ""))


@pytest.fixture(scope="module")
def scratch() -> Iterator[dict[str, str]]:
    db = "agent04_scratch_" + uuid.uuid4().hex[:10]
    password = uuid.uuid4().hex
    admin = psycopg.connect(_dsn("postgres"), autocommit=True)
    admin.execute(f'CREATE DATABASE "{db}"')
    exists = admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,)).fetchone()
    if exists is None:
        admin.execute(f"CREATE ROLE {APP_ROLE} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '{password}'")
    admin.execute(f"ALTER ROLE {APP_ROLE} PASSWORD '{password}'")
    owner = psycopg.connect(_dsn(db), autocommit=True)
    owner.execute(DDL)
    for t in TABLES:
        owner.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        owner.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        owner.execute(
            f"CREATE POLICY tenant ON {t} USING (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid) "
            f"WITH CHECK (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid)"
        )
        owner.execute(f"GRANT SELECT, INSERT, UPDATE ON {t} TO {APP_ROLE}")
    try:
        yield {"db": db, "password": password}
    finally:
        owner.close()
        admin.execute(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
        admin.execute(f"DROP ROLE IF EXISTS {APP_ROLE}")
        admin.close()


class PgRunner:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def rows(self, sql: str, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        return self._conn.execute(sql, params).fetchall()  # type: ignore[no-any-return]

    def execute(self, sql: str, params: Mapping[str, Any]) -> int:
        return int(self._conn.execute(sql, params).rowcount)


def make_library(scratch: dict[str, str], documents: Any = None) -> SqlKnowledgeLibrary:
    @contextmanager
    def factory(scope: TenantScope) -> Iterator[PgRunner]:
        with (
            psycopg.connect(
                _dsn(scratch["db"], APP_ROLE, scratch["password"]), row_factory=dict_row
            ) as conn,
            conn.transaction(),
        ):
            org = uuid.UUID(scope.org_id.split("_", 1)[1])
            conn.execute("SELECT set_config('app.org_id', %s, true)", (str(org),))
            yield PgRunner(conn)

    return SqlKnowledgeLibrary(factory, FtsQueryBuilder({"en": "english"}, "simple"), documents)


class Tenant:
    """One org/channel with ids in both wire and uuid form, seeded through the owner connection."""

    def __init__(self, scratch: dict[str, str]) -> None:
        self.conn = psycopg.connect(_dsn(scratch["db"]), autocommit=True)
        self.org, self.channel = uuid.uuid7(), uuid.uuid7()
        self.scope = TenantScope(
            str(format_id(Prefix.ORGANISATION, self.org)),
            str(format_id(Prefix.CHANNEL, self.channel)),
        )

    def wire(self, prefix: Prefix, value: uuid.UUID) -> str:
        return str(format_id(prefix, value))

    def collection(self, restricted: bool = False) -> uuid.UUID:
        cid = uuid.uuid7()
        self.conn.execute(
            "INSERT INTO knowledge_collections VALUES (%s,%s,%s,%s,%s,%s)",
            (cid, self.org, self.channel, f"col_{cid.hex[-10:]}", "t", restricted),
        )
        return cid

    def source(
        self,
        collection: uuid.UUID,
        *,
        release: uuid.UUID | None = None,
        status: str = "INDEXED",
        ownership: str = "OWNED_COPY",
        version: int = 1,
    ) -> uuid.UUID:
        sid = uuid.uuid7()
        self.conn.execute(
            "INSERT INTO knowledge_sources (id, org_id, channel_id, collection_id, kind, title, language, ownership, content_sha256, size_bytes, status, ingest_version, release_approval_id) "
            "VALUES (%s,%s,%s,%s,'BOOK','T','en',%s,%s,1,%s,%s,%s)",
            (
                sid,
                self.org,
                self.channel,
                collection,
                ownership,
                hashlib.sha256(sid.bytes).digest(),
                status,
                version,
                release,
            ),
        )
        return sid

    def chunk(
        self,
        source: uuid.UUID,
        collection: uuid.UUID,
        body: str,
        no: int,
        *,
        release: uuid.UUID | None = None,
        version: int = 1,
    ) -> uuid.UUID:
        kid = uuid.uuid7()
        self.conn.execute(
            "INSERT INTO knowledge_chunks (id, org_id, channel_id, source_id, collection_id, ingest_version, chunk_no, language, body, body_sha256, search_tsv, release_approval_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'en',%s,%s,to_tsvector('english', %s),%s)",
            (
                kid,
                self.org,
                self.channel,
                source,
                collection,
                version,
                no,
                body,
                hashlib.sha256(body.encode()).digest(),
                body,
                release,
            ),
        )
        return kid

    def approval(
        self,
        *,
        kind: str = "KNOWLEDGE_RELEASE",
        state: str = "APPROVED",
        subject_kind: str,
        subject_id: uuid.UUID,
        sha: bytes | None = None,
        ref: str | None = None,
    ) -> uuid.UUID:
        aid = uuid.uuid7()
        self.conn.execute(
            "INSERT INTO approvals VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (aid, self.org, kind, state, subject_kind, subject_id, sha, ref),
        )
        return aid


@pytest.fixture
def tenant(scratch: dict[str, str]) -> Iterator[Tenant]:
    t = Tenant(scratch)
    yield t
    t.conn.close()


BODY = "A stop loss closes a position once price reaches a chosen level."


def test_search_load_status_filters_and_replay(scratch: dict[str, str], tenant: Tenant) -> None:
    lib = make_library(scratch)
    col = tenant.collection()
    src = tenant.source(col)
    chunk = tenant.chunk(src, col, BODY, 1)
    for bad in (
        {"status": "RETIRED"},
        {"status": "FAILED"},
        {"ownership": "UNKNOWN"},
        {"version": 2},
    ):
        s = tenant.source(col, **bad)
        tenant.chunk(s, col, BODY, 1)
    scope = tenant.scope
    col_w = tenant.wire(Prefix.KNOWLEDGE_COLLECTION, col)
    hits = lib.search(scope, SearchRequest("stop loss", "en", frozenset({col_w}), 10))
    assert [h.chunk_id for h in hits] == [tenant.wire(Prefix.KNOWLEDGE_CHUNK, chunk)]
    assert hits[0].rank > 0 and not hits[0].collection_restricted
    assert (
        lib.search(
            scope,
            SearchRequest(
                "stop loss",
                "en",
                frozenset({col_w}),
                10,
                frozenset({tenant.wire(Prefix.KNOWLEDGE_SOURCE, uuid.uuid7())}),
            ),
        )
        == []
    )
    rows = lib.load_chunks(scope, [hits[0].chunk_id])
    assert rows[0].body == BODY and rows[0].body_sha256 == hashlib.sha256(BODY.encode()).hexdigest()
    assert (
        lib.search(
            scope,
            SearchRequest("stop'; DROP TABLE knowledge_chunks; --", "en", frozenset({col_w}), 5),
        )
        == []
    )
    # insert: replay is a no-op, a primary-key clash is typed, a foreign scope is refused
    src_w = tenant.wire(Prefix.KNOWLEDGE_SOURCE, src)
    new = ChunkRow(
        tenant.wire(Prefix.KNOWLEDGE_CHUNK, uuid.uuid7()),
        scope.org_id,
        scope.channel_id,
        src_w,
        col_w,
        3,
        1,
        None,
        None,
        None,
        None,
        "en",
        "text one",
        hashlib.sha256(b"text one").hexdigest(),
    )
    assert lib.insert_chunks(scope, [new]).written == 1
    again = lib.insert_chunks(scope, [new])
    assert (again.written, again.skipped_existing) == (0, 1)
    clash = ChunkRow(
        new.chunk_id,
        scope.org_id,
        scope.channel_id,
        src_w,
        col_w,
        3,
        2,
        None,
        None,
        None,
        None,
        "en",
        "t2",
        hashlib.sha256(b"t2").hexdigest(),
    )
    with pytest.raises(IdempotencyConflict):
        lib.insert_chunks(scope, [clash])
    other_channel = ChunkRow(
        new.chunk_id,
        scope.org_id,
        "chn_" + str(uuid.uuid7()),
        src_w,
        col_w,
        3,
        9,
        None,
        None,
        None,
        None,
        "en",
        "t3",
        hashlib.sha256(b"t3").hexdigest(),
    )
    with pytest.raises(InputInvalid):
        lib.insert_chunks(scope, [other_channel])
    assert lib.chunk_count(scope, src_w, 3) == 1
    status = lib.set_source_status(scope, src_w, KnowledgeSourceStatus.FAILED, 5, 0.5)
    assert (
        status.status is KnowledgeSourceStatus.FAILED
        and status.ingest_version == 5
        and status.reliability_score == 0.5
    )


def test_rls_with_and_without_tenant_and_across_tenants(scratch: dict[str, str]) -> None:
    a, b = Tenant(scratch), Tenant(scratch)
    try:
        for t in (a, b):
            col = t.collection()
            t.chunk(t.source(col), col, BODY, 1)
        lib = make_library(scratch)
        cols_a = [c.collection_id for c in lib.collections_for_channel(a.scope)]
        assert len(cols_a) == 1
        # org A reading org B's ids, with B's channel: nothing (RLS and the explicit predicates)
        cols_b = [c.collection_id for c in lib.collections_for_channel(b.scope)]
        crossed = TenantScope(a.scope.org_id, b.scope.channel_id)
        assert lib.collections_for_channel(crossed) == []
        assert lib.search(crossed, SearchRequest("stop loss", "en", frozenset(cols_b), 5)) == []
        assert lib.search(a.scope, SearchRequest("stop loss", "en", frozenset(cols_b), 5)) == []
        # a raw query as the app role without the tenant set sees no rows (fail closed)
        with psycopg.connect(_dsn(scratch["db"], APP_ROLE, scratch["password"])) as conn:
            assert conn.execute("SELECT count(*) FROM knowledge_chunks").fetchone() == (0,)
            conn.execute("SELECT set_config('app.org_id', %s, false)", (str(a.org),))
            assert conn.execute("SELECT count(*) FROM knowledge_chunks").fetchone() == (1,)
        # the explicit predicates alone are enough: query with the policy checked out of the way
        owner = psycopg.connect(_dsn(scratch["db"]), autocommit=True)
        owner.execute("ALTER TABLE knowledge_chunks NO FORCE ROW LEVEL SECURITY")
        owner.execute("ALTER TABLE knowledge_chunks DISABLE ROW LEVEL SECURITY")
        try:
            hits = lib.search(
                a.scope, SearchRequest("stop loss", "en", frozenset(cols_a + cols_b), 10)
            )
            assert hits and all(h.org_id == a.scope.org_id for h in hits)
        finally:
            owner.execute("ALTER TABLE knowledge_chunks ENABLE ROW LEVEL SECURITY")
            owner.execute("ALTER TABLE knowledge_chunks FORCE ROW LEVEL SECURITY")
            owner.close()
    finally:
        a.conn.close()
        b.conn.close()


class Documents:
    def __init__(self, docs: dict[str, bytes]) -> None:
        self.docs = docs

    def read(self, scope: TenantScope, subject_ref: str) -> bytes | None:
        return self.docs.get(subject_ref)


def canonical(title: str, key: str, ids: list[str]) -> bytes:
    return json.dumps(
        {"chunk_ids": sorted(ids), "collection_key": key, "topic_title": title},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


def decide(
    lib: SqlKnowledgeLibrary,
    t: Tenant,
    col: uuid.UUID,
    kind: VideoKind = VideoKind.METHOD_TOPIC,
    title: str = "Our method topic",
) -> dict[str, Any]:
    """Search then gate exactly as the retriever does, through the real SQL."""
    scope = t.scope
    col_w = t.wire(Prefix.KNOWLEDGE_COLLECTION, col)
    hits = lib.search(scope, SearchRequest("stop loss", "en", frozenset({col_w}), 10))
    assert hits, "the seeded chunk must be found"
    h = hits[0]
    meta = ChunkMeta(
        h.chunk_id,
        h.org_id,
        h.collection_id,
        h.collection_key,
        h.collection_restricted,
        h.source_id,
        h.source_release_approval_id,
        h.chunk_release_approval_id,
    )
    res = RestrictedCollectionGate().evaluate(
        meta, TopicFlags(kind, title), _LibraryApprovals(lib, scope)
    )
    return {
        "allowed": res.allowed,
        "reason": res.reason.value if res.reason else None,
        "labelled": res.method_labelled,
    }


def test_release_gate_rg01_to_rg12_through_real_sql(
    scratch: dict[str, str], tenant: Tenant
) -> None:
    other = Tenant(scratch)
    try:
        t = tenant
        col = t.collection(restricted=True)
        key = f"col_{col.hex[-10:]}"

        def case(
            *,
            subject: str = "source",
            state: str = "APPROVED",
            kind: str = "KNOWLEDGE_RELEASE",
            approval_org: Tenant | None = None,
            pointer: str = "source",
            topic: str = "Our method topic",
            hash_title: str | None = None,
            listed: bool = True,
            collection_ok: bool = True,
            document: bool = False,
            source_ok: bool = True,
        ) -> dict[str, Any]:
            src = t.source(col)
            chunk_id = uuid.uuid7()
            chunk_w = t.wire(Prefix.KNOWLEDGE_CHUNK, chunk_id)
            docs: dict[str, bytes] = {}
            owner = approval_org or t
            if subject == "source":
                subject_id = src if source_ok else uuid.uuid7()
                a = owner.approval(
                    kind=kind, state=state, subject_kind="knowledge_source", subject_id=subject_id
                )
            else:
                listed_ids = [chunk_w] if listed else [t.wire(Prefix.KNOWLEDGE_CHUNK, uuid.uuid7())]
                doc = canonical(hash_title or topic, key, listed_ids)
                sha = hashlib.sha256(doc).digest()
                ref = f"amw-blob://x/{uuid.uuid4().hex}.json" if document else None
                a = owner.approval(
                    kind=kind,
                    state=state,
                    subject_kind="knowledge_release",
                    subject_id=col if collection_ok else uuid.uuid7(),
                    sha=sha,
                    ref=ref,
                )
                if ref:
                    docs[ref] = doc
            body = BODY + f" {uuid.uuid4().hex[:6]}"
            if subject == "source":
                t.conn.execute(
                    "UPDATE knowledge_sources SET release_approval_id=%s WHERE id=%s", (a, src)
                )
                t.conn.execute(
                    "INSERT INTO knowledge_chunks (id, org_id, channel_id, source_id, collection_id, ingest_version, chunk_no, language, body, body_sha256, search_tsv) VALUES (%s,%s,%s,%s,%s,1,1,'en',%s,%s,to_tsvector('english',%s))",
                    (
                        chunk_id,
                        t.org,
                        t.channel,
                        src,
                        col,
                        body,
                        hashlib.sha256(body.encode()).digest(),
                        body,
                    ),
                )
            else:
                t.conn.execute(
                    "INSERT INTO knowledge_chunks (id, org_id, channel_id, source_id, collection_id, ingest_version, chunk_no, language, body, body_sha256, search_tsv, release_approval_id) VALUES (%s,%s,%s,%s,%s,1,1,'en',%s,%s,to_tsvector('english',%s),%s)",
                    (
                        chunk_id,
                        t.org,
                        t.channel,
                        src,
                        col,
                        body,
                        hashlib.sha256(body.encode()).digest(),
                        body,
                        a,
                    ),
                )
            lib = make_library(scratch, Documents(docs) if document else None)
            out = decide_for(lib, t, col, chunk_w, topic)
            t.conn.execute("DELETE FROM knowledge_chunks WHERE id=%s", (chunk_id,))
            return out

        def decide_for(
            lib: SqlKnowledgeLibrary,
            tt: Tenant,
            c: uuid.UUID,
            chunk_w: str,
            topic: str,
            kind: VideoKind = VideoKind.METHOD_TOPIC,
        ) -> dict[str, Any]:
            scope = tt.scope
            hits = [
                h
                for h in lib.search(
                    scope,
                    SearchRequest(
                        "stop loss", "en", frozenset({tt.wire(Prefix.KNOWLEDGE_COLLECTION, c)}), 10
                    ),
                )
                if h.chunk_id == chunk_w
            ]
            assert hits
            h = hits[0]
            meta = ChunkMeta(
                h.chunk_id,
                h.org_id,
                h.collection_id,
                h.collection_key,
                h.collection_restricted,
                h.source_id,
                h.source_release_approval_id,
                h.chunk_release_approval_id,
            )
            res = RestrictedCollectionGate().evaluate(
                meta, TopicFlags(kind, topic), _LibraryApprovals(lib, scope)
            )
            return {"allowed": res.allowed, "reason": res.reason.value if res.reason else None}

        assert case() == {"allowed": True, "reason": None}  # RG-01
        # RG-02: released but a general topic
        src = t.source(col)
        a = t.approval(subject_kind="knowledge_source", subject_id=src)
        t.conn.execute("UPDATE knowledge_sources SET release_approval_id=%s WHERE id=%s", (a, src))
        cid = t.chunk(src, col, BODY + " rg02", 1)
        assert decide_for(
            make_library(scratch),
            t,
            col,
            t.wire(Prefix.KNOWLEDGE_CHUNK, cid),
            "x",
            VideoKind.GENERAL,
        ) == {"allowed": False, "reason": "NOT_METHOD_TOPIC"}
        # RG-03: no release at all
        src3 = t.source(col)
        c3 = t.chunk(src3, col, BODY + " rg03", 1)
        assert decide_for(
            make_library(scratch), t, col, t.wire(Prefix.KNOWLEDGE_CHUNK, c3), "x"
        ) == {"allowed": False, "reason": "RELEASE_MISSING"}
        assert case(state="PENDING")["reason"] == "RELEASE_NOT_APPROVED"  # RG-04
        assert case(state="REJECTED")["reason"] == "RELEASE_NOT_APPROVED"  # RG-05
        assert case(kind="TOPIC")["reason"] == "RELEASE_WRONG_KIND"  # RG-06
        # RG-07: another org's approval is invisible under RLS and the org predicate: fails closed
        assert case(approval_org=other)["allowed"] is False
        # RG-08 (unrestricted collection ignores the flags) is covered below
        # RG-09: per-topic release, hash from the subject document (authoritative) and pointer fallback
        assert case(subject="topic", document=True) == {"allowed": True, "reason": None}
        assert case(subject="topic", document=False) == {"allowed": True, "reason": None}
        # RG-10: recorded for another topic title: the hash binds the title
        assert (
            case(
                subject="topic", document=True, topic="Another topic", hash_title="Our method topic"
            )["reason"]
            == "RELEASE_NOT_COVERING"
        )
        # RG-11: the approval lists other chunks, not this one
        assert (
            case(subject="topic", document=True, listed=False)["reason"] == "RELEASE_NOT_COVERING"
        )
        # RG-12: source-level release of the chunk's own source; a release of another source does not cover
        assert case(subject="source", source_ok=True)["allowed"] is True
        assert case(subject="source", source_ok=False)["reason"] == "RELEASE_NOT_COVERING"
        # per-topic approval for another collection does not cover
        assert (
            case(subject="topic", document=True, collection_ok=False)["reason"]
            == "RELEASE_NOT_COVERING"
        )
        # a tampered document (hash mismatch) releases nothing
        src_t = t.source(col)
        doc = canonical("Our method topic", key, [])
        a_t = t.approval(
            subject_kind="knowledge_release",
            subject_id=col,
            sha=hashlib.sha256(doc).digest(),
            ref="amw-blob://x/t.json",
        )
        c_t = t.chunk(src_t, col, BODY + " tamper", 1, release=a_t)
        tampered = Documents({"amw-blob://x/t.json": doc + b" "})
        assert (
            decide_for(
                make_library(scratch, tampered),
                t,
                col,
                t.wire(Prefix.KNOWLEDGE_CHUNK, c_t),
                "Our method topic",
            )["reason"]
            == "RELEASE_NOT_COVERING"
        )
        # RG-08: an unrestricted collection ignores the method flags
        open_col = t.collection(restricted=False)
        open_src = t.source(open_col)
        open_chunk = t.chunk(open_src, open_col, BODY + " open", 1)
        assert (
            decide_for(
                make_library(scratch),
                t,
                open_col,
                t.wire(Prefix.KNOWLEDGE_CHUNK, open_chunk),
                "x",
                VideoKind.GENERAL,
            )["allowed"]
            is True
        )
        digest = release_subject_sha256("Our method topic", key, ["a"])
        assert len(digest) == 64
    finally:
        other.conn.close()
