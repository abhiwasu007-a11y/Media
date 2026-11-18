"""Shared scanner bundle used by the plan, section and cut checkers."""

from dataclasses import dataclass

from agent_05_scriptwriter.checks.scanners import (
    FinPrefilter,
    ForbiddenTokenScanner,
    ForwardLookingScanner,
)
from agent_05_scriptwriter.lexicon import LexiconPack


@dataclass(frozen=True, slots=True)
class Scanners:
    lexicons: LexiconPack
    fin: FinPrefilter
    forbidden: ForbiddenTokenScanner
    forward: ForwardLookingScanner

    @classmethod
    def from_lexicons(cls, pack: LexiconPack) -> Scanners:
        return cls(
            pack, FinPrefilter(pack), ForbiddenTokenScanner(pack), ForwardLookingScanner(pack)
        )

    def languages(self, language: str) -> list[str]:
        """The script language plus ``en-IN`` for English fields when the pack has it."""
        out = [language]
        if language != "en-IN" and "en-IN" in self.lexicons.languages:
            out.append("en-IN")
        return out

    def fin_ids(self, text: str, language: str) -> list[str]:
        ids: set[str] = set()
        for lang in self.languages(language):
            ids.update(self.fin.scan(text, lang))
            ids.update(self.forward.scan(text, lang, "ANY"))
        return sorted(ids)

    def tokens(self, text: str, language: str) -> list[str]:
        found: set[str] = set()
        for lang in self.languages(language):
            found.update(self.forbidden.scan(text, lang))
        return [
            t
            for t in ("URL", "EMAIL", "HASHTAG", "REFERRAL_CODE", "FIRST_PERSON", "DISCLAIMER_LIKE")
            if t in found
        ]

    def forward_ids(self, text: str, language: str, scene_kind: str) -> list[str]:
        ids: set[str] = set()
        for lang in self.languages(language):
            ids.update(self.forward.scan(text, lang, scene_kind))
        return sorted(ids)
