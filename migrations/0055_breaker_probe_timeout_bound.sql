-- 0055 server-side upper bound of the probe lease (P4-05, CCR-108 follow-up; home of the bound
-- PROPOSED as CCR-168). Re-check L1b m-1: amw_breaker_admit took the lease length from the caller,
-- so a caller could lease a HALF_OPEN probe for years and wedge the breaker. The bound is platform
-- configuration, not a literal: platform_controls key 'breaker_probe_timeout_max_ms', a jsonb
-- object "<provider>.<operation_class>" -> maximum lease in ms (written only by PLATFORM_OWNER
-- through amw_sysfn, 04 section 5.1). No value ships with this migration: the values are
-- REQUIRES REVIEW (Phase 1): measure the slowest legitimate call per operation class (07 section
-- 4.2). No key, no entry, an entry that is not a positive integer, or a requested lease above the
-- entry refuses every admission with SQLSTATE AMW04 (PERMANENT.CONFIG_INVALID), fail closed.
-- Numbering: 0052, 0053 and 0054 are taken by the open PRs #54, #58 and #60; this file does not
-- depend on them. amw_sysfn owns amw_breaker_admit; this file re-grants SET on it for its own
-- transaction only and revokes it again at the end (the L1a hardening of 0010 stays in force).
SET LOCAL ROLE amw_owner;
ALTER TABLE platform_controls DROP CONSTRAINT platform_controls_key_check;
ALTER TABLE platform_controls ADD CONSTRAINT platform_controls_key_check
  CHECK (key IN ('platform_emergency_stop', 'admission_paused', 'breaker_probe_timeout_max_ms'));
ALTER TABLE platform_controls ADD CONSTRAINT platform_controls_probe_bound_shape
  CHECK (key <> 'breaker_probe_timeout_max_ms' OR jsonb_typeof(value) = 'object');
GRANT SELECT ON platform_controls TO amw_sysfn;
RESET ROLE;
GRANT amw_sysfn TO amw_owner WITH INHERIT FALSE, SET TRUE;
SET LOCAL ROLE amw_sysfn;

-- Same body as 0051 plus the bound check before the row lock (an error changes nothing).
CREATE OR REPLACE FUNCTION amw_breaker_admit(
  p_provider text, p_operation_class text, p_credential_scope text, p_half_open_max_probes int,
  p_probe_timeout_ms bigint)
  RETURNS TABLE (admitted boolean, state text, open_until timestamptz, epoch bigint)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
  AS $$
DECLARE
  b circuit_breakers;
  v_bound jsonb;
BEGIN
  IF p_half_open_max_probes < 1 OR p_probe_timeout_ms IS NULL OR p_probe_timeout_ms < 1 THEN
    RAISE EXCEPTION 'half_open_max_probes >= 1 and a probe timeout are required' USING ERRCODE = '22023';
  END IF;
  SELECT pc.value -> (p_provider || '.' || p_operation_class) INTO v_bound
    FROM platform_controls pc WHERE pc.key = 'breaker_probe_timeout_max_ms';
  IF v_bound IS NULL OR jsonb_typeof(v_bound) <> 'number'
     OR v_bound::numeric < 1 OR v_bound::numeric <> trunc(v_bound::numeric) THEN
    RAISE EXCEPTION 'no server-side probe lease bound for %.%', p_provider, p_operation_class
      USING ERRCODE = 'AMW04';
  END IF;
  IF p_probe_timeout_ms > v_bound::numeric THEN
    RAISE EXCEPTION 'probe lease of % ms is above the server-side bound for %.%',
      p_probe_timeout_ms, p_provider, p_operation_class USING ERRCODE = 'AMW04';
  END IF;
  SELECT * INTO b FROM circuit_breakers c
   WHERE c.provider = p_provider AND c.operation_class = p_operation_class
     AND c.credential_scope = p_credential_scope FOR UPDATE;
  IF NOT FOUND OR b.state = 'CLOSED' THEN
    admitted := true; state := coalesce(b.state, 'CLOSED'); open_until := NULL;
    epoch := coalesce(b.half_open_epoch, 0);
    RETURN NEXT;
    RETURN;
  END IF;
  IF b.state = 'OPEN' THEN
    IF now() < b.open_until THEN
      admitted := false; state := b.state; open_until := b.open_until; epoch := b.half_open_epoch;
      RETURN NEXT;
      RETURN;
    END IF;
    b.state := 'HALF_OPEN';
    b.half_open_in_flight := 0;
    b.half_open_epoch := b.half_open_epoch + 1;
    b.window_started_at := now();
    b.window_calls := 0;
    b.window_failures := 0;
  END IF;
  -- probes that never reported (crashed worker, refused after admission) are reclaimed once the
  -- lease of the last admitted probe has expired
  IF b.half_open_in_flight > 0 AND now() > b.half_open_probe_until THEN
    b.half_open_in_flight := 0;
    b.half_open_epoch := b.half_open_epoch + 1;
  END IF;
  IF b.half_open_in_flight >= p_half_open_max_probes THEN
    admitted := false;
  ELSE
    b.half_open_in_flight := b.half_open_in_flight + 1;
    b.half_open_probe_until := now() + make_interval(secs => p_probe_timeout_ms / 1000.0);
    admitted := true;
  END IF;
  UPDATE circuit_breakers c
     SET state = b.state, half_open_in_flight = b.half_open_in_flight,
         half_open_probe_until = b.half_open_probe_until, half_open_epoch = b.half_open_epoch,
         window_started_at = b.window_started_at, window_calls = b.window_calls,
         window_failures = b.window_failures, row_version = c.row_version + 1
   WHERE c.id = b.id;
  state := b.state; open_until := b.open_until; epoch := b.half_open_epoch;
  RETURN NEXT;
END
$$;
REVOKE ALL ON FUNCTION amw_breaker_admit(text, text, text, int, bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION amw_breaker_admit(text, text, text, int, bigint) TO amw_app, amw_publisher;

RESET ROLE;
GRANT amw_sysfn TO amw_owner WITH INHERIT FALSE, SET FALSE;
