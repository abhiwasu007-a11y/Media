"""TenantScope and ScriptGate (F-01, F-03): deterministic checks before any model call."""

import re
from collections.abc import Iterable

from agent_09_video_director.problems import input_invalid
from amw_core.errors import CrossTenantRefError, TenantMismatchError

_URI_ORG = re.compile(r"^amw-(?:blob|entity)://(org_[0-9a-f-]{36}|platform)/")


def assert_tenant_consistent(
    org_id: str, *, declared_orgs: Iterable[str], uris: Iterable[str]
) -> None:
    """Org equality across envelope, input and context refs; every URI belongs to ``org_id``.

    ``platform`` URIs (shared templates, rule packs) are allowed; any other org is a cross-tenant
    reference (08 section 8). Messages carry no content.
    """
    if any(o != org_id for o in declared_orgs):
        raise TenantMismatchError("org of envelope, input or refs differs")
    for uri in uris:
        m = _URI_ORG.match(uri)
        if m is None or m.group(1) not in (org_id, "platform"):
            raise CrossTenantRefError("reference points to another tenant")


def script_gate(
    *,
    script_sha256: str,
    ref_sha256: str,
    verified_script_sha256: str,
    stage_verdict: str,
    approval_approved: bool = False,
    claim_blocked: bool = False,
    script_status: str = "ACTIVE",
) -> None:
    """FR-02: the plan is made only on the script that Agent 06 verified and that is allowed."""
    violations: list[str] = []
    if not (script_sha256 == verified_script_sha256 == ref_sha256):
        violations.append("SCRIPT_HASH_MISMATCH")
    if stage_verdict == "NEEDS_HUMAN_REVIEW":
        if not approval_approved:
            violations.append("VERDICT_NOT_APPROVED")
    elif stage_verdict != "ALLOWED":
        violations.append("VERDICT_NOT_ALLOWED")
    if claim_blocked:
        violations.append("CLAIM_BLOCKED")
    if script_status in {"REJECTED", "SUPERSEDED"}:
        violations.append("SCRIPT_NOT_CURRENT")
    if violations:
        first, *rest = violations
        raise input_invalid(first, extra=rest)
