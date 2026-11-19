"""amw_runtime: config, preflight, calendar, chart-data policy, disclaimer (no network, no keys)."""

import hashlib
import json
import logging
import shutil
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from amw_core.errors import ConfigInvalidError
from amw_runtime.calendar import MarketCalendar
from amw_runtime.chartdata import ChartDataPolicy, assert_bars_older_than_lag
from amw_runtime.config import DEFAULT_CONFIG_FILE, RuntimeConfig, load_runtime_config
from amw_runtime.confirmations import ConfirmationKind, ConfirmationRecord
from amw_runtime.data_files import DATA_DIR
from amw_runtime.disclaimer import DRAFT_STATUS, get_disclaimer
from amw_runtime.errors import (
    BarsTooRecentError,
    CalendarUnavailableError,
    ChartSourceRefusedError,
    DisclaimerError,
    PreflightRefused,
)
from amw_runtime.preflight import run_preflight

pytestmark = pytest.mark.unit
IST = timezone(timedelta(hours=5, minutes=30))
CANARY = "canary-secret-value-0123456789"
SECRETS = {"AMW_SECRET_ANTHROPIC_API_KEY": CANARY, "AMW_SECRET_ELEVENLABS_API_KEY": CANARY}
DEV = {"AMW_ENVIRONMENT": "development"}
EVENING = datetime(2026, 11, 19, 20, 0, tzinfo=IST)  # Thursday, after the guard window


def cfg(mode: str = "DRY_RUN", **extra: str) -> RuntimeConfig:
    return load_runtime_config({"AMW_RUNTIME_MODE": mode, **extra})


def limit(provider: str, **kw: object) -> ConfirmationRecord:
    base: dict[str, object] = {
        "kind": ConfirmationKind.PROVIDER_LIMIT,
        "provider": provider,
        "amount_minor": 1000,
        "currency": "USD",
        "recorded_from": "OWNER_CHAT_OPERATOR",
        "evidence_id": f"ev-{provider}",
        "verified": True,
    }
    return ConfirmationRecord(**{**base, **kw})


class Row:
    def __init__(self, state: str = "CONFIRMED", src: str = "OWNER_CHAT_OPERATOR") -> None:
        self.evidence_state, self.recorded_from = state, src


class Lookup:
    def __init__(self, row: Row | None) -> None:
        self.row = row

    def get(self, evidence_id: str) -> Row | None:
        return self.row


def real_limits() -> list[ConfirmationRecord]:
    return [limit("anthropic"), limit("elevenlabs")]


# ---------------------------------------------------------------- config
def test_config_caps_in_micros_and_owner_values() -> None:
    c = cfg()
    assert (c.per_video_cap_micros, c.total_cap_micros) == (5_000_000, 50_000_000)
    assert c.hard_stop_on_breach
    assert c.price_data_lag_days == 30
    assert c.required_secret_names == (
        "AMW_SECRET_ANTHROPIC_API_KEY",
        "AMW_SECRET_ELEVENLABS_API_KEY",
    )
    assert c.owner_decisions.music_in_first_sample is False
    assert c.owner_decisions.upload is False


@pytest.mark.parametrize("env", [{}, {"AMW_RUNTIME_MODE": "real"}, {"AMW_RUNTIME_MODE": ""}])
def test_config_mode_fail_closed(env: dict[str, str]) -> None:
    with pytest.raises(ConfigInvalidError):
        load_runtime_config(env)


def test_env_can_only_lower_caps() -> None:
    assert cfg(AMW_RUNTIME_PER_VIDEO_CAP_MINOR="300").per_video_cap_micros == 3_000_000
    for bad in ("501", "0", "abc", "-1"):
        with pytest.raises(ConfigInvalidError):
            cfg(AMW_RUNTIME_PER_VIDEO_CAP_MINOR=bad)
    with pytest.raises(ConfigInvalidError):
        cfg(AMW_RUNTIME_TOTAL_CAP_MINOR="5001")


def _variant(tmp_path: Path, edit: object) -> dict[str, str]:
    data = json.loads(DEFAULT_CONFIG_FILE.read_text(encoding="utf-8"))
    edit(data)  # type: ignore[operator]
    path = tmp_path / "rc.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return {"AMW_RUNTIME_MODE": "DRY_RUN", "AMW_RUNTIME_CONFIG_PATH": str(path)}


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d["finance"]["currency_minor_exponent"].clear(),  # no exponent: no code default
        lambda d: d["budget"].update(hard_stop_on_breach=False),
        lambda d: d["providers"][0].update(secret_name="ANTHROPIC_KEY"),  # noqa: S106
        lambda d: d["providers"][0].update(secret_name=None),
        lambda d: d.pop("price_data_lag"),
        lambda d: d["budget"].update(currency="EUR"),
        lambda d: d.pop("providers"),
    ],
)
def test_config_data_invalid_fails_closed(tmp_path: Path, edit: object) -> None:
    with pytest.raises(ConfigInvalidError):
        load_runtime_config(_variant(tmp_path, edit))


def test_config_unreadable_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigInvalidError):
        load_runtime_config(
            {"AMW_RUNTIME_MODE": "DRY_RUN", "AMW_RUNTIME_CONFIG_PATH": str(tmp_path / "none.json")}
        )


# ---------------------------------------------------------------- preflight
def test_dry_run_passes_with_test_fixture_and_says_so() -> None:
    recs = [limit(p, test_fixture=True, evidence_id=None) for p in ("anthropic", "elevenlabs")]
    rep = run_preflight(cfg(), recs, env=DEV, calendar=MarketCalendar(), render_start=EVENING)
    assert rep.test_confirmation_used
    assert not rep.secrets_checked
    assert any("secret check skipped" in n for n in rep.notes)
    assert any("TEST confirmation" in n for n in rep.notes)
    assert DRAFT_STATUS in rep.disclaimer_status
    assert any("not SEBI-registered" in i for i in rep.open_owner_items)


def test_real_run_passes_with_verified_evidence() -> None:
    rep = run_preflight(
        cfg("REAL_RUN"),
        real_limits(),
        env={**DEV, **SECRETS},
        evidence=Lookup(Row()),
        render_start=EVENING,
    )
    assert rep.secrets_checked
    assert not rep.test_confirmation_used


def test_fin_r10_confirmation_clears_open_item() -> None:
    rec = ConfirmationRecord(
        kind=ConfirmationKind.FIN_R10_NOT_SEBI_REGISTERED,
        recorded_from="OWNER_CHAT_OPERATOR",
        evidence_id="e1",
        verified=True,
    )
    rep = run_preflight(
        cfg("REAL_RUN"),
        [*real_limits(), rec],
        env={**DEV, **SECRETS},
        evidence=Lookup(Row()),
        render_start=EVENING,
    )
    assert rep.open_owner_items == ()


def codes(exc: pytest.ExceptionInfo[PreflightRefused]) -> set[str]:
    return {i.code for i in exc.value.items}


def test_real_run_refuses_listing_every_unmet_item() -> None:
    with pytest.raises(PreflightRefused) as exc:
        run_preflight(
            cfg("REAL_RUN"),
            [],
            env={"AMW_VPS": "1"},
            render_start=datetime(2026, 11, 19, 10, 0, tzinfo=IST),
        )
    assert codes(exc) == {
        "PROVIDER_LIMIT:anthropic",
        "PROVIDER_LIMIT:elevenlabs",
        "SECRETS",
        "ENVIRONMENT",
        "MARKET_HOURS",
    }


@pytest.mark.parametrize(
    "kw",
    [
        {"verified": False},
        {"test_fixture": True},
        {"evidence_id": None, "review_code": None},
        {"amount_minor": 0},
        {"currency": "EUR"},
    ],
)
def test_real_run_refuses_weak_limit_confirmations(kw: dict[str, object]) -> None:
    recs = [limit("anthropic", **kw), limit("elevenlabs")]
    with pytest.raises(PreflightRefused) as exc:
        run_preflight(
            cfg("REAL_RUN"),
            recs,
            env={**DEV, **SECRETS},
            evidence=Lookup(Row()),
            render_start=EVENING,
        )
    assert codes(exc) == {"PROVIDER_LIMIT:anthropic"}


@pytest.mark.parametrize("row", [None, Row("VERIFIED"), Row("CONFIRMED", "WEB_DASHBOARD")])
def test_real_run_needs_confirmed_owner_channel_evidence(row: Row | None) -> None:
    with pytest.raises(PreflightRefused) as exc:
        run_preflight(
            cfg("REAL_RUN"),
            real_limits(),
            env={**DEV, **SECRETS},
            evidence=Lookup(row),
            render_start=EVENING,
        )
    assert len(exc.value.items) == 2


def test_real_run_without_lookup_is_refused() -> None:
    with pytest.raises(PreflightRefused):
        run_preflight(cfg("REAL_RUN"), real_limits(), env={**DEV, **SECRETS}, render_start=EVENING)


def test_dry_run_still_refuses_unverified_fixture_and_missing_env() -> None:
    recs = [limit(p, test_fixture=True, verified=False) for p in ("anthropic", "elevenlabs")]
    with pytest.raises(PreflightRefused) as exc:
        run_preflight(cfg(), recs, env={}, render_start=EVENING)
    assert {"ENVIRONMENT", "PROVIDER_LIMIT:anthropic"} <= codes(exc)


def test_environment_must_be_development() -> None:
    recs = [limit(p, test_fixture=True) for p in ("anthropic", "elevenlabs")]
    for env in ({"AMW_ENVIRONMENT": "production"}, {**DEV, "AMW_ON_VPS": "true"}):
        with pytest.raises(PreflightRefused) as exc:
            run_preflight(cfg(), recs, env=env, render_start=EVENING)
        assert codes(exc) == {"ENVIRONMENT"}
    ok = run_preflight(cfg(), recs, env={**DEV, "AMW_VPS": "0"}, render_start=EVENING)
    assert "ENVIRONMENT" in ok.checks_passed


def test_budget_and_lag_checks_refuse() -> None:
    recs = [limit(p, test_fixture=True) for p in ("anthropic", "elevenlabs")]
    bad = cfg().model_copy(update={"per_video_cap_micros": 6_000_000, "price_data_lag_days": 7})
    with pytest.raises(PreflightRefused) as exc:
        run_preflight(bad, recs, env=DEV, render_start=EVENING)
    assert codes(exc) == {"BUDGETS", "LAG"}


def test_missing_calendar_and_disclaimer_refuse(tmp_path: Path) -> None:
    recs = [limit(p, test_fixture=True) for p in ("anthropic", "elevenlabs")]
    bad = cfg().model_copy(update={"data_dir": tmp_path, "disclaimer_version": "v9"})
    with pytest.raises(PreflightRefused) as exc:
        run_preflight(bad, recs, env=DEV, render_start=EVENING)
    assert {"CALENDAR", "DISCLAIMER", "MARKET_HOURS"} <= codes(exc)


def test_2027_calendar_is_invalid_by_design_so_preflight_refuses() -> None:
    recs = [limit(p, test_fixture=True) for p in ("anthropic", "elevenlabs")]
    with pytest.raises(PreflightRefused) as exc:
        run_preflight(cfg(), recs, env=DEV, render_start=datetime(2027, 3, 3, 20, 0, tzinfo=IST))
    assert {"CALENDAR", "MARKET_HOURS"} <= codes(exc)


def test_no_value_leak_in_logs_or_errors(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    env = {**DEV, **SECRETS, "AMW_RUNTIME_MODE": "REAL_RUN"}
    c = load_runtime_config(env)
    with pytest.raises(PreflightRefused) as refused:
        run_preflight(c, [], env=env, render_start=EVENING)
    assert CANARY not in str(refused.value)
    assert CANARY not in repr(refused.value.items)
    rep = run_preflight(c, real_limits(), env=env, evidence=Lookup(Row()), render_start=EVENING)
    assert CANARY not in repr(rep)
    assert CANARY not in repr(c)
    assert CANARY not in caplog.text
    secret_env = {**env, "AMW_RUNTIME_PER_VIDEO_CAP_MINOR": CANARY}
    with pytest.raises(ConfigInvalidError) as err:
        load_runtime_config(secret_env)
    assert CANARY not in str(err.value)
    assert CANARY not in repr(err.value.details)


# ---------------------------------------------------------------- calendar
def at(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def test_session_boundaries_on_a_trading_day() -> None:
    cal = MarketCalendar()  # Thursday 2026-11-19, a trading day
    assert not cal.in_regular_session(at(2026, 11, 19, 9, 14))
    assert cal.in_regular_session(at(2026, 11, 19, 9, 15))
    assert cal.in_regular_session(at(2026, 11, 19, 15, 29))
    assert not cal.in_regular_session(at(2026, 11, 19, 15, 30))
    assert not cal.render_allowed(at(2026, 11, 19, 9, 15))
    assert not cal.render_allowed(at(2026, 11, 19, 15, 30))  # guard is stricter (until 16:00)
    assert not cal.render_allowed(at(2026, 11, 19, 9, 0))
    assert cal.render_allowed(at(2026, 11, 19, 8, 59))
    assert cal.render_allowed(at(2026, 11, 19, 16, 0))


def test_holiday_weekend_special_session() -> None:
    cal = MarketCalendar()
    assert cal.render_allowed(at(2026, 12, 25, 11, 0))  # Christmas, listed holiday
    assert cal.render_allowed(at(2026, 11, 21, 11, 0))  # Saturday
    assert cal.render_allowed(at(2026, 11, 22, 11, 0))  # Sunday
    assert not cal.render_allowed(at(2026, 11, 8, 11, 0))  # Muhurat Sunday: guard whole window
    assert cal.render_allowed(at(2026, 11, 24, 11, 0))  # Guru Nanak holiday


def test_utc_input_is_converted_to_ist_without_dst() -> None:
    cal = MarketCalendar()
    assert not cal.render_allowed(datetime(2026, 11, 19, 4, 0, tzinfo=UTC))  # 09:30 IST
    assert cal.render_allowed(datetime(2026, 11, 19, 3, 29, tzinfo=UTC))  # 08:59 IST
    assert not cal.render_allowed(datetime(2026, 7, 15, 4, 0, tzinfo=UTC))  # no DST shift


def test_calendar_fails_closed() -> None:
    cal = MarketCalendar()
    assert not cal.render_allowed(at(2027, 3, 3, 20, 0))  # invalid-by-design 2027 file
    assert not cal.render_allowed(at(2030, 1, 4, 20, 0))  # no file at all
    assert not cal.covers(2027)
    assert cal.covers(2026)
    with pytest.raises(CalendarUnavailableError):
        cal.is_trading_day(date(2027, 1, 4))
    with pytest.raises(CalendarUnavailableError):
        cal.render_allowed(datetime(2026, 11, 19, 20, 0))  # naive datetime


def test_calendar_bad_files(tmp_path: Path) -> None:
    src = DATA_DIR / "calendar"
    with pytest.raises(CalendarUnavailableError):
        MarketCalendar(tmp_path)  # no session file
    shutil.copy(src / "nse_session.json", tmp_path)
    cal = MarketCalendar(tmp_path)
    cases = {
        2026: {"year": 2026, "status": "VERIFIED", "holidays": []},
        2025: {"year": 2025, "status": "VERIFIED", "holidays": [{"date": "2024-01-01"}]},
        2024: {"year": 2024, "status": "VERIFIED", "holidays": [{"date": "nope"}]},
        2023: {"year": 2022, "status": "VERIFIED", "holidays": [{"date": "2023-01-26"}]},
    }
    for year, body in cases.items():
        (tmp_path / f"nse_holidays_{year}.json").write_text(json.dumps(body), encoding="utf-8")
        assert not cal.covers(year)
    (tmp_path / "nse_holidays_2022.json").write_text("not json", encoding="utf-8")
    assert not cal.covers(2022)


def test_inconsistent_session_config(tmp_path: Path) -> None:
    sess = json.loads((DATA_DIR / "calendar" / "nse_session.json").read_text(encoding="utf-8"))
    sess["regular_close"] = "09:00"
    (tmp_path / "nse_session.json").write_text(json.dumps(sess), encoding="utf-8")
    with pytest.raises(CalendarUnavailableError):
        MarketCalendar(tmp_path)


def test_session_values_match_research_log() -> None:
    log = (Path(__file__).parents[2] / "docs/v4/RESEARCH_LOG.md").read_text(encoding="utf-8")
    cal = MarketCalendar()
    assert "NSE-01" in log
    assert "NSE-02" in log
    assert "NSE-03" in log
    assert (cal.regular_open.isoformat(), cal.regular_close.isoformat()) == ("09:15:00", "15:30:00")
    assert "09:15 hrs" in log
    assert "15:30 hrs" in log


# ---------------------------------------------------------------- chart data
def test_bars_lag_boundary() -> None:
    today = date(2026, 11, 19)
    assert_bars_older_than_lag(today - timedelta(days=30), today)  # exactly 30 days: allowed
    for last in (today - timedelta(days=29), today, today + timedelta(days=1), None):
        with pytest.raises(BarsTooRecentError):
            assert_bars_older_than_lag(last, today)


def test_policy_source_and_lag() -> None:
    pol = ChartDataPolicy.from_config(cfg(AMW_CHART_DATA_PACK_LOCATION="pointer-only"))
    assert pol.location == "pointer-only"
    assert pol.lag_days == 30
    pol.require_source("course_data_pack")
    for other in ("web", "exchange_feed", ""):
        with pytest.raises(ChartSourceRefusedError):
            pol.require_source(other)
    with pytest.raises(BarsTooRecentError):
        pol.assert_bars_older_than_lag(date(2026, 11, 1), date(2026, 11, 19))
    assert ChartDataPolicy.from_config(cfg()).location is None


# ---------------------------------------------------------------- disclaimer
def test_disclaimer_v1_draft_hash_and_text() -> None:
    d = get_disclaimer("v1")
    assert d.version == "v1"
    assert d.status == "DRAFT – not lawyer-approved"  # noqa: RUF001
    assert d.is_draft
    assert d.sha256 == hashlib.sha256(d.text.encode("utf-8")).hexdigest()
    assert d.text.startswith("हा व्हिडिओ केवळ शैक्षणिक उद्देशाने आहे.")
    assert d.text.endswith("सल्ल्याने घ्या.")
    assert "SEBI-नोंदणीकृत" in d.text


@pytest.mark.parametrize("version", ["v2", "1", "../x", ""])
def test_unknown_disclaimer_version(version: str) -> None:
    with pytest.raises(DisclaimerError):
        get_disclaimer(version)


def test_tampered_disclaimer_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "disclaimer").mkdir()
    raw = json.loads((DATA_DIR / "disclaimer" / "mr_v1.json").read_text(encoding="utf-8"))
    raw["text"] += " x"
    (tmp_path / "disclaimer" / "mr_v1.json").write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr("amw_runtime.disclaimer.DATA_DIR", tmp_path)
    with pytest.raises(DisclaimerError):
        get_disclaimer("v1")
    (tmp_path / "disclaimer" / "mr_v1.json").write_text("{}", encoding="utf-8")
    with pytest.raises(DisclaimerError):
        get_disclaimer("v1")
