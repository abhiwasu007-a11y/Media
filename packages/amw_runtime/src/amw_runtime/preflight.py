"""Preflight (interface 2): refuses a run unless every requirement holds; lists every unmet item.

Dry-run mode skips the secret check (and says so) and may use a TEST confirmation fixture (the
report says so). Real-run mode needs verified, evidence-backed owner confirmations.
"""

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from amw_runtime.calendar import MarketCalendar, now_utc
from amw_runtime.config import RunMode, RuntimeConfig
from amw_runtime.confirmations import ConfirmationKind, ConfirmationRecord, EvidenceLookup
from amw_runtime.disclaimer import Disclaimer, get_disclaimer
from amw_runtime.errors import DisclaimerError, PreflightRefused, UnmetItem

SUPPORTED_LAG_UNIT = "CALENDAR_DAYS"
CONFIRMED = "CONFIRMED"
OWNER_CHANNEL = "OWNER_CHAT_OPERATOR"


@dataclass(frozen=True)
class PreflightReport:
    mode: RunMode
    checks_passed: tuple[str, ...]
    secrets_checked: bool
    test_confirmation_used: bool
    disclaimer_status: str
    open_owner_items: tuple[str, ...]
    notes: tuple[str, ...] = field(default=())


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() not in {"", "0", "false", "no"}


def _limit_problem(
    config: RuntimeConfig,
    provider: str,
    records: Sequence[ConfirmationRecord],
    evidence: EvidenceLookup | None,
) -> tuple[str | None, bool]:
    """(problem or None, used_test_fixture) for one provider's spending-limit confirmation."""
    mine = [
        r for r in records if r.kind is ConfirmationKind.PROVIDER_LIMIT and r.provider == provider
    ]
    if not mine:
        return "no owner confirmation of the provider spending limit", False
    reasons: list[str] = []
    for rec in mine:
        if rec.currency not in config.currency_minor_exponent or (rec.amount_minor or 0) <= 0:
            reasons.append("limit amount/currency invalid")
        elif not rec.verified:
            reasons.append("confirmation not verified")
        elif rec.test_fixture:
            if config.mode is RunMode.REAL_RUN:
                reasons.append("TEST confirmation fixture refused in real-run mode")
            else:
                return None, True
        elif not (rec.evidence_id or rec.review_code):
            reasons.append("no evidence id or review code")
        elif evidence is None or rec.evidence_id is None:
            reasons.append("owner-evidence lookup needed to verify the record")
        else:
            row = evidence.get(rec.evidence_id)
            if row is None or row.evidence_state != CONFIRMED or row.recorded_from != OWNER_CHANNEL:
                reasons.append("evidence row is not CONFIRMED from the owner chat channel")
            else:
                return None, False
    return "; ".join(dict.fromkeys(reasons)), False


def run_preflight(
    config: RuntimeConfig,
    confirmations: Sequence[ConfirmationRecord],
    *,
    env: Mapping[str, str] | None = None,
    evidence: EvidenceLookup | None = None,
    calendar: MarketCalendar | None = None,
    render_start: datetime | None = None,
) -> PreflightReport:
    """Raise ``PreflightRefused`` listing every unmet item, else return the report.
    ``env`` is read for NAMES/markers only (default: the process environment)."""
    environ = os.environ if env is None else env
    unmet: list[UnmetItem] = []
    passed: list[str] = []
    notes: list[str] = []
    open_items: list[str] = []
    test_used = False

    def check(code: str, ok: bool, message: str) -> None:
        if ok:
            passed.append(code)
        else:
            unmet.append(UnmetItem(code, message))

    # provider spending limits confirmed by the owner (R14 intact: evidence must be CONFIRMED)
    for prov in (p for p in config.providers if p.required):
        problem, used = _limit_problem(config, prov.name, confirmations, evidence)
        test_used = test_used or used
        check(f"PROVIDER_LIMIT:{prov.name}", problem is None, problem or "")
    if test_used:
        notes.append("TEST confirmation fixture used (dry run): not an owner confirmation")

    # budgets present and within the owner caps (HARD STOP on breach is part of the config)
    caps_ok = (
        0 < config.per_video_cap_micros <= config.owner_per_video_cap_micros
        and 0 < config.total_cap_micros <= config.owner_total_cap_micros
        and config.per_video_cap_micros <= config.total_cap_micros
        and config.hard_stop_on_breach
    )
    check("BUDGETS", caps_ok, "budgets missing, above the owner caps, or no hard stop")

    # secrets: names only, real-run mode only
    secrets_checked = config.mode is RunMode.REAL_RUN
    if secrets_checked:
        missing = [n for n in config.required_secret_names if not environ.get(n)]
        check("SECRETS", not missing, "missing secret names: " + ", ".join(missing))
    else:
        notes.append("dry-run mode: secret check skipped")

    # calendar config present and valid for the render date
    cal = calendar
    start = render_start or now_utc()
    try:
        cal = cal or MarketCalendar(config.data_dir / "calendar")
        cal_ok = cal.covers(start.astimezone(cal.tz).year)
        cal_msg = "market calendar missing, invalid or not VERIFIED for the render year"
    except Exception:  # any failure here means: calendar not usable
        cal, cal_ok = None, False
        cal_msg = "market calendar config missing or invalid"
    check("CALENDAR", cal_ok, cal_msg)

    # lag config (30 days, calendar days)
    check(
        "LAG",
        config.price_data_lag_days == 30 and config.price_data_lag_unit == SUPPORTED_LAG_UNIT,
        "price-data lag config is not 30 CALENDAR_DAYS (IN-02)",
    )

    # disclaimer template present; DRAFT status flagged, never hidden
    disc: Disclaimer | None = None
    try:
        disc = get_disclaimer(config.disclaimer_version)
    except DisclaimerError as exc:
        check("DISCLAIMER", False, str(exc))
    else:
        passed.append("DISCLAIMER")
        if disc.is_draft:
            notes.append(f"disclaimer {disc.version} status: {disc.status}")

    # FIN-R10: valid only if the owner is not SEBI-registered; an owner item, never assumed
    if not any(
        c.kind is ConfirmationKind.FIN_R10_NOT_SEBI_REGISTERED and c.verified and not c.test_fixture
        for c in confirmations
    ):
        open_items.append("FIN-R10: owner confirmation that the owner is not SEBI-registered")

    # development environment only
    env_value = environ.get(config.environment_variable)
    markers = [m for m in config.vps_markers if _truthy(environ.get(m))]
    check(
        "ENVIRONMENT",
        env_value == config.required_environment and not markers,
        "render must run in the development environment (a VPS marker is set or "
        f"{config.environment_variable} is not {config.required_environment})",
    )

    # no market-hours conflict for the render start
    if cal is not None and cal_ok:
        decision = cal.check_render(start)
        check("MARKET_HOURS", decision.allowed, decision.reason)
    else:
        check("MARKET_HOURS", False, "cannot check market hours without a valid calendar")

    if unmet:
        raise PreflightRefused(tuple(unmet))
    return PreflightReport(
        mode=config.mode,
        checks_passed=tuple(passed),
        secrets_checked=secrets_checked,
        test_confirmation_used=test_used,
        disclaimer_status=disc.status if disc else "",
        open_owner_items=tuple(open_items),
        notes=tuple(notes),
    )
