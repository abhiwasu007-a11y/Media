-- 0058 tasks.stage_id (04 section 5.3; CCR-214 (a), CCR-211; ticket PASS6-A2): the production-type
-- stage (24 section 2 stage_id, ^[a-z0-9_]{2,32}$) of a task materialised from a graph, so two
-- stages of one task type (s06_verify, s06_chart) can be told apart and a resumed runner can
-- rebuild its stage map. Additive: a nullable column (NULL only for a task created outside a
-- graph) and a partial unique key (a revision iteration of a stage exists once among live tasks;
-- a CANCELLED task is replaced at the same iteration, 24 section 3.3 rule 1). `tasks` already has
-- org_id, ENABLE + FORCE row level security and its grants (0002); a new column inherits them.
SET LOCAL ROLE amw_owner;

ALTER TABLE tasks ADD COLUMN stage_id text;
ALTER TABLE tasks ADD CONSTRAINT tasks_stage_id_format
  CHECK (stage_id IS NULL OR stage_id ~ '^[a-z0-9_]{2,32}$');
CREATE UNIQUE INDEX tasks_stage_iteration_live
  ON tasks (org_id, job_id, stage_id, iteration)
  WHERE stage_id IS NOT NULL AND state <> 'CANCELLED';
