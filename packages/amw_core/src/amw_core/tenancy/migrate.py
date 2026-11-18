"""Forward-only SQL migration runner (04 section 8; small and dependency-free beyond psycopg).

* Files: ``migrations/NNNN_<snake_name>.sql`` at the repository root, applied in number order.
* Each file runs in **one transaction** together with its bookkeeping row, under a transaction
  advisory lock, so concurrent runners serialise and a failed file leaves nothing behind.
* Checksummed: the SHA-256 of every applied file is stored; a changed, missing or renumbered file
  that was already applied is refused (``PERMANENT.CONFIG_INVALID``). There is no "down".
* The bookkeeping table ``amw_schema_migrations`` is GLOBAL (04 section 4: migration bookkeeping).

The runner is used by deploy (as ``amw_migrator``) and by the test suites. Credentials are never
passed here: the DSN carries no password and libpq reads the environment's secret mechanism.
"""

import argparse
import hashlib
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql

from amw_core.errors import ConfigInvalidError

_NAME = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")
_LOCK_KEY = 0x414D_574D  # "AMWM": one advisory lock for every runner of this database
BOOKKEEPING_TABLE = "amw_schema_migrations"
_TABLE = sql.Identifier(BOOKKEEPING_TABLE)


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    path: Path
    sha256: str

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")


def discover(directory: Path) -> list[Migration]:
    """Every migration file in ``directory`` in version order; refuses duplicates and bad names.

    Gaps in the numbering are allowed on purpose: the 3A lane split reserves 0001-0049 for lane L1a
    and 0050-0099 for lane L1b. What is refused is a *pending* file
    numbered below the applied head."""
    found: dict[int, Migration] = {}
    for path in sorted(directory.glob("*.sql")):
        match = _NAME.fullmatch(path.name)
        if match is None:
            raise ConfigInvalidError(f"migration file name not NNNN_name.sql: {path.name}")
        version = int(match["version"])
        if version in found:
            raise ConfigInvalidError(f"duplicate migration number {version:04d}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        found[version] = Migration(version, match["name"], path, digest)
    return [found[v] for v in sorted(found)]


def _ensure_bookkeeping(conn: psycopg.Connection[tuple[object, ...]]) -> None:
    conn.execute(
        sql.SQL(
            "CREATE TABLE IF NOT EXISTS {} ("
            " version int PRIMARY KEY, name text NOT NULL, sha256 text NOT NULL,"
            " applied_at timestamptz NOT NULL DEFAULT now())"
        ).format(_TABLE)
    )
    conn.execute(sql.SQL("REVOKE ALL ON {} FROM PUBLIC").format(_TABLE))


def applied(conn: psycopg.Connection[tuple[object, ...]]) -> dict[int, tuple[str, str]]:
    """``{version: (name, sha256)}`` of the migrations recorded in this database."""
    exists = conn.execute("SELECT to_regclass(%s) IS NOT NULL", (BOOKKEEPING_TABLE,)).fetchone()
    if not exists or not exists[0]:
        return {}
    rows = conn.execute(sql.SQL("SELECT version, name, sha256 FROM {}").format(_TABLE)).fetchall()
    return {int(str(v)): (str(n), str(s)) for v, n, s in rows}


def _verify_history(known: dict[int, tuple[str, str]], files: Sequence[Migration]) -> None:
    by_version = {m.version: m for m in files}
    for version, (name, digest) in sorted(known.items()):
        current = by_version.get(version)
        if current is None:
            raise ConfigInvalidError(f"applied migration {version:04d}_{name} is missing")
        if current.name != name or current.sha256 != digest:
            raise ConfigInvalidError(
                f"applied migration {version:04d}_{name} was changed (forward-only: add a new file)"
            )
    pending = [m.version for m in files if m.version not in known]
    if known and pending and min(pending) < max(known):
        raise ConfigInvalidError(
            f"migration {min(pending):04d} is older than the applied head {max(known):04d}"
        )


def migrate(conninfo: str, directory: Path) -> list[Migration]:
    """Apply every pending migration of ``directory``; returns the ones applied now."""
    files = discover(directory)
    done: list[Migration] = []
    with psycopg.connect(conninfo, autocommit=True) as conn:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_KEY,))
            _ensure_bookkeeping(conn)
            _verify_history(applied(conn), files)
        for migration in files:
            with conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_KEY,))
                _ensure_bookkeeping(conn)
                known = applied(conn)
                _verify_history(known, files)
                if migration.version in known:
                    continue
                conn.execute(migration.sql.encode("utf-8"))
                conn.execute("RESET ROLE")
                conn.execute(
                    sql.SQL("INSERT INTO {} (version, name, sha256) VALUES (%s, %s, %s)").format(
                        _TABLE
                    ),
                    (migration.version, migration.name, migration.sha256),
                )
                done.append(migration)
    return done


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m amw_core.tenancy.migrate")
    parser.add_argument("--dsn", required=True, help="libpq connection string without password")
    parser.add_argument("--dir", type=Path, default=Path("migrations"))
    args = parser.parse_args(argv)
    for migration in migrate(args.dsn, args.dir):
        sys.stdout.write(f"applied {migration.version:04d}_{migration.name}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
