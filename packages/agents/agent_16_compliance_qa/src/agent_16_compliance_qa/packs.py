"""RulePackLoader (C0, F-02; FR-01): union of the compliance profile's packs and the packs the
channel category requires; every pack file verified against ``rules_sha256``; a ``DRAFT`` pack
is refused. The gate never runs on an unverified pack (13 section 2.1)."""

import hashlib
from collections.abc import Mapping, Sequence
from typing import Literal

from agent_16_compliance_qa.base import Model
from amw_core.enums import RulePackStatus
from amw_core.errors import ConfigInvalidError

Severity = Literal["BLOCKING", "WARNING"]


class PackRow(Model):
    rule_pack_id: str
    key: str
    version: int
    status: RulePackStatus
    rules_sha256: str
    rules: Mapping[str, Severity]
    """rule ID -> severity, as the verified pack file states it."""


class LoadedPacks(Model):
    packs: tuple[PackRow, ...]

    @property
    def active_rule_ids(self) -> frozenset[str]:
        return frozenset(r for p in self.packs for r in p.rules)

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(p.key for p in self.packs)

    def severity(self, rule_id: str) -> Severity:
        for p in self.packs:
            if rule_id in p.rules:
                return p.rules[rule_id]
        raise ConfigInvalidError(f"rule {rule_id} is in no active pack")

    def pack_of(self, rule_id: str) -> PackRow | None:
        return next((p for p in self.packs if rule_id in p.rules), None)


def load_packs(
    profile_packs: Sequence[PackRow],
    category_packs: Sequence[PackRow],
    files: Mapping[str, bytes],
) -> LoadedPacks:
    union: dict[str, PackRow] = {}
    for p in (*profile_packs, *category_packs):
        if p.status is RulePackStatus.DRAFT:
            raise ConfigInvalidError(f"DRAFT rule pack {p.key} attached (13 section 11.6)")
        body = files.get(p.rule_pack_id)
        if body is None or hashlib.sha256(body).hexdigest() != p.rules_sha256:
            raise ConfigInvalidError(f"rule pack {p.key} v{p.version} fails its hash check")
        seen = union.get(p.key)
        if seen is not None and seen.version != p.version:
            raise ConfigInvalidError(f"two versions of rule pack {p.key} attached")
        union[p.key] = p
    if not union:
        raise ConfigInvalidError("no rule pack active for this channel")
    return LoadedPacks(packs=tuple(sorted(union.values(), key=lambda p: p.key)))
