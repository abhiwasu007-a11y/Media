"""A lint finding: stable identity (no line numbers) so a baseline can list known defects."""

from dataclasses import dataclass

JsonObject = dict[str, object]


@dataclass(frozen=True, order=True)
class Finding:
    path: str  # posix path relative to the repository (or lint root parent)
    code: str  # e.g. P-SECTIONS, E-COUNT
    message: str

    @property
    def key(self) -> str:
        return f"{self.path}|{self.code}|{self.message}"
