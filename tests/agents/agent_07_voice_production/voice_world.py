"""Builds the world of one ``voice_synthesis`` golden case (fixtures -> fakes) and runs it."""

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

from agent_07_voice_production.ports import (
    ApprovalFacts,
    AssetFacts,
    AudioAnalysis,
    LicenceFacts,
    StreamFacts,
    VoiceBundle,
)
from agent_07_voice_production.voice_stage import VoiceDeps, VoiceSynthesisStage
from amw_adapters.common import FailurePlan
from amw_core.contracts.common import PayloadObject, ResourceBudget
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import TaskOutput
from amw_core.enums import (
    ApprovalState,
    AssetStatus,
    ConsentState,
    LicenceSourceType,
    LicenceState,
    PresenterKind,
    Priority,
    ThirdPartyPermission,
    VoiceKind,
)
from amw_core.errors import RateLimitedError
from amw_core.exec_context import ExecContext
from amw_core.ids import CHANNEL, CORRELATION, JOB, TASK, Prefix, new_id
from amw_core.interfaces.voices import VoiceConsentRecord, VoiceRecord
from amw_core.testing.memory import MemoryCheckpointStore, MemoryIdempotencyStore
from tests.agents.agent_07_voice_production.support import (
    NOW,
    FakeBreaker,
    FakeBudget,
    FakeClock,
    FakeControl,
    FakeFacts,
    FakeRegistry,
    MemoryBlobs,
    MemoryLedger,
    MemoryTenancy,
    PcmTools,
    ToneTts,
    ViewOf,
    capabilities,
    config,
    exec_ctx,
    tone_samples,
    wav_bytes,
)

OTHER_ORG = "org_01939e5a-7c3b-7d1e-8a4f-0123456789cd"
OTHER_CHANNEL = "chn_01939e5a-7c3b-7d1e-8a4f-0123456789cd"


class HumanTools(PcmTools):
    """Descriptor-driven facts for the owner recording (no real decoder in the unit run)."""

    def __init__(self, asset: dict[str, Any]) -> None:
        self.asset = asset

    def probe(self, path: Path) -> StreamFacts:
        a = self.asset
        samples = a["duration_ms"] * a["sample_rate_hz"] // 1000
        return StreamFacts(a["sample_rate_hz"], a["channels"], samples, "pcm_s16le")

    def to_working_format(self, src: Path, dst: Path) -> None:
        dst.write_bytes(wav_bytes(tone_samples(self.asset["duration_ms"])))

    def analyse(
        self, path: Path, *, silence_noise_db: float, silence_min_s: float
    ) -> AudioAnalysis:
        base = super().analyse(path, silence_noise_db=silence_noise_db, silence_min_s=silence_min_s)
        return AudioAnalysis(
            base.stream,
            base.loudness,
            self.asset["clipping_samples"],
            base.peak_dbfs,
            base.silence_runs,
            base.noise_floor_dbfs,
        )


@dataclass
class VoiceWorld:
    stage: VoiceSynthesisStage
    task_input: TaskInput
    tts: ToneTts
    ledger: MemoryLedger
    registry: FakeRegistry
    blobs: MemoryBlobs
    facts: FakeFacts
    budget: FakeBudget
    org: str

    def ctx(self, attempt: str | None = None) -> ExecContext:
        return exec_ctx(self.task_input, attempt or _ATTEMPT)

    def run(self, attempt: str | None = None) -> TaskOutput:
        return self.stage.run(self.task_input, self.ctx(attempt))


_ATTEMPT = new_id(Prefix.TASK_ATTEMPT)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(case: dict[str, Any], scratch: Path, *, control: FakeControl | None = None) -> VoiceWorld:
    fx = case["input"]["fixtures"]
    payload: dict[str, Any] = json.loads(json.dumps(case["input"]["payload"]))
    org = payload["script_ref"].split("://", 1)[1].split("/", 1)[0]
    gate = fx["script_gate"]
    blobs = MemoryBlobs()

    # script, verification, dictionary blobs
    script_doc = json.dumps(fx["script"], ensure_ascii=False).encode()
    script_hash = _sha(script_doc)
    ref_org = OTHER_ORG if gate["script_ref_org"] == "other" else org
    payload["script_ref"] = payload["script_ref"].replace(org, ref_org)
    blobs.seed(payload["script_ref"].replace(ref_org, org), script_doc)
    if ref_org != org:
        blobs.seed(payload["script_ref"], script_doc)
    payload["script_sha256"] = script_hash if gate["sha_matches"] else payload["script_sha256"]
    verification = {
        "script_id": payload["script_id"],
        "script_version": payload["script_version"],
        "overall": {"verification_verdict": gate["verdict"]},
    }
    blobs.seed(payload["verification_ref"], json.dumps(verification).encode())
    dfx = fx["dictionary"]
    dictionary = json.dumps(
        {
            "dictionary_key": "test-dict",
            "language": "mr-IN",
            "version": 1,
            "entries": dfx["entries"],
        },
        ensure_ascii=False,
    ).encode()
    blobs.seed(payload["dictionary_ref"], dictionary)
    payload["dictionary_sha256"] = _sha(dictionary)

    channel = CHANNEL.new()
    asset_org: Any = OTHER_ORG if dfx["org"] == "other" else org
    allowed: Any = (channel,) if dfx["channel_permitted"] else (OTHER_CHANNEL,)
    assets: dict[str, AssetFacts] = {
        payload["dictionary_ref"]: AssetFacts(
            new_id(Prefix.ASSET),
            asset_org,
            "DOCUMENT",
            True,
            allowed,
            _sha(dictionary),
        )
    }

    # voice bundle
    vfx = fx["voice"]
    voice_id = payload["voice_id"]
    kind = VoiceKind(vfx["kind"])
    lic = vfx["licence"]
    licence = None
    if vfx["licence_id_resolves"] and lic is not None:
        licence = LicenceFacts(
            new_id(Prefix.LICENCE),
            None if lic["holder"] == "platform" else org,
            LicenceState(lic["state"]),
            LicenceSourceType(lic["source_type"]),
            lic["covers_monetized_youtube"],
            ThirdPartyPermission(lic["third_party_permission"]),
        )
    consent_id: Any = new_id(Prefix.VOICE_CONSENT) if vfx["consent"] is not None else None
    consent = None
    owner_flag = False
    if vfx["consent"] is not None:
        cf = vfx["consent"]
        permitted: Any
        if cf.get("permitted_channel_ids") == "NULL":
            permitted = None
        elif cf["permitted_channel_ids_contains_channel"]:
            permitted = (channel,)
        else:
            permitted = (OTHER_CHANNEL,)
        consent = VoiceConsentRecord(
            consent_id,
            org,
            ConsentState(cf["state"]),
            permitted,
            False,
            NOW - timedelta(days=1) if cf["expired"] else None,
            NOW - timedelta(days=1) if cf["withdrawn"] else None,
        )
        owner_flag = cf["voice_owner_is_org_owner"]
    human = kind is VoiceKind.HUMAN_RECORDED
    voice = VoiceRecord(
        voice_id,
        org,
        "test voice",
        kind,
        None if human else "fake_tts",
        None if human else "fake-neutral-1",
        tuple(vfx["languages"]),
        consent_id,
        None,
        licence.licence_id if licence is not None else None,
        PresenterKind(vfx["presenter_kind"]),
        AssetStatus(vfx["status"]),
    )
    bundle = None if vfx["org"] == "other" else VoiceBundle(voice, licence, consent, owner_flag)

    approval = None
    if gate.get("approval") is not None:
        ap = gate["approval"]
        approval = ApprovalFacts(
            ApprovalState(ap["state"]),
            payload["script_sha256"] if ap["subject_sha256_matches"] else "0" * 64,
        )
    facts = FakeFacts(
        script_hash=script_hash,
        approval_facts=approval,
        bundle=bundle,
        brand_kit_voice=voice_id if vfx["brand_kit_binds"] else new_id(Prefix.VOICE),
        monetized=fx["job"]["monetized_destination"],
        platform_owner=fx["org_kind"] == "PLATFORM_OWNER",
        assets=assets,
    )

    tools: PcmTools = PcmTools()
    if human:
        hn = fx["human_narration"]["asset"]
        raw = b"owner-recording-bytes-" + payload["human_narration"]["asset_ref"].encode()
        payload["human_narration"]["asset_sha256"] = blobs.seed(
            payload["human_narration"]["asset_ref"], raw
        )
        assets[payload["human_narration"]["asset_ref"]] = AssetFacts(
            new_id(Prefix.ASSET),
            cast(Any, OTHER_ORG if hn["org"] == "other" else org),
            "AUDIO_VOICE",
            hn["status"] == "ACTIVE",
            None,
            payload["human_narration"]["asset_sha256"],
        )
        tools = HumanTools(hn)

    afx = fx["adapter"]
    failures = FailurePlan()
    if afx["fake"]["behaviour"] == "RATE_LIMIT_ONCE_ON_s2":
        failures = FailurePlan(sequence=[None, RateLimitedError("429", retry_after_ms=1)])
    tts = ToneTts(
        ms_per_char=afx["fake"]["ms_per_char"],
        behaviour=afx["fake"]["behaviour"],
        failures=failures,
    )
    caps = capabilities(
        pace=afx["pace_control"],
        emotion=afx["emotion_control"],
        phoneme=afx["phoneme_support"],
        languages=tuple(afx["languages"]),
        max_chars=afx["max_chars_per_request"],
    )
    cfg_fx = fx["config"]
    cfg = config(
        gap_ms=cfg_fx["gap_ms"],
        trim_keep_ms=cfg_fx["trim_keep_ms"],
        price_micros_per_1k_chars=cfg_fx["price_micros_per_1k_chars"],
        sample_max_segments=cfg_fx["sample_max_segments"],
    )
    bfx = fx["budget"]
    budget = FakeBudget(
        provider_row=bfx["provider_budget_row"] == "ACTIVE",
        reservation_micros=bfx["reservation_micros"],
    )
    ledger, registry = MemoryLedger(), FakeRegistry()
    deps = VoiceDeps(
        config=cfg,
        tts=ViewOf(tts, caps),
        storage=blobs,
        tenancy=MemoryTenancy(),
        idempotency=MemoryIdempotencyStore(),
        ledger=cast(Any, ledger),
        budget=cast(Any, budget),
        breaker=FakeBreaker(open_=bfx["breaker"] == "OPEN"),
        checkpoints=MemoryCheckpointStore(),
        facts=facts,
        registry=registry,
        tools=tools,
        clock=FakeClock(),
        control=control or FakeControl(),
        scratch_root=scratch,
        sleep=lambda _s: None,
    )
    task_input = make_task_input(
        org, channel, payload, "agent_07.voice_synthesis.input", "agent_07"
    )
    return VoiceWorld(
        VoiceSynthesisStage(deps), task_input, tts, ledger, registry, blobs, facts, budget, org
    )


def make_task_input(
    org: str, channel: str, payload: dict[str, Any], schema: str, agent: str
) -> TaskInput:
    return TaskInput(
        org_id=org,
        job_id=JOB.new(),
        task_id=TASK.new(),
        project_id=None,
        channel_id=channel,
        agent_id=agent,
        source_agent="agent_01",
        priority=Priority.NORMAL,
        deadline=None,
        context_refs=(),
        resource_budget=ResourceBudget(
            max_cost_micros=50_000_000, currency="USD", max_wall_ms=600_000
        ),
        payload=PayloadObject(payload_schema=schema, payload_schema_version="1.0.0", data=payload),
        correlation_id=CORRELATION.new(),
        idempotency_key="idk_" + "0" * 64,
        retry_count=0,
        schema_version="1.0.0",
    )
