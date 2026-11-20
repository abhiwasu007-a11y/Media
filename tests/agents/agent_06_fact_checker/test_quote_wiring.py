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
from agent_06_fact_checker.library.wiring import (
    LibraryQuoteCheckFactory,
    QuoteCheck,
    StaticLibraryIndex,
    WorkRef,
)
from amw_core.contracts.task_output import gate_failures, integrity_failures
from amw_core.enums import OutputStatus
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


SETTINGS = QuoteSettings(require_locator=True)


def library(tmp_path: Path) -> tuple[Path, Any, StaticLibraryIndex]:
    files = {**ls.FILES, "phil/marathi.txt": MARATHI_FILE}
    repo = ls.make_library(tmp_path, files)
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
    return repo, records, index


def check(tmp_path: Path) -> QuoteCheck:
    repo, records, index = library(tmp_path)
    reader = CheckoutLibraryReader(LibraryRef(repo, ls.head_sha(repo)), ls.LIMITS)
    verifier = QuoteVerifier(records, reader, SETTINGS)
    return QuoteCheck(verifier, records, index, job_date=ls.JOB_DATE)


def factory(lib: tuple[Path, Any, StaticLibraryIndex], ref: Any) -> LibraryQuoteCheckFactory:
    _, records, index = lib
    return LibraryQuoteCheckFactory(
        ref_for_job=lambda _task: ref(),
        limits=ls.LIMITS,
        settings=SETTINGS,
        records=records,
        index=index,
    )


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

    if "quotes" not in kw:
        kw["quotes"] = check(tmp_path)
    out, w = go(with_claims_hash(d), kw.pop("responses", []), **kw)
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


def error_code(out: Any) -> str:
    assert out.status is not OutputStatus.SUCCEEDED and out.error is not None
    return str(out.error.code)


def test_no_quote_check_configured_fails_closed_and_the_model_is_never_asked(
    tmp_path: Path,
) -> None:
    out, w = run(tmp_path, [quote_claim()], quotes=None)
    assert error_code(out) == "PERMANENT.MISSING_DEPENDENCY"
    assert out.error is not None and out.error.details is not None
    assert out.error.details.reason == "QUOTE_CHECK_NOT_CONFIGURED"
    assert w.llm.calls == 0


def test_no_quote_check_is_fine_when_the_script_has_no_model_bound_quote(tmp_path: Path) -> None:
    out, w = run(tmp_path, [claim(1)], quotes=None, responses=[batch(result_for("c1"))])
    assert doc(out)["claims"][0]["status"] == "VERIFIED" and w.llm.calls == 1
    uncited = quote_claim(citation_refs=[])  # CODE_ONLY by policy: never a model call either
    out2, w2 = run(tmp_path, [uncited], quotes=None)
    assert one(out2)["status"] == "NEEDS_SUBSTANTIATION" and w2.llm.calls == 0


def test_factory_without_a_library_reference_is_a_typed_refusal_for_a_quote_script(
    tmp_path: Path,
) -> None:
    out, w = run(tmp_path, [quote_claim()], quotes=factory(library(tmp_path), lambda: None))
    assert error_code(out) == "PERMANENT.MISSING_DEPENDENCY"
    assert out.error is not None and out.error.details is not None
    assert out.error.details.reason == "QUOTE_LIBRARY_REF_MISSING"
    assert w.llm.calls == 0
    # a script with nothing to quote does not need the library
    out2, _ = run(
        tmp_path,
        [claim(1)],
        quotes=factory(library(tmp_path), lambda: None),
        responses=[batch(result_for("c1"))],
    )
    assert doc(out2)["claims"][0]["status"] == "VERIFIED"


def test_factory_builds_the_check_from_the_job_library_reference(tmp_path: Path) -> None:
    lib = library(tmp_path)
    ref = LibraryRef(lib[0], ls.head_sha(lib[0]))
    out, w = run(tmp_path, [quote_claim()], quotes=factory(lib, lambda: ref))
    assert one(out)["status"] == "VERIFIED" and w.llm.calls == 0


def test_library_missing_is_a_typed_error(tmp_path: Path) -> None:
    ref = LibraryRef(tmp_path / "no-such-library", "a" * 40)
    out, w = run(tmp_path, [quote_claim()], quotes=factory(library(tmp_path), lambda: ref))
    assert error_code(out) == "PERMANENT.MISSING_DEPENDENCY" and w.llm.calls == 0


def test_library_commit_sha_mismatch_is_a_typed_error(tmp_path: Path) -> None:
    lib = library(tmp_path)
    ref = LibraryRef(lib[0], "b" * 40)
    out, w = run(tmp_path, [quote_claim()], quotes=factory(lib, lambda: ref))
    assert error_code(out) == "PERMANENT.INPUT_INVALID" and w.llm.calls == 0


def test_dirty_library_tree_leaves_the_quote_unverified_and_never_verifies_it(
    tmp_path: Path,
) -> None:
    lib = library(tmp_path)
    repo = lib[0]
    ref = LibraryRef(repo, ls.head_sha(repo))
    target = repo / "phil" / "original.txt"
    target.write_text(target.read_text(encoding="utf-8") + "\nlocal edit\n", encoding="utf-8")
    out, w = run(tmp_path, [quote_claim()], quotes=factory(lib, lambda: ref))
    c = one(out)
    assert c["status"] == "UNVERIFIABLE" and c["reason_codes"] == ["QUOTE_NOT_ATTRIBUTABLE"]
    assert c["verification_verdict"] == "NEEDS_HUMAN_REVIEW" and w.llm.calls == 0
    assert doc(out)["revision_requests"][0]["action"] == "REMOVE_OR_REWORD"


def test_reader_failure_in_review_is_mapped_to_a_typed_result_not_an_escape(
    tmp_path: Path,
) -> None:
    class Broken:
        commit_sha = "c" * 40

        def read_text(self, relative_path: str) -> str:
            raise OSError("disk gone")

    _, records, index = library(tmp_path)
    broken = QuoteCheck(
        QuoteVerifier(records, Broken(), SETTINGS), records, index, job_date=ls.JOB_DATE
    )
    out, w = run(tmp_path, [quote_claim()], quotes=broken)
    assert one(out)["status"] == "UNVERIFIABLE" and w.llm.calls == 0


FAKE = "It is not time we lack but the will to keep it."  # 12 words, not in the library


def test_guard_sends_a_long_unchecked_quote_of_a_known_author_to_a_human(tmp_path: Path) -> None:
    sneaky = claim(
        1,
        claim_type="FACTUAL",
        quote=f'Testor wrote "{FAKE}"',
        normalized_claim="Testor wrote a sentence about time.",
        citation_refs=[REF],
    )
    out, w = run(tmp_path, [sneaky])
    c = one(out)
    assert c["status"] == "NEEDS_SUBSTANTIATION" and c["reason_codes"] == ["QUOTE_NOT_ATTRIBUTABLE"]
    assert w.llm.calls == 0


def test_guard_lets_a_proven_quote_continue_but_an_unknown_author_goes_to_a_human(
    tmp_path: Path,
) -> None:
    proven = claim(
        1,
        claim_type="FACTUAL",
        quote=f'Testor wrote "{GOOD}"',
        normalized_claim="Testor wrote a sentence about time.",
        citation_refs=[REF],
    )
    out, w = run(tmp_path, [proven], responses=[batch(result_for("c1"))])
    assert w.llm.calls == 1 and doc(out)["claims"][0]["local_id"] == "c1"
    # QUOTE-GUARD-2: a marked quote of nobody the library knows was a fail-open (the model was
    # asked); it now ends in human review, never in a model verdict
    stranger = claim(
        1,
        claim_type="FACTUAL",
        quote=f'The CEO said "{FAKE}"',
        normalized_claim="The CEO made a statement.",
        citation_refs=[REF],
    )
    out2, w2 = run(tmp_path, [stranger], responses=[batch(result_for("c1"))])
    c = one(out2)
    assert c["status"] == "NEEDS_SUBSTANTIATION" and c["reason_codes"] == ["QUOTE_NOT_ATTRIBUTABLE"]
    assert w2.llm.calls == 0


MARATHI_ATTRIBUTED = "टेस्टर यांनी लिहिले की वेळ कमी नसतो."  # INVENTED, no quotation marks
UNMARKED = [
    ("Testor wrote that time is short.", "Testor wrote a sentence about time."),
    ("Testor said time is short.", "A statement about time."),
    ("The CEO says the market is calm.", "A statement about the market."),
    (MARATHI_ATTRIBUTED, "टेस्टर यांचे विधान."),
    ("वेळ कमी आहे असे टेस्टर म्हणाले.", "टेस्टर यांचे विधान."),
]


@pytest.mark.parametrize(("quote", "norm"), UNMARKED)
def test_unmarked_attribution_goes_to_the_check_and_then_a_human_never_the_model(
    tmp_path: Path, quote: str, norm: str
) -> None:
    sneaky = claim(1, claim_type="FACTUAL", quote=quote, normalized_claim=norm, citation_refs=[REF])
    out, w = run(tmp_path, [sneaky], responses=[batch(result_for("c1"))])
    c = one(out)
    assert c["status"] == "NEEDS_SUBSTANTIATION" and c["reason_codes"] == ["QUOTE_NOT_ATTRIBUTABLE"]
    assert c["mode"] == "CODE_ONLY" and c["evidence"] == []
    assert w.llm.calls == 0


@pytest.mark.parametrize(
    "quote",
    [f'Testor wrote "{FAKE}"', f'The CEO said "{FAKE}"', 'टेस्टर म्हणाले "' + FAKE + '"'],
)
def test_without_a_quote_check_a_guarded_claim_is_a_typed_error_not_a_model_verdict(
    tmp_path: Path, quote: str
) -> None:
    sneaky = claim(
        1,
        claim_type="FACTUAL",
        quote=quote,
        normalized_claim="A statement about time.",
        citation_refs=[REF],
    )
    out, w = run(tmp_path, [sneaky], quotes=None, responses=[batch(result_for("c1"))])
    assert error_code(out) == "PERMANENT.MISSING_DEPENDENCY"
    assert out.error is not None and out.error.details is not None
    assert out.error.details.reason == "QUOTE_CHECK_NOT_CONFIGURED"
    assert w.llm.calls == 0


@pytest.mark.parametrize(
    ("quote", "norm"),
    [(UNMARKED[0][0], UNMARKED[0][1]), (MARATHI_ATTRIBUTED, "टेस्टर यांचे विधान.")],
)
def test_without_a_quote_check_an_unmarked_attribution_is_a_typed_error(
    tmp_path: Path, quote: str, norm: str
) -> None:
    sneaky = claim(1, claim_type="FACTUAL", quote=quote, normalized_claim=norm, citation_refs=[REF])
    out, w = run(tmp_path, [sneaky], quotes=None, responses=[batch(result_for("c1"))])
    assert error_code(out) == "PERMANENT.MISSING_DEPENDENCY" and w.llm.calls == 0


def test_factory_without_a_library_reference_refuses_a_guarded_claim_too(tmp_path: Path) -> None:
    sneaky = claim(
        1,
        claim_type="FACTUAL",
        quote=UNMARKED[0][0],
        normalized_claim=UNMARKED[0][1],
        citation_refs=[REF],
    )
    f = factory(library(tmp_path), lambda: None)
    out, w = run(tmp_path, [sneaky], quotes=f, responses=[batch(result_for("c1"))])
    assert error_code(out) == "PERMANENT.MISSING_DEPENDENCY" and w.llm.calls == 0


def test_ordinary_factual_claims_are_not_guarded_with_or_without_a_quote_check(
    tmp_path: Path,
) -> None:
    plain = claim(1, claim_type="FACTUAL")
    short_term = claim(  # a short term in quotation marks is not a quotation (below the config)
        2,
        claim_type="FACTUAL",
        quote='The "stoic" school began in Athens.',
        normalized_claim="The Stoic school began in Athens.",
    )
    for kw in ({}, {"quotes": None}):
        out, w = run(
            tmp_path,
            [plain, short_term],
            responses=[batch(result_for("c1"), result_for("c2"))],
            **kw,
        )
        assert [c["status"] for c in doc(out)["claims"]] == ["VERIFIED", "VERIFIED"]
        assert w.llm.calls == 1


@pytest.mark.parametrize(
    "quote",
    [
        "Seneca believed that time is the only thing we truly own.",
        "सेनेका असे मानत होता की वेळ आपली आहे.",
    ],
)
def test_reported_speech_goes_to_human_review_with_or_without_a_quote_check(
    tmp_path: Path, quote: str
) -> None:
    reported = claim(1, claim_type="FACTUAL", quote=quote, normalized_claim="A view of a person.")
    for kw in ({}, {"quotes": None}):
        out, w = run(tmp_path, [reported], responses=[batch(result_for("c1"))], **kw)
        c = one(out)
        assert c["status"] == "NEEDS_SUBSTANTIATION"
        assert c["reason_codes"] == ["QUOTE_NOT_ATTRIBUTABLE"] and c["mode"] == "CODE_ONLY"
        assert w.llm.calls == 0


def test_a_quote_split_across_two_claims_is_guarded_in_both(tmp_path: Path) -> None:
    first = claim(1, claim_type="FACTUAL", quote="He added “one two three")
    second = claim(2, claim_type="FACTUAL", quote="four five six seven” and left.")
    out, w = run(tmp_path, [first, second], responses=[batch(result_for("c1"), result_for("c2"))])
    assert [c["status"] for c in doc(out)["claims"]] == ["NEEDS_SUBSTANTIATION"] * 2
    assert w.llm.calls == 0
