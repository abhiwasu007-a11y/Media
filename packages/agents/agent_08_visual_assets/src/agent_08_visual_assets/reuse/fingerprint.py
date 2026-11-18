"""Fingerprints (FR-12, blueprint 6.10, GLOSSARY ``fingerprint_algo``; ``algo_version`` 1).

``SHA256``: SHA-256 of the file bytes. ``PERCEPTUAL_FRAME``: per sampled frame, luma, resized to
9 x 8, bit 1 when a pixel is darker than its right neighbour (64-bit difference hash, row-major,
most significant bit first), stored as 16 hex characters. Distance is the Hamming distance.
Pillow does the decoding and resizing; no network, no randomness.
"""

import hashlib
import io
from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image

from amw_core.errors import InputInvalidError

ALGO_VERSION = 1
GRID_W, GRID_H = 9, 8
MAX_PIXELS = 64_000_000  # decompression-bomb guard (S-13)

Image.MAX_IMAGE_PIXELS = MAX_PIXELS


@dataclass(frozen=True, slots=True)
class FrameHash:
    frame_ms: int
    hash_hex: str


@dataclass(frozen=True, slots=True)
class FingerprintSet:
    sha256: str
    algo_version: int
    perceptual_frames: tuple[FrameHash, ...]


class FingerprintDHash:
    @staticmethod
    def compute(grid: Sequence[Sequence[int]]) -> str:
        if len(grid) != GRID_H or any(len(row) != GRID_W for row in grid):
            raise InputInvalidError("luma grid must be 9 columns by 8 rows")
        value = 0
        for row in grid:
            for x in range(GRID_W - 1):
                value = (value << 1) | (1 if row[x] < row[x + 1] else 0)
        return f"{value:016x}"

    @staticmethod
    def luma_grid(image_bytes: bytes) -> list[list[int]]:
        """9 x 8 luma grid of an encoded still (PNG, JPEG, ...)."""
        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                small = img.convert("L").resize((GRID_W, GRID_H), Image.Resampling.LANCZOS)
        except OSError, Image.DecompressionBombError, ValueError:
            raise InputInvalidError("media cannot be decoded as an image") from None
        pixels = list(small.tobytes())
        return [pixels[r * GRID_W : (r + 1) * GRID_W] for r in range(GRID_H)]


def hamming(a: str, b: str) -> int:
    if len(a) != 16 or len(b) != 16:
        raise InputInvalidError("perceptual hashes are 16 hex characters")
    return (int(a, 16) ^ int(b, 16)).bit_count()


class Fingerprinter:
    """Fingerprints a still (one frame); clips go through a ``MediaProbePort`` frame sampler."""

    @staticmethod
    def sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @classmethod
    def still(cls, content: bytes) -> FingerprintSet:
        grid = FingerprintDHash.luma_grid(content)
        return FingerprintSet(
            cls.sha256(content), ALGO_VERSION, (FrameHash(0, FingerprintDHash.compute(grid)),)
        )

    @classmethod
    def from_grids(
        cls, content: bytes, frames: Sequence[tuple[int, Sequence[Sequence[int]]]]
    ) -> FingerprintSet:
        return FingerprintSet(
            cls.sha256(content),
            ALGO_VERSION,
            tuple(FrameHash(ms, FingerprintDHash.compute(grid)) for ms, grid in frames),
        )
