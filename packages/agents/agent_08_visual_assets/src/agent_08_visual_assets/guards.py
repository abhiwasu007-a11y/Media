"""``TenantGuard``: agreement of organisation ids, URI ownership, path safety (blueprint 10.1, 19.1).

Pure. ``evaluate`` returns a decision (used by the golden dataset and by the security event
emitter); ``check_task`` raises the matching ``amw_core`` error. A foreign id and a missing id
produce the same error with the same message (no existence oracle, S-03, ``TG-08``).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from amw_core.errors import (
    CrossTenantRefError,
    InputInvalidError,
    MissingDependencyError,
    PermissionDeniedError,
    TenantMismatchError,
)
from amw_core.ids import Prefix, is_valid_id

PLATFORM = "platform"
MISSING_MESSAGE = "referenced entity not found"
_URI_RE = re.compile(r"^amw-(?:blob|entity)://(?P<owner>[^/]+)/(?P<rest>.+)$")


@dataclass(frozen=True, slots=True)
class GuardDecision:
    ok: bool
    error_code: str | None = None
    security_event: bool = False
    message: str = ""


def _org_ok(value: str) -> bool:
    return is_valid_id(value, Prefix.ORGANISATION)


class TenantGuard:
    @staticmethod
    def evaluate(
        *,
        context_org: str,
        envelope_org: str,
        input_org: str,
        uris: Sequence[str],
        write: bool,
    ) -> GuardDecision:
        for org in (context_org, envelope_org, input_org):
            if not _org_ok(org):
                return GuardDecision(False, InputInvalidError.code, False, "bad organisation id")
        if not (context_org == envelope_org == input_org):
            return GuardDecision(
                False, TenantMismatchError.code, True, "organisation ids disagree"
            )
        for uri in uris:
            match = _URI_RE.match(uri)
            if match is None:
                return GuardDecision(False, InputInvalidError.code, False, "malformed uri")
            segments = match.group("rest").split("/")
            if any(s in ("", ".", "..") for s in segments):
                return GuardDecision(False, InputInvalidError.code, True, "unsafe uri path")
            owner = match.group("owner")
            if owner == PLATFORM:
                if write:
                    return GuardDecision(
                        False, PermissionDeniedError.code, True, "platform area is read-only"
                    )
                continue
            if not _org_ok(owner):
                return GuardDecision(False, InputInvalidError.code, False, "bad uri owner")
            if owner != context_org:
                return GuardDecision(False, CrossTenantRefError.code, True, MISSING_MESSAGE)
        return GuardDecision(True)

    @classmethod
    def check_task(
        cls,
        *,
        context_org: str,
        envelope_org: str,
        input_org: str,
        uris: Sequence[str],
        write: bool,
    ) -> None:
        decision = cls.evaluate(
            context_org=context_org,
            envelope_org=envelope_org,
            input_org=input_org,
            uris=uris,
            write=write,
        )
        if decision.ok:
            return
        errors: dict[str | None, type[Exception]] = {
            InputInvalidError.code: InputInvalidError,
            TenantMismatchError.code: TenantMismatchError,
            CrossTenantRefError.code: CrossTenantRefError,
            PermissionDeniedError.code: PermissionDeniedError,
        }
        raise errors[decision.error_code](decision.message)

    @staticmethod
    def entity_not_visible(kind: str) -> MissingDependencyError:
        """Same error for an id of another tenant and for a missing id (``TG-08``)."""
        return MissingDependencyError(MISSING_MESSAGE, details={"class": kind})

    @staticmethod
    def entity_decision(*, visible_to_context: bool) -> GuardDecision:
        if visible_to_context:
            return GuardDecision(True)
        return GuardDecision(False, MissingDependencyError.code, True, MISSING_MESSAGE)
