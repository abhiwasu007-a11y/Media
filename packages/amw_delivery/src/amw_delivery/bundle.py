"""Delivery bundle builder (3A-14; 3A slice spec section 4; capability ``file_delivery``).

``build_bundle`` collects the artefacts of one job BY REFERENCE from blob storage (streamed,
SHA-256 verified, tenant checked), writes the reports and the manifest, and zips the folder. It
fails closed: any missing artefact, hash mismatch, ungated compliance, cross-tenant reference or
oversized file raises a typed error and leaves no partial bundle and no zip behind.

Files written (names fixed): ``video_16x9.mp4``, ``video_9x16.mp4`` (when shorts are wanted),
``thumbnails/<option>.<ext>``, ``subtitles.srt`` (primary language) and ``subtitles.<lang>.srt``
(the other languages), ``qc_report.json``/``.md``, ``cost_per_stage.json``/``.csv``, ``README.txt``
and ``manifest.json`` (SHA-256 of every other file; its own SHA-256 is returned).
"""

import hashlib
import json
import re
import shutil
import zipfile
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path

from amw_core.contracts.common import storage_uri_owner
from amw_core.enums import ComplianceVerdict
from amw_core.errors import (
    CorruptedOutputError,
    CrossTenantRefError,
    InputInvalidError,
    MissingDependencyError,
    NotAuthorisedError,
    TenantMismatchError,
)
from amw_core.interfaces.storage import BlobStorage, BlobUri
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.observability.redaction import Redactor
from amw_delivery.models import (
    ArtefactRef,
    BundleInputs,
    BundleManifest,
    ManifestFile,
)
from amw_delivery.reports import cost_csv, cost_json, qc_report_json, qc_report_md, summarise_score

_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_VERSION_LIKE = re.compile(r"^(?:0|1)\.\d+\.\d+\.\d+$")
_CHUNK = 1024 * 1024


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_text_clean(name: str, text: str) -> None:
    """No keys, URL credentials or server addresses in any text file of the bundle."""
    if Redactor().text(text) != text:
        raise InputInvalidError("a secret-like value is in a bundle file", details={"file": name})
    for m in _IPV4.finditer(text):
        if not _VERSION_LIKE.match(m.group(0)):
            raise InputInvalidError("an IP address is in a bundle file", details={"file": name})


def _preflight(inputs: BundleInputs, context: TenantContext) -> None:
    if context.org_id != inputs.org_id:
        raise TenantMismatchError("tenant context differs from the bundle's org")
    comp = inputs.compliance
    if comp.verdict is not ComplianceVerdict.ALLOWED or not comp.authorised_for_delivery:
        raise NotAuthorisedError(
            "delivery refused: compliance is not ALLOWED and authorised for delivery",
            details={"verdict": str(comp.verdict), "authorised": comp.authorised_for_delivery},
        )
    if comp.render_sha256 != inputs.video_16x9.sha256:
        raise NotAuthorisedError("delivery refused: the authorisation names another render hash")
    missing: list[str] = []
    if inputs.shorts_wanted and inputs.video_9x16 is None:
        missing.append("video_9x16")
    if inputs.video_9x16 is not None and not inputs.shorts_wanted:
        raise InputInvalidError("a 9:16 file is given but shorts_wanted is false")
    ids = [t.option_id for t in inputs.thumbnails]
    if len(set(ids)) != len(ids):
        raise InputInvalidError("duplicate thumbnail option id")
    if inputs.chosen_thumbnail_id not in ids:
        missing.append("chosen_thumbnail")
    langs = [s.language for s in inputs.subtitles]
    if len(set(langs)) != len(langs):
        raise InputInvalidError("duplicate subtitle language")
    if inputs.primary_language not in langs:
        missing.append("primary_language_subtitles")
    if missing:
        raise MissingDependencyError(
            "required artefact missing from the bundle inputs", details={"missing": missing}
        )
    if not inputs.qc_checks or not inputs.score_rows or not inputs.gates:
        raise MissingDependencyError("QC checks, score rows and gates are required")
    summarise_score(inputs.score_rows)  # validates the machine maximum and the 100 total
    refs: list[ArtefactRef] = [inputs.video_16x9, *(t.ref for t in inputs.thumbnails)]
    refs += [s.ref for s in inputs.subtitles]
    if inputs.video_9x16 is not None:
        refs.append(inputs.video_9x16)
    for ref in refs:
        if storage_uri_owner(ref.uri) != inputs.org_id:
            raise CrossTenantRefError("artefact reference belongs to another tenant")
    lim = inputs.limits
    for ref in refs:
        if ref.size_bytes > lim.max_file_bytes:
            raise InputInvalidError("file exceeds the configured size limit", details={"uri": "?"})
    for t in inputs.thumbnails:
        if t.ref.size_bytes > lim.max_thumbnail_bytes:
            raise InputInvalidError("thumbnail exceeds the configured size limit")
    if sum(r.size_bytes for r in refs) > lim.max_total_bytes:
        raise InputInvalidError("bundle exceeds the configured total size limit")


def _stream_to(
    storage: BlobStorage,
    context: TenantContext,
    ref: ArtefactRef,
    dest: Path,
    max_bytes: int,
) -> int:
    """Copy one blob to ``dest`` chunk by chunk, verifying SHA-256 and size on the way."""
    h = hashlib.sha256()
    size = 0
    chunks: Iterator[bytes] = storage.get(context, BlobUri(ref.uri), ref.sha256)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("xb") as fh:
        for chunk in chunks:
            size += len(chunk)
            if size > max_bytes:
                raise InputInvalidError("file exceeds the configured size limit while streaming")
            h.update(chunk)
            fh.write(chunk)
    if h.hexdigest() != ref.sha256 or size != ref.size_bytes:
        raise CorruptedOutputError(
            "artefact content does not match its recorded SHA-256 / size",
            details={"name": dest.name},
        )
    return size


def _readme(inputs: BundleInputs, names: list[str]) -> str:
    lines = [
        inputs.banner,
        "",
        f"Delivery bundle for job {inputs.job_id}",
        f"Production type: {inputs.production_type_key} v{inputs.production_type_version}",
        f"Config version: {inputs.config_version}",
        "",
        "Contents:",
        *[f"  {n}" for n in names],
        "  manifest.json (SHA-256 and size of every file above)",
        "",
        "Nothing here has been uploaded anywhere. Upload by hand if you decide to publish.",
        f"Disclaimer status: {inputs.disclaimer.status_label} "
        f"(version {inputs.disclaimer.version})",
        f"Chosen thumbnail: {inputs.chosen_thumbnail_id}",
        "See qc_report.md for the compliance verdict, the score and the gates.",
        "",
    ]
    return "\n".join(lines)


def _media_type(name: str) -> str:
    return {
        "mp4": "video/mp4",
        "png": "image/png",
        "jpg": "image/jpeg",
        "webp": "image/webp",
        "srt": "application/x-subrip",
        "json": "application/json",
        "md": "text/markdown",
        "csv": "text/csv",
        "txt": "text/plain",
    }.get(name.rsplit(".", 1)[-1], "application/octet-stream")


def build_bundle(
    inputs: BundleInputs,
    out_dir: Path,
    *,
    storage: BlobStorage,
    context: TenantContext,
) -> BundleManifest:
    """Build and verify the bundle in ``out_dir`` (must be absent or empty) and zip it.

    Raises (07 codes): ``NotAuthorisedError`` (compliance / authorisation),
    ``MissingDependencyError`` (artefact absent), ``CorruptedOutputError`` (hash or size
    mismatch), ``CrossTenantRefError``, ``TenantMismatchError``, ``InputInvalidError`` (limits,
    malformed inputs, secret-like text).
    On any failure ``out_dir`` is left as it was found.
    """
    _preflight(inputs, context)
    out_dir = Path(out_dir)
    if out_dir.exists() and (not out_dir.is_dir() or any(out_dir.iterdir())):
        raise InputInvalidError("out_dir must be empty or absent")
    created_dir = not out_dir.exists()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        return _build(inputs, out_dir, storage, context)
    except BaseException:
        if created_dir:
            shutil.rmtree(out_dir, ignore_errors=True)
        else:
            for child in out_dir.iterdir():
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    with suppress(OSError):
                        child.unlink()
        raise


def _build(
    inputs: BundleInputs, out_dir: Path, storage: BlobStorage, context: TenantContext
) -> BundleManifest:
    lim = inputs.limits
    plan: list[tuple[str, ArtefactRef, int]] = [
        ("video_16x9.mp4", inputs.video_16x9, lim.max_file_bytes)
    ]
    if inputs.video_9x16 is not None:
        plan.append(("video_9x16.mp4", inputs.video_9x16, lim.max_file_bytes))
    for t in inputs.thumbnails:
        plan.append(
            (f"thumbnails/{t.option_id}.{_EXT[t.media_type]}", t.ref, lim.max_thumbnail_bytes)
        )
    for s in inputs.subtitles:
        name = (
            "subtitles.srt"
            if s.language == inputs.primary_language
            else f"subtitles.{s.language}.srt"
        )
        plan.append((name, s.ref, lim.max_file_bytes))
    total = 0
    for name, ref, cap in plan:
        total += _stream_to(storage, context, ref, out_dir / name, cap)
        if total > lim.max_total_bytes:
            raise InputInvalidError("bundle exceeds the configured total size limit")
    for name, _ref, _cap in plan:
        if name.endswith(".srt"):
            text = (out_dir / name).read_text(encoding="utf-8", errors="strict")
            if "-->" not in text:
                raise InputInvalidError("subtitle file has no cue", details={"file": name})
            _check_text_clean(name, text)
    texts: dict[str, str] = {
        "qc_report.json": qc_report_json(inputs),
        "qc_report.md": qc_report_md(inputs),
        "cost_per_stage.json": cost_json(inputs),
        "cost_per_stage.csv": cost_csv(inputs),
    }
    names = [n for n, _r, _c in plan] + list(texts) + ["README.txt"]
    texts["README.txt"] = _readme(inputs, [*names])
    for name, text in texts.items():
        _check_text_clean(name, text)
        (out_dir / name).write_text(text, encoding="utf-8")
    files: list[ManifestFile] = []
    for name in sorted([*[n for n, _r, _c in plan], *texts]):
        p = out_dir / name
        data_hash = hashlib.sha256()
        with p.open("rb") as fh:
            while chunk := fh.read(_CHUNK):
                data_hash.update(chunk)
        files.append(
            ManifestFile(
                name=name,
                sha256=data_hash.hexdigest(),
                size_bytes=p.stat().st_size,
                media_type=_media_type(name),
            )
        )
    manifest_body = {
        "schema_id": "amw.delivery_manifest",
        "schema_version": 1,
        "org_id": inputs.org_id,
        "job_id": inputs.job_id,
        "deliverable_preset": inputs.deliverable_preset,
        "production_type_key": inputs.production_type_key,
        "production_type_version": inputs.production_type_version,
        "config_version": inputs.config_version,
        "metadata_present": inputs.metadata_present,
        "banner": inputs.banner,
        "render_sha256": inputs.video_16x9.sha256,
        "chosen_thumbnail_id": inputs.chosen_thumbnail_id,
        "shorts_included": inputs.video_9x16 is not None,
        "files": [f.model_dump(mode="json") for f in files],
    }
    manifest_text = json.dumps(manifest_body, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _check_text_clean("manifest.json", manifest_text)
    (out_dir / "manifest.json").write_text(manifest_text, encoding="utf-8")
    manifest_sha = _sha(manifest_text.encode())
    zip_path = out_dir / f"bundle_{inputs.job_id}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
        for name in [f.name for f in files] + ["manifest.json"]:
            # fixed timestamp and mode: the same inputs give the same zip bytes, so a retried
            # delivery attempt finds identical bytes in the write-once store
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            with (out_dir / name).open("rb") as src, zf.open(info, "w", force_zip64=True) as dst:
                shutil.copyfileobj(src, dst, _CHUNK)
    zbuf = hashlib.sha256()
    with zip_path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            zbuf.update(chunk)
    return BundleManifest(
        org_id=inputs.org_id,
        job_id=inputs.job_id,
        deliverable_preset=inputs.deliverable_preset,
        production_type_key=inputs.production_type_key,
        production_type_version=inputs.production_type_version,
        config_version=inputs.config_version,
        metadata_present=inputs.metadata_present,
        banner=inputs.banner,
        render_sha256=inputs.video_16x9.sha256,
        chosen_thumbnail_id=inputs.chosen_thumbnail_id,
        shorts_included=inputs.video_9x16 is not None,
        files=tuple(files),
        manifest_sha256=manifest_sha,
        zip_name=zip_path.name,
        zip_sha256=zbuf.hexdigest(),
        zip_size_bytes=zip_path.stat().st_size,
    )
