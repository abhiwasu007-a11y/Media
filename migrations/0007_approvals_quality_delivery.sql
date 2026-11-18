-- 0007 approvals and editorial contribution (04 section 5.16), quality / QC / compliance (5.17),
-- publications (5.21), notifications (5.23) and the publish guard.
-- Deferred on the coordinator's instruction until contract pass 3 lands: owner_instruction_evidence,
-- its roles and triggers, the human-row rule triggers, the compliance is_final guard and the
-- evidence_id foreign keys (the evidence model is being redesigned at database level).
SET LOCAL ROLE amw_owner;

CREATE TABLE approvals (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  job_id uuid,
  kind text NOT NULL CHECK (kind IN ('TOPIC', 'BRIEF', 'CONCEPT', 'SCRIPT', 'STORYBOARD', 'VOICE_SAMPLE', 'ROUGH_CUT', 'FINAL_VIDEO', 'THUMBNAIL', 'METADATA', 'PUBLISH', 'SPEND', 'NEW_CHANNEL', 'NEW_CATEGORY', 'SENSITIVE_CLAIM', 'COPYRIGHT_DOUBT', 'UNUSUAL_PUBLISH', 'POLICY_CHANGE', 'DLQ_REPLAY', 'EXPERIMENT', 'COMMENT_REPLY', 'KNOWLEDGE_RELEASE', 'USAGE_RIGHTS')),
  subject_kind text NOT NULL,
  subject_id uuid NOT NULL,
  subject_sha256 bytea CHECK (octet_length(subject_sha256) = 32),
  subject_ref text,
  state text NOT NULL CHECK (state IN ('PENDING', 'APPROVED', 'REJECTED', 'CHANGES_REQUESTED', 'EXPIRED', 'WITHDRAWN')),
  workflow_key text NOT NULL,
  current_step int NOT NULL,
  managed_service boolean NOT NULL,
  requested_by text NOT NULL,
  decided_at timestamptz,
  expires_at timestamptz,
  review_code text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  UNIQUE (org_id, review_code),
  FOREIGN KEY (org_id, job_id) REFERENCES jobs (org_id, id)
);
CREATE INDEX approvals_org_state_kind ON approvals (org_id, state, kind);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON approvals
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('approvals', 'mutable');

-- CCR-070: subject_ref is write-once.
CREATE FUNCTION amw_approval_subject_ref_once() RETURNS trigger
  LANGUAGE plpgsql
  AS $$
BEGIN
  IF OLD.subject_ref IS NOT NULL AND NEW.subject_ref IS DISTINCT FROM OLD.subject_ref THEN
    RAISE EXCEPTION 'approvals.subject_ref is write-once' USING ERRCODE = 'AMW02';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER subject_ref_once BEFORE UPDATE OF subject_ref ON approvals
  FOR EACH ROW EXECUTE FUNCTION amw_approval_subject_ref_once();

ALTER TABLE tasks ADD FOREIGN KEY (org_id, approval_id) REFERENCES approvals (org_id, id);
ALTER TABLE dead_letter ADD FOREIGN KEY (org_id, replay_approval_id) REFERENCES approvals (org_id, id);

CREATE TABLE approval_steps (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  approval_id uuid NOT NULL,
  step_no int NOT NULL,
  required_role text NOT NULL CHECK (required_role IN ('PLATFORM_OWNER', 'ORG_OWNER', 'ORG_ADMIN', 'PRODUCER', 'REVIEWER_APPROVER', 'FINANCE', 'VIEWER', 'CLIENT_GUEST')),
  assignee_user_id uuid REFERENCES users (id),
  state text NOT NULL CHECK (state IN ('NOT_STARTED', 'PENDING', 'APPROVED', 'REJECTED', 'CHANGES_REQUESTED', 'SKIPPED')),
  decided_by uuid REFERENCES users (id),
  decided_at timestamptz,
  comment text,
  approval_channel text CHECK (approval_channel IN ('OWNER_CHAT_OPERATOR', 'WEB_DASHBOARD', 'CLIENT_PORTAL')),
  recorded_by text,
  evidence_id uuid,  -- TFK -> owner_instruction_evidence (added with contract pass 3)
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  UNIQUE (org_id, approval_id, step_no),
  FOREIGN KEY (org_id, approval_id) REFERENCES approvals (org_id, id),
  CONSTRAINT approval_steps_channel_once_decided
    CHECK (state IN ('NOT_STARTED', 'PENDING') OR approval_channel IS NOT NULL),
  CONSTRAINT approval_steps_operator_evidence
    CHECK (approval_channel IS DISTINCT FROM 'OWNER_CHAT_OPERATOR' OR evidence_id IS NOT NULL)
);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON approval_steps
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('approval_steps', 'mutable');

CREATE TABLE editorial_contributions (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  job_id uuid NOT NULL,
  approval_id uuid,
  contributor_user_id uuid NOT NULL REFERENCES users (id),
  approval_channel text NOT NULL CHECK (approval_channel IN ('OWNER_CHAT_OPERATOR', 'WEB_DASHBOARD', 'CLIENT_PORTAL')),
  recorded_by text NOT NULL,
  evidence_id uuid,  -- TFK -> owner_instruction_evidence (added with contract pass 3)
  type text NOT NULL CHECK (type IN ('ANGLE', 'EXAMPLE', 'OPINION', 'CORRECTION')),
  description text NOT NULL,
  target_ref text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  FOREIGN KEY (org_id, job_id) REFERENCES jobs (org_id, id),
  FOREIGN KEY (org_id, approval_id) REFERENCES approvals (org_id, id),
  CONSTRAINT editorial_operator_evidence
    CHECK (approval_channel <> 'OWNER_CHAT_OPERATOR' OR evidence_id IS NOT NULL)
);
CREATE INDEX editorial_contributions_org_job ON editorial_contributions (org_id, job_id);
SELECT amw_setup_tenant_table('editorial_contributions', 'mutable');

CREATE TABLE quality_scores (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  job_id uuid NOT NULL,
  subject_kind text NOT NULL,
  subject_id uuid NOT NULL,
  subject_sha256 bytea NOT NULL CHECK (octet_length(subject_sha256) = 32),
  rubric_version text NOT NULL,
  dimension text NOT NULL CHECK (dimension IN ('RESEARCH_ACCURACY', 'STORYTELLING', 'AUDIENCE_VALUE', 'VISUAL_QUALITY', 'AUDIO_QUALITY', 'EDITING_QUALITY', 'THUMBNAIL_METADATA', 'COMPLIANCE')),
  max_points smallint NOT NULL,
  points numeric(5, 2) NOT NULL,
  scorer_kind text NOT NULL CHECK (scorer_kind IN ('DETERMINISTIC', 'LLM_JUDGE', 'HUMAN')),
  scorer_ref text NOT NULL,
  evidence_ref text,
  approval_channel text CHECK (approval_channel IN ('OWNER_CHAT_OPERATOR', 'WEB_DASHBOARD', 'CLIENT_PORTAL')),
  recorded_by text,
  evidence_id uuid,  -- TFK -> owner_instruction_evidence (added with contract pass 3)
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  FOREIGN KEY (org_id, job_id) REFERENCES jobs (org_id, id),
  CONSTRAINT quality_scores_max_points CHECK (max_points = CASE dimension
    WHEN 'RESEARCH_ACCURACY' THEN 20 WHEN 'STORYTELLING' THEN 15 WHEN 'AUDIENCE_VALUE' THEN 15
    WHEN 'VISUAL_QUALITY' THEN 15 WHEN 'AUDIO_QUALITY' THEN 10 WHEN 'EDITING_QUALITY' THEN 10
    WHEN 'THUMBNAIL_METADATA' THEN 10 WHEN 'COMPLIANCE' THEN 5 END),
  CONSTRAINT quality_scores_points_range CHECK (points >= 0 AND points <= max_points),
  CONSTRAINT quality_scores_human_fields CHECK (scorer_kind <> 'HUMAN'
    OR (approval_channel IS NOT NULL AND recorded_by IS NOT NULL AND evidence_id IS NOT NULL
        AND scorer_ref ~ '^usr_[0-9a-f-]{36}$'))
);
CREATE INDEX quality_scores_org_job_subject ON quality_scores (org_id, job_id, subject_id);
SELECT amw_setup_tenant_table('quality_scores', 'mutable');

CREATE TABLE qc_results (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  job_id uuid NOT NULL,
  task_id uuid NOT NULL,
  render_id uuid,
  check_id text NOT NULL CHECK (check_id ~ '^[a-z0-9_.-]{3,96}$'),
  kind text NOT NULL CHECK (kind IN ('DETERMINISTIC', 'LLM_JUDGE', 'HUMAN')),
  verdict text NOT NULL CHECK (verdict IN ('PASS', 'FAIL', 'WARN', 'SKIPPED')),
  blocking boolean NOT NULL,
  rule_id text,
  measured_num numeric,
  measured_text text,
  threshold_num numeric,
  threshold_text text,
  unit text,
  message text NOT NULL,
  evidence_ref text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  FOREIGN KEY (org_id, job_id) REFERENCES jobs (org_id, id),
  FOREIGN KEY (org_id, task_id) REFERENCES tasks (org_id, id),
  FOREIGN KEY (org_id, render_id) REFERENCES renders (org_id, id)
);
CREATE INDEX qc_results_org_job_check ON qc_results (org_id, job_id, check_id);
SELECT amw_setup_tenant_table('qc_results', 'mutable');

CREATE TABLE compliance_verdicts (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  job_id uuid NOT NULL,
  subject_kind text NOT NULL,
  subject_id uuid NOT NULL,
  subject_sha256 bytea NOT NULL CHECK (octet_length(subject_sha256) = 32),
  rule_pack_id uuid REFERENCES rule_packs (id),
  rule_pack_version int,
  rule_id text,
  verdict text NOT NULL CHECK (verdict IN ('ALLOWED', 'BLOCKED', 'NEEDS_HUMAN_REVIEW')),
  disclosure_decision text CHECK (disclosure_decision IN ('REQUIRED', 'NOT_REQUIRED', 'NEEDS_HUMAN_REVIEW')),
  rationale text NOT NULL,
  evidence_ref text,
  decided_by text NOT NULL,
  is_final boolean NOT NULL,
  evidence_id uuid,  -- TFK -> owner_instruction_evidence (added with contract pass 3)
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  FOREIGN KEY (org_id, job_id) REFERENCES jobs (org_id, id),
  CONSTRAINT compliance_verdicts_pack_null
    CHECK (rule_pack_id IS NOT NULL OR (rule_id IS NULL AND is_final)),
  CONSTRAINT compliance_verdicts_pack_version CHECK ((rule_pack_id IS NULL) = (rule_pack_version IS NULL))
);
CREATE INDEX compliance_verdicts_org_job_final ON compliance_verdicts (org_id, job_id, is_final);
SELECT amw_setup_tenant_table('compliance_verdicts', 'mutable');

CREATE TABLE publications (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  job_id uuid NOT NULL,
  channel_id uuid,
  render_id uuid NOT NULL,
  render_sha256 bytea NOT NULL CHECK (octet_length(render_sha256) = 32),
  destination_kind text NOT NULL CHECK (destination_kind IN ('YOUTUBE', 'FILE_DELIVERY')),
  state text NOT NULL CHECK (state IN ('DRAFT', 'UPLOADING', 'UPLOADED_PRIVATE', 'PROCESSING', 'READY_PRIVATE', 'SCHEDULED', 'PUBLISHED', 'DELIVERED', 'VERIFIED', 'FAILED', 'REMOVED')),
  privacy_status text CHECK (privacy_status IN ('private', 'public', 'unlisted')),
  external_video_id text,
  upload_session_ct bytea,
  upload_session_nonce bytea,
  contains_synthetic_media boolean,
  disclosure_verdict_id uuid,
  approval_id uuid NOT NULL,
  authorisation_verdict_id uuid NOT NULL,
  gcp_project_id uuid,  -- FK -> gcp_projects (0007)
  scheduled_publish_at timestamptz,
  published_at timestamptz,
  verification_state text NOT NULL DEFAULT 'NOT_CHECKED'
    CHECK (verification_state IN ('NOT_CHECKED', 'MATCH', 'MISMATCH')),
  verified_at timestamptz,
  verification_details jsonb,
  idempotency_key text NOT NULL CHECK (idempotency_key ~ '^idk_[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  UNIQUE (org_id, external_video_id),
  UNIQUE (org_id, idempotency_key),
  FOREIGN KEY (org_id, job_id) REFERENCES jobs (org_id, id),
  FOREIGN KEY (org_id, channel_id) REFERENCES channels (org_id, id),
  FOREIGN KEY (org_id, render_id) REFERENCES renders (org_id, id),
  FOREIGN KEY (org_id, disclosure_verdict_id) REFERENCES compliance_verdicts (org_id, id),
  FOREIGN KEY (org_id, approval_id) REFERENCES approvals (org_id, id),
  FOREIGN KEY (org_id, authorisation_verdict_id) REFERENCES compliance_verdicts (org_id, id),
  CONSTRAINT publications_youtube_channel CHECK (destination_kind <> 'YOUTUBE' OR channel_id IS NOT NULL),
  CONSTRAINT publications_youtube_synthetic
    CHECK (destination_kind <> 'YOUTUBE' OR contains_synthetic_media IS NOT NULL)
);
CREATE UNIQUE INDEX publications_no_duplicate_youtube ON publications (org_id, channel_id, render_sha256)
  WHERE destination_kind = 'YOUTUBE' AND state <> 'FAILED';
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON publications
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('publications', 'mutable');

-- Publish guard (04 section 5.21; rule 5: never publish an unapproved video).
CREATE FUNCTION amw_publish_guard() RETURNS trigger
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
        WHERE c.org_id = NEW.org_id AND c.job_id = NEW.job_id AND c.approval_id = NEW.approval_id) THEN
    RAISE EXCEPTION 'publish guard: no editorial contribution bound to the approval'
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
CREATE TRIGGER publish_guard BEFORE INSERT OR UPDATE OF state ON publications
  FOR EACH ROW EXECUTE FUNCTION amw_publish_guard();

CREATE TABLE notifications (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  user_id uuid NOT NULL REFERENCES users (id),
  channel text NOT NULL CHECK (channel IN ('EMAIL', 'IN_APP', 'WHATSAPP', 'SLACK')),
  template_key text NOT NULL,
  subject_kind text NOT NULL,
  subject_id uuid NOT NULL,
  status text NOT NULL CHECK (status IN ('QUEUED', 'SENT', 'FAILED', 'READ')),
  sent_at timestamptz,
  read_at timestamptz,
  error_code text,
  idempotency_key text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  UNIQUE (org_id, idempotency_key)
);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON notifications
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('notifications', 'mutable');
