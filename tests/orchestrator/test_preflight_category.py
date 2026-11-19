# ruff: noqa: PT018
"""D13 / CCR-273 (PROPOSED): FIN-R10 is a finance-only gate; an unset or unknown category is
finance (fail closed). Every other preflight item still refuses a non-finance job."""

import pytest

from amw_orchestrator import services
from amw_orchestrator.executor import ChannelCategory, JobFacts
from amw_orchestrator.services import run_job_preflight
from amw_runtime.config import RunMode, load_runtime_config
from amw_runtime.errors import PreflightRefused, UnmetItem
from amw_runtime.preflight import PreflightReport
from tests.orchestrator.test_executor import _job

pytestmark = pytest.mark.unit
ENV = {"AMW_RUNTIME_MODE": "REAL_RUN"}


def _refused(job: JobFacts) -> PreflightRefused:
    cfg = load_runtime_config(ENV)
    assert cfg.mode is RunMode.REAL_RUN
    with pytest.raises(PreflightRefused) as exc:
        run_job_preflight(job, cfg, [], env={})
    return exc.value


def test_finance_job_is_refused_for_fin_r10_and_every_other_item() -> None:
    codes = {i.code for i in _refused(_job(ChannelCategory.FINANCE)).items}
    assert "FIN_R10" in codes and len(codes) > 1


def test_non_finance_job_never_waits_on_fin_r10_but_keeps_every_other_refusal() -> None:
    codes = {i.code for i in _refused(_job(ChannelCategory.NON_FINANCE)).items}
    assert "FIN_R10" not in codes and codes  # PROVIDER_LIMIT, secrets, environment... remain


def test_a_refusal_that_lists_only_fin_r10_is_waived_for_non_finance_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    only = PreflightRefused((UnmetItem("FIN_R10", "owner confirmation missing"),))

    def refuse(*args: object, **kwargs: object) -> PreflightReport:
        raise only

    monkeypatch.setattr(services, "run_preflight", refuse)
    cfg = load_runtime_config(ENV)
    report = run_job_preflight(_job(ChannelCategory.NON_FINANCE), cfg, [])
    assert "FIN_R10 waived" in report.notes[0]
    with pytest.raises(PreflightRefused):  # finance, and an unset category, keep the refusal
        run_job_preflight(_job(ChannelCategory.FINANCE), cfg, [])
