"""amw_core.observability: JSON lines with tenant / correlation fields; secret redaction (08 3.1
rule 3; the log-leak test of 08 section 8.5 injects a canary secret)."""

import io
import json
import logging
import threading

import pytest

from amw_core.observability import (
    REDACTED,
    Redactor,
    bind_log_context,
    configure_logging,
    contains_secret,
    current_log_context,
    get_logger,
    log_context,
)
from amw_core.observability.redaction import RedactionFilter

pytestmark = pytest.mark.unit
CANARY = "canary-9f3e2d1c0b-secret"


def _capture(redactor: Redactor | None = None) -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    configure_logging(redactor, stream=stream)
    return get_logger("test"), stream


def _lines(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_every_line_carries_the_context_fields() -> None:
    log, stream = _capture()
    with log_context(org_id="org_a", correlation_id="cor_1", job_id="job_1", actor="agent_01"):
        with log_context(task_id="tsk_1", attempt_id="att_1"):
            log.info("step %s done", "x", extra={"tokens_in": 12})
        log.warning("outer")
    log.info("no context")
    first, second, third = _lines(stream)
    assert first["message"] == "step x done"
    for key, value in {
        "org_id": "org_a",
        "correlation_id": "cor_1",
        "job_id": "job_1",
        "task_id": "tsk_1",
        "attempt_id": "att_1",
        "actor": "agent_01",
        "tokens_in": 12,
        "level": "INFO",
        "logger": "amw.test",
    }.items():
        assert first[key] == value
    assert "task_id" not in second and second["org_id"] == "org_a"
    assert third["org_id"] == "platform"  # 08 section 8: platform-wide lines say so
    assert str(first["ts"]).endswith("Z")


def test_failure_fields_and_extra_override() -> None:
    log, stream = _capture()
    with log_context(org_id="org_a", error_code="AGENT.CRASH", error_class="AGENT"):
        log.error("failed", extra={"org_id": "org_b_explicit"})
    (line,) = _lines(stream)
    assert line["error_code"] == "AGENT.CRASH" and line["error_class"] == "AGENT"
    assert line["org_id"] == "org_b_explicit"


def test_unknown_context_field_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown"), log_context(prompt_text="x"):  # type: ignore[arg-type]
        pass


def test_context_is_isolated_per_thread() -> None:
    seen: dict[str, object] = {}

    def worker() -> None:
        seen["ctx"] = current_log_context()

    with log_context(org_id="org_a"):
        t = threading.Thread(target=worker)
        t.start()
        t.join()
    assert seen["ctx"] == {}
    bind_log_context(org_id="org_bound")
    assert current_log_context()["org_id"] == "org_bound"
    bind_log_context(org_id=None)


@pytest.mark.security
def test_canary_secret_never_reaches_a_log_line() -> None:
    log, stream = _capture(Redactor([CANARY]))
    with log_context(org_id="org_a"):
        log.info("calling provider with %s", CANARY)
        log.info("headers", extra={"headers": {"x-api-key": CANARY, "accept": "json"}})
        log.info("nested", extra={"payload": {"items": [f"prefix {CANARY} suffix"]}})
        try:
            raise RuntimeError(f"boom {CANARY}")
        except RuntimeError:
            log.exception("crash")
    text = stream.getvalue()
    assert CANARY not in text
    lines = _lines(stream)
    assert lines[1]["headers"] == {"x-api-key": REDACTED, "accept": "json"}
    assert "exception" in lines[3] and REDACTED in str(lines[3]["exception"])


@pytest.mark.security
@pytest.mark.parametrize(
    "value",
    [
        "sk-ant-api03-" + "A" * 30,
        "sk-" + "b" * 40,
        "ghp_" + "c" * 36,
        "AIza" + "d" * 35,
        "AKIA" + "E" * 16,
        "xoxb-1234567890-abc",
        "Authorization: Bearer abcdefghijklmnop",
        "Basic dXNlcjpwYXNzd29yZDEyMw==",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.c2lnbmF0dXJlLXZhbHVl",
        "password=hunter2hunter2",
        "-----BEGIN PRIVATE KEY-----\nMIIEv\n-----END PRIVATE KEY-----",
    ],
)
def test_known_secret_patterns_are_removed(value: str) -> None:
    out = Redactor().text(f"before {value} after")
    assert REDACTED in out
    assert value not in out


@pytest.mark.security
def test_url_credentials_and_secret_named_fields() -> None:
    r = Redactor()
    assert r.text("postgresql://amw:pw123@db.internal/amw") == f"postgresql://{REDACTED}@db.internal/amw"
    redacted = r.value(
        {
            "api_key": "x",
            "access_token": "y",
            "password": "z",
            "tokens_in": 10,
            "idempotency_key": "idk_" + "0" * 64,
            "task_id": "tsk_1",
            "raw": b"\x00\x01",
            "nested": [{"secret": "s"}],
        }
    )
    assert redacted["api_key"] == REDACTED and redacted["access_token"] == REDACTED
    assert redacted["password"] == REDACTED and redacted["nested"] == [{"secret": REDACTED}]
    assert redacted["tokens_in"] == 10 and redacted["task_id"] == "tsk_1"
    assert redacted["idempotency_key"] == "idk_" + "0" * 64
    assert redacted["raw"] == "<2 bytes>"
    assert r.value({"token": None}) == {"token": None}


def test_short_values_are_not_mass_redacted() -> None:
    r = Redactor(["abc", "longer-secret"])
    assert r.text("abc longer-secret") == f"abc {REDACTED}"


@pytest.mark.security
def test_contains_secret() -> None:
    assert contains_secret({"note": "sk-ant-" + "x" * 30})
    assert contains_secret({"password": "pw"})
    assert not contains_secret({"from": "ACTIVE", "to": "SUSPENDED_EXCEEDED", "n": 1, "l": [b"x"]})


def test_filter_handles_bad_format_args() -> None:
    record = logging.LogRecord("amw.x", logging.INFO, __file__, 1, "%d", ("not-int",), None)
    assert RedactionFilter().filter(record)
    assert record.msg == "%d" and record.args is None


def test_configure_logging_replaces_its_own_handler() -> None:
    _capture()
    _, stream = _capture()
    logger = logging.getLogger("amw")
    assert sum(1 for h in logger.handlers if getattr(h, "_amw_handler", False)) == 1
    get_logger("amw.x").info("once")
    assert len(_lines(stream)) == 1
