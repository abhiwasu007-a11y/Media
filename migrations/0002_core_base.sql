-- 0002 core base: tenant context, table helpers and the work / queue / state tables.
-- Sources: docs/v4/04_DATABASE_ARCHITECTURE.md sections 1-3, 5.1, 5.3, 5.4, 5.6, 5.7 (checkpoints),
-- 5.9; 03 section 11. Forward-only; the runner executes this file in one transaction.

-- Every object below is owned by amw_owner (FORCE RLS applies to it too, INF-11).
SET LOCAL ROLE amw_owner;

-- ---------------------------------------------------------------------------------------------
-- 3.2 Tenant context functions (fail closed: an unset setting matches no row).
-- ---------------------------------------------------------------------------------------------
CREATE FUNCTION amw_current_org() RETURNS uuid
  LANGUAGE sql STABLE
  AS $$ SELECT NULLIF(current_setting('app.org_id', true), '')::uuid $$;

CREATE FUNCTION amw_current_user() RETURNS uuid
  LANGUAGE sql STABLE
  AS $$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$;

-- ---------------------------------------------------------------------------------------------
-- Shared trigger functions.
-- ---------------------------------------------------------------------------------------------
-- Mut columns (04 section 2): updated_at follows every UPDATE.
CREATE FUNCTION amw_touch_updated_at() RETURNS trigger
  LANGUAGE plpgsql
  AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END
$$;

-- Append-only tables (04 section 1 rule 7): UPDATE / DELETE / TRUNCATE rejected for every role.
-- SQLSTATE AMW02 maps to PERMANENT.PERMISSION_DENIED in amw_core.tenancy.
CREATE FUNCTION amw_reject_modification() RETURNS trigger
  LANGUAGE plpgsql
  AS $$
BEGIN
  RAISE EXCEPTION 'append-only table %: % rejected', TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'AMW02';
END
$$;

-- ---------------------------------------------------------------------------------------------
-- Table set-up helpers (one place for the RLS + grants pattern of 04 sections 3.3-3.5).
-- mode: 'mutable' (SELECT, INSERT, UPDATE), 'append_only' (SELECT, INSERT + reject trigger),
--       'mutable_delete' (SELECT, INSERT, UPDATE, DELETE), 'read_only' (SELECT).
-- ---------------------------------------------------------------------------------------------
CREATE FUNCTION amw_grant_table(t regclass, mode text) RETURNS void
  LANGUAGE plpgsql
  AS $$
DECLARE
  privs text;
BEGIN
  privs := CASE mode
    WHEN 'mutable' THEN 'SELECT, INSERT, UPDATE'
    WHEN 'mutable_delete' THEN 'SELECT, INSERT, UPDATE, DELETE'
    WHEN 'append_only' THEN 'SELECT, INSERT'
    WHEN 'read_only' THEN 'SELECT'
  END;
  IF privs IS NULL THEN
    RAISE EXCEPTION 'unknown grant mode %', mode;
  END IF;
  EXECUTE format('REVOKE ALL ON %s FROM PUBLIC', t);
  EXECUTE format('GRANT %s ON %s TO amw_app, amw_publisher', privs, t);
  EXECUTE format('GRANT SELECT ON %s TO amw_readonly', t);
  IF mode = 'append_only' THEN
    EXECUTE format(
      'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %s FOR EACH ROW EXECUTE FUNCTION amw_reject_modification()',
      'append_only_row', t);
    EXECUTE format(
      'CREATE TRIGGER %I BEFORE TRUNCATE ON %s FOR EACH STATEMENT EXECUTE FUNCTION amw_reject_modification()',
      'append_only_truncate', t);
  END IF;
END
$$;

-- 3.4 Standard tenant policy (ENABLE + FORCE + tenant_isolation on org_id).
CREATE FUNCTION amw_setup_tenant_table(t regclass, mode text) RETURNS void
  LANGUAGE plpgsql
  AS $$
BEGIN
  EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', t);
  EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY', t);
  EXECUTE format(
    'CREATE POLICY tenant_isolation ON %s USING (org_id = amw_current_org()) WITH CHECK (org_id = amw_current_org())',
    t);
  PERFORM amw_grant_table(t, mode);
END
$$;

-- 3.5 Shared-catalogue policy (nullable org_id: NULL rows readable by all, writable by none).
CREATE FUNCTION amw_setup_catalogue_table(t regclass, mode text) RETURNS void
  LANGUAGE plpgsql
  AS $$
BEGIN
  EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', t);
  EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY', t);
  EXECUTE format(
    'CREATE POLICY catalogue_read ON %s FOR SELECT USING (org_id IS NULL OR org_id = amw_current_org())', t);
  EXECUTE format(
    'CREATE POLICY catalogue_write ON %s FOR ALL USING (org_id = amw_current_org()) WITH CHECK (org_id = amw_current_org())',
    t);
  PERFORM amw_grant_table(t, mode);
END
$$;

-- RLS for one partition of a partitioned tenant table (a partition queried directly would
-- otherwise not apply the parent's policies). No grants: partitions are reached via the parent.
CREATE FUNCTION amw_setup_tenant_partition(t regclass) RETURNS void
  LANGUAGE plpgsql
  AS $$
BEGIN
  EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', t);
  EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY', t);
  EXECUTE format(
    'CREATE POLICY tenant_isolation ON %s USING (org_id = amw_current_org()) WITH CHECK (org_id = amw_current_org())',
    t);
  EXECUTE format('REVOKE ALL ON %s FROM PUBLIC', t);
END
$$;

REVOKE ALL ON FUNCTION amw_grant_table(regclass, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION amw_setup_tenant_table(regclass, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION amw_setup_catalogue_table(regclass, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION amw_setup_tenant_partition(regclass) FROM PUBLIC;

-- ---------------------------------------------------------------------------------------------
-- 5.1 organisations (TENANT, policy on id), users (GLOBAL, RLS self/membership), memberships,
--     workspaces, channels.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE organisations (
  id uuid PRIMARY KEY,
  name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),
  slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9-]{3,63}$'),
  kind text NOT NULL CHECK (kind IN ('PLATFORM_OWNER', 'CLIENT', 'AGENCY')),
  status text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'SUSPENDED', 'OFFBOARDING', 'DELETED')),
  tier text NOT NULL DEFAULT 'TIER_0' CHECK (tier IN ('TIER_0', 'TIER_1', 'TIER_2', 'TIER_3')),
  is_platform_owner boolean NOT NULL DEFAULT false,
  display_timezone text NOT NULL DEFAULT 'Asia/Kolkata',
  data_location_note text,
  plan_id uuid,  -- FK -> plans is added with the T2 plans table
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX organisations_one_platform_owner
  ON organisations (is_platform_owner) WHERE is_platform_owner;
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON organisations
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
ALTER TABLE organisations ENABLE ROW LEVEL SECURITY;
ALTER TABLE organisations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON organisations
  USING (id = amw_current_org()) WITH CHECK (id = amw_current_org());
REVOKE ALL ON organisations FROM PUBLIC;
-- Creation only through an audited platform-owner function (04 section 5.1): no INSERT grant.
GRANT SELECT, UPDATE ON organisations TO amw_app, amw_publisher;
GRANT SELECT ON organisations TO amw_readonly, amw_auth;

CREATE TABLE users (
  id uuid PRIMARY KEY,
  email citext NOT NULL UNIQUE,
  display_name text NOT NULL,
  status text NOT NULL CHECK (status IN ('ACTIVE', 'DISABLED', 'DELETED')),
  mfa_enrolled boolean NOT NULL DEFAULT false,
  last_login_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1
);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON users
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();

CREATE TABLE memberships (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  user_id uuid NOT NULL REFERENCES users (id),
  role text NOT NULL CHECK (role IN ('PLATFORM_OWNER', 'ORG_OWNER', 'ORG_ADMIN', 'PRODUCER', 'REVIEWER_APPROVER', 'FINANCE', 'VIEWER', 'CLIENT_GUEST')),
  status text NOT NULL CHECK (status IN ('INVITED', 'ACTIVE', 'SUSPENDED', 'REMOVED')),
  workspace_ids uuid[],
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  UNIQUE (org_id, user_id)
);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON memberships
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('memberships', 'mutable');

-- PLATFORM_OWNER only in the organisation with is_platform_owner (04 section 5.1).
CREATE FUNCTION amw_membership_role_guard() RETURNS trigger
  LANGUAGE plpgsql
  AS $$
BEGIN
  IF NEW.role = 'PLATFORM_OWNER' AND NOT EXISTS (
       SELECT 1 FROM organisations o WHERE o.id = NEW.org_id AND o.is_platform_owner) THEN
    RAISE EXCEPTION 'PLATFORM_OWNER membership only in the platform owner organisation'
      USING ERRCODE = 'AMW02';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER membership_role_guard BEFORE INSERT OR UPDATE OF role, org_id ON memberships
  FOR EACH ROW EXECUTE FUNCTION amw_membership_role_guard();

-- users: GLOBAL identity; RLS restricts reads to self or members of the current org; writes
-- only by amw_auth for the user in app.user_id (ADR-003 decides the auth component).
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
CREATE POLICY users_visible ON users FOR SELECT
  USING (id = amw_current_user() OR EXISTS (
    SELECT 1 FROM memberships m WHERE m.user_id = users.id AND m.org_id = amw_current_org()));
CREATE POLICY users_auth_write ON users FOR ALL TO amw_auth
  USING (id = amw_current_user()) WITH CHECK (id = amw_current_user());
REVOKE ALL ON users FROM PUBLIC;
GRANT SELECT ON users TO amw_app, amw_publisher, amw_readonly;
GRANT SELECT, INSERT, UPDATE ON users TO amw_auth;

CREATE TABLE workspaces (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  name text NOT NULL,
  status text NOT NULL CHECK (status IN ('ACTIVE', 'ARCHIVED')),
  white_label_ref text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  UNIQUE (org_id, name)
);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON workspaces
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('workspaces', 'mutable');

CREATE TABLE channels (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  workspace_id uuid NOT NULL,
  platform text NOT NULL CHECK (platform IN ('YOUTUBE')),
  external_channel_id text,
  title text NOT NULL,
  language text NOT NULL,
  category text NOT NULL,
  compliance_profile_id uuid,  -- TFK -> compliance_profiles (0003)
  brand_kit_id uuid,           -- TFK -> brand_kits (T0+, added with Agent 08 / S11)
  gcp_project_id uuid,         -- FK -> gcp_projects (0007)
  status text NOT NULL CHECK (status IN ('DRAFT', 'CONNECTED', 'NEEDS_REAUTH', 'PAUSED', 'DISCONNECTED')),
  production_window jsonb,
  connected_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  UNIQUE (org_id, platform, external_channel_id),
  FOREIGN KEY (org_id, workspace_id) REFERENCES workspaces (org_id, id),
  CONSTRAINT channels_profile_before_connected
    CHECK (status <> 'CONNECTED' OR compliance_profile_id IS NOT NULL)
);
CREATE INDEX channels_org_workspace ON channels (org_id, workspace_id);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON channels
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('channels', 'mutable');

-- ---------------------------------------------------------------------------------------------
-- 5.2 production_types (GLOBAL registry rows, immutable; seeded by migrations).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE production_types (
  id uuid PRIMARY KEY,
  key text NOT NULL CHECK (key IN ('CHANNEL_LONG_FORM', 'SHORTS', 'AD_SPOT', 'EXPLAINER_CORPORATE_TRAINING', 'ECOMMERCE_PRODUCT', 'DUBBING_LOCALISATION')),
  version int NOT NULL CHECK (version >= 1),
  status text NOT NULL CHECK (status IN ('PLANNED', 'IN_DEVELOPMENT', 'IMPLEMENTED', 'TESTED', 'PRODUCTION_READY')),
  tier text NOT NULL CHECK (tier IN ('TIER_0', 'TIER_1', 'TIER_2', 'TIER_3')),
  record jsonb NOT NULL,
  record_sha256 bytea NOT NULL CHECK (octet_length(record_sha256) = 32),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (key, version)
);
CREATE TRIGGER immutable_row BEFORE UPDATE OR DELETE ON production_types
  FOR EACH ROW EXECUTE FUNCTION amw_reject_modification();
REVOKE ALL ON production_types FROM PUBLIC;
GRANT SELECT ON production_types TO amw_app, amw_publisher, amw_readonly;

-- ---------------------------------------------------------------------------------------------
-- 5.3 projects, jobs, tasks, task_dependencies, task_attempts.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE projects (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  workspace_id uuid NOT NULL,
  channel_id uuid,
  name text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('SERIES', 'CAMPAIGN', 'CLIENT_ORDER', 'INTERNAL')),
  status text NOT NULL CHECK (status IN ('ACTIVE', 'ARCHIVED')),
  default_production_type text CHECK (default_production_type IN ('CHANNEL_LONG_FORM', 'SHORTS', 'AD_SPOT', 'EXPLAINER_CORPORATE_TRAINING', 'ECOMMERCE_PRODUCT', 'DUBBING_LOCALISATION')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  FOREIGN KEY (org_id, workspace_id) REFERENCES workspaces (org_id, id),
  FOREIGN KEY (org_id, channel_id) REFERENCES channels (org_id, id)
);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON projects
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('projects', 'mutable');

CREATE TABLE jobs (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  workspace_id uuid NOT NULL,
  project_id uuid,
  channel_id uuid,
  parent_job_id uuid,
  production_type_key text NOT NULL CHECK (production_type_key IN ('CHANNEL_LONG_FORM', 'SHORTS', 'AD_SPOT', 'EXPLAINER_CORPORATE_TRAINING', 'ECOMMERCE_PRODUCT', 'DUBBING_LOCALISATION')),
  production_type_version int NOT NULL,
  language text NOT NULL,
  state text NOT NULL DEFAULT 'PENDING' CHECK (state IN ('PENDING', 'VALIDATING', 'QUEUED', 'RUNNING', 'CHECKPOINTED', 'COMPLETED', 'FAILED', 'DEAD_LETTER', 'CANCELLED')),
  state_version int NOT NULL DEFAULT 1,
  state_changed_at timestamptz NOT NULL DEFAULT now(),
  outcome text CHECK (outcome IN ('PUBLISHED', 'DELIVERED', 'BLOCKED_COMPLIANCE', 'REJECTED_BY_APPROVER', 'NO_DELIVERABLE')),
  priority smallint NOT NULL CHECK (priority BETWEEN 0 AND 4),
  deadline timestamptz,
  correlation_id uuid NOT NULL,
  idempotency_key text NOT NULL CHECK (idempotency_key ~ '^idk_[0-9a-f]{64}$'),
  requested_by text NOT NULL,
  input_ref text,
  monetized_destination boolean NOT NULL DEFAULT true,
  task_count int NOT NULL DEFAULT 0,
  cost_estimate_micros bigint NOT NULL DEFAULT 0,
  cost_verified_micros bigint NOT NULL DEFAULT 0,
  currency char(3) NOT NULL,
  failed_task_id uuid,  -- TFK -> tasks (below)
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  UNIQUE (org_id, idempotency_key),
  FOREIGN KEY (org_id, workspace_id) REFERENCES workspaces (org_id, id),
  FOREIGN KEY (org_id, project_id) REFERENCES projects (org_id, id),
  FOREIGN KEY (org_id, channel_id) REFERENCES channels (org_id, id),
  FOREIGN KEY (org_id, parent_job_id) REFERENCES jobs (org_id, id),
  FOREIGN KEY (production_type_key, production_type_version)
    REFERENCES production_types (key, version),
  CONSTRAINT jobs_outcome_iff_completed CHECK ((state = 'COMPLETED') = (outcome IS NOT NULL))
);
CREATE INDEX jobs_org_live_state ON jobs (org_id, state)
  WHERE state NOT IN ('COMPLETED', 'CANCELLED');
CREATE INDEX jobs_org_channel_created ON jobs (org_id, channel_id, created_at DESC);
CREATE INDEX jobs_org_correlation ON jobs (org_id, correlation_id);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON jobs
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('jobs', 'mutable');

CREATE TABLE tasks (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  job_id uuid NOT NULL,
  task_type text NOT NULL
    CHECK (task_type ~ '^(agent_(0[1-9]|1[0-7])|svc_s(0[1-9]|1[0-3]))\.[a-z0-9_]+$'),
  agent_id text NOT NULL,
  iteration int NOT NULL DEFAULT 0,
  is_required boolean NOT NULL DEFAULT true,
  state text NOT NULL DEFAULT 'PENDING' CHECK (state IN ('PENDING', 'VALIDATING', 'QUEUED', 'RUNNING', 'CHECKPOINTED', 'RETRY_WAIT', 'COMPLETED', 'FAILED', 'DEAD_LETTER', 'CANCELLED')),
  wait_reason text CHECK (wait_reason IN ('DRAIN', 'AWAITING_APPROVAL', 'AWAITING_QUOTA', 'AWAITING_BUDGET', 'AWAITING_EXTERNAL', 'OPERATOR_PAUSE')),
  state_version int NOT NULL DEFAULT 1,
  state_changed_at timestamptz NOT NULL DEFAULT now(),
  priority smallint NOT NULL CHECK (priority BETWEEN 0 AND 4),
  resource_class text NOT NULL CHECK (resource_class IN ('LIGHT', 'AI_IO', 'HEAVY_CPU', 'PUBLISH')),
  required_capabilities text[] NOT NULL CHECK (required_capabilities <@ ARRAY['llm', 'tts', 'image_gen', 'video_gen', 'stock_search', 'music_search', 'render_ffmpeg', 'media_probe', 'doc_extract', 'web_fetch', 'publish_youtube', 'file_delivery', 'analytics_ingest', 'notify_email']::text[]),
  idempotency_key text NOT NULL CHECK (idempotency_key ~ '^idk_[0-9a-f]{64}$'),
  input_ref text,
  input_sha256 bytea,
  output_ref text,
  output_sha256 bytea,
  input_schema_version text,
  payload_schema text NOT NULL,
  payload_schema_version text NOT NULL,
  resource_budget jsonb NOT NULL,
  attempt_count int NOT NULL DEFAULT 0,
  max_attempts int NOT NULL CHECK (max_attempts BETWEEN 1 AND 10),
  next_attempt_at timestamptz,
  deadline timestamptz,
  cancel_requested_at timestamptz,
  cancel_reason text,
  resume_checkpoint_id uuid,  -- TFK -> checkpoints (below)
  approval_id uuid,           -- TFK -> approvals (0006)
  error_code text,
  error_class text CHECK (error_class IN ('TEMPORARY', 'PERMANENT', 'RESOURCE', 'AGENT', 'INFRASTRUCTURE', 'PUBLISHING')),
  last_error jsonb,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  UNIQUE (org_id, idempotency_key),
  FOREIGN KEY (org_id, job_id) REFERENCES jobs (org_id, id),
  CONSTRAINT tasks_agent_is_type_prefix CHECK (agent_id = split_part(task_type, '.', 1)),
  CONSTRAINT tasks_wait_reason_iff_checkpointed
    CHECK ((state = 'CHECKPOINTED') = (wait_reason IS NOT NULL)),
  CONSTRAINT tasks_attempts_within_max CHECK (attempt_count <= max_attempts),
  CONSTRAINT tasks_retry_wait_needs_time CHECK (state <> 'RETRY_WAIT' OR next_attempt_at IS NOT NULL)
);
CREATE INDEX tasks_org_job ON tasks (org_id, job_id);
CREATE INDEX tasks_retry_due ON tasks (next_attempt_at) WHERE state = 'RETRY_WAIT';
CREATE INDEX tasks_stuck ON tasks (state_changed_at)
  WHERE state IN ('VALIDATING', 'FAILED', 'CHECKPOINTED');
SELECT amw_setup_tenant_table('tasks', 'mutable');

ALTER TABLE jobs ADD FOREIGN KEY (org_id, failed_task_id) REFERENCES tasks (org_id, id);

CREATE TABLE task_dependencies (
  org_id uuid NOT NULL REFERENCES organisations (id),
  task_id uuid NOT NULL,
  depends_on_task_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org_id, task_id, depends_on_task_id),
  FOREIGN KEY (org_id, task_id) REFERENCES tasks (org_id, id),
  FOREIGN KEY (org_id, depends_on_task_id) REFERENCES tasks (org_id, id),
  CHECK (task_id <> depends_on_task_id)
);
CREATE INDEX task_dependencies_depends_on ON task_dependencies (org_id, depends_on_task_id);
SELECT amw_setup_tenant_table('task_dependencies', 'mutable');

-- 5.4 workers (GLOBAL: logical names only, no host details).
CREATE TABLE workers (
  id uuid PRIMARY KEY,
  logical_name text NOT NULL UNIQUE,
  capabilities text[] NOT NULL CHECK (capabilities <@ ARRAY['llm', 'tts', 'image_gen', 'video_gen', 'stock_search', 'music_search', 'render_ffmpeg', 'media_probe', 'doc_extract', 'web_fetch', 'publish_youtube', 'file_delivery', 'analytics_ingest', 'notify_email']::text[]),
  resource_classes text[] NOT NULL CHECK (resource_classes <@ ARRAY['LIGHT', 'AI_IO', 'HEAVY_CPU', 'PUBLISH']::text[]),
  max_concurrency int NOT NULL CHECK (max_concurrency >= 1),
  status text NOT NULL CHECK (status IN ('STARTING', 'IDLE', 'BUSY', 'DRAINING', 'STOPPED', 'LOST')),
  software_version text NOT NULL,
  heartbeat_at timestamptz,
  drain_requested_at timestamptz,
  dedicated_org_id uuid REFERENCES organisations (id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1
);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON workers
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
REVOKE ALL ON workers FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON workers TO amw_app, amw_publisher;
GRANT SELECT ON workers TO amw_readonly;

CREATE TABLE task_attempts (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  task_id uuid NOT NULL,
  attempt_no int NOT NULL CHECK (attempt_no >= 1),
  worker_id uuid REFERENCES workers (id),
  result text NOT NULL DEFAULT 'RUNNING' CHECK (result IN ('SUCCEEDED', 'FAILED_RETRYABLE', 'FAILED_FINAL', 'SUSPENDED', 'LEASE_EXPIRED', 'CANCELLED', 'RUNNING')),
  started_at timestamptz NOT NULL,
  ended_at timestamptz,
  heartbeat_at timestamptz,
  duration_ms bigint,
  resumed_from_checkpoint_id uuid,  -- TFK -> checkpoints (below)
  is_replay boolean NOT NULL DEFAULT false,
  output_ref text,
  resource_usage jsonb,
  error_code text,
  error jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  UNIQUE (org_id, task_id, attempt_no),
  FOREIGN KEY (org_id, task_id) REFERENCES tasks (org_id, id)
);
SELECT amw_setup_tenant_table('task_attempts', 'mutable');

-- 5.7 checkpoints.
CREATE TABLE checkpoints (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  task_id uuid NOT NULL,
  attempt_id uuid NOT NULL,
  seq int NOT NULL,
  step_key text NOT NULL,
  state_ref text NOT NULL,
  state_sha256 bytea NOT NULL,
  completed_effects text[] NOT NULL,
  progress_ratio numeric(4, 3) CHECK (progress_ratio BETWEEN 0 AND 1),
  is_latest boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  UNIQUE (org_id, task_id, seq),
  FOREIGN KEY (org_id, task_id) REFERENCES tasks (org_id, id),
  FOREIGN KEY (org_id, attempt_id) REFERENCES task_attempts (org_id, id)
);
CREATE UNIQUE INDEX checkpoints_one_latest ON checkpoints (org_id, task_id) WHERE is_latest;
SELECT amw_setup_tenant_table('checkpoints', 'mutable');

ALTER TABLE tasks ADD FOREIGN KEY (org_id, resume_checkpoint_id) REFERENCES checkpoints (org_id, id);
ALTER TABLE task_attempts
  ADD FOREIGN KEY (org_id, resumed_from_checkpoint_id) REFERENCES checkpoints (org_id, id);

-- 5.4 task_queue (ADR-001 option A: own table).
CREATE TABLE task_queue (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  task_id uuid NOT NULL,
  job_id uuid NOT NULL,
  queue_name text NOT NULL CHECK (queue_name IN ('light', 'ai', 'render', 'publish')),
  status text NOT NULL DEFAULT 'READY' CHECK (status IN ('READY', 'CLAIMED', 'DONE', 'CANCELLED')),
  priority smallint NOT NULL CHECK (priority BETWEEN 0 AND 4),
  resource_class text NOT NULL CHECK (resource_class IN ('LIGHT', 'AI_IO', 'HEAVY_CPU', 'PUBLISH')),
  required_capabilities text[] NOT NULL CHECK (required_capabilities <@ ARRAY['llm', 'tts', 'image_gen', 'video_gen', 'stock_search', 'music_search', 'render_ffmpeg', 'media_probe', 'doc_extract', 'web_fetch', 'publish_youtube', 'file_delivery', 'analytics_ingest', 'notify_email']::text[]),
  scheduled_at timestamptz NOT NULL,
  claimed_at timestamptz,
  claimed_by uuid REFERENCES workers (id),
  lease_expires_at timestamptz,
  heartbeat_at timestamptz,
  fair_share_key text NOT NULL,
  resume_checkpoint_id uuid,
  envelope jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  FOREIGN KEY (org_id, task_id) REFERENCES tasks (org_id, id),
  FOREIGN KEY (org_id, job_id) REFERENCES jobs (org_id, id),
  FOREIGN KEY (org_id, resume_checkpoint_id) REFERENCES checkpoints (org_id, id),
  CONSTRAINT task_queue_lease_when_claimed CHECK (status <> 'CLAIMED' OR lease_expires_at IS NOT NULL)
);
CREATE INDEX task_queue_ready ON task_queue (queue_name, priority, scheduled_at)
  WHERE status = 'READY';
CREATE INDEX task_queue_claimed_lease ON task_queue (lease_expires_at) WHERE status = 'CLAIMED';
CREATE UNIQUE INDEX task_queue_one_live_per_task ON task_queue (org_id, task_id)
  WHERE status IN ('READY', 'CLAIMED');
SELECT amw_setup_tenant_table('task_queue', 'mutable');

-- 5.9 idempotency_keys.
CREATE TABLE idempotency_keys (
  org_id uuid NOT NULL REFERENCES organisations (id),
  key text NOT NULL CHECK (key ~ '^idk_[0-9a-f]{64}$'),
  scope text NOT NULL,
  request_sha256 bytea NOT NULL,
  status text NOT NULL CHECK (status IN ('IN_PROGRESS', 'COMPLETED', 'FAILED')),
  task_id uuid,
  result_ref text,
  locked_until timestamptz,
  completed_at timestamptz,
  expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org_id, key),
  FOREIGN KEY (org_id, task_id) REFERENCES tasks (org_id, id),
  CONSTRAINT idempotency_keys_never_expiring_scopes
    CHECK (expires_at IS NULL OR NOT (scope LIKE 'upload.%' OR scope LIKE 'publish.%'))
);
SELECT amw_setup_tenant_table('idempotency_keys', 'mutable');

-- ---------------------------------------------------------------------------------------------
-- 5.6 state_transitions (append-only, partitioned by month on occurred_at) and the GLOBAL
--     state_transition_rules seed (03 sections 11.3 and 11.5, one row per allowed pair).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE state_transitions (
  id uuid NOT NULL,
  org_id uuid NOT NULL REFERENCES organisations (id),
  entity_kind text NOT NULL CHECK (entity_kind IN ('JOB', 'TASK')),
  entity_id uuid NOT NULL,
  transition_id text NOT NULL CHECK (transition_id IN ('T01', 'T02', 'T03', 'T04', 'T05', 'T06', 'T07', 'T08', 'T09', 'T10', 'T11', 'T12', 'T13', 'T14', 'T15', 'T16', 'T17', 'T18', 'T19', 'T20', 'J01', 'J02', 'J03', 'J04', 'J05', 'J06', 'J07', 'J08', 'J09', 'J10', 'J11', 'J12')),
  from_state text,
  to_state text NOT NULL,
  wait_reason text CHECK (wait_reason IN ('DRAIN', 'AWAITING_APPROVAL', 'AWAITING_QUOTA', 'AWAITING_BUDGET', 'AWAITING_EXTERNAL', 'OPERATOR_PAUSE')),
  actor_kind text NOT NULL CHECK (actor_kind IN ('HUMAN', 'AGENT', 'SERVICE', 'SYSTEM')),
  actor_ref text NOT NULL,
  authority text NOT NULL,
  error_code text,
  state_version_after int NOT NULL,
  correlation_id uuid NOT NULL,
  occurred_at timestamptz NOT NULL,
  audit_seq bigint NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id, occurred_at)
) PARTITION BY RANGE (occurred_at);
CREATE INDEX state_transitions_org_entity ON state_transitions (org_id, entity_id, occurred_at);
SELECT amw_setup_tenant_table('state_transitions', 'append_only');
-- Monthly partitions are created ahead by the maintenance task (04 section 6); the default
-- partition keeps inserts working until then.
CREATE TABLE state_transitions_default PARTITION OF state_transitions DEFAULT;
SELECT amw_setup_tenant_partition('state_transitions_default');

CREATE TABLE state_transition_rules (
  entity_kind text NOT NULL CHECK (entity_kind IN ('JOB', 'TASK')),
  transition_id text NOT NULL CHECK (transition_id IN ('T01', 'T02', 'T03', 'T04', 'T05', 'T06', 'T07', 'T08', 'T09', 'T10', 'T11', 'T12', 'T13', 'T14', 'T15', 'T16', 'T17', 'T18', 'T19', 'T20', 'J01', 'J02', 'J03', 'J04', 'J05', 'J06', 'J07', 'J08', 'J09', 'J10', 'J11', 'J12')),
  from_state text,
  to_state text NOT NULL,
  allowed_actor_kinds text[] NOT NULL CHECK (allowed_actor_kinds <@ ARRAY['HUMAN', 'AGENT', 'SERVICE', 'SYSTEM']::text[]),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT state_transition_rules_unique_pair
    UNIQUE NULLS NOT DISTINCT (entity_kind, from_state, to_state, transition_id)
);
CREATE UNIQUE INDEX state_transition_rules_pk
  ON state_transition_rules (entity_kind, transition_id, coalesce(from_state, '∅'));
CREATE TRIGGER immutable_row BEFORE UPDATE OR DELETE ON state_transition_rules
  FOR EACH ROW EXECUTE FUNCTION amw_reject_modification();
REVOKE ALL ON state_transition_rules FROM PUBLIC;
GRANT SELECT ON state_transition_rules TO amw_app, amw_publisher, amw_readonly;

-- Actor kinds per 03 section 11.3 actor column: ORCH = agent_01 (AGENT); WKR = the executing
-- agent or service (AGENT, SERVICE); SCHED / REAP / DLQH = sys_* (SYSTEM); HUMAN (HUMAN).
-- Job rows (03 section 11.5) are derived in the transaction of the task transition that causes
-- them, so their actor kinds are those of the causing task rows (J05: T07 / T15; J06: T05 / T09;
-- J07: T04 / T08 / T19 superseded; J08: T06 / T11 / T13 / T16; J09: T14; J10: T17); J01 is a job
-- creation (calendar / brief by agents, sys_api / sys_operator, humans); J11 / J12 as written.
INSERT INTO state_transition_rules (entity_kind, transition_id, from_state, to_state, allowed_actor_kinds) VALUES
  ('TASK', 'T01', NULL, 'PENDING', ARRAY['AGENT']),
  ('TASK', 'T02', 'PENDING', 'VALIDATING', ARRAY['AGENT']),
  ('TASK', 'T03', 'VALIDATING', 'QUEUED', ARRAY['AGENT']),
  ('TASK', 'T04', 'VALIDATING', 'COMPLETED', ARRAY['AGENT']),
  ('TASK', 'T05', 'VALIDATING', 'CHECKPOINTED', ARRAY['AGENT']),
  ('TASK', 'T06', 'VALIDATING', 'FAILED', ARRAY['AGENT']),
  ('TASK', 'T07', 'QUEUED', 'RUNNING', ARRAY['AGENT', 'SERVICE']),
  ('TASK', 'T08', 'RUNNING', 'COMPLETED', ARRAY['AGENT', 'SERVICE']),
  ('TASK', 'T09', 'RUNNING', 'CHECKPOINTED', ARRAY['AGENT', 'SERVICE']),
  ('TASK', 'T10', 'RUNNING', 'RETRY_WAIT', ARRAY['AGENT', 'SERVICE', 'SYSTEM']),
  ('TASK', 'T11', 'RUNNING', 'FAILED', ARRAY['AGENT', 'SERVICE', 'SYSTEM']),
  ('TASK', 'T12', 'RETRY_WAIT', 'QUEUED', ARRAY['SYSTEM']),
  ('TASK', 'T13', 'RETRY_WAIT', 'FAILED', ARRAY['SYSTEM']),
  ('TASK', 'T14', 'FAILED', 'DEAD_LETTER', ARRAY['SYSTEM']),
  ('TASK', 'T15', 'CHECKPOINTED', 'QUEUED', ARRAY['SYSTEM', 'AGENT', 'HUMAN']),
  ('TASK', 'T16', 'CHECKPOINTED', 'FAILED', ARRAY['SYSTEM']),
  ('TASK', 'T17', 'DEAD_LETTER', 'QUEUED', ARRAY['HUMAN']),
  ('TASK', 'T18', 'DEAD_LETTER', 'CANCELLED', ARRAY['HUMAN']),
  ('TASK', 'T19', 'PENDING', 'CANCELLED', ARRAY['AGENT', 'HUMAN']),
  ('TASK', 'T19', 'VALIDATING', 'CANCELLED', ARRAY['AGENT', 'HUMAN']),
  ('TASK', 'T19', 'QUEUED', 'CANCELLED', ARRAY['AGENT', 'HUMAN']),
  ('TASK', 'T19', 'RETRY_WAIT', 'CANCELLED', ARRAY['AGENT', 'HUMAN']),
  ('TASK', 'T19', 'CHECKPOINTED', 'CANCELLED', ARRAY['AGENT', 'HUMAN']),
  ('TASK', 'T19', 'FAILED', 'CANCELLED', ARRAY['HUMAN']),
  ('TASK', 'T20', 'RUNNING', 'CANCELLED', ARRAY['AGENT', 'SERVICE', 'SYSTEM']),
  ('JOB', 'J01', NULL, 'PENDING', ARRAY['AGENT', 'SYSTEM', 'HUMAN']),
  ('JOB', 'J02', 'PENDING', 'VALIDATING', ARRAY['AGENT']),
  ('JOB', 'J03', 'VALIDATING', 'QUEUED', ARRAY['AGENT']),
  ('JOB', 'J04', 'VALIDATING', 'FAILED', ARRAY['AGENT']),
  ('JOB', 'J05', 'QUEUED', 'RUNNING', ARRAY['AGENT', 'SERVICE', 'SYSTEM', 'HUMAN']),
  ('JOB', 'J05', 'CHECKPOINTED', 'RUNNING', ARRAY['AGENT', 'SERVICE', 'SYSTEM', 'HUMAN']),
  ('JOB', 'J06', 'QUEUED', 'CHECKPOINTED', ARRAY['AGENT', 'SERVICE']),
  ('JOB', 'J06', 'RUNNING', 'CHECKPOINTED', ARRAY['AGENT', 'SERVICE']),
  ('JOB', 'J07', 'QUEUED', 'COMPLETED', ARRAY['AGENT', 'SERVICE', 'HUMAN']),
  ('JOB', 'J07', 'RUNNING', 'COMPLETED', ARRAY['AGENT', 'SERVICE', 'HUMAN']),
  ('JOB', 'J08', 'QUEUED', 'FAILED', ARRAY['AGENT', 'SERVICE', 'SYSTEM']),
  ('JOB', 'J08', 'RUNNING', 'FAILED', ARRAY['AGENT', 'SERVICE', 'SYSTEM']),
  ('JOB', 'J08', 'CHECKPOINTED', 'FAILED', ARRAY['AGENT', 'SERVICE', 'SYSTEM']),
  ('JOB', 'J09', 'FAILED', 'DEAD_LETTER', ARRAY['SYSTEM']),
  ('JOB', 'J10', 'DEAD_LETTER', 'RUNNING', ARRAY['HUMAN']),
  ('JOB', 'J11', 'DEAD_LETTER', 'CANCELLED', ARRAY['HUMAN']),
  ('JOB', 'J12', 'PENDING', 'CANCELLED', ARRAY['AGENT', 'HUMAN']),
  ('JOB', 'J12', 'VALIDATING', 'CANCELLED', ARRAY['AGENT', 'HUMAN']),
  ('JOB', 'J12', 'QUEUED', 'CANCELLED', ARRAY['AGENT', 'HUMAN']),
  ('JOB', 'J12', 'RUNNING', 'CANCELLED', ARRAY['AGENT', 'HUMAN']),
  ('JOB', 'J12', 'CHECKPOINTED', 'CANCELLED', ARRAY['AGENT', 'HUMAN']),
  ('JOB', 'J12', 'FAILED', 'CANCELLED', ARRAY['AGENT', 'HUMAN']);

-- Defence in depth for 03 section 11.1: a state write whose (from, to) pair has no rule row is
-- rejected even when code is bypassed. SQLSTATE AMW01 maps to PERMANENT.INVALID_TRANSITION.
CREATE FUNCTION amw_check_state_transition() RETURNS trigger
  LANGUAGE plpgsql
  AS $$
DECLARE
  kind text := CASE TG_TABLE_NAME WHEN 'jobs' THEN 'JOB' ELSE 'TASK' END;
  old_state text := CASE TG_OP WHEN 'INSERT' THEN NULL ELSE OLD.state END;
BEGIN
  IF TG_OP = 'UPDATE' AND NEW.state IS NOT DISTINCT FROM OLD.state THEN
    RETURN NEW;
  END IF;
  IF NOT EXISTS (
       SELECT 1 FROM state_transition_rules r
        WHERE r.entity_kind = kind
          AND r.from_state IS NOT DISTINCT FROM old_state
          AND r.to_state = NEW.state) THEN
    RAISE EXCEPTION 'invalid % transition % -> %', lower(kind), coalesce(old_state, '∅'), NEW.state
      USING ERRCODE = 'AMW01';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER check_state_transition BEFORE INSERT OR UPDATE OF state ON jobs
  FOR EACH ROW EXECUTE FUNCTION amw_check_state_transition();
CREATE TRIGGER check_state_transition BEFORE INSERT OR UPDATE OF state ON tasks
  FOR EACH ROW EXECUTE FUNCTION amw_check_state_transition();
