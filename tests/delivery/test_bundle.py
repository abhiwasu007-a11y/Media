"""Delivery bundle: happy path from in-memory fakes and the fail-closed cases."""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from amw_core import ids
from amw_core.enums import ComplianceVerdict
from amw_core.errors import (
    CorruptedOutputError,
    CrossTenantRefError,
    InputInvalidError,
    MissingDependencyError,
    NotAuthorisedError,
    TenantMismatchError,
)
from amw_core.interfaces.tenancy_context import TenantContext
from amw_delivery.bundle import build_bundle
from amw_delivery.models import (
    BundleLimits,
    ComplianceInfo,
    DisclaimerInfo,
    ScoreRow,
)
from tests.delivery.support import BANNER, World

pytestmark = pytest.mark.integration


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_full_bundle_from_fakes(tmp_path: Path) -> None:
    w = World(tmp_path, shorts=True)
    out = tmp_path / "bundle"
    m = build_bundle(w.inputs(), out, storage=w.storage, context=w.context)
    names = {f.name for f in m.files}
    assert names == {
        "video_16x9.mp4", "video_9x16.mp4", "thumbnails/v1.png", "thumbnails/v2.png",
        "thumbnails/v3.png", "subtitles.srt", "subtitles.hi.srt", "qc_report.json",
        "qc_report.md", "cost_per_stage.json", "cost_per_stage.csv", "README.txt",
    }  # fmt: skip
    for f in m.files:
        assert _sha(out / f.name) == f.sha256
        assert (out / f.name).stat().st_size == f.size_bytes
    disk = json.loads((out / "manifest.json").read_text())
    assert {x["name"] for x in disk["files"]} == names
    assert disk["chosen_thumbnail_id"] == "v2"
    assert _sha(out / "manifest.json") == m.manifest_sha256
    assert _sha(out / m.zip_name) == m.zip_sha256
    with zipfile.ZipFile(out / m.zip_name) as zf:
        assert set(zf.namelist()) == names | {"manifest.json"}
        assert zf.testzip() is None
    assert m.shorts_included


def test_reports_content(tmp_path: Path) -> None:
    w = World(tmp_path)
    out = tmp_path / "b"
    m = build_bundle(w.inputs(), out, storage=w.storage, context=w.context)
    assert not m.shorts_included
    assert "video_9x16.mp4" not in {f.name for f in m.files}
    md = (out / "qc_report.md").read_text()
    assert md.startswith(f"# {BANNER}")
    assert "COMPLIANCE VERDICT: ALLOWED" in md
    assert "DRAFT - not lawyer-approved" in md
    assert "d-0.1" in md
    assert "general information, not investment advice" in md
    assert "| VISUAL_QUALITY | 15 | 12 | 10 | 10 |" in md
    assert "human scores needed" in md
    qc = json.loads((out / "qc_report.json").read_text())
    assert qc["score"]["machine_total"] == "21"
    assert qc["score"]["used_total"] == "19"
    assert qc["gates_failed"] == ["quality.threshold"]
    cost = json.loads((out / "cost_per_stage.json").read_text())
    assert cost["totals"]["total_micros"] == 1234
    assert cost["caps"]["pilot_remaining_micros"] == 4998766
    csv_text = (out / "cost_per_stage.csv").read_text()
    assert csv_text.startswith(f"# {BANNER}")
    assert "s05_script" in csv_text
    assert "TOTAL" in csv_text
    assert "CAP:per_video_limit_minor" in csv_text
    assert BANNER in (out / "README.txt").read_text()


def test_banner_comes_from_caller(tmp_path: Path) -> None:
    w = World(tmp_path)
    build_bundle(w.inputs(banner="REAL RUN"), tmp_path / "b", storage=w.storage, context=w.context)
    assert (tmp_path / "b" / "qc_report.md").read_text().startswith("# REAL RUN")
    assert BANNER not in (tmp_path / "b" / "README.txt").read_text()


def _fails(tmp_path: Path, w: World, exc: type[Exception], **over: object) -> None:
    out = tmp_path / "bundle"
    with pytest.raises(exc):
        build_bundle(w.inputs(**over), out, storage=w.storage, context=w.context)
    assert not out.exists()


def test_missing_artefact(tmp_path: Path) -> None:
    w = World(tmp_path)
    inputs = w.inputs()
    del w.storage.blobs[inputs.thumbnails[0].ref.uri]
    out = tmp_path / "bundle"
    with pytest.raises(MissingDependencyError):
        build_bundle(inputs, out, storage=w.storage, context=w.context)
    assert not out.exists()


def test_missing_required_inputs(tmp_path: Path) -> None:
    w = World(tmp_path)
    _fails(tmp_path, w, MissingDependencyError, shorts_wanted=True)
    _fails(tmp_path, w, MissingDependencyError, chosen_thumbnail_id="v9")
    _fails(tmp_path, w, MissingDependencyError, primary_language="fr")
    _fails(tmp_path, w, MissingDependencyError, qc_checks=())
    _fails(tmp_path, w, InputInvalidError, video_9x16=w.inputs().video_16x9)


def test_hash_mismatch(tmp_path: Path) -> None:
    w = World(tmp_path)
    inputs = w.inputs()
    uri = inputs.video_16x9.uri
    w.storage.blobs[uri] = w.storage.blobs[uri] + b"x"  # stored bytes changed after the record
    out = tmp_path / "bundle"
    with pytest.raises(CorruptedOutputError):
        build_bundle(inputs, out, storage=w.storage, context=w.context)
    assert not out.exists()


def test_size_in_ref_wrong(tmp_path: Path) -> None:
    w = World(tmp_path)
    inputs = w.inputs()
    bad = inputs.video_16x9.model_copy(update={"size_bytes": inputs.video_16x9.size_bytes - 1})
    _fails(tmp_path, w, CorruptedOutputError, video_16x9=bad,
           compliance=inputs.compliance)  # fmt: skip


@pytest.mark.parametrize(
    ("verdict", "authorised"),
    [
        (ComplianceVerdict.BLOCKED, True),
        (ComplianceVerdict.NEEDS_HUMAN_REVIEW, True),
        (ComplianceVerdict.ALLOWED, False),
    ],
)
def test_ungated_compliance(tmp_path: Path, verdict: ComplianceVerdict, authorised: bool) -> None:
    w = World(tmp_path)
    base = w.inputs().compliance
    comp = ComplianceInfo(
        verdict=verdict, authorised_for_delivery=authorised,
        authorisation_verdict_id="cvd_1", render_sha256=base.render_sha256,
    )  # fmt: skip
    _fails(tmp_path, w, NotAuthorisedError, compliance=comp)


def test_authorisation_for_another_render(tmp_path: Path) -> None:
    w = World(tmp_path)
    comp = ComplianceInfo(
        verdict=ComplianceVerdict.ALLOWED, authorised_for_delivery=True,
        authorisation_verdict_id="cvd_1", render_sha256="0" * 64,
    )  # fmt: skip
    _fails(tmp_path, w, NotAuthorisedError, compliance=comp)


def test_cross_org_reference(tmp_path: Path) -> None:
    w = World(tmp_path)
    other = ids.ORG.new()
    foreign = w.put("x.mp4", w.video, owner=other)
    comp = w.inputs().compliance.model_copy(update={"render_sha256": foreign.sha256})
    _fails(tmp_path, w, CrossTenantRefError, video_16x9=foreign, compliance=comp)


def test_cross_org_context(tmp_path: Path) -> None:
    w = World(tmp_path)
    ctx = TenantContext(ids.ORG.new(), ids.ActorRef("sys_operator"))
    with pytest.raises(TenantMismatchError):
        build_bundle(w.inputs(), tmp_path / "b", storage=w.storage, context=ctx)
    assert not (tmp_path / "b").exists()


def test_storage_blocks_foreign_blob_even_if_ref_is_forged(tmp_path: Path) -> None:
    """Second line: the storage itself refuses a URI of another tenant for this context."""
    w = World(tmp_path)
    other = TenantContext(ids.ORG.new(), ids.ActorRef("sys_operator"))
    inputs = w.inputs()
    with pytest.raises(TenantMismatchError):
        build_bundle(inputs, tmp_path / "b", storage=w.storage, context=other)
    with pytest.raises(CrossTenantRefError):
        list(w.storage.get(other, inputs.video_16x9.uri, inputs.video_16x9.sha256))  # type: ignore[arg-type]


def test_oversized_file_and_total(tmp_path: Path) -> None:
    w = World(tmp_path)
    lim = BundleLimits(max_file_bytes=1000, max_total_bytes=10**9, max_thumbnail_bytes=10**6)
    _fails(tmp_path, w, InputInvalidError, limits=lim)
    lim = BundleLimits(max_file_bytes=10**9, max_total_bytes=1000, max_thumbnail_bytes=10**6)
    _fails(tmp_path, w, InputInvalidError, limits=lim)
    lim = BundleLimits(max_file_bytes=10**9, max_total_bytes=10**9, max_thumbnail_bytes=3)
    _fails(tmp_path, w, InputInvalidError, limits=lim)


def test_oversized_while_streaming(tmp_path: Path) -> None:
    """A ref that under-declares its size cannot get around the limit."""
    w = World(tmp_path)
    inputs = w.inputs()
    lim = BundleLimits(
        max_file_bytes=len(w.video) - 10, max_total_bytes=10**9, max_thumbnail_bytes=10**6
    )
    liar = inputs.video_16x9.model_copy(update={"size_bytes": 5})
    _fails(tmp_path, w, InputInvalidError, limits=lim, video_16x9=liar)


def test_score_rules(tmp_path: Path) -> None:
    w = World(tmp_path)
    too_much = (
        ScoreRow(dimension="A", source="MACHINE", max_points=50, points=50),
        ScoreRow(dimension="B", source="MACHINE", max_points=50, points=50),
    )
    _fails(tmp_path, w, InputInvalidError, score_rows=too_much)
    dup = (
        ScoreRow(dimension="A", source="MACHINE", max_points=10, points=1),
        ScoreRow(dimension="A", source="MACHINE", max_points=10, points=2),
    )
    _fails(tmp_path, w, InputInvalidError, score_rows=dup)


def test_secret_and_address_in_text_refused(tmp_path: Path) -> None:
    w = World(tmp_path)
    bad = DisclaimerInfo(text="key sk-abcdefghijklmnopqrstuvwxyz0123", version="1",
                         status_label="DRAFT - not lawyer-approved")  # fmt: skip
    _fails(tmp_path, w, InputInvalidError, disclaimer=bad)
    _fails(tmp_path, w, InputInvalidError, disclosure_note="host 203.0.113.9 is the server")


def test_bad_subtitle_refused(tmp_path: Path) -> None:
    w = World(tmp_path)
    inputs = w.inputs()
    subs = (
        inputs.subtitles[0].model_copy(update={"ref": w.put("subs/bad.srt", b"no cues here")}),
        inputs.subtitles[1],
    )
    _fails(tmp_path, w, InputInvalidError, subtitles=subs)


def test_out_dir_must_be_empty_and_is_cleaned(tmp_path: Path) -> None:
    w = World(tmp_path)
    out = tmp_path / "bundle"
    out.mkdir()
    (out / "keep.txt").write_text("x")
    with pytest.raises(InputInvalidError):
        build_bundle(w.inputs(), out, storage=w.storage, context=w.context)
    assert (out / "keep.txt").exists()
    # an existing empty directory is accepted and emptied again after a failure
    empty = tmp_path / "empty"
    empty.mkdir()
    inputs = w.inputs()
    del w.storage.blobs[inputs.subtitles[1].ref.uri]
    with pytest.raises(MissingDependencyError):
        build_bundle(inputs, empty, storage=w.storage, context=w.context)
    assert empty.is_dir()
    assert list(empty.iterdir()) == []


def test_works_with_local_disk_storage(tmp_path: Path) -> None:
    from amw_core.storage import LocalDiskStorage

    w = World(tmp_path)
    disk = LocalDiskStorage(tmp_path / "blobs")
    inputs = w.inputs()
    for uri, data in w.storage.blobs.items():
        disk.put(w.context, uri, __import__("io").BytesIO(data))  # type: ignore[arg-type]
    m = build_bundle(inputs, tmp_path / "b", storage=disk, context=w.context)
    assert m.files
