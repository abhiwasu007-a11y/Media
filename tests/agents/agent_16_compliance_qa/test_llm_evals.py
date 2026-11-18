# ruff: noqa: PT018
"""The four LLM datasets against recorded-fixture fake responses (no paid call, no network).

The datasets define the expected **outcome**, not a model reply, so each case's recorded reply
is built from its ``expected`` object (``recorded_*``): VIOLATION for ``violation_required``,
NO_VIOLATION for ``not_violation`` and for every other rule where ALLOWED is acceptable,
UNCERTAIN otherwise; quotes copied from the item text; refusals as stated. The deterministic
post-checks and the algebra then run end to end and the code-computed verdict is asserted. Where
a case's outcome depends on code (V6, V9, frame test, FIN-R9, V11), a second test feeds an
all-NO_VIOLATION judge and proves code alone holds the verdict. The packs also go through the
``amw_evals`` runner (schema and refusal assertions) with the same recorded replies.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from agent_16_compliance_qa.algebra import evaluate_policy, policy_verdict, post_check
from agent_16_compliance_qa.authorisation.evidence import derive_approval_state
from agent_16_compliance_qa.authorisation.facts import EvidenceFacts, StepFacts
from agent_16_compliance_qa.config import Lexicon
from agent_16_compliance_qa.judge.frames import apply_frames
from agent_16_compliance_qa.judge.models import (
    FramesOutput,
    ItemClaim,
    ParaphraseInput,
    ParaphraseOutput,
    PolicyInput,
    PolicyOutput,
    QualityOutput,
)
from agent_16_compliance_qa.judge.paraphrase import QuotationApproval, apply_paraphrase
from agent_16_compliance_qa.judge.quality import apply_quality
from agent_16_compliance_qa.prefilter import select_rules
from agent_16_compliance_qa.scoring.rubric import Criterion
from amw_core.enums import ApprovalChannel, ApprovalState, ComplianceVerdict, QualityDimension
from amw_evals.adapter import FakeAdapter, LlmResponse
from amw_evals.runner import run_eval
from tests.agents.agent_16_compliance_qa.support import (
    EN_LEXICON,
    EVALS,
    REPO,
    case_ids,
    cases,
    config,
    evidence_mapping,
)

CG = cases("compliance_gate")
PARA = cases("compliance_gate_paraphrase")
FRAMES = cases("compliance_gate_frames")
QS = cases("quality_score")
LEX = Lexicon.model_validate(EN_LEXICON)
REFUSAL = {"message": "recorded", "missing_inputs": [], "violated_rule_ids": []}


def _refusal(reason: str | None) -> dict[str, Any] | None:
    return None if reason is None else {"reason": reason, **REFUSAL}


# --- compliance_gate (policy judge + algebra) ---------------------------------------------
def recorded_policy(case: dict[str, Any], all_clean: bool = False) -> dict[str, Any]:
    e, inp = case["expected"], case["input"]
    if e["refusal_reason"]:
        return {
            "findings": [],
            "frame_tests": [],
            "injection_suspected": [],
            "refusal": _refusal(e["refusal_reason"]),
        }
    findings, tests = [], []
    for it in inp["items"]:
        for rule in it["rules_to_check"]:
            if not all_clean and rule in e["violation_required"]:
                f, q = "VIOLATION", it["text"][:400]
            elif (
                not all_clean
                and rule not in e["not_violation"]
                and "ALLOWED" not in e["verdict_in"]
            ):
                f, q = "UNCERTAIN", it["text"][:400]
            else:
                f, q = "NO_VIOLATION", None
            findings.append(
                {
                    "item_id": it["item_id"],
                    "rule_id": rule,
                    "finding": f,
                    "quote": q,
                    "rationale": f"recorded {f} for {rule}",
                }
            )
        if it["named_instruments"]:
            v = not all_clean and "FIN-R13" in e["violation_required"]
            tests.append(
                {
                    "item_id": it["item_id"],
                    "past_tense_frame": not v,
                    "teaches_concept": not v,
                    "leaves_expectation": v,
                }
            )
    inj = [i["item_id"] for i in inp["items"]] if e["injection_expected"] else []
    return {"findings": findings, "frame_tests": tests, "injection_suspected": inj, "refusal": None}


def run_policy(case: dict[str, Any], reply: dict[str, Any]) -> tuple[ComplianceVerdict, Any]:
    inp = PolicyInput.model_validate(case["input"])
    check = post_check(inp, PolicyOutput.model_validate(reply))
    lex = config().prefilter_lexicon(case["input"]["language"])
    results = evaluate_policy(inp, check, lex, {})
    return policy_verdict(results), (check, results)


def prefiltered(case: dict[str, Any]) -> dict[str, Any]:
    """The case as the gate builds it (review M5): the REAL pre-filter (configured lexicons,
    merged per item) selects the items and their ``rules_to_check``; an item without a signal
    is not sent. The dataset's own ``rules_to_check`` are not used here."""
    inp = case["input"]
    lex = config().prefilter_lexicon(inp["language"])
    active = frozenset(inp["active_rule_ids"])
    items = []
    for it in inp["items"]:
        claims = [ItemClaim.model_validate(c) for c in it["claims"]]
        rules = select_rules(it["text"], it["named_instruments"], claims, lex, active)
        if rules:
            items.append(it | {"rules_to_check": list(rules)})
    return case | {"input": inp | {"items": items}}


PREFILTER_GAPS = {
    "EDGE-R6-04": "a percentage / money amount with no first- or second-person subject is not a "
    "blueprint 6.2 signal; REQUIRES REVIEW (Phase 1): owner decides whether to widen the rule",
}


@pytest.mark.parametrize("case", CG, ids=case_ids(CG))
def test_compliance_gate_case_through_the_prefilter(case: dict[str, Any]) -> None:
    """End to end as in production: pre-filter -> recorded judge reply -> post-check ->
    algebra. An item the pre-filter drops is never judged, so the verdict comes from what the
    pre-filter sent (nothing sent and no refusal => ALLOWED)."""
    if case["case_id"] in PREFILTER_GAPS:
        pytest.xfail(PREFILTER_GAPS[case["case_id"]])
    e = case["expected"]
    pc = prefiltered(case)
    if not pc["input"]["items"]:
        assert e["refusal_reason"] or "ALLOWED" in e["verdict_in"], "pre-filter dropped it"
        return
    verdict, (check, _) = run_policy(pc, recorded_policy(pc))
    if e["refusal_reason"] is None:
        assert verdict.value in e["verdict_in"]
        found = {k[1] for k, f in check.findings.items() if f.finding == "VIOLATION"}
        sent = {r for i in pc["input"]["items"] for r in i["rules_to_check"]}
        assert set(e["violation_required"]) & sent <= found


@pytest.mark.parametrize("case_id", sorted(PREFILTER_GAPS))
def test_listed_prefilter_gaps_are_real(case_id: str) -> None:
    """A listed gap must still be a gap (remove it from the list once the lexicon covers it)."""
    case = next(c for c in CG if c["case_id"] == case_id)
    pc = prefiltered(case)
    if pc["input"]["items"]:
        verdict, _ = run_policy(pc, recorded_policy(pc))
        assert verdict.value not in case["expected"]["verdict_in"]


def test_prefilter_detects_marathi_hindi_and_hinglish() -> None:
    """The mr / hi lexicons are real words (provisional), not English copies."""
    lex = config().prefilter_lexicon("mr-IN")
    active = frozenset({"FIN-R1", "FIN-R2", "FIN-R3", "FIN-R5", "FIN-R13", "YTG-R7"})
    assert "FIN-R1" in select_rules("हा शेअर आत्ताच खरेदी करा", (), (), lex, active)
    assert "FIN-R1" in select_rules("यह शेयर अभी खरीदो", (), (), lex, active)
    assert "FIN-R1" in select_rules("Ye share abhi kharid lo", (), (), lex, active)
    assert "FIN-R5" in select_rules("आमच्या ग्रुप मध्ये या", (), (), lex, active)
    assert "YTG-R7" in select_rules("चला मुलांनो", (), (), lex, active)
    assert {"FIN-R3", "FIN-R13"} <= set(
        select_rules("निफ्टी उद्या वाढेल", ("निफ्टी",), (), lex, active)
    )
    en_only = config().lexicon("mr-IN")
    assert "buy" not in en_only.imperative_verbs  # not a copy of the English lexicon


@pytest.mark.parametrize("case", CG, ids=case_ids(CG))
def test_compliance_gate_case(case: dict[str, Any]) -> None:
    e = case["expected"]
    verdict, (check, results) = run_policy(case, recorded_policy(case))
    assert verdict.value in e["verdict_in"]  # A4
    violations = {r.rule_id for r in results if r.check_verdict.value == "FAIL"}
    found = {k[1] for k, f in check.findings.items() if f.finding == "VIOLATION"}
    assert set(e["violation_required"]) <= found  # A5
    assert not (set(e["not_violation"]) & found)  # A6
    assert check.refusal_reason == e["refusal_reason"]  # A8
    if e["injection_expected"]:  # A7
        assert check.injection_items
    if "YTG-R7" in found:  # A12
        assert "YTG-R7" not in violations
    assert check.quote_failures == 0


CODE_HELD = [
    c
    for c in CG
    if any(k in (c.get("notes") or "") for k in ("V9", "V6")) or c["case_id"] in ("EDGE-WITHIN",)
]


@pytest.mark.parametrize("case", CODE_HELD, ids=case_ids(CODE_HELD))
def test_judge_never_clears_a_code_flag(case: dict[str, Any]) -> None:
    """An all-NO_VIOLATION judge cannot turn these cases ALLOWED (V6, V9, FIN-R9)."""
    verdict, _ = run_policy(case, recorded_policy(case, all_clean=True))
    assert verdict is not ComplianceVerdict.ALLOWED
    assert verdict.value in case["expected"]["verdict_in"]


def test_judge_findings_are_post_checked() -> None:
    case = next(c for c in CG if c["case_id"] == "AK-02")
    reply = recorded_policy(case)
    for f in reply["findings"]:
        if f["finding"] == "VIOLATION":
            f["quote"] = "words that are not in the item"  # hallucinated quote -> UNCERTAIN
    reply["findings"].append(
        {
            "item_id": "i99",
            "rule_id": "FIN-R1",
            "finding": "NO_VIOLATION",
            "quote": None,
            "rationale": "unknown item",
        }
    )
    reply["findings"].append(
        {
            "item_id": "i01",
            "rule_id": "YTG-R10",
            "finding": "NO_VIOLATION",
            "quote": None,
            "rationale": "rule not sent",
        }
    )
    verdict, (check, _) = run_policy(case, reply)
    assert check.quote_failures >= 1 and check.dropped == 2
    assert verdict is not ComplianceVerdict.ALLOWED  # doubt, never ALLOWED


def test_missing_judge_finding_is_doubt_and_injection_does_not_change_the_verdict() -> None:
    case = next(c for c in CG if c["case_id"] == "AK-01")
    reply = recorded_policy(case)
    reply["findings"] = reply["findings"][1:]  # one (item, rule) pair unanswered
    verdict, _ = run_policy(case, reply)
    assert verdict is ComplianceVerdict.NEEDS_HUMAN_REVIEW
    inj = next(c for c in CG if c["case_id"] == "EDGE-INJ-02")
    v1, _ = run_policy(inj, recorded_policy(inj))
    no_flag = recorded_policy(inj) | {"injection_suspected": []}
    v2, _ = run_policy(inj, no_flag)
    assert v1 is v2 is ComplianceVerdict.ALLOWED


@pytest.mark.unit
def test_p01_monotonic_judge_never_improves_a_verdict() -> None:
    """P-01: for every case and rule, replacing a finding by NO_VIOLATION never makes the
    verdict worse-than-code better; VIOLATION / UNCERTAIN never improve it either."""
    from agent_16_compliance_qa.base import worse_or_equal

    for case in CG:
        if case["expected"]["refusal_reason"]:
            continue
        base, _ = run_policy(case, recorded_policy(case, all_clean=True))
        for finding in ("VIOLATION", "UNCERTAIN"):
            reply = recorded_policy(case, all_clean=True)
            for f in reply["findings"]:
                f["finding"] = finding
                f["quote"] = next(
                    i["text"][:400] for i in case["input"]["items"] if i["item_id"] == f["item_id"]
                )
            stricter, _ = run_policy(case, reply)
            assert worse_or_equal(stricter, base), case["case_id"]


# --- paraphrase ---------------------------------------------------------------------------
_BOOLS = {
    "CLOSE_PARAPHRASE": (True, True, True, True),
    "OWN_WORDS": (False, False, False, False),
    "UNCERTAIN": (True, False, False, False),
}


def recorded_paraphrase(case: dict[str, Any]) -> dict[str, Any]:
    e = case["expected"]
    if e["refusal_reason"]:
        return {"results": [], "injection_suspected": [], "refusal": _refusal(e["refusal_reason"])}
    results = []
    for pid, decision in e["decisions"].items():
        quotation = bool(e["is_quotation"].get(pid))
        st, ex, sq, sc = _BOOLS[decision]
        results.append(
            {
                "pair_id": pid,
                "decision": decision,
                "same_structure": st,
                "same_examples": ex,
                "same_sequence": sq,
                "surface_change_only": sc,
                "is_quotation": quotation,
                "closest_passage_id": "s01",
                "rationale": "recorded",
            }
        )
    pairs = [p["pair_id"] for p in case["input"]["pairs"]]
    return {
        "results": results,
        "injection_suspected": pairs if e["injection_expected"] else [],
        "refusal": None,
    }


def _quotation_approvals(case: dict[str, Any]) -> tuple[dict[str, str], list[QuotationApproval]]:
    hashes = {p["pair_id"]: f"span-{p['pair_id']}" for p in case["input"]["pairs"]}
    approvals = []
    for a in case.get("fixture", {}).get("approvals", []):
        ev = EvidenceFacts.model_validate(evidence_mapping(state=a["evidence_state"]))
        step = StepFacts(
            step_no=1,
            state="APPROVED",
            decided_by_kind="HUMAN",
            membership_active=True,
            holds_required_role=True,
            recorded_by_kind="OPERATOR",
            approval_channel=ApprovalChannel.OWNER_CHAT_OPERATOR,
            evidence=ev,
        )
        state = derive_approval_state(
            ApprovalState(a["state"]), [step], frozenset({ApprovalChannel.OWNER_CHAT_OPERATOR})
        )
        span = hashes[a["pair_id"]] if a["span_hash_matches"] else "span-other"
        if a["kind"] == "COPYRIGHT_DOUBT":
            approvals.append(QuotationApproval(span, state))
    return hashes, approvals


@pytest.mark.parametrize("case", PARA, ids=case_ids(PARA))
def test_paraphrase_case(case: dict[str, Any]) -> None:
    e = case["expected"]
    inp = ParaphraseInput.model_validate(case["input"])
    hashes, approvals = _quotation_approvals(case)
    d = apply_paraphrase(
        inp, ParaphraseOutput.model_validate(recorded_paraphrase(case)), hashes, approvals
    )
    accepted = {e["verdict"]} | ({"BLOCKED"} if case["case_id"] == "EDGE-08" else set())
    assert d.verdict.value in accepted
    if not e["refusal_reason"]:
        assert {p.pair_id: p.decision for p in d.pairs} == e["decisions"]
        assert {p.pair_id for p in d.pairs if p.is_quotation} == {
            k for k, v in e["is_quotation"].items() if v
        }
    assert d.refusal_reason == e["refusal_reason"]
    assert bool(d.injection_pairs) == e["injection_expected"]
    if any(p.verdict is ComplianceVerdict.ALLOWED and p.is_quotation for p in d.pairs):
        assert any(p.approval_applied for p in d.pairs)  # a quotation passes only by approval


def test_paraphrase_code_reapplies_rule_3() -> None:
    case = next(c for c in PARA if c["case_id"] == "AK-02")
    reply = recorded_paraphrase(case)
    reply["results"][0]["surface_change_only"] = True  # booleans say copy, decision says own
    d = apply_paraphrase(
        ParaphraseInput.model_validate(case["input"]),
        ParaphraseOutput.model_validate(reply),
        {},
        [],
    )
    assert d.verdict is ComplianceVerdict.BLOCKED
    reply["results"] = []
    d2 = apply_paraphrase(
        ParaphraseInput.model_validate(case["input"]),
        ParaphraseOutput.model_validate(reply),
        {},
        [],
    )
    assert d2.verdict is ComplianceVerdict.NEEDS_HUMAN_REVIEW


# --- frames -------------------------------------------------------------------------------
def recorded_frames(case: dict[str, Any]) -> dict[str, Any]:
    e = case["expected"]
    if e["refusal_reason"]:
        return {"findings": [], "injection_suspected": [], "refusal": _refusal(e["refusal_reason"])}
    findings = []
    for check, values in e["findings"].items():
        finding = values[0]
        ids = e["frame_ids_required"].get(check, [])
        findings.append(
            {"check_id": check, "finding": finding, "frame_ids": ids, "rationale": "recorded"}
        )
    frames = [f["frame_id"] for f in case["input"]["frames"]]
    return {
        "findings": findings,
        "injection_suspected": frames[:1] if e["injection_expected"] else [],
        "refusal": None,
    }


@pytest.mark.parametrize("case", FRAMES, ids=case_ids(FRAMES))
def test_frames_case(case: dict[str, Any]) -> None:
    e, inp = case["expected"], case["input"]
    out = FramesOutput.model_validate(recorded_frames(case))
    checks = apply_frames(
        inp["checks_requested"],
        inp["sensitive_channel"],
        [f["frame_id"] for f in inp["frames"]],
        out,
        False,
    )
    by_id = {c.check_id: c for c in checks}
    for cid, cv in e["code_verdicts"].items():
        got = by_id[cid]
        allowed = cv.get("check_verdict_in") or [cv["check_verdict"]]
        assert got.verdict.value in allowed
        assert got.blocking is cv["blocking"] is False  # D-12: a vision finding never blocks
        assert (got.compliance_verdict.value if got.compliance_verdict else None) == cv[
            "compliance_verdict"
        ]
        assert set(e["frame_ids_required"].get(cid, [])) <= set(got.frame_ids)
    if e["refusal_reason"]:
        assert all(c.finding == "NOT_EVALUATED" for c in checks)  # never NONE_FOUND (D-11)
        assert all(c.verdict.value == "WARN" for c in checks)
    assert all(c.compliance_verdict is not ComplianceVerdict.BLOCKED for c in checks)


def test_frames_watermark_blocks_only_once_calibrated() -> None:
    case = next(c for c in FRAMES if c["case_id"] == "AK-01")
    inp = case["input"]
    out = FramesOutput.model_validate(recorded_frames(case))
    ids = [f["frame_id"] for f in inp["frames"]]
    cal = apply_frames(inp["checks_requested"], False, ids, out, True)[0]
    assert cal.verdict.value == "FAIL" and cal.blocking
    bad = out.model_copy(
        update={"findings": (out.findings[0].model_copy(update={"frame_ids": ("f77",)}),)}
    )
    assert apply_frames(inp["checks_requested"], False, ids, bad, False)[0].finding == "UNCERTAIN"
    clean_with_ids = out.model_copy(
        update={"findings": (out.findings[0].model_copy(update={"finding": "NONE_FOUND"}),)}
    )
    assert (
        apply_frames(inp["checks_requested"], False, ids, clean_with_ids, False)[0].verdict.value
        == "WARN"
    )


# --- quality judge ------------------------------------------------------------------------
def _crit(case: dict[str, Any]) -> list[Criterion]:
    return [
        Criterion(
            criterion_id=c["criterion_id"],
            dimension=QualityDimension(c["dimension"]),
            kind="LLM_JUDGE",
            max_points=c["max_points"],
        )
        for c in case["input"]["criteria"]
    ]


def _refs(case: dict[str, Any]) -> frozenset[str]:
    inp = case["input"]
    refs = {s["segment_id"] for s in inp.get("script", [])}
    refs |= {f["frame_id"] for f in inp.get("frames", [])}
    return frozenset(refs | {"title"} | {f"thumbnail_{i + 1}" for i in range(3)})


def recorded_quality(case: dict[str, Any]) -> dict[str, Any]:
    e, inp = case["expected"], case["input"]
    if e["refusal_reason"]:
        return {
            "group_id": inp["group_id"],
            "scores": [],
            "check_results": [],
            "injection_suspected": [],
            "refusal": _refusal(e["refusal_reason"]),
        }
    ref = sorted(_refs(case))[0]
    scores = [
        {
            "criterion_id": c["criterion_id"],
            "points": e["bands"][c["criterion_id"]][0],
            "max_points": c["max_points"],
            "evidence_refs": [ref],
            "why_not_higher": "x",
        }
        for c in inp["criteria"]
    ]
    checks = [
        {
            "check_id": cid,
            "elements": [{"element_id": k, "score": v[0]} for k, v in bands.items()],
            "absent_content_elements": e.get("absent_content", {}).get(cid, []),
            "rationale": "recorded",
        }
        for cid, bands in e["check_bands"].items()
    ]
    return {
        "group_id": inp["group_id"],
        "scores": scores,
        "check_results": checks,
        "injection_suspected": ["s01"] if e["injection_expected"] else [],
        "refusal": None,
    }


@pytest.mark.parametrize("case", QS, ids=case_ids(QS))
def test_quality_case(case: dict[str, Any]) -> None:
    e, inp = case["expected"], case["input"]
    requested = tuple(inp.get("requested_checks") or ())
    expected_elements = {cid: frozenset(b) for cid, b in e["check_bands"].items()}
    res = apply_quality(
        _crit(case),
        QualityOutput.model_validate(recorded_quality(case)),
        _refs(case),
        requested,
        expected_elements,
    )
    for s in res.scores:
        lo, hi = e["bands"].get(s.criterion_id, (0, 0))
        assert lo <= s.earned <= hi
    assert res.refusal_reason == e["refusal_reason"]
    for row in res.checks:
        bands = e["check_bands"].get(row.check_id)
        if not bands:
            assert row.verdict in ("SKIPPED", "WARN")
            continue
        for el, score in row.elements:
            assert bands[el][0] <= score <= bands[el][1]
        assert row.verdict == ("WARN" if any(s == 0 for _, s in row.elements) else "PASS")
    assert bool(res.injection) == e["injection_expected"]


def test_quality_post_checks() -> None:
    from amw_core.errors import OutputSchemaInvalidError

    case = next(c for c in QS if c["case_id"] == "AK-01")
    reply = recorded_quality(case)
    reply["scores"][0]["points"] = 99
    with pytest.raises(OutputSchemaInvalidError):
        apply_quality(_crit(case), QualityOutput.model_validate(reply), _refs(case), (), {})
    reply = recorded_quality(case)
    reply["scores"][0]["evidence_refs"] = ["s99"]  # not in the input
    res = apply_quality(_crit(case), QualityOutput.model_validate(reply), _refs(case), (), {})
    assert res.scores[0].earned == 0 and res.scores[0].finding
    res = apply_quality(_crit(case), None, _refs(case), ("edit.promise_alignment",), {})
    assert all(s.earned == 0 for s in res.scores) and res.checks[0].verdict == "SKIPPED"


# --- the packs through the amw_evals runner (schema + refusal assertions) -------------------
@pytest.mark.parametrize(
    ("dataset", "rows", "recorder"),
    [
        ("compliance_gate", CG, recorded_policy),
        ("compliance_gate_frames", FRAMES, recorded_frames),
        ("quality_score", QS, recorded_quality),
    ],
)
def test_packs_through_the_amw_evals_runner(
    tmp_path: Path, dataset: str, rows: list[dict[str, Any]], recorder: Any
) -> None:
    adapter = FakeAdapter({c["case_id"]: LlmResponse(output=recorder(c)) for c in rows})
    records, summary = run_eval(
        REPO / "docs/v4", EVALS / dataset, adapter, {}, tmp_path / "r.jsonl"
    )
    failed = [r["case_id"] for r in records if not r["passed"]]
    assert summary.total == len(rows) and not failed, failed
    assert summary.cost_micros == 0 and len(adapter.calls) == len(rows)
    assert all(
        json.loads(line)["figure_kind"] == "ESTIMATE"
        for line in (tmp_path / "r.jsonl").read_text().splitlines()
    )
