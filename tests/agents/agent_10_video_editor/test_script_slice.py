"""Agent 10's slice of the REAL Agent 05 script document (CCR-200, CCR-279 part b).

The document is emitted by Agent 05's own assembler (``real_script.py``); Agent 10 reads it through
``ScriptDocumentSlice`` (list of ``DocSegment`` objects, scenes, disclaimer slots), ignores every
field it does not use and fails closed on a missing, empty or duplicate segment id.
"""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from agent_05_scriptwriter.contracts import ScriptDocument
from agent_10_video_editor.canonical import sha256_hex
from agent_10_video_editor.inputs import parse_script_document
from agent_10_video_editor.timeline import TextBinder
from amw_core.enums import OutputStatus
from amw_core.errors import SchemaInvalidError
from tests.agents.agent_10_video_editor.real_script import DISCLAIMER_TEXT, real_script_document
from tests.agents.agent_10_video_editor.support import World, payload_data, run_chain


def _bytes(doc: dict[str, Any]) -> bytes:
    return json.dumps(doc, sort_keys=True).encode()


@pytest.mark.unit
def test_real_document_is_a_valid_agent_05_document_with_list_segments() -> None:
    doc = real_script_document(6, on_screen=("Key idea",), disclaimer=True)
    ScriptDocument.model_validate(doc)  # the producer's own contract accepts it
    assert isinstance(doc["segments"], list)
    assert {"segment_id", "text", "kind", "scene_id"} <= set(doc["segments"][0])


@pytest.mark.unit
def test_slice_reads_segment_text_by_id_and_ignores_unread_fields() -> None:
    doc = real_script_document(6)
    strings = parse_script_document(_bytes(doc))
    assert strings.segments == {s["segment_id"]: s["text"] for s in doc["segments"]}
    extra = deepcopy(doc)
    extra["brand_new_producer_field"] = {"x": 1}
    extra["segments"][0]["brand_new_segment_field"] = 7
    assert parse_script_document(_bytes(extra)).segments == strings.segments


@pytest.mark.unit
def test_on_screen_strings_come_from_scenes_and_disclaimer_by_sha256() -> None:
    doc = real_script_document(6, on_screen=("Key idea", "Second term"), disclaimer=True)
    strings = parse_script_document(_bytes(doc))
    for text in ("Key idea", "Second term", DISCLAIMER_TEXT):
        assert strings.on_screen[sha256_hex(text.encode())] == text
    slot = doc["disclaimer_slots"][0]
    assert strings.on_screen[slot["text_sha256"]] == DISCLAIMER_TEXT


@pytest.mark.unit
def test_text_binder_binds_overlay_hashes_against_the_real_document() -> None:
    from agent_10_video_editor.inputs import PlanOverlay, TextRef

    doc = real_script_document(6, on_screen=("Key idea",))
    strings = parse_script_document(_bytes(doc))
    sha = sha256_hex(b"Key idea")
    overlay = PlanOverlay(
        overlay_id="ov01",
        kind="CAPTION_CARD",
        start_ms=0,
        end_ms=1000,
        text_refs=(TextRef(sha256=sha, scene_id="sec1.sc1", index=0),),
    )
    assert TextBinder.bind([overlay], strings) == {sha: "Key idea"}


def _mutations() -> list[tuple[str, Any]]:
    def duplicate(d: dict[str, Any]) -> None:
        d["segments"][1]["segment_id"] = d["segments"][0]["segment_id"]

    def empty(d: dict[str, Any]) -> None:
        d["segments"] = []

    def no_id(d: dict[str, Any]) -> None:
        del d["segments"][0]["segment_id"]

    def blank_id(d: dict[str, Any]) -> None:
        d["segments"][0]["segment_id"] = ""

    def no_text(d: dict[str, Any]) -> None:
        del d["segments"][0]["text"]

    def no_segments(d: dict[str, Any]) -> None:
        del d["segments"]

    def legacy_dict(d: dict[str, Any]) -> None:
        d["segments"] = {s["segment_id"]: s["text"] for s in d["segments"]}

    def no_scenes(d: dict[str, Any]) -> None:
        del d["scenes"]

    def dangling_slot(d: dict[str, Any]) -> None:
        d["disclaimer_slots"][0]["segment_id"] = "s9999"

    return [
        ("duplicate", duplicate),
        ("empty", empty),
        ("no_id", no_id),
        ("blank_id", blank_id),
        ("no_text", no_text),
        ("no_segments", no_segments),
        ("legacy_dict", legacy_dict),
        ("no_scenes", no_scenes),
        ("dangling_slot", dangling_slot),
    ]


@pytest.mark.unit
@pytest.mark.parametrize(("name", "mutate"), _mutations(), ids=[n for n, _ in _mutations()])
def test_slice_fails_closed(name: str, mutate: Any) -> None:
    doc = real_script_document(6, disclaimer=True)
    mutate(doc)
    with pytest.raises(SchemaInvalidError):
        parse_script_document(_bytes(doc))
    assert name  # the id of the case


@pytest.mark.unit
def test_not_json_is_schema_invalid() -> None:
    with pytest.raises(SchemaInvalidError):
        parse_script_document(b"not json")
    with pytest.raises(SchemaInvalidError):
        parse_script_document(b'{"segments": "x"}')


@pytest.mark.unit
def test_end_to_end_real_script_document_through_render_and_subtitles(tmp_path: Path) -> None:
    """Real agent_05 document -> slice -> render stage and subtitles stage accept it."""
    world = World(tmp_path, on_screen=("Key idea",))
    stored = world.docs["agent_05.script_document"]
    ScriptDocument.model_validate(stored)  # what the stages read is the producer's real shape
    assert isinstance(stored["segments"], list)
    chain = run_chain(world)
    assert chain["render"].status is OutputStatus.SUCCEEDED
    subs = chain["subtitles"]
    assert subs.status is OutputStatus.SUCCEEDED
    assert all(r.verdict == "PASS" for r in subs.validation_results)
    assert payload_data(subs)["srt"][0]["cue_count"] == world.n_shots


@pytest.mark.unit
def test_end_to_end_broken_real_document_is_refused_by_render(tmp_path: Path) -> None:
    world = World(tmp_path)
    broken = deepcopy(world.docs["agent_05.script_document"])
    broken["segments"][1]["segment_id"] = broken["segments"][0]["segment_id"]
    uri, sha = world.put("agent_05.script_document.broken.json", _bytes(broken))
    world.refs["agent_05.script_document"] = (uri, sha)
    world.script_blob_sha = sha
    with pytest.raises(SchemaInvalidError):
        run_chain(world)
