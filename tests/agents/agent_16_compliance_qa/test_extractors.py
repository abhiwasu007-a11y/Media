# ruff: noqa: PT018
"""``DocumentGateFactExtractor`` / ``DocumentUniquenessExtractor`` / ``DocumentScoreFactExtractor``
(PASS6-K item 2; blueprint 15.1a and 15.1b): every field equals its source, and every absent or
contradicting source gives the stated, stricter result (compliance fails closed)."""

import copy
import hashlib
from typing import Any

import pytest

from agent_16_compliance_qa.checks import rules as R  # noqa: N812
from agent_16_compliance_qa.inputs.extractors import (
    ChannelRow,
    DocumentGateFactExtractor,
    DocumentScoreFactExtractor,
    DocumentUniquenessExtractor,
    is_sensitive,
)
from agent_16_compliance_qa.scoring.aggregate import QcRow
from amw_core import ids
from amw_core.enums import (
    AudienceKind,
    CheckVerdict,
    ComplianceVerdict,
    DisclosureDecision,
    PresenterKind,
    VisualSourceTier,
)
from amw_core.errors import (
    InputInvalidError,
    MissingDependencyError,
    SchemaInvalidError,
)
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.testing.memory import MemoryTransaction
from tests.agents.agent_16_compliance_qa.extractor_support import (
    CLAIM_ROWS,
    EVAL_DATE,
    PASS_QC,
    QUOTE_APPROVAL,
    RELEASE,
    RELEASE_SHA,
    Rows,
    blobs_of,
    docs,
    full_rows,
    request,
    scope,
    with_asset,
)
from tests.agents.agent_16_compliance_qa.support import config


def tx() -> MemoryTransaction:
    return MemoryTransaction(
        TenantContext(ids.ORG.new(), ids.actor_ref("agent_16"), ids.CORRELATION.new())
    )


def gate(rows: Rows | None = None, d: dict[str, Any] | None = None, **req: Any) -> Any:
    r = request(**req)
    ex = DocumentGateFactExtractor(rows or full_rows(), config(), scope(r))
    return ex.extract(r, blobs_of(d or docs()), EVAL_DATE, tx())


def test_every_gate_fact_equals_its_source() -> None:
    out = gate()
    i = out.inputs
    assert i.channel_category == "finance" and i.sensitive_channel is True
    assert i.audience_kind is AudienceKind.GENERAL and i.language == "mr-IN"
    assert i.production_type_key == "CHANNEL_LONG_FORM" and i.live_format == "STANDARD"
    refs = {x.ref: x for x in i.items}
    assert refs["seg.s2"].text == "A candle shows price movement"
    assert refs["seg.s2"].context_before == "Intro line" and refs["seg.s2"].context_after
    assert refs["seg.s2"].named_instruments == ("NIFTY",) and refs["seg.s2"].claim_ids == ("clm_1",)
    assert refs["seg.s2"].claims[0].rule_flags == ("FIN-R9",)
    assert refs["seg.s2"].chart is not None and refs["seg.s2"].chart.chart_kind == "CANDLESTICK"
    assert refs["scene.hook.sc1.t0"].surface == "ON_SCREEN_TEXT"
    assert refs["title"].text == "Title" and refs["description"].text == "A description"
    assert refs["thumb.v2"].surface == "THUMBNAIL_TEXT"
    # FIN-R10: spoken from the DISCLAIMER segment + slot, on-screen from the plan overlay
    assert i.disclaimer_spoken and i.disclaimer_onscreen and i.disclaimer_template_version == "v1"
    assert i.method_label_overlay is False  # no Agent 09 overlay kind marks the label (CCR-272)
    assert [(c.chart_id, c.age_days) for c in i.charts] == [("chart_a", 61)]
    assert [m.segment_ref for m in i.method_segments] == ["seg.s3"]
    assert i.method_segments[0].labelled and i.method_segments[0].release_state == "NONE"
    assert out.method_release_approvals["seg.s3"].approval_id == RELEASE
    assert out.method_release_approvals["seg.s3"].released_sha256 == RELEASE_SHA
    assert i.presenter_kind is PresenterKind.NEUTRAL_NARRATION and i.voice_known
    assert i.voice_kind == "NEUTRAL_TTS"
    assert {a.asset_ref for a in i.licensed_assets} == {"ast_1", "ast_2", "ast_3", "ast_4"}
    assert [t.shows_person for t in i.thumbnail_person_assets] == [True]
    assert i.thumbnail_person_assets[0].is_realistic_synthetic is False
    assert {a.asset_ref for a in i.disclosure_assets} == {"sh01", "sh02", "ast_5"}
    assert [(s.shot_ref, s.tier, s.has_origin) for s in i.realism_shots] == [
        ("sh01", VisualSourceTier.C_CODE_MOTION, True)
    ]
    assert (
        i.frame_ids == ("f01", "f02", "f03") and i.uniqueness_verdict is ComplianceVerdict.ALLOWED
    )
    assert (i.metadata_present, i.description_hash_matches, i.metadata_terms) == (False, None, None)
    assert i.evaluation_date == EVAL_DATE and i.routing.thumbnails_stage_id == "s11_thumbs"
    fp = i.frames_payload
    assert fp is not None and fp["checks_requested"] == [
        "qc.watermark.visual",
        "qc.visual.no_synthetic_presenter",
    ]
    assert [f["frame_id"] for f in fp["frames"]] == ["f01", "f02", "f03"]
    assert fp["overlay_list"] == [] and fp["sensitive_channel"] is True
    assert i.near_copy == () and i.paraphrase_pairs == () and out.quotation_approvals == {}


def test_a_price_claim_without_a_chart_is_an_undated_price_that_needs_a_human() -> None:
    d = docs()
    d["claims_ref"]["claims"].append(
        {"local_id": "c3", "segment_id": "s3", "claim_type": "PRICE_LEVEL"}
    )
    d["verification_ref"]["claims"].append({"claim_id": "clm_3", "local_id": "c3"})
    i = gate(d=d).inputs
    assert [p.has_date for p in i.text_prices] == [False]
    res = R.price_lag(list(i.charts), list(i.text_prices), 30)
    assert res.compliance_verdict is ComplianceVerdict.NEEDS_HUMAN_REVIEW


@pytest.mark.parametrize(
    ("channel", "packs", "expected"),
    [
        (None, (), True),  # no channel row: treated as finance
        (ChannelRow(None, AudienceKind.GENERAL), (), True),  # unknown category
        (ChannelRow("", AudienceKind.GENERAL), (), True),
        (ChannelRow("cooking", AudienceKind.GENERAL), ("rp.finance_sebi_in",), True),
        (ChannelRow("Health", AudienceKind.GENERAL), (), True),
        (ChannelRow("cooking", AudienceKind.GENERAL), ("rp.youtube_general",), False),
    ],
)
def test_sensitive_channel_rule(
    channel: ChannelRow | None, packs: tuple[str, ...], expected: bool
) -> None:
    assert is_sensitive(channel, packs) is expected


def test_audience_kind_null_is_needs_human_review() -> None:
    rows = full_rows(channel_row=ChannelRow("finance", None, "kcl_1"))
    i = gate(rows).inputs
    assert i.audience_kind is None
    assert (
        R.audience(i.audience_kind, False).compliance_verdict
        is ComplianceVerdict.NEEDS_HUMAN_REVIEW
    )


@pytest.mark.parametrize(
    "missing",
    [
        "script_ref",
        "claims_ref",
        "verification_ref",
        "asset_manifest_ref",
        "shot_plan_ref",
        "voice_ref",
        "thumbnails_ref",
        "uniqueness_ref",
        "research_pack_ref",
        "frames_ref",
        "render_qc_ref",
    ],
)
def test_a_missing_document_is_missing_dependency(missing: str) -> None:
    b = blobs_of(docs())
    del b[missing]
    r = request()
    with pytest.raises(MissingDependencyError):
        DocumentGateFactExtractor(full_rows(), config(), scope(r)).extract(r, b, EVAL_DATE, tx())


def test_an_unparsable_document_is_schema_invalid() -> None:
    d = docs()
    d["script_ref"] = {"segments": "not a list"}
    with pytest.raises(SchemaInvalidError) as exc:
        gate(d=d)
    assert exc.value.details["violations"][0].keyword == "DOCUMENT_INVALID"


def test_no_database_row_is_missing_dependency() -> None:
    with pytest.raises(MissingDependencyError):
        gate(full_rows(channel_row=None))
    rows = full_rows()
    rows.job_row = None
    with pytest.raises(MissingDependencyError):
        gate(rows)


@pytest.mark.parametrize(
    "over",
    [
        {"channel_category": "education"},
        {"language": "en-IN"},
        {"production_type_key": "SHORTS"},
        {
            "routing": {
                "script_stage_id": "s05_script",
                "assets_stage_id": "x",
                "thumbnails_stage_id": None,
            }
        },
    ],
)
def test_a_request_that_contradicts_the_rows_is_refused(over: dict[str, Any]) -> None:
    with pytest.raises(InputInvalidError):
        gate(**over)


def test_thumbnails_disabled_in_the_production_type_record() -> None:
    rows = full_rows()
    assert rows.job_row is not None
    object.__setattr__(rows.job_row, "routing_thumbnails_stage_id", None)
    d = docs()
    d["thumbnails_ref"]["variants"] = [
        {
            "variant_id": "v1",
            "text_local": "T1",
            "picture": {"kind": "CODE_GLYPH", "asset_id": None},
        }
    ]
    i = gate(
        rows,
        d,
        routing={
            "script_stage_id": "s05_script",
            "assets_stage_id": "s08_assets",
            "thumbnails_stage_id": None,
        },
    ).inputs
    assert i.thumbnail_person_assets == () and i.routing.thumbnails_stage_id is None


def test_a_missing_licence_row_or_ledger_row_fails_the_licence_rules() -> None:
    rows = full_rows()
    del rows.asset_rows["ast_2"]
    i = gate(rows).inputs
    _, r6, _ = R.licence(list(i.licensed_assets))
    assert r6.compliance_verdict is ComplianceVerdict.BLOCKED  # YTG-R6 FAIL, never a pass
    rows = full_rows()
    with_asset(rows, "ast_2", has_ledger_row=False)
    _, r6b, _ = R.licence(list(gate(rows).inputs.licensed_assets))
    assert r6b.compliance_verdict is ComplianceVerdict.BLOCKED


def test_unknown_licence_state_or_coverage_needs_a_human() -> None:
    rows = full_rows()
    with_asset(rows, "ast_2", licence_state=None, covers_monetized_youtube=None)
    _, r6, _ = R.licence(list(gate(rows).inputs.licensed_assets))
    assert r6.compliance_verdict is ComplianceVerdict.NEEDS_HUMAN_REVIEW


def test_an_unresolved_shot_or_unknown_tier_is_refused() -> None:
    d = docs()
    d["asset_manifest_ref"]["shots"][0]["status"] = "UNRESOLVED"
    with pytest.raises(InputInvalidError):
        gate(d=d)
    d = docs()
    del d["asset_manifest_ref"]["shots"][0]["tier"]
    with pytest.raises(InputInvalidError):
        gate(d=d)


def test_realism_view_naming_an_unknown_shot_is_refused() -> None:
    d = docs()
    d["shot_plan_ref"]["views"]["agent_16_realism"][0]["shot_id"] = "sh99"
    with pytest.raises(InputInvalidError):
        gate(d=d)


def test_voice_without_a_voices_row_is_unknown_and_a_mismatch_is_refused() -> None:
    i = gate(full_rows(presenter=None)).inputs
    assert i.voice_known is False and i.presenter_kind is None and i.voice_kind is None
    assert (
        R.persona(True, None, False, [], []).compliance_verdict
        is ComplianceVerdict.NEEDS_HUMAN_REVIEW
    )
    with pytest.raises(InputInvalidError):
        gate(full_rows(presenter=PresenterKind.OWNER_VOICE))


@pytest.mark.parametrize(
    ("kind", "presenter", "expected"),
    [
        ("HUMAN_RECORDED", "OWNER_VOICE", "OWNER_VOICE"),
        ("CONSENTED_CLONE", "OWNER_VOICE", "OWNER_CLONE"),
        ("PROVIDER_STOCK", "NEUTRAL_NARRATION", "NEUTRAL_TTS"),
        ("CONSENTED_CLONE", "SYNTHETIC_PERSONA", "OTHER_REAL_PERSON"),
        ("PROVIDER_STOCK", "OWNER_VOICE", None),  # no row of the mapping: needs a human
    ],
)
def test_voice_kind_mapping(kind: str, presenter: str, expected: str | None) -> None:
    d = docs()
    d["voice_ref"] = {"voice": {"voice_kind": kind, "presenter_kind": presenter}}
    i = gate(full_rows(presenter=PresenterKind(presenter)), d).inputs
    assert i.voice_kind == expected
    if expected is None:
        assert (
            R.disclosure([], [], i.voice_kind).compliance_verdict
            is ComplianceVerdict.NEEDS_HUMAN_REVIEW
        )


def test_disclaimer_missing_pieces_fail_fin_r10() -> None:
    d = docs()
    d["script_ref"]["disclaimer_slots"] = []
    i = gate(d=d).inputs
    assert not i.disclaimer_spoken and i.disclaimer_template_version is None
    d = docs()
    d["shot_plan_ref"]["overlays"] = []
    i = gate(d=d).inputs
    res = R.disclaimer(
        i.disclaimer_spoken, i.disclaimer_onscreen, i.disclaimer_template_version, False, None
    )
    assert res.compliance_verdict is ComplianceVerdict.BLOCKED
    d = docs()
    d["script_ref"]["disclaimer_slots"].append(
        {"slot_id": "d2", "segment_id": "s4", "template_version": "v2"}
    )
    assert gate(d=d).inputs.disclaimer_template_version is None  # two versions: no version


def test_method_release_is_none_when_the_pack_names_none_or_several() -> None:
    d = docs()
    d["research_pack_ref"]["method"]["release_approval_ids"] = []
    out = gate(d=d)
    assert out.method_release_approvals == {"seg.s3": None}
    d = docs()
    d["research_pack_ref"]["method"]["release_approval_ids"] = [RELEASE, "apr_other"]
    assert gate(d=d).method_release_approvals == {"seg.s3": None}
    out = gate(full_rows(release={}))
    assert out.method_release_approvals == {"seg.s3": None}  # approval row unknown: no binding
    res = R.method_release(list(out.inputs.method_segments), False)
    assert res.compliance_verdict is ComplianceVerdict.BLOCKED


def test_frames_payload_is_null_without_a_judged_row_and_presenter_only_if_sensitive() -> None:
    assert gate(full_rows(judged=())).inputs.frames_payload is None
    rows = full_rows(judged=("qc.visual.no_synthetic_presenter",))
    rows.channel_row = ChannelRow("cooking", AudienceKind.GENERAL)
    assert rows.job_row is not None
    object.__setattr__(rows.job_row, "active_pack_keys", ("rp.youtube_general",))
    assert gate(rows, channel_category="cooking").inputs.frames_payload is None


def test_frames_are_capped_by_config_and_the_schema() -> None:
    d = docs()
    d["frames_ref"]["frames"] = [
        {"frame_id": f"f{i:02d}", "frame_index": i, "t_ms": i, "uri": f"u{i}", "sha256": "d" * 64}
        for i in range(1, 100)
    ]
    r = request()
    cfg = config(**{"compliance.frames.max_frames": 5})
    fp = (
        DocumentGateFactExtractor(full_rows(), cfg, scope(r))
        .extract(r, blobs_of(d), EVAL_DATE, tx())
        .inputs.frames_payload
    )
    assert fp is not None and len(fp["frames"]) == 5
    assert len(gate(d=d).inputs.frames_payload["frames"]) == 60


def test_evidence_manifest_for_another_render_is_refused() -> None:
    d = docs()
    d["frames_ref"]["render_sha256"] = "9" * 64
    with pytest.raises(InputInvalidError):
        gate(d=d)


def test_a_metadata_bundle_is_not_read_before_3c() -> None:
    r = request()
    b = blobs_of(docs()) | {"metadata_ref": b"{}"}
    with pytest.raises(InputInvalidError):
        DocumentGateFactExtractor(full_rows(), config(), scope(r)).extract(r, b, EVAL_DATE, tx())


def test_chart_dated_in_the_future_or_undated() -> None:
    d = docs()
    d["asset_manifest_ref"]["shots"][0]["chart"]["data_end_date"] = "2026-03-01"
    with pytest.raises(InputInvalidError):
        gate(d=d)
    d["asset_manifest_ref"]["shots"][0]["chart"]["data_end_date"] = None
    i = gate(d=d).inputs
    assert i.charts[0].age_days is None
    assert (
        R.price_lag(list(i.charts), [], 30).compliance_verdict
        is ComplianceVerdict.NEEDS_HUMAN_REVIEW
    )


def test_an_extractor_without_scope_or_transaction_refuses() -> None:
    r = request()
    with pytest.raises(MissingDependencyError):
        DocumentGateFactExtractor(full_rows(), config()).extract(
            r, blobs_of(docs()), EVAL_DATE, tx()
        )
    bound = DocumentGateFactExtractor(full_rows(), config()).bind(scope(r))
    assert bound.extract(r, blobs_of(docs()), EVAL_DATE, tx()).inputs.language == "mr-IN"


# --- YTG-R9: cited knowledge chunks ---------------------------------------------------------
class Chunks:
    def __init__(
        self, org: str, collection: str = "kcl_1", text: str = "A candle shows price movement"
    ) -> None:
        self.org, self.collection, self.text = org, collection, text

    def read(self, tx: Any, chunk_id: str) -> Any:
        from agent_16_compliance_qa.nearcopy import ChunkText

        return ChunkText(
            chunk_id=chunk_id, org_id=self.org, collection_id=self.collection, text=self.text
        )


def cited_docs() -> dict[str, Any]:
    d = docs()
    d["research_pack_ref"]["citations_available"][0]["kind"] = "KNOWLEDGE_CHUNK"
    return d


def test_cited_chunks_without_a_private_reader_fail_closed() -> None:
    with pytest.raises(MissingDependencyError):
        gate(d=cited_docs())


def test_cited_chunks_build_pairs_hashes_and_near_copy() -> None:
    r = request()
    t = tx()
    quote_hash = hashlib.sha256(b"A candle shows price movement").hexdigest()
    rows = full_rows(quotes={quote_hash: QUOTE_APPROVAL})
    d = cited_docs()
    d["claims_ref"]["claims"][0]["claim_type"] = "QUOTED_THIRD_PARTY"
    d["claims_ref"]["claims"][0]["citation_refs"] = ["ref_a"]
    out = DocumentGateFactExtractor(
        rows, config(), scope(r), Chunks(str(t.context.org_id))
    ).extract(r, blobs_of(d), EVAL_DATE, t)
    i = out.inputs
    assert len(i.paraphrase_pairs) == 1 and i.paraphrase_pairs[0].pair_id == "p01"
    assert i.paraphrase_pairs[0].attribution_present is True
    assert i.span_hashes == {"p01": quote_hash}
    assert i.near_copy[0].sentence_ref == "seg.s2" and i.near_copy[0].lcs_chars > 0
    assert out.quotation_approvals == {quote_hash: QUOTE_APPROVAL}


def test_cited_chunk_of_another_collection_is_refused() -> None:
    from amw_core.errors import CrossTenantRefError

    r = request()
    t = tx()
    with pytest.raises(CrossTenantRefError):
        DocumentGateFactExtractor(
            full_rows(), config(), scope(r), Chunks(str(t.context.org_id), collection="other")
        ).extract(r, blobs_of(cited_docs()), EVAL_DATE, t)


def test_cited_chunks_without_a_channel_collection_fail_closed() -> None:
    r = request()
    t = tx()
    rows = full_rows(channel_row=ChannelRow("finance", AudienceKind.GENERAL, None))
    with pytest.raises(MissingDependencyError):
        DocumentGateFactExtractor(rows, config(), scope(r), Chunks(str(t.context.org_id))).extract(
            r, blobs_of(cited_docs()), EVAL_DATE, t
        )


# --- uniqueness (S2) ------------------------------------------------------------------------
def uniq_blobs() -> dict[str, bytes]:
    d = docs()
    d["template_ref"] = {
        "segments": [
            {"section_role": "HOOK", "text": "Intro line"},
            {"section_role": "CONCEPT", "text": "x"},
            {"section_role": "CONCEPT", "text": "y"},
            {"section_role": "DISCLAIMER", "text": "z"},
        ],
        "shot_types": ["CHART", "FOOTAGE"],
    }
    return blobs_of(d)


def test_uniqueness_facts_equal_their_sources() -> None:
    f = DocumentUniquenessExtractor().extract(uniq_blobs())
    assert [s.section_role for s in f.script] == ["HOOK", "CONCEPT", "CONCEPT", "DISCLAIMER"]
    assert f.shots == ("CHART", "FOOTAGE") and f.template_shots == ("CHART", "FOOTAGE")
    assert f.complete is True and f.template[0].text == "Intro line"


def test_uniqueness_with_an_empty_template_is_incomplete_and_a_missing_one_is_refused() -> None:
    b = uniq_blobs()
    d: dict[str, Any] = {"segments": [], "shot_types": []}
    b["template_ref"] = blobs_of({"t": d})["t"]
    assert DocumentUniquenessExtractor().extract(b).complete is False
    del b["template_ref"]
    with pytest.raises(MissingDependencyError):
        DocumentUniquenessExtractor().extract(b)
    with pytest.raises(SchemaInvalidError):
        DocumentUniquenessExtractor().extract(uniq_blobs() | {"shot_plan_ref": b"{}"})


# --- quality-score facts (15.1b) ------------------------------------------------------------
class Verifier:
    def __init__(self, state: str) -> None:
        self.state = state
        self.seen: list[tuple[str, str]] = []

    def derive(self, tx: Any, approval_id: str, kind: Any, subject: str) -> str:
        self.seen.append((approval_id, subject))
        return self.state


def score(rows: Rows, d: dict[str, Any] | None = None, state: str = "APPROVED") -> Any:
    ex = DocumentScoreFactExtractor(rows, Verifier(state))  # type: ignore[arg-type]
    r = request()
    return ex.extract(r.subject.render_id, blobs_of(d or docs()), tx(), scope(r), True)


def test_every_score_fact_equals_its_source() -> None:
    rows = full_rows(qc=(PASS_QC,), claim_rows=CLAIM_ROWS)
    rows.thumb_qc = (
        QcRow(check_id="a11.q.legibility", verdict=CheckVerdict.PASS),
        QcRow(check_id="a11.q.text_fit", verdict=CheckVerdict.PASS),
        QcRow(check_id="a11.q.canvas", verdict=CheckVerdict.PASS),
    )
    f = score(rows)
    assert f.qc == (PASS_QC,)
    assert [
        (c.claim_id, c.has_citation_or_chart, c.sensitive_claim_approved) for c in f.claims
    ] == [
        ("clm_1", True, False),
        ("clm_2", False, True),
    ]
    s = f.script
    assert (s.hook_options, s.promise_fields_present, s.section_count) == (2, True, 1)
    assert (s.sections_with_takeaway, s.sections_with_example, s.viewer_problem_addressed) == (
        None,
        None,
        None,
    )
    t = f.thumbnails
    assert (t.variants, t.required_variants, t.spec_ok, t.legible, t.title_length_ok) == (
        3,
        3,
        True,
        True,
        None,
    )
    g = f.gate
    assert (
        g.overall is ComplianceVerdict.ALLOWED
        and g.licence_pass is True
        and g.disclaimer_pass is True
    )
    assert g.disclosure_decision is DisclosureDecision.NOT_REQUIRED and g.finance is True


def test_absent_score_sources_give_the_stated_result() -> None:
    f = score(full_rows(qc=(), claim_rows=(), thumb_qc=()))
    assert f.qc == () and f.claims == ()
    assert f.thumbnails.spec_ok is None and f.thumbnails.legible is None
    d = docs()
    d["gate_output_ref"]["rules"] = []
    d["script_ref"]["promise"] = {"working_title_local": "T"}
    del d["script_ref"]["hook_options"]
    f = score(full_rows(qc=()), d)
    assert f.gate.licence_pass is None and f.gate.disclaimer_pass is None
    assert f.script.promise_fields_present is False and f.script.hook_options is None


def test_no_render_is_missing_dependency_and_an_unapproved_claim_is_not_approved() -> None:
    with pytest.raises(MissingDependencyError):
        score(full_rows(qc=None))
    f = score(full_rows(qc=(), claim_rows=CLAIM_ROWS), state="PENDING")
    assert [c.sensitive_claim_approved for c in f.claims] == [False, False]


def test_a_failing_thumbnail_check_is_reported() -> None:
    rows = full_rows(qc=())
    rows.thumb_qc = (
        QcRow(check_id="a11.q.legibility", verdict=CheckVerdict.FAIL),
        QcRow(check_id="a11.q.text_fit", verdict=CheckVerdict.PASS),
        QcRow(check_id="a11.q.canvas", verdict=CheckVerdict.FAIL),
    )
    f = score(rows)
    assert f.thumbnails.legible is False and f.thumbnails.spec_ok is False


def test_the_copied_documents_are_not_mutated() -> None:
    d = docs()
    before = copy.deepcopy(d)
    gate(d=d)
    assert d == before


def test_stock_assets_do_not_need_a_third_party_permission_but_unknown_origin_does() -> None:
    i = gate().inputs
    r5, r6, _ = R.licence(list(i.licensed_assets))
    assert r5.compliance_verdict is ComplianceVerdict.ALLOWED
    assert r6.compliance_verdict is ComplianceVerdict.ALLOWED
    d = docs()
    d["asset_manifest_ref"]["shots"][1]["source_type"] = None  # origin unknown: third party
    r5b, _, _ = R.licence(list(gate(d=d).inputs.licensed_assets))
    assert r5b.compliance_verdict is ComplianceVerdict.NEEDS_HUMAN_REVIEW


def test_inconsistent_script_documents_are_refused() -> None:
    d = docs()
    d["script_ref"]["segments"][1]["chart_ref"] = "chart_unknown"
    with pytest.raises(InputInvalidError):
        gate(d=d)
    d = docs()
    d["claims_ref"]["claims"][0]["segment_id"] = "s99"
    with pytest.raises(InputInvalidError):
        gate(d=d)
    d = docs()
    del d["verification_ref"]["claims"][0]
    with pytest.raises(InputInvalidError):
        gate(d=d)


def test_a_shot_that_may_show_a_synthetic_person_fails_persona_on_a_sensitive_channel() -> None:
    d = docs()
    d["asset_manifest_ref"]["shots"][1]["disclosure"] = {
        "is_realistic_synthetic": True,
        "depicts_real_person": False,
    }
    rows = full_rows()
    with_asset(rows, "ast_2", shows_person=None)  # the asset row does not know: strict
    i = gate(rows, d).inputs
    assert R.persona(
        True, i.presenter_kind, True, list(i.render_person_assets), []
    ).compliance_verdict is (ComplianceVerdict.BLOCKED)
