"""Brand fonts (owner decision 2026-11-19, WS-06): Mukta primary, Noto Sans Devanagari fallback.

Covers the pinned files and licences, the per-glyph fallback, the stage wiring (provenance, no
fallback for tenant fonts) and the regression for the "boxes" seen in the dry run (break 14).
"""

import hashlib
import io
import json
from importlib import resources

import pytest
from fontTools.ttLib import TTFont  # type: ignore[import-untyped]
from PIL import Image, ImageDraw, ImageFont

from agent_11_thumbnail_design.canary import canary_spec
from agent_11_thumbnail_design.composer import PillowComposer, font_pieces
from agent_11_thumbnail_design.errors import GlyphMissingError
from agent_11_thumbnail_design.models import Brief, Promise
from agent_11_thumbnail_design.pinning import (
    FALLBACK_FONT_KEY,
    font_manifest,
    pinned_font_bytes,
)
from agent_11_thumbnail_design.ports import RegisteredAsset
from agent_11_thumbnail_design.templates import glyph_catalogue
from tests.agents.agent_11_thumbnail_design.env import Env, err_of, make_env, run_att
from tests.agents.agent_11_thumbnail_design.fontgen import build_font
from tests.agents.agent_11_thumbnail_design.test_composer import ORG, spec

#: Title and subject words of the dry run (the Marathi title of ``thumb_v1.png``) and a
#: mixed Marathi / Latin line; ``ळ`` and ``ऱ`` are Marathi letters.
MARATHI_TITLE = "डायव्हर्जन्स ?"
MARATHI_LINES = ("ट्रेंड कसा वाचायचा", "डायव्हर्जन्स ?", "ऱ ळ ज्ञ क्ष श्र ₹ trend 2026")
NOTDEF_PROBE = "\U000f0000"  # unassigned private-use plane code point: every font draws .notdef


def _read(name: str) -> bytes:
    return (
        resources.files("agent_11_thumbnail_design")
        .joinpath("data/fonts")
        .joinpath(name)
        .read_bytes()
    )


def _manifest_raw() -> dict[str, dict[str, object]]:
    raw = json.loads(_read("manifest.json"))
    return {f["key"]: f for f in raw["fonts"]}


def _mask(font: ImageFont.FreeTypeFont, text: str) -> bytes:
    img = Image.new("L", (400, 200), 0)
    ImageDraw.Draw(img).text((20, 20), text, font=font, fill=255)
    return img.tobytes()


def _font(data: bytes, px: int = 90) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(io.BytesIO(data), px, layout_engine=ImageFont.Layout.RAQM)


# ---------------------------------------------------------------------------- pinned files


@pytest.mark.parametrize("key", ["mukta_regular", "mukta_bold"])
def test_mukta_is_pinned_ofl_with_its_licence_beside_the_font(key: str) -> None:
    entry = _manifest_raw()[key]
    data = _read(str(entry["file"]))
    assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    assert len(data) == entry["bytes"]
    assert entry["licence"] == "OFL-1.1"
    assert entry["unmodified"] is True
    assert entry["purpose"] == "brand_primary"
    assert entry["research_id"] == "RV-09"
    licence = _read(str(entry["licence_file"])).decode("utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1" in licence
    assert str(entry["copyright"]) in licence.splitlines()[0]
    name = TTFont(io.BytesIO(data))["name"]
    assert name.getDebugName(0) == entry["copyright"]  # the font's own copyright line
    assert font_manifest()[str(entry["sha256"])].key == key


def test_noto_is_the_pinned_fallback() -> None:
    entry = _manifest_raw()[FALLBACK_FONT_KEY]
    assert entry["purpose"] == "brand_fallback"
    assert entry["licence"] == "OFL-1.1"
    assert hashlib.sha256(pinned_font_bytes(FALLBACK_FONT_KEY)).hexdigest() == entry["sha256"]


def test_every_manifest_font_file_is_listed_and_no_unlisted_font_ships() -> None:
    listed = {str(f["file"]) for f in _manifest_raw().values()}
    shipped = {
        p.name
        for p in resources.files("agent_11_thumbnail_design").joinpath("data/fonts").iterdir()
        if p.name.endswith((".ttf", ".otf", ".ttc", ".woff", ".woff2"))
    }
    assert shipped == listed


# ---------------------------------------------------------------------------- tofu regression


@pytest.mark.parametrize("key", ["mukta_regular", "mukta_bold", FALLBACK_FONT_KEY])
def test_marathi_text_has_no_notdef_glyphs_cmap_and_pixels(key: str) -> None:
    """No .notdef box for the Marathi title and subject words: cmap AND pixel evidence."""
    data = pinned_font_bytes(key)
    text = " ".join(MARATHI_LINES)
    # 1. cmap: every code point maps to a real glyph (not gid 0 / .notdef)
    tt = TTFont(io.BytesIO(data))
    cmap = tt.getBestCmap()
    notdef = tt.getGlyphOrder()[0]
    chars = {c for c in text if not c.isspace()}
    assert not [c for c in chars if ord(c) not in cmap or cmap[ord(c)] == notdef]
    assert not PillowComposer().missing_glyphs(ORG, data, text)
    # 2. pixels: each character's raster differs from the .notdef box of the same font, and the
    #    whole title is not a row of boxes (Raqm shapes conjuncts, so compare per character).
    font = _font(data)
    box = _mask(font, NOTDEF_PROBE)
    assert any(box)
    for ch in sorted(chars):
        got = _mask(font, ch)
        assert any(got), f"U+{ord(ch):04X} draws nothing"
        assert got != box, f"U+{ord(ch):04X} renders as the .notdef box"
    title = _mask(font, MARATHI_TITLE)
    assert title != _mask(font, NOTDEF_PROBE * len(MARATHI_TITLE))


def test_rendered_marathi_thumbnail_title_is_real_text_and_tofu_is_refused() -> None:
    data = pinned_font_bytes("mukta_bold")
    sha = hashlib.sha256(data).hexdigest()
    ok = PillowComposer().render(spec(font_bytes=data, font_sha256=sha, lines=(MARATHI_TITLE,)))
    assert not ok.missing_glyphs
    assert ok.runs
    img = Image.open(io.BytesIO(ok.png)).convert("RGB")
    x0, y0, x1, y1 = ok.text_box_px
    text_px = img.crop((x0, y0, x1, y1))
    background = text_px.getpixel((0, 0))
    ink = sum(1 for p in text_px.get_flattened_data() if p != background)
    assert ink > 2000  # real glyph ink in the title box
    # a code point no font covers is refused (never drawn as a .notdef box)
    with pytest.raises(GlyphMissingError):
        PillowComposer().render(spec(font_bytes=data, font_sha256=sha, lines=(NOTDEF_PROBE * 4,)))


def test_the_subject_picture_is_a_code_drawn_chart_line_and_does_not_depend_on_the_font() -> None:
    """Break 14 / Q-O30 (D11 item 4): the three outlined rectangles of the dry run were the glyph
    ``g1_level_steps``, drawn by code, not font tofu. They are replaced by ``g1_rsi_line`` (axes,
    two guide lines and one oscillating line; no outlined rectangle). The subject area is still
    identical whatever the font is."""
    keys = [g.key for g in glyph_catalogue()]
    assert "g1_level_steps" not in keys
    g1 = next(g for g in glyph_catalogue() if g.key == "g1_rsi_line")
    assert g1.neutral
    assert sum(op["op"] == "polygon" for op in g1.ops) == 1  # the line
    assert all(op["outline"] is None for op in g1.ops)  # nothing reads as an outlined box
    tpl_box = spec().template.subject_box
    w, h = 1920, 1080
    x, y, bw, bh = tpl_box
    region = (x * w // 1000, y * h // 1000, (x + bw) * w // 1000, (y + bh) * h // 1000)
    pics = []
    for key in ("mukta_bold", "noto_sans_devanagari_vf"):
        d = pinned_font_bytes(key)
        r = PillowComposer().render(
            spec(font_bytes=d, font_sha256=hashlib.sha256(d).hexdigest(), lines=(MARATHI_TITLE,))
        )
        pics.append(Image.open(io.BytesIO(r.png)).convert("RGB").crop(region).tobytes())
    assert pics[0] == pics[1]


# ---------------------------------------------------------------------------- per-glyph fallback


def test_font_pieces_splits_only_where_the_primary_lacks_a_glyph() -> None:
    primary, fallback = frozenset(map(ord, "abc ")), frozenset(map(ord, "xyz"))
    assert font_pieces("ab c", primary, fallback) == [("ab c", False)]
    assert font_pieces("abxyc", primary, fallback) == [("ab", False), ("xy", True), ("c", False)]
    assert font_pieces("ax y", primary, fallback) == [("a", False), ("x y", True)]
    assert font_pieces("ab", primary, None) == [("ab", False)]  # no fallback: one primary run
    assert font_pieces("", primary, fallback) == []


def test_fallback_draws_a_glyph_mukta_lacks_and_without_it_the_render_fails() -> None:
    mukta = pinned_font_bytes("mukta_bold")
    assert 0x0978 not in TTFont(io.BytesIO(mukta)).getBestCmap()
    comp = PillowComposer()
    assert comp.missing_glyphs(ORG, mukta, "ॸ") == ("ॸ",)
    with_fb = canary_spec("mukta_bold_noto_fallback")
    assert with_fb.fallback_font_bytes is not None
    assert not comp.missing_glyphs(
        ORG, mukta, "".join(with_fb.lines), None, with_fb.fallback_font_bytes
    )
    assert comp.render(with_fb).missing_glyphs == ()
    from dataclasses import replace

    with pytest.raises(GlyphMissingError):
        comp.render(replace(with_fb, fallback_font_bytes=None, fallback_font_sha256=None))


def test_fallback_that_is_not_needed_changes_no_pixel() -> None:
    """Text fully covered by Mukta renders identically with or without the fallback font set."""
    mukta = pinned_font_bytes("mukta_bold")
    base = spec(font_bytes=mukta, font_sha256=hashlib.sha256(mukta).hexdigest(), lines=("ट्रेंड",))
    from dataclasses import replace

    fb = pinned_font_bytes(FALLBACK_FONT_KEY)
    withfb = replace(
        base, fallback_font_bytes=fb, fallback_font_sha256=hashlib.sha256(fb).hexdigest()
    )
    assert (
        PillowComposer().render(base).pixel_sha256 == PillowComposer().render(withfb).pixel_sha256
    )


def test_tampered_fallback_is_refused() -> None:
    from dataclasses import replace

    from agent_11_thumbnail_design.errors import FontIntegrityError

    s = canary_spec("mukta_bold_noto_fallback")
    bad = bytearray(s.fallback_font_bytes or b"")
    bad[-1] ^= 1
    with pytest.raises(FontIntegrityError):
        PillowComposer().render(replace(s, fallback_font_bytes=bytes(bad)))


# ---------------------------------------------------------------------------- stage wiring


def _marathi() -> tuple[Promise, Brief]:
    return (
        Promise(
            promise_statement="डायव्हर्जन्स कसा वाचायचा ते तुम्ही शिकाल.",
            promise_key_terms=("डायव्हर्जन्स",),
            working_title_local="डायव्हर्जन्स कसा वाचायचा",
        ),
        Brief(
            subject_idea="outline of level steps",
            text_idea_local="डायव्हर्जन्स ?",
            must_not_promise=("profit",),
        ),
    )


def test_stage_with_mukta_records_primary_and_fallback_in_the_provenance() -> None:
    env = make_env(language="mr-IN", promise=_marathi(), font=pinned_font_bytes("mukta_bold"))
    out = run_att(env, env.ti, "att_1")
    assert out.payload is not None
    assert out.payload.data is not None
    assert out.payload.data["verdict"] == "ALLOWED"
    prov = out.payload.data["provenance"]
    assert prov["font_source"] == "repo_manifest:mukta_bold"
    assert prov["font_fallback_source"] == f"repo_manifest:{FALLBACK_FONT_KEY}"


def _non_manifest_font() -> bytes:
    """A valid font whose bytes are not in the repo manifest (stands for a tenant's own font)."""
    tt = TTFont(io.BytesIO(build_font()))
    tt["head"].fontRevision = 7.0
    out = io.BytesIO()
    tt.save(out)
    data = out.getvalue()
    assert hashlib.sha256(data).hexdigest() not in font_manifest()
    return data


def _provenance(env: Env) -> dict[str, object]:
    out = run_att(env, env.ti, "att_1")
    assert out.payload is not None
    assert out.payload.data is not None
    prov: dict[str, object] = out.payload.data["provenance"]
    return prov


def test_a_tenant_font_gets_no_fallback() -> None:
    env = make_env(font=_non_manifest_font())
    prov = _provenance(env)
    assert prov["font_source"] == "tenant_asset"
    assert prov["font_fallback_source"] is None
    assert prov["font_fallback_used"] is False


def test_manifest_only_policy_refuses_a_non_manifest_font_but_not_manifest_fonts() -> None:
    from amw_core.errors import MissingDependencyError

    env = make_env(font=_non_manifest_font(), agent_11__fonts__policy="MANIFEST_ONLY")
    info = err_of(run_att(env, env.ti, "att_1"), MissingDependencyError)
    assert "font_manifest_only" in str(info.details.model_dump())
    ok = make_env(
        language="mr-IN",
        promise=_marathi(),
        font=pinned_font_bytes("mukta_bold"),
        agent_11__fonts__policy="MANIFEST_ONLY",
    )
    assert _provenance(ok)["font_source"] == "repo_manifest:mukta_bold"
    free = make_env(font=_non_manifest_font(), agent_11__fonts__policy="TENANT_ALLOWED")
    assert _provenance(free)["font_source"] == "tenant_asset"


def _with_fallback_glyph() -> tuple[Promise, Brief]:
    return (
        Promise(
            promise_statement="डायव्हर्जन्स कसा वाचायचा ते तुम्ही शिकाल.",
            promise_key_terms=("डायव्हर्जन्स",),
            working_title_local="डायव्हर्जन्स ॸ वाचा",
        ),
        Brief(
            subject_idea="outline of level steps",
            text_idea_local="डायव्हर्जन्स ॸ",
            must_not_promise=("profit",),
        ),
    )


def test_noto_is_registered_and_licensed_whenever_it_draws_a_glyph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_11_thumbnail_design import stage as stage_mod

    seen: list[object] = []
    original = stage_mod._Run._licence_facts

    def spy(self: object, *args: object, **kwargs: object) -> object:
        facts = original(self, *args, **kwargs)  # type: ignore[arg-type]
        seen.extend(facts)
        return facts

    monkeypatch.setattr(stage_mod._Run, "_licence_facts", spy)
    env = make_env(
        language="mr-IN", promise=_with_fallback_glyph(), font=pinned_font_bytes("mukta_bold")
    )
    env.repo.registered[("FONT", FALLBACK_FONT_KEY)] = RegisteredAsset(
        "ast_noto", "FONT", FALLBACK_FONT_KEY, "ACTIVE", True, "FONT"
    )
    prov = _provenance(env)
    assert prov["font_fallback_used"] is True
    assert "ast_noto" in prov["font_asset_ids"]  # type: ignore[operator]
    fonts_used = {r.asset_id for r in env.repo.ledger if r.usage_kind == "FONT"}
    assert fonts_used == {"ast_font", "ast_noto"}
    noto = [f for f in seen if getattr(f, "asset_id", None) == "ast_noto"]
    assert noto, "no LicenceFact for the Noto fallback font"
    for fact in noto:
        assert fact.usage_kind == "FONT"  # type: ignore[attr-defined]
        assert fact.has_ledger_row is True  # type: ignore[attr-defined]
        assert fact.ledger_has_interval is False  # type: ignore[attr-defined]
        assert fact.licence_state == "ACTIVE"  # type: ignore[attr-defined]
        assert fact.covers_monetized is True  # type: ignore[attr-defined]


def test_unregistered_noto_refuses_when_it_would_draw_a_glyph_and_is_not_needed_otherwise() -> None:
    from amw_core.errors import MissingDependencyError

    need = make_env(
        language="mr-IN", promise=_with_fallback_glyph(), font=pinned_font_bytes("mukta_bold")
    )
    err_of(run_att(need, need.ti, "att_1"), MissingDependencyError)
    plain = make_env(language="mr-IN", promise=_marathi(), font=pinned_font_bytes("mukta_bold"))
    prov = _provenance(plain)  # Mukta covers everything: Noto is not used, so not required
    assert prov["font_fallback_used"] is False
    assert prov["font_asset_ids"] == ["ast_font"]


# ---------------------------------------------------------------------------- one coverage rule


def test_agent_10_and_agent_11_agree_on_what_the_font_set_covers() -> None:
    from agent_10_video_editor.fonts import cmap_font_reader
    from agent_10_video_editor.timeline import FontCoverage
    from amw_core.errors import InputInvalidError

    mukta, noto = pinned_font_bytes("mukta_bold"), pinned_font_bytes(FALLBACK_FONT_KEY)
    comp = PillowComposer()
    sets = {"mukta": (mukta, None), "mukta+noto": (mukta, noto)}
    for name, (primary, fallback) in sets.items():
        cps = [cmap_font_reader(primary)] + ([cmap_font_reader(fallback)] if fallback else [])
        covered_by_10 = frozenset().union(*cps)
        for ch in "ॸडायव्हर्जन्स ?ऱळ₹→▲▼a ":
            try:
                FontCoverage.check(covered_by_10, [ch])
                ten_ok = True
            except InputInvalidError:
                ten_ok = False
            eleven_ok = not comp.missing_glyphs(ORG, primary, ch, None, fallback)
            assert ten_ok == eleven_ok, (name, ch)
    assert comp.missing_glyphs(ORG, mukta, "ॸ") == ("ॸ",)
    assert comp.missing_glyphs(ORG, mukta, "ॸ", None, noto) == ()


# ---------------------------------------------------------------------------- weight, arrows


def test_fallback_glyph_uses_the_weight_of_the_requested_mukta_weight() -> None:
    from dataclasses import replace

    bold = canary_spec("mukta_bold_noto_fallback")
    assert bold.fallback_weight == 700
    regular = replace(bold, fallback_weight=400)
    assert (
        PillowComposer().render(bold).pixel_sha256 != PillowComposer().render(regular).pixel_sha256
    )


@pytest.mark.parametrize("ch", ["→", "↑", "▲", "▼", "⬆"])
def test_arrows_and_triangles_are_in_neither_font_and_are_refused_not_drawn_as_boxes(
    ch: str,
) -> None:
    mukta, noto = pinned_font_bytes("mukta_bold"), pinned_font_bytes(FALLBACK_FONT_KEY)
    comp = PillowComposer()
    assert comp.missing_glyphs(ORG, mukta, ch, None, noto) == (ch,)
    from dataclasses import replace

    with pytest.raises(GlyphMissingError):
        comp.render(replace(canary_spec("mukta_bold_noto_fallback"), lines=(f"ट्रेंड {ch}",)))


def test_the_owner_channel_default_is_manifest_only_and_refuses_a_non_manifest_font() -> None:
    """No key set (the owner channel): the code default is MANIFEST_ONLY."""
    from agent_11_thumbnail_design.config import Agent11Settings
    from amw_core.errors import MissingDependencyError
    from tests.agents.agent_11_thumbnail_design.fakes import settings

    assert settings(agent_11__fonts__policy=None).fonts_policy == "MANIFEST_ONLY"
    assert Agent11Settings.model_fields["fonts_policy"].default == "MANIFEST_ONLY"
    env = make_env(font=_non_manifest_font(), agent_11__fonts__policy=None)
    info = err_of(run_att(env, env.ti, "att_1"), MissingDependencyError)
    assert "font_manifest_only" in str(info.details.model_dump())
    owner = make_env(
        language="mr-IN",
        promise=_marathi(),
        font=pinned_font_bytes("mukta_bold"),
        agent_11__fonts__policy=None,
    )
    assert _provenance(owner)["font_source"] == "repo_manifest:mukta_bold"
