"""ComplianceGate (``agent_16.compliance_gate``, ``s16_comp``; F-01, F-15; blueprint section 4 CG).

Order (deterministic first): C0 verified packs -> C1 code rule checks -> C2 pre-filter ->
C3 policy judge on the flagged items only -> C4/C5 near-copy and paraphrase judge on the
candidates -> C3f frames judge -> C6 disclosure -> C7 algebra -> payload + gate results.
A judge answer can never clear a code flag; doubt goes to the owner (``review_requests``).
Inputs arrive assembled by ``GateInputAssembler`` (RLS reads, ref and hash checks: plumbing).
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from typing import Any, Final, Literal

from pydantic import Field

from agent_16_compliance_qa.algebra import evaluate_policy, overall_verdict, post_check
from agent_16_compliance_qa.base import Model, worst
from agent_16_compliance_qa.checks import RuleResult, needs_human
from agent_16_compliance_qa.checks import rules as R  # noqa: N812
from agent_16_compliance_qa.config import Agent16Config
from agent_16_compliance_qa.judge.frames import FrameCheck, apply_frames
from agent_16_compliance_qa.judge.models import (
    FrameCheckId,
    FramesOutput,
    ItemChart,
    ItemClaim,
    ParaphraseInput,
    ParaphraseOutput,
    ParaphrasePair,
    PolicyInput,
    PolicyItem,
    PolicyOutput,
    Surface,
)
from agent_16_compliance_qa.judge.paraphrase import QuotationApproval, apply_paraphrase
from agent_16_compliance_qa.nearcopy import NearCopyResult
from agent_16_compliance_qa.packs import LoadedPacks
from agent_16_compliance_qa.prefilter import select_rules
from amw_core.contracts.task_output import ValidationResult
from amw_core.enums import (
    AudienceKind,
    CheckKind,
    CheckVerdict,
    ComplianceVerdict,
    DisclosureDecision,
    PresenterKind,
)
from amw_core.errors import InputInvalidError, InsufficientInputError

_LOG = logging.getLogger(__name__)
FINANCE_PACK: Final = "rp.finance_sebi_in"
KIDS_PACK: Final = "rp.kids"
_COPYRIGHT_RULES: Final = frozenset({"YTG-R5", "YTG-R6", "YTG-R9"})
_DISCLOSURE_KEYS: Final = {
    DisclosureDecision.REQUIRED: "disclosure.required",
    DisclosureDecision.NOT_REQUIRED: "disclosure.not_required",
    DisclosureDecision.NEEDS_HUMAN_REVIEW: "disclosure.needs_human_review",
}


class SourceItem(Model):
    """One text item (script segment, on-screen text, thumbnail text, title, description)."""

    ref: str
    surface: Surface
    text: str
    context_before: str = ""
    context_after: str = ""
    named_instruments: tuple[str, ...] = ()
    claims: tuple[ItemClaim, ...] = ()
    chart: ItemChart | None = None


class Routing(Model):
    script_stage_id: str
    assets_stage_id: str
    thumbnails_stage_id: str | None


class GateInputs(Model):
    channel_category: str
    language: str
    sensitive_channel: bool
    routing: Routing
    items: tuple[SourceItem, ...]
    charts: tuple[R.ChartAge, ...]
    text_prices: tuple[R.TextPrice, ...]
    disclaimer_spoken: bool
    disclaimer_onscreen: bool
    disclaimer_template_version: str | None
    metadata_present: bool
    description_hash_matches: bool | None
    method_segments: tuple[R.MethodSegment, ...]
    method_label_overlay: bool
    production_type_key: str
    live_format: Literal["STANDARD", "LIVE"]
    metadata_terms: tuple[str, ...] | None
    presenter_kind: PresenterKind | None
    voice_known: bool
    render_person_assets: tuple[R.PersonAsset, ...]
    thumbnail_person_assets: tuple[R.PersonAsset, ...]
    licensed_assets: tuple[R.LicensedAsset, ...]
    audience_kind: AudienceKind | None
    disclosure_assets: tuple[R.DisclosureAsset, ...]
    realism_shots: tuple[R.RealismShot, ...]
    voice_kind: R.VoiceKind | None
    paraphrase_pairs: tuple[ParaphrasePair, ...] = ()
    span_hashes: Mapping[str, str] = Field(default_factory=dict)
    quotation_approvals: tuple[tuple[str, str], ...] = ()
    """(span sha256, F-26 derived state) of ``COPYRIGHT_DOUBT`` approvals."""
    near_copy: tuple[NearCopyResult, ...] = ()
    frame_ids: tuple[str, ...] = ()
    frames_payload: Mapping[str, Any] | None = None
    uniqueness_verdict: ComplianceVerdict
    evaluation_date: date


PolicyJudge = Callable[[PolicyInput], PolicyOutput]
ParaphraseJudge = Callable[[ParaphraseInput], ParaphraseOutput]
FramesJudge = Callable[[Mapping[str, Any]], FramesOutput]


class GateDecision(Model):
    verdict: ComplianceVerdict
    rules: tuple[RuleResult, ...]
    frame_checks: tuple[FrameCheck, ...]
    disclosure: R.DisclosureResult
    earliest_compliant_publish_date: date | None
    injection_items: tuple[str, ...]
    quote_failures: int
    judge_calls: int


def _local_items(
    inputs: GateInputs, packs: LoadedPacks, cfg: Agent16Config
) -> tuple[list[PolicyItem], dict[str, str]]:
    lexicon = cfg.prefilter_lexicon(inputs.language)
    active = packs.active_rule_ids
    items: list[PolicyItem] = []
    refs: dict[str, str] = {}
    for item in inputs.items:
        rules = select_rules(item.text, item.named_instruments, item.claims, lexicon, active)
        if not rules:
            continue
        local = f"i{len(items) + 1:02d}"
        refs[local] = item.ref
        items.append(
            PolicyItem(
                item_id=local,
                surface=item.surface,
                text=item.text,
                context_before=item.context_before,
                context_after=item.context_after,
                named_instruments=item.named_instruments,
                claims=item.claims,
                chart=item.chart,
                rules_to_check=rules,
            )
        )
    return items, refs


class ComplianceGate:
    def __init__(
        self,
        cfg: Agent16Config,
        packs: LoadedPacks,
        policy_judge: PolicyJudge,
        paraphrase_judge: ParaphraseJudge,
        frames_judge: FramesJudge,
    ) -> None:
        self._cfg, self._packs = cfg, packs
        self._policy, self._para, self._frames = policy_judge, paraphrase_judge, frames_judge

    def deterministic(self, inp: GateInputs) -> list[RuleResult]:
        """C1: every deterministic rule of an active pack (13 section 1.4)."""
        active = self._packs.active_rule_ids
        out: list[RuleResult] = []
        finance = FINANCE_PACK in self._packs.keys
        if finance:
            out.append(
                R.price_lag(list(inp.charts), list(inp.text_prices), self._cfg.price_data_lag_days)
            )
            out.append(
                R.disclaimer(
                    inp.disclaimer_spoken,
                    inp.disclaimer_onscreen,
                    inp.disclaimer_template_version,
                    inp.metadata_present,
                    inp.description_hash_matches,
                )
            )
            out.append(R.method_release(list(inp.method_segments), inp.method_label_overlay))
            out.append(
                R.live_format(
                    inp.production_type_key,
                    inp.live_format,
                    list(inp.metadata_terms) if inp.metadata_terms is not None else None,
                    self._cfg.lexicon(inp.language).live_format_terms,
                )
            )
        out.append(
            R.persona(
                inp.sensitive_channel,
                inp.presenter_kind,
                inp.voice_known,
                list(inp.render_person_assets),
                list(inp.thumbnail_person_assets),
            )
        )
        r5, r6, _ = R.licence(list(inp.licensed_assets))
        out += [r5, r6]
        out.append(R.audience(inp.audience_kind, KIDS_PACK in self._packs.keys))
        for nc in inp.near_copy:
            if nc.exceeds_threshold:  # a code flag: the paraphrase judge cannot clear it
                out.append(
                    needs_human(
                        "YTG-R9",
                        "near-copy measure above threshold",
                        item_refs=(nc.sentence_ref,),
                        remedy="script",
                        evidence={
                            "chunk_id": nc.chunk_id,
                            "overlap_ratio": nc.overlap_ratio,
                            "lcs_chars": nc.lcs_chars,
                        },
                    )
                )
        return [r for r in out if r.rule_id in active]

    def evaluate(self, inp: GateInputs) -> GateDecision:
        det = self.deterministic(inp)
        calls = 0
        judged: list[RuleResult] = []
        injection: list[str] = []
        quote_failures = 0
        items, refs = _local_items(inp, self._packs, self._cfg)
        size = self._cfg.max_items_per_judge_call
        severities = {r: self._packs.severity(r) for r in self._packs.active_rule_ids}
        for start in range(0, len(items), size):
            batch = PolicyInput(
                channel_category=inp.channel_category,
                owner_sebi_registration="UNREGISTERED",
                language=inp.language,
                active_rule_ids=tuple(sorted(self._packs.active_rule_ids)),
                items=tuple(items[start : start + size]),
            )
            out = self._policy(batch)
            calls += 1
            if out.refusal is not None:
                if out.refusal.reason == "INSUFFICIENT_INPUT":
                    raise InsufficientInputError("policy judge: insufficient input")
                if out.refusal.reason in ("OUT_OF_SCOPE", "CONFLICTING_INSTRUCTIONS"):
                    raise InputInvalidError(f"policy judge refusal {out.refusal.reason}")
            check = post_check(batch, out)
            quote_failures += check.quote_failures
            injection += [refs[i] for i in check.injection_items]
            for r in evaluate_policy(
                batch, check, self._cfg.prefilter_lexicon(inp.language), severities
            ):
                judged.append(
                    r.model_copy(update={"item_refs": tuple(refs.get(i, i) for i in r.item_refs)})
                )
        if inp.paraphrase_pairs and "YTG-R9" in self._packs.active_rule_ids:
            pin = ParaphraseInput(language_script=inp.language, pairs=inp.paraphrase_pairs)
            pout = self._para(pin)
            calls += 1
            approvals = [QuotationApproval(h, s) for h, s in inp.quotation_approvals]  # type: ignore[arg-type]
            pd = apply_paraphrase(pin, pout, inp.span_hashes, approvals)
            for pv in pd.pairs:
                cv = {
                    ComplianceVerdict.ALLOWED: CheckVerdict.PASS,
                    ComplianceVerdict.BLOCKED: CheckVerdict.FAIL,
                }.get(pv.verdict, CheckVerdict.WARN)
                judged.append(
                    RuleResult(
                        rule_id="YTG-R9",
                        check_verdict=cv,
                        compliance_verdict=pv.verdict,
                        kind=CheckKind.LLM_JUDGE,
                        rationale=pv.rationale[:1000],
                        item_refs=(pv.pair_id,),
                        remedy="script",
                        evidence={
                            "decision": pv.decision,
                            "is_quotation": pv.is_quotation,
                            "approval_applied": pv.approval_applied,
                        },
                    )
                )
        if injection or quote_failures:  # section 19.3 rule 9 / section 22 (no content text)
            _LOG.warning(
                "a16.gate.injection_or_quote_failure",
                extra={"injection_items": len(injection), "quote_failures": quote_failures},
            )
        checks: list[FrameCheckId] = ["qc.watermark.visual"]
        if inp.sensitive_channel:
            checks.append("qc.visual.no_synthetic_presenter")
        fout: FramesOutput | None = None
        if inp.frames_payload is not None and inp.frame_ids:
            fout = self._frames(inp.frames_payload)
            calls += 1
        frames = apply_frames(
            checks,
            inp.sensitive_channel,
            inp.frame_ids,
            fout,
            self._cfg.watermark_visual_calibrated,
        )
        disc = R.disclosure(list(inp.disclosure_assets), list(inp.realism_shots), inp.voice_kind)
        if "YTG-R3" in self._packs.active_rule_ids:
            det.append(
                RuleResult(
                    rule_id="YTG-R3",
                    check_verdict=disc.check_verdict,
                    compliance_verdict=disc.compliance_verdict,
                    rationale=disc.rationale[:1000],
                    evidence={
                        "disclosure_decision": disc.disclosure_decision.value,
                        "decided_by_order": disc.decided_by_order,
                    },
                )
            )
        rules = [apply_severity(r, self._packs) for r in (*det, *judged)]
        if inp.uniqueness_verdict is not ComplianceVerdict.ALLOWED and "YTG-R1" in (
            self._packs.active_rule_ids
        ):
            rules.append(uniqueness_rule(inp.uniqueness_verdict))
        presenter = [f.compliance_verdict for f in frames]  # V10 adds NHR only, never BLOCKED
        verdict = overall_verdict(
            rules,
            inp.uniqueness_verdict,
            disc.disclosure_decision is DisclosureDecision.NEEDS_HUMAN_REVIEW,
            presenter,
        )
        lag = next((r for r in det if r.rule_id == "FIN-R9"), None)
        earliest = None
        if lag is not None and lag.evidence.get("youngest_age_days") is not None:
            wait = self._cfg.price_data_lag_days - int(lag.evidence["youngest_age_days"])
            earliest = inp.evaluation_date + timedelta(days=wait)
        return GateDecision(
            verdict=verdict,
            rules=tuple(rules),
            frame_checks=tuple(frames),
            disclosure=disc,
            earliest_compliant_publish_date=earliest,
            injection_items=tuple(injection),
            quote_failures=quote_failures,
            judge_calls=calls,
        )


def apply_severity(result: RuleResult, packs: LoadedPacks) -> RuleResult:
    """V8 (review M1): a failing WARNING-severity rule is ``WARN`` with no compliance verdict,
    so the algebra's verdict and the blocking gate results always agree."""
    if (
        result.compliance_verdict is ComplianceVerdict.BLOCKED
        and result.rule_id in packs.active_rule_ids
        and packs.severity(result.rule_id) != "BLOCKING"
    ):
        return result.model_copy(
            update={
                "check_verdict": CheckVerdict.WARN,
                "compliance_verdict": None,
                "rationale": f"warning-severity rule (V8): {result.rationale}"[:1000],
            }
        )
    return result


def uniqueness_rule(verdict: ComplianceVerdict) -> RuleResult:
    """The S2 uniqueness verdict as the YTG-R1 gate row (blocked => script revision)."""
    blocked = verdict is ComplianceVerdict.BLOCKED
    return RuleResult(
        rule_id="YTG-R1",
        check_verdict=CheckVerdict.FAIL if blocked else CheckVerdict.WARN,
        compliance_verdict=verdict,
        rationale=f"svc_s02 uniqueness verdict {verdict.value}",
        remedy="script",
    )


def rule_rows(decision: GateDecision) -> list[RuleResult]:
    """One row per rule: the worst result over its items (payload ``rules[]``)."""
    by_rule: dict[str, list[RuleResult]] = {}
    for r in decision.rules:
        by_rule.setdefault(r.rule_id, []).append(r)
    rows = []
    for rid in sorted(by_rule):
        group = by_rule[rid]
        v = worst(r.compliance_verdict for r in group)
        pick = next(
            (r for r in group if r.compliance_verdict is v and v is not ComplianceVerdict.ALLOWED),
            None,
        ) or next((r for r in group if r.check_verdict is CheckVerdict.WARN), group[0])
        refs = tuple(sorted({i for r in group for i in r.item_refs}))
        kind = (
            CheckKind.LLM_JUDGE
            if any(r.kind is CheckKind.LLM_JUDGE for r in group)
            else CheckKind.DETERMINISTIC
        )
        rows.append(pick.model_copy(update={"item_refs": refs, "kind": kind}))
    return rows


def remedy_stage(result: RuleResult, routing: Routing) -> str | None:
    if result.check_verdict is not CheckVerdict.FAIL:
        return None
    if result.remedy == "assets":
        return routing.assets_stage_id
    if result.remedy == "thumbnails" and routing.thumbnails_stage_id:
        return routing.thumbnails_stage_id
    return routing.script_stage_id


def validation_results(
    decision: GateDecision, routing: Routing, packs: LoadedPacks
) -> list[ValidationResult]:
    """Domain results of the registered blocking gate ``s16_comp``: ``gate: true``; a WARN or
    SKIPPED result never blocks; a failing result names ``remedy_stage_id`` (24 section 3.3)."""
    out = []
    for r in rule_rows(decision):
        blocking = (
            (
                r.check_verdict is CheckVerdict.FAIL
                and r.compliance_verdict is ComplianceVerdict.BLOCKED
                and packs.severity(r.rule_id) == "BLOCKING"
            )
            if r.rule_id in packs.active_rule_ids
            else False
        )
        out.append(
            ValidationResult(
                check_id=r.rule_id.lower().replace("-", "."),
                kind=r.kind,
                verdict=r.check_verdict,
                blocking=blocking,
                rule_id=r.rule_id,
                message=r.rationale[:2000],
                gate=True,
                remedy_stage_id=remedy_stage(r, routing) if blocking else None,
            )
        )
    for f in decision.frame_checks:
        out.append(
            ValidationResult(
                check_id=f.check_id,
                kind=CheckKind.LLM_JUDGE,
                verdict=f.verdict,
                blocking=f.blocking,
                rule_id="YTG-R2" if "presenter" in f.check_id else None,
                message=f.rationale or f.finding,
                gate=True,
                remedy_stage_id=routing.assets_stage_id if f.blocking else None,
            )
        )
    if decision.verdict is ComplianceVerdict.BLOCKED and not any(r.blocking for r in out):
        out.append(  # fail closed: a BLOCKED verdict always carries a blocking gate result
            ValidationResult(
                check_id="a16.gate.verdict",
                kind=CheckKind.DETERMINISTIC,
                verdict=CheckVerdict.FAIL,
                blocking=True,
                rule_id=None,
                message="compliance verdict BLOCKED",
                gate=True,
                remedy_stage_id=routing.script_stage_id,
            )
        )
    return out


def review_requests(decision: GateDecision) -> list[dict[str, str]]:
    """FR-12: every NEEDS_HUMAN_REVIEW item names its rule, evidence and approval kind (only
    ``SENSITIVE_CLAIM`` / ``COPYRIGHT_DOUBT`` exist for this, 24 section 3.3 rule 2)."""
    out = []
    for r in rule_rows(decision):
        if r.compliance_verdict is ComplianceVerdict.NEEDS_HUMAN_REVIEW:
            kind = "COPYRIGHT_DOUBT" if r.rule_id in _COPYRIGHT_RULES else "SENSITIVE_CLAIM"
            out.append(
                {
                    "rule_id": r.rule_id,
                    "approval_kind": kind,
                    "evidence_ref": "items:" + ",".join(r.item_refs or (r.rule_id,)),
                }
            )
    for f in decision.frame_checks:
        if f.compliance_verdict is ComplianceVerdict.NEEDS_HUMAN_REVIEW:
            out.append(
                {
                    "rule_id": "YTG-R2",
                    "approval_kind": "SENSITIVE_CLAIM",
                    "evidence_ref": "frames:" + ",".join(f.frame_ids or ("none",)),
                }
            )
    return out


def gate_payload(
    decision: GateDecision,
    subject: Mapping[str, str],
    routing: Routing,
    packs: LoadedPacks,
    verdict_ids: Sequence[str],
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    """``agent_16.compliance_gate.output`` 1.0.0 (section 8.2)."""
    rows = rule_rows(decision)
    pack_rows = []
    for p in packs.packs:
        v = worst(r.compliance_verdict for r in rows if r.rule_id in p.rules)
        pack_rows.append(
            {"key": p.key, "version": p.version, "rule_pack_id": p.rule_pack_id, "verdict": v.value}
        )
    findings = [
        {
            "rule_id": r.rule_id,
            "item_ref": ref,
            "finding": r.rationale[:500],
            "remedy_stage_id": remedy_stage(r, routing),
        }
        for r in rows
        if r.check_verdict is CheckVerdict.FAIL
        for ref in (r.item_refs or (r.rule_id,))
    ]
    gate_failed = any(v.blocking for v in validation_results(decision, routing, packs))
    return {
        "verdict": decision.verdict.value,
        "subject": dict(subject),
        "packs": pack_rows,
        "rules": [
            {
                "rule_id": r.rule_id,
                "check_verdict": r.check_verdict.value,
                "compliance_verdict": r.compliance_verdict.value if r.compliance_verdict else None,
                "kind": r.kind.value,
                "rationale": r.rationale[:1000],
                "evidence": {**r.evidence, "item_refs": list(r.item_refs)},
                "precondition": r.precondition,
                "remedy_stage_id": remedy_stage(r, routing),
            }
            for r in rows
        ],
        "frame_checks": [
            {
                "check_id": f.check_id,
                "finding": f.finding,
                "frame_ids": list(f.frame_ids),
                "verdict": f.verdict.value,
                "rationale": f.rationale[:500],
            }
            for f in decision.frame_checks
        ],
        "disclosure": {
            "decision": decision.disclosure.disclosure_decision.value,
            "rationale": decision.disclosure.rationale,
            "report_text_key": _DISCLOSURE_KEYS[decision.disclosure.disclosure_decision],
        },
        "earliest_compliant_publish_date": (
            decision.earliest_compliant_publish_date.isoformat()
            if decision.earliest_compliant_publish_date
            else None
        ),
        "review_requests": review_requests(decision),
        "revision_findings": findings,
        "verdict_ids": list(verdict_ids),
        "gate_verdict": "FAILED" if gate_failed else "PASSED",
        "provenance": dict(provenance)
        | {
            "judge_calls": decision.judge_calls,
            "quote_verification_failures": decision.quote_failures,
            "injection_suspected": list(decision.injection_items),
        },
    }
