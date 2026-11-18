"""Secret redaction (08 section 3.1 rule 3): by key name, by known pattern, by known value."""

import logging
import re
from collections.abc import Iterable, Mapping
from typing import Any

REDACTED = "[REDACTED]"

SECRET_KEY_NAME = re.compile(
    r"(?i)(?:^|[_.-])(?:pass(?:word|wd)?|secrets?|token|api[_-]?key|apikey|authorization|"
    r"auth[_-]?header|cookie|credentials?|private[_-]?key|dsn|database[_-]?url|db[_-]?url|"
    r"session[_-]?ref|kek|dek)(?:$|[_.-])"
)
"""Field names whose values are always removed (``logging of objects named *token*/*secret*``)."""

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----[\s\S]*?(-----END[^-]*-----|$)"
    ),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(basic)\s+[A-Za-z0-9+/=]{12,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password|passwd)\s*[:=]\s*\S{6,}"),
)
"""Known secret shapes (provider keys, bearer/basic headers, JWTs, key=value assignments)."""

URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<cred>[^/@\s:]+:[^/@\s]+)@")
"""``scheme://user:password@host`` -> the credential part is removed."""

_MIN_VALUE_LEN = 6


class Redactor:
    """Removes secrets from strings and nested structures. ``values`` are exact secret values
    (from ``AmwSettings.secret_values``); values shorter than 6 characters are ignored so short
    common strings are never mass-redacted."""

    def __init__(self, values: Iterable[str] = ()) -> None:
        self._values: tuple[str, ...] = ()
        self.add_values(values)

    def add_values(self, values: Iterable[str]) -> None:
        merged = set(self._values) | {v for v in values if len(v) >= _MIN_VALUE_LEN}
        self._values = tuple(sorted(merged, key=len, reverse=True))

    def text(self, value: str) -> str:
        out = value
        for secret in self._values:
            if secret in out:
                out = out.replace(secret, REDACTED)
        out = URL_CREDENTIALS.sub(lambda m: f"{m['scheme']}{REDACTED}@", out)
        for pattern in SECRET_PATTERNS:
            out = pattern.sub(REDACTED, out)
        return out

    def value(self, value: Any, key: str | None = None) -> Any:
        if key is not None and SECRET_KEY_NAME.search(key):
            return REDACTED if value is not None else None
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, Mapping):
            return {str(k): self.value(v, str(k)) for k, v in value.items()}
        if isinstance(value, (list, tuple, set, frozenset)):
            return [self.value(v) for v in value]
        if isinstance(value, (bytes, bytearray)):
            return f"<{len(value)} bytes>"
        return value


def contains_secret(value: Any, redactor: Redactor | None = None) -> bool:
    """True if redaction would change ``value`` (used to refuse secrets in audit details)."""
    r = redactor or Redactor()
    return bool(r.value(value) != _plain(value))


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(v) for v in value]
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    return value


_STD_ATTRS = frozenset(
    logging.LogRecord("x", 0, "x", 0, "x", None, None).__dict__.keys() | {"message", "asctime"}
)


class RedactionFilter(logging.Filter):
    """Redacts the message, its arguments and every ``extra`` field of a record in place."""

    def __init__(self, redactor: Redactor | None = None) -> None:
        super().__init__()
        self.redactor = redactor or Redactor()

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except TypeError, ValueError:
            message = str(record.msg)
        record.msg = self.redactor.text(message)
        record.args = None
        for key in list(record.__dict__):
            if key in _STD_ATTRS:
                continue
            record.__dict__[key] = self.redactor.value(record.__dict__[key], key)
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = self.redactor.text(
                logging.Formatter().formatException(record.exc_info)
            )
            record.exc_info = None
        return True
