-- 0055 own review code for evidence without an approval (CCR-116; 04 section 5.16
-- owner_instruction_evidence.review_code; 03 section 11.6 rule 7; ticket P4-01).
-- An OWNER_TOPIC / DATASET_INTAKE evidence, and any other CONTENT / SCORE evidence that has no
-- approval_id, carries its own review code: the format and alphabet of approvals.review_code
-- (CCR-090: 23456789ABCDEFGHJKMNPQRSTUVWXYZ, at least one letter and one digit, 4 to 8 characters:
-- the configured length is 4 by default, Q-O11), stored in upper case.
-- review_codes is the one registry of every code of an org: a PRIMARY KEY (org_id, code) makes a
-- code resolve to exactly one owner (an approval or an own-code evidence) under every isolation
-- level (a unique index sees concurrent and committed rows regardless of the snapshot).
-- Evidence tied to an approval carries exactly that approval's code (checked against approvals),
-- so "confirm <code>" can only ever resolve to the rows issued for that code. Approval codes are
-- immutable. A code is never reused: refused rows keep theirs.
-- The evidence store issues the code before it computes evidence_sha256 (which covers
-- review_code), so the code is supplied with the INSERT; this file is the authority for its
-- format and uniqueness.
SET LOCAL ROLE amw_owner;

-- The record kinds whose verification rule is CONTENT or SCORE (03 section 11.6 rule 7 table).
CREATE FUNCTION amw_evidence_own_code_kind(p_record_kind text) RETURNS boolean
  LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, pg_temp
  AS $$
  SELECT p_record_kind IN ('CONTRIBUTION', 'REVISION_NOTE', 'OWNER_TOPIC', 'DATASET_INTAKE',
                           'HUMAN_SCORE')
$$;
REVOKE ALL ON FUNCTION amw_evidence_own_code_kind(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION amw_evidence_own_code_kind(text)
  TO amw_app, amw_publisher, amw_operator, amw_verifier, amw_verifier_fn;

CREATE TABLE review_codes (
  org_id uuid NOT NULL REFERENCES organisations (id),
  code text NOT NULL,
  owner_kind text NOT NULL CHECK (owner_kind IN ('APPROVAL', 'EVIDENCE')),
  owner_id uuid NOT NULL,
  PRIMARY KEY (org_id, code),
  CHECK (code = upper(code)),
  CHECK (owner_kind <> 'EVIDENCE'
         OR (code ~ '^[2-9A-HJKMNP-Z]{4,8}$' AND code ~ '[2-9]' AND code ~ '[A-HJKMNP-Z]'))
);
ALTER TABLE review_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_codes FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON review_codes
  USING (org_id = amw_current_org()) WITH CHECK (org_id = amw_current_org());
REVOKE ALL ON review_codes FROM PUBLIC;
GRANT SELECT, INSERT ON review_codes TO amw_app, amw_publisher, amw_operator;
GRANT SELECT ON review_codes TO amw_verifier, amw_verifier_fn, amw_readonly;
INSERT INTO review_codes (org_id, code, owner_kind, owner_id)
  SELECT org_id, upper(review_code), 'APPROVAL', id FROM approvals;

-- Which row a code was issued for: (owner_kind, owner_id) or no row.
CREATE FUNCTION amw_review_code_owner(p_org_id uuid, p_code text)
  RETURNS TABLE (owner_kind text, owner_id uuid)
  LANGUAGE sql STABLE SET search_path = pg_catalog, public, pg_temp
  AS $$
  SELECT c.owner_kind, c.owner_id FROM review_codes c
   WHERE c.org_id = p_org_id AND c.code = upper(p_code)
$$;
REVOKE ALL ON FUNCTION amw_review_code_owner(uuid, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION amw_review_code_owner(uuid, text)
  TO amw_app, amw_operator, amw_verifier, amw_verifier_fn;

CREATE FUNCTION amw_review_code_register(p_org_id uuid, p_code text, p_kind text, p_owner uuid)
  RETURNS void
  LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp
  AS $$
BEGIN
  INSERT INTO review_codes (org_id, code, owner_kind, owner_id)
    VALUES (p_org_id, upper(p_code), p_kind, p_owner);
EXCEPTION
  WHEN unique_violation THEN
    RAISE EXCEPTION 'review code already used in this org' USING ERRCODE = 'AMW02';
  WHEN check_violation THEN
    RAISE EXCEPTION 'malformed own review code (CCR-090 format, upper case, 4 to 8 characters)'
      USING ERRCODE = 'AMW02';
END
$$;
REVOKE ALL ON FUNCTION amw_review_code_register(uuid, text, text, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION amw_review_code_register(uuid, text, text, uuid)
  TO amw_app, amw_publisher, amw_operator, amw_verifier_fn;

CREATE FUNCTION amw_evidence_review_code_guard() RETURNS trigger
  LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp
  AS $$
DECLARE
  v_code text;
BEGIN
  IF NEW.approval_id IS NOT NULL THEN
    -- Tied to an approval: carries exactly that approval's code (never another row's code).
    SELECT a.review_code INTO v_code FROM approvals a
     WHERE a.org_id = NEW.org_id AND a.id = NEW.approval_id;
    IF NEW.review_code IS NULL AND NEW.state = 'REFUSED' THEN
      RETURN NEW;
    END IF;
    IF v_code IS NULL OR NEW.review_code IS NULL OR upper(NEW.review_code) <> upper(v_code) THEN
      RAISE EXCEPTION 'evidence tied to an approval carries that approval''s review code'
        USING ERRCODE = 'AMW02';
    END IF;
    RETURN NEW;
  END IF;
  IF NOT amw_evidence_own_code_kind(NEW.record_kind) THEN
    RETURN NEW;
  END IF;
  IF NEW.review_code IS NULL THEN
    IF NEW.state <> 'REFUSED' THEN
      RAISE EXCEPTION 'evidence without an approval needs its own review code (CCR-116)'
        USING ERRCODE = 'AMW02';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.review_code <> upper(NEW.review_code) THEN
    RAISE EXCEPTION 'own review code must be upper case' USING ERRCODE = 'AMW02';
  END IF;
  PERFORM amw_review_code_register(NEW.org_id, NEW.review_code, 'EVIDENCE', NEW.id);
  RETURN NEW;
END
$$;
REVOKE ALL ON FUNCTION amw_evidence_review_code_guard() FROM PUBLIC;
CREATE TRIGGER evidence_review_code_guard BEFORE INSERT ON owner_instruction_evidence
  FOR EACH ROW EXECUTE FUNCTION amw_evidence_review_code_guard();

-- Approval codes enter the same registry and never change afterwards.
CREATE FUNCTION amw_approval_review_code_guard() RETURNS trigger
  LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp
  AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF NEW.review_code IS DISTINCT FROM OLD.review_code OR NEW.org_id IS DISTINCT FROM OLD.org_id THEN
      RAISE EXCEPTION 'an approval review code is immutable' USING ERRCODE = 'AMW02';
    END IF;
    RETURN NEW;
  END IF;
  PERFORM amw_review_code_register(NEW.org_id, NEW.review_code, 'APPROVAL', NEW.id);
  RETURN NEW;
END
$$;
REVOKE ALL ON FUNCTION amw_approval_review_code_guard() FROM PUBLIC;
CREATE TRIGGER approval_review_code_guard BEFORE INSERT OR UPDATE OF review_code, org_id
  ON approvals FOR EACH ROW EXECUTE FUNCTION amw_approval_review_code_guard();
