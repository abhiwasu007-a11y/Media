"""Recorded model responses for the claim-extraction eval cases (hand-authored fixtures).

``docs/v4/evals/agent_06_fact_checker/claim_extraction/cases.jsonl`` carries inputs and expected
verdicts but no model output, so each fixture below is the JSON the model is expected to return
for the case, written from the worked examples of ``claim_extraction.v1`` and its rules. They are
fixtures, not provider recordings: they let the deterministic post-checks (D1-D11) run end to end.
Offsets are computed from the case's own segment text, never typed.
"""

# ruff: noqa: E501

import json
from typing import Any

R = "BLOCKING"
W = "WARNING"
H, C, F = "HISTORICAL", "CURRENT", "FUTURE"


def claim(
    quote: str,
    ctype: str,
    *,
    seg: str = "s1",
    time: str = H,
    inst: str | None = None,
    chart: str | None = None,
    cite: bool = False,
    req: bool = False,
    flags: tuple[tuple[str, str], ...] = (),
) -> dict[str, Any]:
    return {
        "quote": quote,
        "ctype": ctype,
        "seg": seg,
        "time": time,
        "inst": inst,
        "chart": chart,
        "cite": cite,
        "req": req,
        "flags": flags,
    }


# case_id -> claim specs (a ``*`` quote means the whole segment without its final period)
SPECS: dict[str, list[dict[str, Any]]] = {
    "AK-01": [
        claim(
            "price made a lower low while RSI made a higher low",
            "HISTORICAL_MARKET",
            inst="NIFTY",
            chart="chart_1",
        ),
        claim(
            "This bullish divergence was followed by a rally",
            "HISTORICAL_MARKET",
            inst="NIFTY",
            chart="chart_1",
        ),
        claim(
            "the same pattern failed later on that chart when price kept falling",
            "HISTORICAL_MARKET",
            inst="NIFTY",
            chart="chart_1",
        ),
    ],
    "AK-02": [
        claim("NIFTY looks weak", "FORWARD_VIEW", time=C, inst="NIFTY", flags=(("FIN-R3", R),)),
        claim(
            "sell the 24,000 call this week",
            "RECOMMENDATION",
            time=F,
            inst="NIFTY",
            flags=(("FIN-R1", R), ("FIN-R2", R), ("FIN-R3", R)),
        ),
    ],
    "AK-03": [
        claim("My strategy made 18% last month", "PERFORMANCE_CLAIM", flags=(("FIN-R6", R),))
    ],
    "AK-04": [
        claim(
            "Open an account with broker Y via this link",
            "PROMOTION",
            time=C,
            flags=(("FIN-R8", R),),
        )
    ],
    "HN-05": [claim("*", "DEFINITION", time="TIMELESS")],
    "HN-06": [claim("*", "HYPOTHETICAL_EXAMPLE", time="TIMELESS")],
    "HN-07": [claim("*", "FACTUAL", time="TIMELESS", req=True, cite=True)],
    "HN-08": [claim("*", "FACTUAL", time="TIMELESS", req=True, cite=True)],
    "HN-09": [claim("*", "PROMOTION", time=C)],
    "HN-10": [claim("*", "FACTUAL", time="TIMELESS", req=True)],
    "HN-11": [claim("buy now before it is too late", "QUOTED_THIRD_PARTY", time=C)],
    "EDGE-12": [
        claim(
            "buy ABC Industries today, it will double",
            "QUOTED_THIRD_PARTY",
            time=C,
            inst="ABC Industries",
            flags=(("FIN-R1", W),),
        )
    ],
    "EDGE-13": [
        claim(
            "If NIFTY breaks 24,000 this week, the next stop could be 24,500",
            "PRICE_LEVEL",
            time=F,
            inst="NIFTY",
            flags=(("FIN-R2", R), ("FIN-R3", R)),
        )
    ],
    "EDGE-14": [
        claim(
            "BANKNIFTY moved in a sharp V-shaped recovery",
            "HISTORICAL_MARKET",
            inst="BANKNIFTY",
            chart="chart_2",
        )
    ],
    "EDGE-15": [claim("*", "HISTORICAL_MARKET", inst="NIFTY", chart="chart_3")],
    "EDGE-16": [claim("*", "PROMOTION", time=F, flags=(("FIN-R4", R),))],
    "EDGE-17": [claim("*", "PROMOTION", time=C, flags=(("FIN-R5", R),))],
    "EDGE-18": [claim("*", "TESTIMONIAL", flags=(("FIN-R7", R),))],
    "EDGE-19": [claim("*", "STATISTICAL", flags=(("FIN-R6", W),))],
    "EDGE-20": [
        claim(
            "on this historical chart we wait for the setup taught in course chapter 7 before considering an entry",
            "PROMOTION",
            time="TIMELESS",
            chart="chart_1",
        )
    ],
    "EDGE-21": [
        claim(
            "on this historical chart we wait for the setup taught in course chapter 7 before considering an entry",
            "PROMOTION",
            time="TIMELESS",
            chart="chart_1",
            flags=(("FIN-R12", W),),
        )
    ],
    "EDGE-22": [
        claim(
            "Buy BANKNIFTY futures tomorrow morning",
            "RECOMMENDATION",
            time=F,
            inst="BANKNIFTY",
            flags=(("FIN-R1", R), ("FIN-R3", R)),
        )
    ],
    "EDGE-23": [
        claim(
            "Kal Bank Nifty ka 52000 put kharid lo, pakka profit hoga",
            "RECOMMENDATION",
            time=F,
            inst="Bank Nifty",
            flags=(("FIN-R1", R), ("FIN-R2", R), ("FIN-R3", R)),
        )
    ],
    "EDGE-24": [
        claim(
            "जुन्या NIFTY चार्टवर किंमत खालचा तळ करत होती, पण RSI वरचा तळ करत होता",
            "HISTORICAL_MARKET",
            inst="NIFTY",
            chart="chart_1",
        ),
        claim("याला bullish divergence म्हणतात", "DEFINITION", time="TIMELESS"),
    ],
    "EDGE-25": [
        claim(
            "उद्या NIFTY चा 24,000 कॉल विका",
            "RECOMMENDATION",
            time=F,
            inst="NIFTY",
            flags=(("FIN-R1", R), ("FIN-R3", R)),
        )
    ],
    "HN-27": [
        claim(
            "This video is sponsored by ChartPad, a charting software",
            "PROMOTION",
            time=C,
            flags=(("FIN-R8", W),),
        )
    ],
    "HN-28": [claim("*", "PROMOTION", time=C)],
    "EDGE-29": [claim("*", "FACTUAL", time="TIMELESS", req=True)],
    "MIX-30": [
        claim("*", "DEFINITION", time="TIMELESS"),
        claim(
            "So buy the NIFTY weekly call tomorrow and hold it",
            "RECOMMENDATION",
            seg="s2",
            time=F,
            inst="NIFTY",
            flags=(("FIN-R1", R), ("FIN-R3", R)),
        ),
    ],
    "EDGE-31": [
        claim(
            "a double bottom formed before a rally",
            "HISTORICAL_MARKET",
            inst="BANKNIFTY",
            chart="chart_1",
        ),
        claim(
            "BANKNIFTY should rally again from here",
            "FORWARD_VIEW",
            time=F,
            inst="BANKNIFTY",
            flags=(("FIN-R13", R),),
        ),
    ],
    "HN-32": [
        claim(
            "a double bottom formed before a rally",
            "HISTORICAL_MARKET",
            inst="BANKNIFTY",
            chart="chart_1",
        ),
        claim(
            "it tells us nothing about what BANKNIFTY will do next",
            "OPINION",
            time="TIMELESS",
            inst="BANKNIFTY",
        ),
    ],
    "HN-33": [claim("*", "HISTORICAL_MARKET", inst="NIFTY", chart="chart_1")],
    "EDGE-34": [claim("*", "DEFINITION", time="TIMELESS", chart="chart_4")],
    "EDGE-35": [claim("*", "STATISTICAL", time="TIMELESS", req=True, cite=True)],
}
MANUAL = {"REF-26"}
"""Cases whose recorded response is a refusal (built by ``refusal_response``)."""


def refusal_response() -> str:
    return json.dumps(
        {
            "claims": [],
            "overall": {
                "proposed_verdict": "NEEDS_HUMAN_REVIEW",
                "blocking_rule_ids": [],
                "needs_human_review_reasons": ["Script contains only placeholder text."],
            },
            "refusal": {
                "reason": "INSUFFICIENT_INPUT",
                "message": "The script has no content to analyse.",
                "missing_inputs": ["segments[].text"],
                "violated_rule_ids": [],
            },
        }
    )


def recorded_response(case: dict[str, Any]) -> str:
    """The recorded model JSON for one eval case (one batch)."""
    case_id = case["case_id"]
    if case_id in MANUAL:
        return refusal_response()
    inp = case["input"]
    segs = {s["segment_id"]: s["text"] for s in inp["segments"]}
    cites = [c["citation_ref"] for c in inp["available_citations"]]
    claims: list[dict[str, Any]] = []
    for n, spec in enumerate(SPECS[case_id], 1):
        text = segs[spec["seg"]]
        quote = text.rstrip(".") if spec["quote"] == "*" else spec["quote"]
        start = text.index(quote)
        flags = [{"rule_id": r, "severity": s, "evidence": quote[:80]} for r, s in spec["flags"]]
        verdict = (
            "BLOCKED"
            if any(s == R for _, s in spec["flags"])
            else "NEEDS_HUMAN_REVIEW"
            if flags
            else "ALLOWED"
        )
        claims.append(
            {
                "local_id": f"c{n}",
                "segment_id": spec["seg"],
                "char_start": start,
                "char_end": start + len(quote),
                "quote": quote,
                "normalized_claim": quote[:300],
                "claim_type": spec["ctype"],
                "time_reference_kind": spec["time"],
                "instrument": spec["inst"],
                "chart_data_ref": spec["chart"],
                "requires_citation": spec["req"],
                "citation_refs": cites[:1] if spec["cite"] else [],
                "rule_flags": flags,
                "proposed_verdict": verdict,
                "rationale": "Recorded fixture response.",
            }
        )
    overall = "ALLOWED"
    for c in claims:
        if c["proposed_verdict"] == "BLOCKED":
            overall = "BLOCKED"
        elif c["proposed_verdict"] == "NEEDS_HUMAN_REVIEW" and overall == "ALLOWED":
            overall = "NEEDS_HUMAN_REVIEW"
    return json.dumps(
        {
            "claims": claims,
            "overall": {
                "proposed_verdict": overall,
                "blocking_rule_ids": [],
                "needs_human_review_reasons": [],
            },
            "refusal": None,
        },
        ensure_ascii=False,
    )
