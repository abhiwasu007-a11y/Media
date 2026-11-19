# ruff: noqa: PT018
"""The four Agent 16 / S2 output models equal the JSON Schema blocks of blueprint 8.2-8.5.

The document is the contract (03 section 2.1): the blocks are read from it here, never copied.
Three checks per model: (1) the model's own JSON Schema has the same canonical shape as the block
(types, nullability, enums, patterns, bounds, required sets, unknown fields forbidden); (2) a
payload emitted by the producer's own fakes is valid for the block (``jsonschema``) and for the
model and survives a round trip unchanged; (3) differential mutations derived from the block (drop
each required field, add an unknown field, break each enum / pattern / bound) are refused by the
model exactly where the block refuses them.
"""

import copy
import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError
from referencing import Registry, Resource

from agent_16_compliance_qa.authorisation.stage import (
    PublicationAuthorisationStage,
    PublicationAuthorisationWorker,
)
from agent_16_compliance_qa.payload_models import (
    ComplianceGateOutput,
    PublicationAuthorisationOutput,
    QualityScoreOutput,
    UniquenessCheckOutput,
)
from agent_16_compliance_qa.stages import UniquenessInput
from tests.agents.agent_16_compliance_qa.support import FixedClock, config
from tests.agents.agent_16_compliance_qa.test_auth_stage import AUDIT, Writer, world
from tests.agents.agent_16_compliance_qa.test_entry_points import score_world
from tests.agents.agent_16_compliance_qa.test_stages import (
    NOW,
    Storage,
    Tenancy,
    ctx_of,
    gate_world,
    task_input,
    uniq_world,
)

pytestmark = pytest.mark.contract

DOC = Path(__file__).resolve().parents[3] / "docs/v4/agents/agent_16_compliance_qa.md"
COMMON = (
    Path(__file__).resolve().parents[3]
    / "packages/amw_core/src/amw_core/contracts/schemas/amw.common/1.0.0.json"
)
PREFIX = "urn:amw:schema:"


@cache
def blocks() -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for m in re.finditer(r"```json\n(.*?)\n```", DOC.read_text(encoding="utf-8"), re.S):
        try:
            doc = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(doc, dict) and str(doc.get("$id", "")).startswith(PREFIX):
            found[doc["$id"].removeprefix(PREFIX).rsplit(":", 1)[0]] = doc
    return found


def _validator(name: str) -> Draft202012Validator:
    common = json.loads(COMMON.read_text(encoding="utf-8"))
    registry: Registry[Any] = Registry().with_resource(
        "urn:amw:schema:amw.common:1.0.0", Resource.from_contents(common)
    )
    return Draft202012Validator(blocks()[name], registry=registry)


# --- canonical shape ---------------------------------------------------------------------
def _deref(node: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        ref = node["$ref"]
        if ref.startswith("urn:amw:schema:amw.common"):
            target = json.loads(COMMON.read_text(encoding="utf-8"))
            for part in ref.split("#/")[1].split("/"):
                target = target[part]
            node = {**{k: v for k, v in node.items() if k != "$ref"}, **target}
        else:
            target = root
            for part in ref.removeprefix("#/").split("/"):
                target = target[part]
            node = {**{k: v for k, v in node.items() if k != "$ref"}, **target}
    return node


_BOUNDS = ("minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems", "pattern")


def shape(node: dict[str, Any], root: dict[str, Any]) -> Any:
    """Canonical form of a (sub)schema: the facts a validator would act on."""
    node = _deref(node, root)
    options = node.get("oneOf") or node.get("anyOf")
    if options is not None:
        parts = [shape(o, root) for o in options]
        nullable = any(p == {"type": "null"} for p in parts)
        rest = [p for p in parts if p != {"type": "null"}]
        base = rest[0] if len(rest) == 1 else {"any": rest}
        return {**base, "nullable": True} if nullable else base
    if "const" in node:
        return {"enum": [node["const"]]}
    if "enum" in node:
        values = [v for v in node["enum"] if v is not None]
        out: dict[str, Any] = {"enum": sorted(values)}
        if None in node["enum"]:
            out["nullable"] = True
        return out
    kind = node.get("type")
    nullable = isinstance(kind, list) and "null" in kind
    if isinstance(kind, list):
        kind = next(k for k in kind if k != "null")
    out = {"type": kind}
    if nullable:
        out["nullable"] = True
    if kind == "object":
        props = node.get("properties")
        if props is None:
            out["free"] = True
            ap = node.get("additionalProperties")
            if isinstance(ap, dict):
                out["values"] = shape(ap, root)
        else:
            out["closed"] = node.get("additionalProperties") is False
            out["required"] = sorted(node.get("required", []))
            out["props"] = {k: shape(v, root) for k, v in props.items()}
    elif kind == "array":
        out["items"] = shape(node["items"], root)
    if kind == "string" and "format" in node:
        out["format"] = node["format"]
    for key in _BOUNDS:
        if key in node:
            out[key] = node[key]
    return out


def model_shape(model: type[BaseModel]) -> Any:
    schema = model.model_json_schema(mode="validation")
    return shape(schema, schema)


def differences(a: Any, b: Any, path: str = "") -> list[str]:
    """Every place the two canonical shapes differ, as ``path: block vs model``."""
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[str] = []
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                out.append(f"{path}/{key}: block={a.get(key, '-')!r} model={b.get(key, '-')!r}")
            else:
                out += differences(a[key], b[key], f"{path}/{key}")
        return out
    return [] if a == b else [f"{path}: block={a!r} model={b!r}"]


CASES: list[tuple[str, type[BaseModel]]] = [
    ("agent_16.compliance_gate.output", ComplianceGateOutput),
    ("svc_s02.uniqueness_check.output", UniquenessCheckOutput),
    ("agent_16.quality_score.output", QualityScoreOutput),
    ("agent_16.publication_authorisation.output", PublicationAuthorisationOutput),
    ("svc_s02.uniqueness_check.input", UniquenessInput),
]


@pytest.mark.parametrize(("name", "model"), CASES, ids=[c[0] for c in CASES])
def test_the_model_has_the_shape_of_the_document_block(name: str, model: type[BaseModel]) -> None:
    doc = blocks()[name]
    assert differences(shape(doc, doc), model_shape(model)) == []


def test_all_blocks_of_the_four_outputs_and_the_s02_input_were_found() -> None:
    assert {n for n, _ in CASES} <= set(blocks())


# --- differential mutations ----------------------------------------------------------------
def _walk(schema: dict[str, Any], root: dict[str, Any], path: tuple[Any, ...] = ()) -> Any:
    """Yield ``(path, resolved sub-schema)`` for every object / leaf the block describes."""
    node = _deref(schema, root)
    options = node.get("oneOf") or node.get("anyOf")
    if options is not None:
        for opt in options:
            yield from _walk(opt, root, path)
        return
    yield path, node
    if node.get("type") == "object" and "properties" in node:
        for key, sub in node["properties"].items():
            yield from _walk(sub, root, (*path, key))
    if node.get("type") == "array" and isinstance(node.get("items"), dict):
        yield from _walk(node["items"], root, (*path, 0))


def _get(doc: Any, path: tuple[Any, ...]) -> Any:
    for p in path:
        doc = doc[p]
    return doc


def _set(doc: Any, path: tuple[Any, ...], value: Any) -> None:
    for p in path[:-1]:
        doc = doc[p]
    doc[path[-1]] = value


def _exists(doc: Any, path: tuple[Any, ...]) -> bool:
    try:
        _get(doc, path)
    except KeyError, IndexError, TypeError:
        return False
    return True


def _mutations(name: str, valid: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    block = blocks()[name]
    out: list[tuple[str, dict[str, Any]]] = []
    for path, node in _walk(block, block):
        if not _exists(valid, path) and path:
            continue  # a branch the sample does not exercise (an empty array, a null)
        if node.get("type") == "object" and "properties" in node:
            holder = _get(valid, path) if path else valid
            if not isinstance(holder, dict):
                continue
            for req in node.get("required", []):
                if req in holder:
                    doc = copy.deepcopy(valid)
                    del (_get(doc, path) if path else doc)[req]
                    out.append((f"drop {'/'.join(map(str, (*path, req)))}", doc))
            if node.get("additionalProperties") is False:
                doc = copy.deepcopy(valid)
                (_get(doc, path) if path else doc)["unknown_field"] = 1
                out.append((f"extra {'/'.join(map(str, path))}", doc))
        if "enum" in node and path:
            doc = copy.deepcopy(valid)
            _set(doc, path, "NOT_A_VALUE")
            out.append((f"enum {'/'.join(map(str, path))}", doc))
        if "pattern" in node and path:
            doc = copy.deepcopy(valid)
            _set(doc, path, "not matching")
            out.append((f"pattern {'/'.join(map(str, path))}", doc))
        if node.get("type") in ("number", "integer") and path:
            for key, bad in (("minimum", -1), ("maximum", 10**6)):
                if key in node:
                    doc = copy.deepcopy(valid)
                    _set(doc, path, bad)
                    out.append((f"{key} {'/'.join(map(str, path))}", doc))
            doc = copy.deepcopy(valid)
            _set(doc, path, "1")
            out.append((f"type {'/'.join(map(str, path))}", doc))
        if node.get("type") == "string" and path and "maxLength" in node:
            doc = copy.deepcopy(valid)
            _set(doc, path, "x" * (node["maxLength"] + 1))
            out.append((f"maxLength {'/'.join(map(str, path))}", doc))
    return out


def _check_same_verdict(name: str, model: type[BaseModel], payload: dict[str, Any]) -> None:
    v = _validator(name)
    schema_errors = list(v.iter_errors(payload))
    try:
        model.model_validate(payload)
        model_ok = True
    except ValidationError:
        model_ok = False
    assert model_ok == (not schema_errors), (name, schema_errors[:2])


def _exercise(name: str, model: type[BaseModel], valid: dict[str, Any]) -> int:
    _check_same_verdict(name, model, valid)
    assert (
        model.model_validate(valid).model_dump(mode="json", exclude_unset=True) == valid
    )  # round trip, unchanged
    assert not list(_validator(name).iter_errors(valid))
    muts = _mutations(name, valid)
    assert len(muts) >= 5
    for label, doc in muts:
        _check_same_verdict(name, model, doc)
        assert list(_validator(name).iter_errors(doc)), f"{label} should be refused by the block"
        with pytest.raises(ValidationError):
            model.model_validate(doc)
    return len(muts)


# --- real emitted payloads -------------------------------------------------------------------
def test_compliance_gate_output_emitted_by_the_stage_matches_the_block_and_the_model() -> None:
    w = gate_world()
    out = w.stage.run(w.ti, ctx_of(w.ti))
    assert out.payload is not None and out.payload.data is not None
    assert out.payload.payload_schema == "agent_16.compliance_gate.output"
    assert _exercise("agent_16.compliance_gate.output", ComplianceGateOutput, out.payload.data) > 10


def test_quality_score_output_emitted_by_the_stage_matches_the_block_and_the_model() -> None:
    w = score_world()
    out = w.stage.run(w.ti, ctx_of(w.ti))
    assert out.payload is not None and out.payload.data is not None
    assert out.payload.payload_schema == "agent_16.quality_score.output"
    assert _exercise("agent_16.quality_score.output", QualityScoreOutput, out.payload.data) > 10


def test_authorisation_output_emitted_by_the_stage_matches_the_block_and_the_model() -> None:
    h, repo, req = world()
    stage = PublicationAuthorisationStage(config(), repo, h.a16, Writer(), AUDIT)
    worker = PublicationAuthorisationWorker(stage, Tenancy(), Storage(), FixedClock(NOW))
    ti = task_input(
        str(h.org),
        "agent_16",
        "agent_16.publication_authorisation.input",
        json.loads(req.model_dump_json()),
    )
    out = worker.run(ti, ctx_of(ti))
    assert out.payload is not None and out.payload.data is not None
    assert out.payload.payload_schema == "agent_16.publication_authorisation.output"
    n = _exercise(
        "agent_16.publication_authorisation.output",
        PublicationAuthorisationOutput,
        out.payload.data,
    )
    assert n > 10


@pytest.mark.parametrize("identical", [False, True])
def test_uniqueness_output_and_input_match_the_blocks_and_the_models(identical: bool) -> None:
    stage, ti, _, _ = uniq_world(identical)
    assert _exercise("svc_s02.uniqueness_check.input", UniquenessInput, dict(ti.payload.data or {}))
    out = stage.run(ti, ctx_of(ti))
    assert out.payload is not None and out.payload.data is not None
    assert out.payload.payload_schema == "svc_s02.uniqueness_check.output"
    assert _exercise("svc_s02.uniqueness_check.output", UniquenessCheckOutput, out.payload.data)


def test_a_producer_payload_that_breaks_its_schema_is_never_emitted() -> None:
    from agent_16_compliance_qa.payload_models import emit
    from amw_core.errors import IncompleteOutputError

    w = gate_world()
    out = w.stage.run(w.ti, ctx_of(w.ti))
    assert out.payload is not None and out.payload.data is not None
    bad = {**out.payload.data, "subject": {"render_id": "secret-value"}}
    with pytest.raises(IncompleteOutputError) as err:
        emit(ComplianceGateOutput, bad)
    assert err.value.code == "AGENT.INCOMPLETE_OUTPUT"
    assert "secret-value" not in json.dumps(err.value.details)  # locations only, never values
    assert "subject.render_id" in err.value.details["fields"]
