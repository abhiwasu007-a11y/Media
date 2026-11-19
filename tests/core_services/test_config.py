"""amw_core.config: typed settings, 07 design defaults, secrets only from the environment."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from amw_core.config import (
    AmwSettings,
    ConfigKeyRegistry,
    LlmTaskSettings,
    load_settings,
    require_secrets,
)
from amw_core.enums import LlmModelTier, RetryPolicy
from amw_core.errors import ConfigInvalidError
from tests.docs_tables import doc_text, section, table_rows

pytestmark = pytest.mark.unit
CANARY = "canary-secret-value-0123456789"


def test_retry_defaults_match_07_section_3_3() -> None:
    cfg = load_settings(environ={})
    expected = {
        RetryPolicy.TEMPORARY: (2_000, 2, 300_000, 5),
        RetryPolicy.RATE_LIMITED: (10_000, 2, 900_000, 6),
        RetryPolicy.DB: (200, 2, 10_000, 5),
        RetryPolicy.RESOURCE: (60_000, 2, 1_800_000, 3),
        RetryPolicy.AGENT: (5_000, 2, 120_000, 3),
        RetryPolicy.AGENT_PARSE: (0, 1, 0, 2),
        RetryPolicy.INFRA: (30_000, 2, 900_000, 8),
        RetryPolicy.PUBLISH_RESUME: (15_000, 2, 600_000, 5),
    }
    for policy, (base, mult, cap, attempts) in expected.items():
        p = cfg.retry_policy(policy)
        assert (p.base_ms, p.multiplier, p.cap_ms, p.max_attempts) == (base, mult, cap, attempts)
        assert p.jitter == (Decimal("0.5") if base else Decimal(0))
    assert cfg.retry_policy(RetryPolicy.RATE_LIMITED).retry_after_max_ms == 3_600_000


def test_policy_defaults_equal_the_07_table() -> None:
    """Parse 07 section 3.3 and compare every number with the shipped defaults."""
    body = section(doc_text("07_FAILURE_MANAGEMENT.md"), r"3\.3", 3)
    rows = table_rows(body)
    cfg = load_settings(environ={})
    names = set()
    for cells in rows:
        name = cells[0].strip("` ")
        names.add(name)
        p = cfg.retry_policy(RetryPolicy(name))
        if name == "agent_parse":
            assert (p.base_ms, p.max_attempts) == (0, 2)
            continue
        nums = [int(c.replace(",", "").split()[0]) for c in (cells[1], cells[3], cells[5])]
        assert (p.base_ms, p.cap_ms, p.max_attempts) == tuple(nums), name
        assert p.multiplier == int(cells[2]), name
        assert p.jitter == Decimal(cells[4]), name
    assert names == {p.value for p in RetryPolicy}


def test_breaker_limits_and_caps_defaults() -> None:
    cfg = load_settings(environ={})
    b = cfg.breaker_default
    assert (b.window_ms, b.min_calls, b.failure_ratio, b.consecutive_failures) == (
        60_000,
        5,
        Decimal("0.5"),
        5,
    )
    assert (b.open_ms, b.open_ms_max, b.half_open_max_probes, b.half_open_successes_to_close) == (
        30_000,
        900_000,
        1,
        2,
    )
    lim = cfg.limits
    assert (lim.max_attempts_per_task, lim.max_revision_loops, lim.max_tasks_per_job) == (
        10,
        3,
        200,
    )
    assert (lim.max_child_jobs_per_job, lim.max_replays_per_item) == (10, 3)
    assert lim.max_job_active_ms == 86_400_000
    assert cfg.caps.lock_conflict_reevaluations == 5
    assert cfg.reaper.interval_ms == 15_000
    assert cfg.reaper.lease_ms == 60_000


def test_owner_values_have_no_default() -> None:
    cfg = load_settings(environ={})
    assert cfg.finance.variance_alert_ratio is None
    assert cfg.finance.devanagari_token_factor is None
    assert cfg.finance.currency_minor_exponent == {}
    assert cfg.evals.max_run_cost_micros is None
    assert cfg.evals.live_smoke_max_cost_micros is None
    assert cfg.dlq.replay_cost_review_micros is None
    assert cfg.secrets == {}
    assert cfg.database.url is None
    assert cfg.storage.root is None
    assert cfg.llm.tiers == {}
    assert cfg.llm.tasks == {}


def test_environment_overrides_nested_values() -> None:
    cfg = load_settings(
        environ={
            "AMW_LIMITS__MAX_TASKS_PER_JOB": "50",
            "AMW_RETRY__TEMPORARY__BASE_MS": "1000",
            "AMW_RETRY__TEMPORARY__MULTIPLIER": "3",
            "AMW_RETRY__TEMPORARY__CAP_MS": "9000",
            "AMW_RETRY__TEMPORARY__JITTER": "0.25",
            "AMW_RETRY__TEMPORARY__MAX_ATTEMPTS": "4",
            "AMW_FINANCE__CURRENCY_MINOR_EXPONENT": '{"INR": 2}',
            "UNRELATED": "x",
        }
    )
    assert cfg.limits.max_tasks_per_job == 50
    assert cfg.retry_policy(RetryPolicy.TEMPORARY).multiplier == 3
    assert cfg.retry_policy(RetryPolicy.DB).base_ms == 200  # untouched policies keep defaults
    assert cfg.finance.currency_minor_exponent == {"INR": 2}


def test_config_file_then_environment(tmp_path: Path) -> None:
    file = tmp_path / "amw.toml"
    file.write_text(
        "[limits]\nmax_tasks_per_job = 40\nmax_revision_loops = 2\n"
        '[llm.tiers.MID]\nprovider = "llm_provider"\nmodel = "model-from-config"\n'
        '[llm.tasks."agent_05.script_draft"]\nmodel_tier = "MID"\ncost_budget_micros = 100\n',
        encoding="utf-8",
    )
    cfg = load_settings(config_file=file, environ={"AMW_LIMITS__MAX_TASKS_PER_JOB": "30"})
    assert cfg.limits.max_tasks_per_job == 30
    assert cfg.limits.max_revision_loops == 2
    task = cfg.llm.for_task("agent_05.script_draft")
    assert isinstance(task, LlmTaskSettings)
    assert task.model_tier is LlmModelTier.MID
    assert cfg.llm.resolve(LlmModelTier.MID).model == "model-from-config"
    with pytest.raises(ConfigInvalidError):
        cfg.llm.resolve(LlmModelTier.TOP)
    with pytest.raises(ConfigInvalidError):
        cfg.llm.for_task("agent_06.claim_extraction")


def test_json_config_file(tmp_path: Path) -> None:
    file = tmp_path / "amw.json"
    file.write_text(json.dumps({"reaper": {"interval_ms": 5000}}), encoding="utf-8")
    assert load_settings(config_file=file, environ={}).reaper.interval_ms == 5000
    bad = tmp_path / "amw.yaml"
    bad.write_text("x: 1", encoding="utf-8")
    with pytest.raises(ConfigInvalidError):
        load_settings(config_file=bad, environ={})
    listing = tmp_path / "list.json"
    listing.write_text("[1]", encoding="utf-8")
    with pytest.raises(ConfigInvalidError):
        load_settings(config_file=listing, environ={})


@pytest.mark.security
@pytest.mark.parametrize(
    "content",
    [f'[secrets]\nllm_api_key = "{CANARY}"\n', f'[database]\nurl = "{CANARY}"\n'],
)
def test_secrets_are_never_read_from_a_config_file(tmp_path: Path, content: str) -> None:
    file = tmp_path / "amw.toml"
    file.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigInvalidError) as err:
        load_settings(config_file=file, environ={})
    assert CANARY not in str(err.value)


@pytest.mark.security
def test_secrets_come_from_the_environment_and_a_mounted_directory(tmp_path: Path) -> None:
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    (secret_dir / "tts_api_key").write_text(CANARY + "-tts\n", encoding="utf-8")
    (secret_dir / ".hidden").write_text("ignored", encoding="utf-8")
    cfg = load_settings(
        environ={"AMW_SECRETS__LLM_API_KEY": CANARY, "AMW_DATABASE__URL": "postgresql://u:p@h/d"},
        secrets_dir=secret_dir,
    )
    assert cfg.secret("llm_api_key") == CANARY
    assert cfg.secret("tts_api_key") == CANARY + "-tts"
    assert ".hidden" not in cfg.secrets
    assert CANARY not in repr(cfg)
    assert CANARY not in str(cfg.model_dump())
    assert set(cfg.secret_values()) == {CANARY, CANARY + "-tts", "postgresql://u:p@h/d"}
    with pytest.raises(ConfigInvalidError):
        load_settings(environ={}, secrets_dir=tmp_path / "missing")


@pytest.mark.security
def test_startup_check_names_missing_secrets_only() -> None:
    cfg = load_settings(environ={"AMW_SECRETS__LLM_API_KEY": CANARY})
    require_secrets(cfg, ["llm_api_key"])
    with pytest.raises(ConfigInvalidError) as err:
        require_secrets(cfg, ["llm_api_key", "tts_api_key"])
    assert err.value.details == {"names": ["tts_api_key"]}
    assert CANARY not in str(err.value)
    assert CANARY not in json.dumps(err.value.details)
    with pytest.raises(ConfigInvalidError):
        cfg.secret("tts_api_key")


@pytest.mark.security
def test_invalid_values_report_fields_not_values() -> None:
    with pytest.raises(ConfigInvalidError) as err:
        load_settings(environ={"AMW_LIMITS__MAX_ATTEMPTS_PER_TASK": "11-" + CANARY})
    assert err.value.details["fields"] == ["limits.max_attempts_per_task"]
    assert CANARY not in str(err.value)
    with pytest.raises(ConfigInvalidError):
        load_settings(environ={"AMW_LIMITS__MAX_ATTEMPTS_PER_TASK": "11"})  # > DB ceiling 10
    with pytest.raises(ConfigInvalidError):
        load_settings(environ={"AMW_LIMITS__NOT_A_LIMIT": "1"})
    assert load_settings(environ={"AMW_TEST_DATABASE_URL": "x"}).limits.max_tasks_per_job == 200
    with pytest.raises(ConfigInvalidError):
        load_settings(environ={"AMW_BREAKER_DEFAULT__OPEN_MS": "1000000"})  # > open_ms_max
    with pytest.raises(ConfigInvalidError):
        load_settings(environ={"AMW_LIMITS": "1", "AMW_LIMITS__MAX_TASKS_PER_JOB": "2"})


def test_breaker_override_per_provider_operation() -> None:
    cfg = load_settings(
        environ={"AMW_BREAKER": '{"llm_provider.llm.completion": {"min_calls": 9}}'}
    )
    assert cfg.breaker_for("llm_provider", "llm.completion").min_calls == 9
    assert cfg.breaker_for("tts_provider", "tts.synthesize").min_calls == 5


def test_settings_are_frozen() -> None:
    cfg = load_settings(environ={})
    with pytest.raises(ValueError, match="frozen"):
        cfg.environment = "prod"  # type: ignore[misc]
    assert isinstance(cfg, AmwSettings)


def test_process_environment_is_the_default_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMW_REAPER__INTERVAL_MS", "7000")
    assert load_settings().reaper.interval_ms == 7000


def test_registry_rejects_a_key_declared_twice() -> None:
    reg = ConfigKeyRegistry()
    reg.declare("limits.max_tasks_per_job", "amw_core")
    reg.declare("agent_05.max_hooks", "agent_05")
    reg.declare("llm.agent_05.script_draft.model_tier", "agent_05")
    with pytest.raises(ConfigInvalidError, match="twice"):
        reg.declare("limits.max_tasks_per_job", "amw_core")
    with pytest.raises(ConfigInvalidError):
        reg.declare("agent_05.other", "agent_06")
    with pytest.raises(ConfigInvalidError):
        reg.declare("limits.foo", "agent_05")
    with pytest.raises(ConfigInvalidError):
        reg.declare("NotAKey", "amw_core")
    reg.allow_namespace("approvals", "svc_s07")
    reg.declare("approvals.owner_chat.window", "svc_s07")
    with pytest.raises(ConfigInvalidError):
        reg.allow_namespace("approvals", "agent_01")
    with pytest.raises(ConfigInvalidError):
        reg.allow_namespace("qc", "agent_10")
    with pytest.raises(ConfigInvalidError):
        reg.declare("finance.x", "agent_09")
    reg.declare_all(["retry.temporary.base_ms", "breaker.x.y.window_ms"], "amw_core")
    assert reg.keys["agent_05.max_hooks"] == "agent_05"


def test_currency_exponent_fixture_is_config_data_cited_to_rv07() -> None:
    """CCR-133 / P4-07: INR 2 and USD 2 exist only as config data (RV-07, REQUIRES REVIEW)."""
    from tests.core_services.support import CURRENCY_EXPONENT_FIXTURE

    text = CURRENCY_EXPONENT_FIXTURE.read_text(encoding="utf-8")
    assert "RV-07" in text
    assert "REQUIRES REVIEW" in text
    cfg = load_settings(environ={}, config_file=CURRENCY_EXPONENT_FIXTURE)
    assert cfg.finance.currency_minor_exponent == {"INR": 2, "USD": 2}
    assert load_settings(environ={}).finance.currency_minor_exponent == {}


def test_no_code_default_currency_exponent_in_source() -> None:
    """No source file under packages/*/src maps a currency code to its exponent."""
    import re

    pattern = re.compile(r"[\"'](INR|USD)[\"']\s*:\s*[0-9]")
    root = Path(__file__).resolve().parents[2] / "packages"
    hits = [str(p) for p in root.glob("**/src/**/*.py") if pattern.search(p.read_text("utf-8"))]
    assert hits == []
