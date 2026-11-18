-- 0009 owner-instruction evidence with database-level provenance (CCR-100; 04 sections 3.1, 3.6a,
-- 5.16, 5.17; 03 section 11.6; 08 section 5.3). Identity comes from the database role
-- (current_user / session_user), never from the self-set app.actor.
--   amw_operator   (LOGIN)   inserts evidence only as PENDING_VERIFICATION / REFUSED; runs
--                            amw_human_record_apply.
--   amw_verifier   (LOGIN)   runs amw_evidence_mark_verified / _confirmed / amw_evidence_refuse.
--   amw_verifier_fn (NOLOGIN) owns the SECURITY DEFINER functions and evidence_mac_keys; the only
--                            role that updates evidence or writes human rows. Not BYPASSRLS: the
--                            functions run inside the caller's tenant transaction.
-- A superuser can still bypass all of this (08: defence in depth, tamper-evident).

-- Bootstrap part (role creation needs CREATEROLE, the extension a privileged role).
DO $roles$
DECLARE
  r record;
BEGIN
  FOR r IN SELECT * FROM (VALUES ('amw_operator', true), ('amw_verifier', true),
                                 ('amw_verifier_fn', false)) AS t(name, login)
  LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r.name) THEN
      BEGIN
        EXECUTE format('CREATE ROLE %I %s', r.name, CASE WHEN r.login THEN 'LOGIN' ELSE 'NOLOGIN' END);
      EXCEPTION WHEN duplicate_object THEN
        NULL;
      END;
    END IF;
  END LOOP;
END
$roles$;
ALTER ROLE amw_operator LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
ALTER ROLE amw_verifier LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
ALTER ROLE amw_verifier_fn NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
GRANT amw_verifier_fn TO amw_owner WITH INHERIT FALSE, SET TRUE;
GRANT USAGE ON SCHEMA public TO amw_operator, amw_verifier;
GRANT USAGE, CREATE ON SCHEMA public TO amw_verifier_fn;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

SET LOCAL ROLE amw_owner;

-- Reading the tenant row is part of opening a tenant transaction (amw_core.tenancy).
GRANT SELECT ON organisations TO amw_operator, amw_verifier, amw_verifier_fn;

-- ---------------------------------------------------------------------------------------------
-- Table.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE owner_instruction_evidence (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  job_id uuid,
  approval_id uuid,
  step_no int,
  record_kind text NOT NULL CHECK (record_kind IN ('STEP_DECISION', 'CONTRIBUTION', 'HUMAN_SCORE',
    'COMPLIANCE_DECISION', 'OWNER_TOPIC', 'DATASET_INTAKE', 'KNOWLEDGE_RELEASE_REQUEST',
    'REVISION_NOTE')),
  subject_kind text NOT NULL,
  subject_id uuid NOT NULL,
  review_code text,
  parsed_decision text CHECK (parsed_decision IN ('NOT_STARTED', 'PENDING', 'APPROVED', 'REJECTED', 'CHANGES_REQUESTED', 'SKIPPED')),
  parsed_target_stage_id text CHECK (parsed_target_stage_id ~ '^[a-z0-9_]{2,32}$'),
  claimed_scores jsonb,
  source_kind text NOT NULL CHECK (source_kind IN ('OWNER_CHAT_MESSAGE', 'TOOL_RESULT', 'SUBAGENT_MESSAGE', 'NOTIFICATION', 'DOCUMENT')),
  session_id text NOT NULL,
  event_uuid text NOT NULL,
  quote text NOT NULL CHECK (char_length(quote) BETWEEN 1 AND 4000),
  message_at timestamptz NOT NULL,
  state text NOT NULL CHECK (state IN ('PENDING_VERIFICATION', 'VERIFIED', 'CONFIRMED', 'REFUSED')),
  evidence_mac bytea CHECK (octet_length(evidence_mac) = 32),
  mac_key_version int,
  event_verified_at timestamptz,
  verifier_result jsonb,
  confirmation_event_uuid text,
  confirmation_quote text,
  confirmation_message_at timestamptz,
  recorded_by text NOT NULL,
  on_behalf_of uuid NOT NULL REFERENCES users (id),
  evidence_sha256 bytea NOT NULL CHECK (octet_length(evidence_sha256) = 32),
  refused_reason text,
  supersedes_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  FOREIGN KEY (org_id, job_id) REFERENCES jobs (org_id, id),
  FOREIGN KEY (org_id, approval_id) REFERENCES approvals (org_id, id),
  FOREIGN KEY (org_id, supersedes_id) REFERENCES owner_instruction_evidence (org_id, id),
  CONSTRAINT evidence_decision_kinds_only CHECK (
    record_kind IN ('STEP_DECISION', 'COMPLIANCE_DECISION', 'KNOWLEDGE_RELEASE_REQUEST')
    OR parsed_decision IS NULL),
  CONSTRAINT evidence_target_stage_only_for_changes
    CHECK (parsed_target_stage_id IS NULL OR parsed_decision = 'CHANGES_REQUESTED'),
  CONSTRAINT evidence_scores_only_for_human_score CHECK (
    claimed_scores IS NULL
    OR (record_kind = 'HUMAN_SCORE' AND jsonb_typeof(claimed_scores) = 'object'
        AND claimed_scores <> '{}'::jsonb)),
  CONSTRAINT evidence_refused_reason CHECK ((state = 'REFUSED') = (refused_reason IS NOT NULL)),
  CONSTRAINT evidence_only_owner_chat_verifies
    CHECK (state = 'REFUSED' OR source_kind = 'OWNER_CHAT_MESSAGE'),
  CONSTRAINT evidence_mac_when_verified CHECK (state NOT IN ('VERIFIED', 'CONFIRMED')
    OR (evidence_mac IS NOT NULL AND mac_key_version IS NOT NULL AND event_verified_at IS NOT NULL)),
  CONSTRAINT evidence_confirmed_fields CHECK (state <> 'CONFIRMED'
    OR (confirmation_event_uuid IS NOT NULL AND confirmation_quote IS NOT NULL
        AND confirmation_message_at IS NOT NULL)),
  CONSTRAINT evidence_confirmation_later
    CHECK (confirmation_message_at IS NULL OR confirmation_message_at > message_at),
  CONSTRAINT evidence_confirmation_distinct
    CHECK (confirmation_event_uuid IS NULL OR confirmation_event_uuid <> event_uuid)
);
CREATE UNIQUE INDEX evidence_one_live_per_event ON owner_instruction_evidence (org_id, event_uuid)
  WHERE state <> 'REFUSED';
CREATE UNIQUE INDEX evidence_one_per_confirmation
  ON owner_instruction_evidence (org_id, confirmation_event_uuid);
CREATE INDEX evidence_subject ON owner_instruction_evidence (org_id, subject_kind, subject_id);
ALTER TABLE owner_instruction_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE owner_instruction_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON owner_instruction_evidence
  USING (org_id = amw_current_org()) WITH CHECK (org_id = amw_current_org());
REVOKE ALL ON owner_instruction_evidence FROM PUBLIC;
GRANT SELECT, INSERT ON owner_instruction_evidence TO amw_operator;
GRANT SELECT ON owner_instruction_evidence TO amw_verifier, amw_app, amw_publisher, amw_readonly;
GRANT SELECT, UPDATE ON owner_instruction_evidence TO amw_verifier_fn;

ALTER TABLE approval_steps
  ADD FOREIGN KEY (org_id, evidence_id) REFERENCES owner_instruction_evidence (org_id, id);
ALTER TABLE editorial_contributions
  ADD FOREIGN KEY (org_id, evidence_id) REFERENCES owner_instruction_evidence (org_id, id);
ALTER TABLE quality_scores
  ADD FOREIGN KEY (org_id, evidence_id) REFERENCES owner_instruction_evidence (org_id, id);
ALTER TABLE compliance_verdicts
  ADD FOREIGN KEY (org_id, evidence_id) REFERENCES owner_instruction_evidence (org_id, id);
-- CCR-102: human compliance rows carry their channel and recorder.
ALTER TABLE compliance_verdicts
  ADD COLUMN approval_channel text CHECK (approval_channel IN ('OWNER_CHAT_OPERATOR', 'WEB_DASHBOARD', 'CLIENT_PORTAL')),
  ADD COLUMN recorded_by text,
  ADD CONSTRAINT compliance_verdicts_human_fields CHECK (decided_by !~ '^usr_'
    OR (approval_channel IS NOT NULL AND recorded_by IS NOT NULL AND evidence_id IS NOT NULL));

GRANT SELECT ON approvals, approval_steps, jobs TO amw_operator;
GRANT SELECT ON approvals, approval_steps, memberships, jobs TO amw_verifier_fn;
GRANT UPDATE ON approval_steps TO amw_verifier_fn;
GRANT SELECT, INSERT ON editorial_contributions, quality_scores, compliance_verdicts TO amw_verifier_fn;

-- Initial state and the one-message-one-record rule (CCR-100, CCR-101).
CREATE FUNCTION amw_evidence_insert_guard() RETURNS trigger
  LANGUAGE plpgsql
  AS $$
BEGIN
  IF NEW.state NOT IN ('PENDING_VERIFICATION', 'REFUSED')
     OR NEW.evidence_mac IS NOT NULL OR NEW.mac_key_version IS NOT NULL
     OR NEW.event_verified_at IS NOT NULL OR NEW.verifier_result IS NOT NULL
     OR NEW.confirmation_event_uuid IS NOT NULL OR NEW.confirmation_quote IS NOT NULL
     OR NEW.confirmation_message_at IS NOT NULL THEN
    RAISE EXCEPTION 'evidence is created pending (or refused) with no verification fields'
      USING ERRCODE = 'AMW02';
  END IF;
  IF EXISTS (SELECT 1 FROM owner_instruction_evidence e
              WHERE e.org_id = NEW.org_id AND e.confirmation_event_uuid = NEW.event_uuid) THEN
    RAISE EXCEPTION 'this owner message already confirms another record' USING ERRCODE = 'AMW02';
  END IF;
  -- Identity comes from the database role, never from the caller (CCR-100): the operator login
  -- is the only role with INSERT, and its rows are always recorded by sys_operator. recorded_by
  -- is part of the MAC input.
  IF session_user = 'amw_operator' THEN
    NEW.recorded_by := 'sys_operator';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER evidence_insert_guard BEFORE INSERT ON owner_instruction_evidence
  FOR EACH ROW EXECUTE FUNCTION amw_evidence_insert_guard();

-- Forward-only state changes, each setting its own columns once, only inside the 3.6a functions.
CREATE FUNCTION amw_evidence_forward_only() RETURNS trigger
  LANGUAGE plpgsql
  AS $$
DECLARE
  allowed text[];
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'owner_instruction_evidence rows are never deleted' USING ERRCODE = 'AMW02';
  END IF;
  IF current_user <> 'amw_verifier_fn' THEN
    RAISE EXCEPTION 'evidence changes only through the verifier functions' USING ERRCODE = 'AMW02';
  END IF;
  IF OLD.state = 'PENDING_VERIFICATION' AND NEW.state = 'VERIFIED' THEN
    allowed := ARRAY['state', 'event_verified_at', 'verifier_result', 'evidence_mac',
                     'mac_key_version'];
  ELSIF OLD.state = 'VERIFIED' AND NEW.state = 'CONFIRMED' THEN
    allowed := ARRAY['state', 'confirmation_event_uuid', 'confirmation_quote',
                     'confirmation_message_at', 'verifier_result', 'evidence_mac', 'mac_key_version'];
  ELSIF OLD.state IN ('PENDING_VERIFICATION', 'VERIFIED') AND NEW.state = 'REFUSED' THEN
    allowed := ARRAY['state', 'refused_reason', 'verifier_result'];
  ELSE
    RAISE EXCEPTION 'evidence state change % -> % not allowed', OLD.state, NEW.state
      USING ERRCODE = 'AMW02';
  END IF;
  IF (to_jsonb(NEW) - allowed) IS DISTINCT FROM (to_jsonb(OLD) - allowed) THEN
    RAISE EXCEPTION 'evidence columns outside the state change were modified' USING ERRCODE = 'AMW02';
  END IF;
  IF NEW.confirmation_event_uuid IS NOT NULL AND EXISTS (
       SELECT 1 FROM owner_instruction_evidence e
        WHERE e.org_id = NEW.org_id AND e.event_uuid = NEW.confirmation_event_uuid
          AND e.state <> 'REFUSED') THEN
    RAISE EXCEPTION 'this owner message already backs another record' USING ERRCODE = 'AMW02';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER evidence_forward_only BEFORE UPDATE OR DELETE ON owner_instruction_evidence
  FOR EACH ROW EXECUTE FUNCTION amw_evidence_forward_only();
CREATE TRIGGER evidence_no_truncate BEFORE TRUNCATE ON owner_instruction_evidence
  FOR EACH STATEMENT EXECUTE FUNCTION amw_reject_modification();

-- ---------------------------------------------------------------------------------------------
-- Key table and MAC (owner amw_verifier_fn; no grant to any role).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE evidence_mac_keys (
  version int PRIMARY KEY CHECK (version >= 1),
  key bytea NOT NULL CHECK (octet_length(key) >= 32),
  created_at timestamptz NOT NULL DEFAULT now(),
  retired_at timestamptz
);
REVOKE ALL ON evidence_mac_keys FROM PUBLIC;
ALTER TABLE evidence_mac_keys OWNER TO amw_verifier_fn;

-- Canonical MAC input: the evidence fields incl. org_id, id and state (jsonb text form is
-- deterministic: keys are ordered by jsonb).
CREATE FUNCTION amw_evidence_mac_input(e owner_instruction_evidence) RETURNS bytea
  LANGUAGE sql IMMUTABLE
  AS $$
  SELECT convert_to(jsonb_build_object(
    'org_id', e.org_id, 'id', e.id, 'state', e.state, 'job_id', e.job_id,
    'approval_id', e.approval_id, 'step_no', e.step_no, 'record_kind', e.record_kind,
    'subject_kind', e.subject_kind, 'subject_id', e.subject_id, 'review_code', e.review_code,
    'parsed_decision', e.parsed_decision, 'parsed_target_stage_id', e.parsed_target_stage_id,
    'claimed_scores', e.claimed_scores, 'source_kind', e.source_kind, 'session_id', e.session_id,
    'event_uuid', e.event_uuid, 'quote', e.quote,
    'message_at', to_char(e.message_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    'event_verified_at',
      to_char(e.event_verified_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    'verifier_result', e.verifier_result, 'confirmation_event_uuid', e.confirmation_event_uuid,
    'confirmation_quote', e.confirmation_quote,
    'confirmation_message_at',
      to_char(e.confirmation_message_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    'on_behalf_of', e.on_behalf_of, 'recorded_by', e.recorded_by, 'evidence_sha256', encode(e.evidence_sha256, 'hex'),
    'supersedes_id', e.supersedes_id, 'mac_key_version', e.mac_key_version)::text, 'UTF8')
$$;
REVOKE ALL ON FUNCTION amw_evidence_mac_input(owner_instruction_evidence) FROM PUBLIC;

-- Setup: the migrator loads a key version from the environment's secret mechanism.
CREATE FUNCTION amw_evidence_mac_key_add(p_version int, p_key bytea) RETURNS void
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
  AS $$
BEGIN
  INSERT INTO evidence_mac_keys (version, key) VALUES (p_version, p_key);
  UPDATE evidence_mac_keys SET retired_at = now() WHERE version < p_version AND retired_at IS NULL;
END
$$;
REVOKE ALL ON FUNCTION amw_evidence_mac_key_add(int, bytea) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION amw_evidence_mac_key_add(int, bytea) TO amw_migrator;

CREATE FUNCTION amw_evidence_mac_of(e owner_instruction_evidence) RETURNS bytea
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
  AS $$
  SELECT hmac(amw_evidence_mac_input(e), k.key, 'sha256')
    FROM evidence_mac_keys k WHERE k.version = e.mac_key_version
$$;
REVOKE ALL ON FUNCTION amw_evidence_mac_of(owner_instruction_evidence) FROM PUBLIC;

CREATE FUNCTION amw_evidence_mac_valid(p_evidence_id uuid) RETURNS boolean
  LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
  AS $$
DECLARE
  e owner_instruction_evidence;
  expected bytea;
BEGIN
  SELECT * INTO e FROM owner_instruction_evidence
   WHERE id = p_evidence_id AND org_id = amw_current_org();
  IF NOT FOUND OR e.evidence_mac IS NULL THEN
    RETURN false;
  END IF;
  expected := amw_evidence_mac_of(e);
  RETURN expected IS NOT NULL AND expected = e.evidence_mac;
END
$$;
REVOKE ALL ON FUNCTION amw_evidence_mac_valid(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION amw_evidence_mac_valid(uuid)
  TO amw_app, amw_publisher, amw_operator, amw_verifier;

-- ---------------------------------------------------------------------------------------------
-- Verifier functions (EXECUTE: amw_verifier; session_user must be amw_verifier).
-- ---------------------------------------------------------------------------------------------
CREATE FUNCTION amw_evidence_lock(p_evidence_id uuid) RETURNS owner_instruction_evidence
  LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp
  AS $$
DECLARE
  e owner_instruction_evidence;
BEGIN
  IF session_user <> 'amw_verifier' THEN
    RAISE EXCEPTION 'only the verifier login may change evidence' USING ERRCODE = 'AMW02';
  END IF;
  SELECT * INTO e FROM owner_instruction_evidence
   WHERE id = p_evidence_id AND org_id = amw_current_org() FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'evidence not found in this tenant' USING ERRCODE = 'AMW03';
  END IF;
  RETURN e;
END
$$;
REVOKE ALL ON FUNCTION amw_evidence_lock(uuid) FROM PUBLIC;

CREATE FUNCTION amw_evidence_current_key() RETURNS int
  LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public, pg_temp
  AS $$
DECLARE
  v int;
BEGIN
  SELECT max(version) INTO v FROM evidence_mac_keys WHERE retired_at IS NULL;
  IF v IS NULL THEN
    RAISE EXCEPTION 'no evidence MAC key is loaded' USING ERRCODE = 'AMW03';
  END IF;
  RETURN v;
END
$$;
REVOKE ALL ON FUNCTION amw_evidence_current_key() FROM PUBLIC;

CREATE FUNCTION amw_evidence_mark_verified(p_evidence_id uuid, p_verifier_result jsonb)
  RETURNS void
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
  AS $$
DECLARE
  e owner_instruction_evidence := amw_evidence_lock(p_evidence_id);
BEGIN
  IF e.state <> 'PENDING_VERIFICATION' THEN
    RAISE EXCEPTION 'evidence is not PENDING_VERIFICATION' USING ERRCODE = 'AMW01';
  END IF;
  e.state := 'VERIFIED';
  e.event_verified_at := now();
  e.verifier_result := p_verifier_result;
  e.mac_key_version := amw_evidence_current_key();
  UPDATE owner_instruction_evidence
     SET state = e.state, event_verified_at = e.event_verified_at,
         verifier_result = e.verifier_result, mac_key_version = e.mac_key_version,
         evidence_mac = amw_evidence_mac_of(e)
   WHERE id = e.id AND org_id = e.org_id;
END
$$;

CREATE FUNCTION amw_evidence_mark_confirmed(
  p_evidence_id uuid, p_confirmation_event_uuid text, p_confirmation_quote text,
  p_confirmation_message_at timestamptz, p_verifier_result jsonb) RETURNS void
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
  AS $$
DECLARE
  e owner_instruction_evidence := amw_evidence_lock(p_evidence_id);
BEGIN
  IF e.state <> 'VERIFIED' THEN
    RAISE EXCEPTION 'evidence is not VERIFIED' USING ERRCODE = 'AMW01';
  END IF;
  IF amw_evidence_mac_of(e) IS DISTINCT FROM e.evidence_mac THEN
    RAISE EXCEPTION 'evidence MAC is not valid' USING ERRCODE = 'AMW02';
  END IF;
  e.state := 'CONFIRMED';
  e.confirmation_event_uuid := p_confirmation_event_uuid;
  e.confirmation_quote := p_confirmation_quote;
  e.confirmation_message_at := p_confirmation_message_at;
  e.verifier_result := p_verifier_result;
  e.mac_key_version := amw_evidence_current_key();
  UPDATE owner_instruction_evidence
     SET state = e.state, confirmation_event_uuid = e.confirmation_event_uuid,
         confirmation_quote = e.confirmation_quote,
         confirmation_message_at = e.confirmation_message_at,
         verifier_result = e.verifier_result, mac_key_version = e.mac_key_version,
         evidence_mac = amw_evidence_mac_of(e)
   WHERE id = e.id AND org_id = e.org_id;
END
$$;

CREATE FUNCTION amw_evidence_refuse(p_evidence_id uuid, p_reason text, p_verifier_result jsonb)
  RETURNS void
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
  AS $$
DECLARE
  e owner_instruction_evidence := amw_evidence_lock(p_evidence_id);
BEGIN
  IF e.state NOT IN ('PENDING_VERIFICATION', 'VERIFIED') THEN
    RAISE EXCEPTION 'evidence cannot be refused from %', e.state USING ERRCODE = 'AMW01';
  END IF;
  UPDATE owner_instruction_evidence
     SET state = 'REFUSED', refused_reason = p_reason,
         verifier_result = coalesce(p_verifier_result, verifier_result)
   WHERE id = e.id AND org_id = e.org_id;
END
$$;

REVOKE ALL ON FUNCTION amw_evidence_mark_verified(uuid, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION amw_evidence_mark_confirmed(uuid, text, text, timestamptz, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION amw_evidence_refuse(uuid, text, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION amw_evidence_mark_verified(uuid, jsonb) TO amw_verifier;
GRANT EXECUTE ON FUNCTION amw_evidence_mark_confirmed(uuid, text, text, timestamptz, jsonb) TO amw_verifier;
GRANT EXECUTE ON FUNCTION amw_evidence_refuse(uuid, text, jsonb) TO amw_verifier;

-- ---------------------------------------------------------------------------------------------
-- Human rows: only amw_verifier_fn writes them (inside amw_human_record_apply), and the trigger
-- re-checks the evidence (CONFIRMED, valid MAC, same human, matching subject, membership).
-- ---------------------------------------------------------------------------------------------
CREATE FUNCTION amw_human_row_guard() RETURNS trigger
  LANGUAGE plpgsql
  AS $$
DECLARE
  human uuid;
  need_role text;
  ev owner_instruction_evidence;
BEGIN
  IF TG_TABLE_NAME = 'approval_steps' THEN
    IF NEW.decided_by IS NULL AND NEW.decided_at IS NULL AND NEW.approval_channel IS NULL
       AND NEW.recorded_by IS NULL AND NEW.evidence_id IS NULL
       AND NEW.state IN ('NOT_STARTED', 'PENDING', 'SKIPPED') THEN
      RETURN NEW;  -- an undecided step is not a human row
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.decided_by IS NOT DISTINCT FROM OLD.decided_by
       AND NEW.state IS NOT DISTINCT FROM OLD.state
       AND NEW.decided_at IS NOT DISTINCT FROM OLD.decided_at
       AND NEW.approval_channel IS NOT DISTINCT FROM OLD.approval_channel
       AND NEW.recorded_by IS NOT DISTINCT FROM OLD.recorded_by
       AND NEW.evidence_id IS NOT DISTINCT FROM OLD.evidence_id
       AND OLD.decided_by IS NULL THEN
      RETURN NEW;
    END IF;
    human := NEW.decided_by;
    need_role := NEW.required_role;
  ELSIF TG_TABLE_NAME = 'editorial_contributions' THEN
    human := NEW.contributor_user_id;
  ELSIF TG_TABLE_NAME = 'quality_scores' THEN
    IF NEW.scorer_kind <> 'HUMAN' THEN
      RETURN NEW;
    END IF;
    human := substr(NEW.scorer_ref, 5)::uuid;
  ELSE  -- compliance_verdicts
    IF NEW.decided_by !~ '^usr_' THEN
      IF NEW.is_final AND NEW.decided_by <> 'agent_16' THEN
        RAISE EXCEPTION 'a final verdict is agent_16''s or a human row' USING ERRCODE = 'AMW02';
      END IF;
      RETURN NEW;
    END IF;
    human := substr(NEW.decided_by, 5)::uuid;
  END IF;

  IF current_user <> 'amw_verifier_fn' THEN
    RAISE EXCEPTION 'human rows are written only by amw_human_record_apply' USING ERRCODE = 'AMW02';
  END IF;
  IF human IS NULL OR NEW.approval_channel IS DISTINCT FROM 'OWNER_CHAT_OPERATOR'
     OR NEW.evidence_id IS NULL THEN
    RAISE EXCEPTION 'human row needs its human, channel OWNER_CHAT_OPERATOR and evidence'
      USING ERRCODE = 'AMW02';
  END IF;
  SELECT * INTO ev FROM owner_instruction_evidence e
   WHERE e.org_id = NEW.org_id AND e.id = NEW.evidence_id;
  IF NOT FOUND OR ev.source_kind <> 'OWNER_CHAT_MESSAGE' OR ev.state <> 'CONFIRMED'
     OR ev.on_behalf_of <> human OR NOT amw_evidence_mac_valid(ev.id) THEN
    RAISE EXCEPTION 'evidence is not a confirmed, MAC-valid owner message of this human'
      USING ERRCODE = 'AMW02';
  END IF;
  IF TG_TABLE_NAME = 'approval_steps' THEN
    IF ev.record_kind NOT IN ('STEP_DECISION', 'KNOWLEDGE_RELEASE_REQUEST')
       OR ev.approval_id IS DISTINCT FROM NEW.approval_id
       OR ev.step_no IS DISTINCT FROM NEW.step_no
       OR ev.parsed_decision IS DISTINCT FROM NEW.state THEN
      RAISE EXCEPTION 'evidence does not back this step decision' USING ERRCODE = 'AMW02';
    END IF;
  ELSIF TG_TABLE_NAME = 'editorial_contributions' THEN
    IF ev.record_kind <> 'CONTRIBUTION'
       OR ev.approval_id IS DISTINCT FROM NEW.approval_id
       OR (ev.job_id IS NOT NULL AND ev.job_id <> NEW.job_id)
       OR strpos(ev.quote, NEW.description) = 0 THEN
      RAISE EXCEPTION 'evidence does not back this contribution' USING ERRCODE = 'AMW02';
    END IF;
  ELSIF TG_TABLE_NAME = 'quality_scores' THEN
    IF ev.record_kind <> 'HUMAN_SCORE' OR ev.subject_kind <> NEW.subject_kind
       OR ev.subject_id <> NEW.subject_id
       OR jsonb_typeof(ev.claimed_scores -> NEW.dimension) IS DISTINCT FROM 'number'
       OR (ev.claimed_scores ->> NEW.dimension)::numeric <> NEW.points
       OR NEW.points <> trunc(NEW.points) THEN
      RAISE EXCEPTION 'evidence does not back this score' USING ERRCODE = 'AMW02';
    END IF;
  ELSE
    IF ev.record_kind <> 'STEP_DECISION' OR ev.subject_id <> NEW.subject_id THEN
      RAISE EXCEPTION 'evidence does not back this verdict' USING ERRCODE = 'AMW02';
    END IF;
  END IF;
  IF NOT EXISTS (
       SELECT 1 FROM memberships m
        WHERE m.org_id = NEW.org_id AND m.user_id = human AND m.status = 'ACTIVE'
          AND (need_role IS NULL OR m.role = need_role)) THEN
    RAISE EXCEPTION 'the human holds no ACTIVE membership with the required role'
      USING ERRCODE = 'AMW02';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER human_row_guard BEFORE INSERT OR UPDATE ON approval_steps
  FOR EACH ROW EXECUTE FUNCTION amw_human_row_guard();
CREATE TRIGGER human_row_guard BEFORE INSERT OR UPDATE ON editorial_contributions
  FOR EACH ROW EXECUTE FUNCTION amw_human_row_guard();
CREATE TRIGGER human_row_guard BEFORE INSERT OR UPDATE ON quality_scores
  FOR EACH ROW EXECUTE FUNCTION amw_human_row_guard();
CREATE TRIGGER human_row_guard BEFORE INSERT OR UPDATE ON compliance_verdicts
  FOR EACH ROW EXECUTE FUNCTION amw_human_row_guard();

-- The one human row an evidence names (04 section 3.6a). Arguments after the evidence ID carry
-- what the evidence row does not hold: the contribution type and description (a verbatim part
-- of the quote) and the rubric version of a score.
CREATE FUNCTION amw_human_record_apply(
  p_evidence_id uuid,
  p_contribution_type text DEFAULT NULL,
  p_description text DEFAULT NULL,
  p_rubric_version text DEFAULT NULL) RETURNS void
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
  AS $$
DECLARE
  ev owner_instruction_evidence;
  ap approvals;
  dim text;
  pts jsonb;
BEGIN
  IF session_user <> 'amw_operator' THEN
    RAISE EXCEPTION 'only the operator login applies human records' USING ERRCODE = 'AMW02';
  END IF;
  SELECT * INTO ev FROM owner_instruction_evidence
   WHERE id = p_evidence_id AND org_id = amw_current_org();
  IF NOT FOUND THEN
    RAISE EXCEPTION 'evidence not found in this tenant' USING ERRCODE = 'AMW03';
  END IF;
  IF ev.state <> 'CONFIRMED' OR NOT amw_evidence_mac_valid(ev.id) THEN
    RAISE EXCEPTION 'evidence is not CONFIRMED with a valid MAC' USING ERRCODE = 'AMW02';
  END IF;
  IF ev.approval_id IS NOT NULL THEN
    SELECT * INTO ap FROM approvals WHERE id = ev.approval_id AND org_id = ev.org_id;
  END IF;

  IF ev.record_kind IN ('STEP_DECISION', 'KNOWLEDGE_RELEASE_REQUEST') THEN
    IF ap.id IS NULL OR ev.step_no IS DISTINCT FROM ap.current_step THEN
      RAISE EXCEPTION 'evidence does not name the approval''s current step' USING ERRCODE = 'AMW02';
    END IF;
    IF ap.state <> 'PENDING' THEN
      RAISE EXCEPTION 'the approval is no longer PENDING' USING ERRCODE = 'AMW02';
    END IF;
    UPDATE approval_steps
       SET state = ev.parsed_decision, decided_by = ev.on_behalf_of, decided_at = now(),
           approval_channel = 'OWNER_CHAT_OPERATOR', recorded_by = 'sys_operator',
           evidence_id = ev.id
     WHERE org_id = ev.org_id AND approval_id = ev.approval_id AND step_no = ev.step_no
       AND decided_by IS NULL;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'step not found or already decided' USING ERRCODE = 'AMW01';
    END IF;
    IF ap.kind IN ('SENSITIVE_CLAIM', 'COPYRIGHT_DOUBT') THEN
      INSERT INTO compliance_verdicts (id, org_id, job_id, subject_kind, subject_id, subject_sha256,
          verdict, rationale, decided_by, is_final, evidence_id, approval_channel, recorded_by)
      VALUES (amw_uuid7(), ev.org_id, ap.job_id, ap.subject_kind, ap.subject_id,
          ap.subject_sha256,
          CASE ev.parsed_decision WHEN 'APPROVED' THEN 'ALLOWED' ELSE 'BLOCKED' END,
          ev.quote, 'usr_' || ev.on_behalf_of::text, true, ev.id, 'OWNER_CHAT_OPERATOR',
          'sys_operator');
    END IF;
  ELSIF ev.record_kind = 'CONTRIBUTION' THEN
    IF p_contribution_type IS NULL OR p_description IS NULL OR ev.job_id IS NULL THEN
      RAISE EXCEPTION 'a contribution needs its type, description and job' USING ERRCODE = 'AMW02';
    END IF;
    INSERT INTO editorial_contributions (id, org_id, job_id, approval_id, contributor_user_id,
        approval_channel, recorded_by, evidence_id, type, description)
    VALUES (amw_uuid7(), ev.org_id, ev.job_id, ev.approval_id, ev.on_behalf_of,
        'OWNER_CHAT_OPERATOR', 'sys_operator', ev.id, p_contribution_type, p_description);
  ELSIF ev.record_kind = 'HUMAN_SCORE' THEN
    IF p_rubric_version IS NULL OR ap.id IS NULL OR ap.subject_sha256 IS NULL
       OR ap.subject_id <> ev.subject_id OR ap.job_id IS NULL THEN
      RAISE EXCEPTION 'a human score needs its rubric version and an approval subject'
        USING ERRCODE = 'AMW02';
    END IF;
    FOR dim, pts IN SELECT * FROM jsonb_each(ev.claimed_scores) LOOP
      INSERT INTO quality_scores (id, org_id, job_id, subject_kind, subject_id, subject_sha256,
          rubric_version, dimension, max_points, points, scorer_kind, scorer_ref,
          approval_channel, recorded_by, evidence_id)
      VALUES (amw_uuid7(), ev.org_id, ap.job_id, ev.subject_kind, ev.subject_id,
          ap.subject_sha256, p_rubric_version, dim,
          CASE dim WHEN 'RESEARCH_ACCURACY' THEN 20 WHEN 'STORYTELLING' THEN 15
            WHEN 'AUDIENCE_VALUE' THEN 15 WHEN 'VISUAL_QUALITY' THEN 15 WHEN 'AUDIO_QUALITY' THEN 10
            WHEN 'EDITING_QUALITY' THEN 10 WHEN 'THUMBNAIL_METADATA' THEN 10
            WHEN 'COMPLIANCE' THEN 5 END,
          pts::text::numeric, 'HUMAN', 'usr_' || ev.on_behalf_of::text, 'OWNER_CHAT_OPERATOR',
          'sys_operator', ev.id);
    END LOOP;
  ELSE
    RAISE EXCEPTION 'record kind % writes no human row here', ev.record_kind USING ERRCODE = 'AMW02';
  END IF;
END
$$;
REVOKE ALL ON FUNCTION amw_human_record_apply(uuid, text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION amw_human_record_apply(uuid, text, text, text) TO amw_operator;

-- Publish guard re-checks the contribution's evidence (CCR-100: every consumer re-checks).
CREATE OR REPLACE FUNCTION amw_publish_guard() RETURNS trigger
  LANGUAGE plpgsql
  AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND (NEW.state IS NOT DISTINCT FROM OLD.state
                           OR NEW.state NOT IN ('UPLOADING', 'SCHEDULED', 'PUBLISHED')) THEN
    RETURN NEW;
  END IF;
  IF NOT EXISTS (
       SELECT 1 FROM approvals a
        WHERE a.org_id = NEW.org_id AND a.id = NEW.approval_id AND a.state = 'APPROVED'
          AND a.kind IN ('FINAL_VIDEO', 'PUBLISH') AND a.subject_sha256 = NEW.render_sha256) THEN
    RAISE EXCEPTION 'publish guard: no APPROVED approval for this render' USING ERRCODE = 'AMW02';
  END IF;
  IF NOT EXISTS (
       SELECT 1 FROM editorial_contributions c
         JOIN owner_instruction_evidence e ON e.org_id = c.org_id AND e.id = c.evidence_id
        WHERE c.org_id = NEW.org_id AND c.job_id = NEW.job_id AND c.approval_id = NEW.approval_id
          AND e.state = 'CONFIRMED' AND amw_evidence_mac_valid(e.id)) THEN
    RAISE EXCEPTION 'publish guard: no evidenced editorial contribution bound to the approval'
      USING ERRCODE = 'AMW02';
  END IF;
  IF NOT EXISTS (
       SELECT 1 FROM compliance_verdicts v
        WHERE v.org_id = NEW.org_id AND v.id = NEW.authorisation_verdict_id AND v.is_final
          AND v.verdict = 'ALLOWED' AND v.subject_sha256 = NEW.render_sha256) THEN
    RAISE EXCEPTION 'publish guard: no final ALLOWED authorisation for this render'
      USING ERRCODE = 'AMW02';
  END IF;
  RETURN NEW;
END
$$;

-- Ownership last: the grants above were made by amw_owner and carry over to the new owner
-- (a REVOKE / GRANT issued after the owner change would be a silent no-op).
ALTER FUNCTION amw_evidence_mac_input(owner_instruction_evidence) OWNER TO amw_verifier_fn;
ALTER FUNCTION amw_evidence_mac_key_add(int, bytea) OWNER TO amw_verifier_fn;
ALTER FUNCTION amw_evidence_mac_of(owner_instruction_evidence) OWNER TO amw_verifier_fn;
ALTER FUNCTION amw_evidence_mac_valid(uuid) OWNER TO amw_verifier_fn;
ALTER FUNCTION amw_evidence_lock(uuid) OWNER TO amw_verifier_fn;
ALTER FUNCTION amw_evidence_current_key() OWNER TO amw_verifier_fn;
ALTER FUNCTION amw_evidence_mark_verified(uuid, jsonb) OWNER TO amw_verifier_fn;
ALTER FUNCTION amw_evidence_mark_confirmed(uuid, text, text, timestamptz, jsonb) OWNER TO amw_verifier_fn;
ALTER FUNCTION amw_evidence_refuse(uuid, text, jsonb) OWNER TO amw_verifier_fn;
ALTER FUNCTION amw_human_record_apply(uuid, text, text, text) OWNER TO amw_verifier_fn;
