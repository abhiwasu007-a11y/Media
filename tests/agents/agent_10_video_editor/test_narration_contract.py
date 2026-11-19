"""CCR-127 / CCR-128 review fixes: Agent 10 reads the real agent_07 output; fail-closed finance."""

import json
from pathlib import Path

import pytest

from agent_07_voice_production.contracts import VoiceSynthesisOutput
from agent_10_video_editor.inputs import NarrationTimeline
from agent_10_video_editor.ports import ChannelProfile
from amw_core.enums import OutputStatus

ROOT = Path(__file__).resolve().parents[3]
CASES = ROOT / "docs/v4/evals/agent_07_voice_production/voice_synthesis/cases.jsonl"


def _real_agent_07_output(tmp_path: Path) -> dict[str, object]:
    from tests.agents.agent_07_voice_production.voice_world import build

    case = next(
        json.loads(line)
        for line in CASES.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line)["case_id"] == "VS-01"
    )
    out = build(case, tmp_path).run()
    assert out.status is OutputStatus.SUCCEEDED
    assert out.payload is not None
    assert out.payload.data is not None
    return dict(out.payload.data)


@pytest.mark.integration
def test_agent_10_reads_the_output_of_the_real_agent_07_stage(tmp_path: Path) -> None:
    data = _real_agent_07_output(tmp_path)
    VoiceSynthesisOutput.model_validate(data)  # it is the contract shape
    parsed = NarrationTimeline.model_validate(data)
    assert parsed.narration.asset_id == data["narration"]["asset_id"]  # type: ignore[index]
    assert parsed.narration.asset_id is not None
    assert parsed.source == data["timeline"]["source"]  # type: ignore[index]
    assert [s.segment_id for s in parsed.segments] == [
        s["segment_id"]
        for s in data["timeline"]["segments"]  # type: ignore[index]
    ]
    assert parsed.end_ms == max(s.end_ms for s in parsed.segments) > 0


@pytest.mark.unit
@pytest.mark.parametrize(
    "category",
    ["finance", "Finance", "FINANCE", " finance", "finance ", "finance​", "", "  ", None],
)
def test_finance_decision_fails_closed_on_every_spelling(category: str | None) -> None:
    assert ChannelProfile(category, ()).is_finance


@pytest.mark.unit
def test_finance_pack_spelling_and_known_non_finance() -> None:
    assert ChannelProfile("education", (" RP.Finance_SEBI_IN ",)).is_finance
    assert ChannelProfile("education", ("rp.finance_sebi_in​",)).is_finance
    assert not ChannelProfile("education", ("rp.youtube_general",)).is_finance
    assert not ChannelProfile(" Education ", ()).is_finance
