"""The fixed canary fixtures (U-169): one render per pinned font, hashed as a decoded raster.

Used by the canary tests and by ``scripts/probe_render_env.py``. Nothing here reads the host.
"""

from agent_11_thumbnail_design.composer import RenderSpec
from agent_11_thumbnail_design.pinning import pinned_font_bytes
from agent_11_thumbnail_design.templates import glyph_catalogue, load_templates, palette

CANARY_ORG = "org_00000000-0000-7000-8000-000000000001"
CANARY_FONTS = (
    "a11_test_box",
    "noto_sans_devanagari_vf",
    "mukta_regular",
    "mukta_bold",
    "mukta_bold_noto_fallback",
)
# canary key -> (manifest font key, fallback manifest font key or None)
_FONTS: dict[str, tuple[str, str | None]] = {
    "mukta_bold_noto_fallback": ("mukta_bold", "noto_sans_devanagari_vf"),
}
_LINES = {
    "a11_test_box": (("Read the trend",), "TERM_HIGHLIGHT", ("trend",)),
    "noto_sans_devanagari_vf": (("ट्रेंड वाचा",), "PLAIN", ()),
    "mukta_regular": (("ट्रेंड वाचा trend",), "PLAIN", ()),
    "mukta_bold": (("ट्रेंड वाचा trend",), "TERM_HIGHLIGHT", ("trend",)),
    # U+0978 (Devanagari letter marwari dda) is in Noto Sans Devanagari but not in Mukta: the
    # canary proves the per-glyph fallback (mixed fonts on one baseline).
    "mukta_bold_noto_fallback": (("ट्रेंड ॸ वाचा",), "PLAIN", ()),
}


def canary_spec(font_key: str) -> RenderSpec:
    import hashlib

    lines, emphasis, terms = _LINES[font_key]
    primary_key, fallback_key = _FONTS.get(font_key, (font_key, None))
    data = pinned_font_bytes(primary_key)
    fallback = pinned_font_bytes(fallback_key) if fallback_key else None
    tpl = {t.template_key: t for t in load_templates()}["tpl_split_left_text"]
    return RenderSpec(
        org_id=CANARY_ORG,
        canvas_w=1920,
        canvas_h=1080,
        template=tpl,
        colours=palette(),
        lines=lines,
        emphasis=emphasis,
        accent_role="PRIMARY",
        key_terms=terms,
        picture_kind="CODE_GLYPH",
        glyph=glyph_catalogue()[0],
        image_bytes=None,
        image_sha256=None,
        font_bytes=data,
        font_sha256=hashlib.sha256(data).hexdigest(),
        min_font_px=48,
        max_font_px=200,
        font_step_px=8,
        fallback_font_bytes=fallback,
        fallback_font_sha256=hashlib.sha256(fallback).hexdigest() if fallback else None,
    )


__all__ = ["CANARY_FONTS", "CANARY_ORG", "canary_spec"]
