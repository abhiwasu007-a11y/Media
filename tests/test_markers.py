"""Markers of 27 section 3 are registered and every used marker is registered."""

from pathlib import Path

from scripts.check_markers import REQUIRED, check, registered

ROOT = Path(__file__).resolve().parent.parent


def test_required_markers_registered() -> None:
    assert registered(ROOT / "pyproject.toml") >= REQUIRED


def test_repo_has_no_unregistered_markers() -> None:
    assert check(ROOT) == []


def test_detects_unregistered_marker(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\nmarkers = ["unit: x"]\n', encoding="utf-8"
    )
    (tmp_path / "test_a.py").write_text("@pytest.mark." + "mystery\ndef test_a(): ...\n")
    problems = check(tmp_path)
    assert any("mystery" in p for p in problems)
    assert any("required marker not registered: e2e" in p for p in problems)
