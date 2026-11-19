"""Fixture world of the Agent 16 fact extractors (PASS6-K): the upstream documents of 15.1, the
database rows of 15.1a/15.1b as an in-memory ``FactRowReader`` and the gate request."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from agent_16_compliance_qa.assembler import ComplianceGateInput
from agent_16_compliance_qa.inputs.extractors import (
    AssetFactRow,
    ChannelRow,
    ClaimRow,
    JobRow,
    ReadScope,
)
from agent_16_compliance_qa.scoring.aggregate import QcRow
from amw_core import ids
from amw_core.enums import (
    AudienceKind,
    CheckVerdict,
    ClaimStatus,
    LicenceState,
    PresenterKind,
    VisualSourceTier,
)
from amw_core.interfaces.tenancy_context import TenantTransaction

R_SHA = "a" * 64
RENDER_ID = ids.new_id(ids.Prefix.RENDER)
SCRIPT_ID = ids.new_id(ids.Prefix.SCRIPT)
EVAL_DATE = date(2026, 1, 31)
RELEASE = "apr_release_1"
RELEASE_SHA = "c" * 64
QUOTE_APPROVAL = "apr_quote_1"


def j(doc: Any) -> bytes:
    return json.dumps(doc, ensure_ascii=False).encode("utf-8")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def seg(sid: str, kind: str, section: str | None, text: str, **extra: Any) -> dict[str, Any]:
    return {
        "segment_id": sid,
        "kind": kind,
        "section_id": section,
        "scene_id": f"{section or 'disc'}.sc1",
        "text": text,
        **extra,
    }


def docs() -> dict[str, Any]:
    """Every upstream document as a plain dict (tests change one and re-serialise)."""
    return {
        "script_ref": {
            "segments": [
                seg("s1", "HOOK_PROOF", "hook", "Intro line"),
                seg(
                    "s2",
                    "BODY",
                    "sec1",
                    "A candle shows price movement",
                    chart_ref="chart_a",
                    concept_refs=[{"concept_id": "k1", "citation_refs": ["ref_a"]}],
                ),
                seg(
                    "s3",
                    "BODY",
                    "sec1",
                    "Our method marks a level",
                    method_label=True,
                    concept_refs=[{"concept_id": "k2", "citation_refs": ["ref_m"]}],
                ),
                seg("s4", "DISCLAIMER", None, "Not advice"),
            ],
            "scenes": [{"scene_id": "hook.sc1", "on_screen_text": ["Hook text"]}],
            "sections": [{"section_id": "sec1", "section_kind": "CONCEPT"}],
            "promise": {
                "working_title_local": "Title",
                "promise_statement": "You will learn",
                "promise_key_terms": ["candle"],
            },
            "disclaimer_slots": [{"slot_id": "d1", "segment_id": "s4", "template_version": "v1"}],
            "chart_requests": [{"chart_id": "chart_a", "chart_kind": "CANDLESTICK"}],
            "hook_options": [{"hook_id": "h1"}, {"hook_id": "h2"}],
            "description_draft": "A description",
            "unread_field": {"anything": 1},
        },
        "claims_ref": {
            "claims": [
                {
                    "local_id": "c1",
                    "segment_id": "s2",
                    "claim_type": "HISTORICAL_MARKET",
                    "time_reference_kind": "HISTORICAL",
                    "instrument": "NIFTY",
                    "chart_data_ref": "chart_a",
                    "citation_refs": ["ref_a"],
                    "rule_flags": [{"rule_id": "FIN-R9"}],
                },
                {
                    "local_id": "c2",
                    "segment_id": "s3",
                    "claim_type": "FACTUAL",
                    "citation_refs": [],
                },
            ]
        },
        "verification_ref": {
            "script_id": SCRIPT_ID,
            "script_sha256": "",  # stamped by ``blobs_of`` from the script blob
            "claims": [
                {"claim_id": "clm_1", "local_id": "c1"},
                {"claim_id": "clm_2", "local_id": "c2"},
            ],
        },
        "asset_manifest_ref": {
            "shots": [
                {
                    "shot_id": "sh01",
                    "status": "SOURCED",
                    "tier": "C_CODE_MOTION",
                    "asset_id": "ast_1",
                    "source_type": "CODE_GENERATED",
                    "disclosure": {"is_realistic_synthetic": False, "depicts_real_person": False},
                    "chart": {"chart_id": "chart_a", "data_end_date": "2025-12-01"},
                },
                {
                    "shot_id": "sh02",
                    "status": "SOURCED",
                    "tier": "B_LICENSED_STOCK",
                    "asset_id": "ast_2",
                    "source_type": "PAID_STOCK",
                    "disclosure": {"is_realistic_synthetic": False, "depicts_real_person": False},
                },
            ],
            "overlays": [
                {
                    "overlay_id": "ov01",
                    "template_asset_id": "ast_3",
                    "source_type": "CODE_GENERATED",
                }
            ],
            "fonts": [{"asset_id": "ast_4", "source_type": "FONT"}],
            "music_beds": [],
        },
        "shot_plan_ref": {
            "overlays": [{"overlay_id": "ov01", "kind": "DISCLAIMER_CARD"}],
            "views": {
                "agent_16_realism": [
                    {
                        "shot_id": "sh01",
                        "realistic_event_depiction": False,
                        "schematic": True,
                        "origin": "MODEL",
                    }
                ]
            },
            "shots": [{"intent_kind": "CHART"}, {"intent_kind": "FOOTAGE"}],
        },
        "render_qc_ref": {"render_id": RENDER_ID, "render_sha256": R_SHA},
        "voice_ref": {
            "voice": {"voice_kind": "PROVIDER_STOCK", "presenter_kind": "NEUTRAL_NARRATION"}
        },
        "thumbnails_ref": {
            "variants": [
                {
                    "variant_id": "v1",
                    "text_local": "T1",
                    "picture": {"kind": "OWNER_IMAGE", "asset_id": "ast_5"},
                },
                {
                    "variant_id": "v2",
                    "text_local": "T2",
                    "picture": {"kind": "CODE_GLYPH", "asset_id": None},
                },
                {
                    "variant_id": "v3",
                    "text_local": "T3",
                    "picture": {"kind": "NONE", "asset_id": None},
                },
            ]
        },
        "uniqueness_ref": {"verdict": "ALLOWED"},
        "research_pack_ref": {
            "evidence": [
                {"citation_ref": "ref_a", "method_labelled": False},
                {"citation_ref": "ref_m", "method_labelled": True},
            ],
            "citations_available": [
                {"citation_ref": "ref_a", "kind": "EXTERNAL_REFERENCE"},
                {"citation_ref": "ref_m", "kind": "EXTERNAL_REFERENCE"},
            ],
            "method": {"used": True, "release_approval_ids": [RELEASE]},
        },
        "frames_ref": {
            "render_sha256": R_SHA,
            "frames": [
                {
                    "frame_id": f"f{i:02d}",
                    "frame_index": i,
                    "t_ms": i * 1000,
                    "uri": f"u{i}",
                    "sha256": "d" * 64,
                }
                for i in range(1, 4)
            ],
        },
        "gate_output_ref": {
            "subject": {
                "render_id": RENDER_ID,
                "render_sha256": R_SHA,
                "script_id": SCRIPT_ID,
                "script_sha256": "",  # stamped by ``blobs_of``
            },
            "verdict": "ALLOWED",
            "rules": [
                {"rule_id": "YTG-R6", "check_verdict": "PASS"},
                {"rule_id": "FIN-R10", "check_verdict": "PASS"},
            ],
            "disclosure": {"decision": "NOT_REQUIRED"},
        },
    }


def script_sha(d: Mapping[str, Any] | None = None) -> str:
    """The subject's ``script_sha256``: the hash of the script blob (agent_06 8.2)."""
    return sha(j((d or docs())["script_ref"]))


def blobs_of(d: Mapping[str, Any]) -> dict[str, bytes]:
    """Serialise the documents; the script hash carried by the verification and gate outputs is
    stamped from the script document, so a test that changes the script keeps them consistent."""
    out = dict(d)
    stamp = script_sha(d) if "script_ref" in d else ""
    if "verification_ref" in out:
        out["verification_ref"] = out["verification_ref"] | {"script_sha256": stamp}
    if "gate_output_ref" in out:
        g = out["gate_output_ref"]
        if "subject" in g:
            out["gate_output_ref"] = g | {"subject": g["subject"] | {"script_sha256": stamp}}
    return {k: j(v) for k, v in out.items()}


def asset_row(aid: str, **over: Any) -> AssetFactRow:
    base: dict[str, Any] = {
        "asset_id": aid,
        "tier": VisualSourceTier.C_CODE_MOTION,
        "shows_person": False,
        "is_realistic_synthetic": False,
        "has_ledger_row": True,
        "licence_state": LicenceState.ACTIVE,
        "covers_monetized_youtube": True,
        "third_party_permission": None,
    }
    return AssetFactRow(**(base | over))


def with_asset(rows: Rows, aid: str, **over: Any) -> None:
    """Replace fields of an asset row (the rows are frozen dataclasses)."""
    old = rows.asset_rows[aid]
    fields = {f: getattr(old, f) for f in old.__slots__}
    rows.asset_rows[aid] = AssetFactRow(**(fields | over))


@dataclass
class Rows:
    """In-memory ``FactRowReader`` (no SQL): every method returns what the test configured."""

    channel_row: ChannelRow | None = field(
        default_factory=lambda: ChannelRow("finance", AudienceKind.GENERAL, "kcl_1")
    )
    job_row: JobRow | None = None
    asset_rows: dict[str, AssetFactRow] = field(default_factory=dict)
    presenter: PresenterKind | None = PresenterKind.NEUTRAL_NARRATION
    judged: tuple[str, ...] = ("qc.watermark.visual", "qc.visual.no_synthetic_presenter")
    release: dict[str, str] = field(default_factory=lambda: {RELEASE: RELEASE_SHA})
    quotes: dict[str, str] = field(default_factory=dict)
    qc: tuple[QcRow, ...] | None = ()
    thumb_qc: tuple[QcRow, ...] = ()
    claim_rows: tuple[ClaimRow, ...] = ()

    def channel(self, tx: TenantTransaction, job_id: str) -> ChannelRow | None:
        return self.channel_row

    def job(self, tx: TenantTransaction, job_id: str) -> JobRow | None:
        return self.job_row

    def assets(self, tx: TenantTransaction, asset_ids: Sequence[str]) -> Mapping[str, AssetFactRow]:
        return {a: self.asset_rows[a] for a in asset_ids if a in self.asset_rows}

    def voice_presenter_kind(self, tx: TenantTransaction, job_id: str) -> PresenterKind | None:
        return self.presenter

    def judged_qc_check_ids(self, tx: TenantTransaction, render_id: str) -> tuple[str, ...]:
        return self.judged

    def release_approval_subjects(
        self, tx: TenantTransaction, approval_ids: Sequence[str]
    ) -> Mapping[str, str]:
        return {a: self.release[a] for a in approval_ids if a in self.release}

    def copyright_doubt_approvals(
        self, tx: TenantTransaction, span_hashes: Sequence[str]
    ) -> Mapping[str, str]:
        return {h: a for h, a in self.quotes.items() if h in span_hashes}

    def qc_rows(self, tx: TenantTransaction, render_id: str) -> tuple[QcRow, ...] | None:
        return self.qc

    def thumbnail_qc_rows(self, tx: TenantTransaction, job_id: str) -> tuple[QcRow, ...]:
        return self.thumb_qc

    def claims(self, tx: TenantTransaction, claim_ids: Sequence[str]) -> tuple[ClaimRow, ...]:
        return self.claim_rows


def full_rows(**over: Any) -> Rows:
    rows = Rows(
        job_row=JobRow(
            language="mr-IN",
            production_type_key="CHANNEL_LONG_FORM",
            live_format=None,
            active_pack_keys=("rp.finance_sebi_in", "rp.youtube_general"),
            routing_script_stage_id="s05_script",
            routing_assets_stage_id="s08_assets",
            routing_thumbnails_stage_id="s11_thumbs",
        ),
        asset_rows={
            "ast_1": asset_row("ast_1"),
            "ast_2": asset_row("ast_2", tier=VisualSourceTier.B_LICENSED_STOCK),
            "ast_3": asset_row("ast_3"),
            "ast_4": asset_row("ast_4"),
            "ast_5": asset_row("ast_5", tier=VisualSourceTier.A_OWNER_REAL, shows_person=True),
        },
    )
    for k, v in over.items():
        setattr(rows, k, v)
    return rows


def request(d: Mapping[str, Any] | None = None, **over: Any) -> ComplianceGateInput:
    org = str(ids.ORG.new())
    ref = {"uri": f"amw-blob://{org}/jobs/x", "sha256": "0" * 64}
    data: dict[str, Any] = {
        "subject": {
            "render_id": RENDER_ID,
            "render_sha256": R_SHA,
            "script_id": SCRIPT_ID,
            "script_sha256": script_sha(d),
        },
        "iteration": 0,
        "channel_category": "finance",
        "production_type_key": "CHANNEL_LONG_FORM",
        "destination_kinds": ["FILE_DELIVERY"],
        "evaluate_as_destination": "YOUTUBE",
        "owner_sebi_registration": "UNREGISTERED",
        "language": "mr-IN",
        "routing": {
            "script_stage_id": "s05_script",
            "assets_stage_id": "s08_assets",
            "thumbnails_stage_id": "s11_thumbs",
        },
        "inputs": dict.fromkeys(
            (
                "script_ref",
                "claims_ref",
                "verification_ref",
                "asset_manifest_ref",
                "shot_plan_ref",
                "render_qc_ref",
                "voice_ref",
                "thumbnails_ref",
                "uniqueness_ref",
                "research_pack_ref",
                "frames_ref",
            ),
            ref,
        )
        | {"metadata_ref": None},
    }
    return ComplianceGateInput.model_validate(data | over)


def scope(req: ComplianceGateInput) -> ReadScope:
    return ReadScope(ids.new_id(ids.Prefix.JOB), req.subject.render_id)


PASS_QC = QcRow(check_id="qc.audio.loudness", verdict=CheckVerdict.PASS)
CLAIM_ROWS = (
    ClaimRow("clm_1", "HISTORICAL_MARKET", ClaimStatus.VERIFIED, 1, "chart_a", None),
    ClaimRow("clm_2", "FACTUAL", ClaimStatus.UNVERIFIABLE, 0, None, ("apr_s", "e" * 64)),
)
