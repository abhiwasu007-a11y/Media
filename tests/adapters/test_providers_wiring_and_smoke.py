"""Provider registry (fake vs real by runtime mode, real only after a passed preflight) and the
live smoke script, both against the real amw_runtime API with mock transports (no network, no
key, no paid call)."""

import copy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from scripts.provider_smoke import run_smoke

from amw_adapters.llm import FakeLlmAdapter
from amw_adapters.llm.anthropic import AnthropicLlmAdapter
from amw_adapters.real.authorisation import ProviderAuthorisation, verify_authorisation
from amw_adapters.real.guard import CapOnlyCallGuard
from amw_adapters.tts import FakeTtsAdapter
from amw_adapters.tts.elevenlabs import ElevenLabsTtsAdapter
from amw_core.errors import ConfigInvalidError
from amw_runtime.config import RunMode, load_runtime_config
from amw_runtime.confirmations import ConfirmationKind, ConfirmationRecord
from amw_runtime.preflight import PreflightReport, run_preflight
from amw_runtime.providers import build_providers
from tests.adapters.mock_providers import (
    TEST_KEY_VALUE,
    MockAnthropic,
    MockElevenLabs,
    Scripted,
)
from tests.adapters.preflight_support import (
    EVENING,
    ORG_ID,
    REAL_ENV,
    Lookup,
    limits,
    passed_report,
)

pytestmark = pytest.mark.integration


def test_dry_run_gives_fakes_and_reads_no_key() -> None:
    cfg = load_runtime_config({"AMW_RUNTIME_MODE": "DRY_RUN"})
    out = build_providers(cfg, preflight=None, env={})
    assert not out.real
    assert isinstance(out.llm, FakeLlmAdapter)
    assert isinstance(out.tts, FakeTtsAdapter)


def test_real_run_refused_without_a_passed_real_preflight() -> None:
    cfg = load_runtime_config(REAL_ENV)
    with pytest.raises(ConfigInvalidError):
        build_providers(cfg, preflight=None, env=REAL_ENV, guard_for=CapOnlyCallGuard)
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
    assert dry_report.provider_authorisations == ()
    with pytest.raises(ConfigInvalidError):
        build_providers(cfg, preflight=dry_report, env=REAL_ENV, guard_for=CapOnlyCallGuard)


class LookalikeReport:
    """Duck-typed stand-in with every field the old structural check read."""

    mode = RunMode.REAL_RUN
    secrets_checked = True
    test_confirmation_used = False
    checks_passed = ("PROVIDER_LIMIT:anthropic", "PROVIDER_LIMIT:elevenlabs")
    provider_authorisations = ()


@pytest.mark.security
def test_duck_typed_or_hand_built_reports_cannot_open_the_gate() -> None:
    cfg = load_runtime_config(REAL_ENV)
    with pytest.raises(ConfigInvalidError):  # not the real report type
        build_providers(
            cfg,
            preflight=LookalikeReport(),  # type: ignore[arg-type]
            env=REAL_ENV,
            guard_for=CapOnlyCallGuard,
        )
    hand_built = PreflightReport(
        mode=RunMode.REAL_RUN,
        checks_passed=LookalikeReport.checks_passed,
        secrets_checked=True,
        test_confirmation_used=False,
        disclaimer_status="",
        open_owner_items=(),
    )
    with pytest.raises(ConfigInvalidError, match="provider spending limit"):
        build_providers(cfg, preflight=hand_built, env=REAL_ENV, guard_for=CapOnlyCallGuard)
    with pytest.raises(ConfigInvalidError):  # an unsealed hand-built token cannot be forged
        verify_authorisation(
            ProviderAuthorisation(
                provider="anthropic", org_id=ORG_ID, job_id=None, per_video_cap_micros=5_000_000,
                total_cap_micros=50_000_000, currency="USD", issued_at=1, expires_at=2**40,
                nonce="n", seal=b"\0" * 32,
            ),
            datetime(2026, 1, 1, tzinfo=UTC), provider="anthropic", currency="USD",
        )  # fmt: skip
    with pytest.raises(TypeError):
        copy.copy(passed_report().provider_authorisations[0])


@pytest.mark.security
def test_no_public_mint_function_exists_in_the_source_tree() -> None:
    """The old design had a public mint function whose only caller was scanned for; tokens are
    now sealed with a key held only by amw_runtime.preflight, so no mint function may exist."""
    src = Path(__file__).resolve().parents[2] / "packages"
    names = [
        str(p.relative_to(src))
        for p in src.rglob("*.py")
        if "mint_provider_authorisation" in p.read_text(encoding="utf-8")
    ]
    assert names == []


def test_real_run_with_passed_preflight_gives_real_adapters() -> None:
    cfg = load_runtime_config(REAL_ENV)
    report = passed_report()
    assert {a.provider for a in report.provider_authorisations} == {"anthropic", "elevenlabs"}
    assert all(a.per_video_cap_micros == 5_000_000 for a in report.provider_authorisations)
    out = build_providers(cfg, preflight=report, env=REAL_ENV, guard_for=CapOnlyCallGuard)
    assert out.real
    assert isinstance(out.llm, AnthropicLlmAdapter)
    assert isinstance(out.tts, ElevenLabsTtsAdapter)
    with pytest.raises(ConfigInvalidError, match="call guard"):
        build_providers(cfg, preflight=report, env=REAL_ENV)
    with pytest.raises(ConfigInvalidError) as info:
        build_providers(cfg, preflight=report, env={}, guard_for=CapOnlyCallGuard)
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
        build_providers(other, preflight=passed_report(), env=REAL_ENV, guard_for=CapOnlyCallGuard)


def _smoke(env: dict[str, str], **kw: Any) -> tuple[int, list[str], MockAnthropic, MockElevenLabs]:
    llm, tts = MockAnthropic(), MockElevenLabs()
    lines: list[str] = []
    args: dict[str, Any] = {
        "confirmations": limits(),
        "evidence": Lookup(limits()),
        "org_id": ORG_ID,
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
    got, lines, llm, _ = _smoke({**REAL_ENV, **CAP}, evidence=None, org_id=ORG_ID)
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
        {**REAL_ENV, **CAP}, confirmations=limits(), evidence=Lookup(limits()), org_id=ORG_ID,
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
        {**REAL_ENV, **CAP}, confirmations=limits(), evidence=Lookup(limits()), org_id=ORG_ID,
        llm_model="claude-haiku-5-5", tts_model="eleven_v4", voice_id="mrVoice1",
        transports={"anthropic": llm2.transport(), "elevenlabs": MockElevenLabs().transport()},
        render_start=EVENING, out=lines.append,
    )  # fmt: skip
    assert code == 4
