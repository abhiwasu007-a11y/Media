-- 0006 memory (04 section 5.10), scripts (5.11), licences and assets (5.15), voices (5.12),
-- renders (5.18), licence_ledger (5.15).
SET LOCAL ROLE amw_owner;

CREATE TABLE memory_items (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  scope text NOT NULL CHECK (scope IN ('WORKING', 'TASK', 'PROJECT', 'CHANNEL', 'LONG_TERM')),
  workspace_id uuid NOT NULL,
  channel_id uuid,
  project_id uuid,
  job_id uuid,
  task_id uuid,
  key text NOT NULL,
  value jsonb,
  value_ref text,
  provenance_ref text NOT NULL,
  confidence numeric(4, 3) CHECK (confidence BETWEEN 0 AND 1),
  created_by text NOT NULL,
  expires_at timestamptz,
  review_after timestamptz,
  superseded_by uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  FOREIGN KEY (org_id, workspace_id) REFERENCES workspaces (org_id, id),
  FOREIGN KEY (org_id, channel_id) REFERENCES channels (org_id, id),
  FOREIGN KEY (org_id, project_id) REFERENCES projects (org_id, id),
  FOREIGN KEY (org_id, job_id) REFERENCES jobs (org_id, id),
  FOREIGN KEY (org_id, task_id) REFERENCES tasks (org_id, id),
  FOREIGN KEY (org_id, superseded_by) REFERENCES memory_items (org_id, id),
  CONSTRAINT memory_items_channel_scope
    CHECK (scope NOT IN ('CHANNEL', 'LONG_TERM') OR channel_id IS NOT NULL),
  CONSTRAINT memory_items_project_scope CHECK (scope <> 'PROJECT' OR project_id IS NOT NULL),
  CONSTRAINT memory_items_task_scope
    CHECK (scope NOT IN ('TASK', 'WORKING') OR (job_id IS NOT NULL AND task_id IS NOT NULL)),
  CONSTRAINT memory_items_one_value CHECK ((value IS NULL) <> (value_ref IS NULL)),
  CONSTRAINT memory_items_expiry
    CHECK (scope NOT IN ('WORKING', 'TASK', 'PROJECT') OR expires_at IS NOT NULL)
);
CREATE INDEX memory_items_lookup ON memory_items (org_id, scope, channel_id, key);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON memory_items
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('memory_items', 'mutable');

CREATE TABLE scripts (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  job_id uuid NOT NULL,
  channel_id uuid,
  language text NOT NULL,
  version int NOT NULL,
  iteration int NOT NULL,
  parent_script_id uuid,
  status text NOT NULL CHECK (status IN ('DRAFT', 'IN_REVIEW', 'APPROVED', 'REJECTED', 'SUPERSEDED')),
  body_ref text NOT NULL,
  content_sha256 bytea NOT NULL CHECK (octet_length(content_sha256) = 32),
  segment_count int NOT NULL,
  word_count int NOT NULL,
  est_duration_ms bigint,
  created_by_task_id uuid NOT NULL,
  prompt_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  UNIQUE (org_id, job_id, language, version),
  FOREIGN KEY (org_id, job_id) REFERENCES jobs (org_id, id),
  FOREIGN KEY (org_id, channel_id) REFERENCES channels (org_id, id),
  FOREIGN KEY (org_id, parent_script_id) REFERENCES scripts (org_id, id),
  FOREIGN KEY (org_id, created_by_task_id) REFERENCES tasks (org_id, id)
);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON scripts
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('scripts', 'mutable');

-- CCR-033: only status (and the Mut bookkeeping) of a script may change; content is write-once.
CREATE FUNCTION amw_only_status_changes() RETURNS trigger
  LANGUAGE plpgsql
  AS $$
BEGIN
  IF (to_jsonb(NEW) - 'status' - 'updated_at' - 'row_version')
     IS DISTINCT FROM (to_jsonb(OLD) - 'status' - 'updated_at' - 'row_version') THEN
    RAISE EXCEPTION '%: only status may change', TG_TABLE_NAME USING ERRCODE = 'AMW02';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER only_status_changes BEFORE UPDATE ON scripts
  FOR EACH ROW EXECUTE FUNCTION amw_only_status_changes();

CREATE TABLE licences (
  id uuid PRIMARY KEY,
  org_id uuid REFERENCES organisations (id),
  licence_key text NOT NULL,
  vendor text NOT NULL,
  source_type text NOT NULL CHECK (source_type IN ('OWNER_MADE', 'CLIENT_SUPPLIED', 'PAID_STOCK', 'FREE_STOCK', 'CODE_GENERATED', 'AI_GENERATED', 'MUSIC_LIBRARY', 'SFX_LIBRARY', 'FONT', 'TTS_PROVIDER', 'VOICE_CLONE', 'HUMAN_NARRATION')),
  licence_name text NOT NULL,
  covers_monetized_youtube boolean,
  third_party_permission text NOT NULL CHECK (third_party_permission IN ('PERMITTED', 'NOT_PERMITTED', 'UNKNOWN')),
  indemnification boolean,
  channel_registration_supported boolean,
  territory text,
  starts_at timestamptz NOT NULL,
  expires_at timestamptz,
  state text NOT NULL CHECK (state IN ('PENDING_VERIFICATION', 'ACTIVE', 'EXPIRING', 'EXPIRED', 'REVOKED', 'REJECTED')),
  terms_ref text NOT NULL,
  terms_sha256 bytea NOT NULL CHECK (octet_length(terms_sha256) = 32),
  verified_by uuid REFERENCES users (id),
  verified_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id)
);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON licences
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_catalogue_table('licences', 'mutable');

CREATE TABLE assets (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  workspace_id uuid,
  kind text NOT NULL CHECK (kind IN ('VIDEO', 'IMAGE', 'AUDIO_MUSIC', 'AUDIO_SFX', 'AUDIO_VOICE', 'FONT', 'CHART', 'SUBTITLE', 'TEMPLATE', 'DOCUMENT')),
  visual_source_tier text CHECK (visual_source_tier IN ('A_OWNER_REAL', 'B_LICENSED_STOCK', 'C_CODE_MOTION', 'D_AI_VIDEO', 'E_AI_STILL')),
  title text,
  storage_ref text NOT NULL,
  content_sha256 bytea NOT NULL CHECK (octet_length(content_sha256) = 32),
  size_bytes bigint NOT NULL,
  media_type text NOT NULL,
  duration_ms bigint,
  width_px int,
  height_px int,
  source_type text NOT NULL CHECK (source_type IN ('OWNER_MADE', 'CLIENT_SUPPLIED', 'PAID_STOCK', 'FREE_STOCK', 'CODE_GENERATED', 'AI_GENERATED', 'MUSIC_LIBRARY', 'SFX_LIBRARY', 'FONT', 'TTS_PROVIDER', 'VOICE_CLONE', 'HUMAN_NARRATION')),
  source_url text,
  vendor_item_id text,
  licence_id uuid REFERENCES licences (id),
  is_realistic_synthetic boolean NOT NULL,
  depicts_real_person boolean NOT NULL,
  release_ref text,
  allowed_channel_ids uuid[],
  expires_at timestamptz,
  status text NOT NULL CHECK (status IN ('ACTIVE', 'QUARANTINED', 'EXPIRED', 'DELETED')),
  attributes jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  UNIQUE (org_id, content_sha256),
  FOREIGN KEY (org_id, workspace_id) REFERENCES workspaces (org_id, id),
  CONSTRAINT assets_visual_tier
    CHECK (kind NOT IN ('VIDEO', 'IMAGE', 'CHART') OR visual_source_tier IS NOT NULL),
  CONSTRAINT assets_licence_required
    CHECK (source_type IN ('OWNER_MADE', 'CODE_GENERATED') OR licence_id IS NOT NULL)
);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON assets
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('assets', 'mutable');

CREATE TABLE voices (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  display_name text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('PROVIDER_STOCK', 'CONSENTED_CLONE', 'HUMAN_RECORDED')),
  provider text,
  provider_voice_ref text,
  languages text[] NOT NULL,
  consent_id uuid,  -- TFK -> voice_consents (T0+, created with Agent 07)
  pronunciation_dict_ref text,
  licence_id uuid REFERENCES licences (id),
  presenter_kind text NOT NULL CHECK (presenter_kind IN ('NEUTRAL_NARRATION', 'OWNER_VOICE', 'SYNTHETIC_PERSONA')),
  status text NOT NULL CHECK (status IN ('ACTIVE', 'QUARANTINED', 'EXPIRED', 'DELETED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  CONSTRAINT voices_clone_needs_consent CHECK (kind <> 'CONSENTED_CLONE' OR consent_id IS NOT NULL),
  CONSTRAINT voices_active_needs_licence CHECK (status <> 'ACTIVE' OR licence_id IS NOT NULL)
);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON voices
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('voices', 'mutable');

-- CCR-027 (provisional): presenter_kind derived at insert for a provider stock voice; every other
-- value comes from a recorded human decision and must be given explicitly.
CREATE FUNCTION amw_voice_presenter_default() RETURNS trigger
  LANGUAGE plpgsql
  AS $$
BEGIN
  IF NEW.presenter_kind IS NULL AND NEW.kind = 'PROVIDER_STOCK' THEN
    NEW.presenter_kind := 'NEUTRAL_NARRATION';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER voice_presenter_default BEFORE INSERT ON voices
  FOR EACH ROW EXECUTE FUNCTION amw_voice_presenter_default();

CREATE TABLE renders (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  job_id uuid NOT NULL,
  script_id uuid,
  kind text NOT NULL CHECK (kind IN ('MASTER', 'EXPORT', 'PREVIEW')),
  preset_key text NOT NULL,
  version int NOT NULL,
  timeline_sha256 bytea NOT NULL CHECK (octet_length(timeline_sha256) = 32),
  width_px int NOT NULL,
  height_px int NOT NULL,
  fps_num int NOT NULL,
  fps_den int NOT NULL,
  video_codec text NOT NULL,
  audio_codec text NOT NULL,
  video_bitrate_bps bigint,
  audio_bitrate_bps bigint,
  audio_sample_rate_hz int,
  duration_ms bigint NOT NULL,
  integrated_lufs numeric(5, 2),
  true_peak_dbtp numeric(5, 2),
  size_bytes bigint NOT NULL,
  storage_ref text NOT NULL,
  content_sha256 bytea NOT NULL CHECK (octet_length(content_sha256) = 32),
  status text NOT NULL CHECK (status IN ('RENDERING', 'COMPLETE', 'QC_PASSED', 'QC_FAILED', 'SUPERSEDED')),
  worker_id uuid REFERENCES workers (id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  UNIQUE (org_id, content_sha256),
  FOREIGN KEY (org_id, job_id) REFERENCES jobs (org_id, id),
  FOREIGN KEY (org_id, script_id) REFERENCES scripts (org_id, id)
);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON renders
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('renders', 'mutable');

CREATE TABLE licence_ledger (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  asset_id uuid NOT NULL,
  licence_id uuid NOT NULL REFERENCES licences (id),
  job_id uuid NOT NULL,
  render_id uuid,
  task_id uuid,
  shot_id text,
  usage_kind text NOT NULL CHECK (usage_kind IN ('SHOT', 'IMAGE', 'MUSIC_BED', 'SFX', 'VOICE', 'FONT', 'TEMPLATE', 'AI_OUTPUT')),
  source_url text,
  vendor_item_id text,
  used_from_ms bigint,
  used_to_ms bigint,
  client_permission_ref text,
  expiry_at timestamptz,
  recorded_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  FOREIGN KEY (org_id, asset_id) REFERENCES assets (org_id, id),
  FOREIGN KEY (org_id, job_id) REFERENCES jobs (org_id, id),
  FOREIGN KEY (org_id, render_id) REFERENCES renders (org_id, id),
  FOREIGN KEY (org_id, task_id) REFERENCES tasks (org_id, id),
  CONSTRAINT licence_ledger_replay_key
    UNIQUE NULLS NOT DISTINCT (org_id, task_id, asset_id, usage_kind, shot_id, used_from_ms)
);
CREATE INDEX licence_ledger_org_job ON licence_ledger (org_id, job_id);
CREATE INDEX licence_ledger_org_licence ON licence_ledger (org_id, licence_id);
SELECT amw_setup_tenant_table('licence_ledger', 'append_only');

-- Insert guard (04 section 5.15; CCR-028): ACTIVE licence of this org or the platform; a
-- platform-held licence used outside the platform owner org needs third-party permission; a
-- monetized destination needs covers_monetized_youtube = true.
CREATE FUNCTION amw_licence_ledger_guard() RETURNS trigger
  LANGUAGE plpgsql
  AS $$
DECLARE
  lic record;
  monetized boolean;
  platform_org boolean;
BEGIN
  SELECT l.org_id, l.state, l.third_party_permission, l.covers_monetized_youtube INTO lic
    FROM licences l WHERE l.id = NEW.licence_id AND (l.org_id IS NULL OR l.org_id = NEW.org_id);
  IF NOT FOUND THEN
    RAISE EXCEPTION 'licence not found for this tenant' USING ERRCODE = 'AMW02';
  END IF;
  IF lic.state <> 'ACTIVE' THEN
    RAISE EXCEPTION 'licence is not ACTIVE' USING ERRCODE = 'AMW02';
  END IF;
  SELECT o.is_platform_owner INTO platform_org FROM organisations o WHERE o.id = NEW.org_id;
  IF lic.org_id IS NULL AND NOT coalesce(platform_org, false)
     AND lic.third_party_permission <> 'PERMITTED' THEN
    RAISE EXCEPTION 'platform licence without third-party permission' USING ERRCODE = 'AMW02';
  END IF;
  SELECT j.monetized_destination INTO monetized FROM jobs j
   WHERE j.org_id = NEW.org_id AND j.id = NEW.job_id;
  IF coalesce(monetized, true) AND lic.covers_monetized_youtube IS NOT TRUE THEN
    RAISE EXCEPTION 'licence does not cover monetized YouTube use' USING ERRCODE = 'AMW02';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER licence_ledger_guard BEFORE INSERT ON licence_ledger
  FOR EACH ROW EXECUTE FUNCTION amw_licence_ledger_guard();
