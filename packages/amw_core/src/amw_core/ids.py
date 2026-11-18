"""Identifiers (docs/v4/GLOSSARY_AND_IDS.md section 2).

* Storage: native ``uuid`` holding a UUIDv7, generated in application code by ``new_id``
  (section 2.1 rule 1). Generator: the standard library ``uuid.uuid7`` (Python 3.14, RFC 9562).
* Wire / log / UI form: ``<prefix>_<canonical lowercase UUID>`` (rule 2). The prefix is checked and
  stripped on input; a wrong prefix is ``PERMANENT.INPUT_INVALID`` (rule 3).
* Actor references (section 2.3), executor IDs and idempotency keys (section 2.4, 03 section 9.1).
"""

import hashlib
import json
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import NewType
from urllib.parse import urlsplit, urlunsplit

from amw_core.errors import InputInvalidError


class Prefix(StrEnum):
    """GLOSSARY section 2.2: one prefix per entity (member name = entity)."""

    ORGANISATION = "org"
    WORKSPACE = "wsp"
    CHANNEL = "chn"
    USER = "usr"
    MEMBERSHIP = "mbr"
    USER_SESSION = "ses"
    USER_AUTH_REF = "uar"
    INVITATION = "ivt"
    PROJECT = "prj"
    JOB = "job"
    TASK = "tsk"
    TASK_ATTEMPT = "att"
    STATE_TRANSITION = "stt"
    QUEUE_ITEM = "qit"
    DEAD_LETTER = "dlq"
    CHECKPOINT = "ckp"
    CIRCUIT_BREAKER = "cbk"
    MESSAGE = "msg"
    CORRELATION = "cor"
    AUDIT_ENTRY = "aud"
    COST_ENTRY = "cst"
    BUDGET = "bgt"
    BUDGET_RESERVATION = "bgr"
    LICENCE = "lic"
    LICENCE_LEDGER_ENTRY = "lcu"
    ASSET = "ast"
    ASSET_FINGERPRINT = "afp"
    VOICE = "vce"
    VOICE_CONSENT = "vcn"
    BRAND_KIT = "bkt"
    COMPLIANCE_PROFILE = "cpf"
    RULE_PACK = "rpk"
    COMPLIANCE_VERDICT = "cvd"
    KNOWLEDGE_SOURCE = "ksr"
    KNOWLEDGE_CHUNK = "kch"
    KNOWLEDGE_COLLECTION = "kcl"
    MEMORY_ITEM = "mem"
    SCRIPT = "scr"
    CLAIM = "clm"
    CITATION = "cit"
    APPROVAL = "apr"
    APPROVAL_STEP = "aps"
    EDITORIAL_CONTRIBUTION = "edc"
    QUALITY_SCORE = "qsc"
    QC_RESULT = "qcr"
    RENDER = "rnd"
    PUBLICATION = "pub"
    OAUTH_TOKEN = "oat"  # noqa: S105 - ID prefix, not a token
    TENANT_DATA_KEY = "dek"
    GCP_PROJECT = "gcp"
    ANALYTICS_SNAPSHOT = "ans"
    EXPERIMENT = "exp"
    NOTIFICATION = "ntf"
    REVIEW_COMMENT = "rvc"
    COMMUNITY_COMMENT = "cmt"
    CONTROL_SETTING = "ctl"
    DATA_REQUEST = "dtr"
    WORKER = "wkr"
    PRODUCTION_TYPE = "prt"
    ORG_PRODUCTION_TYPE = "opt"
    API_KEY = "key"
    WEBHOOK = "whk"
    WEBHOOK_DELIVERY = "whd"
    PLAN = "pln"
    SUBSCRIPTION = "sub"
    USAGE_EVENT = "use"
    INVOICE = "ivc"
    SSO_CONNECTION = "sso"
    VERIFIED_DOMAIN = "dom"
    EVAL_RUN = "run"
    OWNER_INSTRUCTION_EVIDENCE = "oie"


UUID7_BODY = r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_WIRE_RE = re.compile(rf"^(?P<prefix>[a-z]{{3}})_(?P<body>{UUID7_BODY})$")
EXECUTOR_ID_PATTERN = r"^(agent_(0[1-9]|1[0-7])|svc_s(0[1-9]|1[0-3]))$"
ACTOR_REF_PATTERN = (
    rf"^(agent_(0[1-9]|1[0-7])|svc_s(0[1-9]|1[0-3])|usr_{UUID7_BODY}|sys_[a-z_]{{3,32}})$"
)
IDEMPOTENCY_KEY_PATTERN = r"^idk_[0-9a-f]{64}$"
_EXECUTOR_RE = re.compile(EXECUTOR_ID_PATTERN)
_ACTOR_RE = re.compile(ACTOR_REF_PATTERN)
_IDK_RE = re.compile(IDEMPOTENCY_KEY_PATTERN)
_PREFIXES = frozenset(p.value for p in Prefix)

WireId = NewType("WireId", str)
OrgId = NewType("OrgId", str)
WorkspaceId = NewType("WorkspaceId", str)
ChannelId = NewType("ChannelId", str)
UserId = NewType("UserId", str)
ProjectId = NewType("ProjectId", str)
JobId = NewType("JobId", str)
TaskId = NewType("TaskId", str)
AttemptId = NewType("AttemptId", str)
StateTransitionId = NewType("StateTransitionId", str)
QueueItemId = NewType("QueueItemId", str)
DeadLetterId = NewType("DeadLetterId", str)
CheckpointId = NewType("CheckpointId", str)
MessageId = NewType("MessageId", str)
CorrelationId = NewType("CorrelationId", str)
AuditEntryId = NewType("AuditEntryId", str)
CostEntryId = NewType("CostEntryId", str)
BudgetId = NewType("BudgetId", str)
ReservationId = NewType("ReservationId", str)
WorkerId = NewType("WorkerId", str)
ApprovalId = NewType("ApprovalId", str)
PublicationId = NewType("PublicationId", str)
RenderId = NewType("RenderId", str)
AssetId = NewType("AssetId", str)
ActorRef = NewType("ActorRef", str)
ExecutorId = NewType("ExecutorId", str)
IdempotencyKey = NewType("IdempotencyKey", str)


def new_uuid7() -> uuid.UUID:
    """A fresh UUIDv7 (time-ordered)."""
    return uuid.uuid7()


def format_id(prefix: Prefix, value: uuid.UUID) -> WireId:
    """Wire form of a stored UUIDv7; refuses non-v7 values."""
    if value.version != 7 or value.variant != uuid.RFC_4122:
        raise InputInvalidError(f"not a UUIDv7: {value}")
    return WireId(f"{prefix.value}_{value}")


def new_id(entity: Prefix) -> WireId:
    """``amw_core.ids.new_id(entity)`` of GLOSSARY section 2.1 rule 1."""
    return format_id(entity, new_uuid7())


def prefix_of(wire: str) -> Prefix:
    """The entity prefix of a wire ID; ``PERMANENT.INPUT_INVALID`` if malformed."""
    match = _WIRE_RE.fullmatch(wire)
    if match is None or match["prefix"] not in _PREFIXES:
        raise InputInvalidError("malformed wire ID", details={"value": wire[:80]})
    return Prefix(match["prefix"])


def parse_id(wire: str, expected: Prefix) -> uuid.UUID:
    """Check and strip the prefix (rule 3); returns the UUID stored in the DB."""
    actual = prefix_of(wire)
    if actual is not expected:
        raise InputInvalidError(
            f"wrong ID prefix: expected {expected.value}_, got {actual.value}_",
            details={"value": wire[:80]},
        )
    return uuid.UUID(wire.split("_", 1)[1])


def is_valid_id(wire: str, expected: Prefix | None = None) -> bool:
    try:
        actual = prefix_of(wire)
    except InputInvalidError:
        return False
    return expected is None or actual is expected


@dataclass(frozen=True, slots=True)
class IdKind[T: str]:
    """Typed helper for one entity: ``JOB.new() -> JobId``, ``JOB.validate(s) -> JobId``."""

    prefix: Prefix
    wrap: Callable[[str], T]

    def new(self) -> T:
        return self.wrap(new_id(self.prefix))

    def validate(self, wire: str) -> T:
        parse_id(wire, self.prefix)
        return self.wrap(wire)

    def from_uuid(self, value: uuid.UUID) -> T:
        return self.wrap(format_id(self.prefix, value))

    def to_uuid(self, wire: str) -> uuid.UUID:
        return parse_id(wire, self.prefix)


ORG = IdKind(Prefix.ORGANISATION, OrgId)
WORKSPACE = IdKind(Prefix.WORKSPACE, WorkspaceId)
CHANNEL = IdKind(Prefix.CHANNEL, ChannelId)
USER = IdKind(Prefix.USER, UserId)
PROJECT = IdKind(Prefix.PROJECT, ProjectId)
JOB = IdKind(Prefix.JOB, JobId)
TASK = IdKind(Prefix.TASK, TaskId)
ATTEMPT = IdKind(Prefix.TASK_ATTEMPT, AttemptId)
STATE_TRANSITION = IdKind(Prefix.STATE_TRANSITION, StateTransitionId)
QUEUE_ITEM = IdKind(Prefix.QUEUE_ITEM, QueueItemId)
DEAD_LETTER = IdKind(Prefix.DEAD_LETTER, DeadLetterId)
CHECKPOINT = IdKind(Prefix.CHECKPOINT, CheckpointId)
MESSAGE = IdKind(Prefix.MESSAGE, MessageId)
CORRELATION = IdKind(Prefix.CORRELATION, CorrelationId)
AUDIT_ENTRY = IdKind(Prefix.AUDIT_ENTRY, AuditEntryId)
COST_ENTRY = IdKind(Prefix.COST_ENTRY, CostEntryId)
BUDGET = IdKind(Prefix.BUDGET, BudgetId)
RESERVATION = IdKind(Prefix.BUDGET_RESERVATION, ReservationId)
WORKER = IdKind(Prefix.WORKER, WorkerId)
APPROVAL = IdKind(Prefix.APPROVAL, ApprovalId)
PUBLICATION = IdKind(Prefix.PUBLICATION, PublicationId)
RENDER = IdKind(Prefix.RENDER, RenderId)
ASSET = IdKind(Prefix.ASSET, AssetId)
OWNER_EVIDENCE = IdKind(Prefix.OWNER_INSTRUCTION_EVIDENCE, WireId)
KNOWLEDGE_COLLECTION = IdKind(Prefix.KNOWLEDGE_COLLECTION, WireId)


class SystemActor(StrEnum):
    """GLOSSARY section 2.3 ``SYSTEM`` actors. ``sys_operator`` (CCR-010, D5) records owner
    decisions on the owner's behalf; it is never an approver itself."""

    SCHEDULER = "sys_scheduler"
    REAPER = "sys_reaper"
    DLQ_HANDLER = "sys_dlq_handler"
    MIGRATOR = "sys_migrator"
    API = "sys_api"
    OPERATOR = "sys_operator"


def is_executor_id(value: str) -> bool:
    """``agent_01``..``agent_17`` or ``svc_s01``..``svc_s13`` (amw.common#/$defs/executor_id)."""
    return _EXECUTOR_RE.fullmatch(value) is not None


def is_actor_ref(value: str) -> bool:
    """GLOSSARY section 2.3 / amw.common#/$defs/actor_ref."""
    return _ACTOR_RE.fullmatch(value) is not None


def executor_id(value: str) -> ExecutorId:
    if not is_executor_id(value):
        raise InputInvalidError("not an executor ID", details={"value": value[:80]})
    return ExecutorId(value)


def actor_ref(value: str) -> ActorRef:
    if not is_actor_ref(value):
        raise InputInvalidError("not an actor reference", details={"value": value[:80]})
    return ActorRef(value)


def is_idempotency_key(value: str) -> bool:
    return _IDK_RE.fullmatch(value) is not None


def idempotency_key_of(value: str) -> IdempotencyKey:
    if not is_idempotency_key(value):
        raise InputInvalidError("not an idempotency key (idk_ + 64 hex)")
    return IdempotencyKey(value)


class IdempotencyScope(StrEnum):
    """03 section 9.2 scopes (every external side effect). ``task.<task_type>`` is the pattern
    ``TASK_SCOPE_PATTERN`` (natural key: job, stage_id, task_type, iteration; CCR-005);
    ``webhook.deliver`` is Tier 3 and ``billing.charge`` Tier 2."""

    JOB_CREATE = "job.create"
    LLM_CALL = "llm.call"
    TTS_SYNTHESIZE = "tts.synthesize"
    MEDIA_GENERATE = "media.generate"
    STOCK_LICENSE = "stock.license"
    RENDER_MASTER = "render.master"
    DB_OUTPUT = "db.output"
    UPLOAD_YOUTUBE = "upload.youtube"
    PUBLISH_YOUTUBE = "publish.youtube"
    THUMBNAIL_SET = "thumbnail.set"
    CAPTIONS_INSERT = "captions.insert"
    DELIVERY_FILE = "delivery.file"
    NOTIFY_SEND = "notify.send"
    WEBHOOK_DELIVER = "webhook.deliver"
    BILLING_CHARGE = "billing.charge"
    FETCH_REFERENCE = "fetch.reference"
    RENDER_SEGMENT = "render.segment"


TASK_SCOPE_PATTERN = r"^task\.(agent_(0[1-9]|1[0-7])|svc_s(0[1-9]|1[0-3]))\.[a-z0-9_]+$"
_TASK_SCOPE_RE = re.compile(TASK_SCOPE_PATTERN)
_SCOPES = frozenset(s.value for s in IdempotencyScope)
NEVER_EXPIRING_SCOPE_PREFIXES = ("upload.", "publish.")
"""03 section 9.1 rule 4: keys of these scopes never expire."""


def is_idempotency_scope(scope: str) -> bool:
    """A scope of the 03 section 9.2 table (fixed name or ``task.<task_type>``)."""
    return scope in _SCOPES or _TASK_SCOPE_RE.fullmatch(scope) is not None


def make_idempotency_key(
    org_id: str, scope: str, natural_key: Sequence[str | int]
) -> IdempotencyKey:
    """03 section 9.1: ``idk_`` + SHA-256 of the canonical ``{org_id, scope, natural_key}``.

    Canonical form: UTF-8, sorted keys, no insignificant whitespace, strings and integers only.
    ``scope`` must be a 03 section 9.2 scope (``PERMANENT.INPUT_INVALID`` otherwise).
    """
    parse_id(org_id, Prefix.ORGANISATION)
    if not is_idempotency_scope(scope):
        raise InputInvalidError(f"unknown idempotency scope {scope!r} (03 section 9.2)")
    for part in natural_key:
        if isinstance(part, bool) or not isinstance(part, (str, int)):
            raise InputInvalidError("idempotency natural key parts must be strings or integers")
    material = {"org_id": org_id, "natural_key": list(natural_key), "scope": scope}
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return IdempotencyKey("idk_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest())


EXTERNAL_REF_PATTERN = r"^ext_[0-9a-f]{24}$"
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_PCT = re.compile(r"%([0-9A-Fa-f]{2})")


def _percent(text: str) -> str:
    def fix(match: re.Match[str]) -> str:
        char = chr(int(match[1], 16))
        return char if char in _UNRESERVED else "%" + match[1].upper()

    return _PCT.sub(fix, text)


def _remove_dot_segments(path: str) -> str:
    """RFC 3986 section 5.2.4."""
    output: list[str] = []
    for segment in path.split("/"):
        if segment == "..":
            if len(output) > 1:
                output.pop()
        elif segment != ".":
            output.append(segment)
    if path.endswith(("/.", "/..")):
        output.append("")
    result = "/".join(output)
    return result if result.startswith("/") or not path.startswith("/") else "/" + result


def normalise_reference_url(url: str) -> str:
    """GLOSSARY section 2.4 URL normalisation (CCR-066), in the stated order."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise InputInvalidError("external references are absolute https URLs")
    host = parts.hostname.rstrip(".")
    try:
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise InputInvalidError("host cannot be IDNA-encoded") from exc
    netloc = host
    if parts.port is not None and parts.port != 443:
        netloc = f"{host}:{parts.port}"
    if parts.username is not None:
        userinfo = parts.netloc.rsplit("@", 1)[0]
        netloc = f"{userinfo}@{netloc}"
    path = _remove_dot_segments(_percent(parts.path)) or "/"
    params = [_percent(p) for p in parts.query.split("&")] if parts.query else []
    params.sort(key=lambda p: tuple(p.split("=", 1)) if "=" in p else (p, ""))
    query = "&".join(params)
    return urlunsplit(("https", netloc, path, query, ""))


def make_external_ref_id(org_id: str, url: str) -> str:
    """GLOSSARY section 2.4 (CCR-044): ``ext_`` + first 24 hex of SHA-256 over the canonical
    ``{"org_id": ..., "url": <normalised URL>}``; the URL is normalised here (CCR-066)."""
    parse_id(org_id, Prefix.ORGANISATION)
    canonical = json.dumps(
        {"org_id": org_id, "url": normalise_reference_url(url)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return "ext_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
