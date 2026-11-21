"""Stages 08/09/11: code-made visuals (kinetic Mukta text, simple diagrams) and the thumbnail.

Fonts: Mukta (SIL OFL 1.1), copied from the agent_11 pinned font data.
"""

import contextlib
import json
import math
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = Path(__file__).parent / "fonts"
W, H, FPS = 1920, 1080, 30  # design canvas of the code-made scenes
OW, OH = W, H  # output canvas: 1920x1080 (long) or 1080x1920 (Shorts), see set_output()


def set_output(vertical: bool) -> None:
    global OW, OH
    OW, OH = (1080, 1920) if vertical else (W, H)


BG = (16, 21, 31)
BG2 = (28, 36, 52)
INK = (245, 239, 230)
DIM = (150, 156, 170)
ACC = (242, 165, 65)  # saffron
RED = (224, 82, 82)
GRN = (110, 196, 140)
COLS = {"दिला": (120, 170, 235), "गेला": RED, "जगलो": GRN}


LANG = "mr"


def set_language(code: str) -> None:
    global LANG
    if code != LANG:
        LANG = code
        font.cache_clear()


@lru_cache(maxsize=128)
def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    from .languages import font_path  # noqa: PLC0415

    return ImageFont.truetype(str(font_path(LANG, bold)), size, layout_engine=ImageFont.Layout.RAQM)


def ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def mix(c1, c2, a):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * a) for i in range(3))


@lru_cache(maxsize=1)
def background() -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for y in range(H):  # soft vertical gradient
        d.line([(0, y), (W, y)], fill=mix(BG, BG2, (y / H) ** 1.5))
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([W * 0.55, -H * 0.3, W * 1.3, H * 0.6], fill=60)
    glow = glow.filter(ImageFilter.GaussianBlur(180))
    img.paste(Image.new("RGB", (W, H), (60, 48, 30)), (0, 0), glow)
    img.paste(Image.new("RGB", (W, H), (0, 0, 0)), (0, 0), vignette((W, H)))
    return img


@lru_cache(maxsize=4)
def vignette(size: tuple[int, int] = (W, H)) -> Image.Image:
    w, h = size
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).ellipse([-w * 0.15, -h * 0.25, w * 1.15, h * 1.25], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(160))
    return m.point(lambda v: int((255 - v) * 0.55))


@lru_cache(maxsize=4)
def bottom_shade(size: tuple[int, int] = (W, H)) -> Image.Image:
    """Mask that darkens the lower part of a picture so captions stay readable."""
    w, h = size
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    for y in range(h):
        a = max(0.0, (y / h - 0.45) / 0.55)
        d.line([(0, y), (w, y)], fill=int(215 * a**1.4))
    return m.point(lambda v: max(v, 40))


PARTICLES = [((i * 7919) % W, (i * 104729) % H, 1 + (i % 3), 6 + (i * 13) % 14) for i in range(26)]


def particles(d, t):
    for x0, y0, r, sp in PARTICLES:
        x = (x0 + t * sp * 0.6) % W
        y = (y0 - t * sp) % H
        d.ellipse([x - r, y - r, x + r, y + r], fill=(70, 72, 84))


def fit(text: str, max_w: int, size: int, bold=True) -> ImageFont.FreeTypeFont:
    while size > 28:
        f = font(size, bold)
        if f.getlength(text) <= max_w:
            return f
        size -= 4
    return font(size, bold)


def text_c(d, xy, text, f, fill, anchor="mm", alpha=1.0, bg=None):
    col = mix(bg or BG, fill, alpha) if alpha < 1 else fill
    d.text(xy, text, font=f, fill=col, anchor=anchor)


def wrap(text: str, f, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if f.getlength(t) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# ---------------------------------------------------------------- beat panel (shared)
def beats_panel(d, beats, t, dur, x0, x1, y_mid, big=96):
    """Beats appear one by one (every dur/len seconds); current one bright, older ones dimmed."""
    n = max(1, len(beats))
    seg = dur / n
    k = min(n - 1, int(t / seg))
    shown = beats[: k + 1]
    gap = big * 1.45
    y = y_mid - gap * (len(shown) - 1) / 2
    for i, b in enumerate(shown):
        a = ease((t - i * seg) / 0.45)
        cur = i == k
        f = fit(b, x1 - x0, big if cur else int(big * 0.72))
        dy = (1 - a) * 30
        col = INK if cur else DIM
        d.text(((x0 + x1) / 2, y + i * gap + dy), b, font=f, fill=mix(BG, col, a), anchor="mm")
    return k


# ---------------------------------------------------------------- visuals
def v_kinetic(d, s, t, dur, img):
    beats_panel(d, s["beats"], t, dur, 160, W - 160, H / 2, big=120)
    w = (W - 600) * ease(t / dur)
    d.rounded_rectangle([300, H - 150, 300 + max(8, w), H - 142], 4, fill=ACC)


def v_title(d, s, t, dur, img):
    beats = s["beats"]
    for i, b in enumerate(beats):
        a = ease((t - i * 0.7) / 0.6)
        f = fit(b, W - 300, 150 if i == 0 else 70, bold=i == 0)
        y = H / 2 - 120 + (0 if i == 0 else 90 + i * 85)
        d.text((W / 2, y + (1 - a) * 25), b, font=f, fill=mix(BG, ACC if i == 0 else INK, a), anchor="mm")
    fn = s.get("visual_params", {}).get("footnote")
    if fn and t > 1.5:
        d.text((W / 2, H - 80), fn, font=fit(fn, W - 200, 34, False), fill=DIM, anchor="mm")


def v_question(d, s, t, dur, img):
    a = ease(t / 0.8)
    r = 230 + 10 * math.sin(t * 2)
    cx, cy = 470, H / 2
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=mix(BG, ACC, a), width=8)
    d.text((cx, cy - 20), "?", font=font(340), fill=mix(BG, ACC, a), anchor="mm")
    beats_panel(d, s["beats"], t, dur, 840, W - 100, H / 2, big=100)


def phone(d, x, y, w, h):
    d.rounded_rectangle([x, y, x + w, y + h], 48, outline=INK, width=6, fill=(22, 28, 40))
    d.rounded_rectangle([x + w / 2 - 50, y + 22, x + w / 2 + 50, y + 34], 6, fill=DIM)


def v_phone(d, s, t, dur, img):
    px, py, pw, ph = 230, 140, 440, 820
    phone(d, px, py, pw, ph)
    n = int(t * 2.2) + 1
    for i in range(min(n, 9)):
        a = ease((t - i / 2.2) / 0.3)
        yy = py + 80 + i * 78
        d.rounded_rectangle([px + 28, yy, px + pw - 28, yy + 62], 14, fill=mix((22, 28, 40), (52, 62, 84), a))
        d.ellipse([px + 44, yy + 16, px + 74, yy + 46], fill=mix((22, 28, 40), ACC if i % 3 == 0 else (120, 170, 235), a))
        d.rounded_rectangle([px + 90, yy + 18, px + pw - 60 - (i * 37 % 90), yy + 30], 5, fill=mix((22, 28, 40), DIM, a))
        d.rounded_rectangle(
            [px + 90, yy + 38, px + pw - 140 - (i * 53 % 60), yy + 46], 4, fill=mix((22, 28, 40), (90, 96, 110), a)
        )
    target = 112 if "११२" in "".join(s["beats"]) else 9
    cnt = max(1, min(target, int(target * ease(t / max(dur, 1)))))
    d.ellipse([px + pw - 70, py - 30, px + pw + 30, py + 70], fill=RED)
    d.text((px + pw - 20, py + 20), str(cnt), font=font(44), fill=INK, anchor="mm")
    beats_panel(d, s["beats"], t, dur, 800, W - 120, H / 2, big=96)


def person(d, cx, cy, sc, col):
    d.ellipse([cx - 55 * sc, cy - 230 * sc, cx + 55 * sc, cy - 120 * sc], fill=col)
    d.rounded_rectangle([cx - 95 * sc, cy - 105 * sc, cx + 95 * sc, cy + 170 * sc], int(70 * sc), fill=col)


def v_person(d, s, t, dur, img):
    sway = math.sin(t * 1.3) * 6
    person(d, 480 + sway, 640, 1.6, (70, 80, 102))
    d.ellipse([300, 900, 660, 940], fill=(12, 16, 24))
    if any(w in "".join(s["beats"]) for w in ("आई", "मुलगी", "तिचे", "रांग", "याल")):
        person(d, 720 - sway, 700, 1.05, (96, 84, 70))
    beats_panel(d, s["beats"], t, dur, 860, W - 120, H / 2, big=96)


def v_ledger(d, s, t, dur, img):
    # Marathi labels are fallbacks for the sample job only; scripts should supply rows / title in visual_params.
    vp = s.get("visual_params", {})
    rows = vp.get("rows") or [["दिला", ""], ["गेला", ""], ["जगलो", ""]]
    x0, y0, x1 = 160, 210, 1120
    d.rounded_rectangle([x0 - 30, y0 - 110, x1 + 30, y0 + 3 * 190 + 40], 24, fill=(238, 228, 205))
    d.text(((x0 + x1) / 2, y0 - 55), vp.get("title") or "वेळेचा हिशोब", font=font(64), fill=(70, 50, 30), anchor="mm")
    for i, (name, val) in enumerate(rows[:3]):
        a = ease((t - i * 0.6) / 0.5)
        y = y0 + 20 + i * 190
        d.line([x0, y - 10, x1, y - 10], fill=(200, 185, 160), width=3)
        col = COLS.get(name, ACC)
        d.rounded_rectangle([x0, y + 20, x0 + 240, y + 140], 18, fill=mix((238, 228, 205), col, a))
        d.text((x0 + 120, y + 80), name, font=font(64), fill=mix((238, 228, 205), (20, 20, 20), a), anchor="mm")
        if val:
            f = fit(val, x1 - x0 - 300, 52, False)
            d.text((x0 + 290, y + 80), val, font=f, fill=mix((238, 228, 205), (50, 40, 30), a), anchor="lm")
    beats_panel(d, s["beats"], t, dur, 1200, W - 80, H / 2, big=80)


def clock(d, cx, cy, t, running):
    d.rounded_rectangle([cx - 170, cy - 380, cx + 170, cy + 380], 40, fill=(74, 52, 36), outline=(120, 90, 60), width=6)
    d.ellipse([cx - 140, cy - 350, cx + 140, cy - 70], fill=(238, 228, 205))
    for k in range(12):
        ang = k * math.pi / 6
        d.line(
            [cx + 115 * math.sin(ang), cy - 210 - 115 * math.cos(ang), cx + 128 * math.sin(ang), cy - 210 - 128 * math.cos(ang)],
            fill=(60, 40, 30),
            width=5,
        )
    mang = (t * 0.6 if running else 0.0) + 1.2
    hang = mang / 12 + 4.1
    for ang, ln, wd in ((hang, 70, 9), (mang, 105, 6)):
        d.line([cx, cy - 210, cx + ln * math.sin(ang), cy - 210 - ln * math.cos(ang)], fill=(30, 20, 15), width=wd)
    sw = 0.35 * math.sin(t * math.pi) if running else 0.0
    px, py = cx + 230 * math.sin(sw), cy - 30 + 230 * math.cos(sw)
    d.line([cx, cy - 30, px, py], fill=(200, 160, 80), width=6)
    d.ellipse([px - 38, py - 38, px + 38, py + 38], fill=(220, 175, 90))


def v_clock(d, s, t, dur, img, running=False):
    clock(d, 520, 560, t, running)
    beats_panel(d, s["beats"], t, dur, 900, W - 120, H / 2, big=100)


def v_crossed(d, s, t, dur, img):
    word = s.get("visual_params", {}).get("word", "नंतर")
    f = font(260)
    cx, cy = 620, 520
    d.text((cx, cy), word, font=f, fill=INK, anchor="mm")
    a = ease((t - 0.8) / 0.7)
    wl = f.getlength(word) / 2 + 40
    if a > 0:
        d.line([cx - wl, cy + 60, cx - wl + 2 * wl * a, cy - 60], fill=RED, width=22)
    beats_panel(d, s["beats"], t, dur, 1100, W - 80, H / 2, big=84)


def v_timeline(d, s, t, dur, img):
    parts = s.get("visual_params", {}).get("parts") or ["गेलेला", "चालू", "येणारा"]
    y = 420
    spans = [(140, 900, ACC, False), (930, 1010, GRN, False), (1040, 1780, DIM, True)]
    for i, ((x0, x1, col, dashed), name) in enumerate(zip(spans, parts, strict=False)):
        a = ease((t - i * 0.6) / 0.6)
        xe = x0 + (x1 - x0) * a
        if dashed:
            x = x0
            while x < xe:
                d.rounded_rectangle([x, y - 20, min(x + 50, xe), y + 20], 10, outline=col, width=4)
                x += 80
        else:
            d.rounded_rectangle([x0, y - 30, max(x0 + 2, xe), y + 30], 18, fill=col)
        d.text(((x0 + x1) / 2, y - 90), name, font=font(64), fill=mix(BG, col if col != DIM else INK, a), anchor="mm")
    beats_panel(d, s["beats"], t, dur, 160, W - 160, 760, big=84)


def v_quote(d, s, t, dur, img):
    p = s.get("visual_params", {})
    q = "“" + (p.get("quote") or "life, if you know how to use it, is long.") + "”"
    a = ease(t / 0.8)
    d.text((W / 2, 300), q, font=fit(q, W - 260, 92, False), fill=mix(BG, INK, a), anchor="mm")
    m = p.get("meaning", "")
    a2 = ease((t - 1.2) / 0.7)
    d.text((W / 2, 470), m, font=fit(m, W - 260, 80), fill=mix(BG, ACC, a2), anchor="mm")
    cr = p.get("credit") or p.get("quote_credit") or ""
    if cr and not cr.startswith("—"):
        cr = "— " + cr
    if cr:
        d.text((W / 2, 600), cr, font=fit(cr, W - 300, 40, False), fill=mix(BG, DIM, a2), anchor="mm")
    beats_panel(d, s["beats"], t, dur, 160, W - 160, 830, big=72)


def v_check(d, s, t, dur, img):
    p = s.get("visual_params", {})
    items = p.get("items") or s["beats"]
    n = len(items)
    seg = max(0.8, (dur - 1) / max(1, n))
    for i, it in enumerate(items):
        a = ease((t - i * seg) / 0.5)
        y = 300 + i * 160 - (n - 3) * 50
        d.rounded_rectangle([170, y - 45, 260, y + 45], 18, outline=mix(BG, ACC, a), width=6)
        if a > 0.6:
            if p.get("strike_all"):
                d.line([180, y - 35, 250, y + 35], fill=RED, width=10)
                d.line([250, y - 35, 180, y + 35], fill=RED, width=10)
            else:
                d.line([188, y, 210, y + 26, 250, y - 30], fill=GRN, width=12, joint="curve")
        d.text((300, y), it, font=fit(it, 780, 70), fill=mix(BG, INK, a), anchor="lm")
    beats_panel(d, s["beats"], t, dur, 1140, W - 80, H / 2, big=76)
    if p.get("footer"):
        d.text((W - 80, H - 70), p["footer"], font=font(36, False), fill=DIM, anchor="rm")


def v_bar(d, s, t, dur, img):
    hrs = s.get("visual_params", {}).get("hours")
    x0, y0, bw, bh = 220, 260, 140, 600
    for i in range(7):
        val = (hrs or 4.5) * (0.85 + 0.3 * ((i * 37) % 10) / 10)
        a = ease((t - i * 0.15) / 0.8)
        h = bh * min(1, val / 9) * a
        xx = x0 + i * (bw + 30)
        d.rounded_rectangle([xx, y0 + bh - h, xx + bw * 0.8, y0 + bh], 12, fill=ACC if i == 6 else (90, 110, 150))
    lab = f"{hrs} तास / दिवस" if hrs else s.get("visual_params", {}).get("label", "?")
    if hrs:
        lab = lab.replace(str(hrs), "०१२३४५६७८९"[int(hrs)] if isinstance(hrs, int) and hrs < 10 else str(hrs))
    d.text((x0 + 3.5 * (bw + 30), y0 - 70), lab, font=font(64), fill=INK, anchor="mm")
    beats_panel(d, s["beats"], t, dur, 1420, W - 60, H / 2, big=70)


DRAW = {
    "kinetic_text": v_kinetic,
    "title_card": v_title,
    "question_card": v_question,
    "phone_notifications": v_phone,
    "silhouette_person": v_person,
    "ledger_table": v_ledger,
    "clock_stopped": lambda *a: v_clock(*a, running=False),
    "clock_running": lambda *a: v_clock(*a, running=True),
    "crossed_word": v_crossed,
    "timeline_three_parts": v_timeline,
    "quote_card": v_quote,
    "checklist": v_check,
    "screen_time_bar": v_bar,
}


class Media:
    """A picture or a stock clip behind one scene: Ken Burns on stills, frames streamed from ffmpeg for video."""

    def __init__(self, job: Path, asset: dict, dur: float, idx: int):
        self.kind, self.idx, self.dur = asset["kind"], idx, dur
        self.w, self.h = OW, OH
        self.proc = None
        if self.kind == "image":
            im = Image.open(job / asset["file"]).convert("RGB")
            sc = max(self.w * 1.14 / im.width, self.h * 1.14 / im.height)
            self.img = im.resize((int(im.width * sc), int(im.height * sc)), Image.LANCZOS)
            self.depth = None
            dfile = (job / asset["file"]).with_name((job / asset["file"]).stem + "_depth.png")
            if dfile.exists():  # 2.5D parallax: near pixels move more than far ones
                import cv2  # noqa: PLC0415 - optional speed path
                import numpy as np  # noqa: PLC0415

                self.cv2, self.np = cv2, np
                self.arr = np.asarray(self.img)
                d = np.asarray(Image.open(dfile).convert("L").resize(self.img.size, Image.BILINEAR), np.float32) / 255.0
                self.depth = cv2.GaussianBlur(d, (0, 0), 6)
        else:
            vf = f"scale={self.w}:{self.h}:force_original_aspect_ratio=increase,crop={self.w}:{self.h},fps={FPS},eq=saturation=0.85"
            self.proc = subprocess.Popen(
                [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-stream_loop",
                    "-1",
                    "-i",
                    str(job / asset["file"]),
                    "-t",
                    f"{dur + 1:.2f}",
                    "-vf",
                    vf,
                    "-an",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "-",
                ],
                stdout=subprocess.PIPE,
            )
            self.last = Image.new("RGB", (self.w, self.h), BG)

    def frame(self, t: float) -> Image.Image:
        if self.kind == "image" and self.depth is not None:
            return self._parallax(t)
        if self.kind == "image":
            p = min(1.0, max(0.0, t / max(self.dur, 0.1)))
            q = p if self.idx % 2 == 0 else 1 - p  # alternate zoom in / zoom out
            base = min(self.img.width, self.img.height * self.w / self.h)
            cw = base / (1 + 0.12 * q)
            ch = cw * self.h / self.w
            px = 0.35 + 0.3 * (p if self.idx % 3 else 1 - p)
            dx, dy = (self.img.width - cw) * px, (self.img.height - ch) * 0.5
            return self.img.resize((self.w, self.h), Image.BILINEAR, box=(dx, dy, dx + cw, dy + ch))
        raw = self.proc.stdout.read(self.w * self.h * 3) if self.proc else b""
        if len(raw) == self.w * self.h * 3:
            self.last = Image.frombytes("RGB", (self.w, self.h), raw)
        return self.last

    def _parallax(self, t: float) -> Image.Image:
        np, cv2 = self.np, self.cv2
        p = min(1.0, max(0.0, t / max(self.dur, 0.1)))
        e = p * p * (3 - 2 * p)  # smoothstep camera move
        sgn = 1 if self.idx % 2 == 0 else -1
        zoom = 1.0 + 0.07 * e
        ih, iw = self.depth.shape
        base = min(iw, ih * self.w / self.h) / zoom
        sx = base / self.w
        cx = iw / 2 + sgn * (e - 0.5) * iw * 0.03
        cy = ih / 2
        if not hasattr(self, "_grid"):
            self._grid = np.meshgrid(
                np.arange(self.w, dtype=np.float32) - self.w / 2, np.arange(self.h, dtype=np.float32) - self.h / 2
            )
        gx, gy = self._grid
        mx = cx + gx * sx
        my = cy + gy * sx
        dep = cv2.remap(self.depth, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        shift = sgn * (e - 0.5) * 46.0  # pixels of parallax between near and far
        mx = mx - (dep - 0.5) * shift * sx
        my = my - (dep - 0.5) * abs(shift) * 0.25 * sx
        out = cv2.remap(self.arr, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        return Image.fromarray(out)

    def close(self) -> None:
        if self.proc:
            self.proc.kill()
            self.proc.wait()


def media_caption(d, s, t, dur):
    """Current beat in a rounded dialogue box (reference style), one beat at a time."""
    beats = s["beats"] or [""]
    seg = dur / len(beats)
    k = min(len(beats) - 1, int(t / seg))
    a = ease((t - k * seg) / 0.35)
    b = beats[k]
    ow, oh = d.im.size
    f = fit(b, ow - (420 if ow > oh else 140), 78 if ow > oh else 70)
    w = f.getlength(b)
    y = oh - (150 if ow > oh else 520) + (1 - a) * 20
    box = [ow / 2 - w / 2 - 34, y - 58, ow / 2 + w / 2 + 34, y + 50]
    d.rounded_rectangle(box, 26, fill=mix((0, 0, 0), (14, 40, 92), a), outline=mix((0, 0, 0), (255, 212, 0), a), width=4)
    d.text((ow / 2, y - 2), b, font=f, fill=mix((14, 40, 92), (255, 236, 120), a), anchor="mm")


def frame_media(s, t, dur, media, media_t):
    img = media.frame(media_t)
    img = Image.composite(Image.new("RGB", img.size, (0, 0, 0)), img, bottom_shade(img.size))
    media_caption(ImageDraw.Draw(img), s, t, dur)
    return film_look(img, t)


def frame(s, t, dur, media=None):
    if media is not None:
        img = media.frame(t)
        img = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, bottom_shade())
        d = ImageDraw.Draw(img)
        media_caption(d, s, t, dur)
    else:
        img = background().copy()
        d = ImageDraw.Draw(img)
        particles(d, t)
        DRAW.get(s["visual"], v_kinetic)(d, s, t, dur, img)
    if media is not None:
        img = film_look(img, t)
    return to_output(img)


def to_output(card: Image.Image) -> Image.Image:
    """Place a 16:9 code-made card on the output canvas (Shorts: blurred fill behind, card in the middle)."""
    if card.size == (OW, OH):
        return card
    sc = max(OW / card.width, OH / card.height)
    bg = card.resize((int(card.width * sc / 4), int(card.height * sc / 4)), Image.BILINEAR).filter(ImageFilter.GaussianBlur(6))
    bg = bg.resize((int(card.width * sc), int(card.height * sc)), Image.BILINEAR)
    bg = bg.crop(((bg.width - OW) // 2, (bg.height - OH) // 2, (bg.width - OW) // 2 + OW, (bg.height - OH) // 2 + OH))
    bg = Image.blend(Image.new("RGB", (OW, OH), (0, 0, 0)), bg, 0.55)
    fg = card.resize((OW, int(card.height * OW / card.width)), Image.LANCZOS)
    bg.paste(fg, (0, (OH - fg.height) // 2))
    return bg


@lru_cache(maxsize=1)
def _grade_lut():
    """Cinematic grade: slightly lifted teal shadows, warm highlights, gentle S-curve."""
    lut = []
    for ch in range(3):
        for v in range(256):
            x = v / 255
            x = 0.75 * x + 0.25 * x * x * (3 - 2 * x)  # soft S-curve
            if ch == 0:
                x = x + 0.05 * x**2
            elif ch == 2:
                x = x + 0.06 * (1 - x) ** 2 - 0.03 * x**2
            lut.append(max(0, min(255, int(x * 255))))
    return lut


@lru_cache(maxsize=16)
def _grain(k: int, size: tuple[int, int] = (W, H)) -> Image.Image:
    import random  # noqa: PLC0415

    rnd = random.Random(k)  # noqa: S311 - visual noise, not security
    g = Image.effect_noise((size[0] // 2, size[1] // 2), 22 + rnd.random() * 4).resize(size, Image.BILINEAR)
    return g


def film_look(img: Image.Image, t: float) -> Image.Image:
    img = img.point(_grade_lut())
    size = img.size
    img = Image.blend(img, Image.merge("RGB", [_grain(int(t * FPS) % 8, size)] * 3), 0.045)
    img.paste(Image.new("RGB", size, (0, 0, 0)), (0, 0), vignette(size))
    return img


def thumbnail(script, out: Path, hero: Path | None = None):
    """Bold YouTube-style thumbnail: AI hero picture when present, big outlined text on the left."""
    tt = script["thumbnail_text"]
    if hero and hero.exists():
        im = Image.open(hero).convert("RGB")
        sc = max(W / im.width, H / im.height)
        im = im.resize((int(im.width * sc), int(im.height * sc)), Image.LANCZOS)
        img = im.crop(((im.width - W) // 2, (im.height - H) // 2, (im.width - W) // 2 + W, (im.height - H) // 2 + H))
        shade = Image.linear_gradient("L").rotate(-90).resize((W, H)).point(lambda v: int(v * 0.75))
        img = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, shade)
    else:
        img = background().copy()
        clock(ImageDraw.Draw(img), 1500, 600, 0, False)
    d = ImageDraw.Draw(img)
    yellow = (255, 212, 0)
    f1, f2 = fit(tt["line1"], 1050, 200), fit(tt["line2"], 1050, 220)
    d.text((90, 380), tt["line1"], font=f1, fill=(255, 255, 255), anchor="lm", stroke_width=14, stroke_fill=(0, 0, 0))
    d.text((90, 650), tt["line2"], font=f2, fill=yellow, anchor="lm", stroke_width=16, stroke_fill=(0, 0, 0))
    img.resize((1280, 720), Image.LANCZOS).save(out, optimize=True)


DELIVERY_VIDEO = [
    "-c:v",
    "libx264",
    "-profile:v",
    "high",
    "-preset",
    "medium",
    "-b:v",
    "8M",
    "-maxrate",
    "12M",
    "-bufsize",
    "16M",
    "-pix_fmt",
    "yuv420p",
    "-r",
    "30",
    "-fps_mode",
    "cfr",
    "-g",
    "15",
    "-bf",
    "2",
]


def render_visuals(job: Path, script: dict, timings: dict, out: Path) -> int:
    """Render the silent 1080p30 visuals track for ``timings`` into ``out``; returns frames written."""
    by = {s["id"]: s for s in script["scenes"]}
    af = job / "assets.json"
    assets = json.loads(af.read_text()) if af.exists() else {}
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{OW}x{OH}",
        "-r",
        str(FPS),
        "-i",
        "-",
        # encoded once at the delivery settings (H.264 High, 8 Mbps VBR target, D10); stage 10 copies this stream
        *DELIVERY_VIDEO,
        str(out),
    ]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert p.stdin is not None
    ok = False
    try:
        fi = 0
        prev = None  # last frame of the previous scene, dissolved into the new one
        xf = round(0.4 * FPS)
        for row in timings["scenes"]:
            s, dur, start = by[row["id"]], row["dur"], round(row["start"] * FPS)
            end = round((row["start"] + dur) * FPS)
            a = assets.get(row["id"])
            idx = int(row["id"][1:]) if row["id"][1:].isdigit() else 0
            files = [f for f in (a.get("files") or [a["file"]]) if (job / f).exists()] if a else []
            # one segment per shot: the picture changes every few seconds inside a scene
            n = max(1, len(files))
            segs = [(start + round((end - start) * j / n), start + round((end - start) * (j + 1) / n), j) for j in range(n)]
            last = prev
            for s0, s1, j in segs:
                seg_dur = max(0.1, (s1 - s0) / FPS)
                kind = "video" if files and files[j].endswith(".mp4") else "image"
                media = Media(job, {**a, "file": files[j], "kind": kind}, seg_dur, idx * 3 + j) if files else None
                try:
                    while fi < s1:
                        t = (fi - start) / FPS
                        if media is not None:
                            media_t = (fi - s0) / FPS
                            img = frame_media(s, max(0.0, min(dur, t)), dur, media, media_t)
                        else:
                            img = frame(s, max(0.0, min(dur, t)), dur, None)
                        k = fi - s0
                        if prev is not None and k < xf:
                            img = Image.blend(prev, img, (k + 1) / (xf + 1))
                        elif prev is None and k < xf:  # fade in from black at the very start
                            img = Image.blend(Image.new("RGB", (OW, OH), (0, 0, 0)), img, (k + 1) / (xf + 1))
                        p.stdin.write(img.tobytes())
                        last = img
                        fi += 1
                finally:
                    if media:
                        media.close()
                prev = last
        while fi < round(timings["total"] * FPS):
            p.stdin.write(to_output(background()).tobytes())
            fi += 1
        p.stdin.close()
        if p.wait() != 0:
            raise RuntimeError("ffmpeg failed while encoding visuals")
        ok = True
        return fi
    finally:
        if not ok:
            with contextlib.suppress(Exception):
                p.stdin.close()
            if p.poll() is None:
                p.kill()
            with contextlib.suppress(Exception):
                p.wait(timeout=10)
            out.unlink(missing_ok=True)
