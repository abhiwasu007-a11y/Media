-- 0053 R14 write path for channels.audience_kind (CCR-114; 04 sections 5.1, 3.6a; ticket P4-02).
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
SET LOCAL ROLE amw_owner;

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
    -- CCR-114: the APPROVED final step of a NEW_CHANNEL approval sets channels.audience_kind.
    IF ap.kind = 'NEW_CHANNEL' AND ev.parsed_decision = 'APPROVED' THEN
      SELECT max(s.step_no) INTO final_step FROM approval_steps s
       WHERE s.org_id = ev.org_id AND s.approval_id = ap.id;
      IF ev.step_no = final_step THEN
        IF ap.subject_kind <> 'channel' OR ap.subject_sha256 IS NULL THEN
          RAISE EXCEPTION 'a NEW_CHANNEL approval needs a channel subject document'
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
