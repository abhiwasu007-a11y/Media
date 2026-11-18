"""Adversarial tests of the copy guard (IN-08 / YTG-R9 copyright protection).

Every case states its expected outcome under the PROPOSED thresholds of ``conftest.PROPOSED``
(REQUIRES REVIEW owner/counsel: they are proposals, not product values). ``CAUGHT`` means the
note must fail ``COPY_OVERLAP``; ``ALLOWED`` documents what the proposed thresholds tolerate.
"""
# ruff: noqa: E501, PT018, RUF001

from dataclasses import replace

import pytest

from agent_04_research_knowledge.guards.copy_guard import CopyGuard, words_of
from agent_04_research_knowledge.models.enums import NoteProblem, ReliabilityTier
from agent_04_research_knowledge.steps.assemble import enforce_pack_coverage
from agent_04_research_knowledge.steps.notes import NoteLimits, NoteValidator
from amw_core.text_normalise import Script, dominant_script
from tests.agents.agent_04_research_knowledge.conftest import PROPOSED
from tests.agents.agent_04_research_knowledge.test_guards import note
from tests.agents.agent_04_research_knowledge.test_steps import concept_ev, vnote

pytestmark = pytest.mark.unit
EN = (
    "A stop loss is an order placed in advance that closes a position once price reaches a chosen "
    "level against it. Traders often move the level further away after entry, which removes the "
    "protection the order was meant to give."
)
MR = (
    "स्टॉप-लॉस म्हणजे किंमत ठरावीक पातळीवर आली की व्यवहार आपोआप बंद करणारी आधी दिलेली ऑर्डर होय. "
    "अनेक व्यापारी प्रवेशानंतर ही पातळी दूर हलवतात आणि त्यामुळे संरक्षण नाहीसे होते."
)
HI = (
    "ख़तरा कम करने के लिए पहले से तय स्तर पर सौदा बंद करने वाला आदेश स्टॉप लॉस कहलाता है "
    "और यह सँभालना आसान बनाता है तथा नुकसान सीमित रखता है।"
)
GUARD = CopyGuard()
ZWSP, ZWNJ, ZWJ, SHY = chr(0x200B), chr(0x200C), chr(0x200D), chr(0xAD)
CGJ, VS16, ACUTE, RLO = chr(0x34F), chr(0xFE0F), chr(0x301), chr(0x202E)
TAGS = "".join(chr(0xE0020 + i) for i in range(3))


def per_word(text: str, ch: str) -> str:
    """The evasion of the review: one invisible character inside every word."""
    return " ".join(w[:1] + ch + w[1:] for w in text.split())


def caught(candidate: str, passage: str) -> bool:
    res = GUARD.check(candidate, passage, PROPOSED)
    return not res.passed and res.skipped_reason is None


@pytest.mark.parametrize(
    "evade",
    [
        lambda t: t,
        lambda t: per_word(t, ZWSP),
        lambda t: per_word(t, ZWJ),
        lambda t: per_word(t, ZWNJ),
        lambda t: per_word(t, SHY),
        lambda t: per_word(t, CGJ),
        lambda t: per_word(t, VS16),
        lambda t: per_word(t, ACUTE),
        lambda t: per_word(t, RLO),
        lambda t: per_word(t, TAGS),
        lambda t: t.upper(),
        lambda t: t.replace("o", "о").replace("a", "а").replace("e", "е"),
        lambda t: t.replace("o", "ο").replace("p", "р"),
        lambda t: "".join(chr(ord(c) + 0xFEE0) if "!" < c <= "~" else c for c in t),
        lambda t: "‮" + t + "﻿",
    ],
    ids=[
        "plain",
        "zwsp",
        "zwj",
        "zwnj",
        "soft-hyphen",
        "cgj",
        "vs16",
        "acute",
        "rlo",
        "tags",
        "upper",
        "cyrillic",
        "greek",
        "fullwidth",
        "bidi-bom",
    ],
)
def test_english_verbatim_copy_with_evasions_is_caught(evade) -> None:  # type: ignore[no-untyped-def]
    assert caught(evade(EN), EN)


@pytest.mark.parametrize(
    "evade",
    [
        lambda t: t,
        lambda t: per_word(t, ZWSP),
        lambda t: per_word(t, ZWJ),
        lambda t: per_word(t, ZWNJ),
        lambda t: per_word(t, SHY),
        lambda t: per_word(t, CGJ),
        lambda t: per_word(t, VS16),
        lambda t: per_word(t, RLO),
        lambda t: per_word(t, TAGS),
        lambda t: t.replace("।", "|").replace(".", "।"),
    ],
    ids=["plain", "zwsp", "zwj", "zwnj", "soft-hyphen", "cgj", "vs16", "rlo", "tags", "danda"],
)
def test_devanagari_verbatim_copy_with_evasions_is_caught(evade) -> None:  # type: ignore[no-untyped-def]
    assert caught(evade(MR), MR)
    assert caught(evade(HI), HI)


def test_devanagari_variant_spellings_fold_together() -> None:
    nukta = HI.replace("ख़", "ख़")  # precomposed nukta letter
    plain = HI.replace("ख़", "ख")  # nukta dropped
    chandra = HI.replace("सँभालना", "संभालना")  # chandrabindu vs anusvara
    for variant in (nukta, plain, chandra):
        assert words_of(variant) == words_of(HI)
        assert caught(variant, HI)


def test_zero_width_characters_are_removed_not_split() -> None:
    assert words_of(f"st{ZWSP}op{SHY} l{ZWJ}oss") == ["stop", "loss"]
    assert words_of("स्टॉ‍प ल‌ॉस") == words_of("स्टॉप लॉस")


def test_script_is_decided_by_text_not_tags() -> None:
    assert dominant_script(MR) == dominant_script(HI) is Script.DEVANAGARI
    assert (
        dominant_script("pаss") is Script.LATIN
    )  # a Cyrillic homoglyph does not change the script
    res = GUARD.check(MR, MR, PROPOSED)
    assert res.skipped_reason is None and not res.passed  # even with identical text
    assert GUARD.check(HI.replace("स्टॉप लॉस", "स्टॉप-लॉस"), MR, PROPOSED).skipped_reason is None
    cross = GUARD.check("A stop loss closes a position at a preset level.", MR, PROPOSED)
    assert cross.skipped_reason == "CROSS_LANGUAGE" and cross.passed


WORDS = EN.split()


def one_word_changed_in_eight() -> str:
    out = list(WORDS)
    for i in range(3, len(out), 8):
        out[i] = "zzzz"
    return " ".join(out)


def filler_inserted() -> str:
    out: list[str] = []
    for i, w in enumerate(WORDS):
        out.append(w)
        if i % 4 == 3:
            out.append("really")
    return " ".join(out)


def sentences_reordered() -> str:
    first, second = EN.split(". ", 1)
    return second.rstrip(".") + ". " + first


def synonym_every_third() -> str:
    return " ".join("thing" if i % 3 == 2 else w for i, w in enumerate(WORDS))


@pytest.mark.parametrize(
    ("name", "make", "expected_caught"),
    [
        ("one word changed in eight", one_word_changed_in_eight, True),  # fuzzy run + LCS
        ("filler words inserted", filler_inserted, True),  # LCS ratio
        ("sentences reordered", sentences_reordered, True),  # verbatim run / containment
        ("synonym every third word", synonym_every_third, True),  # LCS ratio
        (
            "first half verbatim, rest own words",
            lambda: (
                " ".join(WORDS[:14])
                + " and then a different tale about discipline is told in a new way"
            ),
            True,
        ),
        # ALLOWED by the proposed thresholds: short echoes of common phrases, own sentence
        (
            "two short echoes in an own sentence",
            lambda: (
                "Traders place an order placed in advance when a plan needs a level and then review what the order was meant to give them."
            ),
            False,
        ),
        (
            "independent paraphrase",
            lambda: (
                "An exit instruction set beforehand ends a trade automatically when the market turns past a trader's chosen limit."
            ),
            False,
        ),
    ],
)
def test_evasion_outcomes_under_proposed_thresholds(name: str, make, expected_caught: bool) -> None:  # type: ignore[no-untyped-def]
    assert caught(make(), EN) is expected_caught, name


def test_marathi_light_paraphrase_and_reordering() -> None:
    words = MR.split()
    changed = " ".join("काहीतरी" if i % 8 == 3 else w for i, w in enumerate(words))
    assert caught(changed, MR)
    first, second = MR.split("। ", 1) if "। " in MR else MR.split(". ", 1)
    assert caught(second + " " + first, MR)


# ---- validator level: language tags no longer matter, pool, aggregate ------------------------------
LIMITS = NoteLimits(300, PROPOSED, 0.5)


def test_note_validator_catches_devanagari_copy_and_rejects_non_latin_notes() -> None:
    v = NoteValidator()
    copied = v.validate(note(MR[:140], statement_kind="DEFINITION"), MR, LIMITS)
    assert not copied.passed and copied.problem is NoteProblem.COPY_OVERLAP
    own = "Marathi wording about an order that exits a trade at a preset level."
    assert v.validate(
        note(own), MR, LIMITS
    ).passed  # an English note of a Marathi passage: WARN path
    non_latin = v.validate(note("पूर्णपणे वेगळ्या शब्दांत मांडलेला एक नवा विचार मांडला आहे."), MR, LIMITS)
    assert not non_latin.passed and non_latin.problem is NoteProblem.AMBIGUOUS


def test_note_is_checked_against_every_passage_of_the_retrieval_set() -> None:
    other = "Sizing a position means dividing the money at risk by the distance to the stop level, which gives the number of units to trade."
    candidate = note(other[:110])
    v = NoteValidator()
    assert v.validate(candidate, EN, LIMITS).passed  # cited passage alone: not seen
    res = v.validate(candidate, EN, LIMITS, pool=[EN, other])
    assert not res.passed and res.problem is NoteProblem.COPY_OVERLAP


def test_aggregate_rebuild_of_one_passage_by_several_notes_is_stopped() -> None:
    words = EN.split()
    own = "so the idea here is mostly about keeping discipline when plans meet markets"
    pieces = [" ".join(words[i : i + 5]) + " " + own for i in range(0, len(words) - 4, 5)]
    # each note alone is under every per-note threshold ...
    assert all(GUARD.check(p, EN, PROPOSED).passed for p in pieces)
    notes = []
    for i, piece in enumerate(pieces):
        base = vnote(chr(97 + i), "DEFINITION", ReliabilityTier.B_PUBLISHED)
        notes.append(
            replace(
                base,
                passage=replace(base.passage, text=EN),
                note=base.note.model_copy(update={"note": piece}),
            )
        )
    ce = concept_ev(["DEFINITION"], list(notes))
    # ... together they rebuild the passage: the pack-level check removes notes
    removed = enforce_pack_coverage([ce], PROPOSED.ngram_n, 0.5)
    assert removed >= 1 and ce.dropped and len(ce.notes) < len(notes)
    assert all(d.problem is NoteProblem.COPY_OVERLAP for d in ce.dropped)
    kept_cover = enforce_pack_coverage([ce], PROPOSED.ngram_n, 0.5)
    assert kept_cover == 0  # now under the limit: nothing more is removed
