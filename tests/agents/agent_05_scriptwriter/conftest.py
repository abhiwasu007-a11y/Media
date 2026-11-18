"""No network in Agent 05 tests (27 section 8.1): sockets are blocked."""

import socket
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _block_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("network access is blocked in tests")

    monkeypatch.setattr(socket.socket, "connect", refuse)
