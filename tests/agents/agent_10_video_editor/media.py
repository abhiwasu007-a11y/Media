"""Synthetic media generated at test time with ``lavfi`` (never real material, never network)."""

import hashlib
import shutil
import subprocess
from pathlib import Path

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
HAVE_FFMPEG = FFMPEG is not None and FFPROBE is not None


class LavfiMedia:
    """Deterministic synthetic media (fixed noise seed); bytes are cached by label."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._cache: dict[str, bytes] = {}

    def _ff(self, *args: str) -> None:
        subprocess.run(  # noqa: S603
            [str(FFMPEG), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", *args],
            check=True,
            cwd=self._root,
        )

    def _cached(self, key: str, make: str) -> bytes:
        if key not in self._cache:
            out = self._root / make
            self._cache[key] = out.read_bytes()
        return self._cache[key]

    def shot(self, label: str, duration_ms: int) -> tuple[bytes, str]:
        key = f"shot:{label}:{duration_ms}"
        if key not in self._cache:
            seed = int(hashlib.sha256(label.encode()).hexdigest()[:6], 16)
            out = self._root / f"{label}.mp4"
            self._ff(
                "-f", "lavfi", "-i",
                f"testsrc2=size=640x360:rate=30,noise=alls=30:allf=t:all_seed={seed}",
                "-t", f"{duration_ms / 1000:.3f}", "-c:v", "libx264", "-preset", "ultrafast",
                "-threads", "1", "-pix_fmt", "yuv420p", "-fflags", "+bitexact", str(out),
            )  # fmt: skip
            self._cache[key] = out.read_bytes()
        return self._cache[key], "mp4"

    def still(self, label: str) -> bytes:
        key = f"still:{label}"
        if key not in self._cache:
            out = self._root / f"{label}.png"
            self._ff(
                "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=1", "-frames:v", "1", str(out)
            )
            self._cache[key] = out.read_bytes()
        return self._cache[key]

    def master(self, duration_ms: int) -> bytes:
        key = f"master:{duration_ms}"
        if key not in self._cache:
            out = self._root / f"master{duration_ms}.wav"
            self._ff(
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-af", "volume=-6dB",
                "-t", f"{duration_ms / 1000:.3f}", "-ac", "2", str(out),
            )  # fmt: skip
            self._cache[key] = out.read_bytes()
        return self._cache[key]
