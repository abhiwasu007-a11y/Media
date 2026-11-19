# ruff: noqa: PT018
"""D13 / CCR-273 (PROPOSED), CAT-01: the finance-only preflight items (FIN-R10, the price-data lag
config item) apply only to a finance job; an unset or unknown category is finance (fail closed).
Every other item (PROVIDER_LIMIT evidence, org binding, caps, secrets, environment, config,
calendar, render window) is unchanged and a passing non-finance REAL_RUN mints its tokens."""

import ast
import dataclasses
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from amw_core.ids import JOB
from amw_orchestrator.executor import ChannelCategory, JobFacts, resolve_channel_category
from amw_orchestrator.services import run_job_preflight
from amw_runtime.config import RuntimeConfig, load_runtime_config
from amw_runtime.confirmations import ConfirmationKind, ConfirmationRecord
from amw_runtime.errors import PreflightRefused
from amw_runtime.preflight import (
    JobPreflightScope,
    PreflightReport,
    mint_job_scope,
    run_preflight,
)
from tests.adapters.conftest import packaged_with_render_minutes  # noqa: F401  (autouse)
from tests.adapters.preflight_support import EVENING, ORG_ID, REAL_ENV, Lookup, limits
from tests.orchestrator.test_executor import _job

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]


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
    non = _job_in_org(ChannelCategory.NON_FINANCE)
    forged = mint_job_scope(org_id=fin.org_id, job_id=fin.job_id, finance_rules_apply=False)
    assert _codes(fin, _limits_only(), job_scope=forged) == {"FIN_R10"}  # overwritten by the job's
    # the old public boolean no longer exists on either entry point
    with pytest.raises(TypeError):
        _pf(fin, _limits_only(), finance_rules_apply=False)
    with pytest.raises(TypeError):
        _pf(non, _limits_only(), finance_rules_apply=True)


def test_run_preflight_has_no_public_boolean_and_a_scope_cannot_be_hand_built() -> None:
    cfg = load_runtime_config(REAL_ENV)
    records = _limits_only()
    kw: dict[str, Any] = {
        "env": REAL_ENV, "evidence": Lookup(records), "render_start": EVENING,
        "org_id": str(ORG_ID),
    }  # fmt: skip
    with pytest.raises(TypeError):
        run_preflight(cfg, records, finance_rules_apply=False, **kw)  # type: ignore[call-arg]
    with pytest.raises(TypeError):  # no key: not constructible
        JobPreflightScope(str(ORG_ID), "job_x", False)
    with pytest.raises(TypeError):
        JobPreflightScope(str(ORG_ID), "job_x", False, object())
    fake = SimpleNamespace(org_id=str(ORG_ID), job_id="job_x", finance_rules_apply=False)
    with pytest.raises(PreflightRefused) as exc:  # a duck is not a scope
        run_preflight(cfg, records, job_scope=fake, job_id="job_x", **kw)  # type: ignore[arg-type]
    assert {i.code for i in exc.value.items} == {"JOB_SCOPE"}


def test_a_scope_of_another_org_or_job_is_refused() -> None:
    cfg = load_runtime_config(REAL_ENV)
    records = _limits_only()
    job_id = str(JOB.new())
    kw: dict[str, Any] = {
        "env": REAL_ENV, "evidence": Lookup(records), "render_start": EVENING,
    }  # fmt: skip
    for scope_org, scope_job in [(str(JOB.new()), job_id), (str(ORG_ID), str(JOB.new()))]:
        scope = mint_job_scope(org_id=scope_org, job_id=scope_job, finance_rules_apply=False)
        with pytest.raises(PreflightRefused) as exc:
            run_preflight(cfg, records, job_scope=scope, org_id=str(ORG_ID), job_id=job_id, **kw)
        assert {i.code for i in exc.value.items} == {"JOB_SCOPE"}
    scope = mint_job_scope(org_id=str(ORG_ID), job_id="job_x", finance_rules_apply=False)
    with pytest.raises(PreflightRefused) as exc2:  # no job id at all
        run_preflight(cfg, records, job_scope=scope, org_id=str(ORG_ID), **kw)
    assert {i.code for i in exc2.value.items} == {"JOB_SCOPE"}


def test_only_the_orchestrator_job_preflight_mints_a_scope() -> None:
    callers = []
    for path in (ROOT / "packages").rglob("*.py"):
        if "/src/" not in path.as_posix():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            name = (
                node.func.id if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                else node.func.attr if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) else ""
            )  # fmt: skip
            if name in {"mint_job_scope", "JobPreflightScope"}:
                callers.append(path.relative_to(ROOT).as_posix())
    assert sorted(set(callers)) == [
        "packages/amw_orchestrator/src/amw_orchestrator/services.py",
        "packages/amw_runtime/src/amw_runtime/preflight.py",
    ]


def test_the_report_carries_the_resolved_category() -> None:
    for category in ChannelCategory:
        rep = _pf(_job_in_org(category), limits() if category is ChannelCategory.FINANCE
                  else _limits_only())  # fmt: skip
        assert f"job channel category (from channels.category): {category.value}" in rep.notes


def test_the_flag_cannot_come_from_config_or_confirmations() -> None:
    base = load_runtime_config(REAL_ENV).model_dump(warnings=False)
    with pytest.raises(ValidationError):
        RuntimeConfig.model_validate({**base, "finance_rules_apply": False})
    with pytest.raises(ValidationError):
        ConfirmationRecord(  # type: ignore[call-arg]
            kind=ConfirmationKind.PROVIDER_LIMIT,
            finance_rules_apply=False,
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
