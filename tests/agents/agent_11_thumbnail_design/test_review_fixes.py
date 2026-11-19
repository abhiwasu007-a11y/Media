"""PR #39 review fixes: fail-closed config (B1, M1, M7, M6), Devanagari matching (M2), no partial
output (M3), replay after an in-flight call (M4), cross-tenant ASSET refs (M5)."""

import dataclasses
from datetime import datetime, timedelta
from typing import Any

import pytest

from agent_11_thumbnail_design.errors import FontIntegrityError
from agent_11_thumbnail_design.models import Brief, Promise
from agent_11_thumbnail_design.stage import Lexicons, RulePacks, ThumbnailStage
from agent_11_thumbnail_design.textutil import contains_sequence, folded_words
from amw_core.errors import (
    ConfigInvalidError,
    CrossTenantRefError,
    LockConflictError,
    MissingDependencyError,
    QualityRepeatedFailureError,
)
from tests.agents.agent_11_thumbnail_design.env import Env, make_env
from tests.agents.agent_11_thumbnail_design.fakes import FakeClock

NEUTRAL = (
    Promise(
        promise_statement="Learn to read a trend.",
        promise_key_terms=("trend",),
        working_title_local="How to read a trend",
    ),
    Brief(subject_idea="level steps", text_idea_local="Read the trend", must_not_promise=()),
)


def _with(env: Env, **deps: Any) -> Env:
    d = dataclasses.replace(env.stage.d, **deps)
    return dataclasses.replace(env, stage=ThumbnailStage(d))


def _lex(env: Env, **kw: Any) -> Lexicons:
    return dataclasses.replace(env.stage.d.lexicons, **kw)


@pytest.mark.parametrize("markers", [(), ("", "  ")])
def test_b1_finance_with_absent_or_empty_marker_list_is_config_invalid(
    markers: tuple[str, ...],
) -> None:
    env = _with(make_env(finance=True, promise=NEUTRAL), lexicons=_lex_for(markers))
    with pytest.raises(ConfigInvalidError) as e:
        env.stage.run(env.ti, "att_1")
    assert e.value.details["check_id"] == "a11.pre.config"
    assert "compliance.finance_sebi_in.markers" in e.value.details["violations"]
    assert env.llm.calls == 0


def _lex_for(markers: tuple[str, ...]) -> Lexicons:
    base = make_env().stage.d.lexicons
    return dataclasses.replace(base, finance_markers=markers)


def test_b1_empty_marker_list_is_fine_off_finance_but_injection_lists_always_required() -> None:
    ok = _with(make_env(), lexicons=_lex_for(()))
    assert ok.stage.run(ok.ti, "a").status.value == "SUCCEEDED"
    env = make_env()
    bad = _with(env, lexicons=_lex(env, injection_markers=(), instruction_phrases=()))
    with pytest.raises(ConfigInvalidError) as e:
        bad.stage.run(bad.ti, "a")
    assert {"injection_markers", "instruction_phrases"} <= set(e.value.details["violations"])
    assert bad.llm.calls == 0


def test_m7_missing_finance_pack_and_altered_prompt_fail_closed() -> None:
    env = make_env(finance=True, promise=NEUTRAL)
    packs = RulePacks({"rp.youtube_general": "x"}, None)
    gone = _with(env, packs=packs)
    with pytest.raises(ConfigInvalidError) as e:
        gone.stage.run(gone.ti, "a")
    assert "rule_pack:rp.finance_sebi_in" in e.value.details["violations"]
    tampered = _with(env, prompt=dataclasses.replace(env.stage.d.prompt, text="changed"))
    with pytest.raises(ConfigInvalidError) as e2:
        tampered.stage.run(tampered.ti, "a")
    assert "prompt_sha256_mismatch" in e2.value.details["violations"]
    assert env.llm.calls == 0


def test_m6_missing_raqm_is_permanent_and_precedes_the_paid_call() -> None:
    env = make_env()

    class NoRaqm:
        def __init__(self, inner: Any) -> None:
            self._i = inner

        def raqm_available(self) -> bool:
            return False

        def __getattr__(self, name: str) -> Any:
            return getattr(self._i, name)

    env = _with(env, composer=NoRaqm(env.stage.d.composer))
    with pytest.raises(MissingDependencyError) as e:
        env.stage.run(env.ti, "a")
    assert e.value.code == "PERMANENT.MISSING_DEPENDENCY"
    assert env.llm.calls == 0


def test_unpinned_render_environment_is_permanent_and_precedes_the_paid_call() -> None:
    env = make_env()

    class Unpinned:
        def __init__(self, inner: Any) -> None:
            self._i = inner

        def environment_problem(self) -> str | None:
            return "not pinned"

        def __getattr__(self, name: str) -> Any:
            return getattr(self._i, name)

    env = _with(env, composer=Unpinned(env.stage.d.composer))
    with pytest.raises(MissingDependencyError) as e:
        env.stage.run(env.ti, "a")
    assert e.value.details["missing"] == ["pinned_render_environment"]
    assert env.llm.calls == 0


def test_unpinned_font_asset_is_refused_before_the_paid_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = make_env()
    monkeypatch.setattr(
        "agent_11_thumbnail_design.stage.verify_font",
        lambda *_: (_ for _ in ()).throw(FontIntegrityError("x")),
    )
    with pytest.raises(MissingDependencyError) as e:
        env.stage.run(env.ti, "a")
    assert e.value.details["missing"] == ["pinned_font"]
    assert env.llm.calls == 0


def test_m1_promise_statement_that_is_a_call_is_blocked_on_finance() -> None:
    p = Promise(
        promise_statement="Buy this stock today for profit.",
        promise_key_terms=("stock",),
        working_title_local="A look at the stock",
    )
    env = make_env(finance=True, promise=(p, NEUTRAL[1]))
    out = env.stage.run(env.ti, "a")
    assert out.payload is not None
    assert out.payload.data is not None
    assert out.payload.data["verdict"] == "BLOCKED"
    assert out.payload.data["violated_rule_ids"] == ["FIN-R1"]
    assert env.llm.calls == 0


def test_m2_devanagari_vowel_signs_are_not_stripped_and_matching_is_whole_word() -> None:
    assert folded_words("खरेदी करा शेअर वाचा, किंमती!") == ["खरेदी", "करा", "शेअर", "वाचा", "किंमती"]
    assert not contains_sequence(folded_words("किंमती वाचा"), folded_words("किंमत"))
    assert not contains_sequence(folded_words("करा"), folded_words("कर"))
    assert contains_sequence(folded_words("किंमत वाचा."), folded_words("किंमत"))
    assert folded_words("(buy), now!") == ["buy", "now"]


def test_m3_licence_failure_leaves_no_asset_ledger_row_or_png() -> None:
    env = make_env()
    reg = env.repo.registered[("FONT", "ast_font")]
    env.repo.registered[("FONT", "ast_font")] = dataclasses.replace(reg, licence_state="REVOKED")
    before = set(env.storage.blobs)
    with pytest.raises(QualityRepeatedFailureError) as e:
        env.stage.run(env.ti, "a")
    assert "a11.q.licence_rows" in e.value.details["check_ids"]
    assert env.repo.image_inserts == []
    assert env.repo.ledger_inserts == []
    assert not [u for u in set(env.storage.blobs) - before if "/thumbnails/" in u]


class _Killed(BaseException):
    pass


class _LateClock(FakeClock):
    def now(self) -> datetime:
        return super().now() + timedelta(hours=1)


def test_m4_replay_after_a_kill_inside_the_llm_call_reconciles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = make_env()

    def dies(request: Any, *, idempotency_key: str) -> Any:
        raise _Killed

    with monkeypatch.context() as m:
        m.setattr(env.llm, "complete", dies)
        with pytest.raises(_Killed):
            env.stage.run(env.ti, "att_1")
        # still locked: another attempt may hold it -> retryable, not INPUT_INVALID
        with pytest.raises(LockConflictError):
            env.stage.run(env.ti, "att_2")
    late = _LateClock()
    env2 = _with(env, clock=late)
    out = env2.stage.run(env2.ti, "att_3")
    assert out.payload is not None
    assert out.payload.data is not None
    assert out.payload.data["variant_count_produced"] == 3
    assert any(c.get("reconciled_stale_key") for c in out.payload.data["provenance"]["calls"])


def test_m5_cross_tenant_asset_ref_is_rejected_with_a_security_event() -> None:
    env = make_env(owner_assets=1)
    other = "org_00000000-0000-7000-8000-0000000000ff"
    refs = [
        *env.ti.context_refs,
        env.ti.context_refs[0].model_copy(update={"uri": f"amw-blob://{other}/assets/x.png"}),
    ]
    ti = env.ti.model_copy(update={"context_refs": tuple(refs)})
    with pytest.raises(CrossTenantRefError):
        env.stage.run(ti, "a")
    assert [e.action for e in env.audit.entries] == ["security.cross_tenant_ref"]
    assert env.llm.calls == 0


def test_m5_unresolvable_own_asset_ref_is_missing_dependency() -> None:
    env = make_env(owner_assets=1)
    env.repo.assets.clear()
    with pytest.raises(MissingDependencyError):
        env.stage.run(env.ti, "a")
