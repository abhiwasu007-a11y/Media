"""Review fixes: size caps are config data and enforced while reading; storage calls carry the
incoming context's actor and correlation id (not the channel id)."""

import dataclasses
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from agent_05_scriptwriter.errors import InputInvalid
from amw_core.errors import ConfigInvalidError, InputInvalidError
from amw_orchestrator.brand_kit import FontManifest, ManifestBrandKitReader
from amw_orchestrator.brand_kit.fonts import packaged_manifest_path
from amw_orchestrator.input_limits import InputLimits, packaged_input_limits, read_bounded
from tests.brand_kit.test_brand_kit import World as KitWorld
from tests.script_inputs.world import World

PACK_REF = {
    "purpose": "PRIOR_OUTPUT",
    "schema": "agent_04.research_pack.output",
    "schema_version": "1.0.0",
}


class SpyStorage:
    """Delegates to the real storage; records the tenant context and the chunks pulled."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.contexts: list[Any] = []
        self.chunks_read = 0

    def head(self, context: Any, uri: Any) -> Any:
        self.contexts.append(context)
        return self.inner.head(context, uri)

    def get(self, context: Any, uri: Any, sha: str) -> Iterator[bytes]:
        self.contexts.append(context)
        for chunk in self.inner.get(context, uri, sha):
            self.chunks_read += 1
            yield chunk


def test_packaged_limits_are_config_data_and_have_no_other_source() -> None:
    limits = packaged_input_limits()
    assert limits.max_research_pack_bytes >= 1
    assert limits.max_brand_kit_bytes >= 1
    with pytest.raises(ValueError, match="max_brand_kit_bytes"):
        InputLimits.model_validate({"max_research_pack_bytes": 1})


def test_read_bounded_stops_before_reading_the_rest() -> None:
    pulled = 0

    def stream() -> Iterator[bytes]:
        nonlocal pulled
        for _ in range(1000):
            pulled += 1
            yield b"x" * 10

    with pytest.raises(InputInvalidError):
        read_bounded(stream(), 25, lambda: InputInvalidError("big"))
    assert pulled == 3  # the 3rd chunk crossed the cap; 997 chunks were never pulled
    assert read_bounded(iter([b"ab", b"cd"]), 4, lambda: InputInvalidError("big")) == b"abcd"


def test_resolver_storage_calls_carry_actor_and_correlation_id(tmp_path: Path) -> None:
    w = World(tmp_path)
    ref = w.put(w.pack_doc)
    spy = SpyStorage(w.storage)
    w.storage = spy  # type: ignore[assignment]
    w.ctx = dataclasses.replace(w.ctx, actor="agent_05", correlation_id="corr-123")
    ti = w.task(refs=[{**ref, **PACK_REF}])
    w.resolver().resolve(w.ctx, ti, w.data(ti))
    assert spy.contexts
    for tenant in spy.contexts:
        assert str(tenant.org_id) == w.ctx.org_id
        assert str(tenant.actor) == "agent_05"
        assert str(tenant.correlation_id) == "corr-123"
        assert tenant.correlation_id != w.ctx.channel_id


def test_oversize_research_pack_is_refused_without_reading_it_whole(tmp_path: Path) -> None:
    w = World(tmp_path)
    big = json.dumps({"pad": "x" * 300_000}).encode()
    ref = w.put(big, "big.json")
    spy = SpyStorage(w.storage)
    w.storage = spy  # type: ignore[assignment]
    w.limits = InputLimits(max_research_pack_bytes=1024, max_brand_kit_bytes=1024)
    ti = w.task(refs=[{**ref, **PACK_REF}])
    with pytest.raises(InputInvalid):
        w.resolver().resolve(w.ctx, ti, w.data(ti))
    assert spy.chunks_read == 1  # the first chunk alone crossed the cap


def test_oversize_brand_kit_is_refused_while_reading(tmp_path: Path) -> None:
    kit = KitWorld(tmp_path)
    uri, sha = kit.put(b'{"pad": "' + b"x" * 200_000 + b'"}')
    spy = SpyStorage(kit.storage)
    small = InputLimits(max_research_pack_bytes=1024, max_brand_kit_bytes=1024)
    reader = ManifestBrandKitReader(spy, kit.assets, FontManifest(packaged_manifest_path()), small)  # type: ignore[arg-type]
    with pytest.raises(InputInvalidError, match="too large"):
        reader.brand_kit(kit.tx, uri, sha)
    assert spy.chunks_read == 1


def test_manifest_entry_without_a_file_is_a_typed_error(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"fonts": [{"key": "k", "purpose": "brand_primary"}]}))
    with pytest.raises(ConfigInvalidError):
        FontManifest(manifest).font("k")
