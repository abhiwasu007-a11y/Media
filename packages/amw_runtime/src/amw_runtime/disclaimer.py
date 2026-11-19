"""FIN-R10 disclaimer template (interface 5): versioned data file with a sha256 check."""

import hashlib
import re
from dataclasses import dataclass

from amw_runtime.data_files import DATA_DIR, read_json
from amw_runtime.errors import DisclaimerError

DRAFT_STATUS = "DRAFT – not lawyer-approved"  # noqa: RUF001 (en dash is the owner-set label)
_VERSION = re.compile(r"^v[0-9]+$")


@dataclass(frozen=True)
class Disclaimer:
    text: str
    version: str
    status: str
    sha256: str
    language: str = "mr"

    @property
    def is_draft(self) -> bool:
        return self.status == DRAFT_STATUS


def get_disclaimer(version: str) -> Disclaimer:
    if not _VERSION.match(version):
        raise DisclaimerError("unknown disclaimer version")
    path = DATA_DIR / "disclaimer" / f"mr_{version}.json"
    if not path.is_file():
        raise DisclaimerError("unknown disclaimer version")
    try:
        raw = read_json(path)
        text, digest = str(raw["text"]), str(raw["sha256"])
        status, ver = str(raw["status"]), str(raw["version"])
    except ValueError, KeyError:
        raise DisclaimerError("disclaimer template invalid") from None
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != digest or ver != version:
        raise DisclaimerError("disclaimer template fails its sha256/version check")
    return Disclaimer(text=text, version=ver, status=status, sha256=digest)
