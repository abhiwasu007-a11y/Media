# ruff: noqa: PT018
"""ComplianceGate end to end on a fixture video with the JudgeClient over a scripted LLM:
code checks first, judge only on flagged items, a judge cannot clear a code flag, gate results
(``gate: true``, ``remedy_stage_id``), payload contract, failure injection (07 section 12)."""

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

import jsonschema
import pytest

from agent_16_compliance_qa.checks import rules as R  # noqa: N812
from agent_16_compliance_qa.gate import (
    ComplianceGate,
    GateInputs,
    Routing,
    SourceItem,
    gate_payload,
    validation_results,
)
from agent_16_compliance_qa.judge.client import CallMeter, CallScope, JudgeClient, system_prompt
from agent_16_compliance_qa.judge.models import (
    FramesOutput,
    ItemClaim,
    ParaphraseOutput,
    PolicyOutput,
)
from agent_16_compliance_qa.nearcopy import ChunkText, check_near_copy
from agent_16_compliance_qa.output import build_task_output, integrity, next_action_for
from agent_16_compliance_qa.packs import PackRow, load_packs
from amw_core import ids
from amw_core.contracts.validation import validate_task_output
from amw_core.enums import ComplianceVerdict, PresenterKind, RulePackStatus
from amw_core.errors import (
    BudgetExhaustedError,
    CircuitOpenError,
    ConfigInvalidError,
    CrossTenantRefError,
    InputInvalidError,
    InsufficientInputError,
    InvalidJsonError,
    LoopCapExceededError,
    OutputSchemaInvalidError,
)
from amw_core.interfaces import TenantContext
from amw_core.testing.memory import MemoryTransaction
from tests.agents.agent_16_compliance_qa.support import (
    PROMPTS,
    Breaker,
    Budget,
    FixedClock,
    Ledger,
    ScriptedLlm,
    blueprint_schema,
    config,
)

YTG = ["YTG-R1", "YTG-R2", "YTG-R3", "YTG-R5", "YTG-R6", "YTG-R7", "YTG-R9"]
FIN = [
    "FIN-R1",
    "FIN-R2",
    "FIN-R3",
    "FIN-R4",
    "FIN-R5",
    "FIN-R6",
    "FIN-R7",
    "FIN-R8",
    "FIN-R9",
    "FIN-R10",
    "FIN-R11",
    "FIN-R12",
    "FIN-R13",
]
ROUTING = Routing(
    script_stage_id="s05_script", assets_stage_id="s08_assets", thumbnails_stage_id="s11_thumbs"
)


def pack(
    key: str, rules: list[str], status: RulePackStatus = RulePackStatus.ACTIVE
) -> tuple[PackRow, bytes]:
    body = json.dumps({"key": key, "rules": rules}).encode()
    row = PackRow(
        rule_pack_id=ids.new_id(ids.Prefix.RULE_PACK),
        key=key,
        version=1,
        status=status,
        rules_sha256=hashlib.sha256(body).hexdigest(),
        rules=dict.fromkeys(rules, "BLOCKING"),
    )
    return row, body


def subject() -> dict[str, str]:
    """A schema-valid gate subject (8.2): the payload is validated by its model on emission."""
    return {
        "render_id": ids.new_id(ids.Prefix.RENDER),
        "render_sha256": "a" * 64,
        "script_id": ids.new_id(ids.Prefix.SCRIPT),
        "script_sha256": "b" * 64,
    }


def packs(finance: bool = True) -> Any:
    yt, ybody = pack("rp.youtube_general", YTG)
    rows, files = [yt], {yt.rule_pack_id: ybody}
    if finance:
        fin, fbody = pack("rp.finance_sebi_in", FIN)
        rows.append(fin)
        files[fin.rule_pack_id] = fbody
    return load_packs(rows[:1], rows[1:], files)


def clean_inputs(**over: Any) -> GateInputs:
    base: dict[str, Any] = {
        "channel_category": "finance",
        "language": "en-IN",
        "sensitive_channel": True,
        "routing": ROUTING,
        "items": [
            SourceItem(
                ref="seg_1",
                surface="SCRIPT_SEGMENT",
                text="A stop order turns into a market order when touched.",
                claims=(
                    ItemClaim(
                        claim_type="DEFINITION", time_reference_kind="TIMELESS", rule_flags=()
                    ),
                ),
            ),
            SourceItem(
                ref="seg_2",
                surface="SCRIPT_SEGMENT",
                text="On this past NIFTY chart the gap was followed by a fall.",
                named_instruments=("NIFTY",),
                claims=(
                    ItemClaim(
                        claim_type="HISTORICAL_MARKET",
                        time_reference_kind="HISTORICAL",
                        rule_flags=(),
                    ),
                ),
                chart={
                    "chart_kind": "REAL_HISTORICAL",
                    "instrument": "NIFTY",
                    "data_age_vs_lag": "OLDER_THAN_LAG",
                },
            ),
        ],
        "charts": [R.ChartAge(chart_id="c1", age_days=60)],
        "text_prices": [],
        "disclaimer_spoken": True,
        "disclaimer_onscreen": True,
        "disclaimer_template_version": "v1",
        "metadata_present": False,
        "description_hash_matches": None,
        "method_segments": [],
        "method_label_overlay": False,
        "production_type_key": "CHANNEL_LONG_FORM",
        "live_format": "STANDARD",
        "metadata_terms": None,
        "presenter_kind": PresenterKind.OWNER_VOICE,
        "voice_known": True,
        "render_person_assets": [],
        "thumbnail_person_assets": [],
        "licensed_assets": [
            R.LicensedAsset(
                asset_ref="a1",
                source_kind="CODE_GENERATED",
                has_ledger_row=True,
                licence_state="ACTIVE",
                covers_monetized_youtube=True,
                third_party_permission="NOT_APPLICABLE",
            )
        ],
        "audience_kind": "GENERAL",
        "disclosure_assets": [
            R.DisclosureAsset(
                asset_ref="a1",
                tier="C_CODE_MOTION",
                is_realistic_synthetic=False,
                realistic_person=False,
            )
        ],
        "realism_shots": [],
        "voice_kind": "OWNER_VOICE",
        "frame_ids": ("f01", "f02"),
        "frames_payload": {"checks_requested": []},
        "uniqueness_verdict": ComplianceVerdict.ALLOWED,
        "evaluation_date": date(2026, 1, 31),
    }
    return GateInputs.model_validate(base | over)


def policy_reply(batch: Any, finding: str = "NO_VIOLATION") -> PolicyOutput:
    findings, tests = [], []
    for it in batch.items:
        for rule in it.rules_to_check:
            findings.append(
                {
                    "item_id": it.item_id,
                    "rule_id": rule,
                    "finding": finding,
                    "quote": it.text if finding != "NO_VIOLATION" else None,
                    "rationale": "x",
                }
            )
        if it.named_instruments:
            tests.append(
                {
                    "item_id": it.item_id,
                    "past_tense_frame": True,
                    "teaches_concept": True,
                    "leaves_expectation": False,
                }
            )
    return PolicyOutput.model_validate(
        {"findings": findings, "frame_tests": tests, "injection_suspected": [], "refusal": None}
    )


def frames_clean(_: Any) -> FramesOutput:
    return FramesOutput.model_validate(
        {
            "findings": [
                {
                    "check_id": "qc.watermark.visual",
                    "finding": "NONE_FOUND",
                    "frame_ids": [],
                    "rationale": "-",
                },
                {
                    "check_id": "qc.visual.no_synthetic_presenter",
                    "finding": "NONE_FOUND",
                    "frame_ids": [],
                    "rationale": "-",
                },
            ],
            "injection_suspected": [],
            "refusal": None,
        }
    )


def no_para(_: Any) -> ParaphraseOutput:
    raise AssertionError("no paraphrase candidates in this fixture")


class Calls:
    def __init__(self, reply: Any = policy_reply) -> None:
        self.batches: list[Any] = []
        self._reply = reply

    def __call__(self, batch: Any) -> PolicyOutput:
        self.batches.append(batch)
        return self._reply(batch)  # type: ignore[no-any-return]


def gate(policy: Any = None, finance: bool = True, **cfg: Any) -> ComplianceGate:
    return ComplianceGate(config(**cfg), packs(finance), policy or Calls(), no_para, frames_clean)


def test_clean_video_is_allowed_and_only_flagged_items_reach_the_judge() -> None:
    calls = Calls()
    d = gate(calls).evaluate(clean_inputs())
    assert d.verdict is ComplianceVerdict.ALLOWED, [
        r for r in d.rules if r.compliance_verdict is not ComplianceVerdict.ALLOWED
    ]
    sent = [i.text for b in calls.batches for i in b.items]
    assert sent == [
        "On this past NIFTY chart the gap was followed by a fall."
    ]  # seg_1 has no signal
    assert d.earliest_compliant_publish_date == date(2026, 1, 1)  # 60 days old, lag 30
    results = validation_results(d, ROUTING, packs())
    assert results and all(r.gate for r in results)
    payload = gate_payload(
        d,
        {
            "render_id": ids.new_id(ids.Prefix.RENDER),
            "render_sha256": "a" * 64,
            "script_id": ids.new_id(ids.Prefix.SCRIPT),
            "script_sha256": "b" * 64,
        },
        ROUTING,
        packs(),
        [ids.new_id(ids.Prefix.COMPLIANCE_VERDICT)],
        {"prompt_ids": ["agent_16/compliance_gate.v1"]},
    )
    schema = blueprint_schema("### 8.2 `agent_16.compliance_gate.output`")
    jsonschema.Draft202012Validator(schema).validate(payload)
    out = build_task_output(
        payload_schema="agent_16.compliance_gate.output",
        data=payload,
        results=[*results, integrity("schema", True, "payload valid")],
        blob=None,
        usage=__import__("agent_16_compliance_qa.output", fromlist=["Usage"]).Usage(),
        now=datetime(2026, 1, 31, tzinfo=UTC),
        currency="USD",
        quality_score=None,
        verdict=d.verdict,
        downstream=None,
    )
    validate_task_output(out.model_dump(mode="json", exclude_none=False) | {})


def test_code_flags_survive_an_all_clean_judge() -> None:
    within = clean_inputs(charts=[R.ChartAge(chart_id="c1", age_days=12)])
    d = gate().evaluate(within)
    assert d.verdict is ComplianceVerdict.BLOCKED
    r9 = next(r for r in validation_results(d, ROUTING, packs()) if r.rule_id == "FIN-R9")
    assert r9.blocking and r9.remedy_stage_id == "s08_assets"
    assert d.earliest_compliant_publish_date == date(2026, 2, 18)
    nodisc = gate().evaluate(clean_inputs(disclaimer_onscreen=False))
    r10 = next(r for r in validation_results(nodisc, ROUTING, packs()) if r.rule_id == "FIN-R10")
    assert nodisc.verdict is ComplianceVerdict.BLOCKED and r10.remedy_stage_id == "s05_script"
    persona = gate().evaluate(clean_inputs(presenter_kind=PresenterKind.SYNTHETIC_PERSONA))
    assert persona.verdict is ComplianceVerdict.BLOCKED
    flagged = clean_inputs(
        items=[
            SourceItem(
                ref="seg_9",
                surface="SCRIPT_SEGMENT",
                text="A sell signal is when the line crosses zero.",
                claims=(
                    ItemClaim(
                        claim_type="DEFINITION",
                        time_reference_kind="TIMELESS",
                        rule_flags=("FIN-R1",),
                    ),
                ),
            )
        ]
    )
    assert gate().evaluate(flagged).verdict is ComplianceVerdict.NEEDS_HUMAN_REVIEW  # V6
    thumb = clean_inputs(
        thumbnail_person_assets=[R.PersonAsset(shows_person=True, is_realistic_synthetic=True)]
    )
    r2 = next(
        r
        for r in validation_results(gate().evaluate(thumb), ROUTING, packs())
        if r.rule_id == "YTG-R2"
    )
    assert r2.remedy_stage_id == "s11_thumbs"
    kids = gate().evaluate(clean_inputs(audience_kind=None))
    assert kids.verdict is ComplianceVerdict.NEEDS_HUMAN_REVIEW  # V11a


def test_judge_violation_blocks_and_nhr_raises_review_requests() -> None:
    d = gate(Calls(lambda b: policy_reply(b, "VIOLATION"))).evaluate(clean_inputs())
    assert d.verdict is ComplianceVerdict.BLOCKED
    u = gate(Calls(lambda b: policy_reply(b, "UNCERTAIN"))).evaluate(clean_inputs())
    assert u.verdict is ComplianceVerdict.NEEDS_HUMAN_REVIEW
    from agent_16_compliance_qa.gate import review_requests

    reqs = review_requests(u)
    assert reqs and all(r["approval_kind"] == "SENSITIVE_CLAIM" for r in reqs)
    lic = gate().evaluate(
        clean_inputs(
            licensed_assets=[
                R.LicensedAsset(
                    asset_ref="a9",
                    source_kind="STOCK_LICENSED",
                    has_ledger_row=True,
                    licence_state="ACTIVE",
                    covers_monetized_youtube=None,
                    third_party_permission="NOT_APPLICABLE",
                )
            ]
        )
    )
    assert {
        "rule_id": "YTG-R6",
        "approval_kind": "COPYRIGHT_DOUBT",
        "evidence_ref": "items:a9",
    } in review_requests(lic)
    assert next_action_for(u.verdict, []).type.value == "ESCALATE"


def test_presenter_frame_finding_never_blocks_alone() -> None:
    def presenter(_: Any) -> FramesOutput:
        return FramesOutput.model_validate(
            {
                "findings": [
                    {
                        "check_id": "qc.visual.no_synthetic_presenter",
                        "finding": "PRESENTER_PRESENT",
                        "frame_ids": ["f01"],
                        "rationale": "-",
                    }
                ],
                "injection_suspected": [],
                "refusal": None,
            }
        )

    g = ComplianceGate(config(), packs(), Calls(), no_para, presenter)
    d = g.evaluate(clean_inputs())
    assert d.verdict is ComplianceVerdict.NEEDS_HUMAN_REVIEW
    wm = next(f for f in d.frame_checks if f.check_id == "qc.watermark.visual")
    assert wm.finding == "NOT_EVALUATED" and wm.verdict.value == "WARN"  # never NONE_FOUND


def test_refusals_map_to_typed_errors() -> None:
    def refusal(reason: str) -> Any:
        return lambda b: PolicyOutput.model_validate(
            {
                "findings": [],
                "frame_tests": [],
                "injection_suspected": [],
                "refusal": {
                    "reason": reason,
                    "message": "x",
                    "missing_inputs": [],
                    "violated_rule_ids": [],
                },
            }
        )

    with pytest.raises(InsufficientInputError):
        gate(Calls(refusal("INSUFFICIENT_INPUT"))).evaluate(clean_inputs())
    with pytest.raises(InputInvalidError):
        gate(Calls(refusal("CONFLICTING_INSTRUCTIONS"))).evaluate(clean_inputs())
    unsafe = gate(Calls(refusal("UNSAFE_CONTENT"))).evaluate(clean_inputs())
    assert unsafe.verdict is ComplianceVerdict.NEEDS_HUMAN_REVIEW


def test_pack_loader_refuses_draft_and_hash_mismatch() -> None:
    yt, body = pack("rp.youtube_general", YTG)
    draft, dbody = pack("rp.finance_sebi_in", FIN, RulePackStatus.DRAFT)
    with pytest.raises(ConfigInvalidError):  # FI-01 hash mismatch
        load_packs([yt], [], {yt.rule_pack_id: body + b" "})
    with pytest.raises(ConfigInvalidError):
        load_packs([yt], [draft], {yt.rule_pack_id: body, draft.rule_pack_id: dbody})
    with pytest.raises(ConfigInvalidError):
        load_packs([], [], {})
    loaded = load_packs([yt], [yt], {yt.rule_pack_id: body})  # union, no duplicate
    assert len(loaded.packs) == 1 and loaded.pack_of("YTG-R2") is not None
    with pytest.raises(ConfigInvalidError):
        loaded.severity("FIN-R1")


# --- JudgeClient: budget, cap, breaker, parse retry, idempotency (FI-04...FI-08) ------------
def client(
    texts: list[str],
    max_calls: int = 4,
    max_cost: int = 1000,
    breaker: Breaker | None = None,
    budget: Budget | None = None,
) -> tuple[JudgeClient, ScriptedLlm, Ledger]:
    llm, rec = ScriptedLlm(texts), Ledger()
    cfg = config().step("llm_policy")
    tx = MemoryTransaction(TenantContext(ids.ORG.new(), ids.ActorRef("agent_16")))
    jc = JudgeClient(
        llm=llm,
        step=cfg,
        meter=CallMeter(max_calls=max_calls, max_cost_micros=max_cost, currency="USD"),
        budget=budget or Budget(),
        costs=rec,
        breaker=breaker or Breaker(),
        clock=FixedClock(datetime(2026, 1, 31, tzinfo=UTC)),
        scope=CallScope(tx, ids.JOB.new(), ids.TASK.new(), ids.ATTEMPT.new()),
        language="en-IN",
    )
    return jc, llm, rec


OK = json.dumps({"findings": [], "frame_tests": [], "injection_suspected": [], "refusal": None})


def test_judge_client_retries_once_then_raises() -> None:
    jc, llm, rec = client(["not json", OK])
    assert jc.judge("sys", {"a": 1}, PolicyOutput, "policy.b01").findings == ()
    assert len(llm.requests) == 2 and len(rec.rows) == 2 and len(set(llm.keys)) == 2
    assert "not valid JSON" in llm.requests[1].messages[0].content
    jc, _, _ = client(["not json", "still not json"])
    with pytest.raises(InvalidJsonError):  # FI-05: twice invalid -> DLQ by the worker
        jc.judge("sys", {}, PolicyOutput, "policy.b01")
    jc, _, _ = client(['{"findings": 1}', '{"findings": 2}'])
    with pytest.raises(OutputSchemaInvalidError):
        jc.judge("sys", {}, PolicyOutput, "policy.b01")


def test_judge_client_budget_cap_and_breaker() -> None:
    jc, llm, _ = client([OK], max_cost=50)  # worst case per call is 100 micros
    with pytest.raises(BudgetExhaustedError):  # FI-07
        jc.judge("sys", {}, PolicyOutput, "policy.b01")
    assert llm.requests == []
    jc, _, _ = client([OK, OK], max_calls=1)
    jc.judge("sys", {}, PolicyOutput, "policy.b01")
    with pytest.raises(LoopCapExceededError):  # FI-08
        jc.judge("sys", {}, PolicyOutput, "policy.b02")

    jc, llm, _ = client([OK], breaker=Breaker(open_=True))
    with pytest.raises(CircuitOpenError):  # FI-04 breaker: no attempt
        jc.judge("sys", {}, PolicyOutput, "policy.b01")
    assert llm.requests == []
    jc, llm, _ = client([OK], budget=Budget(gate_open=False))
    with pytest.raises(BudgetExhaustedError):  # 09 section 8: no PROVIDER budget, no call
        jc.judge("sys", {}, PolicyOutput, "policy.b01")
    assert llm.requests == []
    jc, llm, _ = client([OK], budget=Budget(remaining=10))
    with pytest.raises(BudgetExhaustedError):  # E2: the reservation does not cover the call
        jc.judge("sys", {}, PolicyOutput, "policy.b01")
    assert llm.requests == []


def test_judge_client_writes_one_ledger_row_per_call_and_runs_e3() -> None:
    budget = Budget()
    jc, _llm, rec = client(["not json", OK], budget=budget)
    jc.judge("sys", {}, PolicyOutput, "policy.b01")
    assert len(rec.entries) == 2 == len(budget.after) == len(budget.checks)
    assert all(e.entry.task_id and e.entry.attempt_id for e in rec.entries.values())


def test_call_meter_takes_the_tightest_cap_and_zero_without_steps() -> None:
    from amw_core.contracts.common import ResourceBudget

    step = config().step("llm_policy")
    rb = ResourceBudget(max_cost_micros=50, currency="USD", max_wall_ms=1000, max_llm_calls=2)
    m = CallMeter.for_task([step], 16, rb)
    assert m.max_calls == min(2, step.max_calls) and m.max_cost_micros == min(
        50, step.max_cost_micros
    )
    assert CallMeter.for_task([], 16, rb).max_calls == 0
    unlimited = ResourceBudget(max_cost_micros=10**9, currency="USD", max_wall_ms=1000)
    assert CallMeter.for_task([step], 1, unlimited).max_calls == 1


def test_gate_enforces_max_llm_calls_with_any_judge() -> None:
    """Review M3: the gate's own cap holds even when the judge callable has none."""
    calls = Calls()
    items = [
        SourceItem(ref=f"x{i}", surface="SCRIPT_SEGMENT", text="Buy this stock now")
        for i in range(3)
    ]
    cfg = config(
        **{"compliance.gate.max_items_per_judge_call": 1, "compliance.gate.max_llm_calls": 2}
    )
    g = ComplianceGate(cfg, packs(), calls, no_para, frames_clean)
    with pytest.raises(LoopCapExceededError):
        g.evaluate(clean_inputs(items=items))
    assert len(calls.batches) == 2


def test_system_prompt_holds_no_tenant_data_and_model_comes_from_config() -> None:
    text = (PROMPTS / "compliance_gate.v1.md").read_text(encoding="utf-8")
    sys = system_prompt(text, {"rp.youtube_general": "PACK-TEXT"})
    assert sys.startswith("## Role") and "## A. Input payload schema" not in sys
    assert "PACK-TEXT" in sys
    org = ids.ORG.new()
    jc, llm, _ = client([OK])
    jc.judge(sys, {"items": []}, PolicyOutput, "policy.b01")
    assert org not in llm.requests[0].system and llm.requests[0].model == "test-model-from-config"


def test_near_copy_stays_in_the_tenant_and_flags_above_threshold() -> None:
    org = ids.ORG.new()
    tx = MemoryTransaction(TenantContext(org, ids.ActorRef("agent_16")))

    class Reader:
        def read(self, tx: Any, chunk_id: str) -> ChunkText:
            other = chunk_id == "k_other"
            return ChunkText(
                chunk_id=chunk_id,
                org_id=ids.ORG.new() if other else org,
                collection_id="col1",
                text="a stop order becomes a market order when the price is reached",
            )

    s = [("seg_1", "a stop order becomes a market order when the price is reached", ["k1"])]
    res = check_near_copy(tx, s, Reader(), "col1", 3, 0.5, None)
    assert res[0].exceeds_threshold and res[0].overlap_ratio == 1.0
    assert check_near_copy(tx, s, Reader(), "col1", None, None, None)[0].candidate
    with pytest.raises(CrossTenantRefError):  # S-05
        check_near_copy(tx, [("seg_1", "x", ["k_other"])], Reader(), "col1", 3, None, None)
    with pytest.raises(CrossTenantRefError):
        check_near_copy(tx, s, Reader(), "col_other_channel", 3, None, None)
    near = clean_inputs(near_copy=res)
    assert gate().evaluate(near).verdict is ComplianceVerdict.NEEDS_HUMAN_REVIEW


def test_prefilter_signals_select_rules_and_never_clear() -> None:
    from agent_16_compliance_qa.config import Lexicon
    from agent_16_compliance_qa.prefilter import contains_any, quote_verified, select_rules
    from tests.agents.agent_16_compliance_qa.support import EN_LEXICON

    lex = Lexicon.model_validate(EN_LEXICON)
    active = frozenset(YTG + FIN)

    def sel(text: str, inst: tuple[str, ...] = (), claims: tuple[ItemClaim, ...] = ()) -> set[str]:
        return set(select_rules(text, inst, claims, lex, active))

    assert sel("A candle has a body.") == set()
    assert {"FIN-R3", "FIN-R13"} <= sel("NIFTY will rise again", ("NIFTY",))
    assert "FIN-R1" in sel("Buy this now")
    assert "FIN-R2" in sel("the target is 24000")
    assert {"FIN-R6", "FIN-R7"} <= sel("I made 40% last month")
    assert {"FIN-R5", "FIN-R8"} <= sel("use my code at https://x.example/?ref=1")
    assert "FIN-R5" in sel("join our daily calls group")
    assert "YTG-R2" in sel("I am Ava, your host")
    assert "YTG-R7" in sel("hello little friends, a nursery song")
    rec = ItemClaim(
        claim_type="RECOMMENDATION", time_reference_kind="CURRENT", rule_flags=("FIN-R8",)
    )
    assert {"FIN-R1", "FIN-R8"} <= sel("neutral words", claims=(rec,))
    assert "FIN-R1" not in set(select_rules("Buy this now", (), (), lex, frozenset(YTG)))
    assert contains_any("मंजूर आहे", ["मंजूर"]) and not contains_any("x", ["", "y"])
    assert quote_verified("abc", "xabcx") and not quote_verified(None, "abc")


def _silent(_: Any) -> PolicyOutput:
    return PolicyOutput(findings=(), frame_tests=(), injection_suspected=(), refusal=None)


EVASIONS = [
    "B\u200buy this stock now",  # zero-width space
    "\uff42\uff55\uff59 this stock now",  # full-width
    "bu\u00ady this stock now",  # soft hyphen
    "bu\u0443 this stock now",  # Cyrillic look-alike y
    "\U0001d41b\U0001d42e\U0001d432 this stock now",  # mathematical bold
    "B\u200du\u2060y this stock now",  # zero-width joiner + word joiner
    "Join our gr\u200boup for daily c\u200balls",
    "\ufeffSELL this stock now",
    "b-u-y this stock now",  # separator-split (re-review m1)
    "b.u.y this stock now",
    "b u y this stock now",
    "B_U_Y this stock now",
    "join our g-r-o-u-p today",
    *(
        pytest.param(
            text,
            marks=pytest.mark.xfail(
                strict=True,
                reason="core_need CCR-110: amw_core.text_normalise does not fold this look-alike "
                "(CCR-105 forbids a private fold)",
            ),
        )
        for text in (
            "b\u057dy this stock now",  # Armenian seh (u)
            "b\u057ey this stock now",  # Armenian vo (look-alike of u)
            "bu\u13a9 this stock now",  # Cherokee yu (look-alike of Y)
        )
    ),
]


@pytest.mark.parametrize("text", EVASIONS)
def test_prefilter_evasions_reach_the_judge_and_a_silent_judge_never_allows(text: str) -> None:
    """Review B2: with a silent judge (no finding = doubt) every evasion still reaches the judge
    and the gate verdict is NEEDS_HUMAN_REVIEW, never ALLOWED."""
    calls = Calls(_silent)
    item = SourceItem(ref="x1", surface="SCRIPT_SEGMENT", text=text)
    d = gate(calls).evaluate(clean_inputs(items=[item]))
    assert any(i.text == text for b in calls.batches for i in b.items)
    assert d.verdict is not ComplianceVerdict.ALLOWED


def test_devanagari_digits_and_nukta_are_matched() -> None:
    from agent_16_compliance_qa.prefilter import select_rules
    from amw_core.text_normalise import normalise_for_matching

    def norm(text: str) -> str:
        return normalise_for_matching(text).text

    assert norm("१२३") == "123" and norm("क़") == norm("क") and norm("सँ") == norm("सं")
    assert norm(norm("\uff42\u200b\uff55y")) == norm("\uff42\u200b\uff55y") == "buy"
    lex = config().prefilter_lexicon("mr-IN")
    rules = select_rules("मी १८% कमावले", (), (), lex, frozenset({"FIN-R6", "FIN-R7"}))
    assert set(rules) == {"FIN-R6", "FIN-R7"}
    assert "FIN-R2" in select_rules(
        "NIFTY टार्गेट २४,५००", ("NIFTY",), (), lex, frozenset({"FIN-R2"})
    )


def test_uniqueness_masked_identity_ignores_zero_width_characters() -> None:
    from agent_16_compliance_qa.uniqueness import Segment, masked_identical

    template = [Segment(section_role="HOOK", text="Today we learn {topic} in five steps.")]
    script = [Segment(section_role="HOOK", text="To\u200bday we le\u00adarn gaps in five steps.")]
    assert masked_identical(script, template)


@pytest.mark.parametrize(
    "verdict", [ComplianceVerdict.BLOCKED, ComplianceVerdict.NEEDS_HUMAN_REVIEW]
)
def test_uniqueness_verdict_is_a_gate_row_and_blocked_never_passes(
    verdict: ComplianceVerdict,
) -> None:
    """Review M1: the algebra's verdict, ``gate_verdict``, the gate results and next_action
    agree."""
    from agent_16_compliance_qa.gate import review_requests

    d = gate().evaluate(clean_inputs(uniqueness_verdict=verdict))
    assert d.verdict is verdict
    vr = validation_results(d, ROUTING, packs())
    payload = gate_payload(d, subject(), ROUTING, packs(), [], {})
    na = next_action_for(d.verdict, vr)
    if verdict is ComplianceVerdict.BLOCKED:
        assert payload["gate_verdict"] == "FAILED"
        blocking = [r for r in vr if r.blocking]
        assert blocking and all(r.gate and r.remedy_stage_id for r in blocking)
        assert na.reason.startswith("gate FAILED") and "ytg.r1" in na.reason
    else:
        assert payload["gate_verdict"] == "PASSED" and na.type.value == "ESCALATE"
        assert any(r["rule_id"] == "YTG-R1" for r in review_requests(d))


def test_warning_severity_fail_is_warn_and_never_blocks() -> None:
    """V8: a deterministic failure of a WARNING-severity rule is WARN; the verdict is not
    BLOCKED while the results say nothing blocks."""
    row, body = pack("rp.finance_sebi_in", FIN)
    row = row.model_copy(update={"rules": dict.fromkeys(FIN, "BLOCKING") | {"FIN-R9": "WARNING"}})
    yt, ybody = pack("rp.youtube_general", YTG)
    p = load_packs([yt], [row], {yt.rule_pack_id: ybody, row.rule_pack_id: body})
    g = ComplianceGate(config(), p, Calls(), no_para, frames_clean)
    d = g.evaluate(clean_inputs(charts=[R.ChartAge(chart_id="c1", age_days=12)]))
    vr = validation_results(d, ROUTING, p)
    r9 = next(r for r in vr if r.rule_id == "FIN-R9")
    assert r9.verdict.value == "WARN" and not r9.blocking
    assert d.verdict is not ComplianceVerdict.BLOCKED
    assert gate_payload(d, subject(), ROUTING, p, [], {})["gate_verdict"] == "PASSED"


def test_blocked_verdict_without_a_blocking_row_fails_closed() -> None:
    from agent_16_compliance_qa.checks import failed

    d = gate().evaluate(clean_inputs())
    forged = d.model_copy(update={"verdict": ComplianceVerdict.BLOCKED})
    vr = validation_results(forged, ROUTING, packs())
    assert any(r.check_id == "a16.gate.verdict" and r.blocking for r in vr)
    assert next_action_for(ComplianceVerdict.BLOCKED, []).reason.startswith("gate FAILED")
    assert failed("FIN-R9", "x").compliance_verdict is ComplianceVerdict.BLOCKED


def _frame_reply(*, duplicate: bool) -> Any:
    def reply(batch: Any) -> PolicyOutput:
        out = policy_reply(batch)
        bad = tuple(t.model_copy(update={"leaves_expectation": True}) for t in out.frame_tests)
        return out.model_copy(
            update={"frame_tests": (*bad, *out.frame_tests) if duplicate else bad}
        )

    return reply


@pytest.mark.parametrize("duplicate", [False, True])
def test_a_failing_frame_test_is_never_overridden_by_a_later_pass(duplicate: bool) -> None:
    """Review M2 (P-01): failing V7 frame test then a passing duplicate for the same item."""
    d = gate(Calls(_frame_reply(duplicate=duplicate))).evaluate(clean_inputs())
    assert d.verdict is ComplianceVerdict.BLOCKED
    from agent_16_compliance_qa.algebra import post_check
    from agent_16_compliance_qa.judge.models import PolicyInput

    calls = Calls(_frame_reply(duplicate=True))
    gate(calls).evaluate(clean_inputs())
    b = calls.batches[0]
    pc = post_check(PolicyInput.model_validate(b.model_dump()), _frame_reply(duplicate=True)(b))
    assert all(t.leaves_expectation for t in pc.frame_tests.values())


def test_split_word_join_leaves_ordinary_text_alone() -> None:
    from agent_16_compliance_qa.prefilter import collapse_split_words, select_rules
    from tests.agents.agent_16_compliance_qa.test_llm_evals import CG

    ordinary = [
        "a candle has a body.",
        "I am a trader and I read a b test",
        "A. B. Smith wrote x / y / z",
        "e.g. the 2008 gap",
    ]
    assert [collapse_split_words(t) for t in ordinary] == ordinary
    lex = config().prefilter_lexicon("en-IN")
    active = frozenset(YTG + FIN)
    assert select_rules("A candle has a body.", (), (), lex, active) == ()
    # no dataset item changes its selection because of the join (false-positive check)
    changed = [
        it["text"]
        for c in CG
        for it in c["input"]["items"]
        if collapse_split_words(it["text"].casefold()) != it["text"].casefold()
    ]
    assert changed == []
