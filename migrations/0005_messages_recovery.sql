-- 0005 messages (04 section 5.5), dead letter (5.7) and circuit breakers (5.8).
SET LOCAL ROLE amw_owner;

CREATE TABLE message_log (
  id uuid NOT NULL,
  org_id uuid NOT NULL REFERENCES organisations (id),
  sender text NOT NULL,
  receiver text NOT NULL,
  job_id uuid,
  task_id uuid,
  payload_schema text NOT NULL,
  payload_uri text NOT NULL,
  payload_sha256 bytea NOT NULL CHECK (octet_length(payload_sha256) = 32),
  priority smallint NOT NULL CHECK (priority BETWEEN 0 AND 4),
  sent_at timestamptz NOT NULL,
  correlation_id uuid NOT NULL,
  schema_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id, sent_at),
  FOREIGN KEY (org_id, job_id) REFERENCES jobs (org_id, id),
  FOREIGN KEY (org_id, task_id) REFERENCES tasks (org_id, id)
) PARTITION BY RANGE (sent_at);
CREATE INDEX message_log_org_task ON message_log (org_id, task_id);
SELECT amw_setup_tenant_table('message_log', 'append_only');
CREATE TABLE message_log_default PARTITION OF message_log DEFAULT;
SELECT amw_setup_tenant_partition('message_log_default');

CREATE TABLE message_receipts (
  org_id uuid NOT NULL REFERENCES organisations (id),
  message_id uuid NOT NULL,
  receiver text NOT NULL,
  processed_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org_id, message_id)
);
SELECT amw_setup_tenant_table('message_receipts', 'append_only');

CREATE TABLE dead_letter (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  task_id uuid NOT NULL,
  job_id uuid NOT NULL,
  failure_class text NOT NULL CHECK (failure_class IN ('TEMPORARY', 'PERMANENT', 'RESOURCE', 'AGENT', 'INFRASTRUCTURE', 'PUBLISHING')),
  error_code text NOT NULL,
  reason text NOT NULL,
  error jsonb NOT NULL,
  payload_ref text NOT NULL,
  payload_sha256 bytea NOT NULL CHECK (octet_length(payload_sha256) = 32),
  retry_history jsonb NOT NULL CHECK (jsonb_typeof(retry_history) = 'array'),
  traceback_ref text,
  last_attempt_id uuid,
  last_run_at timestamptz,
  recovery_status text NOT NULL DEFAULT 'NEW' CHECK (recovery_status IN ('NEW', 'TRIAGED', 'REPLAY_REQUESTED', 'REPLAY_APPROVED', 'REPLAYED', 'RESOLVED', 'DISCARDED')),
  escalation_level text NOT NULL CHECK (escalation_level IN ('L1', 'L2', 'L3')),
  replay_count int NOT NULL DEFAULT 0 CHECK (replay_count >= 0),
  replay_approval_id uuid,  -- TFK -> approvals (0006)
  triaged_by uuid REFERENCES users (id),
  root_cause_note text,
  resolved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  FOREIGN KEY (org_id, task_id) REFERENCES tasks (org_id, id),
  FOREIGN KEY (org_id, job_id) REFERENCES jobs (org_id, id),
  FOREIGN KEY (org_id, last_attempt_id) REFERENCES task_attempts (org_id, id),
  CONSTRAINT dead_letter_root_cause_before_replay
    CHECK (recovery_status NOT IN ('REPLAY_APPROVED', 'REPLAYED') OR root_cause_note IS NOT NULL)
);
CREATE INDEX dead_letter_org_status ON dead_letter (org_id, recovery_status, created_at);
CREATE INDEX dead_letter_org_task ON dead_letter (org_id, task_id);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON dead_letter
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('dead_letter', 'mutable');

-- Updated only through amw_breaker_record (04 section 3.6): the application roles read only.
CREATE TABLE circuit_breakers (
  id uuid PRIMARY KEY,
  org_id uuid REFERENCES organisations (id),
  provider text NOT NULL,
  operation_class text NOT NULL,
  credential_scope text NOT NULL
    CHECK (credential_scope = 'platform' OR credential_scope ~ '^gcp_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
  state text NOT NULL CHECK (state IN ('CLOSED', 'OPEN', 'HALF_OPEN')),
  window_started_at timestamptz NOT NULL,
  window_calls int NOT NULL DEFAULT 0,
  window_failures int NOT NULL DEFAULT 0,
  consecutive_failures int NOT NULL DEFAULT 0,
  opened_at timestamptz,
  open_until timestamptz,
  open_count int NOT NULL DEFAULT 0,
  half_open_in_flight int NOT NULL DEFAULT 0,
  last_error_code text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  UNIQUE (provider, operation_class, credential_scope)
);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON circuit_breakers
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_catalogue_table('circuit_breakers', 'read_only');
