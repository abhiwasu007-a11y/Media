"""CCR-279 evidence: the real agent_05 script document shape against agent_10's ``ScriptStrings``.

``agent_05.script_document`` writes ``segments`` as a list of ``DocSegment`` objects;
``agent_10.inputs.ScriptStrings.segments`` is ``dict[str, str]`` (``segment_id -> text``). The two
cannot validate against each other. The failing test below is a documented ``xfail(strict=True)``:
it flips to an error (XPASS) on the day the separate fix lane gives agent_10 a consumer slice model
that reads the real agent_05 shape (CCR-200), and the marker must then be removed.
The audio-master payload is NOT part of this problem: the real agent_07 ``AudioMasterOutput``
payload validates against agent_10 ``AudioMaster`` (checked in review of PR 99)."""

from typing import Any

import pytest
from pydantic import ValidationError

from agent_05_scriptwriter.contracts import DocSegment, ScriptDocument
from agent_10_video_editor.inputs import ScriptStrings

pytestmark = pytest.mark.unit

SEGMENT: dict[str, Any] = {
    "segment_id": "s1",
    "kind": "HOOK_PROOF",
    "section_id": None,
    "scene_id": "sc1",
    "text": "One sentence of narration.",
    "pace": None,
    "emotion": None,
    "concept_refs": [],
    "chart_ref": None,
    "method_label": False,
    "hypothetical_example": False,
    "est_start_ms": None,
    "est_duration_ms": None,
    "parent_segment_ids": [],
}


def test_the_real_script_document_declares_segments_as_a_list_of_docsegment() -> None:
    seg = DocSegment.model_validate(SEGMENT)  # a real DocSegment, not a hand-made shape
    assert seg.segment_id == "s1"
    assert ScriptDocument.model_fields["segments"].annotation is not dict
    assert ScriptStrings.model_fields["segments"].annotation == dict[str, str]


@pytest.mark.xfail(
    raises=ValidationError,
    strict=True,
    reason="CCR-279: agent_10 ScriptStrings.segments is dict[str, str]; agent_05 writes a list",
)
def test_agent_10_script_strings_accepts_the_real_agent_05_segments() -> None:
    ScriptStrings.model_validate({"segments": [SEGMENT]})
