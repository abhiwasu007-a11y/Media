"""Provider registry (fake vs real by runtime mode, real only after a passed preflight) and the
live smoke script, both against the real amw_runtime API with mock transports (no network, no
key, no paid call)."""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from scripts.provider_smoke import run_smoke

from amw_adapters.llm import FakeLlmAdapter
from amw_adapters.llm.anthropic import AnthropicLlmAdapter
from amw_adapters.registry import build_providers
from amw_adapters.tts import FakeTtsAdapter
from amw_adapters.tts.elevenlabs import ElevenLabsTtsAdapter
from amw_core.errors import ConfigInvalidError
from amw_runtime.config import load_runtime_config
from amw_runtime.confirmations import ConfirmationKind, ConfirmationRecord
from amw_runtime.preflight import PreflightReport, run_preflight
from tests.adapters.mock_providers import (
    TEST_ENV,
    TEST_KEY_VALUE,
    MockAnthropic,
    MockElevenLabs,
    Scripted,
)

pytestmark = pytest.mark.integration
IST = timezone(timedelta(hours=5, minutes=30))
EVENING = datetime(2026, 11, 19, 20, 0, tzinfo=IST)  # a Thursday, after the guard window
REAL_ENV = {"AMW_RUNTIME_MODE": "REAL_RUN", "AMW_ENVIRONMENT": "development", **TEST_ENV}


class Row:
    evidence_state = "CONFIRMED"
    recorded_from = "OWNER_CHAT_OPERATOR"


class Lookup:
    def get(self, evidence_id: str) -> Row:
        return Row()


def limits() -> list[ConfirmationRecord]:
    return [
        ConfirmationRecord(
            kind=ConfirmationKind.PROVIDER_LIMIT, provider=p, amount_minor=500, currency="USD",
            recorded_from="OWNER_CHAT_OPERATOR", evidence_id=f"ev-{p}", verified=True,
        )
        for p in ("anthropic", "elevenlabs")
    ]  # fmt: skip


def passed_report() -> PreflightReport:
    return run_preflight(
        load_runtime_config(REAL_ENV), limits(), env=REAL_ENV, evidence=Lookup(),
        render_start=EVENING,
    )  # fmt: skip


def test_dry_run_gives_fakes_and_reads_no_key() -> None:
    cfg = load_runtime_config({"AMW_RUNTIME_MODE": "DRY_RUN"})
    out = build_providers(cfg, preflight=None, env={})
    assert not out.real
    assert isinstance(out.llm, FakeLlmAdapter)
    assert isinstance(out.tts, FakeTtsAdapter)


def test_real_run_refused_without_a_passed_real_preflight() -> None:
    cfg = load_runtime_config(REAL_ENV)
    with pytest.raises(ConfigInvalidError):
        build_providers(cfg, preflight=None, env=REAL_ENV)
    dry_cfg = load_runtime_config({**REAL_ENV, "AMW_RUNTIME_MODE": "DRY_RUN"})
    dry_fixture = ConfirmationRecord(
        kind=ConfirmationKind.PROVIDER_LIMIT, provider="x", amount_minor=1, currency="USD",
        recorded_from="OWNER_CHAT_OPERATOR", verified=True, test_fixture=True,
    )  # fmt: skip
    dry_report = run_preflight(
        dry_cfg,
        [dry_fixture.model_copy(update={"provider": p}) for p in ("anthropic", "elevenlabs")],
        env=REAL_ENV,
        render_start=EVENING,
    )
    with pytest.raises(ConfigInvalidError):
        build_providers(cfg, preflight=dry_report, env=REAL_ENV)


def test_real_run_with_passed_preflight_gives_real_adapters() -> None:
    cfg = load_runtime_config(REAL_ENV)
    out = build_providers(cfg, preflight=passed_report(), env=REAL_ENV)
    assert out.real
    assert isinstance(out.llm, AnthropicLlmAdapter)
    assert isinstance(out.tts, ElevenLabsTtsAdapter)
    with pytest.raises(ConfigInvalidError) as info:
        build_providers(cfg, preflight=passed_report(), env={})
    assert info.value.details["names"] == [
        "AMW_SECRET_ANTHROPIC_API_KEY",
        "AMW_SECRET_ELEVENLABS_API_KEY",
    ]


def test_registry_refuses_unknown_real_provider() -> None:
    cfg = load_runtime_config(REAL_ENV)
    other = cfg.model_copy(
        update={"providers": tuple(
            p.model_copy(update={"name": "other_llm"}) if p.role == "LLM" else p
            for p in cfg.providers
        )}
    )  # fmt: skip
    with pytest.raises(ConfigInvalidError):
        build_providers(other, preflight=passed_report(), env=REAL_ENV)


def _smoke(env: dict[str, str], **kw: Any) -> tuple[int, list[str], MockAnthropic, MockElevenLabs]:
    llm, tts = MockAnthropic(), MockElevenLabs()
    lines: list[str] = []
    args: dict[str, Any] = {
        "confirmations": limits(),
        "evidence": Lookup(),
        "llm_model": "claude-haiku-5-5",
        "tts_model": "eleven_v4",
        "voice_id": "mrVoice1",
        "transports": {"anthropic": llm.transport(), "elevenlabs": tts.transport()},
        "render_start": EVENING,
        "out": lines.append,
    }
    code = run_smoke(env, **{**args, **kw})
    return code, lines, llm, tts


CAP = {"AMW_EVALS__LIVE_SMOKE_MAX_COST_MICROS": "20000"}


@pytest.mark.security
def test_smoke_one_call_per_provider_and_no_secret_printed() -> None:
    code, lines, llm, tts = _smoke({**REAL_ENV, **CAP})
    assert code == 0, lines
    assert llm.billable == 1
    assert tts.billable == 1
    assert [r.url.path for r in llm.requests] == ["/v1/messages/count_tokens", "/v1/messages"]
    text = "\n".join(lines)
    assert "anthropic: OK" in text
    assert "elevenlabs: OK" in text
    assert TEST_KEY_VALUE not in text


@pytest.mark.parametrize(
    ("env", "code"),
    [
        ({**REAL_ENV, "AMW_RUNTIME_MODE": "DRY_RUN", **CAP}, 2),
        (REAL_ENV, 2),  # no owner cap
        ({**REAL_ENV, "AMW_EVALS__LIVE_SMOKE_MAX_COST_MICROS": "0"}, 2),
        ({**REAL_ENV, "AMW_EVALS__LIVE_SMOKE_MAX_COST_MICROS": "999999999"}, 2),  # above per-video
        ({**REAL_ENV, "AMW_EVALS__LIVE_SMOKE_MAX_COST_MICROS": "10"}, 2),  # worst case above cap
        ({"AMW_RUNTIME_MODE": "BOGUS"}, 2),
    ],
)
def test_smoke_refusals_make_no_paid_call(env: dict[str, str], code: int) -> None:
    got, lines, llm, tts = _smoke(env)
    assert got == code, lines
    assert llm.billable == 0
    assert tts.billable == 0


def test_smoke_preflight_refusal_and_unknown_models() -> None:
    got, lines, llm, _ = _smoke({**REAL_ENV, **CAP}, evidence=None)
    assert got == 3
    assert any("PROVIDER_LIMIT:anthropic" in line for line in lines)
    assert llm.requests == []
    got, _, llm, _ = _smoke({**REAL_ENV, **CAP}, tts_model="eleven_multilingual_v2")
    assert got == 2
    assert llm.requests == []


def test_smoke_reports_a_failed_call() -> None:
    llm, tts = MockAnthropic(), MockElevenLabs()
    tts.script.append(Scripted(401, {"detail": {"type": "authentication_error"}}))
    llm.script.append(Scripted(200, {"input_tokens": 9}))
    llm.script.append(Scripted(500, {"error": {"type": "api_error"}}))
    lines: list[str] = []
    code = run_smoke(
        {**REAL_ENV, **CAP}, confirmations=limits(), evidence=Lookup(),
        llm_model="claude-haiku-5-5", tts_model="eleven_v4", voice_id="mrVoice1",
        transports={"anthropic": llm.transport(), "elevenlabs": tts.transport()},
        render_start=EVENING, out=lines.append,
    )  # fmt: skip
    assert code == 4
    assert "anthropic: FAILED TEMPORARY.UPSTREAM_5XX upstream_status=500" in lines
    assert "elevenlabs: FAILED PERMANENT.AUTH_INVALID upstream_status=401" in lines
    llm2 = MockAnthropic()
    llm2.script.append(Scripted(401, {"error": {"type": "authentication_error"}}))
    code = run_smoke(
        {**REAL_ENV, **CAP}, confirmations=limits(), evidence=Lookup(),
        llm_model="claude-haiku-5-5", tts_model="eleven_v4", voice_id="mrVoice1",
        transports={"anthropic": llm2.transport(), "elevenlabs": MockElevenLabs().transport()},
        render_start=EVENING, out=lines.append,
    )  # fmt: skip
    assert code == 4
