"""Deterministic assertions (27 section 6.2 item 1). Each applies only when the case asks for it."""

import json
from dataclasses import dataclass

from jsonschema import Draft202012Validator

from amw_evals.findings import JsonObject


@dataclass(frozen=True)
class AssertionResult:
    passed: bool
    detail: str = ""

    def as_json(self) -> JsonObject:
        return {"passed": self.passed, "detail": self.detail}


def _strings(value: object) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def collect_rule_ids(output: object) -> set[str]:
    """Every rule id the output flags: any 'rule_id' value plus refusal.violated_rule_ids."""
    ids: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            rid = node.get("rule_id")
            if isinstance(rid, str):
                ids.add(rid)
            for k, v in node.items():
                if k == "violated_rule_ids":
                    ids.update(_strings(v))
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(output)
    return ids


def verdict_of(output: object) -> str | None:
    if not isinstance(output, dict):
        return None
    overall = output.get("overall")
    if isinstance(overall, dict) and isinstance(overall.get("proposed_verdict"), str):
        return str(overall["proposed_verdict"])
    pv = output.get("proposed_verdict")
    return pv if isinstance(pv, str) else None


def refusal_reason_of(output: object) -> str | None:
    if isinstance(output, dict):
        refusal = output.get("refusal")
        if isinstance(refusal, dict) and isinstance(refusal.get("reason"), str):
            return str(refusal["reason"])
    return None


def check_offsets(output: object, payload: JsonObject) -> AssertionResult | None:
    """quote == segment.text[char_start:char_end] for every claim (claims + segments shapes)."""
    if not isinstance(output, dict) or not isinstance(output.get("claims"), list):
        return None
    segments = payload.get("segments")
    if not isinstance(segments, list):
        return None
    texts = {
        s["segment_id"]: s["text"]
        for s in segments
        if isinstance(s, dict)
        and isinstance(s.get("segment_id"), str)
        and isinstance(s.get("text"), str)
    }
    bad: list[str] = []
    for claim in output["claims"]:
        if not isinstance(claim, dict) or "char_start" not in claim:
            continue
        sid = claim.get("segment_id")
        text = texts.get(sid) if isinstance(sid, str) else None
        start, end, quote = claim.get("char_start"), claim.get("char_end"), claim.get("quote")
        if (
            text is None
            or not isinstance(start, int)
            or not isinstance(end, int)
            or text[start:end] != quote
        ):
            bad.append(str(claim.get("local_id")))
    return AssertionResult(not bad, f"offset mismatch in {bad}" if bad else "")


def run_assertions(
    output: object,
    expected: JsonObject,
    payload: JsonObject,
    output_schema: JsonObject | None,
) -> dict[str, AssertionResult]:
    results: dict[str, AssertionResult] = {}

    if output_schema is not None:
        errs = sorted(
            Draft202012Validator(output_schema).iter_errors(output),
            key=lambda e: [str(p) for p in e.absolute_path],
        )
        if errs:
            where = "/".join(str(p) for p in errs[0].absolute_path) or "(root)"
            msg = f"{len(errs)} error(s); first at {where}: {errs[0].message[:100]}"
            results["schema"] = AssertionResult(False, msg)
        else:
            results["schema"] = AssertionResult(True)
        required = output_schema.get("required")
        if isinstance(output, dict) and isinstance(required, list):
            absent = [k for k in required if isinstance(k, str) and k not in output]
            results["required_fields"] = AssertionResult(
                not absent, f"absent: {absent}" if absent else ""
            )
        else:
            results["required_fields"] = AssertionResult(False, "output is not an object")

    offsets = check_offsets(output, payload)
    if offsets is not None:
        results["offsets"] = offsets

    banned = _strings(expected.get("banned")) + _strings(expected.get("must_not_contain"))
    if banned:
        blob = json.dumps(output, ensure_ascii=False).lower()
        hits = [b for b in banned if b.lower() in blob]
        results["banned_phrases"] = AssertionResult(not hits, f"present: {hits}" if hits else "")

    flagged = collect_rule_ids(output)
    must = _strings(expected.get("must_flag")) + _strings(expected.get("must_flag_rules"))
    must += _strings(expected.get("rule_ids_all"))
    if must:
        lacking = sorted(set(must) - flagged)
        results["expected_flags"] = AssertionResult(
            not lacking, f"not flagged: {lacking}" if lacking else ""
        )
    forbidden = _strings(expected.get("must_not_flag"))
    if forbidden:
        wrong = sorted(set(forbidden) & flagged)
        results["forbidden_flags"] = AssertionResult(
            not wrong, f"flagged: {wrong}" if wrong else ""
        )

    if isinstance(expected.get("verdict"), str):
        got = verdict_of(output)
        results["verdict"] = AssertionResult(
            got == expected["verdict"], f"expected {expected['verdict']}, got {got}"
        )
    if "refusal_reason" in expected:
        got_reason = refusal_reason_of(output)
        results["refusal_reason"] = AssertionResult(
            got_reason == expected["refusal_reason"],
            f"expected {expected['refusal_reason']}, got {got_reason}",
        )
    return results
