"""Exact-quote verification wired into ``ClaimVerificationStep`` (D12, CCR-291, CCR-302 PROPOSED).

SYNTHETIC text only: the fake library is a throw-away git repository of invented sentences (and one
invented Marathi sentence); no text of the private library is used."""

# ruff: noqa: PT018

import json
from pathlib import Path
from typing import Any

import pytest

from agent_06_fact_checker.library.quotes import QuoteSettings, QuoteVerifier
from agent_06_fact_checker.library.reader import CheckoutLibraryReader, LibraryRef
from agent_06_fact_checker.library.wiring import QuoteCheck, StaticLibraryIndex, WorkRef
from amw_core.contracts.task_output import gate_failures, integrity_failures
from tests.agents.agent_06_fact_checker import library_support as ls
from tests.agents.agent_06_fact_checker.test_verification_step import (
    REF,
    batch,
    claim,
    data,
    doc,
    go,
    result_for,
)

pytestmark = pytest.mark.unit

REF2 = "kch_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8f02"
REF3 = "kch_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8f03"
REF4 = "kch_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8f04"
GOOD = "It is not time we lack but the will to hold it."
MARATHI_LINE = "वेळ कमी नसतो, तो वापरण्याची इच्छा कमी असते."  # INVENTED sentence, not book text
MARATHI_FILE = f"§ १.१\n{MARATHI_LINE}\n"


def quote_claim(text: str = GOOD, who: str = "Testor", **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "claim_type": "QUOTED_THIRD_PARTY",
        "quote": f'{who} wrote "{text}"',
        "normalized_claim": f"{who} wrote a sentence about time.",
        "citation_refs": [REF],
    }
    return claim(1, **{**base, **over})


def check(tmp_path: Path) -> QuoteCheck:
    files = {**ls.FILES, "phil/marathi.txt": MARATHI_FILE}
    repo = ls.make_library(tmp_path, files)
    reader = CheckoutLibraryReader(LibraryRef(repo, ls.head_sha(repo)), ls.LIMITS)
    records = ls.records()
    records["mr"] = ls.record("mr", "phil/marathi.txt", author="Aelius Testor")
    index = StaticLibraryIndex(
        {
            REF: WorkRef("orig", "I.1", ("Testor",)),
            REF2: WorkRef("orig", "I.2", ("Testor",)),
            REF3: WorkRef("modern", "1", ("Fictus",)),
            REF4: WorkRef("mr", "१.१", ("Testor",)),
        }
    )
    verifier = QuoteVerifier(
        records, reader, QuoteSettings(require_locator=True, guard_min_words=6)
    )
    return QuoteCheck(verifier, records, index, job_date=ls.JOB_DATE)


def run(tmp_path: Path, claims: list[dict[str, Any]], **kw: Any) -> tuple[Any, Any]:
    d = data(claims, channel_category="youtube_general", active_rule_packs=["rp.youtube_general"])
    d["available_citations"] = [
        {**d["available_citations"][0], "citation_ref": r} for r in (REF,)
    ] + [
        {
            "citation_ref": r,
            "kind": "KNOWLEDGE_CHUNK",
            "title": "t",
            "content_sha256": d["available_citations"][0]["content_sha256"],
        }
        for r in (REF2, REF3, REF4)
    ]
    from tests.agents.agent_06_fact_checker.support import with_claims_hash

    out, w = go(with_claims_hash(d), kw.pop("responses", []), quotes=check(tmp_path), **kw)
    return out, w


def one(out: Any) -> dict[str, Any]:
    return dict(doc(out)["claims"][0])


def test_exact_quote_is_verified_without_a_model_call_and_credited(tmp_path: Path) -> None:
    out, w = run(tmp_path, [quote_claim()])
    c = one(out)
    assert c["status"] == "VERIFIED" and c["mode"] == "CODE_ONLY" and c["reason_codes"] == []
    assert w.llm.calls == 0
    assert doc(out)["gate_verdict"] == "PASSED"
    assert not gate_failures(out) and not integrity_failures(out)
    (credits_ref,) = [r for r in out.output_refs if r.uri.endswith("quote_credits.json")]
    body = json.loads(w.blobs.data[credits_ref.uri])
    assert body["works"] == [
        {
            "work_id": "orig",
            "use": "QUOTED",
            "credit_line": "Aelius Testor, On orig. Public domain.",
        }
    ]


@pytest.mark.parametrize(
    ("text", "who", "refs", "status", "reason"),
    [
        (
            "It is not time we lack but the will to keep it.",
            "Testor",
            [REF],
            "CONTRADICTED",
            "QUOTE_NOT_ATTRIBUTABLE",
        ),
        (GOOD, "Testor", [REF2], "CONTRADICTED", "QUOTE_NOT_ATTRIBUTABLE"),  # wrong place
        (GOOD, "Fictus", [REF], "CONTRADICTED", "QUOTE_NOT_ATTRIBUTABLE"),  # other known author
        (GOOD, "Someone", [REF], "NEEDS_SUBSTANTIATION", "QUOTE_NOT_ATTRIBUTABLE"),  # nobody named
        (GOOD, "Testor", [], "NEEDS_SUBSTANTIATION", "QUOTE_NOT_ATTRIBUTABLE"),  # no source
        (
            GOOD,
            "Testor",
            [REF, REF2],
            "NEEDS_SUBSTANTIATION",
            "QUOTE_NOT_ATTRIBUTABLE",
        ),  # two places
        ("too short", "Testor", [REF], "NEEDS_SUBSTANTIATION", "QUOTE_NOT_ATTRIBUTABLE"),
        (GOOD, "Fictus", [REF3], "CONTRADICTED", "QUOTE_NOT_ATTRIBUTABLE"),  # not public domain
    ],
)
def test_unverifiable_quotes_are_removed_or_block_the_claim(
    tmp_path: Path, text: str, who: str, refs: list[str], status: str, reason: str
) -> None:
    out, _ = run(tmp_path, [quote_claim(text, who, citation_refs=refs)])
    c = one(out)
    assert c["status"] == status and c["reason_codes"] == [reason] and c["evidence"] == []
    d = doc(out)
    assert d["revision_requests"][0]["action"] == "REMOVE_OR_REWORD"
    assert d["gate_verdict"] == ("FAILED" if status == "CONTRADICTED" else "PASSED")


def test_a_claim_without_quotation_marks_is_an_empty_quote(tmp_path: Path) -> None:
    out, _ = run(tmp_path, [quote_claim() | {"quote": "Testor said that time is short."}])
    assert one(out)["status"] == "NEEDS_SUBSTANTIATION"


def test_non_public_domain_work_is_ideas_only_with_a_further_reading_credit(tmp_path: Path) -> None:
    ideas = claim(1, claim_type="FACTUAL", citation_refs=[REF3])
    out, w = run(tmp_path, [ideas], responses=[batch(result_for("c1", "NOT_FOUND"))])
    (ref,) = [r for r in out.output_refs if r.uri.endswith("quote_credits.json")]
    body = json.loads(w.blobs.data[ref.uri])
    (entry,) = body["works"]
    assert entry["use"] == "IDEAS_ONLY"
    assert entry["credit_line"].startswith("Further reading: Quintus Fictus, On modern")


def test_marathi_quote_is_verified_exactly(tmp_path: Path) -> None:
    c = quote_claim(MARATHI_LINE, "Testor", citation_refs=[REF4])
    out, _ = run(tmp_path, [c])
    assert one(out)["status"] == "VERIFIED"
    changed = quote_claim(
        MARATHI_LINE.replace("कमी असते", "जास्त असते"), "Testor", citation_refs=[REF4]
    )
    out2, _ = run(tmp_path, [changed])
    assert one(out2)["status"] == "CONTRADICTED"


def test_a_script_without_library_works_has_no_credit_artifact(tmp_path: Path) -> None:
    out, _ = run(tmp_path, [claim(1, citation_refs=[])], sources=[])
    assert not [r for r in out.output_refs if r.uri.endswith("quote_credits.json")]
