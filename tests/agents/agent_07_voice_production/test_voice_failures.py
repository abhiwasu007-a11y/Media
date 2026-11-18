"""FI-01...FI-17 for ``s07_voice`` and the S-tests (tenancy, log leak, no list_voices)."""

import copy
import json
import logging
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_07_voice_production import voice_stage
from agent_07_voice_production.ports import TtsAdapterView
from amw_adapters.common import FailurePlan
from amw_core.contracts.task_output import TaskOutput
from amw_core.enums import OutputStatus
from amw_core.errors import (
    AuthInvalidError,
    CallTimeoutError,
    ProviderRefusalError,
    RateLimitedError,
    Upstream5xxError,
)
from amw_core.ids import TaskId
from tests.agents.agent_07_voice_production.support import NOW, ToneTts, capabilities
from tests.agents.agent_07_voice_production.voice_world import VoiceWorld, build

ROOT = Path(__file__).resolve().parents[3]
LINES = (
    (ROOT / "docs/v4/evals/agent_07_voice_production/voice_synthesis/cases.jsonl")
    .read_text("utf-8")
    .splitlines()
)
BY_ID = {json.loads(x)["case_id"]: json.loads(x) for x in LINES}
pytestmark = [pytest.mark.failure_injection]


def world(tmp: Path, case_id: str = "VS-01", **faults: Any) -> VoiceWorld:
    case = copy.deepcopy(BY_ID[case_id])
    w = build(case, tmp)
    if "sequence" in faults:
        w.tts.engine.failures = FailurePlan(sequence=faults["sequence"])
    return w


def code(out: TaskOutput) -> str | None:
    return out.error.code if out.error else None


def test_fi01_rate_limit_beyond_the_cap_ends_the_attempt_retryable(tmp_path: Path) -> None:
    w = world(tmp_path, sequence=[RateLimitedError("429", retry_after_ms=10**9)])
    out = w.run()
    assert out.status is OutputStatus.FAILED
    assert code(out) == "TEMPORARY.RATE_LIMITED"
    assert out.error is not None
    assert out.error.retryable
    assert w.ledger.rows == {}


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (Upstream5xxError("5xx"), "TEMPORARY.UPSTREAM_5XX"),
        (CallTimeoutError("t"), "TEMPORARY.TIMEOUT"),
    ],
)
def test_fi02_fi03_temporary_failures_exhaust_the_in_attempt_retries(
    tmp_path: Path, failure: Any, expected: str
) -> None:
    w = world(tmp_path, sequence=[failure] * 3)
    out = w.run()
    assert code(out) == expected
    assert w.tts.invocations == 3
    assert len(w.ledger.rows) == 0
    assert w.registry.asset_rows == 0


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (AuthInvalidError("401"), "PERMANENT.AUTH_INVALID"),
        (ProviderRefusalError("no"), "PERMANENT.PROVIDER_REFUSAL"),
    ],
)
def test_fi04_fi05_permanent_provider_failures_are_not_retried(
    tmp_path: Path, failure: Any, expected: str
) -> None:
    w = world(tmp_path, sequence=[failure])
    out = w.run()
    assert code(out) == expected
    assert w.tts.invocations == 1


def test_fi07_silent_clip_is_corrupted_output(tmp_path: Path) -> None:
    case = copy.deepcopy(BY_ID["VS-01"])
    case["input"]["fixtures"]["adapter"]["fake"]["behaviour"] = "SILENT"
    out = build(case, tmp_path).run()
    assert code(out) == "AGENT.CORRUPTED_OUTPUT"


def test_implausible_duration_is_corrupted_output(tmp_path: Path) -> None:
    case = copy.deepcopy(BY_ID["VS-01"])
    w = build(case, tmp_path)
    w.stage._d = replace(
        w.stage._d, config=w.stage._d.config.model_copy(update={"clip_max_ms_per_char": 10})
    )
    assert code(w.run()) == "AGENT.CORRUPTED_OUTPUT"


def test_fi11_resume_after_a_kill_makes_one_call_per_segment(tmp_path: Path) -> None:
    w = world(
        tmp_path,
        sequence=[None, None, Upstream5xxError("x"), Upstream5xxError("x"), Upstream5xxError("x")],
    )
    first = w.run("att_01939e5a-7c3b-7d1e-8a4f-0123456789a1")
    assert first.status is OutputStatus.FAILED
    assert w.tts.invocations == 2 + 3
    assert len(w.ledger.rows) == 2  # the two finished sentences are ledgered, nothing else
    before = w.tts.invocations
    second = w.run("att_01939e5a-7c3b-7d1e-8a4f-0123456789a2")
    assert second.status is OutputStatus.SUCCEEDED
    assert w.tts.invocations - before == 1  # only the third sentence is called
    assert len(w.ledger.rows) == 3
    assert w.registry.asset_rows == 1
    assert second.payload is not None
    assert second.payload.data is not None
    assert second.payload.data["cost"]["calls"] == 3
    assert second.payload.data["cost"]["characters"] == 116


def test_fi16_drain_at_a_segment_boundary_checkpoints_and_suspends(tmp_path: Path) -> None:
    w = world(tmp_path)
    w.stage._d.control.drain = True  # type: ignore[attr-defined]
    out = w.run()
    assert out.status is OutputStatus.SUSPENDED
    assert out.next_action.wait_reason is not None
    assert out.next_action.wait_reason.value == "DRAIN"
    assert w.tts.invocations == 1
    assert w.registry.asset_rows == 0
    cps = w.stage._d.checkpoints.list_for_task(_tx(w), TaskId(w.task_input.task_id))
    assert [c.checkpoint.step_key for c in cps][-1] == "voice.drain"
    assert len(cps[-1].checkpoint.completed_effects) == 1


def _tx(w: VoiceWorld) -> Any:
    from amw_core.ids import ActorRef, OrgId
    from amw_core.interfaces.tenancy_context import TenantContext
    from amw_core.testing.memory import MemoryTransaction

    return MemoryTransaction(TenantContext(OrgId(w.org), ActorRef("agent_07")))


def test_fi17_consent_withdrawn_between_batches_stops_further_calls(tmp_path: Path) -> None:
    case = copy.deepcopy(BY_ID["VS-12"])
    w = build(case, tmp_path)
    deps = w.stage._d
    deps_cfg = deps.config.model_copy(update={"checkpoint_every_n": 1})
    bundle = w.facts.bundle
    assert bundle is not None
    assert bundle.consent is not None
    withdrawn = replace(
        bundle, consent=replace(bundle.consent, withdrawn_at=NOW - timedelta(days=1))
    )
    state = {"reads": 0}
    original = w.facts.voice_bundle

    def flip(tx: Any, voice_id: str) -> Any:
        state["reads"] += 1
        return (
            original(tx, voice_id) if state["reads"] == 1 else withdrawn
        )  # first read at the start

    w.facts.voice_bundle = flip  # type: ignore[method-assign]
    w.stage._d = replace(deps, config=deps_cfg)
    out = w.run()
    assert code(out) == "PERMANENT.PERMISSION_DENIED"
    assert w.tts.invocations == 1
    assert w.registry.asset_rows == 0


# --- S-tests --------------------------------------------------------------------------------


@pytest.mark.security
def test_s09_list_voices_is_unreachable_from_a_stage() -> None:
    view = TtsAdapterView(ToneTts(), capabilities())
    assert not hasattr(view, "list_voices")
    assert not hasattr(view, "engine")


@pytest.mark.security
def test_s05_no_script_text_or_secret_in_logs_or_outputs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    case = copy.deepcopy(BY_ID["VS-01"])
    canary = "CANARY-SCRIPT-TEXT-9f3"
    case["input"]["fixtures"]["script"]["segments"][0]["text"] = f"{canary} आज"
    w = build(case, tmp_path)
    with caplog.at_level(logging.DEBUG, logger="agent_07"):
        out = w.run()
    assert out.status is OutputStatus.SUCCEEDED
    blob = json.dumps(out.model_dump(mode="json"), ensure_ascii=False)
    assert canary not in blob
    assert "fake-neutral-1" not in blob
    logs = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert logs
    assert canary not in logs
    assert "fake-neutral-1" not in logs
    assert all(
        getattr(r, "org_id", None) == w.org for r in caplog.records
    )  # every line carries org_id
    consent_free = out.payload is not None and out.payload.data is not None
    assert consent_free
    assert "voice_owner_name" not in blob


@pytest.mark.tenancy
def test_cross_tenant_refs_and_rows_are_never_read(tmp_path: Path) -> None:
    for case_id, expected in (
        ("VS-28", "PERMANENT.CROSS_TENANT_REF"),
        ("VS-27", "PERMANENT.MISSING_DEPENDENCY"),
    ):
        w = build(copy.deepcopy(BY_ID[case_id]), tmp_path / case_id)
        out = w.run()
        assert code(out) == expected
        assert w.tts.invocations == 0
        assert not any(OTHER in u for u in w.blobs.reads for OTHER in ("0123456789cd",))


@pytest.mark.tenancy
def test_task_for_another_agent_or_org_is_a_tenant_error(tmp_path: Path) -> None:
    w = build(copy.deepcopy(BY_ID["VS-01"]), tmp_path)
    wrong = w.task_input.model_copy(update={"agent_id": "agent_08"})
    out = w.stage.run(wrong, "att_01939e5a-7c3b-7d1e-8a4f-0123456789a1")
    assert code(out) == "PERMANENT.TENANT_MISMATCH"


def test_voice_stage_module_names_no_provider_literal() -> None:
    source = Path(voice_stage.__file__).read_text(encoding="utf-8")
    assert "elevenlabs" not in source.lower()
    assert "google" not in source.lower()
