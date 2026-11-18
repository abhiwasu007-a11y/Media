"""The secret-scan gate must catch what it claims to catch and ignore ordinary text."""

from pathlib import Path

from scripts.secret_scan import scan


def test_detects_private_key(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("-----BEGIN " + "PRIVATE KEY-----\nabc\n", encoding="utf-8")
    assert scan(f)


def test_detects_assigned_secret(tmp_path: Path) -> None:
    f = tmp_path / "b.py"
    fake_value = "abcdefghijklmnopqrstuvwxyz" + "012345"
    f.write_text(f'API_KEY = "{fake_value}"\n', encoding="utf-8")
    assert scan(f)


def test_ignores_ordinary_text(tmp_path: Path) -> None:
    f = tmp_path / "c.md"
    f.write_text("Keys come only through the secret mechanism.\n", encoding="utf-8")
    assert not scan(f)
