"""Course ``data_pack`` reader port (Q22, 3A_SLICE R20, CCR-257/258).

Channel charts use the owner's course ``data_pack`` under the same allowance as the course, and
only rows older than the SEBI price-data lag (IN-02). The data never enters git: the pack lives at
a configured location outside the repository (``charts.data_pack_root``, unset = fail closed with
``PERMANENT.CONFIG_INVALID``) and the configured file map (``charts.data_pack_files``, key
``<INSTRUMENT>@<TIMEFRAME>`` to a file name inside the root) says which file holds which series. No
file name of the pack is written in this repository. Files are opened read-only and never written;
the reader never lists or walks the root, it only opens the configured names.

``manifest_sha256`` is the SHA-256 of the canonical JSON ``{file name: file SHA-256}`` over every
configured file: it pins the exact pack contents a chart was drawn from (chart provenance,
CCR-256). Rows are parsed by ``DatasetLoader.parse`` (one parser for registered datasets and the
pack): ISO dates strictly ascending, decimal prices, no NaN, bounded bar count.
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Protocol, Self, runtime_checkable

from agent_08_visual_assets.charts.dataset import Bar, DatasetLoader
from agent_08_visual_assets.charts.spec import canonical_json
from amw_core.errors import ConfigInvalidError, InputInvalidError, MissingDependencyError

DATA_PACK_TIMEFRAMES = ("1D", "1W")
"""Timeframes the chart path renders from the pack (the lag guard covers 1D/1W/1M; intraday files
of the pack are not used by the chart path, CCR-259)."""
ROOT_KEY = "charts.data_pack_root"
FILES_KEY = "charts.data_pack_files"
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
class DataPackSeries:
    instrument: str
    timeframe: str
    bars: tuple[Bar, ...]
    file_sha256: str
    manifest_sha256: str

    def index_window(self, start: date, end: date) -> tuple[int, int]:
        """Dataset bar indexes of the first and last bar dated inside ``[start, end]``."""
        if end < start:
            raise InputInvalidError("chart window ends before it starts")
        idx = [i for i, b in enumerate(self.bars) if start <= b.date <= end]
        if not idx:
            raise InputInvalidError("chart window holds no bar of the data_pack series")
        return idx[0], idx[-1]


@runtime_checkable
class DataPackReader(Protocol):
    """Read-only port to the course data_pack."""

    def manifest_sha256(self) -> str: ...

    def load(self, instrument: str, timeframe: str) -> DataPackSeries: ...


def _manifest(file_hashes: Mapping[str, str]) -> str:
    return hashlib.sha256(canonical_json(dict(file_hashes)).encode("utf-8")).hexdigest()


def _parse(
    instrument: str, timeframe: str, content: bytes, max_bars: int, manifest: str
) -> DataPackSeries:
    digest = DatasetLoader.sha256(content)
    series = DatasetLoader.parse(content, max_bars=max_bars, sha256=digest)
    return DataPackSeries(instrument, timeframe, series.bars, digest, manifest)


def _check_timeframe(timeframe: str) -> None:
    if timeframe not in DATA_PACK_TIMEFRAMES:
        raise InputInvalidError("timeframe is not supported for data_pack charts")


class FileDataPackReader:
    """File-backed implementation: opens only the configured file names under the root."""

    def __init__(self, settings: DataPackSettings) -> None:
        if not settings.root.is_dir():
            raise ConfigInvalidError(f"{ROOT_KEY} does not point to a readable directory")
        self._s = settings
        self._hashes: dict[str, str] | None = None

    def _read(self, name: str) -> bytes:
        path = self._s.root / name
        try:
            with path.open("rb") as fh:  # read-only; the pack is never written
                return fh.read()
        except OSError:
            raise ConfigInvalidError("a configured data_pack file cannot be read") from None

    def _file_hashes(self) -> dict[str, str]:
        if self._hashes is None:
            names = sorted(set(self._s.files.values()))
            self._hashes = {n: hashlib.sha256(self._read(n)).hexdigest() for n in names}
        return self._hashes

    def manifest_sha256(self) -> str:
        return _manifest(self._file_hashes())

    def load(self, instrument: str, timeframe: str) -> DataPackSeries:
        _check_timeframe(timeframe)
        name = self._s.files.get(series_key(instrument, timeframe))
        if name is None:
            raise MissingDependencyError("no data_pack series is configured for this request")
        content = self._read(name)
        if hashlib.sha256(content).hexdigest() != self._file_hashes()[name]:
            raise ConfigInvalidError("a data_pack file changed while it was read")
        return _parse(instrument, timeframe, content, self._s.max_bars, self.manifest_sha256())


@dataclass
class MemoryDataPackReader:
    """In-memory test double (synthetic bars only): series key to CSV bytes."""

    files: Mapping[str, bytes]
    max_bars: int = 100_000
    reads: list[str] = field(default_factory=list)

    def manifest_sha256(self) -> str:
        return _manifest({k: hashlib.sha256(v).hexdigest() for k, v in sorted(self.files.items())})

    def load(self, instrument: str, timeframe: str) -> DataPackSeries:
        _check_timeframe(timeframe)
        key = series_key(instrument, timeframe)
        if key not in self.files:
            raise MissingDependencyError("no data_pack series is configured for this request")
        self.reads.append(key)
        return _parse(instrument, timeframe, self.files[key], self.max_bars, self.manifest_sha256())
