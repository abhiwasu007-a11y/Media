# ruff: noqa: PT018
"""Rubric arithmetic, no-scaling / PRO_RATA, score gate modes (Q-O2), config startup rules."""

from typing import Any

import pytest

from agent_16_compliance_qa.config import Agent16Config, MachineScaling, ScoreGateMode
from agent_16_compliance_qa.judge.models import QualityOutput
from agent_16_compliance_qa.quality import GroupRequest, QualityScorer, score_payload
from agent_16_compliance_qa.scoring.aggregate import (
    ClaimFact,
    CriterionScore,
    DeterministicInputs,
    GateFacts,
    QcRow,
    ScriptFacts,
    ThumbnailFacts,
    aggregate,
    score_deterministic,
    score_gate,
)
from agent_16_compliance_qa.scoring.rubric import (
    RUBRIC_V1,
    group_criteria,
    machine_criteria,
    validate_rubric,
)
from amw_core.enums import CheckVerdict, ClaimStatus, ComplianceVerdict, QualityDimension
from amw_core.errors import ConfigInvalidError
from tests.agents.agent_16_compliance_qa.support import BASE_CONFIG, blueprint_schema, config

ROUTING = {
    "script_stage_id": "s05_script",
    "plan_stage_id": "s09_plan",
    "voice_stage_id": "s07_voice",
    "render_stage_id": "s10_render",
    "thumbnails_stage_id": "s11_thumbs",
}
ALL_QC = [p for c in RUBRIC_V1 for p in c.check_prefixes]


def full_inputs(**over: Any) -> DeterministicInputs:
    base: dict[str, Any] = {
        "qc": [
            QcRow(check_id=p + ("x" if p.endswith(".") else ""), verdict=CheckVerdict.PASS)
            for p in ALL_QC
            if p != "qc.audio.music_bed_offset"
        ]
        + [
            QcRow(
                check_id="qc.audio.music_bed_offset",
                verdict=CheckVerdict.SKIPPED,
                precondition="no music bed",
            )
        ],
        "claims": [
            ClaimFact(
                claim_id="c1",
                claim_type="FACTUAL",
                status=ClaimStatus.VERIFIED,
                has_citation_or_chart=True,
            )
        ],
        "script": ScriptFacts(
            hook_options=3,
            promise_fields_present=True,
            sections_with_takeaway=4,
            sections_with_example=4,
            section_count=4,
            viewer_problem_addressed=True,
        ),
        "thumbnails": ThumbnailFacts(
            variants=3, required_variants=3, spec_ok=True, legible=True, title_length_ok=True
        ),
        "gate": GateFacts(
            overall=ComplianceVerdict.ALLOWED,
            licence_pass=True,
            disclosure_decision="NOT_REQUIRED",
            disclaimer_pass=True,
            finance=True,
        ),
    }
    return DeterministicInputs.model_validate(base | over)


def full_judge(payload: Any) -> QualityOutput:
    group = payload["group_id"]
    return QualityOutput.model_validate(
        {
            "group_id": group,
            "scores": [
                {
                    "criterion_id": c.criterion_id,
                    "points": c.max_points,
                    "max_points": c.max_points,
                    "evidence_refs": ["s01"],
                    "why_not_higher": "-",
                }
                for c in group_criteria(group)
            ],
            "check_results": [],
            "injection_suspected": [],
            "refusal": None,
        }
    )


def groups() -> dict[Any, GroupRequest]:
    return {
        g: GroupRequest(payload={"group_id": g}, known_refs=frozenset({"s01"}))
        for g in ("G1", "G2", "G3")
    }


def test_rubric_sums() -> None:
    validate_rubric()
    assert sum(c.max_points for c in machine_criteria()) == 79
    tm = [c for c in RUBRIC_V1 if c.dimension is QualityDimension.THUMBNAIL_METADATA]
    assert [
        sum(c.max_points for c in tm if c.kind == k)
        for k in ("DETERMINISTIC", "LLM_JUDGE", "HUMAN")
    ] == [4, 4, 2]
    with pytest.raises(ValueError, match="100"):
        validate_rubric(RUBRIC_V1[1:])


def test_machine_total_without_scaling_is_at_most_79_and_never_passes() -> None:
    res = QualityScorer(config(), full_judge).score(full_inputs(), groups(), ROUTING)
    assert res.machine_total == 78  # 79 minus the SKIPPED music-bed point
    assert res.gate == "NOT_GATING" and res.judge_calls == 3
    gate = next(r for r in res.results if r.check_id == "a16.qs.gate.machine_total")
    assert gate.gate and not gate.blocking and gate.verdict is CheckVerdict.WARN
    music = next(
        c for r in res.dimensions for c in r.criteria if c.criterion_id == "au.d.music_bed"
    )
    assert music.status == "SKIPPED" and music.earned == 0
    assert all(r.gate for r in res.results)
    import jsonschema

    payload = score_payload(res, [], {"prompt": "agent_16/quality_score.v1"})
    jsonschema.validate(payload, blueprint_schema("### 8.4 `agent_16.quality_score.output`"))


def test_pro_rata_removes_skipped_from_both_sums() -> None:
    cfg = config(**{"quality.machine_scaling": "PRO_RATA"})
    res = QualityScorer(cfg, full_judge).score(full_inputs(), groups(), ROUTING)
    au = next(r for r in res.dimensions if r.dimension is QualityDimension.AUDIO_QUALITY)
    assert au.points == 10  # 6 of 6 scored D points scaled to the 10-point dimension
    assert res.machine_total == 100


def test_missing_inputs_earn_zero_not_full_points() -> None:
    d = score_deterministic(
        full_inputs(
            qc=[],
            claims=None,
            script=ScriptFacts(
                hook_options=None,
                promise_fields_present=None,
                sections_with_takeaway=None,
                sections_with_example=None,
                section_count=None,
                viewer_problem_addressed=None,
            ),
        )
    )
    nulled = [
        c
        for c in d
        if c.criterion_id.startswith(("ra.", "st.", "av.", "vq.", "eq."))
        or c.criterion_id in ("au.d.loudness", "au.d.codec", "au.d.clean")
    ]
    assert nulled and all(c.earned == 0 and c.finding for c in nulled)


def test_blocking_mode_names_the_weakest_dimensions_stage() -> None:
    rows = aggregate(
        [
            CriterionScore(
                criterion_id=c.criterion_id,
                dimension=c.dimension,
                kind=c.kind,
                max=c.max_points,
                earned=0 if c.dimension is QualityDimension.AUDIO_QUALITY else c.max_points,
                status="SCORED",
            )
            for c in machine_criteria()
        ],
        MachineScaling.PRO_RATA,
    )
    verdict, res, total = score_gate(rows, 95, ScoreGateMode.BLOCKING, ROUTING)
    assert verdict == "FAIL" and res.blocking and res.remedy_stage_id == "s07_voice"
    assert total == 90
    verdict, res, _ = score_gate(rows, 85, ScoreGateMode.BLOCKING, ROUTING)
    assert verdict == "PASS" and not res.blocking


def test_judge_refusal_scores_the_group_zero() -> None:
    def refusing(payload: Any) -> QualityOutput:
        return QualityOutput.model_validate(
            {
                "group_id": payload["group_id"],
                "scores": [],
                "check_results": [],
                "injection_suspected": [],
                "refusal": {
                    "reason": "INSUFFICIENT_INPUT",
                    "message": "x",
                    "missing_inputs": [],
                    "violated_rule_ids": [],
                },
            }
        )

    res = QualityScorer(config(), refusing).score(full_inputs(), groups(), ROUTING)
    judged = [c for r in res.dimensions for c in r.criteria if c.kind == "LLM_JUDGE"]
    assert judged and all(c.earned == 0 for c in judged)


def test_config_startup_rules() -> None:
    with pytest.raises(ConfigInvalidError):  # U-83 / AC-21
        config(**{"quality.score_gate_mode": "BLOCKING"})
    assert (
        config(
            **{"quality.score_gate_mode": "BLOCKING", "quality.machine_scaling": "PRO_RATA"}
        ).score_gate_mode
        is ScoreGateMode.BLOCKING
    )
    with pytest.raises(ConfigInvalidError):
        config(**{"approvals.accepted_channels": ["OWNER_CHAT_OPERATOR", "WEB_DASHBOARD"]})
    with pytest.raises(ConfigInvalidError):
        config(**{"agent_16.llm.fallback_on_unavailable": True})
    with pytest.raises(ConfigInvalidError):
        config(**{"llm.agent_16.compliance_gate.frames.accepts_images": False})
    with pytest.raises(ConfigInvalidError):
        Agent16Config.from_mapping(
            {k: v for k, v in BASE_CONFIG.items() if k != "quality.publish_min_score"}
        )
    with pytest.raises(ConfigInvalidError):
        config(**{"some.unknown.key": 1})
    cfg = config()
    assert cfg.lexicon("en-IN").version == "lex.en.test.1"
    with pytest.raises(ConfigInvalidError):
        cfg.lexicon("ta-IN")
    assert cfg.step("llm_policy").model == "test-model-from-config"
    with pytest.raises(ConfigInvalidError):
        Agent16Config.from_mapping(
            {k: v for k, v in BASE_CONFIG.items() if ".quality_score.judge." not in k}
        ).step("llm_quality")
