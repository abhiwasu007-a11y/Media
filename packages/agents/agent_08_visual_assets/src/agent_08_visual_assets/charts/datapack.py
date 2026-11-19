"""Course ``data_pack`` reader port for the operator intake (Q22, 3A_SLICE R20, CCR-257/258).

Channel charts use the owner's course ``data_pack`` under the same allowance as the course, and
only rows older than the SEBI price-data lag (IN-02). The pack never enters git and is never read
at render time: the operator tool registers a pack file as an owner-made ``DATASET`` asset through
``AssetRegistrar.register_data_pack_series`` (human actor, ``SourceIntakeGuard`` first, audited),
and charts are drawn from that registered blob, hash-verified (``DataPackChartBuilder``).

``FileDataPackReader`` guards the location (MAJOR-1 of the PR #75 review):

* the root comes from ``charts.data_pack_root`` (unset = ``PERMANENT.CONFIG_INVALID``, fail closed);
* the root must contain no symbolic link (its real path equals its absolute path), must end in
  exactly ``research/course/data_pack`` (the layout stated in 00_REPO_AND_SERVER_AUDIT), no folder
  above that suffix may be a Trade research area or another research tree (``IS``, ``VAL``, ``OOS``,
  ``books``, ``review``, ``reports``, ``visual_audit``, ``research``, ``course``) and no component
  may hold ``holdout`` (any case); the factory never reads those folders;
* only the configured bare file names are opened (``charts.data_pack_files``: key
  ``<INSTRUMENT>@<1D|1W>``), never a listing, relative to a descriptor of the validated root; the
  opened descriptor is pinned to the validated entry (regular file, one hard link, same device and
  inode, ``O_NOFOLLOW``), and at most ``max_bars`` rows of ``MAX_ROW_BYTES`` bytes are read;
* files are opened read-only and never written.

``manifest_sha256`` is the SHA-256 of the canonical JSON ``{file name: file SHA-256}`` over every
configured file: it pins the pack contents a dataset was registered from (CCR-256). No file name of
the pack is written in this repository.
"""

import hashlib
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, Self, runtime_checkable

from agent_08_visual_assets.charts.spec import canonical_json
from amw_core.errors import ConfigInvalidError, InputInvalidError, MissingDependencyError

DATA_PACK_TIMEFRAMES = ("1D", "1W")
"""Timeframes the chart path renders from the pack (the lag guard covers 1D/1W/1M; intraday files
of the pack are not used by the chart path, CCR-259)."""
ROOT_KEY = "charts.data_pack_root"
FILES_KEY = "charts.data_pack_files"
ALLOWED_ROOT_SUFFIX = ("research", "course", "data_pack")
"""The only accepted location shape: ``.../research/course/data_pack`` (00 audit)."""
_DENIED_PARTS = frozenset(
    {"is", "val", "oos", "books", "review", "reports", "visual_audit", "research", "course"}
)
"""Folder names refused ABOVE the allowed suffix: Trade research areas and other research trees."""
MAX_ROW_BYTES = 256
"""Upper bound of one CSV row (``timestamp,open,high,low,close[,volume,oi]``) used for the file
size cap ``max_bars * MAX_ROW_BYTES``; a format bound, not a policy value."""
_FILE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}\.csv$")
_SERIES_KEY = re.compile(r"^[A-Za-z0-9_.-]{1,64}@(1D|1W)$")


def series_key(instrument: str, timeframe: str) -> str:
    return f"{instrument}@{timeframe}"


@dataclass(frozen=True, slots=True)
class DataPackSettings:
    """Validated location and file map of the pack (from the runtime config, never committed)."""

    root: Path
    files: Mapping[str, str]
    max_bars: int

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], *, max_bars: int) -> Self:
        root = raw.get(ROOT_KEY)
        if not isinstance(root, str) or not root.strip():
            raise ConfigInvalidError(f"{ROOT_KEY} is not set: charts from the data_pack are off")
        files = raw.get(FILES_KEY)
        if not isinstance(files, Mapping) or not files:
            raise ConfigInvalidError(f"{FILES_KEY} is not set: no data_pack series is configured")
        clean: dict[str, str] = {}
        for key, name in files.items():
            if not isinstance(key, str) or not _SERIES_KEY.match(key):
                raise ConfigInvalidError(f"{FILES_KEY} has an invalid series key")
            if not isinstance(name, str) or not _FILE_NAME.match(name):
                # a bare file name inside the root: no separator, no parent reference
                raise ConfigInvalidError(f"{FILES_KEY} has an invalid file name")
            clean[key] = name
        if max_bars < 1:
            raise ConfigInvalidError("assets.chart.max_dataset_bars must be >= 1")
        return cls(Path(root), clean, max_bars)


@dataclass(frozen=True, slots=True)
class DataPackFile:
    """One pack file as read: its bytes, their SHA-256 and the manifest of the whole pack."""

    instrument: str
    timeframe: str
    content: bytes
    sha256: str
    manifest_sha256: str


@runtime_checkable
class DataPackReader(Protocol):
    """Read-only port to the course data_pack (operator intake only)."""

    def manifest_sha256(self) -> str: ...

    def read(self, instrument: str, timeframe: str) -> DataPackFile: ...


def _manifest(file_hashes: Mapping[str, str]) -> str:
    return hashlib.sha256(canonical_json(dict(file_hashes)).encode("utf-8")).hexdigest()


def _check_timeframe(timeframe: str) -> None:
    if timeframe not in DATA_PACK_TIMEFRAMES:
        raise InputInvalidError("timeframe is not supported for data_pack charts")


def _check_entry(info: os.stat_result, cap: int) -> None:
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ConfigInvalidError("a configured data_pack file is not a regular file")
    if info.st_nlink != 1:
        raise ConfigInvalidError("a configured data_pack file has more than one hard link")
    if info.st_size > cap:
        raise ConfigInvalidError("a configured data_pack file exceeds the size cap")


def check_root(root: Path) -> Path:
    """The guarded real path of the pack root, or ``CONFIG_INVALID``."""
    absolute = Path(os.path.abspath(root))
    try:
        real = absolute.resolve(strict=True)
    except OSError:
        raise ConfigInvalidError(f"{ROOT_KEY} does not point to a readable directory") from None
    if not real.is_dir():
        raise ConfigInvalidError(f"{ROOT_KEY} does not point to a readable directory")
    if real != absolute:
        raise ConfigInvalidError(f"{ROOT_KEY} passes through a symbolic link")
    parts = [p.lower() for p in real.parts]
    if any("holdout" in p for p in parts):
        raise ConfigInvalidError(f"{ROOT_KEY} lies in a Trade research area")
    if tuple(real.parts[-len(ALLOWED_ROOT_SUFFIX) :]) != ALLOWED_ROOT_SUFFIX:
        raise ConfigInvalidError(f"{ROOT_KEY} is not the course data_pack folder")
    if any(p in _DENIED_PARTS for p in parts[: -len(ALLOWED_ROOT_SUFFIX)]):
        raise ConfigInvalidError(f"{ROOT_KEY} lies in a Trade research area")
    return real


class FileDataPackReader:
    """File-backed implementation: opens only the configured file names under the guarded root."""

    def __init__(self, settings: DataPackSettings) -> None:
        self._root = check_root(settings.root)
        st = os.stat(self._root, follow_symlinks=False)
        self._root_id = (st.st_dev, st.st_ino)
        self._s = settings
        self._hashes: dict[str, str] | None = None

    def _open_root(self) -> int:
        """A directory descriptor of the validated root (no symlink, same device and inode)."""
        try:
            dfd = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError:
            raise ConfigInvalidError(f"{ROOT_KEY} cannot be opened") from None
        st = os.fstat(dfd)
        if (st.st_dev, st.st_ino) != self._root_id:
            os.close(dfd)
            raise ConfigInvalidError(f"{ROOT_KEY} changed after it was validated")
        return dfd

    def _read(self, name: str) -> bytes:
        """Read one configured file, pinned to the entry that was validated: lstat and open relative
        to the root descriptor (no path re-resolution), ``O_NOFOLLOW`` and ``O_NONBLOCK`` (a FIFO
        never blocks), then ``fstat`` of the OPENED descriptor must show a regular file with one
        link, the same device and inode as the lstat, and a size within the cap; at most cap + 1
        bytes are read; anything longer, or a length other than the fstat size, is refused."""
        cap = self._s.max_bars * MAX_ROW_BYTES
        dfd = self._open_root()
        try:
            try:
                info = os.lstat(name, dir_fd=dfd)
            except OSError:
                raise ConfigInvalidError("a configured data_pack file cannot be read") from None
            _check_entry(info, cap)
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
            except OSError:
                raise ConfigInvalidError("a configured data_pack file cannot be read") from None
        finally:
            os.close(dfd)
        with os.fdopen(fd, "rb") as fh:  # read-only; the pack is never written
            opened = os.fstat(fh.fileno())
            _check_entry(opened, cap)
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise ConfigInvalidError("a configured data_pack file was replaced while opened")
            chunks: list[bytes] = []
            size = 0
            while size <= cap:
                chunk = fh.read(cap + 1 - size)
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
        data = b"".join(chunks)
        if len(data) > cap:
            raise ConfigInvalidError("a configured data_pack file exceeds the size cap")
        if len(data) != opened.st_size:
            raise ConfigInvalidError("a configured data_pack file changed while it was read")
        return data

    def _file_hashes(self) -> dict[str, str]:
        if self._hashes is None:
            names = sorted(set(self._s.files.values()))
            self._hashes = {n: hashlib.sha256(self._read(n)).hexdigest() for n in names}
        return self._hashes

    def manifest_sha256(self) -> str:
        return _manifest(self._file_hashes())

    def read(self, instrument: str, timeframe: str) -> DataPackFile:
        _check_timeframe(timeframe)
        name = self._s.files.get(series_key(instrument, timeframe))
        if name is None:
            raise MissingDependencyError("no data_pack series is configured for this request")
        content = self._read(name)
        digest = hashlib.sha256(content).hexdigest()
        if digest != self._file_hashes()[name]:
            raise ConfigInvalidError("a data_pack file changed while it was read")
        return DataPackFile(instrument, timeframe, content, digest, self.manifest_sha256())


@dataclass
class MemoryDataPackReader:
    """In-memory test double (synthetic bars only): series key to CSV bytes."""

    files: Mapping[str, bytes]
    reads: list[str] = field(default_factory=list)

    def manifest_sha256(self) -> str:
        return _manifest({k: hashlib.sha256(v).hexdigest() for k, v in sorted(self.files.items())})

    def read(self, instrument: str, timeframe: str) -> DataPackFile:
        _check_timeframe(timeframe)
        key = series_key(instrument, timeframe)
        if key not in self.files:
            raise MissingDependencyError("no data_pack series is configured for this request")
        self.reads.append(key)
        content = self.files[key]
        return DataPackFile(
            instrument,
            timeframe,
            content,
            hashlib.sha256(content).hexdigest(),
            self.manifest_sha256(),
        )
