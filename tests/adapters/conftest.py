"""Every adapter test runs with outbound networking disabled (27 section 8: no network in tests)."""

import json
import socket
from pathlib import Path

import pytest

from amw_runtime.config import DEFAULT_CONFIG_FILE


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_a: object, **_k: object) -> None:
        raise AssertionError("adapter test attempted a network connection")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture(autouse=True)
def packaged_with_render_minutes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The shipped runtime data has no render duration (REQUIRES REVIEW, owner item), so a
    REAL_RUN preflight cannot pass on it yet. Tests load a packaged-style file with 60 minutes
    through the one packaged loader (same approach as tests/runtime)."""
    data = json.loads(DEFAULT_CONFIG_FILE.read_text(encoding="utf-8"))
    data["render"]["max_duration_minutes"] = 60
    path = tmp_path / "packaged_rc.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr("amw_runtime.config.DEFAULT_CONFIG_FILE", path)
