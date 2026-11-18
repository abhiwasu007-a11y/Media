"""PR 37 review fixes: B1 channel-map loudness, M3 required config, M4 master clipping, M5 codec."""

import wave
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from agent_07_voice_production.config import AgentSevenConfig
from agent_07_voice_production.master import MasterRun, run_passes
from agent_07_voice_production.master_stage import _require_delivery_encode, evaluate_master
from agent_07_voice_production.pcm import count_full_scale_pcm
from agent_07_voice_production.ports import Loudness, StreamFacts
from amw_core.errors import ConfigInvalidError, IncompleteOutputError
from tests.agents.agent_07_voice_production.master_world import StubFfmpeg
from tests.agents.agent_07_voice_production.support import config
from tests.agents.agent_07_voice_production.test_master_loop import analysis, stem

pytestmark = pytest.mark.unit

DUAL_MONO_LU = 3.0103


@dataclass
class DualMonoStub(StubFfmpeg):
    """The mapped measurement of a mono stem reads +3.01 LU louder (BS.1770 channel sum)."""

    def measure_mapped(self, stem: Path, *, input_channels: int) -> Loudness:
        base = super().measure_mapped(stem, input_channels=input_channels)
        assert base.integrated_lufs is not None
        extra = DUAL_MONO_LU if input_channels == 1 else 0.0
        return Loudness(base.integrated_lufs + extra, base.true_peak_dbtp, base.lra_lu)


def test_gain_is_solved_from_the_mapped_loudness(tmp_path: Path) -> None:
    ff = DualMonoStub(stem(-23.0, -13.0), [0.3], 384_000, [])
    run = run_passes(ff, stem=Path("x"), pre=analysis(ff), cfg=config(), workdir=tmp_path)
    assert run.gain_db == pytest.approx(9.0 - DUAL_MONO_LU, abs=1e-3)  # not the mono-based 9.0


def test_required_master_keys_have_no_shipped_default() -> None:
    bare = AgentSevenConfig.checked(config_version="x")
    assert bare.limiter_ceiling_dbtp is None
    assert bare.codec_headroom_step_db is None
    assert bare.pause_span_tolerance_ms is None
    with pytest.raises(ConfigInvalidError) as err:
        bare.require_master()
    assert err.value.details["missing"] == [
        "limiter_ceiling_dbtp",
        "codec_headroom_step_db",
        "pause_span_tolerance_ms",
    ]
    config().require_master()


def test_required_voice_keys_include_the_retry_and_lock_settings() -> None:
    bare = AgentSevenConfig.checked(
        config_version="x",
        gap_ms=1,
        trim_keep_ms=0,
        price_micros_per_1k_chars=1,
        price_ref="p",
    )
    with pytest.raises(ConfigInvalidError) as err:
        bare.require_voice()
    assert err.value.details["missing"] == [
        "max_attempt_retries",
        "max_retry_after_ms",
        "idempotency_lock_ms",
    ]


def _run(tmp: Path) -> tuple[MasterRun, AgentSevenConfig]:
    ff = StubFfmpeg(stem(-23.0, -13.0), [0.3], 384_000, [])
    cfg = config()
    return run_passes(ff, stem=Path("x"), pre=analysis(ff), cfg=cfg, workdir=tmp), cfg


def test_master_clipping_is_a_blocking_gate(tmp_path: Path) -> None:
    run, cfg = _run(tmp_path)
    run = replace(run, master_clipping_samples=3)
    ff = StubFfmpeg(stem(-23.0, -13.0), [0.3], 384_000, [])
    results, _ = evaluate_master(
        cfg=cfg,
        pre=analysis(ff),
        run=run,
        pauses=(),
        duration_delta_samples=0,
        music_offset=None,
        music_active=False,
    )
    clip = next(r for r in results if r.check_id == "qc.audio.clipping")
    assert clip.gate
    assert clip.blocking
    assert clip.verdict.value == "FAIL"
    assert clip.remedy_stage_id == "s07_voice"
    ok, _ = _run(tmp_path)
    assert ok.master_clipping_samples == 0


def test_count_full_scale_in_a_24_bit_master(tmp_path: Path) -> None:
    path = tmp_path / "m.wav"
    frames = [0, 8_388_607, -8_388_608, 1000, -8_388_607]  # rails: +max, -min
    raw = b"".join(v.to_bytes(3, "little", signed=True) for v in frames)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(3)
        handle.setframerate(48_000)
        handle.writeframes(raw)
    assert count_full_scale_pcm(path) == 2


@pytest.mark.parametrize(
    ("override", "check"),
    [
        ({"codec": "mp3"}, "qc.audio.codec"),
        ({"profile": "HE"}, "qc.audio.codec"),
        ({"sample_rate_hz": 44_100}, "qc.audio.sample_rate"),
        ({"channels": 1}, "qc.audio.channels"),
        ({"bitrate_bps": 256_000}, "qc.audio.bitrate"),
    ],
)
def test_a_wrong_encode_is_an_integrity_failure_not_a_constant(
    tmp_path: Path, override: dict[str, Any], check: str
) -> None:
    run, cfg = _run(tmp_path)
    bad = replace(run, codec=replace(run.codec, **override))
    with pytest.raises(IncompleteOutputError) as err:
        _require_delivery_encode(bad, cfg)
    assert check in err.value.details["check_ids"]
    _require_delivery_encode(run, cfg)


def test_a_master_stream_that_is_not_stereo_48k_is_refused(tmp_path: Path) -> None:
    run, cfg = _run(tmp_path)
    bad = replace(run, master_stream=StreamFacts(48_000, 1, 48_000, "x"))
    with pytest.raises(IncompleteOutputError):
        _require_delivery_encode(bad, cfg)
