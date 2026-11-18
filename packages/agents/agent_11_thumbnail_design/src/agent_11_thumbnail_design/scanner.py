"""InjectionScanner (F-09): instruction-like content and marker detection in data."""

from collections.abc import Iterable
from dataclasses import dataclass

from agent_11_thumbnail_design.textutil import fold


@dataclass(frozen=True, slots=True)
class ScanResult:
    flagged: bool
    hits: tuple[str, ...]


class InjectionScanner:
    """Markers and instruction phrases are config / rule-pack content, never literals here."""

    def __init__(self, markers: Iterable[str], instruction_phrases: Iterable[str] = ()) -> None:
        self._needles = tuple(sorted({fold(m) for m in (*markers, *instruction_phrases) if m}))

    def scan(self, text: str) -> ScanResult:
        folded = fold(text)
        hits = tuple(n for n in self._needles if n in folded)
        return ScanResult(bool(hits), hits)
