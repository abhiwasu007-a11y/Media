# ruff: noqa: E501
"""SYNTHETIC Marathi fixtures of the real-chain dry run (plumbing, NOT quality, NOT book text).

Every sentence below is INVENTED for this test (a generic remark about time and learning). None of it
is taken from any book or from the private knowledge library (D12). The canned model responses of the
real agents are written in English (their own test fixtures); for a Devanagari job
(``mr-IN`` / ``hi-IN``) the helpers here replace the TEXT fields of those answers by Marathi
sentences, field by field, so that every deterministic check of the real agent still runs on real
Devanagari text (script check, term bracketing, character budgets, glyph coverage later in the chain).

The key term is written the way agent_05 section 6.4 requires: the local term followed by the English
term in brackets on every mention (the English word inside brackets is the only Latin text)."""

from typing import Any

MARATHI = "mr-IN"
ORD_MR = ["पहिला", "दुसरा", "तिसरा", "चौथा", "पाचवा", "सहावा", "सातवा", "आठवा"]
OPTION_MR = {"h1": "एक", "h2": "दोन", "h3": "तीन"}
SCENE_MR = ["पहिले", "दुसरे", "तिसरे"]

TERM_LOCAL = "मर्यादित वेळ"
"""Marathi label of the synthetic concept (agent_04 plan ``label``)."""
TERM_EN = "finite time"
"""English label (agent_04 plan ``label_en``)."""
NOTE_MR = "प्रत्येक माणसाला दिवसभर वापरण्यासाठी मर्यादित वेळ मिळतो आणि त्याचा वापर कसा करायचा हे त्यालाच ठरवावे लागते."
"""Invented Marathi research note (the note text of agent_04 in a Marathi run)."""


def is_devanagari_job(language: str | None) -> bool:
    return language is not None and language.split("-")[0] in {"mr", "hi"}


def bracketed(term_local: str, term_en: str) -> str:
    return f"{term_local} ({term_en})"


def localize_plan(plan: dict[str, Any], term_local: str, term_en: str) -> dict[str, Any]:
    """Replace the English text fields of a plan answer by invented Marathi sentences."""
    key = bracketed(term_local, term_en)
    for hook in plan["hooks"]:
        opt = OPTION_MR.get(hook["hook_id"], "एक")
        texts = (
            f"एका काल्पनिक उदाहरणात {key} स्पष्ट दिसतो, पर्याय {opt}.",
            f"{key} शिकणाऱ्यासाठी का महत्त्वाचा आहे, पर्याय {opt}?",
            f"आपण {key} कसा समजून घ्यायचा ते पाहू, पर्याय {opt}.",
        )
        for beat, text in zip(hook["beats"], texts, strict=True):
            beat["sentences"][0]["text"] = text
            if beat["concrete_example"] is not None:
                beat["concrete_example"] = "एक काल्पनिक उदाहरण"
        hook["rubric"]["rationale"] = "scored on the written rubric"
    tp = plan["title_promise"]
    tp["working_title_local"] = f"{key} खरोखर काय सांगतो"
    tp["promise_statement"] = f"{key} म्हणजे काय आणि काय नाही ते तुम्हाला समजेल."
    for i, sec in enumerate(plan["sections"]):
        sec["heading_local"] = f"भाग {ORD_MR[i]}"
    plan["description_draft"] = f"काल्पनिक उदाहरणांसह {key} यावर एक छोटा धडा."
    plan["thumbnail_brief"]["text_idea_local"] = f"{key}?"
    plan["thumbnail_brief"]["subject_idea"] = "a simple sketch of an hourglass"
    return plan


def localize_section(section: dict[str, Any], n: int) -> dict[str, Any]:
    """Replace the English sentences of a section answer (``n`` = 1-based section number)."""
    word = ORD_MR[n - 1]
    for j, scene in enumerate(section["scenes"]):
        scene["sentences"][0]["text"] = (
            f"हा धड्याचा {word} भाग आहे. {SCENE_MR[j]} दृश्य कल्पना सोपी ठेवते."
        )
        scene["sentences"][1]["text"] = f"मग आपण {word} भागावर क्षणभर थांबतो."
    return section
BRAND_FONT_KEY = "mukta_regular"
"""Pinned brand font of the repo manifest (D10): Mukta with the Noto fallback."""
