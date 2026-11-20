# ADR-016 — VPS render profile as dashboard settings

| Field | Value |
|---|---|
| Status | **PROPOSED** (documentation only; discuss-then-build, owner rule A6). Software: **Not built.** |
| Date | 2026-11-20 |
| Owner decisions | D15 (audited limits, fixed for any VPS render), D16 (the limits are settings the administrator can change; no hard-coding) |
| Directive / docs | ADR-012 (render placement), `00_REPO_AND_SERVER_AUDIT.md` Part C-2, `06_NIGHT_SCHEDULING.md`, `16_COMMAND_CENTER.md` §7, `04_DATABASE_ARCHITECTURE.md` §5.1 (`org_controls`, `platform_controls`), `08_SECURITY.md` §5, `27_ENGINEERING_STANDARDS.md` §7.3 rule 1 |
| Contracts | none edited. Storage of the settings needs a contract decision: **CCR-298 (PROPOSED)** |
| Research | none needed (no external fact). The audited numbers are the owner's (D15, source = owner-run audit) |

## 1. Context
D15 recorded fixed limits for any VPS render (window, systemd slice limits, priority, concurrency, pause thresholds). The owner now says (D16): if the VPS is upsized, the matching setting must be in the dashboard so it can be raised or lowered when a rendering issue appears; and whatever the administrator can change must not be hard-coded, so the owner never has to change code for it.

State today (checked in the docs): **the dashboard does not exist.** S8 (Command Center) is 3C; 3A has an operator tool only (`16_COMMAND_CENTER.md`, `3A_SLICE_SPEC.md` §247 row "Command Center dashboard (S8) ... 3C"). Nothing is built for this ADR. VPS rendering happens only after the Seneca sample passes; the render happens in the development environment now.

## 2. How a dashboard-editable setting is modelled today
| Aspect | Today (source) |
|---|---|
| Per-tenant controls | table `org_controls` (`key`, `value jsonb`, `updated_by`), `UNIQUE (org_id, key)`, keys fixed by 04 §5.1: `agent_enabled.<agent_id>`, `production_schedule`, `daily_production_limit`, `publishing_enabled`, `emergency_stop`, `ip_allowlist` |
| Platform controls | table `platform_controls` (GLOBAL), keys `platform_emergency_stop`, `admission_paused`; written only by `PLATFORM_OWNER` through `amw_sysfn`; audited in the platform owner org's chain (04 §5.1; 16 §7.4) |
| Validation | each value is validated per key by `amw_core.config` against the value table (CCR-140); an invalid value is `PERMANENT.CONFIG_INVALID` and the control acts in its closed state (04 §5.1) |
| Who may write | permission key `control.write`, held by `PLATFORM_OWNER` (platform controls), `ORG_OWNER`, `ORG_ADMIN` (`08_SECURITY.md` §5.2). Roles: `PLATFORM_OWNER`, `ORG_OWNER`, `ORG_ADMIN`, `PRODUCER`, `REVIEWER_APPROVER`, `FINANCE`, `VIEWER`, `CLIENT_GUEST` (GLOSSARY §6.44) |
| Audit | every change is audited as `control.<key>.changed`; the reason for `emergency_stop` is carried in the audit `details` (04 §5.1; 16 §7.2) |
| Config layers (code side) | `amw_core.config` (pydantic-settings) is the only way to read configuration; models, providers, limits, thresholds and windows are config, never literals (27 §7.3 rule 1); platform window resolution `channels.production_window` -> `production_schedule` -> config `night.window.default` (CCR-139); the platform window 00:00-07:00 IST cannot be widened by a tenant on the shared VPS (16 §7.2) |
| Hard ceilings in packaged data | `runtime_config.json`: the packaged owner caps are hard ceilings; env values and an explicit override file may only LOWER them (`runtime/README.md`, D10 era) |

## 3. Two different rules, kept apart
- **Rule H (existing, spending caps):** a ceiling in packaged data is a hard ceiling; an override may only LOWER it. This protects money.
- **Rule R (this ADR, render capacity):** render limits must be RAISABLE by the administrator, because the VPS may be upsized. A packaged ceiling would defeat that. The bound is instead (a) the host CAPACITY setting, which the administrator updates when the VPS is upsized, minus (b) a reserve for the other apps on the host, plus (c) fail-closed sanity limits on each value. Rule R does not touch rule H; the spending caps stay hard ceilings.

## 4. PROPOSAL (not decided)
**The VPS render profile = settings, with the D15 audited values as seeded DEFAULTS in config data.**
| Setting | Type, unit | Default (D15) | Read by |
|---|---|---|---|
| `render.window.start`, `render.window.end` | local time of day, IST | 00:00, 07:00 | runner guard |
| `render.slice.memory_high` | bytes (shown as GB) | 1.5 GB | slice unit (deployment) and guard |
| `render.slice.memory_max` | bytes | 2 GB | slice unit and guard |
| `render.slice.cpu_quota_percent` | integer percent | 100 | slice unit and guard |
| `render.slice.cpu_weight_class`, `render.slice.io_weight_class` | enum `LOW` / `NORMAL` / `HIGH`; the numeric systemd weights per class are config data: **REQUIRES REVIEW (Phase 1): the numbers per class; D15 states only "low"** | `LOW` | slice unit |
| `render.process.nice`, `render.process.ionice_class` | integer; enum | 19; idle | runner |
| `render.concurrency` | integer, min 1 | 1 | runner guard |
| `render.abort.mem_available_min` | bytes | 1.5 GB | runner guard sampler |
| `render.abort.psi_cpu_avg10_max` | number (PSI percent) | 40 | runner guard sampler |
| `render.abort.psi_window_seconds` | integer seconds | 120 | runner guard sampler |
| `render.on_breach` | enum `PAUSE` / `ABORT` | **REQUIRES REVIEW (owner)** (D15: not chosen) | runner guard |
| `host.capacity.vcpu`, `host.capacity.ram_bytes` | integer; bytes | vCPU 2 (owner-run audit); RAM: **REQUIRES REVIEW (Phase 1): total RAM is not stated in the audit summary** (only `mem_available` minima) | validation |
| `host.reserve.vcpu`, `host.reserve.ram_bytes` | the share kept for the other apps on the host | **REQUIRES REVIEW (owner / measurement): no value is proposed here, none is invented** | validation |

**Rules**
1. **Capacity rule:** `render.slice.cpu_quota_percent` (as vCPUs) <= `host.capacity.vcpu` - `host.reserve.vcpu`; `render.slice.memory_max` <= `host.capacity.ram_bytes` - `host.reserve.ram_bytes`; `memory_high` <= `memory_max`; the pause/abort memory threshold must lie below the audited free-memory floor logic of the host (checked against capacity, not against a literal). A value above the limit is refused. Until the reserve is set the settings fail closed (no VPS render admitted).
2. **Who may change:** the administrator, through the dashboard settings (D16 message 2), with `control.write`. Which role is "the administrator" for a host-level setting is **REQUIRES REVIEW (owner)**: the docs define `PLATFORM_OWNER` (platform controls, only in the platform owner org), `ORG_OWNER` and `ORG_ADMIN` (org controls). The profile describes one shared host, so it is platform scope (a tenant cannot widen the shared-VPS window, 16 §7.2); candidates: `PLATFORM_OWNER` only, or `PLATFORM_OWNER` plus `ORG_ADMIN` of the platform owner org. No new role is invented. In 3A the only human is the owner (08 §5.2 rule 4).
3. **Audit:** every change writes an audit entry with the key, old value, new value, actor and a mandatory reason (event name to be registered under the `control.<key>.changed` pattern, 08 §9.2).
4. **Typed and validated:** each key has a type, unit and min/max sanity limits; an invalid or missing value is `PERMANENT.CONFIG_INVALID` and the guard refuses admission (fail closed).
5. **Takes effect for the NEXT render only,** never mid-render (the renderer reads the settings once at start and stores the snapshot, with its hash, in the render record).
6. **Raise versus lower:** lowering is allowed with audit only. Whether RAISING a value above the audited defaults needs an additional explicit owner confirmation (owner approval evidence, R14 style) while a change within the defaults does not: **REQUIRES REVIEW (owner)**. This ADR does not decide it.
7. **Guard:** the runner guard VPS-RENDER-1 reads every limit from the settings snapshot (no constants) and enforces them; the slice unit file is generated from the same settings by the operator (a deployment step, outside the application; the app never edits systemd).
8. **No hard-coding (D16):** none of the values above appears as a literal in code; the defaults live in config data (packaged data, like `runtime_config.json`) and the stored settings override them.

**What is built now: nothing.** No code, migration, config or VPS change; the dashboard page cannot exist before the dashboard.

## 5. Open questions for the owner (provisional defaults in brackets, per rule A9)
1. Which role is "the administrator" for the render profile (PLATFORM_OWNER only, or also ORG_ADMIN of the platform owner org)? [provisional: PLATFORM_OWNER only]
2. Does raising a limit above the audited defaults need an extra owner confirmation? [provisional: yes, owner confirmation for any raise; lowering needs audit only]
3. Pause or abort on breach? (D15 left open) [provisional: pause at the next safe point, abort if the breach lasts]. This is a provisional default for planning only, not a decision.
4. The reserve for the other apps on the host (vCPU, RAM): to be set from a measurement. No default.
5. Total RAM of the host (needed for the capacity block).

## 6. Tickets (backlog, none built)
| ID | Content | Depends on |
|---|---|---|
| VPS-RENDER-1 | runner guard (D15 item 4), now reading all limits from the render-profile settings snapshot instead of constants | VPS-RENDER-2 |
| VPS-RENDER-2 | settings schema (typed keys, units, ranges, capacity rule), validation that fails closed, audit entry (old, new, reason), owner confirmation when raising (if the owner decides yes), `amw_core.config` keys and seeded defaults in config data | CCR-298 decision, owner answers 1-5 |
| VPS-RENDER-3 | dashboard page for the render profile (administrator edit, history, capacity block) | the dashboard (S8, 3C) existing |
| CFG-AUDIT | scan of the code for operational values not read from config; Appendix A is the first read-only scan; migrate (b) items to config keys in a later PR | none |

## Appendix A. CFG-AUDIT, first read-only scan (2026-11-20)
Method: `grep` over `packages/*/src` and `packages/agents/*/src` for module constants and literal defaults of limits, windows, thresholds, timeouts, retries, caps and targets (tests excluded). **Not exhaustive** (about 1,100 upper-case assignments exist; many are protocol values). No code was changed. "Who may edit" is the proposal for the administrator-editable class and is subject to owner question 1.

**Where the existing rule is not followed (honest statement).** 27 §7.3 rule 1 and the lane rule say limits, thresholds and windows are config, never literals. The scan finds operational values as literals or as package-local defaults in several places (list (b)). Some are marked as "design defaults / ESTIMATE" in their own comments, and some are a deliberate one-sided guard (the value can be tightened but not loosened, `agent_07/config.py`). The hard-coded ceiling pattern (`TASK_ATTEMPT_CEILING`) is the existing "ceiling in code" the owner may not want for values that the administrator should change.

### (a) Legitimate constants (protocol, contract or unit values; keep in code)
| File | Value | Why it stays |
|---|---|---|
| `amw_core/.../contracts/error.py`, `validation.py` | `MAX_VIOLATIONS` 200, `MAX_VIOLATION_MESSAGE` 500 | payload-shape bound of the error contract |
| `amw_core/.../audit/chain.py` | `MAX_DETAILS_BYTES` 64 KiB | audit record format bound |
| `amw_core/.../interfaces/storage.py` | `CHUNK_BYTES` 1 MiB | I/O unit |
| `amw_core/.../owner_evidence_*.py` | `MIN_KEY_BYTES` 32, `ECHO_QUOTE_PREFIX` 40, `MAX_ECHO_QUOTE` 600 | MAC and echo-format security bounds |
| `amw_adapters/.../real/authorisation.py` | `SEAL_BYTES` 32 | seal format |
| `amw_core/.../config/settings.py` | `MAX_MINOR_EXPONENT` 6; `amw_runtime/.../config.py` `_MICROS_EXPONENT` 6 | money unit format |
| `agent_07/.../pcm.py` | `FULL_SCALE`, `MAX_S16`, `MIN_S16`, `SILENT_DBFS` | PCM arithmetic |
| `agent_07/.../config.py` | `SPEC_SAMPLE_RATE_HZ` 48000, `SPEC_TARGET_LUFS` -14, `SPEC_TRUE_PEAK_MAX_DBTP` -1, `SPEC_MIN_BITRATE_BPS` 384000 | delivery spec floor of 18 §5 (tighten-only; the config may tighten, not loosen) |
| `agent_08/.../fingerprint.py`, `graphics.py`, `charts/*.py` | `ALGO_VERSION`, `TEMPLATE_VERSION` | version markers |
| `agent_10/.../probe.py` | `SILENCE_FLOOR_DBTP` -144; `qc/evidence.py` `MAX_FRAMES` 999 | measurement unit and format bounds |
| `amw_delivery/.../models.py` | `TOTAL_POINTS` 100, `MAX_MACHINE_POINTS` 79 | scoring contract (18 §11) |
| `agent_10/.../guard.py` | `_DAY` 1440, `_WEEK` | time arithmetic |
| `threshold=0` in QC and check results | zero-tolerance checks | gate semantics |

### (b) Operational values an administrator may need to change (candidates; move to config keys later)
| File | Value | Current location | Proposed config key | Who may edit |
|---|---|---|---|---|
| `amw_adapters/.../real/http.py` | retry policy base 2 s, multiplier 2, cap 300 s, jitter 0.5, 5 attempts (comment: ESTIMATE; the registry passes the configured policy) | module constant `DEFAULT_BACKOFF` | `retry.temporary.*` (exists in the registry; the constant is a fallback) | administrator (REQUIRES REVIEW: role) |
| `amw_core/.../retries/policy.py` | `TASK_ATTEMPT_CEILING` 10 | module constant | `retry.attempt_ceiling` | administrator, within the ceiling decision of the owner |
| `amw_orchestrator/.../registry.py` | `MAX_REVISION_LOOPS_CEILING` 10 | module constant | `orchestrator.max_revision_loops_ceiling` | administrator |
| `amw_runtime/.../preflight.py` | `SCOPE_TTL` 60 s | module constant | `preflight.scope_ttl_seconds` | administrator |
| `amw_core/.../config/settings.py` | breaker `window_ms` default 60,000 (default in the model; real value comes from config) | field default | already a config field; seeded default belongs in packaged data | administrator |
| `agent_06/.../library/quotes.py` | `min_quote_chars` 20 (provisional, CCR-291); `guard_min_words` has no default | dataclass default | `agent_06.quotes.min_quote_chars` | administrator |
| `agent_06/.../library/copyright.py` | `PD_YEARS_AFTER_DEATH` 60, `EARLIEST_DEATH_YEAR` -3500 | module constant (legal rule and CCR-291 provisional) | `library.pd_years_after_death` (legal value: counsel; not administrator-editable without review), `library.earliest_death_year` | owner (legal) |
| `agent_06/.../reconcile.py` | `MAX_EVIDENCE_ITEMS` 6 | module constant | `agent_06.max_evidence_items` | administrator |
| `agent_04/.../guards/copy_guard.py` | `MIN_SHARED_WORDS` 3 | module constant | `agent_04.copy_guard.min_shared_words` | administrator |
| `agent_04/.../library/search.py` | `MAX_QUERY_CHARS` 120 | module constant | `agent_04.library.max_query_chars` | administrator |
| `agent_04/.../steps/research_pack.py` | `LOCK_MS` 600,000 | module constant | `agent_04.research_pack.lock_ms` | administrator |
| `agent_05/.../checks/echo.py` | `PROMPT_MIN_WORDS` 6, `INSTRUCTION_MIN_WORDS` 4 | module constant | `agent_05.echo.*` | administrator |
| `agent_05/.../pre/brief_mapper.py` | `SUMMARY_MAX` 600 | module constant | `agent_05.brief.summary_max_chars` | administrator |
| `agent_11/.../guards.py` | `_MAX_COPIED_RUN` 5 | module constant | `agent_11.guards.max_copied_run` | administrator |
| `agent_16/.../inputs/extractors.py` | `REQUIRED_THUMBNAIL_VARIANTS` 3, `FRAMES_SCHEMA_CAP` 60 | module constant | `agent_16.thumbnail_variants_required`, `agent_16.frames_cap` | administrator (the variant count may be a directive value: REQUIRES REVIEW) |
| `agent_08/.../reuse/fingerprint.py` | `MAX_PIXELS` 64,000,000 | module constant | `agent_08.fingerprint.max_pixels` | administrator |
| `agent_08/.../charts/datapack.py` | `MAX_ROW_BYTES` 256 | module constant | `agent_08.datapack.max_row_bytes` | administrator |
| `agent_09/.../config.py` | cadence 3000 ms, change gap 5000 ms, hook window 30,000 ms, slot and repair limits | `base_for_tests()` only (test base; production values come from config) | already config; confirm no production path uses `base_for_tests` | administrator |
| `agent_10/.../qc/selftest.py`, `qc/stage.py` | selftest bitrate target 8,000,000 bps, GOP 15, B-frames 2, tolerance 1000 ms | literals in the self-test and stage | encode targets belong to ADR-014 / `agent_10.render.*` config; confirm the stage reads config, not these literals | administrator (REQUIRES REVIEW) |
| `amw_delivery/.../vertical.py` | subprocess `timeout_s` 60 | literal | `delivery.ffmpeg_timeout_seconds` | administrator |
| `agent_10/.../ffmpeg.py` | process wait `timeout` 10 s | literal | `agent_10.ffmpeg.terminate_grace_seconds` | administrator |
| `amw_adapters/.../real/memory.py` | `max_entries` 10,000 | parameter default | `adapters.memory.max_entries` | administrator |
| `amw_runtime` lag | 30-day price-data lag | packaged data (`_packaged_lag_days`) with a caller override | already data; a legal value (IN-02): editable only by the owner after counsel review | owner |
| render window, slice limits, thresholds | D15 values | NOT in code yet (docs only) | `render.*`, `host.*` of section 4 | administrator (open question 1) |

Counts are by file, not exhaustive; a full CFG-AUDIT must also review function-parameter defaults and dictionary literals, and compare each item with the config registry (`amw_core.config.registry`) to see which already have a config key. That comparison was not done in this scan.
