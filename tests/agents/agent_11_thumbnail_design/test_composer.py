"""Composer tests: determinism (U-90..94), canary (U-169), shaping evidence (NFR-7), failures."""

import hashlib
import io
import os
import time
from dataclasses import replace

import pytest
from fontTools.ttLib import TTFont  # type: ignore[import-untyped]
from PIL import Image, ImageFont

from agent_11_thumbnail_design import pinning
from agent_11_thumbnail_design.canary import CANARY_FONTS, canary_spec
from agent_11_thumbnail_design.composer import PillowComposer, RenderSpec, hex_to_rgb, phash64
from agent_11_thumbnail_design.errors import (
    FontIntegrityError,
    GlyphMissingError,
    TextDoesNotFitError,
)
from agent_11_thumbnail_design.pinning import (
    current_fingerprint,
    font_manifest,
    pinned_font_bytes,
    pixel_sha256,
    recorded_canary,
    render_environment,
    verify_font,
)
from agent_11_thumbnail_design.templates import glyph_catalogue, load_templates, palette
from tests.agents.agent_11_thumbnail_design.env import png_bytes
from tests.agents.agent_11_thumbnail_design.fontgen import build_font

FONT = build_font()
FONT_SHA = hashlib.sha256(FONT).hexdigest()
ORG = "org_00000000-0000-7000-8000-000000000001"
#: Canary (U-169): the ``canary.py`` fixtures render to a recorded raster hash per FreeType
#: version (``data/environments.json``; box test font, real Noto font). PNG bytes are not the
#: cross-host identity (host zlib); the decoded raster is.


def spec(**over: object) -> RenderSpec:
    tpl = {t.template_key: t for t in load_templates()}[str(over.pop("tpl", "tpl_split_left_text"))]
    base = {
        "org_id": ORG,
        "canvas_w": 1920,
        "canvas_h": 1080,
        "template": tpl,
        "colours": palette(),
        "lines": ("Read the trend",),
        "emphasis": "TERM_HIGHLIGHT",
        "accent_role": "PRIMARY",
        "key_terms": ("trend",),
        "picture_kind": "CODE_GLYPH",
        "glyph": glyph_catalogue()[0],
        "image_bytes": None,
        "image_sha256": None,
        "font_bytes": FONT,
        "font_sha256": FONT_SHA,
        "min_font_px": 48,
        "max_font_px": 200,
        "font_step_px": 8,
    }
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


@pytest.mark.parametrize("font_key", CANARY_FONTS)
def test_canary_hash_is_recorded(font_key: str) -> None:
    """Listed FreeType: exact match. Unlisted: skip with the hash; strict in the clean-image job."""
    fp = current_fingerprint()
    got = PillowComposer().render(canary_spec(font_key)).pixel_sha256
    recorded = recorded_canary(fp.freetype2, font_key)
    if recorded is None:
        msg = f"environment not recorded: freetype {fp.freetype2} ({font_key}); pixel_sha256={got}"
        if os.environ.get("A11_REQUIRE_RECORDED_ENV") == "1":
            pytest.fail(msg)
        pytest.skip(msg)
    assert got == recorded, f"canary differs for FreeType {fp.freetype2} ({font_key}): {got}"


def test_canary_fixture_is_the_documented_spec() -> None:
    assert canary_spec("a11_test_box").font_sha256 == FONT_SHA
    assert PillowComposer().render(canary_spec("a11_test_box")).png == (
        PillowComposer().render(spec()).png
    )


def test_render_environment_is_recorded_as_provenance_and_never_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fp = current_fingerprint()
    monkeypatch.setattr(pinning, "current_fingerprint", lambda: replace(fp, freetype2="0.0.0"))
    rec = render_environment()
    assert rec["freetype2"] == "0.0.0"
    assert rec["canary_recorded"] is False
    assert len(str(rec["font_manifest_sha256"])) == 64
    assert PillowComposer().render(spec()).pixel_sha256  # an unlisted environment still renders


def test_pixel_hash_is_the_decoded_raster_and_png_encoding_does_not_change_it() -> None:
    """Same pixels, different zlib level: different file bytes, identical pixel identity."""
    r = PillowComposer().render(spec())
    img = Image.open(io.BytesIO(r.png))
    img.load()
    assert pixel_sha256(img.mode, img.size, img.tobytes()) == r.pixel_sha256
    other = io.BytesIO()
    img.save(other, "PNG", compress_level=1)
    assert other.getvalue() != r.png
    again = Image.open(io.BytesIO(other.getvalue()))
    again.load()
    assert pixel_sha256(again.mode, again.size, again.tobytes()) == r.pixel_sha256
    assert not img.info  # no metadata chunks (no time stamp, no profile, no gamma)


def test_test_font_bytes_do_not_depend_on_the_wall_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression of the flake: head.created/modified used to carry the build time."""
    first = build_font()
    monkeypatch.setattr(time, "time", lambda: 1_900_000_000.0)
    assert build_font() == first


def test_committed_test_font_equals_generator_and_is_pinned() -> None:
    assert build_font() == build_font()  # no wall-clock time stamp in the font
    assert pinned_font_bytes("a11_test_box") == build_font()
    assert FONT_SHA in font_manifest()


def test_production_font_is_pinned_ofl_and_shapes_devanagari() -> None:
    data = pinned_font_bytes("noto_sans_devanagari_vf")
    pinned = font_manifest()[hashlib.sha256(data).hexdigest()]
    assert pinned.licence == "OFL-1.1"
    assert not PillowComposer().missing_glyphs(ORG, data, "ट्रेंड कसा वाचायचा")
    r = PillowComposer().render(
        spec(font_bytes=data, font_sha256=pinned.sha256, lines=("ट्रेंड वाचा",))
    )
    assert r.font_px >= 48


def test_tampered_font_is_refused() -> None:
    bad = bytearray(FONT)
    bad[-1] ^= 1
    with pytest.raises(FontIntegrityError):  # bytes do not match the claimed (recorded) hash
        PillowComposer().render(spec(font_bytes=bytes(bad)))
    with pytest.raises(FontIntegrityError):  # same check on the glyph-coverage path
        PillowComposer().missing_glyphs(ORG, bytes(bad), "abc", FONT_SHA)


def test_tenant_brand_font_with_a_recorded_hash_is_allowed() -> None:
    """FR-09: a font outside the repo manifest renders when its bytes match the recorded hash."""
    tt = TTFont(io.BytesIO(FONT))
    tt["name"].setName("Brand Box", 1, 3, 1, 0x409)
    out = io.BytesIO()
    tt.save(out)
    brand = out.getvalue()
    sha = hashlib.sha256(brand).hexdigest()
    assert sha not in font_manifest()
    assert verify_font(brand, sha) == "tenant_asset"
    assert PillowComposer().render(spec(font_bytes=brand, font_sha256=sha)).pixel_sha256 == (
        PillowComposer().render(spec()).pixel_sha256
    )
    assert verify_font(FONT, FONT_SHA) == "repo_manifest:a11_test_box"


def test_system_font_is_never_used(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[object] = []
    real = ImageFont.truetype

    def spy(font: object, *a: object, **k: object) -> object:
        seen.append(font)
        return real(font, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(ImageFont, "truetype", spy)
    PillowComposer().render(spec())
    assert seen
    assert all(isinstance(f, io.BytesIO) for f in seen)  # memory only: no name, no path


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
        spec(
            tpl="tpl_full_bleed_subject_band",
            picture_kind="OWNER_IMAGE",
            glyph=None,
            image_bytes=img,
            image_sha256=hashlib.sha256(img).hexdigest(),
            emphasis="PLAIN",
        )
    )
    pix = Image.open(io.BytesIO(r.png)).convert("RGB")
    assert pix.getpixel((960, 300)) == (10, 200, 10)  # picture area
    bottom = pix.getpixel((960, 1000))
    assert isinstance(bottom, tuple)
    assert bottom[0] < 40  # the band below is the background colour


def test_a_long_single_option_wraps_to_two_balanced_lines() -> None:
    r = PillowComposer().render(
        spec(
            tpl="tpl_centered_statement",
            lines=("trend from price structure basics",),
            emphasis="PLAIN",
            min_font_px=100,
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
    assert r.runs
    assert not r.missing_glyphs


def test_pinned_brand_font_shapes_conjuncts_with_raqm() -> None:
    """Real-font shaping evidence with the pinned Mukta (no system font is read)."""
    data = pinned_font_bytes("mukta_regular")
    raqm = ImageFont.truetype(io.BytesIO(data), 100, layout_engine=ImageFont.Layout.RAQM)
    basic = ImageFont.truetype(io.BytesIO(data), 100, layout_engine=ImageFont.Layout.BASIC)
    assert raqm.getlength("क्ष") < basic.getlength("क्ष")
    assert not PillowComposer().missing_glyphs(ORG, data, "ट्रेंड कसा वाचायचा")


def test_replace_import_is_used() -> None:
    assert replace(spec(), lines=("a",)).lines == ("a",)
