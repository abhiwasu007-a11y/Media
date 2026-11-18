-- 0010 system functions (04 section 3.6): identifier-only, cross-tenant, SECURITY DEFINER, owned by
-- amw_sysfn (BYPASSRLS), fixed search_path; EXECUTE for the application role only. The caller
-- opens a tenant transaction per returned org_id before reading anything else.
-- Signature additions beyond the 04 table (recorded as contract needs): amw_queue_claim takes the
-- worker's queue names and the lease length; amw_queue_heartbeat renews a lease outside a tenant
-- transaction; amw_stuck_tasks takes the 07 section 6 dwell limits; amw_breaker_record takes the
-- 07 section 4.2 configuration. Thresholds are configuration, never literals here.
SET LOCAL ROLE amw_owner;

GRANT SELECT, UPDATE ON task_queue TO amw_sysfn;
GRANT SELECT ON tasks, approvals, dead_letter, workers TO amw_sysfn;
GRANT SELECT, INSERT, UPDATE ON circuit_breakers TO amw_sysfn;

-- T07 claim: fair share = among admissible rows of the best priority, the tenant
-- (fair_share_key) with the fewest rows currently CLAIMED goes first; then oldest scheduled_at.
-- Weights by plan are 3C (ADR-001). One row per loop so the in-flight count is current.
CREATE FUNCTION amw_queue_claim(
  p_worker_id uuid, p_capabilities text[], p_resource_classes text[], p_n int,
  p_queue_names text[], p_lease_ms bigint)
  RETURNS TABLE (queue_item_id uuid, org_id uuid, task_id uuid, envelope jsonb)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
  AS $$
DECLARE
  item uuid;
  dedicated uuid;
BEGIN
  IF p_n < 1 OR p_lease_ms < 1 THEN
    RAISE EXCEPTION 'claim needs n >= 1 and lease_ms >= 1' USING ERRCODE = '22023';
  END IF;
  SELECT w.dedicated_org_id INTO dedicated FROM workers w WHERE w.id = p_worker_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'worker is not registered' USING ERRCODE = 'AMW03';
  END IF;
  FOR i IN 1..p_n LOOP
    SELECT q.id INTO item FROM task_queue q
     WHERE q.status = 'READY' AND q.scheduled_at <= now()
       AND q.queue_name = ANY (p_queue_names)
       AND q.resource_class = ANY (p_resource_classes)
       AND q.required_capabilities <@ p_capabilities
       AND (dedicated IS NULL OR q.org_id = dedicated)
     ORDER BY q.priority,
              (SELECT count(*) FROM task_queue c
                WHERE c.fair_share_key = q.fair_share_key AND c.status = 'CLAIMED'),
              q.scheduled_at, q.id
     LIMIT 1
     FOR UPDATE SKIP LOCKED;
    EXIT WHEN item IS NULL;
    UPDATE task_queue q
       SET status = 'CLAIMED', claimed_by = p_worker_id, claimed_at = now(), heartbeat_at = now(),
           lease_expires_at = now() + make_interval(secs => p_lease_ms / 1000.0)
     WHERE q.id = item
    RETURNING q.id, q.org_id, q.task_id, q.envelope
      INTO queue_item_id, org_id, task_id, envelope;
    RETURN NEXT;
    item := NULL;
  END LOOP;
END
$$;

CREATE FUNCTION amw_queue_heartbeat(p_item_id uuid, p_worker_id uuid, p_lease_ms bigint)
  RETURNS timestamptz
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
  AS $$
DECLARE
  until timestamptz;
BEGIN
  UPDATE task_queue
     SET lease_expires_at = now() + make_interval(secs => p_lease_ms / 1000.0), heartbeat_at = now()
   WHERE id = p_item_id AND claimed_by = p_worker_id AND status = 'CLAIMED'
     AND lease_expires_at >= now()
  RETURNING lease_expires_at INTO until;
  RETURN until;  -- NULL: the lease is no longer held by this worker
END
$$;

CREATE FUNCTION amw_due_retries(p_limit int)
  RETURNS TABLE (org_id uuid, task_id uuid)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
  AS $$
  SELECT t.org_id, t.id FROM tasks t
   WHERE t.state = 'RETRY_WAIT' AND t.next_attempt_at <= now()
   ORDER BY t.next_attempt_at, t.id LIMIT p_limit
$$;

-- "May have cleared": an approval wait only once its approval reached a final state; every
-- other wait reason is returned for the scheduler to evaluate (window, quota day, budget, ...).
CREATE FUNCTION amw_due_resumes(p_limit int)
  RETURNS TABLE (org_id uuid, task_id uuid, wait_reason text)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
  AS $$
  SELECT t.org_id, t.id, t.wait_reason FROM tasks t
   WHERE t.state = 'CHECKPOINTED'
     AND (t.wait_reason <> 'AWAITING_APPROVAL' OR EXISTS (
          SELECT 1 FROM approvals a
           WHERE a.org_id = t.org_id AND a.id = t.approval_id AND a.state <> 'PENDING'))
   ORDER BY t.state_changed_at, t.id LIMIT p_limit
$$;

CREATE FUNCTION amw_expired_leases(p_limit int)
  RETURNS TABLE (org_id uuid, task_id uuid, queue_item_id uuid)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
  AS $$
  SELECT q.org_id, q.task_id, q.id FROM task_queue q
   WHERE q.status = 'CLAIMED' AND q.lease_expires_at < now()
   ORDER BY q.lease_expires_at, q.id LIMIT p_limit
$$;

-- 07 section 6 rows that need a transition: VALIDATING too long; FAILED without a DLQ row.
CREATE FUNCTION amw_stuck_tasks(p_limit int, p_validating_ms bigint, p_failed_no_dlq_ms bigint)
  RETURNS TABLE (org_id uuid, task_id uuid, state text)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
  AS $$
  SELECT t.org_id, t.id, t.state FROM tasks t
   WHERE (t.state = 'VALIDATING'
          AND t.state_changed_at < now() - make_interval(secs => p_validating_ms / 1000.0))
      OR (t.state = 'FAILED'
          AND t.state_changed_at < now() - make_interval(secs => p_failed_no_dlq_ms / 1000.0)
          AND NOT EXISTS (SELECT 1 FROM dead_letter d
                           WHERE d.org_id = t.org_id AND d.task_id = t.id))
   ORDER BY t.state_changed_at, t.id LIMIT p_limit
$$;

-- 07 section 4.3. A failure counts only when its code is marked "breaker counts" (the caller
-- passes p_counted from the 07 catalogue); an uncounted failure changes nothing. HALF_OPEN probes
-- are counted in window_calls (window_failures stays 0 there: any counted failure reopens).
CREATE FUNCTION amw_breaker_record(
  p_provider text, p_operation_class text, p_credential_scope text, p_succeeded boolean,
  p_counted boolean, p_error_code text, p_window_ms bigint, p_min_calls int,
  p_failure_ratio numeric, p_consecutive_failures int, p_open_ms bigint, p_open_ms_max bigint,
  p_half_open_successes_to_close int)
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
    b.window_started_at := now();
    b.window_calls := 0;
    b.window_failures := 0;
  END IF;
  IF b.state = 'CLOSED' AND now() - b.window_started_at > make_interval(secs => p_window_ms / 1000.0) THEN
    b.window_started_at := now();
    b.window_calls := 0;
    b.window_failures := 0;
  END IF;

  IF b.state = 'OPEN' OR (NOT p_succeeded AND NOT p_counted) THEN
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
      b.state := 'OPEN';
      b.opened_at := now();
      b.open_until := now() + make_interval(secs => open_for / 1000.0);
      b.open_count := b.open_count + 1;
    END IF;
  END IF;

  UPDATE circuit_breakers c
     SET state = b.state, window_started_at = b.window_started_at, window_calls = b.window_calls,
         window_failures = b.window_failures, consecutive_failures = b.consecutive_failures,
         opened_at = b.opened_at, open_until = b.open_until, open_count = b.open_count,
         last_error_code = b.last_error_code, row_version = c.row_version + 1
   WHERE c.id = b.id;
  state := b.state;
  open_until := b.open_until;
  RETURN NEXT;
END
$$;

REVOKE ALL ON FUNCTION amw_queue_claim(uuid, text[], text[], int, text[], bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION amw_queue_heartbeat(uuid, uuid, bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION amw_due_retries(int) FROM PUBLIC;
REVOKE ALL ON FUNCTION amw_due_resumes(int) FROM PUBLIC;
REVOKE ALL ON FUNCTION amw_expired_leases(int) FROM PUBLIC;
REVOKE ALL ON FUNCTION amw_stuck_tasks(int, bigint, bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION amw_breaker_record(text, text, text, boolean, boolean, text, bigint, int,
  numeric, int, bigint, bigint, int) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION amw_queue_claim(uuid, text[], text[], int, text[], bigint) TO amw_app;
GRANT EXECUTE ON FUNCTION amw_queue_heartbeat(uuid, uuid, bigint) TO amw_app;
GRANT EXECUTE ON FUNCTION amw_due_retries(int) TO amw_app;
GRANT EXECUTE ON FUNCTION amw_due_resumes(int) TO amw_app;
GRANT EXECUTE ON FUNCTION amw_expired_leases(int) TO amw_app;
GRANT EXECUTE ON FUNCTION amw_stuck_tasks(int, bigint, bigint) TO amw_app;
GRANT EXECUTE ON FUNCTION amw_breaker_record(text, text, text, boolean, boolean, text, bigint, int,
  numeric, int, bigint, bigint, int) TO amw_app, amw_publisher;

-- Ownership last (grants made by amw_owner carry over).
ALTER FUNCTION amw_queue_claim(uuid, text[], text[], int, text[], bigint) OWNER TO amw_sysfn;
ALTER FUNCTION amw_queue_heartbeat(uuid, uuid, bigint) OWNER TO amw_sysfn;
ALTER FUNCTION amw_due_retries(int) OWNER TO amw_sysfn;
ALTER FUNCTION amw_due_resumes(int) OWNER TO amw_sysfn;
ALTER FUNCTION amw_expired_leases(int) OWNER TO amw_sysfn;
ALTER FUNCTION amw_stuck_tasks(int, bigint, bigint) OWNER TO amw_sysfn;
ALTER FUNCTION amw_breaker_record(text, text, text, boolean, boolean, text, bigint, int, numeric,
  int, bigint, bigint, int) OWNER TO amw_sysfn;

-- ---------------------------------------------------------------------------------------------
-- Hardening after the last ALTER ... OWNER of lane L1a (code review PR #40, M1/M2).
-- Back to the bootstrap role (the runner's own role; SET LOCAL ROLE amw_owner ends here).
-- * amw_owner (and through it the login role amw_migrator) keeps ownership of the tables but may no
--   longer SET ROLE to amw_sysfn (BYPASSRLS) or amw_verifier_fn (owner of evidence_mac_keys):
--   04 section 3.1/3.6a, "never granted to a login role". A later migration that must hand a new
--   function to one of them re-grants SET for its own transaction and revokes it again at its end.
-- * No role may create temporary tables (they shadow real tables for SECURITY DEFINER code).
-- ---------------------------------------------------------------------------------------------
RESET ROLE;
GRANT amw_sysfn TO amw_owner WITH INHERIT FALSE, SET FALSE;
GRANT amw_verifier_fn TO amw_owner WITH INHERIT FALSE, SET FALSE;
DO $temp$
BEGIN
  EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database());
END
$temp$;
