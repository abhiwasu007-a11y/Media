"""Run preflight (``amw_runtime``, PR #70) against real-path evidence: TEST confirmation fixtures
are refused in real-run mode, and a provider-limit confirmation passes only with a CONFIRMED,
MAC-valid owner-chat evidence row (``ConfirmedEvidenceLookup``).

Skipped while ``amw_runtime`` is not in the workspace (it is on its own branch); the modules are
imported by name so this file type-checks without it.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from amw_core.interfaces import DbRole
from amw_core.owner_evidence_real import ConfirmedEvidenceLookup
from tests.adapters.test_session_record_flow import make_world
from tests.evidence_support import PASSWORDS
from tests.session_transcript import minutes

preflight: Any = pytest.importorskip("amw_runtime.preflight")
confirmations: Any = pytest.importorskip("amw_runtime.confirmations")
runtime_config: Any = pytest.importorskip("amw_runtime.config")
runtime_errors: Any = pytest.importorskip("amw_runtime.errors")

pytestmark = [pytest.mark.integration, pytest.mark.security]
IST = timezone(timedelta(hours=5, minutes=30))
EVENING = datetime(2026, 11, 19, 20, 0, tzinfo=IST)
DEV = {"AMW_ENVIRONMENT": "development"}
SECRETS = {"AMW_SECRET_ANTHROPIC_API_KEY": "x" * 24, "AMW_SECRET_ELEVENLABS_API_KEY": "x" * 24}
PROVIDERS = ("anthropic", "elevenlabs")


def limit(provider: str, evidence_id: str | None, **kw: object) -> Any:
    base: dict[str, object] = {
        "kind": confirmations.ConfirmationKind.PROVIDER_LIMIT,
        "provider": provider,
        "amount_minor": 1000,
        "currency": "USD",
        "recorded_from": "OWNER_CHAT_OPERATOR",
        "evidence_id": evidence_id,
        "verified": True,
    }
    return confirmations.ConfirmationRecord(**{**base, **kw})


def run(records: list[Any], lookup: Any) -> Any:
    return preflight.run_preflight(
        runtime_config.load_runtime_config({"AMW_RUNTIME_MODE": "REAL_RUN"}),
        records,
        env={**DEV, **SECRETS},
        evidence=lookup,
        render_start=EVENING,
    )


def confirmed_lookup(tmp_path: Path, *, confirm: bool = True) -> tuple[Any, str]:
    w = make_world(tmp_path)
    uid = w.t.human("approve R7K2", minutes(5))
    w.t.human("confirm R7K2", minutes(8))
    w.write()
    row = w.record(uid, "approve R7K2", minutes(5))
    if confirm:
        w.verify(row)
        w.worker.confirm_from_chat(w.tx, row.id, minutes(30))
    app = w.db.login(DbRole.APP, PASSWORDS[DbRole.APP])
    return ConfirmedEvidenceLookup(w.db, app, w.tx), row.id


def test_real_run_passes_only_with_confirmed_owner_chat_evidence(tmp_path: Path) -> None:
    lookup, evidence_id = confirmed_lookup(tmp_path)
    report = run([limit(p, evidence_id) for p in PROVIDERS], lookup)
    assert not report.test_confirmation_used
    (tmp_path / "p").mkdir()
    pending, pending_id = confirmed_lookup(tmp_path / "p", confirm=False)
    with pytest.raises(runtime_errors.PreflightRefused):
        run([limit(p, pending_id) for p in PROVIDERS], pending)


def test_real_run_refuses_test_fixture_even_with_confirmed_evidence(tmp_path: Path) -> None:
    lookup, evidence_id = confirmed_lookup(tmp_path)
    records = [limit(p, evidence_id, test_fixture=True) for p in PROVIDERS]
    with pytest.raises(runtime_errors.PreflightRefused) as exc:
        run(records, lookup)
    assert {i.code for i in exc.value.items} == {f"PROVIDER_LIMIT:{p}" for p in PROVIDERS}


@pytest.mark.xfail(
    strict=True,
    reason="CCR-261: FIN-R10 is cleared by a self-asserted verified=True record; the preflight "
    "does not look the evidence up in real-run mode",
)
def test_fin_r10_needs_evidence_in_real_run(tmp_path: Path) -> None:
    lookup, evidence_id = confirmed_lookup(tmp_path)
    fin = confirmations.ConfirmationRecord(
        kind=confirmations.ConfirmationKind.FIN_R10_NOT_SEBI_REGISTERED,
        recorded_from="OWNER_CHAT_OPERATOR",
        evidence_id=None,
        verified=True,
    )
    report = run([*(limit(p, evidence_id) for p in PROVIDERS), fin], lookup)
    assert report.open_owner_items  # no evidence: the owner item must stay open
