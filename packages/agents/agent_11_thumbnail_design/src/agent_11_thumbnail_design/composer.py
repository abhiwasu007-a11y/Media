"""Composer (F-13, F-14; blueprint 4.3, 9, 20): Pillow with the Raqm layout engine (HarfBuzz).

Pure raster: no network, no clock, no random number; temp files are never used (PNG is encoded
in memory). Same inputs, config, template set, font bytes and library version give identical PNG
bytes (NFR-1). Caches are per instance and keyed with the org (blueprint 19.1 layer 4).
"""

import hashlib
import io
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

from agent_11_thumbnail_design.errors import ComposeFailedError, GlyphMissingError, TextDoesNotFitError
from agent_11_thumbnail_design.measure import contrast_ratio, fit_text
from agent_11_thumbnail_design.revision import canonical_json
from agent_11_thumbnail_design.templates import GlyphSpec, TemplateSpec
from agent_11_thumbnail_design.textutil import contains_sequence, folded_words, words

RGB = tuple[int, int, int]
_IGNORED = frozenset({0x200C, 0x200D, 0x200B, 0x20, 0xA0})


def hex_to_rgb(value: str) -> RGB:
    v = value.lstrip("#")
    return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))


@dataclass(frozen=True, slots=True)
class RenderSpec:
    org_id: str
    canvas_w: int
    canvas_h: int
    template: TemplateSpec
    colours: dict[str, str]
    lines: tuple[str, ...]
    emphasis: str
    accent_role: str
    key_terms: tuple[str, ...]
    picture_kind: str
    glyph: GlyphSpec | None
    image_bytes: bytes | None
    image_sha256: str | None
    font_bytes: bytes
    font_sha256: str
    min_font_px: int
    max_font_px: int
    font_step_px: int
    font_cap_px: int | None = None
    """Repair: an upper bound below ``max_font_px`` (font size step down)."""

    def description(self) -> bytes:
        return canonical_json(
            {
                "canvas": [self.canvas_w, self.canvas_h],
                "template": [self.template.template_key, self.template.version],
                "colours": self.colours,
                "lines": list(self.lines),
                "emphasis": self.emphasis,
                "accent": self.accent_role,
                "key_terms": list(self.key_terms),
                "picture": [self.picture_kind, self.glyph.key if self.glyph else None, self.image_sha256],
                "font": self.font_sha256,
                "fit": [self.min_font_px, self.max_font_px, self.font_step_px, self.font_cap_px],
            }
        )


@dataclass(frozen=True, slots=True)
class TextRun:
    text: str
    bbox: tuple[int, int, int, int]
    font_px: int
    fg: RGB
    bg: RGB
    contrast: float


@dataclass(frozen=True, slots=True)
class RenderResult:
    png: bytes
    width: int
    height: int
    runs: tuple[TextRun, ...]
    lines: tuple[str, ...]
    font_px: int
    phash: str
    composition_sha256: str
    text_box_px: tuple[int, int, int, int]
    missing_glyphs: tuple[str, ...] = field(default=())


class ImageComposer(Protocol):
    def render(self, spec: RenderSpec) -> RenderResult: ...
    def missing_glyphs(self, org_id: str, font_bytes: bytes, text: str) -> tuple[str, ...]: ...


class _Metrics:
    def __init__(self, font_at: "FontProvider") -> None:
        self._font_at = font_at

    def text_width(self, line: str, font_px: int) -> float:
        return float(self._font_at(font_px).getlength(line))

    def line_height(self, font_px: int) -> float:
        ascent, descent = self._font_at(font_px).getmetrics()
        return float(ascent + descent)


class FontProvider(Protocol):
    def __call__(self, px: int) -> ImageFont.FreeTypeFont: ...


def phash64(img: Image.Image) -> str:
    """Average hash over an 8x8 grey thumbnail (box filter): 64 bits as 16 hex digits."""
    grey = img.convert("L").resize((8, 8), Image.Resampling.BOX)
    px = list(grey.get_flattened_data())
    mean = sum(px) / 64
    bits = 0
    for v in px:
        bits = (bits << 1) | (1 if v >= mean else 0)
    return f"{bits:016x}"


class PillowComposer:
    def __init__(self) -> None:
        self._fonts: dict[str, ImageFont.FreeTypeFont] = {}
        self._cmaps: dict[str, frozenset[int]] = {}

    # --- fonts ---------------------------------------------------------------------------
    def _font(self, org_id: str, sha: str, data: bytes, px: int) -> ImageFont.FreeTypeFont:
        key = f"amw:{org_id}:a11:{sha}:{px}"
        if key not in self._fonts:
            try:
                self._fonts[key] = ImageFont.truetype(
                    io.BytesIO(data), px, layout_engine=ImageFont.Layout.RAQM
                )
            except OSError as exc:
                raise ComposeFailedError("font could not be loaded") from exc
        return self._fonts[key]

    def missing_glyphs(self, org_id: str, font_bytes: bytes, text: str) -> tuple[str, ...]:
        sha = hashlib.sha256(font_bytes).hexdigest()
        key = f"amw:{org_id}:a11cmap:{sha}"
        if key not in self._cmaps:
            cmap = TTFont(io.BytesIO(font_bytes), lazy=True).getBestCmap() or {}
            self._cmaps[key] = frozenset(cmap)
        cmap_set = self._cmaps[key]
        return tuple(sorted({ch for ch in text if ord(ch) not in cmap_set and ord(ch) not in _IGNORED}))

    def raqm_available(self) -> bool:
        from PIL import features

        return bool(features.check("raqm"))

    # --- render --------------------------------------------------------------------------
    def render(self, spec: RenderSpec) -> RenderResult:
        if not self.raqm_available():
            raise ComposeFailedError("the Raqm layout engine is not available")
        text_all = " ".join(spec.lines)
        missing = self.missing_glyphs(spec.org_id, spec.font_bytes, text_all)
        if missing:
            raise GlyphMissingError("glyphs missing: " + "".join(missing))
        w, h = spec.canvas_w, spec.canvas_h
        bg = hex_to_rgb(spec.colours["background"])
        img = Image.new("RGB", (w, h), bg)
        draw = ImageDraw.Draw(img)
        t = spec.template
        if t.band:
            draw.rectangle(_px(t.band, w, h), fill=bg)
        self._subject(img, draw, spec)
        if t.band:
            draw.rectangle(_px(t.band, w, h), fill=bg)
        runs, lines, font_px, box = self._text(img, draw, spec)
        out = io.BytesIO()
        img.save(out, "PNG", optimize=False, compress_level=6)
        return RenderResult(
            png=out.getvalue(),
            width=w,
            height=h,
            runs=tuple(runs),
            lines=tuple(lines),
            font_px=font_px,
            phash=phash64(img),
            composition_sha256=hashlib.sha256(spec.description()).hexdigest(),
            text_box_px=box,
            missing_glyphs=missing,
        )

    def _subject(self, img: Image.Image, draw: ImageDraw.ImageDraw, spec: RenderSpec) -> None:
        w, h = spec.canvas_w, spec.canvas_h
        x0, y0, x1, y1 = _px(spec.template.subject_box, w, h)
        if spec.picture_kind == "OWNER_IMAGE" and spec.image_bytes is not None:
            try:
                src = Image.open(io.BytesIO(spec.image_bytes)).convert("RGB")
            except OSError as exc:
                raise ComposeFailedError("owner image could not be decoded") from exc
            bw, bh = x1 - x0, y1 - y0
            scale = max(bw / src.width, bh / src.height)
            size = (max(bw, round(src.width * scale)), max(bh, round(src.height * scale)))
            src = src.resize(size, Image.Resampling.LANCZOS)
            left, top = (size[0] - bw) // 2, (size[1] - bh) // 2
            img.paste(src.crop((left, top, left + bw, top + bh)), (x0, y0))
        elif spec.picture_kind == "CODE_GLYPH" and spec.glyph is not None:
            side = min(x1 - x0, y1 - y0)
            ox, oy = x0 + (x1 - x0 - side) // 2, y0 + (y1 - y0 - side) // 2
            lw = max(2, side // 60)
            for op in spec.glyph.ops:
                fill = hex_to_rgb(spec.colours[op["fill"]]) if op.get("fill") else None
                line = hex_to_rgb(spec.colours[op["outline"]]) if op.get("outline") else None
                if op["op"] == "rect":
                    bx, by, bw, bh = op["box"]
                    draw.rectangle(
                        (ox + bx * side // 1000, oy + by * side // 1000,
                         ox + (bx + bw) * side // 1000, oy + (by + bh) * side // 1000),
                        fill=fill, outline=line, width=lw)
                elif op["op"] == "polygon":
                    pts = [(ox + px * side // 1000, oy + py * side // 1000) for px, py in op["points"]]
                    draw.polygon(pts, fill=fill, outline=line)

    def _text(
        self, img: Image.Image, draw: ImageDraw.ImageDraw, spec: RenderSpec
    ) -> tuple[list[TextRun], list[str], int, tuple[int, int, int, int]]:
        w, h = spec.canvas_w, spec.canvas_h
        bx0, by0, bx1, by1 = _px(spec.template.text_box, w, h)

        def font_at(px: int) -> ImageFont.FreeTypeFont:
            return self._font(spec.org_id, spec.font_sha256, spec.font_bytes, px)

        metrics = _Metrics(font_at)
        max_px = min(spec.max_font_px, spec.font_cap_px or spec.max_font_px)
        lines = list(spec.lines)
        fit = _try_fit(lines, spec.template.text_lines_max, bx1 - bx0, by1 - by0, metrics, spec, max_px)
        if fit is None and len(lines) == 1 and spec.template.text_lines_max >= 2:
            for split in _balanced_splits(lines[0]):
                fit = _try_fit(split, spec.template.text_lines_max, bx1 - bx0, by1 - by0, metrics, spec, max_px)
                if fit is not None:
                    lines = split
                    break
        if fit is None:
            raise TextDoesNotFitError("text does not fit the template box")
        font_px = fit
        font = font_at(font_px)
        lh = metrics.line_height(font_px)
        total_h = lh * len(lines)
        y = by0 + (by1 - by0 - total_h) / 2
        text_c = hex_to_rgb(spec.colours["text"])
        accent_c = hex_to_rgb(spec.colours[spec.accent_role.lower()])
        runs: list[TextRun] = []
        terms = [folded_words(k) for k in spec.key_terms]
        draw_ops: list[tuple[float, float, str, RGB]] = []
        for li, line in enumerate(lines):
            width = font.getlength(line)
            x = bx0 + ((bx1 - bx0 - width) / 2 if spec.template.align == "center" else 0)
            consumed = ""
            for seg, colour in _segments(line, li, len(lines), spec.emphasis, terms, text_c, accent_c):
                sx = x + font.getlength(consumed)
                bbox = (int(sx), int(y), int(sx + font.getlength(seg)) + 1, int(y + lh) + 1)
                runs.append(_make_run(img, seg, bbox, font_px, colour))
                consumed += seg
                draw_ops.append((sx, y, seg, colour))
            y += lh
        for sx, sy, seg, colour in draw_ops:
            draw.text((sx, sy), seg, font=font, fill=colour)
        return runs, lines, font_px, (bx0, by0, bx1, by1)


def _px(box: tuple[int, int, int, int], w: int, h: int) -> tuple[int, int, int, int]:
    x, y, bw, bh = box
    return (x * w // 1000, y * h // 1000, (x + bw) * w // 1000, (y + bh) * h // 1000)


def _try_fit(lines: Sequence[str], lines_max: int, bw: float, bh: float, metrics: _Metrics, spec: RenderSpec, max_px: int) -> int | None:
    try:
        return fit_text(lines, lines_max, bw, bh, metrics, max_px, spec.min_font_px, spec.font_step_px).font_px
    except TextDoesNotFitError:
        return None


def _balanced_splits(line: str) -> list[list[str]]:
    ws = words(line)
    if len(ws) < 2:
        return []
    cuts = sorted(range(1, len(ws)), key=lambda i: (abs(len(" ".join(ws[:i])) - len(" ".join(ws[i:]))), i))
    return [[" ".join(ws[:i]), " ".join(ws[i:])] for i in cuts]


def _segments(
    line: str, li: int, n_lines: int, emphasis: str, terms: list[list[str]], text_c: RGB, accent_c: RGB
) -> list[tuple[str, RGB]]:
    if emphasis == "TWO_TONE" and n_lines == 2:
        return [(line, accent_c if li == 1 else text_c)]
    if emphasis != "TERM_HIGHLIGHT" or not terms:
        return [(line, text_c)]
    ws = line.split(" ")
    flags = [False] * len(ws)
    folded = [folded_words(x) or [""] for x in ws]
    flat = [f[0] for f in folded]
    for term in terms:
        n = len(term)
        for i in range(len(flat) - n + 1):
            if n and flat[i : i + n] == term:
                for j in range(i, i + n):
                    flags[j] = True
    segs: list[tuple[str, RGB]] = []
    i = 0
    while i < len(ws):
        j = i
        while j < len(ws) and flags[j] == flags[i]:
            j += 1
        text = " ".join(ws[i:j])
        segs.append((text + (" " if j < len(ws) else ""), accent_c if flags[i] else text_c))
        i = j
    return [(s.rstrip() if k == len(segs) - 1 else s, c) for k, (s, c) in enumerate(segs)]


def _make_run(img: Image.Image, seg: str, bbox: tuple[int, int, int, int], font_px: int, fg: RGB) -> TextRun:
    box = (max(0, bbox[0]), max(0, bbox[1]), min(img.width, max(bbox[0] + 1, bbox[2])), min(img.height, max(bbox[1] + 1, bbox[3])))
    region = img.crop(box).resize((1, 1), Image.Resampling.BOX)
    px = region.getpixel((0, 0))
    bg = (int(px[0]), int(px[1]), int(px[2])) if isinstance(px, tuple) else (int(px), int(px), int(px))
    return TextRun(seg.strip(), bbox, font_px, fg, bg, contrast_ratio(fg, bg))


__all__ = ["ImageComposer", "PillowComposer", "RenderResult", "RenderSpec", "contains_sequence", "hex_to_rgb"]
