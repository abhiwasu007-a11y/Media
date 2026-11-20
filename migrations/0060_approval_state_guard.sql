-- 0060 approvals.state is a human row (PR #108 review r1 BLOCKER; R14; CCR-297, PROPOSED).
--
-- Before this file amw_app and amw_publisher held UPDATE on approvals (0002 amw_grant_table
-- 'mutable') and nothing guarded approvals.state, so any application login could write
-- state = 'APPROVED' with no owner evidence, and the publish guard (0009) trusted that column.
-- Also freely writable: approvals.subject_sha256 and tasks.approval_id.
--
-- Changes (the SAME mechanism as the other human rows of 0009: amw_human_row_guard, the
-- amw_verifier_fn definer role, evidence re-checked inside the database):
-- 1. amw_approval_backed(org, approval, state): the evidence re-check in SQL. True only when the
--    deciding step(s) carry state, an owner-chat decision of that human, CONFIRMED, MAC valid, bound
--    to this approval, step, subject and review code, and not superseded by a later decision.
-- 2. amw_human_row_guard gets an approvals branch: a decided state (APPROVED, REJECTED,
--    CHANGES_REQUESTED, WITHDRAWN) is written only by amw_verifier_fn and only when
--    amw_approval_backed holds; an approval is never created decided; a decided approval is
--    immutable (state, decided_at, subject, hash, workflow); the subject columns of a PENDING
--    approval do not change either (the hash may be filled once while it is NULL).
--    WITHDRAWN has no evidence path: it stays impossible (fail closed).
-- 3. amw_approval_settle(approval): the one door amw_app uses to derive approvals.state from the
--    decided step (SECURITY DEFINER, owner amw_verifier_fn, idempotent). The trigger re-checks.
-- 4. tasks.approval_id is set once (NULL -> a PENDING approval of the same org and job) and never
--    rewritten or cleared.
-- 5. The publish guard re-checks, at use time, that the approving evidence is still CONFIRMED,
--    MAC valid and not superseded (a later REJECT after settle blocks a later publish).
-- Roles: amw_verifier_fn owns the helper functions; this file grants SET on it for its own
-- transaction only and revokes it at the end (as 0051 and 0059).

SET LOCAL ROLE amw_owner;
GRANT UPDATE (state, decided_at) ON approvals TO amw_verifier_fn;
RESET ROLE;

GRANT amw_verifier_fn TO amw_owner WITH INHERIT FALSE, SET TRUE;
SET LOCAL ROLE amw_verifier_fn;

-- Evidence re-check (read only; runs as the caller, who needs SELECT on the three tables: the
-- publish guard already reads the evidence as amw_publisher).
CREATE FUNCTION amw_approval_backed(p_org uuid, p_approval uuid, p_state text) RETURNS boolean
  LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public, pg_temp
  AS $$
DECLARE
  ap approvals;
  st approval_steps;
  ev owner_instruction_evidence;
  n int := 0;
  v_profile text;
  v_prod boolean;
  v_test boolean;
BEGIN
  IF p_state NOT IN ('APPROVED', 'REJECTED', 'CHANGES_REQUESTED') THEN
    RETURN false;  -- no evidence path writes any other decided state
  END IF;
  SELECT profile INTO v_profile FROM evidence_db_profile WHERE id;
  SELECT * INTO ap FROM approvals WHERE org_id = p_org AND id = p_approval;
  IF NOT FOUND THEN
    RETURN false;
  END IF;
  FOR st IN SELECT * FROM approval_steps s
             WHERE s.org_id = p_org AND s.approval_id = p_approval AND s.state <> 'SKIPPED'
               AND (p_state = 'APPROVED' OR s.step_no = ap.current_step)
             ORDER BY s.step_no
  LOOP
    n := n + 1;
    IF st.state <> p_state OR st.decided_by IS NULL OR st.evidence_id IS NULL
       OR st.approval_channel IS DISTINCT FROM 'OWNER_CHAT_OPERATOR' THEN
      RETURN false;
    END IF;
    SELECT * INTO ev FROM owner_instruction_evidence e
     WHERE e.org_id = p_org AND e.id = st.evidence_id;
    IF NOT FOUND OR ev.state <> 'CONFIRMED' OR ev.source_kind <> 'OWNER_CHAT_MESSAGE'
       OR ev.record_kind NOT IN ('STEP_DECISION', 'KNOWLEDGE_RELEASE_REQUEST')
       OR NOT amw_evidence_mac_valid(ev.id)
       OR ev.approval_id IS DISTINCT FROM ap.id OR ev.step_no IS DISTINCT FROM st.step_no
       OR ev.parsed_decision::text IS DISTINCT FROM st.state
       OR ev.on_behalf_of IS DISTINCT FROM st.decided_by
       OR ev.subject_kind IS DISTINCT FROM ap.subject_kind
       OR ev.subject_id IS DISTINCT FROM ap.subject_id
       OR upper(ev.review_code) IS DISTINCT FROM upper(ap.review_code) THEN
      RETURN false;
    END IF;
    -- source mark (PR 108 r2 MAJOR; 0059): a REAL-profile database accepts only evidence the
    -- verifier marked as a production session record (an unmarked result is NOT production, as in
    -- the Python port); a TEST-profile database accepts only the test-fixture mark.
    v_prod := coalesce(ev.verifier_result -> 'session_source_production' = 'true'::jsonb, false);
    v_test := coalesce(ev.verifier_result -> 'session_source_test_fixture' = 'true'::jsonb, false);
    IF v_profile IS NULL
       OR (v_profile = 'REAL' AND NOT (v_prod AND NOT v_test))
       OR (v_profile = 'TEST' AND NOT (v_test AND NOT v_prod))
       OR v_profile NOT IN ('REAL', 'TEST') THEN
      RETURN false;
    END IF;
    -- not superseded: same rule as amw_evidence_mark_confirmed (0059)
    IF EXISTS (
         SELECT 1 FROM owner_instruction_evidence o
          WHERE o.org_id = ev.org_id AND o.id <> ev.id
            AND o.subject_kind = ev.subject_kind AND o.subject_id = ev.subject_id
            AND upper(o.review_code) = upper(ev.review_code)
            AND NOT (o.approval_id IS NOT NULL AND ev.approval_id IS NOT NULL
                     AND o.approval_id <> ev.approval_id)
            AND o.record_kind IN ('STEP_DECISION', 'COMPLIANCE_DECISION',
                                  'KNOWLEDGE_RELEASE_REQUEST')
            AND o.message_at >= ev.message_at) THEN
      RETURN false;
    END IF;
  END LOOP;
  RETURN n > 0;
END
$$;
REVOKE ALL ON FUNCTION amw_approval_backed(uuid, uuid, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION amw_approval_backed(uuid, uuid, text)
  TO amw_app, amw_publisher, amw_readonly;

-- The one door through which amw_app derives approvals.state from the decided step.
-- Returns true when this call changed the state, false when the approval was already settled.
CREATE FUNCTION amw_approval_settle(p_approval_id uuid) RETURNS boolean
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
  AS $$
DECLARE
  ap approvals;
  st approval_steps;
BEGIN
  SELECT * INTO ap FROM approvals
   WHERE id = p_approval_id AND org_id = amw_current_org() FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'approval not found in this tenant' USING ERRCODE = 'AMW03';
  END IF;
  SELECT * INTO st FROM approval_steps
   WHERE org_id = ap.org_id AND approval_id = ap.id AND step_no = ap.current_step;
  IF NOT FOUND OR st.state NOT IN ('APPROVED', 'REJECTED', 'CHANGES_REQUESTED') THEN
    RAISE EXCEPTION 'the approval''s current step is not decided' USING ERRCODE = 'AMW02';
  END IF;
  IF ap.state <> 'PENDING' THEN
    RETURN false;  -- already settled (the caller compares the state it wanted)
  END IF;
  -- hold the deciding evidence row against a concurrent change until this transaction ends
  -- (the publish guard re-checks the evidence at use time as well)
  PERFORM 1 FROM owner_instruction_evidence e
   WHERE e.org_id = ap.org_id AND e.id = st.evidence_id FOR SHARE;
  UPDATE approvals SET state = st.state, decided_at = now()
   WHERE id = ap.id AND org_id = ap.org_id AND state = 'PENDING';
  RETURN true;
END
$$;
REVOKE ALL ON FUNCTION amw_approval_settle(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION amw_approval_settle(uuid) TO amw_app;

RESET ROLE;
GRANT amw_verifier_fn TO amw_owner WITH INHERIT FALSE, SET FALSE;

SET LOCAL ROLE amw_owner;

-- amw_human_row_guard of 0009 with one more branch (approvals); everything else is unchanged.
CREATE OR REPLACE FUNCTION amw_human_row_guard() RETURNS trigger
  LANGUAGE plpgsql
  AS $$
DECLARE
  human uuid;
  need_role text;
  ev owner_instruction_evidence;
BEGIN
  IF TG_TABLE_NAME = 'approvals' THEN
    IF TG_OP = 'INSERT' THEN
      IF NEW.state IN ('APPROVED', 'REJECTED', 'CHANGES_REQUESTED', 'WITHDRAWN') THEN
        RAISE EXCEPTION 'an approval is created PENDING; its decision comes from owner evidence'
          USING ERRCODE = 'AMW02';
      END IF;
      RETURN NEW;
    END IF;
    IF NEW.org_id IS DISTINCT FROM OLD.org_id OR NEW.kind IS DISTINCT FROM OLD.kind
       OR NEW.subject_kind IS DISTINCT FROM OLD.subject_kind
       OR NEW.subject_id IS DISTINCT FROM OLD.subject_id
       OR NEW.workflow_key IS DISTINCT FROM OLD.workflow_key
       OR NEW.job_id IS DISTINCT FROM OLD.job_id
       OR (OLD.subject_sha256 IS NOT NULL
           AND NEW.subject_sha256 IS DISTINCT FROM OLD.subject_sha256) THEN
      RAISE EXCEPTION 'an approval''s subject, hash, kind and workflow never change'
        USING ERRCODE = 'AMW02';
    END IF;
    IF NEW.current_step IS DISTINCT FROM OLD.current_step
       OR NEW.managed_service IS DISTINCT FROM OLD.managed_service THEN
      RAISE EXCEPTION 'an approval''s current step and managed-service flag are not written here'
        USING ERRCODE = 'AMW02';  -- no legal writer exists yet (step advance is not built)
    END IF;
    IF OLD.state IN ('APPROVED', 'REJECTED', 'CHANGES_REQUESTED', 'WITHDRAWN') THEN
      IF NEW.state IS DISTINCT FROM OLD.state OR NEW.decided_at IS DISTINCT FROM OLD.decided_at
         OR NEW.subject_sha256 IS DISTINCT FROM OLD.subject_sha256 THEN
        RAISE EXCEPTION 'a decided approval is immutable' USING ERRCODE = 'AMW02';
      END IF;
      RETURN NEW;
    END IF;
    IF NEW.state IN ('APPROVED', 'REJECTED', 'CHANGES_REQUESTED', 'WITHDRAWN') THEN
      IF OLD.state <> 'PENDING' OR current_user <> 'amw_verifier_fn' THEN
        RAISE EXCEPTION 'approvals.state is decided only through amw_approval_settle'
          USING ERRCODE = 'AMW02';
      END IF;
      IF NOT amw_approval_backed(NEW.org_id, NEW.id, NEW.state) THEN
        RAISE EXCEPTION 'no confirmed owner evidence backs this approval decision'
          USING ERRCODE = 'AMW02';
      END IF;
    ELSIF NEW.state IS DISTINCT FROM OLD.state OR NEW.decided_at IS DISTINCT FROM OLD.decided_at THEN
      -- EXPIRED / PENDING rewrites have no legal writer yet (expiry is not built): fail closed
      RAISE EXCEPTION 'approvals.state and decided_at change only through amw_approval_settle'
        USING ERRCODE = 'AMW02';
    ELSIF OLD.subject_sha256 IS NULL AND NEW.subject_sha256 IS NOT NULL
          AND OLD.state <> 'PENDING' THEN
      RAISE EXCEPTION 'the subject hash is set only while the approval is PENDING'
        USING ERRCODE = 'AMW02';
    END IF;
    RETURN NEW;
  END IF;

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
CREATE TRIGGER human_row_guard BEFORE INSERT OR UPDATE ON approvals
  FOR EACH ROW EXECUTE FUNCTION amw_human_row_guard();

-- tasks.approval_id: set once, to a PENDING approval of the same org and job; never rewritten.
CREATE FUNCTION amw_task_approval_pointer_guard() RETURNS trigger
  LANGUAGE plpgsql
  AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND NEW.approval_id IS NOT DISTINCT FROM OLD.approval_id THEN
    RETURN NEW;
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.approval_id IS NOT NULL THEN
    RAISE EXCEPTION 'tasks.approval_id is set once and never rewritten' USING ERRCODE = 'AMW02';
  END IF;
  IF NEW.approval_id IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM approvals a
        WHERE a.org_id = NEW.org_id AND a.id = NEW.approval_id AND a.state = 'PENDING'
          AND a.job_id IS NOT NULL AND a.job_id = NEW.job_id) THEN
    RAISE EXCEPTION 'tasks.approval_id points only to a PENDING approval of the same job'
      USING ERRCODE = 'AMW02';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER approval_pointer_guard BEFORE INSERT OR UPDATE OF approval_id ON tasks
  FOR EACH ROW EXECUTE FUNCTION amw_task_approval_pointer_guard();

-- Publish guard: the approving evidence is re-checked at use time (CCR-100: every consumer
-- re-checks); approvals.state alone is no longer trusted.
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
          AND a.kind IN ('FINAL_VIDEO', 'PUBLISH') AND a.subject_sha256 = NEW.render_sha256
          AND amw_approval_backed(a.org_id, a.id, 'APPROVED')) THEN
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
RESET ROLE;
