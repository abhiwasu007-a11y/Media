"""Shared pure helpers of the input builders (CCR-203, ticket PASS6-B1).

Nothing here imports an agent package. The builders pass references and facts: a document that
another stage produced is found by what that stage's own Task Output says (a payload field that
names it, or the artifact file name its blueprint fixes in ``output_refs``) and is handed on by
URI and SHA-256; it is never rewritten (CCR-200, CCR-202). Anything that is missing is a typed
``MISSING_DEPENDENCY`` / ``INPUT_INVALID`` refusal, never a guess.
"""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from amw_core.contracts import ContextRef, TaskOutput, ValidationResult
from amw_core.enums import ContextRefPurpose, ProductionTypeKey
from amw_core.errors import InputInvalidError, MissingDependencyError
from amw_orchestrator.approval_binding import ExpectedSubject, require_bound_approval
from amw_orchestrator.executor import BuildContext, DocRef, JobFacts
from amw_orchestrator.payloads import ApprovalOutput

YOUTUBE_GENERAL = "rp.youtube_general"
FINANCE_SEBI_IN = "rp.finance_sebi_in"
# Also sent for non-finance jobs: a GLOSSARY constant (status of the owner), not a finance rule.
OWNER_SEBI_REGISTRATION = "UNREGISTERED"
"""GLOSSARY section 6.52: the only value of v1; every payload that carries the field is a closed
``const`` in its schema. It is a registration status of the owner, not a finance rule text."""

SCRIPT_DOCUMENT_SCHEMA = "agent_05.script_document"
"""The ``ContextRef.schema`` name of the script document (agent_05 section 8.3; agent_10 7.1)."""


def need[T](value: T | None, what: str, **details: str) -> T:
    """``value`` or ``MISSING_DEPENDENCY`` (the typed refusal of an absent input)."""
    if value is None:
        raise MissingDependencyError(f"input builder: {what} is not available", details=details)
    return value


def active_rule_packs(job: JobFacts) -> list[str]:
    """24 ``rule_packs``: ``rp.youtube_general`` always, the finance pack only for finance
    (CCR-273; unknown category = finance)."""
    return [YOUTUBE_GENERAL, *([FINANCE_SEBI_IN] if job.finance_rules_apply else [])]


def is_shorts(job: JobFacts) -> bool:
    return job.production_type_key is ProductionTypeKey.SHORTS


def script_stage_id(job: JobFacts) -> str:
    """The script stage of the job's production type (24 sections 7.1a / 7.2a)."""
    return "s05_shorts" if is_shorts(job) else "s05_script"


def aspect_ratio(job: JobFacts) -> str:
    return "9:16" if is_shorts(job) else "16:9"


def stage_output(ctx: BuildContext, stage_id: str) -> TaskOutput:
    """The latest COMPLETED output of a stage of this job, else of the parent job (Shorts)."""
    out = ctx.upstream.get(stage_id) or ctx.upstream.get(f"parent.{stage_id}")
    if out is None:
        raise MissingDependencyError("upstream output missing", details={"stage_id": stage_id[:64]})
    return out


def has_stage(ctx: BuildContext, stage_id: str) -> bool:
    return stage_id in ctx.upstream


def payload(ctx: BuildContext, stage_id: str) -> dict[str, Any]:
    """The payload data of an upstream output (inline, else read by reference and verified)."""
    return payload_of(ctx, stage_output(ctx, stage_id))


def payload_of(ctx: BuildContext, out: TaskOutput) -> dict[str, Any]:
    pl = out.payload
    if pl is None:
        raise MissingDependencyError("upstream output has no payload")
    if pl.data is not None:
        return dict(pl.data)
    if pl.data_ref is None or pl.data_sha256 is None or ctx.services is None:
        raise MissingDependencyError("upstream payload is stored by reference and unreadable")
    return dict(ctx.services.read_json(pl.data_ref, pl.data_sha256))


def read_doc(ctx: BuildContext, ref: DocRef) -> dict[str, Any]:
    """Hash-verified read of a stored JSON document (only builders whose input model carries
    document content, never a hand-off copy, use it)."""
    services = need(ctx.services, "the document reader")
    return dict(services.read_json(ref.uri, ref.sha256))


def artifact(out: TaskOutput, pattern: str) -> DocRef:
    """The output ref whose task-artifact name (the path after ``/artifacts/``) matches the
    regular expression ``pattern`` exactly once; zero or several is a typed refusal."""
    rx = re.compile(pattern)
    found = [r for r in out.output_refs if rx.fullmatch(r.uri.split("/artifacts/", 1)[-1])]
    if len(found) != 1:
        raise MissingDependencyError(
            "upstream output does not name exactly one such artifact",
            details={"artifact": pattern[:64], "found": str(len(found))},
        )
    return DocRef(found[0].uri, found[0].sha256)


def ref_in(
    data: Mapping[str, Any], key: str, sha_key: str = "sha256", uri_key: str = "uri"
) -> DocRef:
    """A ``{uri, sha256}`` object of an upstream payload as a ``DocRef``."""
    node = data.get(key)
    if not isinstance(node, Mapping) or uri_key not in node or sha_key not in node:
        raise MissingDependencyError(
            "upstream payload does not carry the reference", details={"field": key[:64]}
        )
    return DocRef(str(node[uri_key]), str(node[sha_key]))


def context_ref(
    doc: DocRef,
    purpose: ContextRefPurpose,
    schema: str | None = None,
    schema_version: str | None = None,
) -> ContextRef:
    return ContextRef.model_validate(
        {
            "uri": doc.uri,
            "purpose": purpose.value,
            "sha256": doc.sha256,
            **({"schema": schema} if schema else {}),
            **({"schema_version": schema_version} if schema_version else {}),
        }
    )


def as_wire(doc: DocRef) -> dict[str, str]:
    return {"uri": doc.uri, "sha256": doc.sha256}


def canonical_json(value: Any) -> str:
    """03 section 9.1: UTF-8 text, keys sorted, separators ``,`` and ``:``, no ASCII escaping."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def claims_sha256(claims: Sequence[Any]) -> str:
    """agent_06 section 7.2: SHA-256 of the canonical JSON of the ``claims`` list."""
    return sha256_text(canonical_json(list(claims)))


def rule_pack_refs(ctx: BuildContext) -> list[ContextRef]:
    """One ``RULE_PACK`` ref per active rule pack (the job documents name them)."""
    packs = ctx.job.documents.rule_packs
    refs = []
    for key in active_rule_packs(ctx.job):
        pack = need(packs.get(key), "the rule pack document", pack=key)
        refs.append(context_ref(pack.doc, ContextRefPurpose.RULE_PACK))
    return refs


def profile_ref(ctx: BuildContext) -> ContextRef:
    doc = need(ctx.job.documents.compliance_profile, "the compliance profile")
    return context_ref(doc, ContextRefPurpose.COMPLIANCE_PROFILE)


def brand_kit_doc(ctx: BuildContext) -> DocRef:
    return need(ctx.job.documents.brand_kit, "the brand kit")


def failing(ctx: BuildContext) -> tuple[ValidationResult, ...]:
    """The failing results the revision was routed from (24 section 3.3 rule 7)."""
    return ctx.revision_feedback


def require_iteration_output(ctx: BuildContext) -> TaskOutput:
    """The previous iteration's output of this stage (``PRIOR_OUTPUT``, 24 section 3.3 rule 6)."""
    if ctx.prior_output is None:
        raise InputInvalidError(
            "a revision iteration needs the previous output of the stage",
            details={"stage_id": ctx.stage.stage_id},
        )
    return ctx.prior_output


def payload_doc_ref(ctx: BuildContext, stage_id: str) -> DocRef:
    """The payload of a stage's output as a stored document (by its own ``data_ref`` when it is
    stored by reference, else a verbatim write-once copy made by the build services).

    The copy is a storage write inside a builder (a side effect), but it is replay-safe: the path
    is fixed by the output's own task and attempt, and ``TaskIo.put_payload`` writes it once and
    returns the existing blob when its hash already matches, so a rebuild changes nothing."""
    out = stage_output(ctx, stage_id)
    pl = out.payload
    if pl is not None and pl.data_ref is not None and pl.data_sha256 is not None:
        return DocRef(pl.data_ref, pl.data_sha256)
    return need(ctx.services, "the build services").payload_document(ctx.job, out)


def bound_script_approval(ctx: BuildContext) -> ApprovalOutput | None:
    """The ``a_script`` approval, accepted only for the CURRENT script (state, kind, document
    hash, confirmed evidence, no TEST_FIXTURE in a real run: CCR-296 PROVISIONAL). ``None`` when
    the graph has no ``a_script`` stage (the default registry leaves it disabled). Called by every
    builder that hands the script approval to a PAID stage (``agent_07``, ``agent_09``) and by
    ``agent_16``, so an unconfirmed, stale or other-subject approval is refused before any spend."""
    if not has_stage(ctx, "a_script"):
        return None
    script = payload(ctx, script_stage_id(ctx.job))
    return require_bound_approval(
        payload(ctx, "a_script"),
        stage_id="a_script",
        approval_kind="SCRIPT",
        subject=ExpectedSubject(
            "script", script["script_id"], ref_in(script, "script_document").sha256
        ),
        org_id=ctx.job.org_id,
        evidence=ctx.evidence,
        real_run=ctx.real_run,
    )
