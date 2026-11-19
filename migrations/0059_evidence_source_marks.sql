-- 0059 owner-evidence session-source marks (lane R, PR #77 recheck N2; CCR-265, PROPOSED).
-- 0058 is planned for contract pass 6, so this file takes 0059.
--
-- The verifier records which kind of session source verified a row: the key
-- session_source_production (real session record) or session_source_test_fixture (dry-run TEST
-- source), inside verifier_result and therefore inside the MAC input of 0009.
--
-- Changes:
-- 1. A database profile row, REAL by default. A TEST mark may only be written in a database whose
--    profile is TEST, and a production mark only in a REAL one. Only the table owner changes the
--    profile; no login role has UPDATE.
-- 2. The marks are fixed at verification. amw_evidence_mark_confirmed and amw_evidence_refuse
--    MERGE the new result into the stored one (0009 replaced it, so a TEST row confirmed by a real
--    worker came out marked production). The stored marks always win, and the earlier checks are
--    kept, so a dispute no longer erases the verification result.
-- 3. amw_evidence_mark_confirmed refuses a decision record that a later (or simultaneous)
--    decision record on the same subject and code supersedes (only two different non-NULL
--    approvals exempt each other) (PR #77 recheck N1, CCR-264).
-- amw_verifier_fn owns the functions. As in 0051, this file grants SET on it for its own
-- transaction only and revokes it at the end. Every function pins search_path to end with pg_temp.

SET LOCAL ROLE amw_owner;
CREATE TABLE evidence_db_profile (
  id boolean PRIMARY KEY DEFAULT true CHECK (id),
  profile text NOT NULL CHECK (profile IN ('REAL', 'TEST')),
  updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO evidence_db_profile (profile) VALUES ('REAL');
REVOKE ALL ON evidence_db_profile FROM PUBLIC;
GRANT SELECT ON evidence_db_profile TO amw_verifier_fn, amw_verifier, amw_operator, amw_app,
  amw_readonly;
RESET ROLE;

GRANT amw_verifier_fn TO amw_owner WITH INHERIT FALSE, SET TRUE;
SET LOCAL ROLE amw_verifier_fn;

-- Merge a new verifier result into the stored one; the stored source marks are kept as they are
-- (a mark absent at verification can never be added later).
CREATE FUNCTION amw_evidence_result_merge(p_old jsonb, p_new jsonb) RETURNS jsonb
  LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog, public, pg_temp
  AS $$
DECLARE
  r jsonb := (coalesce(p_old, '{}'::jsonb) || coalesce(p_new, '{}'::jsonb))
             - 'session_source_test_fixture' - 'session_source_production';
BEGIN
  IF p_old ? 'session_source_test_fixture' THEN
    r := r || jsonb_build_object('session_source_test_fixture', p_old -> 'session_source_test_fixture');
  END IF;
  IF p_old ? 'session_source_production' THEN
    r := r || jsonb_build_object('session_source_production', p_old -> 'session_source_production');
  END IF;
  RETURN r;
END
$$;
REVOKE ALL ON FUNCTION amw_evidence_result_merge(jsonb, jsonb) FROM PUBLIC;

-- A first verification result may carry at most one mark, and only the one the profile allows.
CREATE FUNCTION amw_evidence_marks_check(p_result jsonb) RETURNS void
  LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public, pg_temp
  AS $$
DECLARE
  v_profile text;
  v_test boolean := coalesce(p_result -> 'session_source_test_fixture' = 'true'::jsonb, false);
  v_prod boolean := coalesce(p_result -> 'session_source_production' = 'true'::jsonb, false);
BEGIN
  SELECT profile INTO v_profile FROM evidence_db_profile WHERE id;
  IF v_test AND v_prod THEN
    RAISE EXCEPTION 'a verification is either TEST or production' USING ERRCODE = 'AMW02';
  END IF;
  IF v_test AND v_profile IS DISTINCT FROM 'TEST' THEN
    RAISE EXCEPTION 'TEST evidence is refused in a REAL database' USING ERRCODE = 'AMW02';
  END IF;
  IF v_prod AND v_profile IS DISTINCT FROM 'REAL' THEN
    RAISE EXCEPTION 'production evidence is refused in a TEST database' USING ERRCODE = 'AMW02';
  END IF;
END
$$;
REVOKE ALL ON FUNCTION amw_evidence_marks_check(jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION amw_evidence_mark_verified(p_evidence_id uuid, p_verifier_result jsonb)
  RETURNS void
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
  AS $$
DECLARE
  e owner_instruction_evidence := amw_evidence_lock(p_evidence_id);
BEGIN
  IF e.state <> 'PENDING_VERIFICATION' THEN
    RAISE EXCEPTION 'evidence is not PENDING_VERIFICATION' USING ERRCODE = 'AMW01';
  END IF;
  PERFORM amw_evidence_marks_check(p_verifier_result);
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

CREATE OR REPLACE FUNCTION amw_evidence_mark_confirmed(
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
  -- Only the latest decision on a code is confirmed (CCR-264): any other decision record on the
  -- same subject and code whose owner message is as late or later, in any state, refuses this one
  -- (fail closed, also for a tie). Only two different, non-NULL approvals exempt each other; a
  -- NULL approval or another step never does.
  IF e.record_kind IN ('STEP_DECISION', 'COMPLIANCE_DECISION', 'KNOWLEDGE_RELEASE_REQUEST')
     AND EXISTS (
       SELECT 1 FROM owner_instruction_evidence o
        WHERE o.org_id = e.org_id AND o.id <> e.id
          AND o.subject_kind = e.subject_kind AND o.subject_id = e.subject_id
          AND upper(o.review_code) = upper(e.review_code)
          AND NOT (o.approval_id IS NOT NULL AND e.approval_id IS NOT NULL
                   AND o.approval_id <> e.approval_id)
          AND o.record_kind IN ('STEP_DECISION', 'COMPLIANCE_DECISION', 'KNOWLEDGE_RELEASE_REQUEST')
          AND o.message_at >= e.message_at) THEN
    RAISE EXCEPTION 'a later decision on this code supersedes this record' USING ERRCODE = 'AMW02';
  END IF;
  e.state := 'CONFIRMED';
  e.confirmation_event_uuid := p_confirmation_event_uuid;
  e.confirmation_quote := p_confirmation_quote;
  e.confirmation_message_at := p_confirmation_message_at;
  e.verifier_result := amw_evidence_result_merge(e.verifier_result, p_verifier_result);
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

CREATE OR REPLACE FUNCTION amw_evidence_refuse(p_evidence_id uuid, p_reason text,
  p_verifier_result jsonb) RETURNS void
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
         verifier_result = CASE WHEN e.verifier_result IS NULL AND p_verifier_result IS NULL
                                THEN NULL
                                ELSE amw_evidence_result_merge(e.verifier_result, p_verifier_result)
                           END
   WHERE id = e.id AND org_id = e.org_id;
END
$$;

RESET ROLE;
GRANT amw_verifier_fn TO amw_owner WITH INHERIT FALSE, SET FALSE;
