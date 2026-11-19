"""Print the rendering environment and the agent_11 canary hashes of THIS host (read-only).

Run it from a repo checkout, exactly like this (needs uv; it fetches Python 3.14 itself):

    uv sync --frozen --all-packages && uv run --frozen python scripts/probe_render_env.py

Part 1 needs only Pillow. Part 2 renders the canary fixtures of ``agent_11_thumbnail_design.canary``
and therefore needs the workspace environment (fontTools, pydantic, amw_core). The exit code is
non-zero if either part fails. Output carries no secrets and no absolute paths (home and checkout
are shown as ``~`` and ``<repo>``). No network, no files written. Send the whole output.
"""

import hashlib
import io
import locale
import os
import platform
import sys
import zlib
from pathlib import Path


def _redact(text: str) -> str:
    repo = str(Path(__file__).resolve().parents[1])
    home = str(Path.home())
    return text.replace(repo, "<repo>").replace(home, "~")


def _os_release() -> str:
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8")
    except OSError:
        return "unknown"
    pairs = dict(
        line.split("=", 1) for line in text.splitlines() if "=" in line and not line.startswith("#")
    )
    return pairs.get("PRETTY_NAME", "unknown").strip('"')


def _mapped_libs() -> list[str]:
    """Shared libraries actually loaded in this process that matter for rendering and PNG."""
    wanted = ("libz", "libfribidi", "libraqm", "libharfbuzz", "libfreetype", "libpng")
    seen: set[str] = set()
    try:
        for line in Path("/proc/self/maps").read_text(encoding="utf-8").splitlines():
            path = line.split()[-1] if len(line.split()) >= 6 else ""
            if any(w in os.path.basename(path) for w in wanted):
                seen.add(path)
    except OSError:
        pass
    return sorted(seen)


def part1() -> None:
    import PIL
    from PIL import features

    print("python", sys.version.replace("\n", " "))
    print("platform", platform.platform(), "machine", platform.machine())
    print("os", _os_release())
    print(
        "locale",
        locale.getlocale(),
        "LANG",
        os.environ.get("LANG"),
        "LC_ALL",
        os.environ.get("LC_ALL"),
    )
    print("pillow", PIL.__version__, "file", _redact(str(Path(PIL.__file__).parent)))
    for name in ("freetype2", "raqm", "harfbuzz", "fribidi", "zlib", "libjpeg_turbo", "littlecms2"):
        try:
            ok = features.check(name)
            print("feature", name, features.version(name) if ok else "absent")
        except Exception as exc:
            print("feature", name, "error", type(exc).__name__)
    print("python zlib compile", zlib.ZLIB_VERSION, "runtime", zlib.ZLIB_RUNTIME_VERSION)
    print("zlib-ng in PIL.features.pilinfo:", "zlib-ng" in _pilinfo())
    for lib in _mapped_libs():
        print("loaded", _redact(lib))


def _pilinfo() -> str:
    from PIL import features

    buf = io.StringIO()
    features.pilinfo(out=buf, supported_formats=False)
    return buf.getvalue()


def part2() -> None:
    sys.path.insert(
        0,
        str(Path(__file__).resolve().parents[1] / "packages/agents/agent_11_thumbnail_design/src"),
    )
    from PIL import Image, features

    from agent_11_thumbnail_design.canary import CANARY_FONTS, canary_spec
    from agent_11_thumbnail_design.composer import PillowComposer
    from agent_11_thumbnail_design.pinning import recorded_canary

    freetype = str(features.version("freetype2"))
    for key in CANARY_FONTS:
        spec = canary_spec(key)
        res = PillowComposer().render(spec)
        img = Image.open(io.BytesIO(res.png))
        img.load()
        print("canary", key)
        print("  font_sha256       ", spec.font_sha256)
        print("  pixel_sha256      ", res.pixel_sha256)
        print("  png_sha256        ", hashlib.sha256(res.png).hexdigest(), "bytes", len(res.png))
        print("  recorded for FT", freetype, recorded_canary(freetype, key))
        print("  matches_recorded  ", res.pixel_sha256 == recorded_canary(freetype, key))


def main() -> int:
    print(
        "probe: run via `uv run --frozen python scripts/probe_render_env.py` "
        "after `uv sync --frozen --all-packages`"
    )
    failed = False
    try:
        part1()
    except Exception as exc:
        print("part1 FAILED:", type(exc).__name__, exc)
        failed = True
    try:
        part2()
    except Exception as exc:
        print(
            "part2 FAILED:",
            type(exc).__name__,
            exc,
            "(run it with the workspace environment, see the header)",
        )
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
