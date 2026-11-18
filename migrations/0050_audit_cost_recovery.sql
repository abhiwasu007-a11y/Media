-- 0050 audit, cost and recovery tables (lane L1b; migrations 0050-0099).
-- Sources: docs/v4/04_DATABASE_ARCHITECTURE.md sections 5.7 (dead_letter), 5.8 (circuit_breakers,
-- amw_breaker_record), 5.13 (audit_log, audit_chain_heads), 5.14 (cost_ledger, budgets,
-- budget_reservations); 07 sections 4-5; 09 sections 3-6; 08 section 9.1. Forward-only, one
-- transaction. Uses the table helpers of 0001 (RLS + grants pattern of 04 sections 3.3-3.5).

SET LOCAL ROLE amw_owner;

-- ---------------------------------------------------------------------------------------------
-- 5.13 audit_log: append-only, hash-chained per tenant, partitioned by month on occurred_at.
-- row_hash is computed in amw_core.audit (SHA-256 of prev_hash || canonical JSON of the row).
-- amw_app / amw_publisher: INSERT only (04 section 5.13, 08 section 9.1); amw_readonly reads
-- (chain verification and the JSON export run with the read-only role).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE audit_log (
  id uuid NOT NULL,
  org_id uuid NOT NULL REFERENCES organisations (id),
  seq bigint NOT NULL CHECK (seq >= 1),
  occurred_at timestamptz NOT NULL,
  actor_kind text NOT NULL CHECK (actor_kind IN ('HUMAN', 'AGENT', 'SERVICE', 'SYSTEM')),
  actor_ref text NOT NULL CHECK (actor_ref ~ '^(agent_(0[1-9]|1[0-7])|svc_s(0[1-9]|1[0-3])|usr_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|sys_[a-z_]{3,32})$'),
  on_behalf_of uuid,
  authority text NOT NULL CHECK (char_length(authority) BETWEEN 1 AND 200),
  action text NOT NULL CHECK (action ~ '^[a-z0-9_]+(\.[a-z0-9_]+)+$'),
  target_kind text NOT NULL CHECK (char_length(target_kind) BETWEEN 1 AND 64),
  target_id uuid,
  job_id uuid,
  correlation_id uuid,
  details jsonb NOT NULL CHECK (jsonb_typeof(details) = 'object'),
  prev_hash bytea NOT NULL CHECK (octet_length(prev_hash) = 32),
  row_hash bytea NOT NULL CHECK (octet_length(row_hash) = 32),
  PRIMARY KEY (org_id, seq, occurred_at)
) PARTITION BY RANGE (occurred_at);
CREATE INDEX audit_log_org_target ON audit_log (org_id, target_kind, target_id);
CREATE INDEX audit_log_org_action ON audit_log (org_id, action, occurred_at);
SELECT amw_setup_tenant_table('audit_log', 'append_only');
REVOKE SELECT ON audit_log FROM amw_app, amw_publisher;
-- Monthly partitions are created ahead by the maintenance task (04 section 6).
CREATE TABLE audit_log_default PARTITION OF audit_log DEFAULT;
SELECT amw_setup_tenant_partition('audit_log_default');

-- The chain head: the writer takes SELECT ... FOR UPDATE on it, inserts the row, moves the head,
-- in the same transaction (serialises audit writes per tenant).
CREATE TABLE audit_chain_heads (
  org_id uuid PRIMARY KEY REFERENCES organisations (id),
  last_seq bigint NOT NULL CHECK (last_seq >= 0),
  last_hash bytea NOT NULL CHECK (octet_length(last_hash) = 32),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON audit_chain_heads
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
-- The head only moves forward by exactly one row (an app bug can never rewind it).
CREATE FUNCTION amw_audit_head_forward() RETURNS trigger
  LANGUAGE plpgsql
  AS $$
BEGIN
  IF NEW.org_id <> OLD.org_id OR NEW.last_seq <> OLD.last_seq + 1 THEN
    RAISE EXCEPTION 'audit chain head may only advance by one' USING ERRCODE = 'AMW02';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER audit_head_forward BEFORE UPDATE ON audit_chain_heads
  FOR EACH ROW EXECUTE FUNCTION amw_audit_head_forward();
CREATE TRIGGER audit_head_no_delete BEFORE DELETE ON audit_chain_heads
  FOR EACH ROW EXECUTE FUNCTION amw_reject_modification();
SELECT amw_setup_tenant_table('audit_chain_heads', 'mutable');

-- ---------------------------------------------------------------------------------------------
-- 5.14 cost_ledger: append-only, one row per paid call. Not partitioned yet (04 section 6 allows
-- Tier 0 without partitions): the tenant-composite self reference estimate_entry_id -> (org_id,
-- id) needs UNIQUE (org_id, id), which a partitioned table cannot hold. The PK keeps the
-- partition key so partitioning can be enabled later.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE cost_ledger (
  id uuid NOT NULL,
  org_id uuid NOT NULL REFERENCES organisations (id),
  job_id uuid,
  task_id uuid,
  attempt_id uuid,
  channel_id uuid,
  agent_id text CHECK (agent_id ~ '^(agent_(0[1-9]|1[0-7])|svc_s(0[1-9]|1[0-3]))$'),
  provider text NOT NULL CHECK (char_length(provider) BETWEEN 1 AND 100),
  model text,
  operation text NOT NULL CHECK (operation IN ('llm.completion', 'llm.count_tokens', 'llm.batch', 'tts.synthesize', 'tts.list_voices', 'stock.search', 'stock.license', 'music.search', 'music.license', 'image.generate', 'video.generate', 'web.fetch', 'render.ffmpeg', 'delivery.file', 'storage.bytes', 'youtube.quota')),
  billing_mode text CHECK (billing_mode IN ('STANDARD', 'BATCH', 'CACHED_PROMPT')),
  tokens_in int CHECK (tokens_in >= 0),
  tokens_out int CHECK (tokens_out >= 0),
  tokens_cached_in int CHECK (tokens_cached_in >= 0),
  tokens_cache_write_in int CHECK (tokens_cache_write_in >= 0),
  chars_in int CHECK (chars_in >= 0),
  language text,
  units numeric(20, 6) CHECK (units >= 0),
  unit_kind text CHECK (unit_kind IN ('characters', 'audio_ms', 'images', 'video_ms', 'render_ms', 'quota_units', 'items', 'bytes')),
  amount_micros bigint NOT NULL CHECK (amount_micros >= 0),
  currency char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
  fx_rate numeric(18, 8) CHECK (fx_rate > 0),
  fx_source text,
  figure_kind text NOT NULL CHECK (figure_kind IN ('ESTIMATE', 'VERIFIED')),
  price_ref text,
  estimate_entry_id uuid,
  verification_ref text,
  idempotency_key text CHECK (idempotency_key ~ '^idk_[0-9a-f]{64}$'),
  occurred_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id, occurred_at),
  UNIQUE (org_id, id),
  UNIQUE (org_id, idempotency_key, figure_kind, occurred_at),
  FOREIGN KEY (org_id, job_id) REFERENCES jobs (org_id, id),
  FOREIGN KEY (org_id, task_id) REFERENCES tasks (org_id, id),
  FOREIGN KEY (org_id, attempt_id) REFERENCES task_attempts (org_id, id),
  FOREIGN KEY (org_id, channel_id) REFERENCES channels (org_id, id),
  FOREIGN KEY (org_id, estimate_entry_id) REFERENCES cost_ledger (org_id, id),
  CONSTRAINT cost_ledger_units_pair CHECK ((units IS NULL) = (unit_kind IS NULL)),
  CONSTRAINT cost_ledger_fx_pair CHECK (fx_rate IS NULL OR fx_source IS NOT NULL),
  CONSTRAINT cost_ledger_quota_no_money CHECK (unit_kind IS DISTINCT FROM 'quota_units' OR amount_micros = 0),
  CONSTRAINT cost_ledger_estimate_priced
    CHECK (figure_kind <> 'ESTIMATE' OR amount_micros = 0 OR price_ref IS NOT NULL),
  CONSTRAINT cost_ledger_estimate_fields
    CHECK (figure_kind <> 'ESTIMATE' OR (estimate_entry_id IS NULL AND verification_ref IS NULL)),
  CONSTRAINT cost_ledger_verified_ref CHECK (figure_kind <> 'VERIFIED' OR verification_ref IS NOT NULL)
);
CREATE INDEX cost_ledger_org_job ON cost_ledger (org_id, job_id);
CREATE INDEX cost_ledger_org_occurred ON cost_ledger (org_id, occurred_at);
CREATE INDEX cost_ledger_org_task ON cost_ledger (org_id, task_id);
-- At most one VERIFIED row per ESTIMATE (a VERIFIED row replaces its estimate in sums, 09 3.3).
CREATE UNIQUE INDEX cost_ledger_one_verified ON cost_ledger (org_id, estimate_entry_id)
  WHERE figure_kind = 'VERIFIED' AND estimate_entry_id IS NOT NULL;
-- A VERIFIED row points to an ESTIMATE, never to another VERIFIED row.
CREATE FUNCTION amw_cost_ledger_verified_target() RETURNS trigger
  LANGUAGE plpgsql
  AS $$
BEGIN
  IF NEW.estimate_entry_id IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM cost_ledger c
       WHERE c.org_id = NEW.org_id AND c.id = NEW.estimate_entry_id AND c.figure_kind = 'ESTIMATE') THEN
    RAISE EXCEPTION 'estimate_entry_id must reference an ESTIMATE row' USING ERRCODE = 'AMW02';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER cost_ledger_verified_target BEFORE INSERT ON cost_ledger
  FOR EACH ROW EXECUTE FUNCTION amw_cost_ledger_verified_target();
SELECT amw_setup_tenant_table('cost_ledger', 'append_only');

-- ---------------------------------------------------------------------------------------------
-- 5.14 budgets and budget_reservations.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE budgets (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  scope_kind text NOT NULL CHECK (scope_kind IN ('ORG', 'WORKSPACE', 'CHANNEL', 'PRODUCTION_TYPE', 'PROVIDER')),
  scope_id uuid,
  scope_key text,
  period text NOT NULL CHECK (period IN ('DAY', 'MONTH', 'PER_VIDEO', 'PER_JOB', 'PILOT_TOTAL')),
  limit_minor bigint NOT NULL CHECK (limit_minor >= 0),
  currency char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
  soft_limit_ratio numeric(4, 3) NOT NULL CHECK (soft_limit_ratio BETWEEN 0 AND 1),
  state text NOT NULL CHECK (state IN ('ACTIVE', 'SUSPENDED_EXCEEDED', 'DISABLED')),
  non_critical_suspend boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  CONSTRAINT budgets_scope_shape CHECK (
    CASE scope_kind
      WHEN 'ORG' THEN scope_id IS NULL AND scope_key IS NULL
      WHEN 'WORKSPACE' THEN scope_id IS NOT NULL AND scope_key IS NULL
      WHEN 'CHANNEL' THEN scope_id IS NOT NULL AND scope_key IS NULL
      WHEN 'PRODUCTION_TYPE' THEN scope_id IS NULL AND scope_key IS NOT NULL
      WHEN 'PROVIDER' THEN scope_id IS NULL AND scope_key IS NOT NULL
    END)
);
CREATE INDEX budgets_org_scope ON budgets (org_id, scope_kind, scope_key);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON budgets
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
-- 09 section 13: only a human (owner / Finance) creates a budget or changes its limit, scope,
-- currency or period, sets DISABLED, or releases a suspension; S4 itself may only suspend
-- (ACTIVE -> SUSPENDED_EXCEEDED) or apply a DAY/MONTH roll-over (SUSPENDED_EXCEEDED -> ACTIVE
-- once the period changed). app.user_id is set only for human actors (amw_core.tenancy).
CREATE FUNCTION amw_budgets_guard() RETURNS trigger
  LANGUAGE plpgsql
  AS $$
DECLARE
  human boolean := amw_current_user() IS NOT NULL;
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NOT human THEN
      RAISE EXCEPTION 'budgets are created by a human only' USING ERRCODE = 'AMW02';
    END IF;
    RETURN NEW;
  END IF;
  IF human THEN
    NEW.row_version := OLD.row_version + 1;
    RETURN NEW;
  END IF;
  IF (NEW.scope_kind, NEW.scope_id, NEW.scope_key, NEW.period, NEW.limit_minor, NEW.currency,
      NEW.soft_limit_ratio, NEW.non_critical_suspend)
     IS DISTINCT FROM
     (OLD.scope_kind, OLD.scope_id, OLD.scope_key, OLD.period, OLD.limit_minor, OLD.currency,
      OLD.soft_limit_ratio, OLD.non_critical_suspend) THEN
    RAISE EXCEPTION 'budget limits are changed by a human only' USING ERRCODE = 'AMW02';
  END IF;
  IF NOT ((OLD.state = 'ACTIVE' AND NEW.state = 'SUSPENDED_EXCEEDED')
          OR (OLD.state = 'SUSPENDED_EXCEEDED' AND NEW.state = 'ACTIVE'
              AND OLD.period IN ('DAY', 'MONTH'))
          OR OLD.state = NEW.state) THEN
    RAISE EXCEPTION 'budget state change % -> % needs a human', OLD.state, NEW.state
      USING ERRCODE = 'AMW02';
  END IF;
  NEW.row_version := OLD.row_version + 1;
  RETURN NEW;
END
$$;
CREATE TRIGGER budgets_guard BEFORE INSERT OR UPDATE ON budgets
  FOR EACH ROW EXECUTE FUNCTION amw_budgets_guard();
SELECT amw_setup_tenant_table('budgets', 'mutable');

CREATE TABLE budget_reservations (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  budget_id uuid NOT NULL,
  task_id uuid NOT NULL,
  amount_micros bigint NOT NULL CHECK (amount_micros >= 0),
  currency char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
  status text NOT NULL CHECK (status IN ('HELD', 'CONSUMED', 'RELEASED')),
  released_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  FOREIGN KEY (org_id, budget_id) REFERENCES budgets (org_id, id),
  FOREIGN KEY (org_id, task_id) REFERENCES tasks (org_id, id),
  CONSTRAINT budget_reservations_released_at CHECK ((status = 'RELEASED') = (released_at IS NOT NULL))
);
CREATE INDEX budget_reservations_org_budget_status ON budget_reservations (org_id, budget_id, status);
CREATE INDEX budget_reservations_org_task ON budget_reservations (org_id, task_id);
-- Retries never reserve twice (09 section 3.4 step 4): one HELD row per budget and task.
CREATE UNIQUE INDEX budget_reservations_one_held ON budget_reservations (org_id, budget_id, task_id)
  WHERE status = 'HELD';
-- HELD -> CONSUMED | RELEASED only; a closed reservation never reopens.
CREATE FUNCTION amw_budget_reservations_forward() RETURNS trigger
  LANGUAGE plpgsql
  AS $$
BEGIN
  IF OLD.status <> 'HELD' OR NEW.status = 'HELD'
     OR (NEW.budget_id, NEW.task_id, NEW.amount_micros, NEW.currency)
        IS DISTINCT FROM (OLD.budget_id, OLD.task_id, OLD.amount_micros, OLD.currency) THEN
    RAISE EXCEPTION 'reservation change not allowed' USING ERRCODE = 'AMW02';
  END IF;
  NEW.row_version := OLD.row_version + 1;
  RETURN NEW;
END
$$;
CREATE TRIGGER budget_reservations_forward BEFORE UPDATE ON budget_reservations
  FOR EACH ROW EXECUTE FUNCTION amw_budget_reservations_forward();
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON budget_reservations
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('budget_reservations', 'mutable');

-- ---------------------------------------------------------------------------------------------
-- 5.7 dead_letter and 5.8 circuit_breakers + amw_breaker_record are created by lane L1a (0005,
-- 0010). L1b adds only the immutability guard of 07 section 5.2 rule 3 on dead_letter.
-- ---------------------------------------------------------------------------------------------
-- 07 section 5.2 rule 3: never deleted (no DELETE grant); the content of the dead-lettering
-- event (payload, error, history) never changes; only the workflow columns move.
CREATE FUNCTION amw_dead_letter_guard() RETURNS trigger
  LANGUAGE plpgsql
  AS $$
BEGIN
  IF (NEW.task_id, NEW.job_id, NEW.failure_class, NEW.error_code, NEW.reason, NEW.error,
      NEW.payload_ref, NEW.payload_sha256, NEW.retry_history, NEW.traceback_ref,
      NEW.last_attempt_id, NEW.last_run_at, NEW.escalation_level)
     IS DISTINCT FROM
     (OLD.task_id, OLD.job_id, OLD.failure_class, OLD.error_code, OLD.reason, OLD.error,
      OLD.payload_ref, OLD.payload_sha256, OLD.retry_history, OLD.traceback_ref,
      OLD.last_attempt_id, OLD.last_run_at, OLD.escalation_level)
     OR NEW.replay_count < OLD.replay_count
     OR OLD.recovery_status IN ('RESOLVED', 'DISCARDED') THEN
    RAISE EXCEPTION 'dead_letter change not allowed' USING ERRCODE = 'AMW02';
  END IF;
  NEW.row_version := OLD.row_version + 1;
  RETURN NEW;
END
$$;
CREATE TRIGGER dead_letter_guard BEFORE UPDATE ON dead_letter
  FOR EACH ROW EXECUTE FUNCTION amw_dead_letter_guard();
