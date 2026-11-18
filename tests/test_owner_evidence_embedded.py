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
