# ruff: noqa: E501, PT018
"""CCR-302 (PROPOSED): the credit artifact of ``s06_verify`` reaches the script gate as a context ref."""

from types import SimpleNamespace
from typing import Any

import pytest

from amw_core.enums import ContextRefPurpose
from amw_orchestrator.input_builders import agent_16 as b16
from amw_orchestrator.input_builders import common as common

pytestmark = pytest.mark.unit
BASE = "amw-blob://org_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8f01/jobs/j/tasks/t/attempts/a/artifacts/"
SHA = "ab" * 32


def _out(*names: str) -> Any:
    return SimpleNamespace(output_refs=[SimpleNamespace(uri=BASE + n, sha256=SHA) for n in names])


def test_the_credit_artifact_is_passed_as_a_prior_output_context_ref(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        common,
        "stage_output",
        lambda ctx, stage: _out("claim_verification_output.json", "quote_credits.json"),
    )
    (ref,) = b16._credit_refs(object())  # type: ignore[arg-type]
    assert ref.purpose is ContextRefPurpose.PRIOR_OUTPUT and ref.uri.endswith("quote_credits.json")
    assert ref.sha256 == SHA and ref.schema_ == "agent_06.quote_credits"


def test_no_credit_artifact_means_no_extra_ref(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        common, "stage_output", lambda ctx, stage: _out("claim_verification_output.json")
    )
    assert b16._credit_refs(object()) == []  # type: ignore[arg-type]
