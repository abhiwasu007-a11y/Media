"""Eval dataset lint per evals/README.md section 2 and 27 section 6.1."""

import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

from amw_evals.findings import Finding, JsonObject
from amw_evals.prompt_doc import NAME_RE, PromptDoc, parse_prompt

CATEGORIES = {"ANSWER_KEY", "HARD_NEGATIVE", "EDGE", "REFUSAL", "POSITIVE"}
BASE_KEYS = ("case_id", "category", "description", "input", "expected", "notes")
MIN_LLM_CASES = 20
AK_REF = re.compile(r"\bAK-[0-9]{2}\b")


def dataset_dirs(root: Path) -> list[Path]:
    base = root / "evals"
    if not base.is_dir():
        return []
    return sorted(p.parent for p in base.glob("*/*/cases.jsonl"))


def find_prompt(root: Path, dataset: Path) -> Path | None:
    """The prompt for evals/<agent>/<task>/ is prompts/<agent>/<task>.v<N>.md (highest N)."""
    agent, task = dataset.parent.name, dataset.name
    found: list[tuple[int, Path]] = []
    for p in (root / "prompts" / agent).glob(f"{task}.v*.md"):
        m = NAME_RE.match(p.name)
        if m and m.group("task") == task:
            found.append((int(m.group("ver")), p))
    return max(found)[1] if found else None


def load_cases(path: Path) -> tuple[list[JsonObject], list[tuple[int, str]]]:
    """Return (cases, errors); an error is (line number, message)."""
    cases: list[JsonObject] = []
    errors: list[tuple[int, str]] = []
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            errors.append((no, "blank line"))
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append((no, f"invalid JSON: {exc.msg}"))
            continue
        if not isinstance(obj, dict):
            errors.append((no, "not a JSON object"))
            continue
        cases.append(obj)
    return cases, errors


def _as_set(value: object) -> set[str]:
    return {v for v in value if isinstance(v, str)} if isinstance(value, list) else set()


def lint_dataset(root: Path, dataset: Path, rel_base: Path) -> list[Finding]:
    rel = (dataset / "cases.jsonl").relative_to(rel_base).as_posix()
    out: list[Finding] = []
    prompt_path = find_prompt(root, dataset)
    doc: PromptDoc | None = parse_prompt(prompt_path) if prompt_path else None
    is_llm = doc is not None

    readme = dataset / "README.md"
    if not readme.is_file():
        out.append(Finding(rel, "E-README", "dataset has no README.md (thresholds, assertions)"))
    if is_llm and not (dataset / "rubric.md").is_file():
        out.append(Finding(rel, "E-RUBRIC", "LLM dataset has no rubric.md"))

    cases, errors = load_cases(dataset / "cases.jsonl")
    for no, msg in errors:
        out.append(Finding(rel, "E-JSON", f"line {no}: {msg}"))
    if is_llm and len(cases) + len(errors) < MIN_LLM_CASES:
        out.append(
            Finding(
                rel, "E-COUNT", f"{len(cases)} case(s); an LLM step needs at least {MIN_LLM_CASES}"
            )
        )

    input_schema = doc.input_schema() if doc else None
    validator = Draft202012Validator(input_schema) if input_schema else None
    seen: set[str] = set()
    for i, case in enumerate(cases, start=1):
        cid = case.get("case_id")
        label = cid if isinstance(cid, str) else f"case #{i}"
        required = list(BASE_KEYS) + (["judge_min"] if is_llm else [])
        missing = [k for k in required if k not in case]
        if missing:
            out.append(Finding(rel, "E-KEYS", f"{label}: missing key(s) {', '.join(missing)}"))
        if isinstance(cid, str):
            if cid in seen:
                out.append(Finding(rel, "E-DUP-ID", f"duplicate case_id {cid}"))
            seen.add(cid)
        elif "case_id" in case:
            out.append(Finding(rel, "E-KEYS", f"{label}: case_id is not a string"))
        cat = case.get("category")
        if "category" in case and cat not in CATEGORIES:
            out.append(Finding(rel, "E-CATEGORY", f"{label}: unknown category {cat!r}"))
        exp = case.get("expected")
        if isinstance(exp, dict):
            both = sorted(_as_set(exp.get("must_flag")) & _as_set(exp.get("must_not_flag")))
            if both:
                out.append(
                    Finding(
                        rel,
                        "E-FLAG-OVERLAP",
                        f"{label}: in both must_flag and must_not_flag: {both}",
                    )
                )
        elif "expected" in case:
            out.append(Finding(rel, "E-KEYS", f"{label}: expected is not an object"))
        if validator is not None and "input" in case:
            errs = list(validator.iter_errors(case["input"]))
            if errs:
                where = "/".join(str(p) for p in errs[0].absolute_path) or "(root)"
                out.append(
                    Finding(
                        rel,
                        "E-INPUT-INVALID",
                        f"{label}: input fails the prompt's input schema at {where}: "
                        f"{errs[0].message[:100]}",
                    )
                )

    # answer-key cases the dataset README names must exist in cases.jsonl
    if readme.is_file():
        named = set(AK_REF.findall(readme.read_text(encoding="utf-8")))
        for ak in sorted(named - seen):
            out.append(
                Finding(
                    rel, "E-ANSWER-KEY", f"README names {ak} but cases.jsonl has no such case_id"
                )
            )
    return out


def lint_datasets(root: Path, rel_base: Path | None = None) -> list[Finding]:
    rel_base = rel_base or root.parent
    found: list[Finding] = []
    for d in dataset_dirs(root):
        found.extend(lint_dataset(root, d, rel_base))
    return sorted(found)
