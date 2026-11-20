"""``FactRowReader`` of agent_16 on PostgreSQL (blueprint section 15.1a / 15.1b sources).

Read only: SELECTs inside the caller's tenant transaction as ``amw_app``, each with an explicit
``org_id`` predicate on top of RLS. It writes nothing. A row that is absent from the tenant
(another tenant's rows are invisible) yields the port's "absent" value (``None``, empty), never a
default that could pass a check.

Sources and the provisional answers where 04 has no column (CCR-300, PROPOSED, fail closed):

* ``channel``: ``channels.category`` verbatim (CCR-295: the raw value), ``audience_kind`` (NULL =
  not decided); ``knowledge_collection_id`` has no table yet, so ``None``.
* ``job``: ``language`` and ``production_type_key`` from ``jobs``; ``live_format`` is ``STANDARD``
  (15.1a: every 3A production type); the active packs are the always-on platform packs plus the
  packs of the channel's compliance profile (``ACTIVE`` only); the routing stage IDs are the
  ``tasks.stage_id`` of the job's non-cancelled tasks of the script / assets / thumbnails task
  types, which is exactly the stage graph materialised from the production-type record (a
  disabled stage has no task, 15.1a "thumbnails disabled => null"). A stage that is missing or
  maps to two stage IDs makes the whole row ``None``.
* ``voice_presenter_kind``: no table links a job to its voice (``voices`` is a catalogue), so the
  answer is always ``None`` (15.1a: no voice record => ``NEEDS_HUMAN_REVIEW``, F-08).
* ``claims``: ``citations`` and ``claims.chart_data_ref`` do not exist, so ``citation_count`` is 0
  and ``chart_data_ref`` is ``None`` (the stricter reading, 15.1b). The ``SENSITIVE_CLAIM``
  approval is the newest approval of that kind whose ``subject_id`` is the claim; its state is
  derived later by the approval verifier, never here.
* ``assets`` joins ``assets``, ``licences`` and ``licence_ledger``; the port carries no job ID, so
  ``has_ledger_row`` means "the asset has a ledger row of this tenant" (REQUIRES REVIEW: CCR-300
  asks for the job ID on the port).
"""

from collections.abc import Sequence
from typing import Any, Final, Literal

from agent_16_compliance_qa.inputs.extractors import AssetFactRow, ChannelRow, ClaimRow, JobRow
from agent_16_compliance_qa.scoring.aggregate import QcRow
from amw_core.enums import (
    AudienceKind,
    CheckVerdict,
    ClaimStatus,
    LicenceState,
    PresenterKind,
    VisualSourceTier,
)
from amw_core.errors import InputInvalidError
from amw_core.ids import APPROVAL, ASSET, JOB, RENDER, format_id
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_orchestrator.db_adapters._sql import CLAIM, org_of, rows, uuid_of

SCRIPT_TASK_TYPES: Final = ("agent_05.script_draft", "agent_05.shorts_adaptation")
ASSETS_TASK_TYPE: Final = "agent_08.asset_sourcing"
THUMBNAILS_TASK_TYPE: Final = "agent_11.thumbnail_variants"
JUDGED_MESSAGE: Final = "JUDGED_BY_AGENT_16"
"""``qc_results.message`` of a check agent_10 skipped for agent_16's frame judge (15.1a)."""
THUMBNAIL_CHECK_PREFIX: Final = "a11."
_LATEST_QC: Final = (
    "SELECT DISTINCT ON (check_id) check_id, verdict FROM qc_results WHERE org_id = %s AND {scope}"
    " ORDER BY check_id, created_at DESC, id DESC"
)


def _single(stage_ids: Sequence[Any]) -> str | None:
    """The one stage ID of a stage kind; two different IDs make the routing ambiguous (``None``)."""
    distinct = {str(s) for s in stage_ids}
    return next(iter(distinct)) if len(distinct) == 1 else None


class PgFactRowReader:
    # -- channel and job -----------------------------------------------------------------
    def channel(self, tx: TenantTransaction, job_id: str) -> ChannelRow | None:
        found = rows(
            tx,
            "SELECT c.category, c.audience_kind FROM jobs j"
            " JOIN channels c ON c.org_id = j.org_id AND c.id = j.channel_id"
            " WHERE j.org_id = %s AND j.id = %s",
            (org_of(tx), uuid_of(JOB, job_id)),
        )
        if not found:
            return None
        category, audience = found[0]
        return ChannelRow(
            category if isinstance(category, str) else None,
            AudienceKind(audience) if audience is not None else None,
            None,
        )

    def job(self, tx: TenantTransaction, job_id: str) -> JobRow | None:
        org, job = org_of(tx), uuid_of(JOB, job_id)
        base = rows(
            tx,
            "SELECT language, production_type_key, channel_id FROM jobs"
            " WHERE org_id = %s AND id = %s",
            (org, job),
        )
        if not base:
            return None
        language, type_key, channel = base[0]
        stages = self._stages(tx, org, job)
        script, assets = stages.get("script"), stages.get("assets")
        if script is None or assets is None:
            return None
        return JobRow(
            language=str(language),
            production_type_key=str(type_key),
            live_format="STANDARD",
            active_pack_keys=self._pack_keys(tx, org, channel),
            routing_script_stage_id=script,
            routing_assets_stage_id=assets,
            routing_thumbnails_stage_id=stages.get("thumbnails"),
        )

    @staticmethod
    def _stages(tx: TenantTransaction, org: Any, job: Any) -> dict[str, str]:
        found = rows(
            tx,
            "SELECT DISTINCT task_type, stage_id FROM tasks WHERE org_id = %s AND job_id = %s"
            " AND stage_id IS NOT NULL AND state <> 'CANCELLED' AND task_type = ANY(%s)",
            (org, job, [*SCRIPT_TASK_TYPES, ASSETS_TASK_TYPE, THUMBNAILS_TASK_TYPE]),
        )
        kinds = {
            "script": [r for r in found if r[0] in SCRIPT_TASK_TYPES],
            "assets": [r for r in found if r[0] == ASSETS_TASK_TYPE],
            "thumbnails": [r for r in found if r[0] == THUMBNAILS_TASK_TYPE],
        }
        out: dict[str, str] = {}
        for kind, group in kinds.items():
            stage = _single([r[1] for r in group])
            if stage is not None:
                out[kind] = stage
        return out

    @staticmethod
    def _pack_keys(tx: TenantTransaction, org: Any, channel: Any) -> tuple[str, ...]:
        found = rows(
            tx,
            "SELECT p.key FROM rule_packs p WHERE p.status = 'ACTIVE' AND p.always_on"
            " AND (p.org_id IS NULL OR p.org_id = %s)"
            " UNION SELECT p.key FROM channels c"
            " JOIN compliance_profiles cp ON cp.org_id = c.org_id"
            "   AND cp.id = c.compliance_profile_id"
            " JOIN compliance_profile_rule_packs cpp ON cpp.org_id = cp.org_id"
            "   AND cpp.profile_id = cp.id"
            " JOIN rule_packs p ON p.id = cpp.rule_pack_id"
            " WHERE c.org_id = %s AND c.id = %s AND cp.status = 'ACTIVE' AND p.status = 'ACTIVE'"
            " ORDER BY 1",
            (org, org, channel),
        )
        return tuple(str(r[0]) for r in found)

    # -- voice, assets ---------------------------------------------------------------------
    def voice_presenter_kind(self, tx: TenantTransaction, job_id: str) -> PresenterKind | None:
        org_of(tx)  # the transaction must still be a tenant transaction (and the job ID valid)
        uuid_of(JOB, job_id)
        return None

    def assets(self, tx: TenantTransaction, asset_ids: Sequence[str]) -> dict[str, AssetFactRow]:
        wanted = {uuid_of(ASSET, a): a for a in asset_ids}
        if not wanted:
            return {}
        found = rows(
            tx,
            "SELECT a.id, a.visual_source_tier, a.depicts_real_person, a.is_realistic_synthetic,"
            " EXISTS (SELECT 1 FROM licence_ledger ll WHERE ll.org_id = a.org_id"
            "   AND ll.asset_id = a.id),"
            " l.state, l.covers_monetized_youtube, l.third_party_permission"
            " FROM assets a LEFT JOIN licences l ON l.id = a.licence_id"
            " WHERE a.org_id = %s AND a.id = ANY(%s)",
            (org_of(tx), list(wanted)),
        )
        out: dict[str, AssetFactRow] = {}
        for aid, tier, person, synthetic, ledger, state, covers, permission in found:
            wire = wanted[aid]
            out[wire] = AssetFactRow(
                asset_id=wire,
                tier=VisualSourceTier(tier) if tier is not None else None,
                shows_person=person,
                is_realistic_synthetic=synthetic,
                has_ledger_row=bool(ledger),
                licence_state=LicenceState(state) if state is not None else None,
                covers_monetized_youtube=covers,
                third_party_permission=_third_party(permission),
            )
        return out

    # -- approvals -------------------------------------------------------------------------
    def release_approval_subjects(
        self, tx: TenantTransaction, approval_ids: Sequence[str]
    ) -> dict[str, str]:
        wanted = {uuid_of(APPROVAL, a): a for a in approval_ids}
        if not wanted:
            return {}
        found = rows(
            tx,
            "SELECT id, subject_sha256 FROM approvals WHERE org_id = %s"
            " AND kind = 'KNOWLEDGE_RELEASE' AND subject_sha256 IS NOT NULL AND id = ANY(%s)",
            (org_of(tx), list(wanted)),
        )
        return {wanted[r[0]]: bytes(r[1]).hex() for r in found}

    def copyright_doubt_approvals(
        self, tx: TenantTransaction, span_hashes: Sequence[str]
    ) -> dict[str, str]:
        digests = {_digest(h): h for h in span_hashes}
        if not digests:
            return {}
        found = rows(
            tx,
            "SELECT DISTINCT ON (subject_sha256) subject_sha256, id FROM approvals"
            " WHERE org_id = %s AND kind = 'COPYRIGHT_DOUBT' AND subject_sha256 = ANY(%s)"
            " ORDER BY subject_sha256, created_at DESC, id DESC",
            (org_of(tx), list(digests)),
        )
        return {digests[bytes(r[0])]: format_id(APPROVAL.prefix, r[1]) for r in found}

    # -- QC rows ---------------------------------------------------------------------------
    def judged_qc_check_ids(self, tx: TenantTransaction, render_id: str) -> tuple[str, ...]:
        found = rows(
            tx,
            "SELECT DISTINCT check_id FROM qc_results WHERE org_id = %s AND render_id = %s"
            " AND verdict = 'SKIPPED' AND message = %s ORDER BY check_id",
            (org_of(tx), uuid_of(RENDER, render_id), JUDGED_MESSAGE),
        )
        return tuple(str(r[0]) for r in found)

    def qc_rows(self, tx: TenantTransaction, render_id: str) -> tuple[QcRow, ...] | None:
        org, render = org_of(tx), uuid_of(RENDER, render_id)
        if not rows(tx, "SELECT 1 FROM renders WHERE org_id = %s AND id = %s", (org, render)):
            return None
        found = rows(tx, _LATEST_QC.format(scope="render_id = %s"), (org, render))
        return tuple(QcRow(check_id=str(r[0]), verdict=CheckVerdict(r[1])) for r in found)

    def thumbnail_qc_rows(self, tx: TenantTransaction, job_id: str) -> tuple[QcRow, ...]:
        found = rows(
            tx,
            _LATEST_QC.format(scope="job_id = %s AND starts_with(check_id, %s)"),
            (org_of(tx), uuid_of(JOB, job_id), THUMBNAIL_CHECK_PREFIX),
        )
        return tuple(QcRow(check_id=str(r[0]), verdict=CheckVerdict(r[1])) for r in found)

    # -- claims ----------------------------------------------------------------------------
    def claims(self, tx: TenantTransaction, claim_ids: Sequence[str]) -> tuple[ClaimRow, ...]:
        wanted = {uuid_of(CLAIM, c): c for c in claim_ids}
        if not wanted:
            return ()
        org = org_of(tx)
        found = rows(
            tx,
            "SELECT id, claim_type, status FROM claims WHERE org_id = %s AND id = ANY(%s)"
            " ORDER BY id",
            (org, list(wanted)),
        )
        approvals = rows(
            tx,
            "SELECT DISTINCT ON (subject_id) subject_id, id, subject_sha256 FROM approvals"
            " WHERE org_id = %s AND kind = 'SENSITIVE_CLAIM' AND subject_sha256 IS NOT NULL"
            " AND subject_id = ANY(%s) ORDER BY subject_id, created_at DESC, id DESC",
            (org, list(wanted)),
        )
        bound = {r[0]: (format_id(APPROVAL.prefix, r[1]), bytes(r[2]).hex()) for r in approvals}
        return tuple(
            ClaimRow(
                claim_id=wanted[cid],
                claim_type=str(ctype),
                status=ClaimStatus(status) if status is not None else None,
                citation_count=0,
                chart_data_ref=None,
                sensitive_approval=bound.get(cid),
            )
            for cid, ctype, status in found
        )


def _digest(hex_digest: str) -> bytes:
    try:
        digest = bytes.fromhex(hex_digest)
    except ValueError:
        raise InputInvalidError("span hash is not hexadecimal") from None
    if len(digest) != 32:
        raise InputInvalidError("span hash must be 32 bytes")
    return digest


def _third_party(value: Any) -> Literal["PERMITTED", "NOT_PERMITTED", "UNKNOWN"] | None:
    if value is None:
        return None
    if value == "PERMITTED":
        return "PERMITTED"
    if value == "NOT_PERMITTED":
        return "NOT_PERMITTED"
    return "UNKNOWN"  # any other value is read as not known (fail closed)
