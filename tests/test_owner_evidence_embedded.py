# ruff: noqa: RUF001
"""A6 (CCR-125): a quote must lie in the owner-authored part of a reply; embedded text never
counts and an unmarked embedded part is NEEDS_CLARIFICATION (nothing recorded)."""

from typing import Any

import pytest

from amw_core.enums import EvidenceRecordKind
from amw_core.ids import WireId
from amw_core.owner_evidence_verifier import (
    EMBEDDED_PART_UNMARKED,
    OWNER_PART_MISMATCH,
    RECORD,
    Refusal,
    Verified,
    verify_owner_event,
)
from tests.test_owner_evidence_verifier import (
    NOW,
    POLICY,
    REQUESTED,
    event,
    evidence,
    verify_via_store,
)

EMBEDDED = "> Approve R7K2 please"
OWN = "Approve R7K2"


def run(ev: Any, ne: Any = None) -> Any:
    return verify_owner_event(
        ev,
        evidence=ne or evidence(),
        evidence_id=WireId("evd_1"),
        purpose=RECORD,
        quote=(ne or evidence()).quote,
        message_at=(ne or evidence()).message_at,
        anchor=REQUESTED,
        distinct_from_event_uuid=None,
        policy=POLICY,
        now=NOW,
    )


def test_plain_event_is_unchanged() -> None:
    assert isinstance(run(event()), Verified)


def test_marked_owner_part_with_quote_inside_passes() -> None:
    content = f"{OWN}\n{EMBEDDED}"
    out = run(event(content=content, embeds_earlier_message=True, owner_authored_content=OWN))
    assert isinstance(out, Verified)


@pytest.mark.parametrize(
    "content",
    [
        f"{OWN}\n{EMBEDDED}",
        "I will think.\n> Approve R7K2 please",
        "On Mon, the owner wrote:\nApprove R7K2",
        "-----Original Message-----\nApprove R7K2",
    ],
)
def test_unmarked_embedded_text_needs_clarification(content: str) -> None:
    out = run(event(content=content, embeds_earlier_message=content.startswith("Approve")))
    assert isinstance(out, Refusal)
    assert out.reason == EMBEDDED_PART_UNMARKED
    assert out.needs_clarification


def test_flag_without_marking_needs_clarification() -> None:
    out = run(event(embeds_earlier_message=True))
    assert isinstance(out, Refusal)
    assert out.needs_clarification


def test_quote_in_embedded_part_only_is_refused() -> None:
    content = f"Thanks.\n{EMBEDDED}"
    out = run(event(content=content, embeds_earlier_message=True, owner_authored_content="Thanks."))
    assert isinstance(out, Refusal)
    assert out.reason in {"quote_verbatim", "subject_reference", "decision_matches"} | {
        "needs_clarification"
    }
    assert not isinstance(out, Verified)


def test_marked_part_not_in_content_is_refused() -> None:
    out = run(event(owner_authored_content="Approve R7K2 now", embeds_earlier_message=True))
    assert isinstance(out, Refusal)
    assert out.reason == OWNER_PART_MISMATCH


def test_empty_marked_part_is_refused() -> None:
    out = run(event(owner_authored_content="  ", embeds_earlier_message=True))
    assert isinstance(out, Refusal)
    assert out.reason == OWNER_PART_MISMATCH


def test_embedded_decision_cannot_complete_owner_text() -> None:
    # attack: the owner wrote only "ok"; the embedded text carries the review code and word
    content = "ok\n> R7K2 approved"
    out = run(event(content=content, embeds_earlier_message=True, owner_authored_content="ok"))
    assert not isinstance(out, Verified)


def test_content_kind_quote_in_embedded_text_refused() -> None:
    ne = evidence(
        record_kind=EvidenceRecordKind.OWNER_TOPIC,
        quote="make a video about gold loans",
        review_code=None,
        parsed_decision=None,
    )
    content = "ok\n> make a video about gold loans"
    out = run(event(content=content, embeds_earlier_message=True, owner_authored_content="ok"), ne)
    assert not isinstance(out, Verified)


def test_store_refuses_and_records_clarification() -> None:
    record = verify_via_store(event(content=f"{OWN}\n{EMBEDDED}"))
    assert record.verifier_result[EMBEDDED_PART_UNMARKED] is False
    assert record.verifier_result["quote_verbatim"] is False


# --- review M48-1..3: invisible prefixes, other quote styles, the marked part itself -------------
INVISIBLE = ["​", "⁠", "‎", "﻿", "‍", "­", "⁣"]


@pytest.mark.parametrize("ch", INVISIBLE)
def test_invisible_prefix_before_the_quote_marker_is_caught(ch: str) -> None:
    out = run(event(content=f"{OWN}\n{ch}> Thanks"))
    assert isinstance(out, Refusal)
    assert out.reason == EMBEDDED_PART_UNMARKED
    assert out.needs_clarification


@pytest.mark.parametrize("ch", INVISIBLE)
def test_invisible_prefix_with_leading_spaces_is_caught(ch: str) -> None:
    out = run(event(content=f"{OWN}\n  {ch} {ch}> Thanks"))
    assert isinstance(out, Refusal)
    assert out.reason == EMBEDDED_PART_UNMARKED


@pytest.mark.parametrize(
    "line",
    [
        "› Thanks",
        "» Thanks",
        "| Thanks",
        "≥ Thanks",
        "＞ Thanks",
        "﹥ Thanks",
        "-----Original Message-----",
        "- Original Message -",
        "________________________________",
        "Begin forwarded message:",
        "On Mon, 3 Nov 2025 at 10:00, Abhi <a@example.invalid> wrote:",
        "Abhi wrote:",
        "अभि म्हणाले:",
    ],
)
def test_other_quote_and_header_styles_are_caught(line: str) -> None:
    out = run(event(content=f"{OWN}\n{line}\nApprove R7K2"))
    assert isinstance(out, Refusal)
    assert out.reason == EMBEDDED_PART_UNMARKED


def test_outlook_header_block_is_caught() -> None:
    block = "From: Abhi\nSent: Monday\nTo: x\nSubject: s\nApprove R7K2"
    out = run(event(content=block))
    assert isinstance(out, Refusal)
    assert out.reason == EMBEDDED_PART_UNMARKED


def test_from_alone_is_not_a_header_block() -> None:
    out = run(event(content="Approve R7K2\nFrom: Abhi"))
    assert not (isinstance(out, Refusal) and out.reason == EMBEDDED_PART_UNMARKED)


def test_marked_part_that_is_the_whole_embedded_content_is_refused() -> None:
    """A naive source marks everything as owner-authored: the marked part is checked itself."""
    content = f"ok\n​> {OWN}"
    out = run(event(content=content, owner_authored_content=content, embeds_earlier_message=True))
    assert isinstance(out, Refusal)
    assert out.reason == EMBEDDED_PART_UNMARKED


def test_marked_clean_part_with_invisible_prefix_in_embedded_part_still_passes() -> None:
    content = f"{OWN}\n​> old text"
    out = run(event(content=content, owner_authored_content=OWN, embeds_earlier_message=True))
    assert isinstance(out, Verified)
