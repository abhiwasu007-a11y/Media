"""Supported video languages: name for prompts, on-screen font, and a speaking-rate estimate for timing without a voice.

Fonts: Mukta (bundled, SIL OFL) covers Devanagari and Latin. Other scripts use the Noto families installed in the
image from the Debian packages fonts-noto-core and fonts-noto-cjk (SIL OFL). A missing font falls back to Mukta and
the job notes it (glyphs would show as boxes, so QC must catch that before any publish).
"""

from pathlib import Path

NOTO = Path("/usr/share/fonts/truetype/noto")
NOTO_CJK = Path("/usr/share/fonts/opentype/noto")
BUNDLED = Path(__file__).parent / "fonts"

# code: (English name, native name, font file stem or path, words per second ESTIMATE, right-to-left)
LANGS: dict[str, tuple[str, str, str, float, bool]] = {
    "mr": ("Marathi", "मराठी", "mukta", 2.45, False),
    "hi": ("Hindi", "हिन्दी", "mukta", 2.6, False),
    "en": ("English", "English", "mukta", 2.5, False),
    "gu": ("Gujarati", "ગુજરાતી", "NotoSansGujarati", 2.4, False),
    "bn": ("Bengali", "বাংলা", "NotoSansBengali", 2.4, False),
    "pa": ("Punjabi", "ਪੰਜਾਬੀ", "NotoSansGurmukhi", 2.5, False),
    "ta": ("Tamil", "தமிழ்", "NotoSansTamil", 2.0, False),
    "te": ("Telugu", "తెలుగు", "NotoSansTelugu", 2.1, False),
    "kn": ("Kannada", "ಕನ್ನಡ", "NotoSansKannada", 2.1, False),
    "ml": ("Malayalam", "മലയാളം", "NotoSansMalayalam", 1.9, False),
    "ur": ("Urdu", "اردو", "NotoNaskhArabic", 2.5, True),
    "es": ("Spanish", "Español", "mukta", 2.7, False),
    "fr": ("French", "Français", "mukta", 2.6, False),
    "de": ("German", "Deutsch", "mukta", 2.3, False),
    "pt": ("Portuguese", "Português", "mukta", 2.6, False),
    "it": ("Italian", "Italiano", "mukta", 2.6, False),
    "id": ("Indonesian", "Bahasa Indonesia", "mukta", 2.5, False),
    "ru": ("Russian", "Русский", "NotoSans", 2.3, False),
    "ar": ("Arabic", "العربية", "NotoNaskhArabic", 2.2, True),
    "ja": ("Japanese", "日本語", "cjk", 4.5, False),  # rate in characters per second (no spaces)
    "ko": ("Korean", "한국어", "cjk", 2.4, False),
    "zh": ("Chinese (Simplified)", "简体中文", "cjk", 4.0, False),  # characters per second
}
CHAR_BASED = {"ja", "zh"}  # no word spaces: timing counts characters


def info(code: str) -> tuple[str, str, str, float, bool]:
    return LANGS.get(code, LANGS["mr"])


def font_path(code: str, bold: bool) -> Path:
    stem = info(code)[2]
    if stem == "mukta":
        return BUNDLED / ("Mukta-Bold.ttf" if bold else "Mukta-Regular.ttf")
    if stem == "cjk":
        f = NOTO_CJK / ("NotoSansCJK-Bold.ttc" if bold else "NotoSansCJK-Regular.ttc")
    else:
        f = NOTO / f"{stem}-{'Bold' if bold else 'Regular'}.ttf"
    return f if f.exists() else BUNDLED / ("Mukta-Bold.ttf" if bold else "Mukta-Regular.ttf")


def units(code: str, text: str) -> int:
    """Words (or characters for ja/zh) for the timing estimate."""
    return len(text.replace(" ", "")) if code in CHAR_BASED else len(text.split())


def font_ok(code: str) -> bool:
    """False when the language's own font is missing and Mukta would be used (wrong glyphs for that script)."""
    stem = info(code)[2]
    return stem == "mukta" or font_path(code, True).name != "Mukta-Bold.ttf"
