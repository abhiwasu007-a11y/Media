"""Run preflight (``amw_runtime``, PR #70) against real-path evidence. In real-run mode:
- TEST confirmation fixtures are refused;
- a provider-limit or FIN-R10 confirmation passes only with a CONFIRMED, MAC-valid,
  production-marked owner-chat evidence row of the run's org whose quote states what the
  confirmation claims (``ConfirmedEvidenceLookup``: ``org_id`` and ``subject`` of PR #70's
  ``EvidenceView``).

Skipped while ``amw_runtime`` is not in the workspace (it is on its own branch). The modules are
imported by name so this file type-checks without it; it was run on a local merge with PR #70.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from amw_core import ids
from amw_core.enums import EvidenceRecordKind
from amw_core.errors import ConfigInvalidError
from amw_core.interfaces import DbRole
from amw_core.owner_evidence_real import ConfirmationOutcome, ConfirmedEvidenceLookup
from tests.adapters.test_session_record_flow import APPROVAL, make_world
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
QUOTES = {
    "anthropic": "{code} anthropic spending limit is 10 USD",
    "elevenlabs": "{code} elevenlabs spending limit is 10.00 USD",
    "fin": "{code} SEBI registration status statement for this channel",
}
CODES = {"anthropic": "R7K2", "elevenlabs": "M4P9", "fin": "H3W8"}
KINDS = frozenset({EvidenceRecordKind.CONTRIBUTION})


def record(org: str, which: str, evidence_id: str | None, **kw: object) -> Any:
    kind = confirmations.ConfirmationKind
    base: dict[str, object] = {
        "org_id": org,
        "recorded_from": "OWNER_CHAT_OPERATOR",
        "evidence_id": evidence_id,
        "verified": True,
    }
    if which == "fin":
        base["kind"] = kind.FIN_R10_NOT_SEBI_REGISTERED
    else:
        base |= {"kind": kind.PROVIDER_LIMIT, "provider": which, "amount_minor": 1000}
        base["currency"] = "USD"
    return confirmations.ConfirmationRecord(**{**base, **kw})


def run(records: list[Any], lookup: Any, org: str) -> Any:
    config = runtime_config.load_runtime_config({"AMW_RUNTIME_MODE": "REAL_RUN"})
    return preflight.run_preflight(
        config.model_copy(update={"render_max_duration_minutes": 60}),
        records,
        env={**DEV, **SECRETS},
        evidence=lookup,
        render_start=EVENING,
        org_id=org,
    )


def evidence_world(tmp_path: Path, *, confirm: bool = True) -> tuple[Any, dict[str, str], str]:
    """One owner-chat evidence row per confirmation, each under its own approval code."""
    w = make_world(tmp_path)
    rows: dict[str, Any] = {}
    for i, which in enumerate(("anthropic", "elevenlabs", "fin")):
        approval = APPROVAL if which == "anthropic" else ids.new_id(ids.Prefix.APPROVAL)
        if which != "anthropic":
            w.db.register_approval_code(w.tx, CODES[which], approval)
        quote = QUOTES[which].format(code=CODES[which])
        uid = w.t.human(quote, minutes(5 + i))
        w.write()
        rows[which] = w.record(
            uid,
            quote,
            minutes(5 + i),
            record_kind=EvidenceRecordKind.CONTRIBUTION,
            parsed_decision=None,
            job_id=ids.JOB.new(),
            approval_id=ids.ApprovalId(approval),
            review_code=CODES[which],
        )
    for i, (which, row) in enumerate(rows.items()):
        w.t.human(f"confirm {CODES[which]}", minutes(8 + i))
        w.write()
        if confirm:
            w.verify(row)
            assert w.scan(row).outcome is ConfirmationOutcome.CONFIRMED
    app = w.db.login(DbRole.APP, PASSWORDS[DbRole.APP])
    org = next(iter(rows.values())).org_id
    ids_ = {which: row.id for which, row in rows.items()}
    records = [record(org, which, ids_[which]) for which in rows]
    lookup = ConfirmedEvidenceLookup.for_confirmations(
        w.db, app, w.tx, records, allowed_kinds=KINDS, currency_exponents={"USD": 2}
    )
    return lookup, ids_, org


def test_real_run_passes_only_with_confirmed_owner_chat_evidence(tmp_path: Path) -> None:
    lookup, ids_, org = evidence_world(tmp_path)
    records = [record(org, which, ids_[which]) for which in ids_]
    report = run(records, lookup, org)
    assert not report.test_confirmation_used
    assert "FIN_R10" in report.checks_passed
    (tmp_path / "p").mkdir()
    pending, pending_ids, pending_org = evidence_world(tmp_path / "p", confirm=False)
    with pytest.raises(runtime_errors.PreflightRefused):
        run([record(pending_org, w, pending_ids[w]) for w in pending_ids], pending, pending_org)
    with pytest.raises(runtime_errors.PreflightRefused):  # bound to another org
        run(records, lookup, ids.ORG.new())


def test_one_row_cannot_back_two_confirmations(tmp_path: Path) -> None:
    lookup, ids_, org = evidence_world(tmp_path)
    shared = [record(org, which, ids_["anthropic"]) for which in PROVIDERS]
    with pytest.raises(ConfigInvalidError):
        ConfirmedEvidenceLookup.for_confirmations(None, None, None, shared)  # type: ignore[arg-type]  # refused before any database call
    with pytest.raises(runtime_errors.PreflightRefused):  # and the preflight refuses reuse too
        run([*shared, record(org, "fin", ids_["fin"])], lookup, org)


def test_real_run_refuses_test_fixture_even_with_confirmed_evidence(tmp_path: Path) -> None:
    lookup, ids_, org = evidence_world(tmp_path)
    records = [record(org, w, ids_[w], test_fixture=True) for w in PROVIDERS]
    with pytest.raises(runtime_errors.PreflightRefused) as exc:
        run([*records, record(org, "fin", ids_["fin"])], lookup, org)
    assert {f"PROVIDER_LIMIT:{p}" for p in PROVIDERS} <= {i.code for i in exc.value.items}


def test_fin_r10_needs_evidence_in_real_run(tmp_path: Path) -> None:
    """Was a strict xfail (CCR-261); PR #70 now looks FIN-R10 evidence up."""
    lookup, ids_, org = evidence_world(tmp_path)
    limits = [record(org, w, ids_[w]) for w in PROVIDERS]
    with pytest.raises(runtime_errors.PreflightRefused) as exc:
        run([*limits, record(org, "fin", None)], lookup, org)
    assert "FIN_R10" in {i.code for i in exc.value.items}
