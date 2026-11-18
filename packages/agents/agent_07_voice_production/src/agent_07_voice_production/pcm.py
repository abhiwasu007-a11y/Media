"""PCM helpers on 16-bit WAV (stdlib ``wave`` only): header facts, clipping count, levels,
silence trimming and concatenation at sample precision.

The working format of the voice step is PCM 16-bit mono 48 000 Hz (FR-10); stems and clips are
always written in it, so these helpers cover everything the voice step measures itself. Loudness
and true peak are never computed here: they come from FFmpeg ``ebur128`` (INF-09).
"""

import math
import wave
from array import array
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from amw_core.errors import CorruptedOutputError, InputInvalidError

FULL_SCALE = 32_768
MAX_S16 = 32_767
MIN_S16 = -32_768
SILENT_DBFS = -120.0


@dataclass(frozen=True, slots=True)
class WavInfo:
    sample_rate_hz: int
    channels: int
    sample_width: int
    frames: int


def wav_info(path: Path) -> WavInfo:
    """Header facts of any PCM WAV (any width); undecodable input is a typed error."""
    try:
        with wave.open(str(path), "rb") as handle:
            return WavInfo(
                handle.getframerate(),
                handle.getnchannels(),
                handle.getsampwidth(),
                handle.getnframes(),
            )
    except (wave.Error, EOFError, OSError) as exc:
        raise CorruptedOutputError("audio is not a decodable PCM WAV") from exc


def read_s16(path: Path) -> tuple[WavInfo, array[int]]:
    """Interleaved samples of a 16-bit WAV."""
    info = wav_info(path)
    if info.sample_width != 2:
        raise InputInvalidError(
            "only 16-bit PCM is handled here", details={"width": info.sample_width}
        )
    with wave.open(str(path), "rb") as handle:
        raw = handle.readframes(info.frames)
    samples: array[int] = array("h")
    samples.frombytes(raw)
    return info, samples


def decode_s16_bytes(data: bytes) -> tuple[WavInfo, array[int]]:
    """Samples of a 16-bit WAV held in memory (a provider clip)."""
    import io

    try:
        with wave.open(io.BytesIO(data), "rb") as handle:
            info = WavInfo(
                handle.getframerate(),
                handle.getnchannels(),
                handle.getsampwidth(),
                handle.getnframes(),
            )
            raw = handle.readframes(info.frames)
    except (wave.Error, EOFError) as exc:
        raise CorruptedOutputError("provider audio is not a decodable PCM WAV") from exc
    if info.sample_width != 2:
        raise CorruptedOutputError("provider audio is not 16-bit PCM")
    samples: array[int] = array("h")
    samples.frombytes(raw)
    return info, samples


def write_s16(
    path: Path, samples: Sequence[int] | array[int], sample_rate_hz: int, channels: int
) -> None:
    data = samples if isinstance(samples, array) else array("h", samples)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(data.tobytes())


def count_clipped(samples: Sequence[int]) -> int:
    """Samples at digital full scale (18 section 5, stem samples at 0 dBFS)."""
    return sum(1 for s in samples if s >= MAX_S16 or s <= MIN_S16)


def peak_dbfs(samples: Sequence[int]) -> float:
    peak = max((abs(s) for s in samples), default=0)
    return SILENT_DBFS if peak == 0 else round(20 * math.log10(peak / FULL_SCALE), 2)


def rms_dbfs(samples: Sequence[int]) -> float:
    if not samples:
        return SILENT_DBFS
    mean_square = sum(s * s for s in samples) / len(samples)
    return (
        SILENT_DBFS if mean_square == 0 else round(10 * math.log10(mean_square / FULL_SCALE**2), 2)
    )


def trim_silence(
    samples: array[int], sample_rate_hz: int, keep_ms: int, threshold_dbfs: float
) -> array[int]:
    """Trim leading and trailing silence to ``keep_ms`` at each edge (FR-10). An all-silent clip
    is a provider fault (a silent clip must not become a success, FI-07)."""
    threshold = FULL_SCALE * 10 ** (threshold_dbfs / 20)
    first = next((i for i, s in enumerate(samples) if abs(s) > threshold), None)
    if first is None:
        raise CorruptedOutputError("provider audio is silent")
    last = len(samples) - 1 - next(i for i, s in enumerate(reversed(samples)) if abs(s) > threshold)
    keep = keep_ms * sample_rate_hz // 1000
    return samples[max(0, first - keep) : min(len(samples), last + 1 + keep)]


def silence_samples(duration_ms: int, sample_rate_hz: int) -> array[int]:
    return array("h", bytes(2 * (duration_ms * sample_rate_hz // 1000)))


def count_full_scale_pcm(path: Path) -> int:
    """Samples at digital full scale in a 16, 24 or 32-bit PCM WAV (``qc.audio.clipping``).
    A sample counts when it sits at the positive or negative rail of its width."""
    info = wav_info(path)
    width = info.sample_width
    if width not in (2, 3, 4):
        raise InputInvalidError("unsupported PCM width", details={"width": width})
    with wave.open(str(path), "rb") as handle:
        raw = handle.readframes(info.frames)
    high, low = (1 << (8 * width - 1)) - 1, -(1 << (8 * width - 1))
    count = 0
    chunk = 3 * 65_536 if width == 3 else width * 65_536
    for offset in range(0, len(raw), chunk):
        block = raw[offset : offset + chunk]
        values: Iterable[int]
        if width == 3:
            values = (
                int.from_bytes(block[i : i + 3], "little", signed=True)
                for i in range(0, len(block) - 2, 3)
            )
        else:
            values = array("i" if width == 4 else "h", block)
        count += sum(1 for v in values if v >= high or v <= low)
    return count
