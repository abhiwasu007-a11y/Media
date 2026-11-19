"""Preflight (interface 2): refuses a run unless every requirement holds; lists every unmet item.

Dry-run mode skips the secret check (and says so) and may use a TEST confirmation fixture (the
report says so). Real-run mode needs verified, evidence-backed owner confirmations.
"""

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from pydantic import ValidationError

from amw_core.errors import ConfigInvalidError
from amw_runtime.calendar import MarketCalendar, now_utc
from amw_runtime.config import ENV_MODE, RunMode, RuntimeConfig, load_runtime_config
from amw_runtime.confirmations import (
    SOURCE_REAL,
    SOURCE_TEST_FIXTURE,
    SUBJECT_KIND,
    ConfirmationKind,
    ConfirmationRecord,
    EvidenceLookup,
)
from amw_runtime.disclaimer import Disclaimer, get_disclaimer
from amw_runtime.errors import DisclaimerError, PreflightRefused, UnmetItem

SUPPORTED_LAG_UNIT = "CALENDAR_DAYS"
# fields a caller may legitimately vary in a real run (all other fields must equal the data)
_CALLER_VARIABLE_FIELDS = (
    "per_video_cap_micros",
    "total_cap_micros",
    "chart_data_location",
    "override_applied",
)
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


_MISSING = object()


def _attrs(row: object, *names: str) -> dict[str, object] | None:
    out = {n: getattr(row, n, _MISSING) for n in names}
    return None if any(v is _MISSING for v in out.values()) else out


def _evidence_problem(
    rec: ConfirmationRecord,
    evidence: EvidenceLookup | None,
    org_id: str | None,
    used_ids: set[str],
    *,
    real_run: bool = True,
) -> str | None:
    """A record counts only if its evidence row is CONFIRMED, from the owner chat, MAC-valid,
    bound to this org, kind and subject, REAL (a TEST_FIXTURE row only in a dry run), and not
    already used for another record. Missing row attributes are a typed refusal."""
    if not rec.verified:
        return "confirmation not verified"
    if not (rec.evidence_id or rec.review_code):
        return "no evidence id or review code"
    if evidence is None or rec.evidence_id is None:
        return "owner-evidence lookup needed to verify the record"
    if org_id is None or rec.org_id != org_id:
        return "record is not bound to this run's org"
    if rec.evidence_id in used_ids:
        return "the same evidence row cannot confirm two items"
    row = evidence.get(rec.evidence_id)
    if row is None:
        return "evidence row not found"
    a = _attrs(
        row,
        "evidence_id",
        "evidence_state",
        "recorded_from",
        "org_id",
        "kind",
        "subject_kind",
        "subject_id",
        "source_kind",
        "mac_valid",
    )
    if a is None:
        return "evidence row lacks required attributes (shared evidence contract)"
    if a["mac_valid"] is not True:
        return "evidence row MAC is not valid"
    if a["evidence_state"] != CONFIRMED or a["recorded_from"] != OWNER_CHANNEL:
        return "evidence row is not CONFIRMED from the owner chat channel"
    if a["source_kind"] == SOURCE_TEST_FIXTURE:
        if real_run:
            return "TEST_FIXTURE evidence refused in real-run mode"
    elif a["source_kind"] != SOURCE_REAL:
        return "evidence row source is neither REAL nor TEST_FIXTURE"
    if (
        a["evidence_id"] != rec.evidence_id
        or a["org_id"] != org_id
        or a["kind"] != rec.kind.value
        or a["subject_kind"] != SUBJECT_KIND
        or a["subject_id"] != rec.subject()
    ):
        return "evidence row is not bound to this org, kind and subject"
    used_ids.add(rec.evidence_id)
    return None


def _limit_problem(
    config: RuntimeConfig,
    provider: str,
    records: Sequence[ConfirmationRecord],
    evidence: EvidenceLookup | None,
    org_id: str | None,
    used_ids: set[str],
) -> tuple[str | None, bool]:
    """(problem or None, used_test_fixture) for one provider's spending-limit confirmation."""
    mine = [
        r for r in records if r.kind is ConfirmationKind.PROVIDER_LIMIT and r.provider == provider
    ]
    if not mine:
        return "no owner confirmation of the provider spending limit", False
    reasons: list[str] = []
    for rec in mine:
        exp = config.currency_minor_exponent.get(rec.currency or "")
        if rec.currency != config.currency or exp is None or (rec.amount_minor or 0) <= 0:
            reasons.append("limit currency must be the budget currency and the amount positive")
        elif (rec.amount_minor or 0) * 10 ** (6 - exp) > config.owner_total_cap_micros:
            reasons.append("provider limit is above the pilot cap")
        elif rec.test_fixture:
            if config.mode is RunMode.REAL_RUN:
                reasons.append("TEST confirmation fixture refused in real-run mode")
            elif not rec.verified:
                reasons.append("confirmation not verified")
            else:
                return None, True
        else:
            problem = _evidence_problem(
                rec, evidence, org_id, used_ids, real_run=config.mode is RunMode.REAL_RUN
            )
            if problem is None:
                return None, False
            reasons.append(problem)
    return "; ".join(dict.fromkeys(reasons)), False


def run_preflight(
    config: RuntimeConfig,
    confirmations: Sequence[ConfirmationRecord],
    *,
    env: Mapping[str, str] | None = None,
    evidence: EvidenceLookup | None = None,
    calendar: MarketCalendar | None = None,
    render_start: datetime | None = None,
    org_id: str | None = None,
) -> PreflightReport:
    """Raise ``PreflightRefused`` listing every unmet item, else return the report.
    ``env`` is read for NAMES/markers only (default: the process environment). ``org_id`` is the
    run's org; real-run evidence must be bound to it."""
    environ = os.environ if env is None else env
    unmet: list[UnmetItem] = []
    passed: list[str] = []
    notes: list[str] = []
    open_items: list[str] = []
    test_used = False
    used_ids: set[str] = set()

    def check(code: str, ok: bool, message: str) -> None:
        if ok:
            passed.append(code)
        else:
            unmet.append(UnmetItem(code, message))

    # N2: never trust the caller's rule objects. Re-run the config validators (model_copy and
    # model_construct bypass them); in a real run the rules must equal the packaged data.
    try:
        config = RuntimeConfig.model_validate(config.model_dump(warnings=False))
    except ValidationError:
        raise PreflightRefused(
            (UnmetItem("CONFIG", "runtime config fails re-validation at preflight time"),)
        ) from None
    ceiling_pv, ceiling_total = config.owner_per_video_cap_micros, config.owner_total_cap_micros
    if config.mode is RunMode.REAL_RUN:
        try:
            packaged = load_runtime_config({ENV_MODE: RunMode.REAL_RUN.value})
        except ConfigInvalidError:
            raise PreflightRefused(
                (UnmetItem("CONFIG", "packaged runtime config is missing or invalid"),)
            ) from None
        ceiling_pv = packaged.owner_per_video_cap_micros
        ceiling_total = packaged.owner_total_cap_micros
        mine, theirs = config.model_dump(), packaged.model_dump()
        for key in _CALLER_VARIABLE_FIELDS:
            mine.pop(key), theirs.pop(key)
        check(
            "CONFIG",
            mine == theirs,
            "real run: config differs from the packaged owner data (caps ceilings, providers, "
            "environment, calendar, lag, render window or disclaimer rules)",
        )
        check(
            "CALENDAR_SOURCE",
            calendar is None,
            "real run: a caller-supplied calendar is not accepted; the packaged one is used",
        )
        calendar = None

    # provider spending limits confirmed by the owner (R14 intact: evidence must be CONFIRMED)
    for prov in (p for p in config.providers if p.required):
        problem, used = _limit_problem(config, prov.name, confirmations, evidence, org_id, used_ids)
        test_used = test_used or used
        check(f"PROVIDER_LIMIT:{prov.name}", problem is None, problem or "")
    if test_used:
        notes.append("TEST confirmation fixture used (dry run): not an owner confirmation")

    # budgets present and within the owner caps (HARD STOP on breach is part of the config)
    caps_ok = (
        0 < config.per_video_cap_micros <= ceiling_pv
        and 0 < config.total_cap_micros <= ceiling_total
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
    start_ok = start.tzinfo is not None and start.utcoffset() is not None
    if not start_ok:
        cal_msg = "render start must be a timezone-aware datetime"
    try:
        cal = cal or MarketCalendar(config.data_dir / "calendar")
        cal_ok = start_ok and cal.covers(start.astimezone(cal.tz).year)
        if start_ok:
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
    # Real run: REFUSED unless an evidence-backed CONFIRMED owner-chat row binds to this org.
    # Dry run: stays an OPEN item. A self-asserted record never clears it.
    r10_problems: list[str] = []
    r10_ok = False
    for rec in (c for c in confirmations if c.kind is ConfirmationKind.FIN_R10_NOT_SEBI_REGISTERED):
        if rec.test_fixture:
            r10_problems.append("TEST fixture never confirms FIN-R10")
            continue
        problem = _evidence_problem(rec, evidence, org_id, used_ids, real_run=True)
        if problem is None:
            r10_ok = True
            break
        r10_problems.append(problem)
    if config.mode is RunMode.REAL_RUN:
        check(
            "FIN_R10",
            r10_ok,
            "FIN-R10 owner confirmation (not SEBI-registered) missing or not evidence-backed"
            + (": " + "; ".join(dict.fromkeys(r10_problems)) if r10_problems else ""),
        )
    elif not r10_ok:
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

    # no market-hours conflict anywhere in the planned render window [start, start + max]
    minutes = config.render_max_duration_minutes
    check(
        "RENDER_DURATION",
        minutes is not None,
        "render.max_duration_minutes is not set (REQUIRES REVIEW); the render window is unknown",
    )
    if cal is not None and cal_ok and minutes is not None:
        decision = cal.check_render_window(start, start + timedelta(minutes=minutes))
        check("MARKET_HOURS", decision.allowed, decision.reason)
    else:
        check("MARKET_HOURS", False, "cannot check market hours without a calendar and a window")

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
