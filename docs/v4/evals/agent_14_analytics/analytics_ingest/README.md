# Eval set — `agent_14.analytics_ingest` (no LLM; deterministic golden dataset)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 14 Analytics |
| MVP | **3C** · Tier 0 |
| Prompt | **none**: this task type makes no model call (blueprint §6). The golden dataset is deterministic (27 §6.1, evals/README §2). |
| Depends on | agents/agent_14_analytics.md §6, §10 (`ReportNormalizer.process_report`), §18; 04_DATABASE_ARCHITECTURE.md §5.22; RESEARCH_LOG YT-14; 07 §2 |
| Directive sections covered | §3.1 row 14 (ingestion); §3.3 Learning loop data; rule 4 (never fabricate); rule 9 (tenant isolation) |
| Files | `cases.jsonl` (28 cases), `rubric.md` (states that no judge applies) |

## 1. Scope
Tests the pure normalisation and validation function `process_report(context, report) -> result` that sits between the YouTube access port and the append-only table. No network, no database: the case supplies the already-fetched report in a neutral form, the known publications of the channel, and the previously processed reports. Dates are **relative day offsets** from a fixed anchor day (the harness resolves offset 0 to a fixed Pacific-time date); the case file contains no calendar dates. The time zone of dates is the Pacific day boundary stated on the official Reporting and Analytics API pages (fetched 2026-11-18; the blueprint §12 records the entry proposed for RESEARCH_LOG). The configured rejection ratio and point counts in `context.config` are fixtures and not proposals.

## 2. Case coverage
| Category | Cases | What they prove |
|---|---|---|
| POSITIVE | POS-01…POS-06 | reach rows mapped to publications; channel-level rows; 100-point retention curve; anonymised value kept as returned; CTR stored unconverted; backfill appended with supersession |
| HARD_NEGATIVE | HN-01…HN-10 | duplicate report; identical backfill; empty report; duplicate row; unmapped video; invalid values; incomplete curve; empty curve; unknown video for retention |
| EDGE | EDGE-01…EDGE-12 | future and out-of-range dates; all-invalid report; foreign channel (isolation breach); org mismatch; forbidden monetary metric; call cap; 403 / 429 / 503; expired report; corrupt curve |

## 3. `expected` object
`status` (`SUCCEEDED` / `FAILED`), `error_code` (07 §2 code or `null`), `rows_written`, `flags` (sorted set), `publication_ids` (one per written row, `null` for channel-level), `supersedes_report_ids`, `security_event` (boolean), optional `api_calls_made`.

## 4. Deterministic assertions (all cases)
| ID | Assertion |
|---|---|
| I1 | result equals `expected` on all fields (flags compared as sets) |
| I2 | no written row has a metric value that is not present in the report (no fabrication, no interpolation, no unit conversion) |
| I3 | no written row has `org_id` or `channel_id` other than the task's |
| I4 | re-running the same case on its own output state writes 0 rows (idempotence) |
| I5 | `security_event = true` exactly for tenant or channel mismatch cases |
| I6 | a failed case writes no row at all (all or nothing per report) |
| I7 | the error object of a failure validates against `amw.error` 1.0.0 and carries the stated code |

## 5. Judge
None. Every case is decided by deterministic assertions (blueprint §26).

## 6. Pass thresholds (config `evals.agent_14.analytics_ingest.*`)
| Threshold | Value |
|---|---|
| All cases | **28 / 28** — mandatory (deterministic code; no tolerance) |
| I2 and I3 on any case | **0 failures** — mandatory |
| Mutation check: flipping the channel id check or the dedupe check makes at least one case fail | required in CI (27 §8) |

## 7. Recording fields
`run_id`, `case_id`, `passed`, `assertions` (I1–I7), `started_at`, code version. No token, cost or judge fields (no model).

## 8. Open points
- The unit of `video_thumbnail_impressions_ctr` is not confirmed in RESEARCH_LOG (POS-05 stores the number as returned).
- Reach report latency and the Reporting API quota are REQUIRES REVIEW (blueprint §12); no case depends on them.
