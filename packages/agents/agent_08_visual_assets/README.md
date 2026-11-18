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

## Open items (not done, not faked)

- Stock (B), AI video (D) and AI still (E) acquisition through the adapters is not wired in the stage
  (recorded as `TIER_DISABLED`); their gates, prompt composer, disclosure flags and error mapper exist.
- LLM wrappers `QueryPlanner` / `CandidateRanker` (prompt loading, validation, repair, refusal mapping)
  are not built; the stage takes a `FootageSelector`. The `query_plan` / `candidate_rank` packs: the runner
  is exercised but their `expected` blocks are case summaries, not schema-valid outputs, so a recorded
  replay cannot pass the schema check; model-in-the-loop run listed.
- Devanagari: matplotlib has no complex-script shaping (test U-13 not met); a shaping library and font
  choice is needed before Marathi/Hindi text appears in charts or graphics.
- Music bed sourcing (3B), checkpoint persistence through `CheckpointStore`, budget/cost-ledger calls,
  idempotency-store use for paid effects, observability, near-duplicate calibration (3B).
- Persistence is behind Protocols with in-memory fakes only (`testing/memory.py`); no SQL yet.

## Status (owner vocabulary: Planned / In Development / Implemented / Tested)

| Feature | Status |
|---|---|
| Chart path (dataset, case match, lag guard, annotations, deterministic render) | Implemented, Tested |
| Code graphics (tier C text card, diagram, abstract template) | Implemented, Tested |
| Owner footage (tier A, selection through an injected `FootageSelector`) | Implemented, Tested (selector is a test fake) |
| Licence ledger rows (shots, overlays, fonts) | Implemented, Tested |
| Gate result and remedy stage | Implemented, Tested |
| Dataset intake guard and registrar | Implemented, Tested |
| `reveal_stills[]` with one IMAGE ledger row per still | Implemented, Tested |
| `agent_08.chart_facts` | Implemented, Tested |
| Fingerprints, reuse engine, tier-E guard, AI gates/composer/flags (units) | Implemented, Tested (not wired to adapters) |
| Stock (B), AI video (D), AI still (E) acquisition | Planned |
| `QueryPlanner` / `CandidateRanker` LLM wrappers | Planned |
| Checkpoint persistence, budget/cost-ledger calls | Planned |
| SQL persistence (only in-memory fakes exist) | Planned |
| Music bed (3B) | Planned |
| Devanagari shaping (U-13) | Open: matplotlib has no complex-script shaping; needs a shaping library and font decision |

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
