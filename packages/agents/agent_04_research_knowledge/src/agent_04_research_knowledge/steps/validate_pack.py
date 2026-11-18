"""S6: PackValidator: the ``a04.*`` checks of blueprint 8 and 20.3 as ``ValidationResult`` rows.

Only ``a04.topic_allowed`` is a gate result (``gate: true``, 03 section 5.3 rule 4). Every other
blocking FAIL is a process-integrity failure (rule 2(b)).
"""

from collections.abc import Mapping
from typing import Protocol

from agent_04_research_knowledge.guards.copy_guard import CopyResult
from agent_04_research_knowledge.library.models import TenantScope
from agent_04_research_knowledge.library.protocol import KnowledgeLibrary
from agent_04_research_knowledge.models.common import Refusal
from agent_04_research_knowledge.models.enums import CopyGuardStatus, Coverage, ExclusionReason
from agent_04_research_knowledge.models.pack_output import ResearchPack
from amw_core.contracts.common import storage_uri_owner
from amw_core.contracts.task_output import ValidationResult
from amw_core.enums import CheckKind, CheckVerdict, ComplianceVerdict, TimeReferenceKind, VideoKind

CHECK_IDS = (
    "a04.schema",
    "a04.tenant_scope",
    "a04.citation_resolvable",
    "a04.restricted_gate",
    "a04.copy_guard",
    "a04.forward_looking_excluded",
    "a04.topic_allowed",
    "a04.coverage",
    "a04.reliability_floor",
    "a04.prior_gaps_closed",
    "a04.notes_refused",
    "a04.copy_guard_cross_language",
)
GATE_CHECK_ID = "a04.topic_allowed"


class CitationResolver(Protocol):
    def chunk_sha256(self, chunk_id: str) -> str | None:
        """Body hash of a chunk of this org and channel; ``None`` when it does not exist."""
        ...

    def snapshot_content_sha256(self, snapshot_ref: str) -> str | None:
        """``content_sha256`` stored in a reference snapshot; ``None`` when it does not exist."""
        ...


class LibraryCitationResolver:
    """Resolves chunk citations through the tenant-scoped library and snapshots through a reader."""

    def __init__(
        self,
        library: KnowledgeLibrary,
        scope: TenantScope,
        snapshot_reader: "SnapshotReader",
    ) -> None:
        self._library, self._scope, self._reader = library, scope, snapshot_reader

    def chunk_sha256(self, chunk_id: str) -> str | None:
        rows = self._library.load_chunks(self._scope, [chunk_id])
        return rows[0].body_sha256 if rows else None

    def snapshot_content_sha256(self, snapshot_ref: str) -> str | None:
        return self._reader.content_sha256(snapshot_ref)


class SnapshotReader(Protocol):
    def content_sha256(self, snapshot_ref: str) -> str | None: ...


def _result(
    check_id: str,
    verdict: CheckVerdict,
    message: str,
    *,
    blocking: bool,
    rule_id: str | None = None,
    measured: bool | int | float | str | None = None,
    threshold: bool | int | float | str | None = None,
    unit: str | None = None,
    gate: bool = False,
) -> ValidationResult:
    return ValidationResult(
        check_id=check_id,
        kind=CheckKind.DETERMINISTIC,
        verdict=verdict,
        blocking=blocking and verdict is CheckVerdict.FAIL or (blocking and verdict is CheckVerdict.PASS and not gate),
        rule_id=rule_id,
        measured=measured,
        threshold=threshold,
        unit=unit,
        message=message,
        gate=gate,
    )


def topic_allowed_result(pack: ResearchPack) -> ValidationResult:
    """The only gate result: FAIL iff BLOCKED (rule_id: the first violated rule)."""
    verdict = pack.topic_verdict
    if verdict.verdict is ComplianceVerdict.BLOCKED:
        rule = verdict.violated_rule_ids[0] if verdict.violated_rule_ids else None
        return ValidationResult(
            check_id=GATE_CHECK_ID, kind=CheckKind.DETERMINISTIC, verdict=CheckVerdict.FAIL,
            blocking=True, rule_id=rule, gate=True,
            message="topic is a forbidden call; no research was planned",
        )  # fmt: skip
    if verdict.verdict is ComplianceVerdict.NEEDS_HUMAN_REVIEW:
        return ValidationResult(
            check_id=GATE_CHECK_ID, kind=CheckKind.DETERMINISTIC, verdict=CheckVerdict.WARN,
            blocking=False, gate=True, message="topic needs human review",
        )  # fmt: skip
    return ValidationResult(
        check_id=GATE_CHECK_ID, kind=CheckKind.DETERMINISTIC, verdict=CheckVerdict.PASS,
        blocking=False, gate=True, message="topic allowed",
    )  # fmt: skip


def notes_refused_result(concept_id: str, refusal: Refusal) -> ValidationResult:
    rules = tuple(refusal.violated_rule_ids)
    return ValidationResult(
        check_id="a04.notes_refused", kind=CheckKind.DETERMINISTIC, verdict=CheckVerdict.WARN,
        blocking=False, rule_id=rules[0] if rules else None,
        message=f"notes batch of {concept_id} refused ({refusal.reason.value}); rules: {', '.join(rules)}"[:2000],
    )  # fmt: skip


class PackValidator:
    def __init__(self, resolver: CitationResolver) -> None:
        self._resolver = resolver

    def validate(
        self,
        pack: ResearchPack,
        org_id: str,
        *,
        scope: TenantScope,
        library: KnowledgeLibrary,
        copy_results: Mapping[str, CopyResult],
        has_revision: bool,
        unclosed_gap_ids: tuple[str, ...],
        cross_language_items: int,
        refused: list[ValidationResult],
    ) -> list[ValidationResult]:
        results = [
            _ok("a04.schema", "pack validates against agent_04.research_pack.output 1.0.0"),
            topic_allowed_result(pack),
        ]
        if pack.topic_verdict.verdict is not ComplianceVerdict.ALLOWED:
            return results
        results.insert(1, self._tenant_scope(pack, org_id, scope, library))
        results.append(self._citations(pack))
        results.append(self._restricted(pack))
        results.append(self._copy(pack, copy_results))
        results.append(self._forward(pack))
        total = pack.coverage_summary.concepts_total
        sourced = pack.coverage_summary.sourced
        results.append(
            _result(
                "a04.coverage",
                CheckVerdict.PASS if sourced == total else CheckVerdict.WARN,
                f"{sourced} of {total} concepts are SOURCED",
                blocking=False,
                measured=(sourced / total) if total else 0.0,
                unit="ratio",
            )
        )
        low = [e for e in pack.evidence if e.exclusion_reason is ExclusionReason.LOW_RELIABILITY]
        results.append(
            _result(
                "a04.reliability_floor",
                CheckVerdict.WARN if low else CheckVerdict.PASS,
                f"{len(low)} factual notes below the reliability floor",
                blocking=False,
                measured=len(low),
            )
        )
        if not has_revision:
            results.append(
                _result("a04.prior_gaps_closed", CheckVerdict.SKIPPED, "no revision", blocking=False)
            )
        else:
            results.append(
                _result(
                    "a04.prior_gaps_closed",
                    CheckVerdict.WARN if unclosed_gap_ids else CheckVerdict.PASS,
                    f"{len(unclosed_gap_ids)} input gaps not closed",
                    blocking=False,
                    measured=len(unclosed_gap_ids),
                )
            )
        results.extend(refused)
        results.append(
            _result(
                "a04.copy_guard_cross_language",
                CheckVerdict.WARN if cross_language_items else CheckVerdict.PASS,
                f"{cross_language_items} usable notes skipped the copy guard (cross-language)",
                blocking=False,
                rule_id="YTG-R9" if cross_language_items else None,
                measured=cross_language_items,
            )
        )
        return results

    def _tenant_scope(
        self, pack: ResearchPack, org_id: str, scope: TenantScope, library: KnowledgeLibrary
    ) -> ValidationResult:
        bad = 0
        for src in pack.sources:
            if src.source_ref.startswith("ksr_") and library.get_source(scope, src.source_ref) is None:
                bad += 1
            if src.snapshot_ref and storage_uri_owner(src.snapshot_ref) != org_id:
                bad += 1
        return _result(
            "a04.tenant_scope",
            CheckVerdict.FAIL if bad else CheckVerdict.PASS,
            "every id and URI belongs to the task's org and channel"
            if not bad
            else f"{bad} ids or URIs are outside the task's org or channel",
            blocking=True,
            measured=bad,
        )

    def _citations(self, pack: ResearchPack) -> ValidationResult:
        sources = {s.source_ref: s for s in pack.sources}
        available = {c.citation_ref: c for c in pack.citations_available}
        unresolved = 0
        for ev in pack.evidence:
            if not ev.usable_for_script:
                continue
            cit = available.get(ev.citation_ref)
            if cit is None:
                unresolved += 1
            elif ev.citation_ref.startswith("kch_"):
                if self._resolver.chunk_sha256(ev.citation_ref) != cit.content_sha256:
                    unresolved += 1
            else:
                src = sources.get(ev.source_ref)
                snap = src.snapshot_ref if src else None
                stored = self._resolver.snapshot_content_sha256(snap) if snap else None
                if stored is None or stored != cit.content_sha256:
                    unresolved += 1
        return _result(
            "a04.citation_resolvable",
            CheckVerdict.FAIL if unresolved else CheckVerdict.PASS,
            "every usable note has a resolvable citation"
            if not unresolved
            else f"{unresolved} usable notes have an unresolvable citation",
            blocking=True,
            measured=unresolved,
        )

    @staticmethod
    def _restricted(pack: ResearchPack) -> ValidationResult:
        labelled = [e for e in pack.evidence if e.usable_for_script and e.method_labelled]
        ok = not labelled or (
            pack.topic.video_kind is VideoKind.METHOD_TOPIC and bool(pack.method.release_approval_ids)
        )
        return _result(
            "a04.restricted_gate",
            CheckVerdict.PASS if ok else CheckVerdict.FAIL,
            "no restricted material without a passed gate"
            if ok
            else "method material used without a released approval and a method topic",
            blocking=True,
            rule_id=None if ok else "FIN-R12",
            measured=len(labelled),
        )

    @staticmethod
    def _copy(pack: ResearchPack, results: Mapping[str, CopyResult]) -> ValidationResult:
        failed = 0
        for ev in pack.evidence:
            if not ev.usable_for_script:
                continue
            res = results.get(ev.evidence_id)
            if ev.copy_guard is CopyGuardStatus.PASSED and (res is None or not res.passed):
                failed += 1
        return _result(
            "a04.copy_guard",
            CheckVerdict.FAIL if failed else CheckVerdict.PASS,
            "no usable note above the copy-guard thresholds"
            if not failed
            else f"{failed} usable notes lack a passed copy-guard result",
            blocking=True,
            rule_id=None if not failed else "YTG-R9",
            measured=failed,
        )

    @staticmethod
    def _forward(pack: ResearchPack) -> ValidationResult:
        bad = sum(
            1
            for e in pack.evidence
            if e.usable_for_script and e.time_reference_kind is TimeReferenceKind.FUTURE
        )
        return _result(
            "a04.forward_looking_excluded",
            CheckVerdict.FAIL if bad else CheckVerdict.PASS,
            "no usable note is forward-looking"
            if not bad
            else f"{bad} usable notes carry a future reference",
            blocking=True,
            rule_id="FIN-R13" if bad else None,
            measured=bad,
        )


def _ok(check_id: str, message: str) -> ValidationResult:
    return _result(check_id, CheckVerdict.PASS, message, blocking=True)


def coverage_share(pack: ResearchPack) -> float:
    total = len(pack.concepts)
    return sum(c.coverage is Coverage.SOURCED for c in pack.concepts) / total if total else 0.0
