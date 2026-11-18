-- 0001 database roles (04 section 3.1), schema privileges and extensions. Kept apart from the
-- tables so role changes (e.g. the evidence verifier role of contract pass 3) land as their own
-- migration. Needs a bootstrap role with CREATEROLE (deploy: the DBA; tests: the superuser).
-- Lane split (3A build): migrations 0001-0049 are lane L1a, 0050-0099 lane L1b (audit_log,
-- audit_chain_heads, cost_ledger, budgets, budget_reservations).

-- ---------------------------------------------------------------------------------------------
-- 3.1 Roles (cluster-wide, created idempotently; attributes re-asserted on every run).
-- ---------------------------------------------------------------------------------------------
DO $roles$
DECLARE
  r record;
BEGIN
  FOR r IN SELECT * FROM (VALUES
      ('amw_owner', false), ('amw_migrator', true), ('amw_app', true), ('amw_publisher', true),
      ('amw_auth', true), ('amw_readonly', true), ('amw_sysfn', false)) AS t(name, login)
  LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r.name) THEN
      BEGIN
        EXECUTE format('CREATE ROLE %I %s', r.name, CASE WHEN r.login THEN 'LOGIN' ELSE 'NOLOGIN' END);
      EXCEPTION WHEN duplicate_object THEN
        NULL;  -- created concurrently by another database of the same cluster
      END;
    END IF;
  END LOOP;
END
$roles$;

ALTER ROLE amw_owner NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
ALTER ROLE amw_migrator LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
ALTER ROLE amw_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
ALTER ROLE amw_publisher LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
ALTER ROLE amw_auth LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
ALTER ROLE amw_readonly LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
ALTER ROLE amw_sysfn NOLOGIN NOSUPERUSER BYPASSRLS NOCREATEROLE NOCREATEDB;

GRANT amw_owner TO amw_migrator;
-- The owner may hand system functions to amw_sysfn (ALTER FUNCTION ... OWNER needs SET ROLE);
-- INHERIT FALSE: amw_owner never uses amw_sysfn's rights implicitly. No login role is a direct member.
GRANT amw_sysfn TO amw_owner WITH INHERIT FALSE;

CREATE EXTENSION IF NOT EXISTS citext;

GRANT USAGE, CREATE ON SCHEMA public TO amw_owner;
GRANT USAGE, CREATE ON SCHEMA public TO amw_sysfn;
GRANT USAGE ON SCHEMA public TO amw_app, amw_publisher, amw_auth, amw_readonly;

