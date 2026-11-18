"""A tiny generated test font (box glyphs; nothing downloaded, nothing large committed).

It covers ASCII and a few Devanagari letters. Its GSUB table has one ``akhn`` ligature
(KA + VIRAMA + SSA -> one conjunct glyph) so a shaping engine can be told apart from a naive one.
"""

import io

from fontTools.feaLib.builder import addOpenTypeFeaturesFromString  # type: ignore[import-untyped]
from fontTools.fontBuilder import FontBuilder  # type: ignore[import-untyped]
from fontTools.pens.ttGlyphPen import TTGlyphPen  # type: ignore[import-untyped]

ADVANCE = 600
DEVANAGARI = {
    "ka": 0x0915,
    "ssa": 0x0937,
    "virama": 0x094D,
    "tta": 0x091F,
    "ra": 0x0930,
    "ee": 0x0947,
    "anusvara": 0x0902,
    "dda": 0x0921,
    "va": 0x0935,
    "aa": 0x093E,
    "ca": 0x091A,
    "ya": 0x092F,
    "na": 0x0928,
    "ma": 0x092E,
    "ta": 0x0924,
    "sa": 0x0938,
    "pa": 0x092A,
    "la": 0x0932,
    "ha": 0x0939,
    "ga": 0x0917,
    "da": 0x0926,
    "ba": 0x092C,
    "ii": 0x0940,
    "uu": 0x0942,
    "ra2": 0x0930,
}
CONJUNCT_ADVANCE = 700
VIRAMA_ADVANCE = 300


def _box(width: int, h: int = 700) -> object:
    pen = TTGlyphPen(None)
    pen.moveTo((50, 0))
    pen.lineTo((50, h))
    pen.lineTo((width - 50, h))
    pen.lineTo((width - 50, 0))
    pen.closePath()
    return pen.glyph()


def build_font() -> bytes:
    chars = {f"u{cp:04X}": cp for cp in range(0x21, 0x7F)}
    names = {name: cp for name, cp in DEVANAGARI.items() if name != "ra2"}
    glyph_order = [".notdef", "space", *chars, *names, "ka_ssa"]
    cmap = {
        0x20: "space",
        **{cp: n for n, cp in chars.items()},
        **{cp: n for n, cp in names.items()},
    }
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(glyph_order)
    fb.setupCharacterMap(cmap)
    glyphs = {}
    metrics = {}
    for g in glyph_order:
        width = {"space": 300, "virama": VIRAMA_ADVANCE, "ka_ssa": CONJUNCT_ADVANCE}.get(g, ADVANCE)
        glyphs[g] = _box(width) if g != "space" else TTGlyphPen(None).glyph()
        metrics[g] = (width, 50)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "A11 Test Box", "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    fb.setupPost()
    addOpenTypeFeaturesFromString(
        fb.font,
        "languagesystem DFLT dflt;\nlanguagesystem dev2 dflt;\nlanguagesystem deva dflt;\n"
        "feature akhn { sub ka virama ssa by ka_ssa; } akhn;\n",
    )
    out = io.BytesIO()
    fb.font.save(out)
    return out.getvalue()
