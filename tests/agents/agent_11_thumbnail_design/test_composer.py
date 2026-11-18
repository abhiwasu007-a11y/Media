"""Composer tests: determinism (U-90..94), canary (U-169), shaping evidence (NFR-7), failures."""

import hashlib
import io
from dataclasses import replace

import pytest
from agent_11_thumbnail_design.composer import PillowComposer, RenderSpec, hex_to_rgb, phash64
from agent_11_thumbnail_design.errors import GlyphMissingError, TextDoesNotFitError
from agent_11_thumbnail_design.templates import glyph_catalogue, load_templates, palette
from PIL import Image, ImageFont

from tests.agents.agent_11_thumbnail_design.env import png_bytes
from tests.agents.agent_11_thumbnail_design.fontgen import build_font

FONT = build_font()
FONT_SHA = hashlib.sha256(FONT).hexdigest()
ORG = "org_00000000-0000-7000-8000-000000000001"
#: Recorded canary (U-169): the fixed fixture below renders to this SHA-256 with Pillow 13.0.0
#: (Raqm 0.11.0, HarfBuzz 14.5.0, FreeType 2.14.3). A library change re-records it on purpose.
CANARY_SHA256 = "3cbf11eca3b912013ef02294b4c444a2da3954967dee1ad00cb706325356f221"


def spec(**over: object) -> RenderSpec:
    tpl = {t.template_key: t for t in load_templates()}[str(over.pop("tpl", "tpl_split_left_text"))]
    base = {
        "org_id": ORG, "canvas_w": 1920, "canvas_h": 1080, "template": tpl, "colours": palette(),
        "lines": ("Read the trend",), "emphasis": "TERM_HIGHLIGHT", "accent_role": "PRIMARY",
        "key_terms": ("trend",), "picture_kind": "CODE_GLYPH", "glyph": glyph_catalogue()[0],
        "image_bytes": None, "image_sha256": None, "font_bytes": FONT, "font_sha256": FONT_SHA,
        "min_font_px": 48, "max_font_px": 200, "font_step_px": 8,
    }  # fmt: skip
    base.update(over)
    return RenderSpec(**base)  # type: ignore[arg-type]


def test_byte_identical_across_runs_and_instances() -> None:
    a = PillowComposer().render(spec())
    b = PillowComposer().render(spec())
    c = PillowComposer().render(spec())
    assert a.png == b.png == c.png
    assert a.composition_sha256 == b.composition_sha256
    assert (a.width, a.height) == (1920, 1080)
    assert Image.open(io.BytesIO(a.png)).size == (1920, 1080)


def test_canary_hash_is_recorded() -> None:
    sha = hashlib.sha256(PillowComposer().render(spec()).png).hexdigest()
    assert CANARY_SHA256 == sha, f"re-record the canary: {sha}"


def test_changing_the_text_changes_the_pixels_and_hash() -> None:
    comp = PillowComposer()
    a = comp.render(spec())
    b = comp.render(spec(lines=("trend",)))
    assert a.png != b.png
    assert a.phash != b.phash


def test_text_is_drawn_in_two_colours_for_a_highlight_and_contrast_is_measured() -> None:
    r = PillowComposer().render(spec())
    assert len(r.runs) == 2  # "Read the" and the highlighted key term
    assert {run.fg for run in r.runs} == {
        hex_to_rgb(palette()["text"]),
        hex_to_rgb(palette()["primary"]),
    }
    assert min(run.contrast for run in r.runs) > 4.5
    assert r.lines == ("Read the trend",)


def test_two_tone_and_centered_template() -> None:
    r = PillowComposer().render(
        spec(
            tpl="tpl_centered_statement",
            lines=("Read the trend", "price structure"),
            emphasis="TWO_TONE",
            accent_role="SECONDARY",
        )
    )
    assert len(r.runs) == 2
    assert r.runs[1].fg == hex_to_rgb(palette()["secondary"])


def test_owner_image_is_drawn_into_the_band_template() -> None:
    img = png_bytes((10, 200, 10), (800, 800))
    r = PillowComposer().render(
        spec(tpl="tpl_full_bleed_subject_band", picture_kind="OWNER_IMAGE", glyph=None, image_bytes=img,
             image_sha256=hashlib.sha256(img).hexdigest(), emphasis="PLAIN")
    )  # fmt: skip
    pix = Image.open(io.BytesIO(r.png)).convert("RGB")
    assert pix.getpixel((960, 300)) == (10, 200, 10)  # picture area
    assert pix.getpixel((960, 1000))[0] < 40  # the band below is the background colour


def test_a_long_single_option_wraps_to_two_balanced_lines() -> None:
    r = PillowComposer().render(
        spec(
            tpl="tpl_centered_statement",
            lines=("trend from price structure basics",),
            emphasis="PLAIN",
        )
    )
    assert len(r.lines) == 2
    assert " ".join(r.lines) == "trend from price structure basics"


def test_text_that_cannot_fit_raises() -> None:
    with pytest.raises(TextDoesNotFitError):
        PillowComposer().render(spec(lines=("x" * 70,), min_font_px=120))


def test_missing_glyph_is_reported_and_not_rendered() -> None:
    comp = PillowComposer()
    assert comp.missing_glyphs(ORG, FONT, "Read 漢") == ("漢",)
    with pytest.raises(GlyphMissingError):
        comp.render(spec(lines=("Read 漢",)))


def test_font_cap_steps_the_size_down() -> None:
    comp = PillowComposer()
    big = comp.render(spec())
    small = comp.render(spec(font_cap_px=big.font_px - 16))
    assert small.font_px <= big.font_px - 16


def test_phash_is_16_hex_digits() -> None:
    assert len(phash64(Image.new("RGB", (64, 64), (1, 2, 3)))) == 16


def test_devanagari_conjunct_is_shaped_by_raqm_not_by_a_naive_layout() -> None:
    """Shaping evidence: KA + VIRAMA + SSA becomes one conjunct glyph under HarfBuzz (Raqm).

    The generated test font has one ``akhn`` ligature (width 700); a naive layout adds the three
    advances. ``Image.core`` reports Raqm, so a missing engine fails here, not silently.
    """
    comp = PillowComposer()
    assert comp.raqm_available()
    raqm = ImageFont.truetype(io.BytesIO(FONT), 100, layout_engine=ImageFont.Layout.RAQM)
    basic = ImageFont.truetype(io.BytesIO(FONT), 100, layout_engine=ImageFont.Layout.BASIC)
    assert raqm.getlength("क्ष") == 70.0
    assert basic.getlength("क्ष") == 150.0
    r = comp.render(spec(lines=("ट्रेंड क्ष",), emphasis="PLAIN", key_terms=()))
    assert r.runs and not r.missing_glyphs


def test_system_devanagari_font_when_present() -> None:
    """Real-font evidence when a Devanagari OFL/GPL font exists on the machine (not committed)."""
    import pathlib

    path = pathlib.Path("/usr/share/fonts/truetype/freefont/FreeSerif.ttf")
    if not path.is_file():
        pytest.skip("OPEN ITEM: no system Devanagari font; real-font shaping evidence not run")
    data = path.read_bytes()
    raqm = ImageFont.truetype(io.BytesIO(data), 100, layout_engine=ImageFont.Layout.RAQM)
    basic = ImageFont.truetype(io.BytesIO(data), 100, layout_engine=ImageFont.Layout.BASIC)
    assert raqm.getlength("क्ष") < basic.getlength("क्ष")
    assert not PillowComposer().missing_glyphs(ORG, data, "ट्रेंड कसा वाचायचा")


def test_replace_import_is_used() -> None:
    assert replace(spec(), lines=("a",)).lines == ("a",)
