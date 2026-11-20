# ruff: noqa: PT018
"""D13 / CCR-273 (PROPOSED), CAT-01: the finance-only preflight items (FIN-R10, the price-data lag
config item) apply only to a finance job; an unset or unknown category is finance (fail closed).

The non-finance decision is DERIVED inside ``run_job_preflight`` from the job's own row and
``channels.category`` (re-read in the tenant transaction), never taken from a caller object: the
public ``JobFacts`` cannot carry it, and the sealed ``JobPreflightScope`` cannot be forged, copied
or replayed. Every other item (PROVIDER_LIMIT evidence, org binding, caps, secrets, environment,
calendar, render window) is unchanged and a passing non-finance REAL_RUN mints its tokens.

Needs ``AMW_TEST_DATABASE_URL`` for the database tests (the suite skips without it)."""

import copy
import dataclasses
import pickle
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

import amw_orchestrator.services as services_module
import amw_runtime.preflight as preflight_module
from amw_core.config import RulePackSettings
from amw_core.ids import CHANNEL, JOB
from amw_core.interfaces.tenancy_context import TenantContext, TenantTransaction
from amw_orchestrator.executor import ChannelCategory, JobFacts
from amw_orchestrator.services import run_job_preflight
from amw_runtime.config import RuntimeConfig, load_runtime_config
from amw_runtime.confirmations import ConfirmationKind, ConfirmationRecord
from amw_runtime.errors import PreflightRefused
from amw_runtime.preflight import (
    JobPreflightScope,
    PreflightReport,
    mint_job_scope,
    register_job_scope_minter,
    run_preflight,
)
from tests.adapters.conftest import packaged_with_render_minutes  # noqa: F401  (autouse)
from tests.adapters.preflight_support import EVENING, ORG_ID, REAL_ENV, Lookup, limits
from tests.orchestrator.world import Rig, build_rig

NON_FINANCE_ROW = "youtube_general"  # the philosophy channel: a documented non-finance category


def _without_r10(records: list[ConfirmationRecord]) -> list[ConfirmationRecord]:
    return [r for r in records if r.kind is not ConfirmationKind.FIN_R10_NOT_SEBI_REGISTERED]


def _records(rig: Rig, *, r10: bool) -> list[ConfirmationRecord]:
    records = limits(rig.seed.org_id)
    return records if r10 else _without_r10(records)


def _pf(
    rig: Rig, job: JobFacts, records: list[ConfirmationRecord], **kwargs: Any
) -> PreflightReport:
    return run_job_preflight(
        job, load_runtime_config(REAL_ENV), records,
        tenancy=kwargs.pop("tenancy", rig.tenancy), jobs=rig.jobs,
        env=REAL_ENV, evidence=Lookup(records, rig.seed.org_id), render_start=EVENING, **kwargs,
    )  # fmt: skip


def _codes(rig: Rig, job: JobFacts, records: list[ConfirmationRecord], **kw: Any) -> set[str]:
    with pytest.raises(PreflightRefused) as exc:
        _pf(rig, job, records, **kw)
    return {i.code for i in exc.value.items}


# ---- the decision follows the channel row --------------------------------------------------------


@pytest.mark.integration
def test_finance_job_is_refused_without_fin_r10_evidence(pg_dsn: str, tmp_path: Path) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    job = rig.intake("finance")
    assert _codes(rig, job, _records(rig, r10=False)) == {"FIN_R10"}


@pytest.mark.integration
def test_finance_job_with_every_item_gets_tokens_and_the_fin_r10_check(
    pg_dsn: str, tmp_path: Path
) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    rep = _pf(rig, rig.intake("finance"), _records(rig, r10=True))
    assert "FIN_R10" in rep.checks_passed and "LAG" in rep.checks_passed
    assert {a.provider for a in rep.provider_authorisations} == {"anthropic", "elevenlabs"}


@pytest.mark.integration
def test_non_finance_job_gets_tokens_with_provider_limit_evidence_and_no_fin_r10(
    pg_dsn: str, tmp_path: Path
) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    job = rig.intake(NON_FINANCE_ROW)
    rep = _pf(rig, job, _records(rig, r10=False))
    assert {a.provider for a in rep.provider_authorisations} == {"anthropic", "elevenlabs"}
    assert all(
        a.org_id == job.org_id and a.job_id == job.job_id for a in rep.provider_authorisations
    )
    assert "FIN_R10" not in rep.checks_passed and "LAG" not in rep.checks_passed
    assert "PROVIDER_LIMIT:anthropic" in rep.checks_passed
    assert any("FIN_R10 and LAG not checked" in n for n in rep.notes)
    assert rep.open_owner_items == ()


@pytest.mark.integration
def test_non_finance_job_without_provider_limit_evidence_is_refused(
    pg_dsn: str, tmp_path: Path
) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    job = rig.intake(NON_FINANCE_ROW)
    assert _codes(rig, job, []) == {"PROVIDER_LIMIT:anthropic", "PROVIDER_LIMIT:elevenlabs"}
    one = [r for r in _records(rig, r10=False) if r.provider == "anthropic"]
    assert _codes(rig, job, one) == {"PROVIDER_LIMIT:elevenlabs"}


@pytest.mark.integration
def test_non_finance_job_keeps_org_binding_environment_and_secrets(
    pg_dsn: str, tmp_path: Path
) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    job = rig.intake(NON_FINANCE_ROW)
    records = _records(rig, r10=False)
    cfg = load_runtime_config(REAL_ENV)
    other_org_evidence = Lookup(records, str(JOB.new()))  # the rows belong to another org
    with pytest.raises(PreflightRefused) as exc:
        run_job_preflight(
            job, cfg, records, tenancy=rig.tenancy, jobs=rig.jobs, env=REAL_ENV,
            evidence=other_org_evidence, render_start=EVENING,
        )  # fmt: skip
    assert {i.code for i in exc.value.items} == {
        "PROVIDER_LIMIT:anthropic",
        "PROVIDER_LIMIT:elevenlabs",
    }
    with pytest.raises(PreflightRefused) as exc2:
        run_job_preflight(
            job, cfg, records, tenancy=rig.tenancy, jobs=rig.jobs, env={},
            evidence=Lookup(records, rig.seed.org_id), render_start=EVENING,
        )  # fmt: skip
    assert {"SECRETS", "ENVIRONMENT"} <= {i.code for i in exc2.value.items}


@pytest.mark.integration
@pytest.mark.parametrize(
    "stored",
    ["finance", "philosophy", "YouTube_General", "non_finance", "non-finance", "nonfinance", ""],
)
def test_unset_or_undocumented_category_is_finance_and_needs_fin_r10(
    pg_dsn: str, tmp_path: Path, stored: str
) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    job = rig.intake(stored)
    assert _codes(rig, job, _records(rig, r10=False)) == {"FIN_R10"}


@pytest.mark.integration
def test_the_rule_pack_settings_narrow_the_preflight_decision(pg_dsn: str, tmp_path: Path) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    job = rig.intake(NON_FINANCE_ROW)
    narrowed = RulePackSettings(non_finance_categories=frozenset({"kids"}))
    assert _codes(rig, job, _records(rig, r10=False), rule_packs=narrowed) == {"FIN_R10"}
    broken: Any = {"non_finance_categories": {"finance", NON_FINANCE_ROW}}  # not a RulePackSettings
    assert _codes(rig, job, _records(rig, r10=False), rule_packs=broken) == {"FIN_R10"}


@pytest.mark.integration
def test_the_report_carries_the_category_that_was_re_read(pg_dsn: str, tmp_path: Path) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    for stored, category in (("finance", ChannelCategory.FINANCE),
                             (NON_FINANCE_ROW, ChannelCategory.NON_FINANCE)):  # fmt: skip
        job = rig.intake(stored, title=f"Report {stored}")
        rep = _pf(rig, job, _records(rig, r10=category is ChannelCategory.FINANCE))
        assert f"job channel category (re-read from channels.category): {category.value}" in (
            rep.notes
        )


# ---- the decision is not the caller's: JobFacts, kwargs, the channel edited later ----------------


@pytest.mark.integration
def test_a_forged_job_facts_cannot_relax_a_finance_job(pg_dsn: str, tmp_path: Path) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    job = rig.intake("finance")
    records = _records(rig, r10=False)
    forged = [
        dataclasses.replace(job, channel_category=ChannelCategory.NON_FINANCE),
        dataclasses.replace(
            job, channel_category=ChannelCategory.NON_FINANCE, channel_category_row=NON_FINANCE_ROW
        ),
        dataclasses.replace(job, channel_id=str(CHANNEL.new())),  # another (unknown) channel
    ]
    for facts in forged:
        assert _codes(rig, facts, records) == {"FIN_R10"}


@pytest.mark.integration
def test_job_facts_that_claim_finance_do_not_tighten_a_non_finance_row_either(
    pg_dsn: str, tmp_path: Path
) -> None:
    # the decision is the row's in both directions: the caller object is not read at all
    rig = build_rig(pg_dsn, tmp_path)
    job = rig.intake(NON_FINANCE_ROW)
    claims_finance = dataclasses.replace(job, channel_category=ChannelCategory.FINANCE)
    rep = _pf(rig, claims_finance, _records(rig, r10=False))
    assert "FIN_R10" not in rep.checks_passed


@pytest.mark.integration
def test_the_channel_row_is_re_read_at_preflight_not_at_intake(pg_dsn: str, tmp_path: Path) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    job = rig.intake(NON_FINANCE_ROW)
    assert job.finance_rules_apply is False  # what intake saw
    rig.set_channel_category("finance")  # the channel is edited afterwards
    assert _codes(rig, job, _records(rig, r10=False)) == {"FIN_R10"}
    rig.set_channel_category(NON_FINANCE_ROW)
    assert "FIN_R10" not in _pf(rig, job, _records(rig, r10=False)).checks_passed


@pytest.mark.integration
def test_an_unknown_job_or_another_org_or_a_failing_tenancy_is_finance(
    pg_dsn: str, tmp_path: Path
) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    job = rig.intake(NON_FINANCE_ROW)
    records = _records(rig, r10=False)
    # a job id that has no row: the channel is unknown, so finance
    assert _codes(rig, dataclasses.replace(job, job_id=str(JOB.new())), records) == {"FIN_R10"}

    class Failing:
        @contextmanager
        def transaction(self, context: TenantContext) -> Iterator[TenantTransaction]:
            raise RuntimeError("database down")
            yield  # pragma: no cover

    assert _codes(rig, job, records, tenancy=Failing()) == {"FIN_R10"}
    other_org = dataclasses.replace(job, org_id=str(JOB.new()))
    assert "FIN_R10" in _codes(rig, other_org, records)


@pytest.mark.integration
def test_kwargs_cannot_carry_the_decision_or_the_binding(pg_dsn: str, tmp_path: Path) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    fin = rig.intake("finance")
    records = _records(rig, r10=False)
    with pytest.raises(TypeError):
        _pf(rig, fin, records, finance_rules_apply=False)
    forged = SimpleNamespace(org_id=fin.org_id, job_id=fin.job_id, finance_rules_apply=False)
    assert _codes(rig, fin, records, job_scope=forged) == {"FIN_R10"}  # overwritten by the minted
    rep = _pf(rig, rig.intake(NON_FINANCE_ROW, title="kwargs job"), _records(rig, r10=False),
              job_id="job_someone_else", org_id="org_other")  # fmt: skip
    assert all(a.org_id == rig.seed.org_id for a in rep.provider_authorisations)


# ---- the scope cannot be forged, copied, replayed or minted elsewhere ----------------------------


class _Spy:
    """Captures the scope ``run_job_preflight`` hands to ``run_preflight``."""

    def __init__(self) -> None:
        self.scopes: list[JobPreflightScope] = []

    def __call__(self, *args: Any, **kwargs: Any) -> PreflightReport:
        self.scopes.append(kwargs["job_scope"])
        return run_preflight(*args, **kwargs)


def _real_scope(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, stored: str
) -> tuple[JobPreflightScope, JobFacts]:
    spy = _Spy()
    monkeypatch.setattr(services_module, "run_preflight", spy)
    job = rig.intake(stored, title=f"Scope {stored}")
    _pf(rig, job, _records(rig, r10=stored == "finance"))
    return spy.scopes[0], job


def _direct(rig: Rig, job: JobFacts, scope: object, *, org: str | None = None) -> set[str]:
    records = _records(rig, r10=False)
    with pytest.raises(PreflightRefused) as exc:
        run_preflight(
            load_runtime_config(REAL_ENV), records, env=REAL_ENV,
            evidence=Lookup(records, rig.seed.org_id), render_start=EVENING,
            org_id=org or job.org_id, job_id=job.job_id, job_scope=scope,  # type: ignore[arg-type]
        )  # fmt: skip
    return {i.code for i in exc.value.items}


@pytest.mark.integration
def test_a_scope_is_final_frozen_and_has_no_key_in_the_module(
    pg_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    scope, _ = _real_scope(rig, monkeypatch, NON_FINANCE_ROW)
    assert scope.finance_rules_apply is False and len(scope.seal) == 32
    with pytest.raises(AttributeError):
        scope.finance_rules_apply = True
    with pytest.raises(AttributeError):
        del scope.org_id
    with pytest.raises(TypeError):
        type("Sub", (JobPreflightScope,), {})
    assert "sealed" in repr(scope) and scope.nonce not in repr(scope)
    # the seal key is a closure variable, not a module attribute
    assert not any(isinstance(v, bytes) and len(v) == 32 for v in vars(preflight_module).values())


@pytest.mark.integration
def test_every_forgery_route_is_refused(
    pg_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    scope, job = _real_scope(rig, monkeypatch, "finance")  # a finance scope: flipping it relaxes
    # route 1: dataclasses.replace (not a dataclass: refused outright)
    with pytest.raises(TypeError):
        dataclasses.replace(scope, finance_rules_apply=False)  # type: ignore[type-var]
    # route 2: the constructor with every field, a made-up seal (no module key exists to use)
    for seal in (b"\0" * 32, scope.seal, b"x" * 32):
        ctor = JobPreflightScope(
            org_id=job.org_id, job_id=job.job_id, finance_rules_apply=False,
            expires_at=scope.expires_at, nonce="n1" + str(seal[:1]), seal=seal,
        )  # fmt: skip
        assert _direct(rig, job, ctor) == {"JOB_SCOPE"}
    # route 3: object.__new__ plus object.__setattr__ (all fields, and a half-built object)
    forged = object.__new__(JobPreflightScope)
    assert _direct(rig, job, forged) == {"JOB_SCOPE"}
    for name, value in (("org_id", job.org_id), ("job_id", job.job_id),
                        ("finance_rules_apply", False), ("expires_at", scope.expires_at),
                        ("nonce", "n2"), ("seal", scope.seal)):  # fmt: skip
        object.__setattr__(forged, name, value)
    assert _direct(rig, job, forged) == {"JOB_SCOPE"}
    # route 4: flip the decision on a real scope (the seal covers it)
    object.__setattr__(scope, "finance_rules_apply", False)
    assert _direct(rig, job, scope) == {"JOB_SCOPE"}


@pytest.mark.integration
def test_a_scope_cannot_be_copied_deep_copied_pickled_or_replaced(
    pg_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    scope, _ = _real_scope(rig, monkeypatch, NON_FINANCE_ROW)
    for action in (
        copy.copy, copy.deepcopy, copy.replace, pickle.dumps,
        lambda s: pickle.dumps(s, protocol=0), lambda s: pickle.dumps(s, protocol=2),
        lambda s: s.__reduce__(), lambda s: s.__getstate__(),
    ):  # fmt: skip
        with pytest.raises(TypeError):
            action(scope)


@pytest.mark.integration
def test_a_real_scope_is_bound_to_org_and_job_used_once_and_expires(
    pg_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    scope, job = _real_scope(rig, monkeypatch, NON_FINANCE_ROW)  # already used once inside
    assert _direct(rig, job, scope) == {"JOB_SCOPE"}  # one use: a replay is refused
    for stored_title, org_or_job in (("a", "org"), ("b", "job")):
        fresh, fjob = _real_scope(rig, monkeypatch, NON_FINANCE_ROW)
        if org_or_job == "org":
            assert _direct(rig, fjob, fresh, org=str(JOB.new())) == {"JOB_SCOPE"}
        else:
            other = dataclasses.replace(fjob, job_id=str(JOB.new()))
            assert _direct(rig, other, fresh) == {"JOB_SCOPE"}
        assert stored_title
    fresh, fjob = _real_scope(rig, monkeypatch, NON_FINANCE_ROW)

    class Later(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> Later:
            return cls.fromtimestamp((datetime.now(UTC) + timedelta(hours=1)).timestamp(), tz)

    monkeypatch.setattr(preflight_module, "datetime", Later)
    assert _direct(rig, fjob, fresh) == {"JOB_SCOPE"}  # expired


@pytest.mark.integration
def test_only_the_registered_orchestrator_job_preflight_can_mint(
    pg_dsn: str, tmp_path: Path
) -> None:
    build_rig(pg_dsn, tmp_path)
    org, job = str(ORG_ID), str(JOB.new())
    with pytest.raises(Exception, match="minted only by"):  # called from a test function
        mint_job_scope(org_id=org, job_id=job, finance_rules_apply=False)

    def looks_like_it(**kw: Any) -> JobPreflightScope:  # same name, another code object
        return mint_job_scope(**kw)

    with pytest.raises(Exception, match="minted only by"):
        looks_like_it(org_id=org, job_id=job, finance_rules_apply=False)
    with pytest.raises(Exception, match="already registered"):  # the minter is registered once
        register_job_scope_minter(looks_like_it.__code__)
    # and a registration attempt cannot displace run_job_preflight
    with pytest.raises(Exception, match="minted only by"):
        mint_job_scope(org_id=org, job_id=job, finance_rules_apply=False)


# ---- run_preflight on its own --------------------------------------------------------------------


@pytest.mark.unit
def test_run_preflight_has_no_public_boolean_a_duck_is_not_a_scope_and_it_defaults_to_finance() -> (
    None
):
    cfg = load_runtime_config(REAL_ENV)
    records = _without_r10(limits())
    kw: dict[str, Any] = {
        "env": REAL_ENV, "evidence": Lookup(records), "render_start": EVENING,
        "org_id": str(ORG_ID),
    }  # fmt: skip
    with pytest.raises(TypeError):
        run_preflight(cfg, records, finance_rules_apply=False, **kw)  # type: ignore[call-arg]
    with pytest.raises(PreflightRefused) as exc:  # the direct call defaults to finance
        run_preflight(cfg, records, **kw)
    assert {i.code for i in exc.value.items} == {"FIN_R10"}
    fake = SimpleNamespace(org_id=str(ORG_ID), job_id="job_x", finance_rules_apply=False)
    with pytest.raises(PreflightRefused) as exc:  # a duck is not a scope
        run_preflight(cfg, records, job_scope=fake, job_id="job_x", **kw)  # type: ignore[arg-type]
    assert {i.code for i in exc.value.items} == {"JOB_SCOPE"}
    with pytest.raises(PreflightRefused) as exc:  # no job id at all
        run_preflight(cfg, records, job_scope=fake, **kw)  # type: ignore[arg-type]
    assert {i.code for i in exc.value.items} == {"JOB_SCOPE"}


@pytest.mark.unit
def test_the_flag_cannot_come_from_config_or_confirmations() -> None:
    base = load_runtime_config(REAL_ENV).model_dump(warnings=False)
    with pytest.raises(ValidationError):
        RuntimeConfig.model_validate({**base, "finance_rules_apply": False})
    with pytest.raises(ValidationError):
        ConfirmationRecord(  # type: ignore[call-arg]
            kind=ConfirmationKind.PROVIDER_LIMIT,
            finance_rules_apply=False,
        )


@pytest.mark.unit
def test_a_hand_built_report_opens_nothing() -> None:
    cfg = load_runtime_config(REAL_ENV)
    hand_built = PreflightReport(
        mode=cfg.mode, checks_passed=(), secrets_checked=True, test_confirmation_used=False,
        disclaimer_status="", open_owner_items=(), notes=("FIN_R10 waived",),
    )  # fmt: skip
    assert hand_built.provider_authorisations == ()
