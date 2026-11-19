# agent_08_visual_assets (Agent 08, Visual Assets)

Implements blueprint `docs/v4/agents/agent_08_visual_assets.md` (task `agent_08.asset_sourcing`,
stage `s08_assets`), ticket 3A-09. Private method content never enters this package: charts are drawn
from owner-registered datasets and owner chart cases, nothing is invented here.

## Plotting / rasteriser choice (27 section 3 tool decision)

| Item | Choice | Licence | Pinned version |
|---|---|---|---|
| Chart and graphic rasteriser | matplotlib, Agg backend, drawn on `Figure` objects (no pyplot state) | matplotlib licence (PSF-based, permissive) | 3.11.2 |
| Image decode / resize (fingerprints) | Pillow | HPND | 13.0.0 |
| Numerics (transitive) | NumPy | BSD-3-Clause | 2.5.5 |
| Font | DejaVu Sans bundled in the matplotlib wheel, unless the brand kit gives a font file | Bitstream Vera / DejaVu (free) | with matplotlib |

No network at runtime (fully local libraries). Determinism: fixed DPI and canvas, no timestamps or
seeds, PNG metadata stripped; the same spec renders to the same SHA-256 (also across processes, tested).
Test images are generated at test time from synthetic OHLC data, never from private market data.

## What exists

- Hierarchy cascade A to E (`cascade/tier_cascade.py`) with recorded skip reasons; a chart never falls to
  stock or AI. Stage (`stage.py`) wires charts, graphics (tier C) and the owner library (tier A, ranking
  through an injected `FootageSelector`).
- Chart path: dataset loader (hash verified), chart cases (owner-curated), lag guard (FIN-R9, 30-day
  config), annotation validator (FIN-R13), deterministic renderer, reveal sequence (`reveal_stills[]`,
  one asset and one `IMAGE` ledger row per still), `agent_08.chart_facts` documents.
- Licence ledger rows per shot, per overlay interval (`TEMPLATE`), per brand font (`FONT`);
  `LedgerRowBuilder` also builds the 3B `MUSIC_BED` row; `CoverageVerifier`; `LicenceGuard`.
- `SourceIntakeGuard` + `AssetRegistrar` (human, operator tool, `data_pack`, read-only).
- Fingerprints (SHA-256 + 64-bit dHash), `ReuseEngine` (tenant-scoped), `TierShareGuard`, `AiBudgetGate`,
  `AiPromptComposer`, `DisclosureFlags`, `SafetyFloor`, `TieBreaker`, `GateRouter` (gate result and
  `remedy_stage_id`), `ChangedShotSelector`, `CheckpointManager.resume`, `AdapterErrorMapper`, `TenantGuard`.
- Pydantic models equal to the blueprint JSON Schemas (validated against the schemas in the document).

## data_pack chart scenes (owner decision: the real skeleton run includes them)

`DataPackChartBuilder.build(request, as_of=..., dataset_asset_id=...)` draws one chart scene from the
course `data_pack` through the `DataPackReader` port. The pack stays outside git: the runtime config
gives `charts.data_pack_root` and `charts.data_pack_files` (`<INSTRUMENT>@<1D|1W>` to a file name in
the root); no pack file name is written in this repository and the reader only opens configured names,
read-only. Every bar of the window must satisfy `as_of - bar_end >= lag_days` (30, IN-02; weekly bars
end at date + 6); a newer bar refuses the request (`PERMANENT.INPUT_INVALID`, `details.reason =
DATA_WITHIN_LAG`) unless the request sets `clip_to_lag`. The arithmetic equals Agent 06
`price_age.classify` (parity test); Agent 16 re-checks at publish with `recheck_lag_at`. Outputs: reveal
stills, the `agent_08.chart_facts` 1.0.0 document (schema-validated in tests), a provenance record
(lag proof, dataset SHA-256, pack manifest SHA-256; proposed in CCR-256) and the asset attributes.
Tests use synthetic bars only. Divergence markers use the proposed annotation kind `CONNECT_BARS`
(CCR-255).

## Open items (not done, not faked)

- Stock (B), AI video (D) and AI still (E) acquisition through the adapters is not wired in the stage
  (recorded as `TIER_DISABLED`); their gates, prompt composer, disclosure flags and error mapper exist.
- LLM wrappers `QueryPlanner` / `CandidateRanker` (prompt loading, validation, repair, refusal mapping)
  are not built; the stage takes a `FootageSelector`. The `query_plan` / `candidate_rank` packs: the runner
  is exercised but their `expected` blocks are case summaries, not schema-valid outputs, so a recorded
  replay cannot pass the schema check; model-in-the-loop run listed.
- Devanagari: matplotlib 3.11.2 shapes text through libraqm (measured: the pre-base vowel sign and
  conjuncts render correctly with Noto Sans Devanagari); the data_pack chart builder checks libraqm and
  glyph coverage. The brand-font default (Mukta vs Noto, Q-O6) is the owner's decision; the stage's
  older chart path and the graphics templates still draw Latin allowlist text only.
- data_pack chart builder: not yet called by `AssetSourcingStage` (the stage still takes owner chart
  cases with bar-index windows over registered datasets); wiring waits for CCR-258/259.
- Music bed sourcing (3B), checkpoint persistence through `CheckpointStore`, budget/cost-ledger calls,
  idempotency-store use for paid effects, observability, near-duplicate calibration (3B).
- Persistence is behind Protocols with in-memory fakes only (`testing/memory.py`); no SQL yet.

## Status (owner vocabulary: Planned / In Development / Implemented / Tested)

"Called by the stage" means the code path runs inside `AssetSourcingStage.run` in a test.

| Feature | Status |
|---|---|
| Chart path (dataset, case match, lag guard, annotations, deterministic render, intake class enforced on read) | Implemented, Tested (stage) |
| Code graphics (tier C text card, diagram, abstract template) | Implemented, Tested (stage) |
| Owner footage (tier A) with `SafetyFloor` + `TieBreaker`; selector is injected | Implemented, Tested with a scripted `FootageSelector` fake (no real model) |
| Licence ledger rows (shots, overlays, fonts); one covering row per asset | Implemented, Tested (stage) |
| Gate result and remedy stage | Implemented, Tested (stage) |
| Dataset intake guard and registrar | Implemented, Tested |
| `reveal_stills[]` (one IMAGE asset per step; the last still is the chart asset and shares its single row) | Implemented, Tested (stage) |
| `agent_08.chart_facts` (end date = end of the last bar's period) | Implemented, Tested (stage) |
| Validation rows of 8.3 (measured, or SKIPPED non-blocking when not measurable) | Implemented, Tested (stage) |
| Revision carry-over (`ChangedShotSelector`; rows reused, not rewritten) | Implemented, Tested (stage) |
| Reuse through `ReuseEngine` (exact, tenant, status, expiry, channel) | Implemented, Tested (stage; near-duplicate path unit only) |
| Brand font read from tenant storage; the rendering font is the ledgered font asset | Implemented, Tested (stage) |
| `AiBudgetGate`, `AiPromptComposer`, `DisclosureFlags` | Implemented, unit only (golden pack); NOT called by the stage |
| `AdapterErrorMapper`, `CheckpointManager.resume` | Implemented, unit only (golden pack); NOT called by the stage |
| Stock (B), AI video (D), AI still (E) acquisition | Planned |
| `QueryPlanner` / `CandidateRanker` LLM wrappers | Planned |
| Checkpoint persistence, budget/cost-ledger calls | Planned |
| SQL persistence (only in-memory fakes exist) | Planned |
| Music bed (3B) | Planned |
| Devanagari shaping (U-13) | Implemented, Tested for data_pack charts (libraqm in matplotlib 3.11.2; glyph coverage and shaping asserted); font default is owner question Q-O6 |
| data_pack chart scenes (`charts/datapack.py`, `charts/datapack_builder.py`): reader port (file-backed at `charts.data_pack_root`, unset = CONFIG_INVALID; in-memory double), per-bar SEBI lag (refuse, clip only on request), RSI (Wilder), 1920x1080 render with bilingual source label and as-of range, contract chart facts, provenance (lag proof, pack manifest hash), CHART asset registration (CODE_GENERATED self-grant) | Implemented, Tested (unit, synthetic bars); NOT called by the stage (CCR-255 to CCR-259) |

Measured numbers (package-local config, `coveragerc` in this directory; the root config does not
measure agent packages, listed under core_needs): see the final report of the PR; command:
`uv run pytest tests/agents/agent_08_visual_assets --cov --cov-config=packages/agents/agent_08_visual_assets/coveragerc --cov-fail-under=80`.

## Package-local formats, pending a contract decision

No contract names are claimed for these.

- Dataset: UTF-8 CSV, header `date,open,high,low,close` (extra columns ignored); ISO dates strictly
  ascending; decimal prices only (no empty cell, NaN or infinity); high/low consistent with open/close.
- Chart case: JSON object `{case_id, data_kind (REAL_HISTORICAL|SCHEMATIC), instrument|null, timeframe
  (1D|1W|1M), dataset_asset_id|null, window{first_bar_index,last_bar_index}|null, indicators[]
  (SMA_n, EMA_n, RSI_n), pattern_concept_ids[], outcome (WORKED|FAILED|BOTH|NOT_APPLICABLE),
  annotations[] {kind, bar|from_bar|to_bar, text, price, extend_right}, method_content,
  release_approval_id|null, template_id, schematic_points[]|null}`. Bar numbers are dataset bar indexes.

## Eval packs query_plan and candidate_rank: plumbing only

Replayable with a pass: **0 of 29** (query_plan) and **0 of 30** (candidate_rank). Their `expected` blocks
are case summaries that do not validate against the prompt output schema, so a recorded replay fails
the schema assertion. The pass rate is **not asserted**. `test_eval_packs.py` checks only that the runner
evaluates every case and fails if the replayable count changes from these numbers.
