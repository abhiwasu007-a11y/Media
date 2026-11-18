-- 0008 YouTube access, tokens, data keys (04 section 5.19) and quota (5.20). Unused in 3A
-- (3A_SLICE_SPEC section 2.2) but created now so the data model needs no tenancy retro-fit.
SET LOCAL ROLE amw_owner;

CREATE TABLE gcp_projects (
  id uuid PRIMARY KEY,
  org_id uuid REFERENCES organisations (id),
  ownership text NOT NULL CHECK (ownership IN ('PLATFORM', 'CLIENT_OWNED')),
  project_label text NOT NULL,
  oauth_verification_status text NOT NULL CHECK (oauth_verification_status IN ('NOT_STARTED', 'IN_REVIEW', 'PASSED', 'FAILED')),
  api_audit_status text NOT NULL CHECK (api_audit_status IN ('NOT_STARTED', 'IN_REVIEW', 'PASSED', 'FAILED')),
  quota_limits jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  CONSTRAINT gcp_projects_platform_ownership CHECK ((ownership = 'PLATFORM') = (org_id IS NULL))
);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON gcp_projects
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_catalogue_table('gcp_projects', 'mutable');

ALTER TABLE channels ADD FOREIGN KEY (gcp_project_id) REFERENCES gcp_projects (id);
ALTER TABLE publications ADD FOREIGN KEY (gcp_project_id) REFERENCES gcp_projects (id);

CREATE TABLE tenant_data_keys (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  wrapped_key bytea NOT NULL,
  kek_ref text NOT NULL,
  algorithm text NOT NULL,
  status text NOT NULL CHECK (status IN ('ACTIVE', 'RETIRED', 'DESTROYED')),
  rotated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, id)
);
SELECT amw_setup_tenant_table('tenant_data_keys', 'mutable');

CREATE TABLE oauth_tokens (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  channel_id uuid NOT NULL,
  gcp_project_id uuid NOT NULL REFERENCES gcp_projects (id),
  scopes text[] NOT NULL,
  granted_by_user_id uuid NOT NULL REFERENCES users (id),
  access_token_ct bytea,
  access_token_nonce bytea,
  refresh_token_ct bytea NOT NULL,
  refresh_token_nonce bytea NOT NULL,
  data_key_id uuid NOT NULL,
  expires_at timestamptz,
  status text NOT NULL CHECK (status IN ('ACTIVE', 'REFRESH_FAILED', 'REVOKED', 'EXPIRED')),
  last_refreshed_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  FOREIGN KEY (org_id, channel_id) REFERENCES channels (org_id, id),
  FOREIGN KEY (org_id, data_key_id) REFERENCES tenant_data_keys (org_id, id)
);
CREATE UNIQUE INDEX oauth_tokens_one_active ON oauth_tokens (org_id, channel_id)
  WHERE status = 'ACTIVE';
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON oauth_tokens
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('oauth_tokens', 'mutable');
-- Column grants: the encrypted token columns are readable only by amw_publisher (04 section 3.1).
REVOKE SELECT ON oauth_tokens FROM amw_app, amw_readonly;
GRANT SELECT (id, org_id, channel_id, gcp_project_id, scopes, granted_by_user_id, data_key_id,
              expires_at, status, last_refreshed_at, revoked_at, created_at, updated_at,
              row_version)
  ON oauth_tokens TO amw_app, amw_readonly;

-- Updated only through amw_quota_reserve / amw_quota_release (not in 3A): read-only for the
-- application roles.
CREATE TABLE quota_usage (
  org_id uuid REFERENCES organisations (id),
  gcp_project_id uuid NOT NULL REFERENCES gcp_projects (id),
  pt_date date NOT NULL,
  bucket text NOT NULL CHECK (bucket IN ('VIDEO_UPLOADS', 'SEARCH', 'BATCH_GET_STATS', 'DEFAULT')),
  units_used bigint NOT NULL,
  units_reserved bigint NOT NULL,
  units_limit bigint NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (gcp_project_id, pt_date, bucket)
);
SELECT amw_setup_catalogue_table('quota_usage', 'read_only');
