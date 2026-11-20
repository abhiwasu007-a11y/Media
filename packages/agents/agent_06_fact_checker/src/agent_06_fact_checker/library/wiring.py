"""Stage wiring of the exact-quote check into ``ClaimVerificationStep`` (D12; CCR-302 PROPOSED).

CCR-291 built the verifier but left one gap: the extraction schema (``ExtractedClaim``) carries
``citation_refs`` only, no ``work_id`` and no ``locator``. PROVISIONAL default (CCR-302, nothing is
added to any contract): the library INDEX (which the private library repository maintains and the
composition root loads next to the library path and commit SHA of the job) maps a ``citation_ref``
to ``(work_id, locator, names)``. From it the stage derives, per ``QUOTED_THIRD_PARTY`` claim:

* the work and the chapter / verse: from the claim's own ``citation_refs``; two different works or
  places, or none the index knows, mean no source (fail closed);
* the quoted words: the spans in quotation marks inside ``claim.quote``; no span is an empty quote;
* the attributed author: the author the claim text NAMES (a name from the index, whole word). The
  cited work's author named: its canonical author. A different known author named: that author
  (the verifier then reports an attribution mismatch and blocks). Nobody named: no source, the
  quote is removed or reworded.

The check is authoritative for such a claim: the model is not asked about it. Statuses follow
CCR-291 exactly (existing contract values only). Library text never leaves the verifier: the
outcome carries codes only. A work that is not public domain is never read; it can be used for
ideas only and then needs the further-reading credit (``credit_line``)."""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from agent_06_fact_checker.library.copyright import WorkCopyrightRecord
from agent_06_fact_checker.library.credits import WorkUse, credit_line
from agent_06_fact_checker.library.quotes import (
    QuoteAction,
    QuoteCheckResult,
    QuoteCode,
    QuoteSettings,
    QuoteSubmission,
    QuoteVerifier,
    find_quoted_spans,
    normalise_quote_text,
    unreadable_result,
)
from agent_06_fact_checker.library.reader import (
    CheckoutLibraryReader,
    LibraryLimits,
    LibraryRef,
)
from agent_06_fact_checker.models import (
    ClaimMode,
    VerificationClaim,
    VerificationInput,
)
from agent_06_fact_checker.planner import ClaimPlan
from agent_06_fact_checker.reconcile import Outcome
from amw_core.contracts.common import AmwModel
from amw_core.contracts.task_input import TaskInput
from amw_core.enums import ClaimStatus, ClaimType
from amw_core.errors import InputInvalidError, MissingDependencyError

CREDITS_SCHEMA = "agent_06.quote_credits"
CREDITS_VERSION = "1.0.0"
CREDITS_FILE = "quote_credits.json"


@dataclass(frozen=True, slots=True)
class WorkRef:
    """One entry of the library index: where a citation lives."""

    work_id: str
    locator: str | None
    """Chapter / verse as the library text marks it (``§ <locator>``), ``None`` when unknown."""
    names: tuple[str, ...]
    """Names under which scripts attribute the author (``Seneca``); the canonical author of the
    work record is always accepted."""


class LibraryIndex(Protocol):
    def lookup(self, citation_ref: str) -> WorkRef | None: ...


class StaticLibraryIndex:
    """In-memory index (tests, and the loader of the private index file at the composition root)."""

    def __init__(self, entries: Mapping[str, WorkRef]) -> None:
        self._entries = dict(entries)

    def lookup(self, citation_ref: str) -> WorkRef | None:
        return self._entries.get(citation_ref)

    def works(self) -> dict[str, WorkRef]:
        return {e.work_id: e for e in self._entries.values()}


class CreditEntry(AmwModel):
    work_id: str
    use: WorkUse
    credit_line: str | None
    """``None`` when the work has no record (the gate must fail closed)."""


class QuoteCredits(AmwModel):
    """Credit data for the script gate and agent_16 (``quote_credits.json``, a second artifact of
    the verification task, never a change of the verification payload)."""

    schema_version: str = CREDITS_VERSION
    script_id: str
    script_sha256: str
    works: tuple[CreditEntry, ...]


@dataclass(frozen=True, slots=True)
class QuoteReview:
    outcomes: dict[str, Outcome]
    """``local_id`` -> code-derived outcome of every quote claim."""
    used: dict[str, WorkUse]
    """Every library work the script used: ``QUOTED`` only for a verified exact quote."""
    codes: dict[str, tuple[QuoteCode, ...]]


_RANK = {QuoteAction.KEEP: 0, QuoteAction.REMOVE_QUOTE: 1, QuoteAction.BLOCK_CLAIM: 2}


def _names_in(text: str, names: Sequence[str]) -> bool:
    """A name occurs as whole words (case-insensitive, NFC, whitespace folded)."""
    hay = normalise_quote_text(text).casefold()
    for raw in names:
        name = normalise_quote_text(raw).casefold()
        if name and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", hay):
            return True
    return False


class QuoteCheck:
    """Quote verification of the claims of one verification task."""

    def __init__(
        self,
        verifier: QuoteVerifier,
        records: Mapping[str, WorkCopyrightRecord],
        index: StaticLibraryIndex,
        *,
        job_date: date,
    ) -> None:
        self._verifier = verifier
        self._records = records
        self._index = index
        self._job_date = job_date

    def _target(self, claim: VerificationClaim) -> WorkRef | None:
        refs = {self._index.lookup(r) for r in claim.citation_refs}
        refs.discard(None)
        pairs = {(r.work_id, r.locator) for r in refs if r is not None}
        if len(pairs) != 1:
            return None
        return next(r for r in refs if r is not None)

    def _attributed(self, claim: VerificationClaim, target: WorkRef) -> str | None:
        text = f"{claim.quote} {claim.normalized_claim}"
        record = self._records.get(target.work_id)
        own = (*target.names, record.author) if record is not None else target.names
        if _names_in(text, own):
            return record.author if record is not None else None
        for other in self._index.works().values():
            rec = self._records.get(other.work_id)
            if (
                rec is not None
                and other.work_id != target.work_id
                and _names_in(text, (*other.names, rec.author))
            ):
                return rec.author
        return None

    def _submissions(self, claim: VerificationClaim) -> list[QuoteSubmission]:
        target = self._target(claim)
        author = self._attributed(claim, target) if target is not None else None
        spans = [claim.quote[s.start : s.end] for s in find_quoted_spans(claim.quote)] or [""]
        return [
            QuoteSubmission(
                claim_id=claim.claim_id,
                quoted_text=span,
                attributed_author=author or "",
                work_id=target.work_id if target is not None and author is not None else None,
                locator=target.locator if target is not None else None,
            )
            for span in spans
        ]

    def _is_guarded(self, claim: VerificationClaim) -> bool:
        """Fake-quote guard (claim level): a claim that is NOT typed as a quote, but holds a quoted
        span of ``guard_min_words`` words or more and names an author of the library, is treated
        as a quote claim too. The script text itself is not part of the verification input, so a
        quotation that was never extracted as a claim cannot be seen here (documented limit)."""
        words = self._verifier.settings.guard_min_words
        long_span = any(s.words >= words for s in find_quoted_spans(claim.quote))
        if not long_span:
            return False
        text = f"{claim.quote} {claim.normalized_claim}"
        for entry in self._index.works().values():
            record = self._records.get(entry.work_id)
            names = (*entry.names, record.author) if record is not None else entry.names
            if _names_in(text, names):
                return True
        return False

    def _verify(self, claim: VerificationClaim) -> list[QuoteCheckResult]:
        subs = self._submissions(claim)
        try:
            return self._verifier.verify(subs, job_date=self._job_date)
        except InputInvalidError, MissingDependencyError, OSError:
            # the library could not be read or is not the pinned commit: typed, fail closed
            return [unreadable_result(sub) for sub in subs]

    def review(self, plans: Sequence[ClaimPlan]) -> QuoteReview:
        outcomes: dict[str, Outcome] = {}
        codes: dict[str, tuple[QuoteCode, ...]] = {}
        used: dict[str, WorkUse] = {}
        for plan in plans:
            claim = plan.claim
            for ref in claim.citation_refs:  # every cited work is at least further reading
                found = self._index.lookup(ref)
                if found is not None:
                    used.setdefault(found.work_id, WorkUse.IDEAS_ONLY)
        for plan in plans:
            claim = plan.claim
            if plan.mode is ClaimMode.SKIPPED:
                continue
            typed = claim.claim_type is ClaimType.QUOTED_THIRD_PARTY
            if not typed and not self._is_guarded(claim):
                continue
            results = self._verify(claim)
            worst = max(results, key=lambda r: (_RANK[r.action], r.status.value))
            codes[claim.local_id] = tuple(r.code for r in results)
            kept = worst.action is QuoteAction.KEEP
            if kept:
                for r in results:
                    if r.work_id is not None:
                        used[r.work_id] = WorkUse.QUOTED
            if typed:
                outcomes[claim.local_id] = _outcome(claim, worst, plan)
            elif not kept:  # guarded claim whose quote is not proven: human review, no model call
                outcomes[claim.local_id] = _outcome(claim, _unproven(worst), plan)
            # a guarded claim with a proven quote continues on the normal evidence path
        return QuoteReview(outcomes, used, codes)

    def credits(
        self, review: QuoteReview, *, script_id: str, script_sha256: str
    ) -> QuoteCredits | None:
        if not review.used:
            return None
        entries = []
        for work_id in sorted(review.used):
            record = self._records.get(work_id)
            use = review.used[work_id]
            entries.append(
                CreditEntry(
                    work_id=work_id,
                    use=use,
                    credit_line=credit_line(record, use) if record is not None else None,
                )
            )
        return QuoteCredits(script_id=script_id, script_sha256=script_sha256, works=tuple(entries))


def _unproven(worst: QuoteCheckResult) -> QuoteCheckResult:
    """A not-proven quote inside a claim that is not typed as a quote is never ``CONTRADICTED``
    here (the claim's other content was not checked): it goes to a human."""
    if worst.status is ClaimStatus.CONTRADICTED:
        return worst.model_copy(update={"status": ClaimStatus.NEEDS_SUBSTANTIATION})
    return worst


def _outcome(claim: VerificationClaim, worst: QuoteCheckResult, plan: ClaimPlan) -> Outcome:
    verified = worst.status is ClaimStatus.VERIFIED
    return Outcome(
        claim,
        ClaimMode.CODE_ONLY,
        worst.status,
        [] if worst.reason is None else [worst.reason],
        script_cited=verified,
        quote_exact=verified,
    )


class QuoteCheckFactory(Protocol):
    """Builds the quote check of ONE verification job (the library is pinned per job)."""

    def __call__(
        self, task: TaskInput, inp: VerificationInput, *, job_date: date, required: bool
    ) -> QuoteCheck | None:
        """``required`` is true when the script has a claim typed as a quote. A required check
        that cannot be built is a typed error (never a silent fallback to the model); one that is
        not required may be ``None``."""
        ...


@dataclass(frozen=True, slots=True)
class LibraryQuoteCheckFactory:
    """Production wiring: a ``QuoteCheck`` over the read-only library reader (D12).

    The verification payload (contract 03) carries no library reference, so the composition root
    supplies ``ref_for_job``: it returns the library path and FULL commit SHA that belong to the
    job (``None`` when the job has none). The index, the work records, the limits and the quote
    settings are configuration owned by the composition root; their file formats belong to the
    private library repository and are not defined here."""

    ref_for_job: Callable[[TaskInput], LibraryRef | None]
    limits: LibraryLimits
    settings: QuoteSettings
    records: Mapping[str, WorkCopyrightRecord]
    index: StaticLibraryIndex

    def __call__(
        self, task: TaskInput, inp: VerificationInput, *, job_date: date, required: bool
    ) -> QuoteCheck | None:
        ref = self.ref_for_job(task)
        if ref is None:
            if required:
                raise MissingDependencyError(
                    "the script quotes a third party but the job carries no library reference "
                    "(path and commit SHA): quotes cannot be verified",
                    details={"reason": "QUOTE_LIBRARY_REF_MISSING"},
                )
            return None
        reader = CheckoutLibraryReader(ref, self.limits)  # typed: missing path / HEAD != SHA
        verifier = QuoteVerifier(self.records, reader, self.settings)
        return QuoteCheck(verifier, self.records, self.index, job_date=job_date)
