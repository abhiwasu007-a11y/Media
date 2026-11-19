"""The provider authorisation cannot be forged in plain Python (MAJOR 1 of the PR 96 review).

Every test tries one way round the gate and must fail. What these tests do NOT cover (and cannot):
code that can run arbitrary code in the process (read closure cells of ``amw_runtime.preflight``,
patch module globals or memory) can always forge; the seal stops mistakes and in-tree shortcuts."""

import copy
import pickle
from datetime import UTC, datetime, timedelta

import pytest

from amw_adapters.llm.anthropic import AnthropicLlmAdapter
from amw_adapters.real import authorisation as authorisation_module
from amw_adapters.real.authorisation import (
    ProviderAuthorisation,
    install_verifier,
    verify_authorisation,
)
from amw_adapters.real.catalogue import load_catalogue
from amw_adapters.real.guard import BudgetCallGuard, CapOnlyCallGuard, call_scope, require_guard
from amw_adapters.real.secrets import SecretRef
from amw_core.errors import ConfigInvalidError
from amw_runtime import preflight as preflight_module
from amw_runtime.errors import PreflightRefused
from tests.adapters.guards import GuardedWorld, auth, cap_guard
from tests.adapters.mock_providers import ANTHROPIC_SECRET, TEST_ENV
from tests.adapters.preflight_support import ORG_ID, passed_report

pytestmark = pytest.mark.security
CAT = load_catalogue()
NOW = datetime.now(UTC)


def verify(token: ProviderAuthorisation) -> object:
    return verify_authorisation(token, NOW, provider=token.provider, currency=token.currency)


def fields(token: ProviderAuthorisation) -> dict[str, object]:
    return {
        "provider": token.provider, "org_id": token.org_id, "job_id": token.job_id,
        "per_video_cap_micros": token.per_video_cap_micros,
        "total_cap_micros": token.total_cap_micros, "currency": token.currency,
        "issued_at": token.issued_at, "expires_at": token.expires_at, "nonce": token.nonce,
        "seal": token.seal,
    }  # fmt: skip


def test_a_real_token_verifies_and_is_clamped_to_the_owner_ceiling() -> None:
    grant = verify(auth("anthropic"))
    assert (grant.per_video_cap_micros, grant.total_cap_micros) == (5_000_000, 50_000_000)  # type: ignore[attr-defined]


def test_no_mint_function_or_mint_key_is_importable() -> None:
    for name in ("mint_provider_authorisation", "_MINT", "_KEY", "_SECRET", "_key"):
        assert not hasattr(authorisation_module, name)
    assert not any(isinstance(v, bytes | bytearray) for v in vars(preflight_module).values())


def test_hand_built_token_with_any_seal_fails() -> None:
    real = auth("anthropic")
    base = fields(real)
    for seal in (b"\0" * 32, b"", real.seal[:-1] + b"x"):
        forged = ProviderAuthorisation(**{**base, "seal": seal})  # type: ignore[arg-type]
        with pytest.raises(ConfigInvalidError):
            verify(forged)


@pytest.mark.parametrize(
    "change",
    [
        {"per_video_cap_micros": 10**12, "total_cap_micros": 10**12},
        {"total_cap_micros": 10**12},
        {"org_id": "org_other"},
        {"job_id": "job_other"},
        {"provider": "elevenlabs"},
        {"expires_at": 2**40},
        {"nonce": "another"},
    ],
)
def test_copying_fields_of_a_real_token_and_changing_one_breaks_the_seal(
    change: dict[str, object],
) -> None:
    real = auth("anthropic")
    forged = ProviderAuthorisation(**{**fields(real), **change})  # type: ignore[arg-type]
    with pytest.raises(ConfigInvalidError):
        verify_authorisation(forged, NOW, provider=forged.provider, currency="USD")


def test_the_token_is_immutable_uncopyable_and_final() -> None:
    real = auth("anthropic")
    with pytest.raises(AttributeError):
        real.per_video_cap_micros = 10**12
    with pytest.raises(AttributeError):
        del real.seal
    for fn in (pickle.dumps, copy.copy, copy.deepcopy):
        with pytest.raises(TypeError):
            fn(real)
    with pytest.raises(TypeError):

        class Sub(ProviderAuthorisation):  # type: ignore[misc]  # a subclass could override ``canonical``
            pass


def test_a_subclass_or_lookalike_token_is_refused_by_the_verifier() -> None:
    class Look:
        provider = "anthropic"
        currency = "USD"

    with pytest.raises(ConfigInvalidError):
        verify_authorisation(Look(), NOW, provider="anthropic", currency="USD")


def test_the_verifier_cannot_be_replaced_from_outside_preflight() -> None:
    with pytest.raises(ConfigInvalidError):
        install_verifier(lambda a, n: None)  # type: ignore[arg-type,return-value]


def test_issuing_works_only_inside_run_preflight() -> None:
    with pytest.raises(ConfigInvalidError):
        preflight_module._issue_authorisation(
            "anthropic", ORG_ID, None, 10**12, 10**12, "USD", NOW, timedelta(days=999),
            ["PROVIDER_LIMIT:anthropic"],
        )  # fmt: skip


def test_a_cap_above_the_owner_ceiling_cannot_come_out_of_a_preflight() -> None:
    with pytest.raises(PreflightRefused):
        passed_report(cap_micros=10**12)


def test_adapters_refuse_noop_duck_typed_and_subclassed_guards() -> None:
    real = auth("anthropic")

    class NoOpGuard:
        authorisation = real

        def before(self, call: object) -> None: ...
        def after(self, usage: object) -> None: ...
        def failed(self, key: str, *, delivered: bool | None) -> None: ...
        def check_authorisation(self, **kw: object) -> None: ...

    secret = SecretRef(ANTHROPIC_SECRET, TEST_ENV)
    with pytest.raises(ConfigInvalidError):
        AnthropicLlmAdapter(CAT.anthropic, secret, guard=NoOpGuard())  # type: ignore[arg-type]
    with pytest.raises(ConfigInvalidError):
        require_guard(NoOpGuard(), provider="anthropic", currency="USD")  # type: ignore[arg-type]
    with pytest.raises(TypeError):

        class Sub(CapOnlyCallGuard):  # type: ignore[misc]
            def before(self, call: object) -> None: ...

    with pytest.raises(TypeError):

        class Sub2(BudgetCallGuard):  # type: ignore[misc]
            pass


def test_a_token_is_checked_at_every_call_and_expires() -> None:
    token = auth("anthropic", ttl=timedelta(seconds=60))
    clock = [datetime.now(UTC)]
    guard = CapOnlyCallGuard(token, now=lambda: clock[0])
    from amw_adapters.real.guard import PlannedCall

    call = PlannedCall("anthropic", "llm.completion", 1, "USD", "idk_" + "0" * 64)
    guard.before(call)
    clock[0] += timedelta(seconds=61)
    with pytest.raises(ConfigInvalidError, match="expired"):
        guard.before(call)
    with pytest.raises(ConfigInvalidError, match="expired"):
        require_guard(guard, provider="anthropic", currency="USD")


def test_a_token_is_bound_to_its_org_and_job() -> None:
    world = GuardedWorld()
    other_job = world.w.job()
    for token in (
        auth("anthropic", org_id=ORG_ID, job_id=world.job),  # another org
        auth("anthropic", org_id=world.w.org, job_id=other_job),  # another job
        auth("anthropic", org_id=world.w.org, job_id=None),  # no job at all
    ):
        guard = BudgetCallGuard(
            token, budget=world.w.guard, ledger=world.w.ledger,
            tenancy=world.guard("anthropic")._tenancy, clock=world.w.clock,
        )  # fmt: skip
        from amw_adapters.real.guard import PlannedCall

        with call_scope(world.ctx), pytest.raises(ConfigInvalidError, match="bound"):
            guard.before(PlannedCall("anthropic", "llm.completion", 1, "USD", "idk_" + "1" * 64))


def test_a_token_for_another_provider_is_refused() -> None:
    with pytest.raises(ConfigInvalidError):
        require_guard(cap_guard("elevenlabs"), provider="anthropic", currency="USD")
