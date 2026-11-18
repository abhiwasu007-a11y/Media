# mypy: disable-error-code="arg-type,attr-defined,misc,has-type,no-untyped-def,no-any-return"
"""Reuse lookup, plan reader rules and the diagram template."""

import json
from datetime import timedelta

import pytest

from agent_08_visual_assets.models.shot_plan import ShotPlanReader
from agent_08_visual_assets.reuse.engine import ReuseCandidate, ReuseEngine, ReuseRequest
from agent_08_visual_assets.sources.graphics import (
    DiagramSpec,
    GraphicKind,
    GraphicTemplateRenderer,
)
from amw_core.errors import InputInvalidError
from tests.agents.agent_08_visual_assets.fixtures import PALETTE
from tests.agents.agent_08_visual_assets.test_stage import shot


def cand(org: str, sha: str, status: str = "ACTIVE") -> ReuseCandidate:
    return ReuseCandidate(org, status, None, None, 0, sha)


@pytest.mark.unit
def test_find_prefers_exact_and_never_crosses_tenants() -> None:
    req = ReuseRequest("orgA", "chn", "s1")
    lib = [
        ("a_near", cand("orgA", "s9"), "0000000000000001"),
        ("b_foreign", cand("orgB", "s1"), "0000000000000000"),
        ("c_exact", cand("orgA", "s1"), None),
    ]
    hit = ReuseEngine.find(
        library=lib,
        request=req,
        request_phash="0000000000000000",
        max_uses=None,
        hamming_threshold=2,
    )
    assert hit is not None
    assert hit[0] == "c_exact"
    near = ReuseEngine.find(
        library=lib[:2],
        request=req,
        request_phash="0000000000000000",
        max_uses=None,
        hamming_threshold=2,
    )
    assert near is not None
    assert near[0] == "a_near"
    assert (
        ReuseEngine.find(
            library=[("q", cand("orgA", "s1", "QUARANTINED"), None)],
            request=req,
            request_phash=None,
            max_uses=None,
            hamming_threshold=None,
        )
        is None
    )
    expired = ReuseCandidate("orgA", "ACTIVE", timedelta(0), None, 0, "s1")
    assert (
        ReuseEngine.decide(
            asset=expired, request=req, distance=None, max_uses=None, hamming_threshold=None
        ).reason
        == "EXPIRED"
    )


@pytest.mark.unit
def test_plan_reader_validations() -> None:
    ok = [
        shot(1, "CHART", 0, 1000, chart_id="chart_1"),
        shot(2, "TEXT_CARD", 1000, 2000, on_screen_text=["x"]),
    ]
    shots, overlays = ShotPlanReader.read(json.dumps({"views": {"agent_08_shots": ok}}).encode())
    assert len(shots) == 2
    assert overlays == []
    bad_cases = [
        [shot(1, "FOOTAGE", 0, 1000, chart_id="chart_1")],
        [shot(1, "FOOTAGE", 0, 1000, allowed_tiers=["A_OWNER_REAL"])],
        [shot(1, "FOOTAGE", 0, 1000, allowed_tiers=["C_CODE_MOTION", "A_OWNER_REAL"])],
        [shot(1, "TEXT_CARD", 0, 1000)],
        [shot(1, "FOOTAGE", 0, 1000), shot(1, "FOOTAGE", 1000, 2000)],
        [shot(1, "FOOTAGE", 0, 1000), shot(2, "FOOTAGE", 500, 2000)],
        [shot(1, "FOOTAGE", 1000, 1000)],
    ]
    for views in bad_cases:
        with pytest.raises(InputInvalidError):
            ShotPlanReader.read(json.dumps({"views": {"agent_08_shots": views}}).encode())
    with pytest.raises(InputInvalidError):
        ShotPlanReader.read(b'{"nope": 1}')


@pytest.mark.unit
def test_diagram_template() -> None:
    d = DiagramSpec(("One", "Two", "Three"), ((0, 1), (1, 2)))
    kw = {
        "kind": GraphicKind.DIAGRAM,
        "lines": [],
        "allowlist": ["One", "Two", "Three"],
        "width_px": 640,
        "height_px": 360,
        "palette": PALETTE,
    }
    assert GraphicTemplateRenderer.render(diagram=d, **kw).png
    assert GraphicTemplateRenderer.render(
        diagram=d, **{**kw, "width_px": 360, "height_px": 640}
    ).png
    with pytest.raises(InputInvalidError):
        GraphicTemplateRenderer.render(diagram=DiagramSpec(("One",), ((0, 5),)), **kw)
    with pytest.raises(InputInvalidError):
        GraphicTemplateRenderer.render(diagram=None, **kw)
