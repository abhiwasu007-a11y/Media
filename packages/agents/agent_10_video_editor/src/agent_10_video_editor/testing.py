"""In-memory fakes for tests and the walking skeleton (no network, no real media).

``FakeFfmpegRunner`` is the in-memory fake behind the ``FfmpegRunner`` Protocol: it parses the
argument lists built by ``ArgvBuilder`` and writes deterministic fake outputs (a small JSON
header after a magic prefix), answers ffprobe from that header and returns canned detector text.
Same argv and same input bytes give the same output bytes, so resume, replay and segment-key
behaviour are testable without FFmpeg. Not for production use.
"""

import hashlib
import io
import re
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from agent_10_video_editor.canonical import canonical_json, sha256_hex
from agent_10_video_editor.config import AgentTenConfig, Placement
from agent_10_video_editor.ffmpeg import ProcessResult, RunLimits
from agent_10_video_editor.guard import AdmissionProbe, LocalTime, TimerHandle
from agent_10_video_editor.inputs import AssetRecord
from agent_10_video_editor.ports import (
    LicenceSnapshot,
    QcRow,
    RenderRow,
    SubtitleAsset,
)
from amw_core.enums import CostFigureKind, RenderStatus
from amw_core.errors import (
    CorruptedOutputError,
    CrossTenantRefError,
    InputInvalidError,
    MissingDependencyError,
)
from amw_core.ids import COST_ENTRY, OrgId
from amw_core.interfaces.cost_ledger import CostEntry, CostTotals, NewCostEntry
from amw_core.interfaces.storage import (
    BlobHead,
    BlobInfo,
    BlobUri,
    ReadableStream,
)
from amw_core.interfaces.tenancy_context import TenantContext, TenantTransaction
from amw_core.testing.memory import MemoryTransaction

FAKE_MAGIC = b"FAKEMEDIA\n"


def make_config(**overrides: Any) -> AgentTenConfig:
    """A complete valid configuration with test values (calibration values are test values)."""
    data: dict[str, Any] = {
        "render": {
            "fps_num": 30,
            "fps_den": 1,
            "preset_key": "yt_master_1080p",
            "video_encoder": "libx264",
            "video_bitrate_bps": 20_000_000,
            "video_maxrate_bps": 25_000_000,
            "gop_frames": 60,
            "segment_target_ms": 8_000,
            "threads": 1,
            "drain_finish_max_ms": 0,
            "x264_preset": "ultrafast",
        },
        "sub": {"max_chars_per_cue": 42},
        "guard": {
            "market_windows": [
                {"weekday": d, "start_min": 540, "end_min": 960}
                for d in ("MON", "TUE", "WED", "THU", "FRI")
            ],
            "night_window": {"start_min": 0, "end_min": 420, "grace_ms": 600_000},
        },
        "qc": {},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key] = {**data[key], **value}
        else:
            data[key] = value
    return AgentTenConfig.from_mapping(data)


# ----------------------------------------------------------------------------- storage


class MemoryBlobStorage:
    """``BlobStorage`` in memory: tenant check, write-once, hash verified on ``get``."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self._recorded: dict[str, str] = {}
        self.put_count = 0
        self.after_put: Callable[[str], None] | None = None

    @staticmethod
    def _owner(uri: str) -> str:
        return uri.split("://", 1)[1].split("/", 1)[0]

    def _check(self, context: TenantContext, uri: str, *, write: bool) -> None:
        owner = self._owner(uri)
        if owner != context.org_id and not (owner == "platform" and not write):
            raise CrossTenantRefError("blob belongs to another tenant")

    def blob_uri(self, context: TenantContext, area: str, path: str) -> BlobUri:
        return BlobUri(f"amw-blob://{context.org_id}/{area}/{path}")

    def put(self, context: TenantContext, uri: BlobUri, stream: ReadableStream) -> BlobInfo:
        self._check(context, uri, write=True)
        data = stream.read()
        if uri in self.blobs:
            raise InputInvalidError("write-once: blob exists")
        self.blobs[uri] = data
        self._recorded[uri] = sha256_hex(data)
        self.put_count += 1
        info = BlobInfo(uri, sha256_hex(data), len(data))
        if self.after_put is not None:
            self.after_put(uri)
        return info

    def put_bytes(self, context: TenantContext, uri: str, data: bytes) -> BlobInfo:
        return self.put(context, BlobUri(uri), io.BytesIO(data))

    def get(self, context: TenantContext, uri: BlobUri, expected_sha256: str) -> Iterator[bytes]:
        self._check(context, uri, write=False)
        if uri not in self.blobs:
            raise MissingDependencyError("blob absent")
        data = self.blobs[uri]
        if sha256_hex(data) != expected_sha256:
            raise CorruptedOutputError("blob hash mismatch")
        yield data

    def head(self, context: TenantContext, uri: BlobUri) -> BlobHead:
        self._check(context, uri, write=False)
        data = self.blobs.get(uri)
        if data is None:
            return BlobHead(False, None, None)
        # like a real backend, the recorded hash is the one written at put time
        return BlobHead(True, self._recorded[uri], len(data))

    def list_prefix(self, context: TenantContext, org_id: OrgId, area: str) -> list[BlobInfo]:
        if org_id != context.org_id:
            raise CrossTenantRefError("other tenant")
        prefix = f"amw-blob://{org_id}/{area}/"
        return [
            BlobInfo(BlobUri(u), sha256_hex(d), len(d))
            for u, d in self.blobs.items()
            if u.startswith(prefix)
        ]

    def corrupt(self, uri: str) -> None:
        """Flip a byte in place; the recorded hash stays the old one (silent corruption)."""
        data = bytearray(self.blobs[uri])
        self._recorded[uri] = sha256_hex(bytes(data))
        data[-1] ^= 0xFF
        self.blobs[uri] = bytes(data)


class MemoryTenancy:
    def __init__(self) -> None:
        self.opened = 0

    def transaction(self, context: TenantContext) -> AbstractContextManager[TenantTransaction]:
        @contextmanager
        def _tx() -> Iterator[TenantTransaction]:
            self.opened += 1
            yield MemoryTransaction(context)

        return _tx()

    def require_same_tenant(self, tx: TenantTransaction, org_id: str) -> None:
        if tx.context.org_id != org_id:
            raise CrossTenantRefError("other tenant")

    def cache_key(self, org_id: OrgId, area: str, key: str) -> str:
        return f"amw:{org_id}:{area}:{key}"


# ----------------------------------------------------------------------------- clock, probe, timers


class FakeClock:
    """``Clock`` with a fixed wall time and a monotonic counter that advances per call."""

    def __init__(self, start: datetime | None = None, tick_ms: int = 1) -> None:
        self._now = start or datetime(2000, 1, 1, tzinfo=UTC)
        self._mono = 0
        self._tick = tick_ms

    def now(self) -> datetime:
        return self._now

    def monotonic_ms(self) -> int:
        self._mono += self._tick
        return self._mono


class FakeAdmissionProbe(AdmissionProbe):
    def __init__(self, now: LocalTime, placement: Placement = Placement.DEV) -> None:
        self.now = now
        self._placement = placement
        self.drain = False

    def now_local(self) -> LocalTime:
        return self.now

    def drain_flag(self) -> bool:
        return self.drain

    def placement(self) -> Placement:
        return self._placement


class _ManualHandle:
    def __init__(self, delay_ms: int, callback: Callable[[], None]) -> None:
        self.delay_ms = delay_ms
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class ManualTimerFactory:
    """Timers that fire only when the test says so (``fire_all``)."""

    def __init__(self) -> None:
        self.handles: list[_ManualHandle] = []

    def start(self, delay_ms: int, callback: Callable[[], None]) -> TimerHandle:
        handle = _ManualHandle(delay_ms, callback)
        self.handles.append(handle)
        return handle

    def fire_all(self) -> None:
        for handle in self.handles:
            if not handle.cancelled:
                handle.callback()


# ----------------------------------------------------------------------------- ledger, repositories


class MemoryCostLedger:
    def __init__(self) -> None:
        self.rows: list[CostEntry] = []

    def record(self, tx: TenantTransaction, entry: NewCostEntry) -> CostEntry:
        row = CostEntry(COST_ENTRY.new(), tx.context.org_id, entry)
        self.rows.append(row)
        return row

    def get(self, tx: TenantTransaction, entry_id: Any) -> CostEntry | None:
        return next((r for r in self.rows if r.id == entry_id), None)

    def for_job(self, tx: TenantTransaction, job_id: Any) -> Sequence[CostEntry]:
        return [r for r in self.rows if r.entry.job_id == job_id]

    def for_task(self, tx: TenantTransaction, task_id: Any) -> Sequence[CostEntry]:
        return [r for r in self.rows if r.entry.task_id == task_id]

    def job_totals(self, tx: TenantTransaction, job_id: Any) -> CostTotals:
        return CostTotals(0, 0, 0, len(self.rows), 0, "INR")


class MemoryRenderRepository:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], RenderRow] = {}

    def _mine(self, tx: TenantTransaction) -> list[RenderRow]:
        return [r for (org, _), r in self.rows.items() if org == tx.context.org_id]

    def find_by_content(self, tx: TenantTransaction, content_sha256: str) -> RenderRow | None:
        return next((r for r in self._mine(tx) if r.content_sha256 == content_sha256), None)

    def find_master(
        self, tx: TenantTransaction, job_id: str, timeline_sha256: str, preset_key: str
    ) -> RenderRow | None:
        return next(
            (
                r
                for r in self._mine(tx)
                if r.job_id == job_id
                and r.timeline_sha256 == timeline_sha256
                and r.preset_key == preset_key
                and r.status is not RenderStatus.SUPERSEDED
            ),
            None,
        )

    def get(self, tx: TenantTransaction, render_id: str) -> RenderRow | None:
        return self.rows.get((tx.context.org_id, render_id))

    def insert(self, tx: TenantTransaction, row: RenderRow) -> RenderRow:
        existing = self.find_by_content(tx, row.content_sha256)
        if existing is not None:
            return existing
        for key, other in list(self.rows.items()):
            if key[0] == tx.context.org_id and (other.job_id, other.kind, other.preset_key) == (
                row.job_id,
                row.kind,
                row.preset_key,
            ):
                self.rows[key] = replace(other, status=RenderStatus.SUPERSEDED)
        self.rows[(tx.context.org_id, row.render_id)] = row
        return row

    def set_qc(
        self,
        tx: TenantTransaction,
        render_id: str,
        status: RenderStatus,
        integrated_lufs: float | None,
        true_peak_dbtp: float | None,
    ) -> RenderRow:
        row = replace(
            self.rows[(tx.context.org_id, render_id)],
            status=status,
            integrated_lufs=integrated_lufs,
            true_peak_dbtp=true_peak_dbtp,
        )
        self.rows[(tx.context.org_id, render_id)] = row
        return row


class MemoryQcResultRepository:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], QcRow] = {}

    def insert_many(self, tx: TenantTransaction, rows: Sequence[QcRow]) -> int:
        new = 0
        for row in rows:
            key = (tx.context.org_id, row.task_id, row.check_id)
            if key not in self.rows:
                self.rows[key] = row
                new += 1
        return new

    def for_render(self, tx: TenantTransaction, render_id: str) -> Sequence[QcRow]:
        return [
            r
            for (org, _, _), r in self.rows.items()
            if org == tx.context.org_id and r.render_id == render_id
        ]


class MemoryAssetCatalog:
    def __init__(self) -> None:
        self.assets: dict[tuple[str, str], AssetRecord] = {}
        self.subtitles: dict[tuple[str, str], SubtitleAsset] = {}

    def add(self, org_id: str, record: AssetRecord) -> None:
        self.assets[(org_id, record.asset_id)] = record

    def lookup(self, tx: TenantTransaction, asset_ids: Sequence[str]) -> Mapping[str, AssetRecord]:
        return {
            a: self.assets[(tx.context.org_id, a)]
            for a in asset_ids
            if (tx.context.org_id, a) in self.assets
        }

    def find_subtitle(self, tx: TenantTransaction, content_sha256: str) -> SubtitleAsset | None:
        return self.subtitles.get((tx.context.org_id, content_sha256))

    def insert_subtitle(self, tx: TenantTransaction, asset: SubtitleAsset) -> SubtitleAsset:
        return self.subtitles.setdefault((tx.context.org_id, asset.content_sha256), asset)


class MemoryLicenceReader:
    def __init__(self, snapshot: LicenceSnapshot | None = None) -> None:
        self.snapshot_value = snapshot or LicenceSnapshot()

    def snapshot(
        self, tx: TenantTransaction, job_id: str, render_id: str, asset_ids: Sequence[str]
    ) -> LicenceSnapshot:
        return self.snapshot_value


# ----------------------------------------------------------------------------- the fake runner

_CLEAN_EBUR128 = (
    "[Parsed_ebur128_0 @ 0x1] Summary:\n\n  Integrated loudness:\n    I:         -14.0 LUFS\n"
    "    Threshold: -24.0 LUFS\n\n  Loudness range:\n    LRA:         5.0 LU\n"
    "    Threshold: -34.0 LUFS\n    LRA low:   -19.0 LUFS\n    LRA high:  -14.0 LUFS\n\n"
    "  True peak:\n    Peak:       -1.5 dBFS\n"
)


@dataclass
class FakeCall:
    kind: str
    argv: tuple[str, ...]


class FakeFfmpegRunner:
    """Deterministic in-memory ``FfmpegRunner``."""

    def __init__(
        self, *, width: int = 1920, height: int = 1080, video_bitrate_bps: int = 20_000_000
    ) -> None:
        self.width, self.height, self.video_bitrate_bps = width, height, video_bitrate_bps
        self.calls: list[FakeCall] = []
        self.detector_text: dict[str, str] = {"ebur128": _CLEAN_EBUR128}
        self.before_encode: Callable[[int, str], None] | None = None
        self.crash_on_encode: set[int] = set()
        self.bad_idr = False
        self.faststart = True
        self.unreadable_inputs: set[str] = set()
        self._encodes = 0
        self._lock = threading.Lock()

    @property
    def encode_calls(self) -> int:
        return sum(1 for c in self.calls if c.kind in ("segment", "mux"))

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        limits: RunLimits,
        stop: Callable[[], bool] | None = None,
    ) -> ProcessResult:
        with self._lock:
            return self._run(list(argv), cwd, stop)

    # -- dispatch -------------------------------------------------------------------------------

    def _run(self, argv: list[str], cwd: Path, stop: Callable[[], bool] | None) -> ProcessResult:
        tool = Path(argv[0]).name
        joined = " ".join(argv)
        if tool == "ffprobe":
            return self._ffprobe(argv, cwd)
        if "-version" in argv:
            self.calls.append(FakeCall("version", tuple(argv)))
            return ProcessResult(0, stdout="ffmpeg version fake-1.0 (in-memory)\n")
        if "-filter_complex" in argv:
            return self._encode("segment", argv, cwd, stop)
        if "concat" in argv and "-movflags" in argv:
            return self._encode("mux", argv, cwd, stop)
        if "-frames:v" in argv and "image2" in argv and "-ss" in argv:
            return self._image(argv, cwd)
        if "tile=" in joined:
            return self._sheet(argv, cwd)
        for kind in ("ebur128", "silencedetect", "blackdetect", "freezedetect", "showinfo"):
            if kind in joined:
                self.calls.append(FakeCall(kind, tuple(argv)))
                key = "scene" if kind == "showinfo" else kind
                return ProcessResult(0, stderr=self.detector_text.get(key, ""))
        self.calls.append(FakeCall("other", tuple(argv)))
        return ProcessResult(0)

    # -- encodes --------------------------------------------------------------------------------

    def _encode(
        self, kind: str, argv: list[str], cwd: Path, stop: Callable[[], bool] | None
    ) -> ProcessResult:
        self._encodes += 1
        self.calls.append(FakeCall(kind, tuple(argv)))
        if self.before_encode is not None:
            self.before_encode(self._encodes, kind)
        if stop is not None and stop():
            return ProcessResult(-15, killed_by="SIGTERM")
        if self._encodes in self.crash_on_encode:
            return ProcessResult(1, stderr="fake crash")
        inputs = [argv[i + 1] for i, a in enumerate(argv) if a == "-i"]
        for name in inputs:
            if name in self.unreadable_inputs:
                return ProcessResult(1, stderr="Invalid data found when processing input")
        out_name = argv[-1]
        if kind == "segment":
            frames = int(argv[argv.index("-frames:v") + 1])
            graph = argv[argv.index("-filter_complex") + 1]
            size = re.search(r"scale=(\d+):(\d+):force", graph)
            header = {
                "kind": "segment",
                "frames": frames,
                "fps": argv[argv.index("-r") + 1],
                "width": int(size.group(1)) if size else self.width,
                "height": int(size.group(2)) if size else self.height,
                "argv": hashlib.sha256(canonical_json(argv)).hexdigest(),
                "inputs": [
                    sha256_hex((cwd / n).read_bytes()) for n in inputs if (cwd / n).exists()
                ],
                "colour": [
                    argv[argv.index(f) + 1]
                    for f in ("-color_primaries", "-color_trc", "-colorspace", "-color_range")
                ],
            }
        else:
            names = re.findall(r"file '([^']+)'", (cwd / "concat.txt").read_text())
            parts = [self._header((cwd / n).read_bytes()) for n in names]
            master = (cwd / "master.wav").read_bytes()
            header = {
                "kind": "final",
                "frames": sum(p["frames"] for p in parts),
                "fps": parts[0]["fps"],
                "width": parts[0]["width"],
                "height": parts[0]["height"],
                "colour": parts[0]["colour"],
                "segments": [p["argv"] for p in parts],
                "duration": argv[argv.index("-t") + 1],
                "audio_sha": sha256_hex(master),
                "audio": {
                    "codec": argv[argv.index("-c:a") + 1],
                    "profile": argv[argv.index("-profile:a") + 1],
                    "bitrate": int(argv[argv.index("-b:a") + 1]),
                    "rate": int(argv[argv.index("-ar") + 1]),
                    "channels": int(argv[argv.index("-ac") + 1]),
                },
            }
        (cwd / out_name).write_bytes(self._boxes(header))
        return ProcessResult(0)

    def _boxes(self, header: dict[str, Any]) -> bytes:
        """``ftyp``, ``moov`` (the fake header) and ``mdat`` boxes; order per ``faststart``."""
        moov_body = FAKE_MAGIC + canonical_json(header) + b"\n"
        ftyp = (24).to_bytes(4, "big") + b"ftypisom" + b"\0" * 12
        moov = (len(moov_body) + 8).to_bytes(4, "big") + b"moov" + moov_body
        mdat = (72).to_bytes(4, "big") + b"mdat" + b"\0" * 64
        return ftyp + (moov + mdat if self.faststart else mdat + moov)

    @staticmethod
    def _header(data: bytes) -> dict[str, Any]:
        import json

        at = data.find(FAKE_MAGIC)
        if at < 0:
            raise ValueError("not fake media")
        return json.loads(data[at + len(FAKE_MAGIC) :].split(b"\n", 1)[0])  # type: ignore[no-any-return]

    # -- ffprobe --------------------------------------------------------------------------------

    def _ffprobe(self, argv: list[str], cwd: Path) -> ProcessResult:
        import json

        name = argv[-1]
        path = cwd / name
        self.calls.append(FakeCall("probe", tuple(argv)))
        if not path.exists() or FAKE_MAGIC not in path.read_bytes():
            return ProcessResult(1, stderr="Invalid data found when processing input")
        head = self._header(path.read_bytes())
        num, den = (int(x) for x in head["fps"].split("/"))
        text = " ".join(argv)
        if "nb_read_frames" in text:
            return ProcessResult(
                0, stdout=json.dumps({"streams": [{"nb_read_frames": str(head["frames"])}]})
            )
        if "frame=key_frame" in text:
            first = {
                "key_frame": 0 if self.bad_idr else 1,
                "pict_type": "P" if self.bad_idr else "I",
            }
            return ProcessResult(0, stdout=json.dumps({"frames": [first]}))
        if "packet=pts_time" in text:
            rows = [f"{Decimal(i * den) / Decimal(num):.6f}" for i in range(head["frames"])]
            return ProcessResult(0, stdout="\n".join(rows) + "\n")
        duration = Decimal(head["frames"] * den) / Decimal(num)
        if "stream=codec_type,start_time,duration" in text:
            return ProcessResult(
                0, stdout=f"video,0.000000,{duration:.6f}\naudio,0.000000,{duration:.6f}\n"
            )
        colour = head["colour"]
        video = {
            "codec_type": "video",
            "codec_name": "h264",
            "profile": "High",
            "pix_fmt": "yuv420p",
            "width": head["width"],
            "height": head["height"],
            "field_order": "progressive",
            "r_frame_rate": f"{num}/{den}",
            "avg_frame_rate": f"{num}/{den}",
            "bit_rate": str(self.video_bitrate_bps),
            "start_time": "0.000000",
            "duration": f"{duration:.6f}",
            "color_primaries": colour[0],
            "color_transfer": colour[1],
            "color_space": colour[2],
            "color_range": colour[3],
        }
        streams = [video]
        if head["kind"] == "final":
            a = head["audio"]
            streams.append(
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "profile": "LC",
                    "sample_rate": str(a["rate"]),
                    "channels": a["channels"],
                    "bit_rate": str(int(a["bitrate"] * 0.6)),
                    "start_time": "0.000000",
                    "duration": f"{duration:.6f}",
                }
            )
        size = path.stat().st_size
        return ProcessResult(
            0,
            stdout=json.dumps(
                {
                    "streams": streams,
                    "format": {
                        "duration": f"{duration:.6f}",
                        "size": str(size),
                        "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
                    },
                }
            ),
        )

    # -- evidence -------------------------------------------------------------------------------

    def _image(self, argv: list[str], cwd: Path) -> ProcessResult:
        self.calls.append(FakeCall("frame", tuple(argv)))
        seek = argv[argv.index("-ss") + 1]
        (cwd / argv[-1]).write_bytes(
            b"FAKEPNG"
            + seek.encode()
            + sha256_hex((cwd / argv[argv.index("-i") + 1]).read_bytes()).encode()
        )
        return ProcessResult(0)

    def _sheet(self, argv: list[str], cwd: Path) -> ProcessResult:
        self.calls.append(FakeCall("sheet", tuple(argv)))
        names = sorted(p.name for p in cwd.glob("s*.png"))
        (cwd / argv[-1]).write_bytes(b"FAKESHEET" + ",".join(names).encode())
        return ProcessResult(0)


__all__ = [
    "FAKE_MAGIC",
    "CostFigureKind",
    "FakeAdmissionProbe",
    "FakeCall",
    "FakeClock",
    "FakeFfmpegRunner",
    "ManualTimerFactory",
    "MemoryAssetCatalog",
    "MemoryBlobStorage",
    "MemoryCostLedger",
    "MemoryLicenceReader",
    "MemoryQcResultRepository",
    "MemoryRenderRepository",
    "MemoryTenancy",
    "make_config",
]
