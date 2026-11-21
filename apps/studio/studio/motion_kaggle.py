"""Generate short AI video clips on Kaggle's free GPU with Wan2.1-T2V-1.3B (Apache-2.0).

Flow: build a private Python *script* kernel -> push it (GPU + internet) -> poll status -> download outputs.

REST facts come from the official client code (Kaggle/kaggle-api, read 2026-11):
- src/kaggle/api/kaggle_api_extended.py: ``kernels_push`` (request fields slug / newTitle / text / language /
  kernelType / isPrivate / enableGpu / enableInternet / sessionTimeoutSeconds, language "python", kernelType "script"),
  ``kernels_status`` (GetKernelSessionStatus), ``kernels_output`` (ListKernelSessionOutput, paged, files fetched by URL).
- kagglesdk (PyPI ``kagglesdk``): ``kagglesdk/kaggle_http_client.py`` (every call is ``POST
  {base}/v1/{service}/{Method}`` with a JSON body; auth = HTTP Basic username:key; prod base https://api.kaggle.com),
  ``kagglesdk/kernels/services/kernels_api_service.py`` (service ``kernels.KernelsApiService``, methods SaveKernel,
  GetKernelSessionStatus, ListKernelSessionOutput), ``kagglesdk/kernels/types/kernels_api_service.py`` (JSON field
  names, e.g. response ``files[].url/fileName``, ``nextPageToken``, ``status``, ``failureMessage``) and
  ``kagglesdk/kernels/types/kernels_enums.py`` (KernelWorkerStatus, serialised by name).
Model usage: diffusers docs ``docs/source/en/api/pipelines/wan.md`` (WanPipeline, AutoencoderKLWan, export_to_video).
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

API_BASE = "https://api.kaggle.com"
KERNELS_SERVICE = "kernels.KernelsApiService"
MODEL_ID = "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"
WIDTH, HEIGHT = 832, 480
NUM_FRAMES = 49  # 4k+1 frames required by Wan; 49 frames at 16 fps is about 3 s
FPS = 16
POLL_S = 30
HTTP_TIMEOUT_S = 120
DONE_FILE = "done.json"
# UNVERIFIED: the GPU shape is chosen server-side from enableGpu; the default T4 x2 / P100 choice is not documented
# in the client code, so the kernel only assumes a 16 GB class card.
GPU_NOTE = "enableGpu=true only; accelerator type not selectable here"
# UNVERIFIED: that Kaggle keeps signed output URLs valid long enough and accepts no auth header on them.
OUTPUT_URL_NEEDS_AUTH = False
_TERMINAL_OK = {"COMPLETE"}
_TERMINAL_BAD = {"ERROR", "CANCEL_REQUESTED", "CANCEL_ACKNOWLEDGED"}

_KERNEL_TEMPLATE = """\
import json, os, subprocess, sys, traceback

SHOTS = json.loads(__SHOTS_JSON__)
OUT = "/kaggle/working"
RESULTS, ERRORS = {}, {}


def save():
    with open(os.path.join(OUT, "__DONE__"), "w", encoding="utf-8") as f:
        json.dump({"clips": RESULTS, "errors": ERRORS}, f)


try:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "diffusers", "transformers", "accelerate",
                    "ftfy", "imageio", "imageio-ffmpeg"], check=True)
    import torch
    from diffusers import AutoencoderKLWan, WanPipeline
    from diffusers.utils import export_to_video

    vae = AutoencoderKLWan.from_pretrained("__MODEL__", subfolder="vae", torch_dtype=torch.float32)
    pipe = WanPipeline.from_pretrained("__MODEL__", vae=vae, torch_dtype=torch.float16)
    pipe.enable_model_cpu_offload()
except Exception:
    err = traceback.format_exc()[-1500:]
    for s in SHOTS:
        ERRORS[s["id"]] = "setup failed: " + err
    save()
    raise SystemExit(0)

NEG = "blurry, low quality, distorted, watermark, text, subtitles, static, worst quality"
for s in SHOTS:
    sid = s["id"]
    try:
        frames = pipe(prompt=s["prompt"], negative_prompt=NEG, height=__H__, width=__W__, num_frames=__FRAMES__,
                      guidance_scale=5.0, num_inference_steps=30).frames[0]
        export_to_video(frames, os.path.join(OUT, sid + ".mp4"), fps=__FPS__)
        RESULTS[sid] = sid + ".mp4"
    except Exception as exc:
        ERRORS[sid] = (type(exc).__name__ + ": " + str(exc))[:500]
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass
    save()
save()
"""


def kernel_source(shots: list[dict[str, str]]) -> str:
    """Return the Python source of the Kaggle script kernel for these shots."""
    payload = [{"id": str(s["id"]), "prompt": str(s["prompt"])} for s in shots]
    shots_literal = repr(json.dumps(payload))  # a valid Python string literal containing the JSON
    return (
        _KERNEL_TEMPLATE.replace("__SHOTS_JSON__", shots_literal)
        .replace("__DONE__", DONE_FILE)
        .replace("__MODEL__", MODEL_ID)
        .replace("__H__", str(HEIGHT))
        .replace("__W__", str(WIDTH))
        .replace("__FRAMES__", str(NUM_FRAMES))
        .replace("__FPS__", str(FPS))
    )


def _auth_header(username: str, key: str) -> str:
    return "Basic " + base64.b64encode(f"{username}:{key}".encode()).decode("ascii")


def _call(username: str, key: str, method: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST one JSON RPC-style call; raise RuntimeError(status + short body) on failure. Never includes the key."""
    req = urllib.request.Request(  # noqa: S310 (fixed https base)
        f"{API_BASE}/v1/{KERNELS_SERVICE}/{method}",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": _auth_header(username, key)},
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:  # noqa: S310
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        excerpt = exc.read(300).decode("utf-8", "replace")
        raise RuntimeError(f"Kaggle {method} failed: HTTP {exc.code}: {excerpt}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Kaggle {method} unreachable: {exc.reason}") from None
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        raise RuntimeError(f"Kaggle {method}: non-JSON response: {raw[:200]!r}") from None
    if isinstance(data, dict) and isinstance(data.get("code"), int) and data["code"] >= 400:
        raise RuntimeError(f"Kaggle {method} failed: code {data['code']}: {str(data.get('message', ''))[:300]}")
    return data


def push_kernel(username: str, key: str, slug: str, title: str, source: str, timeout_s: int) -> dict[str, Any]:
    """Create/replace the private GPU script kernel and start its run."""
    body = {
        "slug": f"{username}/{slug}",
        "newTitle": title,
        "text": source,
        "language": "python",
        "kernelType": "script",
        "isPrivate": True,
        "enableGpu": True,
        "enableInternet": True,
        "sessionTimeoutSeconds": timeout_s,
    }
    data = _call(username, key, "SaveKernel", body)
    if data.get("error"):
        raise RuntimeError(f"Kaggle SaveKernel rejected the kernel: {str(data['error'])[:300]}")
    return data


def get_status(username: str, key: str, slug: str) -> tuple[str, str]:
    """Return (status name, failure message), e.g. ("RUNNING", "")."""
    data = _call(username, key, "GetKernelSessionStatus", {"userName": username, "kernelSlug": slug})
    return str(data.get("status", "QUEUED")).rsplit(".", 1)[-1].upper(), str(data.get("failureMessage", "") or "")


def wait_for_kernel(
    username: str, key: str, slug: str, timeout_s: int, log: Callable[[str], None], poll_s: int = POLL_S
) -> tuple[str, str]:
    """Poll until a terminal status or timeout. Returns (status, failure message); status "TIMEOUT" on timeout."""
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        try:
            status, msg = get_status(username, key, slug)
        except RuntimeError as exc:
            # The kernel may not be visible for a moment after the push; transient errors are retried.
            status, msg = "UNKNOWN", str(exc)
        if status != last:
            log(f"kaggle kernel {slug}: {status}")
            last = status
        if status in _TERMINAL_OK or status in _TERMINAL_BAD:
            return status, msg
        time.sleep(poll_s)
    return "TIMEOUT", f"no result after {timeout_s}s"


def list_output(username: str, key: str, slug: str) -> list[dict[str, str]]:
    """List all output files (name + download URL), following nextPageToken."""
    files: list[dict[str, str]] = []
    token = ""
    while True:
        body: dict[str, Any] = {"userName": username, "kernelSlug": slug, "pageSize": 50}
        if token:
            body["pageToken"] = token
        data = _call(username, key, "ListKernelSessionOutput", body)
        files += [{"name": f.get("fileName", ""), "url": f.get("url", "")} for f in data.get("files") or []]
        token = data.get("nextPageToken") or ""
        if not token:
            return files


def _safe_name(name: str) -> str:
    return Path(name).name if name and ".." not in Path(name).parts else ""


def download_file(url: str, dest: Path) -> None:
    """Download a signed output URL to dest (no Kaggle credentials are sent)."""
    if urlparse(url).scheme != "https":
        raise RuntimeError("refusing non-https output URL")
    try:
        with urllib.request.urlopen(url, timeout=300) as resp, dest.open("wb") as out:  # noqa: S310
            while chunk := resp.read(1 << 20):
                out.write(chunk)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"output download failed: HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"output download unreachable: {exc.reason}") from None


def download_outputs(username: str, key: str, slug: str, out_dir: Path) -> list[str]:
    """Download every output file into out_dir; return the saved base names."""
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for item in list_output(username, key, slug):
        name = _safe_name(item["name"])
        if not name or not item["url"]:
            continue
        download_file(item["url"], out_dir / name)
        saved.append(name)
    return saved


def _read_done(out_dir: Path) -> dict[str, Any]:
    try:
        data = json.loads((out_dir / DONE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def generate_clips(
    username: str,
    key: str,
    shots: list[dict],
    out_dir: Path,
    *,
    timeout_s: int = 6 * 3600,
    log: Callable[[str], None] = print,
) -> dict:
    """Run Wan2.1-1.3B on Kaggle for each shot and download the mp4 files into out_dir.

    Returns {"clips": {id: filename}, "errors": {id: msg}, "kernel": "user/slug", "status": str}.
    Raises RuntimeError on API/auth failures (the key is never included in messages or logs).
    """
    if not shots:
        return {"clips": {}, "errors": {}, "kernel": "", "status": "EMPTY"}
    slug = f"amw-wan-clips-{int(time.time())}"
    title = slug.replace("-", " ")  # slugifies back to `slug`
    log(f"kaggle: pushing kernel {username}/{slug} ({len(shots)} shots)")
    push_kernel(username, key, slug, title, kernel_source(shots), timeout_s)
    status, msg = wait_for_kernel(username, key, slug, timeout_s, log)
    errors: dict[str, str] = {}
    clips: dict[str, str] = {}
    if status == "TIMEOUT":
        errors = {str(s["id"]): msg for s in shots}
        return {"clips": clips, "errors": errors, "kernel": f"{username}/{slug}", "status": status}
    try:
        saved = set(download_outputs(username, key, slug, out_dir))
    except RuntimeError as exc:
        saved = set()
        msg = msg or str(exc)
    done = _read_done(out_dir)
    errors = {str(k): str(v) for k, v in (done.get("errors") or {}).items()}
    for s in shots:
        sid = str(s["id"])
        fname = f"{sid}.mp4"
        if fname in saved:
            clips[sid] = fname
        elif sid not in errors:
            errors[sid] = msg or f"kernel {status}: no clip produced"
    log(f"kaggle: {len(clips)} clips, {len(errors)} errors, status {status}")
    return {"clips": clips, "errors": errors, "kernel": f"{username}/{slug}", "status": status}
