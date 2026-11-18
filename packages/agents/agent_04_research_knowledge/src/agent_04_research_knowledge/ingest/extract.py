"""FormatDetector, TextLayerExtractor, PageQualityChecker (blueprint 10.9; ADR-013 section 2.2).

Text layer only in 3A: plain text, Markdown and HTML are read here; a page break is a form feed.
PDF, EPUB and DOCX need a document-library decision that is not part of this build, so they are
refused as unsupported (the source becomes ``FAILED``, never silently dropped). No OCR engine is
called: a page that fails the quality check is recorded ``needs_ocr`` for 3B.
"""

from dataclasses import dataclass

from agent_04_research_knowledge.errors import InputInvalid
from agent_04_research_knowledge.steps.external import html_to_text

TEXT = "text"
HTML = "html"
_TEXT_TYPES = {"text/plain": TEXT, "text/markdown": TEXT, "text/html": HTML}
PAGE_BREAK = "\f"


def detect_format(media_type: str) -> str:
    kind = _TEXT_TYPES.get(media_type.split(";", 1)[0].strip().lower())
    if kind is None:
        raise InputInvalid("unsupported source format for text-layer extraction")
    return kind


@dataclass(frozen=True, slots=True)
class Page:
    number: int
    text: str = ""

    def __repr__(self) -> str:
        return f"Page({self.number})"


def extract_pages(content: bytes, media_type: str) -> list[Page]:
    kind = detect_format(media_type)
    try:
        raw = content.decode("utf-8")
    except UnicodeDecodeError:
        raise InputInvalid("source file is corrupt (not valid UTF-8 text)") from None
    if kind == HTML:
        raw = html_to_text(raw)
    return [Page(i, t) for i, t in enumerate(raw.split(PAGE_BREAK), start=1)]


class PageQualityChecker:
    """A page is usable when it has enough text and few non-printable characters."""

    def __init__(self, min_chars: int, max_nonprintable_ratio: float) -> None:
        self._min, self._max = min_chars, max_nonprintable_ratio

    def needs_ocr(self, page: Page) -> bool:
        text = page.text.strip()
        if len(text) < self._min:
            return True
        bad = sum(1 for c in text if not (c.isprintable() or c in "\n\t")) + text.count("�")
        return bad / len(text) > self._max
