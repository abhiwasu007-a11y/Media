"""PostgreSQL fixtures for the DB adapter suites (tests/pg_fixtures.py; skips without
``AMW_TEST_DATABASE_URL``)."""

from tests.pg_fixtures import admin, pg_dsn, tenancy, tenant_a, tenant_b

__all__ = ["admin", "pg_dsn", "tenancy", "tenant_a", "tenant_b"]
