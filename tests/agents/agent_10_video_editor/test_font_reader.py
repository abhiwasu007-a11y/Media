"""F-10 font coverage with the repo's brand fonts (owner decision WS-06): Mukta, Noto fallback."""

from pathlib import Path

import pytest

from agent_10_video_editor.fonts import cmap_font_reader
from agent_10_video_editor.timeline import FontCoverage
from amw_core.errors import InputInvalidError

FONTS = (
    Path(__file__).resolve().parents[3]
    / "packages/agents/agent_11_thumbnail_design/src/agent_11_thumbnail_design/data/fonts"
)
TITLE = "डायव्हर्जन्स ? ट्रेंड कसा वाचायचा ऱ ळ ₹ 2026 trend"


@pytest.mark.unit
def test_mukta_covers_marathi_and_latin_and_noto_adds_the_missing_glyph() -> None:
    mukta = cmap_font_reader((FONTS / "Mukta-Bold.ttf").read_bytes())
    noto = cmap_font_reader((FONTS / "NotoSansDevanagari-VF.ttf").read_bytes())
    FontCoverage.check(mukta, [TITLE])
    assert 0x0978 not in mukta
    assert 0x0978 in noto  # DEVANAGARI LETTER MARWARI DDA
    with pytest.raises(InputInvalidError):
        FontCoverage.check(mukta, ["ॸ"])
    FontCoverage.check(mukta | noto, ["ॸ"])  # per-glyph fallback: the union of the manifest fonts
