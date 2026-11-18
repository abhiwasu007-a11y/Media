-- 0003 identity and controls (04 section 5.1): user_auth_refs, user_sessions (GLOBAL, RLS self),
-- invitations, org_controls (TENANT), platform_controls (GLOBAL).
SET LOCAL ROLE amw_owner;

CREATE TABLE user_auth_refs (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users (id),
  provider text NOT NULL CHECK (provider IN ('LOCAL_PASSWORD', 'GOOGLE', 'SAML', 'OIDC')),
  external_subject text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (provider, external_subject)
);
ALTER TABLE user_auth_refs ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_auth_refs FORCE ROW LEVEL SECURITY;
CREATE POLICY self_only ON user_auth_refs
  USING (user_id = amw_current_user()) WITH CHECK (user_id = amw_current_user());
REVOKE ALL ON user_auth_refs FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON user_auth_refs TO amw_auth;

CREATE TABLE user_sessions (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users (id),
  active_org_id uuid REFERENCES organisations (id),
  mfa_verified_at timestamptz,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  user_agent_hash bytea CHECK (octet_length(user_agent_hash) = 32),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX user_sessions_user_expiry ON user_sessions (user_id, expires_at);
ALTER TABLE user_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY self_only ON user_sessions
  USING (user_id = amw_current_user()) WITH CHECK (user_id = amw_current_user());
REVOKE ALL ON user_sessions FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON user_sessions TO amw_auth;

-- active_org_id must have an ACTIVE membership of the session's user (04 section 5.1). The
-- membership lives in a tenant table, so the check runs as amw_sysfn (identifier-only read).
CREATE FUNCTION amw_user_session_org_guard() RETURNS trigger
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
  AS $$
BEGIN
  IF NEW.active_org_id IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM memberships m
        WHERE m.org_id = NEW.active_org_id AND m.user_id = NEW.user_id AND m.status = 'ACTIVE') THEN
    RAISE EXCEPTION 'session organisation needs an ACTIVE membership' USING ERRCODE = 'AMW02';
  END IF;
  RETURN NEW;
END
$$;
GRANT SELECT ON memberships TO amw_sysfn;
ALTER FUNCTION amw_user_session_org_guard() OWNER TO amw_sysfn;
REVOKE ALL ON FUNCTION amw_user_session_org_guard() FROM PUBLIC;
CREATE TRIGGER user_session_org_guard BEFORE INSERT OR UPDATE OF active_org_id, user_id
  ON user_sessions FOR EACH ROW EXECUTE FUNCTION amw_user_session_org_guard();

CREATE TABLE invitations (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  email citext NOT NULL,
  role text NOT NULL CHECK (role IN ('PLATFORM_OWNER', 'ORG_OWNER', 'ORG_ADMIN', 'PRODUCER', 'REVIEWER_APPROVER', 'FINANCE', 'VIEWER', 'CLIENT_GUEST') AND role <> 'PLATFORM_OWNER'),
  token_hash bytea NOT NULL UNIQUE CHECK (octet_length(token_hash) = 32),
  state text NOT NULL CHECK (state IN ('PENDING', 'ACCEPTED', 'EXPIRED', 'REVOKED')),
  invited_by uuid NOT NULL REFERENCES users (id),
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id)
);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON invitations
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('invitations', 'mutable');

CREATE TABLE org_controls (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  key text NOT NULL CHECK (
    key ~ '^agent_enabled\.(agent_(0[1-9]|1[0-7])|svc_s(0[1-9]|1[0-3]))$'
    OR key IN ('production_schedule', 'daily_production_limit', 'publishing_enabled',
               'emergency_stop', 'ip_allowlist')),
  value jsonb NOT NULL,
  updated_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  UNIQUE (org_id, key)
);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON org_controls
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('org_controls', 'mutable');

-- Written only by PLATFORM_OWNER through amw_sysfn (04 section 5.1): amw_app reads only.
CREATE TABLE platform_controls (
  id uuid PRIMARY KEY,
  key text NOT NULL UNIQUE CHECK (key IN ('platform_emergency_stop', 'admission_paused')),
  value jsonb NOT NULL,
  updated_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1
);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON platform_controls
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
REVOKE ALL ON platform_controls FROM PUBLIC;
GRANT SELECT ON platform_controls TO amw_app, amw_publisher, amw_readonly;
