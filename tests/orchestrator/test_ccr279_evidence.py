"""CCR-279 part (b), resolved by PR #101: the real agent_05 script document through agent_10.

``agent_05.script_document`` writes ``segments`` as a list of ``DocSegment`` objects. Agent 10 now
reads it through ``ScriptDocumentSlice`` / ``parse_script_document`` (CCR-200: read the producer's
real shape, ignore unread fields). The document here is the one Agent 05's own assembler emits
(``real_script_document``) and it is validated by the producer's own ``ScriptDocument`` model first,
so the orchestrator builder hands Agent 10 a document that Agent 10 accepts. This is a shape check
only: it does not run the real Agent 10 entry point inside the orchestrator dry run.
The audio-master payload is not part of this problem: the real agent_07 ``AudioMasterOutput``
payload validates against agent_10 ``AudioMaster`` (checked in review of PR 99)."""

import json
from typing import Any

import pytest

from agent_05_scriptwriter.contracts import DocSegment, ScriptDocument
from agent_10_video_editor.inputs import ScriptDocumentSlice, ScriptStrings, parse_script_document
from amw_core.errors import SchemaInvalidError
from tests.agents.agent_10_video_editor.real_script import real_script_document

pytestmark = pytest.mark.unit


def _bytes(doc: dict[str, Any]) -> bytes:
    return json.dumps(doc, sort_keys=True).encode()


def test_the_real_script_document_declares_segments_as_a_list_of_docsegment() -> None:
    doc = real_script_document(4, on_screen=("Key idea",), disclaimer=True)
    ScriptDocument.model_validate(doc)  # the producer's own contract
    for seg in doc["segments"]:
        DocSegment.model_validate(seg)
    assert isinstance(doc["segments"], list)
    assert ScriptStrings.model_fields["segments"].annotation == dict[str, str]  # the derived view


def test_agent_10_reads_the_real_agent_05_document_through_its_slice() -> None:
    doc = real_script_document(4, on_screen=("Key idea",), disclaimer=True)
    ScriptDocumentSlice.model_validate(doc)
    strings = parse_script_document(_bytes(doc))
    assert strings.segments == {s["segment_id"]: s["text"] for s in doc["segments"]}
    assert strings.on_screen  # scene on-screen strings and the disclaimer, keyed by SHA-256


def test_a_document_without_segments_is_still_refused() -> None:
    doc = real_script_document(4)
    doc["segments"] = []
    with pytest.raises(SchemaInvalidError):
        parse_script_document(_bytes(doc))
