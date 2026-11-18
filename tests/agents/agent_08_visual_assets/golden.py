# mypy: disable-error-code="arg-type,attr-defined,misc,has-type,no-untyped-def,no-any-return"
# mypy: disable-error-code="assignment,union-attr,index,call-arg"
# (test helpers feed dataset dicts and fakes into typed APIs; the package is strict clean)
"""Adapters from the deterministic_core dataset cases to the Agent 08 functions."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from agent_08_visual_assets.cascade.selection import (
    Assessment,
    Fit,
    RankedCandidate,
    SafetyFloor,
    TieBreaker,
)
from agent_08_visual_assets.cascade.share import TierShareGuard
from agent_08_visual_assets.cascade.tier_cascade import (
    Attempt,
    ChartAttempt,
    IntentKind,
    Probes,
    StepRefusalReason,
    TierCascade,
    accept,
    chart_preconditions,
    skip_with,
)
from agent_08_visual_assets.charts.annotations import Annotation, AnnotationValidator
from agent_08_visual_assets.charts.facts import ChartFactsBuilder, FactBar
from agent_08_visual_assets.charts.lag import ChartLagGuard, EarliestPublishDate
from agent_08_visual_assets.charts.spec import ChartSpecHasher
from agent_08_visual_assets.checkpoint import CheckpointManager
from agent_08_visual_assets.errors import AdapterErrorMapper, MapOutcome, ProviderOutcome
from agent_08_visual_assets.gate import GateRouter, Unresolved
from agent_08_visual_assets.guards import TenantGuard
from agent_08_visual_assets.licence.disclosure import DisclosureFlags
from agent_08_visual_assets.licence.guard import LicenceGuard, LicenceView
from agent_08_visual_assets.licence.ledger import (
    CoverageVerifier,
    CoverElement,
    CoverRow,
    LedgerRowBuilder,
)
from agent_08_visual_assets.licence.timeline import OverlayInput, TimelineLedgerPlanner
from agent_08_visual_assets.models.common import Sha256Hex  # noqa: F401
from agent_08_visual_assets.plan.revision import ChangedShotSelector, ShotKey
from agent_08_visual_assets.registrar import SourceIntakeGuard
from agent_08_visual_assets.reuse.engine import ReuseCandidate, ReuseEngine, ReuseRequest
from agent_08_visual_assets.reuse.fingerprint import FingerprintDHash, hamming
from agent_08_visual_assets.sources.ai_budget import AiBudgetGate
from agent_08_visual_assets.sources.ai_prompt import AiPromptComposer, Lexicon
from amw_core.enums import (  # noqa: F401
    ActorKind,
    AssetKind,
    AssetStatus,
    ChartDataKind,
    DataAgeVsLag,
    LicenceDestination,
    LicenceSourceType,
    LicenceState,
    ShotUnresolvedReason,
    ThirdPartyPermission,
    VisualSkipReason,
    VisualSourceTier,
)
from amw_core.errors import (
    AmwError,
    InputInvalidError,  # noqa: F401
)

TODAY = date(2026, 1, 1)
TEST_LEXICON = Lexicon(
    "lex_a08_test_v1",
    presenter_terms=("anchor", "presenter", "host", "spokesperson", "reporter"),
    market_data_terms=("candlestick", "chart", "ticker", "trading screen", "stock market"),
)


def _off(n: int | None) -> date | None:
    return None if n is None else TODAY + timedelta(days=n)


def _err(exc: AmwError) -> dict[str, Any]:
    return {"status": "ERROR", "error_code": type(exc).code}


def run_case(function: str, i: dict[str, Any]) -> dict[str, Any]:
    if function == "ChartLagGuard.classify":
        try:
            starts = i["last_bar_start_offsets"]
            r = ChartLagGuard.classify(
                timeframe=i["timeframe"],
                lag_days=i["lag_days"],
                platform_min_lag_days=i["platform_min_lag_days"],
                last_bar_start=None if i["data_missing"] or not starts else _off(starts[-1]),
                period_end=_off(i["period_end_offset"]),
                today=TODAY,
            )
        except AmwError as exc:
            return _err(exc)
        end = r.data_end_date
        return {
            "status": "OK",
            "data_end_offset": None if end is None else (end - TODAY).days,
            "age_days": r.age_days,
            "data_age_vs_lag": r.data_age_vs_lag.value,
            "usable": r.usable,
            "earliest_publish_offset": None
            if r.earliest_publish_date is None
            else (r.earliest_publish_date - TODAY).days,
        }
    if function == "EarliestPublishDate.compute":
        d = EarliestPublishDate.compute(
            [_off(c["data_end_offset"]) for c in i["charts"]], i["lag_days"]
        )
        return {"earliest_publish_offset": None if d is None else (d - TODAY).days}
    if function == "TierCascade.resolve_shot":
        return _cascade(i)
    if function == "LicenceGuard.check":
        lic = i["licence"]
        days = lic["expires_in_days"]
        g = LicenceGuard.check(
            licence=LicenceView(
                LicenceState(lic["state"]),
                None if days is None else timedelta(days=days),
                lic["platform_held"],
                ThirdPartyPermission(lic["third_party_permission"]),
                lic["covers_monetized_youtube"],
                lic["indemnification"],
                LicenceSourceType(lic["source_type"]),
            ),
            destination=LicenceDestination(i["destination"]),
            tenant_is_platform_owner=i["tenant_is_platform_owner"],
            warning_window=timedelta(days=i["warning_window_days"]),
        )
        return {
            "usable": g.usable,
            "reason": g.reason.value if g.reason else None,
            "warnings": [w.value for w in g.warnings],
        }
    if function == "ReuseEngine.lookup":
        a, rq = i["asset"], i["request"]
        d = ReuseEngine.decide(
            asset=ReuseCandidate(
                a["org"],
                a["status"],
                None if a["expires_in_days"] is None else timedelta(days=a["expires_in_days"]),
                None if a["allowed_channels"] is None else tuple(a["allowed_channels"]),
                a["uses_in_window"],
                a["sha"],
            ),
            request=ReuseRequest(rq["org"], rq["channel"], rq["sha"]),
            distance=i["hamming"],
            max_uses=i["max_uses"],
            hamming_threshold=i["hamming_threshold"],
        )
        return {"decision": d.decision.value, "reason": d.reason}
    if function == "FingerprintDHash.compute":
        try:
            return {"status": "OK", "hash_hex": FingerprintDHash.compute(i["luma_9x8"])}
        except AmwError as exc:
            return _err(exc)
    if function == "hamming":
        return {"distance": hamming(i["a"], i["b"])}
    if function == "AiBudgetGate.decide":
        d2 = AiBudgetGate.decide(
            clips_used=i["clips_used"],
            max_clips=i["max_clips"],
            shot_ms=i["shot_ms"],
            max_clip_ms=i["max_clip_ms"],
            remaining_ms=i["remaining_ms"],
            remaining_micros=i["remaining_micros"],
            est_clip_micros=i["est_clip_micros"],
            s4_reservation_ok=i["s4_reservation_ok"],
        )
        out: dict[str, Any] = {"decision": d2.action.value}
        if d2.action.value == "SUSPEND":
            out.update(
                error_code=d2.error_code,
                wait_reason=d2.wait_reason.value if d2.wait_reason else None,
            )
        else:
            out["reason"] = d2.reason
        return out
    if function == "TierShareGuard.allows":
        try:
            s = TierShareGuard.allows(
                e_ms_planned=i["e_ms_planned"],
                new_e_ms=i["new_e_ms"],
                total_visual_ms=i["total_visual_ms"],
                limit=Decimal(str(i["limit"])),
            )
        except AmwError as exc:
            return _err(exc)
        return {"status": "OK", "allowed": s.allowed, "e_share_permille": s.e_share_permille}
    if function == "CoverageVerifier.verify":
        res = CoverageVerifier.verify(
            [CoverElement(e["element"], e["asset"], e["start"], e["end"]) for e in i["elements"]],
            [
                CoverRow(r["asset"], r["from"], r["to"], r.get("job"), r.get("render"))
                for r in i["rows"]
            ],
            job_id=i.get("job_id"),
            render_id=i.get("render_id"),
        )
        return {"gaps": list(res.gaps), "pass": res.passed}
    if function == "LedgerRowBuilder.build":
        try:
            row = LedgerRowBuilder.build(
                tier=VisualSourceTier(i["tier"]) if i["tier"] else None,
                kind=AssetKind(i["kind"]) if i["kind"] != "VIDEO" or True else None,
                source_type=LicenceSourceType(i["source_type"]),
                start_ms=i["start"],
                end_ms=i["end"],
                licence_ref=i["licence"],
                element_id=i["element_id"],
                vendor_item_id=i.get("vendor_item_id"),
                source_url=i.get("source_url"),
            )
        except AmwError as exc:
            return {"error_code": type(exc).code, "row": None}
        return {
            "usage_kind": row.usage_kind.value,
            "licence_ref": row.licence_ref,
            "used_from_ms": row.used_from_ms,
            "used_to_ms": row.used_to_ms,
            "render_id": row.render_id,
            "source_url": row.source_url,
            "vendor_item_id": row.vendor_item_id,
            "shot_id": row.shot_id,
        }
    if function == "AdapterErrorMapper.map":
        m = AdapterErrorMapper.map(
            ProviderOutcome(
                i["adapter"],
                i.get("http_status"),
                i.get("retry_after_s"),
                bool(i.get("timeout")),
                i.get("network_error"),
                i.get("provider_signal"),
                i.get("phase"),
            )
        )
        if m.outcome is MapOutcome.CANDIDATE_GONE:
            return {"error_code": None, "outcome": "CANDIDATE_GONE", "retryable": False}
        return {
            "error_code": m.error_code,
            "retry_after_ms": m.retry_after_ms,
            "retryable": m.retryable,
        }
    if function == "TenantGuard.check_task":
        if i.get("entity_lookup"):
            d3 = TenantGuard.entity_decision(
                visible_to_context=i["entity_lookup"]["visible_to_context"]
            )
            return {
                "result": "ERROR",
                "error_code": d3.error_code,
                "security_event": d3.security_event,
                "message_identical_to_missing": d3.message
                == TenantGuard.entity_not_visible("asset").message,
            }
        d4 = TenantGuard.evaluate(
            context_org=i["context_org"],
            envelope_org=i["envelope_org"],
            input_org=i["input_org"],
            uris=i["uris"],
            write=i["write"],
        )
        if d4.ok:
            return {"result": "OK"}
        return {"result": "ERROR", "error_code": d4.error_code, "security_event": d4.security_event}
    if function == "AiPromptComposer.compose":
        try:
            c = AiPromptComposer.compose(
                description=i["description"],
                channel_category=i["channel_category"],
                style=i["style"],
                max_chars=i["max_chars"],
                needs_real_person=i["needs_real_person"],
                lexicon=TEST_LEXICON,
            )
        except AmwError as exc:
            return _err(exc)
        if c.rejection:
            return {"status": "REJECTED", "reason": c.rejection.value}
        return {"status": "OK", "prompt": c.prompt, "prompt_sha256": c.prompt_sha256}
    if function == "DisclosureFlags.compute":
        r2 = DisclosureFlags.compute(
            tier=VisualSourceTier(i["tier"]),
            style=i["style"],
            depicts_real_person=i["depicts_real_person"],
        )
        if r2.rejection:
            return {"status": "REJECTED", "reason": r2.rejection.value}
        f = r2.flags
        assert f is not None
        return {
            "status": "OK",
            "is_realistic_synthetic": f.is_realistic_synthetic,
            "depicts_real_person": f.depicts_real_person,
            "usage_kind": f.usage_kind.value if f.usage_kind else None,
        }
    if function == "SafetyFloor.apply":
        fr = SafetyFloor.apply(
            [
                Assessment(a["candidate_id"], Fit(a["fit"]), tuple(a["reason_codes"]))
                for a in i["assessments"]
            ],
            i["order"],
        )
        return {
            "fits": [{"candidate_id": c, "fit": f2.value} for c, f2 in fr.fits],
            "order": list(fr.order),
        }
    if function == "TieBreaker.order":
        return {
            "order": TieBreaker.order(
                [
                    RankedCandidate(
                        c["candidate_id"],
                        Fit(c["fit"]),
                        VisualSourceTier(c["tier"]),
                        c["reused_recently"],
                        c["duration_ms"],
                    )
                    for c in i["candidates"]
                ],
                i["shot_ms"],
            )
        }
    if function == "ChartSpecHasher.hash":
        a_hash, b_hash = ChartSpecHasher.hash(i["spec_a"]), ChartSpecHasher.hash(i["spec_b"])
        return {"relation": "SAME" if a_hash == b_hash else "DIFFERENT", "hash_a": a_hash}
    if function == "AnnotationValidator.validate":
        v = AnnotationValidator.validate(
            annotations=[Annotation(**a) for a in i["annotations"]],
            last_bar_index=i["last_bar_index"],
            on_screen_text_allowlist=i["on_screen_text_allowlist"],
            template_labels=i["template_labels"],
        )
        return (
            {"status": "OK"}
            if v.ok
            else {"status": "REJECTED", "reason": v.reason.value if v.reason else None}
        )
    if function == "CheckpointManager.resume":
        p = CheckpointManager.resume(i["shots"], i["checkpoint_completed"], i["completed_effects"])
        return {
            "remaining": list(p.remaining),
            "ledger_rows_to_write": list(p.ledger_rows_to_write),
            "external_effects_to_skip": list(p.external_effects_to_skip),
        }
    if function == "GateRouter.route":
        o = GateRouter.route(
            [Unresolved(u["shot_id"], ShotUnresolvedReason(u["reason"])) for u in i["unresolved"]],
            i["script_stage_id"],
        )
        g2 = o.gate_result
        return {
            "task_status": o.task_status,
            "gate_verdict": o.gate_verdict,
            "error_code": o.error_code,
            "gate_result": None
            if g2 is None
            else {
                "check_id": g2.check_id,
                "verdict": g2.verdict,
                "blocking": g2.blocking,
                "gate": g2.gate,
                "remedy_stage_id": g2.remedy_stage_id,
            },
            "next_action_type": o.next_action_type,
        }
    if function == "ChartFactsBuilder.build":
        kind = ChartDataKind(i["chart_kind"])
        facts = ChartFactsBuilder.build(
            kind,
            i["timeframe"],
            [
                FactBar(
                    _off(b["offset"]),
                    Decimal(b["o"]),
                    Decimal(b["h"]),
                    Decimal(b["l"]),
                    Decimal(b["c"]),
                )
                for b in i["bars"]
            ],
        )
        out2: list[dict[str, Any]] = []
        for f3 in facts.facts:
            d5 = dict(f3.data)
            row2: dict[str, Any] = {"fact_id": f3.fact_id, "kind": f3.kind}
            for k, v2 in d5.items():
                if isinstance(v2, date):
                    k = {
                        "first_date": "first_offset",
                        "last_date": "last_offset",
                        "date": "offset",
                    }[k]
                    v2 = (v2 - TODAY).days
                row2[k] = v2
            out2.append(row2)
        res2: dict[str, Any] = {"facts": out2}
        if not facts.emit_document or i["chart_kind"] == "SCHEMATIC":
            res2["emit_document"] = facts.emit_document
        elif "emit_document" in _expected_hint:
            res2["emit_document"] = True
        return res2
    if function == "SourceIntakeGuard.check":
        r3 = SourceIntakeGuard.check(
            actor_kind=ActorKind(i["actor_kind"]),
            via_operator_tool=i["via_operator_tool"],
            source_class=i["source_class"],
            access=i["access"],
        )
        return {
            "result": r3.result.value,
            "attributes": r3.attributes,
            "error_code": r3.error_code,
            "audit_event": r3.audit_event,
        }
    if function == "TimelineLedgerPlanner.plan":
        try:
            rows = TimelineLedgerPlanner.plan(
                [
                    OverlayInput(
                        o["overlay_id"], o["kind"], o["start_ms"], o["end_ms"], o["template_asset"]
                    )
                    for o in i["overlays"]
                ],
                i["brand_fonts"],
                i["timeline_end_ms"],
            )
        except AmwError as exc:
            return {"error_code": type(exc).code, "rows": None}
        return {
            "rows": [
                {
                    "element_id": r.element_id,
                    "asset": r.asset,
                    "usage_kind": r.usage_kind.value,
                    "used_from_ms": r.used_from_ms,
                    "used_to_ms": r.used_to_ms,
                    "shot_id": r.shot_id,
                }
                for r in rows
            ]
        }
    if function == "ChangedShotSelector.select":

        def key(k: dict[str, Any]) -> ShotKey:
            return ShotKey(
                k["shot_id"], k["content_key"], k["start_ms"], k["end_ms"], k["aspect_ratio"]
            )

        sel = ChangedShotSelector.select(
            [key(k) for k in i["previous"]],
            [key(k) for k in i["current"]],
            i["hint_changed_shot_ids"],
        )
        return {"resource": list(sel.resource), "carry_over": list(sel.carry_over)}
    raise KeyError(function)


_expected_hint: set[str] = set()


def _cascade(i: dict[str, Any]) -> dict[str, Any]:
    kind = i["intent_kind"]
    refusal = i.get("step_refusal")
    unsafe = bool(refusal and refusal["reason"] == StepRefusalReason.UNSAFE_CONTENT)
    rsn = refusal["reason"] if refusal else None
    step = refusal["step"] if refusal else None
    probes: Probes[str] = Probes()
    if kind == "CHART":
        c = i["chart"]
        age = DataAgeVsLag(c["data_age_vs_lag"]) if c["data_age_vs_lag"] else None

        def chart() -> ChartAttempt[str]:
            why = chart_preconditions(
                kind=ChartDataKind(c["kind"]),
                case_found=c["case_found"],
                dataset_found=c["dataset_found"],
                method_content=c["method_content"],
                release_approved=c["release_approved"],
                data_age=age,
            )
            return ChartAttempt(accepted=None if why else "chart", unresolved=why)

        probes.chart = chart
        res = TierCascade.resolve_shot(intent=IntentKind.CHART, probes=probes)
    elif kind == "GRAPHIC":
        probes.graphic = lambda: (
            accept("g") if i["graphic_content"] else skip_with(VisualSkipReason.NO_TEMPLATE_CONTENT)
        )
        res = TierCascade.resolve_shot(intent=IntentKind.GRAPHIC, probes=probes)
    else:
        refused_none = rsn in ("INSUFFICIENT_INPUT", "OUT_OF_SCOPE", "CONFLICTING_INSTRUCTIONS")

        def owner() -> Attempt[str]:
            if refused_none:
                return skip_with(
                    VisualSkipReason.NO_CANDIDATE
                    if step == "query_plan"
                    else VisualSkipReason.NO_ACCEPTABLE_FIT
                )
            if i["owner_candidates"] == 0:
                return skip_with(VisualSkipReason.NO_CANDIDATE)
            return (
                accept("owner")
                if i["owner_accepted"]
                else skip_with(VisualSkipReason.NO_ACCEPTABLE_FIT)
            )

        def stock() -> Attempt[str]:
            if not i["stock_enabled"]:
                return skip_with(VisualSkipReason.TIER_DISABLED)
            lic = i["stock_licence"]
            if lic == "ABSENT":
                return skip_with(VisualSkipReason.LICENCE_ABSENT)
            if lic == "NOT_USABLE":
                return skip_with(VisualSkipReason.LICENCE_NOT_USABLE)
            if refused_none:
                return skip_with(
                    VisualSkipReason.NO_CANDIDATE
                    if step == "query_plan"
                    else VisualSkipReason.NO_ACCEPTABLE_FIT
                )
            if i["stock_candidates"] == 0:
                return skip_with(VisualSkipReason.NO_CANDIDATE)
            return (
                accept("stock")
                if i["stock_accepted"]
                else skip_with(VisualSkipReason.NO_ACCEPTABLE_FIT)
            )

        probes.owner, probes.stock = owner, stock
        probes.graphic = lambda: (
            accept("g") if i["graphic_content"] else skip_with(VisualSkipReason.NO_TEMPLATE_CONTENT)
        )

        def video() -> Attempt[str]:
            if not i["ai_video_enabled"]:
                return skip_with(VisualSkipReason.TIER_DISABLED)
            return accept("d") if i["ai_budget_ok"] else skip_with(VisualSkipReason.BUDGET)

        def still() -> Attempt[str]:
            if not i["image_enabled"]:
                return skip_with(VisualSkipReason.TIER_DISABLED)
            return accept("e") if i["e_share_ok"] else skip_with(VisualSkipReason.TIER_SHARE_LIMIT)

        probes.ai_video, probes.ai_still = video, still
        res = TierCascade.resolve_shot(
            intent=IntentKind.FOOTAGE,
            probes=probes,
            prohibited_depiction=i["prohibited_depiction"],
            unsafe_refusal=unsafe,
        )
    out: dict[str, Any] = {
        "status": "SOURCED" if res.sourced else "UNRESOLVED",
        "tier": res.tier.value if res.tier else None,
        "skips": [{"tier": s.tier.value, "reason": s.reason.value} for s in res.skips],
    }
    if res.sourced:
        out["warnings"] = [w.value for w in res.warnings]
    else:
        out["unresolved_reason"] = res.unresolved_reason.value if res.unresolved_reason else None
    return out
