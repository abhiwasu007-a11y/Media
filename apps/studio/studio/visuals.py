"""Stages 08/09/11: code-made visuals (kinetic Mukta text, simple diagrams) and the thumbnail.

Fonts: Mukta (SIL OFL 1.1), copied from the agent_11 pinned font data.
"""

import math
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = Path(__file__).parent / "fonts"
W, H, FPS = 1920, 1080, 30
BG = (16, 21, 31)
BG2 = (28, 36, 52)
INK = (245, 239, 230)
DIM = (150, 156, 170)
ACC = (242, 165, 65)  # saffron
RED = (224, 82, 82)
GRN = (110, 196, 140)
COLS = {"दिला": (120, 170, 235), "गेला": RED, "जगलो": GRN}


@lru_cache(maxsize=64)
def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    f = FONTS / ("Mukta-Bold.ttf" if bold else "Mukta-Regular.ttf")
    return ImageFont.truetype(str(f), size, layout_engine=ImageFont.Layout.RAQM)


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
    return img


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
    rows = s.get("visual_params", {}).get("rows") or [["दिला", ""], ["गेला", ""], ["जगलो", ""]]
    x0, y0, x1 = 160, 210, 1120
    d.rounded_rectangle([x0 - 30, y0 - 110, x1 + 30, y0 + 3 * 190 + 40], 24, fill=(238, 228, 205))
    d.text(((x0 + x1) / 2, y0 - 55), "वेळेचा हिशोब", font=font(64), fill=(70, 50, 30), anchor="mm")
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
    q = "“" + p.get("quote", "life, if you know how to use it, is long.") + "”"
    a = ease(t / 0.8)
    d.text((W / 2, 300), q, font=fit(q, W - 260, 92, False), fill=mix(BG, INK, a), anchor="mm")
    m = p.get("meaning", "")
    a2 = ease((t - 1.2) / 0.7)
    d.text((W / 2, 470), m, font=fit(m, W - 260, 80), fill=mix(BG, ACC, a2), anchor="mm")
    cr = "— Seneca, On the Shortness of Life, Ch. 2 · tr. John W. Basore (1932), public domain"
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


def frame(s, t, dur):
    img = background().copy()
    d = ImageDraw.Draw(img)
    DRAW.get(s["visual"], v_kinetic)(d, s, t, dur, img)
    fade = min(1.0, t / 0.25, (dur - t) / 0.25)
    if fade < 1:
        img = Image.blend(Image.new("RGB", (W, H), BG), img, max(0.0, fade))
    return img


def thumbnail(script, out: Path):
    tt = script["thumbnail_text"]
    img = background().resize((W, H)).copy()
    d = ImageDraw.Draw(img)
    clock(d, 1500, 600, 0, False)
    d.text((110, 380), tt["line1"], font=fit(tt["line1"], 1150, 190), fill=INK, anchor="lm")
    d.text((110, 640), tt["line2"], font=fit(tt["line2"], 1150, 200), fill=ACC, anchor="lm")
    if tt.get("line3"):
        d.text((110, 900), tt["line3"], font=font(72, False), fill=DIM, anchor="lm")
    img.resize((1280, 720), Image.LANCZOS).save(out, optimize=True)


def render_visuals(job: Path, script: dict, timings: dict, out: Path) -> int:
    """Render the silent 1080p30 visuals track for ``timings`` into ``out``; returns frames written."""
    by = {s["id"]: s for s in script["scenes"]}
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
        f"{W}x{H}",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "12",
        "-pix_fmt",
        "yuv420p",
        str(out),
    ]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert p.stdin is not None
    fi = 0
    for row in timings["scenes"]:
        s, dur, start = by[row["id"]], row["dur"], round(row["start"] * FPS)
        end = round((row["start"] + dur) * FPS)
        while fi < end:
            t = (fi - start) / FPS
            p.stdin.write(frame(s, max(0.0, min(dur, t)), dur).tobytes())
            fi += 1
    while fi < round(timings["total"] * FPS):
        p.stdin.write(background().tobytes())
        fi += 1
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg failed while encoding visuals")
    return fi
