# ruff: noqa: PT018
"""Deterministic datasets run fully: ``compliance_rules_core`` (50) and ``uniqueness_check`` (20),
both 100 % thresholds; plus unit tests of the S2 measures."""

from typing import Any

import pytest

from agent_16_compliance_qa.checks import RuleResult
from agent_16_compliance_qa.checks import rules as R  # noqa: N812
from agent_16_compliance_qa.uniqueness import (
    Measures,
    Segment,
    Thresholds,
    decide,
    masked_identical,
    role_sequence_equal,
    shot_sequence_identity,
    template_text_share,
)
from amw_core import ids
from amw_core.enums import AudienceKind, PresenterKind
from amw_core.errors import CrossTenantRefError
from tests.agents.agent_16_compliance_qa.support import EN_LEXICON, case_ids, cases

RULES = cases("compliance_rules_core")
UQ = cases("uniqueness_check")


def _result(r: RuleResult) -> dict[str, Any]:
    return {
        "rule_id": r.rule_id,
        "check_verdict": r.check_verdict.value,
        "compliance_verdict": r.compliance_verdict.value if r.compliance_verdict else None,
    }


def run_rule_case(fn: str, inp: dict[str, Any]) -> dict[str, Any]:
    if fn == "price_lag":
        r = R.price_lag(
            [R.ChartAge(**c) for c in inp["charts"]],
            [R.TextPrice(**t) for t in inp["text_prices"]],
            inp["lag_days"],
        )
        return _result(r) | {"days_until_compliant": r.extras["days_until_compliant"]}
    if fn == "disclaimer":
        r = R.disclaimer(**inp)
        return _result(r) | {k: r.extras[k] for k in ("description_check", "report_label")}
    if fn == "method_release":
        r = R.method_release(
            [R.MethodSegment(**s) for s in inp["segments"]], inp["label_overlay_present"]
        )
        return _result(r)
    if fn == "live_format":
        r = R.live_format(
            inp["production_type_key"],
            inp["format"],
            inp["metadata_terms"],
            tuple(EN_LEXICON["live_format_terms"]),
        )
        return _result(r) | {"metadata_check": r.extras["metadata_check"]}
    if fn == "persona":
        voice = inp["voice"]
        r = R.persona(
            inp["channel_sensitive"],
            PresenterKind(voice["presenter_kind"]) if voice else None,
            voice is not None,
            [R.PersonAsset(**a) for a in inp["render_assets"]],
            [R.PersonAsset(**a) for a in inp["thumbnail_assets"]],
        )
        return _result(r)
    if fn == "licence":
        r5, r6, expiring = R.licence([R.LicensedAsset(**a) for a in inp["assets"]])
        return {
            "YTG-R5": {k: v for k, v in _result(r5).items() if k != "rule_id"},
            "YTG-R6": {k: v for k, v in _result(r6).items() if k != "rule_id"},
            "expiring_assets": expiring,
        }
    if fn == "audience":
        kind = AudienceKind(inp["audience_kind"]) if inp["audience_kind"] else None
        return _result(R.audience(kind, inp["kids_pack_active"]))
    if fn == "disclosure":
        d = R.disclosure(
            [R.DisclosureAsset(**a) for a in inp["assets"]],
            [R.RealismShot(**s) for s in inp["realism_shots"]],
            inp["voice_kind"],
        )
        return {
            "rule_id": d.rule_id,
            "disclosure_decision": d.disclosure_decision.value,
            "decided_by_order": d.decided_by_order,
        }
    raise AssertionError(fn)


@pytest.mark.unit
@pytest.mark.parametrize("case", RULES, ids=case_ids(RULES))
def test_compliance_rules_core_case(case: dict[str, Any]) -> None:
    assert len(RULES) == 50
    assert run_rule_case(case["function"], case["input"]) == case["expected"]


def _uq(fx: dict[str, Any]) -> Any:
    m = Measures.model_validate({k: v for k, v in fx.items() if k != "thresholds"})
    return decide(m, Thresholds.model_validate(fx["thresholds"]), 3, "s05_script")


@pytest.mark.unit
@pytest.mark.parametrize("case", UQ, ids=case_ids(UQ))
def test_uniqueness_case(case: dict[str, Any]) -> None:
    exp = case["expected"]
    if exp["verdict"] == "FAILED_TASK":
        with pytest.raises(CrossTenantRefError) as ei:
            _uq(case["input"]["fixture"])
        assert ei.value.code == exp["checks"]["error"]
        return
    d = _uq(case["input"]["fixture"])
    assert d.verdict.value == exp["verdict"]
    for cid, v in exp["checks"].items():
        assert d.checks[cid].value == v, cid
    if "remedy_stage_id" in exp:
        assert d.remedy_stage_id == exp["remedy_stage_id"]
        fail = next(r for r in d.results if r.check_id == "a16.uniq.masked_structure")
        assert fail.gate and fail.blocking and fail.remedy_stage_id == "s05_script"
    assert all(r.gate for r in d.results)
    assert not any(r.blocking for r in d.results if r.verdict.value in ("WARN", "SKIPPED"))


def test_uniqueness_measures() -> None:
    template = [
        Segment(section_role="HOOK", text="Today we look at {topic}."),
        Segment(section_role="BODY", text="Here is {point}."),
    ]
    filled = [
        Segment(section_role="HOOK", text="Today we look at stop orders."),
        Segment(section_role="BODY", text="Here is the gap."),
    ]
    own = [
        Segment(section_role="HOOK", text="Your stop filled at 97, not 100."),
        Segment(section_role="BODY", text="A gap skips the level."),
    ]
    assert masked_identical(filled, template) and not masked_identical(own, template)
    assert not masked_identical(filled[:1], template) and not masked_identical(filled, [])
    assert role_sequence_equal(own, template)
    assert template_text_share(filled, template) > template_text_share(own, template)
    assert template_text_share([], template) == 0.0
    assert shot_sequence_identity(["A", "B", "C"], ["A", "B", "D"]) == round(2 / 3, 4)
    assert shot_sequence_identity([], []) == 0.0


def test_uniqueness_payload_contract() -> None:
    from agent_16_compliance_qa.output import uniqueness_payload
    from tests.agents.agent_16_compliance_qa.support import validate_against_blueprint

    for case in UQ:
        fx = case["input"]["fixture"]
        if not fx["refs_same_org"]:
            continue
        m = Measures.model_validate({k: v for k, v in fx.items() if k != "thresholds"})
        t = Thresholds.model_validate(fx["thresholds"])
        payload = uniqueness_payload(
            decide(m, t, 3, "s05_script"),
            m,
            t,
            f"amw-blob://{ids.ORG.new()}/evidence/job/uniq.json",
        )
        validate_against_blueprint(payload, "### 8.3 `svc_s02.uniqueness_check.output`")
