# ruff: noqa: PT018
"""D13 / CCR-273 (PROPOSED), CAT-01: the finance-only preflight items (FIN-R10, the price-data lag
config item) apply only to a finance job; an unset or unknown category is finance (fail closed).
Every other item (PROVIDER_LIMIT evidence, org binding, caps, secrets, environment, config,
calendar, render window) is unchanged and a passing non-finance REAL_RUN mints its tokens."""

import dataclasses

import pytest
from pydantic import ValidationError

from amw_core.ids import JOB
from amw_orchestrator.executor import ChannelCategory, JobFacts, resolve_channel_category
from amw_orchestrator.services import run_job_preflight
from amw_runtime.config import RuntimeConfig, load_runtime_config
from amw_runtime.confirmations import ConfirmationKind, ConfirmationRecord
from amw_runtime.errors import PreflightRefused
from amw_runtime.preflight import PreflightReport, run_preflight
from tests.adapters.conftest import packaged_with_render_minutes  # noqa: F401  (autouse)
from tests.adapters.preflight_support import EVENING, ORG_ID, REAL_ENV, Lookup, limits
from tests.orchestrator.test_executor import _job

pytestmark = pytest.mark.unit


def _job_in_org(category: ChannelCategory) -> JobFacts:
    return dataclasses.replace(_job(category), org_id=str(ORG_ID), job_id=str(JOB.new()))


def _pf(
    job: JobFacts,
    records: list[ConfirmationRecord],
    **kwargs: object,
) -> PreflightReport:
    cfg = load_runtime_config(REAL_ENV)
    return run_job_preflight(
        job, cfg, records, env=REAL_ENV, evidence=Lookup(records), render_start=EVENING, **kwargs
    )


def _codes(job: JobFacts, records: list[ConfirmationRecord], **kwargs: object) -> set[str]:
    with pytest.raises(PreflightRefused) as exc:
        _pf(job, records, **kwargs)
    return {i.code for i in exc.value.items}


def _without_r10(records: list[ConfirmationRecord]) -> list[ConfirmationRecord]:
    return [r for r in records if r.kind is not ConfirmationKind.FIN_R10_NOT_SEBI_REGISTERED]


def _limits_only() -> list[ConfirmationRecord]:
    return _without_r10(limits())


def test_finance_job_is_refused_without_fin_r10_evidence() -> None:
    assert _codes(_job_in_org(ChannelCategory.FINANCE), _limits_only()) == {"FIN_R10"}


def test_finance_job_with_every_item_gets_tokens_and_the_fin_r10_check() -> None:
    rep = _pf(_job_in_org(ChannelCategory.FINANCE), limits())
    assert "FIN_R10" in rep.checks_passed and "LAG" in rep.checks_passed
    assert {a.provider for a in rep.provider_authorisations} == {"anthropic", "elevenlabs"}


def test_non_finance_job_gets_tokens_with_provider_limit_evidence_and_no_fin_r10() -> None:
    job = _job_in_org(ChannelCategory.NON_FINANCE)
    rep = _pf(job, _limits_only())
    assert {a.provider for a in rep.provider_authorisations} == {"anthropic", "elevenlabs"}
    assert all(
        a.org_id == job.org_id and a.job_id == job.job_id for a in rep.provider_authorisations
    )
    assert "FIN_R10" not in rep.checks_passed and "LAG" not in rep.checks_passed
    assert "PROVIDER_LIMIT:anthropic" in rep.checks_passed
    assert any("FIN_R10 and LAG not checked" in n for n in rep.notes)
    assert rep.open_owner_items == ()


def test_non_finance_job_without_provider_limit_evidence_is_refused() -> None:
    job = _job_in_org(ChannelCategory.NON_FINANCE)
    assert _codes(job, []) == {"PROVIDER_LIMIT:anthropic", "PROVIDER_LIMIT:elevenlabs"}
    one = [r for r in _limits_only() if r.provider == "anthropic"]
    assert _codes(job, one) == {"PROVIDER_LIMIT:elevenlabs"}


def test_non_finance_job_keeps_org_binding_environment_and_secrets() -> None:
    job = _job_in_org(ChannelCategory.NON_FINANCE)
    cfg = load_runtime_config(REAL_ENV)
    records = _limits_only()
    other_org = dataclasses.replace(job, org_id=str(JOB.new()))  # evidence bound to ORG_ID
    with pytest.raises(PreflightRefused) as exc:
        run_job_preflight(
            other_org, cfg, records, env=REAL_ENV, evidence=Lookup(records), render_start=EVENING
        )
    assert {i.code for i in exc.value.items} == {
        "PROVIDER_LIMIT:anthropic",
        "PROVIDER_LIMIT:elevenlabs",
    }
    with pytest.raises(PreflightRefused) as exc2:
        run_job_preflight(job, cfg, records, env={}, evidence=Lookup(records), render_start=EVENING)
    assert {"SECRETS", "ENVIRONMENT"} <= {i.code for i in exc2.value.items}


@pytest.mark.parametrize(
    "raw", [None, "", "finance", "philosophy", "Youtube_General", "nonfinance"]
)
def test_unset_or_unknown_category_is_finance_and_needs_fin_r10(raw: str | None) -> None:
    category = resolve_channel_category(raw)
    assert category is ChannelCategory.FINANCE
    assert _codes(_job_in_org(category), _limits_only()) == {"FIN_R10"}


def test_the_flag_is_the_jobs_not_the_callers() -> None:
    # a caller cannot relax a finance job through kwargs: the job's own category wins
    fin = _job_in_org(ChannelCategory.FINANCE)
    assert _codes(fin, _limits_only(), finance_rules_apply=False) == {"FIN_R10"}
    # nor tighten or loosen it by anything else the caller passes
    non = _job_in_org(ChannelCategory.NON_FINANCE)
    assert "LAG" not in _pf(non, _limits_only(), finance_rules_apply=True).checks_passed


def test_the_flag_cannot_come_from_config_or_confirmations() -> None:
    base = load_runtime_config(REAL_ENV).model_dump(warnings=False)
    with pytest.raises(ValidationError):
        RuntimeConfig.model_validate({**base, "finance_rules_apply": False})
    with pytest.raises(ValidationError):
        ConfirmationRecord(
            kind=ConfirmationKind.PROVIDER_LIMIT,
            finance_rules_apply=False,  # type: ignore[call-arg]
        )


def test_default_of_run_preflight_is_finance_and_a_hand_built_report_opens_nothing() -> None:
    cfg = load_runtime_config(REAL_ENV)
    records = _limits_only()
    with pytest.raises(PreflightRefused) as exc:  # the direct call defaults to finance
        run_preflight(
            cfg, records, env=REAL_ENV, evidence=Lookup(records), render_start=EVENING,
            org_id=str(ORG_ID),
        )  # fmt: skip
    assert {i.code for i in exc.value.items} == {"FIN_R10"}
    hand_built = PreflightReport(
        mode=cfg.mode, checks_passed=(), secrets_checked=True, test_confirmation_used=False,
        disclaimer_status="", open_owner_items=(), notes=("FIN_R10 waived",),
    )  # fmt: skip
    assert hand_built.provider_authorisations == ()
