"""Migration runner (04 section 8): forward-only, transactional, checksummed."""

import shutil
from pathlib import Path
from typing import Any

import psycopg
import pytest

from amw_core.errors import ConfigInvalidError
from amw_core.tenancy import migrate as runner
from tests.pg_fixtures import MIGRATIONS

pytestmark = pytest.mark.integration


def test_discover_orders_and_hashes() -> None:
    files = runner.discover(MIGRATIONS)
    assert [m.version for m in files] == sorted(m.version for m in files)
    assert files[0].version == 1
    assert all(len(m.sha256) == 64 for m in files)


def test_discover_rejects_bad_names(tmp_path: Path) -> None:
    (tmp_path / "1_bad.sql").write_text("SELECT 1;")
    with pytest.raises(ConfigInvalidError):
        runner.discover(tmp_path)


def test_discover_rejects_duplicates(tmp_path: Path) -> None:
    (tmp_path / "0001_a.sql").write_text("SELECT 1;")
    (tmp_path / "0001_b.sql").write_text("SELECT 1;")
    with pytest.raises(ConfigInvalidError):
        runner.discover(tmp_path)


def test_rerun_applies_nothing(pg_dsn: str) -> None:
    assert runner.migrate(pg_dsn, MIGRATIONS) == []


def test_recorded_history_matches_files(admin: psycopg.Connection[tuple[Any, ...]]) -> None:
    known = runner.applied(admin)
    assert {v: s for v, (_, s) in known.items()} == {
        m.version: m.sha256 for m in runner.discover(MIGRATIONS)
    }


def test_changed_applied_file_is_refused(empty_dsn: str, tmp_path: Path) -> None:
    pg_dsn = empty_dsn
    for f in MIGRATIONS.glob("*.sql"):
        shutil.copy(f, tmp_path / f.name)
    runner.migrate(pg_dsn, tmp_path)
    first = sorted(tmp_path.glob("*.sql"))[0]
    first.write_text(first.read_text() + "\n-- edited\n")
    with pytest.raises(ConfigInvalidError, match="changed"):
        runner.migrate(pg_dsn, tmp_path)


def test_missing_applied_file_is_refused(empty_dsn: str, tmp_path: Path) -> None:
    pg_dsn = empty_dsn
    for f in MIGRATIONS.glob("*.sql"):
        shutil.copy(f, tmp_path / f.name)
    runner.migrate(pg_dsn, tmp_path)
    sorted(tmp_path.glob("*.sql"))[0].unlink()
    with pytest.raises(ConfigInvalidError, match="missing"):
        runner.migrate(pg_dsn, tmp_path)


def test_failed_migration_leaves_nothing(empty_dsn: str, tmp_path: Path) -> None:
    pg_dsn = empty_dsn
    for f in MIGRATIONS.glob("*.sql"):
        shutil.copy(f, tmp_path / f.name)
    (tmp_path / "9999_broken.sql").write_text(
        "CREATE TABLE amw_runner_probe (id int); SELECT * FROM no_such_table;"
    )
    with pytest.raises(psycopg.errors.UndefinedTable):
        runner.migrate(pg_dsn, tmp_path)
    with psycopg.connect(pg_dsn) as conn:
        assert conn.execute("SELECT to_regclass('amw_runner_probe')").fetchone() == (None,)
        assert 9999 not in runner.applied(conn)


def test_older_pending_file_is_refused(empty_dsn: str, tmp_path: Path) -> None:
    pg_dsn = empty_dsn
    for f in MIGRATIONS.glob("*.sql"):
        shutil.copy(f, tmp_path / f.name)
    (tmp_path / "9998_probe.sql").write_text("SELECT 1;")
    runner.migrate(pg_dsn, tmp_path)
    (tmp_path / "9997_late.sql").write_text("SELECT 1;")
    with pytest.raises(ConfigInvalidError, match="older"):
        runner.migrate(pg_dsn, tmp_path)


def test_main_prints_nothing_when_current(pg_dsn: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert runner.main(["--dsn", pg_dsn, "--dir", str(MIGRATIONS)]) == 0
    assert capsys.readouterr().out == ""
