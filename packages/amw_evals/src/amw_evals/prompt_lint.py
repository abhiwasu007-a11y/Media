"""Prompt lint per 27 section 4.4 and prompts/README.md."""

import itertools
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from amw_evals.findings import Finding, JsonObject
from amw_evals.prompt_doc import (
    AGENT_DIR_RE,
    NAME_RE,
    REQUIRED_SECTIONS,
    VAR_RE,
    parse_prompt,
)

DIALECT = "https://json-schema.org/draft/2020-12/schema"
HEADER_FIELDS = (
    "Prompt ID",
    "Task type",
    "Status",
    "Input payload schema",
    "Output payload schema",
    "Eval set",
    "Config keys",
)
DATE_PATTERNS = (
    re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b"),
    re.compile(
        r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
        r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.? "
        r"[0-9]{1,2}(?:st|nd|rd|th)?,? "
        r"(?:19|20)\d{2}\b"
    ),
    re.compile(
        r"\b[0-9]{1,2}(?:st|nd|rd|th)? "
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* (?:19|20)\d{2}\b"
    ),
    re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\s?[AaPp]\.?[Mm]\b"),
    re.compile(r"\b(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d\b"),
)
BANNED_TERMS = re.compile(
    r"\b(?:claude|anthropic|openai|gpt-?[0-9a-z.]*|gemini|llama|mistral|elevenlabs|"
    r"sk-[A-Za-z0-9]{8,})\b",
    re.IGNORECASE,
)
PRICE = re.compile(r"[$€£₹]\s?[0-9]|\b[0-9]+(?:\.[0-9]+)?\s?(?:USD|INR|EUR)\b")


def _f(rel: str, code: str, msg: str) -> Finding:
    return Finding(rel, code, msg)


def _check_schema(
    label: str, text: str | None, rel: str, code: str
) -> tuple[JsonObject | None, list[Finding]]:
    if text is None:
        return None, []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, [_f(rel, f"{code}-PARSE", f"{label} is not valid JSON: {exc.msg}")]
    if not isinstance(data, dict):
        return None, [_f(rel, f"{code}-PARSE", f"{label} is not a JSON object")]
    found: list[Finding] = []
    if data.get("$schema") != DIALECT:
        found.append(_f(rel, f"{code}-DIALECT", f"{label} $schema must be {DIALECT}"))
    try:
        Draft202012Validator.check_schema(data)
    except SchemaError as exc:
        found.append(
            _f(
                rel,
                f"{code}-INVALID",
                f"{label} is not a valid 2020-12 schema: {exc.message[:120]}",
            )
        )
        return None, found
    return data, found


def _validate_instance(
    schema: JsonObject, text: str, label: str, rel: str, code: str
) -> list[Finding]:
    try:
        instance = json.loads(text)
    except json.JSONDecodeError as exc:
        return [_f(rel, "P-EXAMPLE-JSON", f"{label} is not valid JSON: {exc.msg}")]
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda e: [str(p) for p in e.absolute_path],
    )
    if not errors:
        return []
    first = errors[0]
    where = "/".join(str(p) for p in first.absolute_path) or "(root)"
    return [
        _f(
            rel,
            code,
            f"{label} does not validate ({len(errors)} error(s)); "
            f"first at {where}: {first.message[:100]}",
        )
    ]


def lint_prompt(path: Path, rel: str) -> list[Finding]:
    out: list[Finding] = []
    m = NAME_RE.match(path.name)
    if not m or not AGENT_DIR_RE.match(path.parent.name):
        out.append(
            _f(
                rel,
                "P-NAME",
                "file must be prompts/<agent>/<task>.v<N>.md with an agent package folder",
            )
        )
    doc = parse_prompt(path)

    # header table
    for field_name in HEADER_FIELDS:
        if not any(k.lower() == field_name.lower() for k in doc.header):
            out.append(_f(rel, "P-HEADER", f"header table lacks row '{field_name}'"))
    pid = next((v for k, v in doc.header.items() if k.lower() == "prompt id"), None)
    expected = doc.expected_prompt_id
    if pid and expected and pid.strip("`") != expected:
        out.append(
            _f(rel, "P-ID", f"Prompt ID '{pid.strip('`')}' does not match path ({expected})")
        )

    # sections present and in order
    positions: list[tuple[str, int]] = []
    titles = [s.title.lower() for s in doc.sections]
    for name in REQUIRED_SECTIONS:
        idx = next((i for i, t in enumerate(titles) if t.startswith(name.lower())), None)
        if idx is None:
            out.append(_f(rel, "P-SECTIONS", f"missing section '## {name}'"))
        else:
            positions.append((name, idx))
    for (a, ia), (b, ib) in itertools.pairwise(positions):
        if ib < ia:
            out.append(_f(rel, "P-SECTIONS", f"section '{b}' must come after '{a}'"))

    # forbidden content
    seen: set[str] = set()
    for pat in DATE_PATTERNS:
        for hit in pat.findall(doc.text):
            if hit not in seen:
                seen.add(hit)
                out.append(_f(rel, "P-DATE", f"calendar date or clock time in prompt: '{hit}'"))
    for hit in sorted({h.lower() for h in BANNED_TERMS.findall(doc.text)}):
        out.append(_f(rel, "P-BANNED-TERM", f"model/provider name or key-like string: '{hit}'"))
    if PRICE.search(doc.text):
        out.append(_f(rel, "P-PRICE", "price or currency amount in prompt"))

    # variables
    inputs = doc.section("Inputs")
    declared = set(VAR_RE.findall("\n".join(inputs.lines))) if inputs else set()
    body = doc.text.replace("\n".join(inputs.lines), "") if inputs else doc.text
    used = set(VAR_RE.findall(body))
    used -= {"rule_pack", "config"}
    for var in sorted(used - declared):
        out.append(
            _f(rel, "P-VAR-UNDECLARED", f"variable {{{{{var}}}}} used but not declared in Inputs")
        )

    # schemas
    out_text = doc.output_schema_text()
    if out_text is None:
        out.append(_f(rel, "P-SCHEMA-MISSING", "no ```json block under '## Output JSON Schema'"))
    out_schema, f1 = _check_schema("Output JSON Schema", out_text, rel, "P-SCHEMA")
    out.extend(f1)
    if out_schema is not None and '"refusal"' not in (out_text or ""):
        out.append(_f(rel, "P-REFUSAL", "output schema has no 'refusal' property (27 section 4.3)"))
    in_text = doc.input_schema_text()
    in_schema, f2 = _check_schema("Input payload schema", in_text, rel, "P-INSCHEMA")
    out.extend(f2)

    # worked examples
    if not 2 <= len(doc.examples) <= 3:
        out.append(
            _f(rel, "P-EXAMPLES-COUNT", f"{len(doc.examples)} worked example(s); 2-3 required")
        )
    for ex in doc.examples:
        label = ex.title.split("—")[0].strip()
        if not ex.output_blocks:
            out.append(_f(rel, "P-EXAMPLE-OUTPUT", f"{label}: no 'Output:' json block"))
        for ob in ex.output_blocks:
            if out_schema is None:
                try:
                    json.loads(ob.text)
                except json.JSONDecodeError as exc:
                    out.append(
                        _f(rel, "P-EXAMPLE-JSON", f"{label} output is not valid JSON: {exc.msg}")
                    )
            else:
                out.extend(
                    _validate_instance(
                        out_schema, ob.text, f"{label} output", rel, "P-EXAMPLE-INVALID"
                    )
                )
        for in_blk in ex.input_blocks:
            if ex.input_inline:
                continue
            if in_schema is None:
                try:
                    json.loads(in_blk.text)
                except json.JSONDecodeError as exc:
                    out.append(
                        _f(rel, "P-EXAMPLE-JSON", f"{label} input is not valid JSON: {exc.msg}")
                    )
            else:
                out.extend(
                    _validate_instance(
                        in_schema, in_blk.text, f"{label} input", rel, "P-EXAMPLE-INPUT-INVALID"
                    )
                )
    return out


def prompt_files(root: Path) -> list[Path]:
    base = root / "prompts"
    if not base.is_dir():
        return []
    return sorted(
        p for p in base.glob("*/*.md") if not p.name.startswith("_") and p.name != "README.md"
    )


def lint_prompts(root: Path, rel_base: Path | None = None) -> list[Finding]:
    rel_base = rel_base or root.parent
    findings: list[Finding] = []
    for p in prompt_files(root):
        findings.extend(lint_prompt(p, p.relative_to(rel_base).as_posix()))
    return sorted(findings)
