"""Scaffold smoke test: every workspace package imports and the interpreter pin holds."""

import importlib
import sys

import pytest

PACKAGES = [
    "amw_core",
    "amw_adapters",
    "amw_orchestrator",
    "agent_04_research_knowledge",
    "agent_05_scriptwriter",
    "agent_06_fact_checker",
    "agent_07_voice_production",
    "agent_08_visual_assets",
    "agent_09_video_director",
]


def test_python_minor_is_pinned() -> None:
    assert sys.version_info[:2] == (3, 14)


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name: str) -> None:
    assert importlib.import_module(name).__doc__
