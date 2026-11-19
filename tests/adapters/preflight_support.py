"""A REAL preflight for tests: the only way to get a provider authorisation (it is sealed)."""

from datetime import datetime, timedelta, timezone
from typing import Any

from amw_core.ids import ORG
from amw_core.owner_evidence_status import EvidenceSourceKind, EvidenceStatus
from amw_runtime.config import load_runtime_config
from amw_runtime.confirmations import ConfirmationKind, ConfirmationRecord
from amw_runtime.preflight import PreflightReport, run_preflight
from tests.adapters.mock_providers import TEST_ENV

IST = timezone(timedelta(hours=5, minutes=30))
EVENING = datetime(2026, 11, 19, 20, 0, tzinfo=IST)  # a Thursday, after the guard window
REAL_ENV = {"AMW_RUNTIME_MODE": "REAL_RUN", "AMW_ENVIRONMENT": "development", **TEST_ENV}
ORG_ID = ORG.new()


class Lookup:
    """Fake evidence store: each evidence id maps to a CONFIRMED, MAC-valid, REAL row bound to
    its record (the shared amw_core evidence contract)."""

    def __init__(self, records: list[ConfirmationRecord], org: str = ORG_ID) -> None:
        self.rows = {
            r.evidence_id: EvidenceStatus(
                evidence_id=r.evidence_id, evidence_state="CONFIRMED",
                recorded_from="OWNER_CHAT_OPERATOR", org_id=org, kind=r.kind.value,
                subject_kind="ORG", subject_id=org, subject=r.subject(),
                source_kind=EvidenceSourceKind.REAL, mac_valid=True,
            )
            for r in records
            if r.evidence_id
        }  # fmt: skip

    def get(self, evidence_id: str) -> EvidenceStatus | None:
        return self.rows.get(evidence_id)


def limits(org: str = ORG_ID) -> list[ConfirmationRecord]:
    """The owner confirmations a REAL_RUN preflight needs today: both provider limits and
    FIN-R10 (the preflight still demands FIN-R10 for every real run; D13 narrows it to finance
    channels in a separate change, so this lane does not touch that rule)."""
    records = [
        ConfirmationRecord(
            kind=ConfirmationKind.PROVIDER_LIMIT, provider=p, amount_minor=500, currency="USD",
            org_id=org, recorded_from="OWNER_CHAT_OPERATOR", evidence_id=f"ev-{p}",
            verified=True,
        )
        for p in ("anthropic", "elevenlabs")
    ]  # fmt: skip
    records.append(
        ConfirmationRecord(
            kind=ConfirmationKind.FIN_R10_NOT_SEBI_REGISTERED, org_id=org,
            recorded_from="OWNER_CHAT_OPERATOR", evidence_id="ev-r10", verified=True,
        )
    )  # fmt: skip
    return records


def passed_report(
    *,
    org_id: str = ORG_ID,
    job_id: str | None = None,
    cap_micros: int | None = None,
    ttl: timedelta | None = None,
) -> PreflightReport:
    config = load_runtime_config(REAL_ENV)
    if cap_micros is not None:
        config = config.model_copy(update={"per_video_cap_micros": cap_micros})
    extra: dict[str, Any] = {} if ttl is None else {"authorisation_ttl": ttl}
    return run_preflight(
        config, limits(org_id), env=REAL_ENV, evidence=Lookup(limits(org_id), org_id),
        render_start=EVENING,
        org_id=org_id, job_id=job_id, **extra,
    )  # fmt: skip
