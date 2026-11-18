"""``DatasetLoader`` and ``BarSeries``: the owner's historical OHLC dataset (blueprint 10.3, U-06).

Format: UTF-8 CSV with header ``date,open,high,low,close`` (extra columns are ignored). The loader
verifies the SHA-256 against the registered hash before parsing (S-06), requires ISO dates in
strictly ascending order and decimal prices with no empty cell, NaN or infinity, and a bounded
number of bars. Decimals only: no float ever touches a price.
"""

import csv
import hashlib
import io
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from amw_core.errors import CorruptedOutputError, InputInvalidError

REQUIRED_COLUMNS = ("date", "open", "high", "low", "close")


@dataclass(frozen=True, slots=True)
class Bar:
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True, slots=True)
class BarSeries:
    bars: tuple[Bar, ...]
    sha256: str

    def __len__(self) -> int:
        return len(self.bars)

    @property
    def start_date(self) -> date:
        return self.bars[0].date

    @property
    def end_date(self) -> date:
        return self.bars[-1].date

    def window(self, first: int, last: int) -> Sequence[Bar]:
        if not 0 <= first <= last < len(self.bars):
            raise InputInvalidError("chart window is outside the dataset")
        return self.bars[first : last + 1]


def _decimal(raw: str) -> Decimal:
    try:
        value = Decimal(raw.strip())
    except InvalidOperation:
        raise InputInvalidError("dataset holds a non-decimal price") from None
    if not value.is_finite():
        raise InputInvalidError("dataset holds a non-finite price")
    return value


class DatasetLoader:
    @staticmethod
    def sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @classmethod
    def load(cls, content: bytes, *, expected_sha256: str, max_bars: int) -> BarSeries:
        digest = cls.sha256(content)
        if digest != expected_sha256:
            # S-06: a blob changed after registration is never rendered
            raise CorruptedOutputError("dataset hash does not match the registered hash")
        return cls.parse(content, max_bars=max_bars, sha256=digest)

    @staticmethod
    def parse(content: bytes, *, max_bars: int, sha256: str) -> BarSeries:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            raise InputInvalidError("dataset is not UTF-8") from None
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None or any(c not in reader.fieldnames for c in REQUIRED_COLUMNS):
            raise InputInvalidError("dataset header must contain date,open,high,low,close")
        bars: list[Bar] = []
        for row in reader:
            if len(bars) >= max_bars:
                raise InputInvalidError("dataset has more bars than the configured maximum")
            try:
                day = date.fromisoformat((row["date"] or "").strip())
            except ValueError:
                raise InputInvalidError("dataset holds a non-ISO date") from None
            o, h, low, c = (_decimal(row[k] or "") for k in ("open", "high", "low", "close"))
            if high_low_broken(o, h, low, c):
                raise InputInvalidError("dataset bar has high below low or outside open/close")
            if bars and day <= bars[-1].date:
                raise InputInvalidError("dataset dates are not strictly ascending")
            bars.append(Bar(day, o, h, low, c))
        if not bars:
            raise InputInvalidError("dataset has no bars")
        return BarSeries(tuple(bars), sha256)


def high_low_broken(o: Decimal, h: Decimal, low: Decimal, c: Decimal) -> bool:
    return h < low or h < max(o, c) or low > min(o, c)
