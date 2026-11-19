"""Composer (F-13, F-14; blueprint 4.3, 9, 20): Pillow with the Raqm layout engine (HarfBuzz).

Pure raster: no network, no clock, no random number; temp files are never used (PNG is encoded
in memory). Same inputs, config, template set, pinned font bytes and a pinned rendering environment
give an identical raster (``pixel_sha256``) on any host and identical PNG bytes on one host (NFR-1;
see ``pinning``). Caches are per instance and keyed with the org (blueprint 19.1 layer 4).
"""

import hashlib
import io
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from PIL import Image, ImageDraw, ImageFont

from agent_11_thumbnail_design.errors import (
    ComposeFailedError,
    FontIntegrityError,
    GlyphMissingError,
    TextDoesNotFitError,
)
from agent_11_thumbnail_design.measure import contrast_ratio, fit_text
from agent_11_thumbnail_design.pinning import (
    pixel_sha256,
    verify_font,
)
from agent_11_thumbnail_design.revision import canonical_json
from agent_11_thumbnail_design.templates import GlyphSpec, TemplateSpec
from agent_11_thumbnail_design.textutil import contains_sequence, folded_words, words
from amw_core.font_coverage import (
    IGNORED_CODE_POINTS,
    fallback_code_points,
    read_cmap,
    uncovered_code_points,
)

RGB = tuple[int, int, int]
_IGNORED = IGNORED_CODE_POINTS


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
    fallback_font_bytes: bytes | None = None
    """Per-glyph fallback font (a manifest font): used only for code points the primary lacks."""
    fallback_font_sha256: str | None = None
    fallback_weight: int | None = None
    """``wght`` set on a variable fallback font, so Bold text gets Bold fallback glyphs."""

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
                "picture": [
                    self.picture_kind,
                    self.glyph.key if self.glyph else None,
                    self.image_sha256,
                ],
                "font": self.font_sha256,
                **(
                    {"font_fallback": [self.fallback_font_sha256, self.fallback_weight]}
                    if self.fallback_font_sha256
                    else {}
                ),
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
    pixel_sha256: str
    """Host-independent identity of the raster (decoded RGB); ``png`` bytes depend on host zlib."""
    width: int
    height: int
    runs: tuple[TextRun, ...]
    lines: tuple[str, ...]
    font_px: int
    phash: str
    composition_sha256: str
    text_box_px: tuple[int, int, int, int]
    missing_glyphs: tuple[str, ...] = field(default=())
    fallback_used: bool = False
    """True when at least one glyph of the text was drawn by the fallback font."""


class ImageComposer(Protocol):
    def render(self, spec: RenderSpec) -> RenderResult: ...
    def missing_glyphs(
        self,
        org_id: str,
        font_bytes: bytes,
        text: str,
        font_sha256: str | None = None,
        fallback_font_bytes: bytes | None = None,
        fallback_font_sha256: str | None = None,
    ) -> tuple[str, ...]: ...
    def raqm_available(self) -> bool: ...


class _Metrics:
    def __init__(self, font_at: FontProvider, width_of: WidthProvider | None = None) -> None:
        self._font_at = font_at
        self._width_of = width_of

    def text_width(self, line: str, font_px: int) -> float:
        if self._width_of is not None:
            return self._width_of(line, font_px)
        return float(self._font_at(font_px).getlength(line))

    def line_height(self, font_px: int) -> float:
        ascent, descent = self._font_at(font_px).getmetrics()
        return float(ascent + descent)


class FontProvider(Protocol):
    def __call__(self, px: int) -> ImageFont.FreeTypeFont: ...


class WidthProvider(Protocol):
    def __call__(self, text: str, px: int) -> float: ...


def _set_weight(font: ImageFont.FreeTypeFont, weight: int) -> None:
    """Set the ``wght`` axis of a variable font (other axes keep their default)."""
    try:
        axes = font.get_variation_axes()
    except OSError:  # not a variable font: the static file is used as it is
        return
    values: list[float] = []
    for axis in axes:
        raw_name: object = axis["name"]
        name = raw_name.decode("latin-1") if isinstance(raw_name, bytes) else str(raw_name)
        lo, hi, default = (float(axis[k] or 0) for k in ("minimum", "maximum", "default"))
        values.append(min(max(float(weight), lo), hi) if name.lower() == "weight" else default)
    font.set_variation_by_axes(values)


def font_pieces(
    text: str, primary: frozenset[int], fallback: frozenset[int] | None
) -> list[tuple[str, bool]]:
    """Split text into runs, each drawn with one font: ``(run, use_fallback)``.

    A character goes to the fallback font only when the primary lacks it and the fallback has it.
    Spaces and joiners (``_IGNORED``) stay with the run they follow, so a conjunct is not broken
    by them. Without a fallback the text is one primary run (the pre-fallback behaviour).
    """
    if fallback is None or not text:
        return [(text, False)] if text else []
    out: list[tuple[str, bool]] = []
    for ch in text:
        cp = ord(ch)
        use_fb = cp not in primary and cp in fallback and cp not in _IGNORED
        if out and (out[-1][1] == use_fb or cp in _IGNORED):
            out[-1] = (out[-1][0] + ch, out[-1][1])
        else:
            out.append((ch, use_fb))
    return out


def phash64(img: Image.Image) -> str:
    """Average hash over an 8x8 grey thumbnail (box filter): 64 bits as 16 hex digits."""
    grey = img.convert("L").resize((8, 8), Image.Resampling.BOX)
    px = list(grey.tobytes())
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
    def _font(
        self, org_id: str, sha: str, data: bytes, px: int, weight: int | None = None
    ) -> ImageFont.FreeTypeFont:
        key = f"amw:{org_id}:a11:{sha}:{px}:{weight}"
        if key not in self._fonts:
            try:
                # Always from memory (verified bytes): never a name or path, so no system font
                # lookup or fallback can happen.
                font = ImageFont.truetype(io.BytesIO(data), px, layout_engine=ImageFont.Layout.RAQM)
                if weight is not None:
                    _set_weight(font, weight)
                self._fonts[key] = font
            except OSError as exc:
                raise ComposeFailedError("font could not be loaded") from exc
        return self._fonts[key]

    def _cmap(self, org_id: str, font_bytes: bytes) -> frozenset[int]:
        sha = hashlib.sha256(font_bytes).hexdigest()
        key = f"amw:{org_id}:a11cmap:{sha}"
        if key not in self._cmaps:
            self._cmaps[key] = read_cmap(font_bytes)
        return self._cmaps[key]

    def missing_glyphs(
        self,
        org_id: str,
        font_bytes: bytes,
        text: str,
        font_sha256: str | None = None,
        fallback_font_bytes: bytes | None = None,
        fallback_font_sha256: str | None = None,
    ) -> tuple[str, ...]:
        """Characters no font of the set covers (cmap lookup; the fallback is checked per glyph)."""
        if font_sha256 is not None:
            verify_font(font_bytes, font_sha256)  # FontIntegrityError on a mismatch
        cmaps = [self._cmap(org_id, font_bytes)]
        if fallback_font_bytes is not None:
            if fallback_font_sha256 is not None:
                verify_font(fallback_font_bytes, fallback_font_sha256)
            cmaps.append(self._cmap(org_id, fallback_font_bytes))
        return tuple(sorted(chr(cp) for cp in uncovered_code_points([text], cmaps)))

    def raqm_available(self) -> bool:
        from PIL import features

        return bool(features.check("raqm"))

    # --- render --------------------------------------------------------------------------
    def render(self, spec: RenderSpec) -> RenderResult:
        if not self.raqm_available():
            raise ComposeFailedError("the Raqm layout engine is not available")
        verify_font(spec.font_bytes, spec.font_sha256)  # FontIntegrityError: bytes != recorded hash
        if spec.fallback_font_bytes is not None:
            verify_font(spec.fallback_font_bytes, spec.fallback_font_sha256 or "")
        text_all = " ".join(spec.lines)
        missing = self.missing_glyphs(
            spec.org_id, spec.font_bytes, text_all, None, spec.fallback_font_bytes
        )
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
            pixel_sha256=pixel_sha256(img.mode, img.size, img.tobytes()),
            width=w,
            height=h,
            runs=tuple(runs),
            lines=tuple(lines),
            font_px=font_px,
            phash=phash64(img),
            composition_sha256=hashlib.sha256(spec.description()).hexdigest(),
            text_box_px=box,
            missing_glyphs=missing,
            fallback_used=bool(
                spec.fallback_font_bytes is not None
                and fallback_code_points(
                    spec.lines,
                    self._cmap(spec.org_id, spec.font_bytes),
                    self._cmap(spec.org_id, spec.fallback_font_bytes),
                )
            ),
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
                        (
                            ox + bx * side // 1000,
                            oy + by * side // 1000,
                            ox + (bx + bw) * side // 1000,
                            oy + (by + bh) * side // 1000,
                        ),
                        fill=fill,
                        outline=line,
                        width=lw,
                    )
                elif op["op"] == "polygon":
                    pts = [
                        (ox + px * side // 1000, oy + py * side // 1000) for px, py in op["points"]
                    ]
                    draw.polygon(pts, fill=fill, outline=line)

    def _text(
        self, img: Image.Image, draw: ImageDraw.ImageDraw, spec: RenderSpec
    ) -> tuple[list[TextRun], list[str], int, tuple[int, int, int, int]]:
        w, h = spec.canvas_w, spec.canvas_h
        bx0, by0, bx1, by1 = _px(spec.template.text_box, w, h)

        def font_at(px: int) -> ImageFont.FreeTypeFont:
            return self._font(spec.org_id, spec.font_sha256, spec.font_bytes, px)

        fb_bytes = spec.fallback_font_bytes
        primary_cmap = self._cmap(spec.org_id, spec.font_bytes)
        fb_cmap = self._cmap(spec.org_id, fb_bytes) if fb_bytes is not None else None
        fb_sha = hashlib.sha256(fb_bytes).hexdigest() if fb_bytes is not None else ""

        def fb_at(px: int) -> ImageFont.FreeTypeFont:
            if fb_bytes is None:
                raise ComposeFailedError("no fallback font is set")
            return self._font(spec.org_id, fb_sha, fb_bytes, px, spec.fallback_weight)

        def pieces(text: str) -> list[tuple[str, bool]]:
            return font_pieces(text, primary_cmap, fb_cmap)

        def width_of(text: str, px: int) -> float:
            return sum(
                float((fb_at(px) if use_fb else font_at(px)).getlength(piece))
                for piece, use_fb in pieces(text)
            )

        metrics = _Metrics(font_at, width_of)
        max_px = min(spec.max_font_px, spec.font_cap_px or spec.max_font_px)
        lines = list(spec.lines)
        fit = _try_fit(
            lines, spec.template.text_lines_max, bx1 - bx0, by1 - by0, metrics, spec, max_px
        )
        if fit is None and len(lines) == 1 and spec.template.text_lines_max >= 2:
            for split in _balanced_splits(lines[0]):
                fit = _try_fit(
                    split, spec.template.text_lines_max, bx1 - bx0, by1 - by0, metrics, spec, max_px
                )
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
        ascent = font.getmetrics()[0]
        for li, line in enumerate(lines):
            width = width_of(line, font_px)
            x = bx0 + ((bx1 - bx0 - width) / 2 if spec.template.align == "center" else 0)
            consumed = ""
            for seg, colour in _segments(
                line, li, len(lines), spec.emphasis, terms, text_c, accent_c
            ):
                sx = x + width_of(consumed, font_px)
                bbox = (int(sx), int(y), int(sx + width_of(seg, font_px)) + 1, int(y + lh) + 1)
                runs.append(_make_run(img, seg, bbox, font_px, colour))
                consumed += seg
                draw_ops.append((sx, y, seg, colour))
            y += lh
        for sx, sy, seg, colour in draw_ops:
            parts = pieces(seg)
            if all(not use_fb for _, use_fb in parts):
                draw.text((sx, sy), seg, font=font, fill=colour)
                continue
            # Mixed fonts on one segment: every run sits on the primary font's baseline.
            pen = sx
            for piece, use_fb in parts:
                f = fb_at(font_px) if use_fb else font
                draw.text((pen, sy + ascent), piece, font=f, fill=colour, anchor="ls")
                pen += float(f.getlength(piece))
        return runs, lines, font_px, (bx0, by0, bx1, by1)


def _px(box: tuple[int, int, int, int], w: int, h: int) -> tuple[int, int, int, int]:
    x, y, bw, bh = box
    return (x * w // 1000, y * h // 1000, (x + bw) * w // 1000, (y + bh) * h // 1000)


def _try_fit(
    lines: Sequence[str],
    lines_max: int,
    bw: float,
    bh: float,
    metrics: _Metrics,
    spec: RenderSpec,
    max_px: int,
) -> int | None:
    try:
        return fit_text(
            lines, lines_max, bw, bh, metrics, max_px, spec.min_font_px, spec.font_step_px
        ).font_px
    except TextDoesNotFitError:
        return None


def _balanced_splits(line: str) -> list[list[str]]:
    ws = words(line)
    if len(ws) < 2:
        return []
    cuts = sorted(
        range(1, len(ws)), key=lambda i: (abs(len(" ".join(ws[:i])) - len(" ".join(ws[i:]))), i)
    )
    return [[" ".join(ws[:i]), " ".join(ws[i:])] for i in cuts]


def _segments(
    line: str,
    li: int,
    n_lines: int,
    emphasis: str,
    terms: list[list[str]],
    text_c: RGB,
    accent_c: RGB,
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


def _make_run(
    img: Image.Image, seg: str, bbox: tuple[int, int, int, int], font_px: int, fg: RGB
) -> TextRun:
    box = (
        max(0, bbox[0]),
        max(0, bbox[1]),
        min(img.width, max(bbox[0] + 1, bbox[2])),
        min(img.height, max(bbox[1] + 1, bbox[3])),
    )
    region = img.crop(box).resize((1, 1), Image.Resampling.BOX)
    raw = region.tobytes()
    bg = (raw[0], raw[1], raw[2])
    return TextRun(seg.strip(), bbox, font_px, fg, bg, contrast_ratio(fg, bg))


__all__ = [
    "FontIntegrityError",
    "ImageComposer",
    "PillowComposer",
    "RenderResult",
    "RenderSpec",
    "contains_sequence",
    "hex_to_rgb",
]
