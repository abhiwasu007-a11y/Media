"""Every status and value enum of docs/v4/GLOSSARY_AND_IDS.md section 6 (master list).

Values are the exact glossary spellings. DB columns store them as ``text`` with a CHECK
(GLOSSARY section 5), so adding a value is additive and needs a CCR, never a local variant.
``GLOSSARY_ENUMS`` maps each glossary enum name to its class; ``tests/test_enums.py`` parses the
glossary tables and fails if a value is missing or extra.
"""

from collections.abc import Mapping
from enum import Enum, IntEnum, StrEnum
from types import MappingProxyType


# 6.1
class TaskState(StrEnum):
    PENDING = "PENDING"
    VALIDATING = "VALIDATING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CHECKPOINTED = "CHECKPOINTED"
    RETRY_WAIT = "RETRY_WAIT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"
    CANCELLED = "CANCELLED"


# 6.2: same value set as task_state without RETRY_WAIT (retries are task-level only).
class JobState(StrEnum):
    PENDING = "PENDING"
    VALIDATING = "VALIDATING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CHECKPOINTED = "CHECKPOINTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"
    CANCELLED = "CANCELLED"


# 6.3 (only when state = CHECKPOINTED; NULL otherwise)
class WaitReason(StrEnum):
    DRAIN = "DRAIN"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    AWAITING_QUOTA = "AWAITING_QUOTA"
    AWAITING_BUDGET = "AWAITING_BUDGET"
    AWAITING_EXTERNAL = "AWAITING_EXTERNAL"
    OPERATOR_PAUSE = "OPERATOR_PAUSE"


# 6.4 (only when job_state = COMPLETED)
class JobOutcome(StrEnum):
    PUBLISHED = "PUBLISHED"
    DELIVERED = "DELIVERED"
    BLOCKED_COMPLIANCE = "BLOCKED_COMPLIANCE"
    REJECTED_BY_APPROVER = "REJECTED_BY_APPROVER"
    NO_DELIVERABLE = "NO_DELIVERABLE"


# 6.5
class Priority(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"
    BACKGROUND = "BACKGROUND"

    @property
    def queue_int(self) -> int:
        """Queue integer of GLOSSARY section 6.5 (0 = most urgent)."""
        return _PRIORITY_QUEUE_INT[self]


_PRIORITY_QUEUE_INT: Mapping[Priority, int] = MappingProxyType(
    {
        Priority.CRITICAL: 0,
        Priority.HIGH: 1,
        Priority.NORMAL: 2,
        Priority.LOW: 3,
        Priority.BACKGROUND: 4,
    }
)


# 6.6
class ResourceClass(StrEnum):
    LIGHT = "LIGHT"
    AI_IO = "AI_IO"
    HEAVY_CPU = "HEAVY_CPU"
    PUBLISH = "PUBLISH"


# 6.7
class QueueItemStatus(StrEnum):
    READY = "READY"
    CLAIMED = "CLAIMED"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


# 6.8
class AttemptResult(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    SUSPENDED = "SUSPENDED"
    LEASE_EXPIRED = "LEASE_EXPIRED"
    CANCELLED = "CANCELLED"
    RUNNING = "RUNNING"


# 6.9
class OutputStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SUSPENDED = "SUSPENDED"
    REJECTED = "REJECTED"


# 6.10 (advisory only)
class NextActionType(StrEnum):
    CONTINUE = "CONTINUE"
    WAIT = "WAIT"
    RETRY = "RETRY"
    ESCALATE = "ESCALATE"
    STOP = "STOP"


# 6.11
class FeatureStatus(StrEnum):
    PLANNED = "PLANNED"
    IN_DEVELOPMENT = "IN_DEVELOPMENT"
    IMPLEMENTED = "IMPLEMENTED"
    TESTED = "TESTED"
    PRODUCTION_READY = "PRODUCTION_READY"

    @property
    def display(self) -> str:
        """Exact display string of GLOSSARY section 6.11 (rule 7)."""
        return _FEATURE_STATUS_DISPLAY[self]


_FEATURE_STATUS_DISPLAY: Mapping[FeatureStatus, str] = MappingProxyType(
    {
        FeatureStatus.PLANNED: "Planned",
        FeatureStatus.IN_DEVELOPMENT: "In Development",
        FeatureStatus.IMPLEMENTED: "Implemented",
        FeatureStatus.TESTED: "Tested",
        FeatureStatus.PRODUCTION_READY: "Production Ready",
    }
)


# 6.12
class DocStatus(StrEnum):
    NOT_STARTED = "Not started"
    DRAFT = "Draft"
    PARTIAL_BLOCKED = "Partial (blocked)"
    COMPLETE = "Complete"
    AUDITED = "Audited"


# 6.13 (final: all except PENDING)
class ApprovalState(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"

    @property
    def is_final(self) -> bool:
        return self is not ApprovalState.PENDING


# 6.14
class ApprovalStepState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    SKIPPED = "SKIPPED"


# 6.15
class ApprovalKind(StrEnum):
    TOPIC = "TOPIC"
    BRIEF = "BRIEF"
    CONCEPT = "CONCEPT"
    SCRIPT = "SCRIPT"
    STORYBOARD = "STORYBOARD"
    VOICE_SAMPLE = "VOICE_SAMPLE"
    ROUGH_CUT = "ROUGH_CUT"
    FINAL_VIDEO = "FINAL_VIDEO"
    THUMBNAIL = "THUMBNAIL"
    METADATA = "METADATA"
    PUBLISH = "PUBLISH"
    SPEND = "SPEND"
    NEW_CHANNEL = "NEW_CHANNEL"
    NEW_CATEGORY = "NEW_CATEGORY"
    SENSITIVE_CLAIM = "SENSITIVE_CLAIM"
    COPYRIGHT_DOUBT = "COPYRIGHT_DOUBT"
    UNUSUAL_PUBLISH = "UNUSUAL_PUBLISH"
    POLICY_CHANGE = "POLICY_CHANGE"
    DLQ_REPLAY = "DLQ_REPLAY"
    EXPERIMENT = "EXPERIMENT"
    COMMENT_REPLY = "COMMENT_REPLY"
    KNOWLEDGE_RELEASE = "KNOWLEDGE_RELEASE"
    USAGE_RIGHTS = "USAGE_RIGHTS"


# 6.16
class EditorialContributionType(StrEnum):
    ANGLE = "ANGLE"
    EXAMPLE = "EXAMPLE"
    OPINION = "OPINION"
    CORRECTION = "CORRECTION"


# 6.17
class LicenceState(StrEnum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    EXPIRING = "EXPIRING"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    REJECTED = "REJECTED"


# 6.18
class LicenceSourceType(StrEnum):
    OWNER_MADE = "OWNER_MADE"
    CLIENT_SUPPLIED = "CLIENT_SUPPLIED"
    PAID_STOCK = "PAID_STOCK"
    FREE_STOCK = "FREE_STOCK"
    CODE_GENERATED = "CODE_GENERATED"
    AI_GENERATED = "AI_GENERATED"
    MUSIC_LIBRARY = "MUSIC_LIBRARY"
    SFX_LIBRARY = "SFX_LIBRARY"
    FONT = "FONT"
    TTS_PROVIDER = "TTS_PROVIDER"
    VOICE_CLONE = "VOICE_CLONE"
    HUMAN_NARRATION = "HUMAN_NARRATION"


# 6.19 (hierarchy a-e)
class VisualSourceTier(StrEnum):
    A_OWNER_REAL = "A_OWNER_REAL"
    B_LICENSED_STOCK = "B_LICENSED_STOCK"
    C_CODE_MOTION = "C_CODE_MOTION"
    D_AI_VIDEO = "D_AI_VIDEO"
    E_AI_STILL = "E_AI_STILL"


# 6.20
class Capability(StrEnum):
    LLM = "llm"
    TTS = "tts"
    IMAGE_GEN = "image_gen"
    VIDEO_GEN = "video_gen"
    STOCK_SEARCH = "stock_search"
    RENDER_FFMPEG = "render_ffmpeg"
    MEDIA_PROBE = "media_probe"
    PUBLISH_YOUTUBE = "publish_youtube"
    FILE_DELIVERY = "file_delivery"
    ANALYTICS_INGEST = "analytics_ingest"
    NOTIFY_EMAIL = "notify_email"


# 6.21
class ThirdPartyPermission(StrEnum):
    PERMITTED = "PERMITTED"
    NOT_PERMITTED = "NOT_PERMITTED"
    UNKNOWN = "UNKNOWN"


# 6.22
class LicenceUsageKind(StrEnum):
    SHOT = "SHOT"
    IMAGE = "IMAGE"
    MUSIC_BED = "MUSIC_BED"
    SFX = "SFX"
    VOICE = "VOICE"
    FONT = "FONT"
    TEMPLATE = "TEMPLATE"
    AI_OUTPUT = "AI_OUTPUT"


# 6.23
class PublishState(StrEnum):
    DRAFT = "DRAFT"
    UPLOADING = "UPLOADING"
    UPLOADED_PRIVATE = "UPLOADED_PRIVATE"
    PROCESSING = "PROCESSING"
    READY_PRIVATE = "READY_PRIVATE"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    DELIVERED = "DELIVERED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    REMOVED = "REMOVED"


# 6.24 (mirrors YouTube status.privacyStatus; external spelling kept)
class PrivacyStatus(StrEnum):
    PRIVATE = "private"
    PUBLIC = "public"
    UNLISTED = "unlisted"


# 6.25
class VerificationState(StrEnum):
    NOT_CHECKED = "NOT_CHECKED"
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"


# 6.26
class DestinationKind(StrEnum):
    YOUTUBE = "YOUTUBE"
    FILE_DELIVERY = "FILE_DELIVERY"


# 6.27
class CheckVerdict(StrEnum):
    PASS = "PASS"  # noqa: S105 - enum value, not a password
    FAIL = "FAIL"
    WARN = "WARN"
    SKIPPED = "SKIPPED"


# 6.28
class CheckKind(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    LLM_JUDGE = "LLM_JUDGE"
    HUMAN = "HUMAN"


# 6.29
class ComplianceVerdict(StrEnum):
    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


# 6.30
class MemoryScope(StrEnum):
    WORKING = "WORKING"
    TASK = "TASK"
    PROJECT = "PROJECT"
    CHANNEL = "CHANNEL"
    LONG_TERM = "LONG_TERM"


# 6.31 (codes in 07 section 2, see amw_core.errors)
class FailureClass(StrEnum):
    TEMPORARY = "TEMPORARY"
    PERMANENT = "PERMANENT"
    RESOURCE = "RESOURCE"
    AGENT = "AGENT"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    PUBLISHING = "PUBLISHING"


# 6.32
class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


# 6.33
class DlqRecoveryStatus(StrEnum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    REPLAY_REQUESTED = "REPLAY_REQUESTED"
    REPLAY_APPROVED = "REPLAY_APPROVED"
    REPLAYED = "REPLAYED"
    RESOLVED = "RESOLVED"
    DISCARDED = "DISCARDED"


# 6.34
class EscalationLevel(StrEnum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


# 6.35
class ExperimentState(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED_TO_RUN = "APPROVED_TO_RUN"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    INCONCLUSIVE = "INCONCLUSIVE"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"
    ABORTED = "ABORTED"


# 6.36
class ExperimentDecision(StrEnum):
    ADOPT = "ADOPT"
    REJECT = "REJECT"
    EXTEND = "EXTEND"
    NONE = "NONE"


class ExperimentKind(StrEnum):
    TITLE_THUMBNAIL_STUDIO_TEST = "TITLE_THUMBNAIL_STUDIO_TEST"
    PROMPT_VARIANT = "PROMPT_VARIANT"
    TEMPLATE_VARIANT = "TEMPLATE_VARIANT"
    SCHEDULE_VARIANT = "SCHEDULE_VARIANT"
    FORMAT_VARIANT = "FORMAT_VARIANT"


# 6.37
class RulePackScope(StrEnum):
    PLATFORM = "PLATFORM"
    TENANT = "TENANT"


class RuleSeverity(StrEnum):
    BLOCKING = "BLOCKING"
    WARNING = "WARNING"


class RulePackKey(StrEnum):
    YOUTUBE_GENERAL = "rp.youtube_general"
    FINANCE_SEBI_IN = "rp.finance_sebi_in"
    HEALTH = "rp.health"
    KIDS = "rp.kids"
    POLITICAL_NEWS = "rp.political_news"
    ADVERTISING_ASCI_IN = "rp.advertising_asci_in"
    AD_SECTOR_HEALTH_WELLNESS = "rp.ad_sector_health_wellness"
    AD_SECTOR_FOOD = "rp.ad_sector_food"
    AD_SECTOR_FINANCIAL_PRODUCTS = "rp.ad_sector_financial_products"
    AD_SECTOR_EDUCATION_OUTCOMES = "rp.ad_sector_education_outcomes"
    AD_SECTOR_REAL_ESTATE = "rp.ad_sector_real_estate"
    AD_SECTOR_ALCOHOL_TOBACCO_SURROGATE = "rp.ad_sector_alcohol_tobacco_surrogate"
    TENANT_BRAND_SAFETY = "rp.tenant_brand_safety"


# 6.38 (rule text owned by 13_COMPLIANCE_YOUTUBE_POLICY.md)
class FinRuleId(StrEnum):
    FIN_R1 = "FIN-R1"
    FIN_R2 = "FIN-R2"
    FIN_R3 = "FIN-R3"
    FIN_R4 = "FIN-R4"
    FIN_R5 = "FIN-R5"
    FIN_R6 = "FIN-R6"
    FIN_R7 = "FIN-R7"
    FIN_R8 = "FIN-R8"
    FIN_R9 = "FIN-R9"
    FIN_R10 = "FIN-R10"
    FIN_R11 = "FIN-R11"
    FIN_R12 = "FIN-R12"
    FIN_R13 = "FIN-R13"


# 6.39
class ClaimType(StrEnum):
    FACTUAL = "FACTUAL"
    STATISTICAL = "STATISTICAL"
    DEFINITION = "DEFINITION"
    HISTORICAL_MARKET = "HISTORICAL_MARKET"
    HYPOTHETICAL_EXAMPLE = "HYPOTHETICAL_EXAMPLE"
    RECOMMENDATION = "RECOMMENDATION"
    FORWARD_VIEW = "FORWARD_VIEW"
    PRICE_LEVEL = "PRICE_LEVEL"
    PERFORMANCE_CLAIM = "PERFORMANCE_CLAIM"
    TESTIMONIAL = "TESTIMONIAL"
    PROMOTION = "PROMOTION"
    QUOTED_THIRD_PARTY = "QUOTED_THIRD_PARTY"
    PRODUCT_CLAIM = "PRODUCT_CLAIM"
    COMPARATIVE = "COMPARATIVE"
    OPINION = "OPINION"


# 6.40
class ClaimStatus(StrEnum):
    EXTRACTED = "EXTRACTED"
    VERIFIED = "VERIFIED"
    CONTRADICTED = "CONTRADICTED"
    UNVERIFIABLE = "UNVERIFIABLE"
    NEEDS_SUBSTANTIATION = "NEEDS_SUBSTANTIATION"
    SUBSTANTIATED = "SUBSTANTIATED"
    REMOVED = "REMOVED"


# 6.41
class TimeReferenceKind(StrEnum):
    HISTORICAL = "HISTORICAL"
    CURRENT = "CURRENT"
    FUTURE = "FUTURE"
    TIMELESS = "TIMELESS"
    UNSPECIFIED = "UNSPECIFIED"


# 6.42
class QuotaBucket(StrEnum):
    VIDEO_UPLOADS = "VIDEO_UPLOADS"
    SEARCH = "SEARCH"
    BATCH_GET_STATS = "BATCH_GET_STATS"
    DEFAULT = "DEFAULT"


# 6.43
class DisclosureDecision(StrEnum):
    REQUIRED = "REQUIRED"
    NOT_REQUIRED = "NOT_REQUIRED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


# 6.44 Identity and tenancy enums
class Role(StrEnum):
    PLATFORM_OWNER = "PLATFORM_OWNER"
    ORG_OWNER = "ORG_OWNER"
    ORG_ADMIN = "ORG_ADMIN"
    PRODUCER = "PRODUCER"
    REVIEWER_APPROVER = "REVIEWER_APPROVER"
    FINANCE = "FINANCE"
    VIEWER = "VIEWER"
    CLIENT_GUEST = "CLIENT_GUEST"


class OrgKind(StrEnum):
    PLATFORM_OWNER = "PLATFORM_OWNER"
    CLIENT = "CLIENT"
    AGENCY = "AGENCY"


class OrgStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDING = "OFFBOARDING"
    DELETED = "DELETED"


class WorkspaceStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ProjectStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ProjectKind(StrEnum):
    SERIES = "SERIES"
    CAMPAIGN = "CAMPAIGN"
    CLIENT_ORDER = "CLIENT_ORDER"
    INTERNAL = "INTERNAL"


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    DELETED = "DELETED"


class MembershipStatus(StrEnum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"


class InvitationState(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AuthProvider(StrEnum):
    LOCAL_PASSWORD = "LOCAL_PASSWORD"  # noqa: S105 - enum value, not a password
    GOOGLE = "GOOGLE"
    SAML = "SAML"
    OIDC = "OIDC"


class ChannelPlatform(StrEnum):
    YOUTUBE = "YOUTUBE"


class ChannelStatus(StrEnum):
    DRAFT = "DRAFT"
    CONNECTED = "CONNECTED"
    NEEDS_REAUTH = "NEEDS_REAUTH"
    PAUSED = "PAUSED"
    DISCONNECTED = "DISCONNECTED"


class OauthTokenStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REFRESH_FAILED = "REFRESH_FAILED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class DataKeyStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    DESTROYED = "DESTROYED"


class GcpOwnership(StrEnum):
    PLATFORM = "PLATFORM"
    CLIENT_OWNED = "CLIENT_OWNED"


class GoogleReviewStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_REVIEW = "IN_REVIEW"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ActorKind(StrEnum):
    HUMAN = "HUMAN"
    AGENT = "AGENT"
    SERVICE = "SERVICE"
    SYSTEM = "SYSTEM"


class ConsentState(StrEnum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class VoiceKind(StrEnum):
    PROVIDER_STOCK = "PROVIDER_STOCK"
    CONSENTED_CLONE = "CONSENTED_CLONE"
    HUMAN_RECORDED = "HUMAN_RECORDED"


class DataRequestKind(StrEnum):
    EXPORT = "EXPORT"
    ERASURE = "ERASURE"


class DataRequestStatus(StrEnum):
    RECEIVED = "RECEIVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


# 6.45 Content, media and operations enums
class ScriptStatus(StrEnum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class RenderKind(StrEnum):
    MASTER = "MASTER"
    EXPORT = "EXPORT"
    PREVIEW = "PREVIEW"


class RenderStatus(StrEnum):
    RENDERING = "RENDERING"
    COMPLETE = "COMPLETE"
    QC_PASSED = "QC_PASSED"
    QC_FAILED = "QC_FAILED"
    SUPERSEDED = "SUPERSEDED"


class AssetKind(StrEnum):
    VIDEO = "VIDEO"
    IMAGE = "IMAGE"
    AUDIO_MUSIC = "AUDIO_MUSIC"
    AUDIO_SFX = "AUDIO_SFX"
    AUDIO_VOICE = "AUDIO_VOICE"
    FONT = "FONT"
    CHART = "CHART"
    SUBTITLE = "SUBTITLE"
    TEMPLATE = "TEMPLATE"
    DOCUMENT = "DOCUMENT"


class AssetStatus(StrEnum):
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"


class FingerprintAlgo(StrEnum):
    SHA256 = "SHA256"
    PERCEPTUAL_FRAME = "PERCEPTUAL_FRAME"
    AUDIO = "AUDIO"


class KnowledgeSourceKind(StrEnum):
    BOOK = "BOOK"
    COURSE_NOTES = "COURSE_NOTES"
    OWNER_NOTES = "OWNER_NOTES"
    WEB_REFERENCE = "WEB_REFERENCE"
    OFFICIAL_DOCUMENT = "OFFICIAL_DOCUMENT"
    CLIENT_DOCUMENT = "CLIENT_DOCUMENT"


class KnowledgeSourceStatus(StrEnum):
    REGISTERED = "REGISTERED"
    INGESTING = "INGESTING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"
    RETIRED = "RETIRED"


class SourceOwnership(StrEnum):
    OWNED_COPY = "OWNED_COPY"
    LICENSED = "LICENSED"
    OWNER_AUTHORED = "OWNER_AUTHORED"
    PUBLIC_OFFICIAL = "PUBLIC_OFFICIAL"
    UNKNOWN = "UNKNOWN"


class CitationSupport(StrEnum):
    SUPPORTS = "SUPPORTS"
    PARTIAL = "PARTIAL"
    CONTRADICTS = "CONTRADICTS"


class QualityDimension(StrEnum):
    RESEARCH_ACCURACY = "RESEARCH_ACCURACY"
    STORYTELLING = "STORYTELLING"
    AUDIENCE_VALUE = "AUDIENCE_VALUE"
    VISUAL_QUALITY = "VISUAL_QUALITY"
    AUDIO_QUALITY = "AUDIO_QUALITY"
    EDITING_QUALITY = "EDITING_QUALITY"
    THUMBNAIL_METADATA = "THUMBNAIL_METADATA"
    COMPLIANCE = "COMPLIANCE"

    @property
    def max_points(self) -> int:
        """Maximum points of the dimension (GLOSSARY section 6.45; the eight sum to 100)."""
        return _QUALITY_MAX_POINTS[self]


_QUALITY_MAX_POINTS: Mapping[QualityDimension, int] = MappingProxyType(
    {
        QualityDimension.RESEARCH_ACCURACY: 20,
        QualityDimension.STORYTELLING: 15,
        QualityDimension.AUDIENCE_VALUE: 15,
        QualityDimension.VISUAL_QUALITY: 15,
        QualityDimension.AUDIO_QUALITY: 10,
        QualityDimension.EDITING_QUALITY: 10,
        QualityDimension.THUMBNAIL_METADATA: 10,
        QualityDimension.COMPLIANCE: 5,
    }
)


class AnalyticsSource(StrEnum):
    ANALYTICS_API = "ANALYTICS_API"
    REPORTING_API = "REPORTING_API"


class NotificationChannel(StrEnum):
    EMAIL = "EMAIL"
    IN_APP = "IN_APP"
    WHATSAPP = "WHATSAPP"
    SLACK = "SLACK"


class NotificationStatus(StrEnum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    FAILED = "FAILED"
    READ = "READ"


class CommentTriageClass(StrEnum):
    QUESTION = "QUESTION"
    SPAM = "SPAM"
    ABUSE = "ABUSE"
    LEAD = "LEAD"
    UNCLASSIFIED = "UNCLASSIFIED"


class ReplyState(StrEnum):
    NONE = "NONE"
    DRAFTED = "DRAFTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    POSTED = "POSTED"


class WorkerStatus(StrEnum):
    STARTING = "STARTING"
    IDLE = "IDLE"
    BUSY = "BUSY"
    DRAINING = "DRAINING"
    STOPPED = "STOPPED"
    LOST = "LOST"


class IdempotencyStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class BudgetScopeKind(StrEnum):
    """GLOSSARY 6.45. ``PROVIDER`` is pending CCR-3A-5 (09 section 14 #2) and is not a value yet."""

    ORG = "ORG"
    WORKSPACE = "WORKSPACE"
    CHANNEL = "CHANNEL"
    PRODUCTION_TYPE = "PRODUCTION_TYPE"


class BudgetPeriod(StrEnum):
    """GLOSSARY 6.45. ``PILOT_TOTAL`` is pending CCR-3A-4 (09 section 14 #1): not a value yet."""

    DAY = "DAY"
    MONTH = "MONTH"
    PER_VIDEO = "PER_VIDEO"
    PER_JOB = "PER_JOB"


class BudgetState(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED_EXCEEDED = "SUSPENDED_EXCEEDED"
    DISABLED = "DISABLED"


class ReservationStatus(StrEnum):
    HELD = "HELD"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class CostFigureKind(StrEnum):
    ESTIMATE = "ESTIMATE"
    VERIFIED = "VERIFIED"


class BillingMode(StrEnum):
    STANDARD = "STANDARD"
    BATCH = "BATCH"
    CACHED_PROMPT = "CACHED_PROMPT"


class RulePackStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


# production_type_status "uses feature_status" (GLOSSARY 6.45).
ProductionTypeStatus = FeatureStatus


class ApiKeyStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class WebhookDeliveryStatus(StrEnum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    RETRYING = "RETRYING"
    FAILED_FINAL = "FAILED_FINAL"


class SubscriptionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(StrEnum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    VOID = "VOID"


class PlanStatus(StrEnum):
    PROPOSAL = "PROPOSAL"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class UsageMeter(StrEnum):
    VIDEOS = "VIDEOS"
    VIDEO_MINUTES = "VIDEO_MINUTES"
    RENDER_MINUTES = "RENDER_MINUTES"
    AI_SPEND = "AI_SPEND"
    STORAGE_BYTES = "STORAGE_BYTES"


class EntityKind(StrEnum):
    JOB = "JOB"
    TASK = "TASK"


# 6.46
class FigureLabel(StrEnum):
    ESTIMATE = "ESTIMATE"
    MEASURED = "MEASURED"
    PROJECTION = "PROJECTION"
    ACTUAL = "ACTUAL"
    PROPOSAL = "PROPOSAL"
    VERIFIED = "VERIFIED"


# 6.47
class Tier(StrEnum):
    TIER_0 = "TIER_0"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


# 6.48
class ProductionTypeKey(StrEnum):
    CHANNEL_LONG_FORM = "CHANNEL_LONG_FORM"
    SHORTS = "SHORTS"
    AD_SPOT = "AD_SPOT"
    EXPLAINER_CORPORATE_TRAINING = "EXPLAINER_CORPORATE_TRAINING"
    ECOMMERCE_PRODUCT = "ECOMMERCE_PRODUCT"
    DUBBING_LOCALISATION = "DUBBING_LOCALISATION"


# 6.49 (seconds; stored as duration_target_ms)
class AdSpotDurationS(IntEnum):
    S6 = 6
    S15 = 15
    S30 = 30
    S60 = 60

    @property
    def duration_target_ms(self) -> int:
        return int(self) * 1000


# 6.50
class AspectRatio(StrEnum):
    R16_9 = "16:9"
    R9_16 = "9:16"
    R1_1 = "1:1"
    R4_5 = "4:5"


# 6.51 (27 section 4)
class RefusalReason(StrEnum):
    INSUFFICIENT_INPUT = "INSUFFICIENT_INPUT"
    RULE_WOULD_BE_BROKEN = "RULE_WOULD_BE_BROKEN"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    CONFLICTING_INSTRUCTIONS = "CONFLICTING_INSTRUCTIONS"
    UNSAFE_CONTENT = "UNSAFE_CONTENT"


# 6.52 Contract-local value sets
class ControlCommandKind(StrEnum):
    DRAIN = "DRAIN"
    CANCEL = "CANCEL"
    PAUSE = "PAUSE"
    RESUME = "RESUME"


class ContextRefPurpose(StrEnum):
    KNOWLEDGE = "KNOWLEDGE"
    MEMORY = "MEMORY"
    PRIOR_OUTPUT = "PRIOR_OUTPUT"
    BRAND_KIT = "BRAND_KIT"
    COMPLIANCE_PROFILE = "COMPLIANCE_PROFILE"
    RULE_PACK = "RULE_PACK"
    ASSET = "ASSET"
    APPROVAL = "APPROVAL"
    TEMPLATE = "TEMPLATE"
    CLIENT_INPUT = "CLIENT_INPUT"


class OutputRefKind(StrEnum):
    SCRIPT = "SCRIPT"
    AUDIO = "AUDIO"
    VIDEO = "VIDEO"
    IMAGE = "IMAGE"
    SUBTITLE = "SUBTITLE"
    METADATA = "METADATA"
    REPORT = "REPORT"
    DATA = "DATA"
    CHECKPOINT_STATE = "CHECKPOINT_STATE"


class PayloadRefSchema(StrEnum):
    TASK_INPUT = "amw.task_input"
    TASK_OUTPUT = "amw.task_output"
    CONTROL = "amw.control"


# rule_flag_severity is "same as rule_severity".
RuleFlagSeverity = RuleSeverity


class GateOnFailAction(StrEnum):
    REVISE = "REVISE"
    STOP = "STOP"


class ParentInput(StrEnum):
    NONE = "NONE"
    PARENT_JOB = "PARENT_JOB"
    SOURCE_VIDEO = "SOURCE_VIDEO"


class LanguageMode(StrEnum):
    SINGLE = "SINGLE"
    MULTI = "MULTI"


class InputProvider(StrEnum):
    OWNER = "OWNER"
    CLIENT = "CLIENT"
    SYSTEM = "SYSTEM"


class ApprovalWorkflowKey(StrEnum):
    OWNER_ONE_TAP = "owner_one_tap"
    CLIENT_TWO_STEP = "client_two_step"
    OWNER_SENSITIVE = "owner_sensitive"


class DataAgeVsLag(StrEnum):
    """``UNKNOWN`` is treated as within the lag."""

    OLDER_THAN_LAG = "OLDER_THAN_LAG"
    WITHIN_LAG = "WITHIN_LAG"
    UNKNOWN = "UNKNOWN"


class SebiRegistrationStatus(StrEnum):
    UNREGISTERED = "UNREGISTERED"


class CitationInputKind(StrEnum):
    KNOWLEDGE_CHUNK = "KNOWLEDGE_CHUNK"
    EXTERNAL_REFERENCE = "EXTERNAL_REFERENCE"


class EvalCaseCategory(StrEnum):
    ANSWER_KEY = "ANSWER_KEY"
    HARD_NEGATIVE = "HARD_NEGATIVE"
    EDGE = "EDGE"
    REFUSAL = "REFUSAL"
    POSITIVE = "POSITIVE"


class CcrStatus(StrEnum):
    PROPOSED = "Proposed"
    NEEDS_OWNER = "Needs owner"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    APPLIED = "Applied"


class CostUnitKind(StrEnum):
    CHARACTERS = "characters"
    AUDIO_MS = "audio_ms"
    IMAGES = "images"
    VIDEO_MS = "video_ms"
    RENDER_MS = "render_ms"
    QUOTA_UNITS = "quota_units"
    ITEMS = "items"
    BYTES = "bytes"


class QueueName(StrEnum):
    LIGHT = "light"
    AI = "ai"
    RENDER = "render"
    PUBLISH = "publish"


class TransitionId(StrEnum):
    """Task transitions T01-T20 (03 section 11.3) and job transitions J01-J12 (03 section 11.5)."""

    T01 = "T01"
    T02 = "T02"
    T03 = "T03"
    T04 = "T04"
    T05 = "T05"
    T06 = "T06"
    T07 = "T07"
    T08 = "T08"
    T09 = "T09"
    T10 = "T10"
    T11 = "T11"
    T12 = "T12"
    T13 = "T13"
    T14 = "T14"
    T15 = "T15"
    T16 = "T16"
    T17 = "T17"
    T18 = "T18"
    T19 = "T19"
    T20 = "T20"
    J01 = "J01"
    J02 = "J02"
    J03 = "J03"
    J04 = "J04"
    J05 = "J05"
    J06 = "J06"
    J07 = "J07"
    J08 = "J08"
    J09 = "J09"
    J10 = "J10"
    J11 = "J11"
    J12 = "J12"

    @property
    def entity_kind(self) -> EntityKind:
        return EntityKind.TASK if self.value.startswith("T") else EntityKind.JOB


GLOSSARY_ENUMS: Mapping[str, type[Enum]] = MappingProxyType(
    {
        "task_state": TaskState,
        "job_state": JobState,
        "wait_reason": WaitReason,
        "job_outcome": JobOutcome,
        "priority": Priority,
        "resource_class": ResourceClass,
        "queue_item_status": QueueItemStatus,
        "attempt_result": AttemptResult,
        "output_status": OutputStatus,
        "next_action_type": NextActionType,
        "feature_status": FeatureStatus,
        "doc_status": DocStatus,
        "approval_state": ApprovalState,
        "approval_step_state": ApprovalStepState,
        "approval_kind": ApprovalKind,
        "editorial_contribution_type": EditorialContributionType,
        "licence_state": LicenceState,
        "licence_source_type": LicenceSourceType,
        "visual_source_tier": VisualSourceTier,
        "capability": Capability,
        "third_party_permission": ThirdPartyPermission,
        "licence_usage_kind": LicenceUsageKind,
        "publish_state": PublishState,
        "privacy_status": PrivacyStatus,
        "verification_state": VerificationState,
        "destination_kind": DestinationKind,
        "check_verdict": CheckVerdict,
        "check_kind": CheckKind,
        "compliance_verdict": ComplianceVerdict,
        "memory_scope": MemoryScope,
        "failure_class": FailureClass,
        "circuit_state": CircuitState,
        "dlq_recovery_status": DlqRecoveryStatus,
        "escalation_level": EscalationLevel,
        "experiment_state": ExperimentState,
        "experiment_decision": ExperimentDecision,
        "experiment_kind": ExperimentKind,
        "rule_pack_scope": RulePackScope,
        "rule_severity": RuleSeverity,
        "rule_pack_key": RulePackKey,
        "fin_rule_id": FinRuleId,
        "claim_type": ClaimType,
        "claim_status": ClaimStatus,
        "time_reference_kind": TimeReferenceKind,
        "quota_bucket": QuotaBucket,
        "disclosure_decision": DisclosureDecision,
        "role": Role,
        "org_kind": OrgKind,
        "org_status": OrgStatus,
        "workspace_status": WorkspaceStatus,
        "project_status": ProjectStatus,
        "project_kind": ProjectKind,
        "user_status": UserStatus,
        "membership_status": MembershipStatus,
        "invitation_state": InvitationState,
        "auth_provider": AuthProvider,
        "channel_platform": ChannelPlatform,
        "channel_status": ChannelStatus,
        "oauth_token_status": OauthTokenStatus,
        "data_key_status": DataKeyStatus,
        "gcp_ownership": GcpOwnership,
        "google_review_status": GoogleReviewStatus,
        "actor_kind": ActorKind,
        "consent_state": ConsentState,
        "voice_kind": VoiceKind,
        "data_request_kind": DataRequestKind,
        "data_request_status": DataRequestStatus,
        "script_status": ScriptStatus,
        "render_kind": RenderKind,
        "render_status": RenderStatus,
        "asset_kind": AssetKind,
        "asset_status": AssetStatus,
        "fingerprint_algo": FingerprintAlgo,
        "knowledge_source_kind": KnowledgeSourceKind,
        "knowledge_source_status": KnowledgeSourceStatus,
        "source_ownership": SourceOwnership,
        "citation_support": CitationSupport,
        "quality_dimension": QualityDimension,
        "analytics_source": AnalyticsSource,
        "notification_channel": NotificationChannel,
        "notification_status": NotificationStatus,
        "comment_triage_class": CommentTriageClass,
        "reply_state": ReplyState,
        "worker_status": WorkerStatus,
        "idempotency_status": IdempotencyStatus,
        "budget_scope_kind": BudgetScopeKind,
        "budget_period": BudgetPeriod,
        "budget_state": BudgetState,
        "reservation_status": ReservationStatus,
        "cost_figure_kind": CostFigureKind,
        "billing_mode": BillingMode,
        "rule_pack_status": RulePackStatus,
        "production_type_status": ProductionTypeStatus,
        "api_key_status": ApiKeyStatus,
        "webhook_delivery_status": WebhookDeliveryStatus,
        "subscription_status": SubscriptionStatus,
        "invoice_status": InvoiceStatus,
        "plan_status": PlanStatus,
        "usage_meter": UsageMeter,
        "entity_kind": EntityKind,
        "figure_label": FigureLabel,
        "tier": Tier,
        "production_type_key": ProductionTypeKey,
        "ad_spot_duration_s": AdSpotDurationS,
        "aspect_ratio": AspectRatio,
        "refusal_reason": RefusalReason,
        "control_command": ControlCommandKind,
        "context_ref_purpose": ContextRefPurpose,
        "output_ref_kind": OutputRefKind,
        "payload_ref_schema": PayloadRefSchema,
        "rule_flag_severity": RuleFlagSeverity,
        "gate_on_fail_action": GateOnFailAction,
        "parent_input": ParentInput,
        "language_mode": LanguageMode,
        "input_provider": InputProvider,
        "approval_workflow_key": ApprovalWorkflowKey,
        "data_age_vs_lag": DataAgeVsLag,
        "sebi_registration_status": SebiRegistrationStatus,
        "citation_input_kind": CitationInputKind,
        "eval_case_category": EvalCaseCategory,
        "ccr_status": CcrStatus,
        "cost_unit_kind": CostUnitKind,
        "queue_name": QueueName,
        "transition_id": TransitionId,
    }
)
