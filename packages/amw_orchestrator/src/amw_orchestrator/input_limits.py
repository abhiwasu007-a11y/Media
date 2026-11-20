"""Size caps of the documents the input readers load (D16: caps are config data, never literals).

The seeded values live in ``amw_orchestrator/data/input_limits.json``; the composition root loads
them (``packaged_input_limits``) or builds its own ``InputLimits`` and hands the object to each
reader explicitly. No reader has a default. ``read_bounded`` enforces a cap WHILE reading, so a
larger blob is never held in memory whole."""

from collections.abc import Callable, Iterator
from importlib import resources

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from amw_core.errors import ConfigInvalidError


class InputLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_research_pack_bytes: int = Field(ge=1)
    max_brand_kit_bytes: int = Field(ge=1)


def packaged_input_limits() -> InputLimits:
    """The seeded caps (config data shipped with the package)."""
    try:
        raw = resources.files("amw_orchestrator").joinpath("data/input_limits.json").read_bytes()
        return InputLimits.model_validate_json(raw)
    except OSError, ValidationError:
        raise ConfigInvalidError("the packaged input limits are missing or invalid") from None


def read_bounded(
    chunks: Iterator[bytes], max_bytes: int, too_large: Callable[[], Exception]
) -> bytes:
    """Join ``chunks`` but raise ``too_large()`` as soon as the running size exceeds ``max_bytes``
    (the rest is not read; the stream is closed)."""
    parts: list[bytes] = []
    size = 0
    try:
        for chunk in chunks:
            size += len(chunk)
            if size > max_bytes:
                raise too_large()
            parts.append(chunk)
    finally:
        close = getattr(chunks, "close", None)
        if close is not None:
            close()
    return b"".join(parts)
