-- 0051 breaker probe admission (lane L1b; CCR-108, PROPOSED). Review PR #44 M3: HALF_OPEN admitted
-- every worker because no function persisted the probe count. Adds amw_breaker_admit (atomic: row
-- lock, check, count, probe lease) and replaces amw_breaker_record (one optional argument added) so
-- that a finished probe releases its slot (also an uncounted failure), a re-open from HALF_OPEN
-- keeps the first opened_at and every open or close resets the in-flight count and the window.
-- amw_sysfn owns both functions; this file re-grants SET on it for its own transaction only and
-- revokes it again at the end (the L1a hardening of 0010 stays in force). Both functions pin
-- search_path to end with pg_temp.
-- The probe lease needs one column on the L1a table (owner amw_owner).
SET LOCAL ROLE amw_owner;
ALTER TABLE circuit_breakers ADD COLUMN half_open_probe_until timestamptz;
RESET ROLE;
GRANT amw_sysfn TO amw_owner WITH INHERIT FALSE, SET TRUE;
SET LOCAL ROLE amw_sysfn;

-- p_probe: TRUE = the call was admitted as a HALF_OPEN probe by amw_breaker_admit; FALSE = it was
-- admitted while CLOSED, so a late result in HALF_OPEN changes nothing and frees no probe slot;
-- NULL (callers that do not use amw_breaker_admit) = treated as a probe, the L1a behaviour.
DROP FUNCTION amw_breaker_record(text, text, text, boolean, boolean, text, bigint, int, numeric,
  int, bigint, bigint, int);
CREATE FUNCTION amw_breaker_record(
  p_provider text, p_operation_class text, p_credential_scope text, p_succeeded boolean,
  p_counted boolean, p_error_code text, p_window_ms bigint, p_min_calls int,
  p_failure_ratio numeric, p_consecutive_failures int, p_open_ms bigint, p_open_ms_max bigint,
  p_half_open_successes_to_close int, p_probe boolean DEFAULT NULL)
  RETURNS TABLE (state text, open_until timestamptz)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
  AS $$
DECLARE
  b circuit_breakers;
  open_for bigint;
BEGIN
  INSERT INTO circuit_breakers (id, provider, operation_class, credential_scope, state,
      window_started_at)
  VALUES (amw_uuid7(), p_provider, p_operation_class, p_credential_scope, 'CLOSED', now())
  ON CONFLICT (provider, operation_class, credential_scope) DO NOTHING;
  SELECT * INTO b FROM circuit_breakers c
   WHERE c.provider = p_provider AND c.operation_class = p_operation_class
     AND c.credential_scope = p_credential_scope FOR UPDATE;

  IF b.state = 'OPEN' AND now() >= b.open_until THEN
    b.state := 'HALF_OPEN';
    b.half_open_in_flight := 0;
    b.half_open_probe_until := NULL;
    b.window_started_at := now();
    b.window_calls := 0;
    b.window_failures := 0;
  END IF;
  IF b.state = 'CLOSED' AND now() - b.window_started_at > make_interval(secs => p_window_ms / 1000.0) THEN
    b.window_started_at := now();
    b.window_calls := 0;
    b.window_failures := 0;
  END IF;

  IF b.state = 'HALF_OPEN' AND p_probe IS DISTINCT FROM false THEN
    b.half_open_in_flight := greatest(0, b.half_open_in_flight - 1);  -- this probe is finished
  END IF;

  IF b.state = 'OPEN' OR (b.state = 'HALF_OPEN' AND p_probe = false)
     OR (NOT p_succeeded AND NOT p_counted) THEN
    NULL;  -- rejected without I/O while OPEN; an uncounted failure is not a provider fault
  ELSIF p_succeeded THEN
    b.window_calls := b.window_calls + 1;
    b.consecutive_failures := 0;
    IF b.state = 'HALF_OPEN' AND b.window_calls >= p_half_open_successes_to_close THEN
      b.state := 'CLOSED';
      b.window_started_at := now();
      b.window_calls := 0;
      b.window_failures := 0;
      b.open_count := 0;
      b.opened_at := NULL;
      b.open_until := NULL;
      b.half_open_in_flight := 0;
      b.half_open_probe_until := NULL;
    END IF;
  ELSE
    b.window_calls := b.window_calls + 1;
    b.window_failures := b.window_failures + 1;
    b.consecutive_failures := b.consecutive_failures + 1;
    b.last_error_code := p_error_code;
    IF b.state = 'HALF_OPEN'
       OR b.consecutive_failures >= p_consecutive_failures
       OR (b.window_calls >= p_min_calls
           AND b.window_failures::numeric / b.window_calls >= p_failure_ratio) THEN
      open_for := least(p_open_ms * (2::bigint ^ least(b.open_count, 40))::bigint, p_open_ms_max);
      -- a re-open from HALF_OPEN keeps the first opened_at (07 section 4.3: L2 after open_ms_max
      -- in total)
      b.opened_at := CASE WHEN b.state = 'HALF_OPEN' THEN coalesce(b.opened_at, now()) ELSE now() END;
      b.state := 'OPEN';
      b.half_open_in_flight := 0;
      b.half_open_probe_until := NULL;
      b.window_started_at := now();
      b.window_calls := 0;
      b.window_failures := 0;
      b.open_until := now() + make_interval(secs => open_for / 1000.0);
      b.open_count := b.open_count + 1;
    END IF;
  END IF;

  UPDATE circuit_breakers c
     SET state = b.state, window_started_at = b.window_started_at, window_calls = b.window_calls,
         window_failures = b.window_failures, consecutive_failures = b.consecutive_failures,
         opened_at = b.opened_at, open_until = b.open_until, open_count = b.open_count,
         half_open_in_flight = b.half_open_in_flight,
         half_open_probe_until = b.half_open_probe_until,
         last_error_code = b.last_error_code, row_version = c.row_version + 1
   WHERE c.id = b.id;
  state := b.state;
  open_until := b.open_until;
  RETURN NEXT;
END
$$;


REVOKE ALL ON FUNCTION amw_breaker_record(text, text, text, boolean, boolean, text, bigint, int,
  numeric, int, bigint, bigint, int, boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION amw_breaker_record(text, text, text, boolean, boolean, text, bigint, int,
  numeric, int, bigint, bigint, int, boolean) TO amw_app, amw_publisher;

-- 07 section 4.3: OPEN rejects until open_until; the first check at or after it moves the row to
-- HALF_OPEN; HALF_OPEN admits at most p_half_open_max_probes probes at a time (counted in
-- half_open_in_flight under the row lock, so concurrent workers cannot over-admit). A CLOSED
-- breaker admits without changing anything; an unknown breaker is CLOSED (no row yet).
CREATE FUNCTION amw_breaker_admit(
  p_provider text, p_operation_class text, p_credential_scope text, p_half_open_max_probes int,
  p_probe_timeout_ms bigint)
  RETURNS TABLE (admitted boolean, state text, open_until timestamptz)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
  AS $$
DECLARE
  b circuit_breakers;
BEGIN
  IF p_half_open_max_probes < 1 OR p_probe_timeout_ms IS NULL OR p_probe_timeout_ms < 1 THEN
    RAISE EXCEPTION 'half_open_max_probes >= 1 and a probe timeout are required' USING ERRCODE = '22023';
  END IF;
  SELECT * INTO b FROM circuit_breakers c
   WHERE c.provider = p_provider AND c.operation_class = p_operation_class
     AND c.credential_scope = p_credential_scope FOR UPDATE;
  IF NOT FOUND OR b.state = 'CLOSED' THEN
    admitted := true; state := coalesce(b.state, 'CLOSED'); open_until := NULL;
    RETURN NEXT;
    RETURN;
  END IF;
  IF b.state = 'OPEN' THEN
    IF now() < b.open_until THEN
      admitted := false; state := b.state; open_until := b.open_until;
      RETURN NEXT;
      RETURN;
    END IF;
    b.state := 'HALF_OPEN';
    b.half_open_in_flight := 0;
    b.window_started_at := now();
    b.window_calls := 0;
    b.window_failures := 0;
  END IF;
  -- probes that never reported (crashed worker, refused after admission) are reclaimed once the
  -- lease of the last admitted probe has expired
  IF b.half_open_in_flight > 0 AND now() > b.half_open_probe_until THEN
    b.half_open_in_flight := 0;
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
         half_open_probe_until = b.half_open_probe_until,
         window_started_at = b.window_started_at, window_calls = b.window_calls,
         window_failures = b.window_failures, row_version = c.row_version + 1
   WHERE c.id = b.id;
  state := b.state; open_until := b.open_until;
  RETURN NEXT;
END
$$;
REVOKE ALL ON FUNCTION amw_breaker_admit(text, text, text, int, bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION amw_breaker_admit(text, text, text, int, bigint) TO amw_app, amw_publisher;

RESET ROLE;
GRANT amw_sysfn TO amw_owner WITH INHERIT FALSE, SET FALSE;
