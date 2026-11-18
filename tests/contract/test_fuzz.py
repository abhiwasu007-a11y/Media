"""Deterministic fuzz: for generated documents, the Pydantic model and the JSON Schema must agree.

Documents are valid examples with 1-3 random mutations (replace a value, delete a key, add a key).
Rules:
* model accepts  => schema accepts (the model is never more lenient than the schema);
* schema accepts => model accepts, unless the document breaks a rule 03 states outside the schema
  (``model_only_violation``), which must then be the reason the model refused.

Known, intended differences are kept out of the value pool: integral floats such as ``1.0`` (JSON
Schema calls them integers; the model refuses them as money/counters) and strings with a trailing
newline (Python ``re`` lets ``$`` match before it; the model's regex does not).
"""

import copy
import json
import random
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import BaseModel
from pydantic import ValidationError as PydanticError

from amw_core import contracts
from amw_core.contracts.common import storage_uri_owner
from amw_core.errors import CATALOGUE, AmwError
from tests.contract import examples as ex
from tests.docs_tables import stage_table

LONG_FORM_V2 = stage_table(r"7\.1a ")

pytestmark = pytest.mark.contract

SEED = 20261118
ROUNDS = 400

POOL: list[Any] = [
    None, True, False, 0, 1, -1, 7, 101, 2.5, -0.5, "", "1", "0", "true", "x", "PASS",
    "SUCCEEDED", "FAILED", "REJECTED", "SUSPENDED", "WAIT", "CONTINUE", "AWAITING_BUDGET",
    "TEMPORARY", "PERMANENT", "TEMPORARY.TIMEOUT", "PERMANENT.SCHEMA_INVALID", "TEMPORARY.NOPE",
    "s05_script", "s10_render", "s13_deliver", "REVISE", "STOP", "YOUTUBE", "FILE_DELIVERY",
    "rp.youtube_general", "MUSIC", "OWNER_VOICE", "EXTERNAL_URL", "KNOWLEDGE_SOURCE",
    "https://example.org/x", "http://x", "WARN", "SKIPPED", "FAIL",
    "agent_05", "agent_18", "sys_reaper", "usr_x", "1.0.0", "2.0.0", "1.x",
    1767225600, "1767225600", "2026-01-01", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00.5Z",
    "2026-01-01T05:30:00+05:30", "2026-02-30T00:00:00Z", "2026-01-01T00:00:00",
    ex.ORG, ex.OTHER_ORG, ex.JOB, ex.TASK, ex.COR, ex.MSG, ex.IDK, ex.SHA, ex.blob(),
    ex.blob(ex.OTHER_ORG), "amw-blob://platform/t/a.json", "INR", "usd",
    [], [1], {}, {"a": 1}, "application/json",
]  # fmt: skip


def _gated_output() -> dict[str, Any]:
    doc = ex.task_output()
    doc["validation_results"].append(ex.gate_result("FAIL"))
    return doc


def _long_form_v2() -> dict[str, Any]:
    return ex.production_type(copy.deepcopy(LONG_FORM_V2))


DOCS: list[tuple[str, Callable[[], dict[str, Any]], type[BaseModel], str]] = [
    ("amw.task_input", ex.task_input, contracts.TaskInput, "1.0.0"),
    ("amw.envelope", ex.envelope, contracts.Envelope, "1.0.0"),
    ("amw.envelope", lambda: ex.envelope("amw.control"), contracts.Envelope, "1.0.0"),
    ("amw.control", ex.control, contracts.ControlCommand, "1.0.0"),
    ("amw.error", ex.error, contracts.ErrorObject, "1.0.0"),
    ("amw.task_output", ex.task_output, contracts.TaskOutput, "1.0.0"),
    ("amw.task_output", lambda: ex.task_output("FAILED"), contracts.TaskOutput, "1.0.0"),
    ("amw.task_output", lambda: ex.task_output("REJECTED"), contracts.TaskOutput, "1.0.0"),
    ("amw.task_output", lambda: ex.task_output("SUSPENDED"), contracts.TaskOutput, "1.0.0"),
    ("amw.task_output", _gated_output, contracts.TaskOutput, "1.0.0"),
    ("amw.owner_topic", ex.owner_topic, contracts.OwnerTopic, "1.0.0"),
    ("amw.production_type", _long_form_v2, contracts.ProductionType, "1.0.0"),
]


def _containers(node: Any, out: list[Any]) -> list[Any]:
    if isinstance(node, dict):
        out.append(node)
        for value in node.values():
            _containers(value, out)
    elif isinstance(node, list):
        out.append(node)
        for value in node:
            _containers(value, out)
    return out


def mutate(doc: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    doc = copy.deepcopy(doc)
    for _ in range(rng.randint(1, 3)):
        target = rng.choice(_containers(doc, []))
        if isinstance(target, list):
            if target:
                target[rng.randrange(len(target))] = copy.deepcopy(rng.choice(POOL))
            continue
        op = rng.random()
        if op < 0.1:
            target[rng.choice(["extra", "schema_version", "error", "payload"])] = rng.choice(POOL)
        elif target and op < 0.25:
            del target[rng.choice(list(target))]
        elif target:
            target[rng.choice(list(target))] = copy.deepcopy(rng.choice(POOL))
    return doc


def _owner(uri: Any) -> str | None:
    return storage_uri_owner(uri) if isinstance(uri, str) and "://" in uri else None


def _error_rule_broken(err: Any) -> bool:
    return isinstance(err, dict) and (
        err.get("code") not in CATALOGUE
        or str(err.get("code", "")).split(".")[0] != err.get("error_class")
    )


def model_only_violation(name: str, doc: dict[str, Any]) -> bool:
    """Rules of 03 that the schema cannot express (see the models)."""
    if name == "amw.error":
        return _error_rule_broken(doc)
    if name == "amw.task_input":
        uris = [r.get("uri") for r in doc.get("context_refs", []) if isinstance(r, dict)]
        payload = doc.get("payload")
        if isinstance(payload, dict):
            uris.append(payload.get("data_ref"))
        org = doc.get("org_id")
        return any(_owner(u) not in (org, "platform") for u in uris if u is not None)
    if name == "amw.envelope":
        return _owner(doc["payload_ref"]["uri"]) != doc.get("org_id")
    if name == "amw.task_output":
        err = doc.get("error")
        if _error_rule_broken(err):
            return True
    if name == "amw.production_type":
        return _graph_rule_broken(doc)
    return False


def _graph_rule_broken(doc: dict[str, Any]) -> bool:
    """24 section 2 load rules the model adds (unique IDs, known deps, DAG, ancestor targets,
    rp.youtube_general with a YOUTUBE destination)."""
    stages = [s for s in doc.get("stages", []) if isinstance(s, dict)]
    ids = [s.get("stage_id") for s in stages]
    if len(set(map(str, ids))) != len(ids):
        return True
    deps = {str(s.get("stage_id")): list(s.get("depends_on") or []) for s in stages}
    if any(d not in deps for ds in deps.values() for d in ds):
        return True
    try:
        ancestors = {k: _ancestors(k, deps, ()) for k in deps}
    except RecursionError:
        return True
    for stage in stages:
        gate = stage.get("gate")
        on_fail = gate.get("on_fail") if isinstance(gate, dict) else None
        if isinstance(on_fail, dict) and on_fail.get("action") == "REVISE":
            targets = [on_fail.get("target_stage_id"), *(on_fail.get("alt_target_stage_ids") or [])]
            if any(t not in ancestors[str(stage.get("stage_id"))] for t in targets):
                return True
    packs = doc.get("rule_packs", {})
    mandatory = packs.get("mandatory", []) if isinstance(packs, dict) else []
    return "YOUTUBE" in (doc.get("destinations") or []) and "rp.youtube_general" not in mandatory


def _ancestors(stage: str, deps: dict[str, list[Any]], path: tuple[str, ...]) -> set[str]:
    if stage in path:
        raise RecursionError(stage)
    found: set[str] = set()
    for dep in deps[stage]:
        found |= {dep} | _ancestors(dep, deps, (*path, stage))
    return found


def model_accepts(model: type[BaseModel], doc: dict[str, Any]) -> bool:
    try:
        model.model_validate_json(json.dumps(doc))
    except PydanticError, AmwError:
        return False
    try:
        model.model_validate(doc)
    except (PydanticError, AmwError) as exc:  # pragma: no cover - reported by the assertion
        raise AssertionError(f"python mode disagrees with JSON mode: {exc}") from exc
    return True


@pytest.mark.parametrize(
    ("name", "make", "model", "version"), DOCS, ids=[f"{d[0]}-{i}" for i, d in enumerate(DOCS)]
)
def test_model_and_schema_agree(
    name: str, make: Callable[[], dict[str, Any]], model: type[BaseModel], version: str
) -> None:
    rng = random.Random(f"{SEED}:{name}:{make().get('status', '')}")  # noqa: S311 - test seed
    accepted = rejected = 0
    for round_no in range(ROUNDS):
        doc = make() if round_no == 0 else mutate(make(), rng)
        schema_ok = not contracts.schema_violations(name, version, doc)
        model_ok = model_accepts(model, doc)
        context = json.dumps(doc, sort_keys=True)[:600]
        if model_ok:
            assert schema_ok, f"model more lenient than schema: {context}"
            accepted += 1
        else:
            rejected += 1
            if schema_ok:
                assert model_only_violation(name, doc), (
                    f"model refused a schema-valid doc: {context}"
                )
    assert accepted >= 1
    assert rejected >= ROUNDS // 4
