-- 0052 own review code for evidence without an approval (CCR-116; 04 section 5.16
-- owner_instruction_evidence.review_code; 03 section 11.6 rule 7; ticket P4-01).
-- An OWNER_TOPIC / DATASET_INTAKE evidence, and any other CONTENT / SCORE evidence that has no
-- approval_id, carries its own review code: the format and alphabet of approvals.review_code
-- (CCR-090: 23456789ABCDEFGHJKMNPQRSTUVWXYZ, at least one letter and one digit), stored in upper
-- case, unique per org across approval codes and evidence codes (matching is case-insensitive).
-- The evidence store issues the code before it computes evidence_sha256 (which covers
-- review_code), so the code is supplied with the INSERT; this file is the authority for its
-- format and uniqueness. A code is never reused: refused rows keep theirs.
-- Uniqueness across the two tables: a transaction advisory lock on (org, code) in both triggers
-- serialises concurrent writers of the same code (READ COMMITTED: each statement of the
-- function takes a fresh snapshot after the lock), and a partial unique index covers evidence.
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

CREATE FUNCTION amw_review_code_lock(p_org_id uuid, p_code text) RETURNS void
  LANGUAGE sql SET search_path = pg_catalog, pg_temp
  AS $$
  SELECT pg_advisory_xact_lock(hashtextextended('amw_review_code:' || p_org_id::text || ':'
                                                || upper(p_code), 0))
$$;
REVOKE ALL ON FUNCTION amw_review_code_lock(uuid, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION amw_review_code_lock(uuid, text)
  TO amw_app, amw_publisher, amw_operator, amw_verifier_fn;

CREATE UNIQUE INDEX evidence_own_review_code
  ON owner_instruction_evidence (org_id, upper(review_code))
  WHERE approval_id IS NULL AND review_code IS NOT NULL;

CREATE FUNCTION amw_evidence_review_code_guard() RETURNS trigger
  LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp
  AS $$
BEGIN
  IF NEW.approval_id IS NOT NULL OR NOT amw_evidence_own_code_kind(NEW.record_kind) THEN
    RETURN NEW;
  END IF;
  IF NEW.review_code IS NULL THEN
    IF NEW.state <> 'REFUSED' THEN
      RAISE EXCEPTION 'evidence without an approval needs its own review code (CCR-116)'
        USING ERRCODE = 'AMW02';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.review_code !~ '^[2-9A-HJKMNP-Z]+$' OR NEW.review_code !~ '[2-9]'
     OR NEW.review_code !~ '[A-HJKMNP-Z]' THEN
    RAISE EXCEPTION 'malformed own review code (CCR-090 format, upper case)'
      USING ERRCODE = 'AMW02';
  END IF;
  PERFORM amw_review_code_lock(NEW.org_id, NEW.review_code);
  IF EXISTS (SELECT 1 FROM approvals a
              WHERE a.org_id = NEW.org_id AND upper(a.review_code) = NEW.review_code) THEN
    RAISE EXCEPTION 'review code already used by an approval of this org' USING ERRCODE = 'AMW02';
  END IF;
  IF EXISTS (SELECT 1 FROM owner_instruction_evidence e
              WHERE e.org_id = NEW.org_id AND e.approval_id IS NULL
                AND upper(e.review_code) = NEW.review_code) THEN
    RAISE EXCEPTION 'review code already used by an evidence of this org' USING ERRCODE = 'AMW02';
  END IF;
  RETURN NEW;
END
$$;
REVOKE ALL ON FUNCTION amw_evidence_review_code_guard() FROM PUBLIC;
CREATE TRIGGER evidence_review_code_guard BEFORE INSERT ON owner_instruction_evidence
  FOR EACH ROW EXECUTE FUNCTION amw_evidence_review_code_guard();

-- An approval code must not equal an evidence's own code (UNIQUE (org_id, review_code) already
-- covers approvals among themselves; this adds the case-insensitive cross-table check).
CREATE FUNCTION amw_approval_review_code_guard() RETURNS trigger
  LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp
  AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND NEW.review_code IS NOT DISTINCT FROM OLD.review_code
     AND NEW.org_id IS NOT DISTINCT FROM OLD.org_id THEN
    RETURN NEW;
  END IF;
  PERFORM amw_review_code_lock(NEW.org_id, NEW.review_code);
  IF EXISTS (SELECT 1 FROM owner_instruction_evidence e
              WHERE e.org_id = NEW.org_id AND e.approval_id IS NULL
                AND upper(e.review_code) = upper(NEW.review_code)) THEN
    RAISE EXCEPTION 'review code already used by an evidence of this org' USING ERRCODE = 'AMW02';
  END IF;
  RETURN NEW;
END
$$;
REVOKE ALL ON FUNCTION amw_approval_review_code_guard() FROM PUBLIC;
CREATE TRIGGER approval_review_code_guard BEFORE INSERT OR UPDATE OF review_code, org_id
  ON approvals FOR EACH ROW EXECUTE FUNCTION amw_approval_review_code_guard();
