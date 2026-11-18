-- 0004 registry and compliance catalogue (04 section 5.2): org_production_types, rule_packs
-- (SHARED-CATALOGUE), compliance_profiles, compliance_profile_rule_packs.
SET LOCAL ROLE amw_owner;

-- UUIDv7 for the few rows the database itself creates (GLOSSARY section 2.1: application rows
-- get their IDs from amw_core.ids). RFC 9562 layout: 48-bit Unix ms, version 7, variant 10.
CREATE FUNCTION amw_uuid7() RETURNS uuid
  LANGUAGE plpgsql VOLATILE
  AS $$
DECLARE
  ms bigint := floor(extract(epoch FROM clock_timestamp()) * 1000);
  b bytea := uuid_send(gen_random_uuid());
BEGIN
  FOR i IN 0..5 LOOP
    b := set_byte(b, i, ((ms >> (8 * (5 - i))) & 255)::int);
  END LOOP;
  b := set_byte(b, 6, (get_byte(b, 6) & 15) | 112);
  b := set_byte(b, 8, (get_byte(b, 8) & 63) | 128);
  RETURN encode(b, 'hex')::uuid;
END
$$;

CREATE TABLE org_production_types (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  production_type_key text NOT NULL CHECK (production_type_key IN ('CHANNEL_LONG_FORM', 'SHORTS', 'AD_SPOT', 'EXPLAINER_CORPORATE_TRAINING', 'ECOMMERCE_PRODUCT', 'DUBBING_LOCALISATION')),
  enabled_version int NOT NULL,
  enabled boolean NOT NULL,
  overrides jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  UNIQUE (org_id, production_type_key),
  FOREIGN KEY (production_type_key, enabled_version) REFERENCES production_types (key, version)
);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON org_production_types
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('org_production_types', 'mutable');

CREATE TABLE rule_packs (
  id uuid PRIMARY KEY,
  org_id uuid REFERENCES organisations (id),
  key text NOT NULL CHECK (key ~ '^rp\.[a-z0-9_]+$'),
  version int NOT NULL CHECK (version >= 1),
  scope text NOT NULL CHECK (scope IN ('PLATFORM', 'TENANT')),
  category text NOT NULL CHECK (category IN ('youtube_general', 'finance', 'health', 'kids',
    'political_news', 'advertising', 'ad_sector', 'brand_safety')),
  always_on boolean NOT NULL,
  removable boolean NOT NULL,
  rules_ref text NOT NULL,
  rules_sha256 bytea NOT NULL CHECK (octet_length(rules_sha256) = 32),
  status text NOT NULL CHECK (status IN ('DRAFT', 'ACTIVE', 'RETIRED')),
  effective_from timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  CONSTRAINT rule_packs_platform_scope CHECK ((scope = 'PLATFORM') = (org_id IS NULL)),
  CONSTRAINT rule_packs_platform_not_removable CHECK (scope <> 'PLATFORM' OR NOT removable),
  CONSTRAINT rule_packs_always_on_general CHECK (NOT always_on OR key = 'rp.youtube_general')
);
CREATE UNIQUE INDEX rule_packs_key_version
  ON rule_packs (coalesce(org_id, '00000000-0000-0000-0000-000000000000'::uuid), key, version);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON rule_packs
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_catalogue_table('rule_packs', 'mutable');

CREATE TABLE compliance_profiles (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  workspace_id uuid NOT NULL,
  name text NOT NULL,
  version int NOT NULL CHECK (version >= 1),
  status text NOT NULL CHECK (status IN ('DRAFT', 'ACTIVE', 'RETIRED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  FOREIGN KEY (org_id, workspace_id) REFERENCES workspaces (org_id, id)
);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON compliance_profiles
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('compliance_profiles', 'mutable');

ALTER TABLE channels
  ADD FOREIGN KEY (org_id, compliance_profile_id) REFERENCES compliance_profiles (org_id, id);

CREATE TABLE compliance_profile_rule_packs (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  profile_id uuid NOT NULL,
  rule_pack_id uuid NOT NULL REFERENCES rule_packs (id),
  is_mandatory boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  UNIQUE (org_id, profile_id, rule_pack_id),
  FOREIGN KEY (org_id, profile_id) REFERENCES compliance_profiles (org_id, id)
);
SELECT amw_setup_tenant_table('compliance_profile_rule_packs', 'mutable_delete');

-- A link targets a platform pack or a pack of the same org (the plain FK to the catalogue cannot
-- express that); a mandatory link is never removed or weakened by the application roles
-- (04 section 5.2; section 1C.7: tenants add rules, never remove platform gates).
CREATE FUNCTION amw_profile_pack_guard() RETURNS trigger
  LANGUAGE plpgsql
  AS $$
BEGIN
  IF TG_OP IN ('INSERT', 'UPDATE') AND NOT EXISTS (
       SELECT 1 FROM rule_packs p
        WHERE p.id = NEW.rule_pack_id AND (p.org_id IS NULL OR p.org_id = NEW.org_id)) THEN
    RAISE EXCEPTION 'rule pack of another tenant' USING ERRCODE = 'AMW02';
  END IF;
  IF TG_OP IN ('UPDATE', 'DELETE') AND OLD.is_mandatory
     AND current_user IN ('amw_app', 'amw_publisher')
     AND (TG_OP = 'DELETE' OR NOT NEW.is_mandatory OR NEW.rule_pack_id <> OLD.rule_pack_id
          OR NEW.profile_id <> OLD.profile_id) THEN
    RAISE EXCEPTION 'mandatory rule pack link cannot be removed' USING ERRCODE = 'AMW02';
  END IF;
  RETURN CASE TG_OP WHEN 'DELETE' THEN OLD ELSE NEW END;
END
$$;
CREATE TRIGGER profile_pack_guard BEFORE INSERT OR UPDATE OR DELETE ON compliance_profile_rule_packs
  FOR EACH ROW EXECUTE FUNCTION amw_profile_pack_guard();

-- Creating a profile links the always-on platform pack rp.youtube_general (newest ACTIVE
-- version). No such pack = the platform catalogue is not loaded: fail closed (SQLSTATE AMW03 =
-- PERMANENT.MISSING_DEPENDENCY).
CREATE FUNCTION amw_profile_default_pack() RETURNS trigger
  LANGUAGE plpgsql
  AS $$
DECLARE
  pack uuid;
BEGIN
  SELECT p.id INTO pack FROM rule_packs p
   WHERE p.org_id IS NULL AND p.key = 'rp.youtube_general' AND p.status = 'ACTIVE'
   ORDER BY p.version DESC LIMIT 1;
  IF pack IS NULL THEN
    RAISE EXCEPTION 'platform rule pack rp.youtube_general is not loaded' USING ERRCODE = 'AMW03';
  END IF;
  INSERT INTO compliance_profile_rule_packs (id, org_id, profile_id, rule_pack_id, is_mandatory)
  VALUES (amw_uuid7(), NEW.org_id, NEW.id, pack, true);
  RETURN NEW;
END
$$;
CREATE TRIGGER profile_default_pack AFTER INSERT ON compliance_profiles
  FOR EACH ROW EXECUTE FUNCTION amw_profile_default_pack();

-- CCR-081: channel audience decision (13 section 3.7, YTG-R7), set only by a human; NULL = not
-- decided.
ALTER TABLE channels ADD COLUMN audience_kind text CHECK (audience_kind IN ('GENERAL', 'KIDS'));
