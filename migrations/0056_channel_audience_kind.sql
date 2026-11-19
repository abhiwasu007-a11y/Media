-- 0056 R14 write path for channels.audience_kind (CCR-114; 04 sections 5.1, 3.6a; ticket P4-02).
-- The column is set only through a NEW_CHANNEL approval (subject_kind 'channel', subject_id the
-- channel, subject_sha256 the SHA-256 of the canonical JSON {"audience_kind": ..., "channel_id":
-- ...}; canonical form of 03 section 9.1: UTF-8, keys sorted, no insignificant whitespace; the
-- channel_id is the wire form chn_<uuid>, GLOSSARY section 2). When the APPROVED decision of the
-- approval's final step is applied (DECISION evidence, CONFIRMED, valid MAC), amw_human_record_apply
-- sets the column from that document in the same transaction. The database does not read the
-- subject_ref blob: it rebuilds the only two possible documents (GENERAL, KIDS) and takes the one
-- whose hash equals subject_sha256; neither matching refuses the decision. A trigger refuses any
-- other change of the column (current_user must be amw_verifier_fn).
-- amw_verifier_fn owns amw_human_record_apply; this file re-grants SET on it to amw_owner for its
-- own transaction only and revokes it at the end (the L1a hardening of 0010 stays in force).
-- Review fixes (PR #58, B1/B2/M1; PROPOSED CCR-190): what the decision is about must not be
-- changeable after the approval is created, because amw_app holds UPDATE on approvals and
-- approval_steps. Triggers (every role, the table owner and superuser included; DISABLE TRIGGER
-- stays a DDL power of the owner) freeze the approval identity and the step identity, keep a
-- decided step's decision columns as written, refuse DELETE, and refuse a new step once a step of
-- the approval is decided or the approval is no longer PENDING, so the final step (the highest
-- step_no) is fixed before the first decision. amw_human_record_apply checks the evidence subject
-- and review code against the approval and, on the final step, that every other step was
-- APPROVED with evidence.
SET LOCAL ROLE amw_owner;

CREATE FUNCTION amw_approval_identity_frozen() RETURNS trigger
  LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp
  AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'approvals are never deleted (PROPOSED CCR-190)' USING ERRCODE = 'AMW02';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.org_id IS DISTINCT FROM OLD.org_id
     OR NEW.job_id IS DISTINCT FROM OLD.job_id OR NEW.kind IS DISTINCT FROM OLD.kind
     OR NEW.subject_kind IS DISTINCT FROM OLD.subject_kind
     OR NEW.subject_id IS DISTINCT FROM OLD.subject_id
     OR NEW.subject_sha256 IS DISTINCT FROM OLD.subject_sha256
     OR NEW.review_code IS DISTINCT FROM OLD.review_code
     OR NEW.requested_by IS DISTINCT FROM OLD.requested_by
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'the identity of an approval is fixed at creation (PROPOSED CCR-190)'
      USING ERRCODE = 'AMW02';
  END IF;
  RETURN NEW;
END
$$;
REVOKE ALL ON FUNCTION amw_approval_identity_frozen() FROM PUBLIC;
CREATE TRIGGER approval_identity_frozen BEFORE UPDATE OR DELETE ON approvals
  FOR EACH ROW EXECUTE FUNCTION amw_approval_identity_frozen();

CREATE FUNCTION amw_approval_step_frozen() RETURNS trigger
  LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp
  AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'approval steps are never deleted (PROPOSED CCR-190)' USING ERRCODE = 'AMW02';
  END IF;
  IF TG_OP = 'INSERT' THEN
    -- Serialises with amw_human_record_apply, which takes the same lock before it reads the steps.
    -- The lock only orders the two when each reads after it (READ COMMITTED); a REPEATABLE READ
    -- or SERIALIZABLE snapshot taken earlier would miss the other's commit, so it is refused.
    IF current_setting('transaction_isolation') <> 'read committed' THEN
      RAISE EXCEPTION 'approval steps are added only under READ COMMITTED (PROPOSED CCR-190)'
        USING ERRCODE = 'AMW02';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.approval_id::text, 190));
    IF EXISTS (SELECT 1 FROM approvals a
                WHERE a.org_id = NEW.org_id AND a.id = NEW.approval_id AND a.state <> 'PENDING')
       OR EXISTS (SELECT 1 FROM approval_steps s
                   WHERE s.org_id = NEW.org_id AND s.approval_id = NEW.approval_id
                     AND (s.decided_by IS NOT NULL OR s.evidence_id IS NOT NULL
                          OR s.decided_at IS NOT NULL)) THEN
      RAISE EXCEPTION 'the steps of an approval are fixed once a step is decided (PROPOSED CCR-190)'
        USING ERRCODE = 'AMW02';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.org_id IS DISTINCT FROM OLD.org_id
     OR NEW.approval_id IS DISTINCT FROM OLD.approval_id OR NEW.step_no IS DISTINCT FROM OLD.step_no
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'the identity of an approval step is fixed at creation (PROPOSED CCR-190)'
      USING ERRCODE = 'AMW02';
  END IF;
  IF (OLD.decided_by IS NOT NULL OR OLD.evidence_id IS NOT NULL OR OLD.decided_at IS NOT NULL)
     AND (NEW.state IS DISTINCT FROM OLD.state OR NEW.decided_by IS DISTINCT FROM OLD.decided_by
          OR NEW.decided_at IS DISTINCT FROM OLD.decided_at
          OR NEW.approval_channel IS DISTINCT FROM OLD.approval_channel
          OR NEW.recorded_by IS DISTINCT FROM OLD.recorded_by
          OR NEW.evidence_id IS DISTINCT FROM OLD.evidence_id
          OR NEW.required_role IS DISTINCT FROM OLD.required_role) THEN
    RAISE EXCEPTION 'a decided approval step is never changed (PROPOSED CCR-190)'
      USING ERRCODE = 'AMW02';
  END IF;
  RETURN NEW;
END
$$;
REVOKE ALL ON FUNCTION amw_approval_step_frozen() FROM PUBLIC;
CREATE TRIGGER approval_step_frozen BEFORE INSERT OR UPDATE OR DELETE ON approval_steps
  FOR EACH ROW EXECUTE FUNCTION amw_approval_step_frozen();

CREATE FUNCTION amw_channel_audience_guard() RETURNS trigger
  LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp
  AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.audience_kind IS NOT NULL THEN
      RAISE EXCEPTION 'channels.audience_kind is set only by a NEW_CHANNEL approval (CCR-114)'
        USING ERRCODE = 'AMW02';
    END IF;
  ELSIF NEW.audience_kind IS DISTINCT FROM OLD.audience_kind
        AND current_user <> 'amw_verifier_fn' THEN
    RAISE EXCEPTION 'channels.audience_kind is set only by a NEW_CHANNEL approval (CCR-114)'
      USING ERRCODE = 'AMW02';
  END IF;
  RETURN NEW;
END
$$;
REVOKE ALL ON FUNCTION amw_channel_audience_guard() FROM PUBLIC;
CREATE TRIGGER channel_audience_guard BEFORE INSERT OR UPDATE ON channels
  FOR EACH ROW EXECUTE FUNCTION amw_channel_audience_guard();

GRANT SELECT ON channels TO amw_verifier_fn;
GRANT UPDATE (audience_kind) ON channels TO amw_verifier_fn;

RESET ROLE;
GRANT amw_verifier_fn TO amw_owner WITH INHERIT FALSE, SET TRUE;
SET LOCAL ROLE amw_verifier_fn;

-- Same signature and grants as 0009 (04 section 3.6a; CCR-104); the NEW_CHANNEL branch is new.
CREATE OR REPLACE FUNCTION amw_human_record_apply(
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
  final_step int;
  audience text;
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
    -- Same lock as the approval_steps insert trigger: no step can be added while this runs. It
    -- orders the two only under READ COMMITTED (each statement reads after the lock), so another
    -- isolation level is refused (review m2: an older snapshot could miss a committed new step).
    IF current_setting('transaction_isolation') <> 'read committed' THEN
      RAISE EXCEPTION 'human records are applied only under READ COMMITTED' USING ERRCODE = 'AMW02';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(ev.approval_id::text, 190));
    SELECT * INTO ap FROM approvals WHERE id = ev.approval_id AND org_id = ev.org_id;
  END IF;

  IF ev.record_kind IN ('STEP_DECISION', 'KNOWLEDGE_RELEASE_REQUEST') THEN
    IF ap.id IS NULL OR ev.step_no IS DISTINCT FROM ap.current_step THEN
      RAISE EXCEPTION 'evidence does not name the approval''s current step' USING ERRCODE = 'AMW02';
    END IF;
    IF ap.state <> 'PENDING' THEN
      RAISE EXCEPTION 'the approval is no longer PENDING' USING ERRCODE = 'AMW02';
    END IF;
    -- 04 section 5.16: the evidence subject matches the approval's (review fix B1); the review
    -- code the owner's message carried (MAC-bound) is the approval's, whose identity is frozen.
    IF ap.kind = 'NEW_CHANNEL'
       AND (ap.subject_kind <> 'channel' OR ev.subject_kind IS DISTINCT FROM 'channel'
            OR ev.subject_id IS DISTINCT FROM ap.subject_id OR ev.review_code IS NULL
            OR upper(ev.review_code) <> upper(ap.review_code)) THEN
      RAISE EXCEPTION 'the evidence does not name this approval''s channel and review code'
        USING ERRCODE = 'AMW02';
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
    -- CCR-114: the APPROVED final step of a NEW_CHANNEL approval sets channels.audience_kind.
    IF ap.kind = 'NEW_CHANNEL' AND ev.parsed_decision = 'APPROVED' THEN
      SELECT max(s.step_no) INTO final_step FROM approval_steps s
       WHERE s.org_id = ev.org_id AND s.approval_id = ap.id;
      IF ev.step_no = final_step THEN
        IF ap.subject_kind <> 'channel' OR ap.subject_sha256 IS NULL THEN
          RAISE EXCEPTION 'a NEW_CHANNEL approval needs a channel subject document'
            USING ERRCODE = 'AMW02';
        END IF;
        -- Review fix M1: current_step is app-writable, so the final step applies only when every
        -- other step of the approval was decided APPROVED from owner evidence.
        IF EXISTS (SELECT 1 FROM approval_steps s
                    WHERE s.org_id = ev.org_id AND s.approval_id = ap.id
                      AND s.step_no <> ev.step_no
                      AND NOT (s.state = 'APPROVED' AND s.decided_by IS NOT NULL
                               AND s.evidence_id IS NOT NULL)) THEN
          RAISE EXCEPTION 'an earlier step of this NEW_CHANNEL approval is not APPROVED'
            USING ERRCODE = 'AMW02';
        END IF;
        SELECT k INTO audience FROM unnest(ARRAY['GENERAL', 'KIDS']) AS k
         WHERE sha256(convert_to(format('{"audience_kind":"%s","channel_id":"chn_%s"}', k,
                                        ap.subject_id::text), 'UTF8')) = ap.subject_sha256;
        IF audience IS NULL THEN
          RAISE EXCEPTION 'the subject document does not match subject_sha256'
            USING ERRCODE = 'AMW02';
        END IF;
        UPDATE channels SET audience_kind = audience
         WHERE org_id = ev.org_id AND id = ap.subject_id;
        IF NOT FOUND THEN
          RAISE EXCEPTION 'the approval''s channel is not in this tenant' USING ERRCODE = 'AMW03';
        END IF;
      END IF;
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

RESET ROLE;
GRANT amw_verifier_fn TO amw_owner WITH INHERIT FALSE, SET FALSE;
